import { test } from "node:test";
import assert from "node:assert/strict";
import { CLOSE_HOLD_MS, deckFit, deckLayout, HELPER_CLOSE_MS } from "./fit";

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
// решение — по целевой ширине: обёртка колоды (`hp-wrap`) не анимируется, колода = обёртка − место помощника 416
test("deckLayout: цель — обёртка без места помощника (плита 400 + зазор 16)", () => {
  assert.deepEqual(deckLayout(1392, false), { width: 1392, fit: "wide" });
  assert.deepEqual(deckLayout(1232, false), { width: 1232, fit: "wide" });
  assert.deepEqual(deckLayout(1392, true), { width: 976, fit: "narrow" });
  assert.deepEqual(deckLayout(1232, true), { width: 816, fit: "tight" });
});
test("deckLayout: открытие — узкая раскладка сразу, хотя колода ещё широкая (ширина кадра в решение не входит)", () => {
  // первый кадр хода: помощник уже открыт, колода ещё 1388 — раскладка та, что будет в конце
  assert.equal(deckLayout(1392, true).fit, "narrow");
});
test("deckLayout: закрытие — узкая раскладка держится, пока сетка не доехала", () => {
  assert.deepEqual(deckLayout(1392, false, true), { width: 976, fit: "narrow" });
  assert.deepEqual(deckLayout(1232, false, true), { width: 816, fit: "tight" });
  // доехала — широкая
  assert.deepEqual(deckLayout(1392, false, false), { width: 1392, fit: "wide" });
});
test("закрытие: запасной таймер узкой раскладки — ход сетки обёртки (340 мс) + 40, после transitionend, а не до", () => {
  assert.equal(HELPER_CLOSE_MS, 340);
  assert.equal(CLOSE_HOLD_MS, HELPER_CLOSE_MS + 40);
});
test("deckLayout: обёртка ещё не измерена — широкая, без ширины", () => {
  assert.deepEqual(deckLayout(0, true), { width: 0, fit: "wide" });
});
