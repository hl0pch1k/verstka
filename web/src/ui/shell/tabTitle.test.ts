import { test } from "node:test";
import assert from "node:assert/strict";
import { tabTitle } from "./tabTitle";

test("заголовок вкладки: ход сборки, название открытой презентации, иначе Verstka (A3)", () => {
  assert.equal(tabTitle({ building: true, progress: 0.423, screen: "build", deck: "Интеграл" }), "Готовлю презентацию 42 % · Verstka");
  // сборка идёт и тогда, когда человек на другом экране
  assert.equal(tabTitle({ building: true, progress: 1.4, screen: "result", deck: "Интеграл" }), "Готовлю презентацию 100 % · Verstka");
  assert.equal(tabTitle({ building: false, progress: 1, screen: "result", deck: "Интеграл" }), "Интеграл · Verstka");
  assert.equal(tabTitle({ building: false, progress: 0, screen: "result", deck: null }), "Verstka");
  assert.equal(tabTitle({ building: false, progress: 0, screen: "create", deck: "Интеграл" }), "Verstka");
});
