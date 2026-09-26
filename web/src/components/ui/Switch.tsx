// The VK switch: a track with a knob that springs across, an optional label and a count badge. The whole pill is one
// button (role="switch"), so the label is part of the click target. `SwitchTrack` is the bare track and knob for a
// caller that lays out its own label (the create screen's settings).
import { forwardRef, useId, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "../../lib/utils";
import { CountUp } from "./CountUp";

export type SwitchTone = "error" | "warn" | "neutral";
export type SwitchSize = "sm" | "md";

export interface SwitchProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange" | "children"> {
  checked: boolean;
  onChange(next: boolean): void;
  label?: ReactNode;
  /** Keeps only the track and the badge (the label stays for screen readers and in the tooltip). */
  hideLabel?: boolean;
  /** The badge beside the label; 0 or null hides it. */
  count?: number | null;
  tone?: SwitchTone;
  /** What the count means, for screen readers («3 замечания»); the number alone by default. */
  countLabel?: string;
  /** sm: a 36×20 track (dense headers), md: 40×24. */
  size?: SwitchSize;
}

const TRACK: Record<SwitchSize, { track: string; knob: string }> = {
  sm: { track: "h-5 w-9", knob: "h-4 w-4" },
  md: { track: "h-6 w-10", knob: "h-5 w-5" },
};

const BADGE: Record<SwitchTone, string> = {
  error: "bg-red-50 text-red-600",
  warn: "bg-amber-50 text-amber-700",
  neutral: "bg-zinc-100 text-zinc-600",
};

/** The track and the knob. The knob springs 16px (250ms, a slight overshoot) and, while pressed, stretches toward the
 *  side it is about to travel to; the track's colour follows in 200ms. Put it inside an element with `group`. */
export function SwitchTrack({ checked, size = "sm", className }: { checked: boolean; size?: SwitchSize; className?: string }) {
  const s = TRACK[size];
  return (
    <span
      aria-hidden
      className={cn(
        "relative inline-block shrink-0 rounded-full transition-[background-color] duration-200",
        s.track,
        checked ? "bg-accent" : "bg-zinc-300",
        className,
      )}
    >
      <span
        className={cn(
          "absolute left-0.5 top-0.5 rounded-full bg-white shadow-knob transition-transform duration-250 ease-spring group-active:scale-x-110 group-active:duration-100",
          s.knob,
          checked ? "origin-right translate-x-4" : "origin-left translate-x-0",
        )}
      />
    </span>
  );
}

/** The count pops in when it appears and rolls to a new value (400ms). */
function Count({ value, tone }: { value: number; tone: SwitchTone }) {
  return (
    <span aria-hidden className={cn("inline-flex h-5 min-w-5 animate-pop items-center justify-center rounded-full px-1 text-caption font-semibold transition-colors duration-150", BADGE[tone])}>
      <CountUp value={value} ms={400} />
    </span>
  );
}

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  { checked, onChange, label, hideLabel = false, count = null, countLabel, tone = "neutral", size = "sm", disabled, className, title, onClick, type = "button", ...rest },
  ref,
) {
  const descId = useId();
  const hasCount = typeof count === "number" && count > 0;
  const labelText = typeof label === "string" ? label : undefined;
  return (
    <button
      ref={ref}
      type={type}
      role="switch"
      aria-checked={checked}
      aria-describedby={hasCount ? descId : undefined}
      disabled={disabled}
      title={title ?? (hideLabel ? labelText : undefined)}
      onClick={(e) => {
        onClick?.(e);
        if (!e.defaultPrevented) onChange(!checked);
      }}
      className={cn(
        "group inline-flex h-8 shrink-0 cursor-pointer select-none items-center gap-1.5 whitespace-nowrap rounded-full pl-1 transition-[background-color] duration-150 hover:bg-zinc-100 active:bg-zinc-200/70 disabled:pointer-events-none disabled:opacity-40",
        // the badge is a pill of its own: it sits 6px from the pill's end, the label 12px
        hasCount ? "pr-1.5" : label && !hideLabel ? "pr-3" : "pr-1",
        className,
      )}
      {...rest}
    >
      <SwitchTrack checked={checked} size={size} />
      {label &&
        (hideLabel ? (
          <span className="sr-only">{label}</span>
        ) : (
          <span className={cn("text-footnote font-semibold transition-colors duration-150", checked ? "text-zinc-900" : "text-zinc-700")}>{label}</span>
        ))}
      {hasCount && (
        <>
          <Count value={count} tone={tone} />
          <span id={descId} className="sr-only">
            {countLabel ?? String(count)}
          </span>
        </>
      )}
    </button>
  );
});
