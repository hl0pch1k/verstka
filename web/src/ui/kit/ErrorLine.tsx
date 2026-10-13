import type { CSSProperties } from "react";
import { Icon } from "./Icon";

/** Красная строка неудачи рядом с местом действия (без всплывающих уведомлений): значок «alert» 16 и текст 14/20, 600.
 *  `lines` — сколько строк занимает текст: 1 — одна строка с многоточием (полный текст в `title`), больше — обрезка
 *  после N строк, 0 — переносится целиком. `style` — отступы и ширина места, где стоит строка. */
export function ErrorLine({ text, lines = 0, style }: { text: string; lines?: number; style?: CSSProperties }) {
  const one = lines === 1;
  const clip: CSSProperties | undefined = one
    ? { overflow: "hidden", textOverflow: "ellipsis" }
    : lines > 1 ? { display: "-webkit-box", WebkitLineClamp: lines, WebkitBoxOrient: "vertical", overflow: "hidden" } : undefined;
  return (
    <p role="alert" title={lines ? text : undefined}
      style={{ display: one ? "inline-flex" : "flex", alignItems: one ? "center" : "flex-start", gap: 8, minWidth: 0, margin: 0, fontSize: 14, fontWeight: 600, lineHeight: "20px", color: "#DC2626", whiteSpace: one ? "nowrap" : undefined, ...style }}>
      <span style={{ display: "flex", flex: "none", paddingTop: one ? 0 : 2 }}><Icon name="alert" size={16} /></span>
      <span style={{ minWidth: 0, ...clip }}>{text}</span>
    </p>
  );
}
