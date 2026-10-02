// The deck's slides as a column of thumbnails on the left of the stage — the way PowerPoint, Keynote and Google Slides
// show a deck. A white card the stage's height; a long deck scrolls inside it (wheel, the active thumb kept in view)
// with a fade on the side that hides thumbs. One Tab stop: the active thumb (↑/↓ turn the slides here, ←/→ anywhere
// on the deck, and the focus follows the selection). One selection ring glides from thumb to thumb. With the
// «Замечания» switch on, a thumb with remarks carries their count; the slide the agent fixes shows a spinner.
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { smoothScroll, useIndicator } from "../../lib/motion";
import { cn, plural } from "../../lib/utils";
import type { Issue, Variant } from "../../types";
import { withRev, worstSeverity } from "../VariantsHelpers";
import { ThumbBadge, ThumbImg } from "./SlideThumb";

const FADE = {
  both: "[mask-image:linear-gradient(to_bottom,transparent,#000_28px,#000_calc(100%-28px),transparent)]",
  top: "[mask-image:linear-gradient(to_bottom,transparent,#000_28px)]",
  bottom: "[mask-image:linear-gradient(to_bottom,#000_calc(100%-28px),transparent)]",
};

export function SlideRail({ variant, rev, total, selected, aspect, issueMap, showRemarks = false, fixingSlide = null, onSelect, className, railRef }: {
  variant: Variant;
  rev: string;
  total: number;
  selected: number; // 1-based
  aspect: number;
  issueMap: Map<number, Issue[]>;
  /** The «Замечания» switch is on: thumbs with remarks show their count. */
  showRemarks?: boolean;
  /** The slide of this variant the agent is fixing (a spinner on its thumb), null otherwise. */
  fixingSlide?: number | null;
  onSelect(n: number): void;
  className?: string;
  /** The rail's card (the deck fades it in after a layout change narrows or widens it). */
  railRef?: RefObject<HTMLElement>;
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);
  const [broken, setBroken] = useState<Record<string, true>>({});
  const [edges, setEdges] = useState({ top: false, bottom: false });
  // the one selection ring: 4px around the active thumb, its 2px band inset (a 2px gap, then the ring)
  const ring = useIndicator(listRef, '[aria-current="true"]', `${selected}/${variant.strategy}`, { outset: 4 });

  const onBroken = useCallback((u: string) => setBroken((m) => (m[u] ? m : { ...m, [u]: true })), []);

  const measure = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const top = el.scrollTop > 1;
    const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
    setEdges((e) => (e.top === top && e.bottom === bottom ? e : { top, bottom }));
  }, []);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (listRef.current) ro.observe(listRef.current);
    return () => ro.disconnect();
  }, [measure, total]);

  // the rail scrolls by itself only — scrollIntoView would also scroll the page under the title bar
  useEffect(() => {
    const el = selectedRef.current;
    const box = scrollerRef.current;
    const list = listRef.current;
    if (!el || !box || !list) return;
    // ↑/↓ (or ←/→ on the deck) turned the slide while a thumb had the focus: the focus follows the selection
    if (box.contains(document.activeElement) && document.activeElement !== el) el.focus({ preventScroll: true });
    const top = list.offsetTop + el.offsetTop;
    const pad = 32; // the fade: a thumb under it counts as hidden
    if (top - pad < box.scrollTop || top + el.offsetHeight + pad > box.scrollTop + box.clientHeight) {
      box.scrollTo({ top: Math.max(0, top - (box.clientHeight - el.offsetHeight) / 2), behavior: smoothScroll() });
    }
  }, [selected, variant.strategy]);

  const onKey = (e: KeyboardEvent<HTMLOListElement>) => {
    const step = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    if (!step || e.altKey || e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    onSelect(Math.min(total, Math.max(1, selected + step)));
  };

  const fade = edges.top && edges.bottom ? FADE.both : edges.top ? FADE.top : edges.bottom ? FADE.bottom : "";
  let badgeIdx = 0;

  return (
    <nav ref={railRef} aria-label="Слайды" className={cn("flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-card", className)}>
      <div ref={scrollerRef} onScroll={measure} className={cn("relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", fade)}>
        <ol ref={listRef} onKeyDown={onKey} className="relative flex flex-col gap-3 p-3">
          <span
            aria-hidden
            className="pointer-events-none absolute left-0 top-0 z-[1] rounded-xl ring-2 ring-inset ring-accent transition-[transform,width,height] duration-300 ease-glide"
            style={ring.style}
          />
          {Array.from({ length: total }, (_, idx) => {
            const n = idx + 1;
            const raw = variant.slides[idx];
            const url = raw ? withRev(raw, rev) : null;
            const issues = issueMap.get(n);
            const count = showRemarks ? issues?.length ?? 0 : 0;
            const worst = worstSeverity(issues);
            const active = n === selected;
            const fixing = fixingSlide === n;
            const headline = variant.outline?.slides[idx]?.headline ?? "";
            const delay = count > 0 ? Math.min(badgeIdx++ * 20, 200) : 0;
            return (
              <li key={n}>
                <button
                  ref={active ? selectedRef : undefined}
                  type="button"
                  tabIndex={active ? 0 : -1}
                  onClick={() => onSelect(n)}
                  aria-current={active || undefined}
                  aria-label={`Слайд ${n}${headline ? `: ${headline}` : ""}${count > 0 ? `, ${plural(count, "замечание", "замечания", "замечаний")}` : ""}`}
                  title={headline || `Слайд ${n}`}
                  className={cn(
                    "tap-soft relative block w-full cursor-pointer overflow-hidden rounded-lg bg-white ring-1 ring-zinc-900/[0.08] focus-visible:outline-offset-[-2px]",
                    !active && "hover:ring-2 hover:ring-accent-200",
                  )}
                  style={{ aspectRatio: String(aspect) }}
                >
                  {url && !broken[url] ? (
                    <ThumbImg url={url} onBroken={onBroken} />
                  ) : (
                    <span className="flex h-full w-full items-start bg-zinc-50 p-2 text-left text-caption text-zinc-500">
                      <span className="line-clamp-2">{headline || `Слайд ${n}`}</span>
                    </span>
                  )}
                  <span className={cn("absolute bottom-1 left-1 rounded px-1 text-caption font-semibold leading-4 tabular-nums text-white transition-colors duration-150", active ? "bg-accent-fill" : "bg-zinc-900/60")} aria-hidden>
                    {n}
                  </span>
                  <ThumbBadge count={count} sev={worst} fixing={fixing} delay={delay} />
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </nav>
  );
}
