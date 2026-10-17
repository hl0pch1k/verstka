// Колода стопкой (окно уже 1280): слои и помощник — плиты поверх колоды, под ними — затемнение (StackDim). Здесь без
// React: что сейчас сверху (щелчок по затемнению закрывает его) и что закрыть, когда открылось другое (поверх колоды —
// одна плита: помощник и слой не лежат друг на друге).
import type { UiAction, UiState } from "../deck/geometry";

/** Что открыто поверх колоды, сверху вниз: «Удалить шаблон?» (своё затемнение), «Слайды шаблона», «Брендбук», «Слайд N
 *  шаблона» над листом, весь экран, лист «Подробнее», «Текст презентации», раздел, помощник. */
export type Sheet = "tplDelete" | "tplPreview" | "brand" | "pattern" | "lightbox" | "sheet" | "text" | "sect" | "helper";

/** Открытые плиты поверх колоды, сверху вниз. */
export function openSheets(ui: UiState): Sheet[] {
  const out: Sheet[] = [];
  if (ui.tplDelete) out.push("tplDelete");
  if (ui.tplPreview) out.push("tplPreview");
  if (ui.brandLayer) out.push("brand");
  if (ui.sheet && ui.pattern !== null) out.push("pattern");
  if (ui.lightbox) out.push("lightbox");
  if (ui.sheet) out.push("sheet");
  if (ui.textLayer) out.push("text");
  if (ui.sect) out.push("sect");
  if (ui.helper) out.push("helper");
  return out;
}

/** Слой открыт (не помощник). */
export const layerOpen = (ui: UiState): boolean => openSheets(ui).some((s) => s !== "helper");

/** Как закрыть плиту `s`. */
export function closeSheet(s: Sheet): UiAction {
  switch (s) {
    case "tplDelete": return { type: "set", patch: { tplDelete: null } };
    case "tplPreview": return { type: "set", patch: { tplPreview: null } };
    case "brand": return { type: "set", patch: { brandLayer: false } };
    case "pattern": return { type: "pattern", n: null };
    case "lightbox": return { type: "set", patch: { lightbox: false } };
    case "sheet": return { type: "sheet", tab: null };
    case "text": return { type: "set", patch: { textLayer: false } };
    case "sect": return { type: "sect", sect: null };
    case "helper": return { type: "set", patch: { helper: false } };
  }
}

/** Щелчок по затемнению: закрыть верхнюю плиту («Удалить шаблон?» закрывается своим затемнением — его нет в ответе). */
export function dimClose(ui: UiState): UiAction | null {
  const top = openSheets(ui).find((s) => s !== "tplDelete");
  return top ? closeSheet(top) : null;
}

/** Поверх колоды — одна плита: открылся помощник — слои закрываются; открылся слой — закрывается помощник. `was` —
 *  состояние до перемены. Что закрыть (пусто — ничего). */
export function oneSheet(was: UiState, now: UiState): UiAction[] {
  const helperNew = now.helper && !was.helper;
  const layerNew = layerOpen(now) && (!layerOpen(was) || openSheets(now).length > openSheets(was).length);
  if (helperNew && layerOpen(now)) {
    // слои закрываются сверху вниз; «Удалить шаблон?» — вместе со «Слайдами шаблона»
    return openSheets(now).filter((s) => s !== "helper" && s !== "pattern").map(closeSheet);
  }
  if (layerNew && now.helper && !helperNew) return [closeSheet("helper")];
  return [];
}
