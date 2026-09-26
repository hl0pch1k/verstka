// The slide on the result stage: the largest frame the stage allows (a size container, no magic numbers), the remarks
// overlay (numbered frames and pins, a spotlight on the places, bound to the slide that is fully shown), the working
// layer while the agent fixes the slide, and the stage controls (the «Замечания» switch, ‹ 3 / 10 ›, full screen).
// SlideImage is the no-flash cross-fader shared with the lightbox: the image on screen stays until the next one is
// decoded, then the next one moves in over it.
import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { Check, ChevronLeft, ChevronRight, ImageOff, Maximize2 } from "lucide-react";
import { decodeImage, isDecoded, MOTION, stagger, usePresence } from "../lib/motion";
import { cn, plural, SEVERITY_LABEL } from "../lib/utils";
import type { BboxFrac, Severity } from "../types";
import { Button } from "./ui/Button";
import { Spinner } from "./ui/Spinner";
import { Switch } from "./ui/Switch";
import { pct, pinSpots, placeTags, stagePlaces } from "./VariantsHelpers";
import type { Rect, RemarkTone, StageBox, StageRemark, TagSpot } from "./VariantsHelpers";
import "./simple/remarks.css";

// ---------------------------------------------------------------------------------------------------------------------
// SlideImage: the no-flash cross-fader

interface Layer { src: string; ready: boolean; dir: -1 | 0 | 1; mode: "turn" | "reveal"; failed?: boolean }
interface Layers { base: Layer | null; top: Layer | null }

const TURN_CLASS = { "-1": "animate-slide-in-l", "0": "animate-fade", "1": "animate-slide-in-r" } as const;

/**
 * Two layers at most: the base (fully shown) and the top (incoming). Both are keyed by their src, so promoting the top
 * keeps its decoded node: nothing is ever painted blank. A new src waits until it is decoded, then moves in over the
 * base — a push of 12px toward the travel (`dir`), a cross-fade (a variant switch) or the slow `reveal` after a fix.
 * A top that is slow to arrive dims the base after 250ms, so the click is acknowledged.
 * `onReady`: the image is decoded and starts to move in (the moment a working layer over it can leave); `onShown`: it is
 * fully shown (the moment an overlay can bind to it).
 */
export function SlideImage({ src, alt, dir = 0, mode = "turn", onReady, onShown, onAspect, onError, dark = false, className }: {
  src: string | null;
  alt: string;
  dir?: -1 | 0 | 1;
  mode?: "turn" | "reveal";
  onReady?(src: string): void;
  onShown?(src: string): void;
  onAspect?(a: number): void;
  onError?(src: string): void;
  dark?: boolean;
  className?: string;
}) {
  const [st, setSt] = useState<Layers>(() => (src && isDecoded(src) ? { base: { src, ready: true, dir: 0, mode: "turn" }, top: null } : { base: null, top: src ? { src, ready: false, dir: 0, mode: "turn" } : null }));
  const [slow, setSlow] = useState(false);
  const cb = useRef({ onReady, onShown, onAspect, onError });
  cb.current = { onReady, onShown, onAspect, onError };
  const dirRef = useRef({ dir, mode });
  dirRef.current = { dir, mode };

  // the base shown on mount (a decoded image) counts as ready and shown
  useEffect(() => {
    if (st.base && !st.top) {
      cb.current.onReady?.(st.base.src);
      cb.current.onShown?.(st.base.src);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!src) return;
    const { dir: d, mode: m } = dirRef.current;
    setSt(({ base, top }) => {
      if (top?.src === src) return { base, top };
      if (base?.src === src) return { base, top: null }; // back to the slide on screen: the incoming one goes
      const next: Layer = { src, ready: false, dir: d, mode: m };
      // a top already moving in becomes the base at once; one still decoding is simply replaced
      if (top && top.ready && !top.failed) return { base: top, top: next };
      return { base, top: next };
    });
    let alive = true;
    decodeImage(src).then(
      () => alive && setSt((s) => (s.top?.src === src && !s.top.ready ? { ...s, top: { ...s.top, ready: true } } : s)),
      () => {
        if (!alive) return;
        setSt((s) => (s.top?.src === src ? { ...s, top: { ...s.top, failed: true } } : s));
        cb.current.onError?.(src);
      },
    );
    return () => {
      alive = false;
    };
  }, [src]);

  const promote = useCallback((s: string) => {
    setSt((cur) => (cur.top?.src === s ? { base: cur.top, top: null } : cur));
    cb.current.onShown?.(s);
  }, []);

  // a slow arrival dims the slide on screen; a fallback promotes a top whose animation end never came (hidden tab)
  const top = st.top;
  // decoded: it starts to move in now
  useEffect(() => {
    if (top?.ready && !top.failed) cb.current.onReady?.(top.src);
  }, [top?.src, top?.ready, top?.failed]);
  useEffect(() => {
    setSlow(false);
    if (!top || top.failed) return;
    if (!top.ready) {
      const t = window.setTimeout(() => setSlow(true), 250);
      return () => window.clearTimeout(t);
    }
    const t = window.setTimeout(() => promote(top.src), top.mode === "reveal" ? 900 : 700);
    return () => window.clearTimeout(t);
  }, [top?.src, top?.ready, top?.failed, top?.mode, promote]);

  const topReady = !!top && top.ready && !top.failed;
  const layers: { l: Layer; role: "base" | "top" }[] = [];
  if (st.base) layers.push({ l: st.base, role: "base" });
  if (top && !top.failed) layers.push({ l: top, role: "top" });
  const firstLoad = !st.base;

  return (
    <>
      {firstLoad && <div aria-hidden className={cn("absolute inset-0", dark ? "bg-white/5" : "skeleton rounded-none", className)} />}
      {layers.map(({ l, role }) => {
        const isTop = role === "top";
        const labelled = isTop ? topReady : !topReady;
        const enter = !isTop ? "" : !l.ready ? "opacity-0" : firstLoad ? "animate-fade" : l.mode === "reveal" ? "animate-reveal" : TURN_CLASS[String(l.dir) as "-1" | "0" | "1"];
        return (
          <img
            key={l.src}
            src={l.src}
            alt={labelled ? alt : ""}
            aria-hidden={labelled ? undefined : true}
            draggable={false}
            decoding="async"
            onLoad={(e) => {
              const im = e.currentTarget;
              if (im.naturalWidth > 0 && im.naturalHeight > 0) cb.current.onAspect?.(im.naturalWidth / im.naturalHeight);
            }}
            onAnimationEnd={(e) => {
              if (isTop && l.ready && e.target === e.currentTarget) promote(l.src);
            }}
            className={cn(
              "absolute inset-0 h-full w-full object-contain",
              isTop ? cn(enter, l.ready && "rm-fade") : cn("transition-opacity duration-200", slow && top && !top.ready ? "opacity-60" : "opacity-100"),
              className,
            )}
          />
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// pins and boxes

const PIN_FILL: Record<Severity, string> = {
  error: "bg-red-600 text-white",
  warn: "bg-amber-500 text-amber-950",
  info: "bg-zinc-500 text-white",
};
const PING_COLOR: Record<Severity, string> = { error: "rgba(239,68,68,0.45)", warn: "rgba(245,158,11,0.5)", info: "rgba(98,109,122,0.45)" };
const BOX: Record<Severity, string> = {
  error: "border-red-500 bg-red-500/[0.08]",
  warn: "border-amber-500 bg-amber-400/[0.12]",
  info: "border-dashed border-zinc-500 bg-zinc-500/[0.08]",
};
const BOX_ACTIVE: Record<Severity, string> = {
  error: "bg-red-500/[0.16] shadow-[0_0_0_4px_rgba(239,68,68,0.28)]",
  warn: "bg-amber-400/[0.24] shadow-[0_0_0_4px_rgba(245,158,11,0.32)]",
  info: "bg-zinc-500/[0.16] shadow-[0_0_0_4px_rgba(98,109,122,0.28)]",
};
const GLOW: Record<Severity, string> = { error: "ring-red-500/50", warn: "ring-amber-500/50", info: "ring-zinc-500/40" };

const PIN = 20;
const PIN_GAP = 4;
const pinsWidth = (k: number) => PIN * k + PIN_GAP * Math.max(0, k - 1);

/** The numbered marker of a remark: the same on the slide, in the panel and in the lightbox. `fixed`: an emerald check.
 *  Only its scale transitions (the hover link): a pin that turns into a check is another pin (the caller keys it and
 *  pops it in), never a red → emerald colour blend. */
export function RemarkPin({ n, sev, fixed = false, active = false, className }: { n: number; sev: Severity; fixed?: boolean; active?: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-caption font-bold tabular-nums shadow-raise ring-2 ring-white transition-transform duration-150",
        fixed ? "bg-emerald-500 text-white" : PIN_FILL[sev],
        active && "scale-110",
        className,
      )}
    >
      {fixed ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} /> : n}
    </span>
  );
}

interface PlacePins { place: StageBox; remarks: StageRemark[]; order: number }

/** The overlay's geometry: the places (frames) with the remarks whose pins sit on them, in reading order worst first;
 *  the whole-slide remarks; the pins' spots. */
function useLayout(remarks: StageRemark[], w: number, h: number) {
  return useMemo(() => {
    const byId = new Map(remarks.map((r) => [r.issue.id, r]));
    const places = stagePlaces(remarks.filter((r) => !r.whole).map((r) => r.issue));
    const named = new Set<string>();
    const list: PlacePins[] = places.boxes.map((place) => {
      const own = place.issues.map((i) => byId.get(i.id)).filter((r): r is StageRemark => !!r && !named.has(r.issue.id));
      own.sort((a, b) => a.n - b.n);
      own.forEach((r) => named.add(r.issue.id));
      const first = Math.min(...place.issues.map((i) => byId.get(i.id)?.n ?? 99));
      return { place, remarks: own, order: first };
    });
    list.sort((a, b) => a.order - b.order);
    const whole = remarks.filter((r) => r.whole).sort((a, b) => a.n - b.n);
    const avoid: Rect[] = whole.length ? [{ x: 12, y: 12, w: pinsWidth(whole.length), h: PIN }] : [];
    const sizes = new Map(list.map((p) => [p.place.key, { w: pinsWidth(Math.max(1, p.remarks.length)), h: PIN }]));
    const pinned = list.filter((p) => p.remarks.length > 0).map((p) => ({ ...p.place, tagged: true }));
    const spots = w > 0 && h > 0 ? placeTags(pinned, w, h, (b) => sizes.get(b.key) ?? { w: PIN, h: PIN }, avoid, pinSpots) : new Map<string, TagSpot | null>();
    return { list, whole, spots };
  }, [remarks, w, h]);
}

export interface RemarksLayerProps {
  remarks: StageRemark[];
  size: { w: number; h: number };
  activeIds?: string[];
  onActive?(ids: string[] | null): void;
  onPick?(id: string): void;
  /** A row was clicked: its frame pings once (`k` replays it). */
  ping?: { id: string; k: number } | null;
  /** Remarks being fixed: their frames breathe. */
  fixingIds?: string[];
  /** The spotlight (dims the slide around the frames). */
  spotlight?: boolean;
  /** Read-only (the lightbox): native tooltips, no hover links. */
  readOnly?: boolean;
  leaving?: "fast" | "normal" | false;
}

/** The remarks over the slide: a spotlight with a hole per frame, the frames (worst and first in reading order enter
 *  first, 40ms apart), the numbered pins (they pop in 80ms after their frame; errors ping twice), the whole-slide pins
 *  in the top-left corner. `leaving`: the same layer fades out as one piece — inert (clicks go to the slide under it),
 *  its own entrances frozen where they are, so nothing inside replays or pops while it goes. */
export function RemarksLayer({ remarks, size, activeIds = [], onActive, onPick, ping = null, fixingIds = [], spotlight = true, readOnly = false, leaving = false }: RemarksLayerProps) {
  const maskId = `rm${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const { list, whole, spots } = useLayout(remarks, size.w, size.h);
  const anyActive = activeIds.length > 0;
  const isActive = (ids: string[]) => ids.some((id) => activeIds.includes(id));
  const wholeActive = whole.find((r) => activeIds.includes(r.issue.id)) ?? null;
  const wholePing = !leaving && ping ? whole.find((r) => r.issue.id === ping.id) : undefined;
  const px = (b: BboxFrac) => ({ x: b.x * size.w, y: b.y * size.h, w: b.w * size.w, h: b.h * size.h });
  /** No links while read-only (the lightbox) or leaving (the overlay is already on its way out). */
  const passive = readOnly || !!leaving;
  const hover = (ids: string[] | null) => !passive && onActive?.(ids);
  const pick = (e: { stopPropagation(): void }, id: string | undefined) => {
    if (leaving) return; // a leaving frame never swallows the click: it opens the slide like any other spot
    e.stopPropagation();
    if (!readOnly && id) onPick?.(id);
  };

  return (
    <div
      aria-hidden={leaving ? true : undefined}
      {...(leaving ? ({ inert: "" } as Record<string, string>) : null)}
      className={cn(
        "pointer-events-none absolute inset-0 z-10",
        // a turn: the old slide's remarks are mostly gone before the incoming slide is half in (its push-fade eases
        // out, so this exit is front-loaded too and shorter)
        leaving && cn("animate-fade-out rm-fade-out [&_*]:!pointer-events-none [&_*]:![animation-play-state:paused]", leaving === "fast" && "[animation-duration:80ms] [animation-timing-function:var(--ease-out)]"),
      )}
    >
      {spotlight && list.length > 0 && size.w > 0 && (
        <svg className="pointer-events-none absolute inset-0 h-full w-full animate-fade" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden>
          <defs>
            <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="1" height="1">
              <rect x="0" y="0" width="1" height="1" fill="white" />
              {list.map(({ place }) => {
                const pad = 3;
                return (
                  <rect
                    key={place.key}
                    x={place.box.x - pad / size.w}
                    y={place.box.y - pad / size.h}
                    width={place.box.w + (2 * pad) / size.w}
                    height={place.box.h + (2 * pad) / size.h}
                    rx={6 / size.w}
                    ry={6 / size.h}
                    fill="black"
                  />
                );
              })}
            </mask>
          </defs>
          <rect x="0" y="0" width="1" height="1" fill="rgb(14 15 16 / 0.24)" mask={`url(#${maskId})`} />
        </svg>
      )}

      {/* the whole-slide glow: a remark about the whole slide is active or was just clicked */}
      {whole.length > 0 && (
        <div aria-hidden className={cn("remark-glow pointer-events-none absolute inset-0 rounded-xl ring-4 ring-inset", GLOW[(wholeActive ?? whole[0]).issue.severity], wholeActive ? "opacity-100" : "opacity-0")} />
      )}
      {wholePing && <div key={`wp${ping?.k}`} aria-hidden className={cn("remark-inset-flash pointer-events-none absolute inset-0 rounded-xl ring-4 ring-inset", GLOW[wholePing.issue.severity])} />}

      {list.map(({ place, remarks: own }, i) => {
        const ids = place.issues.map((x) => x.id);
        const on = isActive(ids);
        const breathing = ids.some((id) => fixingIds.includes(id));
        const pinging = ping && ids.includes(ping.id) ? ping : null;
        const label = [...place.issues]
          .map((x) => remarks.find((r) => r.issue.id === x.id))
          .filter((r): r is StageRemark => !!r)
          .map((r) => `${r.n}. ${SEVERITY_LABEL[r.issue.severity]}: ${r.text}`)
          .join(" · ");
        const b = place.box;
        return (
          <div
            key={place.key}
            role="note"
            aria-label={label}
            title={readOnly ? own.map((r) => `${r.n}. ${r.title}`).join("\n") || undefined : undefined}
            onClick={(e) => pick(e, own[0]?.issue.id ?? ids[0])}
            onMouseEnter={() => hover(ids)}
            onMouseLeave={() => hover(null)}
            className={cn(
              "pointer-events-auto absolute animate-frame-in transition-opacity duration-150",
              readOnly ? "cursor-default" : "cursor-pointer",
              anyActive && !on ? "opacity-40" : "opacity-100",
            )}
            style={{ left: pct(b.x), top: pct(b.y), width: pct(b.w), height: pct(b.h), ...stagger(i) }}
          >
            <div
              className={cn(
                "absolute inset-0 rounded border-2 transition-[box-shadow,background-color] duration-150",
                BOX[place.sev],
                on && BOX_ACTIVE[place.sev],
                breathing && "remark-breathe",
              )}
            />
            {pinging && !leaving && <span key={pinging.k} aria-hidden className="remark-ping pointer-events-none absolute inset-0 rounded" style={{ ["--ping" as string]: PING_COLOR[place.sev] }} />}
          </div>
        );
      })}

      {/* the pins paint above every frame: a later frame never covers a number */}
      {list.map(({ place, remarks: own }, i) => {
        const spot = spots.get(place.key);
        if (!spot || own.length === 0) return null;
        const r = px(place.box);
        return (
          <div key={`pins-${place.key}`} className="pointer-events-none absolute z-20 flex gap-1" style={{ left: r.x + spot.dx, top: r.y + spot.dy }}>
            {own.map((rm) => (
              <Pin key={rm.issue.id} remark={rm} delay={80 + Math.min(i, 5) * 40} active={activeIds.includes(rm.issue.id)} breathing={fixingIds.includes(rm.issue.id)} readOnly={readOnly} onActive={hover} onPick={pick} />
            ))}
          </div>
        );
      })}
      {whole.length > 0 && (
        <div className="pointer-events-none absolute left-3 top-3 z-20 flex gap-1">
          {whole.map((rm, k) => (
            <Pin key={rm.issue.id} remark={rm} delay={80 + Math.min(list.length + k, 5) * 40} active={activeIds.includes(rm.issue.id)} breathing={fixingIds.includes(rm.issue.id)} readOnly={readOnly} onActive={hover} onPick={pick} />
          ))}
        </div>
      )}
    </div>
  );
}

function Pin({ remark, delay, active, breathing, readOnly, onActive, onPick }: { remark: StageRemark; delay: number; active: boolean; breathing: boolean; readOnly: boolean; onActive(ids: string[] | null): void; onPick(e: { stopPropagation(): void }, id: string): void }) {
  const sev = remark.issue.severity;
  return (
    <span
      className={cn("pointer-events-auto relative animate-pop", readOnly ? "cursor-default" : "cursor-pointer", breathing && "remark-breathe")}
      style={{ animationDelay: `${delay}ms` }}
      title={readOnly ? `${remark.n}. ${remark.title}` : undefined}
      onMouseEnter={() => onActive([remark.issue.id])}
      onMouseLeave={() => onActive(null)}
      onClick={(e) => onPick(e, remark.issue.id)}
    >
      {/* an error calls for attention twice when the remarks appear, then stays still */}
      {sev === "error" && !readOnly && <span aria-hidden className="absolute inset-0 animate-ring-ping rounded-full bg-red-500 opacity-0" style={{ animationDelay: `${delay + 200}ms` }} />}
      <RemarkPin n={remark.n} sev={sev} active={active} className="relative" />
    </span>
  );
}

/** Emerald checks where the fixed remarks were (where their pins sat): they pop, hold and fade (decorative; the panel
 *  carries the status). */
function FixedMarks({ marks, size }: { marks: { n: number; box: BboxFrac | null }[]; size: { w: number; h: number } }) {
  let corner = 0;
  const pinAt = (b: BboxFrac) => {
    const r = { x: b.x * size.w, y: b.y * size.h, w: b.w * size.w, h: b.h * size.h };
    const s = pinSpots(r, { w: PIN, h: PIN })[0];
    return { left: Math.min(size.w - PIN - 4, Math.max(4, r.x + s.dx)), top: Math.min(size.h - PIN - 4, Math.max(4, r.y + s.dy)) };
  };
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 z-20">
      {marks.map((m, i) => {
        const at = m.box ? pinAt(m.box) : { left: 12 + (corner++) * (PIN + PIN_GAP), top: 12 };
        return (
          <span key={`${m.n}-${i}`} className="remark-done absolute inline-flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-white shadow-raise ring-2 ring-white" style={{ ...at, animationDelay: `${i * 40}ms` }}>
            <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
          </span>
        );
      })}
    </div>
  );
}

/** The agent is rebuilding this slide: a light band sweeps it and a glass pill says so. Clicks still open the lightbox. */
function FixingLayer({ label, leaving }: { label: string; leaving: boolean }) {
  return (
    <div aria-hidden={leaving || undefined} className={cn("pointer-events-none absolute inset-0 z-30 overflow-hidden rounded-xl", leaving ? "animate-fade-out rm-fade-out" : "animate-fade rm-fade")}>
      <div className="absolute inset-0 bg-white/[0.14] motion-reduce:bg-accent/5" />
      <div className="remark-scan" />
      <div className={cn("absolute bottom-3 left-1/2 -translate-x-1/2", leaving ? "animate-drop-out" : "animate-drop-in")}>
        <span className="inline-flex h-8 items-center gap-2 whitespace-nowrap rounded-full bg-white/90 px-3 text-caption font-semibold text-zinc-900 shadow-raise backdrop-blur-sm" role="status">
          <Spinner size={16} className="text-accent" label={label} />
          {label}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// the stage

interface Props {
  src: string | null;
  slide: number; // 1-based
  headline: string;
  /** Width / height of the slide; refined from the image's natural size through `onAspect`. */
  aspect: number;
  onAspect(a: number): void;
  /** The frame's width and the well's width, in CSS pixels, whenever either changes. */
  onBox?(frame: number, well: number): void;
  onZoom(): void;
  /** How the next image comes in: the direction of travel (slides), a cross-fade (variants), a reveal (a fix). */
  dir?: -1 | 0 | 1;
  mode?: "turn" | "reveal";
  remarks: StageRemark[];
  showRemarks: boolean;
  activeIds: string[];
  onActive(ids: string[] | null): void;
  onPick(id: string): void;
  ping: { id: string; k: number } | null;
  /** The agent works on this slide: the label of the glass pill («Агент исправляет слайд»), null otherwise. */
  fixing: string | null;
  fixingIds: string[];
  /** The fixed remarks' places, for the emerald checks (after the new image is shown); `key` replays them once. */
  resolved: { key: string; marks: { n: number; box: BboxFrac | null }[] } | null;
  /** A new image is decoded and starts to show (the working layer over the slide can leave now). */
  onReady?(src: string): void;
  frameRef?: RefObject<HTMLDivElement>;
}

/** The well of the stage: takes every pixel the stage leaves and fits the slide into it (container query units). */
export function VariantsSlidePreview({ src, slide, headline, aspect, onAspect, onBox, onZoom, dir = 0, mode = "turn", remarks, showRemarks, activeIds, onActive, onPick, ping, fixing, fixingIds, resolved, onReady, frameRef: frameRefProp }: Props) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [shownSrc, setShownSrc] = useState<string | null>(null);
  const failed = !src || failedSrc === src;

  const wellRef = useRef<HTMLDivElement>(null);
  const ownFrame = useRef<HTMLDivElement>(null);
  const frameRef = frameRefProp ?? ownFrame;
  const onBoxRef = useRef(onBox);
  onBoxRef.current = onBox;
  // the frame's layout size in px (offset sizes: a FLIP's scale never skews it): the pins are placed in it
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const well = wellRef.current;
    const frame = frameRef.current;
    if (!well || !frame) return;
    const run = () => {
      const w = frame.offsetWidth;
      const h = frame.offsetHeight;
      setSize((s) => (s.w === w && s.h === h ? s : { w, h }));
      onBoxRef.current?.(w, well.clientWidth);
    };
    run();
    const ro = new ResizeObserver(run);
    ro.observe(well);
    ro.observe(frame);
    return () => ro.disconnect();
  }, [frameRef]);

  // the overlay belongs to the slide that is fully shown: on a turn the old one leaves in 80ms, the new one enters
  // once the new image has landed — remarks never float over the wrong slide
  const ready = !failed && shownSrc === src;
  const live = showRemarks && ready && remarks.length > 0 ? { key: src ?? "", remarks } : null;
  // the overlay that just went (the mode is off, or the slide on screen changed): it fades out, then unmounts. It is
  // derived in the render that drops the live one (state set while rendering), so the leaving layer is never removed
  // from the page for a commit and mounted again
  const [ghost, setGhost] = useState<{ key: string; remarks: StageRemark[]; fast: boolean } | null>(null);
  const [lastLive, setLastLive] = useState(live);
  if ((lastLive?.key ?? null) !== (live?.key ?? null) || (!!live && !!lastLive && live.remarks !== lastLive.remarks)) {
    if (lastLive && lastLive.key !== live?.key) setGhost({ key: lastLive.key, remarks: lastLive.remarks, fast: !!live || (showRemarks && lastLive.key !== src) });
    setLastLive(live);
  }
  useEffect(() => {
    if (!ghost) return;
    const t = window.setTimeout(() => setGhost(null), ghost.fast ? 90 : MOTION.fast + 10);
    return () => window.clearTimeout(t);
  }, [ghost]);
  // one list with stable keys: the overlay that leaves is the very node that was on screen (it fades out as it is, it
  // never remounts and replays its entrance)
  const layers: { key: string; remarks: StageRemark[]; leaving: "fast" | "normal" | false }[] = [];
  if (ghost && ghost.key !== live?.key) layers.push({ key: ghost.key, remarks: ghost.remarks, leaving: ghost.fast ? "fast" : "normal" });
  if (live) layers.push({ key: live.key, remarks: live.remarks, leaving: false });

  const work = usePresence(!!fixing, MOTION.fast);
  const lastLabel = useRef(fixing ?? "");
  if (fixing) lastLabel.current = fixing;

  const alt = `Слайд ${slide}${headline ? `: ${headline}` : ""}`;
  return (
    <div ref={wellRef} className="relative grid min-h-0 min-w-0 flex-1 place-items-center" style={{ containerType: "size" }}>
      <div
        ref={frameRef}
        data-stage-frame
        onClick={failed ? undefined : onZoom}
        className={cn(
          "relative overflow-hidden rounded-xl bg-white shadow-[0_1px_3px_rgba(0,16,61,0.08)] ring-1 transition-[box-shadow] duration-300",
          fixing ? "ring-2 ring-accent-300" : "ring-zinc-900/[0.08]",
          !failed && "cursor-zoom-in",
        )}
        style={{ aspectRatio: String(aspect), width: `min(100cqw, calc(100cqh * ${aspect.toFixed(4)}))` }}
      >
        {!failed && (
          <SlideImage src={src} alt={alt} dir={dir} mode={mode} onAspect={onAspect} onError={setFailedSrc} onReady={onReady} onShown={setShownSrc} />
        )}
        {failed && (
          <div className="absolute inset-0 flex animate-fade flex-col items-center justify-center gap-2 bg-zinc-50 px-8 text-center">
            <ImageOff className="h-6 w-6 text-zinc-400" aria-hidden />
            <span className="text-footnote text-zinc-500">Превью не сохранилось</span>
            {headline && <span className="max-w-md text-body font-semibold text-zinc-700">{headline}</span>}
          </div>
        )}
        {layers.map((l) => (
          <RemarksLayer
            key={`rl-${l.key}`}
            remarks={l.remarks}
            size={size}
            activeIds={activeIds}
            onActive={onActive}
            onPick={onPick}
            ping={l.leaving ? null : ping}
            fixingIds={fixing ? fixingIds : []}
            spotlight={!fixing}
            leaving={l.leaving}
          />
        ))}
        {resolved && ready && resolved.marks.length > 0 && <FixedMarks key={resolved.key} marks={resolved.marks} size={size} />}
        {work.mounted && <FixingLayer label={lastLabel.current} leaving={work.leaving} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// the stage header's right side

export interface RemarksSwitchState {
  /** The switch has its place in the header (some variant of the deck has remarks, or the mode is on). */
  show: boolean;
  /** It keeps its place but is not shown: this variant has no remarks and the mode is off. */
  hidden?: boolean;
  visible: boolean;
  count: number;
  tone: RemarkTone;
  onToggle(v: boolean): void;
}

/** The right side of the stage header: the «Замечания» switch, ‹ 3 / 10 › and full screen. The switch comes first, so
 *  the arrows never move. `compact`: a narrow stage keeps only the switch's track and count. */
export function SlideControls({ slide, total, canZoom, compact = false, tight = 0, onSelect, onZoom, remarks, rootRef }: {
  slide: number;
  total: number;
  canZoom: boolean;
  compact?: boolean;
  /** A stage too narrow for the whole header: 1 drops ⤢ (the slide opens full screen itself), 2 also «3 / 10». */
  tight?: 0 | 1 | 2;
  onSelect(n: number): void;
  onZoom(): void;
  remarks: RemarksSwitchState;
  rootRef?: RefObject<HTMLDivElement>;
}) {
  const countLabel = plural(remarks.count, "замечание", "замечания", "замечаний");
  return (
    <div ref={rootRef} className="ml-auto flex shrink-0 items-center gap-2">
      {remarks.show && (
        // a clean variant keeps the switch's room (the arrows never move) but shows nothing to switch on
        <span aria-hidden={remarks.hidden || undefined} className={cn("inline-flex transition-[opacity,visibility] duration-150", remarks.hidden && "invisible opacity-0")}>
          <Switch
            data-remarks=""
            checked={remarks.visible}
            onChange={remarks.onToggle}
            label="Замечания"
            hideLabel={compact}
            count={remarks.count}
            countLabel={countLabel}
            tone={remarks.tone}
          />
        </span>
      )}
      <div data-fixed className="flex items-center gap-1">
        <div className="inline-flex items-center gap-1">
          <Button variant="ghost" shape="circle" size="md" icon={ChevronLeft} aria-label="Предыдущий слайд" title="Предыдущий слайд (←)" disabled={slide <= 1} onClick={() => onSelect(slide - 1)} />
          {/* 44px holds «12 / 30»; the number swaps with a short rise, the total stays */}
          {tight < 2 && (
            <span className="w-11 text-center text-footnote tabular-nums text-zinc-700">
              <span key={slide} className="inline-block animate-fade-in">{slide}</span> / {total}
            </span>
          )}
          <Button variant="ghost" shape="circle" size="md" icon={ChevronRight} aria-label="Следующий слайд" title="Следующий слайд (→)" disabled={slide >= total} onClick={() => onSelect(slide + 1)} />
        </div>
        {tight < 1 && <Button variant="ghost" shape="circle" size="md" icon={Maximize2} aria-label="На весь экран" title="На весь экран" disabled={!canZoom} onClick={onZoom} />}
      </div>
    </div>
  );
}
