import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BRAND_RUN0, brandFileName, brandLayerMeta, brandMeta, brandName, brandPalette, brandRows, brandSourceOf, brandTiles, briefShort,
  brandTight, cardName, cardSize, cardTip, conflictView, dataBusy, dataFilesLabel, dataKind, dataPanel, dataRequest, datasetIds, dropKind, fieldWidths, figmaUrlOk, goalsFit,
  fmtLabel, foldBrandEvent, goalChips, goalNoteLine, goalsKey, goalsLabel, goalsOf, hasTable, MAX_DATA_BYTES, panelShort, panelStatus, parseManifest, runWord, sizeProblem, type DataCard,
} from "./dataRules";
import type { BrandConflict, BrandSpec, DatasetSummary, JobEvent } from "../../types";

const BRIEF = "Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, что даёт выручку и где узкие места. Данные — в приложенных файлах.";
const sum = (patch: Partial<DatasetSummary> = {}): DatasetSummary => ({
  id: "d1", file: "Выручка по месяцам.csv", kind: "csv", rows: 21, cols: 3, nature: "time_series", nature_label: "Временной ряд",
  line: "Временной ряд · 21 строка · 3 колонки", issues: [], sheet: null, ...patch,
});
const card = (status: DataCard["status"], patch: Partial<DataCard> = {}): DataCard => ({
  key: "k", file: "Выручка по месяцам.csv", kind: "csv", status, summary: status === "done" ? sum() : null, error: null, ...patch,
});
const ev = (patch: Partial<JobEvent> & { brand?: Partial<BrandSpec> }): JobEvent & { brand?: Partial<BrandSpec> } =>
  ({ job_id: "j", status: "running", progress: 0, message: "", t: 0, ...patch });
const SPEC: BrandSpec = {
  id: "b1", name: "VK Cloud", source: "pdf", file: "Брендбук VK Cloud.pdf", pages: 24,
  colors: [["#0077FF", "primary"], ["#2787F5", "secondary"], ["#0B1220", "text"], ["#FFFFFF", "background"], ["#FF3985", "accent"], ["#00C2FF", "chart"], ["#999999", "neutral"]]
    .map(([hex, role]) => ({ hex, role: role as BrandSpec["colors"][number]["role"], name: null })),
  fonts: [{ role: "heading", family: "VK Sans Display", fallback: "Play", weight: 700 }, { role: "body", family: "VK Sans Text", fallback: "Play", weight: 400 }],
  logos: ["Основной", "Белый", "Знак", "Монохром"].map((name, i) => ({ name, file: `logos/${i}.svg`, variant: (["primary", "white", "mark", "mono"] as const)[i], ground: "any" as const })),
  margins_px: 48, grid: null, rules: [{ text: "Логотип — в правом нижнем углу", kind: "logo" }], logo_place: "bottom_right", warnings: [],
};

test("файлы данных: формат по расширению, CSV/XLSX/JSON — данные, .txt/.md — смотря что внутри, .pptx — «Улучшить готовую»", () => {
  assert.deepEqual(["a.CSV", "b.tsv", "c.xlsx", "d.json", "e.txt", "f.md", "g.pdf"].map(dataKind), ["csv", "tsv", "xlsx", "json", "text", "text", null]);
  assert.deepEqual(["a.csv", "b.md", "c.pptx", "d.docx"].map(dropKind), ["data", "text", "deck", "other"]);
  assert.equal(fmtLabel("Регионы.xlsx"), "XLSX");
});
test("пределы размера — как у сервера: книга Excel 4 МБ, текст с таблицей 15 МБ, остальное 25 МБ; его же слова", () => {
  const MB = 1024 * 1024;
  assert.deepEqual(MAX_DATA_BYTES, { any: 25 * MB, xlsx: 4 * MB, text: 15 * MB });
  assert.equal(sizeProblem("Регионы.xlsx", 4 * MB), null);
  assert.equal(sizeProblem("Регионы.xlsx", 4 * MB + 1),
    "Книга Excel «Регионы.xlsx» больше 4 МБ — сохраните нужный лист как CSV (он прочитается быстрее) или оставьте в книге только нужные листы");
  assert.equal(sizeProblem("Итоги.md", 15 * MB + 1), "Текст «Итоги.md» больше 15 МБ — сохраните таблицу из него как CSV (она прочитается быстрее)");
  assert.equal(sizeProblem("Итоги.txt", 15 * MB), null);
  // CSV, TSV и JSON — общий предел 25 МБ (как на сервере: медленные форматы — только книга и текст)
  assert.equal(sizeProblem("Выручка.csv", 20 * MB), null);
  assert.equal(sizeProblem("Каналы.json", 25 * MB + 1), "«Каналы.json» больше 25 МБ — оставьте в файле только нужные строки и листы");
  // больше общего предела — сначала общий, как на сервере
  assert.equal(sizeProblem("Большая.xlsx", 30 * MB), "«Большая.xlsx» больше 25 МБ — оставьте в файле только нужные строки и листы");
});
test("таблица в тексте: Markdown с разделителем или три строки через табуляцию/«;»; обычный текст — не таблица", () => {
  assert.equal(hasTable("Итоги\n\n| Показатель | III кв. 2026 |\n|---|---|\n| Выручка | 1,24 млрд ₽ |\n"), true);
  assert.equal(hasTable("месяц\tвыручка\nянв\t297\nфев\t302\n"), true);
  assert.equal(hasTable("a;b\nc;d\ne;f"), true);
  assert.equal(hasTable("Итоги продаж VK Cloud. Покажи рост выручки; сравни регионы.\nЕщё строка."), false);
  assert.equal(hasTable("| только | строка |"), false);
});
test("карточка: что говорит, пока разбирается; размер в широкой и узкой колоде; имя листа книги; подсказка", () => {
  assert.equal(runWord("text"), "ищу таблицу в тексте…");
  assert.equal(runWord(null), "читаю таблицу…");
  assert.deepEqual(cardSize(21, 3), { wide: "21 строка · 3 колонки", narrow: "21 строка" });
  assert.deepEqual(cardSize(512, 1), { wide: "512 строк · 1 колонка", narrow: "512 строк" });
  assert.equal(cardName(sum({ file: "Регионы.xlsx", sheet: "Лист1" }), true), "Регионы.xlsx · Лист1");
  assert.equal(cardName(sum({ file: "Регионы.xlsx", sheet: "Лист1" }), false), "Регионы.xlsx");
  assert.equal(cardTip(card("done")), "Выручка по месяцам.csv · CSV · 21 строка · 3 колонки · Временной ряд");
  assert.equal(cardTip(card("fail", { error: "Файл пустой" })), "Выручка по месяцам.csv · Файл пустой");
});
test("шапка панели: ход разбора, итог; id для сборки — только разобранные; пока разбираются — сборка ждёт", () => {
  assert.deepEqual(panelStatus([]), { text: "", short: "", busy: false });
  assert.deepEqual(panelStatus([card("done"), card("done"), card("run"), card("wait")]), { text: "разбираю 3 из 4…", short: "3 из 4…", busy: true });
  assert.deepEqual(panelStatus(Array.from({ length: 7 }, () => card("done"))), { text: "7 файлов разобраны", short: "7 готово", busy: false });
  assert.deepEqual(panelStatus([card("done"), card("fail")]), { text: "1 из 2 разобраны", short: "1 из 2 готово", busy: false });
  // короткая строка — в тесной колоде с помощником (панель у́же 300), при 1440 — как на холсте
  assert.deepEqual([panelShort(1392), panelShort(1318), panelShort(1232), panelShort(1217)], [false, false, true, true]);
  assert.deepEqual(datasetIds([card("done"), card("fail"), card("done", { summary: sum({ id: "d2" }) })]), ["d1", "d2"]);
  assert.equal(dataBusy([card("done"), card("wait")]), true);
  assert.equal(dataBusy([card("done"), card("fail")]), false);
});
test("цели из текста: по порядку, у задачи — первая, со своим графиком; без целей — подпись «графики выберу по данным»", () => {
  assert.deepEqual(goalsOf(BRIEF), [
    { q: "покажи рост выручки", to: "линейный график", task: "dynamics" },
    { q: "сравни регионы", to: "столбцы", task: "comparison" },
  ]);
  assert.deepEqual(goalsOf("Из чего складывается выручка? Как распределено время ответа. Есть ли связь цены и спроса; справочно — клиенты").map((g) => g.task),
    ["shares", "distribution", "relationship", "reference"]);
  assert.deepEqual(goalsOf("Итоги квартала для правления"), []);
  // две цели одной фразой — две таблетки
  assert.deepEqual(goalsOf("Итоги: покажи рост выручки и сравни регионы").map((g) => g.q), ["покажи рост выручки", "сравни регионы"]);
  assert.deepEqual(goalsLabel(0), { wide: "Целей в тексте нет — графики выберу по данным", narrow: "Целей в тексте нет" });
  assert.equal(goalsLabel(2).narrow, "Цели из текста");
});
test("полоса 02 с данными: первая фраза брифа до 44 знаков по слову и сколько файлов", () => {
  assert.equal(briefShort(BRIEF), "Итоги продаж VK Cloud за 9 месяцев 2026 года…");
  assert.equal(briefShort("Короткая тема"), "Короткая тема");
  assert.equal(briefShort("Тема. И ещё"), "Тема…");
  assert.equal(briefShort("  "), "Тема ещё не задана");
  assert.equal(dataFilesLabel(7), "7 файлов данных");
  assert.equal(dataFilesLabel(1), "1 файл данных");
});
test("панель «Данные» в узкой колоде: 400 → 320 при 1440; в тесной колоде поле не у́же 280 — панель сжимается", () => {
  assert.deepEqual(dataPanel(1392), { wide: 400, narrow: 320, hpd: 336 });
  assert.deepEqual(dataPanel(0), { wide: 400, narrow: 320, hpd: 336 });
  assert.deepEqual(fieldWidths(1392), { wide: 688, narrow: 352 });
  // окно 1280: полоса прокрутки окна поверх (1232) и классическая, 15 px (1217) — поле 280 в обеих
  assert.deepEqual([dataPanel(1232).narrow, fieldWidths(1232).narrow, fieldWidths(1232).wide], [232, 280, 528]);
  assert.deepEqual([dataPanel(1217).narrow, fieldWidths(1217).narrow], [217, 280]);
  assert.equal(dataPanel(1232).hpd, 248);
  // окно 1366
  assert.deepEqual([dataPanel(1318).narrow, fieldWidths(1318).narrow], [318, 280]);
  // ещё у́же — панель не у́же 200
  assert.equal(dataPanel(1100).narrow, 200);
});
test("таблетки целей: гаснут те, что не помещаются целиком (первая — всегда); тесная колода с помощником", () => {
  const w = [{ q: 150, gt: 129 }, { q: 105, gt: 70 }];
  assert.deepEqual(goalsFit(w, 1392), { wide: [true, true], narrow: [true, true] });
  assert.deepEqual(goalsFit(w, 1232), { wide: [true, false], narrow: [true, false] });
  assert.deepEqual(goalsFit([{ q: 900, gt: 100 }], 1232), { wide: [true], narrow: [true] });
  assert.equal(brandTight(1392), false);
  assert.equal(brandTight(1318), true);
  assert.equal(brandTight(1232), true);
});
test("брендбук: откуда, имя файла, ссылка Figma", () => {
  const f = (name: string) => new File(["x"], name);
  assert.deepEqual([brandSourceOf(f("a.pdf")), brandSourceOf(f("t.json")), brandSourceOf(f("b.zip")), brandSourceOf([f("x.svg")]), brandSourceOf({ figmaUrl: "https://figma.com/file/abc" })],
    ["pdf", "json", "dir", "dir", "figma"]);
  assert.equal(brandFileName(f("Брендбук VK Cloud.pdf")), "Брендбук VK Cloud.pdf");
  assert.equal(brandFileName({ figmaUrl: "x" }), "Файл Figma");
  assert.equal(figmaUrlOk("https://www.figma.com/design/AbC123/Brand?node-id=1"), true);
  assert.equal(figmaUrlOk("figma.com/file/AbC123"), true);
  assert.equal(figmaUrlOk("https://example.com/file/AbC"), false);
});
test("разбор брендбука: шаги по событиям задачи, итог шага — после двоеточия, ход без шага — по доле", () => {
  let r = BRAND_RUN0;
  r = foldBrandEvent(r, ev({ step: "open", message: "Открыт файл: 24 страницы", brand: { pages: 24 } }));
  r = foldBrandEvent(r, ev({ step: "palette", message: "6 цветов", brand: { colors: SPEC.colors.slice(0, 6) } }));
  assert.equal(r.done, 2);
  assert.deepEqual(r.facts, { open: "24 страницы", palette: "6 цветов" });
  assert.equal(r.brand?.pages, 24);
  const rows = brandRows(r, "pdf", "VK Tech");
  assert.deepEqual(rows.map((x) => x.state), ["done", "done", "cur", "pend", "pend", "pend"]);
  assert.deepEqual([rows[1].a, rows[1].b], ["палитра: ", "6 цветов"]);
  assert.deepEqual([rows[2].a, rows[2].b], ["шрифты", ""]);
  assert.equal(rows[5].a, "сверка с шаблоном VK Tech");
  // плитки: палитра пришла — заполнена; шрифтов ещё нет
  assert.deepEqual(brandTiles(r).map((t) => [t.key, t.on, t.meta]), [["fonts", false, "…"], ["palette", true, "6 цветов"], ["logos", false, "…"]]);
  // событие без шага двигает по доле хода, не назад
  assert.equal(foldBrandEvent(r, ev({ progress: 0.7 })).done, 4);
  assert.equal(foldBrandEvent(r, ev({ progress: 0.1 })).done, 2);
  // имена шагов читателя брендбука (on_step) — те же шаги
  assert.equal(foldBrandEvent(BRAND_RUN0, ev({ step: "шрифты", message: "шрифты: VK Sans Display" })).done, 3);
  assert.equal(foldBrandEvent(BRAND_RUN0, ev({ step: "logo" })).done, 4);
  // первый шаг токенов — свой итог по умолчанию
  assert.deepEqual(brandRows({ done: 1, facts: {}, brand: null }, "json", null)[0], { a: "прочитаны токены: ", b: "цвета, шрифты, отступы", state: "done" });
});
test("брендбук: название, подпись карточки, слоя и полосы, палитра на плитке — шесть цветов", () => {
  assert.equal(brandName(SPEC, "x.pdf"), "VK Cloud");
  assert.equal(brandName({ name: "" }, "Брендбук VK Cloud.pdf"), "VK Cloud");
  assert.equal(brandMeta(SPEC), "PDF · 24 стр.");
  assert.equal(brandMeta({ ...SPEC, source: "folder" }), "архив · 4 логотипа");
  assert.equal(brandMeta({ ...SPEC, source: "tokens" }), "токены JSON");
  assert.equal(brandLayerMeta(SPEC, "x", "VK Tech"), "Брендбук VK Cloud.pdf · 24 страницы · применяется к шаблону VK Tech");
  assert.deepEqual(brandPalette(SPEC), ["#0077FF", "#2787F5", "#0B1220", "#FFFFFF", "#FF3985", "#00C2FF"]);
});
test("расхождения: брендбук важнее — что решил сервер; шаблон важнее — как в шаблоне; кружки — у цветов", () => {
  const font: BrandConflict = { what: "Шрифт заголовков", template: "Play", brand: "VK Sans Display", result: "VK Sans Display, замена — Play", kind: "font" };
  const color: BrandConflict = { what: "Второй акцент", template: "#FF3885", brand: "#FF3985", result: "#FF3985", kind: "color" };
  assert.deepEqual(conflictView(font, "brand"), { k: "Шрифт заголовков", a: "Play", b: "VK Sans Display", sw: false, res: "VK Sans Display, замена — Play" });
  assert.equal(conflictView(font, "template").res, "Play, как в шаблоне");
  assert.equal(conflictView(color, "brand").sw, true);
  assert.equal(conflictView(color, "template").res, "#FF3885, как в шаблоне");
});
test("запрос сборки: поля второй ступени — только когда есть данные или брендбук", () => {
  assert.deepEqual(dataRequest([], null, "brand"), {});
  assert.deepEqual(dataRequest(["d1"], null, "template"), { dataset_ids: ["d1"] });
  assert.deepEqual(dataRequest([], "b1", "template"), { brandbook_id: "b1", brand_priority: "template" });
});
test("манифест примера: текст, число слайдов, файлы и брендбук ссылками; без файлов — ошибка", () => {
  const m = parseManifest({ brief: BRIEF, slides: 9, files: [{ name: "a.csv", url: "/api/examples/x/files/a.csv" }, { name: 1 }], brandbook: { name: "b.pdf", url: "/b" } }, "x");
  assert.deepEqual(m, { name: "x", title: null, brief: BRIEF, slides: 9, files: [{ name: "a.csv", url: "/api/examples/x/files/a.csv" }], brandbook: { name: "b.pdf", url: "/b" } });
  let threw = false;
  try {
    parseManifest({ files: [] }, "x");
  } catch {
    threw = true;
  }
  assert.ok(threw);
  assert.equal(parseManifest({ brandbook: { name: "b.pdf", url: "/b" } }, "bb").files.length, 0);
});

test("цели из текста — как их поймёт сборка: таблетки по ответу сервера, без него — прикидка по тексту; строка без ответа", () => {
  const g = (patch: Record<string, unknown>) => ({ quote: "Покажи рост выручки.", dataset_id: "d1", file: "Выручка.csv", task: "dynamics", task_title: "Динамика",
    viz: "line", viz_title: "линейный график", label: "Динамика · «выручка»", ...patch });
  const server = { goals: [g({}), g({ quote: "покажи рост выручки" }), g({ quote: "«сравни регионы»", task: "comparison", viz_title: null, label: "Сравнение категорий", file: null })] };
  assert.deepEqual(goalChips(server as never, goalsOf("покажи долю")), [
    { key: "dynamics|покажи рост выручки", q: "покажи рост выручки", to: "линейный график", title: "Динамика · «выручка» · Выручка.csv" },
    { key: "comparison|сравни регионы", q: "сравни регионы", to: null, title: "Сравнение категорий" },
  ]);
  // сервер ответил «целей нет» — таблеток нет (прикидка не подмешивается)
  assert.deepEqual(goalChips({ goals: [] }, goalsOf("покажи рост выручки")), []);
  // ответа нет — прикидка
  assert.deepEqual(goalChips(null, goalsOf("Покажи рост выручки")).map((c) => [c.q, c.to]), [["покажи рост выручки", "линейный график"]]);
  assert.equal(goalNoteLine([]), null);
  assert.deepEqual(goalNoteLine([{ quote: "Где узкие места?", reason: "в данных нет мощностей." }, { quote: "что с планом", reason: "плана нет" }]), {
    line: "«где узкие места» — в данных нет мощностей · и ещё 1",
    all: "«где узкие места» — в данных нет мощностей\n«что с планом» — плана нет",
  });
  assert.equal(goalsKey("  Покажи   рост ", ["d1", "d2"], true), "1|d1,d2|Покажи рост");
  assert.ok(goalsKey("x", ["d1"], true) !== goalsKey("x", ["d1"], false));
});
