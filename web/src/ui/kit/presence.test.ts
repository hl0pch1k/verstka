import { test } from "node:test";
import assert from "node:assert/strict";
import { presenceNext, presenceWaits, type Presence } from "./presence";

const HIDDEN: Presence = { mounted: false, shown: false };

test("открытие: сначала монтируется закрытым, со следующего шага показывается", () => {
  const a = presenceNext(HIDDEN, true);
  assert.deepEqual(a, { mounted: true, shown: false });
  assert.deepEqual(presenceNext(a, true), { mounted: true, shown: true });
});

test("закрытие: показ снимается сразу, содержимое остаётся смонтированным до таймера", () => {
  const a = presenceNext({ mounted: true, shown: true }, false);
  assert.deepEqual(a, { mounted: true, shown: false });
  assert.deepEqual(presenceNext(a, false), HIDDEN);
});

test("повторное открытие во время ухода показывает то же содержимое, без перемонтирования", () => {
  assert.deepEqual(presenceNext({ mounted: true, shown: false }, true), { mounted: true, shown: true });
});

test("в покое состояние не меняется — тот же объект, без лишней перерисовки", () => {
  const open: Presence = { mounted: true, shown: true };
  assert.equal(presenceNext(open, true), open);
  assert.equal(presenceNext(HIDDEN, false), HIDDEN);
});

test("открытие в два шага на любой ширине: смонтированное закрытым ждёт отрисовки, показ — следующим шагом", () => {
  const a = presenceNext(HIDDEN, true);
  assert.equal(presenceWaits(true, a), true);
  assert.equal(presenceWaits(true, presenceNext(a, true)), false);
  // закрытие во время ожидания — показа не будет
  assert.equal(presenceWaits(false, a), false);
  assert.equal(presenceWaits(true, HIDDEN), false);
});
