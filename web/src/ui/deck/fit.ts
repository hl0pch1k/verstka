// Ширина колоды: помощник сужает её на всех экранах (1440 → 976 px, 1280 → 816 px), и содержимое плит и слоёв
// перестраивается под неё. Все пороги — здесь: и для CSS (колода ставит `data-fit` и `--deck-w`, плиты — свои data- и
// классы), и для того, что решает JS (сколько обложек в ленте, колонок у раскадровки, какой короткий ряд).
//
// Решение принимается по ЦЕЛЕВОЙ ширине колоды, а не по ширине на кадре хода: обёртка `hp-wrap` не анимируется, и
// колода = обёртка − место помощника (плита 400 + зазор 16). Открытие — узкая раскладка сразу; закрытие — узкая
// держится, пока сетка не доехала (`held`). Содержимое плит и слоёв меняет раскладку перекрёстным затуханием (гаснет,
// подменяется невидимым, проявляется); у плит «Создать» и «Сборки» оно ещё и стоит в ширине колоды на конец хода
// (`plateWidth`) — посреди хода в нём ничего не перестраивается и не переносится.

/** Колода не шире — узкая (открыт помощник). */
export const NARROW_DECK = 1100;
/** Колода не шире — тесная (открыт помощник при окне около 1280). */
export const TIGHT_DECK = 900;
/** Место помощника в обёртке колоды: плита 400 + зазор 16 (shell.css `.hp-wrap.hp-nar`). */
export const HELPER_COL = 416;
/** Поля плиты (48 + 48): содержимое плиты уже колоды на столько. */
export const PLATE_PAD = 96;
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

/** Ширина содержимого плиты в колоде шириной `deck` (без полей 48 + 48); null — колода не измерена (содержимое
 *  резиновое). Содержимое плит «Создать» и «Сборки» стоит в ширине колоды на конец хода: колода сужается или
 *  расширяется, а оно не перестраивается — край плиты подъезжает к нему или отъезжает. */
export function plateWidth(deck: number): number | null {
  return deck > 0 ? deck - PLATE_PAD : null;
}

/** Лента шага 01: в широкой колоде — шесть обложек в четыре колонки (C-templates), в узкой — четыре в три, и с
 *  «Все шаблоны» и «Загрузить свой» это те же два ряда. */
export function ribbonLayout(fit: DeckFit): { covers: number; cols: number } {
  return fit === "wide" ? { covers: 6, cols: 4 } : { covers: 4, cols: 3 };
}

// ── Плита 03 уже доски (окно около 1280 и закрытый помощник; раньше — `@container p3`): ширина её содержимого — колода
// без полей. Те же пороги, только от целевой ширины.
const plate = (deck: number) => deck - PLATE_PAD;
/** Варианту в коротком ряду нужно 173 px: при плите не шире — переключатели уходят в «Все параметры». */
const ROW_SWITCHES = 1254;
/** Сводке тесно для строки ошибки: строка встаёт под ряд заголовка. */
const ERR_BELOW = 1289;
/** Сегментам вариантов со словами («Структурный ✓ продумано») тесно рядом с «Раскадровкой»: остаются галочки. */
const SEG_STATUS = 1263;
/** «Это тема — агент напишет полный текст: ключевые факты, даты, формулы…» целиком не помещается (колода 1232). */
const HINT_TAIL = 1300;

/** Короткий ряд «Параметры и запуск»: `full` — степпер, варианты и переключатели (доска); `short` — без переключателей
 *  (они в «Все параметры»); `narrow` — степпер 200, варианты названием в строку; `tight` — степпер и варианты одной
 *  коробкой-списком. */
export type RowMode = "full" | "short" | "narrow" | "tight";
export function rowMode(width: number): RowMode {
  const fit = deckFit(width);
  if (fit !== "wide") return fit;
  return width > 0 && plate(width) <= ROW_SWITCHES ? "short" : "full";
}
/** Строка ошибки плиты 03 — под рядом заголовка (не на месте сводки). */
export const errBelow = (width: number): boolean => width > 0 && plate(width) <= ERR_BELOW;
/** Подписи хода в сегментах раскадровки помещаются. */
export const segStatus = (width: number): boolean => !(width > 0 && plate(width) <= SEG_STATUS);
/** Подсказка «Это тема…» помещается с перечнем. */
export const hintTail = (width: number): boolean => !(width > 0 && width <= HINT_TAIL);

/** Ключ раскладки плит при колоде шириной `width`: все решения по ширине (колода, короткий ряд, строка ошибки, подсказка
 *  «Это тема…», сегменты раскадровки). Содержимое плиты меняет раскладку перекрёстным затуханием, только когда меняется
 *  ключ, а не на каждом пикселе ширины. */
export function layoutKey(width: number): string {
  return [deckFit(width), rowMode(width), errBelow(width) ? "err-below" : "err-side", hintTail(width) ? "tail" : "short", segStatus(width) ? "seg-words" : "seg-ticks"].join("|");
}
