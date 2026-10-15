import { test } from "node:test";
import assert from "node:assert/strict";
import { filesCols, filesVars, FILES_RIGHT, FILES_RIGHT_TIGHT, HELPER_COL, sheetMorph, SHEET_PAD, sumNarrowing, TIGHT_INNER } from "./sheetMorph";
import { textTight, TEXT_ROW } from "../layers/layerMorph";
import { stackHeights } from "../kit/Tx";

// обёртка колоды: 1392 при окне 1440, 1232 при 1280, 1217 — 1280 с обычной полосой прокрутки страницы (15 px)
const W1440 = 1392, W1280 = 1232, W1280S = 1217;

test("sheetMorph: при 1440 — раскладка V2 (лист 880 в узкой), при 1280 и 1217 — тесная колода; не измерена — не тесная", () => {
  assert.equal(sheetMorph(W1440).tight, false);
  assert.equal(sheetMorph(W1440).inner, 880);
  assert.equal(sheetMorph(W1280).tight, true);
  assert.equal(sheetMorph(W1280).inner, 720);
  assert.equal(sheetMorph(W1280S).tight, true);
  assert.equal(sheetMorph(W1280S).inner, 705);
  assert.equal(sheetMorph(0).tight, false);
  // порог: тесная — пока содержимое листа в узкой у́же TIGHT_INNER
  assert.equal(sheetMorph(TIGHT_INNER + HELPER_COL + SHEET_PAD).tight, false);
  assert.equal(sheetMorph(TIGHT_INNER + HELPER_COL + SHEET_PAD - 1).tight, true);
});

test("«Файлы»: правая колонка в px — в покое те же 50 % − 8 и 44,09 % − 8 (380 при 1440), что у V2; факт паспорта у́же на половину", () => {
  const m = filesCols(sheetMorph(W1440));
  assert.equal(m.wide, 0.5 * (W1440 - 96) - 8);
  assert.ok(Math.abs(m.narrow - 380) < 0.01);
  assert.ok(Math.abs(m.narrow - (FILES_RIGHT * 880 - 8)) < 0.001);
  assert.ok(Math.abs(m.fact - (m.wide - m.narrow) / 2) < 0.001);
  // тесная колода — 40 %: левой колонке (с тремя кнопками у файла) больше места
  const t = filesCols(sheetMorph(W1280));
  assert.ok(Math.abs(t.narrow - (FILES_RIGHT_TIGHT * 720 - 8)) < 0.001);
  assert.ok(720 - 16 - t.narrow > 720 - 16 - (FILES_RIGHT * 720 - 8));
  assert.deepEqual(filesVars(m), { "--dfw": `${m.wide}px`, "--dfn": `${m.narrow}px` });
  assert.deepEqual(filesVars(filesCols(sheetMorph(0))), {});
});

test("«Файлы» с обычной полосой прокрутки (15 px): колонки — половины сетки без полосы, как доли V2 от неё", () => {
  const bar = 15;
  const m = filesCols(sheetMorph(W1440), bar);
  const grid = W1440 - 96 - bar;
  // правая — 50 % − 8 сетки, левая (1fr) — остальное за вычетом зазора 16: поровну
  assert.ok(Math.abs(m.wide - (grid / 2 - 8)) < 0.001);
  assert.ok(Math.abs((grid - 16 - m.wide) - m.wide) < 0.001);
  assert.ok(Math.abs(m.narrow - (FILES_RIGHT * (880 - bar) - 8)) < 0.001);
});

test("sumNarrowing: колонка сводки «Качества» у́же на место помощника за вычетом того, что справа уходит", () => {
  // при 1440 с «Исправить всё автоматически» (кнопка 274.7) — 416 − 290.7 − 32 (значок у «Исправить отмеченные»)
  assert.ok(Math.abs(sumNarrowing({ allw: 274.7, cta: true, word: 0 }) - 93.3) < 0.001);
  // после исправления «Исправить всё…» нет; нет и исправимых — справа ничего не уходит
  assert.equal(sumNarrowing({ allw: null, cta: true, word: 0 }), HELPER_COL - 32);
  assert.equal(sumNarrowing({ allw: null, cta: false, word: 0 }), HELPER_COL);
  // тесная колода: ещё и слово «отмеченные»
  assert.ok(Math.abs(sumNarrowing({ allw: 274.7, cta: true, word: 95.5 }) - (93.3 - 95.5)) < 0.001);
});

test("textTight: шапка «Текста презентации» тесная, когда ряд без подписи не встаёт (при 1280 и 1217), при 1440 — как V2", () => {
  assert.equal(textTight(W1440), false);
  assert.equal(textTight(W1280), true);
  assert.equal(textTight(W1280S), true);
  assert.equal(textTight(0), false);
  assert.ok(W1440 - HELPER_COL - SHEET_PAD >= TEXT_ROW);
});

test("stackHeights: стопка — широкая копия с полями; в узкой не ниже широкой; узкая копия растёт до своей высоты", () => {
  assert.deepEqual(stackHeights(40, 60, 8), { hw: 48, hdd: 20, hn: 60 });
  // узкая копия ниже широкой (кегль 13 вместо 15) — стопка не проседает: широкая остаётся во весь рост
  assert.deepEqual(stackHeights(48, 24, 0), { hw: 48, hdd: 0, hn: 24 });
});

/** Текст CSS-файла из папки web (`npm test`). */
function cssFile(name: string): string {
  // без @types/node: модули node — через process.getBuiltinModule
  const proc = (globalThis as unknown as { process: { cwd(): string; getBuiltinModule(id: string): unknown } }).process;
  const fs = proc.getBuiltinModule("node:fs") as { existsSync(p: string): boolean; readFileSync(p: string, enc: "utf8"): string };
  const path = proc.getBuiltinModule("node:path") as { join(...p: string[]): string };
  let dir = proc.cwd();
  while (!fs.existsSync(path.join(dir, "src/styles", name)) && dir !== path.join(dir, "..")) dir = path.join(dir, "..");
  return fs.readFileSync(path.join(dir, "src/styles", name), "utf8");
}
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
/** `--hpd` стопок: широкая раскладка колоды V2 (`[data-tx="…"]{--hpd:…}`) и тесная (`.dd-tight …{--hpd:…}`). */
function hpdOf(css: string): { base: Record<string, number>; tight: Record<string, number> } {
  const base: Record<string, number> = {};
  const tight: Record<string, number> = {};
  for (const m of css.matchAll(/^\s*(\.dd-tight\s+)?(?::is\(([^)]*)\)|(\[data-tx="[\w-]+"\]))\{--hpd:(-?[\d.]+)px\}/gm)) {
    const names = (m[2] ?? m[3]).match(/[\w-]+(?="\])/g) ?? [];
    for (const n of names) (m[1] ? tight : base)[n] = parseFloat(m[4]);
  }
  return { base, tight };
}
/** Последнее число в px у дорожек правила `selector{grid-template-columns:…}`. */
function track(css: string, selector: string, i = -1): number {
  const m = css.match(new RegExp(`(?:^|[}\\s])${esc(selector)}\\{[^}]*?grid-template-columns:([^;}]*)`, "m"));
  if (!m) throw new Error(`нет правила ${selector}`);
  const px = [...m[1].matchAll(/(?<![\w(,])(\d+(?:\.\d+)?)px/g)].map((x) => parseFloat(x[1]));
  return px[i < 0 ? px.length + i : i];
}

test("--hpd стопок листа сходится с дорожками колонок: при 1440 (V2) и в тесной колоде (свои дорожки)", () => {
  const css = cssFile("details.css");
  const { base, tight } = hpdOf(css);
  const q2 = track(css, ".dd-g", -1);                                    // вторая колонка «Качества» и «Агента» — 526
  for (const [h, sel] of [[base, ".hp-nar .dd-g:not(.dw-g)"], [tight, ".hp-nar .dd-tight .dd-g:not(.dw-g)"]] as const) {
    const d2 = q2 - track(css, sel);                                     // на сколько у́же вторая колонка
    for (const n of ["q-acc", "q-ex1", "q-ex2", "q-eye", "q-kept", "q-row"]) assert.equal(h[n], d2, `${sel} ${n}`);
    assert.equal(h["q-msg"], HELPER_COL - d2, `${sel} q-msg`);          // первая — остальное
  }
  for (const [h, sel] of [[base, ".hp-nar #dd-panel-agent .dd-g"], [tight, ".hp-nar .dd-tight #dd-panel-agent .dd-g"]] as const) {
    const d2 = q2 - track(css, sel);
    for (const n of ["a-a", "a-hint2", "a-q"]) assert.equal(h[n], d2, `${sel} ${n}`);
    for (const n of ["a-sum", "a-tx", "a-head"]) assert.equal(h[n], HELPER_COL - d2, `${sel} ${n}`);
  }
  const w1 = track(css, ".dw-g", 0);                                     // первая колонка «Почему так» — 526
  for (const [h, sel] of [[base, ".hp-nar .dw-g"], [tight, ".hp-nar .dd-tight .dw-g"]] as const) {
    const d1 = w1 - track(css, sel, 0);
    for (const n of ["w-why", "w-dd", "w-form", "w-crit"]) assert.equal(h[n], d1, `${sel} ${n}`);
    for (const n of ["w-ok", "w-sim"]) assert.equal(h[n], HELPER_COL - d1, `${sel} ${n}`);
    // подписи образца — половина второй колонки, подписи макетов — треть
    assert.ok(Math.abs(h["w-cap"] - (HELPER_COL - d1) / 2) < 0.5, `${sel} w-cap`);
    assert.ok(Math.abs(h["w-alt"] - (HELPER_COL - d1) / 3) < 0.001, `${sel} w-alt`);
  }
  // «План»: колонка «О плане» 416 → 300 (тесная — 280); ряд плана: миниатюра 160 → 120, заголовок 232 → 160 (тесная — 200)
  const aside = 416, th = 160, hd = 232;
  const pa = track(css, ".hp-nar #dd-panel-plan"), pt = track(css, ".hp-nar .dd-tight #dd-panel-plan");
  for (const n of ["p-sub", "p-meta", "p-ctx", "p-ttl", "p-cb"]) {
    assert.equal(base[n], aside - pa, n);
    assert.equal(tight[n], aside - pt, n);
  }
  const row = track(css, ".hp-nar .dpl-row", 1), rowT = track(css, ".hp-nar .dd-tight .dpl-row", 1);
  assert.equal(track(css, ".hp-nar .dpl-row", 0), 120);
  assert.equal(base["p-hd"], hd - row);
  assert.equal(tight["p-hd"], hd - rowT);
  // тело ряда — остаток списка: список у́же на 416 − (416 − 300), миниатюра на 40, заголовок на 72
  assert.equal(base["p-body"], HELPER_COL - (aside - pa) - (th - 120) - (hd - row));
  // в тесной колоде тело уходит вместе со своей дорожкой — копии одной ширины
  assert.equal(tight["p-body"], 0);
  // «Шаблон»: «Правила оформления» при 1440 — 416 и в узкой (V2), в тесной колоде — у́же; строки правил и «Шрифты и поля»
  const rules = 416;
  for (const n of ["t-rule", "t-cb"]) {
    assert.equal(base[n], rules - track(css, ".hp-nar .dtp-g"), n);
    assert.equal(tight[n], rules - track(css, ".hp-nar .dd-tight .dtp-g"), n);
  }
});

test("--hpd стопок слоёв: «Текст презентации» — две колонки, «Мои презентации» — четыре; сетки те же в обеих раскладках", () => {
  const css = cssFile("layers.css");
  const { base } = hpdOf(css);
  assert.equal(base["t-sl"], HELPER_COL / 2);
  assert.equal(base["h-ttl"], HELPER_COL / 4);
  assert.ok(/\.gh-grid\{display:grid;grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/.test(css));
  // узкой раскладки сеток слоёв больше нет: те же четыре колонки сужаются (V2 версии 100)
  assert.ok(!/data-fit/.test(css));
});
