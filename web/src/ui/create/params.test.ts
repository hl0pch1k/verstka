import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildRequest, buildRunning, chosenStrategies, eyesOn, OWN, PARAMS0, picturesOn, presetParams, readParams, slidesView, slideWord,
  START_FAILED, startFailure, stepSlides, summaryLine, toggleEyes, togglePictures, toggleStrategy, variantCards, type Params,
} from "./params";
import type { ActiveJob } from "../../lib/jobState";
import type { ImproveSource, StrategyInfo } from "../../types";

const S: StrategyInfo[] = [
  { name: "structured", title: "Структурный", description: "…" },
  { name: "visual", title: "Визуальный", description: "…" },
  { name: "compact", title: "Компактный", description: "…" },
];
const P = (patch: Partial<Params> = {}): Params => ({ ...PARAMS0, ...patch });
const req = (patch: Partial<Parameters<typeof buildRequest>[0]> = {}) =>
  buildRequest({ templateId: "t1", brief: "  История VK  ", params: P(), strategies: S, modelOn: true, images: IMG, improve: null, ...patch });
/** Модель изображений: ключ есть, сервер по умолчанию их генерирует. */
const IMG = { configured: true, enabled: true };

test("черновик: по умолчанию — 12 слайдов, все варианты, модель пишет; взгляд и изображения — как решат модель и сервер", () => {
  assert.deepEqual(readParams(undefined), PARAMS0);
  assert.deepEqual(PARAMS0, { slides: null, strategies: [], audience: "", purpose: "product", ownPurpose: "", useModels: true, eyes: null, pictures: null });
  // выбор человека из черновика остаётся, не тронутое — null
  assert.deepEqual([readParams({ eyes: false, pictures: true }).eyes, readParams({ eyes: false, pictures: true }).pictures], [false, true]);
  assert.deepEqual([readParams({}).eyes, readParams({}).pictures], [null, null]);
});
test("черновик: испорченные поля заменяются значениями по умолчанию, годные остаются", () => {
  const p = readParams({ slides: 99, strategies: ["visual", 3], audience: 7, purpose: "что-то", ownPurpose: "лекция", useModels: false, eyes: "да", pictures: false });
  assert.deepEqual(p, { ...PARAMS0, slides: null, strategies: [], ownPurpose: "лекция", useModels: false, pictures: false });
  assert.equal(readParams({ slides: 8, purpose: OWN }).slides, 8);
  assert.equal(readParams({ purpose: OWN }).purpose, OWN);
  assert.equal(readParams({ purpose: "report" }).purpose, "report");
  assert.deepEqual(readParams({ strategies: ["visual", "compact"] }).strategies, ["visual", "compact"]);
  assert.deepEqual(readParams([1, 2]), PARAMS0);
});

test("слайды: степпер 5–20, по умолчанию 12", () => {
  assert.deepEqual(slidesView(null, null), { count: 12, locked: false, dec: true, inc: true });
  assert.deepEqual(slidesView(5, null), { count: 5, locked: false, dec: false, inc: true });
  assert.deepEqual(slidesView(20, null), { count: 20, locked: false, dec: true, inc: false });
  assert.equal(stepSlides(null, 1), 13);
  assert.equal(stepSlides(5, -1), 5);
  assert.equal(stepSlides(20, 1), 20);
});
test("слайды заданы в тексте: число из текста, степпер заблокирован", () => {
  assert.deepEqual(slidesView(9, 6), { count: 6, locked: true, dec: false, inc: false });
  assert.deepEqual(slidesView(null, 25), { count: 25, locked: true, dec: false, inc: false });
});
test("подпись под числом", () => {
  assert.equal(slideWord(12), "слайдов");
  assert.equal(slideWord(21), "слайд");
  assert.equal(slideWord(3), "слайда");
});

test("варианты: пусто — выбраны все, порядок сервера", () => {
  assert.deepEqual(chosenStrategies(S, []), ["structured", "visual", "compact"]);
  assert.deepEqual(chosenStrategies(S, ["compact", "structured"]), ["structured", "compact"]);
  // выбор, которого у сервера больше нет, — все
  assert.deepEqual(chosenStrategies(S, ["gone"]), ["structured", "visual", "compact"]);
  // сервер ещё не ответил — что выбрано
  assert.deepEqual(chosenStrategies([], ["visual"]), ["visual"]);
});
test("варианты: последний выбранный не снимается", () => {
  assert.deepEqual(toggleStrategy(S, [], "visual"), ["structured", "compact"]);
  assert.deepEqual(toggleStrategy(S, ["structured", "compact"], "visual"), ["structured", "visual", "compact"]);
  assert.equal(toggleStrategy(S, ["visual"], "visual"), null);
});
test("карточки вариантов: тексты V2 для трёх известных, у неизвестного — описание сервера", () => {
  const cards = variantCards(S, ["visual"]);
  assert.deepEqual(cards.map((c) => [c.title, c.desc, c.hint, c.thumb, c.on]), [
    ["Структурный", "Схемы и списки", "Одна мысль на слайд, по порядку", "s", false],
    ["Визуальный", "Крупные изображения", "Крупные цифры и диаграммы", "v", true],
    ["Компактный", "Плотная вёрстка", "Плотные композиции: колонки и таблицы", "c", false],
  ]);
  assert.equal(cards[1].full, "Визуальный — Крупные цифры и диаграммы");
  const other = variantCards([{ name: "x", title: "Новый", description: "Своё описание" }], []);
  assert.deepEqual([other[0].desc, other[0].hint, other[0].on], ["Своё описание", "Своё описание", true]);
  // сервер ещё не ответил — три известных варианта
  assert.deepEqual(variantCards([], []).map((c) => c.name), ["structured", "visual", "compact"]);
});

test("сводка: шаблон · слайды · варианты", () => {
  assert.equal(summaryLine("VK Tech", 12, 3), "VK Tech · 12 слайдов · 3 варианта");
  assert.equal(summaryLine(null, 1, 1), "1 слайд · 1 вариант");
});

test("запрос: поля как в старом CreateScreen; взгляд дизайнера с моделью включён, проверки моделью — как в 3.0, выключены", () => {
  assert.deepEqual(req(), {
    template_id: "t1", brief: "История VK", audience: null, purpose: "product", slides: 12,
    strategies: ["structured", "visual", "compact"], use_models: true, audit_models: false, eyes: true, pictures: true,
    autofix: true, exports: ["pdf", "html"], improved_from: undefined,
  });
});
test("запрос: аудитория, свой тип презентации, выбранные варианты", () => {
  const r = req({ params: P({ audience: "  Совет директоров ", purpose: OWN, ownPurpose: " лекция для студентов ", strategies: ["visual"], slides: 8 }) });
  assert.equal(r.audience, "Совет директоров");
  assert.equal(r.purpose, "лекция для студентов");
  assert.deepEqual(r.strategies, ["visual"]);
  assert.equal(r.slides, 8);
  assert.equal(req({ params: P({ purpose: OWN, ownPurpose: "  " }) }).purpose, null);
});
test("запрос: «Модель проверяет слайды по картинке» — только взгляд дизайнера (`eyes`), не `audit_models`", () => {
  // человек выключил — выключен; включил при выключенной «Модель пишет тексты» — включён
  assert.deepEqual([req({ params: P({ eyes: false }) }).eyes, req({ params: P({ eyes: false }) }).audit_models], [false, false]);
  assert.deepEqual([req({ params: P({ eyes: true, useModels: false }) }).eyes, req({ params: P({ eyes: true }) }).audit_models], [true, false]);
  // не трогал — как модель: модель не пишет тексты — и не смотрит
  assert.equal(req({ params: P({ useModels: false }) }).eyes, false);
});
test("запрос: без модели переключатели модели выключены; без модели изображений — решает сервер", () => {
  const r = req({ params: P({ eyes: true }), modelOn: false, images: { configured: false, enabled: true } });
  assert.equal(r.use_models, false);
  assert.equal(r.audit_models, false);
  assert.equal(r.eyes, false);
  assert.equal(req({ modelOn: false }).eyes, false);
  assert.equal(r.pictures, null);
  assert.equal(req({ params: P({ pictures: false, useModels: false }) }).pictures, false);
  assert.equal(req({ params: P({ useModels: false }) }).use_models, false);
});
test("запрос: изображения по умолчанию — как у сервера (`health.images.enabled`)", () => {
  assert.equal(req({ images: { configured: true, enabled: false } }).pictures, false);
  assert.equal(req({ images: { configured: true, enabled: true } }).pictures, true);
  // выбор человека сильнее
  assert.equal(req({ params: P({ pictures: true }), images: { configured: true, enabled: false } }).pictures, true);
});
test("запрос: «/api/strategies» ещё не ответил — варианты как у карточек (три известных), а не пустой список", () => {
  assert.deepEqual(req({ strategies: [] }).strategies, ["structured", "visual", "compact"]);
  assert.deepEqual(req({ strategies: [], params: P({ strategies: ["visual"] }) }).strategies, ["visual"]);
});
test("запрос: число слайдов из текста — заголовками отправляется, фразой — решает сервер", () => {
  const heads = "Слайд 1. Итоги квартала\nВыручка 10 млн\nСлайд 2. Планы\nРост 20%\nСлайд 3. Риски\nКонкуренты";
  assert.equal(req({ brief: heads, params: P({ slides: 15 }) }).slides, 4);
  assert.equal(req({ brief: "Сделай 7 слайдов про историю VK", params: P({ slides: 15 }) }).slides, null);
});
test("запрос: «Улучшить готовую» — исходная презентация и взгляд модели на каждый новый слайд", () => {
  const src: ImproveSource = { brief: "x", name: "Итоги.pptx", template_id: "src", slides: 14, tables: 1, charts: 0, pictures: 2, audit: { score: 62, errors: 3, warnings: 5 } };
  const r = req({ improve: src });
  assert.deepEqual(r.improved_from, { name: "Итоги.pptx", slides: 14, template_id: "src", audit: { score: 62, errors: 3, warnings: 5 } });
  assert.equal(r.eyes, true);
  assert.equal(r.audit_models, false);
  // переключатель выключен — в «Улучшить готовую» модель всё равно смотрит
  assert.equal(req({ improve: src, params: P({ eyes: false, useModels: false }) }).eyes, true);
  assert.equal(req({ improve: src, modelOn: false }).eyes, false);
});

test("взгляд дизайнера: по умолчанию включён с моделью, которая пишет тексты; без модели выключен", () => {
  assert.equal(eyesOn(P(), true), true);
  assert.equal(eyesOn(P(), false), false);
  assert.equal(eyesOn(P({ useModels: false }), true), false);
  // выбор человека — без модели всё равно выключен
  assert.equal(eyesOn(P({ eyes: true }), false), false);
});
test("взгляд дизайнера: выбор человека держится — и при смене «Модель пишет тексты», и после черновика", () => {
  const off = toggleEyes(P(), true);
  assert.equal(off.eyes, false);
  assert.equal(eyesOn(off, true), false);
  assert.equal(eyesOn({ ...off, useModels: false }, true), false);
  assert.equal(eyesOn({ ...off, useModels: true }, true), false);
  assert.equal(eyesOn(readParams(JSON.parse(JSON.stringify(off))), true), false);
  // включил при выключенной «Модель пишет тексты» — включён
  const on = toggleEyes(P({ useModels: false }), true);
  assert.deepEqual([on.eyes, eyesOn(on, true)], [true, true]);
  assert.equal(eyesOn(toggleEyes(on, true), true), false);
});
test("изображения: по умолчанию — как у сервера; выбор человека держится; без модели изображений — выключены", () => {
  assert.equal(picturesOn(P(), { configured: true, enabled: true }), true);
  assert.equal(picturesOn(P(), { configured: true, enabled: false }), false);
  assert.equal(picturesOn(P({ pictures: true }), { configured: false, enabled: true }), false);
  const off = togglePictures(P(), { configured: true, enabled: true });
  assert.deepEqual([off.pictures, picturesOn(off, { configured: true, enabled: true })], [false, false]);
  const on = togglePictures(P(), { configured: true, enabled: false });
  assert.deepEqual([on.pictures, picturesOn(on, { configured: true, enabled: false })], [true, true]);
});

const job = (patch: Partial<ActiveJob>): ActiveJob => ({ id: "j", label: "", progress: 0, message: "", status: "running", kind: "generate", startedAt: 0, ...patch });
test("сборка уже идёт: только задача generate в очереди или в работе", () => {
  assert.equal(buildRunning(null), false);
  assert.equal(buildRunning(job({})), true);
  assert.equal(buildRunning(job({ status: "queued" })), true);
  assert.equal(buildRunning(job({ status: "done" })), false);
  assert.equal(buildRunning(job({ status: "failed" })), false);
  assert.equal(buildRunning(job({ kind: "analyze" })), false);
  assert.equal(buildRunning(job({ kind: "slide_fix" })), false);
});
test("неудача запуска: только ответ на это нажатие, а не строка прежней сборки или прежнего нажатия", () => {
  const at = 1000;
  const n = (text: string, t = at + 5, kind: "error" | "success" = "error") => ({ kind, text, at: t });
  assert.equal(startFailure(n("Не удалось начать сборку презентации: Текст презентации пуст"), at), "Текст презентации пуст");
  assert.equal(startFailure(n("Не удалось начать сборку презентации: Internal Server Error"), at), START_FAILED);
  // строка прежней сборки («Не получилось: …») — не неудача запуска, даже если пришла после нажатия
  assert.equal(startFailure(n("Не получилось: модель не ответила"), at), null);
  // прежнее нажатие, не ошибка, нажатия нет, строки нет
  assert.equal(startFailure(n("Не удалось начать сборку презентации: Сеть недоступна", at - 1), at), null);
  assert.equal(startFailure(n("Не удалось начать сборку презентации: x", at + 5, "success"), at), null);
  assert.equal(startFailure(n("Не удалось начать сборку презентации: Сеть недоступна"), null), null);
  assert.equal(startFailure(undefined, at), null);
});

test("параметры презентации («Изменить текст»): аудитория, тип, слайды, модель, варианты", () => {
  const p = presetParams(P({ audience: "старая" }), { audience: null, purpose: "report", slides: 30, useModels: false, auditModels: true, pictures: false, strategies: ["compact"] });
  assert.deepEqual(p, { ...PARAMS0, audience: "", purpose: "report", slides: 20, useModels: false, eyes: true, pictures: false, strategies: ["compact"] });
  const own = presetParams(P(), { purpose: "лекция для студентов" });
  assert.deepEqual([own.purpose, own.ownPurpose], [OWN, "лекция для студентов"]);
  // переключатели, которых в параметрах нет, — остаются
  const kept = presetParams(P({ useModels: false, eyes: true, pictures: false }), {});
  assert.deepEqual([kept.useModels, kept.eyes, kept.pictures], [false, true, false]);
});
test("параметры презентации: слайдов и вариантов нет — степпер «по тексту» (null) и все варианты, а не черновик", () => {
  const p = presetParams(P({ slides: 9, strategies: ["visual"] }), { slides: null });
  assert.deepEqual([p.slides, p.strategies], [null, []]);
  const q = presetParams(P({ slides: 9, strategies: ["visual"] }), { strategies: [] });
  assert.deepEqual([q.slides, q.strategies], [null, []]);
});
test("параметры презентации: изображения null — как решит сервер (null), а не «включены»", () => {
  assert.equal(presetParams(P({ pictures: false }), { pictures: null }).pictures, null);
  assert.equal(presetParams(P(), { pictures: true }).pictures, true);
});
test("параметры презентации: взгляд — `eyes`, у старых презентаций — `auditModels`; `eyes` сильнее", () => {
  assert.equal(presetParams(P(), { eyes: false, auditModels: true }).eyes, false);
  assert.equal(presetParams(P(), { eyes: true, auditModels: false }).eyes, true);
  assert.equal(presetParams(P(), { auditModels: true }).eyes, true);
  assert.equal(presetParams(P(), { eyes: null, auditModels: false }).eyes, false);
  assert.equal(presetParams(P({ eyes: true }), {}).eyes, true);
});
test("параметры презентации: взгляд null без `auditModels` — «как модель» (null), а не прежний выбор", () => {
  assert.equal(presetParams(P({ eyes: false }), { eyes: null }).eyes, null);
  assert.equal(presetParams(P({ eyes: false }), {}).eyes, false);
});
