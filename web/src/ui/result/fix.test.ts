import { test } from "node:test";
import assert from "node:assert/strict";
import type { OutlineSlide, SlideFixResult } from "../../types";
import { asSlideFixResult, clock, fixedRows, fixSteps, fixSummary, fixToRevert, lastEditIs, slideEditKind, slideSketch, undoneIn } from "./fix";
import { slideRemarks } from "./marks";
import { CONTRAST, DENSE, MODEL, edit, ev, issue, titleOf, variant } from "./remarks.fixtures";

const plain = (s: string) => s.replace(/ /g, " ");

test("ход исправления: шаги идут по событиям задачи — Критик → Дизайнер → Вёрстка → Проверка", () => {
  const start = fixSteps([], false);
  assert.deepEqual(start.steps.map((s) => [s.name, s.state]), [["Критик", "act"], ["Дизайнер", "wait"], ["Вёрстка", "wait"], ["Проверка", "wait"]]);
  assert.equal(start.steps[0].line, "читает замечания");
  assert.equal(start.steps[3].line, "проверит слайд и соседние");
  const mid = fixSteps([ev("critic", "2 замечания: контраст текста к фону ниже 4,5:1, слайд слишком плотный."), ev("designer", "Переделываю по пожеланию «покажи этапами»")], false);
  assert.deepEqual(mid.steps.map((s) => s.state), ["done", "act", "wait", "wait"]);
  assert.equal(plain(mid.steps[0].line), "2 замечания: контраст текста к фону ниже 4,5:1, слайд слишком плотный");
  assert.equal(plain(mid.steps[1].line), "переделываю по пожеланию «покажи этапами»");
  assert.equal(mid.preview, "wait");
  const late = fixSteps([ev("critic", "1 замечание"), ev("revise", "Слайд собран заново"), ev("compile", "Собран по макету шаблона."),
    ev("check", "Замечаний на слайде не осталось — готовлю превью слайда.")], false);
  assert.deepEqual(late.steps.map((s) => s.state), ["done", "done", "done", "act"]);
  assert.equal(late.preview, "act");
  assert.deepEqual(fixSteps([ev("critic", "1 замечание")], true).steps.map((s) => s.state), ["done", "done", "done", "done"]);
  assert.equal(fixSteps([], true).preview, "done");
});

test("часы хода: минуты и секунды", () => {
  assert.equal(clock(14_400), "0:14");
  assert.equal(clock(65_000), "1:05");
  assert.equal(clock(-5), "0:00");
});

const FIX: SlideFixResult = {
  reply: "Слайд 3: исправлено 2 из 3.", changed: true, applied: true, kind: "fix", strategy: "structured", slide: 3,
  requested: ["contrast_low-3-1", "fill_ratio-3-2", "design_review-3-0"], fixed: ["contrast_low-3-1", "design_review-3-0"],
  remaining: [{ id: "fill_ratio-3-2", check_id: "fill_ratio", severity: "warn", message: "под формулой 5 строк", new: false }],
  score_before: 78.4, new_score: 91.6, changed_other_slides: true, other_slides: [4, 5], how: "model", notes: [], why: null, version: 2, at: 1,
};

test("ответ задачи исправления читается, только если это он", () => {
  assert.equal(asSlideFixResult({ ...FIX, how: "magic", remaining: [{ id: "x", check_id: "y", severity: "boom", message: 3 }] })?.how, "autofix");
  assert.equal(asSlideFixResult({ ...FIX })?.remaining[0].id, "fill_ratio-3-2");
  assert.equal(asSlideFixResult({ reply: "x" }), null);
  assert.equal(asSlideFixResult(null), null);
});

test("«Исправлено»: ряды исправленных — галочкой, оставшиеся — с новым текстом, новые — в конце; номера заново", () => {
  const before = slideRemarks(variant([MODEL, DENSE, CONTRAST]), 3, titleOf);
  const after = slideRemarks(variant([issue({ ...DENSE, message: "под формулой 5 строк" }), issue({ id: "new-3-7", check_id: "margin_violation", bboxes: [{ x: 0.1, y: 0.9, w: 0.5, h: 0.05 }] })]), 3, titleOf);
  const rows = fixedRows(before, FIX, after);
  assert.deepEqual(rows.map((r) => [r.n, r.id, r.done]), [[1, "contrast_low-3-1", true], [2, "fill_ratio-3-2", false], [3, "design_review-3-0", true], [4, "new-3-7", false]]);
  assert.equal(rows[1].text, "Под формулой 5 строк");
  // не применено — ничего не исправлено
  assert.deepEqual(fixedRows(before, { ...FIX, applied: false }, before).map((r) => r.done), [false, false, false]);
});

test("итог исправления: «N из M», было → стало, другие слайды и «Показать»", () => {
  const s = fixSummary(FIX);
  assert.deepEqual([s.fixedN, s.of, s.cap, s.was, s.now, s.line, s.show, s.showTip], [2, 3, "замечания исправлены", 78, 92, "Изменились слайды 4 и 5", 4, "Показать слайды 4 и 5"]);
  const one = fixSummary({ ...FIX, fixed: ["a"], other_slides: [7], changed_other_slides: true });
  assert.deepEqual([one.cap, one.line, one.showTip], ["замечание исправлено", "Изменился слайд 7", "Показать слайд 7"]);
  const none = fixSummary({ ...FIX, fixed: [], other_slides: [], changed_other_slides: false, score_before: null });
  assert.deepEqual([none.cap, none.line, none.show, none.was], ["замечаний исправлены", "Другие слайды не изменились", null, null]);
  assert.equal(fixSummary({ ...FIX, other_slides: [2, 4, 9] }).line, "Изменились слайды 2, 4 и 9");
});

test("«Вернуть как было» — только пока это последнее изменение варианта", () => {
  assert.equal(lastEditIs(variant([], { edits: [edit({ version: 1 }), edit({})] }), 2, "fix"), true);
  assert.equal(lastEditIs(variant([], { edits: [edit({}), edit({ kind: "picture", version: 3 })] }), 2, "fix"), false);
  assert.equal(lastEditIs(variant([], { edits: [edit({}), edit({ kind: "undo", version: 2, undo_of: 2 })] }), 2, "fix"), false);
  assert.equal(lastEditIs(variant([], { edits: [edit({})] }), null, "fix"), false);
  assert.equal(lastEditIs(variant([]), 2, "fix"), false);
});

test("«Вернуть как было» после перезагрузки: последнее изменение варианта — исправление этого слайда", () => {
  const v = variant([], { edits: [edit({ kind: "slide", slides: [5], version: 1 }), edit({ slides: [3], version: 2 })] });
  assert.equal(fixToRevert(v, 3), true);
  assert.equal(fixToRevert(v, 5), false);
  // после него было другое изменение, его отменили или версии нет — возвращать нечего
  assert.equal(fixToRevert(variant([], { edits: [edit({}), edit({ kind: "picture", version: 3 })] }), 3), false);
  assert.equal(fixToRevert(variant([], { edits: [edit({}), edit({ kind: "undo", version: null, undo_of: 2 })] }), 3), false);
  assert.equal(fixToRevert(variant([], { edits: [edit({ version: null })] }), 3), false);
  assert.equal(fixToRevert(variant([], { edits: [edit({ kind: "fix_all", slides: [3, 4] })] }), 3), false);
  assert.equal(fixToRevert(variant([]), 3), false);
  assert.equal(fixToRevert(null, 3), false);
});

const outlineSlide = (patch: Partial<OutlineSlide>): OutlineSlide => ({
  id: "s", kind: "bullets", section: null, headline: "h", subtitle: null, notes: "", fact_refs: [],
  content: { bullets: [], paragraphs: [], items: [], numbers: [], table: null, chart: null, quote: null, quote_author: null, image_hint: null, columns: [] },
  ...patch,
});

test("эскиз исправляемого слайда: форма, которую называет дизайнер, иначе форма слайда по плану", () => {
  const v = variant([], {
    outline: {
      title: "t", subtitle: null, audience: null, purpose: null, strategy: "structured", language: "ru", facts: [], series: [], tables: [],
      slides: [
        outlineSlide({ kind: "title" }), outlineSlide({ kind: "chart", content: { ...outlineSlide({}).content, chart: { type: "pie", series_ids: [], title: null, unit: null, highlight_index: null } } }),
        outlineSlide({ kind: "freeform", content: { ...outlineSlide({}).content, formula: "\\int f(x)dx" } }), outlineSlide({ kind: "timeline" }),
      ],
    },
  });
  assert.deepEqual(slideSketch(v, 1), { kind: "cover", formula: false });
  assert.deepEqual(slideSketch(v, 2), { kind: "pie", formula: false });
  assert.deepEqual(slideSketch(v, 3), { kind: "text", formula: true });
  assert.deepEqual(slideSketch(v, 4), { kind: "timeline", formula: false });
  assert.deepEqual(slideSketch(v, 3, [ev("designer", "«Первообразная» — две колонки с формулой")]), { kind: "compare", formula: true });
  // строка дизайнера без формы («переделываю по замечаниям») эскиз не меняет
  assert.deepEqual(slideSketch(v, 3, [ev("designer", "Переделываю по замечаниям"), ev("designer", "Слайд 3 — правлю оформление по правилам шаблона.")]), { kind: "text", formula: true });
  assert.deepEqual(slideSketch(v, 2, [ev("designer", "Переделываю по замечаниям")].map((e) => ({ ...e, slide: 2 }))), { kind: "pie", formula: false });
  assert.deepEqual(slideSketch(v, 3, [ev("revise", "«Первообразная» — текст с формулой")]), { kind: "text", formula: true });
  assert.deepEqual(slideSketch(v, 9), { kind: "text", formula: false });
});

test("изменение вернули как было в другом месте (лист «Подробнее», помощник) — итога больше нет (C3)", () => {
  // исправление версии 2, потом «верни как было» этой версии
  const undone = variant([], { edits: [edit({ version: 2 }), edit({ kind: "undo", version: 3, undo_of: 2 })] });
  assert.equal(undoneIn(undone, 2), true);
  // вернули другое изменение; ничего не возвращали; версия неизвестна
  assert.equal(undoneIn(variant([], { edits: [edit({ version: 2 }), edit({ kind: "undo", version: 3, undo_of: 1 })] }), 2), false);
  assert.equal(undoneIn(variant([], { edits: [edit({ version: 2 })] }), 2), false);
  assert.equal(undoneIn(undone, null), false);
  assert.equal(undoneIn(null, 2), false);
});

test("slideEditKind: что вернёт «Вернуть как было» слайда — последнее изменение варианта на этом слайде (R9)", () => {
  assert.equal(slideEditKind(variant([], { edits: [edit({}), edit({ kind: "picture", slides: [4], version: 3 })] }), 4), "picture");
  assert.equal(slideEditKind(variant([], { edits: [edit({ kind: "picture", slides: [4], version: 3 })] }), 3), "fix");
  assert.equal(slideEditKind(variant([], { edits: [edit({ kind: "picture", slides: [4], version: 3 }), edit({ undo_of: 3, version: 4 })] }), 4), "picture");
  assert.equal(slideEditKind(variant([], {}), 1), "fix");
});
