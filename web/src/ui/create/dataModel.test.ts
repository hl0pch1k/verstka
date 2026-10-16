import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BRAND0, brandOn, conflictsStale, draftOf, expandCard, fileProblem, focusAfter, newCards, nextWaiting, parseDataDraft, sameIds, sourceOfSpec, toSummary,
  usedAfter, USED_MAX, withStatus,
} from "./dataModel";
import type { DataCard } from "./dataRules";
import type { BrandSpec, DatasetSummary } from "../../types";

const sum = (patch: Partial<DatasetSummary> = {}): DatasetSummary => ({
  id: "d1", file: "Регионы.xlsx", kind: "xlsx", rows: 8, cols: 3, nature: "comparison", nature_label: "Сравнение", line: "", issues: [], sheet: null, ...patch,
});
const SPEC: BrandSpec = {
  id: "b1", name: "VK Cloud", source: "pdf", file: "guideline.pdf", pages: 12, colors: [], fonts: [], logos: [], margins_px: null, grid: null,
  rules: [], logo_place: null, warnings: [],
};
let n = 0;
const key = () => `k${++n}`;

test("новые карточки: годные — в очередь, без формата, пустые и больше 25 МБ — сразу с причиной", () => {
  n = 0;
  const cs = newCards([{ name: "a.csv", size: 10 }, { name: "b.pdf", size: 10 }, { name: "c.csv", size: 0 }, { name: "d.json", size: 26 * 1024 * 1024 }], key);
  assert.deepEqual(cs.map((c) => [c.key, c.status, c.error]), [
    ["k1", "wait", null],
    ["k2", "fail", "Такой файл не прочитать — нужен CSV, XLSX, JSON или текст с таблицей"],
    ["k3", "fail", "Файл пустой"],
    ["k4", "fail", "Файл больше 25 МБ"],
  ]);
  assert.equal(fileProblem({ name: "x.tsv", size: 5 }), null);
});
test("очередь: следующая — первая ждущая; статус меняется только у своей карточки", () => {
  const cs: DataCard[] = [
    { key: "a", file: "a.csv", kind: "csv", status: "done", summary: sum(), error: null },
    { key: "b", file: "b.csv", kind: "csv", status: "wait", summary: null, error: null },
    { key: "c", file: "c.csv", kind: "csv", status: "wait", summary: null, error: null },
  ];
  assert.equal(nextWaiting(cs)?.key, "b");
  const run = withStatus(cs, "b", "run");
  assert.deepEqual(run.map((c) => c.status), ["done", "run", "wait"]);
  assert.equal(nextWaiting(run)?.key, "c");
  assert.equal(nextWaiting(withStatus(run, "c", "fail", "x")), null);
});
test("ответ сервера: книга с листами — по карточке на лист, первая на месте исходной; пусто или ошибка — причина", () => {
  const cs: DataCard[] = [
    { key: "a", file: "Регионы.xlsx", kind: "xlsx", status: "run", summary: null, error: null },
    { key: "b", file: "b.csv", kind: "csv", status: "wait", summary: null, error: null },
  ];
  const two = expandCard(cs, "a", [sum({ id: "d1", sheet: "2025" }), sum({ id: "d2", sheet: "2026" })], null);
  assert.deepEqual(two.map((c) => [c.key, c.file, c.status, c.summary?.id]), [
    ["a", "Регионы.xlsx · 2025", "done", "d1"], ["a#1", "Регионы.xlsx · 2026", "done", "d2"], ["b", "b.csv", "wait", undefined],
  ]);
  assert.equal(expandCard(cs, "a", [sum()], null)[0].file, "Регионы.xlsx");
  assert.deepEqual([expandCard(cs, "a", [], null)[0].status, expandCard(cs, "a", [], null)[0].error], ["fail", "Не нашёл таблицу в файле"]);
  assert.equal(expandCard(cs, "a", null, "Файл пустой")[0].error, "Файл пустой");
});
test("поля карточки: профиль и план ответа GET /api/datasets/{id} в карточку (и черновик) не идут", () => {
  const raw = { ...sum(), profile: { big: "x".repeat(5000) }, plan: { y: 1 } } as DatasetSummary;
  const s = toSummary(raw, "d9");
  assert.deepEqual(Object.keys(s).sort(), ["cols", "file", "id", "issues", "kind", "line", "nature", "nature_label", "rows", "sheet"]);
  assert.equal(s.id, "d9");
});
test("«Изменить текст»: те же наборы в том же порядке — карточки не перечитываются", () => {
  assert.equal(sameIds(["d1", "d2"], ["d1", "d2"]), true);
  assert.equal(sameIds(["d2", "d1"], ["d1", "d2"]), false);
  assert.equal(sameIds([], []), true);
});
test("использованные: без повторов, новые в конце, не больше 200", () => {
  assert.deepEqual(usedAfter(["a", "b"], ["b", "c", "c"]), ["a", "b", "c"]);
  const many = usedAfter([], Array.from({ length: 250 }, (_, i) => `d${i}`));
  assert.equal(many.length, USED_MAX);
  assert.equal(many[0], "d50");
});
test("расхождения устарели: брендбук приложен, а сверен не с выбранным шаблоном (или ни с каким)", () => {
  const b = brandOn("b1", SPEC, [], "t1");
  assert.equal(conflictsStale(b, "t1"), false);
  assert.equal(conflictsStale(b, "t2"), true);
  assert.equal(conflictsStale({ ...b, tplFor: null }, "t1"), true);
  assert.equal(conflictsStale(b, null), false);
  assert.equal(conflictsStale({ ...b, phase: "run" }, "t2"), false);
  assert.deepEqual([sourceOfSpec("tokens"), sourceOfSpec("folder"), sourceOfSpec("pdf")], ["json", "dir", "pdf"]);
});
test("черновик: туда и обратно; идущие карточки и испорченное не переживают перезагрузку", () => {
  const cards: DataCard[] = [
    { key: "a", file: "a.csv", kind: "csv", status: "done", summary: { ...sum(), profile: { x: 1 } } as DatasetSummary, error: null },
    { key: "b", file: "b.csv", kind: "csv", status: "run", summary: null, error: null },
    { key: "c", file: "c.pdf", kind: null, status: "fail", summary: null, error: "Такой файл не прочитать" },
  ];
  const brand = brandOn("b1", SPEC, [{ what: "Шрифт", template: "Play", brand: "VK Sans", result: "VK Sans", kind: "font" }], "t1");
  const raw = JSON.parse(JSON.stringify(draftOf(cards, brand, "template", ["d1"])));
  assert.equal("profile" in raw.cards[0].summary, false);
  const d = parseDataDraft(raw);
  assert.deepEqual(d.cards.map((c) => [c.key, c.status]), [["a", "done"], ["c", "fail"]]);
  assert.deepEqual([d.brand.phase, d.brand.id, d.brand.tplFor, d.brand.conflicts.length, d.priority, d.used], ["on", "b1", "t1", 1, "template", ["d1"]]);
  // без брендбука, испорченное
  assert.deepEqual(parseDataDraft({ cards: [{ key: 1 }, { key: "x", file: "x", status: "done", summary: null }], brand: { id: "b" }, priority: "?", used: [1, "u"] }),
    { cards: [], brand: BRAND0, priority: "brand", used: ["u"] });
  assert.deepEqual(parseDataDraft(undefined), { cards: [], brand: BRAND0, priority: "brand", used: [] });
  // брендбук в черновике — только приложенный
  assert.equal(draftOf([], { ...brand, phase: "run" }, "brand", []).brand, null);
});
test("фокус после «убрать»: ✕ следующей карточки, которая не гаснет; иначе предыдущей; карточек нет — null", () => {
  assert.equal(focusAfter(["a", "b", "c"], "b", ["b"]), "c");
  assert.equal(focusAfter(["a", "b", "c"], "b", ["b", "c"]), "a");
  assert.equal(focusAfter(["a", "b", "c"], "c", ["c"]), "b");
  assert.equal(focusAfter(["a"], "a", ["a"]), null);
  assert.equal(focusAfter(["a"], "x", []), null);
});
