import { test } from "node:test";
import assert from "node:assert/strict";
import { failReason } from "./narrate";

test("a failed build says the server's Russian reason, never a Python message", () => {
  assert.equal(failReason("Сервер перезапускался — сборка прервана. Соберите презентацию ещё раз"), "Сервер перезапускался — сборка прервана. Соберите презентацию ещё раз.");
  assert.equal(failReason("Шаблон ещё не разобран — загрузите его снова.\nTraceback (most recent call last):"), "Шаблон ещё не разобран — загрузите его снова.");
  assert.equal(failReason("list index out of range"), "Измените текст и соберите заново");
  assert.equal(failReason(null), "Измените текст и соберите заново");
});
