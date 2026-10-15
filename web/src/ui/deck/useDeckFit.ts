// Раскладка колоды для того, что решает JS и CSS на экранах, ещё не перенесённых на непрерывное перестроение
// (`data-fit` колоды и обёрток содержимого слоёв и листа «Подробнее», компактный «Результат»). Решение — по целевой
// ширине (fit.ts `deckLayout`): обёртка колоды (`hp-wrap`) не анимируется, колода = обёртка − место помощника. Открытие —
// узкая раскладка с первого кадра; закрытие — узкая держится, пока сетка обёртки не доехала (`transitionend` на
// grid-template-columns, запасной таймер — ход 340 мс + 40). Посреди хода раскладка не меняется. Слои меняют её
// перекрёстным затуханием своей обёртки (layers/Layer `useLayer`).
// «Создать» и «Сборка» этим не пользуются: их содержимое перестраивается вместе с колодой каждый кадр
// (ui/create/morph.ts, ui/build/columns.ts) и берёт отсюда только ширину обёртки (`useDeckWrap`) — по ней считаются обе
// раскладки сразу.
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

/** Ширина обёртки колоды (`hp-wrap`): колода при закрытом помощнике; 0 — ещё не измерена. Внутри `Deck` —
 *  `useDeckWrap`. */
export const DeckWrapContext = createContext(0);
export function useDeckWrap(): number {
  return useContext(DeckWrapContext);
}

/** Ширина обёртки колоды `ref` (её родителя): не анимируется — меняется только с окном. */
export function useWrapWidth(ref: RefObject<HTMLElement>): number {
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
  return wrap;
}

/** Раскладка колоды `ref` по ширине её обёртки `wrap` и помощнику (`helper` открыт). */
export function useDeckLayout(ref: RefObject<HTMLElement>, helper: boolean, wrap: number): DeckLayout {
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
