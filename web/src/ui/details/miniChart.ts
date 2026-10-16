// Мини-график варианта визуализации в «Почему так» (V2 v105 `dsMini`): эскиз 160×90 в палитре шаблона — слои сетки,
// подписей (серые штрихи), заливок (светлая, основная, полупрозрачная), линии, кольца, акцента, пунктира и белых
// разделителей. Рисуется из данных набора (OutlineSlide.content: ряды графика, таблица, карточки) — числа не
// придумываются: столбцы, линия, сектора — это значения в форме варианта; таблица, карточки и страницы — только их
// строение (сколько строк, колонок, карточек — столько, сколько сделал бы сервер). Набор, разбитый на несколько слайдов,
// — весь: значения частей по порядку (иначе другой вариант показал бы только строки этой части). Числа в разных
// единицах («1,24 млрд ₽», «3 480 клиентов») не сравниваются — только строение. Чего в данных нет, того на эскизе нет.
// Чистые функции, без React.
import type { OutlineSlide, SlideData, TaskKind, TemplateManifest, VizKind, VizOption } from "../../types";

/** Слои эскиза — пути `d` в координатах 160×90 (пусто — слоя нет). Порядок отрисовки — как здесь. */
export interface MiniLayers {
  grid: string; light: string; txt: string; ringL: string; ring2: string; ring: string; half: string; main: string;
  sep: string; line: string; acc: string; dash: string;
}

/** Что эскиз берёт из набора. */
export interface MiniSource {
  /** Ряды значений (первый — главный); null — пропуск (разрыв линии, пустое место столбца). */
  series: (number | null)[][];
  /** Подписи значений главного ряда (категории графика, первая колонка таблицы, подписи карточек) — для текста эскиза. */
  labels: string[];
  /** Числа в разных единицах: сравнивать нельзя — столбцы и сектора только строением (сколько значений). */
  mixed: number;
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

const MULT: [RegExp, number][] = [[/трлн/i, 1e12], [/млрд/i, 1e9], [/млн/i, 1e6], [/тыс/i, 1e3]];

/** Величина подписи: число с множителем («1,24 млрд ₽» → 1 240 000 000) и единица без него («₽»); нет числа — null. */
export function amountOf(text: string | null | undefined): { v: number; unit: string } | null {
  const v = numberOf(text);
  if (v === null) return null;
  const t = (text ?? "").toLowerCase().replace(/ё/g, "е");
  const mult = MULT.find(([re]) => re.test(t))?.[1] ?? 1;
  const unit = t.replace(/[-+−]?\d[\d\s\u00a0\u202f.,]*/g, " ").replace(/трлн|млрд|млн|тыс\.?/g, " ").replace(/\s+/g, " ").trim();
  return { v: v * mult, unit };
}

/** Значения подписей в одной шкале: единицы одинаковые — числа с множителями; разные — null (сравнивать нельзя). */
function sameScale(texts: (string | null | undefined)[]): (number | null)[] | null {
  const a = texts.map(amountOf);
  const units = new Set(a.filter((x) => x !== null).map((x) => x!.unit));
  return units.size > 1 ? null : a.map((x) => (x ? x.v : null));
}

/** Колонка таблицы с числами (не первая — она подписи): первая, где числа почти во всех строках. */
function numericColumn(rows: string[][], cols: number): number | null {
  for (let j = 1; j < cols; j++) {
    const nums = rows.filter((r) => numberOf(r[j]) !== null).length;
    if (rows.length && nums >= Math.ceil(rows.length * 0.7)) return j;
  }
  return null;
}

/** Слайды набора по порядку частей: набор разбит на несколько слайдов (`part`) — все его части из `outline`, иначе —
 *  сам слайд. */
function partsOf(slide: Pick<OutlineSlide, "content"> | null | undefined, data: Pick<SlideData, "dataset_id" | "part"> | null | undefined,
  outline: Pick<OutlineSlide, "content" | "data">[] | null | undefined): Pick<OutlineSlide, "content">[] {
  const n = data?.part?.[1] ?? 1;
  if (!slide || !data || !outline || n <= 1) return slide ? [slide] : [];
  const byPart = new Map<number, Pick<OutlineSlide, "content">>();
  for (const s of outline) {
    const d = s.data;
    if (d && d.dataset_id === data.dataset_id && d.part?.[1] === n && !byPart.has(d.part[0])) byPart.set(d.part[0], s);
  }
  if (byPart.size < 2) return [slide];
  return [...byPart.entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1]);
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Данные эскиза — из содержимого слайда (график, таблица или карточки) и профиля набора; набор на нескольких слайдах
 *  (`data.part`) — значения всех его частей из `outline` по порядку. */
export function miniSource(slide: Pick<OutlineSlide, "content"> | null | undefined, data: Pick<SlideData, "outliers" | "aggregation" | "dataset_id" | "part"> | null | undefined,
  outline?: Pick<OutlineSlide, "content" | "data">[] | null): MiniSource {
  const out: MiniSource = { series: [], labels: [], mixed: 0, xy: null, rows: 0, cols: 0, cards: 0, outliers: data?.outliers?.length ?? 0, restRow: /остальн/i.test(data?.aggregation ?? "") };
  const joined = partsOf(slide, data, outline);
  const parts = joined.every((p) => p.content?.chart) || joined.every((p) => p.content?.table) ? joined : slide ? [slide] : [];
  const charts = parts.map((p) => p.content?.chart).filter((c): c is NonNullable<typeof c> => !!c);
  if (charts.length && charts.length === parts.length) {
    const width = Math.max(0, ...charts.map((c) => c.series?.length ?? 0));
    out.series = Array.from({ length: width }, (_, i) => charts.flatMap((c) => (c.series?.[i]?.values ?? []).map(num)));
    // ряды в разных единицах (`split`) друг с другом не сравниваются: эскиз — по главному
    const units = new Set(charts.flatMap((c) => (c.series ?? []).map((x) => x.unit ?? c.unit ?? "")));
    if (out.series.length > 1 && (charts.some((c) => c.split) || units.size > 1)) out.series = out.series.slice(0, 1);
    out.labels = charts.flatMap((c) => c.categories ?? []);
    const xs = charts.flatMap((c) => c.xy?.[0]?.x ?? []);
    const ys = charts.flatMap((c) => c.xy?.[0]?.y ?? []);
    if (xs.length) out.xy = { x: xs, y: ys };
    out.rows = out.labels.length || out.series[0]?.length || out.xy?.x.length || 0;
    out.cols = 1 + Math.max(1, out.series.length);
    return out;
  }
  const tables = parts.map((p) => p.content?.table).filter((t): t is NonNullable<typeof t> => !!t);
  if (tables.length && tables.length === parts.length) {
    const rows = tables.flatMap((t) => t.rows);
    out.rows = rows.length;
    out.cols = tables[0].columns.length;
    const j = numericColumn(rows, out.cols);
    if (j !== null) {
      const vs = sameScale(rows.map((r) => r[j]));
      if (vs) out.series = [vs];
      else out.mixed = rows.length;
      out.labels = rows.map((r) => r[0] ?? "");
    }
    return out;
  }
  const nums = slide?.content?.numbers ?? [];
  if (nums.length) {
    out.cards = nums.length;
    out.rows = nums.length;
    out.cols = 2;
    out.labels = nums.map((x) => x.label);
    const vs = sameScale(nums.map((x) => x.value));
    if (vs) out.series = [vs];
    else out.mixed = nums.length;
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
  if (n < 1) return o;
  const k = Math.min(6, n);
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

/** Числа в разных единицах: только строение — столько одинаковых светлых столбцов (полос), сколько значений, с
 *  подписями; высота ничего не говорит (V2 `ubars` — «разные единицы — сравнивать нельзя»). */
function units(n: number, horizontal: boolean): MiniLayers {
  const o = { ...EMPTY };
  const k = Math.min(horizontal ? 10 : 12, n);
  if (!k) return o;
  if (horizontal) {
    const step = 62 / k;
    const h = Math.max(1.5, step - 2.4);
    for (let i = 0; i < k; i++) {
      const y = 14 + i * step;
      o.txt += hl(16, y + h / 2, 38);
      o.light += rr(48, y, 60, h, 1.5);
    }
    return o;
  }
  o.grid = hl(14, 66, 146);
  const step = 128 / k;
  const w = Math.max(1.5, Math.min(14, step * 0.62));
  for (let i = 0; i < k; i++) {
    const x = 16 + i * step + (step - w) / 2;
    o.light += rr(x, 38, w, 28, 1.5);
    o.txt += hl(x - 1, i % 2 ? 80 : 74, x + w + 1);
  }
  return o;
}

/** Сколько карточек сделал бы сервер (verstka/data/plan.py): у слайда-карточек — их число; динамика — последние три
 *  точки; распределение — медиана, 80-й перцентиль, число значений и выбросы; ключевые значения — до шести; итог и
 *  среднее — итог (у неотрицательных значений), среднее и число строк. Чисел нет — карточек нет. */
export function cardsOf(task: TaskKind | null | undefined, src: MiniSource): number {
  if (src.cards) return Math.min(6, src.cards);
  const vs = present(main0(src));
  if (task === "kpi") return Math.min(6, src.rows);
  if (task === "distribution") return vs.length ? 3 + (src.outliers ? 1 : 0) : 0;
  if (!vs.length) return 0;
  if (task === "dynamics") return Math.min(3, vs.length);
  return vs.every((v) => v >= 0) ? 3 : 2;
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

/** Эскиз варианта `opt` по данным набора `src` (`task` — задача слайда: сколько карточек сделал бы сервер). */
export function miniChart(opt: Pick<VizOption, "kind" | "title">, src: MiniSource, task?: TaskKind | null): MiniLayers {
  const kind: VizKind = opt.kind;
  const vs = main0(src);
  const many = src.series.filter((s) => present(s).length).length > 1;
  if (src.mixed) {
    switch (kind) {
      case "column": case "histogram": case "grouped_column": case "stacked_column": return units(src.mixed, false);
      case "bar": case "grouped_bar": case "stacked_bar": return units(src.mixed, true);
      case "line": case "area": case "pie": case "doughnut": case "scatter": return { ...EMPTY, grid: kind === "line" || kind === "area" ? grid3 : "" };
    }
  }
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
    case "kpi_cards": return cards(cardsOf(task, src));
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
