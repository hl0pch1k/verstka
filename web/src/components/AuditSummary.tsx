// The verdict of the quality check in one card: the score ring, what it means in words, the figures checked against
// the text, and the fix actions. The ring draws in and counts; after a fix (or on another variant) the ring and the
// counts roll to the new values and the verdict cross-fades.
import { Fragment, useRef, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { figuresLine } from "../lib/narrate";
import { cn, fmtSeconds, plural, scoreTone } from "../lib/utils";
import type { AuditReport } from "../types";
import { CountUp } from "./ui/CountUp";
import { ScoreRing } from "./ui/ScoreRing";

const VERDICT: Record<ReturnType<typeof scoreTone>, string> = {
  success: "Отличный результат",
  warn: "Есть что поправить",
  error: "Нужны исправления",
  neutral: "Оценка недоступна",
};

/** «3 ошибки» with the number rolling to a new value (the word follows the final value). */
function Count({ n, one, few, many }: { n: number; one: string; few: string; many: string }) {
  return (
    <>
      <CountUp value={n} ms={400} /> {plural(n, one, few, many).replace(/^\S+\s/, "")}
    </>
  );
}

export function AuditSummaryCard({ audit, actions }: { audit: AuditReport; actions?: ReactNode }) {
  const { summary } = audit;
  const counts = [
    summary.errors ? { k: "e", el: <Count n={summary.errors} one="ошибка" few="ошибки" many="ошибок" /> } : null,
    summary.warnings ? { k: "w", el: <Count n={summary.warnings} one="предупреждение" few="предупреждения" many="предупреждений" /> } : null,
    summary.model_flags ? { k: "m", el: <Count n={summary.model_flags} one="замечание модели" few="замечания модели" many="замечаний модели" /> } : null,
  ].filter((c): c is { k: string; el: JSX.Element } => !!c);
  const figures = figuresLine(summary.figures);
  const facts = [plural(summary.checks_run.length, "проверка", "проверки", "проверок"), audit.seconds ? fmtSeconds(audit.seconds) : null].filter(Boolean);
  // the verdict and the counts line cross-fade when their wording changes (a fix, another variant) — not on the first
  // render, where the whole card rises
  const tone = scoreTone(summary.score);
  const kinds = counts.map((c) => c.k).join("") || "none";
  const first = useRef<{ tone: string; kinds: string }>({ tone, kinds });
  const toneSwap = tone !== first.current.tone ? "animate-fade" : undefined;
  const kindsSwap = kinds !== first.current.kinds ? "animate-fade" : undefined;
  if (toneSwap) first.current.tone = "";
  if (kindsSwap) first.current.kinds = "";

  return (
    <section className="flex items-center gap-6 rounded-2xl bg-white p-6 shadow-card">
      <ScoreRing score={summary.score} size={88} stroke={8} />
      <div className="min-w-0 flex-1">
        <h2 key={tone} className={cn("text-title2 font-bold text-zinc-900", toneSwap)}>{VERDICT[tone]}</h2>
        <p key={kinds} className={cn("mt-1 text-body text-zinc-700", kindsSwap)}>
          {counts.length
            ? counts.map((c, i) => (
                <Fragment key={c.k}>
                  {i > 0 && " · "}
                  {c.el}
                </Fragment>
              ))
            : "Ошибок и предупреждений нет"}
        </p>
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
