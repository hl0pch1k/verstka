// Light, quiet header: the brand (home), «Мои презентации», and «Новая презентация» once a deck is open.
import { Plus } from "lucide-react";
import { useApp } from "../../store";
import { TopBarGenerations } from "../TopBarGenerations";
import { Button } from "../ui/Button";
import { Logo } from "./Logo";

export function Header() {
  const { generations, generationId, loadGeneration, screen, setScreen, setDetail, activeJob } = useApp();
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");

  return (
    <header className="relative z-30 flex h-[68px] shrink-0 items-center gap-4 border-b border-zinc-200/70 bg-white px-8">
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
        {screen === "result" && (
          <Button variant="primary" icon={Plus} disabled={jobRunning} onClick={() => setScreen("create")}>
            Новая презентация
          </Button>
        )}
      </div>
      {jobRunning && (
        <div className="absolute inset-x-0 bottom-0 h-[3px] overflow-hidden bg-accent-50" aria-hidden>
          <div className="h-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.max(4, Math.round((activeJob?.progress ?? 0) * 100))}%` }} />
        </div>
      )}
    </header>
  );
}
