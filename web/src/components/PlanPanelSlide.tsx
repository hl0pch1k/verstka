// Compact rendering of one outline slide's content and of the layout decision the matcher took for it.
import { ChartColumn, Image, Quote } from "lucide-react";
import { cn, kindLabel } from "../lib/utils";
import type { DeckOutline, LayoutSlide, Pattern, SlideContent, SlideItem, TableData } from "../types";
import { PatternThumb } from "./TemplatePanelShared";
import { Badge, type BadgeTone } from "./ui/Badge";

const CHART_RU: Record<string, string> = { bar: "горизонтальные столбцы", column: "столбчатая", line: "линейная", area: "с областями", pie: "круговая", doughnut: "кольцевая" };
const TABLE_ROWS = 6;
const COLS: Record<number, string> = { 1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4" };

function ItemCard({ item }: { item: SlideItem }) {
  return (
    <div className="min-w-0 rounded-lg border border-zinc-200 bg-zinc-50/70 px-3 py-2">
      {item.number && <p className="text-base font-semibold leading-6 tabular-nums text-accent-700">{item.number}</p>}
      <p className="text-[13px] font-medium leading-5 text-zinc-900">{item.title}</p>
      {item.text && <p className="mt-0.5 text-xs leading-[18px] text-zinc-600">{item.text}</p>}
      {item.bullets.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs leading-[18px] text-zinc-600">{item.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>
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
    <div className="overflow-hidden rounded-lg border border-zinc-200">
      <table className="w-full border-collapse text-xs">
        {table.columns.length > 0 && (
          <thead className="bg-zinc-50 text-left text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
            <tr>{table.columns.map((c, i) => <th key={i} className="px-2.5 py-1.5 font-semibold">{c}</th>)}</tr>
          </thead>
        )}
        <tbody className="divide-y divide-zinc-100">
          {rows.map((r, i) => (
            <tr key={i} className="text-zinc-800">{r.map((cell, j) => <td key={j} className={cn("px-2.5 py-1.5", j > 0 && /^[\d\s.,%+−-]+$/.test(cell) && "tabular-nums")}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {(table.caption || table.unit || table.rows.length > TABLE_ROWS) && (
        <p className="border-t border-zinc-100 bg-zinc-50/60 px-2.5 py-1 text-[11px] text-zinc-500">
          {[table.caption, table.unit && `ед. ${table.unit}`, table.rows.length > TABLE_ROWS && `ещё строк: ${table.rows.length - TABLE_ROWS}`].filter(Boolean).join(" · ")}
        </p>
      )}
    </div>
  );
}

export function SlideContentView({ content, outline }: { content: SlideContent; outline: DeckOutline }) {
  const c = content;
  const chart = c.chart;
  const series = chart ? chart.series_ids.map((id) => outline.series.find((s) => s.id === id)) : [];
  const empty = !(c.paragraphs.length || c.bullets.length || c.items.length || c.columns.length || c.numbers.length || c.table || chart || c.quote || c.image_hint);
  if (empty) return null;
  return (
    <div className="space-y-2.5">
      {c.paragraphs.map((p, i) => <p key={i} className="text-[13px] leading-5 text-zinc-700">{p}</p>)}
      {c.bullets.length > 0 && <ul className="list-disc space-y-0.5 pl-5 text-[13px] leading-5 text-zinc-700">{c.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>}
      {c.numbers.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {c.numbers.map((n, i) => (
            <span key={i} className="inline-flex items-baseline gap-1.5 rounded-lg border border-accent-100 bg-accent-50 px-2.5 py-1" title={n.fact_id ? `факт ${n.fact_id}` : undefined}>
              <span className="text-base font-semibold tabular-nums text-accent-700">{n.value}</span>
              <span className="text-xs text-zinc-600">{n.label}</span>
            </span>
          ))}
        </div>
      )}
      {c.items.length > 0 && <ItemGrid items={c.items} />}
      {c.columns.length > 0 && <ItemGrid items={c.columns} />}
      {c.table && <MiniTable table={c.table} />}
      {chart && (
        <div className="flex items-start gap-2.5 rounded-lg border border-dashed border-zinc-300 px-3 py-2 text-xs text-zinc-600">
          <ChartColumn className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" aria-hidden />
          <div className="min-w-0">
            <p className="text-[13px] text-zinc-800">
              Диаграмма <span className="font-medium">{CHART_RU[chart.type] ?? chart.type}</span>{chart.title && <span> · {chart.title}</span>}{chart.unit && <span className="text-zinc-500"> · {chart.unit}</span>}
            </p>
            <p className="truncate">
              {series.length === 0 ? "ряды не привязаны" : series.map((s, i) => (s ? `${s.name} (${s.values.length})` : chart.series_ids[i])).join(" · ")}
              {chart.highlight_index !== null && series[0] && <span className="text-accent-700"> · акцент «{series[0].categories[chart.highlight_index] ?? chart.highlight_index + 1}»</span>}
            </p>
          </div>
        </div>
      )}
      {c.quote && (
        <blockquote className="flex gap-2.5 border-l-2 border-accent pl-3">
          <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" aria-hidden />
          <div>
            <p className="text-[13px] italic leading-5 text-zinc-800">{c.quote}</p>
            {c.quote_author && <p className="mt-0.5 text-xs text-zinc-500">— {c.quote_author}</p>}
          </div>
        </blockquote>
      )}
      {c.image_hint && (
        <p className="flex items-center gap-1.5 text-xs text-zinc-500"><Image className="h-3.5 w-3.5 shrink-0" aria-hidden /> Изображение: {c.image_hint}</p>
      )}
    </div>
  );
}

const scoreTone = (s: number): BadgeTone => (s >= 0.8 ? "success" : s >= 0.5 ? "warn" : "error");
const fitLine = (fit: Record<string, unknown>): string => {
  const parts: string[] = [];
  if (typeof fit.items === "string") parts.push(`ячейки ${fit.items}`);
  if (typeof fit.text_ratio === "number") parts.push(`текст ${Math.round(fit.text_ratio * 100)}%`);
  return parts.join(" · ");
};

export function LayoutDecision({ decision, pattern, aspect }: { decision: LayoutSlide | undefined; pattern: Pattern | null; aspect: string }) {
  if (!decision) return <Badge size="sm">без решения</Badge>;
  const clone = decision.mode === "clone";
  const fit = fitLine(decision.fit);
  const alternatives = decision.alternatives.slice(0, 3).map(([id, s]) => `${id} ${s.toFixed(2)}`).join(", ");
  const tip = [...decision.reasons, alternatives && `альтернативы: ${alternatives}`].filter(Boolean).join("\n");
  const reason = clone ? decision.reasons.find((r) => !/^слайд \d+ шаблона$/.test(r)) : decision.reasons[0]; // «слайд N шаблона» is already on the thumbnail
  return (
    <div className="flex w-52 shrink-0 flex-col gap-1.5" title={tip}>
      {clone && (
        <div className="relative overflow-hidden rounded-md border border-zinc-200 bg-zinc-100" style={{ aspectRatio: aspect }}>
          <PatternThumb src={pattern?.thumbnail_url} alt={decision.pattern_id ?? "паттерн"} />
          {pattern && <span className="absolute left-1 top-1 rounded bg-zinc-900/75 px-1 text-[10px] font-medium text-white">слайд {pattern.source_slide}</span>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-1">
        <Badge size="sm" tone={clone ? "accent" : "info"}>{clone ? "клон" : "синтез"}</Badge>
        <span className="font-mono text-[11px] text-zinc-700">{clone ? decision.pattern_id : decision.composition}</span>
        {pattern && <span className="text-[11px] text-zinc-500">{kindLabel(pattern.kind)}</span>}
        <Badge size="sm" tone={scoreTone(decision.score)} className="ml-auto tabular-nums">{decision.score.toFixed(2)}</Badge>
      </div>
      {(reason || fit) && <p className="truncate text-[11px] leading-4 text-zinc-500">{[reason, fit].filter(Boolean).join(" · ")}</p>}
    </div>
  );
}
