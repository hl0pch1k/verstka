import { test } from "node:test";
import assert from "node:assert/strict";
import { eraserOf, insetLine, moveCss, opaque, sameBoxes, sameSpots, scaleCss, shiftOf, stretchOf } from "./helperMotion";

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
  assert.equal(k!.mid, 1058);
  assert.equal(k!.right, 1080);
  assert.equal(k!.cut, 416);
  // середина начинается на 1 px под левым краем, а в узкой раскладке кончается на 1 px под правым
  assert.ok(Math.abs(24 - 1 + k!.mid * k!.scale - (k!.right - k!.cut + 1)) < 0.1);
  assert.equal(stretchOf(200, 200, 24), null);
  // скругление не больше половины узкой коробки
  assert.equal(stretchOf(60, 40, 24)!.r, 20);
});

test("ход помощника: куски «растяжки» непрозрачны — цвет коробки поверх плиты", () => {
  assert.equal(opaque("rgba(255, 255, 255, 0.5)", "rgb(0, 0, 0)"), "rgb(128, 128, 128)");
  assert.equal(opaque("rgb(10, 20, 30)", "rgb(0, 0, 0)"), "rgb(10, 20, 30)");
  assert.equal(opaque("rgba(0, 0, 0, 0)", "rgb(11, 18, 32)"), "rgb(11, 18, 32)");
  // не разобрать или плита сама прозрачна — как есть
  assert.equal(opaque("var(--x)", "rgb(0, 0, 0)"), "var(--x)");
  assert.equal(opaque("rgba(1, 2, 3, 0.5)", "rgba(0, 0, 0, 0)"), "rgba(1, 2, 3, 0.5)");
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

test("ход помощника: непомеченное стоит там же — угол и высота; ширина блока и пустое не в счёт", () => {
  const B = (x: number, y: number, w: number, h: number) => ({ x, y, w, h });
  assert.equal(sameSpots([B(10, 20, 900, 30)], [B(10, 20, 500, 30)]), true);
  assert.equal(sameSpots([B(10, 20, 100, 30)], [B(10, 20, 100, 60)]), false);
  assert.equal(sameSpots([B(700, 20, 100, 30)], [B(400, 20, 100, 30)]), false);
  assert.equal(sameSpots([B(700, 20, 0, 0)], [B(400, 20, 0, 0)]), true);
  assert.equal(sameSpots([B(0, 0, 1, 1)], []), false);
  // правее края в обеих раскладках — под полосой и занавесом
  assert.equal(sameSpots([B(1200, 20, 40, 16)], [B(870, 20, 40, 16)], 860), true);
  assert.equal(sameSpots([B(1200, 20, 40, 16)], [B(800, 20, 40, 16)], 860), false);
});
