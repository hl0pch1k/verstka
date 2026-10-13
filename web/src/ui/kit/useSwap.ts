// Перекрёстное затухание при смене раскладки: где меняется число элементов (обложки ленты, ряд параметров, колонки
// раскадровки, колонка компактного «Результата»), старое гаснет за 120 мс, подменяется невидимым и новое проявляется за
// 240 мс. Классы `fx-out` / `fx-in` (base.css) ставятся на обёртку, у которой нет своей прозрачности.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../../lib/motion";

export const SWAP_OUT = 120;
export const SWAP_IN = 240;
export type SwapPhase = "out" | "in" | null;

/** Что показано (`shown` — до подмены прежнее) и фаза затухания; `live` — содержимое на виду: невидимое меняется
 *  сразу, без затухания. До первого кадра (значение досчиталось при монтировании) — тоже сразу. */
export function useSwap<T extends string | number | boolean>(value: T, live = true): { shown: T; phase: SwapPhase; cls: string | undefined } {
  const [shown, setShown] = useState(value);
  const [phase, setPhase] = useState<SwapPhase>(null);
  const painted = useRef(false);
  useEffect(() => {
    const raf = window.requestAnimationFrame(() => void (painted.current = true));
    return () => window.cancelAnimationFrame(raf);
  }, []);
  useLayoutEffect(() => {
    if (value === shown) {
      // вернулось то, что показано, пока оно гасло, — проявляется обратно
      setPhase((p) => (p === "out" ? "in" : p));
      return;
    }
    if (!live || !painted.current || prefersReducedMotion()) {
      setShown(value);
      setPhase(null);
      return;
    }
    setPhase("out");
    const t = window.setTimeout(() => {
      setShown(value);
      setPhase("in");
    }, SWAP_OUT);
    return () => window.clearTimeout(t);
  }, [value, shown, live]);
  useEffect(() => {
    if (phase !== "in") return;
    const t = window.setTimeout(() => setPhase(null), SWAP_IN);
    return () => window.clearTimeout(t);
  }, [phase]);
  return { shown, phase, cls: phase ? `fx-${phase}` : undefined };
}
