// Размеры раскладки, которые делят колода, «Создать», «Сборка», слои и лист «Подробнее» (fit.ts, create/morph.ts,
// build/columns.ts, details/sheetMorph.ts, layers/layerMorph.ts, result/compact.ts): одно место, чтобы они не разошлись.

/** Место помощника в обёртке колоды: плита 400 + зазор 16 (shell.css `.hp-wrap.hp-nar`). */
export const HELPER_COL = 416;
/** Поля плиты (48 + 48): содержимое плиты уже колоды на столько. */
export const PLATE_PAD = 96;
/** Поля листа «Подробнее» (48 + 48); по значению те же, что у плиты. */
export const SHEET_PAD = PLATE_PAD;
