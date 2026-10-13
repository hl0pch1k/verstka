import { test } from "node:test";
import assert from "node:assert/strict";
import {
  clampBox, countText, firstRemarkSlide, orderRemarks, plainMessage, remarksSwitch, remarkTitle, remarkTone, slideBadges, slideRemarks, stageMarks, type Remark,
} from "./marks";
import { CONTRAST, DENSE, GRID, MODEL, issue, titleOf, variant } from "./remarks.fixtures";

test("рамка — в долях слайда и внутри него; мелкая или не дробная — не рамка (как сервер `_boxes`)", () => {
  assert.deepEqual(clampBox({ x: 0.161, y: 0.951, w: 0.629, h: 0.08 }), { x: 0.161, y: 0.951, w: 0.629, h: 0.049 });
  assert.deepEqual(clampBox({ x: -0.1, y: 0.2, w: 0.3, h: 0.1 }), { x: 0, y: 0.2, w: 0.2, h: 0.1 });
  assert.equal(clampBox({ x: 0.5, y: 0.5, w: 0.001, h: 0.2 }), null);
  assert.equal(clampBox({ x: 120, y: 40, w: 300, h: 200 }), null);
  assert.equal(clampBox({ x: Number.NaN, y: 0, w: 1, h: 1 }), null);
});

test("порядок замечаний — как на сервере: ошибки, предупреждения, модель; по месту сверху вниз; «весь слайд» — последним", () => {
  const a = issue({ id: "a", severity: "warn", bboxes: [{ x: 0.5, y: 0.5, w: 0.1, h: 0.1 }] });
  const b = issue({ id: "b", severity: "warn" });
  const c = issue({ id: "c", severity: "warn", bboxes: [{ x: 0.1, y: 0.2, w: 0.1, h: 0.1 }] });
  const d = issue({ id: "d", severity: "error" });
  const e = issue({ id: "e", severity: "info", kind: "model" });
  assert.deepEqual(orderRemarks([e, a, b, c, d]).map((i) => i.id), ["d", "c", "a", "b", "e"]);
});

test("название замечания — слова интерфейса, иначе проверки без «(VLM)» и с запятой, иначе важность", () => {
  assert.equal(remarkTitle("contrast_low", "Контраст текста к фону ниже 4.5:1", "warn"), "Контраст текста к фону ниже 4,5:1");
  assert.equal(remarkTitle("design_review", "Взгляд дизайнера (VLM)", "warn"), "Взгляд дизайнера");
  assert.equal(remarkTitle("fill_ratio", null, "warn"), "Слайд слишком пустой или слишком плотный");
  assert.equal(remarkTitle("new_check", null, "err"), "Ошибка");
  assert.equal(remarkTitle("new_check", null, "warn"), "Предупреждение");
  assert.equal(plainMessage("подпись (#9CA3AF на #FFFFFF, 3.1:1) бледная"), "Подпись (3,1:1) бледная");
});

test("замечания слайда: только видимые на сцене, по порядку и с номерами, подписи и значки по важности", () => {
  const rows = slideRemarks(variant([MODEL, DENSE, GRID, CONTRAST, issue({ id: "other", slide: 4 })]), 3, titleOf);
  assert.deepEqual(rows.map((r) => [r.n, r.id, r.tone, r.whole]), [
    [1, "contrast_low-3-1", "err", false], [2, "fill_ratio-3-2", "warn", false], [3, "design_review-3-0", "note", true],
  ]);
  assert.equal(rows[0].title, "Контраст текста к фону ниже 4,5:1");
  assert.equal(rows[0].text, "Подпись под формулой (3,1:1)");
  assert.equal(rows[0].label, "Ошибка");
  assert.equal(rows[0].icon, "alert");
  assert.equal(rows[1].label, "Предупреждение");
  assert.equal(rows[2].label, "Замечание модели · Весь слайд");
  assert.equal(rows[2].icon, "chat-note");
  assert.equal(rows[2].text, "Нет примера. Покажите, как найти первообразную.");
  assert.deepEqual(slideRemarks(variant([]), 3, titleOf), []);
  assert.deepEqual(slideRemarks(null, 3, titleOf), []);
});

test("бейджи миниатюр: число открытых замечаний слайда и цвет худшего", () => {
  const b = slideBadges(variant([MODEL, DENSE, GRID, CONTRAST, issue({ id: "m", slide: 6, severity: "info", kind: "model" }), issue({ id: "deck", slide: 0, severity: "error" })]));
  assert.deepEqual([...b.entries()], [[3, { count: 3, tone: "err" }], [6, { count: 1, tone: "note" }]]);
});

test("замечание модели с важностью «предупреждение» — серое «Замечание модели», как в листе «Подробнее» (C1)", () => {
  const v = variant([MODEL, issue({ id: "slide_content-5-0", slide: 5, check_id: "slide_content", severity: "warn", kind: "model", message: "мало" })]);
  assert.deepEqual([...slideBadges(v).entries()], [[3, { count: 1, tone: "note" }], [5, { count: 1, tone: "note" }]]);
  const [r] = slideRemarks(v, 3, titleOf);
  assert.deepEqual([r.tone, r.label, r.icon], ["note", "Замечание модели · Весь слайд", "chat-note"]);
  // ошибка модели — ошибка; предупреждение правил рядом с замечанием модели — бейдж янтарный
  assert.equal(remarkTone(issue({ severity: "error", kind: "model" })), "err");
  assert.equal(slideBadges(variant([MODEL, DENSE])).get(3)?.tone, "warn");
});

test("включение режима: слайд с замечаниями остаётся, без них — первый слайд с замечаниями", () => {
  const v = variant([issue({ id: "a", slide: 4 }), issue({ id: "b", slide: 7 }), GRID]);
  assert.equal(firstRemarkSlide(v, 7), 7);
  assert.equal(firstRemarkSlide(v, 3), 4);
  assert.equal(firstRemarkSlide(variant([GRID]), 3), null);
});

test("счётчик в шапке панели", () => {
  assert.equal(countText(3), "3 замечания");
  assert.equal(countText(1), "1 замечание");
  assert.equal(countText(0), "нет замечаний");
});

test("«Замечания» в шапке: счётчик только при замечаниях — в режиме без них числа нет, а не янтарный «0»", () => {
  assert.deepEqual(remarksSwitch({ count: 3, errors: true }, false), { shown: true, counter: "warn" });
  assert.deepEqual(remarksSwitch({ count: 3, errors: true }, true), { shown: true, counter: "err" });
  assert.deepEqual(remarksSwitch({ count: 2, errors: false }, true), { shown: true, counter: "warn" });
  assert.deepEqual(remarksSwitch({ count: 0, errors: false }, true), { shown: true, counter: null });
  assert.deepEqual(remarksSwitch({ count: 0, errors: false }, false), { shown: false, counter: null });
});

const row = (r: Partial<Remark>): Remark => ({ id: "r", n: 1, tone: "warn", title: "t", text: "", label: "", icon: "warning", boxes: [], whole: true, ...r });

test("разметка сцены: рамка на каждое место, номер — в левом верхнем углу, выбранная затемняет остальное", () => {
  const rows = slideRemarks(variant([MODEL, DENSE, CONTRAST]), 3, titleOf);
  const m = stageMarks(rows, 0);
  assert.deepEqual(m.frames.map((f) => [f.n, f.tone, f.left, f.top, f.width, f.height, f.on]), [
    [1, "err", "5.21%", "57.41%", "41.25%", "6.67%", true],
    [2, "warn", "2.08%", "68.15%", "77.08%", "18.89%", false],
  ]);
  assert.deepEqual(m.pins.map((p) => [p.n, p.left, p.top, p.on]), [
    [1, "clamp(14px, 5.21%, calc(100% - 14px))", "clamp(14px, 57.41%, calc(100% - 14px))", true],
    [2, "clamp(14px, 2.08%, calc(100% - 14px))", "clamp(14px, 68.15%, calc(100% - 14px))", false],
    [3, "calc(100% - 28px)", "28px", false],
  ]);
  assert.equal(m.pins[2].label, "Замечание 3: Взгляд дизайнера");
  // «весь слайд» выбран — рамка по краю слайда, без затемнения
  const whole = stageMarks(rows, 2).frames.find((f) => f.n === 3);
  assert.deepEqual(whole && [whole.left, whole.top, whole.width, whole.height, whole.on, whole.dim], ["8px", "8px", "calc(100% - 16px)", "calc(100% - 16px)", true, false]);
});

test("разметка сцены: номера на одном месте расходятся, у «всего слайда» — в ряд справа налево; исправленные — галочки", () => {
  const box = [{ x: 0.3, y: 0.3, w: 0.2, h: 0.1 }];
  const rows = [row({ id: "a", n: 1, boxes: box, whole: false }), row({ id: "b", n: 2, boxes: box, whole: false }), row({ id: "c", n: 3 }), row({ id: "d", n: 4 })];
  const m = stageMarks(rows, -1);
  assert.deepEqual(m.pins.map((p) => p.left), [
    "clamp(14px, 30%, calc(100% - 14px))", "clamp(14px, calc(30% + 28px), calc(100% - 14px))", "calc(100% - 28px)", "calc(100% - 60px)",
  ]);
  assert.equal(m.frames.length, 2);
  const done = stageMarks([{ ...rows[0], done: true }, rows[2]], -1);
  assert.deepEqual(done.oks.map((k) => [k.n, k.left, k.label]), [[1, "clamp(14px, 30%, calc(100% - 14px))", "Замечание 1 исправлено"]]);
  assert.deepEqual(done.pins.map((p) => p.n), [3]);
  assert.equal(done.frames.length, 0);
});

test("реестр проверок ещё не ответил: замечание модели с важностью «предупреждение» — «Замечание модели», как его метка (R8)", () => {
  const [r] = slideRemarks(variant([MODEL]), 3, () => null);
  assert.equal(r.tone, "note");
  assert.equal(r.title, "Замечание модели");
  assert.ok(r.label.startsWith("Замечание модели"));
  assert.equal(remarkTitle("design_review", null, "note"), "Замечание модели");
  // ответил — название проверки
  assert.equal(slideRemarks(variant([MODEL]), 3, () => "Взгляд дизайнера (VLM)")[0].title, "Взгляд дизайнера");
});
