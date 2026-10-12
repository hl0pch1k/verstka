import { useEffect, useState } from "react";
import { presenceNext, type Presence } from "./presence";

/** Держит содержимое смонтированным, пока идёт уход (ms), и включает «показ» со следующего кадра после монтирования —
 *  так CSS-переход входа всегда стартует из закрытого состояния. Шаги — чистая presenceNext (presence.ts). */
export function usePresence(open: boolean, ms: number): Presence {
  const [state, setState] = useState<Presence>(() => ({ mounted: open, shown: open }));
  useEffect(() => {
    const step = () => setState((p) => presenceNext(p, open));
    step();
    if (open) {
      let inner = 0;
      const outer = requestAnimationFrame(() => {
        inner = requestAnimationFrame(step);
      });
      return () => {
        cancelAnimationFrame(outer);
        cancelAnimationFrame(inner);
      };
    }
    const t = window.setTimeout(step, ms);
    return () => window.clearTimeout(t);
  }, [open, ms]);
  return state;
}
