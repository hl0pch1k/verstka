// Плита колоды: место `.p2-slot` (абсолютно, 812 px, своя высота в колоде через translateY) и `section.p2-plate`
// со скруглением 40 и полями 40/48. Разметка — boards/V2.dc.html, плиты 01–04.
import type { CSSProperties, ReactNode } from "react";
import { cls } from "../kit/cls";
import { DECK_H } from "./geometry";

export function Plate({ z, y, height = DECK_H, vis, slotClass, className, label, style, children }: {
  /** z-index места: 1–4 для плит колоды, слои выше. */
  z: number;
  /** translateY места, px. */
  y: number;
  /** Высота места: 812 на компьютере, стопкой — высота колоды (ui/deck/stack.ts). */
  height?: number;
  /** Телефон: видимая высота плиты (`--vis`) — по ней содержимое прокручивается внутри плиты (stack.css). */
  vis?: number;
  slotClass?: string;
  className?: string;
  label: string;
  /** Цвета, тень и задержка подъёма плиты. */
  style?: CSSProperties;
  children?: ReactNode;
}) {
  const { background, boxShadow, ...rest } = style ?? {};
  // место — всегда свой слой (translateZ(0)): иначе Safari делает его слоем только на время наведения на кнопку или
  // миниатюру внутри и по окончании снова рисует в документ — в уменьшенной сцене (stage.ts) пиксели округляются
  // по-разному, и вся плита на миг сдвигается (замечание владельца 18.10, скрин 20)
  return (
    <div className={cls("p2-slot", slotClass)}
      style={{ position: "absolute", left: 0, right: 0, top: 0, height, zIndex: z, transform: `translateY(${y}px) translateZ(0)`, ...(vis !== undefined && { "--vis": `${vis}px` }) } as CSSProperties}>
      {/* фон плиты — слой под содержимым (`p2-pbg`, shell.css): при открытии помощника на «Результате» край колоды
          едет им одним (clip-path), а раскладка меняется один раз (helperFlip.ts) */}
      <section className={cls("p2-plate p2-pbg", className)} aria-label={label}
        style={{ position: "relative", height: "100%", padding: "40px 48px", borderRadius: 40, ...rest, "--pbg": background, "--psh": boxShadow ?? "none" } as CSSProperties}>
        {children}
      </section>
    </div>
  );
}
