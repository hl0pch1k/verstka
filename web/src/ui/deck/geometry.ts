// Модель экрана «Слоёв» и геометрия колоды: где стоят четыре плиты (01 шаблон, 02 текст, 03 параметры и запуск,
// 04 сборка/результат) на каждом экране. Числа — из boards/V2.dc.html (`renderVals`: `Y`, `y4`, `s4Cls`), переходы —
// из его `go()` и обработчиков шапок, полос и листа «Подробнее».

export type Screen = "create" | "build" | "result";
export type SheetTab = "quality" | "why" | "agent" | "plan" | "template" | "files";

export interface UiState {
  screen: Screen;
  /** Какой шаг «Создать» раскрыт: шаблон или текст. */
  open: "tpl" | "text";
  /** «Все параметры»: плиты 01/02 свёрнуты в полосы, плита 03 раскрыта. */
  more: boolean;
  /** «Улучшить готовую»: плита 01 свёрнута в полосу, плита 02 встаёт под неё (40 px). */
  improve: boolean;
  /** Слой шапки: «Мои презентации» или «Шаблоны». */
  sect: null | "hist" | "tpls";
  /** Открытая вкладка листа «Подробнее» (null — лист закрыт) и последняя открытая. */
  sheet: SheetTab | null; sheetLast: SheetTab;
  /** Открытый макет шаблона (номер), null — нет. */
  pattern: number | null;
  textLayer: boolean; lightbox: boolean; helper: boolean; note: boolean; remarks: boolean;
  /** Шаблон, открытый на просмотр, и шаблон, ждущий подтверждения удаления (id). */
  tplPreview: string | null; tplDelete: string | null;
  /** результат открыт из «Создать»: плита 04 поднимается снизу одним движением с плитами 02/03 */
  rise: boolean;
  /** возврат на «Создать» с результата: плита 04 уходит вниз непрозрачной со своим содержимым */
  down: boolean;
}

export const UI0: UiState = {
  screen: "create", open: "text", more: false, improve: false,
  sect: null, sheet: null, sheetLast: "quality", pattern: null,
  textLayer: false, lightbox: false, helper: false, note: false, remarks: false,
  tplPreview: null, tplDelete: null, rise: false, down: false,
};

export interface Geometry {
  y: [number, number, number, number];   // translateY плит 01..04, px
  s4: "on" | "off" | "up" | "down";       // класс плиты результата: p2-s4-on / p2-s4-off / + p2-s4-up / p2-s4-down
  heads: boolean;                         // шапки и тела «Создать» видны (иначе — полосы)
  strips: boolean;                        // полосы 01/02 видны
}

export function deckGeometry(ui: UiState): Geometry {
  const create = ui.screen === "create";
  const folded = !create || ui.more;
  let y: Geometry["y"] = folded ? [0, 40, 80, 0] : ui.open === "tpl" ? [0, 524, 668, 0] : [0, 144, 556, 0];
  if (create && !folded && ui.improve) y = [y[0], 40, y[2], 0];
  y[3] = ui.screen === "result" ? 120 : create ? 812 : 80;
  const s4 = ui.screen === "result" ? (ui.rise ? "up" : "on") : ui.down ? "down" : "off";
  return { y, s4, heads: create && !ui.more, strips: !create || ui.more };
}

export type UiAction =
  | { type: "go"; screen: Screen } | { type: "open"; step: "tpl" | "text" } | { type: "more"; on?: boolean }
  | { type: "sect"; sect: UiState["sect"] } | { type: "sheet"; tab: SheetTab | null } | { type: "pattern"; n: number | null }
  | { type: "set"; patch: Partial<UiState> };

/** `rise` и `down` ставит вызывающий код (открытие из «Мои презентации», возврат по логотипу) и сам снимает их
 *  таймером 560 мс — `go` их не трогает. */
export function uiReducer(s: UiState, a: UiAction): UiState {
  switch (a.type) {
    case "go":
      // переход закрывает всё поверх колоды; на «Создать» раскрывается текст (V2 `go('create')`)
      return {
        ...s, screen: a.screen, open: a.screen === "create" ? "text" : s.open,
        sheet: null, sect: null, pattern: null, textLayer: false, lightbox: false, remarks: false, more: false,
        tplPreview: null, tplDelete: null,
      };
    case "open":
      // шапка шага или полоса свёрнутой плиты: шаг раскрывается, «Все параметры» сворачиваются
      return { ...s, open: a.step, more: false };
    case "more":
      // «Все параметры» переключаются; когда они закроются, раскрыт текст (V2)
      return { ...s, more: a.on ?? !s.more, open: "text" };
    case "sect":
      return { ...s, sect: a.sect };
    case "sheet":
      return { ...s, sheet: a.tab, sheetLast: a.tab ?? s.sheetLast };
    case "pattern":
      return { ...s, pattern: a.n };
    case "set":
      return { ...s, ...a.patch };
  }
}
