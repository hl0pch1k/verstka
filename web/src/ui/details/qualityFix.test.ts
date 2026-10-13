import { test } from "node:test";
import assert from "node:assert/strict";
import { FIX0, fixNext, fixView } from "./qualityFix";

test("исправление: старт → ход (отмеченные заняты) → итог «Исправлено N» с «Вернуть как было»", () => {
  let s = fixNext(FIX0, { type: "start", strategy: "s", ids: ["a", "b"] });
  assert.deepEqual(fixView(s, "s"), { busy: ["a", "b"], working: "fix", status: null, undo: false, error: null });
  const seq = s.s!.seq;
  s = fixNext(s, { type: "done", strategy: "s", seq, fixed: 2 });
  assert.deepEqual(fixView(s, "s"), { busy: null, working: null, status: "Исправлено 2 замечания", undo: true, error: null });
});

test("второй запуск, пока идёт первый, отклоняется (у варианта одна задача за раз)", () => {
  const s = fixNext(FIX0, { type: "start", strategy: "s", ids: "all" });
  assert.equal(fixNext(s, { type: "start", strategy: "s", ids: ["x"] }), s);
  // у другого варианта — своя работа
  const t = fixNext(s, { type: "start", strategy: "v", ids: ["x"] });
  assert.deepEqual(fixView(t, "v").busy, ["x"]);
  assert.equal(fixView(t, "s").busy, "all");
});

test("ничего не исправилось — строка неудачи, «Вернуть» не предлагается", () => {
  let s = fixNext(FIX0, { type: "start", strategy: "s", ids: ["a"] });
  s = fixNext(s, { type: "done", strategy: "s", seq: s.s!.seq, fixed: 0 });
  assert.deepEqual(fixView(s, "s"), { busy: null, working: null, status: null, undo: false, error: "Исправить не получилось — замечания остались." });
});

test("неудача запуска или задачи — строка ошибки у места действия", () => {
  let s = fixNext(FIX0, { type: "start", strategy: "s", ids: ["a"] });
  s = fixNext(s, { type: "failed", strategy: "s", seq: s.s!.seq, error: "Вариант уже меняется" });
  assert.deepEqual(fixView(s, "s"), { busy: null, working: null, status: null, undo: false, error: "Вариант уже меняется" });
});

test("«Вернуть как было»: только после итога; ход; после — итога нет; неудача оставляет итог и говорит почему", () => {
  let s = fixNext(FIX0, { type: "undo", strategy: "s" });
  assert.equal(s, FIX0);
  s = fixNext(s, { type: "start", strategy: "s", ids: ["a"] });
  s = fixNext(s, { type: "done", strategy: "s", seq: s.s!.seq, fixed: 1 });
  const done = s;
  s = fixNext(s, { type: "undo", strategy: "s" });
  assert.deepEqual(fixView(s, "s"), { busy: null, working: "undo", status: "Исправлено 1 замечание", undo: true, error: null });
  const back = fixNext(s, { type: "undone", strategy: "s", seq: s.s!.seq });
  assert.deepEqual(fixView(back, "s"), { busy: null, working: null, status: null, undo: false, error: null });
  const bad = fixNext(s, { type: "failed", strategy: "s", seq: s.s!.seq, error: "Не получилось" });
  assert.deepEqual(fixView(bad, "s"), { ...fixView(done, "s"), error: "Не получилось" });
});

test("опоздавший ответ прежнего запуска не трогает новый", () => {
  let s = fixNext(FIX0, { type: "start", strategy: "s", ids: ["a"] });
  const old = s.s!.seq;
  s = fixNext(s, { type: "failed", strategy: "s", seq: old, error: "x" });
  s = fixNext(s, { type: "start", strategy: "s", ids: ["b"] });
  assert.equal(fixNext(s, { type: "done", strategy: "s", seq: old, fixed: 1 }), s);
});
