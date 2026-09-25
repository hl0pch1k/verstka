// While a presentation is being built: on the left the overall progress with the clock (the five-minute promise)
// and the three variants; on the right the agent's work as it happens — Аналитик, Дизайнер with a line per slide,
// Критик, Правка, Вёрстка, Проверка — in plain words, calm: lines only ever get added, the list follows the newest.
import { useEffect, useMemo, useState } from "react";
import { Check } from "lucide-react";
import { buildTimeline, type PhaseKey } from "../lib/agent";
import type { VariantProgress } from "../lib/jobText";
import { variantHint } from "../lib/plain";
import { cn } from "../lib/utils";
import { useApp, type ActiveJob } from "../store";
import { AgentTimeline } from "./simple/AgentTimeline";

const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export function BuildScreen({ job }: { job: ActiveJob }) {
  const { strategies, strategyTitle } = useApp();
  // the interval only asks for a re-render; the clock is read at render time (throttled background tabs never lag)
  const [, tick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  const names = job.items?.length ? job.items : strategies.map((s) => s.name);
  const message = job.message;
  // saving the files means every variant has been laid out and checked
  const exporting = /^сохраняю файлы/i.test(message);
  const pct = Math.round(job.progress * 100);
  const elapsed = Date.now() - job.startedAt;

  const variantOf = (name: string): VariantProgress | undefined => (exporting ? { text: "готово", done: true, frac: 1 } : job.variants?.[name]);
  // the pipeline's own messages speak for the steps the agent does not narrate (laying out, checking)
  const layoutNote = useMemo(() => {
    const busy = names.map((n) => ({ n, st: job.variants?.[n] })).find(({ st }) => st && !st.done && /вёрстка|план готов/.test(st.text));
    return busy?.st ? `${strategyTitle(busy.n)}: ${busy.st.text}` : null;
  }, [names, job.variants, strategyTitle]);
  // the variants are laid out one after another: the check of the first must not end «Вёрстка» for the others
  const laying = !exporting && names.some((n) => (job.variants?.[n]?.frac ?? 0) < 0.75);
  const phase: PhaseKey | null = job.phase === "check" && laying ? "layout" : job.phase ?? null;
  const checkNote = /проверка качества|исправляю замечания|сохраняю файлы/i.test(message) ? message : null;
  const rows = useMemo(() => {
    const notes: Partial<Record<PhaseKey, string | null>> = {
      layout: phase === "layout" ? layoutNote : null,
      check: phase === "check" ? checkNote : null,
    };
    // before Agent v2 the plan came in one piece: the designer row says so instead of listing slides
    if (!job.agent?.length && phase && phase !== "analyst") notes.designer = "план готов";
    return buildTimeline({ events: job.agent ?? [], phase, running: true, notes });
  }, [job.agent, phase, layoutNote, checkNote]);
  const step = Math.max(1, rows.findIndex((r) => r.status === "active") + 1 || rows.filter((r) => r.status === "done" || r.status === "skipped").length);

  return (
    <div className="grid grid-cols-[340px_minmax(0,1fr)] items-start gap-5">
      <div className="space-y-4">
        <section className="rounded-3xl bg-white p-7 shadow-card animate-rise">
          <h1 className="text-[26px] font-bold leading-8 tracking-tight text-zinc-900">Готовлю презентацию</h1>
          <p className="mt-2 text-[14px] leading-5 text-zinc-500">Агент читает текст, продумывает каждый слайд, проверяет себя и собирает три варианта оформления.</p>
          <p className="mt-7 font-display text-[56px] font-bold leading-none tracking-tight text-zinc-900 tabular-nums">
            {pct}
            <span className="text-3xl text-zinc-300">%</span>
          </p>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-zinc-100" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
            <div className="h-full rounded-full bg-accent transition-[width] duration-700 ease-out" style={{ width: `${Math.max(2, pct)}%` }} />
          </div>
          <p className="mt-3 line-clamp-2 h-10 text-[13px] leading-5 text-zinc-600" aria-live="polite">{message}</p>
          <p className="mt-2 text-[13px] tabular-nums text-zinc-500">
            {clock(elapsed)} <span className="text-zinc-400">· не дольше 5 минут</span>
          </p>
        </section>

        {names.length > 1 && (
          <section className="rounded-3xl bg-white p-2 shadow-card animate-rise" style={{ animationDelay: "80ms" }} aria-label="Варианты">
            {names.map((name, i) => {
              const st = variantOf(name);
              return (
                <div key={name} className="rounded-2xl px-3 py-2.5">
                  <div className="flex items-center gap-3">
                    <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-bold transition-colors duration-300", st?.done ? "bg-emerald-500 text-white" : "bg-zinc-100 text-zinc-600")}>
                      {st?.done ? <Check key="d" className="h-3.5 w-3.5 animate-pop" strokeWidth={3} aria-hidden /> : i + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] font-semibold text-zinc-900" title={variantHint(name)}>Вариант {i + 1} · {strategyTitle(name)}</span>
                      <span className={cn("block truncate text-xs", st?.done ? "font-medium text-emerald-700" : st ? "text-zinc-600" : "text-zinc-400")}>{st?.text ?? "в очереди"}</span>
                    </span>
                  </div>
                  <div className="ml-10 mt-2 h-1 overflow-hidden rounded-full bg-zinc-100">
                    <div className={cn("h-full rounded-full transition-[width] duration-700 ease-out", st?.done ? "bg-emerald-500" : "bg-accent")} style={{ width: `${Math.round((st?.frac ?? 0.04) * 100)}%` }} />
                  </div>
                </div>
              );
            })}
          </section>
        )}
      </div>

      <section className="flex h-[calc(100vh-210px)] max-h-[640px] min-h-[420px] flex-col overflow-hidden rounded-3xl bg-white shadow-card animate-rise" style={{ animationDelay: "40ms" }} aria-label="Как работает агент">
        <header className="flex shrink-0 items-baseline justify-between gap-4 px-7 pb-2 pt-6">
          <h2 className="text-[17px] font-semibold text-zinc-900">Как работает агент</h2>
          <span className="text-xs tabular-nums text-zinc-400">шаг {Math.min(step, rows.length)} из {rows.length}</span>
        </header>
        <div data-follow className="scroll-thin min-h-0 flex-1 overflow-y-auto px-7 pb-6 pt-1 [mask-image:linear-gradient(to_bottom,transparent_0,#000_14px)]">
          <AgentTimeline rows={rows} variantTitle={strategyTitle} follow />
        </div>
      </section>
    </div>
  );
}
