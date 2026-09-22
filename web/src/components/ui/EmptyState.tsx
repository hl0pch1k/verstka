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
            "flex items-center justify-center rounded-2xl border border-zinc-200 bg-gradient-to-b from-white to-zinc-50 text-zinc-500 shadow-card",
            compact ? "mb-3 h-10 w-10" : "mb-4 h-12 w-12",
          )}
        >
          {renderIcon(icon, compact ? "h-5 w-5" : "h-6 w-6", 1.75)}
        </div>
      )}
      <h4 className="text-sm font-semibold text-zinc-900">{title}</h4>
      {hint && <p className="mt-1 max-w-sm text-[13px] leading-5 text-zinc-500">{hint}</p>}
      {action && <div className="mt-4 flex items-center gap-2">{action}</div>}
    </div>
  );
}
