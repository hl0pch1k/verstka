// Шапка «Слоёв»: логотип (на главную) со строкой связи и пункты разделов. Разметка — boards/V2.dc.html,
// `<header class="p2-hdr">`.
import { useApp } from "../../store";
import { useGoDown } from "../result/useGoDown";
import { Brand } from "./Brand";
import { Nav } from "./Nav";

export function Header() {
  const { ui, dispatch, healthError, setBrief, setParams } = useApp();
  const goDown = useGoDown();

  // V2 `goHome`: `go('create')` и чистый лист — пустой текст и аудитория (черновик тоже; остальные параметры
  // остаются), текст раскрыт, разделы и «Все параметры» закрыты, «Улучшить готовую» снята. С результата плита 04
  // уходит вниз непрозрачной вместе с плитами (`down`); `go` сбрасывает `down`, поэтому он ставится после и держится,
  // если плита ещё уезжает от прошлого нажатия.
  const goHome = () => {
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: false, down: ui.down } });
    setBrief("");
    setParams({ audience: "" });
    if (ui.screen === "result") goDown();
  };

  return (
    <header className="p2-hdr" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 64, padding: "0 48px" }}>
      <Brand offline={healthError} onHome={goHome} />
      <Nav />
    </header>
  );
}
