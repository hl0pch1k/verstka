// Motion tokens and helpers (MOTION_SPEC.md). One vocabulary for the whole app:
// - durations: instant 100 (press), fast 150 (exits, hovers), base 200 (small enters), slow 300 (panels, travel),
//   data 600 (numbers, rings, bars); stagger 40 ms capped at 6 items;
// - curves (the same strings as the CSS variables in index.css and the tailwind `ease-*` classes): arrivals decelerate
//   (out), departures accelerate (in), travel glides (glide), only small confirmations overshoot (spring);
// - reduced motion: instant, or a ≤ 120 ms opacity cross-fade (the `rm-fade` classes); every JS helper here obeys it.
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type RefObject } from "react";
import { flushSync } from "react-dom";

export const MOTION = { instant: 100, fast: 150, base: 200, slow: 300, data: 600, stagger: 40, staggerMax: 6 } as const;

export const EASE = {
  std: "cubic-bezier(0.2, 0, 0, 1)",
  out: "cubic-bezier(0.16, 1, 0.3, 1)",
  in: "cubic-bezier(0.4, 0, 1, 1)",
  inOut: "cubic-bezier(0.65, 0, 0.35, 1)",
  glide: "cubic-bezier(0.32, 0.72, 0, 1)",
  spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
} as const;

// ---------------------------------------------------------------------------------------------------------------------
// reduced motion

const RM_QUERY = "(prefers-reduced-motion: reduce)";
const rmList = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(RM_QUERY) : null);

/** The person asked the system for less motion (read live, at the moment of the call). */
export function prefersReducedMotion(): boolean {
  return rmList()?.matches ?? false;
}

function subscribeReduced(onChange: () => void): () => void {
  const mq = rmList();
  if (!mq) return () => {};
  mq.addEventListener?.("change", onChange);
  return () => mq.removeEventListener?.("change", onChange);
}

/** Live reduced-motion flag: re-renders when the system setting changes. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeReduced, prefersReducedMotion, () => false);
}

/** `behavior` for JS scrolls: CSS `scroll-behavior` does not reach `scrollTo({behavior:"smooth"})`. */
export function smoothScroll(): ScrollBehavior {
  return prefersReducedMotion() ? "auto" : "smooth";
}

/** Inline delay for the i-th item of a revealed list: 40 ms steps, items past `max` share the last delay. */
export function stagger(i: number, step: number = MOTION.stagger, max: number = MOTION.staggerMax): CSSProperties {
  const k = Math.min(Math.max(0, Math.floor(i)), max);
  return { animationDelay: `${k * step}ms` };
}

// ---------------------------------------------------------------------------------------------------------------------
// numbers

const expoOut = (t: number) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t));

export interface CountUpOptions {
  /** Duration of one move (default 400). */
  ms?: number;
  /** Wait before the first move after mount (a card's rise lands first); later moves start at once. */
  delay?: number;
  /** The first mount starts here instead of 0. */
  from?: number;
}

/** Animates (expo-out) from the last shown value to `target`. The first mount starts at 0 (or `from`), so a ring draws
 *  in; a later change moves directly from the value on screen, so a switch between two scores never drains the ring.
 *  Reduced motion or a hidden tab jumps. A number argument is the duration (old callers). */
export function useCountUp(target: number | null, opts?: number | CountUpOptions): number | null {
  const o: CountUpOptions = typeof opts === "number" ? { ms: opts } : opts ?? {};
  const ms = o.ms ?? 400;
  const [value, setValue] = useState<number | null>(() => (target === null || prefersReducedMotion() ? target : o.from ?? 0));
  const shown = useRef<number | null>(value);
  shown.current = value;
  // the delay holds until the first move really starts (StrictMode's mount → unmount → mount keeps it)
  const moved = useRef(false);
  const delay = useRef(o.delay ?? 0);
  useEffect(() => {
    const wait = moved.current ? 0 : delay.current;
    if (target === null || prefersReducedMotion() || (typeof document !== "undefined" && document.hidden)) {
      moved.current = true;
      return void setValue(target);
    }
    const from = shown.current ?? 0;
    if (from === target) return;
    let raf = 0;
    let start = 0;
    const step = (now: number) => {
      if (!start) start = now + wait;
      const t = Math.max(0, Math.min(1, (now - start) / ms));
      if (now >= start) {
        moved.current = true;
        setValue(t >= 1 ? target : from + (target - from) * expoOut(t));
      }
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return value;
}

// ---------------------------------------------------------------------------------------------------------------------
// presence

/** Keeps a closing element mounted for its exit animation: { mounted, leaving }. Under reduced motion the exit is the
 *  100 ms `rm-fade-out` cross-fade, so the element stays that long at most. */
export function usePresence(open: boolean, ms: number = MOTION.fast): { mounted: boolean; leaving: boolean } {
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) return void setMounted(true);
    if (!mounted) return;
    const t = window.setTimeout(() => setMounted(false), prefersReducedMotion() ? Math.min(ms, 100) : ms);
    return () => window.clearTimeout(t);
  }, [open, mounted, ms]);
  return { mounted: open || mounted, leaving: !open && mounted };
}

// ---------------------------------------------------------------------------------------------------------------------
// gliding indicators (Segmented thumb, tab underline, thumbnail ring)

export interface IndicatorOptions {
  /** Grow the box by this many px on every side (a ring drawn around the item: 4). */
  outset?: number;
}

export interface IndicatorBox { x: number; y: number; w: number; h: number }

export interface Indicator {
  /** Position it with `absolute left-0 top-0` inside the container (which is `relative`). */
  style: CSSProperties;
  /** A target was found and measured. */
  ready: boolean;
  /** The target's layout box in the container (outset applied), for an indicator that needs its own style (an
   *  underline: x and width only). */
  box: IndicatorBox | null;
  /** This position applies without a transition (first measurement, reduced motion): `transitionDuration: "0ms"`. */
  instant: boolean;
}

type Box = IndicatorBox;

/** The layout box of `el` relative to `container` (offsets, so transforms — a press scale, a FLIP — never skew it). */
function boxIn(el: HTMLElement, container: HTMLElement): Box {
  let x = 0;
  let y = 0;
  let node: HTMLElement | null = el;
  while (node && node !== container) {
    x += node.offsetLeft;
    y += node.offsetTop;
    const parent = node.offsetParent as HTMLElement | null;
    if (!parent || !container.contains(parent)) {
      // the container is not the offset parent (not positioned): fall back to the visual rects
      const r = el.getBoundingClientRect();
      const c = container.getBoundingClientRect();
      return { x: r.left - c.left + container.scrollLeft - container.clientLeft, y: r.top - c.top + container.scrollTop - container.clientTop, w: el.offsetWidth, h: el.offsetHeight };
    }
    if (parent !== container) {
      x += parent.clientLeft - parent.scrollLeft;
      y += parent.clientTop - parent.scrollTop;
    }
    node = parent;
  }
  return { x, y, w: el.offsetWidth, h: el.offsetHeight };
}

/** One indicator that glides to the item matching `selector` inside `container` (`_key`: the selected value, for the
 *  reader — the hook re-measures on every commit anyway). The first position (and any position
 *  under reduced motion) applies without a transition, so nothing slides in from the corner on mount. Re-measures on
 *  `key` changes, on size changes of the container or its children, and when the web fonts have loaded. */
export function useIndicator(container: RefObject<HTMLElement>, selector: string, _key: unknown, opts: IndicatorOptions = {}): Indicator {
  const outset = opts.outset ?? 0;
  const [box, setBox] = useState<{ b: Box | null; instant: boolean }>({ b: null, instant: true });
  const shown = useRef(box); // the last box handed to React: nothing is set (no render) while it stays the same
  const had = useRef(false);

  const measure = useRef<(snap?: boolean) => void>(() => {});
  measure.current = (snap = false) => {
    const c = container.current;
    const el = c?.querySelector<HTMLElement>(selector) ?? null;
    const b = c && el && el.offsetWidth > 0 ? boxIn(el, c) : null;
    const instant = snap || !had.current || prefersReducedMotion();
    had.current = !!b;
    const prev = shown.current;
    if (!prev.b && !b) return;
    if (prev.b && b && prev.b.x === b.x && prev.b.y === b.y && prev.b.w === b.w && prev.b.h === b.h && (prev.instant === instant || !instant)) return;
    const next = { b, instant };
    shown.current = next;
    setBox(next);
  };

  // every commit (cheap offset reads; nothing is set when nothing moved): a label that changed width moves the thumb
  // even when the key did not change
  useLayoutEffect(() => measure.current());

  useEffect(() => {
    const c = container.current;
    if (!c) return;
    const run = () => measure.current();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(run) : null;
    const observe = () => {
      if (!ro) return;
      ro.disconnect();
      ro.observe(c);
      // the items, not the absolutely positioned indicator (its size glides every frame and moves nothing)
      Array.from(c.children).forEach((ch) => getComputedStyle(ch).position !== "absolute" && ro.observe(ch));
    };
    observe();
    // children come and go (a list that grows): keep observing all of them
    const mo = typeof MutationObserver !== "undefined" ? new MutationObserver(() => { observe(); run(); }) : null;
    mo?.observe(c, { childList: true });
    let alive = true;
    // the web font swaps the text widths in once: snap to them, no glide on page load
    void document.fonts?.ready.then(() => alive && measure.current(true));
    return () => {
      alive = false;
      ro?.disconnect();
      mo?.disconnect();
    };
  }, [container]);

  const b = box.b;
  if (!b) return { style: { visibility: "hidden", width: 0, height: 0 }, ready: false, box: null, instant: true };
  return {
    ready: true,
    instant: box.instant,
    box: { x: b.x - outset, y: b.y - outset, w: b.w + outset * 2, h: b.h + outset * 2 },
    style: {
      transform: `translate3d(${b.x - outset}px, ${b.y - outset}px, 0)`,
      width: b.w + outset * 2,
      height: b.h + outset * 2,
      ...(box.instant ? { transitionDuration: "0ms" } : null),
    },
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// FLIP

const FLIP_ID = "flip";

function cancelFlip(el: Element) {
  el.getAnimations?.().forEach((a) => {
    if (a.id === FLIP_ID) a.cancel();
  });
}

/** When `key` changes, the element glides from the box it visibly had before the commit to the box the new layout gave
 *  it (translate, plus a scale with `scale: true`). The old box is read during render — the DOM still shows the old
 *  layout then — so an interrupted glide continues from where it visibly is. Transform only; nothing under reduced
 *  motion. */
export function useFlip(ref: RefObject<HTMLElement>, key: unknown, { scale = false, duration = MOTION.slow as number, easing = EASE.glide as string } = {}): void {
  const lastKey = useRef(key);
  const before = useRef<DOMRect | null>(null);
  if (key !== lastKey.current && ref.current && !before.current) before.current = ref.current.getBoundingClientRect();
  useLayoutEffect(() => {
    const el = ref.current;
    const was = before.current;
    const changed = lastKey.current !== key;
    lastKey.current = key;
    before.current = null;
    if (!el || !was || !changed || prefersReducedMotion()) return;
    cancelFlip(el);
    const now = el.getBoundingClientRect();
    if (now.width === 0 || was.width === 0) return;
    const dx = was.left - now.left;
    const dy = was.top - now.top;
    const s = scale ? was.width / now.width : 1;
    if (Math.abs(dx) <= 0.5 && Math.abs(dy) <= 0.5 && Math.abs(s - 1) <= 0.004) return;
    const from = `translate(${dx}px, ${dy}px)${scale ? ` scale(${s})` : ""}`;
    const a = el.animate([{ transformOrigin: "0 0", transform: from }, { transformOrigin: "0 0", transform: "none" }], { duration, easing });
    a.id = FLIP_ID;
  });
}

/** The current translateY of an element's computed transform (a running FLIP included). */
function currentY(el: HTMLElement): number {
  const t = getComputedStyle(el).transform;
  if (!t || t === "none") return 0;
  try {
    return new DOMMatrixReadOnly(t).m42;
  } catch {
    return 0;
  }
}

/** For lists that grow in the middle (the build timeline): when `key` changes, every `[data-flip]` item that moved
 *  glides from its previous place (translateY, 300 ms glide). Reads every position first, then writes. Items that are
 *  new have their own enter animation and are left alone. */
export function useFlipList(container: RefObject<HTMLElement>, selector: string = "[data-flip]", key: unknown, { duration = MOTION.slow as number, easing = EASE.glide as string } = {}): void {
  const lastKey = useRef(key);
  const before = useRef<Map<string, number> | null>(null);
  const read = (c: HTMLElement): Map<string, number> => {
    const top = c.getBoundingClientRect().top;
    const m = new Map<string, number>();
    c.querySelectorAll<HTMLElement>(selector).forEach((el) => {
      const id = el.dataset.flip ?? el.getAttribute("data-flip");
      if (id) m.set(id, el.getBoundingClientRect().top - top);
    });
    return m;
  };
  if (key !== lastKey.current && container.current && !before.current) before.current = read(container.current);
  useLayoutEffect(() => {
    const c = container.current;
    const was = before.current;
    const changed = lastKey.current !== key;
    lastKey.current = key;
    before.current = null;
    if (!c || !was || !changed || prefersReducedMotion()) return;
    const items = Array.from(c.querySelectorAll<HTMLElement>(selector));
    // reads: the new layout box of each item (its running FLIP removed from the measurement)
    const top = c.getBoundingClientRect().top;
    const moves: { el: HTMLElement; dy: number }[] = [];
    for (const el of items) {
      const id = el.dataset.flip ?? el.getAttribute("data-flip");
      if (!id || !was.has(id)) continue;
      const nowTop = el.getBoundingClientRect().top - top - currentY(el);
      const dy = (was.get(id) as number) - nowTop;
      if (Math.abs(dy) > 0.5) moves.push({ el, dy });
    }
    // writes
    for (const { el, dy } of moves) {
      cancelFlip(el);
      const a = el.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration, easing });
      a.id = FLIP_ID;
    }
  });
}

/** Animates `el` from (or, with `reverse`, back to) the viewport rect `rect`: a translate + scale about the top-left
 *  corner (the lightbox grows out of the stage slide and shrinks back into it). Returns null under reduced motion. */
export function flipFromRect(el: HTMLElement, rect: DOMRect | DOMRectReadOnly, { duration = MOTION.slow as number, easing = EASE.glide as string, reverse = false } = {}): Animation | null {
  if (prefersReducedMotion() || !el.animate) return null;
  cancelFlip(el);
  const now = el.getBoundingClientRect();
  if (!now.width || !now.height || !rect.width || !rect.height) return null;
  const sx = rect.width / now.width;
  const sy = rect.height / now.height;
  const there = { transformOrigin: "0 0", transform: `translate(${rect.left - now.left}px, ${rect.top - now.top}px) scale(${sx}, ${sy})` };
  const here = { transformOrigin: "0 0", transform: "none" };
  const a = el.animate(reverse ? [here, there] : [there, here], { duration, easing, fill: reverse ? "forwards" : "none" });
  a.id = FLIP_ID;
  return a;
}

// ---------------------------------------------------------------------------------------------------------------------
// screen changes

interface VTHandle { finished: Promise<void>; ready?: Promise<void>; updateCallbackDone?: Promise<void> }
type VTDocument = Document & { startViewTransition?: (arg: (() => void) | { update: () => void; types?: string[] }) => VTHandle };

/** The browser can cross-fade two DOM states (View Transitions API). */
export const supportsViewTransitions = typeof document !== "undefined" && typeof (document as VTDocument).startViewTransition === "function";

/** Transition types (`:active-view-transition-type()`) are known to the browser. */
const supportsVTTypes = (() => {
  try {
    return typeof CSS !== "undefined" && CSS.supports("selector(:active-view-transition-type(through))");
  } catch {
    return false;
  }
})();

let vtRunning = false;

export interface ViewTransitionOptions {
  /** Two unrelated screens (create → build, a deck → its rebuild): a fade-through — the old page clears in 90 ms,
   *  the new one fades and rises in just after it, so the two never print over each other. Without it the new page
   *  fades in over the old one and the named parts morph (build → deck). */
  through?: boolean;
}

/** Applies a screen change inside a View Transition: the old DOM is captured first, then `update` commits synchronously
 *  (flushSync). No API, reduced motion, or a transition already running → a plain update (the running transition shows
 *  the live new state anyway). The owner of the switch keeps rendering the old screen until it calls this. */
export function viewTransition(update: () => void, opts: ViewTransitionOptions = {}): void {
  const doc = document as VTDocument;
  if (!doc.startViewTransition || prefersReducedMotion() || vtRunning || document.hidden) return update();
  vtRunning = true;
  const root = document.documentElement;
  // the type: a transition type where the browser has them, else an attribute on <html> for the length of the transition
  const flag = opts.through && !supportsVTTypes;
  if (flag) root.dataset.vt = "through";
  const run = () => flushSync(update);
  try {
    const vt = opts.through && supportsVTTypes ? doc.startViewTransition({ update: run, types: ["through"] }) : doc.startViewTransition(run);
    // a skipped transition rejects `ready`: the update has still run, nothing to report
    vt.ready?.catch(() => {});
    vt.updateCallbackDone?.catch(() => {});
    void vt.finished.catch(() => {}).finally(() => {
      vtRunning = false;
      if (flag) delete root.dataset.vt;
    });
  } catch {
    vtRunning = false;
    if (flag) delete root.dataset.vt;
    update();
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// images

const decoded = new Set<string>();
const decoding = new Map<string, Promise<void>>();

/** Resolves once the image is loaded and decoded, so it can be shown on the next frame without a blank paint. Cached:
 *  a src decoded before (a preloaded neighbour) resolves at once. Rejects when the image fails to load. */
export function decodeImage(src: string): Promise<void> {
  if (decoded.has(src)) return Promise.resolve();
  const running = decoding.get(src);
  if (running) return running;
  const p = new Promise<void>((resolve, reject) => {
    const img = new Image();
    img.decoding = "async";
    let settled = false;
    const ok = () => {
      if (settled) return;
      settled = true;
      decoded.add(src);
      resolve();
    };
    const fail = () => {
      if (settled) return;
      settled = true;
      reject(new Error(`image failed: ${src}`));
    };
    img.onerror = fail;
    img.src = src;
    if (typeof img.decode === "function") {
      img.decode().then(ok, () => {
        // decode() rejects for some valid images (and for detached ones in old engines): fall back to load
        if (img.complete && img.naturalWidth > 0) ok();
        else img.onload = ok;
      });
    } else {
      img.onload = ok;
    }
  }).finally(() => decoding.delete(src));
  decoding.set(src, p);
  return p;
}

/** The src was decoded before (a synchronous check for a first paint without a fade). */
export function isDecoded(src: string): boolean {
  return decoded.has(src);
}
