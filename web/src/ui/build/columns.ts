// Раскладка плиты «Сборки» без React: колонки раскадровки и всё, что зависит от ширины окна.
//
// Помощник сужает колоду (сетка 520 мс, закрытие 340), и плита перестраивается вместе с ней каждый кадр (V2 версии 100,
// build.css, блок «Колода, суженная помощником»): колонка агента 416 → 320 и зазор 48 → 24 — дорожки сетки, фаза мельчает
// transform'ом в своей клетке, раскадровка — те же колонки, сужаются, строки агента — стопки из двух копий. Здесь — то,
// что от ширины окна зависит: обе раскладки считаются сразу, по ширине обёртки колоды (`hp-wrap` не анимируется: закрыт
// помощник — колода во всю обёртку, открыт — на 416 у́же), и ставятся переменными CSS. Посреди хода ничего из этого не
// меняется — меняется только окно.
import { BOARD_GAP, fitColumns } from "../../lib/stage";
import type { BuildPhase } from "./buildView";

/** Самая узкая карточка доски (широкая раскладка). */
export const MIN_CARD = 150;

/** Колонки списка шириной `w` и высотой `h` для `n` слайдов с пропорциями `aspect`; не измерен — четыре. */
export function boardColumns(w: number, h: number, n: number, aspect: number, minCard: number): number {
  if (!(w > 0)) return 4;
  // четыре колонки доски, пока карточка не уже minCard; больше — когда иначе все слайды не видны
  const base = [4, 3, 2].find((c) => (w - (c - 1) * BOARD_GAP) / c >= minCard) ?? 1;
  return Math.max(base, fitColumns(w, h - 8, n, aspect));
}

/** Место помощника в обёртке колоды: плита 400 + зазор 16. */
const HELPER_COL = 416;
/** Поля плиты (48 + 48). */
const PLATE_PAD = 96;
/** Колонка агента и зазор: широкая раскладка (доска) и узкая (V2 версии 100). */
export const AGENT = 416;
export const AGENT_GAP = 48;
export const AGENT_NARROW = 320;
export const AGENT_GAP_NARROW = 24;
/** Узкая колонка агента в тесной колоде (окно около 1280; сайт): при 320 левой колонке не хватает места на заголовок
 *  раскадровки. Меньше нельзя: «Как думает агент» 18 px и «шаг 6 из 9» — 265 px. */
export const AGENT_TIGHT = 288;
/** Роль ленты агента: кружок 28 и зазор 16 — текст роли (мысли, подсказки, причина ошибки) у́же колонки на 44. */
export const ROLE_TEXT = 44;
/** Место «03» в ряду фазы: распорка 160 + зазор 32. */
const NUM3 = 192;
/** Ряд «Раскадровка» в узкой раскладке (замер при 1440): подпись со строкой хода и зазор 24 (137 px) и сегменты вариантов
 *  без слов хода, поля 8 — при 1, 2 и 3 вариантах. */
const SB_HEAD = [137, 272, 398, 520];
/** Слова хода в сегментах широкой раскладки («Структурный ✓ продумано») помещаются рядом с «Раскадровкой», пока
 *  содержимое плиты шире 1263 px; уже — остаются галочки (слова — в подсказке сегмента). */
const SEG_WORDS = 1263;
/** Кнопки коробки «Не получилось» в ряд: «Вернуться к тексту» 276, зазор 16, «Собрать ещё раз» 199 (замер). */
const FAIL_ACTS = 491;
/** «Не получилось собрать презентацию» в одну строку (20 px, замер) и причина — не шире 480 (B-failed). */
export const FAIL_TITLE = 470;
export const FAIL_REASON = 480;
/** Поля коробки «Не получилось»: широкая раскладка (B-failed) и узкая (V2: 48 → 24). */
const FAIL_PAD = 48;
const FAIL_PAD_NARROW = 24;
/** Кегль фазы — 36 px, пока самая длинная («Смотрю на слайды целиком», 633 px при 36) встаёт в свою клетку (колода −
 *  поля 96 − колонка агента 416 − зазор 48 − место «03» 192, поле 4 px, как у узкой); у́же — мельче, не меньше 24. */
const PHASE_MAX = 36;
const PHASE_MIN = 24;
const PHASE_LONGEST = 633; // PHW.eyes
/** Фаза в узкой раскладке мельчает до .75 (как названия шагов), длинная — сколько нужно, чтобы встать в свою клетку (V2). */
export const PHASE_NARROW = 0.75;
/** …но не мельче 18 px — кегля названия узкой колонки (у V2 при 1440 самая мелкая фаза — 19.3 px). Не встаёт в клетку и
 *  так — в узкой раскладке она в две строки 18/24 в ряду 48 (стопка из двух копий: однострочная гаснет, двухстрочная
 *  проявляется на месте; ни одна не переносится заново посреди хода). */
export const PHASE_FLOOR = 18;
const PHASE_ROW = 48;
const PHASE_LINE2 = 24;
/** Ширины фаз (lib/stage `STAGE_TITLE`) при 36 px — замер, V2 `PHW`. */
const PHW: Record<BuildPhase, number> = {
  queued: 433, writer: 431, analyst: 273, architect: 445, designer: 486, critic: 515, revise: 502, layout: 586,
  check: 608, eyes: 633, done: 450, failed: 493,
};
/** Фаза в две строки (при 36 px, замер): ширина длинной строки при лучшем переносе — с неразрывными пробелами
 *  STAGE_TITLE («на слайды») и без них. */
const PHW2: Record<BuildPhase, number> = {
  queued: 235, writer: 255, analyst: 147, architect: 289, designer: 303, critic: 293, revise: 320, layout: 320,
  check: 372, eyes: 429, done: 295, failed: 318,
};
const PHW2_LOOSE: Partial<Record<BuildPhase, number>> = { eyes: 380 };

export interface BuildMorph {
  /** Тесная колода (окно около 1280): узкой колонке агента 320 не хватает места — 288. */
  tight: boolean;
  /** Колонка агента в узкой раскладке. */
  agent: number;
  /** Ширина текста ролей ленты агента (копий её стопок) в широкой и узкой раскладке — постоянная на всём ходу, в px:
   *  строка, пришедшая посреди хода, сразу свёрстана на ширину своей раскладки и не переносится заново. */
  textWide: number;
  textNarrow: number;
  /** Левая колонка (фаза, раскадровка) в узкой раскладке. */
  left: number;
  /** Ширина раскадровки в широкой раскладке: по ней — колонки (в узкой те же, сужаются). */
  list: number;
  /** Кегль фазы — один в обеих раскладках (в узкой мельчает transform'ом). */
  font: number;
  /** Клетка фазы в узкой раскладке (левая колонка без места «03»). */
  cell: number;
  /** Слова хода в сегментах вариантов широкой раскладки (в узкой они гаснут и сжимаются всегда). */
  words: boolean;
  /** Ширина текста коробки «Не получилось» (без полей) в широкой и узкой раскладке. */
  failWide: number;
  failNarrow: number;
  /** Кнопки «Не получилось» в узкой раскладке — столбиком (в ряд не встают); в широкой — всегда в ряд, как B-failed. */
  failCol: boolean;
}

/** Обе раскладки плиты «Сборки» по ширине обёртки колоды `wrap` (0 — ещё не измерена: как на доске при 1440). */
export function buildMorph(wrap: number): BuildMorph {
  const w = wrap > 0 ? wrap : 1392;
  const deckN = w - HELPER_COL;
  const tight = deckN - PLATE_PAD - AGENT_NARROW - AGENT_GAP_NARROW < SB_HEAD[3];
  const agent = tight ? AGENT_TIGHT : AGENT_NARROW;
  const left = Math.max(0, deckN - PLATE_PAD - agent - AGENT_GAP_NARROW);
  const list = w - PLATE_PAD - AGENT - AGENT_GAP;
  return {
    tight,
    agent,
    textWide: AGENT - ROLE_TEXT,
    textNarrow: agent - ROLE_TEXT,
    left,
    list,
    font: Math.min(PHASE_MAX, Math.max(PHASE_MIN, Math.floor((PHASE_MAX * (list - NUM3 - 4)) / PHASE_LONGEST * 100) / 100)),
    cell: Math.max(0, left - NUM3),
    words: w - PLATE_PAD > SEG_WORDS,
    failWide: Math.max(0, list - 2 * FAIL_PAD),
    failNarrow: Math.max(0, left - 2 * FAIL_PAD_NARROW),
    failCol: FAIL_ACTS > left - 16,
  };
}

/** Заголовок и причина «Не получилось»: ширины копий в широкой и узкой раскладке; `stack` — в узкой они переносятся
 *  иначе, чем в широкой (две копии в одном месте); иначе — одна, шириной узкой (как при 1440: 488 ≥ 470). */
export function failText(m: BuildMorph): { title: { wide: number; narrow: number; stack: boolean }; reason: { wide: number; narrow: number; stack: boolean } } {
  return {
    title: { wide: m.failWide, narrow: m.failNarrow, stack: m.failNarrow < FAIL_TITLE },
    reason: { wide: Math.min(FAIL_REASON, m.failWide), narrow: Math.min(FAIL_REASON, m.failNarrow), stack: m.failNarrow < FAIL_REASON },
  };
}

/** «Раскадровка» и строка хода остаются в узкой раскладке рядом с `n` сегментами вариантов (иначе сжимаются и гаснут). */
export function boardLabel(m: BuildMorph, n: number): boolean {
  return m.left >= SB_HEAD[Math.max(0, Math.min(3, n))];
}

export interface PhaseFit {
  /** Во сколько раз фаза мельчает в узкой раскладке. */
  scale: number;
  /** В узкой раскладке — в две строки (18/24): копия свёрстана на ширину `width` и высоту строки `line` до scale, сдвиг
   *  `top` ставит две строки в ряд 48 по центру. */
  two: boolean;
  width: number;
  line: number;
  top: number;
  /** Две строки не встают в клетку с неразрывными пробелами фазы («Смотрю на слайды» при 1280 с обычной полосой
   *  прокрутки) — в двухстрочной копии они обычные (сайт: предлог может остаться в конце строки). */
  loose: boolean;
}

/** Фаза `phase` в узкой раскладке: мельчает до .75, длинная — чтобы встала в клетку `cell` (поле 4 px, V2 `bdPhs`), но не
 *  мельче 18 px; не встаёт и при 18 — в две строки по 18/24. `font` — кегль фазы (один в обеих раскладках). */
export function phaseFit(phase: BuildPhase, font: number, cell: number): PhaseFit {
  const w = (PHW[phase] * font) / PHASE_MAX;
  const floor = PHASE_FLOOR / font;
  const fit = (cell - 4) / w;
  const r3 = (n: number) => Math.round(n * 1000) / 1000;
  if (fit >= floor) return { scale: r3(Math.min(PHASE_NARROW, fit)), two: false, width: 0, line: 0, top: 0, loose: false };
  const line = (PHASE_LINE2 * font) / PHASE_FLOOR;
  const loose = (PHW2[phase] * PHASE_FLOOR) / PHASE_MAX > cell - 4 && PHW2_LOOSE[phase] !== undefined;
  return { scale: r3(floor), two: true, width: r3(((cell - 4) * font) / PHASE_FLOOR), line: r3(line), top: r3((PHASE_ROW - 2 * line) / 2), loose };
}

/** Ширина длинной строки фазы в две строки при 18 px (с неразрывными пробелами или без — `loose`). */
export function phaseLine2(phase: BuildPhase, loose: boolean): number {
  return (((loose ? PHW2_LOOSE[phase] : undefined) ?? PHW2[phase]) * PHASE_FLOOR) / PHASE_MAX;
}

/** Во сколько раз фаза мельчает в узкой раскладке (`phaseFit`). */
export function phaseScale(phase: BuildPhase, font: number, cell: number): number {
  return phaseFit(phase, font, cell).scale;
}

/** Сдвиг ленты агента: роли до `upto` включительно — над нижним краем. `heights` — высоты ролей, `gap` — зазор между
 *  ними, `top` — отступ сверху, `view` — сколько видно над нижним краем. Помощник меняет высоты ролей (стопки строк) и
 *  сдвиг одной кривой — сдвиг считается для обеих раскладок сразу (Roles). */
export function rollOf(heights: number[], gap: number, top: number, upto: number, view: number): number {
  if (upto < 0 || !heights.length) return 0;
  const k = Math.min(heights.length - 1, upto);
  let end = top;
  for (let i = 0; i <= k; i++) end += heights[i] + (i ? gap : 0);
  return Math.max(0, Math.round(end - view));
}
