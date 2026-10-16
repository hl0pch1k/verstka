import { test } from "node:test";
import assert from "node:assert/strict";
import { asRebuildResult, rebuildBusy, rebuildNext, REBUILD0, refusalText, rowAct, type RebuildState } from "./rebuild";

const K = "g1|structured";
const free = { off: false, why: null };
const run = (s: RebuildState) => s[K] ?? null;

test("пересборка: запуск → задача → готово; второй запуск на том же варианте, пока идёт, не уходит", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  const r = run(s)!;
  assert.deepEqual([r.slide, r.option, r.phase, r.jobId], [4, 1, "work", null]);
  assert.equal(rebuildBusy(r), true);
  assert.equal(rebuildNext(s, { type: "start", key: K, slide: 4, option: 2 }), s);
  // другой вариант презентации работает сам по себе
  assert.ok(rebuildNext(s, { type: "start", key: "g1|visual", slide: 4, option: 2 }) !== s);
  s = rebuildNext(s, { type: "accepted", key: K, seq: r.seq, jobId: "j1" });
  assert.equal(run(s)!.jobId, "j1");
  // поздний шаг прежнего запуска новый не трогает
  assert.equal(rebuildNext(s, { type: "done", key: K, seq: r.seq - 1, stale: false }), s);
  s = rebuildNext(s, { type: "done", key: K, seq: r.seq, stale: false });
  assert.deepEqual([run(s)!.phase, run(s)!.stale], ["done", false]);
  assert.equal(rebuildBusy(run(s)), false);
});

test("отказ — причина у варианта (кнопки нет: на её месте строка); новый запуск снимает прежний отказ", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 2 });
  const seq = run(s)!.seq;
  s = rebuildNext(s, { type: "failed", key: K, seq, error: "«Круговая диаграмма» не подходит: 8 долей — мелкие сектора нечитаемы." });
  assert.deepEqual(rowAct(run(s), 4, 2, 0, false, free), { mode: "error", text: "«Круговая диаграмма» не подходит: 8 долей — мелкие сектора нечитаемы." });
  assert.deepEqual(rowAct(run(s), 4, 1, 0, false, free), { mode: "button", off: false, why: null });
  assert.deepEqual(rowAct(run(s), 5, 2, 0, false, free), { mode: "button", off: false, why: null }); // другой слайд
  s = rebuildNext(s, { type: "start", key: K, slide: 4, option: 1 });
  assert.equal(rowAct(run(s), 4, 2, 0, false, free).mode, "button");
});

test("место действия: ход — у пересобираемого варианта, остальные кнопки выключены с причиной; выбранный — без действия", () => {
  const s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  assert.deepEqual(rowAct(run(s), 4, 1, 0, false, free), { mode: "busy" });
  assert.deepEqual(rowAct(run(s), 4, 2, 0, false, free), { mode: "button", off: true, why: "Пересобираю слайд 4 — дождитесь конца" });
  assert.deepEqual(rowAct(run(s), 4, 0, 0, false, free), { mode: "none" });
  // чужая задача над вариантом, шаблона нет — выключены её словами
  assert.deepEqual(rowAct(null, 4, 2, 0, false, { off: true, why: "Агент сейчас исправляет слайд 3" }), { mode: "button", off: true, why: "Агент сейчас исправляет слайд 3" });
});

test("пересобрано: у выбранного — «Вернуть как было»; экран не перечитался — строка с «Обновить» у пересобранного", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  s = rebuildNext(s, { type: "done", key: K, seq: run(s)!.seq, stale: true });
  // экран ещё прежний: выбран 0, у варианта 1 — «не обновилась»
  assert.deepEqual(rowAct(run(s), 4, 1, 0, false, free), { mode: "stale" });
  // перечитался: выбран 1, последнее изменение — эта пересборка
  assert.deepEqual(rowAct(run(s), 4, 1, 1, true, free), { mode: "done", undoing: false, text: null, off: false, why: null });
  assert.equal(rowAct(run(s), 4, 0, 1, true, free).mode, "button");
});

test("«Вернуть как было»: идёт — дуга у кнопки, остальные выключены; вернулось — работы нет; не вышло — причина и повтор", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  s = rebuildNext(s, { type: "done", key: K, seq: run(s)!.seq, stale: false });
  s = rebuildNext(s, { type: "undo", key: K, slide: 4 });
  assert.equal(run(s)!.undo, "work");
  assert.deepEqual(rowAct(run(s), 4, 1, 1, true, free), { mode: "done", undoing: true, text: null, off: false, why: null });
  assert.deepEqual(rowAct(run(s), 4, 0, 1, true, free), { mode: "button", off: true, why: "Возвращаю как было — дождитесь конца" });
  assert.equal(rebuildNext(s, { type: "undo", key: K, slide: 4 }), s); // второй возврат не уходит
  const failed = rebuildNext(s, { type: "undoFailed", key: K, seq: run(s)!.seq, error: "Вернуть не получилось. Попробуйте ещё раз." });
  assert.deepEqual(rowAct(run(failed), 4, 1, 1, true, free), { mode: "done", undoing: false, text: "Вернуть не получилось. Попробуйте ещё раз.", off: false, why: null });
  assert.equal(run(rebuildNext(s, { type: "undone", key: K, seq: run(s)!.seq, stale: false })), null);
  // вернулось, а экран не перечитался — у выбранного строка с «Обновить», а не второе «Вернуть»
  const stale = rebuildNext(s, { type: "undone", key: K, seq: run(s)!.seq, stale: true });
  assert.deepEqual(rowAct(run(stale), 4, 1, 1, true, free), { mode: "stale" });
});

test("«Вернуть как было» после перезагрузки (запуска на странице нет): возврат своим запуском", () => {
  const s = rebuildNext(REBUILD0, { type: "undo", key: K, slide: 4 });
  const r = run(s)!;
  assert.deepEqual([r.slide, r.phase, r.undo, r.option], [4, "done", "work", -1]);
  assert.equal(rowAct(r, 4, 2, 2, true, free).mode, "done");
});

test("итог задачи и отказы сервера — по-русски", () => {
  assert.equal(asRebuildResult({ kind: "fix", changed: true }), null);
  assert.equal(asRebuildResult({ kind: "rebuild", changed: true, slide: 4 })?.slide, 4);
  assert.equal(refusalText("Слайд 4 уже показан так: ранжированные горизонтальные столбцы"), "Слайд 4 уже показан так: ранжированные горизонтальные столбцы");
  assert.equal(refusalText("Сеть недоступна: Failed to fetch"), "Сеть недоступна");
  assert.equal(refusalText("Internal Server Error"), "Не получилось пересобрать слайд. Попробуйте ещё раз.");
});
