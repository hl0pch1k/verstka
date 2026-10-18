// Эскиз исправляемого слайда (R-fixing) — блоки, которые перестраиваются по шагам работы агента. Тот же тёмный эскиз
// формы слайда, что в раскадровке сборки (координаты 160×90, полоска заголовка, строки, плашки, акцент), но не
// рисунок по кругу: девять блоков от раскладки к раскладке — плашки отходят на новые места и меняют форму, строки
// переукладываются, один блок на шаге подсвечивается. Раскладки идут последовательностью: первая — форма самого
// слайда, дальше — другие формы по очереди, и каждый следующий круг чуть иной (ширины строк, какой блок подсвечен).
// Чистые функции — без React: шаг → где стоит каждый блок (FixSketch переводит это в transform).
import type { SketchKind } from "../../lib/stage";

/** Блоки эскиза: заголовок, четыре строки текста, три плашки (карточки, рамки), акцент. */
export const BLOCKS = ["head", "l1", "l2", "l3", "l4", "c1", "c2", "c3", "acc"] as const;
export type BlockId = (typeof BLOCKS)[number];
/** Блок в координатах эскиза 160×90: x, y, ширина, высота; `o` — видимость (0 — блок сложен и погашен). */
export interface Box { x: number; y: number; w: number; h: number; o: number }
export type Layout = Record<BlockId, Box>;

const b = (x: number, y: number, w: number, h: number, o = 1): Box => ({ x, y, w, h, o });

/** Раскладки — те же формы, что у эскизов раскадровки (ui/build/SlideSketch), сведённые к девяти блокам. */
export const LAYOUTS = {
  text: { head: b(12, 12, 84, 6), l1: b(12, 30, 136, 3), l2: b(12, 38, 128, 3), l3: b(12, 46, 132, 3), l4: b(12, 54, 104, 3), c1: b(12, 62, 40, 16, 0), c2: b(60, 62, 40, 16, 0), c3: b(108, 62, 40, 16, 0), acc: b(12, 68, 32, 5) },
  cards: { head: b(12, 12, 84, 6), l1: b(18, 52, 28, 3), l2: b(66, 52, 28, 3), l3: b(114, 52, 28, 3), l4: b(18, 60, 22, 3), c1: b(12, 28, 40, 50), c2: b(60, 28, 40, 50), c3: b(108, 28, 40, 50), acc: b(18, 35, 10, 6) },
  compare: { head: b(12, 12, 72, 6), l1: b(20, 46, 46, 3), l2: b(20, 54, 38, 3), l3: b(92, 46, 46, 3), l4: b(92, 54, 40, 3), c1: b(12, 28, 64, 50), c2: b(84, 28, 64, 50), c3: b(84, 28, 64, 50, 0), acc: b(20, 35, 30, 5) },
  pic: { head: b(92, 18, 48, 6), l1: b(92, 32, 56, 3), l2: b(92, 40, 50, 3), l3: b(92, 48, 54, 3), l4: b(92, 56, 36, 3), c1: b(12, 12, 68, 66), c2: b(18, 18, 56, 54, 0), c3: b(92, 66, 40, 8, 0), acc: b(52, 22, 12, 12) },
  numbers: { head: b(12, 12, 80, 6), l1: b(14, 52, 34, 3), l2: b(62, 52, 34, 3), l3: b(110, 52, 34, 3), l4: b(14, 60, 26, 3), c1: b(14, 34, 30, 7), c2: b(62, 34, 30, 7), c3: b(110, 34, 30, 7), acc: b(14, 70, 60, 3, 0) },
  steps: { head: b(12, 12, 60, 6), l1: b(18, 44, 18, 3), l2: b(56, 44, 18, 3), l3: b(94, 44, 18, 3), l4: b(12, 70, 84, 3), c1: b(12, 32, 30, 26), c2: b(50, 32, 30, 26), c3: b(88, 32, 30, 26), acc: b(126, 32, 22, 26) },
  list: { head: b(12, 12, 80, 6), l1: b(25, 30, 95, 3), l2: b(25, 42, 109, 3), l3: b(25, 54, 83, 3), l4: b(25, 66, 101, 3), c1: b(12, 28, 7, 7), c2: b(12, 40, 7, 7), c3: b(12, 52, 7, 7), acc: b(12, 64, 7, 7) },
  cover: { head: b(12, 34, 80, 6), l1: b(12, 46, 58, 6), l2: b(12, 60, 48, 3), l3: b(12, 68, 24, 3), l4: b(12, 76, 24, 3, 0), c1: b(100, 21, 48, 48), c2: b(110, 31, 28, 28, 0), c3: b(100, 21, 48, 48, 0), acc: b(12, 24, 16, 4) },
} satisfies Record<string, Layout>;
export type LayoutKey = keyof typeof LAYOUTS;
const KEYS = Object.keys(LAYOUTS) as LayoutKey[];

/** Форма слайда → раскладка, с которой эскиз начинается (самая похожая из девяти блоков). */
export function startLayout(kind: SketchKind): LayoutKey {
  switch (kind) {
    case "cover": case "section": case "closing": case "quote": return "cover";
    case "cards": return "cards";
    case "agenda": return "list";
    case "compare": case "table": return "compare";
    case "image": case "pie": return "pic";
    case "numbers": case "bars": case "hbars": case "line": return "numbers";
    case "timeline": return "steps";
    case "list": return "list";
    default: return "text";
  }
}

/** Порядок раскладок: с формы слайда, дальше остальные по кругу. */
export function layoutOrder(start: LayoutKey): LayoutKey[] {
  const i = KEYS.indexOf(start);
  return [...KEYS.slice(i), ...KEYS.slice(0, i)];
}

/** Раскладка шага `step`: та же форма, что у шага в порядке, — но каждый следующий круг строки чуть другой длины
 *  (короче на 0, 8 или 16 %), так что круг не повторяет предыдущий кадр в кадр. */
export function layoutAt(start: LayoutKey, step: number): Layout {
  const order = layoutOrder(start);
  const base = LAYOUTS[order[step % order.length]];
  const round = Math.floor(step / order.length);
  if (round === 0) return base;
  const out = { ...base };
  (["l1", "l2", "l3", "l4"] as const).forEach((id, k) => {
    const cut = (((round + k) % 3) * 8) / 100;
    out[id] = { ...base[id], w: Math.round(base[id].w * (1 - cut) * 10) / 10 };
  });
  return out;
}

/** Какой блок подсвечен на шаге: видимые блоки по очереди, со сдвигом на круг. */
export function litAt(start: LayoutKey, step: number): BlockId {
  const l = layoutAt(start, step);
  const seen = BLOCKS.filter((id) => l[id].o > 0);
  return seen[(step * 3 + Math.floor(step / KEYS.length)) % seen.length];
}

/** Шаг эскиза, мс: перестройка 720 мс и пауза, чтобы раскладку успели увидеть. */
export const STEP_MS = 1500;

/** transform блока: блок — во весь эскиз (100 % × 100 %) с началом в левом верхнем углу, сдвиг и масштаб — доли эскиза. */
export function blockTransform(x: Box): string {
  const f = (v: number) => Math.round(v * 10000) / 10000;
  return `translate(${f((x.x / 160) * 100)}%, ${f((x.y / 90) * 100)}%) scale(${f(x.w / 160)}, ${f(x.h / 90)})`;
}

/** Скругление блока в долях его же размера (`border-radius: X% / Y%`): блок масштабируется transform'ом, и скругление
 *  в px сплющилось бы — в долях оно после масштаба то, что нужно: у полосок — полукруглые концы (радиус — половина
 *  высоты), у плашек — 5 единиц эскиза. Эскиз 16:9 — единица по ширине и по высоте одна и та же. */
export function blockRadius(x: Box, bar: boolean): string {
  const r = bar ? x.h / 2 : Math.min(5, x.w / 2, x.h / 2);
  const f = (v: number) => Math.round(Math.min(50, (r / v) * 100) * 100) / 100;
  return `${f(x.w)}% / ${f(x.h)}%`;
}
