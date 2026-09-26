// «Качество» (details drawer): the verdict, the errors and warnings by slide with the fixes a person can apply, the
// minor notes folded, what was already fixed automatically, and the list of checks. The variant follows the drawer's
// menu. Motion: a filter swaps the list with a short cross-fade; during a fix the remarks it works on dim, and after
// it the slides with nothing left fold away while the score ring counts to the new score.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { useApp } from "../store";
import type { FixRequest, FixResult, Issue } from "../types";
import { AppliedFixes, ChecksReference } from "./AuditFixes";
import { auditRev, groupBySlide, isFixable, isMinor, type SlideGroup } from "./AuditHelpers";
import { MinorNotes, SlideIssueGroup, useLeaving } from "./AuditIssues";
import { AuditSummaryCard } from "./AuditSummary";
import { Button } from "./ui/Button";
import { Chip } from "./ui/Chip";
import { Collapse } from "./ui/Collapse";
import { Collapsible } from "./ui/Collapsible";
import { CountUp } from "./ui/CountUp";
import { EmptyState } from "./ui/EmptyState";

type FilterKey = "all" | "error" | "warn" | "fixable";

const FILTERS: Array<{ key: FilterKey; label: string; test(i: Issue): boolean }> = [
  { key: "all", label: "Все", test: () => true },
  { key: "error", label: "Ошибки", test: (i) => i.severity === "error" },
  { key: "warn", label: "Предупреждения", test: (i) => i.severity === "warn" },
  { key: "fixable", label: "Исправимые", test: isFixable },
];

/** The slides' groups: a group whose remarks a fix removed folds away (300 ms) and the groups below glide up. The gap
 *  above each group lives inside its fold (a padded box: padding on the clipped box itself would stay behind as a
 *  16px strip and snap shut at the end), so it folds with it and an empty list takes no room at all. */
function IssueGroups({ groups, render }: { groups: SlideGroup[]; render(g: SlideGroup, leaving: boolean): JSX.Element }) {
  const list = useLeaving(groups, (g) => String(g.slide), (a, b) => a.slide - b.slide);
  return (
    <div>
      {list.map(({ item, leaving }) => (
        <Collapse key={item.slide} open={!leaving}>
          <div className="pt-4">{render(item, leaving)}</div>
        </Collapse>
      ))}
    </div>
  );
}

export function AuditPanel() {
  const { generation, generationLoading, generationId, activeStrategy, activeVariant, selectedSlide, setSelectedSlide, setDetail, activeJob, runJob, loadGeneration, toast, manifest } = useApp();

  const audit = activeVariant?.audit ?? null;
  const scopeKey = `${generationId ?? ""}/${activeStrategy ?? ""}/${auditRev(audit)}`;
  const [filter, setFilterState] = useState<FilterKey>("all");
  // the list cross-fades when the person picks another filter (not when the tab opens: the cards rise then)
  const filtered = useRef(false);
  const setFilter = (f: FilterKey) => {
    filtered.current = true;
    setFilterState(f);
  };
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [submitting, setSubmitting] = useState(false);
  // what the running fix works on: the marked remarks, or every fixable one («Исправить всё»)
  const [fixing, setFixing] = useState<Set<string> | "all" | null>(null);

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
    if (filter !== "all" && counts[filter] === 0) setFilterState("all");
  }, [counts, filter]);

  const busy = (!!activeJob && (activeJob.status === "queued" || activeJob.status === "running")) || submitting;
  useEffect(() => {
    if (!busy) setFixing(null);
  }, [busy]);
  const isFixing = (i: Issue) => !!fixing && busy && (fixing === "all" ? isFixable(i) : fixing.has(i.id));
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
    setFixing(body.issue_ids ? new Set(body.issue_ids) : "all");
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
      setFixing(null);
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
                <Button variant="primary" loading={submitting} disabled={busy} onClick={() => void runFixes({ issue_ids: [...selected] })} className="animate-fade-in">
                  Исправить отмеченные (<CountUp value={picked} ms={400} />)
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

      {/* the filter row and the slides' groups carry their own 16px gaps inside their folds (hence no gap of the column
          here: !mt-0), so when a fix leaves nothing, everything folds away and the cards below glide up by exactly that
          much — no strip left behind, no snap at the end */}
      <div className="!mt-0">
        <Collapse open={mainIssues.length > 0 && showFilters}>
          <div className="flex flex-wrap items-center gap-2 pt-4" role="radiogroup" aria-label="Какие замечания показать">
            {shownFilters.map((f) => (
              <Chip key={f.key} surface="tinted" role="radio" aria-checked={filter === f.key} selected={filter === f.key} count={counts[f.key]} onClick={() => setFilter(f.key)}>
                {f.label}
              </Chip>
            ))}
          </div>
        </Collapse>
        {/* keyed by the filter (a cross-fade when it changes) and the variant (another variant's list is a swap, not a
            fold); a fix keeps the key, so the slides it cleared fold away — also the last one */}
        <div key={filter} className={filtered.current ? "animate-fade [animation-duration:150ms]" : undefined}>
          <IssueGroups
            key={`${generationId ?? ""}/${activeStrategy ?? ""}`}
            groups={groups}
            render={(g, leaving) => (
              <SlideIssueGroup
                group={g}
                headline={headlineOf(g.slide)}
                current={g.slide > 0 && g.slide === selectedSlide}
                selected={selected}
                disabled={busy || leaving}
                onSelect={select}
                onShow={() => show(g.slide)}
                fixing={(i) => leaving || isFixing(i)}
              />
            )}
          />
        </div>
      </div>

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
