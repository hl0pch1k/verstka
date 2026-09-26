import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";
import { CountUp } from "./CountUp";
import { renderIcon, type IconProp } from "./icon";

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  /** A small number after the label (hidden when null / undefined / ""). */
  count?: number | string | null;
  icon?: IconProp;
  /** "white" — on a white card (grey chip); "tinted" — on the canvas or a tinted panel (white chip). */
  surface?: "white" | "tinted";
}

// A toggle or filter chip, 32px. Selected is VK blue everywhere. As a toggle the caller sets aria-pressed; in a radio
// group, role="radio" + aria-checked.
export const Chip = forwardRef<HTMLButtonElement, ChipProps>(function Chip(
  { selected = false, count, icon, surface = "white", className, children, type = "button", ...rest },
  ref,
) {
  const hasCount = count !== undefined && count !== null && count !== "";
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "tap inline-flex h-8 shrink-0 cursor-pointer select-none items-center gap-2 whitespace-nowrap rounded-full px-3 text-footnote font-semibold disabled:pointer-events-none disabled:opacity-40",
        selected
          ? "bg-accent-50 text-accent-700 shadow-selected-inset"
          : surface === "tinted"
            ? "bg-white text-zinc-700 shadow-card hover:bg-zinc-50"
            : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200/70",
        className,
      )}
      {...rest}
    >
      {renderIcon(icon, "h-4 w-4 shrink-0")}
      {children}
      {hasCount && (
        <span className={cn("text-caption tabular-nums transition-colors", selected ? "text-accent-700" : "text-zinc-500")}>
          {typeof count === "number" ? <CountUp value={count} ms={400} /> : count}
        </span>
      )}
    </button>
  );
});
