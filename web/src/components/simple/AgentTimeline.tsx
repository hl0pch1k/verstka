// The agent's work as a vertical list of steps: Аналитик → (Архитектор) → Дизайнер → Критик → Правка → Вёрстка →
// Проверка. Each step shows what it said in plain words; the designer adds a line per slide with the form it chose.
// Used live on the build screen (new lines fade in once, the list follows the newest one) and, finished, in «Как
// работал агент».
import { useLayoutEffect, useRef } from "react";
import { Check, Loader2, Minus } from "lucide-react";
import { eventText, type TimelineRow } from "../../lib/agent";
import { cn } from "../../lib/utils";
import type { AgentEvent } from "../../types";

function Dot({ status, n }: { status: TimelineRow["status"]; n: number }) {
  return (
    <span
      className={cn(
        "relative z-[1] flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition-colors duration-300",
        status === "done" && "bg-accent text-white",
        status === "active" && "bg-white text-accent shadow-[inset_0_0_0_2px_#0077FF]",
        status === "pending" && "bg-zinc-100 text-zinc-400",
        status === "skipped" && "bg-zinc-100 text-zinc-400",
      )}
      aria-hidden
    >
      {status === "done" ? <Check key="d" className="h-3.5 w-3.5 animate-pop" strokeWidth={3} /> : status === "active" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : status === "skipped" ? <Minus className="h-3.5 w-3.5" strokeWidth={3} /> : n}
    </span>
  );
}

function Line({ e, variantTitle, onSlide, pad }: { e: AgentEvent; variantTitle?: (name: string) => string; onSlide?: (n: number) => void; pad: boolean }) {
  const slide = e.slide ?? null;
  // a line about no slide in a list of slide lines keeps the text column aligned
  const badge = slide === null ? pad && <span className="w-[58px] shrink-0" aria-hidden /> : (
    onSlide ? (
      <button type="button" onClick={() => onSlide(slide)} title={`Открыть слайд ${slide}`} className="mt-px inline-flex h-[18px] min-w-[58px] shrink-0 cursor-pointer items-center justify-center rounded-md bg-accent-50 px-1.5 text-[11px] font-semibold tabular-nums text-accent-700 transition-colors hover:bg-accent-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30">
        Слайд {slide}
      </button>
    ) : (
      <span className="mt-px inline-flex h-[18px] min-w-[58px] shrink-0 items-center justify-center rounded-md bg-zinc-100 px-1.5 text-[11px] font-semibold tabular-nums text-zinc-600">Слайд {slide}</span>
    )
  );
  return (
    <li className="flex items-start gap-2 animate-fade-in text-[13px] leading-5 text-zinc-700">
      {badge}
      <span className="min-w-0 flex-1">
        {e.variant && variantTitle && <span className="mr-1.5 whitespace-nowrap text-xs font-medium text-zinc-500">{variantTitle(e.variant)}:</span>}
        {eventText(e)}
      </span>
    </li>
  );
}

export function AgentTimeline({ rows, variantTitle, onSlide, follow = false, className }: {
  rows: TimelineRow[];
  /** Names a variant in a line of its own («Визуальный: 2 замечания»). */
  variantTitle?: (name: string) => string;
  /** Makes the slide badges open that slide. */
  onSlide?: (n: number) => void;
  /** Live: the scrolling parent keeps the newest line in view unless the reader has scrolled up. */
  follow?: boolean;
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
    <ol ref={ref} className={cn("relative", className)}>
      {rows.map((r, i) => {
        const last = i === rows.length - 1;
        const lit = r.status === "done" || r.status === "active";
        return (
          <li key={r.key} className="relative flex gap-3 pb-4 last:pb-0">
            {!last && <span className={cn("absolute left-[11px] top-7 bottom-1 w-0.5 rounded-full transition-colors duration-500", r.status === "done" ? "bg-accent/30" : "bg-zinc-100")} aria-hidden />}
            <Dot status={r.status} n={i + 1} />
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="flex flex-wrap items-baseline gap-x-2 leading-5">
                <span className={cn("text-[14px] font-semibold transition-colors", lit ? "text-zinc-900" : "text-zinc-400")}>{r.title}</span>
                {(r.events.length === 0 || r.status === "active") && !r.note && (
                  <span className={cn("text-xs", r.status === "active" ? "text-zinc-600" : "text-zinc-400")}>{r.hint}</span>
                )}
                {r.note && <span className={cn("text-xs", r.status === "skipped" || r.status === "pending" ? "text-zinc-400" : "text-zinc-600")}>{r.note}</span>}
              </p>
              {r.events.length > 0 && (
                <ul className="mt-1.5 space-y-1">
                  {r.events.map((e, k) => (
                    <Line key={e.seq ?? `${r.key}-${k}`} e={e} variantTitle={variantTitle} onSlide={onSlide} pad={r.events.some((x) => x.slide !== null && x.slide !== undefined)} />
                  ))}
                </ul>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
