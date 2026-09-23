// «Аудит»: the summary header card — the big score plus the counters of the report.
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Bot, Info, ListChecks, OctagonAlert, RefreshCw, Timer, Wand2 } from "lucide-react";
import { cn, fmtSeconds, scoreTone } from "../lib/utils";
import type { AuditReport } from "../types";
import { scoreText } from "./AuditHelpers";
import { Card, CardBody } from "./ui/Card";

type Tone = ReturnType<typeof scoreTone>;

const SCORE_STYLE: Record<Tone, { text: string; ring: string; bar: string; label: string }> = {
  success: { text: "text-emerald-600", ring: "border-emerald-200 bg-emerald-50", bar: "bg-emerald-500", label: "Отличный результат" },
  warn: { text: "text-amber-600", ring: "border-amber-200 bg-amber-50", bar: "bg-amber-500", label: "Есть что поправить" },
  error: { text: "text-red-600", ring: "border-red-200 bg-red-50", bar: "bg-red-500", label: "Нужны исправления" },
  neutral: { text: "text-zinc-500", ring: "border-zinc-200 bg-zinc-50", bar: "bg-zinc-400", label: "Оценка недоступна" },
};

interface Stat {
  icon: LucideIcon;
  label: string;
  value: string;
  tone?: "error" | "warn" | "info" | "accent" | "neutral";
  hint?: string;
}

const STAT_TONE: Record<NonNullable<Stat["tone"]>, string> = {
  error: "text-red-600",
  warn: "text-amber-600",
  info: "text-sky-600",
  accent: "text-accent-700",
  neutral: "text-zinc-900",
};

export function AuditSummaryCard({ audit }: { audit: AuditReport }) {
  const { summary } = audit;
  const tone = scoreTone(summary.score);
  const style = SCORE_STYLE[tone];
  const score = Number.isFinite(summary.score) ? Math.min(100, Math.max(0, summary.score)) : 0;

  const stats: Stat[] = [
    { icon: OctagonAlert, label: "Ошибки", value: String(summary.errors), tone: summary.errors > 0 ? "error" : "neutral" },
    { icon: AlertTriangle, label: "Предупреждения", value: String(summary.warnings), tone: summary.warnings > 0 ? "warn" : "neutral" },
    { icon: Info, label: "Заметки", value: String(summary.infos), tone: summary.infos > 0 ? "info" : "neutral" },
    { icon: Bot, label: "Флаги модели", value: String(summary.model_flags), tone: summary.model_flags > 0 ? "accent" : "neutral", hint: "Замечания LLM/VLM-проверок" },
    { icon: RefreshCw, label: "Проходов", value: String(audit.iterations), hint: "Проходов «проверка → исправление»" },
    { icon: Wand2, label: "Исправлений", value: String(audit.applied_fixes.length), tone: audit.applied_fixes.length > 0 ? "accent" : "neutral", hint: "Применено автоисправлений" },
    { icon: Timer, label: "Время", value: fmtSeconds(audit.seconds) },
    { icon: ListChecks, label: "Проверок", value: String(summary.checks_run.length), hint: summary.checks_run.join(", ") || undefined },
  ];

  return (
    <Card>
      <CardBody className="flex items-stretch gap-6 py-5">
        <div className={cn("flex w-44 shrink-0 flex-col items-center justify-center rounded-xl border px-4 py-4 text-center", style.ring)}>
          <div className="flex items-baseline gap-1">
            <span className={cn("text-5xl font-semibold leading-none tabular-nums tracking-tight", style.text)}>{scoreText(summary.score)}</span>
            <span className="text-sm font-medium text-zinc-400">/100</span>
          </div>
          <div className="mt-2 text-xs font-medium text-zinc-600">Оценка качества</div>
          <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-white/80 ring-1 ring-inset ring-black/5" aria-hidden>
            <div className={cn("h-full rounded-full transition-[width] duration-500", style.bar)} style={{ width: `${score}%` }} />
          </div>
          <div className={cn("mt-2 text-[11px] font-medium", style.text)}>{style.label}</div>
        </div>

        <div className="grid min-w-0 flex-1 grid-cols-4 gap-x-6 gap-y-4 self-center">
          {stats.map((s) => (
            <div key={s.label} className="min-w-0" title={s.hint}>
              <div className="flex items-center gap-1.5 text-xs text-zinc-500">
                <s.icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="truncate">{s.label}</span>
              </div>
              <div className={cn("mt-1 text-xl font-semibold leading-6 tabular-nums", STAT_TONE[s.tone ?? "neutral"])}>{s.value}</div>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}
