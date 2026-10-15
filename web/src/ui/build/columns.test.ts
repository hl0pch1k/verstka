import { test } from "node:test";
import assert from "node:assert/strict";
import { AGENT, AGENT_TIGHT, boardColumns, boardLabel, buildMorph, buildVars, failText, FAIL_ACTS_SHORT, FAIL_REASON, FAIL_TITLE, MIN_CARD, phaseFit, phaseLine2, phaseLines, PHASE_FLOOR, PHASE_NARROW, ROLE_TEXT, rollOf } from "./columns";
import { BOARD_GAP, STAGE_TITLE } from "../../lib/stage";

const A = 16 / 9;
/** Обёртка колоды при окне 1440 и 1280 (поля страницы 24 + 24); 1217 — 1280 с обычной полосой прокрутки страницы (15). */
const W1440 = 1392;
const W1280 = 1232;
const W1280S = 1217;
const PHASES = ["queued", "writer", "analyst", "architect", "designer", "critic", "revise", "layout", "check", "eyes", "done", "failed"] as const;

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
  // текст ролей ленты агента: 416 − 44 и 320 − 44 (V2: строки мысли переносятся в 276 px)
  assert.equal(m.textWide, 372);
  assert.equal(m.textNarrow, 276);
  assert.equal(m.left, 536);
  assert.equal(m.cell, 344);
  assert.equal(m.list, 832);
  assert.equal(m.words, true);
  assert.equal(m.font, 36);
  // коробка «Не получилось»: текст узкой — 536 − 24 − 24, широкой — 832 − 48 − 48; кнопки в ряд в обеих
  assert.equal(m.failNarrow, 488);
  assert.equal(m.failWide, 736);
  assert.equal(m.failShort, false);
});

test("buildMorph при 1280 — тесная колода: колонка агента 288, фаза мельче, сегменты с галочками, кнопки столбиком", () => {
  const m = buildMorph(W1280);
  assert.equal(m.tight, true);
  assert.equal(m.agent, AGENT_TIGHT);
  assert.equal(m.textNarrow, AGENT_TIGHT - ROLE_TEXT);
  assert.equal(m.textWide - m.textNarrow, AGENT - AGENT_TIGHT);
  assert.equal(m.left, 408);
  assert.equal(m.cell, 216);
  assert.equal(m.list, 672);
  assert.equal(m.words, false);
  assert.equal(m.font, 27.07);
  assert.equal(m.failNarrow, 360);
  assert.equal(m.failWide, 576);
  assert.equal(m.failShort, true);
});

test("buildMorph при 1280 с обычной полосой прокрутки (обёртка 1217): левая колонка 393, карточки 86, фаза 26.21", () => {
  const m = buildMorph(W1280S);
  assert.equal(m.tight, true);
  assert.equal(m.agent, AGENT_TIGHT);
  assert.equal(m.left, 393);
  assert.equal(m.cell, 201);
  assert.equal(m.list, 657);
  assert.equal(m.font, 26.21);
  assert.equal(m.words, false);
  // те же четыре колонки, что при закрытом помощнике: карточки 152 → 86 px
  const cols = boardColumns(m.list, 468, 12, A, MIN_CARD);
  assert.equal(cols, 4);
  assert.equal(Math.floor((m.list - 3 * BOARD_GAP) / cols), 152);
  assert.equal(Math.floor((m.left - 3 * BOARD_GAP) / cols), 86);
  // «Раскадровка» при трёх и двух вариантах уходит (393 < 398), при одном — остаётся; кнопки «Не получилось» в узкой —
  // столбиком
  assert.equal(boardLabel(m, 3), false);
  assert.equal(boardLabel(m, 2), false);
  assert.equal(boardLabel(m, 1), true);
  assert.equal(m.failShort, true);
  assert.equal(m.failWide, 561);
  assert.equal(m.failNarrow, 345);
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

test("phaseFit: короткая фаза мельчает до .75, длинная — чтобы встала в клетку (V2 `bdPhs`)", () => {
  const m = buildMorph(W1440);
  assert.equal(phaseFit("analyst", m.font, m.cell).scale, PHASE_NARROW);
  // V2: min(.75, 340 / 633) — «Смотрю на слайды целиком»
  assert.ok(Math.abs(phaseFit("eyes", m.font, m.cell).scale - 340 / 633) < 0.002);
  // фаза в узкой раскладке не шире своей клетки при 1440, 1280 и 1217 (однострочная — целиком, двухстрочная — её копия),
  // в широкой — тоже (колонка без места «03», поле 4 px)
  const W36: Record<string, number> = { queued: 433, eyes: 633, layout: 586, failed: 493, analyst: 273 };
  for (const wrap of [W1440, W1280, W1280S]) {
    const k = buildMorph(wrap);
    for (const [p, w36] of Object.entries(W36)) {
      const w = (w36 * k.font) / 36;
      const f = phaseFit(p as "eyes", k.font, k.cell);
      assert.ok((f.two ? f.width : w) * f.scale <= (f.two ? k.cell + 0.1 : k.cell - 3.5), `${wrap} ${p}`);
      assert.ok(w <= k.list - 192 - 4, `${wrap} ${p} широкая`);
    }
  }
});

test("phaseFit: в узкой раскладке фаза не мельче 18 px — ни при 1440, ни при 1280, ни при 1217", () => {
  for (const wrap of [W1440, W1280, W1280S, 1300, 1360]) {
    const m = buildMorph(wrap);
    for (const p of PHASES) {
      const f = phaseFit(p, m.font, m.cell);
      // не мельче 18 — кроме «Смотрю на слайды целиком» при обёртке 1217 (две строки при 18 не встают и во всю клетку)
      const floor = wrap === W1280S && p === "eyes" ? 16.8 : PHASE_FLOOR - 0.02;
      assert.ok(f.scale * m.font >= floor, `${wrap} ${p}: ${f.scale * m.font}`);
      assert.ok(f.scale <= PHASE_NARROW, `${wrap} ${p}`);
      if (f.two) {
        // две строки 18/24 — ровно ряд 48, по центру; копия свёрстана на клетку (до scale)
        assert.ok(f.line * f.scale <= 24.1 && Math.abs(f.line * PHASE_FLOOR / m.font - 24) < 0.1, `${wrap} ${p} строка`);
        assert.ok(Math.abs(f.top + f.line - 24) < 0.01, `${wrap} ${p} центр`);
        // длинная строка (замер, при кегле фазы) помещается в копию — строк ровно две, а не три — и после scale копия не
        // выходит из клетки
        const long = (phaseLine2(p) * m.font) / PHASE_FLOOR;
        assert.ok(long <= f.width + 0.01, `${wrap} ${p}: строка ${long} в копии ${f.width}`);
        assert.ok(f.width * f.scale <= m.cell + 0.01, `${wrap} ${p}: копия ${f.width * f.scale} в клетке ${m.cell}`);
        // где длинная строка встаёт с полем 4 px, поле остаётся и у копии
        if (long * f.scale <= m.cell - 4) assert.ok(f.width * f.scale <= m.cell - 4 + 0.01, `${wrap} ${p} поле`);
      }
    }
  }
});

test("phaseFit при 1440 — как V2 (в одну строку, не мельче 19.3 px); при 1280 длинные — в две строки 18 px", () => {
  const w = buildMorph(W1440);
  for (const p of PHASES) assert.equal(phaseFit(p, w.font, w.cell).two, false, p);
  assert.ok(Math.abs(phaseFit("eyes", w.font, w.cell).scale * w.font - 19.336) < 0.02);
  const n = buildMorph(W1280);
  const eyes = phaseFit("eyes", n.font, n.cell);
  assert.equal(eyes.two, true);
  assert.ok(Math.abs(eyes.scale * n.font - 18) < 0.02);
  // короткая встаёт в строку и мельчает до .75 (20.3 px)
  assert.deepEqual([phaseFit("analyst", n.font, n.cell).two, phaseFit("analyst", n.font, n.cell).scale], [false, PHASE_NARROW]);
  // «Смотрю на слайды» (214.5 px при 18) в клетку с полем (212) не встаёт — во всю клетку (216) встаёт; при обёртке 1217
  // (клетка 201) — мельчает до 16.9 px, предлог от слова не отрывается
  assert.ok(Math.abs(eyes.width * eyes.scale - n.cell) < 0.1);
  const s = buildMorph(W1280S);
  const e2 = phaseFit("eyes", s.font, s.cell);
  assert.ok(Math.abs(e2.scale * s.font - 16.87) < 0.02, String(e2.scale * s.font));
});

test("phaseLines: две строки фазы — явный перенос по обычному пробелу, короткий предлог не остаётся в конце первой", () => {
  const NB = "\u00a0";
  for (const p of PHASES) {
    const [a, b] = phaseLines(p);
    assert.ok(a && b, p);
    // строки вместе — то же название (короткие слова привязаны неразрывным пробелом), перенос — на месте обычного пробела
    assert.equal(`${a} ${b}`.replace(new RegExp(NB, "g"), " "), STAGE_TITLE[p].replace(new RegExp(NB, "g"), " "), p);
    assert.ok(!/(^|[\s\u00a0])(в|к|с|о|у|и|а|на|по|за|из|от|до|не|для)$/iu.test(a), `${p}: «${a}»`);
  }
  assert.deepEqual(phaseLines("eyes"), [`Смотрю на${NB}слайды`, "целиком"]);
  assert.deepEqual(phaseLines("check"), ["Проверяю", `шрифты и${NB}цвета`]);
  assert.deepEqual(phaseLines("critic"), ["Сверяю план", `с${NB}текстом`]);
});

test("строка агента, пришедшая посреди хода (B1): копии свёрстаны на ширину своей раскладки сразу и не меняют её", () => {
  const css = cssFile("build.css");
  // ширины копий стопок ленты агента — переменные в px, без доли клетки и без хода --hpp: у стопки, смонтированной посреди
  // хода, --hpp сразу на конце, и с шириной от живой клетки её текст переносился бы заново, пока колонка доезжает
  const sel = '.bd-two :is([data-tx="b-err"],[data-tx="b-hint"],[data-tx="b-line"]) > ';
  const at = (copy: string) => css.match(new RegExp(`${esc(sel + copy)}\\{width:([^}]*)\\}`))?.[1];
  const w1440 = buildMorph(W1440);
  assert.equal(at(".hp-txw"), `var(--bd-tw,${w1440.textWide}px) !important`);
  assert.equal(at(".hp-txn"), `var(--bd-tn,${w1440.textNarrow}px) !important`);
  // полоса прокрутки ленты не занимает места ни в одном движке: иначе, появившись посреди хода, она сузила бы колонку
  assert.ok(/\.bd-two :is\(\.bs-log,\.bk-log\)\{scrollbar-width:none\}/.test(css));
  assert.ok(/\.bd-two :is\(\.bs-log,\.bk-log\)::-webkit-scrollbar\{display:none\}/.test(css));
  for (const wrap of [W1440, W1280, W1280S]) {
    const m = buildMorph(wrap);
    // ширины — от окна (обёртки колоды), а не от колоды в кадре: в любом кадре хода строка получает те же
    const v = buildVars(m);
    assert.equal(v["--bd-tw"], `${AGENT - ROLE_TEXT}px`, `${wrap}`);
    assert.equal(v["--bd-tn"], `${m.agent - ROLE_TEXT}px`, `${wrap}`);
    assert.equal(v["--bd-an"], `${m.agent}px`, `${wrap}`);
  }
});

test("failText: при 1440 заголовок и причина — одной копией (как B-failed); при 1280 — двумя: широкая как B-failed, узкая — в клетку", () => {
  const w = failText(buildMorph(W1440));
  assert.equal(w.title.stack, false);
  assert.equal(w.reason.stack, false);
  assert.equal(w.reason.narrow, FAIL_REASON);
  for (const wrap of [W1280, W1280S]) {
    const m = buildMorph(wrap);
    const t = failText(m);
    assert.equal(t.title.stack, true);
    // закрыт помощник: заголовок в строку (B-failed), причина до 480
    assert.ok(t.title.wide >= FAIL_TITLE, `${wrap}`);
    assert.equal(t.reason.wide, FAIL_REASON);
    assert.equal(t.title.narrow, m.failNarrow);
    assert.equal(t.reason.narrow, m.failNarrow);
  }
});

test("кнопки «Не получилось» — в ряд в обеих раскладках: в узкой при 1280 и 1217 — с короткими подписями, они встают", () => {
  for (const wrap of [W1280, W1280S]) {
    const m = buildMorph(wrap);
    assert.equal(m.failShort, true);
    // ряд с короткими подписями — в коробке узкой раскладки (без полей)
    assert.ok(FAIL_ACTS_SHORT <= m.failNarrow, `${wrap}: ${m.failNarrow}`);
  }
  assert.equal(buildMorph(W1440).failShort, false);
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
function esc(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
