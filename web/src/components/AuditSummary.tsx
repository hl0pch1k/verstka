// The verdict of the quality check in one card: the score ring, what it means in words, the figures checked against
// the text, and the fix actions.
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { figuresLine } from "../lib/narrate";
import { cn, fmtSeconds, plural, scoreTone } from "../lib/utils";
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
    summary.errors ? plural(summary.errors, "ошибка", "ошибки", "ошибок") : null,
    summary.warnings ? plural(summary.warnings, "предупреждение", "предупреждения", "предупреждений") : null,
    summary.model_flags ? plural(summary.model_flags, "замечание модели", "замечания модели", "замечаний модели") : null,
  ].filter(Boolean);
  const figures = figuresLine(summary.figures);
  const facts = [plural(summary.checks_run.length, "проверка", "проверки", "проверок"), audit.seconds ? fmtSeconds(audit.seconds) : null].filter(Boolean);

  return (
    <section className="flex items-center gap-6 rounded-2xl bg-white p-6 shadow-card">
      <ScoreRing score={summary.score} size={88} stroke={8} />
      <div className="min-w-0 flex-1">
        <h2 className="text-title2 font-bold text-zinc-900">{VERDICT[scoreTone(summary.score)]}</h2>
        <p className="mt-1 text-body text-zinc-700">{counts.length ? counts.join(" · ") : "Ошибок и предупреждений нет"}</p>
        {figures && (
          <p className={cn("mt-2 flex items-center gap-2 text-footnote", figures.tone === "warn" ? "text-amber-700" : "text-zinc-700")} title={figures.title}>
            {figures.tone === "warn" ? <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" aria-hidden /> : <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" aria-hidden />}
            {figures.text}
          </p>
        )}
        <p className="mt-1 text-footnote text-zinc-500">{facts.join(" · ")}</p>
      </div>
      {actions && <div className="flex shrink-0 flex-col items-stretch gap-2">{actions}</div>}
    </section>
  );
}
