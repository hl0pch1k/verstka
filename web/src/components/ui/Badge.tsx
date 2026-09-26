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
  /** "pill" (default) — rounded-full; "rect" — 8px corners. */
  shape?: "pill" | "rect";
}

// Flat VK chips: tinted fill, no outline. Info is VK blue (there is no second blue).
const SOFT: Record<BadgeTone, string> = {
  neutral: "bg-zinc-100 text-zinc-700",
  accent: "bg-accent-50 text-accent-700",
  success: "bg-emerald-50 text-emerald-700",
  warn: "bg-amber-50 text-amber-700",
  error: "bg-red-50 text-red-600",
  info: "bg-accent-50 text-accent-700",
};

const SOLID: Record<BadgeTone, string> = {
  neutral: "bg-zinc-800 text-white",
  accent: "bg-accent-fill text-white",
  success: "bg-emerald-600 text-white",
  warn: "bg-amber-500 text-amber-950",
  error: "bg-red-600 text-white",
  info: "bg-accent-fill text-white",
};

const DOT: Record<BadgeTone, string> = {
  neutral: "bg-zinc-400",
  accent: "bg-accent",
  success: "bg-emerald-500",
  warn: "bg-amber-500",
  error: "bg-red-500",
  info: "bg-accent",
};

export function Badge({ tone = "neutral", size = "md", icon, dot = false, solid = false, shape = "pill", className, children, ...rest }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 whitespace-nowrap px-2 text-caption font-semibold",
        shape === "rect" ? "rounded-lg" : "rounded-full",
        size === "sm" ? "h-5" : "h-6",
        solid ? SOLID[tone] : SOFT[tone],
        className,
      )}
      {...rest}
    >
      {dot && <span className={cn("h-2 w-2 rounded-full", solid ? "bg-white/90" : DOT[tone])} aria-hidden />}
      {renderIcon(icon, "h-3.5 w-3.5")}
      {children}
    </span>
  );
}
