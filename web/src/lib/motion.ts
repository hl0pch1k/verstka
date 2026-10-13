// Small JS helpers for motion; the animations themselves are CSS (styles/tokens.css: transform and opacity, the curve
// cubic-bezier(0.2, 0, 0, 1), 160/240/360/520 ms). Reduced motion: `smoothScroll` obeys it; `prefersReducedMotion` lets callers do the same.

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
