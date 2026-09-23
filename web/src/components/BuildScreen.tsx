// While a generation runs, the variants step shows the build: stages of the pipeline, progress and the clock
// (the brief allows five minutes per deck — the timer makes the budget visible).
import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { cn } from "../lib/utils";
import type { ActiveJob } from "../store";

const STAGES = [
  { title: "Читаю текст", hint: "нахожу цифры, таблицы и главные мысли" },
  { title: "Составляю план", hint: "что будет на каждом слайде" },
  { title: "Оформляю слайды", hint: "по макетам вашего шаблона" },
  { title: "Проверяю качество", hint: "шрифты, цвета, отступы, читаемость — и исправляю" },
  { title: "Сохраняю файлы", hint: "PowerPoint, PDF и веб-версия" },
];

function stageOf(job: ActiveJob): number {
  const m = job.message.toLowerCase();
  let byText = 0;
  if (/export|экспорт/.test(m)) byText = 4;
  else if (/audit|autofix|аудит|автофикс/.test(m)) byText = 3;
  else if (/render|вёрст|synth|clone/.test(m)) byText = 2;
  else if (/plan|план/.test(m)) byText = 1;
  const byProgress = job.progress >= 0.86 ? 4 : job.progress >= 0.6 ? 3 : job.progress >= 0.25 ? 2 : job.progress >= 0.15 ? 1 : 0;
  return Math.max(byText, byProgress);
}

const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export function BuildScreen({ job }: { job: ActiveJob }) {
  // the interval only asks for a re-render; the clock itself is read at render time, so throttled timers of a
  // background tab never make it lag behind
  const [, tick] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);
  const stage = stageOf(job);
  const pct = Math.round(job.progress * 100);
  const elapsed = Date.now() - job.startedAt;

  return (
    <div className="relative overflow-hidden rounded-[28px] bg-ink px-12 py-11 text-white animate-fade-in">
      <div className="dot-grid-dark absolute inset-0" aria-hidden />
      <div className="absolute -right-32 -top-40 h-[420px] w-[420px] rounded-full bg-accent/25 blur-[120px]" aria-hidden />
      <div className="relative grid grid-cols-[minmax(0,1fr)_340px] gap-12">
        <div>
          <h1 className="text-[34px] font-bold leading-[42px] tracking-tight">Готовлю презентацию</h1>
          <p className="mt-2 max-w-xl text-[15px] leading-6 text-white/60">Сразу три варианта оформления — потом выберете лучший. Обычно это занимает меньше минуты.</p>

          <div className="mt-9 flex items-end gap-4">
            <span className="text-[72px] font-bold leading-none tabular-nums tracking-tight">{pct}<span className="text-4xl text-white/40">%</span></span>
            <span className="mb-2 min-w-0 truncate text-sm text-white/55" aria-live="polite">{job.message}</span>
          </div>
          <div className="mt-5 h-2 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
            <div className="relative h-full overflow-hidden rounded-full bg-accent transition-[width] duration-700 ease-out" style={{ width: `${Math.max(3, pct)}%` }}>
              <span className="absolute inset-0 animate-sweep bg-gradient-to-r from-transparent via-white/40 to-transparent" aria-hidden />
            </div>
          </div>
          <div className="mt-4 flex items-center gap-6 text-[13px] text-white/55">
            <span>Прошло <span className="font-semibold tabular-nums text-white">{clock(elapsed)}</span></span>
            <span>Гарантированно не дольше <span className="font-semibold tabular-nums text-white">5 минут</span></span>
          </div>
        </div>

        <ol className="space-y-1.5 self-center">
          {STAGES.map((s, i) => {
            const done = i < stage;
            const active = i === stage;
            return (
              <li key={s.title} className={cn("flex items-start gap-3.5 rounded-2xl px-4 py-3 transition-colors", active && "bg-white/[0.07]")}>
                <span
                  className={cn(
                    "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                    done ? "bg-accent text-white" : active ? "bg-white text-ink" : "bg-white/[0.08] text-white/40",
                  )}
                  aria-hidden
                >
                  {done ? <Check className="h-4 w-4" strokeWidth={3} /> : active ? <Loader2 className="h-4 w-4 animate-spin" /> : i + 1}
                </span>
                <span className="min-w-0">
                  <span className={cn("block text-[15px] font-semibold", done || active ? "text-white" : "text-white/45")}>{s.title}</span>
                  <span className={cn("block text-xs", active ? "text-white/60" : "text-white/35")}>{s.hint}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
