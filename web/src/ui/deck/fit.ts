// Ширина колоды: помощник сужает её на всех экранах (1440 → 976 px, 1280 → 816 px). «Создать», «Сборка», слои и лист
// «Подробнее» перестраиваются вместе с ней каждый кадр (ui/create/morph.ts, ui/build/columns.ts, ui/details/sheetMorph.ts;
// V2 версии 100) и отсюда ничего не берут. Здесь — раскладка по ЦЕЛЕВОЙ ширине колоды для «Результата» (его шапка
// `ra-whx` и подпись CTA компактного вида, ui/result/compact.ts): они меняются своим перекрёстным затуханием (useSwap),
// как в V2, а не вместе с колодой.
//
// Решение — по цели хода, а не по ширине на кадре: обёртка `hp-wrap` не анимируется, и колода = обёртка − место
// помощника (плита 400 + зазор 16). Открытие — узкая раскладка сразу; закрытие — узкая держится, пока сетка не доехала
// (`held`, useDeckFit.ts).

import { HELPER_COL, PLATE_PAD } from "./layout";

// result/compact.ts берёт PLATE_PAD отсюда; общий источник — ./layout (там и импортировать, тогда этот реэкспорт лишний).
export { PLATE_PAD };

/** Колода не шире — узкая (открыт помощник). */
const NARROW_DECK = 1100;
/** Колода не шире — тесная (открыт помощник при окне около 1280). */
const TIGHT_DECK = 900;
/** Закрытие помощника: ход сетки обёртки колоды (shell.css `.hp-wrap`, grid-template-columns 340 мс). */
export const HELPER_CLOSE_MS = 340;
/** Запасной таймер узкой раскладки при закрытии — на 40 мс позже конца хода: она снимается по `transitionend`, а таймер
 *  — только если события не было (переход прерван или не начался), и не раньше, чем сетка доехала. */
export const CLOSE_HOLD_MS = HELPER_CLOSE_MS + 40;

export type DeckFit = "wide" | "narrow" | "tight";

/** Какая колода по её ширине; 0 — ещё не измерена: широкая, как до помощника. */
export function deckFit(width: number): DeckFit {
  if (!(width > 0) || width > NARROW_DECK) return "wide";
  return width > TIGHT_DECK ? "narrow" : "tight";
}

/** Раскладка колоды: целевая ширина (0 — обёртка ещё не измерена) и какая это колода. */
export interface DeckLayout { width: number; fit: DeckFit }

/** Раскладка по ширине обёртки `wrap`: помощник открыт (`helper`) или ещё закрывается (`held` — сетка едет) — колода
 *  без его места. */
export function deckLayout(wrap: number, helper: boolean, held = false): DeckLayout {
  const width = wrap > 0 ? Math.max(0, wrap - (helper || held ? HELPER_COL : 0)) : 0;
  return { width, fit: deckFit(width) };
}
