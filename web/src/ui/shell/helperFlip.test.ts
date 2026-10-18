import { test } from "node:test";
import assert from "node:assert/strict";
import { flipFrom } from "./helperFlip";

const R = (left: number, top: number, width: number, height: number) => ({ left, top, width, height, right: left + width, bottom: top + height });

test("FLIP помощника: элемент ставится на прежнее место сдвигом, слайд — и масштабом; на месте — ничего", () => {
  assert.equal(flipFrom(R(100, 50, 400, 225), R(100, 74, 400, 225)), "translate(0px, -24px)");
  assert.equal(flipFrom(R(72, 344, 832, 468), R(72, 368, 672, 378), true), "translate(0px, -24px) scale(1.2381)");
  // без масштаба ширина не учитывается (лента миниатюр сужается сразу)
  assert.equal(flipFrom(R(72, 760, 832, 64), R(72, 784, 672, 64)), "translate(0px, -24px)");
  assert.equal(flipFrom(R(10, 10, 100, 100), R(10.2, 10.1, 100, 100), true), null);
});

test("FLIP помощника: название перекладывается с кеглем — масштаб задан числом", () => {
  assert.equal(flipFrom(R(952, 228, 416, 96), R(72, 228, 400, 40), 40 / 32), "translate(880px, 0px) scale(1.25)");
});
