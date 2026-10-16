import { test } from "node:test";
import assert from "node:assert/strict";
import type { Job } from "../../types";
import {
  asRebuildResult, followRebuild, makeRebuildStore, parsePending, rebuildBusy, rebuildNext, REBUILD0, REFUSED_SAME, refusalText, resumeRebuild, rowAct,
  startRebuild, takeFocus, undoRebuild, VARIANT_TAKEN, withoutPending, withPending, type PendingRebuild, type RebuildDeps, type RebuildState,
} from "./rebuild";

const K = "g1|structured";
const free = { off: false, why: null };
const run = (s: RebuildState) => s[K] ?? null;
const done = (s: RebuildState, over: { stale?: boolean; slide?: number } = {}) =>
  rebuildNext(s, { type: "done", key: K, seq: run(s)!.seq, stale: over.stale ?? false, slide: over.slide ?? run(s)!.slide, said: "Слайд 4 пересобран: вертикальные столбцы" });

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
  assert.equal(rebuildNext(s, { type: "done", key: K, seq: r.seq - 1, stale: false, slide: 4, said: "" }), s);
  s = done(s);
  assert.deepEqual([run(s)!.phase, run(s)!.stale, run(s)!.said], ["done", false, "Слайд 4 пересобран: вертикальные столбцы"]);
  assert.equal(rebuildBusy(run(s)), false);
});

test("фокус: запуск — на строку хода, готово — на «Вернуть как было», отказ — на строку отказа; берётся один раз", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  assert.equal(run(s)!.focus, "busy");
  assert.equal(takeFocus(run(s), 5, "busy"), false); // другой слайд
  assert.equal(takeFocus(run(s), 4, "undo"), false); // не то место
  assert.equal(takeFocus(run(s), 4, "busy"), true);
  assert.equal(takeFocus(run(s), 4, "busy"), false); // уже взят
  s = done(s);
  assert.equal(run(s)!.focus, "undo");
  assert.equal(takeFocus(run(s), 4, "undo"), true);
  // не перечиталось — фокус на строку с «Обновить»
  let t = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  t = done(t, { stale: true });
  assert.equal(run(t)!.focus, "note");
  // отказ — на строку отказа; вежливой строки нет (её говорит сама строка у варианта)
  let f = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 2 });
  f = rebuildNext(f, { type: "failed", key: K, seq: run(f)!.seq, error: "Не подходит.", tone: "refused" });
  assert.deepEqual([run(f)!.focus, run(f)!.said], ["note", null]);
});

test("отказ анализа — спокойной строкой у варианта, повтор причины — коротко; неудача — красной", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 2 });
  const seq = run(s)!.seq;
  const why = "«Круговая диаграмма» не подходит: 8 долей — мелкие сектора нечитаемы.";
  s = rebuildNext(s, { type: "failed", key: K, seq, error: why, tone: "refused" });
  assert.deepEqual(rowAct(run(s), 4, 2, 0, false, free), { mode: "refused", text: why, same: false });
  // у варианта уже написано «почему не он» той же фразой — строка не повторяет её (REFUSED_SAME)
  assert.deepEqual(rowAct(run(s), 4, 2, 0, false, free, "8 долей — мелкие сектора нечитаемы."), { mode: "refused", text: why, same: true });
  assert.ok(REFUSED_SAME.includes("причина выше"));
  assert.deepEqual(rowAct(run(s), 4, 1, 0, false, free), { mode: "button", off: false, why: null });
  assert.deepEqual(rowAct(run(s), 5, 2, 0, false, free), { mode: "button", off: false, why: null }); // другой слайд
  const e = rebuildNext(rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 2 }), { type: "failed", key: K, seq: seq + 1, error: "Модель не ответила", tone: "error" });
  assert.deepEqual(rowAct(run(e), 4, 2, 0, false, free), { mode: "error", text: "Модель не ответила" });
  s = rebuildNext(s, { type: "start", key: K, slide: 4, option: 1 });
  assert.equal(rowAct(run(s), 4, 2, 0, false, free).mode, "button");
});

test("место действия: ход — у пересобираемого варианта, остальные выключены с причиной; выбранный — без действия", () => {
  const s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  assert.deepEqual(rowAct(run(s), 4, 1, 0, false, free), { mode: "busy" });
  assert.deepEqual(rowAct(run(s), 4, 2, 0, false, free), { mode: "button", off: true, why: "Пересобираю слайд 4 — дождитесь конца" });
  assert.deepEqual(rowAct(run(s), 4, 0, 0, false, free), { mode: "none" });
  assert.deepEqual(rowAct(null, 4, 2, 0, false, { off: true, why: "Агент сейчас исправляет слайд 3" }), { mode: "button", off: true, why: "Агент сейчас исправляет слайд 3" });
});

test("пересобрано: у выбранного — «Вернуть как было»; экран не перечитался — строка с «Обновить» у пересобранного", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  s = done(s, { stale: true });
  assert.deepEqual(rowAct(run(s), 4, 1, 0, false, free), { mode: "stale" });
  assert.deepEqual(rowAct(run(s), 4, 1, 1, true, free), { mode: "done", undoing: false, text: null, off: false, why: null });
  assert.equal(rowAct(run(s), 4, 0, 1, true, free).mode, "button");
});

test("«Вернуть как было»: идёт — дуга, остальные выключены; вернулось — на месте ничего, фокус на выбранном; не вышло — причина", () => {
  let s = rebuildNext(REBUILD0, { type: "start", key: K, slide: 4, option: 1 });
  s = done(s);
  s = rebuildNext(s, { type: "undo", key: K, slide: 4 });
  assert.equal(run(s)!.undo, "work");
  assert.deepEqual(rowAct(run(s), 4, 1, 1, true, free), { mode: "done", undoing: true, text: null, off: false, why: null });
  assert.deepEqual(rowAct(run(s), 4, 0, 1, true, free), { mode: "button", off: true, why: "Возвращаю как было — дождитесь конца" });
  assert.equal(rebuildNext(s, { type: "undo", key: K, slide: 4 }), s);
  const seq = run(s)!.seq;
  const failed = rebuildNext(s, { type: "undoFailed", key: K, seq, error: "Вернуть не получилось. Попробуйте ещё раз." });
  assert.deepEqual(rowAct(run(failed), 4, 1, 1, true, free), { mode: "done", undoing: false, text: "Вернуть не получилось. Попробуйте ещё раз.", off: false, why: null });
  const back = rebuildNext(s, { type: "undone", key: K, seq, stale: false, slide: 3, said: "Слайд 3 — снова как было" });
  assert.deepEqual([run(back)!.phase, run(back)!.slide, run(back)!.focus, run(back)!.said], ["idle", 3, "row", "Слайд 3 — снова как было"]);
  // на месте ничего не стоит: выбранный анализом — без действия, остальные включены
  assert.deepEqual(rowAct(run(back), 3, 0, 0, false, free), { mode: "none" });
  assert.deepEqual(rowAct(run(back), 3, 1, 0, false, free), { mode: "button", off: false, why: null });
  const stale = rebuildNext(s, { type: "undone", key: K, seq, stale: true, slide: 4, said: "" });
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

// ── ход с сервером: подставные зависимости

class Status extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}
const job = (over: Partial<Job>): Job => ({ id: "j1", kind: "rebuild", status: "done", progress: 1, message: "", error: null, created_at: 0, finished_at: 1, result: null, ...over });
const result = (over: Record<string, unknown> = {}) => ({ kind: "rebuild", changed: true, applied: true, reply: "", strategy: "structured", slide: 4, slides: [4], option: 1, title: "Вертикальные столбцы", ...over });

function fake(over: Partial<RebuildDeps> = {}) {
  const log: string[] = [];
  let finish: ((j: Job) => void | Promise<void>) | null = null;
  let fail: ((j: Job) => void) | null = null;
  const deps: RebuildDeps = {
    request: async (slide, option) => (log.push(`request ${slide} ${option}`), { job_id: "j1" }),
    watch: (jobId, slide, d, f) => {
      log.push(`watch ${jobId} ${slide}`);
      finish = d;
      fail = f;
    },
    reload: async () => (log.push("reload"), true),
    select: (n) => void log.push(`select ${n}`),
    remember: (jobId, slide, option) => void log.push(`remember ${jobId} ${slide} ${option}`),
    forget: (jobId) => void log.push(`forget ${jobId}`),
    taken: () => false,
    revert: async (slide) => (log.push(`revert ${slide}`), { why: null, stale: false }),
    ...over,
  };
  return { deps, log, end: (j: Job) => finish!(j), fail: (j: Job) => fail!(j) };
}

test("ход: запрос → задача записана → готово: перечитано, итог сказан, фокус на «Вернуть как было», запись снята", async () => {
  const store = makeRebuildStore();
  const f = fake();
  await startRebuild(store, K, 4, 1, f.deps);
  assert.deepEqual(f.log, ["request 4 1", "remember j1 4 1", "watch j1 4"]);
  assert.equal(store.get()[K]!.jobId, "j1");
  await f.end(job({ result: result() }));
  const r = store.get()[K]!;
  assert.deepEqual([r.phase, r.stale, r.slide, r.focus, r.said], ["done", false, 4, "undo", "Слайд 4 пересобран: вертикальные столбцы"]);
  assert.deepEqual(f.log.slice(3), ["forget j1", "reload"]); // тот же слайд — выбор не меняется
});

test("ход: слайдов стало другое число — выбран первый новый; не перечиталось — строка с «Обновить» у того же слайда", async () => {
  const store = makeRebuildStore();
  const f = fake();
  await startRebuild(store, K, 5, 0, f.deps);
  await f.end(job({ result: result({ slide: 3, slides: [3], title: "Линейный график" }) }));
  assert.ok(f.log.includes("select 3"));
  assert.deepEqual([store.get()[K]!.slide, store.get()[K]!.said], [3, "Слайд 3 пересобран: линейный график"]);

  const s2 = makeRebuildStore();
  const g = fake({ reload: async () => false });
  await startRebuild(s2, K, 5, 0, g.deps);
  await g.end(job({ result: result({ slides: [3] }) }));
  assert.ok(!g.log.some((x) => x.startsWith("select")));
  assert.deepEqual([s2.get()[K]!.stale, s2.get()[K]!.slide, s2.get()[K]!.focus], [true, 5, "note"]);
  assert.deepEqual(rowAct(s2.get()[K], 5, 0, 1, false, free), { mode: "stale" });
});

test("ход: слайд не изменился — перечитать и сказать спокойно; задача не удалась — красной строкой, запись снята", async () => {
  const store = makeRebuildStore();
  const f = fake();
  await startRebuild(store, K, 4, 2, f.deps);
  await f.end(job({ result: result({ changed: false, reply: "Слайд остался прежним: данные не сложились в кольцо." }) }));
  assert.ok(f.log.includes("reload"));
  assert.deepEqual([store.get()[K]!.phase, store.get()[K]!.tone, store.get()[K]!.error], ["failed", "refused", "Слайд остался прежним: данные не сложились в кольцо."]);

  const s2 = makeRebuildStore();
  const g = fake();
  await startRebuild(s2, K, 4, 2, g.deps);
  g.fail(job({ status: "failed", error: "Модель не ответила" }));
  assert.deepEqual([s2.get()[K]!.phase, s2.get()[K]!.tone, s2.get()[K]!.error], ["failed", "error", "Модель не ответила"]);
  assert.ok(g.log.includes("forget j1"));
});

test("отказ при запуске: 422 — спокойно; 409 и «уже показан так» — сперва перечитать презентацию", async () => {
  const s1 = makeRebuildStore();
  const a = fake({ request: async () => Promise.reject(new Status(422, "«Круговая диаграмма» не подходит: 8 долей.")) });
  await startRebuild(s1, K, 4, 2, a.deps);
  assert.deepEqual([s1.get()[K]!.phase, s1.get()[K]!.tone], ["failed", "refused"]);
  assert.ok(!a.log.includes("reload"));

  // экран отстал (пересобрано в другой вкладке, страница перезагружена посреди задачи): перечитано — и всё
  const s2 = makeRebuildStore();
  const b = fake({ request: async () => Promise.reject(new Status(422, "Слайд 4 уже показан так: вертикальные столбцы")) });
  await startRebuild(s2, K, 4, 1, b.deps);
  assert.deepEqual(b.log, ["reload"]);
  assert.deepEqual([s2.get()[K]!.phase, s2.get()[K]!.focus, s2.get()[K]!.said], ["idle", "row", "Слайд 4 уже показан так: вертикальные столбцы"]);
  assert.deepEqual(rowAct(s2.get()[K], 4, 1, 1, false, free), { mode: "none" });

  const s3 = makeRebuildStore();
  const c = fake({ request: async () => Promise.reject(new Status(409, "Этот вариант уже меняется — дождитесь, пока агент закончит")) });
  await startRebuild(s3, K, 4, 1, c.deps);
  assert.deepEqual(c.log, ["reload"]);
  assert.deepEqual([s3.get()[K]!.phase, s3.get()[K]!.tone], ["failed", "refused"]);

  // над вариантом уже идёт чужая задача — без запроса
  const s4 = makeRebuildStore();
  const d = fake({ taken: () => true });
  await startRebuild(s4, K, 4, 1, d.deps);
  assert.deepEqual(d.log, []);
  assert.deepEqual([s4.get()[K]!.error, s4.get()[K]!.tone], [VARIANT_TAKEN, "refused"]);
});

test("«Вернуть как было»: вернулось — выбран первый слайд пересборки, сказано; не вышло — причина у кнопки", async () => {
  const store = makeRebuildStore();
  const f = fake();
  await undoRebuild(store, K, 5, 3, f.deps);
  assert.deepEqual(f.log, ["revert 5", "select 3"]);
  assert.deepEqual([store.get()[K]!.phase, store.get()[K]!.slide, store.get()[K]!.focus, store.get()[K]!.said], ["idle", 3, "row", "Слайд 3 — снова как было"]);

  const s2 = makeRebuildStore();
  const g = fake({ revert: async () => ({ why: "Вернуть не получилось", stale: false }) });
  await undoRebuild(s2, K, 4, 4, g.deps);
  assert.deepEqual([s2.get()[K]!.undo, s2.get()[K]!.undoError, s2.get()[K]!.focus], ["failed", "Вернуть не получилось", "note"]);

  // вернулось, а экран не перечитался — слайд не трогаем
  const s3 = makeRebuildStore();
  const h = fake({ revert: async () => ({ why: null, stale: true }) });
  await undoRebuild(s3, K, 5, 3, h.deps);
  assert.ok(!h.log.some((x) => x.startsWith("select")));
});

test("перезагрузка посреди пересборки: идёт — снова своя работа; кончилась — перечитать; нет её — забыть; сервер молчит — запись остаётся", async () => {
  const p: PendingRebuild = { gid: "g1", strategy: "structured", slide: 4, option: 1, jobId: "j7", at: Date.now() };
  const s1 = makeRebuildStore();
  const a = fake();
  assert.equal(await resumeRebuild(s1, K, p, async () => job({ id: "j7", status: "running" }), a.deps), true);
  assert.deepEqual(a.log, ["watch j7 4"]);
  assert.deepEqual([s1.get()[K]!.phase, s1.get()[K]!.jobId, s1.get()[K]!.focus], ["work", "j7", null]);
  assert.deepEqual(rowAct(s1.get()[K], 4, 1, 0, false, free), { mode: "busy" });
  await a.end(job({ id: "j7", result: result() }));
  assert.equal(s1.get()[K]!.phase, "done");

  const b = fake();
  assert.equal(await resumeRebuild(makeRebuildStore(), K, p, async () => job({ id: "j7", status: "done" }), b.deps), true);
  assert.deepEqual(b.log, ["forget j7", "reload"]);
  const c = fake();
  assert.equal(await resumeRebuild(makeRebuildStore(), K, p, async () => null, c.deps), true);
  assert.deepEqual(c.log, ["forget j7"]);
  const d = fake();
  assert.equal(await resumeRebuild(makeRebuildStore(), K, p, async () => Promise.reject(new Error("Сеть недоступна")), d.deps), false);
  assert.deepEqual(d.log, []);
});

test("поздний конец прежней задачи новый запуск не трогает", async () => {
  const store = makeRebuildStore();
  const f = fake();
  await startRebuild(store, K, 4, 1, f.deps);
  const first = f.end;
  store.send({ type: "failed", key: K, seq: store.get()[K]!.seq, error: "x", tone: "error" });
  const g = fake({ request: async () => ({ job_id: "j2" }) });
  await startRebuild(store, K, 4, 2, g.deps);
  await first(job({ result: result() }));
  assert.deepEqual([store.get()[K]!.phase, store.get()[K]!.option], ["work", 2]);
  // followRebuild для чужого seq — тоже без следа
  followRebuild(store, K, -1, 4, "j0", fake().deps);
  assert.equal(store.get()[K]!.phase, "work");
});

test("записанные задачи: испорченная запись — пусто, старше суток — нет, одна на вариант", () => {
  const now = 1_000_000_000;
  assert.deepEqual(parsePending("{", now), []);
  assert.deepEqual(parsePending("[1, null, {\"gid\": 3}]", now), []);
  const a: PendingRebuild = { gid: "g1", strategy: "structured", slide: 4, option: 1, jobId: "j1", at: now };
  const old: PendingRebuild = { ...a, jobId: "j0", at: now - 25 * 3600 * 1000 };
  assert.deepEqual(parsePending(JSON.stringify([a, old]), now), [a]);
  const b = { ...a, jobId: "j2", slide: 5 };
  assert.deepEqual(withPending([a], b), [b]); // тот же вариант — новая задача вместо прежней
  const c = { ...a, strategy: "visual", jobId: "j3" };
  assert.deepEqual(withPending([a], c), [a, c]);
  assert.deepEqual(withoutPending([a, c], "j1"), [c]);
});
