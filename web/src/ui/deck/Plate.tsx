// Плита колоды: место `.p2-slot` (абсолютно, 812 px, своя высота в колоде через translateY) и `section.p2-plate`
// со скруглением 40 и полями 40/48. Разметка — boards/V2.dc.html, плиты 01–04.
import type { CSSProperties, ReactNode } from "react";
import { cls } from "../kit/cls";

export function Plate({ z, y, height = 812, slotClass, className, label, style, children }: {
  /** z-index места: 1–4 для плит колоды, слои выше. */
  z: number;
  /** translateY места, px. */
  y: number;
  /** Высота места: 812 на компьютере, стопкой — высота колоды (ui/deck/stack.ts). */
  height?: number;
  slotClass?: string;
  className?: string;
  label: string;
  /** Цвета, тень и задержка подъёма плиты. */
  style?: CSSProperties;
  children?: ReactNode;
}) {
  return (
    <div className={cls("p2-slot", slotClass)} style={{ position: "absolute", left: 0, right: 0, top: 0, height, zIndex: z, transform: `translateY(${y}px)` }}>
      <section className={cls("p2-plate", className)} aria-label={label} style={{ position: "relative", height: "100%", padding: "40px 48px", borderRadius: 40, ...style }}>
        {children}
      </section>
    </div>
  );
}
