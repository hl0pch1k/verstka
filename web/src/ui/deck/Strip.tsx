// Полоса свёрнутой плиты: «01 VK Tech 54 слайда · Play» по верхнему краю плиты (40 px), видна, когда плита
// лежит под следующей (сборка, результат, «Все параметры»). Разметка — boards/V2.dc.html (`stripCls`, `strip3`).
import type { ReactNode } from "react";

/** Что пишет полоса: название, приписка и значок перед названием (у полосы 03 — «Сборка завершена»). */
export interface StripData { title?: ReactNode; meta?: ReactNode; icon?: ReactNode }

export function Strip({ n, title, meta, icon, on, dark, onClick, label }: StripData & {
  /** Номер плиты: «01», «02», «03». */
  n: string;
  /** Полоса видна (p2-on) или скрыта (p2-off). */
  on: boolean;
  /** Тёмная плита 03: светлые цифра и текст. */
  dark?: boolean;
  /** Клик по всей полосе (кнопка p2-sbtn поверх) — возврат к шагу. */
  onClick?: () => void;
  label?: string;
}) {
  return (
    <div className={on ? "p2-strip p2-on" : "p2-strip p2-off"} style={{ position: "absolute", left: 48, right: 48, top: 0, height: 40, display: "flex", alignItems: "center", gap: 12, whiteSpace: "nowrap" }}>
      <span style={{ flex: "none", fontFamily: "'Unbounded','Manrope',sans-serif", fontWeight: 700, fontSize: 13, lineHeight: "20px", color: dark ? "rgba(255,255,255,.56)" : "#5A6272" }}>{n}</span>
      {icon}
      {/* длинное название сжимается многоточием, приписка остаётся целой */}
      {title != null && (
        <span title={typeof title === "string" ? title : undefined}
          style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", fontSize: 14, fontWeight: 700, lineHeight: "20px", color: dark ? "#FFFFFF" : "#0B1220" }}>
          {title}
        </span>
      )}
      {meta != null && <span style={{ flex: "none", fontSize: 13, fontWeight: 500, lineHeight: "20px", color: dark ? "rgba(255,255,255,.64)" : "#5A6272" }}>{meta}</span>}
      {onClick && <button type="button" className="p2-sbtn" onClick={onClick} aria-label={label} />}
    </div>
  );
}
