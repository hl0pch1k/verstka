import { useCallback, useEffect, useRef } from "react";
import { useApp } from "../../store";

/** Плита результата едет 520 мс; флаг хода снимается, когда плиты встали (V2 `openDoc`, `go('create')`: 560 мс). */
const MOVE_MS = 560;

/** Флаг хода плиты результата (`down` — уходит вниз, `rise` — поднимается снизу) на время её хода: ставится после `go`
 *  (он сбрасывает оба) и снимается своим таймером; повторный ход начинает таймер заново. */
function usePlateMove(flag: "down" | "rise"): () => void {
  const { dispatch } = useApp();
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useCallback(() => {
    dispatch({ type: "set", patch: flag === "down" ? { down: true } : { rise: true } });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => dispatch({ type: "set", patch: flag === "down" ? { down: false } : { rise: false } }), MOVE_MS);
  }, [dispatch, flag]);
}

/** Логотип, «Изменить текст», «Дописать текст», «Изменить» в слое текста, неудачная из «Мои презентации»: плита
 *  результата уходит вниз непрозрачной вместе со своей презентацией. Зовётся после `go` (он сбрасывает `down`). */
export function useGoDown(): () => void {
  return usePlateMove("down");
}

/** Открытие презентации из «Создать» («Мои презентации», «Подробный разбор»): плита результата поднимается снизу одним
 *  движением с плитами 02/03 (`p2-s4-up`). Зовётся после `go` (он сбрасывает `rise`). */
export function useRise(): () => void {
  return usePlateMove("rise");
}
