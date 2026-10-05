import { test } from "node:test";
import assert from "node:assert/strict";
import { about, asPictureResult, stage } from "./pictures";

test("a picture change's result is read only when it is one", () => {
  const r = asPictureResult({ reply: "Слайд 2: новое изображение.", changed: true, applied: true, action: "generate", strategy: "visual", slide: 2, version: 3, at: 1, picture: { id: "s2-5", slide: 2, status: "generated" } });
  assert.equal(r?.applied, true);
  assert.equal(r?.version, 3);
  assert.equal(r?.picture?.status, "generated");
  assert.equal(asPictureResult({ reply: "x" }), null);
  assert.equal(asPictureResult(null), null);
  assert.equal(asPictureResult({ reply: "Не получилось", slide: 2, changed: false })?.applied, false);
});

test("the stage line is the job's own plain words, never the agent's", () => {
  assert.equal(stage("Готовлю превью"), "Готовлю превью");
  assert.equal(stage("Ставлю изображение на слайд…"), "Ставлю изображение на слайд");
  assert.equal(stage("Слайд 2 — новое изображение: «вид сверху»."), "Рисую изображение");
  assert.equal(stage(""), "Рисую изображение");
});

test("a picture is told by the person's wish first, then the author's words", () => {
  assert.equal(about({ id: "a", slide: 1, status: "generated", hint: "экран", wish: "вид сверху" }), "вид сверху");
  assert.equal(about({ id: "a", slide: 1, status: "free", hint: "экран панели" }), "экран панели");
});
