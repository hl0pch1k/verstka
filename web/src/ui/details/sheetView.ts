// Лист «Подробнее» без React (boards/D-*, V2 `#p2-lay-d`, `ddTabs`, `dd-back`, меню варианта `dlf.vmenu`): шесть
// вкладок, ход стрелками по ним, полоса «04 Название · Вариант N» над листом и пункты меню варианта.
import type { Generation, Variant } from "../../types";
import type { SheetTab, UiState } from "../deck/geometry";
import { docTitle, scoreOf } from "../result/resultView";

export const SHEET_TABS: { key: SheetTab; label: string }[] = [
  { key: "quality", label: "Качество" }, { key: "why", label: "Почему так" }, { key: "agent", label: "Агент" },
  { key: "plan", label: "План" }, { key: "template", label: "Шаблон" }, { key: "files", label: "Файлы" },
];

/** Вкладка, на которую ведёт клавиша в ряду вкладок (←/→ по кругу, Home/End); чужая клавиша — null. */
export function tabStep(cur: SheetTab, key: string): SheetTab | null {
  const i = SHEET_TABS.findIndex((t) => t.key === cur);
  const n = SHEET_TABS.length;
  const to = key === "ArrowRight" ? (i + 1) % n : key === "ArrowLeft" ? (i - 1 + n) % n : key === "Home" ? 0 : key === "End" ? n - 1 : null;
  return to === null ? null : SHEET_TABS[to].key;
}

/** Поверх листа открыт слой шапки — раздел «Шаблоны» / «Мои презентации», просмотр или удаление шаблона: клавиши
 *  (←/→ вкладки «Почему так», запасной Esc листа и слоя «Слайд N шаблона») — его, не листа. */
export const headerLayerOpen = (ui: Pick<UiState, "sect" | "tplPreview" | "tplDelete">) => !!ui.sect || !!ui.tplPreview || !!ui.tplDelete;

const round = (s: number | null) => (s === null ? null : Math.round(s));

/** Полоса «04 Интеграл · Структурный 89» плиты результата под листом (V2 `dd-back`). */
export function backStrip(g: Generation, v: Variant, titleOf: (name: string) => string): { title: string; name: string; score: number | null; aria: string } {
  const title = docTitle(g, v);
  const name = titleOf(v.strategy);
  const score = round(scoreOf(g, v));
  return { title, name, score, aria: `Вернуться к результату: ${title}, вариант ${name}${score === null ? "" : `, оценка ${score}`}` };
}

export function menuItems(g: Generation, titleOf: (name: string) => string): { key: string; n: number; name: string; score: number | null }[] {
  return g.variants.map((v, i) => ({ key: v.strategy, n: i + 1, name: titleOf(v.strategy), score: round(scoreOf(g, v)) }));
}
