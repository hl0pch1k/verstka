import { test } from "node:test";
import assert from "node:assert/strict";
import { clock, quoted, railSlides, sketchKind, sketchOf, stripQuoted } from "./stage";
import type { AgentEvent } from "../types";

const ev = (step: string, message: string, slide: number | null = null, variant: string | null = null): AgentEvent => ({ step, message, slide, variant });
const plain = (s: string | null) => (s ?? "").replace(/ /g, " ");

test("quoted keeps nested quotes", () => {
  assert.equal(quoted("«Компания «Ромашка» растёт» — таблица"), "Компания «Ромашка» растёт");
  assert.equal(quoted("без кавычек"), null);
  assert.equal(stripQuoted("Обложка «А «Б»», мелким текстом").trim(), "Обложка , мелким текстом");
});

test("sketchKind reads the form words", () => {
  assert.equal(sketchKind("— таблица 3×4."), "table");
  assert.equal(sketchKind("— круговая диаграмма (5 категорий)."), "pie");
  assert.equal(sketchKind("— горизонтальная диаграмма (5 категорий)."), "hbars");
  assert.equal(sketchKind("— столбчатая диаграмма (4 категории)."), "bars");
  assert.equal(sketchKind("— два линейных графика."), "line");
  assert.equal(sketchKind("— список (2 пункта)."), "list");
  assert.equal(sketchKind("— ряд чисел (3 числа)."), "numbers");
  assert.equal(sketchKind("— хронология (5)."), "timeline");
  assert.equal(sketchKind("— что-то новое"), "text");
});

test("sketchOf: designer lines give the slide, its form and its headline", () => {
  const t = sketchOf(ev("designer", "«Средняя месячная выручка на одного клиента составит 5 050 рублей» — таблица 3×4.", 5));
  assert.equal(t?.slide, 5);
  assert.equal(t?.kind, "table");
  assert.equal(plain(t?.headline ?? null), "Средняя месячная выручка на одного клиента составит 5 050 рублей");
  // a dash inside the headline is not the form's dash
  assert.equal(sketchOf(ev("designer", "«Цель — 250 клиентов и 225 000 ₽ прибыли к шестому месяцу» — список (2 пункта).", 2))?.kind, "list");
  assert.equal(sketchOf(ev("designer", "Обложка «Открытие фитнес-студии», мелким текстом — условность данных.", 1))?.kind, "cover");
  assert.equal(sketchOf(ev("designer", "без слайда — таблица")), null);
});

test("sketchOf: a revision counts only when it names a form", () => {
  assert.equal(sketchOf(ev("revise", "Столбчатая диаграмма (2 категории).", 6))?.kind, "bars");
  assert.equal(sketchOf(ev("revise", "Добавил из текста ключевые цифры или вывод, которых на слайде не было.", 6)), null);
  assert.equal(sketchOf(ev("critic", "На слайде нет ключевой цифры из текста: «3 000 000 рублей»", 10)), null);
});

test("railSlides: shared plan, own critic and revision, laid out slides", () => {
  const events = [
    ev("designer", "Обложка «Старт», мелким текстом — условность.", 1),
    ev("designer", "«Доли рынка» — круговая диаграмма (3 категории).", 2),
    ev("designer", "«Итоги» — список (3 пункта).", 4),
    ev("critic", "Заголовок повторяет тему слайда", 2, "visual"),
    ev("critic", "На слайде нет ключевой цифры", 4, "structured"),
    ev("revise", "Таблица 2×3.", 4, "structured"),
  ];
  const rail = railSlides(events, "structured", 3, 2);
  assert.equal(rail.length, 4); // the designer planned slide 4: the rail grows to it
  assert.deepEqual(rail.map((s) => s.sketch?.kind ?? null), ["cover", "pie", null, "table"]);
  assert.deepEqual(rail.map((s) => s.mark), [null, null, null, "fixed"]); // the visual variant's note is not ours
  assert.deepEqual(rail.map((s) => s.laid), [true, true, false, false]);
  assert.equal(railSlides(events, "visual", 3, 0)[1].mark, "note");
  // the revision keeps the designer's headline
  assert.equal(rail[3].sketch?.headline, "Итоги");
  // once the variant's plan says how many slides it has, the rail has exactly that many
  assert.equal(railSlides(events, "structured", 3, 0, true).length, 3);
});

test("clock", () => {
  assert.equal(clock(0), "0:00");
  assert.equal(clock(65.2), "1:05");
  assert.equal(clock(301), "5:01");
});
