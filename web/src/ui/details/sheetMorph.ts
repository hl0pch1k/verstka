// Лист «Подробнее» в колоде, суженной помощником (V2 версии 100, details.css): какая раскладка у листа — решается по
// ширине обёртки колоды (меняется только с окном, посреди хода — нет). При 1440 — дорожки V2; при окне около 1280
// (тесная колода) V2 не помещается — свои дорожки (`dd-tight`, details.css «Тесная колода»).
import { createContext } from "react";

/** Место помощника в обёртке: плита 400 + зазор 16. */
export const HELPER_COL = 416;
/** Поля листа (48 + 48). */
export const SHEET_PAD = 96;
/** Содержимое листа в узкой раскладке у́же — тесная колода. При 1440 оно 880 (V2 помещается), при 1280 — 720, при
 *  обёртке 1217 (1280 с полосой прокрутки) — 705: ряд вкладок с меню и ✕ (761 при плотности V2), колонки «Качества»,
 *  «Агента», «Плана», полоса «Шаблона» и ряды «Файлов» не помещаются. */
export const TIGHT_INNER = 800;

/** «Файлы»: доля правой колонки в узкой раскладке (V2: 50 % → 44,09 %, 380 px при 1440; тесная колода — 40 %). */
export const FILES_RIGHT = 0.4409;
export const FILES_RIGHT_TIGHT = 0.4;

export interface SheetMorph {
  /** Тесная колода. */
  tight: boolean;
  /** Ширина содержимого листа в узкой раскладке, px (0 — обёртка не измерена). */
  inner: number;
  /** «Файлы»: правая колонка в широкой и узкой раскладке, px (V2: 50 % − 8 и 44,09 % − 8 — доли от ширины листа, которая
   *  сама сужается: ход доли по сужающейся ширине не линеен, и колонка шла бы не в такт колоде). 0 — не измерена. */
  filesWide: number;
  filesNarrow: number;
  /** «Файлы», «Паспорт запуска»: на сколько у́же колонка факта в узкой раскладке (`--hpd` стопки f-fact). */
  fact: number;
}

/** Раскладка листа — для вкладок (ставит DetailsSheet). */
export const SheetCtx = createContext<SheetMorph>({ tight: false, inner: 0, filesWide: 0, filesNarrow: 0, fact: 0 });

const r3 = (x: number) => Math.round(x * 1000) / 1000;

export function sheetMorph(wrap: number): SheetMorph {
  const inner = wrap > 0 ? wrap - HELPER_COL - SHEET_PAD : 0;
  const tight = inner > 0 && inner < TIGHT_INNER;
  if (!(inner > 0)) return { tight, inner, filesWide: 0, filesNarrow: 0, fact: 0 };
  // правая колонка «Файлов»: 50 % − 8 листа в широкой и доля узкой − 8 в узкой; факты паспорта — в две колонки
  const filesWide = r3(0.5 * (wrap - SHEET_PAD) - 8);
  const filesNarrow = r3((tight ? FILES_RIGHT_TIGHT : FILES_RIGHT) * inner - 8);
  return { tight, inner, filesWide, filesNarrow, fact: r3((filesWide - filesNarrow) / 2) };
}

/** CSS-переменные листа: дорожки «Файлов» в px. */
export function sheetVars(m: SheetMorph): Record<string, string> {
  return m.filesWide > 0 ? { "--dfw": `${m.filesWide}px`, "--dfn": `${m.filesNarrow}px` } : {};
}

/** «Качество», сводка: на сколько у́же колонка заголовка и строки счёта в узкой раскладке (`--hpd` её стопки). Колода
 *  сужается на 416; справа в узкой раскладке уходят «Исправить всё автоматически» (`allw` — ширина кнопки, и зазор 16),
 *  значок у «Исправить отмеченные» (20 и зазор кнопки 12) и в тесной колоде слово «отмеченные» (`word`). */
export function sumNarrowing({ allw, cta, word }: { allw: number | null; cta: boolean; word: number }): number {
  return HELPER_COL - (allw === null ? 0 : allw + 16) - (cta ? 32 + word : 0);
}
