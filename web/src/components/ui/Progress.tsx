import { useEffect, useState, type ReactNode } from "react";
import { prefersReducedMotion } from "../../lib/motion";
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
  /** Fill from empty on mount (a number: after that many ms — the stagger of a column of bars). */
  appear?: boolean | number;
  className?: string;
}

/** On mount with `appear`: false for the first frames (and the delay), then true — the fill has an empty start. */
function useAppear(appear: boolean | number | undefined): boolean {
  const [on, setOn] = useState(() => appear === undefined || appear === false || prefersReducedMotion());
  useEffect(() => {
    if (on) return;
    const delay = typeof appear === "number" ? appear : 0;
    let t = 0;
    let r2 = 0;
    const r1 = requestAnimationFrame(() => {
      r2 = requestAnimationFrame(() => {
        t = window.setTimeout(() => setOn(true), delay);
      });
    });
    return () => {
      cancelAnimationFrame(r1);
      cancelAnimationFrame(r2);
      window.clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return on;
}

const FILL: Record<ProgressTone, string> = {
  accent: "bg-accent",
  success: "bg-emerald-500",
  warn: "bg-amber-500",
  error: "bg-red-500",
  neutral: "bg-zinc-500",
};

const HEIGHT = { xs: "h-0.5", sm: "h-1", md: "h-2" } as const;

// The fill is full width and slides in by transform (never a width animation), 600 ms on the arrival curve.
export function Progress({ value, tone = "accent", size = "sm", indeterminate = false, label, showValue = false, flat = false, delayMs = 0, appear, className }: ProgressProps) {
  const frac = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  const pct = Math.round(frac * 100);
  const shown = useAppear(appear);
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
          <div
            className={cn("h-full w-full transition-[transform,background-color] duration-600 ease-out", FILL[tone], !flat && "rounded-full")}
            style={{ transform: `translateX(${(shown ? frac * 100 : 0) - 100}%)` }}
          />
        )}
      </div>
    </div>
  );
}
