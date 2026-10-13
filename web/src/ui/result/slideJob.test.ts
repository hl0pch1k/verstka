import { test } from "node:test";
import assert from "node:assert/strict";
import type { SlideFixResult } from "../../types";
import type { ActiveJob } from "../../lib/jobState";
import { VARIANT_BUSY } from "../details/variantWork";
import { busyWhy, JOB0, liveWork, runOf, slideBusy, slideJobNext, variantLiveJob, type SlideJobAction, type SlideJobState } from "./slideJob";

const run = (s: SlideJobState, ...as: SlideJobAction[]) => as.reduce(slideJobNext, s);
const fix = (slide = 3): SlideJobAction => ({ type: "start", kind: "fix", strategy: "structured", slide, wish: "  покажи этапами ", action: null, requested: [], at: 100 });
const RES = { applied: true } as SlideFixResult;

test("запуск: новый номер и работа без задачи; пока идёт работа, второй запуск не начинается", () => {
  const a = slideJobNext(JOB0, fix());
  assert.equal(a.seq, 1);
  assert.deepEqual(a.runs.structured && [a.runs.structured.seq, a.runs.structured.kind, a.runs.structured.slide, a.runs.structured.phase, a.runs.structured.jobId, a.runs.structured.startedAt, a.runs.structured.endedAt, a.runs.structured.wish], [1, "fix", 3, "work", null, 100, null, "покажи этапами"]);
  assert.equal(slideBusy(a.runs.structured), true);
  assert.equal(slideJobNext(a, fix(4)), a);
  assert.equal(slideJobNext(a, { type: "start", kind: "picture", strategy: "structured", slide: 3, wish: "", action: "remove", requested: [], at: 1 }), a);
});

test("сервер принял задачу: у запуска её номер и свои часы; ответ на прежний запуск ничего не меняет", () => {
  const a = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 });
  assert.deepEqual(a.runs.structured && [a.runs.structured.jobId, a.runs.structured.startedAt, a.runs.structured.phase], ["j1", 250, "work"]);
  assert.equal(slideJobNext(a, { type: "accepted", seq: 0, jobId: "old", at: 1 }), a);
});

test("конец работы: итог и остановленные часы; снова можно начинать, а поздний конец прежнего запуска не трогает новый", () => {
  const a = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 }, { type: "settled", seq: 1, at: 900, fix: RES });
  assert.deepEqual(a.runs.structured && [a.runs.structured.phase, a.runs.structured.endedAt, a.runs.structured.fix, a.runs.structured.error], ["done", 900, RES, null]);
  assert.equal(slideBusy(a.runs.structured), false);
  const b = slideJobNext(a, fix(5));
  assert.deepEqual([b.seq, b.runs.structured?.slide, b.runs.structured?.phase], [2, 5, "work"]);
  assert.equal(slideJobNext(b, { type: "settled", seq: 1, at: 1000, error: "поздно" }), b);
  // отказ при запуске — тоже конец, со строкой
  const c = run(JOB0, fix(), { type: "settled", seq: 1, at: 120, error: "Этот вариант уже меняется" });
  assert.deepEqual(c.runs.structured && [c.runs.structured.phase, c.runs.structured.jobId, c.runs.structured.error], ["done", null, "Этот вариант уже меняется"]);
});

test("«Вернуть как было»: только у кончившейся работы и одно за раз; вернулось — итога больше нет, не вышло — строка", () => {
  const done = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 }, { type: "settled", seq: 1, at: 900, fix: RES });
  const undo: SlideJobAction = { type: "undo", kind: "fix", strategy: "structured", slide: 3, at: 1000 };
  const a = slideJobNext(done, undo);
  assert.deepEqual(a.runs.structured && [a.seq, a.runs.structured.seq, a.runs.structured.undo, a.runs.structured.fix], [1, 1, "work", RES]);
  assert.equal(slideBusy(a.runs.structured), true);
  assert.equal(slideJobNext(a, undo), a);
  assert.equal(slideJobNext(a, fix(4)), a);
  assert.equal(slideJobNext(a, { type: "clear", strategy: "structured" }), a);
  assert.equal(slideJobNext(a, { type: "undone", seq: 1 }).runs.structured, undefined);
  const failed = slideJobNext(a, { type: "undoFailed", seq: 1, error: "Вернуть не получилось" });
  assert.deepEqual(failed.runs.structured && [failed.runs.structured.undo, failed.runs.structured.undoError, slideBusy(failed.runs.structured)], ["error", "Вернуть не получилось", false]);
  // идущая работа не отменяется
  const working = slideJobNext(JOB0, fix());
  assert.equal(slideJobNext(working, undo), working);
});

test("«Вернуть как было» после перезагрузки: запуска нет — появляется свой, сразу кончившийся, с идущим возвратом", () => {
  const a = slideJobNext(JOB0, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 500 });
  assert.deepEqual(a.runs.structured && [a.seq, a.runs.structured.kind, a.runs.structured.slide, a.runs.structured.phase, a.runs.structured.undo, a.runs.structured.fix, a.runs.structured.jobId], [1, "fix", 7, "done", "work", null, null]);
  // кончившаяся работа на другом слайде (или другого рода на этом) уступает место возврату исправления этого слайда
  const other = run(JOB0, fix(3), { type: "settled", seq: 1, at: 900, error: "нет" }, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 1000 });
  assert.deepEqual(other.runs.structured && [other.seq, other.runs.structured.slide, other.runs.structured.undo, other.runs.structured.error], [2, 7, "work", null]);
  const picture = run(JOB0, { type: "start", kind: "picture", strategy: "structured", slide: 7, wish: "", action: "generate", requested: [], at: 1 },
    { type: "settled", seq: 1, at: 900, error: "Нет модели изображений" }, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 1000 });
  assert.deepEqual(picture.runs.structured && [picture.seq, picture.runs.structured.kind, picture.runs.structured.undo, picture.runs.structured.error], [2, "fix", "work", null]);
});

test("смена слайда убирает строку неудачи и «слайд остался прежним», но не итог, который можно вернуть", () => {
  const failed = run(JOB0, fix(), { type: "settled", seq: 1, at: 900, error: "нет" });
  assert.equal(slideJobNext(failed, { type: "clear", strategy: "structured" }).runs.structured, undefined);
  const kept = run(JOB0, fix(), { type: "settled", seq: 1, at: 900, fix: { applied: false } as SlideFixResult });
  assert.equal(slideJobNext(kept, { type: "clear", strategy: "structured" }).runs.structured, undefined);
  const applied = run(JOB0, fix(), { type: "settled", seq: 1, at: 900, fix: RES });
  assert.equal(slideJobNext(applied, { type: "clear", strategy: "structured" }), applied);
  const working = slideJobNext(JOB0, fix());
  assert.equal(slideJobNext(working, { type: "clear", strategy: "structured" }), working);
  assert.equal(slideJobNext(JOB0, { type: "clear", strategy: "structured" }), JOB0);
});

test("почему новая работа сейчас не начнётся", () => {
  assert.equal(busyWhy(null), null);
  assert.equal(busyWhy(slideJobNext(JOB0, fix()).runs.structured), "Агент сейчас исправляет слайд 3");
  const pic = slideJobNext(JOB0, { type: "start", kind: "picture", strategy: "structured", slide: 2, wish: "", action: "generate", requested: [], at: 1 });
  assert.equal(busyWhy(pic.runs.structured), "Агент меняет изображение на слайде 2");
  const undoing = slideJobNext(JOB0, { type: "undo", kind: "fix", strategy: "structured", slide: 7, at: 500 });
  assert.equal(busyWhy(undoing.runs.structured), "Возвращаю как было — дождитесь конца");
  assert.equal(busyWhy(run(JOB0, fix(), { type: "settled", seq: 1, at: 900, fix: RES }).runs.structured), null);
});

test("у каждого варианта своя работа: исправление на одном не держит другой (C2)", () => {
  const a = run(JOB0, fix(3), { type: "accepted", seq: 1, jobId: "j1", at: 250 });
  const b = slideJobNext(a, { type: "start", kind: "fix", strategy: "visual", slide: 5, wish: "", action: null, requested: [], at: 300 });
  assert.ok(b !== a);
  assert.deepEqual([runOf(b, "structured")?.slide, runOf(b, "visual")?.slide, runOf(b, "visual")?.seq], [3, 5, 2]);
  // конец и ответ сервера находят свой вариант по номеру запуска
  const c = run(b, { type: "accepted", seq: 2, jobId: "j2", at: 320 }, { type: "settled", seq: 1, at: 900, fix: RES });
  assert.deepEqual([runOf(c, "structured")?.phase, runOf(c, "visual")?.phase, runOf(c, "visual")?.jobId], ["done", "work", "j2"]);
  // смена слайда чистит строку только своего варианта
  const d = run(JOB0, fix(), { type: "settled", seq: 1, at: 900, error: "нет" });
  assert.equal(slideJobNext(d, { type: "clear", strategy: "visual" }), d);
  assert.equal(runOf(JOB0, "structured"), null);
});

test("чужая задача над вариантом: самая новая на этом варианте, кроме своей; почему работа не начнётся и какой слайд меняется", () => {
  const job = (id: string, kind: ActiveJob["kind"], strategy: string, slide: number, gid = "g1"): ActiveJob =>
    ({ id, label: "", progress: 0, message: "", status: "running", kind, startedAt: 0, target: { generation: gid, strategy, slide } });
  const live = [job("a", "slide_fix", "structured", 4), job("b", "edit", "visual", 2), job("c", "picture", "structured", 6), job("d", "fix", "structured", 0, "g2")];
  assert.equal(variantLiveJob(live, "g1", "structured", null)?.id, "c");
  assert.equal(variantLiveJob(live, "g1", "structured", "c")?.id, "a");
  assert.equal(variantLiveJob(live, "g1", "visual", null)?.id, "b");
  assert.equal(variantLiveJob(live, "g1", "classic", null), null);
  assert.equal(variantLiveJob(live, "g2", "visual", null), null);
  assert.deepEqual(liveWork(live[0]), { why: "Агент сейчас исправляет слайд 4", slide: 4 });
  assert.deepEqual(liveWork(live[2]), { why: "Агент меняет изображение на слайде 6", slide: 6 });
  assert.deepEqual(liveWork(live[1]), { why: VARIANT_BUSY, slide: 2 });
  assert.deepEqual(liveWork(live[3]), { why: VARIANT_BUSY, slide: null });
});
