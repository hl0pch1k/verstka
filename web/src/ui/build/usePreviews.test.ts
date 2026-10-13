import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_ROUNDS, pollAgain, previewKey } from "./usePreviews";

test("превью держатся за генерацию: у повтора («Собрать ещё раз») тот же вариант — другой ключ", () => {
  assert.ok(previewKey("g-old", "structured") !== previewKey("g-new", "structured"));
  assert.ok(previewKey("g", "structured") !== previewKey("g", "visual"));
  assert.equal(previewKey("g", "structured"), previewKey("g", "structured"));
  assert.equal(previewKey(null, "structured"), "");
  assert.equal(previewKey("g", null), "");
});

test("опрос превью: только пока сборка идёт, превью ещё не все и круги не кончились", () => {
  assert.equal(pollAgain({ live: true, have: 2, count: 5, round: 1 }), true);
  assert.equal(pollAgain({ live: false, have: 2, count: 5, round: 1 }), false); // сборка кончилась или упала
  assert.equal(pollAgain({ live: true, have: 5, count: 5, round: 1 }), false); // все превью есть
  assert.equal(pollAgain({ live: true, have: 2, count: 5, round: MAX_ROUNDS }), false); // предел
  assert.equal(pollAgain({ live: true, have: 2, count: 5, round: MAX_ROUNDS - 1 }), true);
  assert.ok(MAX_ROUNDS * 1.5 >= 120 && MAX_ROUNDS * 1.5 <= 600, "предел — минуты, не часы");
});
