// Пункты шапки: «Мои презентации» и «Шаблоны» открывают слои-разделы (`ui.sect`), «Помощник» — плиту помощника
// (`ui.helper`); открытый пункт — белая таблетка p2-nav-on. Разметка — boards/V2.dc.html, `<nav class="p2-navs">`.
import { useApp } from "../../store";
import { cls } from "../kit/cls";

export function Nav() {
  const { ui, dispatch } = useApp();
  const hist = ui.sect === "hist";
  const tpls = ui.sect === "tpls";
  return (
    <nav className="p2-navs" aria-label="Разделы" style={{ display: "flex", alignItems: "center", gap: 8, marginRight: -16 }}>
      <button type="button" className={cls("p2-nav", hist && "p2-nav-on")} aria-expanded={hist} aria-controls="p2-lay-h"
        onClick={() => dispatch({ type: "sect", sect: hist ? null : "hist" })}>Мои презентации</button>
      <button type="button" className={cls("p2-nav", tpls && "p2-nav-on")} aria-expanded={tpls} aria-controls="p2-lay-t"
        onClick={() => dispatch({ type: "sect", sect: tpls ? null : "tpls" })}>Шаблоны</button>
      <button type="button" className={cls("p2-nav", ui.helper && "p2-nav-on")} aria-expanded={ui.helper} aria-controls="hp-help"
        title={ui.helper ? "Закрыть помощника" : "Открыть помощника"}
        onClick={() => dispatch({ type: "set", patch: { helper: !ui.helper } })}>Помощник</button>
    </nav>
  );
}
