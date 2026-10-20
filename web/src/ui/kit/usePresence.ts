import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { presenceNext, presenceWaits, type Presence } from "./presence";

/** Держит содержимое смонтированным, пока идёт уход (ms), и включает «показ» только после того, как закрытое состояние
 *  встало в DOM (и прошли ещё два кадра) — так CSS-переход входа всегда стартует из закрытого состояния. Шаги — чистая
 *  presenceNext (presence.ts). Показ ждёт отрисовки закрытого, а не просто двух кадров от клика: тяжёлое содержимое
 *  рисуется дольше кадра, и React сливал «смонтировать закрытым» и «показать» в одну отрисовку — без подъёма.
 *  `instant` (слои колоды) — показ в том же кадре: закрытое монтируется, его стиль пересчитывается принудительно (до
 *  отрисовки, useLayoutEffect), и сразу ставится показ — переход стартует из закрытого в кадре нажатия.
 *  `warm` — смонтировать закрытым заранее (наведение на пункт шапки, layers/warm.ts): тяжёлое содержимое монтируется не в
 *  кадре нажатия. */
export function usePresence(open: boolean, ms: number, warm = false, instant = false): Presence {
  const [state, setState] = useState<Presence>(() => ({ mounted: open || warm, shown: open }));
  // закрытое состояние нарисовано (смонтировано не в этом кадре)
  const painted = useRef(false);
  useEffect(() => {
    if (open) {
      // смонтировать закрытым; показ — ниже (в этом же кадре или когда закрытое уже в DOM)
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
  // открытие: смонтировать закрытым — в этом же кадре (instant); показ — в этом же кадре, если закрытое уже нарисовано
  // (прогрев) или если стиль закрытого пересчитан принудительно (instant)
  useLayoutEffect(() => {
    if (!open || state.shown) return;
    if (!state.mounted) {
      if (instant) setState({ mounted: true, shown: false });
      return;
    }
    if (painted.current || instant) {
      // закрытое — в стиле: переход входа стартует из него
      if (!painted.current) void document.body.offsetWidth;
      setState({ mounted: true, shown: true });
    }
  }, [open, state, instant]);
  const waiting = presenceWaits(open, state) && !instant;
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
