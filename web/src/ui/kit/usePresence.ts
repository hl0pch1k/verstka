import { useEffect, useState } from "react";
import { useStack } from "../shell/tier";
import { presenceNext, type Presence } from "./presence";

/** Держит содержимое смонтированным, пока идёт уход (ms), и включает «показ» со следующего кадра после монтирования —
 *  так CSS-переход входа всегда стартует из закрытого состояния. Шаги — чистая presenceNext (presence.ts).
 *  Колода стопкой (окно уже 1280): показ — только после того, как закрытое состояние встало в DOM (второй эффект ждёт его
 *  отрисовки и ещё двух кадров). Тяжёлое содержимое (лист «Подробнее», раздел) рисуется дольше кадра, и React сливал
 *  «смонтировать закрытым» и «показать» в одну отрисовку — плита вставала сразу на место, без подъёма. На компьютере —
 *  как было. */
export function usePresence(open: boolean, ms: number): Presence {
  const stack = useStack();
  const [state, setState] = useState<Presence>(() => ({ mounted: open, shown: open }));
  useEffect(() => {
    const step = () => setState((p) => presenceNext(p, open));
    if (stack && open) {
      // смонтировать закрытым; показ — второй эффект, когда закрытое уже в DOM
      setState((p) => (p.mounted ? p : presenceNext(p, true)));
      return;
    }
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
  }, [open, ms, stack]);
  const waiting = stack && open && state.mounted && !state.shown;
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
