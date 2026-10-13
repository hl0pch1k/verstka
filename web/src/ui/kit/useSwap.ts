// Перекрёстное затухание при смене раскладки: где меняется число элементов или колонок (обложки ленты, ряд параметров,
// колонки раскадровки, колонка компактного «Результата», сетки слоёв и листа «Подробнее»), старое гаснет за 120 мс,
// подменяется невидимым и новое проявляется за 240 мс. Классы `fx-out` / `fx-in` (base.css) ставятся на обёртку, у
// которой нет своей прозрачности. Что делает каждый шаг — чистая `swapNext` (swap.ts): начатое затухание доигрывает.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { swapNext, type SwapPhase, type SwapState } from "./swap";

export const SWAP_OUT = 120;
export const SWAP_IN = 240;
export type { SwapPhase };

/** Что показано (`shown` — до подмены прежнее) и фаза затухания; `live` — содержимое на виду: невидимое меняется
 *  сразу, без затухания (но начатое затухание доигрывает). До первого кадра (значение досчиталось при монтировании) —
 *  тоже сразу. */
export function useSwap<T extends string | number | boolean>(value: T, live = true): { shown: T; phase: SwapPhase; cls: string | undefined } {
  const [s, setS] = useState<SwapState<T>>(() => ({ shown: value, phase: null }));
  const painted = useRef(false);
  // конец затухания подменяет на значение этого момента (оно могло смениться ещё раз, пока гасло)
  const latest = useRef(value);
  latest.current = value;
  useEffect(() => {
    const raf = window.requestAnimationFrame(() => void (painted.current = true));
    return () => window.cancelAnimationFrame(raf);
  }, []);
  // в том же кадре, что и новое значение: невидимое подменяется до отрисовки
  useLayoutEffect(() => {
    setS((cur) => swapNext(cur, { type: "set", value, live, ready: painted.current && !prefersReducedMotion() }));
  }, [value, live]);
  // ход фазы — по её началу: новое значение посреди затухания его не продлевает
  const phase = s.phase;
  useEffect(() => {
    if (!phase) return;
    const t = window.setTimeout(
      () => setS((cur) => swapNext(cur, phase === "out" ? { type: "swap", value: latest.current } : { type: "end" })),
      phase === "out" ? SWAP_OUT : SWAP_IN,
    );
    return () => window.clearTimeout(t);
  }, [phase]);
  return { shown: s.shown, phase, cls: phase ? `fx-${phase}` : undefined };
}
