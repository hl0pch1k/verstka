import { test } from "node:test";
import assert from "node:assert/strict";
import { GEN, titleOf } from "./details.fixtures";
import { backStrip, menuItems, SHEET_TABS, tabStep } from "./sheetView";

test("вкладки листа — шесть, в порядке доски", () => {
  assert.deepEqual(SHEET_TABS.map((t) => t.label), ["Качество", "Почему так", "Агент", "План", "Шаблон", "Файлы"]);
});

test("стрелки во вкладках: соседняя по кругу, Home и End — крайние", () => {
  assert.equal(tabStep("quality", "ArrowRight"), "why");
  assert.equal(tabStep("quality", "ArrowLeft"), "files");
  assert.equal(tabStep("plan", "Home"), "quality");
  assert.equal(tabStep("plan", "End"), "files");
  assert.equal(tabStep("plan", "Enter"), null);
});

test("полоса «04»: название, вариант с оценкой и подпись для чтения с экрана", () => {
  assert.deepEqual(backStrip(GEN, GEN.variants[1], titleOf), {
    title: "Интеграл", name: "Визуальный", score: 84, aria: "Вернуться к результату: Интеграл, вариант Визуальный, оценка 84",
  });
});

test("меню варианта: номер, название, оценка", () => {
  assert.deepEqual(menuItems(GEN, titleOf), [{ key: "structured", n: 1, name: "Структурный", score: 89 }, { key: "visual", n: 2, name: "Визуальный", score: 84 }, { key: "compact", n: 3, name: "Компактный", score: 89 }]);
});
