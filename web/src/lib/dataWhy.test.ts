import { test } from "node:test";
import assert from "node:assert/strict";
import type { HeadlineFact, SlideData, Variant, VariantEdit } from "../types";
import { dataCols, dataFacts, dataWhyCap, dataWhyView, keyFact, keyText, NO_KEY, periodText, rebuiltLast } from "./dataWhy";
import { DATA_SLIDES } from "./dataWhy.fixtures";

// числа и предлоги держатся неразрывным пробелом — сравниваем по словам
const plain = (s: string | null | undefined) => (s ?? "").replace(/[  ]/g, " ");
const variant = (edits: Partial<VariantEdit>[] = []): Variant => ({
  strategy: "structured", outline: null, plan: null, audit: null, run_manifest: null, slides: [], files: {},
  edits: edits.map((e) => ({ at: 0, request: "", reply: "", kind: "edit", slides: [], score_before: null, score_after: null, ...e })),
});

test("«Почему так» слайда с данными (регионы): файл, колонки, профиль, задача, варианты, заголовок-вывод — из SlideData", () => {
  const s = DATA_SLIDES[4];
  const w = dataWhyView(variant(), 4, s, s.data!);
  assert.equal(w.form, "Горизонтальные столбцы");
  assert.equal(w.file, "Регионы.xlsx");
  assert.equal(w.kind, "xlsx");
  assert.equal(w.meta, "XLSX · 8 строк × 3 колонки · сравнение");
  // колонки: имя с единицей, тип (четыре вида, как на холсте), роль
  assert.deepEqual(w.cols.map((c) => [c.name, c.type, c.role]), [
    ["Регион", "категория", "измерение"], ["Выручка, млн ₽", "число", "метрика"], ["Рост, %", "число", "метрика"],
  ]);
  assert.equal(w.more, 0);
  // без оси времени — измерения первыми; нет пропусков и выбросов — «нет», без тона
  assert.deepEqual(w.facts.map((f) => [f.k, plain(f.v), f.tone]), [
    ["Измерения", "Регион — 8 значений", null], ["Метрики", "Выручка, млн ₽ · Рост, %", null], ["Ось времени", "нет", null],
    ["Пропуски", "нет", null], ["Выбросы", "нет", null],
  ]);
  assert.equal(w.task, "Сравнение категорий");
  assert.equal(w.goal, "Цель из текста: «сравни регионы»");
  assert.ok(/^8 регионов и одна главная метрика/.test(w.taskWhy));
  // шесть задач ТЗ, выбранная — одна; «Ключевые значения» — только у карточек показателей
  assert.deepEqual(w.kinds.map((k) => k.t), ["Динамика", "Сравнение категорий", "Структура долей", "Распределение", "Взаимосвязь", "Справочные значения"]);
  assert.deepEqual(w.kinds.filter((k) => k.on).map((k) => k.t), ["Сравнение категорий"]);
  // варианты по рангу: выбранный — доводы, невыбранные — почему не они
  assert.deepEqual(w.vars.map((x) => [x.n, x.name, x.on]), [
    [1, "Ранжированные горизонтальные столбцы", true], [2, "Вертикальные столбцы", false], [3, "Круговая диаграмма", false],
  ]);
  assert.equal(w.vars[0].why, "8 категорий с длинными названиями: подписи слева, порядок — по выручке. Цель «сравни регионы» подтвердила выбор.");
  assert.equal(w.vars[1].why, "Названия регионов не помещаются под столбцами.");
  assert.equal(w.vars[2].why, "8 долей — мелкие сектора нечитаемы.");
  assert.ok(w.vars.every((x) => x.note === null));
  assert.equal(w.vars[1].label, "Вариант 2: Вертикальные столбцы");
  // заголовок-вывод: число заголовка — из фактов, как оно посчитано, тема, которой заголовок не стал
  assert.equal(plain(w.key), "41 %");
  assert.ok(/^Москва — 1 433 млн ₽ из 3 495 млн ₽, это 41%/.test(plain(w.from)));
  assert.equal(w.plain, "Выручка по регионам");
  assert.equal(w.undoable, false);
  assert.equal(dataWhyCap({ n: 4, total: 9 }, s.data!), "Слайд 4 / 9 · Горизонтальные столбцы");
});

test("пересобрано другим вариантом: «Выбран» у него, лучший по данным — со своими доводами, у выбранного — что анализ ставил его ниже", () => {
  const s = DATA_SLIDES[4];
  const d: SlideData = { ...s.data!, chosen: 1 };
  const w = dataWhyView(variant([{ kind: "rebuild", slides: [4] }]), 4, s, d);
  assert.deepEqual(w.vars.map((x) => x.on), [false, true, false]);
  assert.equal(w.vars[0].why, "8 категорий с длинными названиями: подписи слева, порядок — по выручке. Цель «сравни регионы» подтвердила выбор.");
  assert.equal(w.vars[1].why, "8 категорий — каждая отдельным столбцом, сравнение по высоте.");
  assert.equal(w.vars[1].note, "Анализ ставил его ниже: Названия регионов не помещаются под столбцами.");
  assert.equal(w.form, "Столбцы");
  assert.equal(w.undoable, true);
});

test("«Вернуть как было» — только пока последнее изменение варианта — пересборка этого слайда", () => {
  assert.equal(rebuiltLast(variant(), 4), false);
  assert.equal(rebuiltLast(variant([{ kind: "rebuild", slides: [4] }]), 4), true);
  assert.equal(rebuiltLast(variant([{ kind: "rebuild", slides: [4, 5, 6] }]), 5), true); // таблица на три слайда
  assert.equal(rebuiltLast(variant([{ kind: "rebuild", slides: [4] }]), 3), false);
  assert.equal(rebuiltLast(variant([{ kind: "rebuild", slides: [4] }, { kind: "undo", slides: [], undo_of: 1 }]), 4), false);
  assert.equal(rebuiltLast(variant([{ kind: "rebuild", slides: [4] }, { kind: "fix", slides: [4] }]), 4), false);
});

test("ось времени и пропуски (NPS): периоды по-русски, пропущенные кварталы — жёлтой строкой; задача «с пропусками»", () => {
  const s = DATA_SLIDES[7];
  const w = dataWhyView(variant(), 7, s, s.data!);
  assert.deepEqual(w.facts.slice(0, 4).map((f) => [f.k, plain(f.v), f.tone]), [
    ["Ось времени", "IV кв. 2024 — III кв. 2026, 8 кварталов", null], ["Метрики", "NPS · Ответов", null], ["Измерения", "нет", null],
    ["Пропуски", "2 из 8: II кв. 2025, II кв. 2026", "warn"],
  ]);
  assert.equal(w.task, "Динамика с пропусками");
  assert.deepEqual(w.cols.map((c) => c.type), ["дата", "число", "число"]);
  assert.equal(plain(w.key), "52");
});

test("распределение: выбросы — значения жёлтой строкой, как подготовлены данные слайда — синей", () => {
  const s = DATA_SLIDES[6];
  const f = dataFacts(s.data!);
  assert.deepEqual(f.map((x) => [x.k, plain(x.v), x.tone]).slice(3), [
    ["Пропуски", "нет", null], ["Выбросы", "3 значения: 655, 812, 1 430", "warn"],
    ["На слайде", "10 интервалов по 20 мин, последний — «больше 180»; 3 выброса — отдельно", "info"],
  ]);
  const w = dataWhyView(variant(), 6, s, s.data!);
  assert.equal(plain(w.key), "80 %");
  assert.equal(w.form, "Гистограмма");
});

test("карточки показателей: «Ключевые значения» — задача слайда, значок файла — текст, число заголовка со знаком", () => {
  const s = DATA_SLIDES[2];
  const w = dataWhyView(variant(), 2, s, s.data!);
  assert.equal(w.kind, "text");
  assert.equal(w.task, "Ключевые значения");
  assert.equal(w.kinds.length, 7);
  assert.deepEqual(w.kinds.filter((k) => k.on).map((k) => k.t), ["Ключевые значения"]);
  assert.equal(plain(w.key), "+23 %");
  assert.equal(w.form, "Карточки");
});

test("справочник: колонки больше восьми — строкой «и ещё», таблица топ-10 — «Топ-10» не число заголовка", () => {
  const s = DATA_SLIDES[8];
  const w = dataWhyView(variant(), 8, s, s.data!);
  assert.equal(plain(w.key), "38 %"); // «Топ-10» — номер в слове, не число
  assert.equal(w.facts.find((f) => f.k === "На слайде")?.v, "топ-10 и строка «Остальные 230»");
  const many: SlideData = { ...s.data!, columns: Array.from({ length: 11 }, (_, i) => ({ ...s.data!.columns[0], name: `К${i}` })) };
  const c = dataCols(many);
  assert.equal(c.cols.length, 8);
  assert.equal(c.more, 3);
});

test("число заголовка: сначала с «%», к «+N%» — изменение; нет числа из фактов — понятная строка вместо него", () => {
  const f = (id: string, kind: HeadlineFact["kind"], value: number, unit: string | null): HeadlineFact => ({ id, text: id, value, unit, kind, explain: `${id}.` });
  const facts = [f("total", "total", 3495, "млн ₽"), f("share", "share", 41, "%"), f("chg", "change", 41, "%")];
  assert.equal(keyFact("Москва даёт 41% выручки", facts)?.id, "share");
  assert.equal(keyFact("Выручка выросла: +41% за год", facts)?.id, "chg");
  assert.equal(keyFact("Всего 3 495 млн ₽ выручки", facts)?.id, "total");
  assert.equal(keyFact("Выручка по регионам", facts), null);
  assert.equal(plain(keyText(f("c", "change", 23, "%"))), "+23 %");
  assert.equal(plain(keyText(f("c", "change", -8, "%"))), "−8 %");
  assert.equal(plain(keyText(f("v", "leader", 1433, "млн ₽"))), "1 433 млн ₽");
  assert.equal(plain(keyText(f("v", "total", 1.24, "млрд ₽"))), "1,24 млрд ₽");
  // без фактов — заголовок-тема: так и сказано
  const s = DATA_SLIDES[4];
  const w = dataWhyView(variant(), 4, { ...s, headline: "Выручка по регионам" }, { ...s.data!, headline_facts: [] });
  assert.equal(w.key, null);
  assert.equal(w.from, NO_KEY);
  assert.equal(w.plain, null); // заголовок и есть тема
});

test("периоды оси времени по-русски", () => {
  assert.equal(plain(periodText("2025-01")), "январь 2025");
  assert.equal(plain(periodText("2026-Q3")), "III кв. 2026");
  assert.equal(plain(periodText("2025-01-31")), "31 января 2025");
  assert.equal(plain(periodText("2025-03-01T10:00")), "1 марта 2025, 10:00");
  assert.equal(periodText("2025"), "2025");
  assert.equal(periodText("неделя 5"), "неделя 5");
});
