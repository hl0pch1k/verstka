import type { ReactNode } from "react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

export interface EmptyStateProps {
  /** Lucide component (`icon={Inbox}`) or element. */
  icon?: IconProp;
  title: string;
  /** Optional, ≤ 40 characters: how to recover. */
  hint?: ReactNode;
  /** Usually a <Button/>. */
  action?: ReactNode;
  /** Tighter paddings for use inside small cards and side columns. */
  compact?: boolean;
  className?: string;
}

export function EmptyState({ icon, title, hint, action, compact = false, className }: EmptyStateProps) {
  return (
    <div className={cn("flex w-full flex-col items-center justify-center text-center animate-fade-in", compact ? "px-4 py-6" : "px-6 py-12", className)}>
      {icon && <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-100 text-zinc-500">{renderIcon(icon, "h-6 w-6")}</div>}
      <h4 className="text-title3 font-semibold text-zinc-900">{title}</h4>
      {hint && <p className="mt-1 max-w-md text-footnote text-zinc-500">{hint}</p>}
      {action && <div className="mt-6 flex items-center gap-2">{action}</div>}
    </div>
  );
}
