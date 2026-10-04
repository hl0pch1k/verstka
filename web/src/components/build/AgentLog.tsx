// The right column of a build: how the agent thinks, step by step — the same timeline the drawer's «Агент» keeps for a
// finished deck, live here: Аналитик → Дизайнер (a line per slide with the form it chose) → Критик (its notes, each
// fix on a line of its own) → Правка → Вёрстка → Проверка, the slide a line is about in a small badge. Laid out like
// the storyboard beside it: the title and «шаг 3 из 6» on the page, on the storyboard's line, then a white card that
// starts level with the first row of slides. The card scrolls by itself and follows the newest line unless the reader
// has scrolled up to read; the active step's title stays pinned at its top; lines still below fade out at its foot.
import { useCallback, useEffect, useRef, useState } from "react";
import type { TimelineRow } from "../../lib/agent";
import { cn } from "../../lib/utils";
import { AgentTimeline } from "../simple/AgentTimeline";

export function AgentLog({ rows, variantTitle, step, className }: {
  rows: TimelineRow[];
  /** Names the variants of a line that holds for some of them only. */
  variantTitle(name: string): string;
  /** «шаг 3 из 6», «в очереди» */
  step: string;
  className?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  // more lines below the card's foot: they fade out instead of being cut through
  const [more, setMore] = useState(false);
  const measure = useCallback(() => {
    const el = box.current;
    if (el) setMore(el.scrollTop + el.clientHeight < el.scrollHeight - 2);
  }, []);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    return () => ro.disconnect();
  }, [measure]);
  return (
    <aside aria-label="Как думает агент" className={cn("flex min-h-0 min-w-0 flex-col", className)}>
      <div className="flex h-16 shrink-0 items-center gap-3">
        <h2 className="text-title3 font-semibold text-zinc-900">Как думает агент</h2>
        <span className="ml-auto shrink-0 text-footnote tabular-nums text-zinc-500">{step}</span>
      </div>
      {/* mt-1: level with the storyboard's cards (its list keeps 4px of room for their focus ring) */}
      <div className="mt-1 flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-card">
        {/* data-follow: the timeline keeps this box at the active step's newest line; the active step's title is pinned
            at its top edge on white, the lines scroll away under it */}
        <div
          ref={box}
          data-follow
          onScroll={measure}
          className={cn("scroll-thin relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 pb-6 pt-5", more && "[mask-image:linear-gradient(to_bottom,#000_calc(100%-40px),transparent)]")}
        >
          <AgentTimeline rows={rows} variantTitle={variantTitle} follow pinClassName="top-0 z-[2]" />
        </div>
      </div>
    </aside>
  );
}
