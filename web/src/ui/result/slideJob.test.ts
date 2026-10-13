import { test } from "node:test";
import assert from "node:assert/strict";
import type { SlideFixResult } from "../../types";
import type { ActiveJob } from "../../lib/jobState";
import { VARIANT_BUSY } from "../details/variantWork";
import { adoptPlan, awayFailText, busyWhy, JOB0, liveWork, runOf, slideBusy, slideJobNext, staleOf, variantLiveJob, type SlideJobAction, type SlideJobState } from "./slideJob";
import type { PictureChangeResult } from "../../types";
import type { Remark } from "./marks";

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

// ── R1: изменение сохранено, а презентация на экране не перечиталась
test("итог применён, а экран не перечитан: работа кончилась с итогом и меткой `change`; строка — пока презентация несвежая", () => {
  const a = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 }, { type: "settled", seq: 1, at: 900, fix: RES, stale: true });
  const r = a.runs.structured!;
  assert.deepEqual([r.phase, r.fix, r.error, r.stale], ["done", RES, null, "change"]);
  assert.equal(staleOf(r, true), "change");
  // перечиталась (любым путём) — вид снова по презентации: итог встаёт сам
  assert.equal(staleOf(r, false), null);
  // другой слайд строку не снимает: изменение сохранено, экран его ещё не показал
  assert.equal(slideJobNext(a, { type: "clear", strategy: "structured" }), a);
  // перечитанный итог — без метки
  const b = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 }, { type: "settled", seq: 1, at: 900, fix: RES });
  assert.equal(b.runs.structured!.stale, null);
});

test("вернулось как было, а экран не перечитан: итог остаётся на экране с меткой `undo`; новый возврат её снимает", () => {
  const done = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j1", at: 250 }, { type: "settled", seq: 1, at: 900, fix: RES });
  const going = slideJobNext(done, { type: "undo", kind: "fix", strategy: "structured", slide: 3, at: 1000 });
  const st = slideJobNext(going, { type: "undoStale", seq: 1 });
  assert.deepEqual([st.runs.structured!.undo, st.runs.structured!.undoError, st.runs.structured!.stale, st.runs.structured!.fix], [null, null, "undo", RES]);
  assert.equal(slideBusy(st.runs.structured), false);
  assert.equal(staleOf(st.runs.structured, true), "undo");
  // прежний запуск метку не ставит
  assert.equal(slideJobNext(going, { type: "undoStale", seq: 7 }), going);
  // возврат без итога на странице (перезагрузка) — тоже с меткой
  const back = run(JOB0, { type: "undo", kind: "fix", strategy: "structured", slide: 2, at: 5 }, { type: "undoStale", seq: 1 });
  assert.equal(back.runs.structured!.stale, "undo");
  assert.equal(slideJobNext(back, { type: "clear", strategy: "structured" }), back);
});

// ── R9: задача над слайдом, которую экран не запускал, выглядит как своя
const live = (id: string, kind: ActiveJob["kind"], slide: number, strategy = "structured"): ActiveJob =>
  ({ id, label: "", progress: 0.4, message: "", status: "running", kind, startedAt: 500, target: { generation: "g", strategy, slide } });
const fixKind = () => "fix" as const;

test("adoptPlan: исправление и правка помощника на слайде — карточка хода R-fixing; изображение — ход в карточке «Изображение»", () => {
  assert.deepEqual(adoptPlan(live("j", "slide_fix", 3), null, fixKind), { kind: "fix", slide: 3, undo: false, source: "slide_fix" });
  assert.deepEqual(adoptPlan(live("j", "edit", 4), null, fixKind), { kind: "fix", slide: 4, undo: false, source: "edit" });
  assert.deepEqual(adoptPlan(live("j", "picture", 2), null, fixKind), { kind: "picture", slide: 2, undo: false, source: "picture" });
  // «Вернуть как было» слайда — возврат того рода, каким было последнее изменение слайда
  assert.deepEqual(adoptPlan(live("j", "undo", 2), null, () => "picture"), { kind: "picture", slide: 2, undo: true, source: "undo" });
});

test("adoptPlan: задача над всем вариантом и своя идущая работа — не подхватываются", () => {
  assert.equal(adoptPlan(live("j", "fix", 0), null, fixKind), null); // «Исправить всё» — весь вариант
  assert.equal(adoptPlan(live("j", "undo", 0), null, fixKind), null); // возврат из «Агента» — весь вариант
  assert.equal(adoptPlan(null, null, fixKind), null);
  const busy = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "own", at: 1 }).runs.structured!;
  assert.equal(adoptPlan(live("j", "undo", 3), busy, fixKind), null); // свой возврат или работа ещё идут
  const done = run(JOB0, fix(), { type: "accepted", seq: 1, jobId: "j", at: 1 }).runs.structured!;
  assert.equal(adoptPlan(live("j", "slide_fix", 3), done, fixKind), null); // это и есть своя
});

test("подхваченная работа: задача, её часы и замечания слайда; ход и конец — как у своей; повтор и занятый вариант — без перемен", () => {
  const rows = [{ id: "r1", n: 1 }] as unknown as Remark[];
  const a = slideJobNext(JOB0, { type: "adopt", kind: "fix", strategy: "structured", slide: 3, jobId: "j9", startedAt: 500, requested: rows, undo: false });
  const r = a.runs.structured!;
  assert.deepEqual([r.seq, r.kind, r.slide, r.phase, r.jobId, r.startedAt, r.endedAt, r.wish, r.requested], [1, "fix", 3, "work", "j9", 500, null, "", rows]);
  assert.equal(slideBusy(r), true);
  assert.equal(busyWhy(r), "Агент сейчас исправляет слайд 3");
  // та же задача ещё раз и новая работа, пока эта идёт, — то же состояние
  assert.equal(slideJobNext(a, { type: "adopt", kind: "fix", strategy: "structured", slide: 3, jobId: "j9", startedAt: 500, requested: [], undo: false }), a);
  assert.equal(slideJobNext(a, fix(5)), a);
  // конец — итог R-fixed, как у своей
  const done = slideJobNext(a, { type: "settled", seq: 1, at: 900, fix: RES });
  assert.deepEqual([done.runs.structured!.phase, done.runs.structured!.fix, done.runs.structured!.endedAt], ["done", RES, 900]);
  // правка помощника — тихая строка итога; другой слайд её не снимает
  const note = slideJobNext(a, { type: "settled", seq: 1, at: 900, note: "Сократил заголовок." });
  assert.equal(note.runs.structured!.note, "Сократил заголовок.");
  assert.equal(slideJobNext(note, { type: "clear", strategy: "structured" }), note);
});

test("подхваченная замена изображения узнаёт из итога, что делали; подхваченный возврат — идущий возврат на кончившейся работе", () => {
  const a = run(JOB0, { type: "adopt", kind: "picture", strategy: "structured", slide: 2, jobId: "p", startedAt: 1, requested: [], undo: false },
    { type: "settled", seq: 1, at: 5, picture: { applied: true, action: "remove" } as PictureChangeResult });
  assert.equal(a.runs.structured!.action, "remove");
  const u = slideJobNext(JOB0, { type: "adopt", kind: "fix", strategy: "structured", slide: 2, jobId: "u", startedAt: 1, requested: [], undo: true });
  assert.deepEqual([u.runs.structured!.phase, u.runs.structured!.undo, u.runs.structured!.jobId], ["done", "work", "u"]);
  assert.equal(busyWhy(u.runs.structured), "Возвращаю как было — дождитесь конца");
  assert.equal(runOf(slideJobNext(u, { type: "undone", seq: 1 }), "structured"), null);
});

test("неудача работы, чьё место человек не видит: строка результата — что и на каком слайде, причина по-русски", () => {
  assert.equal(awayFailText("fix", null, 5, { error: "Модель не ответила: ProviderError: 503", message: "" }), "Не получилось исправить слайд 5: модель не ответила.");
  assert.equal(awayFailText("picture", "remove", 2, { error: null, message: "" }), "Не получилось убрать изображение на слайде 2. Попробуйте ещё раз.");
  assert.equal(awayFailText("picture", null, 2, { error: "Traceback: KeyError", message: "" }), "Не получилось заменить изображение на слайде 2. Попробуйте ещё раз.");
});

test("liveWork: возврат как было — его причина у выключенных кнопок", () => {
  assert.deepEqual(liveWork(live("u", "undo", 3)), { why: "Возвращаю как было — дождитесь конца", slide: 3 });
});
