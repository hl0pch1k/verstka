import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildRequest, chosenStrategies, OWN, PARAMS0, presetParams, readParams, slidesView, slideWord, stepSlides, summaryLine,
  toggleStrategy, variantCards, type Params,
} from "./params";
import type { ImproveSource, StrategyInfo } from "../../types";

const S: StrategyInfo[] = [
  { name: "structured", title: "Структурный", description: "…" },
  { name: "visual", title: "Визуальный", description: "…" },
  { name: "compact", title: "Компактный", description: "…" },
];
const P = (patch: Partial<Params> = {}): Params => ({ ...PARAMS0, ...patch });
const req = (patch: Partial<Parameters<typeof buildRequest>[0]> = {}) =>
  buildRequest({ templateId: "t1", brief: "  История VK  ", params: P(), strategies: S, modelOn: true, imagesOn: true, improve: null, ...patch });

test("черновик: по умолчанию — как V2 (12 слайдов, все варианты, модель пишет, взгляд выключен, изображения)", () => {
  assert.deepEqual(readParams(undefined), PARAMS0);
  assert.deepEqual(PARAMS0, { slides: null, strategies: [], audience: "", purpose: "product", ownPurpose: "", useModels: true, eyes: false, pictures: true });
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

test("запрос: поля как в старом CreateScreen", () => {
  assert.deepEqual(req(), {
    template_id: "t1", brief: "История VK", audience: null, purpose: "product", slides: 12,
    strategies: ["structured", "visual", "compact"], use_models: true, audit_models: false, eyes: false, pictures: true,
    autofix: true, exports: ["pdf", "html"], improved_from: undefined,
  });
});
test("запрос: аудитория, свой тип презентации, выбранные варианты, «взгляд» — проверка по картинке", () => {
  const r = req({ params: P({ audience: "  Совет директоров ", purpose: OWN, ownPurpose: " лекция для студентов ", strategies: ["visual"], eyes: true, slides: 8 }) });
  assert.equal(r.audience, "Совет директоров");
  assert.equal(r.purpose, "лекция для студентов");
  assert.deepEqual(r.strategies, ["visual"]);
  assert.equal(r.slides, 8);
  assert.equal(r.audit_models, true);
  assert.equal(r.eyes, true);
  assert.equal(req({ params: P({ purpose: OWN, ownPurpose: "  " }) }).purpose, null);
});
test("запрос: без модели переключатели модели выключены; без модели изображений — решает сервер", () => {
  const r = req({ params: P({ eyes: true }), modelOn: false, imagesOn: false });
  assert.equal(r.use_models, false);
  assert.equal(r.audit_models, false);
  assert.equal(r.eyes, false);
  assert.equal(r.pictures, null);
  assert.equal(req({ params: P({ pictures: false, useModels: false }) }).pictures, false);
  assert.equal(req({ params: P({ useModels: false }) }).use_models, false);
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
  assert.equal(req({ improve: src, modelOn: false }).eyes, false);
});

test("параметры презентации («Изменить текст»): аудитория, тип, слайды, модель, варианты", () => {
  const p = presetParams(P({ audience: "старая" }), { audience: null, purpose: "report", slides: 30, useModels: false, auditModels: true, pictures: null, strategies: ["compact"] });
  assert.deepEqual(p, { ...PARAMS0, audience: "", purpose: "report", slides: 20, useModels: false, eyes: true, pictures: true, strategies: ["compact"] });
  const own = presetParams(P(), { purpose: "лекция для студентов" });
  assert.deepEqual([own.purpose, own.ownPurpose], [OWN, "лекция для студентов"]);
  // чего в параметрах нет — остаётся
  const kept = presetParams(P({ slides: 9, strategies: ["visual"], pictures: false }), {});
  assert.deepEqual([kept.slides, kept.strategies, kept.pictures], [9, ["visual"], false]);
});
