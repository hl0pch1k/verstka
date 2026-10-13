import { test } from "node:test";
import assert from "node:assert/strict";
import type { ActiveJob } from "../../lib/jobState";
import { busyKeys, fixedFromJob, fixView, undoRefusal, undoView, WORK0, workKey, workNext } from "./variantWork";

const K = workKey("g1", "s");
const L = workKey("g1", "v");

test("ключ работы — презентация и вариант", () => {
  assert.equal(K, "g1|s");
  assert.ok(workKey("g1", "s") !== workKey("g2", "s"));
});

test("занятые варианты — по целям идущих задач (сервер держит одну задачу на вариант)", () => {
  const job = (id: string, target?: ActiveJob["target"]): ActiveJob => ({ id, label: "", progress: 0, message: "", status: "running", kind: "fix", startedAt: 0, target });
  const keys = busyKeys([job("a", { generation: "g1", strategy: "s", slide: 0 }), job("b"), job("c", { generation: "g2", strategy: "v", slide: 3 }), job("d", { generation: "g1", strategy: "s", slide: 2 })]);
  assert.deepEqual(keys, ["g1|s", "g2|v"]);
  assert.deepEqual(busyKeys([]), []);
});

test("исправление: старт → ход (отмеченные заняты, кнопки выключены) → итог «Исправлено N» с «Вернуть как было»", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: ["a", "b"] });
  assert.deepEqual(fixView(s, K, "r1", false), { busy: ["a", "b"], working: "fix", status: null, undo: false, error: null, locked: true });
  const seq = s[K]!.fix!.seq;
  s = workNext(s, { type: "fixed", key: K, seq, fixed: 2, rev: "r2" });
  assert.deepEqual(fixView(s, K, "r2", false), { busy: null, working: null, status: "Исправлено 2 замечания", undo: true, error: null, locked: false });
});

test("итог исправления держится, пока вариант не изменился снова (новая ревизия — итога нет)", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: "all" });
  s = workNext(s, { type: "fixed", key: K, seq: s[K]!.fix!.seq, fixed: 1, rev: "r2" });
  assert.equal(fixView(s, K, "r2", false).status, "Исправлено 1 замечание");
  // слайд исправили, изображение сменили, правку вернули из «Агента» — ревизия другая
  assert.deepEqual(fixView(s, K, "r3", false), { busy: null, working: null, status: null, undo: false, error: null, locked: false });
  // ревизия после исправления неизвестна (презентацию не перечитали) — итог виден
  let t = workNext(WORK0, { type: "fix", key: K, ids: "all" });
  t = workNext(t, { type: "fixed", key: K, seq: t[K]!.fix!.seq, fixed: 1, rev: null });
  assert.equal(fixView(t, K, "r9", false).status, "Исправлено 1 замечание");
});

test("пока над вариантом идёт чужая задача (исправление слайда, изображение) — кнопки выключены, старт отклоняется в хуке", () => {
  assert.equal(fixView(WORK0, K, "r1", true).locked, true);
  assert.equal(undoView(WORK0, K, true).busy, true);
  assert.equal(fixView(WORK0, K, "r1", false).locked, false);
});

test("второй запуск, пока идёт первый, отклоняется; у другого варианта — своя работа", () => {
  const s = workNext(WORK0, { type: "fix", key: K, ids: "all" });
  assert.equal(workNext(s, { type: "fix", key: K, ids: ["x"] }), s);
  assert.equal(workNext(s, { type: "undo", key: K, by: "agent" }), s);
  const t = workNext(s, { type: "fix", key: L, ids: ["x"] });
  assert.deepEqual(fixView(t, L, "r", false).busy, ["x"]);
  assert.equal(fixView(t, K, "r", false).busy, "all");
});

test("ничего не исправилось — строка неудачи, «Вернуть» не предлагается", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: ["a"] });
  s = workNext(s, { type: "fixed", key: K, seq: s[K]!.fix!.seq, fixed: 0, rev: "r1" });
  assert.deepEqual(fixView(s, K, "r1", false), { busy: null, working: null, status: null, undo: false, error: "Исправить не получилось — замечания остались.", locked: false });
});

test("неудача запуска или задачи — строка ошибки у места действия, пока вариант тот же", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: ["a"] });
  s = workNext(s, { type: "fixFailed", key: K, seq: s[K]!.fix!.seq, error: "Вариант уже меняется", rev: "r1" });
  assert.deepEqual(fixView(s, K, "r1", false), { busy: null, working: null, status: null, undo: false, error: "Вариант уже меняется", locked: false });
  assert.equal(fixView(s, K, "r2", false).error, null);
});

test("«Вернуть как было» итога: ход в своей кнопке; вернулось — итога нет; неудача оставляет итог и говорит почему", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: ["a"] });
  s = workNext(s, { type: "fixed", key: K, seq: s[K]!.fix!.seq, fixed: 1, rev: "r2" });
  const done = s;
  s = workNext(s, { type: "undo", key: K, by: "quality" });
  assert.deepEqual(fixView(s, K, "r2", false), { busy: null, working: "undo", status: "Исправлено 1 замечание", undo: true, error: null, locked: true });
  // вкладка «Агент» видит, что вариант занят, но дуга — не у неё
  assert.deepEqual(undoView(s, K, false), { busy: true, arc: false, error: null });
  const useq = s[K]!.undo!.seq;
  const back = workNext(s, { type: "undone", key: K, seq: useq });
  assert.deepEqual(fixView(back, K, "r2", false), { busy: null, working: null, status: null, undo: false, error: null, locked: false });
  const bad = workNext(s, { type: "undoFailed", key: K, seq: useq, error: "Не получилось" });
  assert.deepEqual(fixView(bad, K, "r2", false), { ...fixView(done, K, "r2", false), error: "Не получилось" });
  assert.equal(undoView(bad, K, false).error, null);
});

test("«Вернуть как было» вкладки «Агент»: ход и неудача — у неё; переживает закрытие листа (состояние в хранилище)", () => {
  let s = workNext(WORK0, { type: "undo", key: K, by: "agent" });
  assert.deepEqual(undoView(s, K, false), { busy: true, arc: true, error: null });
  assert.equal(fixView(s, K, "r1", false).locked, true);
  const seq = s[K]!.undo!.seq;
  s = workNext(s, { type: "undoFailed", key: K, seq, error: "Возвращать нечего" });
  assert.deepEqual(undoView(s, K, false), { busy: false, arc: false, error: "Возвращать нечего" });
  // новое действие снимает прежнюю строку
  s = workNext(s, { type: "fix", key: K, ids: ["a"] });
  assert.equal(undoView(s, K, false).error, null);
});

test("любое «верни как было» варианта (и с экрана результата) снимает итог исправления", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: ["a"] });
  s = workNext(s, { type: "fixed", key: K, seq: s[K]!.fix!.seq, fixed: 1, rev: null });
  s = workNext(s, { type: "undone", key: K, seq: null });
  assert.equal(fixView(s, K, "r", false).status, null);
});

test("опоздавший ответ прежнего запуска не трогает новый", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: ["a"] });
  const old = s[K]!.fix!.seq;
  s = workNext(s, { type: "fixFailed", key: K, seq: old, error: "x", rev: null });
  s = workNext(s, { type: "fix", key: K, ids: ["b"] });
  assert.equal(workNext(s, { type: "fixed", key: K, seq: old, fixed: 1, rev: null }), s);
});

test("сколько исправлено — по итогу задачи (`applied[].issue_id` среди запрошенных, кроме отменённых); итог не говорит — null", () => {
  const result = { applied: [
    { action: "move_inside", issue_id: "a" }, { action: "shrink_text", issue_id: "b", rolled_back: true }, { action: "xml", issue_id: "a" },
    { action: "condense_text", issue_id: "old" }, { action: "recolor" },
  ] };
  assert.equal(fixedFromJob(result, ["a", "b", "c"]), 1);
  assert.equal(fixedFromJob({ applied: [{ action: "move_inside" }] }, ["a"]), null);
  assert.equal(fixedFromJob(null, ["a"]), null);
  assert.equal(fixedFromJob({ applied: "x" }, ["a"]), null);
});

test("итог «верни как было»: вернулось — null; сервер ответил, что не вышло, — его словами", () => {
  assert.equal(undoRefusal({ changed: true, reply: "Вернул" }), null);
  assert.equal(undoRefusal(null), null);
  assert.equal(undoRefusal({ changed: false, reply: "Возвращать нечего — это первая версия." }), "Возвращать нечего — это первая версия.");
  assert.equal(undoRefusal({ changed: false }), "Вернуть не получилось. Попробуйте ещё раз.");
});

test("исправление кончилось, а вариант не прочитался ни открытым, ни тихо — «Исправлено» не показывается (C4, D-1)", () => {
  let s = workNext(WORK0, { type: "fix", key: K, ids: "all" });
  const seq = s[K]!.fix!.seq;
  s = workNext(s, { type: "fixLost", key: K, seq });
  assert.deepEqual(fixView(s, K, "r1", false), { busy: null, working: null, status: null, undo: false, error: null, locked: false });
  // снова можно исправлять; опоздавший «потерян» прежнего запуска новый не трогает
  const again = workNext(s, { type: "fix", key: K, ids: ["a"] });
  assert.equal(again[K]!.fix!.phase, "fix");
  assert.equal(workNext(again, { type: "fixLost", key: K, seq }), again);
});
