import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { cn } from "../lib/utils";
import { useApp } from "../store";
import { Progress } from "./ui/Progress";

/** Slim global progress strip for the job tracked by store.runJob(); renders nothing when idle. */
export function JobBar() {
  const { activeJob } = useApp();
  if (!activeJob) return null;

  const { status, label, message, progress } = activeJob;
  const failed = status === "failed";
  const done = status === "done";
  const Icon = failed ? AlertCircle : done ? CheckCircle2 : Loader2;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("relative z-10 shrink-0 border-b animate-fade-in", failed ? "border-red-200 bg-red-50" : done ? "border-emerald-200 bg-emerald-50" : "border-accent-100 bg-accent-50")}
    >
      <div className="flex h-9 items-center gap-2.5 px-6 text-[13px]">
        <Icon className={cn("h-4 w-4 shrink-0", failed ? "text-red-600" : done ? "text-emerald-600" : "animate-spin text-accent")} aria-hidden />
        <span className="shrink-0 font-medium text-zinc-900">{label}</span>
        {message && <span className={cn("min-w-0 flex-1 truncate", failed ? "text-red-700" : "text-zinc-600")}>{message}</span>}
        {!failed && <span className="ml-auto shrink-0 font-medium tabular-nums text-zinc-700">{Math.round(progress * 100)}%</span>}
      </div>
      <Progress value={failed ? 1 : progress} tone={failed ? "error" : done ? "success" : "accent"} size="xs" flat indeterminate={status === "queued"} className="absolute inset-x-0 bottom-0 translate-y-px" />
    </div>
  );
}
