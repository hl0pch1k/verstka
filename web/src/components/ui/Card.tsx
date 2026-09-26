import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Hover affordance for clickable cards. */
  interactive?: boolean;
  /** 2px VK-blue outline for the selected card in a set. */
  selected?: boolean;
}

// VK surfaces: white on the grey canvas, 16px radius, a hairline shadow instead of a border.
export function Card({ interactive = false, selected = false, className, ...rest }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-white",
        selected ? "shadow-selected" : "shadow-card",
        interactive && "cursor-pointer transition-shadow duration-150 hover:shadow-raise",
        className,
      )}
      {...rest}
    />
  );
}

export interface CardHeaderProps extends HTMLAttributes<HTMLDivElement> {
  /** Right-aligned controls (buttons, badges). */
  actions?: ReactNode;
}

export function CardHeader({ actions, className, children, ...rest }: CardHeaderProps) {
  return (
    <div className={cn("flex min-h-16 items-center gap-3 px-6 pb-2 pt-6", className)} {...rest}>
      <div className="min-w-0 flex-1">{children}</div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {
  /** @deprecated Cards carry no subtitle sentences: pass a short fact only (a count, «70 чисел сверены с текстом»). */
  hint?: ReactNode;
  /** A number after the title, lighter: «Макеты 37». */
  count?: ReactNode;
}

// The heading alone carries the section: no icon tiles, no subtitle.
export function CardTitle({ hint, count, className, children, ...rest }: CardTitleProps) {
  const hasCount = count !== undefined && count !== null && count !== "";
  const title = (
    <h3 className={cn("truncate text-title3 font-semibold text-zinc-900", className)} {...rest}>
      {children}
      {hasCount && <span className="ml-2 text-footnote font-normal tabular-nums text-zinc-500">{count}</span>}
    </h3>
  );
  if (!hint) return title;
  return (
    <div className="min-w-0">
      {title}
      <p className="mt-0.5 text-footnote text-zinc-500">{hint}</p>
    </div>
  );
}

// Default paddings step aside per side when the caller sets its own (no tailwind-merge: two paddings would fight).
const PAD_TOP = /(^|\s)(p|py|pt)-/;
const PAD_BOTTOM = /(^|\s)(p|py|pb)-/;
const PAD_X = /(^|\s)(p|px|pl|pr)-/;

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  const c = className ?? "";
  return <div className={cn(!PAD_X.test(c) && "px-6", !PAD_TOP.test(c) && "pt-2", !PAD_BOTTOM.test(c) && "pb-6", className)} {...rest} />;
}
