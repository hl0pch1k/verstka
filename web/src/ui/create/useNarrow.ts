// Какая раскладка «Создать» сейчас на деле: узкая — помощник открыт и окно шире 900 px (уже — колода не сужается,
// помощник встаёт под неё столбцом, create.css). По ней в стопках из двух копий (hp-tx) активна одна: её видит чтение с
// экрана и в неё ставится фокус, вторая — aria-hidden и без фокуса.
import { useEffect, useState } from "react";
import { useApp } from "../../store";

const WIDE = "(min-width: 901px)";

/** Окно шире 900 px (раскладка колоды и помощника рядом). */
export function useWideScreen(): boolean {
  const [wide, setWide] = useState(() => typeof window === "undefined" || !window.matchMedia || window.matchMedia(WIDE).matches);
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia(WIDE);
    const on = () => setWide(mq.matches);
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return wide;
}

/** Колода сужена помощником: активна узкая копия стопок. */
export function useNarrow(): boolean {
  const { ui } = useApp();
  const wide = useWideScreen();
  return ui.helper && wide;
}
