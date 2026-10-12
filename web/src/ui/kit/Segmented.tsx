import type { CSSProperties, ReactNode } from "react";
import { cls } from "./cls";

/** Сегменты `.p2-rseg` (R-aside «Вариант оформления»): равные ячейки в таблетке #F3F4F1 высотой 48, выбранная — белая
 *  с тенью. `style` дополняет и перекрывает раскладку группы с доски. */
export function Segmented<T extends string | number>({ items, value, onPick, label, className, style }: {
  items: { key: T; label: ReactNode; title?: string }[];
  value: T;
  onPick(k: T): void;
  label?: string;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div role="group" aria-label={label} className={className}
      style={{ display: "grid", gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))`, gap: 4, height: 48, padding: 4, borderRadius: 999, background: "#F3F4F1", ...style }}>
      {items.map((it) => (
        <button key={String(it.key)} type="button" className={cls("p2-rseg", it.key === value && "p2-rseg-on")}
          aria-pressed={it.key === value} title={it.title} onClick={() => onPick(it.key)}>
          {it.label}
        </button>
      ))}
    </div>
  );
}
