// Ширина колоды для её содержимого. Всё, что перестраивается вместе с колодой каждый кадр («Создать», «Сборка», слои,
// лист «Подробнее»: ui/create/morph.ts, ui/build/columns.ts, ui/details/sheetMorph.ts), берёт отсюда только ширину
// обёртки (`useDeckWrap`) — по ней считаются обе раскладки сразу. Раскладку по целевой ширине (fit.ts `deckLayout`:
// открытие — узкая с первого кадра; закрытие — узкая держится, пока сетка обёртки не доехала, `transitionend` на
// grid-template-columns, запасной таймер — ход 340 мс + 40) читает только «Результат» (`useDeckFit`, `useDeckWidth`).
// Содержимое колоды встаёт сразу в настоящей ширине обёртки (`useWrapWidth`, Deck.tsx): при загрузке ничего не едет.
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState, type RefObject } from "react";
import { prefersReducedMotion } from "../../lib/motion";
import { CLOSE_HOLD_MS, deckLayout, type DeckFit, type DeckLayout } from "./fit";
import { layoutWidth } from "../shell/stage";

export const DeckFitContext = createContext<DeckLayout>({ width: 0, fit: "wide" });

/** Какая сейчас колода (внутри `Deck`): широкая, узкая или тесная. */
export function useDeckFit(): DeckFit {
  return useContext(DeckFitContext).fit;
}

/** Целевая ширина колоды (0 — ещё не измерена). */
export function useDeckWidth(): number {
  return useContext(DeckFitContext).width;
}

/** Ширина обёртки колоды (`hp-wrap`): колода при закрытом помощнике. Содержимое колоды встаёт уже после замера
 *  (`Deck`), так что внутри неё ширина всегда настоящая; 0 — только вне `Deck`. Внутри `Deck` — `useDeckWrap`. */
export const DeckWrapContext = createContext(0);
export function useDeckWrap(): number {
  return useContext(DeckWrapContext);
}

/** Ширина обёртки колоды `ref` (её родителя): не анимируется — меняется только с окном. `null` — ещё не измерена:
 *  первая отрисовка, колоды ещё нет в документе. Замер — в том же кадре, до первой отрисовки страницы; тот же замер
 *  потом сообщает ResizeObserver (ширина рамки, с полосой прокрутки окна, если она есть). До вставки ширину не угадать:
 *  в пустом документе ещё нет полосы прокрутки, а с колодой она появится (классическая полоса — 1232 вместо 1217 при
 *  1280), и то, что встало в угаданной ширине, поехало бы к настоящей своим ходом. */
export function useWrapWidth(ref: RefObject<HTMLElement>): number | null {
  const [wrap, setWrap] = useState<number | null>(null);
  useLayoutEffect(() => {
    const el = ref.current?.parentElement;
    if (!el) {
      setWrap(0); // мерить нечего — содержимое встаёт как есть
      return;
    }
    const measure = () => setWrap(Math.round(layoutWidth(el)));
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
