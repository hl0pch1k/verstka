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
 *  раскадровки, и фаза мельчает до 10 px. Меньше нельзя: «Как думает агент» 18 px и «шаг 6 из 9» — 265 px. */
export const AGENT_TIGHT = 288;
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
/** Поля коробки «Не получилось» в узкой раскладке (V2: 48 → 24). */
const FAIL_PAD = 24;
/** Кегль фазы — 36 px, пока самая длинная («Смотрю на слайды целиком», 633 px при 36) встаёт в свою клетку (колода −
 *  поля 96 − колонка агента 416 − зазор 48 − место «03» 192, поле 4 px, как у узкой); у́же — мельче, не меньше 24. */
const PHASE_MAX = 36;
const PHASE_MIN = 24;
const PHASE_LONGEST = 633; // PHW.eyes
/** Фаза в узкой раскладке мельчает до .75 (как названия шагов), длинная — сколько нужно, чтобы встать в свою клетку (V2). */
export const PHASE_NARROW = 0.75;
/** Ширины фаз (lib/stage `STAGE_TITLE`) при 36 px — замер, V2 `PHW`. */
const PHW: Record<BuildPhase, number> = {
  queued: 433, writer: 431, analyst: 273, architect: 445, designer: 486, critic: 515, revise: 502, layout: 586,
  check: 608, eyes: 633, done: 450, failed: 493,
};

export interface BuildMorph {
  /** Тесная колода (окно около 1280): узкой колонке агента 320 не хватает места — 288. */
  tight: boolean;
  /** Колонка агента в узкой раскладке. */
  agent: number;
  /** На сколько колонка агента у́же в узкой раскладке — `--hpd` стопок ленты агента. */
  hpd: number;
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
  /** Текст коробки «Не получилось» — одной ширины в обеих раскладках (переносы не меняются на ходу): заголовок и причина. */
  failText: number;
  /** Кнопки «Не получилось» столбиком в обеих раскладках: в узкой в ряд не встают. */
  failCol: boolean;
}

/** Обе раскладки плиты «Сборки» по ширине обёртки колоды `wrap` (0 — ещё не измерена: как на доске при 1440). */
export function buildMorph(wrap: number): BuildMorph {
  const w = wrap > 0 ? wrap : 1392;
  const deckN = w - HELPER_COL;
  const tight = deckN - PLATE_PAD - AGENT_NARROW - AGENT_GAP_NARROW < SB_HEAD[3];
  const agent = tight ? AGENT_TIGHT : AGENT_NARROW;
  const left = Math.max(0, deckN - PLATE_PAD - agent - AGENT_GAP_NARROW);
  const inner = Math.max(0, left - 2 * FAIL_PAD);
  return {
    tight,
    agent,
    hpd: AGENT - agent,
    left,
    list: w - PLATE_PAD - AGENT - AGENT_GAP,
    font: Math.min(PHASE_MAX, Math.max(PHASE_MIN, Math.floor((PHASE_MAX * (w - PLATE_PAD - AGENT - AGENT_GAP - NUM3 - 4)) / PHASE_LONGEST * 100) / 100)),
    cell: Math.max(0, left - NUM3),
    words: w - PLATE_PAD > SEG_WORDS,
    failText: inner,
    failCol: FAIL_ACTS > left - 16,
  };
}

/** «Раскадровка» и строка хода остаются в узкой раскладке рядом с `n` сегментами вариантов (иначе сжимаются и гаснут). */
export function boardLabel(m: BuildMorph, n: number): boolean {
  return m.left >= SB_HEAD[Math.max(0, Math.min(3, n))];
}

/** Во сколько раз фаза `phase` мельчает в узкой раскладке: до .75, длинная — чтобы встала в клетку `cell` (поле 4 px). */
export function phaseScale(phase: BuildPhase, font: number, cell: number): number {
  const w = (PHW[phase] * font) / PHASE_MAX;
  return Math.round(Math.max(0.1, Math.min(PHASE_NARROW, (cell - 4) / w)) * 1000) / 1000;
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
