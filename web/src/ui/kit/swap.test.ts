import { test } from "node:test";
import assert from "node:assert/strict";
import { swapNext, type SwapState } from "./swap";

const REST: SwapState<string> = { shown: "wide", phase: null };
const set = (value: string, live = true, ready = true) => ({ type: "set" as const, value, live, ready });

test("смена на виду: гаснет, подменяется в конце затухания и проявляется", () => {
  const out = swapNext(REST, set("narrow"));
  assert.deepEqual(out, { shown: "wide", phase: "out" });
  const inn = swapNext(out, { type: "swap", value: "narrow" });
  assert.deepEqual(inn, { shown: "narrow", phase: "in" });
  assert.deepEqual(swapNext(inn, { type: "end" }), { shown: "narrow", phase: null });
});

test("невидимое и до первого кадра (или без движения) меняется сразу", () => {
  assert.deepEqual(swapNext(REST, set("narrow", false)), { shown: "narrow", phase: null });
  assert.deepEqual(swapNext(REST, set("narrow", true, false)), { shown: "narrow", phase: null });
});

test("стало невидимым посреди затухания — затухание доигрывает, а не возвращается к непрозрачному", () => {
  const out = swapNext(REST, set("narrow"));
  const still = swapNext(out, set("narrow", false));
  assert.equal(still.phase, "out");
  assert.equal(still.shown, "wide");
  // конец затухания: подмена при нулевой прозрачности и проявление — без скачка к 1
  assert.deepEqual(swapNext(still, { type: "swap", value: "narrow" }), { shown: "narrow", phase: "in" });
});

test("значение сменилось ещё раз посреди затухания — гаснет дальше, подменяется последним", () => {
  const out = swapNext({ shown: "wide", phase: null } as SwapState<string>, set("narrow"));
  const again = swapNext(out, set("tight"));
  assert.deepEqual(again, { shown: "wide", phase: "out" });
  assert.deepEqual(swapNext(again, { type: "swap", value: "tight" }), { shown: "tight", phase: "in" });
});

test("вернулось показанное, пока оно гасло, — проявляется обратно без подмены", () => {
  const out = swapNext(REST, set("narrow"));
  assert.deepEqual(swapNext(out, set("wide")), { shown: "wide", phase: "in" });
  // и невидимым — тоже проявляется (непрозрачность не возвращается скачком)
  assert.deepEqual(swapNext(out, set("wide", false)), { shown: "wide", phase: "in" });
});

test("смена посреди проявления — гаснет снова (и невидимым тоже), а не подменяется на полупрозрачном", () => {
  const inn: SwapState<string> = { shown: "narrow", phase: "in" };
  assert.deepEqual(swapNext(inn, set("wide")), { shown: "narrow", phase: "out" });
  assert.deepEqual(swapNext(inn, set("wide", false)), { shown: "narrow", phase: "out" });
});

test("в покое и без перемен — тот же объект; чужие события фазы ничего не меняют", () => {
  assert.equal(swapNext(REST, set("wide")), REST);
  assert.equal(swapNext(REST, { type: "swap", value: "narrow" }), REST);
  assert.equal(swapNext(REST, { type: "end" }), REST);
  const out: SwapState<string> = { shown: "wide", phase: "out" };
  assert.equal(swapNext(out, { type: "end" }), out);
  const inn: SwapState<string> = { shown: "narrow", phase: "in" };
  assert.equal(swapNext(inn, set("narrow")), inn);
  assert.equal(swapNext(inn, { type: "swap", value: "narrow" }), inn);
});
