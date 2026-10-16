// Строка «Проверка слайда · N замечаний» под колонками «Почему так» (V2 `#dd-panel-why`): ведёт во вкладку «Качество».
// Одна для обычного слайда (Why.tsx) и для слайда с данными (DataWhy — там она часть обновления на месте).
import type { CSSProperties } from "react";
import { cls } from "../../kit/cls";
import { Icon } from "../../kit/Icon";
import { SEV, type QTone } from "../quality";

/** `fx` — класс перекрёстного затухания текста и тега (строка сама остаётся на месте, меняются только они). */
export function CheckRow({ check, onOpen, className, style, fx, ...rest }: {
  check: { text: string; tone: QTone | null }; onOpen(): void; className?: string; style?: CSSProperties; fx?: string; "data-mv"?: string;
}) {
  return (
    <button type="button" className={cls("dw-chk", className)} onClick={onOpen} aria-label={`Проверка слайда: ${check.text} — открыть вкладку «Качество»`} style={{ gridColumn: "1 / -1", ...style }} {...rest}>
      <span className="dd-ico" aria-hidden="true"><Icon name="list-check" size={18} /></span>
      <span style={{ fontFamily: "'Unbounded','Manrope',sans-serif", fontSize: 14, fontWeight: 600, lineHeight: "24px", letterSpacing: "-0.02em" }}>
        Проверка слайда <span className={fx} style={{ fontFamily: "'Manrope',system-ui,sans-serif", fontSize: 15, fontWeight: 500, letterSpacing: 0, color: "#5A6272" }}>· {check.text}</span>
      </span>
      {check.tone && <span className={cls("dd-tag", SEV[check.tone].cls, fx)}><Icon name={SEV[check.tone].icon} size={14} />{SEV[check.tone].label}</span>}
      <span style={{ display: "flex", marginLeft: "auto", flex: "none", color: "#5A6272" }}><Icon name="chevron-right" size={18} /></span>
    </button>
  );
}
