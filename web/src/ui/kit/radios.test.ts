import { test } from "node:test";
import assert from "node:assert/strict";
import { radioStep } from "./radios";

test("радиокнопки: стрелки по кругу, Home и End, прочие клавиши — мимо", () => {
  const k = ["brand", "template"] as const;
  assert.equal(radioStep(k, "brand", "ArrowRight"), "template");
  assert.equal(radioStep(k, "template", "ArrowRight"), "brand");
  assert.equal(radioStep(k, "brand", "ArrowLeft"), "template");
  assert.equal(radioStep(k, "template", "ArrowUp"), "brand");
  assert.equal(radioStep(["a", "b", "c"], "b", "End"), "c");
  assert.equal(radioStep(["a", "b", "c"], "b", "Home"), "a");
  assert.equal(radioStep(k, "brand", "Enter"), null);
  assert.equal(radioStep([], "x", "ArrowRight"), null);
});
