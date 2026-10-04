// The right column of a build: how the agent thinks, step by step — the same timeline the drawer's «Агент» keeps for a
// finished deck, live here: Аналитик → Дизайнер (a line per slide with the form it chose) → Критик (its notes, each
// fix on a line of its own) → Правка → Вёрстка → Проверка, the slide a line is about in a small badge. The column
// scrolls by itself and follows the newest line unless the reader has scrolled up to read; the active step's title
// stays pinned at its top. The header says which step of how many is at work.
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
  return (
    <aside aria-label="Как думает агент" className={cn("flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-card", className)}>
      <div className="flex h-16 shrink-0 items-center gap-3 px-6">
        <h2 className="text-title3 font-semibold text-zinc-900">Как думает агент</h2>
        <span className="ml-auto shrink-0 text-footnote tabular-nums text-zinc-500">{step}</span>
      </div>
      {/* data-follow: the timeline keeps this box at the active step's newest line; the active step's title is pinned at
          its top edge on white, the lines scroll away under it */}
      <div data-follow className="scroll-thin relative min-h-0 flex-1 overflow-y-auto px-6 pb-6">
        <AgentTimeline rows={rows} variantTitle={variantTitle} follow pinClassName="top-0 z-[2]" className="pt-1" />
      </div>
    </aside>
  );
}
