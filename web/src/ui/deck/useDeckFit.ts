// Раскладка колоды для того, что решает JS и CSS на экранах, ещё не перенесённых на непрерывное перестроение (колонки
// раскадровки, `data-fit` колоды и обёрток содержимого «Сборки», слоёв и листа «Подробнее»). Решение — по целевой
// ширине (fit.ts `deckLayout`): обёртка колоды (`hp-wrap`) не анимируется, колода = обёртка − место помощника. Открытие —
// узкая раскладка с первого кадра; закрытие — узкая держится, пока сетка обёртки не доехала (`transitionend` на
// grid-template-columns, запасной таймер — ход 340 мс + 40). Посреди хода раскладка не меняется. Содержимое плиты
// «Сборки» меняет её перекрёстным затуханием (`usePlateFit`) и внутри себя видит показанную раскладку — вложенный
// DeckFitContext; слои — своим (layers/Layer `useLayer`).
// «Создать» этим не пользуется: его содержимое перестраивается вместе с колодой каждый кадр (ui/create/morph.ts) и
// берёт отсюда только ширину обёртки (`useDeckWrap`) — по ней считаются обе раскладки сразу.
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { useSwap, type SwapPhase } from "../kit/useSwap";
import { CLOSE_HOLD_MS, deckLayout, layoutKey, type DeckFit, type DeckLayout } from "./fit";

export const DeckFitContext = createContext<DeckLayout>({ width: 0, fit: "wide" });

/** Какая сейчас колода (внутри `Deck`): широкая, узкая или тесная. */
export function useDeckFit(): DeckFit {
  return useContext(DeckFitContext).fit;
}

/** Целевая ширина колоды (0 — ещё не измерена). */
export function useDeckWidth(): number {
  return useContext(DeckFitContext).width;
}

/** Раскладка колоды целиком (ширина и какая она). */
export function useDeckLayoutNow(): DeckLayout {
  return useContext(DeckFitContext);
}

/** Раскладка содержимого плиты по раскладке колоды `now`: сменилась (`layoutKey` — любое решение по ширине) — содержимое
 *  гаснет 120 мс, подменяется невидимым и проявляется 240 мс (useSwap, `cls` — класс обёрток затухания), пока оно на
 *  виду (`live`); невидимое — сразу. `layout` — показанная раскладка (до подмены — прежняя, с её шириной): её отдают
 *  вложенному DeckFitContext, по её `fit` ставят `data-fit` обёрток, по её ширине — ширину содержимого (fit.ts
 *  `plateWidth`). `phase` — идёт ли подмена: внутренние затухания (колонки раскадровки) в ней меняются сразу. */
export function usePlateFit(now: DeckLayout, live: boolean): { layout: DeckLayout; cls: string | undefined; phase: SwapPhase } {
  const key = layoutKey(now.width);
  const s = useSwap(key, live);
  // последняя раскладка каждого ключа: показанный ключ — с той шириной, что была у него
  const seen = useRef<Map<string, DeckLayout> | null>(null);
  if (!seen.current) seen.current = new Map();
  seen.current.set(key, now);
  return { layout: seen.current.get(s.shown) ?? now, cls: s.cls, phase: s.phase };
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
