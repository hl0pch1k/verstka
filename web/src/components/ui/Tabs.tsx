import type { KeyboardEvent } from "react";
import { cn } from "../../lib/utils";
import { Badge, type BadgeTone } from "./Badge";
import { renderIcon, type IconProp } from "./icon";

export interface TabItem<K extends string = string> {
  key: K;
  label: string;
  icon?: IconProp;
  /** Counter shown after the label; hidden when undefined / null / "". */
  badge?: number | string | null;
  badgeTone?: BadgeTone;
  disabled?: boolean;
}

export interface TabsProps<K extends string = string> {
  items: TabItem<K>[];
  value: K;
  onChange: (key: K) => void;
  /** "underline" — section-level tab bar (the host draws the hairline under it); "pills" — VK segmented control. */
  variant?: "underline" | "pills";
  "aria-label"?: string;
  /** Gives every tab an id, `tabId(idPrefix, key)`, so a panel can point back with aria-labelledby. */
  idPrefix?: string;
  /** The id of the panel the tabs switch (aria-controls on every tab). */
  panelId?: string;
  className?: string;
}

/** The id of a tab rendered with `idPrefix`: `<div role="tabpanel" aria-labelledby={tabId("drawer", key)}>`. */
export const tabId = (prefix: string, key: string) => `${prefix}-tab-${key}`;

// the underline tab's keyboard ring: a 40px pill around the label (8px on each side), clear of the 2px underline,
// instead of an outline glued to the text from the bar's top edge to its bottom
const UNDERLINE_RING =
  "focus-visible:outline-none focus-visible:before:pointer-events-none focus-visible:before:absolute focus-visible:before:-inset-x-2 focus-visible:before:inset-y-2 focus-visible:before:rounded-xl focus-visible:before:outline focus-visible:before:outline-2 focus-visible:before:outline-accent";

export function Tabs<K extends string = string>({ items, value, onChange, variant = "underline", className, "aria-label": ariaLabel, idPrefix, panelId }: TabsProps<K>) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    const enabled = items.filter((i) => !i.disabled);
    const idx = enabled.findIndex((i) => i.key === value);
    if (idx < 0 || enabled.length < 2) return;
    e.preventDefault();
    e.stopPropagation();
    const next =
      e.key === "Home" ? enabled[0]
      : e.key === "End" ? enabled[enabled.length - 1]
      : enabled[(idx + (e.key === "ArrowRight" ? 1 : enabled.length - 1)) % enabled.length];
    onChange(next.key);
    e.currentTarget.querySelector<HTMLButtonElement>(`[data-tab="${next.key}"]`)?.focus();
  };

  const pills = variant === "pills";
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={onKey}
      className={cn(pills ? "inline-flex h-10 shrink-0 items-center gap-1 rounded-xl bg-zinc-100 p-1" : "flex h-full items-stretch gap-6", className)}
    >
      {items.map((item) => {
        const active = item.key === value;
        const hasBadge = item.badge !== undefined && item.badge !== null && item.badge !== "";
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            id={idPrefix ? tabId(idPrefix, item.key) : undefined}
            aria-controls={panelId}
            data-tab={item.key}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.key)}
            className={cn(
              "relative inline-flex cursor-pointer items-center gap-2 whitespace-nowrap font-semibold transition-[background-color,color,box-shadow,border-color] duration-150 disabled:cursor-not-allowed disabled:opacity-40",
              pills
                ? cn("h-8 rounded-lg px-3 text-footnote", active ? "bg-white text-zinc-900 shadow-card" : "text-zinc-600 hover:text-zinc-900")
                : cn("-mb-px h-full border-b-2 text-body", UNDERLINE_RING, active ? "border-accent text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-900"),
            )}
          >
            {renderIcon(item.icon, "h-4 w-4 shrink-0")}
            {item.label}
            {hasBadge && (
              <Badge tone={item.badgeTone ?? (active ? "accent" : "neutral")} size="sm">
                {item.badge}
              </Badge>
            )}
          </button>
        );
      })}
    </div>
  );
}
