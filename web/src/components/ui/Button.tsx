import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

// VK button family: primary (filled blue), tonal (light blue — VKUI «secondary»), secondary (neutral grey),
// ghost (text), danger, and inverse for the dark header.
export type ButtonVariant = "primary" | "tonal" | "secondary" | "ghost" | "danger" | "inverse";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner instead of the icon and disables the button. */
  loading?: boolean;
  /** Leading icon: lucide component or element. */
  icon?: IconProp;
  /** Trailing icon. */
  iconRight?: IconProp;
  /** Stretch to the container width. */
  block?: boolean;
}

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:bg-accent-600 active:bg-accent-700 focus-visible:ring-accent/40 shadow-[0_1px_0_rgba(255,255,255,0.12)_inset]",
  tonal: "bg-accent-50 text-accent-700 hover:bg-accent-100 active:bg-accent-200/70 focus-visible:ring-accent/30",
  secondary: "bg-zinc-100 text-zinc-900 hover:bg-zinc-200/80 active:bg-zinc-200 focus-visible:ring-accent/30",
  ghost: "bg-transparent text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 active:bg-zinc-200/70 focus-visible:ring-accent/30",
  danger: "bg-red-600 text-white hover:bg-red-700 active:bg-red-800 focus-visible:ring-red-500/40",
  inverse: "bg-white/[0.08] text-white hover:bg-white/[0.14] active:bg-white/20 focus-visible:ring-white/40",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-[10px] px-3 text-[13px]",
  md: "h-9 gap-2 rounded-[10px] px-3.5 text-sm",
  lg: "h-11 gap-2 rounded-xl px-5 text-[15px]",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, icon, iconRight, block = false, disabled, className, children, type = "button", ...rest },
  ref,
) {
  const iconCls = size === "sm" ? "h-4 w-4 shrink-0" : size === "lg" ? "h-5 w-5 shrink-0" : "h-4 w-4 shrink-0";
  const iconOnly = children === undefined || children === null || children === false;
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex cursor-pointer select-none items-center justify-center whitespace-nowrap font-semibold transition-[background-color,color,box-shadow,transform] duration-150 active:scale-[0.98]",
        "focus:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-45",
        VARIANTS[variant],
        SIZES[size],
        iconOnly && (size === "sm" ? "w-8 px-0" : size === "lg" ? "w-11 px-0" : "w-9 px-0"),
        block && "w-full",
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className={cn(iconCls, "animate-spin")} aria-hidden /> : renderIcon(icon, iconCls)}
      {children}
      {!loading && renderIcon(iconRight, iconCls)}
    </button>
  );
});
