// The planning agent's words for the build page: which form a slide gets (the sketch its storyboard card draws), what
// each phase is called in the page's title, the storyboard's per-slide state. Pure functions, no React.
import type { AgentEvent } from "../types";
import { eventParts, type PhaseKey } from "./agent";

export type SketchKind =
  | "cover" | "bars" | "hbars" | "pie" | "line" | "table" | "numbers" | "cards" | "list" | "timeline" | "compare"
  | "quote" | "image" | "agenda" | "section" | "closing" | "code" | "text";

export interface Sketch { slide: number; kind: SketchKind; headline: string | null }

/** The form under a storyboard card («3  Столбчатая диаграмма»). */
export const KIND_LABEL: Record<SketchKind, string> = {
  cover: "Обложка",
  bars: "Столбчатая диаграмма",
  hbars: "Линейчатая диаграмма",
  pie: "Круговая диаграмма",
  line: "График",
  table: "Таблица",
  numbers: "Крупные числа",
  cards: "Карточки",
  list: "Список",
  timeline: "Этапы",
  compare: "Сравнение",
  quote: "Цитата",
  image: "Картинка и текст",
  agenda: "Содержание",
  section: "Раздел",
  closing: "Финальный слайд",
  code: "Код",
  text: "Текст",
};

/** The build's title per phase, as on the boards (V2 `bdData().PH`): the queue before the first event, the nine roles,
 *  then «готова» or «остановилась». A short preposition is bound to its word by a no-break space: a line never ends on
 *  «к», «по» or «с». */
export const STAGE_TITLE: Record<PhaseKey | "queued" | "done" | "failed", string> = {
  queued: "Готовлюсь к\u00a0сборке",
  writer: "Пишу текст по\u00a0теме",
  analyst: "Читаю текст",
  architect: "Выстраиваю сюжет",
  designer: "Продумываю слайды",
  critic: "Сверяю план с\u00a0текстом",
  revise: "Переделываю слайды",
  layout: "Раскладываю по\u00a0макетам",
  check: "Проверяю шрифты и\u00a0цвета",
  eyes: "Смотрю на\u00a0слайды целиком",
  done: "Презентация готова",
  failed: "Сборка остановилась",
};

/** The first «…» of a text, nested quotes kept («Компания «Ромашка» растёт»); null without a closed one. */
export function quoted(text: string): string | null {
  const start = text.indexOf("«");
  if (start < 0) return null;
  let depth = 0;
  for (let i = start; i < text.length; i++) {
    if (text[i] === "«") depth += 1;
    else if (text[i] === "»" && --depth === 0) return text.slice(start + 1, i).trim() || null;
  }
  return null;
}

/** The text without its «…» parts: what the agent says about the slide, not the slide's own words. */
export function stripQuoted(text: string): string {
  let depth = 0;
  let out = "";
  for (const ch of text) {
    if (ch === "«") depth += 1;
    else if (ch === "»") depth = Math.max(0, depth - 1);
    else if (depth === 0) out += ch;
  }
  return out;
}

// the first match wins: «горизонтальная диаграмма» before «диаграмма», «две диаграммы: круговая и …» reads as a pie
const KINDS: Array<[RegExp, SketchKind]> = [
  [/обложк|титул/i, "cover"],
  [/(?<![а-яё])код(?:а|ом)?(?![а-яё])/i, "code"],
  [/горизонтальн|линейчат/i, "hbars"],
  [/кругов|кольцев/i, "pie"],
  [/линейн|график|с областями/i, "line"],
  [/столбч|гистограмм|диаграмм/i, "bars"],
  [/таблиц/i, "table"],
  [/числ|цифр|показател|метрик/i, "numbers"],
  [/хронолог|таймлайн|процесс|шаг|этап/i, "timeline"],
  [/сравнен|колонк|до и после/i, "compare"],
  [/карточ/i, "cards"],
  [/список|пункт|тезис/i, "list"],
  [/цитат/i, "quote"],
  [/картинк|фото|иллюстрац|изображен/i, "image"],
  [/повестк|содержани/i, "agenda"],
  [/раздел/i, "section"],
  [/финальн/i, "closing"],
];

export function sketchKind(text: string): SketchKind {
  for (const [re, kind] of KINDS) if (re.test(text)) return kind;
  return "text";
}

// a revision line that is a form («Столбчатая диаграмма (2 категории).»), not a note on what was added
const FORM_FIRST = /^(?:обложк|титул|горизонтальн|линейчат|кругов|кольцев|линейн|график|столбч|гистограмм|диаграмм|две\s|два\s|таблиц|ряд\s|больш|крупн|хронолог|таймлайн|процесс|сравнен|карточ|список|цитат|повестк)/i;

/** The sketch of a designer's line (««Заголовок» — круговая диаграмма (5 категорий).») or of a revision that names
 *  its new form; null for anything else. */
export function sketchOf(e: AgentEvent): Sketch | null {
  if (e.slide === null || e.slide === undefined) return null;
  const step = (e.step ?? "").toLowerCase();
  if (step !== "designer" && step !== "revise") return null;
  const { text } = eventParts(e);
  if (step === "revise" && !FORM_FIRST.test(text.trim())) return null;
  return { slide: e.slide, kind: sketchKind(stripQuoted(text)), headline: quoted(text) };
}

export type RailMark = "note" | "fixed" | null;
export interface RailSlide { n: number; sketch: Sketch | null; mark: RailMark; laid: boolean }

/** The storyboard of one variant: a card per slide (`count` at least, more when the designer planned more — unless `exact`:
 *  the variant's plan has said how many slides it has), its sketch (a revision keeps the slide's headline), whether the
 *  critic left a note on it (and whether it was then revised), and whether it is laid out already. */
export function railSlides(events: AgentEvent[], variant: string | null, count: number, laid: number, exact = false): RailSlide[] {
  const sketches = new Map<number, Sketch>();
  const marks = new Map<number, RailMark>();
  let top = count;
  for (const e of events) {
    if (e.variant != null && e.variant !== variant) continue;
    const n = e.slide;
    if (n === null || n === undefined || n < 1) continue;
    const step = (e.step ?? "").toLowerCase();
    const sk = sketchOf(e);
    if (sk) sketches.set(n, { ...sk, headline: sk.headline ?? sketches.get(n)?.headline ?? null });
    if (step === "designer" && !exact) top = Math.max(top, n);
    if (step === "critic" && marks.get(n) !== "fixed") marks.set(n, "note");
    if (step === "revise") marks.set(n, "fixed");
  }
  return Array.from({ length: Math.max(0, top) }, (_, i) => ({ n: i + 1, sketch: sketches.get(i + 1) ?? null, mark: marks.get(i + 1) ?? null, laid: i + 1 <= laid }));
}

/** The storyboard's grid: the gap between cards (both ways), the caption under a card (its 8px gap and a 16px line),
 *  the card's narrowest and widest sizes, and the width a card stays readable at. */
export const BOARD_GAP = 16;
const CAPTION = 24;
const MIN_W = 150;
const MAX_W = 340;
const READABLE_W = 184;

/** The storyboard's columns: every slide in view at the largest size the box allows (no wider than MAX_W); when even
 *  MIN_W cannot show them all, the most columns that keep the cards readable (the list then scrolls). */
export function fitColumns(width: number, height: number, n: number, aspect: number): number {
  if (width <= 0 || n <= 0 || !(aspect > 0)) return 4;
  const cardW = (c: number) => (width - (c - 1) * BOARD_GAP) / c;
  const heightOf = (c: number) => {
    const rows = Math.ceil(n / c);
    return rows * (cardW(c) / aspect + CAPTION) + (rows - 1) * BOARD_GAP;
  };
  for (let c = 1; c <= 8; c++) {
    if (cardW(c) > MAX_W) continue;
    if (cardW(c) < MIN_W) break;
    if (heightOf(c) <= height) return c;
  }
  let c = 1;
  while (c < 8 && cardW(c + 1) >= READABLE_W) c++;
  return c;
}

/** «1:05» */
export const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
