import { test } from "node:test";
import assert from "node:assert/strict";
import type { ActiveJob } from "../../lib/jobState";
import type { AuditReport, BrandSpec, Generation, GenerationMeta, Issue, Variant } from "../../types";
import { DATA_SLIDES } from "../details/dataWhy.fixtures";
import { compactChecks, sourceText } from "./compact";
import { skippedLine, dataFigures, deckBrand, deckTemplate, docLine, lookCard, qualityCard, whyFile } from "./resultView";
import { liveWork } from "./slideJob";

const meta = (patch: Partial<GenerationMeta> = {}): GenerationMeta => ({ id: "g1", template_id: "t1", strategies: ["structured"], ...patch });

test("строка под названием: брендбук презентации — после шаблона (V2 v105 `docLine`); без брендбука — как было", () => {
  assert.equal(docLine("VK Tech", 9, "только что", "брендбук VK Cloud"), "VK Tech · брендбук VK Cloud · 9 слайдов · только что");
  assert.equal(docLine("VK Tech", 12, "сегодня, 17:38"), "VK Tech · 12 слайдов · сегодня, 17:38");
  assert.equal(docLine("VK Tech", 12, "сегодня, 17:38", null), "VK Tech · 12 слайдов · сегодня, 17:38");
  assert.equal(deckBrand(meta({ brandbook: { id: "b1", name: "VK Cloud", file: "Брендбук VK Cloud.pdf", source: "pdf" } })), "брендбук VK Cloud");
  assert.equal(deckBrand(meta({ brandbook: { id: "b1", name: "", file: "Брендбук Ромашка.pdf", source: "pdf" } })), "брендбук Ромашка");
  assert.equal(deckBrand(meta()), null);
  assert.equal(deckBrand(meta({ brandbook: null })), null);
});

test("шаблон презентации для людей: у колоды на брендированной копии — исходный", () => {
  assert.equal(deckTemplate(meta({ template_id: "copy1", base_template_id: "t1" })), "t1");
  assert.equal(deckTemplate(meta()), "t1");
  assert.equal(deckTemplate(meta({ base_template_id: null })), "t1");
});

test("карточка «Почему так» слайда с данными: его файл и природа данных; слайд не из файла — ничего", () => {
  const v = { strategy: "structured", outline: { slides: [{ ...DATA_SLIDES[4], data: null }, DATA_SLIDES[4], DATA_SLIDES[2]] } } as unknown as Variant;
  assert.equal(whyFile(v, 1), null);
  assert.deepEqual(whyFile(v, 2), { text: "Регионы.xlsx · сравнение", icon: "tbl" });
  assert.deepEqual(whyFile(v, 3), { text: "Итоги квартала.txt · таблица в тексте", icon: "txt" });
  assert.equal(whyFile(null, 1), null);
});

test("пока идёт «Пересобрать слайд так», работа над вариантом на экране результата ждёт — с понятной причиной", () => {
  const j = { id: "j", kind: "rebuild", target: { generation: "g1", strategy: "structured", slide: 4 } } as ActiveJob;
  assert.deepEqual(liveWork(j), { why: "Агент пересобирает слайд 4", slide: 4 });
});

const BRAND: BrandSpec = {
  id: "b1", name: "VK Cloud", source: "pdf", file: "Брендбук VK Cloud.pdf", pages: 12,
  colors: [{ hex: "#0077FF", role: "primary", name: null }, { hex: "#2787F5", role: "secondary", name: null }, { hex: "#0B1220", role: "text", name: null },
    { hex: "#FFFFFF", role: "background", name: null }, { hex: "#ff3985", role: "accent", name: null }, { hex: "#00C2FF", role: "chart", name: null }, { hex: "#000000", role: "neutral", name: null }],
  fonts: [{ role: "heading", family: "VK Sans Display", fallback: "Play", weight: 700 }, { role: "body", family: "VK Sans Text", fallback: "Play", weight: 400 }],
  logos: [], margins_px: null, grid: null, rules: [], logo_place: null, warnings: [],
};
const bb = { id: "b1", name: "VK Cloud", file: "Брендбук VK Cloud.pdf", source: "pdf" as const };

test("«Оформление» (V2 v105 `ds-look`): брендбук важнее — шрифт заголовков с заменой и акцент; шаблон важнее; без брендбука — шаблон", () => {
  const o = { template: "VK Tech", font: "Play", brand: BRAND };
  assert.deepEqual(lookCard(meta({ dataset_ids: ["d1"], brandbook: bb, brand_priority: "brand" }), o), {
    tag: "брендбук важнее", text: "VK Tech и брендбук VK Cloud: заголовки — VK Sans Display, замена — Play; акцент #FF3985",
    palette: ["#0077FF", "#2787F5", "#0B1220", "#FFFFFF", "#ff3985", "#00C2FF"],
  });
  assert.equal(lookCard(meta({ brandbook: bb }), o)?.tag, "брендбук важнее"); // по умолчанию брендбук важнее
  assert.deepEqual(lookCard(meta({ dataset_ids: ["d1"], brandbook: bb, brand_priority: "template" }), o)?.text, "VK Tech и брендбук VK Cloud: при расхождении — как в шаблоне");
  assert.deepEqual(lookCard(meta({ dataset_ids: ["d1"] }), o), { tag: "по шаблону", text: "Палитра, шрифт Play и сетка — из шаблона VK Tech", palette: null });
  assert.equal(lookCard(meta({ dataset_ids: ["d1"] }), { ...o, font: null })?.text, "Палитра, шрифты и сетка — из шаблона VK Tech");
  // брендбука уже нет на сервере — без подробностей и плитки
  assert.deepEqual(lookCard(meta({ brandbook: bb }), { ...o, brand: null }), { tag: "брендбук важнее", text: "VK Tech и брендбук VK Cloud", palette: null });
  // колода без файлов и без брендбука — карточки нет
  assert.equal(lookCard(meta(), o), null);
});

const issue = (check_id: string): Issue => ({ id: check_id, slide: 3, check_id, severity: "error", kind: "deterministic", message: "", bboxes: [], element_ids: [], suggestion: null, autofix: null, details: {}, outline_id: null });
const DATA_CHECKS = ["text_overflow", "chart_values_mismatch", "headline_figure_not_in_data"];
const audit = (issues: Issue[] = [], checks_run = DATA_CHECKS): AuditReport => ({ deck: "", template_id: "t1", strategy: "structured", issues, summary: { errors: issues.length, warnings: 0, infos: 0, model_flags: 0, score: 90, checks_run }, per_slide: {}, iterations: 0, applied_fixes: [], seconds: 0 });

test("сверка чисел колоды из файлов: «Числа на слайдах сверены с файлами», в узкой колонке — «7 файлов данных — числа сверены»", () => {
  const g = { ...meta({ dataset_ids: ["a", "b", "c", "d", "e", "f", "g"], summary: { structured: { score: 90 } } }), variants: [] } as Generation;
  const v = { strategy: "structured", audit: audit(), outline: null, plan: null, run_manifest: null, slides: [], files: {} } as Variant;
  assert.deepEqual(dataFigures(g, v), { text: "Числа на слайдах сверены с файлами", tone: "ok", title: "Числа слайдов сверены с файлами: 7 файлов данных", compact: { lead: "7 файлов данных", rest: " — числа сверены" } });
  assert.equal(qualityCard(g, v)?.figures?.text, "Числа на слайдах сверены с файлами");
  const row = compactChecks(g, v, null).find((x) => x.icon === "numbers");
  assert.deepEqual([row?.lead, row?.rest], ["7 файлов данных", " — числа сверены"]);
  // проверки нашли расхождения с файлом — так и сказано, жёлтым
  const bad = { ...v, audit: audit([issue("chart_values_mismatch"), issue("headline_figure_not_in_data"), issue("text_overflow")]) };
  assert.deepEqual([dataFigures(g, bad)?.text, dataFigures(g, bad)?.tone], ["Не совпало с файлами: 2 замечания", "warn"]);
  // без файлов — как было (сверка с текстом брифа)
  assert.equal(dataFigures(meta(), v), null);
  // сверки не было (её проверок нет в checks_run, аудита нет) — «сверены» не говорим
  assert.equal(dataFigures(g, { ...v, audit: audit([], ["text_overflow"]) }), null);
  assert.equal(dataFigures(g, { ...v, audit: null }), null);
  assert.equal(qualityCard(g, { ...v, audit: audit([], []) })?.figures ?? null, null);
});

test("откуда текст колоды из файлов (V2 v105 `hpSrc`): «Текст написал агент — по брифу и 7 файлам данных»", () => {
  const g = (patch: Partial<GenerationMeta>) => ({ ...meta(patch), variants: [] }) as Generation;
  assert.equal(sourceText(g({ brief: "Итоги продаж", dataset_ids: ["a", "b", "c", "d", "e", "f", "g"] }), null), "Текст написал агент — по брифу и 7 файлам данных");
  assert.equal(sourceText(g({ brief: "", dataset_ids: ["a"] }), null), "Текст написал агент — по 1 файлу данных");
  assert.equal(sourceText(g({ brief: "Итоги" }), null), "Ваш текст — агент разложил его по слайдам");
});

test("файлы без слайда: одна тихая строка, причины — в подсказке", () => {
  assert.equal(skippedLine({}), null);
  const one = skippedLine({ data_story: { datasets: 2, slides: 3, skipped: [{ file: "Заметки.txt", sheet: null, message: "Не для графика: одни тексты." }] } });
  assert.deepEqual(one, { text: "Без слайда: «Заметки.txt» — Не для графика: одни тексты", title: "«Заметки.txt» — Не для графика: одни тексты" });
  const two = skippedLine({ data_story: { datasets: 3, slides: 3, skipped: [{ file: "a.csv", sheet: null, message: "x" }, { file: "b.xlsx", sheet: "Лист2", message: "y" }] } });
  assert.equal(two?.text, "Без слайда: 2 файла");
  assert.equal(two?.title, "«a.csv» — x\n«b.xlsx · Лист2» — y");
});

test("данные и база знаний: «Графики — по 2 файлам данных, остальное агент написал по базе знаний «…»»", () => {
  const writer = { mode: "topic", status: "written", text: "Слайд 1…", basis: "kb", part: "kb_with_data", kb: { id: "k", name: "Квартал", docs: [{ id: "a", title: "A" }] } } as GenerationMeta["writer"];
  const g = { ...meta({ brief: "План", dataset_ids: ["a", "b"], writer }), variants: [] } as Generation;
  assert.equal(sourceText(g, null), "Графики — по 2 файлам данных, остальное агент написал по базе знаний «Квартал»");
});
