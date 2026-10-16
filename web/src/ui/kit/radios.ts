// Группа радиокнопок (role="radiogroup" из кнопок role="radio"): стрелки и Home/End переключают выбор и переводят на него
// фокус, в порядке Tab стоит только выбранная (roving tabindex) — как у радиокнопок браузера. Одна для чипов «Качества»
// и переключателя «При расхождении важнее» слоя «Брендбук».
import type { KeyboardEvent } from "react";

/** Какую кнопку выбрать по клавише: стрелки по кругу, Home — первую, End — последнюю; null — клавиша не про выбор. */
export function radioStep<T>(keys: readonly T[], current: T, key: string): T | null {
  const n = keys.length;
  if (!n) return null;
  const i = Math.max(0, keys.indexOf(current));
  if (key === "Home") return keys[0];
  if (key === "End") return keys[n - 1];
  const dir = key === "ArrowRight" || key === "ArrowDown" ? 1 : key === "ArrowLeft" || key === "ArrowUp" ? -1 : 0;
  return dir ? keys[(i + dir + n) % n] : null;
}

/** Обработчик клавиш для контейнера группы и tabIndex её кнопок. */
export function radioGroup<T>(keys: readonly T[], current: T, pick: (k: T) => void) {
  return {
    tabIndex: (k: T) => (k === current ? 0 : -1),
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
      const next = radioStep(keys, current, e.key);
      if (next === null) return;
      e.preventDefault();
      pick(next);
      const radios = e.currentTarget.querySelectorAll<HTMLElement>('[role="radio"]');
      radios[keys.indexOf(next)]?.focus({ preventScroll: true });
    },
  };
}
