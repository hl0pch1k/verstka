// Horizontal row of slide thumbnails under the slide — the way PowerPoint and Google Slides show a deck.
import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/utils";
import type { Issue, Variant } from "../../types";
import { issuesSummary, withRev, worstSeverity } from "../VariantsHelpers";

export function SlideStrip({ variant, rev, total, selected, aspect, issueMap, onSelect }: {
  variant: Variant;
  rev: string;
  total: number;
  selected: number; // 1-based
  aspect: number;
  issueMap: Map<number, Issue[]>;
  onSelect(n: number): void;
}) {
  const selectedRef = useRef<HTMLButtonElement>(null);
  const [broken, setBroken] = useState<Record<string, true>>({});
  // scroll the strip only — scrollIntoView would also scroll the page and hide the title and the download button
  useEffect(() => {
    const el = selectedRef.current;
    const list = el?.closest("ol");
    if (!el || !list) return;
    const left = el.offsetLeft; // the list is the offsetParent (relative): content coordinates, scroll ignored
    if (left < list.scrollLeft || left + el.offsetWidth > list.scrollLeft + list.clientWidth) {
      list.scrollTo({ left: Math.max(0, left - (list.clientWidth - el.offsetWidth) / 2), behavior: "smooth" });
    }
  }, [selected, variant.strategy]);

  return (
    <ol className="scroll-thin relative flex gap-3 overflow-x-auto px-1 pb-2 pt-1" aria-label="Слайды">
      {Array.from({ length: total }, (_, idx) => {
        const n = idx + 1;
        const raw = variant.slides[idx];
        const url = raw ? withRev(raw, rev) : null;
        const issues = issueMap.get(n);
        const worst = worstSeverity(issues);
        const active = n === selected;
        const headline = variant.outline?.slides[idx]?.headline ?? "";
        return (
          <li key={n} className="shrink-0">
            <button
              ref={active ? selectedRef : undefined}
              type="button"
              onClick={() => onSelect(n)}
              aria-current={active || undefined}
              aria-label={`Слайд ${n}${headline ? `: ${headline}` : ""}`}
              title={headline || undefined}
              className="group flex w-[136px] cursor-pointer flex-col items-center gap-1.5 focus:outline-none"
            >
              <span
                className={cn(
                  "relative block w-full overflow-hidden rounded-lg bg-white transition-shadow",
                  active ? "shadow-[0_0_0_3px_#0077FF]" : "shadow-inner-line group-hover:shadow-[0_0_0_2px_#ADD3FF] group-focus-visible:shadow-[0_0_0_2px_#0077FF]",
                )}
                style={{ aspectRatio: String(aspect) }}
              >
                {url && !broken[url] ? (
                  <img src={url} alt="" loading="lazy" decoding="async" draggable={false} onError={() => setBroken((m) => ({ ...m, [url]: true }))} className="block h-full w-full object-cover" />
                ) : (
                  <span className="flex h-full w-full items-center bg-zinc-50 p-1.5 text-[9px] font-medium leading-[11px] text-zinc-500">
                    <span className="line-clamp-3">{headline || `Слайд ${n}`}</span>
                  </span>
                )}
                {(worst === "error" || worst === "warn") && (
                  <span title={issuesSummary(issues)} className={cn("absolute right-1 top-1 h-2.5 w-2.5 rounded-full ring-2 ring-white", worst === "error" ? "bg-red-500" : "bg-amber-400")} />
                )}
              </span>
              <span className={cn("text-xs font-semibold tabular-nums", active ? "text-accent" : "text-zinc-400")}>{n}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
