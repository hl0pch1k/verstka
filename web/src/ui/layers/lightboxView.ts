// Просмотр «На весь экран» без React (boards/R-lightbox, V2 `rtLb*`): счётчик «N / M · заголовок», стрелки, которых нет
// на краях, клавиши и ширина кадра. Листание — тот же текущий слайд, что у результата (`selectedSlide`).
import { slideForKey } from "../result/resultView";

const clamp = (n: number, total: number) => Math.min(Math.max(1, n), Math.max(1, total));

/** Шапка и стрелки просмотра: «3 / 12», заголовок слайда (пусто — null), есть ли куда листать назад и вперёд. */
export function lbView(n: number, total: number, headline: string): { count: string; title: string | null; prev: boolean; next: boolean } {
  const k = clamp(n, total);
  return { count: `${k} / ${Math.max(1, total)}`, title: headline.trim() || null, prev: k > 1, next: k < total };
}

/** Клавиша просмотра: ←/→ — соседний слайд, Home/End — первый и последний (в пределах 1…M), Esc — закрыть; чужая — null. */
export function lbKey(key: string, n: number, total: number): number | "close" | null {
  if (key === "Escape") return "close";
  return slideForKey(key, clamp(n, total), total);
}

/** Ширина кадра (V2 `lb-frame` 1120 × 630): высота места 630, ширина — по пропорциям шаблона, но не шире места между
 *  стрелками (по 48 + 40 с каждой стороны). */
export function lbFrameWidth(aspect: number): string {
  const ar = aspect > 0 ? aspect : 16 / 9;
  return `min(${Math.round(630 * ar)}px, calc(100% - 176px))`;
}
