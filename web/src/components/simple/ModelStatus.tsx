// One grey line in the create bar, only when no model can answer: «Модель недоступна · соберу без неё».
// Refreshed when the Create screen opens, after every generation (flows.ts) and every 30 s while the screen is open.
// It fades in when it appears and out when it goes (or while the bar shows a problem in its place).
import { useEffect, useMemo, useRef, useState } from "react";
import { MOTION, usePresence } from "../../lib/motion";
import { modelIndicator, type Indicator } from "../../lib/modelText";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import type { ModelsStatus } from "../../types";

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

export function ModelStatus({ enabled, hidden = false, className }: { enabled: boolean; /** Something else speaks in this spot now: fade out. */ hidden?: boolean; className?: string }) {
  const { modelStatus, refreshModelStatus, healthError } = useApp();
  useEffect(() => {
    void refreshModelStatus();
    const t = window.setInterval(() => void refreshModelStatus(), 30000);
    return () => window.clearInterval(t);
  }, [refreshModelStatus]);

  const ind = modelIndicator(modelStatus, enabled);
  const show = !!ind && !healthError && !hidden;
  const { mounted, leaving } = usePresence(show, MOTION.fast);
  // the line that is fading out keeps its words
  const last = useRef<Indicator | null>(ind);
  if (ind) last.current = ind;
  const shown = ind ?? last.current;
  if (!mounted || !shown) return null;
  return (
    <span
      className={cn("inline-flex min-w-0 items-center gap-2 text-footnote text-zinc-500", leaving ? "animate-fade-out" : "animate-fade", className)}
      role="status"
      aria-live="polite"
      aria-hidden={leaving || undefined}
    >
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-400" aria-hidden />
      <span className="truncate" title={shown.hint ? `${shown.text}. ${shown.hint}` : shown.text}>{shown.text}</span>
    </span>
  );
}
