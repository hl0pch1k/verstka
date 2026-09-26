import { MOTION, useCountUp } from "../../lib/motion";
import { cn } from "../../lib/utils";

export interface CountUpProps {
  value: number | null;
  /** Duration of one move (default 600, the data token; counts in chips and badges use 400). */
  ms?: number;
  /** Wait before the first move (only with `appear`). */
  delay?: number;
  /** Count up from 0 on mount too (a summary that draws in). Without it the first value shows as is and only later
   *  changes roll. */
  appear?: boolean;
  format?(n: number): string;
  className?: string;
}

const round = (n: number) => String(Math.round(n));

/** A number in text that rolls from the value on screen to the new one (tabular figures, so nothing shifts). Screen
 *  readers get the final value only. */
export function CountUp({ value, ms = MOTION.data, delay = 0, appear = false, format = round, className }: CountUpProps) {
  const shown = useCountUp(value, { ms, delay, from: appear ? 0 : value ?? 0 });
  return (
    <span className={cn("tabular-nums", className)}>
      <span className="sr-only">{value === null ? "—" : format(value)}</span>
      <span aria-hidden>{shown === null ? "—" : format(shown)}</span>
    </span>
  );
}
