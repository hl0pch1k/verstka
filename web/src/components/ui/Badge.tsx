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

// Flat VK chips: tinted fill, no outline.
const SOFT: Record<BadgeTone, string> = {
  neutral: "bg-zinc-100 text-zinc-700",
  accent: "bg-accent-50 text-accent-700",
  success: "bg-emerald-50 text-emerald-700",
  warn: "bg-amber-50 text-amber-800",
  error: "bg-red-50 text-red-700",
  info: "bg-sky-50 text-sky-700",
};

const SOLID: Record<BadgeTone, string> = {
  neutral: "bg-zinc-800 text-white",
  accent: "bg-accent text-white",
  success: "bg-emerald-600 text-white",
  warn: "bg-amber-500 text-white",
  error: "bg-red-600 text-white",
  info: "bg-sky-600 text-white",
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
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-full font-semibold",
        size === "sm" ? "h-5 gap-1 px-1.5 text-[11px]" : "h-6 gap-1.5 px-2.5 text-xs",
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
