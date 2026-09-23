import type { ReactNode } from "react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

export interface EmptyStateProps {
  /** Lucide component (`icon={Inbox}`) or element. */
  icon?: IconProp;
  title: string;
  hint?: ReactNode;
  /** Usually a <Button/>. */
  action?: ReactNode;
  /** Tighter paddings for use inside small cards and side columns. */
  compact?: boolean;
  className?: string;
}

export function EmptyState({ icon, title, hint, action, compact = false, className }: EmptyStateProps) {
  return (
    <div className={cn("flex w-full flex-col items-center justify-center text-center animate-fade-in", compact ? "px-4 py-6" : "px-6 py-14", className)}>
      {icon && (
        <div
          className={cn(
            "flex items-center justify-center rounded-2xl bg-accent-50 text-accent",
            compact ? "mb-3 h-11 w-11" : "mb-5 h-14 w-14",
          )}
        >
          {renderIcon(icon, compact ? "h-5 w-5" : "h-7 w-7", 1.75)}
        </div>
      )}
      <h4 className={cn("font-semibold text-zinc-900", compact ? "text-[15px]" : "text-lg")}>{title}</h4>
      {hint && <p className={cn("mt-1.5 max-w-md text-zinc-500", compact ? "text-[13px] leading-5" : "text-sm leading-6")}>{hint}</p>}
      {action && <div className="mt-5 flex items-center gap-2">{action}</div>}
    </div>
  );
}
