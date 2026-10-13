import { test } from "node:test";
import assert from "node:assert/strict";
import { CLOSE_HOLD_MS, deckFit, deckLayout, errBelow, HELPER_CLOSE_MS, hintTail, layoutKey, plateWidth, ribbonLayout, rowMode, segStatus } from "./fit";

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

// плита 03 (бывшие @container p3): содержимое плиты — колода без полей 96
test("rowMode: короткий ряд — полный (доска), без переключателей (1280), узкий, тесный", () => {
  assert.equal(rowMode(1392), "full");
  assert.equal(rowMode(1232), "short");
  assert.equal(rowMode(976), "narrow");
  assert.equal(rowMode(816), "tight");
  assert.equal(rowMode(0), "full");
});
test("rowMode: переключатели уходят, когда плите 03 не больше 1254 px (колода 1350)", () => {
  assert.equal(rowMode(1351), "full");
  assert.equal(rowMode(1350), "short");
});
test("errBelow: строка ошибки встаёт под ряд заголовка, когда плите 03 не больше 1289 px", () => {
  assert.equal(errBelow(1392), false);
  assert.equal(errBelow(1386), false);
  assert.equal(errBelow(1385), true);
  assert.equal(errBelow(976), true);
  assert.equal(errBelow(0), false);
});
test("segStatus: подписи хода в сегментах раскадровки — пока плите 03 больше 1263 px", () => {
  assert.equal(segStatus(1392), true);
  assert.equal(segStatus(1360), true);
  assert.equal(segStatus(1359), false);
  assert.equal(segStatus(976), false);
  assert.equal(segStatus(0), true);
});
test("hintTail: «Это тема…» с перечнем — пока колода шире 1300", () => {
  assert.equal(hintTail(1392), true);
  assert.equal(hintTail(1301), true);
  assert.equal(hintTail(1300), false);
  assert.equal(hintTail(1232), false);
  assert.equal(hintTail(976), false);
  assert.equal(hintTail(0), true);
});

// Fix round 3: содержимое плит «Создать» и «Сборки» меняет раскладку перекрёстным затуханием (usePlateFit) — по ключу всех
// решений по ширине: затухание — только когда меняется хоть одно, а не на каждом пикселе ширины
test("layoutKey: одна раскладка — один ключ (ширина внутри одних порогов)", () => {
  assert.equal(layoutKey(976), layoutKey(1000));
  assert.equal(layoutKey(816), layoutKey(900));
  assert.equal(layoutKey(1392), layoutKey(1400));
  assert.equal(layoutKey(1232), layoutKey(1240));
});
test("layoutKey: помощник открылся или закрылся — ключ другой при 1440 и 1280", () => {
  assert.ok(layoutKey(1392) !== layoutKey(976));
  assert.ok(layoutKey(1232) !== layoutKey(816));
  // 1440 и 1280 без помощника — разные ряды параметров, подсказка «Это тема…», сегменты, строка ошибки
  assert.ok(layoutKey(1392) !== layoutKey(1232));
});
test("layoutKey: меняется на каждом пороге — узкая/тесная колода, ряд, строка ошибки, подсказка, сегменты", () => {
  for (const [a, b] of [[1101, 1100], [901, 900], [1351, 1350], [1386, 1385], [1301, 1300], [1360, 1359]]) {
    assert.ok(layoutKey(a) !== layoutKey(b), `${a} / ${b}`);
  }
});
test("layoutKey: не измерена — как широкая колода доски", () => {
  assert.equal(layoutKey(0), layoutKey(1392));
});
test("plateWidth: содержимое плиты стоит в ширине колоды на конец хода (без полей 48 + 48); не измерена — нет", () => {
  assert.equal(plateWidth(976), 880);
  assert.equal(plateWidth(1392), 1296);
  assert.equal(plateWidth(0), null);
});
