import { test } from "node:test";
import assert from "node:assert/strict";
import { reloadPlan, replayWanted } from "./reload";

test("перечитывание после изменения: открыта она — сейчас; поверх открывается другая — ждёт; открыта другая — нет (A7)", () => {
  assert.equal(reloadPlan("a", "a", "a"), "now");
  assert.equal(reloadPlan("a", "a", "b"), "wait");
  assert.equal(reloadPlan("a", "b", "b"), "none");
  assert.equal(reloadPlan("a", null, null), "none");
});

test("ждущее перечитывание идёт, когда открытие поверх отменили или оно не удалось и открытая осталась", () => {
  assert.equal(replayWanted("a", "a"), true);
  assert.equal(replayWanted("a", "b"), false); // открылась другая — ждать нечего
  assert.equal(replayWanted(null, "a"), false);
  assert.equal(replayWanted("a", null), false);
});
