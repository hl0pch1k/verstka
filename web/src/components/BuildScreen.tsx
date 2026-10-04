// While a presentation is being built. The page says what the agent is doing now in its title (the phase in plain
// words: «Читаю ваш текст» → «Продумываю слайды» → «Сверяю план с текстом» → …), the time against the five-minute
// promise and one bar of progress, then two columns: the storyboard on the left — a card per slide that
// fills in with the sketch of its form as the designer thinks it through, gets the critic's note and the revision's
// answer, a check once laid out, then the real preview — and on the right how the agent thinks, step by step. The
// variants' switch above the storyboard chooses whose slides are shown. A narrow page (the helper docked) narrows both.
// Entered through a View Transition (create → build, deck → build), the transition's page rise is the only entrance;
// the title and the agent's column take their view-transition names only once it has ended (from the create page,
// which has nothing to morph from, the whole page rises as one piece). When the build ends, the title cross-fades into
// the deck's and the agent's column turns into the deck's aside.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Check } from "lucide-react";
import { api } from "../api";
import { buildTimeline, laterPhase, phaseOfStep, type PhaseKey } from "../lib/agent";
import type { VariantProgress } from "../lib/jobText";
import { variantHint } from "../lib/plain";
import { clock, railSlides, sketchInk, STAGE_TITLE } from "../lib/stage";
import { cn, fmtWhen, plural } from "../lib/utils";
import { useApp, type ActiveJob } from "../store";
import { AgentLog } from "./build/AgentLog";
import { StoryBoard } from "./build/StoryBoard";
import { Segmented, type SegmentedItem } from "./ui/Segmented";

const PROMISE_MS = 5 * 60 * 1000; // the five-minute promise
/** How long a phase's title stays before the next one may replace it: a fast build (no model: a dozen seconds) still
 *  reads as a sequence of steps. */
const TITLE_DWELL_MS = 1100;

/** A variant's state: determinate once the pipeline reports its layout, indeterminate while the agent works on it. */
interface VariantState extends VariantProgress { indeterminate?: boolean }

// what the agent is doing with a variant before the pipeline reports its layout (then: «в очереди на вёрстку»,
// «вёрстка 4 из 6», «проверка качества», «готово»)
const AGENT_STATUS: Partial<Record<PhaseKey, string>> = {
  writer: "пишу текст",
  analyst: "читаю текст",
  architect: "строю сюжет",
  designer: "продумываю слайды",
  critic: "проверяет критик",
  revise: "правка",
};

/** A View Transition is running (the page is being captured or animated). */
const inViewTransition = () => {
  try {
    return document.documentElement.matches(":active-view-transition");
  } catch {
    return false; // a browser without the pseudo-class has no View Transitions either
  }
};

/** The one-off entrances of what the page shows at mount (a title, a check, a sketch drawing itself). */
const ENTRANCES = new Set(["fade", "fade-in", "rise", "pop", "fill-in", "grow-x", "grow-y", "draw"]);

/** How the build page came in. `quiet`: it mounted inside a View Transition, which is its entrance. `title` / `names`:
 *  the title block and the agent's column carry their view-transition names, which the hand-off to the deck needs.
 *  Entering through a transition they get them once it has ended, so the page rises as one piece, with one exception:
 *  a deck's title (read at the first render, while the page being left is still in the DOM) cross-fades in place into
 *  the build's. */
function useEntrance(): { quiet: boolean; title: boolean; names: boolean } {
  const [quiet] = useState(inViewTransition);
  const [fromTitle] = useState(() => quiet && !!document.querySelector(".vt-title"));
  const [settled, setSettled] = useState(!quiet);
  useEffect(() => {
    if (settled) return;
    let raf = 0;
    const tick = () => (inViewTransition() ? (raf = requestAnimationFrame(tick)) : setSettled(true));
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [settled]);
  return { quiet, title: settled || fromTitle, names: settled };
}

const slideUrl = (gid: string, variant: string, n: number) => `/api/generations/${encodeURIComponent(gid)}/${encodeURIComponent(variant)}/slides/slide-${String(n).padStart(3, "0")}.jpg`;

/** The variant's rendered previews, once the build has rendered them (the export, from 86 %): the server's list of the
 *  previews written so far is asked for every 1.5 s, and only the listed images are loaded — never a request for an
 *  image that is not there yet; a listed one that fails to load is tried again with the next round. */
function useSlidePreviews(gid: string | null | undefined, variant: string, count: number, enabled: boolean): Record<number, string> {
  const [found, setFound] = useState<Record<string, string>>({});
  const foundRef = useRef(found);
  foundRef.current = found;
  useEffect(() => {
    if (!gid || !enabled || count <= 0) return;
    let alive = true;
    let timer = 0;
    const load = (name: string) =>
      new Promise<void>((resolve) => {
        const n = Number(name.match(/(\d+)/)?.[1] ?? NaN);
        const key = `${variant}/${n}`;
        if (!Number.isFinite(n) || foundRef.current[key]) return resolve();
        const url = slideUrl(gid, variant, n);
        const img = new Image();
        img.onload = () => {
          if (alive) setFound((m) => (m[key] ? m : { ...m, [key]: url }));
          resolve();
        };
        img.onerror = () => resolve();
        img.src = url;
      });
    const round = async () => {
      let names: string[] = [];
      try {
        names = (await api.slideList(gid, variant)).slides;
      } catch {
        /* the server is busy with the export: the next round asks again */
      }
      if (!alive) return;
      await Promise.all(names.map(load));
      if (alive && Object.keys(foundRef.current).filter((k) => k.startsWith(`${variant}/`)).length < count) timer = window.setTimeout(round, 1500);
    };
    void round();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [gid, variant, count, enabled]);
  return useMemo(() => {
    const out: Record<number, string> = {};
    for (const [key, url] of Object.entries(found)) {
      const [v, n] = [key.slice(0, key.lastIndexOf("/")), Number(key.slice(key.lastIndexOf("/") + 1))];
      if (v === variant) out[n] = url;
    }
    return out;
  }, [found, variant]);
}

/** The phase's words in the page's title: a new phase cross-fades in, at most once per TITLE_DWELL_MS (a burst of
 *  phases skips to the newest). The heading is a polite live region. */
function PhaseTitle({ text: wanted }: { text: string }) {
  const [text, setText] = useState(wanted);
  const since = useRef(performance.now());
  useEffect(() => {
    if (wanted === text) return;
    const t = window.setTimeout(() => {
      since.current = performance.now();
      setText(wanted);
    }, Math.max(0, TITLE_DWELL_MS - (performance.now() - since.current)));
    return () => window.clearTimeout(t);
  }, [wanted, text]);
  return (
    <h1 className="truncate text-title1 font-semibold text-zinc-900" aria-live="polite">
      <span key={text} className="animate-fade">{text}</span>
    </h1>
  );
}

/** Whether a variant is ready, after its name in the switch: a check once it is, an empty slot of the same width
 *  before (the switch never changes its size; how far the shown variant is, the storyboard's own line says). Nothing
 *  spins: the page has one place that says the work goes on — its title. */
function variantMeta(st: VariantState): ReactNode {
  return (
    <span className="inline-flex w-3.5 justify-end">
      {st.done && <Check className="h-3.5 w-3.5 text-accent-600" strokeWidth={2.75} aria-hidden />}
      <span className="sr-only">{st.done ? "готово" : st.text}</span>
    </span>
  );
}

/** The time since the build began beside the five-minute limit («1:42 · лимит 5:00»: not «из», which would read as
 *  a share next to the bar; past it, the time alone). Its own clock: once a second it re-renders itself, not the page. */
function Elapsed({ since }: { since: number }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);
  const ms = Date.now() - since;
  return (
    <p className="shrink-0 whitespace-nowrap tabular-nums" title="Обещаем уложиться в пять минут">
      <span className="text-title2 font-semibold text-zinc-900">{clock(ms / 1000)}</span>
      {ms <= PROMISE_MS && <span className="ml-1.5 text-body text-zinc-400">· лимит {clock(PROMISE_MS / 1000)}</span>}
    </p>
  );
}

export function BuildScreen({ job }: { job: ActiveJob }) {
  const { strategies, strategyTitle, templates, templateId, manifest, templateLabel } = useApp();
  const vt = useEntrance();
  // inside the transition, the entrances of the page's content end at once (a later change still animates)
  const rootRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!vt.quiet) return;
    for (const a of rootRef.current?.getAnimations({ subtree: true }) ?? []) {
      const name = (a as Animation & { animationName?: string }).animationName;
      if (name && ENTRANCES.has(name)) a.finish();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const tid = job.template ?? templateId;
  const tpl = templates.find((t) => t.template_id === tid);
  const file = tpl?.source_file ?? (manifest?.template_id === tid ? manifest?.source_file : null);
  // the cards have the slides' proportions and draw in the template's own strong colour
  const aspect = tpl?.aspect && tpl.aspect > 0 ? tpl.aspect : manifest?.template_id === tid && manifest ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9;
  const ink = useMemo(() => sketchInk(tpl?.palette), [tpl?.palette]);

  const names = job.items?.length ? job.items : strategies.map((s) => s.name);
  // «VK Tech · 3 варианта · сегодня, 18:14»
  const meta = [tid || file ? templateLabel(tid, file) : "", names.length > 1 ? plural(names.length, "вариант", "варианта", "вариантов") : "", fmtWhen(job.startedAt / 1000)].filter(Boolean).join(" · ");
  const message = job.message;
  // saving the files means every variant has been laid out and checked
  const exporting = /^сохраняю файлы/i.test(message);
  const queued = job.status === "queued";

  // the variants are laid out one after another: the check of the first must not end «Вёрстка» for the others
  const laying = !exporting && names.some((n) => (job.variants?.[n]?.frac ?? 0) < 0.75);
  const phase: PhaseKey | null = job.phase === "check" && laying ? "layout" : job.phase ?? null;

  const variantOf = (name: string): VariantState => {
    if (exporting) return { ...job.variants?.[name], text: "готово", done: true, frac: 1 };
    const st = job.variants?.[name];
    if (st && st.text !== "план готов") return st;
    // before the pipeline reports: where the agent is with this variant (shared lines count for every variant);
    // a variant waiting behind another at the critic is with the critic too
    let own: PhaseKey | null = null;
    for (const e of job.agent ?? []) if (e.variant == null || e.variant === name) own = laterPhase(own, phaseOfStep(e.step));
    const jobAt = phase && (phase === "critic" || phase === "revise" || phase === "layout" || phase === "check") ? "critic" : phase;
    const at = laterPhase(own, jobAt);
    if (st || at === "layout" || at === "check") return { ...st, text: "в очереди на вёрстку", done: false, frac: 0 };
    return { text: AGENT_STATUS[at ?? "analyst"] ?? "работаю…", done: false, frac: 0, indeterminate: true };
  };

  // the pipeline's own messages speak for the steps the agent does not narrate (laying out, checking)
  const layoutNote = useMemo(() => {
    const busy = names.map((n) => ({ n, st: job.variants?.[n] })).find(({ st }) => st && !st.done && /вёрстка/.test(st.text));
    return busy?.st ? `${strategyTitle(busy.n)}: ${busy.st.text}` : null;
  }, [names, job.variants, strategyTitle]);
  const checkNote = /проверка качества|исправляю замечания|сохраняю файлы/i.test(message) ? message : null;
  const rows = useMemo(() => {
    const notes: Partial<Record<PhaseKey, string | null>> = {
      layout: phase === "layout" ? layoutNote : null,
      check: phase === "check" ? checkNote : null,
    };
    // before Agent v2 the plan came in one piece: the designer row says so instead of listing slides
    if (!job.agent?.length && phase && phase !== "analyst") notes.designer = "план готов";
    return buildTimeline({ events: job.agent ?? [], phase, running: true, notes });
  }, [job.agent, phase, layoutNote, checkNote]);
  const activeIdx = rows.findIndex((r) => r.status === "active");
  const step = activeIdx >= 0 ? activeIdx + 1 : Math.max(1, rows.filter((r) => r.status === "done" || r.status === "skipped").length);
  const stepText = queued || rows.length === 0 ? "в очереди" : `шаг ${Math.min(step, rows.length)} из ${rows.length}`;
  const title = STAGE_TITLE[queued ? "queued" : phase ?? "queued"];

  // the variant whose slides are shown: the first one until the person picks another
  const [picked, setPicked] = useState<string | null>(null);
  const shown = picked && names.includes(picked) ? picked : names[0] ?? "";
  const own = job.variants?.[shown];
  const laid = exporting ? own?.of ?? 0 : own?.laid ?? 0;
  const count = own?.of ?? job.slides ?? 0;
  const rail = useMemo(() => railSlides(job.agent ?? [], shown, count, laid, own?.of !== undefined), [job.agent, shown, count, laid, own?.of]);
  // until the plan says how many slides there are, ten empty cards hold the place
  const cards = rail.length ? rail : Array.from({ length: 10 }, (_, i) => ({ n: i + 1, sketch: null, mark: null, laid: false }));
  // the slide the agent speaks of: the newest line's (when it is about this variant), else the newest planned one
  const line = job.line ?? null;
  const lineSlide = line?.slide && (line.variant == null || line.variant === shown) ? line.slide : null;
  const lastPlanned = [...rail].reverse().find((s) => s.sketch)?.n ?? null;
  const focus = exporting ? null : lineSlide ?? lastPlanned;
  // the previews come with the export (LibreOffice renders every deck at once, from 86 %): asked for from then on only
  const previews = useSlidePreviews(job.generation, shown, rail.length, job.progress >= 0.86 || exporting);

  const planned = rail.filter((s) => s.sketch).length;
  const laidCount = rail.filter((s) => s.laid).length;
  const boardStatus =
    !rail.length ? "план ещё не готов"
    : laidCount > 0 ? `сверстано ${laidCount} из ${rail.length}`
    : planned > 0 ? `продумано ${planned} из ${rail.length}`
    : String(rail.length);

  const segments: SegmentedItem<string>[] = names.map((name) => {
    const st = variantOf(name);
    return { key: name, label: strategyTitle(name), meta: variantMeta(st), title: [variantHint(name), st.text].filter(Boolean).join(" — ") };
  });

  const pct = Math.round(Math.min(1, Math.max(0, job.progress)) * 100);

  return (
    // left edge = the header's container edge, also while the helper narrows `main` (identical to mx-auto otherwise)
    <div ref={rootRef} className="build-root ml-[max(0px,calc((100vw-1600px)/2))] mr-auto flex h-full min-h-[600px] max-w-[1600px] flex-col px-8 py-6">
      {/* laid out like the result's title bar (H1 + meta line), so the title stays put when the deck replaces the build */}
      <div className="flex shrink-0 items-end gap-6">
        {/* vt-title: the phase cross-fades in place into the deck's title when the build ends */}
        <div className={cn("min-w-0 flex-1", vt.title && "vt-title")}>
          <PhaseTitle text={title} />
          {meta && <p className="truncate text-footnote text-zinc-500" title={meta}>{meta}</p>}
        </div>
        <Elapsed since={job.startedAt} />
      </div>
      <div
        role="progressbar"
        aria-label="Сборка презентации"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={queued ? undefined : pct}
        className="relative mt-4 h-1 shrink-0 overflow-hidden rounded-full bg-zinc-200/80"
      >
        {queued ? (
          // with less motion the queue is a faint full bar, not a still segment that would read as progress
          <div className="absolute inset-y-0 left-0 w-[30%] animate-sweep rounded-full bg-accent motion-reduce:w-full motion-reduce:animate-none motion-reduce:opacity-30" />
        ) : (
          <div className="h-full w-full rounded-full bg-accent transition-transform duration-600 ease-out" style={{ transform: `translateX(${pct - 100}%)` }} />
        )}
      </div>

      <div className="build-grid mt-6 grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] gap-4">
        <StoryBoard
          variant={shown}
          slides={cards}
          images={previews}
          focus={focus}
          aspect={aspect}
          ink={ink}
          running={!queued}
          status={boardStatus}
          switcher={names.length > 1 ? <Segmented ariaLabel="Вариант, чьи слайды показаны" items={segments} value={shown} onChange={setPicked} className="!bg-zinc-200/60" /> : null}
        />
        <AgentLog rows={rows} variantTitle={strategyTitle} step={stepText} className={cn("build-log", vt.names && "vt-aside")} />
      </div>
    </div>
  );
}
