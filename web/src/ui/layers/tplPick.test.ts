import { test } from "node:test";
import assert from "node:assert/strict";
import { deckPick } from "./tplPick";

test("«Шаблоны» over a result say the choice is for the next build and offer to rebuild this deck on it", () => {
  const base = { deckTpl: "vk", deckName: "VK Tech", chosen: "vk", chosenName: "VK Tech", improved: false };
  assert.deepEqual(deckPick(base), { line: "Эта презентация — на «VK Tech». Другой шаблон — для новой презентации или пересборки этой.", rebuild: null });
  assert.deepEqual(deckPick({ ...base, chosen: "bp", chosenName: "Blueprint" }),
    { line: "Выбран «Blueprint» — для новой презентации или пересборки этой.", rebuild: "bp" });
  // «Улучшить готовую»: оформление из исходного файла — только для новой
  assert.deepEqual(deckPick({ ...base, chosen: "bp", chosenName: "Blueprint", improved: true }),
    { line: "Выбран «Blueprint» — для новой презентации.", rebuild: null });
  assert.equal(deckPick({ ...base, chosen: null }).rebuild, null);
});
