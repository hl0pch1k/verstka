// The remarks workspace of the result screen's aside (the «Замечания» switch is on): the remarks of the slide on screen,
// numbered like the pins on the slide, and «Исправить слайд» — the agent fixes them on this slide only, following the
// person's wishes. The footer morphs between the form, the agent's live steps and the outcome.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { AlertCircle, AlertTriangle, ArrowRight, CheckCircle2, RotateCcw, WandSparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "../../api";
import { smoothScroll, stagger, useFlipList, usePresence, MOTION } from "../../lib/motion";
import { cn, plural } from "../../lib/utils";
import type { AgentEvent, Severity, VariantEdit } from "../../types";
import { Button } from "../ui/Button";
import { Collapse } from "../ui/Collapse";
import { CountUp } from "../ui/CountUp";
import { Progress } from "../ui/Progress";
import { Spinner } from "../ui/Spinner";
import { RemarkPin } from "../VariantsSlidePreview";
import type { StageRemark } from "../VariantsHelpers";
import type { SlideFix } from "./useSlideFix";
import "./remarks.css";

// ---------------------------------------------------------------------------------------------------------------------
// check titles (GET /api/checks, once per page)

let titles: Record<string, string> = {};
let titlesLoad: Promise<Record<string, string>> | null = null;

/** The checks' titles by id; empty until the list has arrived (the rows then fall back to the UI's own words). */
export function useCheckTitles(): Record<string, string> {
  const [t, setT] = useState(titles);
  useEffect(() => {
    if (!titlesLoad) {
      titlesLoad = api.checks().then(
        (list) => (titles = Object.fromEntries(list.map((c) => [c.id, c.title]))),
        () => {
          titlesLoad = null; // try again next time
          return titles;
        },
      );
    }
    let alive = true;
    void titlesLoad.then((x) => alive && setT(x));
    return () => {
      alive = false;
    };
  }, []);
  return t;
}

// ---------------------------------------------------------------------------------------------------------------------

const SEV_META: Record<Severity, { text: string; cls: string }> = {
  error: { text: "Ошибка", cls: "text-red-600" },
  warn: { text: "Предупреждение", cls: "text-amber-700" },
  info: { text: "Замечание модели", cls: "text-zinc-500" },
};
/** Which edges of a scroll box hide content: a soft fade there says the list goes on. */
function useScrollEdges(ref: RefObject<HTMLElement>, deps: unknown[]): { top: boolean; bottom: boolean } {
  const [edges, setEdges] = useState({ top: false, bottom: false });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const run = () => {
      const top = el.scrollTop > 1;
      const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
      setEdges((e) => (e.top === top && e.bottom === bottom ? e : { top, bottom }));
    };
    run();
    const ro = new ResizeObserver(run);
    ro.observe(el);
    Array.from(el.children).forEach((c) => ro.observe(c));
    el.addEventListener("scroll", run, { passive: true });
    return () => {
      ro.disconnect();
      el.removeEventListener("scroll", run);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return edges;
}
const EDGE_FADE = {
  both: "[mask-image:linear-gradient(to_bottom,transparent,#000_16px,#000_calc(100%-24px),transparent)]",
  top: "[mask-image:linear-gradient(to_bottom,transparent,#000_16px)]",
  bottom: "[mask-image:linear-gradient(to_bottom,#000_calc(100%-24px),transparent)]",
};

const remarksWord = (n: number) => plural(n, "замечание", "замечания", "замечаний").replace(/^\d+\s/, "");
const elapsedText = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export interface RemarksPanelProps {
  slide: number;
  strategy: string;
  /** The live remarks of the slide on screen (numbered as on the slide). */
  remarks: StageRemark[];
  /** Remarks about the whole deck (slide 0): one line at the end of the list. */
  deckRemarks: number;
  /** The next slide with remarks (wrapping around), null when no other slide has any. */
  nextSlide: number | null;
  activeIds: string[];
  onActive(ids: string[] | null): void;
  /** A frame or pin was clicked on the slide: its row scrolls into view, takes the focus and flashes (`k` replays). */
  picked: { id: string; k: number } | null;
  /** A row was clicked: its frame pings on the slide. */
  onPing(id: string): void;
  onGoto(n: number): void;
  /** «Показать» of the banner: the run's variant and slide. */
  onShowRun(): void;
  onOpenQuality(): void;
  fix: SlideFix;
  edits: VariantEdit[];
  canWish: boolean;
  /** Some job of the app runs: the fix waits for it. */
  busy: boolean;
  wishes: string;
  onWishes(v: string): void;
  /** How the panel comes in: rises in the aside (over the cards that clear before it), or rides in with the aside
   *  column that slides out from under the open helper (no entrance of its own). */
  enter: "rise" | "none";
  leaving: boolean;
  /** How it leaves: fades out over the cards that come back, or stays opaque while the column slides back under the
   *  helper. */
  exit?: "fade" | "tuck";
}

/** The phase a person sees: an undo whose restored slide is not on screen yet still reads «Возвращаю как было». */
const shownPhase = (run: SlideFix["run"]) => (run && run.phase === "undone" && !run.revealed ? "undoing" : run?.phase ?? null);

export function RemarksPanel(props: RemarksPanelProps) {
  const { slide, strategy, remarks, fix, leaving } = props;
  // how it came in is decided once: a helper toggle later must not swap the class (that replays the entrance)
  const [enter] = useState(props.enter);
  const run = fix.run;
  const here = !!run && run.strategy === strategy && run.slide === slide;
  const phase = here ? shownPhase(run) : null;
  const result = here ? run.result : null;

  // «done»: the fixed rows turn into checks (0), collapse (1200), then the list is the reloaded slide's (1500). Played
  // once per run: a panel mounted again later (the switch off and on) or a return to the slide shows the settled list
  const [stage, setStage] = useState<{ at: number; step: "checks" | "collapse" | "live" } | null>(null);
  const skip = useRef<number | null>(run?.celebrated ? run.at : null);
  if (run?.celebrated && !here) skip.current = run.at;
  const choreo = here && phase === "done" && !!result?.applied && result.fixed.length > 0 && skip.current !== run.at;
  useEffect(() => {
    if (!choreo || !run) return;
    if (stage?.at === run.at) return;
    setStage({ at: run.at, step: "checks" });
    const t1 = window.setTimeout(() => setStage((s) => (s && s.at === run.at ? { ...s, step: "collapse" } : s)), 1200);
    // the collapse glides most of its way in the first 100ms: the live list follows it closely
    const t2 = window.setTimeout(() => setStage((s) => (s && s.at === run.at ? { ...s, step: "live" } : s)), 1420);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choreo, run?.at]);
  const staged = choreo && stage?.at === run?.at ? stage.step : "live";
  // the live list only once the reloaded deck is in (a slow reload holds the collapsed rows)
  const step = staged === "live" && choreo && !run?.synced ? "collapse" : staged;
  const played = choreo && step === "live" && !run?.celebrated;
  const celebrate = fix.celebrate;
  useEffect(() => {
    if (played) celebrate();
  }, [played, celebrate]);
  const fixedIds = useMemo(() => new Set(result?.fixed ?? []), [result]);
  const newIds = useMemo(() => new Set((result?.remaining ?? []).filter((r) => r.new).map((r) => r.id)), [result]);
  /** The rows on screen: the snapshot the fix started from while it works and settles, else the live remarks. */
  const rows = step !== "live" || (here && (phase === "submitting" || phase === "running")) ? run!.requested : remarks;
  const justSettled = choreo && step === "live";
  // after the collapse the list is the re-audited slide's: a remark that stayed keeps its place without a blink (the
  // server may renumber its id), its pin pops only when its number changed; a new one rises in
  const stayed = useMemo(() => {
    const m = new Map<string, number>();
    if (!justSettled || !run) return m;
    const left = run.requested.filter((q) => !fixedIds.has(q.issue.id));
    for (const r of remarks) {
      const k = left.findIndex((q) => q.issue.check_id === r.issue.check_id && q.text === r.text);
      if (k >= 0 && !newIds.has(r.issue.id)) m.set(r.issue.id, left.splice(k, 1)[0].n);
    }
    return m;
  }, [justSettled, run, remarks, fixedIds, newIds]);

  const working = phase === "submitting" || phase === "running";
  const requestedIds = useMemo(() => new Set(here ? run.requested.map((r) => r.issue.id) : []), [here, run]);

  // a frame picked on the slide: its row scrolls into view, takes the focus and flashes
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => {
    if (!props.picked) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-remark="${CSS.escape(props.picked.id)}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "nearest", behavior: smoothScroll() });
    el.focus({ preventScroll: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.picked?.k]);

  const empty = rows.length === 0;
  const listKey = `${strategy}/${slide}`;
  // every remark of the slide was fixed: «замечаний нет» starts to come in while the last rows fold away (100ms into
  // their collapse), so the list never stalls on an empty card. Not with the deck's line under the list (the state
  // fills the list's height, that line would sit under it)
  const emptySoon = !empty && step === "collapse" && !!result && result.remaining.length === 0 && props.deckRemarks === 0 && rows.every((r) => fixedIds.has(r.issue.id));
  // remarks come back on the same slide («Вернуть как было»): the state leaves over the rows that rise in (90 ms), it
  // is never cut. Another slide or variant swaps the list at once, as the rows do
  const emptyShown = empty || emptySoon;
  const emptyP = usePresence(emptyShown, MOTION.fast);
  const emptyKey = useRef(listKey);
  if (emptyShown) emptyKey.current = listKey;
  const emptyLeaving = emptyP.leaving && emptyKey.current === listKey;
  const scrollRef = useRef<HTMLDivElement>(null);
  const edges = useScrollEdges(scrollRef, [listKey, empty]);
  const count = remarks.length;

  // the footer: form ↔ the agent's steps ↔ the outcome
  const showProgress = phase === "running";
  // the steps keep what they showed while they fold away (the person turned to another slide, or the job ended): an
  // exit never flips them to «done» while the agent may still be at work
  const progressNow: FixProgressProps = { events: fix.events, progress: fix.progress, message: fix.message, startedAt: run?.startedAt ?? Date.now(), running: phase === "running", wishes: here ? run.wishes : "" };
  const progressShown = useRef(progressNow);
  if (showProgress) progressShown.current = progressNow;
  const showResult = phase === "done" || phase === "failed" || phase === "undoing" || phase === "undone";
  const showForm = count > 0 && phase !== "running" && phase !== "undoing" && phase !== "undone";
  const footer = showProgress || showResult || showForm;

  return (
    <section
      aria-label="Замечания"
      className={cn(
        // relative: it paints over the aside cards that fade out under it (the mode turned on)
        "relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-card",
        // the swap with the cards is a fade-through: out in 90 ms, in 25 ms later (ResultScreen)
        leaving
          ? cn("pointer-events-none rm-fade-out", props.exit !== "tuck" && "animate-fade-out [animation-duration:90ms] [animation-timing-function:var(--ease-out)]")
          : cn(enter === "rise" && "animate-rise [animation-delay:25ms]", "rm-fade"),
      )}
    >
      <header className="flex h-14 shrink-0 items-center gap-2 px-4">
        <h2 className="text-title3 font-semibold text-zinc-900">Слайд {slide}</h2>
        {count > 0 && (
          <span key={listKey} className="animate-fade text-footnote text-zinc-500">
            <CountUp value={count} ms={400} /> {remarksWord(count)}
          </span>
        )}
      </header>

      <Banner {...props} />

      <div ref={scrollRef} className={cn("scroll-thin relative min-h-0 flex-1 overflow-y-auto px-2 pb-2", edges.top && edges.bottom ? EDGE_FADE.both : edges.top ? EDGE_FADE.top : edges.bottom ? EDGE_FADE.bottom : null)}>
        {!empty && (
          // a new slide's list fades in as a whole; rows that come back under the leaving «замечаний нет» only rise
          <RemarkList key={listKey} listRef={listRef} slide={slide} fade={!emptyLeaving}>
            {rows.map((r, i) => {
              const isFixed = step !== "live" && fixedIds.has(r.issue.id);
              const collapsing = step === "collapse" && isFixed;
              return (
                <li key={r.issue.id}>
                  {/* a remark that appeared with the fix grows in, so the rows that stayed glide aside for it */}
                  <Collapse open={!collapsing} appear={justSettled && !stayed.has(r.issue.id)}>
                    <RemarkRow
                      remark={r}
                      index={i}
                      fixed={isFixed}
                      dim={working || phase === "undoing"}
                      breathing={working && requestedIds.has(r.issue.id)}
                      active={props.activeIds.includes(r.issue.id)}
                      flashK={props.picked?.id === r.issue.id ? props.picked.k : null}
                      enter={justSettled ? (stayed.has(r.issue.id) ? "none" : newIds.has(r.issue.id) ? "rise" : "fade") : "stagger"}
                      renumbered={justSettled && stayed.has(r.issue.id) && stayed.get(r.issue.id) !== r.n}
                      onActive={props.onActive}
                      onPing={working ? undefined : props.onPing}
                    />
                  </Collapse>
                </li>
              );
            })}
          </RemarkList>
        )}
        {/* its own slot and key: the state that came in over the folding rows stays the same node once they are gone */}
        {(emptyShown || emptyLeaving) && <EmptyRemarks key={`e-${listKey}`} nextSlide={props.nextSlide} onGoto={props.onGoto} early={!empty} leaving={!emptyShown} />}
        {props.deckRemarks > 0 && (
          <div className="mx-2 mt-2 flex items-center gap-2 rounded-xl bg-zinc-50 px-3 py-2">
            <span className="min-w-0 flex-1 text-footnote text-zinc-700">Ещё {plural(props.deckRemarks, "замечание", "замечания", "замечаний")} ко всей презентации</span>
            <Button variant="ghost" size="sm" onClick={props.onOpenQuality}>Качество</Button>
          </div>
        )}
      </div>

      <Collapse open={footer}>
        <div className="border-t border-zinc-100 p-4">
          <Collapse open={showProgress} appear>
            <FixProgress {...(showProgress ? progressNow : progressShown.current)} />
          </Collapse>
          {/* the gap to the form folds with the strip: it is inside the clipped box */}
          <Collapse open={showResult} appear>
            <div className={showForm ? "pb-3" : undefined}>{here && showResult && <ResultStrip {...props} />}</div>
          </Collapse>
          <Collapse open={showForm}>
            <FixForm {...props} submitting={phase === "submitting"} />
          </Collapse>
        </div>
      </Collapse>
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------------------------

function RemarkRow({ remark, index, fixed, dim, breathing, active, flashK, enter, renumbered = false, onActive, onPing }: {
  remark: StageRemark;
  index: number;
  fixed: boolean;
  dim: boolean;
  breathing: boolean;
  active: boolean;
  flashK: number | null;
  enter: "stagger" | "rise" | "fade" | "none";
  /** It stayed after a fix and got another number: the pin pops once. */
  renumbered?: boolean;
  onActive(ids: string[] | null): void;
  onPing?(id: string): void;
}) {
  const { issue, n, title, text, whole } = remark;
  const meta = SEV_META[issue.severity];
  const was = usePresence(!fixed, MOTION.fast);
  return (
    <button
      type="button"
      data-remark={issue.id}
      aria-disabled={onPing ? undefined : true}
      onMouseEnter={() => onActive([issue.id])}
      onMouseLeave={() => onActive(null)}
      onFocus={() => onActive([issue.id])}
      onBlur={() => onActive(null)}
      onClick={() => onPing?.(issue.id)}
      className={cn(
        "relative isolate flex w-full gap-3 rounded-xl px-2 py-2 text-left transition-[background-color,opacity] duration-150 focus-visible:outline-offset-[-2px]",
        onPing ? "cursor-pointer hover:bg-zinc-50" : "cursor-default",
        active && "bg-zinc-50",
        dim && "opacity-60",
        enter === "stagger" ? "animate-fade-in" : enter === "rise" ? "animate-rise" : enter === "fade" ? "animate-fade" : null,
      )}
      style={enter === "stagger" ? stagger(index, 30, 5) : undefined}
    >
      {flashK !== null && <span key={flashK} aria-hidden className="remark-flash pointer-events-none absolute inset-0 -z-10 rounded-xl" />}
      <span className={cn("relative pt-0.5", breathing && "remark-breathe", renumbered && "animate-pop")}>
        {/* fixed: the numbered pin pops out and the emerald check pops in just after it, on top */}
        {fixed && was.mounted && <RemarkPin key="was" n={n} sev={issue.severity} className="absolute left-0 top-0.5 animate-pop-out" />}
        {fixed ? (
          <RemarkPin key="ok" n={n} sev={issue.severity} fixed active={active} className="relative animate-pop [animation-delay:120ms]" />
        ) : (
          <RemarkPin key="n" n={n} sev={issue.severity} active={active} />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn("block text-footnote font-semibold transition-colors duration-150", fixed ? "text-zinc-500" : "text-zinc-900")}>{title}</span>
        <span className={cn("mt-0.5 line-clamp-3 text-footnote transition-colors duration-150", fixed ? "text-zinc-500" : "text-zinc-700")} title={text}>
          {text}
        </span>
        <span className={cn("mt-1 block text-caption", fixed ? "text-emerald-600" : meta.cls)}>
          {fixed ? "Исправлено" : meta.text}
          {whole && !fixed && <span className="text-zinc-500"> · Весь слайд</span>}
        </span>
      </span>
    </button>
  );
}

/** The rows of one slide. `fade` is read at mount: a class added later would replay the fade from 0. */
function RemarkList({ listRef, slide, fade, children }: { listRef: RefObject<HTMLUListElement>; slide: number; fade: boolean; children: ReactNode }) {
  const [fadeIn] = useState(fade);
  return (
    <ul ref={listRef} aria-label={`Замечания слайда ${slide}`} className={cn("space-y-0.5", fadeIn && "animate-fade")}>
      {children}
    </ul>
  );
}

/** `early`: it comes in over the last fixed rows while they fold, in the very box the list gives it once they are gone
 *  (absolute inset-x-2 top-0 bottom-2 = the scroll box's content box: nothing moves when the rows unmount), 30 ms after
 *  they start to fold — more than half in when their height is gone. Its timing is fixed at mount, so taking its place
 *  in the list later never skips its fade. `leaving`: remarks came back on this slide — it takes that same absolute box
 *  and clears in 90 ms over the rows that rise in. */
function EmptyRemarks({ nextSlide, onGoto, early = false, leaving = false }: { nextSlide: number | null; onGoto(n: number): void; early?: boolean; leaving?: boolean }) {
  const [delay] = useState(early ? 30 : 0);
  return (
    <div
      className={cn(
        "flex min-h-[160px] flex-col items-center justify-center gap-3 px-4 py-6 text-center",
        early || leaving ? "pointer-events-none absolute inset-x-2 bottom-2 top-0" : "h-full",
        // reduced motion: the global 1 ms override makes both instant, as the rows are
        leaving ? "animate-fade-out [animation-duration:90ms] [animation-timing-function:var(--ease-out)]" : "animate-fade",
      )}
      // an arrival over a leaving row: front-loaded, so the two cross-fade instead of meeting at half
      style={delay && !leaving ? { animationDelay: `${delay}ms`, animationTimingFunction: "var(--ease-out)" } : undefined}
    >
      <span className="flex h-12 w-12 animate-pop items-center justify-center rounded-xl bg-emerald-50" style={delay ? { animationDelay: `${delay}ms` } : undefined}>
        <CheckCircle2 className="h-6 w-6 text-emerald-500" aria-hidden />
      </span>
      <p className="text-body font-semibold text-zinc-900 [text-wrap:balance]">{nextSlide ? "На этом слайде замечаний нет" : "Замечаний нет"}</p>
      {nextSlide && (
        <Button variant="secondary" size="md" iconRight={ArrowRight} onClick={() => onGoto(nextSlide)}>
          К слайду {nextSlide}
        </Button>
      )}
    </div>
  );
}

/** The run is on another slide or variant: one line on top of the list, with the way back to it. */
function Banner({ fix, strategy, slide, onShowRun }: RemarksPanelProps) {
  const run = fix.run;
  const elsewhere = !!run && (run.strategy !== strategy || run.slide !== slide) && (run.phase === "submitting" || run.phase === "running" || run.phase === "done" || run.phase === "failed");
  const presence = usePresence(elsewhere, MOTION.fast);
  const last = useRef(run);
  if (elsewhere) last.current = run;
  const r = last.current;
  if (!presence.mounted || !r) return null;
  const n = r.slide;
  const ok = r.phase === "done" && !!r.result?.applied;
  const bad = r.phase === "failed" || (r.phase === "done" && !r.result?.applied);
  const tone = ok ? "bg-emerald-50" : bad ? "bg-amber-50" : "bg-accent-50";
  const text = ok ? `Слайд ${n} исправлен` : bad ? `Не получилось исправить слайд ${n}` : `Исправляю слайд ${n}`;
  return (
    <div className={cn("mx-4 mb-2 flex shrink-0 items-center gap-2 rounded-xl py-1 pl-3 pr-1 text-footnote text-zinc-900", tone, presence.leaving ? "animate-drop-out" : "animate-drop-in")} role="status">
      {ok ? (
        <CheckCircle2 className="h-4 w-4 shrink-0 animate-pop text-emerald-500" aria-hidden />
      ) : bad ? (
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" aria-hidden />
      ) : (
        <Spinner size={16} className="shrink-0 text-accent" label="Исправляю" />
      )}
      <span key={text} className="min-w-0 flex-1 animate-fade py-1.5 [text-wrap:balance]">{text}</span>
      <Button variant="ghost" size="sm" className="shrink-0" onClick={onShowRun}>Показать</Button>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// footer blocks

function FixForm({ slide, remarks, strategy, fix, canWish, busy, wishes, onWishes, submitting }: RemarksPanelProps & { submitting: boolean }) {
  const ta = useRef<HTMLTextAreaElement>(null);
  // two lines hold the example; the field grows with the text up to three
  useLayoutEffect(() => {
    const el = ta.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(88, Math.max(64, el.scrollHeight))}px`;
  }, [wishes]);
  const blocked = busy && !submitting;
  const submit = async () => {
    if (blocked || submitting || remarks.length === 0) return;
    await fix.start(strategy, slide, remarks, canWish ? wishes : "");
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };
  return (
    <div className="space-y-3">
      {canWish && (
        <textarea
          ref={ta}
          rows={1}
          maxLength={500}
          value={wishes}
          onChange={(e) => onWishes(e.target.value)}
          onKeyDown={onKey}
          aria-label="Пожелания"
          placeholder="Пожелания, например: покажи этапами"
          className="scroll-thin block h-16 max-h-[88px] w-full resize-none rounded-xl bg-zinc-100 px-3 py-2 text-footnote leading-6 text-zinc-900 outline-none transition-[background-color,box-shadow] duration-150 placeholder:text-zinc-500 focus:bg-white focus:shadow-selected"
        />
      )}
      {/* a disabled button shows no tooltip: the wrapper carries it while another job runs */}
      <span className="block" title={blocked ? "Агент занят — дождитесь конца" : undefined}>
        <Button variant="primary" size="md" block icon={WandSparkles} loading={submitting} disabled={blocked} onClick={() => void submit()}>
          Исправить слайд
        </Button>
      </span>
    </div>
  );
}

const STEPS: { key: string; label: string; steps: string[] }[] = [
  { key: "critic", label: "Критик", steps: ["critic"] },
  { key: "designer", label: "Дизайнер", steps: ["designer", "revise"] },
  { key: "compile", label: "Вёрстка", steps: ["compile"] },
  { key: "check", label: "Проверка", steps: ["check"] },
];
const stripStep = (m: string) => {
  const t = m.replace(/^\s*(Критик|Дизайнер|Вёрстка|Верстка|Проверка|Правка)\s*:\s*/i, "").trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
};

const PREVIEW_RX = /готовлю\s+превью/i;

interface FixProgressProps { events: AgentEvent[]; progress: number; message: string; startedAt: number; running: boolean; wishes: string }

/** The agent's four steps on this slide, live: done ones get a check, the active one a pulsing dot with its latest line.
 *  After the check the previews still render (≈ 20 s): the four steps are done then and one more active line says so,
 *  so the timeline never reads as finished (or stuck) while the job still works. */
function FixProgress({ events, progress, message, startedAt, running, wishes }: FixProgressProps) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [running]);
  const preparing = running && (progress >= 0.85 || PREVIEW_RX.test(message) || events.some((e) => (e.step ?? "").toLowerCase() === "check" && PREVIEW_RX.test(e.message)));
  // the check keeps its verdict line; «…— готовлю превью слайда» is told by the preview line below
  const latest = STEPS.map((s) => {
    const own = [...events].reverse().filter((e) => s.steps.includes((e.step ?? "").toLowerCase()));
    return own.find((e) => !PREVIEW_RX.test(e.message)) ?? own[0] ?? null;
  });
  const last = latest.reduce((acc, e, i) => (e ? i : acc), -1);
  const activeIdx = preparing ? STEPS.length : Math.max(0, last);
  // a new line pushes the steps below it down: they glide there instead of jumping
  const listRef = useRef<HTMLOListElement>(null);
  useFlipList(listRef, "[data-flip]", `${events.length}/${activeIdx}/${running}`);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Spinner size={16} className="text-accent" label="Агент исправляет слайд" />
        <span className="text-footnote font-semibold text-zinc-900">Агент исправляет слайд</span>
        <span className="ml-auto text-footnote tabular-nums text-zinc-500">{elapsedText(now - startedAt)}</span>
      </div>
      <Progress size="xs" value={progress} indeterminate={progress <= 0.001} />
      <ol ref={listRef} className="space-y-3">
        {STEPS.map((s, i) => {
          const status = !running || i < activeIdx ? "done" : i === activeIdx ? "active" : "pending";
          const ev = latest[i];
          const msg = ev ? stripStep(ev.message) : "";
          return (
            <li key={s.key} data-flip={s.key} className="relative grid grid-cols-[20px_1fr] gap-x-2">
              {(i < STEPS.length - 1 || preparing) && <span aria-hidden className={cn("absolute left-[9.5px] top-6 h-[calc(100%-12px)] w-px transition-colors duration-300", status === "done" ? "bg-emerald-200" : "bg-zinc-200")} />}
              <span className="flex h-5 items-center justify-center">
                {status === "done" ? (
                  <CheckCircle2 key="done" className="h-4 w-4 animate-pop text-emerald-500" aria-hidden />
                ) : status === "active" ? (
                  <span key="active" className="remark-ping-loop h-2 w-2 rounded-full bg-accent" style={{ ["--ping" as string]: "rgba(0,119,255,0.35)" }} aria-hidden />
                ) : (
                  <span key="pending" className="h-2 w-2 rounded-full ring-2 ring-inset ring-zinc-300" aria-hidden />
                )}
              </span>
              <span className="min-w-0">
                <span className={cn("block text-footnote font-semibold transition-colors duration-150", status === "pending" ? "text-zinc-500" : "text-zinc-900")}>{s.label}</span>
                {msg && status !== "pending" && (
                  // a finished step keeps one line (the whole of it in the tooltip): the timeline stays compact
                  <span key={msg} className={cn("mt-0.5 animate-fade-in text-caption text-zinc-700", status === "active" ? "line-clamp-2" : "line-clamp-1")} title={msg} aria-live={status === "active" ? "polite" : undefined}>
                    {msg}
                  </span>
                )}
              </span>
            </li>
          );
        })}
        {preparing && (
          // grows in (its gap inside the fold), so the footer does not jump
          <li data-flip="preview" className="!mt-0">
            <Collapse open appear>
              <span className="grid grid-cols-[20px_1fr] gap-x-2 pt-3">
                <span className="flex h-5 items-center justify-center">
                  <span className="remark-ping-loop h-2 w-2 rounded-full bg-accent" style={{ ["--ping" as string]: "rgba(0,119,255,0.35)" }} aria-hidden />
                </span>
                <span className="text-footnote font-semibold text-zinc-900" aria-live="polite">Готовлю превью слайда</span>
              </span>
            </Collapse>
          </li>
        )}
      </ol>
      {wishes && <p className="line-clamp-2 text-caption text-zinc-500" title={wishes}>«{wishes}»</p>}
    </div>
  );
}

function ResultStrip({ fix, edits, strategy }: RemarksPanelProps) {
  const run = fix.run!;
  const res = run.result;
  const phase = shownPhase(run);
  const last = edits.length ? edits[edits.length - 1] : undefined;
  // while undoing, the button stays (busy) even once the reloaded log already ends with the undo
  const canUndo = !!res?.applied && run.strategy === strategy && (phase === "undoing" || (phase === "done" && last?.kind === "fix" && last.slides[0] === run.slide));

  let tone: "ok" | "warn" | "bad" | "neutral";
  let Icon: LucideIcon;
  let line: string;
  const captions: { text: string; cls: string }[] = [];
  if (phase === "undone") {
    tone = "neutral";
    Icon = RotateCcw;
    line = "Вернул как было";
  } else if (phase === "failed" || !res) {
    tone = "bad";
    Icon = AlertCircle;
    line = "Не получилось исправить";
    if (run.error) captions.push({ text: run.error, cls: "text-zinc-700" });
  } else if (!res.applied) {
    tone = "warn";
    Icon = AlertTriangle;
    line = "Не получилось исправить";
    captions.push({ text: (res.why ?? "Замечания остались — попробуйте добавить пожелание").replace(/\.\s*$/, ""), cls: "text-zinc-700" });
  } else {
    const m = res.requested.length || run.requested.length;
    const f = Math.min(res.fixed.length, m);
    const all = m > 0 && f >= m;
    tone = all ? "ok" : "warn";
    Icon = all ? CheckCircle2 : AlertTriangle;
    const before = res.score_before === null ? null : Math.round(res.score_before);
    const after = res.new_score === null ? null : Math.round(res.new_score);
    const score = before !== null && after !== null && before !== after ? ` · ${before} → ${after}` : "";
    line = (all && m === 1 ? "Замечание исправлено" : `Исправлено ${f} из ${m}`) + score;
    const fresh = res.remaining.filter((r) => r.new).length;
    if (fresh > 0) captions.push({ text: `Появилось ${plural(fresh, "новое замечание", "новых замечания", "новых замечаний")}`, cls: "text-zinc-700" });
  }
  if (res && phase !== "undone" && phase !== "failed") {
    if (res.other_slides.length > 0) captions.push({ text: `Изменились и другие слайды: ${res.other_slides.join(", ")}`, cls: "text-amber-700" });
    if (res.notes[0]) captions.push({ text: res.notes[0].replace(/\.\s*$/, ""), cls: "text-zinc-700" });
  }
  const TINT = { ok: "bg-emerald-50", warn: "bg-amber-50", bad: "bg-red-50", neutral: "bg-zinc-100" }[tone];
  const ICON = { ok: "text-emerald-500", warn: "text-amber-500", bad: "text-red-500", neutral: "text-zinc-500" }[tone];
  return (
    <div
      key={`${phase}-${phase === "undoing" ? "" : run.at}`}
      role={tone === "bad" ? "alert" : "status"}
      aria-live={tone === "bad" ? undefined : "polite"}
      className={cn("rounded-xl px-3 py-3 transition-colors duration-300", TINT, tone === "bad" && "animate-shake")}
    >
      <div className="flex items-start gap-2">
        <Icon className={cn("mt-0.5 h-4 w-4 shrink-0 animate-pop", ICON)} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-footnote font-semibold text-zinc-900">{line}</p>
          {captions.map((c) => (
            <p key={c.text} className={cn("mt-0.5 text-caption", c.cls)}>
              {c.text}
            </p>
          ))}
        </div>
      </div>
      {canUndo && (
        <Button variant="white" size="sm" icon={RotateCcw} className="mt-3" loading={phase === "undoing"} onClick={() => void fix.undo()}>
          Вернуть как было
        </Button>
      )}
    </div>
  );
}
