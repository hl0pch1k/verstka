// «Проверка качества» (details drawer): the verdict, one filter row, remarks by slide with the fixes a person can
// apply, what was already fixed automatically, and the list of checks.
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, plural } from "../lib/utils";
import { useApp } from "../store";
import type { FixRequest, FixResult, Issue, Severity } from "../types";
import { AppliedFixes, ChecksReference } from "./AuditFixes";
import { auditRev, groupBySlide, isFixable } from "./AuditHelpers";
import { SlideIssueGroup } from "./AuditIssues";
import { AuditSummaryCard } from "./AuditSummary";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { Tabs } from "./ui/Tabs";
import { variantScore } from "./VariantsHelpers";

type FilterKey = "all" | Severity | "fixable";

const FILTERS: Array<{ key: FilterKey; label: string; test(i: Issue): boolean }> = [
  { key: "all", label: "Все", test: () => true },
  { key: "error", label: "Ошибки", test: (i) => i.severity === "error" },
  { key: "warn", label: "Предупреждения", test: (i) => i.severity === "warn" },
  { key: "info", label: "Заметки", test: (i) => i.severity === "info" },
  { key: "fixable", label: "Исправимые", test: isFixable },
];

export function AuditPanel() {
  const { generation, generationLoading, generationId, activeStrategy, setActiveStrategy, activeVariant, strategyTitle, selectedSlide, setSelectedSlide, setDetail, activeJob, runJob, loadGeneration, toast, manifest } = useApp();

  const audit = activeVariant?.audit ?? null;
  const scopeKey = `${generationId ?? ""}/${activeStrategy ?? ""}/${auditRev(audit)}`;
  const [filter, setFilter] = useState<FilterKey>("all");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [submitting, setSubmitting] = useState(false);

  const allIssues = useMemo(() => audit?.issues ?? [], [audit]);
  const fixableTotal = useMemo(() => allIssues.filter(isFixable).length, [allIssues]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.key, allIssues.filter(f.test).length])) as Record<FilterKey, number>, [allIssues]);
  const current = FILTERS.find((f) => f.key === filter) ?? FILTERS[0];
  const groups = useMemo(() => groupBySlide(allIssues.filter(current.test)), [allIssues, current]);

  // a new report (another variant, or fixes just applied) clears the selection
  useEffect(() => setSelected(new Set()), [scopeKey]);
  useEffect(() => {
    if (filter !== "all" && counts[filter] === 0) setFilter("all");
  }, [counts, filter]);

  const busy = (!!activeJob && (activeJob.status === "queued" || activeJob.status === "running")) || submitting;
  const select = useCallback((id: string, on: boolean) => {
    setSelected((cur) => {
      const next = new Set(cur);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const runFixes = async (body: FixRequest) => {
    if (!generationId || !activeStrategy || busy) return;
    const gid = generationId;
    setSubmitting(true);
    try {
      const { job_id } = await api.fixes(gid, activeStrategy, body);
      runJob(job_id, "Исправляю замечания", {
        kind: "fix",
        onDone: async (job) => {
          await loadGeneration(gid);
          const r = (job.result ?? null) as Partial<FixResult> | null;
          const score = typeof r?.score === "number" && Number.isFinite(r.score) ? Math.round(r.score) : null;
          toast("success", score !== null ? `Готово: оценка качества ${score} из 100` : "Готово: замечания исправлены");
        },
      });
    } catch (e) {
      toast("error", `Не удалось запустить исправление: ${errText(e)}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (generationLoading && !generation) {
    return (
      <div className="space-y-4" aria-busy>
        <div className="skeleton h-36 w-full rounded-3xl" />
        <div className="skeleton h-28 w-full rounded-2xl" />
        <div className="skeleton h-28 w-full rounded-2xl" />
      </div>
    );
  }
  if (!generation || generation.variants.length === 0) {
    return <EmptyState icon={ShieldCheck} title="Пока нечего проверять" hint="Проверка появится вместе с первой презентацией." />;
  }

  const switcher = generation.variants.length > 1 && (
    <Tabs
      variant="pills"
      value={activeStrategy ?? generation.variants[0].strategy}
      onChange={setActiveStrategy}
      items={generation.variants.map((v, i) => {
        const s = variantScore(v, generation.summary?.[v.strategy]?.score);
        return { key: v.strategy, label: `${i + 1} · ${strategyTitle(v.strategy)}`, badge: s === null ? null : Math.round(s), badgeTone: s === null ? "neutral" : s >= 90 ? "success" : s >= 70 ? "warn" : "error" };
      })}
    />
  );

  if (!audit) {
    return (
      <div className="space-y-5">
        {switcher}
        <EmptyState icon={ShieldCheck} title="Для этого варианта проверки нет" hint="Отчёт не сохранился — вероятно, сборка ещё идёт или прервалась." />
      </div>
    );
  }

  const outline = activeVariant?.outline ?? null;
  const headlineOf = (slide: number) => (slide > 0 ? outline?.slides[slide - 1]?.headline ?? null : null);
  const slideOf = (outlineId: string) => {
    const i = outline?.slides.findIndex((s) => s.id === outlineId) ?? -1;
    return i >= 0 ? i + 1 : null;
  };
  const templateSlide = (pid: string) => (manifest?.template_id === generation.template_id ? manifest.patterns.find((p) => p.id === pid)?.source_slide ?? null : null);
  const picked = selected.size;

  return (
    <div className="space-y-5">
      {switcher}
      <AuditSummaryCard
        audit={audit}
        actions={
          (fixableTotal > 0 || picked > 0) && (
            <>
              {picked > 0 && (
                <Button variant="primary" loading={submitting} disabled={busy} onClick={() => void runFixes({ issue_ids: [...selected] })} className="animate-fade">
                  Исправить отмеченные ({picked})
                </Button>
              )}
              {fixableTotal > 0 && (
                <Button variant={picked > 0 ? "secondary" : "primary"} loading={submitting && picked === 0} disabled={busy} onClick={() => void runFixes({ all_deterministic: true })}>
                  Исправить всё автоматически
                </Button>
              )}
            </>
          )
        }
      />

      {allIssues.length === 0 ? (
        <EmptyState icon={CheckCircle2} title="Замечаний нет" hint="Все проверки пройдены — вариант готов к показу." />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-1.5" role="radiogroup" aria-label="Какие замечания показать">
            {FILTERS.filter((f) => f.key === "all" || counts[f.key] > 0).map((f) => (
              <button
                key={f.key}
                type="button"
                role="radio"
                aria-checked={filter === f.key}
                onClick={() => setFilter(f.key)}
                className={cn(
                  "inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
                  filter === f.key ? "bg-zinc-900 text-white" : "bg-white text-zinc-700 shadow-card hover:bg-zinc-50",
                )}
              >
                {f.label}
                <span className={cn("tabular-nums", filter === f.key ? "text-white/60" : "text-zinc-400")}>{counts[f.key]}</span>
              </button>
            ))}
            {fixableTotal > 0 && picked === 0 && <span className="ml-auto text-xs text-zinc-500">Отметьте исправимые замечания галочкой</span>}
          </div>
          <div className="space-y-3">
            {groups.map((g) => (
              <SlideIssueGroup
                key={g.slide}
                group={g}
                headline={headlineOf(g.slide)}
                current={g.slide > 0 && g.slide === selectedSlide}
                selected={selected}
                disabled={busy}
                onSelect={select}
                onShow={() => {
                  setSelectedSlide(g.slide);
                  setDetail(null);
                }}
              />
            ))}
          </div>
          <p className="text-center text-xs text-zinc-400">
            {plural(allIssues.length, "замечание", "замечания", "замечаний")} · оценка = 100 − 10 за ошибку − 3 за предупреждение; заметки её не снижают
          </p>
        </>
      )}

      <AppliedFixes fixes={audit.applied_fixes} slideOf={slideOf} templateSlide={templateSlide} />
      <ChecksReference />
    </div>
  );
}
