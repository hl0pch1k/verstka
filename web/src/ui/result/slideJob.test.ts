import { test } from "node:test";
import assert from "node:assert/strict";
import type { SlideFixResult } from "../../types";
import { busyWhy, JOB0, slideBusy, slideJobNext, type SlideJobAction, type SlideJobState } from "./slideJob";

const run = (s: SlideJobState, ...as: SlideJobAction[]) => as.reduce(slideJobNext, s);
const fix = (slide = 3): SlideJobAction => ({ type: "start", kind: "fix", strategy: "structured", slide, wish: "  покажи этапами ", action: null, requested: [], at: 100 });
const RES = { applied: true } as SlideFixResult;

test("запуск: новый номер и работа без задачи; пока идёт работа, второй запуск не начинается", () => {
  const a = slideJobNext(JOB0, fix());
  assert.equal(a.seq, 1);
  assert.deepEqual(a.run && [a.run.seq, a.run.kind, a.run.slide, a.run.phase, a.run.jobId, a.run.startedAt, a.run.endedAt, a.run.wish], [1, "fix", 3, "work", null, 100, null, "покажи этапами"]);
  assert.equal(slideBusy(a.run), true);
  assert.equal(slideJobNext(a, fix(4)), a);
  assert.equal(slideJobNext(a, { type: "start", kind: "picture", strategy: "structured", slide: 3, wish: "", action: "remove", requested: [], at: 1 }), a);
});

test("сервер принял задачу: у запуска её номер и свои часы; ответ на прежний запуск ничего не меняет", () => {
  const a = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 });
  assert.deepEqual(a.run && [a.run.jobId, a.run.startedAt, a.run.phase], ["j1", 250, "work"]);
  assert.equal(slideJobNext(a, { type: "accepted", seq: 0, jobId: "old", at: 1 }), a);
});

test("конец работы: итог и остановленные часы; снова можно начинать, а поздний конец прежнего запуска не трогает новый", () => {
  const a = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 }, { type: "settled", seq: 1, at: 900, fix: RES });
  assert.deepEqual(a.run && [a.run.phase, a.run.endedAt, a.run.fix, a.run.error], ["done", 900, RES, null]);
  assert.equal(slideBusy(a.run), false);
  const b = slideJobNext(a, fix(5));
  assert.deepEqual([b.seq, b.run?.slide, b.run?.phase], [2, 5, "work"]);
  assert.equal(slideJobNext(b, { type: "settled", seq: 1, at: 1000, error: "поздно" }), b);
  // отказ при запуске — тоже конец, со строкой
  const c = run(JOB0, fix(), { type: "settled", seq: 1, at: 120, error: "Этот вариант уже меняется" });
  assert.deepEqual(c.run && [c.run.phase, c.run.jobId, c.run.error], ["done", null, "Этот вариант уже меняется"]);
});

test("«Вернуть как было»: только у кончившейся работы и одно за раз; вернулось — итога больше нет, не вышло — строка", () => {
  const done = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 }, { type: "settled", seq: 1, at: 900, fix: RES });
  const undo: SlideJobAction = { type: "undo", kind: "fix", strategy: "structured", slide: 3, at: 1000 };
  const a = slideJobNext(done, undo);
  assert.deepEqual(a.run && [a.seq, a.run.seq, a.run.undo, a.run.fix], [1, 1, "work", RES]);
  assert.equal(slideBusy(a.run), true);
  assert.equal(slideJobNext(a, undo), a);
  assert.equal(slideJobNext(a, fix(4)), a);
  assert.equal(slideJobNext(a, { type: "clear" }), a);
  assert.equal(slideJobNext(a, { type: "undone", seq: 1 }).run, null);
  const failed = slideJobNext(a, { type: "undoFailed", seq: 1, error: "Вернуть не получилось" });
  assert.deepEqual(failed.run && [failed.run.undo, failed.run.undoError, slideBusy(failed.run)], ["error", "Вернуть не получилось", false]);
  // идущая работа не отменяется
  const working = slideJobNext(JOB0, fix());
  assert.equal(slideJobNext(working, undo), working);
});

test("«Вернуть как было» после перезагрузки: запуска нет — появляется свой, сразу кончившийся, с идущим возвратом", () => {
  const a = slideJobNext(JOB0, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 500 });
  assert.deepEqual(a.run && [a.seq, a.run.kind, a.run.slide, a.run.phase, a.run.undo, a.run.fix, a.run.jobId], [1, "fix", 7, "done", "work", null, null]);
  // кончившаяся работа на другом слайде (или другого рода на этом) уступает место возврату исправления этого слайда
  const other = run(JOB0, fix(3), { type: "settled", seq: 1, at: 900, error: "нет" }, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 1000 });
  assert.deepEqual(other.run && [other.seq, other.run.slide, other.run.undo, other.run.error], [2, 7, "work", null]);
  const picture = run(JOB0, { type: "start", kind: "picture", strategy: "structured", slide: 7, wish: "", action: "generate", requested: [], at: 1 },
    { type: "settled", seq: 1, at: 900, error: "Нет модели изображений" }, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 1000 });
  assert.deepEqual(picture.run && [picture.seq, picture.run.kind, picture.run.undo, picture.run.error], [2, "fix", "work", null]);
});

test("смена слайда убирает строку неудачи и «слайд остался прежним», но не итог, который можно вернуть", () => {
  const failed = run(JOB0, fix(), { type: "settled", seq: 1, at: 900, error: "нет" });
  assert.equal(slideJobNext(failed, { type: "clear" }).run, null);
  const kept = run(JOB0, fix(), { type: "settled", seq: 1, at: 900, fix: { applied: false } as SlideFixResult });
  assert.equal(slideJobNext(kept, { type: "clear" }).run, null);
  const applied = run(JOB0, fix(), { type: "settled", seq: 1, at: 900, fix: RES });
  assert.equal(slideJobNext(applied, { type: "clear" }), applied);
  const working = slideJobNext(JOB0, fix());
  assert.equal(slideJobNext(working, { type: "clear" }), working);
  assert.equal(slideJobNext(JOB0, { type: "clear" }), JOB0);
});

test("почему новая работа сейчас не начнётся", () => {
  assert.equal(busyWhy(null), null);
  assert.equal(busyWhy(slideJobNext(JOB0, fix()).run), "Агент сейчас исправляет слайд 3");
  const pic = slideJobNext(JOB0, { type: "start", kind: "picture", strategy: "structured", slide: 2, wish: "", action: "generate", requested: [], at: 1 });
  assert.equal(busyWhy(pic.run), "Агент меняет изображение на слайде 2");
  const undoing = slideJobNext(JOB0, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 500 });
  assert.equal(busyWhy(undoing.run), "Возвращаю как было — дождитесь конца");
  assert.equal(busyWhy(run(JOB0, fix(), { type: "settled", seq: 1, at: 900, fix: RES }).run), null);
});
