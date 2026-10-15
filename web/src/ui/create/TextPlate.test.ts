import { test } from "node:test";
import assert from "node:assert/strict";
import { caretShown, lineStart, scrollFor, spotAt, type CopyLines } from "./TextPlate";

/** Копия поля с переносом по `per` знаков (перевод строки — в конце своей строки) — как широкая и узкая копии «О чём
 *  презентация»: строка 24 px, отступ снизу 24, окно 132 (четыре с половиной строки). */
function copy(text: string, per: number, height = 132): CopyLines {
  const lines: number[] = [];
  let k = 0, col = 0;
  for (const ch of text) {
    if (ch !== "\n" && col === per) {
      k++;
      col = 0;
    }
    lines.push(k);
    if (ch === "\n") {
      k++;
      col = 0;
    } else col++;
  }
  lines.push(k); // место за последним знаком — курсор в конце
  const lh = 24, pad = 0;
  return { n: text.length, line: (i) => lines[Math.min(Math.max(0, i), text.length)], lh, pad, height, max: Math.max(0, pad + (k + 1) * lh + 24 - height) };
}

const TEXT = Array.from({ length: 30 }, (_, i) => `Абзац ${i + 1}. ${"Слово ".repeat(5 + (i % 7))}`).join("\n");
const WIDE = copy(TEXT, 50);
const NARROW = copy(TEXT, 30);
/** Строка поля, которая наверху при прокрутке `top`, — и её знаки. */
const topLine = (c: CopyLines, top: number) => Math.floor((top - c.pad) / c.lh);
const charsOf = (c: CopyLines, k: number) => [lineStart(c, k), lineStart(c, k + 1) - 1];

test("lineStart: первый знак строки; строка 0 и выше — начало текста, за концом — место за последним знаком", () => {
  const c = copy("abcdef\nxy", 3);
  // строки: abc | def\n | xy
  assert.equal(lineStart(c, -1), 0);
  assert.equal(lineStart(c, 0), 0);
  assert.equal(lineStart(c, 1), 3);
  assert.equal(lineStart(c, 2), 7);
  assert.equal(lineStart(c, 9), 9);
});

test("spotAt: верх поля — первый знак верхней строки и на сколько она ушла вверх", () => {
  assert.deepEqual(spotAt(WIDE, 0), { at: 0, dy: 0 });
  const k = 7;
  assert.deepEqual(spotAt(WIDE, k * 24), { at: lineStart(WIDE, k), dy: 0 });
  assert.deepEqual(spotAt(WIDE, k * 24 + 10), { at: lineStart(WIDE, k), dy: 10 });
});

test("scrollFor: входящая копия другой ширины встаёт на то же место текста — её верхняя строка держит первый знак уходящей", () => {
  for (const [from, to] of [[WIDE, NARROW], [NARROW, WIDE]] as const) {
    for (let top = 0; top <= from.max; top += 7) {
      const spot = spotAt(from, top);
      const st = scrollFor(to, spot);
      if (st === to.max && st < to.pad + to.line(spot.at) * to.lh + spot.dy) continue; // упёрлась в конец — ниже
      const [a, b] = charsOf(to, topLine(to, st));
      assert.ok(a <= spot.at && spot.at <= b, `top ${top}: знак ${spot.at} вне верхней строки [${a}, ${b}]`);
      assert.equal(st - to.line(spot.at) * to.lh, spot.dy, "строка ушла вверх на те же пиксели");
    }
  }
});

test("scrollFor: прокрутка до конца — верх узкой копии на той же строке, что и у широкой (а не начало текста)", () => {
  const spot = spotAt(WIDE, WIDE.max);
  assert.ok(spot.at > 0);
  const st = scrollFor(NARROW, spot);
  assert.ok(st > 0 && st <= NARROW.max);
  assert.equal(lineStart(NARROW, topLine(NARROW, st)) <= spot.at, true);
  assert.equal(lineStart(NARROW, topLine(NARROW, st) + 1) > spot.at, true);
});

test("scrollFor: то же место текста в своей же копии — та же прокрутка (смена туда и обратно ничего не сдвигает)", () => {
  for (const c of [WIDE, NARROW]) for (let top = 0; top <= c.max; top += 5) assert.equal(scrollFor(c, spotAt(c, top)), top);
});

test("scrollFor: прокрутка в пределах [0, max]", () => {
  const short = copy("коротко", 30);
  assert.equal(scrollFor(short, { at: 5, dy: 0 }), 0);
  assert.equal(scrollFor(NARROW, { at: TEXT.length, dy: 20 }), NARROW.max);
});

test("caretShown и scrollFor: курсор, видный в уходящей копии, не уходит под низ входящей", () => {
  const top = 10 * 24;
  // курсор на последней целой строке широкого окна: в узкой копии он ниже окна
  const caret = lineStart(WIDE, 13) + 5;
  assert.equal(caretShown(WIDE, top, caret), true);
  assert.equal(caretShown(WIDE, top, lineStart(WIDE, 20)), false);
  const spot = spotAt(WIDE, top);
  const plain = scrollFor(NARROW, spot);
  assert.equal(caretShown(NARROW, plain, caret), false);
  const kept = scrollFor(NARROW, spot, caret);
  assert.equal(caretShown(NARROW, kept, caret), true);
  // ровно настолько, чтобы строка курсора встала низом к низу окна
  assert.equal(kept + NARROW.height, (NARROW.line(caret) + 1) * 24);
  // курсор и так виден — прокрутка та же, что без него
  assert.equal(scrollFor(NARROW, spot, lineStart(WIDE, 10)), plain);
});
