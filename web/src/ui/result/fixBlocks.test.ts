import { test } from "node:test";
import assert from "node:assert/strict";
import { BLOCKS, blockTransform, LAYOUTS, layoutAt, layoutOrder, litAt, startLayout } from "./fixBlocks";

test("эскиз исправления: начинается с формы слайда, дальше — другие раскладки по очереди", () => {
  assert.equal(startLayout("timeline"), "steps");
  assert.equal(startLayout("cards"), "cards");
  assert.equal(startLayout("text"), "text");
  const order = layoutOrder("steps");
  assert.equal(order[0], "steps");
  assert.equal(new Set(order).size, Object.keys(LAYOUTS).length);
  // соседние шаги — разные раскладки: блоки действительно перестраиваются
  for (let s = 0; s < 20; s++) assert.ok(JSON.stringify(layoutAt("steps", s)) !== JSON.stringify(layoutAt("steps", s + 1)), String(s));
});

test("эскиз исправления: следующий круг не повторяет предыдущий кадр в кадр", () => {
  const n = layoutOrder("text").length;
  for (let s = 0; s < n; s++) assert.ok(JSON.stringify(layoutAt("text", s + n)) !== JSON.stringify(layoutAt("text", s)), String(s));
});

test("эскиз исправления: подсвечен видимый блок, блоки — в пределах эскиза, transform — доли эскиза", () => {
  for (let s = 0; s < 30; s++) {
    const l = layoutAt("cards", s);
    assert.ok(l[litAt("cards", s)].o > 0);
    for (const id of BLOCKS) {
      const x = l[id];
      assert.ok(x.x >= 0 && x.y >= 0 && x.x + x.w <= 160 && x.y + x.h <= 90, `${s} ${id}`);
    }
  }
  assert.equal(blockTransform({ x: 16, y: 9, w: 80, h: 45, o: 1 }), "translate(10%, 10%) scale(0.5, 0.5)");
});
