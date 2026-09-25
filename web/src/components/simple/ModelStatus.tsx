// «Модель: Qwen3.8-27B — доступна» under the create button: which model will plan the deck and whether it answers.
// Fetched when the Create screen opens, after every generation (flows.ts) and every 30 s while the screen is open.
import { useEffect, useMemo, useState } from "react";
import { modelIndicator, type Tone } from "../../lib/modelText";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import type { ModelsStatus } from "../../types";

const DOT: Record<Tone, string> = {
  ok: "bg-emerald-500",
  neutral: "bg-accent",
  retry: "bg-amber-400",
  warn: "bg-amber-500",
  off: "bg-zinc-400",
};

/** Seconds until a paused model is tried again, counted down between the status refreshes (0: nothing to wait for). */
export function useRetryIn(st: ModelsStatus | null): number {
  const got = useMemo(() => ({ at: Date.now(), s: st?.retry_in ?? 0 }), [st]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!got.s) return;
    const t = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(t);
  }, [got]);
  if (!got.s) return 0;
  return Math.max(0, Math.ceil(got.s - Math.max(0, now - got.at) / 1000));
}

export function ModelStatus({ enabled, className }: { enabled: boolean; className?: string }) {
  const { modelStatus, refreshModelStatus, healthError } = useApp();
  useEffect(() => {
    void refreshModelStatus();
    const t = window.setInterval(() => void refreshModelStatus(), 30000);
    return () => window.clearInterval(t);
  }, [refreshModelStatus]);
  const retryIn = useRetryIn(modelStatus);

  const ind = modelIndicator(modelStatus, enabled, retryIn);
  if (!ind || healthError) return null;
  return (
    <div className={cn("flex max-w-full flex-col items-center gap-1.5 animate-fade", className)} role="status" aria-live="polite">
      <span
        className="inline-flex max-w-full items-center gap-2 rounded-full bg-white/80 px-3 py-1.5 text-[13px] font-medium text-zinc-700 shadow-card"
        title={modelStatus?.config ? `Настройки моделей: ${modelStatus.config}` : undefined}
      >
        <span className="relative flex h-2 w-2 shrink-0" aria-hidden>
          {ind.tone === "warn" && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60 [animation-iteration-count:3]" />}
          <span className={cn("relative inline-flex h-2 w-2 rounded-full", DOT[ind.tone])} />
        </span>
        <span className="truncate">{ind.text}</span>
        {ind.retry && <span className="shrink-0 font-normal text-zinc-400">· {ind.retry}</span>}
      </span>
      {ind.hint && <p className="max-w-xl text-center text-xs leading-5 text-zinc-500">{ind.hint}</p>}
    </div>
  );
}
