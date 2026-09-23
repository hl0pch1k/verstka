// Small motion helpers: a number that counts up once it appears, honouring «reduce motion».
import { useEffect, useState } from "react";

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Animates 0 → target (ease-out) when the target changes; returns the value to show. */
export function useCountUp(target: number | null, ms = 700): number | null {
  const [value, setValue] = useState<number | null>(target === null || reduced() ? target : 0);
  useEffect(() => {
    if (target === null || reduced()) return void setValue(target);
    let raf = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      setValue(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return value;
}

/** Keeps a closing element mounted for its exit animation: { mounted, leaving }. */
export function usePresence(open: boolean, ms = 160): { mounted: boolean; leaving: boolean } {
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
