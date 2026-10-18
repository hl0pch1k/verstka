import { test } from "node:test";
import assert from "node:assert/strict";
import { eraserOf, insetLine, moveCss, sameBoxes, scaleCss, shiftOf, stretchOf } from "./helperMotion";

const B = (x: number, y: number, w: number, h: number) => ({ x, y, w, h });

test("ход помощника: сдвиг к месту другой раскладки — за вычетом сдвига помеченного предка; на месте — ничего", () => {
  assert.deepEqual(shiftOf(B(1230, 52, 114, 40), B(814, 52, 114, 40)), { dx: -416, dy: 0 });
  assert.deepEqual(shiftOf(B(958, 470, 362, 24), B(849, 470, 55, 24), { dx: -10, dy: 0 }), { dx: -99, dy: 0 });
  assert.equal(moveCss({ dx: -416, dy: 0 }), "translate(-416px, 0px)");
  assert.equal(moveCss({ dx: 0.2, dy: -0.3 }), null);
});

test("ход помощника: сцена — сдвиг и масштаб по ширине, начало масштаба — её угол в обёртке", () => {
  const s = scaleCss(B(48, 216, 832, 468), B(48, 304, 672, 378), B(40, 216, 848, 468));
  assert.ok(s);
  assert.equal(s!.transform, "translate(0px, 88px) scale(0.8077)");
  assert.equal(s!.origin, "8px 0px");
  assert.equal(scaleCss(B(10, 10, 100, 50), B(10, 10, 100, 50), B(0, 0, 200, 50)), null);
});

test("ход помощника: ластик ленты — от её правого края, на сколько она у́же (и запас под обводку)", () => {
  const e = eraserOf(B(44, 692, 840, 79), B(44, 690, 680, 79), B(0, 120, 1392, 812));
  assert.deepEqual(e, { x: 884, y: 568, w: 176, h: 87, dx: -160, dy: -2 });
  assert.equal(eraserOf(B(0, 0, 100, 10), B(0, 0, 100, 10), B(0, 0, 200, 20)), null);
});

test("ход помощника: «растяжка» коробки — края по скруглению, середина сжимается, правый край едет на разницу", () => {
  const k = stretchOf(1104, 688, 24);
  assert.ok(k);
  assert.equal(k!.r, 24);
  assert.equal(k!.mid, 1057);
  assert.equal(k!.right, 1080);
  assert.equal(k!.cut, 416);
  // правый конец середины в узкой раскладке — там же, где левый край правого куска (+1 px нахлёста)
  assert.ok(Math.abs(24 + k!.mid * k!.scale - (k!.right - k!.cut + 1)) < 0.1);
  assert.equal(stretchOf(200, 200, 24), null);
  // скругление не больше половины узкой коробки
  assert.equal(stretchOf(60, 40, 24)!.r, 20);
});

test("ход помощника: обводка коробки — цвет из «inset 0 0 0 1px»", () => {
  assert.equal(insetLine("rgba(255, 255, 255, 0.1) 0px 0px 0px 1px inset"), "rgba(255, 255, 255, 0.1)");
  assert.equal(insetLine("inset 0px 0px 0px 1px rgb(56, 189, 248)"), "rgb(56, 189, 248)");
  assert.equal(insetLine("none"), null);
  assert.equal(insetLine("rgba(11, 18, 32, 0.16) 0px -24px 48px -24px"), null);
});

test("ход помощника: замер верен, пока места те же (до полупикселя)", () => {
  assert.ok(sameBoxes([B(0, 0, 10, 10)], [B(0.3, 0, 10.2, 10)]));
  assert.ok(!sameBoxes([B(0, 0, 10, 10)], [B(1, 0, 10, 10)]));
  assert.ok(!sameBoxes([B(0, 0, 10, 10)], []));
});
