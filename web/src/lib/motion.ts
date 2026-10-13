// Small JS helpers for motion; the animations themselves are CSS (styles/tokens.css: transform and opacity, the curve
// cubic-bezier(0.2, 0, 0, 1), 160/240/360/520 ms). Reduced motion: every helper here obeys it.
import { useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------------------------------------------------
// reduced motion

const RM_QUERY = "(prefers-reduced-motion: reduce)";
const rmList = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(RM_QUERY) : null);

/** The person asked the system for less motion (read live, at the moment of the call). */
export function prefersReducedMotion(): boolean {
  return rmList()?.matches ?? false;
}

/** `behavior` for JS scrolls: CSS `scroll-behavior` does not reach `scrollTo({behavior:"smooth"})`. */
export function smoothScroll(): ScrollBehavior {
  return prefersReducedMotion() ? "auto" : "smooth";
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
