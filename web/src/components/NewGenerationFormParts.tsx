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
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <label htmlFor={htmlFor} className="text-xs font-medium text-zinc-700">
          {label}
          {required && <span className="ml-0.5 text-red-500" aria-hidden>*</span>}
        </label>
        {right}
      </div>
      {children}
      {error ? <p className="mt-1.5 text-xs text-red-600">{error}</p> : hint ? <p className="mt-1.5 text-xs text-zinc-500">{hint}</p> : null}
    </div>
  );
}

export const INPUT_CLS =
  "h-9 w-full rounded-lg border border-zinc-200 bg-white px-3 text-[13px] text-zinc-900 shadow-sm placeholder:text-zinc-400 transition-colors hover:border-zinc-300 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-400";

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
    <div className={cn("flex items-start gap-3", disabled && "opacity-60")}>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed",
          checked ? "bg-accent" : "bg-zinc-300",
        )}
      >
        <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-[left]", checked ? "left-[18px]" : "left-0.5")} aria-hidden />
      </button>
      <label htmlFor={id} className={cn("min-w-0 select-none", disabled ? "cursor-not-allowed" : "cursor-pointer")}>
        <span className="block text-[13px] font-medium leading-5 text-zinc-800">{label}</span>
        {hint && <span className="block text-xs leading-4 text-zinc-500">{hint}</span>}
      </label>
    </div>
  );
}

/** Strategy card with a checkbox: title + description. */
export function StrategyOption({ strategy, checked, disabled, onChange }: {
  strategy: StrategyInfo;
  checked: boolean;
  disabled?: boolean;
  onChange(v: boolean): void;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-3 rounded-lg border px-3.5 py-3 transition-colors",
        checked ? "border-accent/60 bg-accent-50/50" : "border-zinc-200 bg-white hover:border-zinc-300",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <input type="checkbox" className="sr-only" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span
        className={cn(
          "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors",
          checked ? "border-accent bg-accent text-white" : "border-zinc-300 bg-white",
        )}
        aria-hidden
      >
        {checked && <Check className="h-3 w-3" strokeWidth={3} />}
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold leading-5 text-zinc-900">{strategy.title}</span>
        <span className="block text-xs leading-4 text-zinc-500">{strategy.description}</span>
      </span>
    </label>
  );
}
