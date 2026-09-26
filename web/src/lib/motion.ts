// Motion tokens and two small hooks: a number that counts to its new value, and a presence flag for exit animations.
// Enters use MOTION.base, panels MOTION.slow, exits and hovers MOTION.fast (tailwind animations follow the same steps).
import { useEffect, useRef, useState } from "react";

export const MOTION = { fast: 150, base: 200, slow: 300 } as const;

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Animates (ease-out) from the last shown value to `target`; starts from 0 only on the first mount, so a switch
 *  between two scores moves the number and the ring directly instead of draining them. Reduced motion jumps. */
export function useCountUp(target: number | null, ms = 400): number | null {
  const [value, setValue] = useState<number | null>(target === null || reduced() ? target : 0);
  const shown = useRef<number | null>(value);
  shown.current = value;
  useEffect(() => {
    if (target === null || reduced()) return void setValue(target);
    const from = shown.current ?? 0;
    if (from === target) return;
    let raf = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      setValue(from + (target - from) * (1 - Math.pow(1 - t, 3)));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return value;
}

/** Keeps a closing element mounted for its exit animation: { mounted, leaving }. */
export function usePresence(open: boolean, ms: number = MOTION.fast): { mounted: boolean; leaving: boolean } {
  const [mounted, setMounted] = useState(open);
  useEffect(() => {
    if (open) return void setMounted(true);
    if (!mounted) return;
    if (reduced()) return void setMounted(false);
    const t = window.setTimeout(() => setMounted(false), ms);
    return () => window.clearTimeout(t);
  }, [open, mounted, ms]);
  return { mounted: open || mounted, leaving: !open && mounted };
}
