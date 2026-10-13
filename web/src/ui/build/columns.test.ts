import { test } from "node:test";
import assert from "node:assert/strict";
import { boardColumns, MIN_CARD, TIGHT_CARD } from "./columns";
import { plateWidth } from "../deck/fit";

const A = 16 / 9;

test("boardColumns: четыре колонки доски, пока карточка не уже 150; уже — меньше колонок", () => {
  assert.equal(boardColumns(928, 600, 5, A, MIN_CARD), 4);
  assert.equal(boardColumns(512, 600, 5, A, MIN_CARD), 3);
  assert.equal(boardColumns(400, 600, 5, A, MIN_CARD), 2);
});
test("boardColumns: в тесной колоде карточка до 112 — три колонки, а не две", () => {
  assert.equal(boardColumns(400, 600, 5, A, TIGHT_CARD), 3);
});
test("boardColumns: больше колонок, когда иначе не видны все слайды", () => {
  assert.equal(boardColumns(836, 380, 12, A, MIN_CARD), 5);
});
test("boardColumns: список ещё не измерен — четыре", () => {
  assert.equal(boardColumns(0, 0, 12, A, MIN_CARD), 4);
});

// Ход сетки помощника (1440, открытие): колода 1392 → 976. Содержимое плиты стоит в ширине колоды на конец хода
// (plateWidth), поэтому ширина списка на всём ходу одна — колонки не мигают (раньше по живой ширине: 4 → 5 → 4 → 3)
const FRAMES = [1392, 1300, 1193, 1086, 1037, 997, 976];
// список в узкой раскладке: содержимое плиты − зазор 48 − колонка агента 320
const box = (deck: number) => (plateWidth(deck) ?? 0) - 48 - 320;

test("колонки по живой ширине мигали бы посреди хода — содержимое плиты стоит в целевой ширине, и колонки стоят", () => {
  const live = FRAMES.map((now) => boardColumns(box(now), 380, 12, A, MIN_CARD));
  assert.ok(new Set(live).size > 1, `по кадрам ${live.join(",")}`);
  const fixed = FRAMES.map(() => boardColumns(box(976), 380, 12, A, MIN_CARD));
  assert.ok(fixed.every((c) => c === 3));
});
