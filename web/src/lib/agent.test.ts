import { test } from "node:test";
import assert from "node:assert/strict";
import { agentSummary, buildTimeline, eventParts } from "./agent";
import type { Variant } from "../types";

test("agentSummary: a skipped critic is not named twice («Критик Критик пропущен»)", () => {
  const v = {
    strategy: "structured",
    agent: {
      events: [
        { step: "analyst", message: "Нашёл в тексте 12 слайдов, 2 ряда данных и 2 заказанные диаграммы; нужно 12 слайдов.", slide: null, variant: null },
        { step: "designer", message: "«Итоги года» — столбчатая диаграмма (4 категории).", slide: 1, variant: null },
        { step: "critic", message: "Критик пропущен: слайды собраны по правилам, без модели.", slide: null, variant: null },
      ],
    },
  } as unknown as Variant;
  const critic = agentSummary(v).find((l) => l.step === "Критик");
  assert.equal(critic?.text.replace(/\u00a0/g, " "), "Пропущен: слайды собраны по правилам, без модели");
});

test("eventParts: a line under its own step does not name the step again", () => {
  const skipped = eventParts({ step: "critic", message: "Критик пропущен: слайды собраны по правилам, без модели.", slide: null, variant: null });
  assert.equal(skipped.text.replace(/\u00a0/g, " "), "Пропущен: слайды собраны по правилам, без модели.");
  // a word that only starts like the step stays
  const other = eventParts({ step: "critic", message: "Критика данных не нужна.", slide: null, variant: null });
  assert.equal(other.text.replace(/\u00a0/g, " "), "Критика данных не нужна.");
});

test("eventParts: a designer line does not repeat «(модель не ответила)» — the step says it once", () => {
  const line = eventParts({ step: "designer", message: "«Надёжность» собран по правилам (модель не ответила) — ряд чисел (3 числа).", slide: 7, variant: null });
  assert.equal(line.text.replace(/\u00a0/g, " "), "«Надёжность» собран по правилам — ряд чисел (3 числа).");
});

test("buildTimeline: a critic that only said it was skipped is a skipped step, not a done one", () => {
  const rows = buildTimeline({
    events: [
      { step: "analyst", message: "Нашёл в тексте 12 слайдов.", slide: null, variant: null },
      { step: "designer", message: "«Итоги» — таблица 2×3.", slide: 2, variant: null },
      { step: "critic", message: "Критик пропущен: слайды собраны по правилам, без модели.", slide: null, variant: null },
    ],
    phase: "check",
    running: false,
  });
  const critic = rows.find((r) => r.key === "critic");
  assert.equal(critic?.status, "skipped");
  assert.equal(critic?.events.length, 0);
  assert.equal(critic?.note?.replace(/\u00a0/g, " "), "пропущен: слайды собраны по правилам, без модели");
});

test("eventParts: an older run's «заполнил его текстом брифа» never reads «текстом текста»", () => {
  const line = eventParts({ step: "compile", message: "Слайд «Выручка»: в нём не осталось того, что есть в брифе, — заполнил его текстом брифа.", slide: 4, variant: null });
  assert.equal(line.text.includes("текстом текста"), false);
  assert.equal(line.text.replace(/\u00a0/g, " ").includes("заполнил его исходными формулировками"), true);
  // the server's own record already said «текст» for «бриф»
  const stored = eventParts({ step: "compile", message: "Слайд «Выручка»: в нём не осталось того, что есть в тексте, — заполнил его текстом текста.", slide: 4, variant: null });
  assert.equal(stored.text.includes("текстом текста"), false);
});

test("eventParts: older runs' «заказанные диаграммы» and «данные для диаграмм: 2 диаграммы» read plainly", () => {
  const found = eventParts({ step: "analyst", message: "Нашёл в тексте 12 слайдов и 2 заказанные диаграммы.", slide: null, variant: null });
  assert.equal(found.text.replace(/\u00a0/g, " "), "Нашёл в тексте 12 слайдов и 2 указанные диаграммы.");
  const charts = eventParts({ step: "compile", message: "Подготовил данные для диаграмм: 9 диаграмм.", slide: null, variant: null });
  assert.equal(charts.text.replace(/\u00a0/g, " "), "Подготовил данные для диаграмм (9).");
});

test("buildTimeline: «Взгляд дизайнера» says which slides it laid out again and which kept their remark", () => {
  const events = [
    { step: "analyst", message: "Нашёл в тексте 10 слайдов.", slide: null, variant: null },
    { step: "eyes", message: "Посмотрел на 13 слайдов — замечания на слайдах 2, 6.", slide: null, variant: "structured" },
    { step: "eyes", message: "Слова разорваны посередине (карточки).", slide: 2, variant: "structured", fix: "Собрал заново на другом макете шаблона: без разрывов слов." },
    { step: "eyes", message: "Диаграмма или таблица не читается.", slide: 6, variant: "structured", fix: "Новая вёрстка не лучше — оставил прежнюю (прежняя аккуратнее)." },
  ];
  const rows = buildTimeline({ events, phase: null, running: false });
  const eyes = rows.find((r) => r.key === "eyes");
  assert.ok(eyes, "the step shows once the model looked");
  assert.equal(eyes?.title, "Взгляд дизайнера");
  assert.equal(eyes?.note?.replace(/ /g, " "), "1 слайд пересобран, 1 замечание · слайд 6");
  const clean = buildTimeline({ events: [events[0], { step: "eyes", message: "Посмотрел на 13 слайдов — замечаний нет.", slide: null, variant: null }], phase: null, running: false });
  assert.equal(clean.find((r) => r.key === "eyes")?.note, "замечаний нет");
  // a build without the vision model has no such step at all
  assert.ok(!buildTimeline({ events: [events[0]], phase: null, running: false }).some((r) => r.key === "eyes"));
});

test("agentSummary: «Взгляд дизайнера» says how many slides it looked at and laid out again for this variant", () => {
  const v = {
    strategy: "structured",
    agent: {
      events: [
        { step: "designer", message: "«Итоги» — таблица.", slide: 2, variant: null },
        { step: "eyes", message: "Посмотрел на 13 слайдов — замечания на слайдах 2, 6.", slide: null, variant: "structured" },
        { step: "eyes", message: "Слова разорваны посередине.", slide: 2, variant: "structured", fix: "Собрал заново на другом макете шаблона." },
        { step: "eyes", message: "Посмотрел на 13 слайдов — замечаний нет.", slide: null, variant: "visual" },
      ],
    },
  } as unknown as Variant;
  const eyes = agentSummary(v).find((l) => l.step === "Взгляд дизайнера");
  assert.equal(eyes?.text.replace(/ /g, " "), "Посмотрел на 13 слайдов, пересобрал 1 слайд");
  const visual = agentSummary({ ...v, strategy: "visual" } as Variant).find((l) => l.step === "Взгляд дизайнера");
  assert.equal(visual?.text.replace(/ /g, " "), "Посмотрел на 13 слайдов — замечаний нет");
});
