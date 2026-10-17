// Вкладка «План» без React (boards/D-plan, V2 модуль details `dlP`): слайды плана строками — превью, тип, заголовок и
// содержимое (абзац, пункты, даты и числа чипами, формула текстом, карточки, таблица, диаграмма, изображение), справа —
// заголовок колоды, «Текст агента», «Цифры из текста» и «Данные для диаграмм». Данные — `variant.outline`,
// `generation.writer`.
import { plural, kindLabel } from "../../lib/utils";
import type { ChartSpec, DeckOutline, Fact, SlideContent, Variant, WriterInfo } from "../../types";
import { writerSlides } from "../layers/writerText";
import { slideSrc } from "../result/resultView";
import { formulaParts, latexText } from "./latex";
import { vizName } from "../../lib/vizNames";

export { formulaParts, latexText } from "./latex";

/** Название диаграммы — одно на вид, как везде (lib/vizNames, как на сервере). */
export const chartName = (type: string) => vizName(type);

/** Подпись короче `max` знаков — по целым словам, с многоточием, если что-то отрезано. */
export function shortLabel(text: string, max = 32): string {
  const words = text.replace(/^[\s—–\-:;,.]+/, "").replace(/[\s.;,:]+$/, "").split(/\s+/).filter(Boolean);
  let out = "";
  for (const w of words) {
    const next = out ? `${out} ${w}` : w;
    if (next.length > max) return out ? `${out.replace(/[,;:—–-]+$/, "")}…` : `${w.slice(0, max)}…`;
    out = next;
  }
  return out;
}

export interface PlanRow {
  n: number; id: string; kind: string; title: string; sub: string | null; img: string | null;
  par: string | null; bul: string[]; chips: { v: string; l: string }[]; fx: string[];
  items: { t: string; x: string }[]; itemsCls: "dpl-c2" | "dpl-c3";
  tbl: { c1: string; c2: string; rows: { a: string; b: string }[] } | null;
  charts: { type: string; rest: string }[]; image: string | null;
}

const isDate = (t: string) => /\d/.test(t) && t.replace(/\s/g, "").length <= 12;

function chartLine(c: ChartSpec, outline: DeckOutline): { type: string; rest: string } {
  const series = c.series_ids.map((id) => outline.series.find((s) => s.id === id)).filter((s) => !!s);
  const cats = c.categories?.length ? c.categories : series[0]?.categories ?? [];
  const n = cats.length || c.series?.[0]?.values.length || series[0]?.values.length || 0;
  const title = c.title?.trim() || series[0]?.name || "";
  return { type: chartName(c.type), rest: [title, n ? plural(n, "значение", "значения", "значений") : ""].filter(Boolean).map((x) => ` · ${x}`).join("") };
}

function rowOf(v: Variant, outline: DeckOutline, i: number): PlanRow {
  const s = outline.slides[i];
  const c: SlideContent = s.content;
  const dated = c.items.length > 0 && c.items.every((it) => isDate(it.title));
  const chips = dated ? c.items.map((it) => ({ v: it.title, l: shortLabel(it.text || it.bullets[0] || "") }))
    : c.numbers.map((x) => ({ v: x.value, l: shortLabel(x.label) }));
  const cards = (dated ? [] : c.items.length ? c.items : c.columns).slice(0, 3).map((it) => ({ t: it.title, x: it.text || it.bullets.join("; ") }));
  const par = c.paragraphs[0] ?? (c.quote ? `«${c.quote}»${c.quote_author ? ` — ${c.quote_author}` : ""}` : null);
  const t = c.table;
  const extra = c as SlideContent & { photo_hint?: string | null };
  return {
    n: i + 1, id: s.id, kind: kindLabel(s.kind), title: s.headline || "Без заголовка", sub: s.subtitle?.trim() || null, img: slideSrc(v, i + 1),
    par, bul: c.bullets.slice(0, 3), chips: chips.slice(0, 6), fx: formulaParts(c.formula).slice(0, 2),
    items: cards, itemsCls: cards.length === 3 ? "dpl-c3" : "dpl-c2",
    tbl: t && t.columns.length ? { c1: t.columns[0] ?? "", c2: t.columns[1] ?? "", rows: t.rows.slice(0, 3).map((r) => ({ a: r[0] ?? "", b: r[1] ?? "" })) } : null,
    charts: [c.chart, c.chart2].filter((x): x is ChartSpec => !!x).map((ch) => chartLine(ch, outline)),
    image: c.image_hint?.trim() || extra.photo_hint?.trim() || null,
  };
}

export function planRows(v: Variant): PlanRow[] {
  const o = v.outline;
  return o ? o.slides.map((_, i) => rowOf(v, o, i)) : [];
}

/** Шапка справа: название колоды, подзаголовок и «12 слайдов · аудитория: студенты 1 курса». */
export function deckHead(o: DeckOutline): { title: string; sub: string | null; meta: string } {
  const aud = o.audience?.trim();
  return {
    title: o.title || "Презентация", sub: o.subtitle?.trim() || null,
    meta: [plural(o.slides.length, "слайд", "слайда", "слайдов"), aud ? `аудитория: ${aud[0].toLowerCase()}${aud.slice(1)}` : null].filter(Boolean).join(" · "),
  };
}

/** «По статье «Интеграл» · 12 слайдов» — подпись раздела «Текст агента». */
export function writerHead(w: WriterInfo): string {
  return [w.source?.title ? `По статье «${w.source.title}»` : "По теме", w.slides ? plural(w.slides, "слайд", "слайда", "слайдов") : null].filter(Boolean).join(" · ");
}

/** Текст агента по слайдам: «Слайд N · заголовок» и текст слайда одной строкой. */
export function writerTexts(text: string): { n: number; title: string; t: string }[] {
  return writerSlides(text, []).filter((s) => s.n !== null).map((s) => ({
    n: s.n as number, title: s.title, t: s.lines.map((l) => l.map((p) => p.text).join("").trim()).filter(Boolean).join(" "),
  }));
}

/** «Цифры из текста»: значение (с единицей) и короткая подпись — без тире и повтора значения в начале; формула в
 *  подписи («$\frac{8}{3}…») — текстом, а «$» от неё — не единица измерения. */
export function factChips(facts: Fact[]): { v: string; l: string }[] {
  return facts.map((f) => {
    const raw = f.label ?? "";
    const tex = /\$|\\[a-z]/i.test(raw);
    let l = raw.replace(/^[\s—–\-:;,.]+/, "");
    if (f.value && l.startsWith(f.value)) l = l.slice(f.value.length).replace(/^[\s—–\-:;,.]+/, "");
    if (tex) l = latexText(l.replace(/\$/g, " ").replace(/\\\s*$/, ""));
    const unit = tex && f.unit === "$" ? null : f.unit;
    return { v: `${f.value}${unit ? (unit === "%" ? "%" : ` ${unit}`) : ""}`, l: shortLabel(l) };
  });
}

const num = (v: number) => v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });

/** «Данные для диаграмм»: каждая диаграмма плана — тип, слайд, название и значения первого ряда по категориям. */
export function chartData(o: DeckOutline): { count: string; charts: { key: string; type: string; rest: string; head: [string, string]; rows: { a: string; b: string }[] }[] } {
  const charts: { key: string; type: string; rest: string; head: [string, string]; rows: { a: string; b: string }[] }[] = [];
  let series = 0;
  o.slides.forEach((s, i) => {
    [s.content.chart, s.content.chart2].forEach((c, k) => {
      if (!c) return;
      const linked = c.series_ids.map((id) => o.series.find((x) => x.id === id)).filter((x) => !!x);
      const own = c.series?.[0];
      const first = own ? { name: own.name, values: own.values, categories: c.categories ?? [], unit: c.unit } : linked[0];
      if (!first) return;
      series += c.series?.length || linked.length;
      const cats = first.categories.length ? first.categories : c.categories ?? [];
      const title = c.title?.trim() || first.name;
      charts.push({
        key: `${s.id}-${k}`, type: chartName(c.type), rest: ` · слайд ${i + 1}${title ? ` · ${title}` : ""}`,
        head: ["", `${first.name}${first.unit ? `, ${first.unit}` : ""}`],
        rows: cats.map((cat, j) => ({ a: cat, b: typeof first.values[j] === "number" ? num(first.values[j]) : "—" })),
      });
    });
  });
  return { count: plural(series, "ряд", "ряда", "рядов"), charts };
}
