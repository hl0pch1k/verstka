// Dark app header: brand, the five-step flow, the running job, history, model status and the agent toggle.
import { AlertCircle, CheckCircle2, Loader2, Sparkles } from "lucide-react";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import { TopBarGenerations } from "../TopBarGenerations";
import { Logo } from "./Logo";
import { stepOf } from "./steps";
import { Stepper } from "./Stepper";

function JobPill() {
  const { activeJob, setTab, tab } = useApp();
  if (!activeJob) return null;
  const { status, label, progress, kind } = activeJob;
  const failed = status === "failed";
  const done = status === "done";
  const target = kind === "generate" ? "variants" : kind === "analyze" ? "template" : kind === "fix" ? "audit" : null;
  const Icon = failed ? AlertCircle : done ? CheckCircle2 : Loader2;
  return (
    <button
      type="button"
      onClick={() => target && stepOf(tab) !== target && setTab(target)}
      title={activeJob.message}
      className={cn(
        "flex h-9 max-w-[260px] shrink-0 cursor-pointer items-center gap-2 rounded-full pl-2.5 pr-3 text-[13px] font-semibold animate-fade",
        failed ? "bg-red-500/15 text-red-300" : done ? "bg-emerald-500/15 text-emerald-300" : "bg-accent/20 text-accent-200",
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0", !failed && !done && "animate-spin")} aria-hidden />
      <span className="hidden truncate min-[1600px]:inline">{label}</span>
      {!failed && !done && <span className="shrink-0 tabular-nums text-white/70">{Math.round(progress * 100)}%</span>}
    </button>
  );
}

function ModelStatus() {
  const { health, healthError } = useApp();
  const configured = health?.models_configured ?? false;
  const s = healthError
    ? { dot: "bg-red-500", text: "API недоступен", title: "Сервер не отвечает на /api" }
    : !health
      ? { dot: "bg-white/40", text: "Подключение", title: "Подключаемся к серверу" }
      : configured
        ? { dot: "bg-emerald-400", text: "Модели", title: "Открытые модели подключены (OpenRouter / инференс VK)" }
        : { dot: "bg-amber-400", text: "Офлайн", title: "Модели не настроены: работают эвристики и детерминированный планировщик" };
  return (
    <span className="flex h-9 items-center gap-2 rounded-full px-3 text-[13px] font-medium text-white/70" title={`${s.title}${health ? ` · v${health.version}` : ""}`}>
      <span className="relative flex h-2 w-2">
        {!healthError && health && <span className={cn("absolute inset-0 rounded-full opacity-60 animate-pulse-ring", s.dot)} aria-hidden />}
        <span className={cn("relative h-2 w-2 rounded-full", s.dot)} aria-hidden />
      </span>
      <span className="hidden min-[1500px]:inline">{s.text}</span>
    </span>
  );
}

export function Header({ unread }: { unread: number }) {
  const { generations, generationId, loadGeneration, tab, setTab, agentOpen, setAgentOpen, activeJob, setShowLibrary } = useApp();
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");

  const openGeneration = async (id: string) => {
    await loadGeneration(id);
    const step = stepOf(tab);
    if (step === "template" || step === "brief") setTab("variants");
  };

  return (
    <header className="relative z-30 flex h-16 shrink-0 items-center gap-4 bg-ink px-5 text-white min-[1600px]:gap-6 min-[1600px]:px-6">
      <Logo
        onClick={() => {
          setShowLibrary(false);
          setTab("template");
        }}
      />
      <div className="flex min-w-0 flex-1 justify-center">
        <Stepper />
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <JobPill />
        <TopBarGenerations generations={generations} currentId={generationId} onSelect={openGeneration} tone="dark" />
        <ModelStatus />
        <button
          type="button"
          onClick={() => setAgentOpen(!agentOpen)}
          aria-pressed={agentOpen}
          className={cn(
            "relative ml-1 flex h-9 cursor-pointer items-center gap-2 rounded-full px-3.5 text-[13px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40",
            agentOpen ? "bg-accent text-white shadow-glow" : "bg-white/[0.08] text-white hover:bg-white/[0.14]",
          )}
        >
          <Sparkles className="h-4 w-4" aria-hidden />
          Агент
          {!agentOpen && unread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-accent px-1 text-[10px] font-bold ring-2 ring-ink">{unread}</span>
          )}
        </button>
      </div>
      {jobRunning && (
        <div className="absolute inset-x-0 bottom-0 h-[2px] overflow-hidden bg-white/[0.06]" aria-hidden>
          <div className="h-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.max(4, Math.round((activeJob?.progress ?? 0) * 100))}%` }} />
        </div>
      )}
    </header>
  );
}
