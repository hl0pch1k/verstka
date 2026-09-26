// A light, quiet header on the page's own grid, exactly 64px (the hairline is an inset shadow, not a border): the brand
// (home) on the left; «Мои презентации», «Помощник» and, on a deck, «Новая презентация» on the right — all 40px. A thin
// progress line runs along the bottom while a job works somewhere neither the build screen nor the helper shows it.
import { forwardRef, useEffect, useState } from "react";
import { MessageCircle, Plus } from "lucide-react";
import { useApp } from "../../store";
import { TopBarGenerations } from "../TopBarGenerations";
import { Button } from "../ui/Button";
import { Progress } from "../ui/Progress";
import { Logo } from "./Logo";

/** The helper toggle; the dot says a reply came while the helper was closed. */
const HelperToggle = forwardRef<HTMLButtonElement, { open: boolean; unread: boolean; onClick(): void }>(function HelperToggle({ open, unread, onClick }, ref) {
  return (
    <span className="relative inline-flex">
      <Button ref={ref} id="helper-toggle" variant="tonal" size="md" icon={MessageCircle} aria-pressed={open} aria-controls="helper" onClick={onClick}>
        Помощник
      </Button>
      {unread && <span className="pointer-events-none absolute left-7 top-2 h-2 w-2 animate-pop rounded-full bg-red-500 ring-2 ring-white" title="Новый ответ" aria-hidden />}
    </span>
  );
});

export function Header() {
  const { generations, generationId, loadGeneration, screen, setScreen, setDetail, activeJob, agentOpen, setAgentOpen, messages } = useApp();
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const building = jobRunning && activeJob?.kind === "generate";
  // the build screen has its own progress: the header line is for the other jobs (edits, fixes, template analysis)
  const buildVisible = screen === "result" && activeJob?.kind === "generate";

  // replies that arrived while the helper was closed light a dot on its toggle
  const replies = messages.filter((m) => m.role === "assistant").length;
  const [seen, setSeen] = useState(replies);
  useEffect(() => {
    if (agentOpen) setSeen(replies);
  }, [agentOpen, replies]);
  const unread = !agentOpen && replies > seen;

  return (
    <header className="relative z-30 shrink-0 bg-white shadow-[inset_0_-1px_0_rgba(0,16,61,0.08)]">
      <div className="mx-auto flex h-16 w-full max-w-[1600px] items-center gap-2 px-8">
        <Logo
          onClick={() => {
            setDetail(null);
            setScreen("create");
          }}
        />
        <div className="ml-auto flex items-center gap-2">
          <TopBarGenerations
            generations={generations}
            currentId={generationId}
            onSelect={async (id) => {
              await loadGeneration(id);
              setDetail(null);
              setScreen("result");
            }}
          />
          <HelperToggle open={agentOpen} unread={unread} onClick={() => setAgentOpen(!agentOpen)} />
          {/* gone while a deck is being built; an edit or a fix only disables it, so the header never shifts under the pointer */}
          {screen === "result" && !building && (
            <Button variant="secondary" size="md" icon={Plus} disabled={jobRunning} onClick={() => setScreen("create")}>
              Новая презентация
            </Button>
          )}
        </div>
      </div>
      {/* the open helper shows the job's progress itself */}
      {jobRunning && !buildVisible && !agentOpen && (
        <Progress size="xs" flat value={activeJob?.progress ?? 0} indeterminate={activeJob?.status === "queued"} className="absolute inset-x-0 bottom-0" />
      )}
    </header>
  );
}
