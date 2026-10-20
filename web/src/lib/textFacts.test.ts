import { test } from "node:test";
import assert from "node:assert/strict";
import { briefBody, dictatedSlides, factsLine, slideCountOf, slideRange, textFacts } from "./textFacts";

test("slides dictated by headings get a cover in front", () => {
  const text = "Слайд 1. Проблема\nтекст\nСлайд 2. Решение\nтекст\nСлайд 3. Рынок\nтекст";
  assert.equal(dictatedSlides(text), 4);
  assert.equal(dictatedSlides("Расскажи про продукт на 8 слайдов"), 8);
  assert.equal(dictatedSlides("Просто текст без слайдов"), null);
  // a part of the deck is not its size (the server reads the text with the same rule: planning/brief.py)
  assert.equal(dictatedSlides("Итоги покажите в 2 слайдах, без лишнего."), null);
  assert.equal(dictatedSlides("Первые 2 слайда — о проблеме, остальные — о решении."), null);
  assert.equal(dictatedSlides("Из прошлых докладов 3 слайда про рынок."), null);
  assert.equal(dictatedSlides("Сделай, пожалуйста, 12 слайдов про кофейню"), 12);
  assert.equal(dictatedSlides("Не более 10 слайдов."), 10);
  assert.equal(dictatedSlides("Make a 9-slide deck"), 9);
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

test("front matter is not material: the text's length counts the body", () => {
  assert.equal(briefBody("---\nslides: 5\n---\n").trim(), "");
  assert.equal(briefBody("---\nаудитория: инвесторы\n---\nТекст презентации").trim(), "Текст презентации");
  assert.equal(briefBody("Просто текст\n---\nещё"), "Просто текст\n---\nещё");
});

test("диапазон слайдов — как brief.py SLIDE_RANGE_RE: размер колоды — верхняя граница; части колоды — не размер", () => {
  assert.equal(dictatedSlides("Сделай 6–8 слайдов про кофейню"), 8);
  assert.equal(dictatedSlides("Слайдов 8–10, коротко"), 10);
  assert.equal(dictatedSlides("Нужно 8-10 slides about the market"), 10);
  assert.equal(dictatedSlides("Слайдов: от 6 до 8"), 8);
  assert.equal(dictatedSlides("---\nslides: 6-8\n---\nТекст про продукт"), 8);
  assert.equal(slideCountOf("---\nslides: 12\n---\nТекст"), 12);
  assert.deepEqual(slideRange("6–8 слайдов"), [6, 8]);
  // части колоды — не её размер
  assert.equal(dictatedSlides("Расскажи о рынке по 2–3 слайдам на тему"), null);
  assert.equal(dictatedSlides("Итоги — в 2–3 слайдах"), null);
  assert.equal(slideRange("Выручка 1,6–8 слайдов"), null);
  // без диапазона — прежнее правило
  assert.equal(slideCountOf("Расскажи про продукт на 8 слайдов"), 8);
});
