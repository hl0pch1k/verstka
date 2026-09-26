// Compact rendering of one outline slide's content: text, numbers, cards, tables, charts (both of a two-chart slide),
// quotes.
import { ChartArea, ChartBar, ChartColumn, ChartLine, ChartPie, Image, Quote, type LucideIcon } from "lucide-react";
import { cn, plural } from "../lib/utils";
import type { ChartSpec, DeckOutline, SlideContent, SlideItem, TableData } from "../types";

const CHART: Record<string, { name: string; icon: LucideIcon }> = {
  bar: { name: "Горизонтальная диаграмма", icon: ChartBar },
  column: { name: "Столбчатая диаграмма", icon: ChartColumn },
  line: { name: "Линейный график", icon: ChartLine },
  area: { name: "Диаграмма с областями", icon: ChartArea },
  pie: { name: "Круговая диаграмма", icon: ChartPie },
  doughnut: { name: "Кольцевая диаграмма", icon: ChartPie },
};
const TABLE_ROWS = 6;
const COLS: Record<number, string> = { 1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4" };

function ItemCard({ item }: { item: SlideItem }) {
  return (
    <div className="min-w-0 rounded-xl bg-zinc-50 px-3 py-2">
      {item.number && <p className="text-body font-semibold tabular-nums text-accent-700">{item.number}</p>}
      <p className="text-footnote font-semibold text-zinc-900">{item.title}</p>
      {item.text && <p className="mt-0.5 text-caption text-zinc-600">{item.text}</p>}
      {item.bullets.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-caption text-zinc-600">{item.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>
      )}
    </div>
  );
}

function ItemGrid({ items }: { items: SlideItem[] }) {
  return <div className={cn("grid gap-2", COLS[Math.min(4, Math.max(1, items.length))])}>{items.map((it, i) => <ItemCard key={i} item={it} />)}</div>;
}

function MiniTable({ table }: { table: TableData }) {
  const rows = table.rows.slice(0, TABLE_ROWS);
  return (
    <div className="overflow-hidden rounded-xl bg-zinc-50 ring-1 ring-inset ring-zinc-900/[0.06]">
      <table className="w-full border-collapse text-caption">
        {table.columns.length > 0 && (
          <thead className="text-left text-zinc-500">
            <tr>{table.columns.map((c, i) => <th key={i} className="px-3 py-2 font-semibold">{c}</th>)}</tr>
          </thead>
        )}
        <tbody className="divide-y divide-zinc-100">
          {rows.map((r, i) => (
            <tr key={i} className="text-zinc-800">{r.map((cell, j) => <td key={j} className={cn("px-3 py-2", j > 0 && /^[\d\s.,%+−-]+$/.test(cell) && "tabular-nums")}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {(table.caption || table.unit || table.rows.length > TABLE_ROWS) && (
        <p className="border-t border-zinc-100 px-3 py-1 text-caption text-zinc-500">
          {[table.caption, table.unit && `ед. ${table.unit}`, table.rows.length > TABLE_ROWS && `ещё строк: ${table.rows.length - TABLE_ROWS}`].filter(Boolean).join(" · ")}
        </p>
      )}
    </div>
  );
}

/** «Круговая диаграмма · Расходы, ₽ · 6 значений · акцент — Продукты и упаковка» in one line, never cut. */
function ChartLineView({ chart, outline }: { chart: ChartSpec; outline: DeckOutline }) {
  const kind = CHART[chart.type] ?? { name: "Диаграмма", icon: ChartColumn };
  const Icon = kind.icon;
  const series = chart.series_ids.map((id) => outline.series.find((s) => s.id === id) ?? null);
  const categories = chart.categories?.length ? chart.categories : series[0]?.categories ?? [];
  const n = categories.length || chart.series?.[0]?.values.length || series[0]?.values.length || 0;
  const title = chart.title?.trim() || series[0]?.name || null;
  const unit = chart.unit && !(title ?? "").includes(chart.unit) ? chart.unit : null;
  const accent = chart.highlight_index !== null && chart.highlight_index !== undefined ? categories[chart.highlight_index] ?? null : null;
  return (
    <p className="flex items-start gap-2 text-footnote text-zinc-700">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" aria-hidden />
      <span className="min-w-0">
        <span className="font-semibold text-zinc-900">{kind.name}</span>
        {title && ` · ${title}${unit ? `, ${unit}` : ""}`}
        {!title && unit && ` · ${unit}`}
        {n > 0 && ` · ${plural(n, "значение", "значения", "значений")}`}
        {accent && <span className="text-zinc-500"> · акцент{"\u00a0"}— {accent}</span>}
      </span>
    </p>
  );
}

export function SlideContentView({ content, outline }: { content: SlideContent; outline: DeckOutline }) {
  const c = content;
  const charts = [c.chart, c.chart2].filter((x): x is ChartSpec => !!x);
  const empty = !(c.paragraphs.length || c.bullets.length || c.items.length || c.columns.length || c.numbers.length || c.table || charts.length || c.quote || c.image_hint || c.formula);
  if (empty) return null;
  return (
    <div className="space-y-2">
      {c.paragraphs.map((p, i) => <p key={i} className="text-footnote text-zinc-700">{p}</p>)}
      {c.bullets.length > 0 && <ul className="list-disc space-y-0.5 pl-4 text-footnote text-zinc-700">{c.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>}
      {c.numbers.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {c.numbers.map((n, i) => (
            <span key={i} className="inline-flex items-baseline gap-2 rounded-xl bg-accent-50 px-3 py-1">
              <span className="text-body font-semibold tabular-nums text-accent-700">{n.value}</span>
              <span className="text-caption text-zinc-600">{n.label}</span>
            </span>
          ))}
        </div>
      )}
      {c.formula && <p className="inline-flex max-w-full rounded-xl bg-accent-50 px-3 py-1 text-footnote font-semibold tabular-nums text-accent-700">{c.formula}</p>}
      {c.items.length > 0 && <ItemGrid items={c.items} />}
      {c.columns.length > 0 && <ItemGrid items={c.columns} />}
      {c.table && <MiniTable table={c.table} />}
      {charts.map((ch, i) => <ChartLineView key={i} chart={ch} outline={outline} />)}
      {c.quote && (
        <blockquote className="flex gap-2 border-l-2 border-accent pl-3">
          <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
          <div>
            <p className="text-footnote italic text-zinc-800">{c.quote}</p>
            {c.quote_author && <p className="mt-0.5 text-caption text-zinc-500">— {c.quote_author}</p>}
          </div>
        </blockquote>
      )}
      {c.image_hint && (
        <p className="flex items-center gap-2 text-footnote text-zinc-500">
          <Image className="h-4 w-4 shrink-0 text-zinc-400" aria-hidden /> Изображение: {c.image_hint}
        </p>
      )}
    </div>
  );
}
