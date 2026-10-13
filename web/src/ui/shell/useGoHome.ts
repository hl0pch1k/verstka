// «На главную» (логотип) и «Новая презентация» компактного результата: V2 `goHome` / `restart` — `go('create')` и чистый
// лист: пустой текст и аудитория (черновик тоже; остальные параметры остаются), текст раскрыт, разделы и «Все
// параметры» закрыты, «Улучшить готовую» снята. С результата плита 04 уходит вниз непрозрачной вместе с плитами
// (`down`); `go` сбрасывает `down`, поэтому он ставится после и держится, если плита ещё уезжает от прошлого нажатия.
import { useApp } from "../../store";
import { useGoDown } from "../result/useGoDown";

export function useGoHome(): () => void {
  const { ui, dispatch, setBrief, setParams } = useApp();
  const goDown = useGoDown();
  return () => {
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: false, down: ui.down } });
    setBrief("");
    setParams({ audience: "" });
    if (ui.screen === "result") goDown();
  };
}
