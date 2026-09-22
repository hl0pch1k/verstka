import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

export type BadgeTone = "neutral" | "accent" | "success" | "warn" | "error" | "info";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  size?: "sm" | "md";
  icon?: IconProp;
  /** Small coloured dot before the text (status badges). */
  dot?: boolean;
  /** Filled variant for counters that must stand out. */
  solid?: boolean;
}

const SOFT: Record<BadgeTone, string> = {
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-200",
  accent: "bg-accent-50 text-accent-700 ring-accent-100",
  success: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  warn: "bg-amber-50 text-amber-800 ring-amber-100",
  error: "bg-red-50 text-red-700 ring-red-100",
  info: "bg-sky-50 text-sky-700 ring-sky-100",
};

const SOLID: Record<BadgeTone, string> = {
  neutral: "bg-zinc-700 text-white ring-transparent",
  accent: "bg-accent text-white ring-transparent",
  success: "bg-emerald-600 text-white ring-transparent",
  warn: "bg-amber-500 text-white ring-transparent",
  error: "bg-red-600 text-white ring-transparent",
  info: "bg-sky-600 text-white ring-transparent",
};

const DOT: Record<BadgeTone, string> = {
  neutral: "bg-zinc-400",
  accent: "bg-accent",
  success: "bg-emerald-500",
  warn: "bg-amber-500",
  error: "bg-red-500",
  info: "bg-sky-500",
};

export function Badge({ tone = "neutral", size = "md", icon, dot = false, solid = false, className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-full font-medium ring-1 ring-inset",
        size === "sm" ? "h-[18px] gap-1 px-1.5 text-[11px]" : "h-[22px] gap-1.5 px-2 text-xs",
        solid ? SOLID[tone] : SOFT[tone],
        className,
      )}
      {...rest}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", solid ? "bg-white/90" : DOT[tone])} aria-hidden />}
      {renderIcon(icon, "h-3 w-3")}
      {children}
    </span>
  );
}
