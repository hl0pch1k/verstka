import { test } from "node:test";
import assert from "node:assert/strict";
import { lbFrameWidth, lbKey, lbView } from "./lightboxView";

test("счётчик «N / M · заголовок»; стрелки спрятаны на краях", () => {
  assert.deepEqual(lbView(3, 12, "Неопределённый интеграл"), { count: "3 / 12", title: "Неопределённый интеграл", prev: true, next: true });
  assert.deepEqual(lbView(1, 12, ""), { count: "1 / 12", title: null, prev: false, next: true });
  assert.deepEqual(lbView(12, 12, "  "), { count: "12 / 12", title: null, prev: true, next: false });
  // один слайд — листать некуда
  assert.deepEqual(lbView(1, 1, "Обложка"), { count: "1 / 1", title: "Обложка", prev: false, next: false });
  // номер за пределами — к ближнему краю
  assert.deepEqual(lbView(20, 12, "x").count, "12 / 12");
  assert.deepEqual(lbView(0, 12, "x").count, "1 / 12");
});

test("клавиши: ←/→ листают в пределах 1…M, Home/End — к краям, Esc закрывает, чужие — мимо", () => {
  assert.equal(lbKey("ArrowRight", 3, 12), 4);
  assert.equal(lbKey("ArrowLeft", 3, 12), 2);
  assert.equal(lbKey("ArrowLeft", 1, 12), 1);
  assert.equal(lbKey("ArrowRight", 12, 12), 12);
  assert.equal(lbKey("Home", 7, 12), 1);
  assert.equal(lbKey("End", 7, 12), 12);
  assert.equal(lbKey("Escape", 7, 12), "close");
  assert.equal(lbKey("Enter", 7, 12), null);
  assert.equal(lbKey("a", 7, 12), null);
});

test("ширина кадра: 1120 при 16:9, уже у 4:3; место под стрелки остаётся", () => {
  assert.equal(lbFrameWidth(16 / 9), "min(1120px, calc(100% - 176px))");
  assert.equal(lbFrameWidth(4 / 3), "min(840px, calc(100% - 176px))");
  // пропорции неизвестны — 16:9
  assert.equal(lbFrameWidth(0), "min(1120px, calc(100% - 176px))");
});
