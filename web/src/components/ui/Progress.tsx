import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export type ProgressTone = "accent" | "success" | "warn" | "error" | "neutral";

export interface ProgressProps {
  /** Fraction 0..1 (values outside the range are clamped). */
  value: number;
  tone?: ProgressTone;
  /** Track height: xs = 2px, sm = 4px, md = 8px. */
  size?: "xs" | "sm" | "md";
  /** Animated stripe for work without a known fraction. */
  indeterminate?: boolean;
  /** Text above the bar (left). */
  label?: ReactNode;
  /** Show the percentage above the bar (right). */
  showValue?: boolean;
  /** Square ends — for bars glued to a container edge. */
  flat?: boolean;
  className?: string;
}

const FILL: Record<ProgressTone, string> = {
  accent: "bg-accent",
  success: "bg-emerald-500",
  warn: "bg-amber-500",
  error: "bg-red-500",
  neutral: "bg-zinc-500",
};

const HEIGHT = { xs: "h-[3px]", sm: "h-1.5", md: "h-2" } as const;

export function Progress({ value, tone = "accent", size = "sm", indeterminate = false, label, showValue = false, flat = false, className }: ProgressProps) {
  const frac = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  const pct = Math.round(frac * 100);
  return (
    <div className={cn("w-full", className)}>
      {(label || showValue) && (
        <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
          <span className="min-w-0 truncate text-zinc-600">{label}</span>
          {showValue && <span className="shrink-0 font-medium tabular-nums text-zinc-700">{pct}%</span>}
        </div>
      )}
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : pct}
        className={cn("relative w-full overflow-hidden bg-zinc-200/70", HEIGHT[size], !flat && "rounded-full")}
      >
        {indeterminate ? (
          <div
            className={cn("absolute inset-0 animate-shimmer opacity-80", !flat && "rounded-full")}
            style={{ backgroundImage: "linear-gradient(90deg, transparent 0%, #0077FF 50%, transparent 100%)", backgroundSize: "200% 100%" }}
          />
        ) : (
          <div className={cn("h-full transition-[width] duration-500 ease-out", FILL[tone], !flat && "rounded-full")} style={{ width: `${pct}%` }} />
        )}
      </div>
    </div>
  );
}
