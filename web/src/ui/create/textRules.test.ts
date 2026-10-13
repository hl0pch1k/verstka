import { test } from "node:test";
import assert from "node:assert/strict";
import { BRIEF_MIN_TOPIC } from "../../lib/createForm";
import { charsLabel, clipLine, deckError, fileKind, fileTextIssue, improveLive, improveNoteParts, improveShift, improveStep, improveStripMeta, NOT_UTF8, textError, textLine, textPreview, textStrip, TW, TW0, twBlink, twStep, twText, type Tw } from "./textRules";

// ── бриф задачи: textError
test("пустое поле и одни пробелы — empty", () => {
  assert.equal(textError("")?.kind, "empty");
  assert.equal(textError("   \n\t ")?.kind, "empty");
  assert.equal(textError("")?.text, "Напишите, о чём презентация");
});
test(".pdf — type: «Файл «X.pdf» не подойдёт»", () => {
  const e = textError("", { name: "X.pdf" });
  assert.equal(e?.kind, "type");
  assert.equal(e?.text, "Файл «X.pdf» не подойдёт");
  assert.equal(textError("интегралы", { name: "Итоги квартала.pdf" })?.text, "Файл «Итоги квартала.pdf» не подойдёт");
});
test("текст короче BRIEF_MIN_TOPIC — short", () => {
  const short = "и".repeat(BRIEF_MIN_TOPIC - 1);
  assert.equal(textError(short)?.kind, "short");
  assert.equal(textError(`  ${short}  `)?.kind, "short");
  assert.equal(textError("и".repeat(BRIEF_MIN_TOPIC)), null);
});
test("«интегралы» — ошибки нет", () => {
  assert.equal(textError("интегралы"), null);
});
test("файлы, которые поле берёт: .txt и .md — текст, .pptx — «Улучшить готовую»", () => {
  assert.equal(textError("", { name: "Умные сводки.md" }), null);
  assert.equal(textError("", { name: "заметки.TXT" }), null);
  assert.equal(textError("", { name: "Итоги квартала.pptx" }), null);
  assert.equal(fileKind("a.md"), "text");
  assert.equal(fileKind("a.markdown"), "text");
  assert.equal(fileKind("a.pptx"), "deck");
  assert.equal(fileKind("a.ppt"), "deck");
  assert.equal(fileKind("a.odp"), "deck");
  // шаблон оформления — шаг 01, не текст
  assert.equal(fileKind("a.potx"), "other");
  assert.equal(fileKind("a.docx"), "other");
  assert.equal(fileKind("без расширения"), "other");
});
test("настройки в начале текста («---» … «---») — не текст: поле пустое", () => {
  assert.equal(textError("---\nslides: 8\n---\n")?.kind, "empty");
});

// ── печатающаяся подсказка: ритм V2 `twTick`
const run = (s: Tw, n: number) => {
  const out: { s: Tw; ms: number }[] = [];
  for (let i = 0; i < n; i += 1) {
    const r = twStep(s);
    out.push(r);
    s = r.s;
  }
  return out;
};
test("подсказка: сначала фраза целиком держится 3000 мс с мигающим курсором, потом стирается по 25 мс", () => {
  assert.equal(twText(TW0), `Например: ${TW[0]}`);
  assert.equal(twBlink(TW0), true);
  const steps = run(TW0, 5);
  // пять тиков по 500 мс в «держим» (плюс 500 мс, с которыми фраза дописалась) — 3000 мс
  assert.deepEqual(steps.map((x) => x.ms), [500, 500, 500, 500, 500]);
  assert.equal(steps[4].s.mode, "erase");
  const erase = twStep(steps[4].s);
  assert.equal(erase.ms, 25);
  assert.equal(erase.s.n, TW[0].length - 1);
  assert.equal(twBlink(erase.s), false);
});
test("подсказка: стёрта — пауза 400 мс, затем следующая фраза печатается по 45 мс на знак", () => {
  let s: Tw = { i: 0, n: 1, mode: "erase", k: 0 };
  let r = twStep(s);
  assert.equal(r.s.n, 0);
  assert.equal(r.s.mode, "pause");
  assert.equal(r.ms, 400);
  assert.equal(twBlink(r.s), true);
  r = twStep(r.s);
  assert.equal(r.s.i, 1);
  assert.equal(r.s.n, 1);
  assert.equal(r.s.mode, "type");
  assert.equal(r.ms, 45);
  assert.equal(twText(r.s), `Например: ${TW[1].slice(0, 1)}`);
  s = { i: 1, n: TW[1].length - 1, mode: "type", k: 0 };
  r = twStep(s);
  assert.equal(r.s.mode, "hold");
  assert.equal(r.ms, 500);
  // последняя фраза — по кругу к первой
  r = twStep({ i: TW.length - 1, n: 0, mode: "pause", k: 0 });
  assert.equal(r.s.i, 0);
});

// ── строки поля
test("счётчик знаков: тысячи через пробел, слово по числу", () => {
  assert.equal(charsLabel(0), "0 знаков");
  assert.equal(charsLabel(1), "1 знак");
  assert.equal(charsLabel(1551), "1 551 знак");
  assert.equal(charsLabel(1399), "1 399 знаков");
  assert.equal(charsLabel(12345), "12 345 знаков");
});
test("строка под полем: пустое поле и тема — подсказка агента, готовый текст — разбор", () => {
  assert.deepEqual(textLine("", true), { kind: "topic" });
  assert.deepEqual(textLine("История VK", true), { kind: "topic" });
  // без пишущего агента тема строится как есть — подсказки о нём нет
  assert.equal(textLine("История VK", false).kind, "facts");
  // «Проблема» — часть презентации, не обложка: обложка встанет перед ней (3 слайда); «2 дня» и ячейки таблицы — числа
  const full = "Слайд 1. Проблема\nКлиенты ждут ответа 2 дня\nСлайд 2. Решение\nБот отвечает сразу\n| A | B |\n|---|---|\n| 1 | 2 |";
  assert.deepEqual(textLine(full, true), { kind: "facts", facts: "3 слайда, 3 числа, 1 таблица" });
  // о своём проекте агент не пишет — текст строится как есть
  assert.equal(textLine("Наш продукт", true).kind, "facts");
  assert.deepEqual(textLine("Наш продукт", true), { kind: "facts", facts: null });
});
test("свёрнутый шаг: «тема» в кавычках или «Тема ещё не задана»", () => {
  assert.deepEqual(textPreview(""), { text: "Тема ещё не задана", empty: true });
  assert.deepEqual(textPreview("  Интеграл \n"), { text: "«Интеграл»", empty: false });
  assert.equal(textPreview("Первая строка\nвторая").text, "«Первая строка»");
  const long = textPreview("слово ".repeat(40)).text;
  assert.ok(long.endsWith("…»"));
  assert.ok(long.length <= 64);
});
test("обрезка строки по слову", () => {
  assert.equal(clipLine("коротко", 20), "коротко");
  assert.equal(clipLine("раз два три четыре", 12), "раз два три…");
});
test("полоса 02: тема — «тема · текст пишет агент», готовый текст — его разбор, «Улучшить готовую» — презентация", () => {
  const strip = (text: string, improve?: Parameters<typeof textStrip>[1]["improve"]) => textStrip(text, { line: textLine(text, true), improve });
  assert.deepEqual(strip(""), { title: "Тема ещё не задана" });
  assert.deepEqual(strip("Интеграл"), { title: "Интеграл", meta: "тема · текст пишет агент" });
  assert.deepEqual(strip("Слайд 1. Итоги\nВыручка 18 %\nСлайд 2. Клиенты\nтекст"), { title: "Слайд 1. Итоги", meta: "готовый текст · 3 слайда, 1 число" });
  assert.deepEqual(strip("Наш продукт"), { title: "Наш продукт", meta: "готовый текст" });
  const src = { brief: "Слайд 1. Итоги", name: "Итоги квартала.pptx", slides: 14, tables: 3, charts: 4, pictures: 6 };
  assert.deepEqual(strip("Слайд 1. Итоги", src), { title: "Итоги квартала", meta: "текст из презентации · 14 слайдов" });
});
test("полоса 02 берёт готовую строку разбора, сама текст не разбирает", () => {
  const line = { kind: "facts" as const, facts: "9 слайдов" };
  assert.deepEqual(textStrip("Слайд 1. Итоги", { line }), { title: "Слайд 1. Итоги", meta: "готовый текст · 9 слайдов" });
  assert.deepEqual(textStrip("Интеграл", { line: { kind: "topic" } }), { title: "Интеграл", meta: "тема · текст пишет агент" });
});

// ── «Улучшить готовую»
const SRC = {
  brief: "", name: "Итоги квартала.pptx", slides: 14, tables: 3, charts: 4, pictures: 6,
  audit: { score: 62, errors: 2, warnings: 5 },
  problems: Array.from({ length: 9 }, (_, i) => ({ slide: i + 1, code: "x", text: "y" })),
};
const plain = (parts: { t: string; b?: boolean }[]) => parts.map((p) => p.t).join("");
const bold = (parts: { t: string; b?: boolean }[]) => parts.filter((p) => p.b).map((p) => p.t);
test("заметка: всё, что есть в исходной презентации, и что будет дальше (как на доске C-improve)", () => {
  const parts = improveNoteParts(SRC, true);
  assert.equal(plain(parts), "Текст и оформление — из презентации «Итоги квартала»: 14 слайдов, 3 таблицы, 4 диаграммы, 6 изображений. Оценка исходной презентации — 62 из 100. Модель нашла в ней 9 проблем вёрстки. Слайды останутся те же, вёрстка соберётся заново, а модель посмотрит на каждый новый слайд.");
  assert.deepEqual(bold(parts), ["«Итоги квартала»", "62 из 100", "9 проблем вёрстки"]);
});
test("заметка: без оценки, без замечаний, без модели — только то, что известно", () => {
  const parts = improveNoteParts({ ...SRC, title: "Квартал", audit: null, problems: [], tables: 0, charts: 1, pictures: 0, slides: 1 }, false);
  assert.equal(plain(parts), "Текст и оформление — из презентации «Квартал»: 1 слайд, 1 диаграмма. Слайды останутся те же, вёрстка соберётся заново.");
});
test("полоса 01 в «Улучшить готовую»: число слайдов и откуда оформление", () => {
  assert.equal(improveStripMeta(SRC), "14 слайдов · оформление из презентации");
  assert.equal(improveStripMeta({ ...SRC, slides: 1 }), "1 слайд · оформление из презентации");
});
test("поле под заметкой: две строки — как на доске (88 и 16), выше — уходит дальше и растёт меньше", () => {
  assert.deepEqual(improveShift(72), { shift: 88, grow: 16 });
  assert.deepEqual(improveShift(0), { shift: 88, grow: 16 });
  assert.deepEqual(improveShift(92), { shift: 108, grow: 0 });
  assert.deepEqual(improveShift(80), { shift: 96, grow: 8 });
});
test("презентацию не прочитали: одна целая фраза у поля, о презентации, а не о шаблоне", () => {
  const n = "Итоги квартала.pptx";
  assert.equal(deckError("Не удалось загрузить шаблон: Файл не похож на презентацию. Загрузите шаблон PowerPoint (.pptx, .potx, .ppt) или OpenDocument (.odp).", n), "Файл не похож на презентацию.");
  assert.equal(deckError("Не удалось загрузить шаблон: Сеть недоступна: Failed to fetch", n), "Не удалось загрузить презентацию: Сеть недоступна");
  assert.equal(deckError("Не получилось: Не удалось прочитать текст презентации — она добавлена как шаблон", n), "Не удалось прочитать текст презентации — она добавлена как шаблон");
  assert.equal(deckError("Не получилось: Couldn't find end of Start Tag", n), "Не удалось прочитать презентацию «Итоги квартала»");
  assert.equal(deckError("Шаблон разобран, но не загрузился: Сеть недоступна", n), "Презентация прочитана, но не загрузилась — попробуйте ещё раз");
  assert.equal(deckError("Не получилось: OSError", ""), "Не удалось прочитать презентацию");
});

// ── число слайдов неизвестно («Изменить текст» на презентации без числа): строки без «0 слайдов»
test("число слайдов неизвестно: в заметке, полосе 01 и полосе 02 числа нет, точки и разделители целы", () => {
  const blank = { brief: "", name: "Итоги квартала.pptx", tables: 0, charts: 0, pictures: 0 };
  assert.equal(plain(improveNoteParts(blank, false)), "Текст и оформление — из презентации «Итоги квартала». Слайды останутся те же, вёрстка соберётся заново.");
  assert.equal(plain(improveNoteParts({ ...blank, charts: 2 }, false)), "Текст и оформление — из презентации «Итоги квартала»: 2 диаграммы. Слайды останутся те же, вёрстка соберётся заново.");
  assert.equal(improveStripMeta(blank), "оформление из презентации");
  assert.equal(improveStripMeta({ ...blank, slides: 0 }), "оформление из презентации");
  assert.deepEqual(textStrip("Слайд 1. Итоги", { line: textLine("Слайд 1. Итоги", true), improve: blank }), { title: "Итоги квартала", meta: "текст из презентации" });
});

// ── файл .txt/.md: что поле скажет о прочитанном тексте
test("файл не в UTF-8 (знак замены U+FFFD) — строка у поля, а не кракозябры в поле", () => {
  assert.deepEqual(fileTextIssue("Привет \uFFFD\uFFFD\uFFFD", "Старый.txt"), { kind: "file", text: NOT_UTF8 });
  assert.equal(NOT_UTF8, "Файл не в кодировке UTF-8 — сохраните его в UTF-8 и загрузите снова");
  // знак замены сильнее пустоты: файл из одних битых байтов — тоже не UTF-8
  assert.equal(fileTextIssue("\uFFFD", "a.md")?.text, NOT_UTF8);
});
test("файл: пустой — строка «Файл «X» пустой», нормальный — без замечаний", () => {
  assert.deepEqual(fileTextIssue("", "пустой.txt"), { kind: "file", text: "Файл «пустой.txt» пустой" });
  assert.equal(fileTextIssue("   \n\t", "пробелы.md")?.text, "Файл «пробелы.md» пустой");
  assert.equal(fileTextIssue("Умные сводки\nСлайд 1", "Умные сводки.md"), null);
});

// ── «Улучшить готовую»: когда режим кончается
test("режим: ввод в поле его держит", () => {
  let live = improveLive("t1");
  let r = improveStep(live, "Слайд 1. Итоги", "t1");
  assert.equal(r.ends, false);
  live = r.live;
  for (const typed of ["Слайд 1. Итоги\n", "Слайд 1. Итоги\nВыручка", "Выручка"]) {
    r = improveStep(live, typed, "t1");
    assert.equal(r.ends, false, typed);
    live = r.live;
  }
});
test("режим: очистка поля (и одни пробелы) его кончает", () => {
  const live = improveStep(improveLive("t1"), "Слайд 1. Итоги", "t1").live;
  assert.equal(improveStep(live, "", "t1").ends, true);
  assert.equal(improveStep(live, " \n\t", "t1").ends, true);
});
test("режим: другой шаблон его кончает, тот же — нет", () => {
  const live = improveStep(improveLive("t1"), "Слайд 1. Итоги", "t1").live;
  assert.equal(improveStep(live, "Слайд 1. Итоги", "t2").ends, true);
  assert.equal(improveStep(live, "Слайд 1. Итоги", null).ends, true);
  assert.equal(improveStep(live, "Слайд 1. Итоги", "t1").ends, false);
  // презентация без шаблона (null): режим держится, пока шаблон не выбран другой
  const bare = improveStep(improveLive(null), "Слайд 1. Итоги", null).live;
  assert.equal(improveStep(bare, "Слайд 1. Итоги", null).ends, false);
  assert.equal(improveStep(bare, "Слайд 1. Итоги", "t3").ends, true);
});
test("режим: презентация без текста не кончается с первого прохода — только когда текст появился и его стёрли", () => {
  let r = improveStep(improveLive("t1"), "", "t1");
  assert.equal(r.ends, false);
  r = improveStep(r.live, "  ", "t1");
  assert.equal(r.ends, false);
  r = improveStep(r.live, "Тема", "t1");
  assert.equal(r.ends, false);
  assert.equal(improveStep(r.live, "", "t1").ends, true);
  // другой шаблон кончает и пустую
  assert.equal(improveStep(improveLive("t1"), "", "t2").ends, true);
});
