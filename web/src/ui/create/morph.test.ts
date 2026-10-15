import { test } from "node:test";
import assert from "node:assert/strict";
import { ctaShort, deckWidths, hintTail, moreGrid, paramsRow, readyShort, ribbonRows } from "./morph";

// обёртка колоды: 1392 при окне 1440, 1232 при 1280
const W1440 = 1392, W1280 = 1232;
const tracks = (s: string) => s.split(/\s+(?![^(]*\))/);
const pxOf = (s: string) => parseFloat(s);

test("deckWidths: открытый помощник сужает колоду на 416 (плита 400 + зазор 16); не измерена — как на доске", () => {
  assert.deepEqual(deckWidths(W1440), { wide: 1392, narrow: 976 });
  assert.deepEqual(deckWidths(W1280), { wide: 1232, narrow: 816 });
  assert.deepEqual(deckWidths(0), { wide: 1392, narrow: 976 });
});

test("paramsRow при 1440: дорожки V2 — степпер 216 → 200, переключатели 264 → 0, варианты 186.67 → 146.67", () => {
  const r = paramsRow(W1440, 3);
  assert.equal(r.switches, true);
  assert.equal(r.stepper, true);
  // клетка = коробка + поле 16
  assert.deepEqual(tracks(r.wide), ["232px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "280px"]);
  assert.deepEqual(tracks(r.narrow), ["216px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "0px"]);
  assert.equal(r.shrink, 40);
});

test("paramsRow: число дорожек в обеих раскладках одно — сетка интерполируется", () => {
  for (const w of [W1440, W1280, 1300, 1360]) for (const n of [1, 2, 3, 4]) {
    const r = paramsRow(w, n);
    assert.equal(tracks(r.wide).length, n + 2, `${w}/${n}`);
    assert.equal(tracks(r.narrow).length, n + 2, `${w}/${n}`);
  }
});

test("paramsRow при 1280: переключатели — только в «Все параметры», в узкой степпер уходит, варианты с названием", () => {
  const r = paramsRow(W1280, 3);
  assert.equal(r.switches, false);
  assert.equal(r.stepper, false);
  assert.deepEqual(tracks(r.wide), ["232px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "0px"]);
  assert.deepEqual(tracks(r.narrow), ["0px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "0px"]);
  // варианты 226.67 → 165.33: описание держит ширину покоя
  assert.equal(Math.round(r.shrink * 100) / 100, 61.33);
  // в узкой — не уже, чем нужно названию
  assert.ok((W1280 - 416 - 96 - 192 + 16) / 3 - 16 >= 138);
});

test("paramsRow: переключатели уходят ровно там, где варианту меньше 173 px (колода 1350)", () => {
  assert.equal(paramsRow(1351, 3).switches, true);
  assert.equal(paramsRow(1350, 3).switches, false);
});

test("moreGrid при 1440: три колонки в обеих раскладках, подсказка варианта шире в узкой на 33.33 (миниатюра ушла)", () => {
  const m = moreGrid(W1440, 3, false);
  assert.equal(m.tight, false);
  assert.equal(m.thumb, 156);
  assert.equal(m.vhint, -33.333);
  assert.equal(tracks(m.r1Wide).length, 3);
  assert.equal(tracks(m.r1Narrow).length, 3);
  assert.equal(pxOf(tracks(m.r1Narrow)[0]), pxOf(tracks(m.r1Narrow)[2]));
});

test("moreGrid при 1280: тесная — переключатели строками, степпер слайдов по содержимому", () => {
  const m = moreGrid(W1280, 3, true);
  assert.equal(m.tight, true);
  assert.equal(m.thumb, 112);
  const n = tracks(m.r1Narrow).map(pxOf);
  assert.equal(n[2], 168);
  assert.equal(Math.round((n[0] + n[1] + n[2] + 32) * 100) / 100, 816 - 288);
  assert.equal(tracks(m.r1Wide).map(pxOf).reduce((a, b) => a + b) + 32, 1232 - 288);
  // вариант 304 → 165.33, миниатюра 112 уходит, поля 16 → 12: подсказка у́же на 10.67 — роли копий обычные
  assert.equal(m.vhint, 304 - 32 - 112 - 16 - (496 / 3 - 24) > 0 ? Math.round((304 - 32 - 112 - 16 - (496 / 3 - 24)) * 1000) / 1000 : NaN);
  assert.ok(m.vhint > 0);
});

test("подписи по ширине: при 1440 — полные, при 1280 — короткие; перечень у «Это тема…» — пока колода шире 1300", () => {
  assert.equal(readyShort(W1440), false);
  assert.equal(ctaShort(W1440), false);
  assert.equal(readyShort(W1280), true);
  assert.equal(ctaShort(W1280), true);
  assert.equal(hintTail(W1440), true);
  assert.equal(hintTail(W1280), false);
  assert.equal(hintTail(1301), true);
  assert.equal(hintTail(1300), false);
});

const ids = (rows: ReturnType<typeof ribbonRows<string>>["rows"]) => rows.map((r) => r.slots.map((s) => (s.kind === "cover" ? s.item : s.kind) + (s.cut ? "✂" : "")));

test("ribbonRows: шесть обложек, «Все шаблоны», «Загрузить свой» — два ряда по четыре; в каждом уходит последняя обложка", () => {
  const { rows, gone } = ribbonRows(["a", "b", "c", "d", "e", "f"], (t) => t === "a", true);
  assert.deepEqual(ids(rows), [["a", "b", "c", "d✂"], ["e", "f✂", "all", "upload"]]);
  assert.equal(gone, 2);
  assert.equal(rows[0].narrow, "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 0fr)");
  assert.equal(rows[1].narrow, "minmax(0, 1fr) minmax(0, 0fr) minmax(0, 1fr) minmax(0, 1fr)");
});

test("ribbonRows: выбранная обложка не уходит — уходит предыдущая", () => {
  const { rows } = ribbonRows(["a", "b", "c", "d", "e", "f"], (t) => t === "d" || t === "f", true);
  assert.deepEqual(ids(rows), [["a", "b", "c✂", "d"], ["e✂", "f", "all", "upload"]]);
});

test("ribbonRows: без «Все шаблоны» (5–6 шаблонов, скрытых нет) обложки не уходят — до каждой можно добраться; ряды по четыре", () => {
  for (const covers of [["a", "b", "c", "d", "e"], ["a", "b", "c", "d", "e", "f"], ["a", "b", "c"]]) {
    const { rows, gone } = ribbonRows(covers, (t) => t === "a", false);
    assert.equal(gone, 0, covers.join());
    assert.ok(rows.every((r) => r.slots.every((s) => !s.cut)), covers.join());
    // колонки рядов совпадают и в узкой раскладке: по четыре живые дорожки
    for (const r of rows) assert.equal(r.narrow, "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr)");
    assert.equal(rows.flatMap((r) => r.slots).filter((s) => s.kind === "cover").length, covers.length);
  }
});

test("ribbonRows: со «Все шаблоны» короткий ряд — лишние пустые дорожки сверх трёх сжимаются", () => {
  const { rows, gone } = ribbonRows(["a"], () => false, true);
  assert.deepEqual(ids(rows), [["a", "all", "upload"]]);
  assert.equal(gone, 0);
  assert.equal(rows[0].narrow, "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 0fr)");
});

test("ribbonRows: ряд без обложек не теряет плиток", () => {
  const { rows, gone } = ribbonRows([], () => false, false);
  assert.deepEqual(ids(rows), [["upload"]]);
  assert.equal(gone, 0);
});
