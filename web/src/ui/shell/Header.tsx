// Шапка «Слоёв»: логотип (на главную) со строкой связи и пункты разделов. Разметка — boards/V2.dc.html,
// `<header class="p2-hdr">`.
import { useEffect, useRef } from "react";
import { useApp } from "../../store";
import { Brand } from "./Brand";
import { Nav } from "./Nav";

/** Плита результата уходит вниз 520 мс; `down` снимается, когда она ушла за край (V2 `go('create')`: 560 мс). */
const DOWN_MS = 560;

export function Header() {
  const { ui, dispatch, healthError, setBrief } = useApp();
  const downTimer = useRef(0);
  useEffect(() => () => window.clearTimeout(downTimer.current), []);

  // V2 `goHome`: `go('create')` и чистый лист — пустой текст (черновик тоже), текст раскрыт, разделы и «Все
  // параметры» закрыты, «Улучшить готовую» снята. С результата плита 04 уходит вниз непрозрачной вместе с плитами
  // (`down`); `go` сбрасывает `down`, поэтому он ставится после и держится, если плита ещё уезжает от прошлого нажатия.
  const goHome = () => {
    const fromResult = ui.screen === "result";
    dispatch({ type: "go", screen: "create" });
    dispatch({ type: "set", patch: { improve: false, down: fromResult || ui.down } });
    setBrief("");
    if (fromResult) {
      window.clearTimeout(downTimer.current);
      downTimer.current = window.setTimeout(() => dispatch({ type: "set", patch: { down: false } }), DOWN_MS);
    }
  };

  return (
    <header className="p2-hdr" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: 64, padding: "0 48px" }}>
      <Brand offline={healthError} onHome={goHome} />
      <Nav />
    </header>
  );
}
