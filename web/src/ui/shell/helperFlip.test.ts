import { test } from "node:test";
import assert from "node:assert/strict";
import { flipFrom, phaseClasses, plateClip } from "./helperFlip";

const R = (left: number, top: number, width: number, height: number) => ({ left, top, width, height, right: left + width, bottom: top + height });

test("ход помощника: элемент ставится на другое место сдвигом, слайд — и масштабом; на месте — ничего", () => {
  assert.equal(flipFrom(R(100, 50, 400, 225), R(100, 74, 400, 225)), "translate(0px, -24px)");
  assert.equal(flipFrom(R(72, 344, 832, 468), R(72, 368, 672, 378), true), "translate(0px, -24px) scale(1.2381)");
  assert.equal(flipFrom(R(10, 10, 100, 100), R(10.2, 10.1, 100, 100), true), null);
});

test("ход помощника: подрезка мест плит — многоугольник одной формы при любой ширине (вершины переходят одна в одну)", () => {
  const a = plateClip(0, 1344, 812), b = plateClip(416, 1344, 812);
  assert.ok(a.startsWith("polygon(") && b.startsWith("polygon("));
  assert.equal(a.split(",").length, b.split(",").length);
  assert.ok(b.includes("928px 40px") && !b.includes("calc("));
});

test("ход помощника: одна раскладка видна за раз — узкая только в «open» и «fading»", () => {
  assert.equal(phaseClasses("opening"), "hp-open hp-go");
  assert.equal(phaseClasses("open"), "hp-open hp-nar");
  assert.equal(phaseClasses("fading"), "hp-open hp-nar hp-out");
  assert.equal(phaseClasses("closing"), "hp-open hp-back");
  assert.equal(phaseClasses("closed"), "hp-closed");
});
