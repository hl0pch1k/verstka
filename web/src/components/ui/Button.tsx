import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

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
  primary: "bg-accent text-white shadow-sm hover:bg-accent-600 active:bg-accent-700 focus-visible:ring-accent/40",
  secondary: "bg-white text-zinc-800 border border-zinc-200 shadow-sm hover:bg-zinc-50 hover:border-zinc-300 active:bg-zinc-100 focus-visible:ring-accent/30",
  ghost: "bg-transparent text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 active:bg-zinc-200 focus-visible:ring-accent/30",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-700 active:bg-red-800 focus-visible:ring-red-500/40",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 rounded-lg px-2.5 text-[13px]",
  md: "h-9 gap-2 rounded-lg px-3.5 text-sm",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading = false, icon, iconRight, block = false, disabled, className, children, type = "button", ...rest },
  ref,
) {
  const iconCls = size === "sm" ? "h-3.5 w-3.5 shrink-0" : "h-4 w-4 shrink-0";
  const iconOnly = children === undefined || children === null || children === false;
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex select-none items-center justify-center whitespace-nowrap font-medium transition-colors",
        "focus:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        iconOnly && (size === "sm" ? "w-8 px-0" : "w-9 px-0"),
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
