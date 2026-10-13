import { test } from "node:test";
import assert from "node:assert/strict";
import { boardColumns, targetBoxWidth, MIN_CARD, TIGHT_CARD } from "./columns";

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

// Ход сетки помощника (1440, открытие): колода 1392 → 976, раскладка плиты одна на весь ход (узкая — с первого кадра),
// поэтому список = колода − 464 на каждом кадре
const FRAMES = [1392, 1300, 1193, 1086, 1037, 997, 976];
const K = 464;

test("targetBoxWidth: на каждом кадре хода — ширина, которую список получит в конце", () => {
  for (const now of FRAMES) assert.equal(targetBoxWidth(now - K, now, 976), 976 - K);
});
test("targetBoxWidth: цель неизвестна (колода не измерена) — живая ширина", () => {
  assert.equal(targetBoxWidth(700, 1164, 0), 700);
  assert.equal(targetBoxWidth(700, 0, 976), 700);
});
test("колонки по живой ширине мигают посреди хода (4 → 5 → 4 → 3) — по целевой стоят с первого кадра", () => {
  const live = FRAMES.map((now) => boardColumns(now - K, 380, 12, A, MIN_CARD));
  assert.ok(new Set(live).size > 1, `по кадрам ${live.join(",")}`);
  const frozen = FRAMES.map((now) => boardColumns(targetBoxWidth(now - K, now, 976), 380, 12, A, MIN_CARD));
  assert.deepEqual(frozen, FRAMES.map(() => boardColumns(976 - K, 380, 12, A, MIN_CARD)));
  assert.equal(frozen[0], 3);
});
test("закрытие: пока узкая раскладка держится, колонки — от узкой цели; после хода — от широкой", () => {
  // колода растёт 976 → 1392, раскладка узкая (K тот же), цель — 976: колонки не меняются до конца хода
  const closing = [...FRAMES].reverse().map((now) => boardColumns(targetBoxWidth(now - K, now, 976), 380, 12, A, MIN_CARD));
  assert.ok(closing.every((c) => c === closing[0]));
});
