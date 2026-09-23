// «Аудит»: the active variant's audit report — score, filters, issues by slide, fixes and the checks reference.
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Filter, Layers, ShieldCheck, Sparkles, SquareCheckBig, Wand2, X } from "lucide-react";
import { api } from "../api";
import { errText } from "../lib/narrate";
import { cn, plural, SEVERITY_LABEL } from "../lib/utils";
import { useApp } from "../store";
import type { FixRequest, FixResult, Severity } from "../types";
import { ChecksReference, AppliedFixes } from "./AuditFixes";
import { applyFilter, auditRev, countBySeverity, DEFAULT_FILTER, groupBySlide, isFixable, SEVERITIES, type IssueFilter } from "./AuditHelpers";
import { SlideIssueGroup } from "./AuditIssues";
import { AuditSummaryCard } from "./AuditSummary";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { Tabs, type TabItem } from "./ui/Tabs";

const CHIP_ON: Record<Severity, string> = {
  error: "border-transparent bg-red-50 text-red-700",
  warn: "border-transparent bg-amber-50 text-amber-800",
  info: "border-transparent bg-sky-50 text-sky-700",
};

export function AuditPanel() {
  const {
    generation, generationLoading, generationId, activeStrategy, setActiveStrategy, activeVariant, strategyTitle,
    selectedSlide, setSelectedSlide, setTab, activeJob, runJob, loadGeneration, toast,
  } = useApp();

  const audit = activeVariant?.audit ?? null;
  const rev = auditRev(audit);
  const scopeKey = `${generationId ?? ""}/${activeStrategy ?? ""}/${rev}`;

  const [filter, setFilter] = useState<IssueFilter>(DEFAULT_FILTER);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [openSlides, setOpenSlides] = useState<Set<number>>(() => new Set());
  const [submitting, setSubmitting] = useState(false);

  const allIssues = useMemo(() => audit?.issues ?? [], [audit]);
  const totalCounts = useMemo(() => countBySeverity(allIssues), [allIssues]);
  const fixableTotal = useMemo(() => allIssues.filter(isFixable).length, [allIssues]);
  const visible = useMemo(() => applyFilter(allIssues, filter), [allIssues, filter]);
  const groups = useMemo(() => groupBySlide(visible), [visible]);
  const filtered = visible.length !== allIssues.length;

  // A new report (another variant, another generation, or fixes just applied) resets the selection and the accordion.
  useEffect(() => {
    setSelected(new Set());
    const all = groupBySlide(allIssues);
    const withErrors = all.filter((g) => g.counts.error > 0).map((g) => g.slide);
    setOpenSlides(new Set(all.length <= 6 || withErrors.length === 0 ? all.map((g) => g.slide) : withErrors));
  }, [scopeKey]);

  const busy = !!activeJob || submitting;

  const toggleSeverity = (s: Severity) =>
    setFilter((f) => {
      const next = new Set(f.severities);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return { ...f, severities: next };
    });

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
      runJob(job_id, "Применяю исправления", {
        kind: "fix",
        onDone: async (job) => {
          await loadGeneration(gid);
          const r = (job.result ?? null) as Partial<FixResult> | null;
          const score = typeof r?.score === "number" && Number.isFinite(r.score) ? Math.round(r.score) : null;
          const applied = Array.isArray(r?.applied) ? r.applied.length : null;
          const tail = applied !== null ? `, ${plural(applied, "исправление", "исправления", "исправлений")}` : "";
          toast("success", score !== null ? `Исправления применены: новая оценка ${score}/100${tail}` : "Исправления применены: отчёт аудита обновлён");
        },
      });
    } catch (e) {
      toast("error", `Не удалось запустить исправления: ${errText(e)}`);
    } finally {
      setSubmitting(false);
    }
  };

  // ---- empty states -------------------------------------------------------------------------------------------------
  if (generationLoading && !generation) {
    return (
      <div className="space-y-4" aria-busy>
        <div className="skeleton h-8 w-72" />
        <div className="skeleton h-36 w-full" />
        <div className="skeleton h-24 w-full" />
        <div className="skeleton h-24 w-full" />
      </div>
    );
  }
  if (!generation || generation.variants.length === 0) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title="Пока нечего проверять"
        hint="Аудит появится после первой генерации: каждый вариант вёрстки проверяется по детерминированным правилам шаблона и, при желании, моделью."
        action={<Button variant="primary" icon={Sparkles} onClick={() => setTab("template")}>Начать с шаблона</Button>}
      />
    );
  }

  const strategyItems: TabItem<string>[] = generation.variants.map((v) => {
    const errors = v.audit?.summary.errors ?? null;
    return { key: v.strategy, label: strategyTitle(v.strategy), badge: errors, badgeTone: errors === null ? "neutral" : errors > 0 ? "error" : "success" };
  });
  const switcher = <Tabs items={strategyItems} value={activeStrategy ?? strategyItems[0].key} onChange={setActiveStrategy} variant="pills" />;

  if (!audit) {
    return (
      <div className="space-y-4">
        {switcher}
        <EmptyState
          icon={ShieldCheck}
          title="Аудит для этого варианта не запускался"
          hint="Отчёт не был сохранён — вероятно, генерация ещё идёт или завершилась с ошибкой. Другие варианты могут быть проверены."
          action={<Button icon={Layers} onClick={() => setTab("variants")}>К вариантам</Button>}
        />
      </div>
    );
  }

  const selectedCount = selected.size;
  const headlineOf = (slide: number) => (slide > 0 ? activeVariant?.outline?.slides[slide - 1]?.headline ?? null : null);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        {switcher}
        <div className="flex items-center gap-2">
          <Button icon={Wand2} disabled={busy || fixableTotal === 0} loading={submitting} onClick={() => void runFixes({ all_deterministic: true })} title="Применить все детерминированные автоисправления">
            Исправить все автоматические
          </Button>
          <Button variant="primary" icon={SquareCheckBig} disabled={busy || selectedCount === 0} loading={submitting} onClick={() => void runFixes({ issue_ids: [...selected] })}>
            Исправить выбранные ({selectedCount})
          </Button>
        </div>
      </div>

      <AuditSummaryCard audit={audit} />

      <AppliedFixes fixes={audit.applied_fixes} iterations={audit.iterations} />

      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
          <Filter className="h-3.5 w-3.5" aria-hidden />
          Фильтр
        </span>
        {SEVERITIES.map((s) => {
          const on = filter.severities.has(s);
          return (
            <button
              key={s}
              type="button"
              aria-pressed={on}
              onClick={() => toggleSeverity(s)}
              className={cn(
                "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
                on ? CHIP_ON[s] : "border-transparent bg-zinc-100 text-zinc-400 hover:text-zinc-700",
              )}
            >
              {SEVERITY_LABEL[s]}
              <span className="tabular-nums opacity-70">{totalCounts[s]}</span>
            </button>
          );
        })}
        <button
          type="button"
          aria-pressed={filter.fixableOnly}
          onClick={() => setFilter((f) => ({ ...f, fixableOnly: !f.fixableOnly }))}
          className={cn(
            "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
            filter.fixableOnly ? "border-transparent bg-accent-50 text-accent-700" : "border-transparent bg-zinc-100 text-zinc-500 hover:text-zinc-800",
          )}
        >
          <Wand2 className="h-3.5 w-3.5" aria-hidden />
          Только исправимые
          <span className="tabular-nums opacity-70">{fixableTotal}</span>
        </button>
        {filtered && (
          <Button size="sm" variant="ghost" icon={X} onClick={() => setFilter(DEFAULT_FILTER)}>
            Сбросить
          </Button>
        )}
        <span className="ml-auto text-xs text-zinc-500">
          {filtered ? `${visible.length} из ${plural(allIssues.length, "замечания", "замечаний", "замечаний")}` : plural(allIssues.length, "замечание", "замечания", "замечаний")}
          {selectedCount > 0 && ` · выбрано ${selectedCount}`}
        </span>
      </div>

      {allIssues.length === 0 ? (
        <EmptyState icon={CheckCircle2} title="Замечаний нет" hint="Все проверки пройдены — вариант готов к экспорту." action={<Button icon={Layers} onClick={() => setTab("variants")}>Посмотреть слайды</Button>} />
      ) : groups.length === 0 ? (
        <EmptyState compact icon={Filter} title="Под фильтр ничего не попало" hint="Включите другие уровни важности или снимите «только исправимые»." action={<Button size="sm" onClick={() => setFilter(DEFAULT_FILTER)}>Сбросить фильтр</Button>} />
      ) : (
        <div className="space-y-2.5">
          {groups.map((g) => (
            <SlideIssueGroup
              key={g.slide}
              group={g}
              headline={headlineOf(g.slide)}
              open={openSlides.has(g.slide)}
              current={g.slide > 0 && g.slide === selectedSlide}
              selected={selected}
              disabled={busy}
              onToggle={() =>
                setOpenSlides((cur) => {
                  const next = new Set(cur);
                  if (next.has(g.slide)) next.delete(g.slide);
                  else next.add(g.slide);
                  return next;
                })
              }
              onPick={() => g.slide > 0 && setSelectedSlide(g.slide)}
              onShow={() => {
                setSelectedSlide(g.slide);
                setTab("variants");
              }}
              onSelect={select}
              onSelectGroup={(on) =>
                setSelected((cur) => {
                  const next = new Set(cur);
                  g.issues.filter(isFixable).forEach((i) => (on ? next.add(i.id) : next.delete(i.id)));
                  return next;
                })
              }
            />
          ))}
        </div>
      )}

      <ChecksReference />
    </div>
  );
}
