// While a presentation is being built: one calm card with the overall progress and the stages in plain words, and
// a card per variant that follows it from «в очереди» to «готово». The clock makes the five-minute promise visible.
import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import type { VariantProgress } from "../lib/jobText";
import { variantHint } from "../lib/plain";
import { cn } from "../lib/utils";
import { useApp, type ActiveJob } from "../store";

const STAGES = [
  { title: "Читаю текст", hint: "цифры, таблицы и главные мысли" },
  { title: "Составляю план", hint: "что будет на каждом слайде" },
  { title: "Оформляю слайды", hint: "по макетам вашего шаблона" },
  { title: "Проверяю качество", hint: "шрифты, цвета, отступы — и исправляю" },
  { title: "Сохраняю файлы", hint: "PowerPoint, PDF и веб-версия" },
];

function stageOf(job: ActiveJob): number {
  const m = job.message.toLowerCase();
  let byText = 0;
  if (/сохраняю файлы/.test(m)) byText = 4;
  else if (/проверка качества|исправляю замечания/.test(m)) byText = 3;
  else if (/вёрст/.test(m)) byText = 2;
  else if (/план/.test(m)) byText = 1;
  const byProgress = job.progress >= 0.86 ? 4 : job.progress >= 0.6 ? 3 : job.progress >= 0.25 ? 2 : job.progress >= 0.15 ? 1 : 0;
  return Math.max(byText, byProgress);
}

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

  const stage = stageOf(job);
  const pct = Math.round(job.progress * 100);
  const elapsed = Date.now() - job.startedAt;

  return (
    <div className="space-y-5">
      <section className="grid grid-cols-[minmax(0,1fr)_300px] gap-10 rounded-3xl bg-white p-10 shadow-card animate-rise">
        <div className="min-w-0">
          <h1 className="text-[30px] font-bold leading-9 tracking-tight text-zinc-900">Готовлю презентацию</h1>
          <p className="mt-2 max-w-lg text-[15px] leading-6 text-zinc-500">Сразу три варианта оформления — потом выберете лучший. Обычно это занимает меньше минуты.</p>
          <p className="mt-10 font-display text-[64px] font-bold leading-none tracking-tight text-zinc-900 tabular-nums">
            {pct}
            <span className="text-3xl text-zinc-300">%</span>
          </p>
          <div className="mt-5 h-2 overflow-hidden rounded-full bg-zinc-100" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
            <div className="h-full rounded-full bg-accent transition-[width] duration-700 ease-out" style={{ width: `${Math.max(2, pct)}%` }} />
          </div>
          <div className="mt-3 flex items-center justify-between gap-4 text-[13px] text-zinc-500">
            <span className="min-w-0 truncate" aria-live="polite">{message}</span>
            <span className="shrink-0 tabular-nums">
              {clock(elapsed)} <span className="text-zinc-400">· не дольше 5 минут</span>
            </span>
          </div>
        </div>
        <ol className="space-y-1 self-center">
          {STAGES.map((s, i) => {
            const done = i < stage;
            const active = i === stage;
            return (
              <li key={s.title} className={cn("flex items-start gap-3 rounded-2xl px-3 py-2.5 transition-colors duration-300", active && "bg-accent-50")}>
                <span className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition-colors duration-300", done ? "bg-accent text-white" : active ? "bg-white text-accent shadow-[inset_0_0_0_2px_#0077FF]" : "bg-zinc-100 text-zinc-400")} aria-hidden>
                  {done ? <Check key="d" className="h-3.5 w-3.5 animate-pop" strokeWidth={3} /> : active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : i + 1}
                </span>
                <span className="min-w-0">
                  <span className={cn("block text-[14px] font-semibold transition-colors", done || active ? "text-zinc-900" : "text-zinc-400")}>{s.title}</span>
                  <span className={cn("block text-xs", active ? "text-zinc-600" : "text-zinc-400")}>{s.hint}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      {names.length > 1 && (
        <div className={cn("grid gap-4", names.length >= 3 ? "grid-cols-3" : "grid-cols-2")}>
          {names.map((name, i) => {
            const title = strategyTitle(name);
            const st: VariantProgress | undefined = exporting ? { text: "готово", done: true, frac: 1 } : job.variants?.[name];
            return (
              <section key={name} className="animate-rise rounded-2xl bg-white p-4 shadow-card" style={{ animationDelay: `${80 + i * 60}ms` }}>
                <div className="flex items-center gap-3">
                  <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-bold transition-colors duration-300", st?.done ? "bg-emerald-500 text-white" : "bg-zinc-100 text-zinc-600")}>
                    {st?.done ? <Check key="d" className="h-4 w-4 animate-pop" strokeWidth={3} aria-hidden /> : i + 1}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold text-zinc-900">Вариант {i + 1} · {title}</span>
                    <span className="block truncate text-xs text-zinc-500">{variantHint(name)}</span>
                  </span>
                </div>
                <div className="mt-3 h-1 overflow-hidden rounded-full bg-zinc-100">
                  <div className={cn("h-full rounded-full transition-[width] duration-700 ease-out", st?.done ? "bg-emerald-500" : "bg-accent")} style={{ width: `${Math.round((st?.frac ?? 0.04) * 100)}%` }} />
                </div>
                <p className={cn("mt-2 text-xs font-medium", st?.done ? "text-emerald-700" : "text-zinc-500")}>{st?.text ?? "в очереди"}</p>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
