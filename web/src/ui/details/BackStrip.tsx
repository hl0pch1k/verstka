// Полоса «04 Интеграл · Структурный 89» плиты результата под листом «Подробнее» (V2 `dd-back`): видна, пока лист
// открыт (проявляется и гаснет вместе с ним), клик по ней закрывает лист; при наведении справа — «Вернуться к
// результату». Стоит в плите результата, как полоса «04 Результат» под слоем текста.
import { useApp } from "../../store";
import type { Generation, Variant } from "../../types";
import { Icon } from "../kit/Icon";
import { backStrip } from "./sheetView";

export function BackStrip({ g, v }: { g: Generation; v: Variant }) {
  const { ui, dispatch, strategyTitle } = useApp();
  const s = backStrip(g, v, strategyTitle);
  return (
    <div className={ui.sheet ? "p2-on" : "p2-off"}>
      <button type="button" className="dd-back" onClick={(e) => { e.currentTarget.blur(); dispatch({ type: "sheet", tab: null }); }} aria-label={s.aria}>
        <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 700, fontSize: 13, lineHeight: "20px", color: "#5A6272" }}>04</span>
        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", fontSize: 14, fontWeight: 700, lineHeight: "20px", color: "#0B1220" }}>{s.title}</span>
        <span style={{ flex: "none", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: "#5A6272" }}>{s.name}{s.score !== null && <> <span className="p2-rsc">{s.score}</span></>}</span>
        <span className="dd-back-hint" aria-hidden="true">Вернуться к результату<Icon name="chevron-down" size={16} /></span>
      </button>
    </div>
  );
}
