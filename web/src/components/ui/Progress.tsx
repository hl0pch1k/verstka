import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export type ProgressTone = "accent" | "success" | "warn" | "error" | "neutral";

export interface ProgressProps {
  /** Fraction 0..1 (values outside the range are clamped). */
  value: number;
  tone?: ProgressTone;
  /** Track height: xs = 2px, sm = 4px, md = 8px. */
  size?: "xs" | "sm" | "md";
  /** A 30% segment sweeping across, for work without a known fraction (static under reduced motion). */
  indeterminate?: boolean;
  /** Text above the bar (left). */
  label?: ReactNode;
  /** Show the percentage above the bar (right). */
  showValue?: boolean;
  /** Square ends — for bars glued to a container edge. */
  flat?: boolean;
  /** Offsets the indeterminate sweep, so several bars in a column never move in lockstep. */
  delayMs?: number;
  className?: string;
}

const FILL: Record<ProgressTone, string> = {
  accent: "bg-accent",
  success: "bg-emerald-500",
  warn: "bg-amber-500",
  error: "bg-red-500",
  neutral: "bg-zinc-500",
};

const HEIGHT = { xs: "h-0.5", sm: "h-1", md: "h-2" } as const;

export function Progress({ value, tone = "accent", size = "sm", indeterminate = false, label, showValue = false, flat = false, delayMs = 0, className }: ProgressProps) {
  const frac = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  const pct = Math.round(frac * 100);
  return (
    <div className={cn("w-full", className)}>
      {(label || showValue) && (
        <div className="mb-2 flex items-center justify-between gap-3 text-caption">
          <span className="min-w-0 truncate text-zinc-700">{label}</span>
          {showValue && <span className="shrink-0 font-semibold tabular-nums text-zinc-700">{pct}%</span>}
        </div>
      )}
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : pct}
        aria-busy={indeterminate || undefined}
        className={cn("relative w-full overflow-hidden bg-zinc-100", HEIGHT[size], !flat && "rounded-full")}
      >
        {indeterminate ? (
          <div
            className={cn("absolute inset-y-0 left-0 w-[30%] animate-sweep motion-reduce:animate-none", FILL[tone], !flat && "rounded-full")}
            style={delayMs ? { animationDelay: `${delayMs}ms` } : undefined}
          />
        ) : (
          <div className={cn("h-full transition-[width] duration-500 ease-out", FILL[tone], !flat && "rounded-full")} style={{ width: `${pct}%` }} />
        )}
      </div>
    </div>
  );
}
