import { test } from "node:test";
import assert from "node:assert/strict";
import type { GenerateRequest, GenerationMeta, Job, JobEvent } from "../../types";
import { buildView } from "./buildView";
import { failedBuildJob, parsePendingBuild, pendingFor, requestOf, resumeBuild, type PendingBuild } from "./resume";

const REQ: GenerateRequest = {
  template_id: "t1", brief: "Итоги квартала", audience: null, purpose: null, slides: 5, language: "ru", extra_instructions: null,
  strategies: ["structured"], use_models: false, audit_models: false, autofix: true, exports: ["pdf", "html"], pictures: null, eyes: false,
  improved_from: null,
};
const meta = (id: string, patch: Partial<GenerationMeta> = {}): GenerationMeta =>
  ({ id, template_id: "t1", strategies: ["structured", "visual"], brief: "Итоги квартала", slides: 5, created_at: 1000, ...patch });
const titleOf = (n: string) => n;

test("LS.build: запрос сборки читается, только когда в нём есть генерация и шаблон", () => {
  const ok: PendingBuild = { gid: "g1", request: REQ, expected: 7 };
  assert.deepEqual(parsePendingBuild(JSON.stringify(ok)), ok);
  // старая запись без expected — число слайдов неизвестно
  assert.deepEqual(parsePendingBuild(JSON.stringify({ gid: "g1", request: REQ })), { gid: "g1", request: REQ, expected: null });
  assert.equal(parsePendingBuild(null), null);
  assert.equal(parsePendingBuild(""), null);
  assert.equal(parsePendingBuild("{не json"), null);
  assert.equal(parsePendingBuild("null"), null);
  assert.equal(parsePendingBuild(JSON.stringify({ request: REQ, expected: 7 })), null); // без gid
  assert.equal(parsePendingBuild(JSON.stringify({ gid: "g1", request: { brief: "x" } })), null); // без шаблона
  assert.equal(parsePendingBuild(JSON.stringify({ gid: 5, request: REQ })), null);
});

test("запрос сборки по мете: те же входы, недостающее — по умолчанию сервера", () => {
  const r = requestOf(meta("g1", { audience: "совет директоров", purpose: "отчёт", language: "ru", extra_instructions: "коротко", use_models: false, audit_models: true, autofix: false, exports: ["pdf"], pictures: true, eyes: false }));
  assert.equal(r.template_id, "t1");
  assert.equal(r.brief, "Итоги квартала");
  assert.equal(r.audience, "совет директоров");
  assert.equal(r.purpose, "отчёт");
  assert.equal(r.slides, 5);
  assert.deepEqual(r.strategies, ["structured", "visual"]);
  assert.equal(r.extra_instructions, "коротко");
  assert.equal(r.use_models, false);
  assert.equal(r.audit_models, true);
  assert.equal(r.autofix, false);
  assert.deepEqual(r.exports, ["pdf"]);
  assert.equal(r.pictures, true);
  assert.equal(r.eyes, false);
  // мета идущей сборки — без переключателей: модель включена (сервер выключит её сам), автоправка, pdf и html
  const bare = requestOf({ id: "g2", template_id: "t2", strategies: ["structured"], brief: null });
  assert.equal(bare.brief, "");
  assert.equal(bare.use_models, true);
  assert.equal(bare.audit_models, false);
  assert.equal(bare.autofix, true);
  assert.deepEqual(bare.exports, ["pdf", "html"]);
  assert.equal(bare.slides, null);
  assert.equal(bare.pictures, null);
  assert.equal(bare.eyes, null);
  assert.equal(bare.improved_from, null);
});

test("LS.build пишется только для своей генерации: запрос другой сборки к ней не пристаёт", () => {
  const last = { gid: "g1", request: REQ, expected: 7 };
  assert.deepEqual(pendingFor(last, "g1"), { gid: "g1", request: REQ, expected: 7 });
  assert.equal(pendingFor(last, "g2"), null);
  assert.equal(pendingFor(null, "g1"), null);
  assert.equal(pendingFor(last, null), null);
});

test("после перезагрузки: идущая сборка из LS.build — снова за ней", () => {
  const pending: PendingBuild = { gid: "g1", request: REQ, expected: 7 };
  const g = meta("g1", { status: "running", job_id: "j1" });
  assert.deepEqual(resumeBuild(pending, g, []), { kind: "attach", meta: g, listed: false });
});

test("после перезагрузки: сборка из LS.build упала, пока страницы не было, — её неудача", () => {
  const pending: PendingBuild = { gid: "g1", request: REQ, expected: 7 };
  const g = meta("g1", { status: "failed", job_id: "j1", error: "Сервер перезапускался — сборка прервана. Соберите презентацию ещё раз" });
  assert.deepEqual(resumeBuild(pending, g, []), { kind: "failed", meta: g, listed: false });
  // саму генерацию не спросили (сеть) — она есть в списке
  assert.deepEqual(resumeBuild(pending, null, [meta("g0", { status: "done" }), g]), { kind: "failed", meta: g, listed: true });
});

test("после перезагрузки: сборка из LS.build кончилась — её презентация, даже если идёт чужая", () => {
  const pending: PendingBuild = { gid: "g1", request: REQ, expected: 7 };
  const g = meta("g1", { status: "done" });
  const other = meta("g9", { status: "running", job_id: "j9", created_at: 5000 });
  assert.deepEqual(resumeBuild(pending, g, [other, g]), { kind: "done", meta: g, listed: false });
});

test("после перезагрузки: без LS.build (или её генерации нет) — самая новая идущая сборка из списка с задачей", () => {
  const list = [
    meta("old", { status: "running", job_id: "j0", created_at: 1000 }),
    meta("new", { status: "running", job_id: "j2", created_at: 3000 }),
    meta("nojob", { status: "running", created_at: 4000 }), // задачи нет — следить не за чем
    meta("done", { status: "done", created_at: 5000 }),
    meta("failed", { status: "failed", job_id: "j3", created_at: 6000 }), // чужая неудача на экран не встаёт
  ];
  assert.deepEqual(resumeBuild(null, null, list), { kind: "attach", meta: list[1], listed: true });
  // LS.build указывает на удалённую генерацию — тоже по списку
  assert.deepEqual(resumeBuild({ gid: "gone", request: REQ, expected: null }, null, list), { kind: "attach", meta: list[1], listed: true });
  // ничего не идёт — ничего
  assert.equal(resumeBuild(null, null, [list[3], list[4]]), null);
  assert.equal(resumeBuild(null, null, []), null);
});

test("сборка, упавшая без страницы: неудача на экране «Сборка» с причиной из меты, часы без конца — прочерк", () => {
  const g = meta("g1", { status: "failed", job_id: "j1", error: "Сервер перезапускался — сборка прервана. Соберите презентацию ещё раз\nTraceback…" });
  const job = failedBuildJob(g, null, titleOf);
  assert.equal(job.status, "failed");
  assert.equal(job.kind, "generate");
  assert.equal(job.id, "j1");
  assert.equal(job.generation, "g1");
  assert.deepEqual(job.items, ["structured", "visual"]);
  assert.equal(job.template, "t1");
  assert.equal(job.slides, 5);
  assert.equal(job.startedAt, 1_000_000);
  assert.equal(job.endedAt, null); // когда остановилась — неизвестно
  const v = buildView(job, {}, { now: 9_999_999, titleOf });
  assert.equal(v.phase, "failed");
  assert.equal(v.failed?.text, "Сервер перезапускался — сборка прервана. Соберите презентацию ещё раз");
  assert.equal(v.clock, "—");
  // причина не по-русски — подсказка
  assert.equal(buildView(failedBuildJob(meta("g2", { status: "failed", error: "IndexError: list index out of range" }), null, titleOf), {}, { titleOf }).failed?.text, "Измените текст и соберите заново");
  assert.equal(buildView(failedBuildJob(meta("g3", { status: "failed", error: null }), null, titleOf), {}, { titleOf }).failed?.text, "Измените текст и соберите заново");
  // без задачи в мете — свой id, не пустой
  assert.ok(failedBuildJob(meta("g4", { status: "failed" }), null, titleOf).id);
});

test("сборка, упавшая без страницы, когда сервер ещё помнит задачу: лента агента и конец — из записи задачи", () => {
  const ev = (seq: number, step: string, message: string, slide: number | null = null, variant: string | null = null): JobEvent =>
    ({ job_id: "j1", status: "running", progress: 0.4, message, t: seq, type: "agent", step, slide, variant, seq });
  const rec: Job = {
    id: "j1", kind: "generate", status: "failed", progress: 0.42, message: "Модель не ответила", error: "Модель не ответила: сервер модели перегружен",
    created_at: 1000, finished_at: 1086, result: null,
    agent: [
      ev(1, "analyst", "Нашёл в тексте 5 слайдов."),
      ev(2, "designer", "«Итоги квартала» — карточки (4).", 1),
      ev(3, "critic", "Заголовок слишком общий.", 1, "structured"),
    ],
  };
  const g = meta("g1", { status: "failed", job_id: "j1", error: "Модель не ответила: сервер модели перегружен" });
  const job = failedBuildJob(g, rec, titleOf);
  assert.equal(job.endedAt, 1_086_000);
  assert.equal(job.progress, 0.42);
  const v = buildView(job, {}, { titleOf });
  assert.equal(v.failed?.role, "critic"); // где остановилась — по ленте
  assert.equal(v.failed?.text, "Модель не ответила: сервер модели перегружен");
  assert.equal(v.clock, "1:26");
  assert.equal(v.cards[0].state, "critic");
  // запись другой задачи (id не тот) ленту не приносит
  const alien = failedBuildJob(g, { ...rec, id: "j7" }, titleOf);
  assert.equal(alien.agent, undefined);
  assert.equal(alien.endedAt, null);
});
