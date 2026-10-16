// Мини-график варианта визуализации в «Почему так» (V2 v105 `dsMini`): эскиз 160×90 в палитре шаблона — слои сетки,
// подписей (серые штрихи), заливок (светлая, основная, полупрозрачная), линии, кольца, акцента, пунктира и белых
// разделителей. Рисуется из данных самого слайда (OutlineSlide.content: ряды графика, таблица, карточки) — числа не
// придумываются: столбцы, линия, сектора — это значения слайда в форме варианта; таблица, карточки и страницы — только
// их строение (сколько строк, колонок, карточек). Чего в данных нет, того на эскизе нет. Чистые функции, без React.
import type { OutlineSlide, SlideData, TemplateManifest, VizKind, VizOption } from "../types";

/** Слои эскиза — пути `d` в координатах 160×90 (пусто — слоя нет). Порядок отрисовки — как здесь. */
export interface MiniLayers {
  grid: string; light: string; txt: string; ringL: string; ring2: string; ring: string; half: string; main: string;
  sep: string; line: string; acc: string; dash: string;
}

/** Что эскиз берёт из слайда. */
export interface MiniSource {
  /** Ряды значений (первый — главный); null — пропуск (разрыв линии, пустое место столбца). */
  series: (number | null)[][];
  /** Точки рассеяния. */
  xy: { x: number[]; y: number[] } | null;
  /** Строк и колонок таблицы (у графика — категории и колонка подписей с рядами). */
  rows: number;
  cols: number;
  /** Карточек показателей (у слайда-карточек — сколько их; иначе 0 — эскиз карточек по строению). */
  cards: number;
  /** Выбросов у набора: у гистограммы — точки за краем, как на слайде. */
  outliers: number;
  /** В таблице последняя строка — итог «Остальные». */
  restRow: boolean;
}

const EMPTY: MiniLayers = { grid: "", light: "", txt: "", ringL: "", ring2: "", ring: "", half: "", main: "", sep: "", line: "", acc: "", dash: "" };

const f = (n: number) => String(Math.round(n * 10) / 10);
/** Скруглённый прямоугольник. */
const rr = (x: number, y: number, w: number, h: number, q = 2) => {
  const k = Math.max(0, Math.min(q, w / 2, h / 2));
  return `M${f(x + k)} ${f(y)}H${f(x + w - k)}A${f(k)} ${f(k)} 0 0 1 ${f(x + w)} ${f(y + k)}V${f(y + h - k)}A${f(k)} ${f(k)} 0 0 1 ${f(x + w - k)} ${f(y + h)}H${f(x + k)}A${f(k)} ${f(k)} 0 0 1 ${f(x)} ${f(y + h - k)}V${f(y + k)}A${f(k)} ${f(k)} 0 0 1 ${f(x + k)} ${f(y)}Z`;
};
const hl = (x1: number, y: number, x2: number) => `M${f(x1)} ${f(y)}H${f(x2)}`;
const vl = (x: number, y1: number, y2: number) => `M${f(x)} ${f(y1)}V${f(y2)}`;
const ci = (cx: number, cy: number, q: number) => `M${f(cx - q)} ${f(cy)}a${f(q)} ${f(q)} 0 1 0 ${f(2 * q)} 0a${f(q)} ${f(q)} 0 1 0 ${f(-2 * q)} 0Z`;
const poly = (pts: [number, number][]) => (pts.length ? `M${pts.map((p) => `${f(p[0])} ${f(p[1])}`).join("L")}` : "");
const at = (cx: number, cy: number, q: number, a: number): [number, number] => [cx + q * Math.sin(a * 2 * Math.PI), cy - q * Math.cos(a * 2 * Math.PI)];
const arc = (cx: number, cy: number, q: number, a0: number, a1: number) => {
  const s = at(cx, cy, q, a0);
  const e = at(cx, cy, q, Math.min(a1, a0 + 0.9999));
  return `M${f(s[0])} ${f(s[1])}A${f(q)} ${f(q)} 0 ${a1 - a0 > 0.5 ? 1 : 0} 1 ${f(e[0])} ${f(e[1])}`;
};
const sector = (cx: number, cy: number, q: number, a0: number, a1: number) => `${arc(cx, cy, q, a0, a1).replace(/^M/, `M${f(cx)} ${f(cy)}L`)}Z`;

const BASE = 76;
const base = hl(14, BASE, 146);
const grid3 = base + hl(14, 52, 146) + hl(14, 28, 146);

/** Число из подписи слайда: «1 433», «212,4», «1,24 млрд ₽», «+23%», «−8%»; нет числа — null. */
export function numberOf(text: string | null | undefined): number | null {
  const t = (text ?? "").replace(/(\d)[\s\u00a0\u202f](?=\d{3}(?!\d))/g, "$1").replace(/−/g, "-");
  const m = t.match(/[-+]?\d+(?:[.,]\d+)?/);
  if (!m) return null;
  const n = Number(m[0].replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

/** Колонка таблицы с числами (не первая — она подписи): первая, где числа почти во всех строках. */
function numericColumn(rows: string[][], cols: number): number | null {
  for (let j = 1; j < cols; j++) {
    const nums = rows.filter((r) => numberOf(r[j]) !== null).length;
    if (rows.length && nums >= Math.ceil(rows.length * 0.7)) return j;
  }
  return null;
}

/** Данные эскиза — из содержимого слайда (график, таблица или карточки) и профиля набора. */
export function miniSource(slide: Pick<OutlineSlide, "content"> | null | undefined, data: Pick<SlideData, "outliers" | "aggregation"> | null | undefined): MiniSource {
  const c = slide?.content;
  const out: MiniSource = { series: [], xy: null, rows: 0, cols: 0, cards: 0, outliers: data?.outliers?.length ?? 0, restRow: /остальн/i.test(data?.aggregation ?? "") };
  const chart = c?.chart;
  if (chart) {
    out.series = (chart.series ?? []).map((s) => s.values.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null)));
    const xy = chart.xy?.[0];
    if (xy && xy.x.length) out.xy = { x: xy.x, y: xy.y };
    out.rows = chart.categories?.length || out.series[0]?.length || out.xy?.x.length || 0;
    out.cols = 1 + Math.max(1, out.series.length);
    return out;
  }
  const t = c?.table;
  if (t) {
    out.rows = t.rows.length;
    out.cols = t.columns.length;
    const j = numericColumn(t.rows, t.columns.length);
    if (j !== null) out.series = [t.rows.map((r) => numberOf(r[j]))];
    return out;
  }
  const nums = c?.numbers ?? [];
  if (nums.length) {
    out.cards = nums.length;
    out.rows = nums.length;
    out.cols = 2;
    out.series = [nums.map((x) => numberOf(x.value))];
  }
  return out;
}

const main0 = (src: MiniSource) => src.series[0] ?? [];
const present = (vs: (number | null)[]) => vs.filter((v): v is number => v !== null);

/** Не больше `max` значений: длинный ряд — через равные промежутки (форма ряда сохраняется). */
function thin<T>(vs: T[], max: number): T[] {
  if (vs.length <= max) return vs;
  return Array.from({ length: max }, (_, i) => vs[Math.round((i * (vs.length - 1)) / (max - 1))]);
}

function columns(vs: (number | null)[], gapless: boolean, room: number): MiniLayers {
  const o = { ...EMPTY };
  const list = thin(vs, 48);
  const n = list.length;
  const max = Math.max(0, ...present(list));
  if (!n || max <= 0) return { ...o, grid: base };
  const labels = !gapless && n <= 10;
  const floor = labels ? 66 : BASE;
  const top = labels ? 50 : 56;
  const step = room / n;
  const w = gapless ? Math.max(1, step - 1) : Math.max(1.5, Math.min(10, step * 0.62));
  o.grid = hl(14, floor, 146);
  list.forEach((v, i) => {
    const x = 16 + i * step + (step - w) / 2;
    if (v === null) {
      o.dash += rr(x, floor - top * 0.6, w, top * 0.6, 1.5);
      return;
    }
    const h = Math.max(0.8, (Math.max(0, v) / max) * top);
    o.main += rr(x, floor - h, w, h, gapless ? 1 : 1.5);
    if (labels) o.txt += hl(x - 1, i % 2 ? 80 : 74, x + w + 1);
  });
  return o;
}

function bars(vs: (number | null)[]): MiniLayers {
  const o = { ...EMPTY };
  const list = vs.slice(0, 10);
  const n = list.length;
  const max = Math.max(0, ...present(list));
  if (!n || max <= 0) return o;
  const step = 62 / n;
  const h = Math.max(1.5, step - 2.4);
  list.forEach((v, i) => {
    const y = 14 + i * step;
    o.txt += hl(16, y + h / 2, 38);
    if (v === null) o.dash += rr(48, y, 40, h, 1.5);
    else o.main += rr(48, y, Math.max(0.8, (Math.max(0, v) / max) * 94), h, 1.5);
  });
  return o;
}

function lines(vs: (number | null)[], area: boolean): MiniLayers {
  const o = { ...EMPTY, grid: grid3 };
  const list = thin(vs, 60);
  const n = list.length;
  const ok = present(list);
  if (n < 2 || !ok.length) return o;
  let lo = Math.min(...ok);
  let hi = Math.max(...ok);
  if (hi === lo) {
    hi += 1;
    lo -= 1;
  }
  const X = (i: number) => 18 + (i * 124) / (n - 1);
  const Y = (v: number) => 72 - ((v - lo) / (hi - lo)) * 48;
  // отрезки между пропусками; точки — у короткого ряда с пропусками все (как на холсте `gapline`), иначе — последняя и
  // одиночные (отрезка у них нет)
  const gaps = list.some((v) => v === null);
  const dots = new Set<number>();
  let run: [number, number, number][] = [];
  const flush = () => {
    if (run.length > 1) {
      const pts = run.map(([x, y]) => [x, y] as [number, number]);
      o.line += poly(pts);
      if (area) o.light += `${poly(pts)}L${f(pts[pts.length - 1][0])} ${BASE}L${f(pts[0][0])} ${BASE}Z`;
    } else if (run.length === 1) dots.add(run[0][2]);
    run = [];
  };
  list.forEach((v, i) => {
    if (v === null) {
      flush();
      o.dash += vl(X(i), 22, BASE);
    } else run.push([X(i), Y(v), i]);
  });
  flush();
  const last = list.map((v, i) => (v === null ? -1 : i)).filter((i) => i >= 0).pop();
  if (n <= 12 && gaps) list.forEach((v, i) => v !== null && dots.add(i));
  else if (last !== undefined) dots.add(last);
  for (const i of [...dots].sort((a, b) => a - b)) o.main += ci(X(i), Y(list[i] as number), i === last && !(n <= 12 && gaps) ? 3.5 : 2.6);
  return o;
}

function pie(vs: (number | null)[]): MiniLayers {
  const o = { ...EMPTY };
  const list = present(vs).filter((v) => v > 0).slice(0, 12);
  const sum = list.reduce((a, b) => a + b, 0);
  if (!sum) return o;
  let a = 0;
  list.forEach((v, i) => {
    const s = sector(80, 45, 31, a, a + v / sum);
    if (i % 2) o.light += s;
    else o.main += s;
    a += v / sum;
  });
  a = 0;
  if (list.length > 1) for (const v of list) {
    const p = at(80, 45, 31, a);
    o.sep += `M80 45L${f(p[0])} ${f(p[1])}`;
    a += v / sum;
  }
  return o;
}

function doughnut(vs: (number | null)[]): MiniLayers {
  const o = { ...EMPTY };
  const list = present(vs).filter((v) => v > 0).slice(0, 12);
  const sum = list.reduce((a, b) => a + b, 0);
  if (!sum) return o;
  const gap = list.length > 1 ? 0.01 : 0;
  let a = 0;
  list.forEach((v, i) => {
    const e = a + v / sum;
    const d = arc(56, 45, 24, a, Math.max(a + 0.002, e - gap));
    if (i === 0) o.ring += d;
    else if (i === 1) o.ring2 += d;
    else o.ringL += d;
    a = e;
  });
  // подписи справа: точка цвета доли и строка
  const legend = list.slice(0, 4);
  const lens = [36, 28, 32, 22];
  legend.forEach((_, i) => {
    const y = 32 + i * 10;
    const dot = ci(94, y, 2.5);
    if (i === 0) o.main += dot;
    else if (i === 1) o.half += dot;
    else o.light += dot;
    o.txt += hl(100, y, 100 + lens[i]);
  });
  return o;
}

/** Части одного целого одной полосой (накопительный столбец из одного ряда): первая — основным, вторая —
 *  полупрозрачной, остальные — светлой заливкой. */
function stack100(vs: (number | null)[]): MiniLayers {
  const o = { ...EMPTY };
  const list = present(vs).filter((v) => v > 0).slice(0, 12);
  const sum = list.reduce((a, b) => a + b, 0);
  if (!sum) return o;
  let x = 16;
  list.forEach((v, i) => {
    const w = (v / sum) * 128;
    const r = rr(x, 36, w, 18, i === 0 ? 3 : 0.01);
    if (i === 0) o.main += r;
    else if (i === 1) o.half += r;
    else o.light += r;
    if (i > 0) o.sep += vl(x, 36, 54);
    if (i < 3) o.txt += hl(x, 66, x + Math.max(6, Math.min(28, w - 4)));
    x += w;
  });
  return o;
}

/** Несколько рядов: рядом (сгруппированные) или друг на друге (накопительные), столбцами или полосами. */
function multi(series: (number | null)[][], stacked: boolean, horizontal: boolean): MiniLayers {
  const o = { ...EMPTY };
  const ser = series.slice(0, 3);
  const n = Math.min(horizontal ? 8 : 12, Math.max(0, ...ser.map((s) => s.length)));
  if (!n) return o;
  const val = (k: number, i: number) => Math.max(0, ser[k]?.[i] ?? 0);
  const total = (i: number) => ser.reduce((a, _, k) => a + val(k, i), 0);
  const max = stacked ? Math.max(0, ...Array.from({ length: n }, (_, i) => total(i))) : Math.max(0, ...ser.flatMap((s) => present(s.slice(0, n))));
  if (max <= 0) return o;
  const layer = (k: number, d: string) => {
    if (k === 0) o.main += d;
    else if (k === 1) o.half += d;
    else o.light += d;
  };
  if (!horizontal) {
    o.grid = base;
    const step = 128 / n;
    const w = Math.max(2, step * 0.7);
    for (let i = 0; i < n; i++) {
      const x0 = 16 + i * step + (step - w) / 2;
      if (stacked) {
        let y = BASE;
        ser.forEach((_, k) => {
          const h = (val(k, i) / max) * 56;
          if (h > 0) layer(k, rr(x0, y - h, w, h, 0.01));
          y -= h;
        });
      } else {
        const bw = w / ser.length;
        ser.forEach((_, k) => {
          const h = (val(k, i) / max) * 56;
          if (h > 0) layer(k, rr(x0 + k * bw, BASE - h, Math.max(1, bw - 0.6), h, 1));
        });
      }
    }
    return o;
  }
  const step = 62 / n;
  const h = Math.max(1.5, step - 2.4);
  for (let i = 0; i < n; i++) {
    const y = 14 + i * step;
    o.txt += hl(16, y + h / 2, 38);
    if (stacked) {
      let x = 48;
      ser.forEach((_, k) => {
        const w = (val(k, i) / max) * 94;
        if (w > 0) layer(k, rr(x, y, w, h, 0.01));
        x += w;
      });
    } else {
      const bh = h / ser.length;
      ser.forEach((_, k) => {
        const w = (val(k, i) / max) * 94;
        if (w > 0) layer(k, rr(48, y + k * bh, w, Math.max(0.8, bh - 0.4), 1));
      });
    }
  }
  return o;
}

function scatter(xy: MiniSource["xy"]): MiniLayers {
  const o = { ...EMPTY, grid: `${base}${vl(14, 18, BASE)}` };
  if (!xy) return o;
  const pts = thin(xy.x.map((x, i) => [x, xy.y[i]] as const).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y)), 80);
  if (!pts.length) return o;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  for (const [x, y] of pts) {
    const px = 22 + (x1 > x0 ? ((x - x0) / (x1 - x0)) * 118 : 59);
    const py = 70 - (y1 > y0 ? ((y - y0) / (y1 - y0)) * 46 : 23);
    o.main += ci(px, py, 2);
  }
  return o;
}

/** Карточки показателей: строение (сколько карточек), без чисел — основной брусок на месте числа, штрих — подпись. */
function cards(n: number): MiniLayers {
  const o = { ...EMPTY };
  const k = Math.max(1, Math.min(6, n));
  const perRow = k === 4 ? 2 : Math.min(3, k);
  const rowsN = Math.ceil(k / perRow);
  const gap = 4;
  const cw = (132 - (perRow - 1) * gap) / perRow;
  const ch = rowsN === 1 ? 46 : 29;
  const y0 = rowsN === 1 ? 22 : 14;
  for (let i = 0; i < k; i++) {
    const x = 14 + (i % perRow) * (cw + gap);
    const y = y0 + Math.floor(i / perRow) * (ch + gap);
    o.light += rr(x, y, cw, ch, rowsN === 1 ? 6 : 5);
    o.main += rr(x + 6, y + (rowsN === 1 ? 10 : 6), Math.min(30, cw * 0.45), rowsN === 1 ? 10 : 8, 2);
    o.txt += hl(x + 7, y + (rowsN === 1 ? 32 : 22), x + Math.max(14, cw * 0.7));
  }
  return o;
}

/** Таблица: строение — шапка, строки (до шести видно), колонки; итог «Остальные» — светлой строкой. */
function table(rows: number, cols: number, restRow: boolean): MiniLayers {
  const o = { ...EMPTY };
  const r = Math.max(1, Math.min(6, rows || 6));
  const c = Math.max(1, Math.min(4, cols || 3));
  const rh = 58 / (r + 1);
  o.light = rr(14, 14, 132, Math.min(9, rh), 3);
  const cw = 132 / c;
  for (let i = 1; i <= r; i++) {
    o.grid += hl(14, 16 + rh * i, 146);
    for (let j = 0; j < c; j++) o.txt += hl(20 + j * cw, 16 + rh * i + rh / 2, 20 + j * cw + Math.min(34, cw - 12));
  }
  if (restRow) o.light += rr(14, 16 + rh * r + 0.5, 132, rh - 1, 2);
  return o;
}

/** Разбиение на слайды: столько страничек, сколько слайдов (не больше 24 видно). */
function pages(n: number): MiniLayers {
  const o = { ...EMPTY };
  const k = Math.max(1, Math.min(24, n));
  for (let i = 0; i < k; i++) {
    const x = 16 + (i % 6) * 22;
    const y = 16 + Math.floor(i / 6) * 15;
    o.light += rr(x, y, 18, 11, 2);
    o.txt += hl(x + 3, y + 4, x + 11);
  }
  return o;
}

/** Число слайдов из названия варианта «Разбиение на 24 слайда»; не разбиение — null. */
export function pagesOf(opt: Pick<VizOption, "title">): number | null {
  const m = opt.title.match(/разбиени[а-яё]*\s+на\s+(\d+)/i);
  return m ? Number(m[1]) : null;
}

/** Эскиз варианта `opt` по данным слайда `src`. */
export function miniChart(opt: Pick<VizOption, "kind" | "title">, src: MiniSource): MiniLayers {
  const kind: VizKind = opt.kind;
  const vs = main0(src);
  const many = src.series.filter((s) => present(s).length).length > 1;
  switch (kind) {
    case "line": return lines(vs, false);
    case "area": return lines(vs, true);
    case "column": return columns(vs, false, 128);
    case "histogram": {
      const o = columns(vs, true, src.outliers ? 112 : 128);
      if (src.outliers && o.main) o.acc = [134, 140, 146].slice(0, Math.min(3, src.outliers)).map((x) => ci(x, 72.5, 2.5)).join("");
      return o;
    }
    case "bar": return bars(vs);
    case "pie": return pie(vs);
    case "doughnut": return doughnut(vs);
    case "stacked_column":
    case "stacked_bar": return many ? multi(src.series, true, kind === "stacked_bar") : stack100(vs);
    case "grouped_column": return many ? multi(src.series, false, false) : columns(vs, false, 128);
    case "grouped_bar": return many ? multi(src.series, false, true) : bars(vs);
    case "scatter": return scatter(src.xy);
    case "kpi_cards": return cards(src.cards || 3);
    case "table": {
      const p = pagesOf(opt);
      return p ? pages(p) : table(src.rows, src.cols, src.restRow);
    }
  }
  return { ...EMPTY };
}

/** Цвета эскизов — шаблона презентации (у брендированной копии — бренда): основной — первый акцент, акцент — первый
 *  другой по тону; светлая заливка — основной, разбавленный белым. Разбора нет — синий и розовый, как на холсте. */
export interface MiniColors { main: string; acc: string; light: string }
const hexOk = (h: string) => /^[0-9a-f]{6}$/i.test(h.replace(/^#/, ""));
const rgb = (h: string) => {
  const x = h.replace(/^#/, "");
  return [0, 2, 4].map((i) => parseInt(x.slice(i, i + 2), 16));
};
function hue(h: string): number {
  const [r, g, b] = rgb(h).map((v) => v / 255);
  const mx = Math.max(r, g, b);
  const mn = Math.min(r, g, b);
  const d = mx - mn;
  if (!d) return 0;
  const k = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (k * 60 + 360) % 360;
}
const sat = (h: string) => {
  const [r, g, b] = rgb(h);
  const mx = Math.max(r, g, b);
  return mx ? (mx - Math.min(r, g, b)) / mx : 0;
};
export const tint = (hex: string, white = 0.84): string =>
  `#${rgb(hex).map((v) => Math.round(v + (255 - v) * white).toString(16).padStart(2, "0")).join("").toUpperCase()}`;

export function miniColors(manifest: Pick<TemplateManifest, "tokens"> | null | undefined): MiniColors {
  const tokens = manifest?.tokens?.colors ?? [];
  const accents = tokens.filter((c) => hexOk(c.hex) && c.roles?.some((r) => /^accent\./.test(r)) && sat(c.hex) > 0.35);
  const first = accents.find((c) => c.roles.includes("accent.1")) ?? accents[0] ?? tokens.find((c) => c.is_brand && hexOk(c.hex) && sat(c.hex) > 0.35);
  const main = first ? `#${first.hex.replace(/^#/, "").toUpperCase()}` : "#0077FF";
  const away = (h: string) => Math.min(Math.abs(hue(h) - hue(main)), 360 - Math.abs(hue(h) - hue(main)));
  const other = accents.find((c) => `#${c.hex.replace(/^#/, "").toUpperCase()}` !== main && away(c.hex) >= 60);
  const acc = other ? `#${other.hex.replace(/^#/, "").toUpperCase()}` : "#FF3885";
  return { main, acc, light: tint(main) };
}
