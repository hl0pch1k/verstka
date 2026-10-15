import { test } from "node:test";
import assert from "node:assert/strict";
import { AGENT, AGENT_TIGHT, boardColumns, boardLabel, buildMorph, MIN_CARD, phaseScale, PHASE_NARROW, rollOf } from "./columns";

const A = 16 / 9;
/** Обёртка колоды при окне 1440 и 1280 (поля страницы 24 + 24). */
const W1440 = 1392;
const W1280 = 1232;

test("boardColumns: четыре колонки доски, пока карточка не уже 150; уже — меньше колонок", () => {
  assert.equal(boardColumns(928, 600, 5, A, MIN_CARD), 4);
  assert.equal(boardColumns(512, 600, 5, A, MIN_CARD), 3);
  assert.equal(boardColumns(400, 600, 5, A, MIN_CARD), 2);
});
test("boardColumns: больше колонок, когда иначе не видны все слайды", () => {
  assert.equal(boardColumns(836, 380, 12, A, MIN_CARD), 5);
});
test("boardColumns: список ещё не измерен — четыре", () => {
  assert.equal(boardColumns(0, 0, 12, A, MIN_CARD), 4);
});

test("buildMorph при 1440 — как V2: колонка агента 416 → 320, клетка фазы 344, слова хода в сегментах", () => {
  const m = buildMorph(W1440);
  assert.equal(m.tight, false);
  assert.equal(m.agent, 320);
  assert.equal(m.hpd, 96);
  assert.equal(m.left, 536);
  assert.equal(m.cell, 344);
  assert.equal(m.list, 832);
  assert.equal(m.words, true);
  assert.equal(m.font, 36);
  // коробка «Не получилось»: текст не шире узкой (536 − 24 − 24), кнопки в ряд
  assert.equal(m.failText, 488);
  assert.equal(m.failCol, false);
});

test("buildMorph при 1280 — тесная колода: колонка агента 288, фаза мельче, сегменты с галочками, кнопки столбиком", () => {
  const m = buildMorph(W1280);
  assert.equal(m.tight, true);
  assert.equal(m.agent, AGENT_TIGHT);
  assert.equal(m.hpd, AGENT - AGENT_TIGHT);
  assert.equal(m.left, 408);
  assert.equal(m.cell, 216);
  assert.equal(m.list, 672);
  assert.equal(m.words, false);
  assert.equal(m.font, 27.07);
  assert.equal(m.failText, 360);
  assert.equal(m.failCol, true);
});

test("buildMorph: обёртка не измерена — как при 1440", () => {
  assert.deepEqual(buildMorph(0), buildMorph(W1440));
});

test("колонки раскадровки — по ширине окна, а не колоды: открытие и закрытие помощника их не меняют", () => {
  for (const wrap of [W1440, W1280, 1318]) {
    const m = buildMorph(wrap);
    // одна и та же ширина списка, что бы ни было с колодой посреди хода
    const cols = boardColumns(m.list, 468, 12, A, MIN_CARD);
    assert.equal(cols, 4, `обёртка ${wrap}`);
  }
});

test("boardLabel: «Раскадровка» остаётся при трёх вариантах при 1440, при 1280 — только при двух и одном", () => {
  assert.equal(boardLabel(buildMorph(W1440), 3), true);
  assert.equal(boardLabel(buildMorph(W1280), 3), false);
  assert.equal(boardLabel(buildMorph(W1280), 2), true);
  assert.equal(boardLabel(buildMorph(W1280), 1), true);
});

test("phaseScale: короткая фаза мельчает до .75, длинная — чтобы встала в клетку (V2 `bdPhs`)", () => {
  const m = buildMorph(W1440);
  assert.equal(phaseScale("analyst", m.font, m.cell), PHASE_NARROW);
  // V2: min(.75, 340 / 633) — «Смотрю на слайды целиком»
  assert.ok(Math.abs(phaseScale("eyes", m.font, m.cell) - 340 / 633) < 0.002);
  // фаза в узкой раскладке не шире своей клетки при 1440 и 1280, в широкой — тоже (колонка без места «03», поле 4 px)
  const W36: Record<string, number> = { queued: 433, eyes: 633, layout: 586, failed: 493 };
  for (const wrap of [W1440, W1280]) {
    const k = buildMorph(wrap);
    for (const [p, w36] of Object.entries(W36)) {
      const w = (w36 * k.font) / 36;
      assert.ok(w * phaseScale(p as "eyes", k.font, k.cell) <= k.cell, `${wrap} ${p}`);
      assert.ok(w <= k.list - 192 - 4, `${wrap} ${p} широкая`);
    }
  }
});

test("rollOf: роль и следующая — над нижним краем; влезает — без сдвига", () => {
  assert.equal(rollOf([60, 60, 60], 12, 16, 1, 564), 0);
  assert.equal(rollOf([200, 200, 200, 200], 12, 16, 3, 564), 16 + 800 + 36 - 564);
  assert.equal(rollOf([200, 200], 12, 16, 9, 300), 16 + 400 + 12 - 300);
  assert.equal(rollOf([], 12, 16, 0, 300), 0);
});

test("rollOf: высоты и сдвиг идут одной кривой — роли движутся в одну сторону, нижняя видимая стоит у края", () => {
  // помощник открывается: строки ролей переносятся уже (высоты 2-й и 4-й роли растут), сдвиг растёт той же кривой
  const wide = [60, 84, 60, 108, 60, 60];
  const narrow = [60, 128, 60, 172, 60, 60];
  const view = 300, upto = 4;
  const rw = rollOf(wide, 12, 16, upto, view);
  const rn = rollOf(narrow, 12, 16, upto, view);
  const top = (hs: number[], i: number) => 16 + hs.slice(0, i).reduce((a, h) => a + h + 12, 0);
  for (let i = 0; i < wide.length; i++) {
    let prev: number | null = null;
    let dir = 0;
    for (let k = 0; k <= 20; k++) {
      const e = k / 20;
      const hs = wide.map((h, j) => h + (narrow[j] - h) * e);
      const y = top(hs, i) - (rw + (rn - rw) * e);
      if (prev !== null && Math.abs(y - prev) > 1e-9) {
        const d = Math.sign(y - prev);
        assert.ok(dir === 0 || d === dir, `роль ${i} поменяла направление на ${e}`);
        dir = d;
      }
      prev = y;
    }
  }
  // нижний край роли upto — у края на всём ходу (оба сдвига > 0)
  for (let k = 0; k <= 20; k++) {
    const e = k / 20;
    const hs = wide.map((h, j) => h + (narrow[j] - h) * e);
    const end = top(hs, upto) + hs[upto] - (rw + (rn - rw) * e);
    assert.ok(Math.abs(end - view) <= 1, `край ${end} на ${e}`);
  }
});
