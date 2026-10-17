import { test } from "node:test";
import assert from "node:assert/strict";
import { STAGE_H, STAGE_MIN, stageOf, stageScale, stageStyles, unscale } from "./stage";
import { TIER_XL_H } from "./tier";

test("масштаб сцены: окно не ниже холста — 1 (пиксель в пиксель), ниже — во всю высоту окна", () => {
  assert.equal(stageScale(900, true), 1);
  assert.equal(stageScale(1080, true), 1);
  assert.equal(stageScale(760, true), 760 / 900); // жалоба владельца: Safari 1330 × 760
  assert.equal(stageScale(800, true), 800 / 900);
  // уменьшенный холст ровно во всю высоту окна
  for (const h of [675, 700, 760, 800, 899]) assert.ok(Math.abs(STAGE_H * stageScale(h, true) - h) < 1e-6, String(h));
});

test("масштаб не мельче STAGE_MIN; стопка и телефон не уменьшаются; высота не известна — 1", () => {
  assert.equal(stageScale(TIER_XL_H, true), STAGE_MIN);
  assert.equal(stageScale(400, true), STAGE_MIN);
  assert.equal(stageScale(600, false), 1);
  assert.equal(stageScale(390, false), 1);
  assert.equal(stageScale(0, true), 1);
  assert.equal(stageScale(Number.NaN, true), 1);
});

test("стили сцены: 1 — ничего; меньше — страница шире окна в 1/k раз, уменьшена от угла, обёртка — целых px без прокрутки", () => {
  assert.deepEqual(stageStyles(1), {});
  const k = 760 / 900;
  const s = stageStyles(k);
  assert.equal(s.fit?.height, 760);
  assert.equal(s.fit?.overflow, "clip");
  assert.equal(s.root?.transform, `scale(${k})`);
  assert.equal(s.root?.transformOrigin, "0 0");
  assert.equal(s.root?.height, STAGE_H);
  assert.equal(parseFloat(String(s.root?.width)) * k, 100 + 0); // 100 % окна после уменьшения
  // дробная доля пикселя не даёт прокрутки: обёртка не выше уменьшенной сцены
  for (const h of [675, 701, 733, 759, 799, 811, 899]) {
    const kk = stageScale(h, true);
    const fit = Number(stageStyles(kk).fit?.height);
    assert.ok(fit <= h && fit >= h - 1, `${h}: ${fit}`);
  }
});

test("замеры в px раскладки: прямоугольник окна делится на масштаб; вне сцены — 1", () => {
  assert.deepEqual(unscale({ left: 75, top: 150, right: 375, bottom: 300, width: 300, height: 150 }, 0.75),
    { left: 100, top: 200, right: 500, bottom: 400, width: 400, height: 200 });
  const r = { left: 1, top: 2, right: 3, bottom: 4, width: 2, height: 2 };
  assert.equal(unscale(r, 1), r);
  assert.equal(stageOf(null), 1);
  assert.equal(stageOf(undefined), 1);
});
