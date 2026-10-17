// Одно название на вид графика — везде в интерфейсе (навигация «Почему так», варианты, план, таблетки целей). Источник —
// сервер: verstka/schemas/data.py `VIZ_TITLES` (тест vizNames.test.ts сверяет таблицы), задача → вид — data/goals.py
// `GOAL_VIZ`.
import type { TaskKind, VizKind } from "../types";

export const VIZ_TITLES: Record<VizKind, string> = {
  line: "Линейный график",
  column: "Столбцы",
  bar: "Полосы",
  histogram: "Гистограмма",
  pie: "Круговая",
  doughnut: "Кольцевая",
  scatter: "Рассеяние",
  grouped_column: "Сгруппированные столбцы",
  grouped_bar: "Сгруппированные полосы",
  stacked_column: "Накопительные столбцы",
  stacked_bar: "Накопительные полосы",
  kpi_cards: "Карточки показателей",
  table: "Таблица",
  area: "Область",
};

/** Вид графика, к которому ведёт цель (сервер: data/goals.py `GOAL_VIZ`). */
export const GOAL_VIZ: Record<TaskKind, VizKind> = {
  dynamics: "line", comparison: "bar", shares: "doughnut", distribution: "histogram", relationship: "scatter", reference: "table", kpi: "kpi_cards",
};

/** Название вида: «Полосы»; неизвестный вид — «Диаграмма». */
export const vizName = (kind: string | null | undefined): string => (kind && (VIZ_TITLES as Record<string, string>)[kind]) || "Диаграмма";
/** То же со строчной буквы — в середине фразы («→ полосы»). */
export const vizNameLower = (kind: string | null | undefined): string => {
  const s = vizName(kind);
  return s.charAt(0).toLowerCase() + s.slice(1);
};
