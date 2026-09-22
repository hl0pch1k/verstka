// Data extracted from the brief: the fact registry every number on the slides refers to, and the series behind charts.
import { Database, Hash } from "lucide-react";
import { plural } from "../lib/utils";
import type { Fact, Series } from "../types";
import { Badge } from "./ui/Badge";
import { Collapsible } from "./ui/Collapsible";

const num = (v: number) => v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });

export function FactsRegistry({ facts, used }: { facts: Fact[]; used: Set<string> }) {
  const inUse = facts.filter((f) => used.has(f.id)).length;
  return (
    <Collapsible
      icon={Hash}
      title="Реестр фактов"
      hint={facts.length === 0 ? "из брифа не извлечено ни одного числа" : `${plural(facts.length, "факт", "факта", "фактов")} · на слайдах ${inUse}`}
      right={facts.length > 0 && <Badge size="sm">{facts.length}</Badge>}
      bodyClassName="px-0 py-0"
    >
      {facts.length === 0 ? (
        <p className="px-5 py-4 text-[13px] text-zinc-500">Числа на слайдах могут появляться только из этого реестра — пустой реестр означает, что бриф не содержал измеримых данных.</p>
      ) : (
        <table className="w-full border-collapse text-[13px]">
          <thead className="bg-zinc-50 text-left text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-5 py-2">ID</th>
              <th className="px-3 py-2">Значение</th>
              <th className="px-3 py-2">Что означает</th>
              <th className="px-3 py-2">Фрагмент брифа</th>
              <th className="px-5 py-2 text-right">На слайдах</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {facts.map((f) => (
              <tr key={f.id} className="align-top">
                <td className="px-5 py-2 font-mono text-[11px] text-zinc-500">{f.id}</td>
                <td className="whitespace-nowrap px-3 py-2 font-semibold tabular-nums text-zinc-900">
                  {f.value}{f.unit && <span className="ml-1 font-normal text-zinc-500">{f.unit}</span>}
                </td>
                <td className="px-3 py-2 text-zinc-800">{f.label}</td>
                <td className="px-3 py-2 text-xs italic leading-[18px] text-zinc-500">{f.source_span ? `«${f.source_span}»` : "—"}</td>
                <td className="px-5 py-2 text-right">{used.has(f.id) ? <Badge size="sm" tone="success">да</Badge> : <span className="text-xs text-zinc-400">нет</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Collapsible>
  );
}

function SeriesCard({ series }: { series: Series }) {
  const max = Math.max(0, ...series.values);
  return (
    <div className="rounded-lg border border-zinc-200 p-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="min-w-0 truncate text-[13px] font-medium text-zinc-900">{series.name}</p>
        <span className="shrink-0 font-mono text-[11px] text-zinc-400">{series.id}{series.unit && ` · ${series.unit}`}</span>
      </div>
      <ol className="space-y-1">
        {series.categories.map((cat, i) => {
          const v = series.values[i];
          const share = max > 0 && typeof v === "number" ? Math.max(0, v) / max : 0;
          return (
            <li key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] items-center gap-2 text-xs">
              <span className="truncate text-zinc-600" title={cat}>{cat}</span>
              <span className="h-1.5 overflow-hidden rounded-full bg-zinc-100"><span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(share * 100)}%` }} /></span>
              <span className="w-14 text-right tabular-nums text-zinc-900">{typeof v === "number" ? num(v) : "—"}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function SeriesRegistry({ series }: { series: Series[] }) {
  return (
    <Collapsible
      icon={Database}
      title="Ряды данных"
      hint={series.length === 0 ? "диаграммы строить не из чего" : `${plural(series.length, "ряд", "ряда", "рядов")} для диаграмм`}
      right={series.length > 0 && <Badge size="sm">{series.length}</Badge>}
    >
      {series.length === 0 ? (
        <p className="text-[13px] text-zinc-500">В брифе не нашлось последовательностей значений — диаграммы в этой презентации не запланированы.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 min-[1500px]:grid-cols-3">{series.map((s) => <SeriesCard key={s.id} series={s} />)}</div>
      )}
    </Collapsible>
  );
}
