import { useEffect, useState } from "react";
import { OF0, OF_LAND_MS, OF_REST_MS, ofStep, ofTimer, type OfState } from "./offline";

/** Режим полосок логотипа по состоянию связи (V2 `ofSync`/`ofLater`). Шаг к `off` делается прямо в рендере (так
 *  класс бега появляется в том же кадре, что и красный цвет), таймеры возврата и кадра покоя — в эффекте и снимаются
 *  при размонтировании. */
export function useOffline(off: boolean): OfState {
  const [state, setState] = useState<OfState>(() => ofStep(OF0, off));
  const next = ofStep(state, off);
  if (next !== state) setState(next);
  const { mode, rest } = next;
  useEffect(() => {
    if (mode !== "land" && !rest) return;
    const t = window.setTimeout(() => setState(ofTimer), mode === "land" ? OF_LAND_MS : OF_REST_MS);
    return () => window.clearTimeout(t);
  }, [mode, rest]);
  return next;
}
