// The agent's work as a vertical list of steps: Аналитик → (Архитектор) → Дизайнер → Критик → Правка → Вёрстка →
// Проверка. Each step shows what it said in plain words; the designer adds a line per slide with the form it chose,
// the critic a note per slide with its fix on a line of its own. Used live on the build screen (new lines fade in
// once, the active step's title stays pinned, the page follows the newest line) and, finished, in the drawer's «Агент».
import { useLayoutEffect, useRef } from "react";
import { AlertTriangle, ArrowRight, Check, CheckCircle2, Loader2, Minus } from "lucide-react";
import { eventParts, slideGroups, type TimelineEvent, type TimelineRow } from "../../lib/agent";
import { cn } from "../../lib/utils";

function Dot({ status, n }: { status: TimelineRow["status"]; n: number }) {
  return (
    <span
      className={cn(
        "relative z-[1] flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-caption font-bold transition-colors duration-300",
        status === "done" && "bg-accent-fill text-white",
        status === "active" && "bg-white text-accent shadow-selected-inset",
        (status === "pending" || status === "skipped") && "bg-zinc-100 text-zinc-500",
      )}
      aria-hidden
    >
      {status === "done" ? (
        <Check key="d" className="h-3.5 w-3.5 animate-pop" strokeWidth={2.5} />
      ) : status === "active" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : status === "skipped" ? (
        <Minus className="h-3.5 w-3.5" strokeWidth={2.5} />
      ) : (
        n
      )}
    </span>
  );
}

const TAG = "inline-flex h-5 min-w-[72px] shrink-0 items-center justify-center rounded-lg px-2 text-caption font-semibold tabular-nums";

/** The slide's badge (opens «Почему так» when `onSlide` is given), a figure-check icon, or an empty column. */
function Tag({ slide, onSlide, mark, className }: { slide: number | null; onSlide?: (n: number) => void; mark: "ok" | "warn" | null; className?: string }) {
  if (slide !== null) {
    return onSlide ? (
      <button type="button" onClick={() => onSlide(slide)} title={`Почему слайд ${slide} такой`} className={cn(TAG, "cursor-pointer bg-accent-50 text-accent-700 transition-colors duration-150 hover:bg-accent-100", className)}>
        Слайд {slide}
      </button>
    ) : (
      <span className={cn(TAG, "bg-zinc-100 text-zinc-600", className)}>Слайд {slide}</span>
    );
  }
  return (
    <span className={cn("flex h-5 w-[72px] shrink-0 items-center justify-center", className)} aria-hidden>
      {mark === "ok" && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
      {mark === "warn" && <AlertTriangle className="h-4 w-4 text-amber-500" />}
    </span>
  );
}

/** «Сверил цифры…» and «… (проверьте)» of the layout step: the figures checked against the text. */
const figureMark = (text: string): "ok" | "warn" | null => (/\(проверьте\)/i.test(text) ? "warn" : /^сверил цифры/i.test(text) ? "ok" : null);

function Said({ e, variantTitle, className }: { e: TimelineEvent; variantTitle?: (name: string) => string; className?: string }) {
  const { text, fix } = eventParts(e);
  const warn = figureMark(text) === "warn";
  return (
    <div className={cn("min-w-0 max-w-[760px] flex-1", className)}>
      <p className={warn ? "text-amber-700" : "text-zinc-700"}>
        {text}
        {e.variants && e.variants.length > 0 && variantTitle && (
          <span className="ml-2 inline-flex h-5 items-center whitespace-nowrap rounded-lg bg-zinc-100 px-2 align-top text-caption text-zinc-600">
            {e.variants.map(variantTitle).join(" · ")}
          </span>
        )}
      </p>
      {fix && (
        <p className="mt-1 flex gap-1 text-zinc-500">
          <ArrowRight className="mt-[3px] h-3.5 w-3.5 shrink-0 text-zinc-400" aria-hidden />
          <span className="min-w-0">
            <span className="sr-only">Исправление: </span>
            {fix}
          </span>
        </p>
      )}
    </div>
  );
}

function Lines({ row, variantTitle, onSlide, live }: { row: TimelineRow; variantTitle?: (name: string) => string; onSlide?: (n: number) => void; live: boolean }) {
  const pad = row.events.some((x) => x.slide !== null && x.slide !== undefined) || row.events.some((x) => figureMark(eventParts(x).text));
  // live, every piece fades in once, when it arrives: the group's badge with its first line, a later line of the same
  // slide on its own (a group's key is its first line, which a later line never displaces: the lines of a slide stay
  // in arrival order)
  const fade = live ? "animate-fade-in" : undefined;
  // consecutive lines about one slide share its badge, the same while the agent works and after
  return (
    <ul className={cn("mt-2", row.key === "critic" ? "space-y-3" : "space-y-2")}>
      {slideGroups(row.events).map((g, gi) => (
        <li key={g.events[0].seq ?? `${row.key}-g${gi}`} className="flex items-start gap-2 text-footnote">
          {pad && <Tag slide={g.slide} onSlide={onSlide} mark={figureMark(eventParts(g.events[0]).text)} className={fade} />}
          <div className="min-w-0 flex-1 space-y-1">
            {g.events.map((e, k) => (
              <Said key={e.seq ?? k} e={e} variantTitle={variantTitle} className={fade} />
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

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
  useLayoutEffect(() => {
    if (!follow) return;
    const box = ref.current?.closest("[data-follow]") as HTMLElement | null;
    if (!box) return;
    const onScroll = () => {
      stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
    };
    box.addEventListener("scroll", onScroll, { passive: true });
    return () => box.removeEventListener("scroll", onScroll);
  }, [follow]);
  useLayoutEffect(() => {
    if (!follow || !stick.current) return;
    const box = ref.current?.closest("[data-follow]") as HTMLElement | null;
    if (box && box.scrollHeight > box.clientHeight) box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
  }, [follow, total, active]);

  return (
    <ol ref={ref} className={cn("relative [text-wrap:pretty]", className)}>
      {rows.map((r, i) => {
        const last = i === rows.length - 1;
        const lit = r.status === "done" || r.status === "active";
        const pinned = follow && r.status === "active";
        // active: what the step does (its lines are still coming); done: what it came to
        const aside = r.status === "active" ? r.hint : r.note ?? (r.events.length === 0 && r.status === "pending" ? r.hint : null);
        return (
          <li key={r.key} className="relative pb-6 last:pb-0">
            {!last && (
              <span
                className={cn("absolute bottom-1 left-[11px] top-7 w-0.5 rounded-full transition-colors duration-300", r.status === "done" ? "bg-accent-200" : "bg-zinc-100")}
                aria-hidden
              />
            )}
            <div className={cn("-mx-2 -my-1 flex items-center gap-3 px-2 py-1", pinned && cn("sticky bg-white", pinClassName))}>
              <Dot status={r.status} n={i + 1} />
              <p className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                <span className={cn("text-body font-semibold transition-colors duration-150", lit ? "text-zinc-900" : "text-zinc-500")}>{r.title}</span>
                {aside && <span className={cn("text-footnote", r.status === "active" ? "text-zinc-600" : "text-zinc-500")}>{aside}</span>}
              </p>
              {/* the lines that scroll under the pinned title fade out instead of showing their cut descenders: a 4px
                  fade that fills the gap above the first line exactly, drawn only while pinned (a hidden pseudo-element
                  at opacity 0 still paints a strip in Chrome) */}
              {pinned && <span className="pointer-events-none absolute inset-x-0 top-full h-1 bg-gradient-to-b from-white to-transparent" aria-hidden />}
            </div>
            {r.events.length > 0 && (
              <div className="pl-9">
                <Lines row={r} variantTitle={variantTitle} onSlide={onSlide} live={follow} />
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
