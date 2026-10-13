import { useCallback, useEffect, useRef } from "react";
import { useApp } from "../../store";

/** Плита результата едет 520 мс; флаг хода снимается, когда плиты встали (V2 `openDoc`: 560 мс). */
const MOVE_MS = 560;

/** Открытие презентации из «Создать» («Мои презентации», «Подробный разбор», «Сборка готова · Открыть»): плита
 *  результата поднимается снизу одним движением с плитами 02/03 (`p2-s4-up`). Зовётся после `go` (он сбрасывает
 *  `rise`); флаг снимается своим таймером, повторный ход начинает таймер заново. Уход вниз (`down`) ставит сам `go`
 *  (ui/deck/geometry), а снимает таймер колоды. */
export function useRise(): () => void {
  const { dispatch } = useApp();
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useCallback(() => {
    dispatch({ type: "set", patch: { rise: true } });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => dispatch({ type: "set", patch: { rise: false } }), MOVE_MS);
  }, [dispatch]);
}
