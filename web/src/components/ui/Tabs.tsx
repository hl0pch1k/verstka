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
  /** "underline" — page-level tab bar; "pills" — compact segmented switch inside cards. */
  variant?: "underline" | "pills";
  className?: string;
}

export function Tabs<K extends string = string>({ items, value, onChange, variant = "underline", className }: TabsProps<K>) {
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const enabled = items.filter((i) => !i.disabled);
    const idx = enabled.findIndex((i) => i.key === value);
    if (idx < 0 || enabled.length < 2) return;
    e.preventDefault();
    const next = enabled[(idx + (e.key === "ArrowRight" ? 1 : enabled.length - 1)) % enabled.length];
    onChange(next.key);
    e.currentTarget.querySelector<HTMLButtonElement>(`[data-tab="${next.key}"]`)?.focus();
  };

  const pills = variant === "pills";
  return (
    <div
      role="tablist"
      onKeyDown={onKey}
      className={cn(pills ? "inline-flex items-center gap-0.5 rounded-lg bg-zinc-100 p-0.5" : "flex items-stretch gap-1 border-b border-zinc-200", className)}
    >
      {items.map((item) => {
        const active = item.key === value;
        const hasBadge = item.badge !== undefined && item.badge !== null && item.badge !== "";
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            data-tab={item.key}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.key)}
            className={cn(
              "relative inline-flex items-center gap-2 whitespace-nowrap font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-40",
              pills
                ? cn("h-7 rounded-md px-2.5 text-[13px]", active ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-600 hover:text-zinc-900")
                : cn("-mb-px h-11 rounded-t-md border-b-2 px-3 text-sm", active ? "border-accent text-accent-700" : "border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-800"),
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
