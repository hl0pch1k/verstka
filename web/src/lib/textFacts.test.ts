import { test } from "node:test";
import assert from "node:assert/strict";
import { dictatedSlides, factsLine, textFacts } from "./textFacts";

test("slides dictated by headings get a cover in front", () => {
  const text = "Слайд 1. Проблема\nтекст\nСлайд 2. Решение\nтекст\nСлайд 3. Рынок\nтекст";
  assert.equal(dictatedSlides(text), 4);
  assert.equal(dictatedSlides("Расскажи про продукт на 8 слайдов"), 8);
  assert.equal(dictatedSlides("Просто текст без слайдов"), null);
});

test("figures: groups and decimals count once, slide headings and list markers do not", () => {
  const f = textFacts("Слайд 1. Итоги\nВыручка 1 240 000 ₽, рост 18 %, NPS 64.\n1. Первый пункт\n2. Второй пункт\nДоля 3,5 %.");
  assert.equal(f.figures, 4); // 1 240 000 · 18 · 64 · 3,5
});

test("tables: a markdown table counts once", () => {
  const text = "| Метрика | До | После |\n|---|---|---|\n| Время | 47 | 29 |\n\nи ещё\n\n| A | B |\n| :--- | ---: |\n| 1 | 2 |";
  assert.equal(textFacts(text).tables, 2);
});

test("the line says only what the text has", () => {
  assert.equal(factsLine({ slides: 6, figures: 14, tables: 1 }), "6 слайдов, 14 чисел, 1 таблица");
  assert.equal(factsLine({ slides: null, figures: 2, tables: 0 }), "2 числа");
  assert.equal(factsLine({ slides: null, figures: 0, tables: 0 }), null);
});
