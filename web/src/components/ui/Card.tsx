import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Hover affordance for clickable cards. */
  interactive?: boolean;
  /** Accent outline for the selected card in a set. */
  selected?: boolean;
}

export function Card({ interactive = false, selected = false, className, ...rest }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-xl border bg-white shadow-card",
        selected ? "border-accent ring-1 ring-accent/30" : "border-zinc-200",
        interactive && "cursor-pointer transition-shadow hover:shadow-pop",
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
    <div className={cn("flex min-h-[52px] items-center justify-between gap-3 border-b border-zinc-100 px-5 py-3", className)} {...rest}>
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
    <div className="flex min-w-0 items-center gap-2.5">
      {icon && <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600">{renderIcon(icon, "h-4 w-4")}</span>}
      <div className="min-w-0">
        <h3 className={cn("truncate text-sm font-semibold leading-5 text-zinc-900", className)} {...rest}>
          {children}
        </h3>
        {hint && <p className="truncate text-xs leading-4 text-zinc-500">{hint}</p>}
      </div>
    </div>
  );
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 py-4", className)} {...rest} />;
}
