import { test } from "node:test";
import assert from "node:assert/strict";
import { helperBeside, isStack, tierOf, tierOfQueries } from "./tier";

test("ступени по ширине окна: границы 768, 1024, 1280", () => {
  assert.equal(tierOf(360), "sm");
  assert.equal(tierOf(767), "sm");
  assert.equal(tierOf(767.5), "sm");
  assert.equal(tierOf(768), "md");
  assert.equal(tierOf(1023), "md");
  assert.equal(tierOf(1024), "lg");
  assert.equal(tierOf(1279), "lg");
  assert.equal(tierOf(1279.98), "lg");
  assert.equal(tierOf(1280), "xl");
  assert.equal(tierOf(2560), "xl");
});

test("ширина не известна — компьютер", () => {
  assert.equal(tierOf(0), "xl");
  assert.equal(tierOf(Number.NaN), "xl");
});

test("стопка — всё, что уже компьютера; помощник рядом с колодой — только на компьютере", () => {
  assert.deepEqual((["xl", "lg", "md", "sm"] as const).map(isStack), [false, true, true, true]);
  assert.deepEqual((["xl", "lg", "md", "sm"] as const).map(helperBeside), [true, false, false, false]);
});

test("ступень по ответам запросов", () => {
  assert.equal(tierOfQueries({ xl: true, lg: true, md: true }), "xl");
  assert.equal(tierOfQueries({ xl: false, lg: true, md: true }), "lg");
  assert.equal(tierOfQueries({ xl: false, lg: false, md: true }), "md");
  assert.equal(tierOfQueries({ xl: false, lg: false, md: false }), "sm");
});
