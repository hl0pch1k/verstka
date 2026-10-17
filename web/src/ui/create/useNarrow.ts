// Какая раскладка «Создать» сейчас на деле: узкая — помощник открыт и окно компьютерное, от 1280 px (уже — колода
// стопкой и не сужается: помощник — плита снизу поверх неё, ui/shell/tier.ts). По ней в стопках из двух копий (hp-tx)
// активна одна: её видит чтение с экрана и в неё ставится фокус, вторая — aria-hidden и без фокуса.
import { useApp } from "../../store";
import { helperBeside, useTier } from "../shell/tier";

/** Окно компьютерное (раскладка колоды и помощника рядом). */
export function useWideScreen(): boolean {
  return helperBeside(useTier());
}

/** Колода сужена помощником: активна узкая копия стопок. */
export function useNarrow(): boolean {
  const { ui } = useApp();
  const wide = useWideScreen();
  return ui.helper && wide;
}
