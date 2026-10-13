import { test } from "node:test";
import assert from "node:assert/strict";
import { deckFit, ribbonLayout } from "./fit";

// ширины колоды: 1440 — 1392 (закрыт) и 976 (помощник); 1280 — 1232 и 816
test("deckFit: закрытый помощник — широкая колода при 1280 и 1440", () => {
  assert.equal(deckFit(1392), "wide");
  assert.equal(deckFit(1232), "wide");
});
test("deckFit: помощник открыт — узкая при 1440, тесная при 1280", () => {
  assert.equal(deckFit(976), "narrow");
  assert.equal(deckFit(816), "tight");
});
test("deckFit: ширина ещё не измерена — широкая (как до помощника)", () => {
  assert.equal(deckFit(0), "wide");
});
test("ribbonLayout: широкая — шесть обложек в четыре колонки; узкая и тесная — четыре в три", () => {
  assert.deepEqual(ribbonLayout("wide"), { covers: 6, cols: 4 });
  assert.deepEqual(ribbonLayout("narrow"), { covers: 4, cols: 3 });
  assert.deepEqual(ribbonLayout("tight"), { covers: 4, cols: 3 });
});
