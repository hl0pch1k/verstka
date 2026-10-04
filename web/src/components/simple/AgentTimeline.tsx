// How the agent thinks, as a vertical list of steps: Аналитик → (Архитектор) → Дизайнер → Критик → Правка → Вёрстка →
// Проверка. Each step shows what it said, like a train of thought: the designer adds a line per slide with the form it
// chose, the critic a note per slide with its fix on a line of its own (→). The slide a line is about sits in a small
// number badge beside it. Used live in the build's right column and, finished, in the drawer's «Агент». Live, the lines
// of one poll arrive as a small cascade (40 ms apart, once) in their own room (the steps below simply move down: a glide
// would pass over the new lines), a finished step's connector fills downwards in VK blue, the active step's title stays
// pinned and the column follows the active step's newest line.
import { useLayoutEffect, useRef, type CSSProperties } from "react";
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Loader2, Minus } from "lucide-react";
import { eventParts, keepTogether, slideGroups, type PhaseKey, type TimelineEvent, type TimelineRow } from "../../lib/agent";
import { MOTION, smoothScroll } from "../../lib/motion";
import { cn } from "../../lib/utils";

function Dot({ status, n, live }: { status: TimelineRow["status"]; n: number; /** The step has just finished while the reader watched: its check springs in. */ live: boolean }) {
  return (
    <span
      className={cn(
        "relative z-[1] flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-caption font-semibold tabular-nums transition-[background-color,color,box-shadow] duration-300",
        status === "done" && "bg-accent-fill text-white",
        status === "active" && "bg-white text-accent shadow-[inset_0_0_0_1.5px_#0077FF]",
        (status === "pending" || status === "skipped") && "bg-zinc-100 text-zinc-500",
      )}
      aria-hidden
    >
      {status === "done" ? (
        // the check springs in when a step ends while the reader watches (a finished log in the drawer stays calm)
        <Check key="d" className={cn("h-3.5 w-3.5", live && "animate-pop")} strokeWidth={2.5} />
      ) : status === "active" ? (
        <span key="a" className="flex animate-fade">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        </span>
      ) : status === "skipped" ? (
        <Minus className="h-3.5 w-3.5" strokeWidth={2.5} />
      ) : (
        n
      )}
    </span>
  );
}

const TAG = "relative inline-flex h-5 w-7 shrink-0 items-center justify-center rounded-md text-caption font-semibold tabular-nums";

/** The slide's number badge (opens «Почему так» when `onSlide` is given), a figure-check icon, or an empty column. */
function Tag({ slide, onSlide, mark, className, style }: { slide: number | null; onSlide?: (n: number) => void; mark: "ok" | "warn" | null; className?: string; style?: CSSProperties }) {
  if (slide !== null) {
    const n = String(slide);
    return onSlide ? (
      // the 20×28 badge hits as 32×40 (a transparent margin around it)
      <button type="button" onClick={() => onSlide(slide)} title={`Почему слайд ${slide} такой`} aria-label={`Слайд ${slide}: почему так`} className={cn(TAG, "tap cursor-pointer bg-accent-50 text-accent-700 after:absolute after:-inset-1.5 after:content-[''] hover:bg-accent-100", className)} style={style}>
        {n}
      </button>
    ) : (
      <span className={cn(TAG, "bg-zinc-100 text-zinc-600", className)} style={style} title={`Слайд ${slide}`}>
        <span className="sr-only">Слайд </span>
        {n}
      </span>
    );
  }
  return (
    <span className={cn("flex h-5 w-7 shrink-0 items-center justify-center", className)} style={style} aria-hidden>
      {mark === "ok" && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
      {mark === "warn" && <AlertTriangle className="h-4 w-4 text-amber-500" />}
    </span>
  );
}

/** «Сверил цифры…» and «… (проверьте)» of the layout step: the figures checked against the text. */
const figureMark = (text: string): "ok" | "warn" | null => (/\(проверьте\)/i.test(text) ? "warn" : /^сверил цифры/i.test(text) ? "ok" : null);

type Parts = ReturnType<typeof eventParts>;

function Said({ e, parts, variantTitle, className, style }: { e: TimelineEvent; parts: Parts; variantTitle?: (name: string) => string; className?: string; style?: CSSProperties }) {
  const { text, fix } = parts;
  const warn = figureMark(text) === "warn";
  return (
    <div className={cn("min-w-0 max-w-[760px] flex-1", className)} style={style}>
      <p className={warn ? "text-amber-700" : "text-zinc-700"}>{text}</p>
      {/* the variants a line holds for, on a line of their own (inside the sentence they broke it) */}
      {e.variants && e.variants.length > 0 && variantTitle && (
        <p className="mt-1 flex">
          <span className="inline-flex h-[18px] items-center whitespace-nowrap rounded-md bg-zinc-100 px-1.5 text-[11px] font-medium text-zinc-600">
            {e.variants.map(variantTitle).join(", ")}
          </span>
        </p>
      )}
      {fix && (
        <p className="mt-1 flex gap-1.5 text-zinc-800">
          <ArrowRight className="mt-[3px] h-3.5 w-3.5 shrink-0 text-emerald-600" aria-hidden />
          <span className="min-w-0">
            <span className="sr-only">Исправление: </span>
            {fix}
          </span>
        </p>
      )}
    </div>
  );
}

/** The entrance delay of a line that just arrived (ms), or null: no entrance. */
type Arrival = (e: TimelineEvent) => number | null;

function Lines({ row, variantTitle, onSlide, arrival }: { row: TimelineRow; variantTitle?: (name: string) => string; onSlide?: (n: number) => void; arrival?: Arrival }) {
  // each line's words once per render (the cleaning runs a few dozen patterns)
  const parts = new Map(row.events.map((e) => [e, eventParts(e)] as const));
  const partsOf = (e: TimelineEvent) => parts.get(e) ?? eventParts(e);
  // a line that just arrived fades up 4px, 40 ms after the one before it in its batch; the group's badge comes with its
  // first line, a later line of the same slide on its own (a group's key is its first line, which a later line never
  // displaces: the lines of a slide stay in arrival order)
  const enter = (e: TimelineEvent): { className?: string; style?: CSSProperties } => {
    const delay = arrival?.(e) ?? null;
    return delay === null ? {} : { className: "animate-fade-in", style: { animationDelay: `${Math.round(delay)}ms` } };
  };
  // consecutive lines about one slide share its badge, the same while the agent works and after
  return (
    <ul className={cn("mt-2 text-footnote [overflow-wrap:anywhere]", row.key === "critic" ? "space-y-3" : "space-y-2")}>
      {slideGroups(row.events).map((g, gi) => (
        // the badge column is kept on every line of every step: all the lines start at one edge
        <li key={g.events[0].seq ?? `${row.key}-g${gi}`} className="flex items-start gap-2">
          <Tag slide={g.slide} onSlide={onSlide} mark={figureMark(partsOf(g.events[0]).text)} {...enter(g.events[0])} />
          <div className="min-w-0 flex-1 space-y-1">
            {g.events.map((e, k) => (
              <Said key={e.seq ?? k} e={e} parts={partsOf(e)} variantTitle={variantTitle} {...enter(e)} />
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** A line's identity across polls: its sequence number, or (older events) what it says where. */
const lineKey = (e: TimelineEvent) => (e.seq !== undefined && e.seq !== null ? `#${e.seq}` : `${e.step}|${e.slide ?? ""}|${e.variant ?? ""}|${e.message}`);

/** How long a line keeps its entrance class: longer than the longest cascade (6 × 40 ms + 200 ms), so a re-render in
 *  the middle never cuts a fade short, and short enough that a line re-mounted later never replays it. */
const ENTER_WINDOW = 1000;
/** The latest a line may start after it arrived: the stagger cap (6 × 40 ms). */
const MAX_WAIT = MOTION.stagger * MOTION.staggerMax;

export function AgentTimeline({ rows, variantTitle, onSlide, follow = false, pinClassName = "top-0 z-[2]", className }: {
  rows: TimelineRow[];
  /** Names the variants of a line that holds for some of them only («Структурный · Визуальный»). */
  variantTitle?: (name: string) => string;
  /** Makes the slide badges open that slide. */
  onSlide?: (n: number) => void;
  /** Live: the scrolling parent ([data-follow]) keeps the newest line in view unless the reader has scrolled up, and
   *  the active step's title stays pinned while its lines stream in. */
  follow?: boolean;
  /** Where the pinned title stops and how high it sits (under a page's own sticky bar: «top-24 z-[11]»). */
  pinClassName?: string;
  className?: string;
}) {
  const ref = useRef<HTMLOListElement>(null);
  const total = rows.reduce((n, r) => n + r.events.length, 0);
  const active = rows.find((r) => r.status === "active")?.key;
  const stick = useRef(true);

  // a step's check springs in only when the step finishes while the reader watches (opened mid-build, the steps already
  // done are simply done): the moment each step turned done, kept for the length of the pop
  const statusSeen = useRef<Map<PhaseKey, TimelineRow["status"]> | null>(null);
  const doneAt = useRef(new Map<PhaseKey, number>());
  if (follow) {
    const now = performance.now();
    const seen = statusSeen.current;
    for (const r of rows) {
      const was = seen?.get(r.key);
      if (seen && r.status === "done" && was !== undefined && was !== "done") doneAt.current.set(r.key, now);
    }
    statusSeen.current = new Map(rows.map((r) => [r.key, r.status]));
  }
  const justDone = (key: PhaseKey) => performance.now() - (doneAt.current.get(key) ?? -Infinity) < 600;

  // live: the lines cascade in, 40 ms apart, in reading order — a poll's batch as one cascade, and lines that stream in
  // one by one (server events a few ms apart) spaced out the same way; a line that comes alone starts at once. Each
  // line keeps its delay across re-renders (the clock ticks every second), so a fade is never restarted or cut. The
  // lines already there when the timeline mounts come in with the card, without a cascade of their own
  const born = useRef<{ lines: Map<string, { delay: number; at: number }>; next: number } | null>(null);
  let arrival: Arrival | undefined;
  if (follow) {
    const now = performance.now();
    const first = born.current === null;
    const b = (born.current ??= { lines: new Map(), next: 0 });
    for (const r of rows) {
      for (const e of r.events) {
        const key = lineKey(e);
        if (b.lines.has(key)) continue;
        if (first) {
          b.lines.set(key, { delay: -1, at: now });
          continue;
        }
        const start = Math.min(Math.max(now, b.next), now + MAX_WAIT);
        b.next = start + MOTION.stagger;
        b.lines.set(key, { delay: start - now, at: now });
      }
    }
    arrival = (e) => {
      const l = b.lines.get(lineKey(e));
      return l && l.delay >= 0 && now - l.at < ENTER_WINDOW ? l.delay : null;
    };
  }
  // live, the column follows the active step's newest line: the scroll that puts the end of that step at the column's
  // foot (its pinned title stays in view above its lines; the steps still to come wait below, out of the way); with no
  // step at work, the end of the list
  const target = (box: HTMLElement) => {
    const li = active ? ref.current?.querySelector<HTMLElement>(`[data-step="${active}"]`) : null;
    const end = li ? li.getBoundingClientRect().bottom - box.getBoundingClientRect().top + box.scrollTop + 16 : box.scrollHeight;
    return Math.max(0, Math.min(box.scrollHeight - box.clientHeight, end - box.clientHeight));
  };
  // our own smooth scrolls are not the reader's: their scroll events are ignored for their length
  const autoUntil = useRef(0);
  useLayoutEffect(() => {
    if (!follow) return;
    const box = ref.current?.closest("[data-follow]") as HTMLElement | null;
    if (!box) return;
    // the reader going up (the wheel, a touch, the keys) stops the following at once, even in the middle of one of our
    // own scrolls; a drag of the scrollbar is told by the position; scrolling back down to the newest line resumes it
    const off = () => {
      stick.current = false;
      autoUntil.current = 0;
    };
    const onWheel = (e: WheelEvent) => e.deltaY < 0 && off();
    const onKey = (e: KeyboardEvent) => ["ArrowUp", "PageUp", "Home"].includes(e.key) && off();
    let last = box.scrollTop;
    const onScroll = () => {
      const top = box.scrollTop;
      if (performance.now() >= autoUntil.current) {
        if (top < last - 1) stick.current = false;
        else if (top >= target(box) - 24) stick.current = true;
      }
      last = top;
    };
    box.addEventListener("scroll", onScroll, { passive: true });
    box.addEventListener("wheel", onWheel, { passive: true });
    box.addEventListener("touchmove", off, { passive: true });
    box.addEventListener("keydown", onKey);
    return () => {
      box.removeEventListener("scroll", onScroll);
      box.removeEventListener("wheel", onWheel);
      box.removeEventListener("touchmove", off);
      box.removeEventListener("keydown", onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [follow, active]);
  useLayoutEffect(() => {
    if (!follow || !stick.current) return;
    const box = ref.current?.closest("[data-follow]") as HTMLElement | null;
    if (!box || box.scrollHeight <= box.clientHeight) return;
    const top = target(box);
    if (Math.abs(top - box.scrollTop) < 1) return;
    autoUntil.current = performance.now() + 700;
    box.scrollTo({ top, behavior: smoothScroll() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [follow, total, active]);

  return (
    <ol ref={ref} className={cn("relative [text-wrap:pretty]", className)}>
      {rows.map((r, i) => {
        const last = i === rows.length - 1;
        const lit = r.status === "done" || r.status === "active";
        const pinned = follow && r.status === "active";
        // active: what the step does (its lines are still coming) — the layout and the check say how far they are; done:
        // what it came to
        const raw =
          r.status === "active" ? (r.key === "layout" || r.key === "check" ? r.note ?? r.hint : r.hint)
          : r.note ?? (r.events.length === 0 && r.status === "pending" ? r.hint : null);
        const aside = raw ? keepTogether(raw) : null;
        return (
          <li key={r.key} data-step={r.key} className="relative pb-6 last:pb-0">
            {/* the connector to the next step: a quiet track that fills downwards once the step is done */}
            {!last && (
              <span className="absolute bottom-1 left-[11px] top-7 w-0.5 overflow-hidden rounded-full bg-zinc-100" aria-hidden>
                <span className={cn("absolute inset-0 origin-top rounded-full bg-accent-200 transition-transform duration-600 ease-out", r.status === "done" ? "scale-y-100" : "scale-y-0")} />
              </span>
            )}
            {/* pinned, the title sticks at the scroller's content edge: a white band above it covers the scroller's top
                padding, so no line shows above the pinned title (in the flow the band lies over the step above's own
                bottom padding, which is empty) */}
            <div className={cn("-mx-2 -my-1 flex items-center gap-3 px-2 py-1", pinned && cn("sticky bg-white before:pointer-events-none before:absolute before:inset-x-0 before:bottom-full before:h-5 before:bg-white before:content-['']", pinClassName))}>
              <Dot status={r.status} n={i + 1} live={follow && justDone(r.key)} />
              <p className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                <span className={cn("text-body font-semibold transition-colors duration-150", lit ? "text-zinc-900" : "text-zinc-500")}>{r.title}</span>
                {/* live, «что делает» → «к чему пришёл» cross-fades when the step ends (the finished log stays still; the layout's
                    «4 из 6» → «5 из 6» simply changes) */}
                {aside && (
                  <span key={follow ? r.status : undefined} className={cn("text-footnote", r.status === "active" ? "text-zinc-600" : "text-zinc-500", follow && "animate-fade")}>
                    {aside}
                  </span>
                )}
              </p>
              {/* the lines that scroll under the pinned title fade out over 24px instead of showing a line cut in half,
                  drawn only while pinned (a hidden pseudo-element at opacity 0 still paints a strip in Chrome) */}
              {pinned && <span className="pointer-events-none absolute inset-x-0 top-full h-6 bg-gradient-to-b from-white to-transparent" aria-hidden />}
            </div>
            {r.events.length > 0 && (
              <div className="pl-9">
                <Lines row={r} variantTitle={variantTitle} onSlide={onSlide} arrival={arrival} />
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
