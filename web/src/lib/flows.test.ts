import { test } from "node:test";
import assert from "node:assert/strict";
import { failMessage } from "./flows";

test("сообщение помощника о неудаче задачи: причина по-русски, без технического хвоста", () => {
  assert.equal(failMessage("Не получилось собрать презентацию", { error: "Модель не ответила: ProviderError: 503 Service Unavailable", message: "" }),
    "Не получилось собрать презентацию: модель не ответила");
  assert.equal(failMessage("Не получилось разобрать «Отчёт»", { error: "Traceback (most recent call last):\n  KeyError: 'x'", message: "" }),
    "Не получилось разобрать «Отчёт».");
  assert.equal(failMessage("Не получилось собрать презентацию", { error: null, message: "Сервер перезапустился — задача потеряна" }),
    "Не получилось собрать презентацию: сервер перезапустился — задача потеряна");
});
