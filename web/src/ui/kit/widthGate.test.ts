import { test } from "node:test";
import assert from "node:assert/strict";
import { widthGate } from "./widthGate";

test("widthGate: дрожь в долях пикселя посреди хода не проходит, смена ширины на 1 px и больше — проходит", () => {
  const g = widthGate();
  assert.equal(g(372), true); // первая — всегда
  // копия стопки на ходу: клетка + --hpd·--hpp — постоянна до долей пикселя
  for (const w of [372.0001, 371.9998, 372.4, 371.6, 372.9]) assert.equal(g(w), false, String(w));
  assert.equal(g(373), true); // окно стало шире
  assert.equal(g(373.5), false);
  assert.equal(g(360), true);
});

test("widthGate: медленный дрейф не накапливается мимо порога — отсчёт от последней пропущенной", () => {
  const g = widthGate();
  g(100);
  assert.equal(g(100.6), false);
  assert.equal(g(101.2), true);
});
