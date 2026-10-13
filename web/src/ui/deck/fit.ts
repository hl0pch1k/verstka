// Ширина колоды: помощник сужает её на всех экранах (1440 → 976 px, 1280 → 816 px), и содержимое плит и слоёв
// перестраивается под неё. Пороги — общие для CSS (`@container deck`, shell.css) и для того, что решает JS (сколько
// обложек в ленте, сколько колонок у раскадровки): закрытый помощник даёт колоду не уже 1232 px (окно от 1280),
// открытый — не шире 976.

/** Колода не шире — узкая (открыт помощник). */
export const NARROW_DECK = 1100;
/** Колода не шире — тесная (открыт помощник при окне около 1280). */
export const TIGHT_DECK = 900;

export type DeckFit = "wide" | "narrow" | "tight";

/** Какая колода по её ширине; 0 — ещё не измерена: широкая, как до помощника. */
export function deckFit(width: number): DeckFit {
  if (!(width > 0) || width > NARROW_DECK) return "wide";
  return width > TIGHT_DECK ? "narrow" : "tight";
}

/** Лента шага 01: в широкой колоде — шесть обложек в четыре колонки (C-templates), в узкой — четыре в три, и с
 *  «Все шаблоны» и «Загрузить свой» это те же два ряда. */
export function ribbonLayout(fit: DeckFit): { covers: number; cols: number } {
  return fit === "wide" ? { covers: 6, cols: 4 } : { covers: 4, cols: 3 };
}
