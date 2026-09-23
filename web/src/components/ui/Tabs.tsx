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
  /** "underline" — section-level tab bar; "pills" — VK segmented control. */
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
      className={cn(pills ? "inline-flex items-center gap-0.5 rounded-xl bg-zinc-200/60 p-[3px]" : "flex items-stretch gap-6 border-b border-zinc-200", className)}
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
              "relative inline-flex cursor-pointer items-center gap-2 whitespace-nowrap font-semibold transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-40",
              pills
                ? cn("h-8 rounded-[9px] px-3 text-[13px]", active ? "bg-white text-zinc-900 shadow-[0_1px_3px_rgba(0,16,61,0.12)]" : "text-zinc-600 hover:text-zinc-900")
                : cn("-mb-px h-11 border-b-2 text-sm", active ? "border-accent text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-800"),
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
