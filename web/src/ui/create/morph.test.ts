import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ctaShort, deckWidths, hintTail, HELPER_COL, listCard, moreCards, moreGrid, moreThird, paramsRow, readyShort, ribbonRows,
  STEPPER, STEPPER_NARROW, VARIANT_NAME,
} from "./morph";

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

test("paramsRow при 1440: дорожки V2 — степпер 216 → 200, переключатели 264 → 0, варианты карточками 186.67 → 146.67", () => {
  const r = paramsRow(W1440, 3);
  assert.equal(r.switches, true);
  assert.equal(r.list, null);
  // клетка = коробка + поле 16
  assert.deepEqual(tracks(r.wide), ["232px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "280px"]);
  assert.deepEqual(tracks(r.narrow), ["216px", "minmax(0, 1fr)", "minmax(0, 1fr)", "minmax(0, 1fr)", "0px"]);
  assert.equal(r.shrink, 40);
});

test("paramsRow: число дорожек в обеих раскладках одно — сетка интерполируется; степпер остаётся в обеих", () => {
  for (const w of [W1440, W1280, W1280S, 1300, 1360]) for (const n of [1, 2, 3, 4]) {
    const r = paramsRow(w, n);
    assert.equal(tracks(r.wide).length, tracks(r.narrow).length, `${w}/${n}`);
    assert.equal(tracks(r.wide).length, r.list ? 3 : n + 2, `${w}/${n}`);
    assert.equal(pxOf(tracks(r.wide)[0]), STEPPER + 16, `${w}/${n}`);
    assert.equal(pxOf(tracks(r.narrow)[0]), STEPPER_NARROW + 16, `${w}/${n}`);
  }
});

test("paramsRow при 1280 (1232 и 1217): степпер остаётся на плите, варианты в узкой — списком, название встаёт целиком", () => {
  for (const w of [W1280, W1280S]) {
    const r = paramsRow(w, 3);
    assert.equal(r.switches, false, `${w}`);
    const g = r.list;
    assert.ok(g, `${w}: список`);
    if (!g) continue;
    // карточками рядом со степпером 200 названию места нет — поэтому список
    const card = (cells(deckWidths(w).narrow) - 216) / 3 - 16;
    assert.ok(card < VARIANT_NAME, `${w}`);
    // одна колонка строк по 24 через 8 — ровно ряд 88
    assert.equal(g.cols, 1);
    assert.equal(3 * g.pillH + 2 * 8, 88);
    // название не обрезается ни в карточке, ни в строке, и ширина его места одна на всём ходу
    assert.ok(g.title >= LONGEST_TITLE, `${w}: ${g.title}`);
    for (const k of ["wide", "narrow"] as const) {
      const c = listCard(g, 0)[k];
      // название не заходит на галочку справа (зазор 8) ни в карточке, ни в строке
      assert.ok(c.text.x + g.title + 8 <= c.box.x + 0.01, `${w} ${k}`);
    }
  }
});

test("listCard: карточки широкой раскладки — ряд во всю дорожку вариантов; строки узкой — столбиком в её пределах", () => {
  for (const w of [W1280, W1280S]) for (const n of [3, 4]) {
    const g = paramsRow(w, n).list;
    if (!g) continue;
    const block = (deck: number, st: number) => cells(deck) - st - 16;
    const bw = block(deckWidths(w).wide, STEPPER + 16), bn = block(deckWidths(w).narrow, STEPPER_NARROW + 16);
    const cs = Array.from({ length: n }, (_, i) => listCard(g, i));
    // широкая: подряд через 16, последняя — у края дорожки
    for (let i = 1; i < n; i++) assert.ok(Math.abs(cs[i].wide.x - (cs[i - 1].wide.x + cs[i - 1].wide.w + 16)) < 0.01, `${w}/${n}/${i}`);
    assert.ok(Math.abs(cs[n - 1].wide.x + cs[n - 1].wide.w - bw) < 0.01, `${w}/${n}`);
    // узкая: в пределах дорожки и ряда 88, без наложений
    for (const c of cs) {
      assert.ok(c.narrow.x + c.narrow.w <= bn + 0.01 && c.narrow.y + c.narrow.h <= 88 + 0.01, `${w}/${n}`);
      // галочка и название — внутри своей карточки в обеих раскладках
      for (const k of ["wide", "narrow"] as const) {
        const b = c[k];
        assert.ok(b.box.x >= 0 && b.box.x + 20 <= b.w && b.box.y >= 0 && b.box.y + 20 <= b.h, `${w}/${n} ${k} галочка`);
        assert.ok(b.text.x + g.title <= b.w + 0.01 && b.text.y >= 0 && b.text.y + 24 <= b.h + 0.01, `${w}/${n} ${k} название`);
      }
    }
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const a = cs[i].narrow, b = cs[j].narrow;
      const sep = a.x + a.w <= b.x + 0.01 || b.x + b.w <= a.x + 0.01 || a.y + a.h <= b.y + 0.01 || b.y + b.h <= a.y + 0.01;
      assert.ok(sep, `${w}/${n}: ${i} и ${j}`);
    }
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
    const t = moreThird(w);
    assert.ok(Math.abs(hpd["c-swt"] - (t.wide - t.narrow)) < 0.001, `${w} c-swt`);
    assert.ok(Math.abs(hpd["c-swd"] - (t.wide - t.narrow)) < 0.001, `${w} c-swd`);
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
