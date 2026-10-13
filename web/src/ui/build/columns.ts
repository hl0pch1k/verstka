// Колонки раскадровки без React (Storyboard `useColumns`). Колонок столько, чтобы все слайды были видны (lib/stage
// fitColumns), не меньше четырёх, пока карточка не уже 150 px (в тесной колоде — 112).
//
// Помощник сужает колоду ходом сетки (520 мс, закрытие 340): по живой ширине колонки мигали бы посреди хода
// (4 → 5 → 4 → 3). Содержимое плиты стоит в ширине колоды на конец хода (ui/deck/fit `plateWidth`, BuildPlate), поэтому
// список на всём ходу одной ширины и колонки стоят; сменилась раскладка — в подмене перекрёстного затухания.
import { BOARD_GAP, fitColumns } from "../../lib/stage";

/** Самая узкая карточка доски. */
export const MIN_CARD = 150;
/** Самая узкая карточка в тесной колоде (помощник при 1280). */
export const TIGHT_CARD = 112;

/** Колонки списка шириной `w` и высотой `h` для `n` слайдов с пропорциями `aspect`; не измерен — четыре. */
export function boardColumns(w: number, h: number, n: number, aspect: number, minCard: number): number {
  if (!(w > 0)) return 4;
  // четыре колонки доски, пока карточка не уже minCard; больше — когда иначе все слайды не видны
  const base = [4, 3, 2].find((c) => (w - (c - 1) * BOARD_GAP) / c >= minCard) ?? 1;
  return Math.max(base, fitColumns(w, h - 8, n, aspect));
}
