import { forwardRef, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";
import { renderIcon, type IconProp } from "./icon";

// VK button family: primary (filled blue, one per screen), tonal (light blue), secondary (neutral grey),
// white (on the canvas or a tinted notice) and ghost (text). Sizes 32 / 40 / 48. Callers pass layout classes only;
// another look is another variant, never a className override. Focus uses the global 2px outline.
export type ButtonVariant = "primary" | "tonal" | "secondary" | "white" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";
export type ButtonShape = "rect" | "circle";

export interface ButtonLook {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** "circle" — a round button (icon-only controls: close, arrows). */
  shape?: ButtonShape;
  /** Stretch to the container width. */
  block?: boolean;
  /** Leading icon: lucide component or element. */
  icon?: IconProp;
  /** Trailing icon. */
  iconRight?: IconProp;
  /** Shows a spinner instead of the icon and disables the button. */
  loading?: boolean;
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, ButtonLook {}

const BASE =
  "inline-flex shrink-0 cursor-pointer select-none items-center justify-center gap-2 whitespace-nowrap font-semibold transition-[background-color,color,box-shadow,transform] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-40 aria-disabled:pointer-events-none aria-disabled:opacity-40";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent-fill text-white hover:bg-accent-600 active:bg-accent-700",
  // pressed (a toggle that is on): a deeper tint and darker text only — a blue ring would read as keyboard focus
  tonal: "bg-accent-50 text-accent-700 hover:bg-accent-100 active:bg-accent-200 aria-pressed:bg-accent-100 aria-pressed:text-accent-800 aria-pressed:hover:bg-accent-200",
  secondary: "bg-zinc-100 text-zinc-900 hover:bg-zinc-200/70 active:bg-zinc-200",
  white: "bg-white text-zinc-900 shadow-card hover:bg-zinc-50 active:bg-zinc-100",
  ghost: "text-zinc-700 hover:bg-zinc-900/[0.06] hover:text-zinc-900 active:bg-zinc-900/10 aria-expanded:bg-zinc-900/[0.06] aria-expanded:text-zinc-900",
};

const SIZES: Record<ButtonSize, { box: string; iconOnly: string; icon: string; iconOnlyIcon: string }> = {
  sm: { box: "h-8 rounded-lg px-3 text-footnote", iconOnly: "w-8 px-0", icon: "h-4 w-4", iconOnlyIcon: "h-4 w-4" },
  md: { box: "h-10 rounded-xl px-4 text-body", iconOnly: "w-10 px-0", icon: "h-4 w-4", iconOnlyIcon: "h-5 w-5" },
  lg: { box: "h-12 rounded-xl px-6 text-body", iconOnly: "w-12 px-0", icon: "h-5 w-5", iconOnlyIcon: "h-5 w-5" },
};

/** The class string of a button look — for elements that must stay something else (a <label>, a router link). */
export function buttonClass({ variant = "secondary", size = "md", shape = "rect", block = false, iconOnly = false }: { variant?: ButtonVariant; size?: ButtonSize; shape?: ButtonShape; block?: boolean; iconOnly?: boolean } = {}): string {
  const s = SIZES[size];
  return cn(BASE, VARIANTS[variant], s.box, iconOnly && s.iconOnly, shape === "circle" && "rounded-full", block && "w-full");
}

const isEmpty = (children: ReactNode) => children === undefined || children === null || children === false || children === "";

function Content({ size, loading, icon, iconRight, iconOnly, children }: { size: ButtonSize; loading: boolean; icon?: IconProp; iconRight?: IconProp; iconOnly: boolean; children: ReactNode }) {
  const iconCls = cn("shrink-0", iconOnly ? SIZES[size].iconOnlyIcon : SIZES[size].icon);
  return (
    <>
      {loading ? <Loader2 className={cn(iconCls, "animate-spin")} aria-hidden /> : renderIcon(icon, iconCls)}
      {children}
      {!loading && renderIcon(iconRight, iconCls)}
    </>
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", shape = "rect", loading = false, icon, iconRight, block = false, disabled, className, children, type = "button", ...rest },
  ref,
) {
  const iconOnly = isEmpty(children);
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(buttonClass({ variant, size, shape, block, iconOnly }), className)}
      {...rest}
    >
      <Content size={size} loading={loading} icon={icon} iconRight={iconRight} iconOnly={iconOnly}>
        {children}
      </Content>
    </button>
  );
});

export interface LinkButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement>, ButtonLook {
  href: string;
}

/** A link that looks like a Button (downloads, files that open in a new tab). */
export function LinkButton({ variant = "secondary", size = "md", shape = "rect", loading = false, icon, iconRight, block = false, className, children, ...rest }: LinkButtonProps) {
  const iconOnly = isEmpty(children);
  return (
    <a className={cn(buttonClass({ variant, size, shape, block, iconOnly }), className)} aria-busy={loading || undefined} {...rest}>
      <Content size={size} loading={loading} icon={icon} iconRight={iconRight} iconOnly={iconOnly}>
        {children}
      </Content>
    </a>
  );
}
