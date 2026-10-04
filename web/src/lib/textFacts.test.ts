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

test("a first slide that opens on a tagline is the cover: no second cover in front of it", () => {
  const text = [
    "Слайд 1. Умная теплица", "", "Автоматизация полива и контроль микроклимата", "", "Учебный проект о датчиках и данных.", "",
    "Слайд 2. Как это работает", "", "Текст второго слайда.", "",
    "Слайд 3. Спасибо за внимание!", "", "Вопросы и обсуждение.",
  ].join("\n");
  assert.equal(dictatedSlides(text), 3);
  // a first slide named like a part of the deck stays content: a cover goes in front of it
  assert.equal(dictatedSlides("Слайд 1. Проблема\nКлиенты ждут ответа два дня\nСлайд 2. Решение\nБот отвечает сразу"), 3);
  // code or a chart on the first slide: content too
  assert.equal(dictatedSlides("Слайд 1. Данные\nЗапись журнала\n```json\n{}\n```\nСлайд 2. Итоги\nтекст"), 3);
});

test("a first slide named «Discovery» is content; a first slide that is a heading alone is the cover", () => {
  const en = "Slide 1. Discovery\nWe interviewed forty customers.\n\nSlide 2. Plan\nA chatbot answers.\n\nSlide 3. Next steps\nWe hire two engineers.";
  assert.equal(dictatedSlides(en), 4); // a cover in front of «Discovery»
  const bare = "Слайд 1. Умная теплица\n\nСлайд 2. Устройство\nТекст о датчиках.\n\nСлайд 3. Итоги\nТекст об итогах.";
  assert.equal(dictatedSlides(bare), 3);
});
