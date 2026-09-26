import { isValidElement, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "../../lib/utils";

export interface SegmentedItem<K extends string> {
  key: K;
  label: ReactNode;
  /** After the label, lighter (a score, a count); the caller may pass a coloured node. */
  meta?: ReactNode;
  title?: string;
  disabled?: boolean;
}

export interface SegmentedProps<K extends string> {
  items: SegmentedItem<K>[];
  value: K;
  onChange(k: K): void;
  ariaLabel: string;
  /** What the meta is, for screen readers: «оценка» → «Структурный, оценка 100» (without it: «Структурный, 100»). */
  metaLabel?: string;
  className?: string;
}

const hasMeta = (item: { meta?: ReactNode }) => item.meta !== undefined && item.meta !== null && item.meta !== "" && item.meta !== false;

/** The text a node shows (strings and numbers inside elements and fragments), for an accessible name. */
function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

// The VK segmented control: one choice out of a few, a white pill slides over a grey track. Keyboard: ←/→/Home/End
// move and select (the events stop here, so page-level arrow handlers — the slide keys — do not fire).
export function Segmented<K extends string>({ items, value, onChange, ariaLabel, metaLabel, className }: SegmentedProps<K>) {
  const ref = useRef<HTMLDivElement>(null);
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    e.stopPropagation();
    const enabled = items.filter((i) => !i.disabled);
    if (enabled.length === 0) return;
    const idx = Math.max(0, enabled.findIndex((i) => i.key === value));
    const next =
      e.key === "Home" ? enabled[0]
      : e.key === "End" ? enabled[enabled.length - 1]
      : enabled[(idx + (e.key === "ArrowRight" ? 1 : enabled.length - 1)) % enabled.length];
    if (next.key !== value) onChange(next.key);
    ref.current?.querySelector<HTMLButtonElement>(`[data-seg="${next.key}"]`)?.focus();
  };
  return (
    <div ref={ref} role="radiogroup" aria-label={ariaLabel} onKeyDown={onKey} className={cn("inline-flex h-10 shrink-0 items-center gap-1 rounded-xl bg-zinc-100 p-1", className)}>
      {items.map((item) => {
        const active = item.key === value;
        return (
          <button
            key={item.key}
            type="button"
            role="radio"
            data-seg={item.key}
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            disabled={item.disabled}
            title={item.title}
            // the label and the meta are two words for a screen reader («Структурный, оценка 100», not «Структурный100»)
            aria-label={hasMeta(item) ? `${textOf(item.label)}, ${metaLabel ? `${metaLabel} ` : ""}${textOf(item.meta)}` : undefined}
            onClick={() => !active && onChange(item.key)}
            className={cn(
              "inline-flex h-8 cursor-pointer items-center whitespace-nowrap rounded-lg px-3 text-footnote font-semibold transition-[background-color,color,box-shadow] duration-150 disabled:cursor-not-allowed disabled:opacity-40",
              active ? "bg-white text-zinc-900 shadow-card" : "text-zinc-600 hover:text-zinc-900",
            )}
          >
            {item.label}
            {hasMeta(item) && <span className="ml-2 font-normal tabular-nums text-zinc-500">{item.meta}</span>}
          </button>
        );
      })}
    </div>
  );
}
