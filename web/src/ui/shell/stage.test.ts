import { test } from "node:test";
import assert from "node:assert/strict";
import { STAGE_H, STAGE_MIN, STAGE_W, stageOf, stageScale, stageStyles, unscale } from "./stage";

test("масштаб сцены: окно не ниже холста и не уже 1280 — 1; иначе — помещается по высоте и по ширине, шаг 1/40", () => {
  assert.equal(stageScale(1440, 900), 1);
  assert.equal(stageScale(1920, 1080), 1);
  assert.equal(stageScale(1330, 760), 0.825); // жалоба владельца: Safari 1330 × 760 (760/900 = 0.844 → 0.825)
  assert.equal(stageScale(1440, 800), 0.875);
  assert.equal(stageScale(1024, 900), 0.8); // уже 1280 — по ширине
  assert.equal(stageScale(390, 844), 0.3); // телефон — тот же компьютер, уменьшенный
  for (const [w, h] of [[1330, 760], [1100, 700], [1600, 640], [800, 1200]]) {
    const k = stageScale(w, h);
    assert.ok(STAGE_H * k <= h + 1e-6 && STAGE_W * k <= w + 1e-6, `${w}x${h}`);
    assert.equal(Math.round(k * 40), k * 40); // шаг 1/40 — без дробной дрожи
  }
});

test("масштаб не мельче STAGE_MIN; размер не известен — 1", () => {
  assert.equal(stageScale(100, 100), STAGE_MIN);
  assert.equal(stageScale(0, 0), 1);
  assert.equal(stageScale(Number.NaN, Number.NaN), 1);
});

test("стили сцены: 1 — ничего; меньше — zoom, ширина страницы в px (окно / k), обёртка — целых px без прокрутки", () => {
  assert.deepEqual(stageStyles(1, 1440), {});
  const k = stageScale(1330, 760);
  const s = stageStyles(k, 1330);
  assert.equal(s.root?.zoom, k);
  assert.equal(s.root?.transform, undefined);
  assert.equal(s.root?.height, STAGE_H);
  assert.equal(s.root?.width, Math.floor(1330 / k));
  assert.equal(s.fit?.overflow, "clip");
  assert.ok(Number(s.fit?.height) <= 760);
});

test("замеры в px раскладки: прямоугольник окна делится на масштаб; вне сцены — 1", () => {
  assert.deepEqual(unscale({ left: 75, top: 150, right: 375, bottom: 300, width: 300, height: 150 }, 0.75),
    { left: 100, top: 200, right: 500, bottom: 400, width: 400, height: 200 });
  const r = { left: 1, top: 2, right: 3, bottom: 4, width: 2, height: 2 };
  assert.equal(unscale(r, 1), r);
  assert.equal(stageOf(null), 1);
  assert.equal(stageOf(undefined), 1);
});
