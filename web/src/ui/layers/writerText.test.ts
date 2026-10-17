import { test } from "node:test";
import assert from "node:assert/strict";
import type { WriterInfo } from "../../types";
import { firstSource, linePieces, sourceLine, textStripMeta, writerByline, writerSlides, writtenText, type WriterSource } from "./writerText";

const WIKI = "https://ru.wikipedia.org/wiki/Интеграл";
const S: WriterSource[] = [
  { text: "Знак ∫ ввёл Лейбниц в 1675 году.", page: "Интеграл", url: WIKI, sentence: "Обозначение ∫ ввёл Лейбниц в 1675 году." },
  { text: "Строгое определение дал Риман;", page: "Интеграл", url: WIKI, sentence: "Строгое определение интеграла дал Риман (1854)." },
  { text: "", page: "Интеграл", url: WIKI, sentence: "Пустое утверждение." },
];

const TEXT = [
  "Слайд 1. Титульный",
  "Название: «Интеграл».",
  "",
  "Слайд 2. История создания",
  "Интеграл придумали давно. Знак ∫ ввёл Лейбниц в 1675 году. Строгое определение дал Риман",
  "- Термин ввёл Бернулли.",
  "",
  "",
].join("\n");

const W = (over: Partial<WriterInfo> = {}): WriterInfo => ({
  mode: "topic", status: "written", text: TEXT, source: { title: "Интеграл", url: WIKI }, ...over,
});

test("текст по слайдам: «Слайд N. Заголовок» — номер и заголовок, строки тела как написаны, пустые строки — разделители", () => {
  const sl = writerSlides(TEXT, []);
  assert.deepEqual(sl.map((s) => [s.n, s.title, s.lines.length]), [[1, "Титульный", 1], [2, "История создания", 2]]);
  assert.deepEqual(sl[1].lines[1], [{ text: "- Термин ввёл Бернулли.", src: null }]);
});

test("текст без заголовков слайдов — один блок без номера; пустой текст — пусто", () => {
  const sl = writerSlides("Первая строка.\nВторая строка.", []);
  assert.deepEqual(sl.map((s) => [s.n, s.title, s.lines.length]), [[null, "", 2]]);
  assert.deepEqual(writerSlides("  \n\n", []), []);
  // строки до первого заголовка — свой блок без номера, затем слайды
  assert.deepEqual(writerSlides("Вступление.\nСлайд 1. Обложка\nТекст.", []).map((s) => [s.n, s.title]), [[null, ""], [1, "Обложка"]]);
});

test("предложение с источником — отдельный кусок с номером источника; точка или «;» в конце утверждения не мешает", () => {
  const p = linePieces("Интеграл придумали давно. Знак ∫ ввёл Лейбниц в 1675 году. Строгое определение дал Риман", S);
  assert.deepEqual(p, [
    { text: "Интеграл придумали давно. ", src: null },
    { text: "Знак ∫ ввёл Лейбниц в 1675 году.", src: 0 },
    { text: " ", src: null },
    { text: "Строгое определение дал Риман", src: 1 },
  ]);
  // нет источников — строка целиком
  assert.deepEqual(linePieces("Просто строка.", []), [{ text: "Просто строка.", src: null }]);
  // пустое утверждение ни с чем не совпадает
  assert.deepEqual(linePieces("Пустое утверждение.", [S[2]]), [{ text: "Пустое утверждение.", src: null }]);
});

test("пересекающиеся утверждения: остаётся первое найденное, второе не режет его", () => {
  const over: WriterSource[] = [
    { text: "Лейбниц в 1675 году", page: "", url: "", sentence: "a" },
    { text: "ввёл Лейбниц", page: "", url: "", sentence: "b" },
  ];
  assert.deepEqual(linePieces("Знак ввёл Лейбниц в 1675 году.", over), [
    { text: "Знак ввёл ", src: null },
    { text: "Лейбниц в 1675 году", src: 0 },
    { text: ".", src: null },
  ]);
});

test("первый источник по порядку чтения; источников в тексте нет — null", () => {
  assert.equal(firstSource(writerSlides(TEXT, S)), 0);
  assert.equal(firstSource(writerSlides(TEXT, [S[1]])), 0);
  assert.equal(firstSource(writerSlides(TEXT, [])), null);
});

test("подпись под заголовком: по статье, по статьям, по своим знаниям", () => {
  assert.deepEqual(writerByline(W()), { lead: "Написал агент по статье", pages: [{ title: "Интеграл", url: WIKI }], tail: "из Википедии" });
  const two = writerByline(W({ pages: [{ title: "Интеграл", url: WIKI }, { title: "Первообразная", url: "u2" }] }));
  assert.equal(two.lead, "Написал агент по статьям");
  assert.equal(two.pages.length, 2);
  assert.deepEqual(writerByline(W({ source: null })), { lead: "Написал агент по своим знаниям", pages: [], tail: "" });
});

test("строка «Источник»: выбранное предложение статьи и ссылка на него; без источников — статья; без статьи — без ссылки", () => {
  const sel = sourceLine(W(), S, 0);
  assert.equal(sel.quote, "«Обозначение ∫ ввёл Лейбниц в 1675 году.»");
  assert.equal(sel.label, "Википедия");
  assert.ok(sel.href?.startsWith(`${WIKI}#:~:text=`));
  assert.ok(sel.href?.includes(encodeURIComponent("Обозначение ∫ ввёл Лейбниц в 1675")));
  const art = sourceLine(W(), [], null);
  assert.deepEqual([art.quote, art.href, art.label], ["статья «Интеграл» в Википедии", WIKI, "Википедия"]);
  const two = sourceLine(W({ pages: [{ title: "Интеграл", url: WIKI }, { title: "Первообразная", url: "u2" }] }), [], null);
  assert.equal(two.quote, "статьи «Интеграл» и «Первообразная» в Википедии");
  const own = sourceLine(W({ source: null }), [], null);
  assert.deepEqual([own.quote, own.href], ["знания агента — проверьте даты и цифры", null]);
  // источник без адреса — ссылка на статью
  assert.equal(sourceLine(W(), [{ ...S[0], url: "" }], 0).href, WIKI);
});

test("текст для слоя есть только у написанного агентом", () => {
  assert.equal(writtenText(W()), TEXT);
  assert.equal(writtenText(W({ status: "failed" })), null);
  assert.equal(writtenText(W({ text: "   " })), null);
  assert.equal(writtenText(null), null);
});

test("полоса «04 Результат» над слоем: вариант · оценка · слайд N из M", () => {
  assert.equal(textStripMeta("Структурный", 89, 3, 12), "Структурный · 89 из 100 · слайд 3 из 12");
  assert.equal(textStripMeta("Визуальный", null, 1, 12), "Визуальный · слайд 1 из 12");
  assert.equal(textStripMeta("Компактный", 88.6, 2, 0), "Компактный · 89 из 100");
});

test("текст по базе знаний: подпись и строка источника — документ и место, без Википедии", () => {
  const w = { mode: "topic", status: "written", basis: "kb", kb: { id: "k", name: "Квартал", docs: [{ id: "a", title: "Отчёт Q3" }] },
    pages: [{ title: "Отчёт Q3", url: "" }, { title: "Клиенты", url: "" }] } as unknown as Parameters<typeof writerByline>[0];
  assert.deepEqual(writerByline(w).lead, "Написал агент по базе знаний «Квартал»:");
  const src = { text: "NPS вырос до 44", page: "Клиенты", url: "", sentence: "раздел «Удовлетворённость», абз. 3: Индекс NPS вырос с 31 до 44." };
  const line = sourceLine(w, [src], 0);
  assert.equal(line.href, null);
  assert.ok(line.quote.startsWith("«раздел «Удовлетворённость»"));
  assert.equal(line.title, "Документ «Клиенты» базы знаний");
  assert.ok(!sourceLine(w, [], null).quote.includes("Википеди"));
});
