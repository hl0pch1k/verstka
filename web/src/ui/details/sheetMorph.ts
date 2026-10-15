// Лист «Подробнее» в колоде, суженной помощником (V2 версии 100, details.css): какая раскладка у листа — решается по
// ширине обёртки колоды (меняется только с окном, посреди хода — нет). При полной колоде (окно от 1440) — дорожки V2;
// у́же (тесная колода) V2 не помещается — свои дорожки (`dd-tight`, details.css «Тесная колода»).
import { createContext } from "react";
import { HELPER_COL, SHEET_PAD } from "../deck/layout";

/** Содержимое листа в узкой раскладке у́же — тесная колода. Дорожки V2 рассчитаны на 880 — полную колоду (окно от 1440,
 *  обёртка не шире 1392), у́же они не помещаются. Полоса «Шаблона»: факты, шрифт и палитра — 712 px с зазорами, названию
 *  остаётся содержимое − 760 («VK Tech» — 113 px; при окне 1366 (806) — 46 px, «V…»); подпись макета — (содержимое −
 *  520) / 3 («Карточки слайд 7» — 119 px, встаёт с 877). Тело ряда «Плана» — содержимое − 684 (при 1366 — 122 px:
 *  пункты в колонках по 11 px). При 1280 (720, с полосой прокрутки — 705) не помещаются и ряд вкладок с меню и ✕ (761
 *  при плотности V2), колонки «Качества» и «Агента», ряды «Файлов». */
export const TIGHT_INNER = 880;

/** «Файлы»: доля правой колонки в узкой раскладке (V2: 50 % → 44,09 %, 380 px при 1440; тесная колода — 40 %). */
export const FILES_RIGHT = 0.4409;
export const FILES_RIGHT_TIGHT = 0.4;

export interface SheetMorph {
  /** Тесная колода. */
  tight: boolean;
  /** Ширина содержимого листа в узкой раскладке, px (0 — обёртка не измерена). */
  inner: number;
  /** Ширина обёртки колоды, px. */
  wrap: number;
}

/** Раскладка листа — для вкладок (ставит DetailsSheet). */
export const SheetCtx = createContext<SheetMorph>({ tight: false, inner: 0, wrap: 0 });

const r3 = (x: number) => Math.round(x * 1000) / 1000;

export function sheetMorph(wrap: number): SheetMorph {
  const inner = wrap > 0 ? wrap - HELPER_COL - SHEET_PAD : 0;
  return { tight: inner > 0 && inner < TIGHT_INNER, inner, wrap };
}

export interface FilesCols {
  /** Правая колонка в широкой и узкой раскладке, px (V2: 50 % − 8 и 44,09 % − 8 — доли от ширины сетки, которая сама
   *  сужается: ход доли по сужающейся ширине не линеен, и колонка шла бы не в такт колоде). 0 — не измерена. */
  wide: number;
  narrow: number;
  /** «Паспорт запуска»: на сколько у́же колонка факта в узкой раскладке (`--hpd` стопки f-fact). */
  fact: number;
}

/** «Файлы»: дорожки по ширине обёртки колоды и полосе прокрутки вкладки (`scrollbar`, px: обычная полоса — 15, накладная
 *  — 0): сетка у́же листа на её ширину, и доли V2 считаются от неё. */
export function filesCols(m: SheetMorph, scrollbar = 0): FilesCols {
  if (!(m.inner > 0)) return { wide: 0, narrow: 0, fact: 0 };
  const wide = r3(0.5 * (m.wrap - SHEET_PAD - scrollbar) - 8);
  const narrow = r3((m.tight ? FILES_RIGHT_TIGHT : FILES_RIGHT) * (m.inner - scrollbar) - 8);
  return { wide, narrow, fact: r3((wide - narrow) / 2) };
}

/** CSS-переменные сетки «Файлов»: дорожки в px. */
export function filesVars(f: FilesCols): Record<string, string> {
  return f.wide > 0 ? { "--dfw": `${f.wide}px`, "--dfn": `${f.narrow}px` } : {};
}

/** «Качество», сводка: на сколько у́же колонка заголовка и строки счёта в узкой раскладке (`--hpd` её стопки). Колода
 *  сужается на 416; справа в узкой раскладке уходят «Исправить всё автоматически» (`allw` — ширина кнопки, и зазор 16),
 *  значок у «Исправить отмеченные» (20 и зазор кнопки 12) и в тесной колоде слово «отмеченные» (`word`). */
export function sumNarrowing({ allw, cta, word }: { allw: number | null; cta: boolean; word: number }): number {
  return HELPER_COL - (allw === null ? 0 : allw + 16) - (cta ? 32 + word : 0);
}
