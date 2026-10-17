import { useEffect, useState } from "react";
import { presenceNext, presenceWaits, type Presence } from "./presence";

/** Держит содержимое смонтированным, пока идёт уход (ms), и включает «показ» только после того, как закрытое состояние
 *  встало в DOM (и прошли ещё два кадра) — так CSS-переход входа всегда стартует из закрытого состояния. Шаги — чистая
 *  presenceNext (presence.ts). Показ ждёт отрисовки закрытого, а не просто двух кадров от клика: тяжёлое содержимое (лист
 *  «Подробнее», «Мои презентации», «Шаблоны») рисуется дольше кадра, и React сливал «смонтировать закрытым» и «показать»
 *  в одну отрисовку — слой вставал сразу на место, без подъёма. */
export function usePresence(open: boolean, ms: number): Presence {
  const [state, setState] = useState<Presence>(() => ({ mounted: open, shown: open }));
  useEffect(() => {
    if (open) {
      // смонтировать закрытым; показ — эффект ниже, когда закрытое уже в DOM
      setState((p) => (p.mounted ? p : presenceNext(p, true)));
      return;
    }
    const step = () => setState((p) => presenceNext(p, false));
    step();
    const t = window.setTimeout(step, ms);
    return () => window.clearTimeout(t);
  }, [open, ms]);
  const waiting = presenceWaits(open, state);
  useEffect(() => {
    if (!waiting) return;
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => setState((p) => presenceNext(p, true)));
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [waiting]);
  return state;
}
