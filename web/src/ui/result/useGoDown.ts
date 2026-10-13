import { useCallback, useEffect, useRef } from "react";
import { useApp } from "../../store";

/** Плита результата уходит вниз 520 мс; `down` снимается, когда она ушла за край (V2 `go('create')`: 560 мс). */
const DOWN_MS = 560;

/** «Изменить текст», «Дописать текст», «Изменить» в слое текста: плита результата уходит вниз непрозрачной вместе со
 *  своей презентацией, как с логотипа. Зовётся после `go` (он сбрасывает `down`). */
export function useGoDown(): () => void {
  const { dispatch } = useApp();
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useCallback(() => {
    dispatch({ type: "set", patch: { down: true } });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => dispatch({ type: "set", patch: { down: false } }), DOWN_MS);
  }, [dispatch]);
}
