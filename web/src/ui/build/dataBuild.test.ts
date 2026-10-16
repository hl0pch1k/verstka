import { test } from "node:test";
import assert from "node:assert/strict";
import { foldJobEvent, type ActiveJob } from "../../lib/jobState";
import { PHASES } from "../../lib/agent";
import { STAGE_TITLE } from "../../lib/stage";
import type { JobEvent } from "../../types";
import { buildHasData, buildView, DATA_ROLE, DATA_STAGE, PHASE_ROLL, phaseStep, stageTitle, type BuildPhase } from "./buildView";
import { buildMorph, phaseFit, phaseLines } from "./columns";

// Сборка с файлами данных (вторая ступень): события сервера — как у настоящей сборки примера «данные продаж» без модели
// (SSE /api/jobs/{id}/events): строки шага `data` («Изучаю данные: 7 таблиц», по строке на файл), затем дизайнер.
const start: ActiveJob = {
  id: "j", label: "Собираю презентацию", progress: 0, message: "В очереди…", status: "queued", kind: "generate", startedAt: 0,
  items: ["structured", "visual", "compact"], generation: "g1", slides: 9,
};
let seq = 0;
const agent = (step: string, message: string, slide: number | null = null): JobEvent =>
  ({ job_id: "j", status: "running", progress: 0.04, message, t: seq, type: "agent", step, slide, variant: null, seq: ++seq });
const msg = (message: string, progress = 0.6): JobEvent => ({ job_id: "j", status: "running", progress, message, t: seq });
const fold = (job: ActiveJob, ...evs: JobEvent[]) => evs.reduce((j, ev) => foldJobEvent(j, ev, (n) => n), job);
const plain = (s: string | null | undefined) => (s ?? "").replace(/[  ]/g, " ");
const view = (job: ActiveJob, opts = {}) => buildView(job, {}, { now: 3000, ...opts });

const DATA = [
  agent("data", "Изучаю данные: 7 таблиц"),
  agent("data", "«Итоги квартала.txt» — ключевые значения, карточки ключевых показателей: 4 числа с изменением — каждое крупно, со своим ростом."),
  agent("data", "«Выручка по месяцам.csv» — динамика, линейный график: Дата и одна метрика, 21 точка — тренд виден сразу. Цель «покажи рост выручки»."),
  agent("data", "«Регионы.xlsx» — сравнение категорий, ранжированные горизонтальные столбцы: 8 категорий с длинными названиями."),
];
const DESIGN = [agent("designer", "Обложка «Итоги продаж VK Cloud за 9 месяцев 2026 года»", 1), agent("designer", "«Выручка выросла на 23% к сентябрю» по данным файла — линейный график (21 категория)", 3)];

test("сборка с данными: фаза аналитика — «Изучаю данные», роль — «Аналитик данных» со значком графика и числом файлов", () => {
  const v = view(fold(start, msg("brand: применяю брендбук к шаблону", 0.01), ...DATA));
  assert.equal(v.data, true);
  assert.equal(v.phase, "analyst");
  assert.equal(v.title, DATA_STAGE);
  assert.equal(v.title, "Изучаю данные");
  const r = v.roles[1];
  assert.deepEqual([r.key, r.title, r.hint, r.status, r.data], ["analyst", "Аналитик данных", DATA_ROLE.hint, "now", true]);
  assert.equal(plain(r.note), "· 3 файла");
  // последние мысли — строки о файлах, по порядку
  assert.deepEqual(r.lines.map((l) => plain(l.text).slice(0, 16)), ["«Итоги квартала.", "«Выручка по меся", "«Регионы.xlsx» —"]);
  // автор в сборке с данными не запускался; остальные роли — как в любой сборке
  assert.equal(v.roles[0].status, "skip");
  assert.deepEqual(v.roles.filter((x) => x.key !== "analyst").map((x) => [x.title, x.hint]), PHASES.filter((p) => p.key !== "analyst").map((p) => [p.title, p.hint]));
  assert.equal(v.step, "шаг 2 из 9");
  // дальше — дизайнер; аналитик данных — готово
  const w = view(fold(start, ...DATA, ...DESIGN));
  assert.equal(w.phase, "designer");
  assert.equal(w.title, STAGE_TITLE.designer);
  assert.deepEqual([w.roles[1].title, w.roles[1].status], ["Аналитик данных", "done"]);
});

test("запрос сборки шёл с файлами данных — «Аналитик данных» уже в очереди; без строк шага `data` и без запроса — нет", () => {
  const q = view(start, { data: true });
  assert.equal(q.phase, "queued");
  assert.equal(q.data, true);
  assert.deepEqual([q.roles[1].title, q.roles[1].note], ["Аналитик данных", DATA_ROLE.hint]);
  assert.equal(buildHasData(start), false);
  assert.equal(buildHasData(start, true), true);
  assert.equal(buildHasData(fold(start, DATA[0])), true);
});

test("фаза «Изучаю данные» не проскакивает: анализ без модели — доли секунды, а заголовок показывает её своим шагом", () => {
  assert.equal(phaseStep("queued", "layout", true), "analyst");
  assert.equal(phaseStep("analyst", "layout", true), "layout");
  assert.equal(phaseStep("queued", "analyst", true), "analyst");
  assert.equal(phaseStep("queued", "done", true), "done"); // конец — сразу
  assert.equal(phaseStep("designer", "layout", true), "layout");
  for (const a of PHASE_ROLL) for (const b of PHASE_ROLL) assert.equal(phaseStep(a, b, false), b);
});

test("фаза «Изучаю данные» встаёт в свою клетку и в узкой раскладке (две строки «Изучаю / данные» в тесной колоде)", () => {
  for (const wrap of [1392, 1232, 1217]) {
    const m = buildMorph(wrap);
    const f = phaseFit("analyst", m.font, m.cell, true);
    // видимая ширина — не шире клетки (замер при 36 px: 354.4, длинная из двух строк — 175)
    const w = f.two ? (175 * m.font / 36) * f.scale : (355 * m.font / 36) * f.scale;
    assert.ok(w <= m.cell, `${wrap}: ${w} > ${m.cell}`);
    assert.deepEqual(phaseLines("analyst", true), ["Изучаю", "данные"]);
  }
  assert.equal(stageTitle("analyst", true), "Изучаю данные");
  assert.equal(stageTitle("designer", true), STAGE_TITLE.designer);
});

// ── без данных — как было: те же роли, заголовки, клетки фаз (снимок columns.ts до второй ступени, git HEAD 2026-10-16)
const HEAD_FIT = {
  1392: { font: 36, cell: 344, phases: {
    queued: [0.75, false, 0, 0, 0, "Готовлюсь", "к сборке"],
    writer: [0.75, false, 0, 0, 0, "Пишу текст", "по теме"],
    analyst: [0.75, false, 0, 0, 0, "Читаю", "текст"],
    architect: [0.75, false, 0, 0, 0, "Выстраиваю", "сюжет"],
    designer: [0.7, false, 0, 0, 0, "Продумываю", "слайды"],
    critic: [0.66, false, 0, 0, 0, "Сверяю план", "с текстом"],
    revise: [0.677, false, 0, 0, 0, "Переделываю", "слайды"],
    layout: [0.58, false, 0, 0, 0, "Раскладываю", "по макетам"],
    check: [0.559, false, 0, 0, 0, "Проверяю", "шрифты и цвета"],
    eyes: [0.537, false, 0, 0, 0, "Смотрю на слайды", "целиком"],
    done: [0.75, false, 0, 0, 0, "Презентация", "готова"],
    failed: [0.69, false, 0, 0, 0, "Сборка", "остановилась"],
  } },
  1232: { font: 27.07, cell: 216, phases: {
    queued: [0.665, true, 318.797, 36.093, -12.093, "Готовлюсь", "к сборке"],
    writer: [0.665, true, 318.797, 36.093, -12.093, "Пишу текст", "по теме"],
    analyst: [0.75, false, 0, 0, 0, "Читаю", "текст"],
    architect: [0.665, true, 318.797, 36.093, -12.093, "Выстраиваю", "сюжет"],
    designer: [0.665, true, 318.797, 36.093, -12.093, "Продумываю", "слайды"],
    critic: [0.665, true, 318.797, 36.093, -12.093, "Сверяю план", "с текстом"],
    revise: [0.665, true, 318.797, 36.093, -12.093, "Переделываю", "слайды"],
    layout: [0.665, true, 318.797, 36.093, -12.093, "Раскладываю", "по макетам"],
    check: [0.665, true, 318.797, 36.093, -12.093, "Проверяю", "шрифты и цвета"],
    eyes: [0.665, true, 324.812, 36.093, -12.093, "Смотрю на слайды", "целиком"],
    done: [0.665, true, 318.797, 36.093, -12.093, "Презентация", "готова"],
    failed: [0.665, true, 318.797, 36.093, -12.093, "Сборка", "остановилась"],
  } },
  1217: { font: 26.21, cell: 201, phases: {
    queued: [0.687, true, 286.754, 34.947, -10.947, "Готовлюсь", "к сборке"],
    writer: [0.687, true, 286.754, 34.947, -10.947, "Пишу текст", "по теме"],
    analyst: [0.75, false, 0, 0, 0, "Читаю", "текст"],
    architect: [0.687, true, 286.754, 34.947, -10.947, "Выстраиваю", "сюжет"],
    designer: [0.687, true, 286.754, 34.947, -10.947, "Продумываю", "слайды"],
    critic: [0.687, true, 286.754, 34.947, -10.947, "Сверяю план", "с текстом"],
    revise: [0.687, true, 286.754, 34.947, -10.947, "Переделываю", "слайды"],
    layout: [0.687, true, 286.754, 34.947, -10.947, "Раскладываю", "по макетам"],
    check: [0.687, true, 286.754, 34.947, -10.947, "Проверяю", "шрифты и цвета"],
    eyes: [0.643, true, 312.597, 34.947, -10.947, "Смотрю на слайды", "целиком"],
    done: [0.687, true, 286.754, 34.947, -10.947, "Презентация", "готова"],
    failed: [0.687, true, 286.754, 34.947, -10.947, "Сборка", "остановилась"],
  } },
};

test("без данных экран «Сборка» — как до второй ступени: роли, подсказки, заголовки фаз и их клетки те же", () => {
  const ANALYST = agent("analyst", "Нашёл в тексте 11 слайдов, 7 формул.");
  for (const job of [start, fold(start, ANALYST), fold(start, ANALYST, ...DESIGN), fold(start, msg("analyze: loaded cached manifest", 0.03))]) {
    const v = view(job);
    assert.equal(v.data, false);
    assert.deepEqual(v.roles.map((r) => [r.key, r.title, r.hint]), PHASES.map((p) => [p.key, p.title, p.hint]));
    assert.ok(v.roles.every((r) => r.data === undefined));
    assert.equal(v.title, STAGE_TITLE[v.phase]);
    assert.deepEqual(view(job, { data: false }), v);
  }
  for (const [wrap, snap] of Object.entries(HEAD_FIT)) {
    const m = buildMorph(Number(wrap));
    assert.deepEqual([m.font, m.cell], [snap.font, snap.cell]);
    for (const [p, s] of Object.entries(snap.phases)) {
      const f = phaseFit(p as BuildPhase, m.font, m.cell);
      const [l1, l2] = phaseLines(p as BuildPhase);
      assert.deepEqual([f.scale, f.two, f.width, f.line, f.top, plain(l1), plain(l2)], s, `${wrap}: ${p}`);
      assert.deepEqual(phaseFit(p as BuildPhase, m.font, m.cell, false), f);
      assert.equal(stageTitle(p as BuildPhase), STAGE_TITLE[p as BuildPhase]);
    }
  }
});
