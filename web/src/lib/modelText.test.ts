import { test } from "node:test";
import assert from "node:assert/strict";
import { plainAdvice, rebuildOffer, retryWords, sameModelStatus, silentNote } from "./modelText";
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

test("a status poll that brings only a new answer time or the same pause counted down is no news", () => {
  const link = (state: string, extra = {}) => ({ model: "m", label: "Qwen3.8-27B (VK)", host: "vk", state, available: true, last_ok: null, last_error: null, until: null, ...extra });
  const st = (over: Partial<ModelsStatus> = {}, links = [link("error", { last_error: "500" }), link("ok", { last_ok: 1 })]) =>
    ({ configured: true, state: "fallback", working_label: "Qwen3.8-27B (Polza)", retry_in: null, links, ...over }) as unknown as ModelsStatus;
  assert.equal(sameModelStatus(null, 0, st(), 0), false);
  // Polza answered again, VK failed again with another wording: the line is the same
  assert.equal(sameModelStatus(st(), 0, st({}, [link("error", { last_error: "502" }), link("ok", { last_ok: 99 })]), 20_000), true);
  assert.equal(sameModelStatus(st(), 0, st({ state: "retry" }), 20_000), false);
  assert.equal(sameModelStatus(st(), 0, st({ working_label: "Qwen3.6-27B" }), 20_000), false);
  // a pause: the same end within 5 s is the same; a new pause or its end is news
  const down = st({ state: "down", retry_in: 120 });
  assert.equal(sameModelStatus(down, 0, st({ state: "down", retry_in: 100 }), 20_000), true);
  assert.equal(sameModelStatus(down, 0, st({ state: "down", retry_in: 300 }), 20_000), false);
  assert.equal(sameModelStatus(down, 0, st({ state: "down", retry_in: null }), 20_000), false);
  // a link starts or ends its pause
  assert.equal(sameModelStatus(st(), 0, st({}, [link("error", { until: 30, available: false }), link("ok")]), 20_000), false);
});
