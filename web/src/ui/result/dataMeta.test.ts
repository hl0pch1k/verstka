import { test } from "node:test";
import assert from "node:assert/strict";
import type { ActiveJob } from "../../lib/jobState";
import type { GenerationMeta, Variant } from "../../types";
import { DATA_SLIDES } from "../../lib/dataWhy.fixtures";
import { deckBrand, deckTemplate, docLine, whyFile } from "./resultView";
import { liveWork } from "./slideJob";

const meta = (patch: Partial<GenerationMeta> = {}): GenerationMeta => ({ id: "g1", template_id: "t1", strategies: ["structured"], ...patch });

test("строка под названием: брендбук презентации — после шаблона (V2 v105 `docLine`); без брендбука — как было", () => {
  assert.equal(docLine("VK Tech", 9, "только что", "брендбук VK Cloud"), "VK Tech · брендбук VK Cloud · 9 слайдов · только что");
  assert.equal(docLine("VK Tech", 12, "сегодня, 17:38"), "VK Tech · 12 слайдов · сегодня, 17:38");
  assert.equal(docLine("VK Tech", 12, "сегодня, 17:38", null), "VK Tech · 12 слайдов · сегодня, 17:38");
  assert.equal(deckBrand(meta({ brandbook: { id: "b1", name: "VK Cloud", file: "Брендбук VK Cloud.pdf", source: "pdf" } })), "брендбук VK Cloud");
  assert.equal(deckBrand(meta({ brandbook: { id: "b1", name: "", file: "Брендбук Ромашка.pdf", source: "pdf" } })), "брендбук Ромашка");
  assert.equal(deckBrand(meta()), null);
  assert.equal(deckBrand(meta({ brandbook: null })), null);
});

test("шаблон презентации для людей: у колоды на брендированной копии — исходный", () => {
  assert.equal(deckTemplate(meta({ template_id: "copy1", base_template_id: "t1" })), "t1");
  assert.equal(deckTemplate(meta()), "t1");
  assert.equal(deckTemplate(meta({ base_template_id: null })), "t1");
});

test("карточка «Почему так» слайда с данными: его файл и природа данных; слайд не из файла — ничего", () => {
  const v = { strategy: "structured", outline: { slides: [{ ...DATA_SLIDES[4], data: null }, DATA_SLIDES[4], DATA_SLIDES[2]] } } as unknown as Variant;
  assert.equal(whyFile(v, 1), null);
  assert.deepEqual(whyFile(v, 2), { text: "Регионы.xlsx · сравнение", icon: "tbl" });
  assert.deepEqual(whyFile(v, 3), { text: "Итоги квартала.txt · таблица в тексте", icon: "txt" });
  assert.equal(whyFile(null, 1), null);
});

test("пока идёт «Пересобрать слайд так», работа над вариантом на экране результата ждёт — с понятной причиной", () => {
  const j = { id: "j", kind: "rebuild", target: { generation: "g1", strategy: "structured", slide: 4 } } as ActiveJob;
  assert.deepEqual(liveWork(j), { why: "Агент пересобирает слайд 4", slide: 4 });
});
