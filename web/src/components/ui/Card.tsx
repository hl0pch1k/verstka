import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Hover affordance for clickable cards. */
  interactive?: boolean;
  /** Accent outline for the selected card in a set. */
  selected?: boolean;
}

// VK surfaces: white on the grey canvas, 16px radius, a hairline instead of a border.
export function Card({ interactive = false, selected = false, className, ...rest }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-white",
        selected ? "shadow-[0_0_0_2px_#0077FF]" : "shadow-card",
        interactive && "cursor-pointer transition-shadow duration-200 hover:shadow-raise",
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
    <div className={cn("flex min-h-[60px] items-center justify-between gap-3 px-6 pb-2 pt-5", className)} {...rest}>
      <div className="min-w-0 flex-1">{children}</div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {
  icon?: IconProp;
  /** Secondary line under the title. */
  hint?: ReactNode;
}

export function CardTitle({ icon, hint, className, children, ...rest }: CardTitleProps) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      {icon && <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-50 text-accent">{renderIcon(icon, "h-[18px] w-[18px]")}</span>}
      <div className="min-w-0">
        <h3 className={cn("truncate text-[17px] font-semibold leading-6 text-zinc-900", className)} {...rest}>
          {children}
        </h3>
        {hint && <p className="truncate text-[13px] leading-5 text-zinc-500">{hint}</p>}
      </div>
    </div>
  );
}

// Default paddings step aside per axis when the caller sets its own (no tailwind-merge: two paddings would fight).
const PAD_X = /(^|\s)p[xlr]?-/;
const PAD_Y = /(^|\s)p[ytb]?-/;

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  const c = className ?? "";
  return <div className={cn(!PAD_X.test(c) && "px-6", !PAD_Y.test(c) && "pb-6 pt-3", className)} {...rest} />;
}
