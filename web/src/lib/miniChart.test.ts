import { test } from "node:test";
import assert from "node:assert/strict";
import type { ColorToken, VizKind } from "../types";
import { DATA_SLIDES } from "./dataWhy.fixtures";
import { miniChart, miniColors, miniSource, numberOf, pagesOf, tint, type MiniLayers } from "./miniChart";

const paths = (m: MiniLayers) => Object.values(m).join("");
/** Сколько фигур (подпутей «M…») в слое. */
const count = (d: string) => (d.match(/M/g) ?? []).length;
const opt = (kind: VizKind, title = "") => ({ kind, title });

test("числа подписей слайда: пробелы-разделители, запятая, знак, единицы", () => {
  assert.equal(numberOf("1 433"), 1433);
  assert.equal(numberOf("212,4"), 212.4);
  assert.equal(numberOf("1,24 млрд ₽"), 1.24);
  assert.equal(numberOf("3 480"), 3480);
  assert.equal(numberOf("+23%"), 23);
  assert.equal(numberOf("−8%"), -8);
  assert.equal(numberOf("нет"), null);
});

test("данные эскиза — из содержимого слайда: ряд графика, числовая колонка таблицы, числа карточек", () => {
  const reg = miniSource(DATA_SLIDES[4], DATA_SLIDES[4].data);
  assert.deepEqual(reg.series[0], [1433, 612, 318, 274, 236, 214, 210, 198]);
  assert.equal(reg.rows, 8);
  const nps = miniSource(DATA_SLIDES[7], DATA_SLIDES[7].data);
  assert.equal(nps.series[0].filter((v) => v === null).length, 2); // пропуски — пропуски, не ноль
  const cli = miniSource(DATA_SLIDES[8], DATA_SLIDES[8].data);
  assert.equal(cli.rows, 10);
  assert.equal(cli.cols, 5);
  assert.equal(cli.series[0][0], 212.4); // «Выручка, млн ₽» — первая колонка с числами после подписи
  assert.equal(cli.restRow, true); // топ-10 и строка «Остальные»
  const kpi = miniSource(DATA_SLIDES[2], DATA_SLIDES[2].data);
  assert.equal(kpi.cards, 4);
  assert.deepEqual(kpi.series[0], [1.24, 3480, 356, 52]);
  const sup = miniSource(DATA_SLIDES[6], DATA_SLIDES[6].data);
  assert.equal(sup.outliers, 3);
  assert.equal(miniSource(null, null).series.length, 0);
});

test("эскиз рисует сами значения: столбцов — сколько значений, сектора — по долям, полосы — не больше десяти", () => {
  const reg = miniSource(DATA_SLIDES[4], DATA_SLIDES[4].data);
  assert.equal(count(miniChart(opt("column"), reg).main), 8);
  assert.equal(count(miniChart(opt("bar"), reg).main), 8);
  const pie = miniChart(opt("pie"), reg);
  assert.equal(count(pie.main) + count(pie.light), 8);
  // доли: первая — основным кольцом, вторая — полупрозрачным, остальные — светлым
  const chn = miniSource(DATA_SLIDES[4], DATA_SLIDES[4].data);
  const ring = miniChart(opt("doughnut"), { ...chn, series: [[46, 28, 17, 9]] });
  assert.equal(count(ring.ring), 1);
  assert.equal(count(ring.ring2), 1);
  assert.equal(count(ring.ringL), 2);
  const stack = miniChart(opt("stacked_column"), { ...chn, series: [[46, 28, 17, 9]] });
  assert.equal(count(stack.main) + count(stack.half) + count(stack.light), 4);
  const many = miniChart(opt("bar"), { ...reg, series: [Array.from({ length: 30 }, (_, i) => 30 - i)] });
  assert.equal(count(many.main), 10);
});

test("линия: разрывы на месте пропусков (пунктир), точки у короткого ряда с пропусками; гистограмма — выбросы за краем", () => {
  const nps = miniSource(DATA_SLIDES[7], DATA_SLIDES[7].data);
  const m = miniChart(opt("line", "Линейный график с разрывами"), nps);
  assert.equal(count(m.dash), 2);
  assert.equal(count(m.main), 6); // шесть измеренных кварталов — шесть точек
  assert.ok(count(m.line) >= 2); // отрезки между пропусками
  const bars = miniChart(opt("column"), nps);
  assert.equal(count(bars.main), 6);
  assert.equal(count(bars.dash), 2); // пустые места столбцов
  const sup = miniSource(DATA_SLIDES[6], DATA_SLIDES[6].data);
  const h = miniChart(opt("histogram"), sup);
  assert.equal(count(h.main), 10);
  assert.equal(count(h.acc), 3);
});

test("таблица, карточки и разбиение — строение без чисел", () => {
  const cli = miniSource(DATA_SLIDES[8], DATA_SLIDES[8].data);
  const t = miniChart(opt("table", "Таблица топ-10 и итог «остальные 230»"), cli);
  assert.equal(count(t.grid), 6); // строк видно не больше шести
  assert.equal(pagesOf({ title: "Разбиение на 24 слайда" }), 24);
  assert.equal(pagesOf({ title: "Таблица" }), null);
  assert.equal(count(miniChart(opt("table", "Разбиение на 24 слайда"), cli).light), 24);
  const kpi = miniSource(DATA_SLIDES[2], DATA_SLIDES[2].data);
  assert.equal(count(miniChart(opt("kpi_cards"), kpi).light), 4);
  assert.equal(count(miniChart(opt("kpi_cards"), cli).light), 3); // карточек на слайде нет — три по строению
});

test("эскиз любого вида — без NaN; без данных — пусто, а не выдуманные столбцы", () => {
  const kinds: VizKind[] = ["line", "column", "bar", "histogram", "pie", "doughnut", "scatter", "grouped_column", "grouped_bar", "stacked_column", "stacked_bar", "kpi_cards", "table", "area"];
  for (const n of [2, 3, 4, 6, 7, 8]) {
    const src = miniSource(DATA_SLIDES[n], DATA_SLIDES[n].data);
    for (const k of kinds) assert.ok(!/NaN|Infinity/.test(paths(miniChart(opt(k), src))), `слайд ${n}, ${k}`);
  }
  const empty = miniSource(null, null);
  for (const k of ["line", "column", "bar", "pie", "doughnut", "histogram", "scatter"] as VizKind[]) assert.equal(miniChart(opt(k), empty).main, "", k);
  // рассеяние — по точкам слайда
  const xy = miniChart(opt("scatter"), { ...empty, xy: { x: [1, 2, 3, 4], y: [3, 1, 4, 2] } });
  assert.equal(count(xy.main), 4);
});

test("цвета эскизов — шаблона: основной — первый акцент, акцент — другой по тону; светлая — основной с белым", () => {
  const tok = (hex: string, roles: string[], is_brand = false): ColorToken => ({ hex, role: roles[0], roles, semantic: null, is_brand, weight: 1, contexts: {} });
  const m = { tokens: { colors: [tok("FFFFFF", ["background.light"]), tok("0077FF", ["background.dark", "accent.1"], true), tok("2787F5", ["accent.2"]), tok("FF3985", ["accent.3"])], typography: { families: [], scale: [], sizes_used: [], left_align_share: 0, line_spacing: 0 } } };
  assert.deepEqual(miniColors(m), { main: "#0077FF", acc: "#FF3985", light: tint("#0077FF") });
  assert.equal(tint("#0077FF"), "#D6E9FF");
  assert.deepEqual(miniColors(null), { main: "#0077FF", acc: "#FF3885", light: "#D6E9FF" });
});
