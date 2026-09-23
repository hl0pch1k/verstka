// The figures taken from the text (every number on the slides comes from here) and the data behind the charts.
import { Check } from "lucide-react";
import { plural } from "../lib/utils";
import type { Fact, Series } from "../types";
import { Collapsible } from "./ui/Collapsible";

const num = (v: number) => v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });

export function FactsRegistry({ facts, used }: { facts: Fact[]; used: Set<string> }) {
  if (facts.length === 0) return null;
  const inUse = facts.filter((f) => used.has(f.id)).length;
  return (
    <Collapsible title="Цифры из текста" hint={`${plural(facts.length, "цифра", "цифры", "цифр")}, на слайдах ${inUse} — других чисел на слайдах нет`} bodyClassName="px-0 pb-2 pt-0">
      <table className="w-full border-collapse text-[13px]">
        <thead className="text-left text-xs font-medium text-zinc-400">
          <tr>
            <th className="px-6 py-2 font-medium">Значение</th>
            <th className="px-3 py-2 font-medium">Что означает</th>
            <th className="px-3 py-2 font-medium">Откуда в тексте</th>
            <th className="px-6 py-2 text-right font-medium">На слайде</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {facts.map((f) => (
            <tr key={f.id} className="align-top" title={f.id}>
              <td className="whitespace-nowrap px-6 py-2.5 font-semibold tabular-nums text-zinc-900">
                {f.value}
                {f.unit && <span className="ml-1 font-normal text-zinc-500">{f.unit}</span>}
              </td>
              <td className="px-3 py-2.5 text-zinc-800">{f.label}</td>
              <td className="px-3 py-2.5 text-xs leading-[18px] text-zinc-500">{f.source_span ? `«${f.source_span}»` : "—"}</td>
              <td className="px-6 py-2.5 text-right">{used.has(f.id) ? <Check className="ml-auto h-4 w-4 text-emerald-600" strokeWidth={3} aria-label="да" /> : <span className="text-xs text-zinc-300">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Collapsible>
  );
}

function SeriesCard({ series }: { series: Series }) {
  const max = Math.max(0, ...series.values);
  return (
    <div className="rounded-2xl bg-zinc-50 p-4" title={series.id}>
      <p className="mb-2 truncate text-[13px] font-semibold text-zinc-900">
        {series.name}
        {series.unit && <span className="font-normal text-zinc-500">, {series.unit}</span>}
      </p>
      <ol className="space-y-1.5">
        {series.categories.map((cat, i) => {
          const v = series.values[i];
          const share = max > 0 && typeof v === "number" ? Math.max(0, v) / max : 0;
          return (
            <li key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] items-center gap-2 text-xs">
              <span className="truncate text-zinc-600" title={cat}>{cat}</span>
              <span className="h-1.5 overflow-hidden rounded-full bg-zinc-200/70"><span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round(share * 100)}%` }} /></span>
              <span className="w-14 text-right tabular-nums text-zinc-900">{typeof v === "number" ? num(v) : "—"}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function SeriesRegistry({ series }: { series: Series[] }) {
  if (series.length === 0) return null;
  return (
    <Collapsible title="Данные для диаграмм" hint={plural(series.length, "ряд значений", "ряда значений", "рядов значений")}>
      <div className="grid grid-cols-2 gap-3">{series.map((s) => <SeriesCard key={s.id} series={s} />)}</div>
    </Collapsible>
  );
}
