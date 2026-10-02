// The planning agent's words for the build stage: which form a slide gets (a sketch the stage draws and the rail
// shows), what each phase is called on the stage, the rail's per-slide state and the log's lines. Pure functions, no
// React.
import type { AgentEvent } from "../types";
import { eventParts, phaseOfStep, withPhases, type PhaseKey } from "./agent";

export type SketchKind =
  | "cover" | "bars" | "hbars" | "pie" | "line" | "table" | "numbers" | "cards" | "list" | "timeline" | "compare"
  | "quote" | "image" | "agenda" | "section" | "text";

export interface Sketch { slide: number; kind: SketchKind; headline: string | null }

/** The big words of the stage per phase (and for the queue, before the first event). */
export const STAGE_TITLE: Record<PhaseKey | "queued", string> = {
  queued: "Готовлюсь к сборке",
  writer: "Пишу текст по теме",
  analyst: "Читаю ваш текст",
  architect: "Выстраиваю сюжет",
  designer: "Продумываю слайды",
  critic: "Сверяю план с текстом",
  revise: "Переделываю слабые места",
  layout: "Собираю в вашем шаблоне",
  check: "Проверяю каждое число",
};

/** Who speaks in the log («ДИЗАЙНЕР»). */
export const ROLE: Record<PhaseKey, string> = {
  writer: "автор", analyst: "аналитик", architect: "архитектор", designer: "дизайнер",
  critic: "критик", revise: "правка", layout: "вёрстка", check: "проверка",
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

/** The rail of one variant: a tile per slide (`count` at least, more when the designer planned more), its sketch,
 *  whether the critic left a note on it (and whether it was then revised), and whether it is laid out already. */
export function railSlides(events: AgentEvent[], variant: string | null, count: number, laid: number): RailSlide[] {
  const sketches = new Map<number, Sketch>();
  const marks = new Map<number, RailMark>();
  let top = count;
  for (const e of events) {
    if (e.variant != null && e.variant !== variant) continue;
    const n = e.slide;
    if (n === null || n === undefined || n < 1) continue;
    const step = (e.step ?? "").toLowerCase();
    const sk = sketchOf(e);
    if (sk) sketches.set(n, sk);
    if (step === "designer") top = Math.max(top, n);
    if (step === "critic" && marks.get(n) !== "fixed") marks.set(n, "note");
    if (step === "revise") marks.set(n, "fixed");
  }
  return Array.from({ length: Math.max(0, top) }, (_, i) => ({ n: i + 1, sketch: sketches.get(i + 1) ?? null, mark: marks.get(i + 1) ?? null, laid: i + 1 <= laid }));
}

/** «1:05» */
export const clock = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export interface LogLine { key: string; time: string | null; phase: PhaseKey; role: string; slide: number | null; text: string }

/** Every line of the agent, in order, as the log shows it. */
export function logLines(events: AgentEvent[]): LogLine[] {
  return withPhases(events).map((e, i) => ({
    key: e.seq !== undefined && e.seq !== null ? `#${e.seq}` : `${i}`,
    time: typeof e.t === "number" ? clock(e.t) : null,
    phase: e.phase,
    role: ROLE[phaseOfStep(e.step) ?? e.phase],
    slide: e.slide ?? null,
    text: eventParts(e).text,
  }));
}
