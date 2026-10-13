import { test } from "node:test";
import assert from "node:assert/strict";
import type { GenerationMeta } from "../../types";
import { bestScore, coverSrc, coverStrategy, dayBucket, deckState, deckTitle, historyView, openPlan, slidesText } from "./history";

// «сейчас» — 13 октября 2026, полдень по местному времени; отметки — unix-секунды местного времени
const NOW = new Date(2026, 9, 13, 12, 0);
const at = (d: number, h = 10, m = 0, month = 9, year = 2026) => new Date(year, month, d, h, m).getTime() / 1000;
const meta = (id: string, patch: Partial<GenerationMeta> = {}): GenerationMeta =>
  ({ id, template_id: "t1", template_file: "VK_Tech.pptx", strategies: ["structured", "visual"], created_at: at(13), status: "done", ...patch });
const label = (g: GenerationMeta) => (g.template_id === "t1" ? "VK Tech" : "Кофейня");

test("состояние: идущая и в очереди — «собирается», упавшая — «не удалось», остальное (и старые без статуса) — готовая", () => {
  assert.equal(deckState(meta("a", { status: "running" })), "run");
  assert.equal(deckState(meta("a", { status: "queued" })), "run");
  assert.equal(deckState(meta("a", { status: "failed" })), "fail");
  assert.equal(deckState(meta("a", { status: "done" })), "done");
  assert.equal(deckState(meta("a", { status: undefined })), "done");
});

test("оценка — лучшая среди вариантов; каркас темы без текста оценки не имеет", () => {
  assert.equal(bestScore(meta("a", { summary: { structured: { score: 84 }, visual: { score: 89.4 } } })), 89.4);
  assert.equal(bestScore(meta("a", { summary: { structured: { score: null } } })), null);
  assert.equal(bestScore(meta("a")), null);
  const skeleton = meta("a", { writer: { mode: "topic", status: "failed" }, planner: { planned_by: "skeleton" } as GenerationMeta["planner"], summary: { structured: { score: 100 } } });
  assert.equal(bestScore(skeleton), null);
});

test("обложка — первый слайд лучшего варианта; без оценок — первый вариант со слайдами", () => {
  assert.equal(coverStrategy(meta("a", { summary: { structured: { score: 84, n_slides: 12 }, visual: { score: 89, n_slides: 12 } } })), "visual");
  // равные оценки — по порядку вариантов
  assert.equal(coverStrategy(meta("a", { summary: { structured: { score: 89, n_slides: 12 }, visual: { score: 89, n_slides: 12 } } })), "structured");
  // вариант без слайдов обложкой не бывает
  assert.equal(coverStrategy(meta("a", { summary: { structured: { score: 95, n_slides: 0 }, visual: { score: 70, n_slides: 9 } } })), "visual");
  assert.equal(coverStrategy(meta("a")), "structured");
  assert.equal(coverStrategy(meta("a", { strategies: [] })), null);
  assert.equal(coverStrategy(meta("a", { summary: { structured: { n_slides: 0 }, visual: { n_slides: 0 } } })), null);
});

test("адрес обложки: только у готовой, первый слайд лучшего варианта, с ревизией по сводке", () => {
  const g = meta("20261008-1", { summary: { structured: { score: 84, n_slides: 12 }, visual: { score: 89, n_slides: 11, errors: 0, warnings: 2 } } });
  assert.equal(coverSrc(g), "/api/generations/20261008-1/visual/slides/slide-001.jpg?v=890.11.0.2");
  assert.equal(coverSrc(meta("a", { status: "running" })), null);
  assert.equal(coverSrc(meta("a", { status: "failed" })), null);
  assert.equal(coverSrc(meta("a", { strategies: [] })), null);
  // без сводки — без ревизии
  assert.equal(coverSrc(meta("a b")), "/api/generations/a%20b/structured/slides/slide-001.jpg");
});

test("число слайдов: собранные варианты (диапазон, если разные), иначе — сколько просили", () => {
  assert.equal(slidesText(meta("a", { summary: { structured: { n_slides: 12 }, visual: { n_slides: 12 } } })), "12 слайдов");
  assert.equal(slidesText(meta("a", { summary: { structured: { n_slides: 8 }, visual: { n_slides: 10 } } })), "8–10 слайдов");
  assert.equal(slidesText(meta("a", { slides: 3 })), "3 слайда");
  assert.equal(slidesText(meta("a")), null);
});

test("название: своё, иначе первая строка текста без разметки, иначе имя шаблона", () => {
  assert.equal(deckTitle(meta("a", { title: "  Интеграл " })), "Интеграл");
  assert.equal(deckTitle(meta("a", { title: null, brief: "\n# **Итоги квартала**\nСлайд 1." })), "Итоги квартала");
  assert.equal(deckTitle(meta("a", { title: "", brief: "" })), "VK Tech");
});

test("день: сегодня, вчера, дата в пределах недели, раньше — одна группа", () => {
  assert.deepEqual(dayBucket(at(13, 9), NOW), { key: "0", label: "Сегодня", early: false });
  assert.deepEqual(dayBucket(at(12, 23), NOW), { key: "1", label: "Вчера", early: false });
  assert.deepEqual(dayBucket(at(8, 22), NOW), { key: "5", label: "8 окт.", early: false });
  assert.deepEqual(dayBucket(at(7, 22), NOW), { key: "6", label: "7 окт.", early: false });
  assert.deepEqual(dayBucket(at(6, 22), NOW), { key: "early", label: "Раньше", early: true });
  assert.deepEqual(dayBucket(undefined, NOW), { key: "early", label: "Раньше", early: true });
  // часы чуть впереди сервера — всё равно сегодня
  assert.deepEqual(dayBucket(at(13, 13), NOW), { key: "0", label: "Сегодня", early: false });
});

test("список: новые первыми, группы по дням с числом, мета — время (у «Раньше» — дата), шаблон и слайды", () => {
  const list = [
    meta("old", { created_at: at(12, 12, 0, 8), template_id: "t2", summary: { structured: { score: 88, n_slides: 6 } } }),
    meta("int", { created_at: at(13, 17, 38), title: "Интеграл", summary: { structured: { score: 89, n_slides: 12 }, visual: { score: 84, n_slides: 12 } } }),
    meta("ws", { created_at: at(13, 18, 14), status: "running", brief: "Умные сводки в VK WorkSpace", slides: 10 }),
    meta("q", { created_at: at(13, 16, 5), status: "failed", brief: "Итоги квартала", slides: 10 }),
    meta("ww2", { created_at: at(12, 20, 41), title: "Вторая мировая война", summary: { structured: { score: 87, n_slides: 14 } } }),
    meta("old25", { created_at: at(20, 9, 0, 8, 2025), title: "Год назад", summary: { structured: { score: 70, n_slides: 5 } } }),
  ];
  const v = historyView(list, { now: NOW, label, current: "int" });
  assert.equal(v.total, "6 презентаций");
  assert.deepEqual(v.groups.map((g) => [g.day, g.count]), [["Сегодня", "3 презентации"], ["Вчера", "1 презентация"], ["Раньше", "2 презентации"]]);
  const [ws, int, q] = v.groups[0].items;
  assert.deepEqual([ws.id, int.id, q.id], ["ws", "int", "q"]);
  assert.equal(int.meta, "17:38 · VK Tech · 12 слайдов");
  assert.equal(int.score, 89);
  assert.equal(int.state, "done");
  assert.equal(int.current, true);
  assert.equal(int.cover, "/api/generations/int/structured/slides/slide-001.jpg?v=890.12.-.-");
  assert.equal(int.aria, "Интеграл, 17:38 · VK Tech · 12 слайдов, оценка 89 из 100, открыта сейчас");
  // идущая и упавшая: без обложки и без оценки, со своим состоянием в подписи
  assert.equal(ws.state, "run");
  assert.equal(ws.cover, null);
  assert.equal(ws.score, null);
  assert.equal(ws.title, "Умные сводки в VK WorkSpace");
  assert.equal(ws.aria, "Умные сводки в VK WorkSpace, 18:14 · VK Tech · 10 слайдов, собирается");
  assert.equal(q.aria, "Итоги квартала, 16:05 · VK Tech · 10 слайдов, не удалось собрать");
  assert.equal(q.current, false);
  // «Раньше»: вместо времени — дата, у прошлого года — с годом
  const early = v.groups[2].items;
  assert.equal(early[0].meta, "12 сент. · Кофейня · 6 слайдов");
  assert.equal(early[1].meta, "20 сент. 2025 · VK Tech · 5 слайдов");
  // лесенка: 200 мс и шаг 40, дальше девятой карточки не растёт (открытие не ждёт хвост списка)
  assert.deepEqual(v.groups.flatMap((g) => g.items).map((d) => d.delay), [200, 240, 280, 320, 360, 400]);
});

test("лесенка ограничена, список — все презентации, число в шапке — их настоящее число", () => {
  const many = Array.from({ length: 120 }, (_, i) => meta(`g${i}`, { created_at: at(13, 11, 0) - i * 60 }));
  const v = historyView(many, { now: NOW, label, current: null });
  const items = v.groups.flatMap((g) => g.items);
  assert.equal(items.length, 120);
  assert.equal(v.total, "120 презентаций");
  assert.equal(items[0].id, "g0");
  assert.equal(items[119].id, "g119");
  assert.equal(items[8].delay, 520);
  assert.equal(items[119].delay, 520);
  assert.equal(historyView([], { now: NOW, label, current: null }).groups.length, 0);
  assert.equal(historyView([], { now: NOW, label, current: null }).total, "0 презентаций");
});

test("открытие готовой из «Создать»: загрузить, затем плита результата поднимается одним движением с плитами", () => {
  const g = meta("int");
  assert.deepEqual(openPlan(g, { screen: "create", openId: null, buildId: null }), { kind: "result", load: true, rise: true });
  // уже загружена (возврат с результата по логотипу) — без загрузки, сразу
  assert.deepEqual(openPlan(g, { screen: "create", openId: "int", buildId: null }), { kind: "result", load: false, rise: true });
});

test("открытие готовой с результата и со сборки: без подъёма; та же открытая — только закрыть раздел", () => {
  const g = meta("int");
  assert.deepEqual(openPlan(g, { screen: "result", openId: "ww2", buildId: null }), { kind: "result", load: true, rise: false });
  assert.deepEqual(openPlan(g, { screen: "build", openId: "int", buildId: "ws" }), { kind: "result", load: false, rise: false });
  assert.deepEqual(openPlan(g, { screen: "result", openId: "int", buildId: null }), { kind: "stay" });
});

test("идущая — экран сборки с её задачей; уже на её сборке — только закрыть раздел", () => {
  const g = meta("ws", { status: "running", job_id: "j1" });
  assert.deepEqual(openPlan(g, { screen: "create", openId: "int", buildId: null }), { kind: "build" });
  assert.deepEqual(openPlan(g, { screen: "result", openId: "int", buildId: "ws" }), { kind: "build" });
  assert.deepEqual(openPlan(g, { screen: "build", openId: null, buildId: "ws" }), { kind: "stay" });
  assert.deepEqual(openPlan(meta("q2", { status: "queued" }), { screen: "build", openId: null, buildId: "ws" }), { kind: "build" });
});

test("неудачная — «Создать» с той же темой и шаблоном", () => {
  const g = meta("q", { status: "failed" });
  assert.deepEqual(openPlan(g, { screen: "create", openId: null, buildId: null }), { kind: "create" });
  assert.deepEqual(openPlan(g, { screen: "result", openId: "int", buildId: null }), { kind: "create" });
  assert.deepEqual(openPlan(g, { screen: "build", openId: null, buildId: "ws" }), { kind: "create" });
});

test("неудачная сборка, которую держит страница (кончилась, пока человек был в другом месте), — её экран «Сборка»", () => {
  const g = meta("ws", { status: "failed", job_id: "j1" });
  assert.deepEqual(openPlan(g, { screen: "create", openId: null, buildId: "ws" }), { kind: "ended" });
  assert.deepEqual(openPlan(g, { screen: "result", openId: "int", buildId: "ws" }), { kind: "ended" });
  assert.deepEqual(openPlan(g, { screen: "build", openId: null, buildId: "ws" }), { kind: "stay" });
});

test("открытая, но несвежая (изменение сохранено, а перечитать не вышло) — перечитать, а не только закрыть раздел", () => {
  const g = meta("int");
  assert.deepEqual(openPlan(g, { screen: "result", openId: "int", buildId: null, stale: "int" }), { kind: "result", load: true, rise: false });
  assert.deepEqual(openPlan(g, { screen: "create", openId: "int", buildId: null, stale: "int" }), { kind: "result", load: true, rise: true });
  // несвежая другая — эта открыта как есть
  assert.deepEqual(openPlan(g, { screen: "result", openId: "int", buildId: null, stale: "ww2" }), { kind: "stay" });
});

test("неудачная сборка, кончившаяся в другом месте, пока экран вёл другую (R3), — её экран «Сборка», а не «Создать»", () => {
  const g = meta("wa", { status: "failed", job_id: "ja" });
  assert.deepEqual(openPlan(g, { screen: "create", openId: null, buildId: "wb", endedId: "wa" }), { kind: "ended" });
  assert.deepEqual(openPlan(g, { screen: "build", openId: null, buildId: "wb", endedId: "wa" }), { kind: "ended" });
  // другая неудачная — как прежде, «Создать» с её темой
  assert.deepEqual(openPlan(meta("q", { status: "failed" }), { screen: "create", openId: null, buildId: "wb", endedId: "wa" }), { kind: "create" });
});
