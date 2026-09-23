// The verdict of the quality check in one card: the score ring, what it means in words, and the two fix actions.
import type { ReactNode } from "react";
import { fmtSeconds, plural, scoreTone } from "../lib/utils";
import type { AuditReport } from "../types";
import { ScoreRing } from "./ui/ScoreRing";

const VERDICT: Record<ReturnType<typeof scoreTone>, string> = {
  success: "Отличный результат",
  warn: "Есть что поправить",
  error: "Нужны исправления",
  neutral: "Оценка недоступна",
};

export function AuditSummaryCard({ audit, actions }: { audit: AuditReport; actions?: ReactNode }) {
  const { summary } = audit;
  const counts = [
    summary.errors ? plural(summary.errors, "ошибка", "ошибки", "ошибок") : "ошибок нет",
    summary.warnings ? plural(summary.warnings, "предупреждение", "предупреждения", "предупреждений") : null,
    summary.infos ? plural(summary.infos, "заметка", "заметки", "заметок") : null,
    summary.model_flags ? plural(summary.model_flags, "замечание модели", "замечания модели", "замечаний модели") : null,
  ].filter(Boolean);
  const fixed = audit.applied_fixes.filter((f) => (f as { action?: string }).action !== "rollback").length;
  const facts = [
    plural(summary.checks_run.length, "проверка", "проверки", "проверок"),
    fixed ? `${plural(fixed, "исправление", "исправления", "исправлений")} уже сделано автоматически` : null,
    audit.seconds ? `заняло ${fmtSeconds(audit.seconds)}` : null,
  ].filter(Boolean);

  return (
    <section className="flex items-center gap-6 rounded-3xl bg-white p-6 shadow-card">
      <ScoreRing score={summary.score} size={92} stroke={7} />
      <div className="min-w-0 flex-1">
        <h3 className="text-xl font-bold tracking-tight text-zinc-900">{VERDICT[scoreTone(summary.score)]}</h3>
        <p className="mt-1 text-[15px] text-zinc-700">{counts.join(" · ")}</p>
        <p className="mt-1 text-[13px] text-zinc-500">{facts.join(" · ")}</p>
      </div>
      {actions && <div className="flex shrink-0 flex-col items-stretch gap-2">{actions}</div>}
    </section>
  );
}
