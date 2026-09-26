// The row of slide thumbnails under the slide — the way PowerPoint and Google Slides show a deck. Exactly 72px tall and
// exactly as wide as the slide (its edges are the slide's edges, like the stage header's). A short row is centred well
// inside it; a row that would come close to the slide's width is spread edge to edge (thumbs shrink to fit, never below
// 72px); a long deck scrolls sideways within the slide's width (wheel, arrows, auto-centring of the active thumb) with a
// fade on the hidden side. One Tab stop: the active thumb (←/→ turn the slides and the focus follows).
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "../../lib/utils";
import type { Issue, Variant } from "../../types";
import { issuesSummary, withRev, worstSeverity } from "../VariantsHelpers";

const THUMB_W = 112;
const THUMB_H = 64; // the strip is 72: the thumb plus 4px for the active ring and its offset on each side
const GAP = 8;
const MIN_FIT = 72; // a thumb narrower than this is unreadable: scroll instead

const FADE = {
  both: "[mask-image:linear-gradient(to_right,transparent,#000_32px,#000_calc(100%-32px),transparent)]",
  left: "[mask-image:linear-gradient(to_right,transparent,#000_32px)]",
  right: "[mask-image:linear-gradient(to_right,#000_calc(100%-32px),transparent)]",
};

function EdgeButton({ side, onClick }: { side: "left" | "right"; onClick(): void }) {
  const Icon = side === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      tabIndex={-1}
      onClick={onClick}
      aria-label={side === "left" ? "Прокрутить слайды назад" : "Прокрутить слайды вперёд"}
      className={cn(
        "absolute top-1/2 z-10 flex h-7 w-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full bg-white text-zinc-700 shadow-raise transition-colors duration-150 hover:bg-zinc-50 hover:text-zinc-900 animate-fade",
        side === "left" ? "left-0" : "right-0",
      )}
    >
      <Icon className="h-4 w-4" aria-hidden />
    </button>
  );
}

export function SlideStrip({ variant, rev, total, selected, aspect, frameWidth = 0, issueMap, onSelect }: {
  variant: Variant;
  rev: string;
  total: number;
  selected: number; // 1-based
  aspect: number;
  /** The slide frame's width (0 while unknown): the row lines up with it. */
  frameWidth?: number;
  issueMap: Map<number, Issue[]>;
  onSelect(n: number): void;
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);
  const [broken, setBroken] = useState<Record<string, true>>({});
  const [edges, setEdges] = useState({ left: false, right: false });
  // a 16:9 thumb is 112×63; a squarer slide keeps the 64px height and gets narrower
  const natural = Math.min(THUMB_W, Math.round(THUMB_H * aspect));
  const row = total * natural + (total - 1) * GAP;
  const fit = frameWidth > 0 ? Math.floor((frameWidth - (total - 1) * GAP) / total) : 0;
  // flush: the first and the last thumb sit exactly on the slide's edges
  const flush = frameWidth > 0 && row > frameWidth - 96 && fit >= MIN_FIT;
  const width = flush ? Math.min(natural, fit) : natural;

  const measure = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const left = el.scrollLeft > 1;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setEdges((e) => (e.left === left && e.right === right ? e : { left, right }));
  }, []);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    // the wheel turns sideways here: a vertical scroll over the strip moves the thumbnails, never the page
    const onWheel = (e: WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      e.preventDefault();
      el.scrollLeft += e.deltaY;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      ro.disconnect();
      el.removeEventListener("wheel", onWheel);
    };
  }, [measure, total]);

  // scroll the strip only — scrollIntoView would also scroll the page and hide the title and the download button
  useEffect(() => {
    const el = selectedRef.current;
    const list = scrollerRef.current;
    if (!el || !list) return;
    // ←/→ turned the slide while a thumb had the focus: the focus follows the selection
    if (list.contains(document.activeElement) && document.activeElement !== el) el.focus({ preventScroll: true });
    const left = el.offsetLeft; // the scroller is the offsetParent (relative): content coordinates, scroll ignored
    const pad = 32; // the fade: a thumb under it counts as hidden
    if (left - pad < list.scrollLeft || left + el.offsetWidth + pad > list.scrollLeft + list.clientWidth) {
      list.scrollTo({ left: Math.max(0, left - (list.clientWidth - el.offsetWidth) / 2), behavior: "smooth" });
    }
  }, [selected, variant.strategy]);

  const page = (dir: 1 | -1) => {
    const el = scrollerRef.current;
    if (el) el.scrollBy({ left: dir * Math.max(width, el.clientWidth - 2 * width), behavior: "smooth" });
  };

  const fade = edges.left && edges.right ? FADE.both : edges.left ? FADE.left : edges.right ? FADE.right : "";

  return (
    // + 8: the list's p-1 on both sides (room for the active ring), so the thumbs themselves start and end on the slide
    <div className={cn("relative h-[72px] shrink-0", frameWidth > 0 && "self-center")} style={frameWidth > 0 ? { width: frameWidth + 8 } : undefined}>
      <div
        ref={scrollerRef}
        onScroll={measure}
        className={cn("relative h-full overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", fade)}
      >
        <ol className={cn("flex h-full items-center gap-2 p-1", flush ? "w-full justify-between" : "mx-auto w-max")} aria-label="Слайды">
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
                  tabIndex={active ? 0 : -1}
                  onClick={() => onSelect(n)}
                  aria-current={active || undefined}
                  aria-label={`Слайд ${n}${headline ? `: ${headline}` : ""}`}
                  title={headline || `Слайд ${n}`}
                  className={cn(
                    "relative block cursor-pointer overflow-hidden rounded-lg bg-white transition-shadow duration-150 focus-visible:outline-offset-[-2px]",
                    active ? "ring-2 ring-accent ring-offset-2 ring-offset-white" : "ring-1 ring-zinc-900/[0.08] hover:ring-2 hover:ring-accent-200",
                  )}
                  style={{ width, aspectRatio: String(aspect) }}
                >
                  {url && !broken[url] ? (
                    <img src={url} alt="" loading="lazy" decoding="async" draggable={false} onError={() => setBroken((m) => ({ ...m, [url]: true }))} className="block h-full w-full object-cover" />
                  ) : (
                    <span className="flex h-full w-full items-start bg-zinc-50 p-2 text-left text-caption text-zinc-500">
                      <span className="line-clamp-2">{headline || `Слайд ${n}`}</span>
                    </span>
                  )}
                  <span className={cn("absolute bottom-1 left-1 rounded px-1 text-caption font-semibold leading-4 tabular-nums text-white", active ? "bg-accent-fill" : "bg-zinc-900/60")} aria-hidden>
                    {n}
                  </span>
                  {(worst === "error" || worst === "warn") && (
                    <span title={issuesSummary(issues)} className={cn("absolute right-1 top-1 h-2 w-2 rounded-full ring-2 ring-white", worst === "error" ? "bg-red-500" : "bg-amber-500")} />
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      </div>
      {edges.left && <EdgeButton side="left" onClick={() => page(-1)} />}
      {edges.right && <EdgeButton side="right" onClick={() => page(1)} />}
    </div>
  );
}
