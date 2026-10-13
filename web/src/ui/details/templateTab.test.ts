import { test } from "node:test";
import assert from "node:assert/strict";
import { TPL } from "./details.fixtures";
import { bandOf, copyHint, fontRows, layoutsOf, paletteOf, rulesOf } from "./templateTab";

test("обзор: имя, формат, слайды, типы слайдов и шрифт", () => {
  assert.deepEqual(bandOf(TPL), {
    name: "VK Tech", font: "Play",
    facts: [{ v: "16:9", l: "формат" }, { v: "54", l: "слайда" }, { v: "5", l: "типов слайдов" }],
  });
});

test("палитра: до шести цветов по доле, без почти одинаковых; подсказка — цвет и его роль", () => {
  const p = paletteOf(TPL);
  assert.deepEqual(p.map((c) => c.hex), ["#FAFCFF", "#000000", "#8F8F8F", "#0077FF", "#00D3E6", "#C4C4C4"]);
  assert.equal(p[3].tip, "#0077FF · фирменный · нажмите, чтобы скопировать");
  assert.equal(p[0].tip, "#FAFCFF · светлый фон · нажмите, чтобы скопировать");
});

test("строка палитры: подсказка, «скопирован» и неудача", () => {
  assert.equal(copyHint(null), "нажмите, чтобы скопировать");
  assert.equal(copyHint({ hex: "#0077FF", ok: true }), "Цвет #0077FF скопирован");
  assert.equal(copyHint({ hex: "#0077FF", ok: false }), "Не удалось скопировать");
});

test("правила: только выведенные из шаблона и законченные фразы, без повторов шрифта и цветов", () => {
  assert.deepEqual(rulesOf(TPL), ["Карточки и блоки со скруглёнными углами.", "Текст выравнивается по левому краю (исключения: схемы и таблицы)."]);
});

test("шрифты и поля: шкала шрифтов и поля в процентах", () => {
  assert.deepEqual(fontRows(TPL), [
    { a: "Заголовок", b: "Play · 24 пт" }, { a: "Текст", b: "Play · 9 пт" }, { a: "Поля", b: "слева 2\u00a0%, справа 3\u00a0%, сверху 6\u00a0%, снизу 13\u00a0%" },
  ]);
});

test("макеты: шесть первых, «Все N» — все; лесенка 40 мс", () => {
  const six = layoutsOf(TPL, false);
  assert.equal(six.length, 6);
  assert.deepEqual(six.slice(0, 2).map((l) => [l.n, l.kind, l.delay]), [[1, "Титул", "200ms"], [2, "Титул", "240ms"]]);
  const all = layoutsOf(TPL, true);
  assert.equal(all.length, 7);
  assert.equal(all[6].delay, "0ms");
});
