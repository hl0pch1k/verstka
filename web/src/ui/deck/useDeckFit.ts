// Раскладка колоды для того, что решает JS и CSS (обложки ленты, колонки раскадровки, короткий ряд, правила
// `.p2-deck[data-fit=…]`). Решение — по целевой ширине (fit.ts `deckLayout`): обёртка колоды (`hp-wrap`) не
// анимируется, колода = обёртка − место помощника. Открытие — узкая раскладка с первого кадра; закрытие — узкая
// держится, пока сетка обёртки не доехала (`transitionend` на grid-template-columns, запасной таймер — ход 340 мс + 40).
// Посреди хода раскладка не меняется.
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState, type RefObject } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { CLOSE_HOLD_MS, deckLayout, type DeckFit, type DeckLayout } from "./fit";

export const DeckFitContext = createContext<DeckLayout>({ width: 0, fit: "wide" });

/** Какая сейчас колода (внутри `Deck`): широкая, узкая или тесная. */
export function useDeckFit(): DeckFit {
  return useContext(DeckFitContext).fit;
}

/** Целевая ширина колоды (0 — ещё не измерена). */
export function useDeckWidth(): number {
  return useContext(DeckFitContext).width;
}

/** Раскладка колоды `ref` по ширине её обёртки и помощнику (`helper` открыт). */
export function useDeckLayout(ref: RefObject<HTMLElement>, helper: boolean): DeckLayout {
  const [wrap, setWrap] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current?.parentElement;
    if (!el) return;
    const measure = () => setWrap(Math.round(el.getBoundingClientRect().width));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  // помощник закрылся — узкая раскладка держится до конца хода сетки (в том же кадре, что и смена класса обёртки)
  const [held, setHeld] = useState(false);
  const [was, setWas] = useState(helper);
  if (was !== helper) {
    setWas(helper);
    setHeld(!helper && !prefersReducedMotion());
  }
  useEffect(() => {
    if (!held) return;
    const el = ref.current?.parentElement;
    const end = () => setHeld(false);
    const onEnd = (e: TransitionEvent) => {
      if (e.target === el && e.propertyName === "grid-template-columns") end();
    };
    el?.addEventListener("transitionend", onEnd);
    const t = window.setTimeout(end, CLOSE_HOLD_MS);
    return () => {
      el?.removeEventListener("transitionend", onEnd);
      window.clearTimeout(t);
    };
  }, [held, ref]);
  return useMemo(() => deckLayout(wrap, helper, held), [wrap, helper, held]);
}
