// «Качество» (details drawer): the verdict, the errors and warnings by slide with the fixes a person can apply, the
// minor notes folded, what was already fixed automatically, and the list of checks. The variant follows the drawer's
// menu.
import { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { useApp } from "../store";
import type { FixRequest, FixResult, Issue } from "../types";
import { AppliedFixes, ChecksReference } from "./AuditFixes";
import { auditRev, groupBySlide, isFixable, isMinor } from "./AuditHelpers";
import { MinorNotes, SlideIssueGroup } from "./AuditIssues";
import { AuditSummaryCard } from "./AuditSummary";
import { Button } from "./ui/Button";
import { Chip } from "./ui/Chip";
import { Collapsible } from "./ui/Collapsible";
import { EmptyState } from "./ui/EmptyState";

type FilterKey = "all" | "error" | "warn" | "fixable";

const FILTERS: Array<{ key: FilterKey; label: string; test(i: Issue): boolean }> = [
  { key: "all", label: "Все", test: () => true },
  { key: "error", label: "Ошибки", test: (i) => i.severity === "error" },
  { key: "warn", label: "Предупреждения", test: (i) => i.severity === "warn" },
  { key: "fixable", label: "Исправимые", test: isFixable },
];

export function AuditPanel() {
  const { generation, generationLoading, generationId, activeStrategy, activeVariant, selectedSlide, setSelectedSlide, setDetail, activeJob, runJob, loadGeneration, toast, manifest } = useApp();

  const audit = activeVariant?.audit ?? null;
  const scopeKey = `${generationId ?? ""}/${activeStrategy ?? ""}/${auditRev(audit)}`;
  const [filter, setFilter] = useState<FilterKey>("all");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [submitting, setSubmitting] = useState(false);

  const allIssues = useMemo(() => audit?.issues ?? [], [audit]);
  // errors, warnings and the model's remarks are the list; the minor notes of the rules stay folded below
  const mainIssues = useMemo(() => allIssues.filter((i) => !isMinor(i)), [allIssues]);
  const minor = useMemo(() => allIssues.filter(isMinor).sort((a, b) => a.slide - b.slide), [allIssues]);
  const fixableTotal = useMemo(() => allIssues.filter(isFixable).length, [allIssues]);
  // the big «fix everything» belongs to errors and warnings; minor notes get their own small action in their section
  const fixableMain = useMemo(() => mainIssues.filter(isFixable).length, [mainIssues]);
  const counts = useMemo(() => Object.fromEntries(FILTERS.map((f) => [f.key, mainIssues.filter(f.test).length])) as Record<FilterKey, number>, [mainIssues]);
  const current = FILTERS.find((f) => f.key === filter) ?? FILTERS[0];
  const groups = useMemo(() => groupBySlide(mainIssues.filter(current.test)), [mainIssues, current]);
  // the filter row earns its place only when the list mixes kinds of remarks; a chip equal to «Все» adds nothing
  const shownFilters = FILTERS.filter((f) => f.key === "all" || (counts[f.key] > 0 && counts[f.key] < mainIssues.length));
  const showFilters = FILTERS.filter((f) => f.key !== "all" && counts[f.key] > 0).length >= 2 && shownFilters.length >= 2;

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
        <div className="skeleton h-36 w-full rounded-2xl" />
        <div className="skeleton h-28 w-full rounded-2xl" />
        <div className="skeleton h-28 w-full rounded-2xl" />
      </div>
    );
  }
  if (!generation || generation.variants.length === 0) {
    return <EmptyState icon={ShieldCheck} title="Пока нечего проверять" />;
  }
  if (!audit) {
    return <EmptyState icon={ShieldCheck} title="Для этого варианта проверки нет" hint="Соберите презентацию заново" />;
  }

  const outline = activeVariant?.outline ?? null;
  const headlineOf = (slide: number) => (slide > 0 ? outline?.slides[slide - 1]?.headline ?? null : null);
  const slideOf = (outlineId: string) => {
    const i = outline?.slides.findIndex((s) => s.id === outlineId) ?? -1;
    return i >= 0 ? i + 1 : null;
  };
  const templateSlide = (pid: string) => (manifest?.template_id === generation.template_id ? manifest.patterns.find((p) => p.id === pid)?.source_slide ?? null : null);
  const picked = selected.size;
  const show = (slide: number) => {
    setSelectedSlide(slide);
    setDetail(null);
  };

  return (
    <div className="space-y-4">
      <AuditSummaryCard
        audit={audit}
        actions={
          (fixableMain > 0 || picked > 0 || fixableTotal > 0) && (
            <>
              {picked > 0 && (
                <Button variant="primary" loading={submitting} disabled={busy} onClick={() => void runFixes({ issue_ids: [...selected] })} className="animate-fade">
                  Исправить отмеченные ({picked})
                </Button>
              )}
              {fixableMain > 0 && (
                <Button variant={picked > 0 ? "secondary" : "primary"} loading={submitting && picked === 0} disabled={busy} onClick={() => void runFixes({ all_deterministic: true })}>
                  Исправить всё автоматически
                </Button>
              )}
              {/* only the minor notes can be fixed: a quiet action that says what it fixes */}
              {fixableMain === 0 && fixableTotal > 0 && picked === 0 && (
                <Button variant="secondary" loading={submitting} disabled={busy} onClick={() => void runFixes({ all_deterministic: true })}>
                  Исправить заметки
                </Button>
              )}
            </>
          )
        }
      />

      {mainIssues.length > 0 && (
        <>
          {showFilters && (
            <div className="flex flex-wrap items-center gap-2" role="radiogroup" aria-label="Какие замечания показать">
              {shownFilters.map((f) => (
                <Chip key={f.key} surface="tinted" role="radio" aria-checked={filter === f.key} selected={filter === f.key} count={counts[f.key]} onClick={() => setFilter(f.key)}>
                  {f.label}
                </Chip>
              ))}
            </div>
          )}
          {groups.map((g) => (
            <SlideIssueGroup
              key={g.slide}
              group={g}
              headline={headlineOf(g.slide)}
              current={g.slide > 0 && g.slide === selectedSlide}
              selected={selected}
              disabled={busy}
              onSelect={select}
              onShow={() => show(g.slide)}
            />
          ))}
        </>
      )}

      {minor.length > 0 && (
        <Collapsible
          title="Мелкие заметки"
          hint={String(minor.length)}
          keepMounted={false}
        >
          <MinorNotes issues={minor} onShow={show} />
        </Collapsible>
      )}
      <AppliedFixes fixes={audit.applied_fixes} slideOf={slideOf} templateSlide={templateSlide} onShow={show} />
      <ChecksReference total={audit.summary.checks_run.length} />
    </div>
  );
}
