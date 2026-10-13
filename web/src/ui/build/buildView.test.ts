import { test } from "node:test";
import assert from "node:assert/strict";
import { foldJobEvent, type ActiveJob } from "../../lib/jobState";
import { PHASES } from "../../lib/agent";
import { STAGE_TITLE } from "../../lib/stage";
import type { JobEvent } from "../../types";
import { buildView } from "./buildView";

// Задача сборки так, как её видит экран: события агента и сообщения конвейера сворачиваются тем же foldJobEvent, что и
// живой поток (store.runJob), — экран строится из того же ActiveJob.
const start: ActiveJob = {
  id: "j", label: "Собираю презентацию", progress: 0, message: "В очереди…", status: "queued", kind: "generate", startedAt: 0,
  items: ["structured", "visual"], generation: "g1", slides: 12,
};
const titleOf = (n: string) => ({ structured: "Структурный", visual: "Визуальный" })[n] ?? n;
let seq = 0;
const agent = (step: string, message: string, slide: number | null = null, variant: string | null = null, fix: string | null = null): JobEvent =>
  ({ job_id: "j", status: "running", progress: 0.3, message, t: seq, type: "agent", step, slide, variant, seq: ++seq, fix });
const msg = (message: string, progress = 0.6): JobEvent => ({ job_id: "j", status: "running", progress, message, t: seq });
const fold = (job: ActiveJob, ...evs: JobEvent[]) => evs.reduce((j, ev) => foldJobEvent(j, ev, titleOf), job);
// строки агента держат предлоги и числа неразрывным пробелом (lib/agent keepTogether): сравниваем по словам
const plain = (s: string | null | undefined) => (s ?? "").replace(/\u00a0/g, " ");
const view = (job: ActiveJob, previews: Record<string, string[]> = {}, opts = {}) => buildView(job, previews, { now: 3000, titleOf, ...opts });

// Реальные строки записанной сборки (workspace/runs/20261008-222500-2fc8ac/agent.json), сокращённо
const ANALYST = agent("analyst", "Нашёл в тексте 11 слайдов, 7 формул.");
const DESIGN3 = agent("designer", "«Предел определяет непрерывность, производную, интеграл и ряды» — карточки (4).", 3);
const DESIGN2 = agent("designer", "«Строгое определение предела появилось» — хронология (5).", 2);
const CRITIC3 = agent("critic", "Заголовок «Предел определяет непрерывность, производную, интеграл и ряды» является перечислением тем.", 3, "structured", "Заменить заголовок на «Предел — база анализа»");
const REVISE3 = agent("revise", "Карточки (4).", 3, "structured");

test("до событий — подготовка: заголовок очереди, все роли впереди, заглушки без номеров", () => {
  const v = view(start);
  assert.equal(v.phase, "queued");
  assert.equal(v.title, STAGE_TITLE.queued);
  assert.equal(v.clock, "0:03");
  assert.equal(v.progress, null); // прогресса нет — бежит отрезок
  assert.equal(v.step, "в очереди");
  assert.equal(v.roles.length, 9);
  assert.deepEqual(v.roles.map((r) => r.key), PHASES.map((p) => p.key));
  assert.ok(v.roles.every((r) => r.status === "queue"));
  assert.equal(v.roles[1].note, PHASES[1].hint); // впереди — подсказка роли
  assert.equal(v.planned, false);
  assert.equal(v.board, "план ещё не готов");
  assert.equal(v.cards.length, 12); // спросили 12 слайдов
  assert.ok(v.cards.every((c) => c.state === "empty" && !c.focus));
  assert.equal(v.failed, null);
  assert.equal(view({ ...start, slides: null }).cards.length, 10); // число неизвестно — десять заглушек
  assert.deepEqual(v.variants.map((x) => [x.name, x.status]), [["structured", null], ["visual", null]]);
});

test("дизайнер продумал слайд 3 — карточка 3 «эскиз», роль дизайнера «сейчас»", () => {
  const v = view(fold(start, ANALYST, DESIGN3));
  assert.equal(v.phase, "designer");
  assert.equal(v.title, STAGE_TITLE.designer);
  assert.equal(v.cards[2].state, "sketch");
  assert.equal(v.cards[2].kind, "cards");
  assert.equal(v.cards[2].form, "Карточки");
  assert.equal(plain(v.cards[2].title), "Предел определяет непрерывность, производную, интеграл и ряды");
  assert.equal(v.cards[1].state, "empty");
  assert.equal(v.cards[2].focus, true); // о нём сейчас говорит агент
  assert.equal(v.planned, true);
  assert.equal(v.board, "продумано 1 из 12");
  const st = Object.fromEntries(v.roles.map((r) => [r.key, r.status]));
  assert.deepEqual(st, { writer: "skip", analyst: "done", architect: "skip", designer: "now", critic: "queue", revise: "queue", layout: "queue", check: "queue", eyes: "queue" });
  assert.equal(v.roles[0].note, "в этой сборке не запускался");
  assert.equal(v.step, "шаг 4 из 9");
  assert.ok(v.progress !== null && v.progress > 0);
  const designer = v.roles[3];
  assert.equal(designer.note, "· 1 слайд");
  assert.deepEqual(designer.lines.map((l) => l.slide), [3]);
  assert.deepEqual(v.variants.map((x) => x.status), ["продумываю", "продумываю"]);
});

test("критик оставил замечание к слайду 3 — «замечание», правка — «переделан»", () => {
  const critic = view(fold(start, ANALYST, DESIGN2, DESIGN3, CRITIC3));
  assert.equal(critic.phase, "critic");
  assert.equal(critic.cards[2].state, "critic");
  assert.equal(critic.cards[1].state, "sketch");
  assert.equal(critic.cards[2].focus, true);
  const role = critic.roles.find((r) => r.key === "critic");
  assert.equal(role?.status, "now");
  assert.equal(role?.note, "· 1 замечание · слайд 3");
  assert.equal(role?.lines[0].slide, 3);
  assert.equal(plain(role?.lines[0].fix), "Заменить заголовок на «Предел — база анализа»");
  // замечание — вариант «Структурный»; у «Визуального» своего замечания нет
  assert.equal(view(fold(start, ANALYST, DESIGN3, CRITIC3), {}, { variant: "visual" }).cards[2].state, "sketch");

  const revised = view(fold(start, ANALYST, DESIGN2, DESIGN3, CRITIC3, REVISE3));
  assert.equal(revised.cards[2].state, "revised");
  assert.equal(revised.roles.find((r) => r.key === "revise")?.status, "now");
  assert.equal(revised.roles.find((r) => r.key === "critic")?.status, "done");
});

test("вёрстка: сверстанные слайды, слайд в работе, превью по мере готовности", () => {
  const job = fold(start, ANALYST, DESIGN2, DESIGN3, msg("structured: planned 12 slides, rendering"), msg("structured: rendered slide 2/12"));
  const v = view(job, { structured: ["/api/generations/g1/structured/slides/slide-001.jpg"] });
  assert.equal(v.phase, "layout");
  assert.equal(v.cards[0].state, "done");
  assert.equal(v.cards[0].preview, "/api/generations/g1/structured/slides/slide-001.jpg");
  assert.equal(v.cards[1].state, "laid");
  assert.equal(v.cards[2].state, "sketch");
  assert.equal(v.cards[2].focus && v.cards[2].work, true); // верстается сейчас
  assert.equal(v.board, "сверстано 2 из 12");
  assert.deepEqual(v.variants.map((x) => x.status), ["верстаю", "верстаю"]);
  assert.equal(v.roles.find((r) => r.key === "layout")?.note, "· Структурный · 2 из 12");
  // проверка первого варианта, пока второй ещё верстается, — всё ещё «Вёрстка»
  const later = fold(job, msg("structured: audit", 0.7));
  assert.equal(view(later).phase, "layout");
  assert.equal(view(later).variants[0].status, "сверстано");
  assert.equal(view(later).variants[0].done, true);
});

test("неудача — роль с ошибкой та, что работала последней; дальше «не запускалась»", () => {
  const running = fold(start, ANALYST, DESIGN3, CRITIC3);
  const failed: ActiveJob = { ...running, status: "failed", message: "Модель не ответила: сервер модели перегружен", endedAt: 86_000 };
  const v = view(failed, {}, { now: 999_000 });
  assert.equal(v.phase, "failed");
  assert.equal(v.title, "Сборка остановилась");
  assert.equal(v.clock, "1:26"); // часы стоят на конце сборки
  assert.deepEqual(v.failed, { role: "critic", text: "Модель не ответила: сервер модели перегружен" });
  const st = Object.fromEntries(v.roles.map((r) => [r.key, r.status]));
  assert.deepEqual(st, { writer: "skip", analyst: "done", architect: "skip", designer: "done", critic: "error", revise: "skip", layout: "skip", check: "skip", eyes: "skip" });
  assert.equal(v.roles.find((r) => r.key === "revise")?.note, "в этой сборке не запускалась");
  assert.equal(v.roles.find((r) => r.key === "eyes")?.note, "в этой сборке не запускался");
  assert.equal(v.step, "ошибка на шаге 5 из 9");
  assert.ok(v.cards.every((c) => !c.focus));
  // строка области «Сборка» сильнее сообщения задачи; технический хвост — простыми словами
  assert.equal(view(failed, {}, { error: "Не получилось: list index out of range" }).failed?.text, "Измените текст и соберите заново");
  assert.equal(view(failed, {}, { error: "Не получилось: Сервер перезапускался — работа прервана, запустите её ещё раз" }).failed?.text,
    "Сервер перезапускался — работа прервана, запустите её ещё раз");
  // «Собрать ещё раз» не приняли: причина сервера по-русски — она, иначе — «не удалось начать» (как у запуска на «Создать»)
  assert.equal(view(failed, {}, { error: "Не удалось начать сборку презентации: Сеть недоступна" }).failed?.text, "Сеть недоступна");
  assert.equal(view(failed, {}, { error: "Не удалось начать сборку презентации: Internal Server Error" }).failed?.text, "Не удалось начать сборку — попробуйте ещё раз");
  // упала до первого шага — ошибка у аналитика
  assert.equal(view({ ...start, status: "failed", message: "Шаблон ещё не разобран — загрузите его снова" }).failed?.role, "analyst");
});

test("готово — все пройденные роли готовы, не запускавшиеся — пропущены", () => {
  const job = fold(start, ANALYST, DESIGN3, msg("structured: planned 3 slides, rendering"), msg("structured: rendered slide 3/3"), msg("export: pdf, html, slide previews", 0.86));
  const v = view({ ...job, status: "done", progress: 1, message: "Готово", endedAt: 61_000 });
  assert.equal(v.phase, "done");
  assert.equal(v.title, "Презентация готова");
  assert.equal(v.step, "9 из 9 готово");
  assert.equal(v.progress, 1);
  assert.equal(v.clock, "1:01");
  assert.ok(v.roles.every((r) => r.status === "done" || r.status === "skip"));
  assert.equal(v.roles.find((r) => r.key === "eyes")?.status, "skip");
  assert.equal(v.failed, null);
});

test("тема: шаблон разбирается раньше, чем автор пишет текст, — сейчас работает автор, а не аналитик", () => {
  const job = fold(start, msg("analyze: loaded cached manifest", 0.03), msg("plan: 2 variants", 0.15),
    agent("writer", "Ищу материалы по теме «Пределы»."), agent("writer", "Нашёл статью «Предел (математика)» в Википедии."));
  const v = view(job);
  assert.equal(v.phase, "writer");
  assert.equal(v.title, STAGE_TITLE.writer);
  assert.equal(v.roles[0].status, "now");
  assert.equal(v.roles[1].status, "queue");
  assert.equal(v.step, "шаг 1 из 9");
  // аналитик заговорил — его очередь
  assert.equal(view(fold(job, ANALYST)).phase, "analyst");
});
