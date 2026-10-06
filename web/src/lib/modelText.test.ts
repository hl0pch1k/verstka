import { test } from "node:test";
import assert from "node:assert/strict";
import { plainAdvice, rebuildOffer, retryWords, silentNote } from "./modelText";
import type { Generation, ModelsStatus, PlannerInfo } from "../types";

test("advice about money, keys and the service never reaches the screen", () => {
  assert.equal(plainAdvice("На балансе Polza нет средств: пополните баланс."), null);
  assert.equal(plainAdvice("Соберите ещё раз через 2 мин."), "Соберите ещё раз."); // a timer goes: the button waits
  assert.equal(plainAdvice("Соберите ещё раз через минуту."), "Соберите ещё раз через минуту.");
  assert.equal(plainAdvice("Соберите ещё раз после полуночи по московскому времени."), "Соберите ещё раз после полуночи по московскому времени.");
  assert.equal(plainAdvice("Проверьте ключ POLZA_API_KEY в .env."), null);
});

const planner = (over: Partial<PlannerInfo>): PlannerInfo =>
  ({ planned_by: "rules", by_model: false, model: null, model_label: null, reason_code: null, reason: null, advice: null, ...over }) as PlannerInfo;

test("the chat says once that the model is unavailable", () => {
  const g = { use_models: true, planner: planner({ reason_code: "no_credits", advice: "Модель недоступна.", retryable: false }) } as unknown as Generation;
  assert.equal(silentNote(g), "Модель сейчас недоступна. Собрал по вашему тексту без модели.");
  const q = { use_models: true, planner: planner({ reason_code: "quota", advice: "Соберите ещё раз после полуночи по московскому времени.", retryable: true }) } as unknown as Generation;
  assert.ok(silentNote(q).endsWith("Соберите ещё раз после полуночи по московскому времени."), silentNote(q));
});

test("building again is offered only for a reason that passes by itself", () => {
  assert.equal(retryWords(planner({ reason_code: "rate", advice: "Соберите ещё раз через минуту.", retryable: true })), "Соберите ещё раз через минуту.");
  assert.equal(retryWords(planner({ reason_code: "no_credits", advice: "Модель недоступна.", retryable: false })), null);
  assert.equal(retryWords(planner({ reason_code: "error", advice: "Та же сборка получит ту же ошибку: сократите текст.", retryable: false })), null);
});

test("a deck whose model is gone never reads «… через несколько минут. Модель недоступна.»", () => {
  const st = { configured: true, state: "down", advice: "Соберите ещё раз через несколько минут.", retryable: true, retry_in: 60, links: [] } as unknown as ModelsStatus;
  const offer = rebuildOffer(planner({ reason_code: "missing", advice: "Модель недоступна.", retryable: false }), { status: st, latest: true, retryIn: 60 });
  assert.equal(offer.help, "Соберите ещё раз через несколько минут.");
});
