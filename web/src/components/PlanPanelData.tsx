// The figures taken from the text (every number on the slides comes from here) and the data behind the charts.
import { Check } from "lucide-react";
import { mendCut } from "../lib/agent";
import { cn, plural } from "../lib/utils";
import type { Fact, Series } from "../types";
import { Collapsible } from "./ui/Collapsible";
import { Progress } from "./ui/Progress";

const num = (v: number) => v.toLocaleString("ru-RU", { maximumFractionDigits: 2 });

/** «930 000», «60%», «30 дней»: a figure as the text writes it, never broken across lines. */
const figure = (f: Fact) => `${f.value}${f.unit ? (f.unit === "%" ? "%" : ` ${f.unit}`) : ""}`.replace(/ /g, "\u00a0");
const flat = (s: string) => s.toLowerCase().replace(/[\s\u00a0.,«»]+/g, " ").trim();

/** The sentences of the text with the figures taken from each: a sentence that holds six numbers is quoted once. */
function bySentence(facts: Fact[]): Array<{ quote: string | null; facts: Fact[] }> {
  const groups = new Map<string, { quote: string | null; facts: Fact[] }>();
  for (const f of facts) {
    const span = f.source_span?.trim() || null;
    const key = span ?? `#${f.id}`;
    const g = groups.get(key) ?? { quote: span && mendCut(span), facts: [] };
    g.facts.push(f);
    groups.set(key, g);
  }
  return [...groups.values()];
}

/** What a figure means, when the plan says more than the figure itself or its sentence (a tooltip of the chip). */
function meaning(f: Fact): string | null {
  const label = f.label?.trim();
  if (!label) return null;
  const l = flat(label);
  if (l === flat(figure(f)) || l === flat(`${f.value} рублей`) || (f.source_span && l === flat(f.source_span))) return null;
  return label;
}

/** `hint`: the one sentence about the figures checked against the text («70 чисел сверены с текстом»). */
export function FactsRegistry({ facts, used, hint }: { facts: Fact[]; used: Set<string>; hint?: string | null }) {
  if (facts.length === 0) return null;
  // older plans do not link slides to figures: then no figure is marked
  const linked = facts.some((f) => used.has(f.id));
  return (
    <Collapsible title="Цифры из текста" hint={hint ?? plural(facts.length, "цифра", "цифры", "цифр")} keepMounted={false}>
      {/* full-bleed rows in the card's 24px body: the text keeps the card's 24px inset */}
      <ul className="-mx-6 -mb-3 divide-y divide-zinc-100">
        {bySentence(facts).map((g, i) => (
          <li key={i} className="px-6 py-3">
            {g.quote && (
              <p className="line-clamp-2 max-w-[680px] text-caption text-zinc-500" title={g.quote}>
                «{g.quote}»
              </p>
            )}
            <ul className={cn("flex flex-wrap gap-2", g.quote && "mt-2")} aria-label="Числа">
              {g.facts.map((f) => {
                const on = linked && used.has(f.id);
                const what = meaning(f);
                return (
                  <li
                    key={f.id}
                    title={[what, on ? "есть на слайде" : null].filter(Boolean).join(" · ") || undefined}
                    className={cn(
                      "inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-lg px-2 text-footnote font-semibold tabular-nums",
                      on ? "bg-emerald-50 text-emerald-700" : "bg-zinc-100 text-zinc-900",
                    )}
                  >
                    {figure(f)}
                    {on && (
                      <>
                        <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
                        <span className="sr-only">, есть на слайде</span>
                      </>
                    )}
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ul>
    </Collapsible>
  );
}

function SeriesCard({ series }: { series: Series }) {
  const max = Math.max(0, ...series.values);
  return (
    <div className="min-w-0 rounded-xl bg-zinc-50 p-4">
      <p className="mb-2 truncate text-footnote font-semibold text-zinc-900" title={series.unit ? `${series.name}, ${series.unit}` : series.name}>
        {series.name}
        {series.unit && <span className="font-normal text-zinc-500">, {series.unit}</span>}
      </p>
      <ol className="space-y-1">
        {series.categories.map((cat, i) => {
          const v = series.values[i];
          const share = max > 0 && typeof v === "number" ? Math.max(0, v) / max : 0;
          return (
            <li key={i} className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_auto] items-center gap-2 text-caption">
              <span className="truncate text-zinc-600" title={cat}>{cat}</span>
              {/* the bars grow in one after another (40 ms apart, capped) when the section opens */}
              <Progress size="sm" value={share} appear={Math.min(i, 6) * 40} />
              <span className="w-16 text-right tabular-nums text-zinc-900">{typeof v === "number" ? num(v) : "—"}</span>
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
    <Collapsible title="Данные для диаграмм" hint={plural(series.length, "ряд", "ряда", "рядов")} keepMounted={false}>
      <div className="grid grid-cols-2 items-start gap-3">{series.map((s) => <SeriesCard key={s.id} series={s} />)}</div>
    </Collapsible>
  );
}
