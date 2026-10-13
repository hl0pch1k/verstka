import { test } from "node:test";
import assert from "node:assert/strict";
import { GEN, titleOf } from "./details.fixtures";
import { UI0, type UiState } from "../deck/geometry";
import { backStrip, headerLayerOpen, menuItems, SHEET_TABS, tabStep } from "./sheetView";

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

test("поверх листа открыт раздел шапки, просмотр или удаление шаблона — клавиши (←/→, запасной Esc) не листа", () => {
  assert.equal(headerLayerOpen(UI0), false);
  assert.equal(headerLayerOpen({ ...UI0, sect: "tpls" }), true);
  assert.equal(headerLayerOpen({ ...UI0, tplPreview: "t1" }), true);
  assert.equal(headerLayerOpen({ ...UI0, tplDelete: "t1" }), true);
  // слой «Слайд N шаблона» — часть листа, не шапки
  const withPattern: UiState = { ...UI0, pattern: 3 };
  assert.equal(headerLayerOpen(withPattern), false);
});
