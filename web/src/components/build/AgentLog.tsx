// The right column of a build: how the agent thinks, step by step — the same timeline the drawer's «Агент» keeps for a
// finished deck, live here: Аналитик → Дизайнер (a line per slide with the form it chose) → Критик (its notes, each
// fix on a line of its own) → Правка → Вёрстка → Проверка, every line in mono like a train of thought, the slide it is
// about in a small tag. The column scrolls by itself and follows the newest line unless the reader has scrolled up to
// read; the active step's title stays pinned at its top.
import type { TimelineRow } from "../../lib/agent";
import { cn } from "../../lib/utils";
import { AgentTimeline } from "../simple/AgentTimeline";

export function AgentLog({ rows, variantTitle, running, className }: {
  rows: TimelineRow[];
  /** Names the variants of a line that holds for some of them only. */
  variantTitle(name: string): string;
  running: boolean;
  className?: string;
}) {
  return (
    <aside aria-label="Как думает агент" className={cn("flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-card", className)}>
      <div className="flex h-14 shrink-0 items-center gap-2 px-5">
        <h2 className="text-title3 font-semibold text-zinc-900">Как думает агент</h2>
        {running && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-caption font-semibold text-[#3858FF]">
            <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-[#3858FF]" aria-hidden />
            думает
          </span>
        )}
      </div>
      {/* data-follow: the timeline keeps this box at its newest line */}
      <div data-follow className="scroll-thin relative min-h-0 flex-1 overflow-y-auto px-5 pb-5">
        <AgentTimeline rows={rows} variantTitle={variantTitle} follow pinClassName="top-0 z-[2]" className="pt-1" />
      </div>
    </aside>
  );
}
