import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { presenceNext, presenceWaits, type Presence } from "./presence";

/** Держит содержимое смонтированным, пока идёт уход (ms), и включает «показ» только после того, как закрытое состояние
 *  встало в DOM (и прошли ещё два кадра) — так CSS-переход входа всегда стартует из закрытого состояния. Шаги — чистая
 *  presenceNext (presence.ts). Показ ждёт отрисовки закрытого, а не просто двух кадров от клика: тяжёлое содержимое (лист
 *  «Подробнее», «Мои презентации», «Шаблоны») рисуется дольше кадра, и React сливал «смонтировать закрытым» и «показать»
 *  в одну отрисовку — слой вставал сразу на место, без подъёма.
 *  `warm` — смонтировать закрытым заранее (наведение на пункт шапки, layers/warm.ts): закрытое уже нарисовано, и показ —
 *  в том же кадре, что открытие (до отрисовки, useLayoutEffect), подъём начинается в кадре нажатия. */
export function usePresence(open: boolean, ms: number, warm = false): Presence {
  const [state, setState] = useState<Presence>(() => ({ mounted: open || warm, shown: open }));
  // закрытое состояние нарисовано (смонтировано не в этом кадре)
  const painted = useRef(false);
  useEffect(() => {
    if (open) {
      // смонтировать закрытым; показ — эффект ниже, когда закрытое уже в DOM
      setState((p) => (p.mounted ? p : presenceNext(p, true)));
      return;
    }
    const step = () => setState((p) => (warm && !p.shown ? p : presenceNext(p, false)));
    step();
    const t = window.setTimeout(step, ms);
    return () => window.clearTimeout(t);
  }, [open, ms, warm]);
  // прогрев: смонтировать закрытым
  useEffect(() => {
    if (warm && !open) setState((p) => (p.mounted ? p : { mounted: true, shown: false }));
  }, [warm, open]);
  // закрытое смонтированное — через два кадра считается нарисованным
  useEffect(() => {
    if (!state.mounted) {
      painted.current = false;
      return;
    }
    if (state.shown || painted.current) return;
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        painted.current = true;
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [state.mounted, state.shown]);
  // открыли прогретое (закрытое уже нарисовано) — показ в этом же кадре
  useLayoutEffect(() => {
    if (open && state.mounted && !state.shown && painted.current) setState({ mounted: true, shown: true });
  }, [open, state]);
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
