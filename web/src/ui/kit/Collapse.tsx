import type { ReactNode } from "react";
import { cls } from "./cls";

/** Раскрываемое тело (D-quality, D-plan, D-template): открытое появляется ходом `p2-in` (12 px вверх и проявление,
 *  360 мс), закрытое убирается сразу — как в V2. `as` — тег тела с доски (например, `ul` у списков D-quality). */
export function Collapse({ open, children, id, className, as: Tag = "div" }: {
  open: boolean;
  children: ReactNode;
  id?: string;
  className?: string;
  as?: "div" | "ul" | "ol" | "section";
}) {
  if (!open) return null;
  return (
    <Tag id={id} className={cls(className, "p2-in")}>
      {children}
    </Tag>
  );
}
