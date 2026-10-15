import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CARD_PAD_TIGHT, ctaShort, deckWidths, GAP_TIGHT, hintTail, moreCards, moreGrid, NAME_TIGHT, paramsRow,
  readyShort, ribbonRows, STEPPER, STEPPER_NARROW, STEPPER_TIGHT, VARIANT_NAME,
} from "./morph";
import { HELPER_COL } from "../deck/layout";

// обёртка колоды: 1392 при окне 1440, 1232 при 1280, 1217 — 1280 с обычной полосой прокрутки страницы (15 px)
const W1440 = 1392, W1280 = 1232, W1280S = 1217;
const tracks = (s: string) => s.split(/\s+(?![^(]*\))/);
const pxOf = (s: string) => parseFloat(s);
/** Самое длинное название варианта («Структурный», 16 px) — замер. */
const LONGEST_TITLE = 106;
/** Ширина ряда плиты 03 с полями клеток (колода − поля 96 − «03» 192 + поле последней клетки 16). */
const cells = (deck: number) => deck - 96 - 192 + 16;

test("deckWidths: открытый помощник сужает колоду на 416 (плита 400 + зазор 16); не измерена — как на доске", () => {
  assert.deepEqual(deckWidths(W1440), { wide: 1392, narrow: 976 });
  assert.deepEqual(deckWidths(W1280), { wide: 1232, narrow: 816 });
  assert.deepEqual(deckWidths(0), { wide: 1392, narrow: 976 });
});

test("paramsRow при 1440: дорожки V2 — степпер 216 → 200, переключатели 264 → 0, варианты 186.67 → 146.67", () => {
  const r = paramsRow(W1440, 3);
  assert.equal(r.switches, true);
  assert.equal(r.tight, false);
  // клетка = коробка + поле 16
  assert.deepEqual(tracks(r.wide), ["232px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "280px"]);
  assert.deepEqual(tracks(r.narrow), ["216px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "0px"]);
  assert.deepEqual(r.card, { wide: 186.667, narrow: 146.667 });
  assert.equal(r.shrink, 40);
});

test("paramsRow: число дорожек в обеих раскладках одно — сетка интерполируется; степпер остаётся в обеих", () => {
  for (const w of [W1440, W1280, W1280S, 1300, 1360]) for (const n of [1, 2, 3, 4]) {
    const r = paramsRow(w, n);
    assert.equal(tracks(r.wide).length, n + 2, `${w}/${n}`);
    assert.equal(tracks(r.narrow).length, n + 2, `${w}/${n}`);
    assert.equal(pxOf(tracks(r.wide)[0]), STEPPER + 16, `${w}/${n}`);
    assert.equal(pxOf(tracks(r.narrow)[0]), r.tight ? STEPPER_TIGHT + GAP_TIGHT : STEPPER_NARROW + 16, `${w}/${n}`);
  }
});

/** Края клеток короткого ряда в раскладке (от левого края ряда): степпер, варианты. */
function edges(stepper: number, card: number, gap: number, n: number): Array<[number, number]> {
  const out: Array<[number, number]> = [[0, stepper]];
  for (let i = 0; i < n; i++) { const l = stepper + gap + i * (card + gap); out.push([l, l + card]); }
  return out;
}

test("paramsRow при 1280 (1232 и 1217): тесный ряд — степпер на плите, три узкие карточки, название встаёт целиком", () => {
  for (const w of [W1280, W1280S]) {
    const r = paramsRow(w, 3);
    assert.equal(r.switches, false, `${w}`);
    assert.equal(r.tight, true, `${w}`);
    // со степпером 200 карточке с названием места нет — поэтому тесный ряд
    assert.ok((cells(deckWidths(w).narrow) - 216) / 3 - 16 < VARIANT_NAME, `${w}`);
    // ряд узкой раскладки: степпер 144 + 3 карточки через 12 — ровно ширина ряда
    const row = deckWidths(w).narrow - 96 - 192;
    assert.ok(Math.abs(STEPPER_TIGHT + 3 * (r.card.narrow + GAP_TIGHT) - row) < 0.01, `${w}`);
    // самое длинное название при .875 встаёт в карточку (поля 8), и его место — одной ширины в обеих раскладках
    assert.ok(LONGEST_TITLE * NAME_TIGHT <= r.card.narrow - 2 * CARD_PAD_TIGHT, `${w}: ${r.card.narrow}`);
    assert.ok(r.title >= LONGEST_TITLE && r.title * NAME_TIGHT <= r.card.narrow - 2 * CARD_PAD_TIGHT + 0.01, `${w}: ${r.title}`);
    assert.ok(r.title <= r.card.wide - 60, `${w}`);
  }
  // при 1280 карточки 116 (в пределах 116–124), при 1217 — 111
  assert.equal(paramsRow(W1280, 3).card.narrow, 116);
  assert.equal(paramsRow(W1280S, 3).card.narrow, 111);
});

test("paramsRow: ряд сужается одним ходом — каждый край клетки идёт влево, и не дальше края колоды", () => {
  for (const w of [W1440, W1280, W1280S, 1300]) {
    const r = paramsRow(w, 3);
    const sw = r.switches ? 264 : 0;
    const a = edges(STEPPER, r.card.wide, 16, 3);
    const b = edges(r.tight ? STEPPER_TIGHT : STEPPER_NARROW, r.card.narrow, r.tight ? GAP_TIGHT : 16, 3);
    for (let i = 0; i < a.length; i++) {
      for (const k of [0, 1]) {
        const d = b[i][k] - a[i][k];
        assert.ok(d <= 0.01 && -d <= 416 + 0.01, `${w} клетка ${i} край ${k}: ${d}`);
      }
    }
    // правый край последней карточки — у края ряда в обеих раскладках (переключатели справа — свои дорожки)
    assert.ok(Math.abs(a[3][1] + (sw ? sw + 16 : 0) - (w - 96 - 192)) < 0.01, `${w}`);
    assert.ok(Math.abs(b[3][1] - (w - 416 - 96 - 192)) < 0.01, `${w}`);
  }
});

test("paramsRow: переключатели уходят ровно там, где варианту меньше 173 px (колода 1350)", () => {
  assert.equal(paramsRow(1351, 3).switches, true);
  assert.equal(paramsRow(1350, 3).switches, false);
});

test("moreGrid при 1440: три колонки в обеих раскладках, подсказка варианта шире в узкой (миниатюра ушла) — роли копий наоборот", () => {
  const m = moreGrid(W1440, 3, false);
  assert.equal(m.tight, false);
  assert.equal(m.thumb, 156);
  assert.equal(m.vhint, -33.333);
  assert.equal(tracks(m.r1Wide).length, 3);
  assert.equal(tracks(m.r1Narrow).length, 3);
  assert.equal(pxOf(tracks(m.r1Narrow)[0]), pxOf(tracks(m.r1Narrow)[2]));
});

test("moreGrid при 1280 (1232 и 1217): тесная — степпер слайдов по содержимому; подсказка варианта у́же в узкой", () => {
  for (const w of [W1280, W1280S]) {
    const m = moreGrid(w, 3, true);
    assert.equal(m.tight, true);
    assert.equal(m.thumb, 112);
    const n = tracks(m.r1Narrow).map(pxOf);
    assert.equal(n[2], 168);
    // первый ряд — во всю ширину «Все параметры» (колода − 288) в обеих раскладках
    assert.ok(Math.abs(n[0] + n[1] + n[2] + 32 - (deckWidths(w).narrow - 288)) < 0.01);
    assert.ok(Math.abs(tracks(m.r1Wide).map(pxOf).reduce((a, b) => a + b) + 32 - (w - 288)) < 0.01);
    // в узкой у карточки нет миниатюры, но она на 140 px у́же — подсказка всё равно у́же: обычные роли копий
    assert.ok(m.vhint > 0, `${w}`);
  }
});

test("moreCards: карточки заполняют ряд «Все параметры», подсказка — колонка текста карточки; --hpd подсказки — их разница", () => {
  for (const w of [W1440, W1280, W1280S]) for (const short of [false, true]) {
    const c = moreCards(w, 3, short);
    const m = moreGrid(w, 3, short);
    for (const k of ["wide", "narrow"] as const) {
      const row = deckWidths(w)[k] - 288;
      assert.ok(Math.abs(3 * c[k].card + 32 - row) < 0.01, `${w} ${k}`);
      assert.ok(c[k].hint > 0 && c[k].hint < c[k].card, `${w} ${k}`);
    }
    // в широкой рядом с подсказкой миниатюра: колонка текста меньше карточки на поля, миниатюру и зазор
    assert.ok(Math.abs(c.wide.card - c.wide.hint - (32 + m.thumb + 16)) < 0.01, `${w}`);
    assert.ok(Math.abs(m.vhint - (c.wide.hint - c.narrow.hint)) < 0.01, `${w}`);
  }
});

/** create.css: `--hpd` стопок, заданный числом (на сколько клетка у́же в узкой раскладке). Файл — из папки web (`npm test`). */
function cssHpd(): Record<string, number> {
  // без @types/node: модули node — через process.getBuiltinModule
  const proc = (globalThis as unknown as { process: { cwd(): string; getBuiltinModule(id: string): unknown } }).process;
  const fs = proc.getBuiltinModule("node:fs") as { existsSync(p: string): boolean; readFileSync(p: string, enc: "utf8"): string };
  const path = proc.getBuiltinModule("node:path") as { join(...p: string[]): string };
  let dir = proc.cwd();
  while (!fs.existsSync(path.join(dir, "src/styles/create.css")) && dir !== path.join(dir, "..")) dir = path.join(dir, "..");
  const css = fs.readFileSync(path.join(dir, "src/styles/create.css"), "utf8");
  const out: Record<string, number> = {};
  for (const m of css.matchAll(/\[data-tx="([\w-]+)"\]\{--hpd:(-?[\d.]+)px/g)) out[m[1]] = parseFloat(m[2]);
  return out;
}

test("--hpd стопок в create.css сходится с геометрией обеих раскладок при любой ширине окна", () => {
  const hpd = cssHpd();
  for (const w of [W1440, 1360, 1300, W1280, W1280S]) {
    const d = deckWidths(w);
    // поле и заметка «Улучшить готовую» — во всю ширину тела шага: у́же ровно на место помощника
    assert.equal(hpd["c-note"], d.wide - d.narrow, `${w} c-note`);
    assert.equal(hpd["c-ta"], HELPER_COL, `${w} c-ta`);
  }
  // коробки переключателей «Все параметры» — треть ряда: у́же на треть места помощника (пока раскладка не тесная)
  for (const w of [W1440, 1360]) {
    const d = deckWidths(w);
    const third = (d.wide - d.narrow) / 3;
    assert.ok(Math.abs(hpd["c-swt"] - third) < 0.001, `${w} c-swt`);
    assert.ok(Math.abs(hpd["c-swd"] - third) < 0.001, `${w} c-swd`);
  }
  // подсказка варианта: в CSS — значение при 1440 (поверх него — переменная morph.ts при любой ширине)
  assert.equal(hpd["c-vhint"], moreGrid(W1440, 3, false).vhint);
});

test("подписи по ширине: при 1440 — полные, при 1280 (и 1217) — короткие; перечень у «Это тема…» — пока колода шире 1300", () => {
  assert.equal(readyShort(W1440), false);
  assert.equal(ctaShort(W1440), false);
  for (const w of [W1280, W1280S]) {
    assert.equal(readyShort(w), true);
    assert.equal(ctaShort(w), true);
    assert.equal(hintTail(w), false);
  }
  assert.equal(hintTail(W1440), true);
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
