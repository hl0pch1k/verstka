// Vertical filmstrip of slide thumbnails for the active variant.
import { useEffect, useRef, useState } from "react";
import { cn } from "../lib/utils";
import type { Issue, Variant } from "../types";
import { issuesSummary, withRev, worstSeverity } from "./VariantsHelpers";

interface Props {
  variant: Variant;
  rev: string;
  total: number;
  selected: number; // 1-based
  aspect: number;
  issueMap: Map<number, Issue[]>;
  onSelect(n: number): void;
}

export function VariantsFilmstrip({ variant, rev, total, selected, aspect, issueMap, onSelect }: Props) {
  const selectedRef = useRef<HTMLButtonElement>(null);
  const [broken, setBroken] = useState<Record<string, true>>({});

  // Keep the selected thumbnail in view while the user walks the deck with ←/→.
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selected, variant.strategy]);

  return (
    <ol className="space-y-1" aria-label="Слайды варианта">
      {Array.from({ length: total }, (_, idx) => {
        const n = idx + 1;
        const raw = variant.slides[idx];
        const url = raw ? withRev(raw, rev) : null;
        const issues = issueMap.get(n);
        const worst = worstSeverity(issues);
        const active = n === selected;
        const headline = variant.outline?.slides[idx]?.headline ?? "";
        return (
          <li key={n}>
            <button
              ref={active ? selectedRef : undefined}
              type="button"
              onClick={() => onSelect(n)}
              aria-current={active || undefined}
              aria-label={`Слайд ${n}${headline ? `: ${headline}` : ""}`}
              title={headline || undefined}
              className={cn(
                "group flex w-full items-start gap-1.5 rounded-lg p-1 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                active ? "bg-accent-50" : "hover:bg-zinc-100",
              )}
            >
              <span className={cn("w-4 shrink-0 pt-0.5 text-right text-[11px] font-medium tabular-nums", active ? "text-accent-700" : "text-zinc-400")}>{n}</span>
              <span
                className={cn(
                  "relative block min-w-0 flex-1 overflow-hidden rounded-md bg-white transition-shadow",
                  active ? "ring-2 ring-accent" : "ring-1 ring-zinc-200 group-hover:ring-zinc-300",
                )}
                style={{ aspectRatio: String(aspect) }}
              >
                {url && !broken[url] ? (
                  <img
                    src={url}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    draggable={false}
                    onError={() => setBroken((m) => ({ ...m, [url]: true }))}
                    className="block h-full w-full object-cover"
                  />
                ) : (
                  <span className="flex h-full w-full items-center bg-zinc-50 p-1.5 text-[9px] font-medium leading-[11px] text-zinc-500">
                    <span className="line-clamp-3">{headline || `Слайд ${n}`}</span>
                  </span>
                )}
                {(worst === "error" || worst === "warn") && (
                  <span
                    title={issuesSummary(issues)}
                    className={cn("absolute right-1 top-1 h-2.5 w-2.5 rounded-full ring-2 ring-white", worst === "error" ? "bg-red-500" : "bg-amber-400")}
                  />
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
