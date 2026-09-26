// The row of slide thumbnails under the slide — the way PowerPoint and Google Slides show a deck. Exactly 72px tall and
// exactly as wide as the slide (its edges are the slide's edges, like the stage header's). A short row is centred well
// inside it; a row that would come close to the slide's width is spread edge to edge (thumbs shrink to fit, never below
// 72px); a long deck scrolls sideways within the slide's width (wheel, arrows, auto-centring of the active thumb) with a
// fade on the hidden side. One Tab stop: the active thumb (←/→ turn the slides and the focus follows). One selection
// ring glides from thumb to thumb. With the «Замечания» switch on, a thumb with remarks carries their count.
import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { decodeImage, MOTION, smoothScroll, useIndicator, usePresence } from "../../lib/motion";
import { cn, plural } from "../../lib/utils";
import type { Issue, Severity, Variant } from "../../types";
import { withRev, worstSeverity } from "../VariantsHelpers";

const THUMB_W = 112;
const THUMB_H = 64; // the strip is 72: the thumb plus 4px for the active ring and its offset on each side
const GAP = 8;
const MIN_FIT = 72; // a thumb narrower than this is unreadable: scroll instead

const FADE = {
  both: "[mask-image:linear-gradient(to_right,transparent,#000_32px,#000_calc(100%-32px),transparent)]",
  left: "[mask-image:linear-gradient(to_right,transparent,#000_32px)]",
  right: "[mask-image:linear-gradient(to_right,#000_calc(100%-32px),transparent)]",
};

const BADGE: Record<Severity, string> = {
  error: "bg-red-600 text-white",
  warn: "bg-amber-500 text-amber-950",
  info: "bg-zinc-500 text-white",
};

function EdgeButton({ side, show, onClick }: { side: "left" | "right"; show: boolean; onClick(): void }) {
  const { mounted, leaving } = usePresence(show, MOTION.fast);
  if (!mounted) return null;
  const Icon = side === "left" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      tabIndex={-1}
      onClick={onClick}
      aria-label={side === "left" ? "Прокрутить слайды назад" : "Прокрутить слайды вперёд"}
      className={cn(
        "tap absolute top-1/2 z-10 flex h-7 w-7 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full bg-white text-zinc-700 shadow-raise hover:bg-zinc-50 hover:text-zinc-900",
        side === "left" ? "left-0" : "right-0",
        leaving ? "pointer-events-none animate-fade-out" : "animate-fade",
      )}
    >
      <Icon className="h-4 w-4" aria-hidden />
    </button>
  );
}

/** A thumb's picture. A new address (the deck reloaded after a fix or an undo, another variant) replaces the picture on
 *  screen only once it is decoded: the old one stays until then, so the thumb never paints blank. A thumb whose picture
 *  never loaded (lazy, off screen) takes the new address at once. */
function ThumbImg({ url, onBroken }: { url: string; onBroken(url: string): void }) {
  const [shown, setShown] = useState(url);
  const loaded = useRef(false);
  useEffect(() => {
    if (url === shown) return;
    if (!loaded.current) return void setShown(url);
    let live = true;
    const swap = () => live && setShown(url);
    decodeImage(url).then(swap, swap);
    return () => {
      live = false;
    };
  }, [url, shown]);
  return (
    <img
      src={shown}
      alt=""
      loading="lazy"
      decoding="async"
      draggable={false}
      onLoad={() => (loaded.current = true)}
      onError={() => onBroken(shown)}
      className="block h-full w-full object-cover"
    />
  );
}

/** The count of a thumb's remarks (the worst severity's colour); it pops in, re-pops when the count changes and pops
 *  out when the remarks are gone. The slide the agent is fixing shows a spinner instead. */
function ThumbBadge({ count, sev, fixing, delay }: { count: number; sev: Severity | null; fixing: boolean; delay: number }) {
  const show = fixing || (count > 0 && !!sev);
  const { mounted, leaving } = usePresence(show, MOTION.fast);
  const last = useRef({ count, sev, fixing });
  if (show) last.current = { count, sev, fixing };
  if (!mounted) return null;
  const s = last.current;
  if (s.fixing)
    return (
      <span aria-hidden className={cn("absolute right-1 top-1 inline-flex h-4 w-4 items-center justify-center rounded-full bg-white shadow-raise", leaving ? "animate-pop-out" : "animate-pop")}>
        <Loader2 className="h-3 w-3 animate-spin text-accent" />
      </span>
    );
  return (
    <span
      key={s.count}
      aria-hidden
      className={cn(
        "absolute right-1 top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-caption font-semibold leading-4 tabular-nums ring-2 ring-white",
        BADGE[s.sev ?? "info"],
        leaving ? "animate-pop-out" : "animate-pop",
      )}
      style={leaving ? undefined : { animationDelay: `${delay}ms` }}
    >
      {s.count}
    </span>
  );
}

export function SlideStrip({ variant, rev, total, selected, aspect, frameWidth = 0, issueMap, showRemarks = false, fixingSlide = null, onSelect }: {
  variant: Variant;
  rev: string;
  total: number;
  selected: number; // 1-based
  aspect: number;
  /** The slide frame's width (0 while unknown): the row lines up with it. */
  frameWidth?: number;
  issueMap: Map<number, Issue[]>;
  /** The «Замечания» switch is on: thumbs with remarks show their count. */
  showRemarks?: boolean;
  /** The slide of this variant the agent is fixing (a spinner on its thumb), null otherwise. */
  fixingSlide?: number | null;
  onSelect(n: number): void;
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);
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
  // the one selection ring: 4px around the active thumb, its 2px band inset (a 2px gap, then the ring)
  const ring = useIndicator(listRef, '[aria-current="true"]', `${selected}/${variant.strategy}`, { outset: 4 });

  const onBroken = useCallback((u: string) => setBroken((m) => (m[u] ? m : { ...m, [u]: true })), []);

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
    const left = el.offsetLeft + (el.offsetParent === listRef.current ? listRef.current?.offsetLeft ?? 0 : 0);
    const pad = 32; // the fade: a thumb under it counts as hidden
    if (left - pad < list.scrollLeft || left + el.offsetWidth + pad > list.scrollLeft + list.clientWidth) {
      list.scrollTo({ left: Math.max(0, left - (list.clientWidth - el.offsetWidth) / 2), behavior: smoothScroll() });
    }
  }, [selected, variant.strategy]);

  const page = (dir: 1 | -1) => {
    const el = scrollerRef.current;
    if (el) el.scrollBy({ left: dir * Math.max(width, el.clientWidth - 2 * width), behavior: smoothScroll() });
  };

  const fade = edges.left && edges.right ? FADE.both : edges.left ? FADE.left : edges.right ? FADE.right : "";
  let badgeIdx = 0;

  return (
    // + 8: the list's p-1 on both sides (room for the active ring), so the thumbs themselves start and end on the slide
    <div className={cn("relative h-[72px] shrink-0", frameWidth > 0 && "self-center")} style={frameWidth > 0 ? { width: frameWidth + 8 } : undefined}>
      <div
        ref={scrollerRef}
        onScroll={measure}
        className={cn("relative h-full overflow-x-auto overflow-y-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", fade)}
      >
        <ol ref={listRef} className={cn("relative flex h-full items-center gap-2 p-1", flush ? "w-full justify-between" : "mx-auto w-max")} aria-label="Слайды">
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
              <li key={n} className="shrink-0">
                <button
                  ref={active ? selectedRef : undefined}
                  type="button"
                  tabIndex={active ? 0 : -1}
                  onClick={() => onSelect(n)}
                  aria-current={active || undefined}
                  aria-label={`Слайд ${n}${headline ? `: ${headline}` : ""}${count > 0 ? `, ${plural(count, "замечание", "замечания", "замечаний")}` : ""}`}
                  title={headline || `Слайд ${n}`}
                  className={cn(
                    "tap-soft relative block cursor-pointer overflow-hidden rounded-lg bg-white ring-1 ring-zinc-900/[0.08] focus-visible:outline-offset-[-2px]",
                    !active && "hover:ring-2 hover:ring-accent-200",
                  )}
                  style={{ width, aspectRatio: String(aspect) }}
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
      <EdgeButton side="left" show={edges.left} onClick={() => page(-1)} />
      <EdgeButton side="right" show={edges.right} onClick={() => page(1)} />
    </div>
  );
}
