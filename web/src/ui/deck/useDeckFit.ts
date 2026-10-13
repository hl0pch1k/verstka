// Ширина колоды для того, что решает JS (сколько обложек в ленте, сколько колонок у раскадровки). Колода меряет себя
// сама (ResizeObserver) и раздаёт, какая она: широкая, узкая или тесная (fit.ts); CSS смотрит на ту же ширину через
// `@container deck`, с теми же порогами.
import { createContext, useContext, useLayoutEffect, useState, type RefObject } from "react";
import { deckFit, type DeckFit } from "./fit";

export const DeckFitContext = createContext<DeckFit>("wide");

/** Какая сейчас колода (внутри `Deck`). */
export function useDeckFit(): DeckFit {
  return useContext(DeckFitContext);
}

/** Меряет колоду: меняется, только когда она переходит порог (кадры хода сетки не перерисовывают плиты). */
export function useMeasureDeck(ref: RefObject<HTMLElement>): DeckFit {
  const [fit, setFit] = useState<DeckFit>("wide");
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setFit(deckFit(el.getBoundingClientRect().width));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return fit;
}
