import { test } from "node:test";
import assert from "node:assert/strict";
import { UI0 } from "./geometry";
import { bottomOf, deckMin, heldHeight, improveExtra, phoneGeometry, PHONE_MIN, sameMetrics, STACK_MIN, stackGeometry, type StackMetrics } from "./stack";

// телефон: поле 24, полоса 48; шапки и тела — как их меряет колода
const M: StackMetrics = { pad: 24, strip: 48, h1: 120, b1: 700, h2: 110, b2: 520, c3: 300, m3: 900, k3: 1200, r4: 1500, min: 700, q3: 0 };

test("«Создать», открыт текст: от плиты 01 — шапка и поле, плита 03 — под текстом", () => {
  const g = stackGeometry(UI0, M);
  assert.deepEqual(g.y.slice(0, 3), [0, 144, 688]);
  assert.equal(g.height, 688 + 300 + 24);
  assert.equal(g.y[3], g.height, "плита 04 ждёт под нижним краем колоды");
});

test("«Создать», открыт шаблон: плита 02 — под лентой, от неё видна шапка", () => {
  const g = stackGeometry({ ...UI0, open: "tpl" }, M);
  assert.deepEqual(g.y.slice(0, 3), [0, 724, 858]);
  assert.equal(g.height, 858 + 300 + 24);
});

test("файлы с данными и «Улучшить готовую»: плита 01 — полосой, плита 02 под ней", () => {
  assert.equal(stackGeometry({ ...UI0, data: true }, M).y[1], 48);
  assert.equal(stackGeometry({ ...UI0, improve: true }, M).y[1], 48);
  // на шаге «Шаблон» полосы нет — плита 02 под лентой
  assert.equal(stackGeometry({ ...UI0, data: true, open: "tpl" }, M).y[1], 724);
});

test("«Все параметры»: полосы 01 и 02, плита 03 — всё меню", () => {
  const g = stackGeometry({ ...UI0, more: true }, M);
  assert.deepEqual(g.y.slice(0, 3), [0, 48, 96]);
  assert.equal(g.height, 96 + 900 + 24);
});

test("сборка: плита 03 под двумя полосами, плита 04 — на её месте", () => {
  const g = stackGeometry({ ...UI0, screen: "build" }, M);
  assert.deepEqual(g.y, [0, 48, 96, 96]);
  assert.equal(g.height, 96 + 1200 + 24);
});

test("результат: три полосы, плита 04 под ними", () => {
  const g = stackGeometry({ ...UI0, screen: "result" }, M);
  assert.deepEqual(g.y, [0, 48, 96, 144]);
  assert.equal(g.height, 144 + 1500 + 24);
});

test("короткое содержимое — колода до низа окна", () => {
  const g = stackGeometry({ ...UI0, screen: "result" }, { ...M, r4: 100, min: 800 });
  assert.equal(g.height, 800);
});

test("на компьютерных полях (40/40) стопка повторяет холст: «Создать» 0 / 144 / 556", () => {
  const xl: StackMetrics = { pad: 40, strip: 40, h1: 104, b1: 484, h2: 104, b2: 372, c3: 216, m3: 692, k3: 692, r4: 652, min: 812, q3: 0 };
  assert.deepEqual(stackGeometry(UI0, xl).y.slice(0, 3), [0, 144, 556]);
  assert.deepEqual(stackGeometry({ ...UI0, open: "tpl" }, xl).y.slice(0, 3), [0, 524, 668]);
  assert.deepEqual(stackGeometry({ ...UI0, screen: "result" }, xl).y, [0, 40, 80, 120]);
  assert.equal(stackGeometry({ ...UI0, screen: "result" }, xl).height, 812);
});

test("высота на ходу: растёт сразу, уменьшается после хода", () => {
  assert.equal(heldHeight(1200, 900, false), 1200);
  assert.equal(heldHeight(900, 1200, false), 1200);
  assert.equal(heldHeight(900, 1200, true), 900);
});

test("низ содержимого и сравнение замеров", () => {
  assert.equal(bottomOf(24.4, 100.3), 125);
  assert.ok(sameMetrics(M, { ...M }));
  assert.ok(!sameMetrics(M, { ...M, b2: 521 }));
  assert.ok(sameMetrics(null, null));
  assert.ok(!sameMetrics(M, null));
});

// ── телефон (доски M-create, M-build, M-result): колода 744 под шапкой, плита 03 «Создать» видна на 234
const P: StackMetrics = { ...M, min: 744, q3: 234 };

test("телефон, «Создать»: 01 — ряд 56, 02 под ним, 03 прижата к низу (M-create: 0 / 56 / 510)", () => {
  const g = phoneGeometry(UI0, P);
  assert.deepEqual(g.y, [0, 56, 510, 744]);
  assert.equal(g.height, 744);
  assert.deepEqual(g.vis, [56, 454, 234, 0]);
});

test("телефон, «Создать»: файлы с данными и «Улучшить готовую» — плита 01 полосой 48", () => {
  assert.deepEqual(phoneGeometry({ ...UI0, data: true }, P).y, [0, 48, 510, 744]);
  assert.deepEqual(phoneGeometry({ ...UI0, improve: true }, P).y, [0, 48, 510, 744]);
});

test("телефон, шаблон раскрыт: плита 02 — полоса над прижатой 03", () => {
  const g = phoneGeometry({ ...UI0, open: "tpl" }, P);
  assert.deepEqual(g.y, [0, 462, 510, 744]);
  assert.deepEqual(g.vis, [462, 48, 234, 0]);
});

test("телефон: «Все параметры», сборка (M-build: 03 на 96) и результат (M-result: 04 на 144)", () => {
  assert.deepEqual(phoneGeometry({ ...UI0, more: true }, P).vis, [48, 48, 648, 0]);
  const b = phoneGeometry({ ...UI0, screen: "build" }, P);
  assert.deepEqual([b.y, b.vis], [[0, 48, 96, 96], [48, 48, 648, 648]]);
  const r = phoneGeometry({ ...UI0, screen: "result" }, P);
  assert.deepEqual([r.y, r.vis], [[0, 48, 96, 144], [48, 48, 48, 600]]);
});

test("колода не ниже окна (без нижнего поля) и не ниже порога", () => {
  assert.equal(deckMin(900, 64, 16, STACK_MIN), 820);
  assert.equal(deckMin(500, 64, 16, STACK_MIN), STACK_MIN);
  assert.equal(deckMin(800, 56, 0, PHONE_MIN), 744);
  assert.equal(deckMin(640, 56, 0, PHONE_MIN), 584);
  assert.equal(deckMin(375, 56, 0, PHONE_MIN), PHONE_MIN);
});

test("«Улучшить готовую»: к низу шага — сдвиг и рост поля, без замера — числа доски 88 + 16", () => {
  assert.equal(improveExtra("120px", "0px"), 120);
  assert.equal(improveExtra("", ""), 104);
  assert.equal(improveExtra("96.4px", "8px"), 104);
});
