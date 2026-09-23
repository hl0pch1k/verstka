// Building blocks of the «Новая презентация» form: field wrapper, switch, strategy option, constants.
import { useId, type ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "../lib/utils";
import type { StrategyInfo } from "../types";

export const PURPOSES: Array<{ value: string; label: string }> = [
  { value: "feature", label: "Фича" },
  { value: "product", label: "Продукт" },
  { value: "project", label: "Проект" },
  { value: "initiative", label: "Инициатива" },
  { value: "report", label: "Отчёт" },
];

export const BRIEF_MIN = 40;
export const SLIDES_MIN = 5;
export const SLIDES_MAX = 20;
export const SLIDES_DEFAULT = 12;

export const SAMPLE_AUDIENCE = "Продуктовый комитет и руководители направлений";

export const SAMPLE_BRIEF = `Запуск функции «Умные сводки» в корпоративном мессенджере VK WorkSpace: итоги пилота за Q2 2026 и план масштабирования.

Проблема: сотрудники тратят в среднем 47 минут в день на чтение рабочих чатов, а 38% сообщений в командных каналах остаются непрочитанными. По опросу 1 240 пользователей 71% хотят получать краткое содержание пропущенных обсуждений.

Решение: «Умные сводки» — автоматическое резюме непрочитанных веток с выделением решений, задач и дедлайнов. Модель работает в контуре компании, данные не покидают периметр.

Результаты пилота (12 команд, 860 пользователей, 8 недель):

| Метрика | До пилота | После пилота | Изменение |
|---|---|---|---|
| Время на чтение чатов, мин/день | 47 | 29 | −38% |
| Доля непрочитанных сообщений | 38% | 14% | −24 п.п. |
| Пропущенные дедлайны, шт/мес | 21 | 8 | −62% |
| NPS функции | — | 64 | — |

Экономика: экономия 18 минут в день на сотрудника — это около 78 часов в год; при масштабировании на 25 000 пользователей эффект оценивается в 1,9 млн человеко-часов. Стоимость инференса — 0,4 ₽ на сводку, в среднем 6 сводок на пользователя в день.

Дорожная карта: Q3 — раскатка на 30% компании и поддержка тредов; Q4 — сводки по звонкам и интеграция с календарём; Q1 2027 — сводки по проектам в задачах.

Риски: качество резюме на смешанных языках (русский/английский), нагрузка на GPU-кластер в пиковые часы, необходимость обучения пользователей. Команда: продакт, 4 инженера, ML-инженер, дизайнер, аналитик.

Просим одобрить бюджет 14,5 млн ₽ на второе полугодие и выделить 2 дополнительные GPU-ноды.`;

/** Label + control + optional hint / error line. */
export function Field({ label, hint, error, required, htmlFor, right, className, children }: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  required?: boolean;
  htmlFor?: string;
  right?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <label htmlFor={htmlFor} className="text-[13px] font-semibold text-zinc-700">
          {label}
          {required && <span className="ml-0.5 text-red-500" aria-hidden>*</span>}
        </label>
        {right}
      </div>
      {children}
      {error ? <p role="alert" className="mt-1.5 text-xs font-medium text-red-600">{error}</p> : hint ? <p className="mt-1.5 text-xs leading-4 text-zinc-500">{hint}</p> : null}
    </div>
  );
}

export const INPUT_CLS =
  "h-11 w-full rounded-xl border-0 bg-zinc-100 px-3.5 text-sm text-zinc-900 placeholder:text-zinc-500 transition-shadow hover:bg-zinc-200/60 focus:bg-white focus:shadow-[0_0_0_2px_#0077FF] focus:outline-none disabled:cursor-not-allowed disabled:opacity-60";

/** Switch with a label and a description. */
export function Toggle({ label, hint, checked, disabled, onChange }: {
  label: string;
  hint?: ReactNode;
  checked: boolean;
  disabled?: boolean;
  onChange(v: boolean): void;
}) {
  const id = useId();
  return (
    <div className={cn("flex items-start gap-3", disabled && "opacity-55")}>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-0.5 h-6 w-10 shrink-0 cursor-pointer rounded-full transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed",
          checked ? "bg-accent" : "bg-zinc-300",
        )}
      >
        <span className={cn("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-[left] duration-200", checked ? "left-[18px]" : "left-0.5")} aria-hidden />
      </button>
      <label htmlFor={id} className={cn("min-w-0 select-none", disabled ? "cursor-not-allowed" : "cursor-pointer")}>
        <span className="block text-[13px] font-semibold leading-5 text-zinc-900">{label}</span>
        {hint && <span className="block text-xs leading-4 text-zinc-500">{hint}</span>}
      </label>
    </div>
  );
}

/** A tiny slide drawn in SVG: what the strategy's decks look like. */
function StrategyArt({ name, active }: { name: string; active: boolean }) {
  const a = active ? "#0077FF" : "#99A2AD";
  const l = active ? "#ADD3FF" : "#E1E3E6";
  const d = active ? "#19191A" : "#6D7885";
  return (
    <svg viewBox="0 0 160 90" className="h-full w-full" aria-hidden>
      <rect width="160" height="90" rx="8" fill="white" />
      {name === "visual" ? (
        <>
          <rect x="12" y="12" width="70" height="7" rx="3.5" fill={d} />
          <text x="12" y="58" fontSize="30" fontWeight="800" fill={a} fontFamily="Onest, sans-serif">+34%</text>
          <rect x="12" y="66" width="52" height="4" rx="2" fill={l} />
          {[0, 1, 2, 3].map((i) => <rect key={i} x={98 + i * 14} y={70 - (i + 1) * 12} width="9" height={(i + 1) * 12} rx="2" fill={i === 3 ? a : l} />)}
        </>
      ) : name === "compact" ? (
        <>
          <rect x="12" y="12" width="80" height="7" rx="3.5" fill={d} />
          {[0, 1].map((c) => (
            <g key={c}>
              <rect x={12 + c * 72} y="28" width="64" height="5" rx="2.5" fill={a} />
              {[0, 1, 2, 3].map((r) => <rect key={r} x={12 + c * 72} y={39 + r * 10} width={r === 3 ? 40 : 60} height="4" rx="2" fill={l} />)}
            </g>
          ))}
        </>
      ) : (
        <>
          <rect x="12" y="12" width="96" height="7" rx="3.5" fill={d} />
          {[0, 1, 2].map((i) => (
            <g key={i}>
              <rect x={12 + i * 48} y="30" width="42" height="46" rx="6" fill={active ? "#EBF4FF" : "#F0F2F5"} />
              <circle cx={22 + i * 48} cy="41" r="4" fill={a} />
              <rect x={18 + i * 48} y="52" width="30" height="4" rx="2" fill={l} />
              <rect x={18 + i * 48} y="60" width="22" height="4" rx="2" fill={l} />
            </g>
          ))}
        </>
      )}
    </svg>
  );
}

/** Selectable strategy card: illustration, title and description. */
export function StrategyOption({ strategy, checked, disabled, onChange }: {
  strategy: StrategyInfo;
  checked: boolean;
  disabled?: boolean;
  onChange(v: boolean): void;
}) {
  return (
    <label
      className={cn(
        "group relative flex cursor-pointer flex-col gap-3 rounded-2xl p-3 transition-all duration-200",
        checked ? "bg-accent-50 shadow-[0_0_0_2px_#0077FF]" : "bg-zinc-100 hover:bg-zinc-200/60",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <input type="checkbox" className="sr-only" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="block aspect-video overflow-hidden rounded-xl shadow-card">
        <StrategyArt name={strategy.name} active={checked} />
      </span>
      <span
        className={cn(
          "absolute right-5 top-5 flex h-6 w-6 items-center justify-center rounded-full transition-colors",
          checked ? "bg-accent text-white" : "bg-white text-transparent shadow-inner-line",
        )}
        aria-hidden
      >
        <Check className="h-3.5 w-3.5" strokeWidth={3} />
      </span>
      <span className="px-1 pb-1">
        <span className="block text-[15px] font-semibold leading-5 text-zinc-900">{strategy.title}</span>
        <span className="mt-1 block text-xs leading-[18px] text-zinc-600">{strategy.description}</span>
      </span>
    </label>
  );
}
