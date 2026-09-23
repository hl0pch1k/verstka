// Step 3 «Варианты»: the build while a generation runs; afterwards three variant covers to compare, then the chosen
// deck — filmstrip, the slide on stage with audit overlays, and an inspector («почему так» / замечания). The «План»
// view of the same variant sits behind the segmented switch.
import { useEffect, useMemo, useState } from "react";
import { Download, FileCog, History, Layers, ListTree, PenLine } from "lucide-react";
import { slideCount } from "../lib/narrate";
import { cn, fmtDate, fmtSeconds, kindLabel, plural, storage } from "../lib/utils";
import { useApp } from "../store";
import type { Generation, GenerationMeta, Issue, Variant } from "../types";
import { BuildScreen } from "./BuildScreen";
import { PlanPanel } from "./PlanPanel";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { PageHeader } from "./ui/PageHeader";
import { ScoreRing } from "./ui/ScoreRing";
import { Tabs } from "./ui/Tabs";
import { VariantsExplain, VariantsSlideIssues } from "./VariantsExplain";
import { VariantsFilmstrip } from "./VariantsFilmstrip";
import { issuesBySlide, KEY_ISSUES, planEntryFor, variantRev, variantScore, withRev } from "./VariantsHelpers";
import { VariantsRunStrip } from "./VariantsRunStrip";
import { VariantsSlidePreview } from "./VariantsSlidePreview";

const NO_ISSUES: Issue[] = [];
const isEditable = (el: EventTarget | null) => {
  const t = el as HTMLElement | null;
  if (!t || typeof t.closest !== "function") return false;
  return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable || !!t.closest('[role="tablist"], [role="dialog"]');
};

export function VariantsPanel() {
  const { generation, generationLoading, activeJob } = useApp();
  const building = !!activeJob && activeJob.kind === "generate" && (activeJob.status === "queued" || activeJob.status === "running");
  if (building && activeJob) return <BuildScreen job={activeJob} />;
  if (!generation) return generationLoading ? <PanelSkeleton /> : <NoGeneration />;
  if (generation.variants.length === 0) return <NoVariants generation={generation} />;
  return <Loaded generation={generation} />;
}

function VariantCover({ g, v, active, title, compact, onPick }: { g: Generation; v: Variant; active: boolean; title: string; compact: boolean; onPick(): void }) {
  const [broken, setBroken] = useState(false);
  const score = variantScore(v, g.summary?.[v.strategy]?.score);
  const cover = v.slides[0] ? withRev(v.slides[0], variantRev(v)) : null;
  const n = slideCount(v);
  const errors = v.audit?.summary.errors ?? g.summary?.[v.strategy]?.errors ?? null;
  const seconds = v.run_manifest?.timings_s.total ?? g.summary?.[v.strategy]?.seconds ?? null;
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={active}
      className={cn(
        "group flex cursor-pointer items-center gap-4 rounded-2xl p-3 text-left transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        active ? "bg-white shadow-[0_0_0_2px_#0077FF]" : "bg-white/60 shadow-card hover:bg-white hover:shadow-raise",
      )}
    >
      <span className={cn("block shrink-0 overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line", compact ? "w-[88px]" : "w-[132px]")} style={{ aspectRatio: "16 / 9" }}>
        {cover && !broken && <img src={cover} alt="" loading="lazy" draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate text-[15px] font-semibold", active ? "text-zinc-900" : "text-zinc-800")}>{title}</span>
        <span className="mt-0.5 block truncate text-xs text-zinc-500">
          {plural(n, "слайд", "слайда", "слайдов")}
          {seconds !== null && ` · ${fmtSeconds(seconds)}`}
        </span>
        <span className={cn("mt-1.5 inline-flex h-5 items-center rounded-full px-2 text-[11px] font-bold", errors === null ? "bg-zinc-100 text-zinc-500" : errors === 0 ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700")}>
          {errors === null ? "без аудита" : errors === 0 ? "без ошибок" : plural(errors, "ошибка", "ошибки", "ошибок")}
        </span>
      </span>
      <ScoreRing score={score} size={compact ? 40 : 48} />
    </button>
  );
}

function Loaded({ generation }: { generation: Generation }) {
  const { activeVariant, setActiveStrategy, selectedSlide, setSelectedSlide, strategyTitle, manifest, tab, setTab, agentOpen } = useApp();
  const variant = activeVariant ?? generation.variants[0];
  const total = slideCount(variant);
  const rev = variantRev(variant);
  const issueMap = useMemo(() => issuesBySlide(variant.audit), [variant.audit]);
  const slideIssues = issueMap.get(selectedSlide) ?? NO_ISSUES;
  const planView = tab === "plan";

  const [showIssues, setShowIssues] = useState(() => storage.get(KEY_ISSUES) === "1");
  const [inspector, setInspector] = useState<"why" | "issues">("why");
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [naturalAspect, setNaturalAspect] = useState<number | null>(null);
  useEffect(() => setNaturalAspect(null), [generation.id]);

  const templateLoaded = !!manifest && manifest.template_id === generation.template_id;
  const aspect = naturalAspect ?? (templateLoaded && manifest ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9);

  // ←/→ (and Home/End) walk the deck unless the user is typing or inside a widget that owns arrow keys.
  useEffect(() => {
    if (planView) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || isEditable(e.target)) return;
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      const jump = e.key === "Home" ? 1 : e.key === "End" ? total : 0;
      if (!step && !jump) return;
      e.preventDefault();
      setSelectedSlide(jump || selectedSlide + step);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedSlide, total, setSelectedSlide, planView]);

  const toggleIssues = (v: boolean) => {
    setShowIssues(v);
    storage.set(KEY_ISSUES, v ? "1" : "0");
  };

  const outlineSlide = variant.outline?.slides[selectedSlide - 1] ?? null;
  const entry = planEntryFor(variant, selectedSlide);
  const pattern = templateLoaded && manifest && entry?.pattern_id ? manifest.patterns.find((p) => p.id === entry.pattern_id) ?? null : null;
  const raw = variant.slides[selectedSlide - 1];
  const src = raw ? withRev(raw, rev) : null;
  const score = variantScore(variant, generation.summary?.[variant.strategy]?.score);
  const pptx = variant.files["deck.pptx"] ?? null;
  const n = generation.variants.length;

  return (
    <div className="space-y-6 pb-6">
      <PageHeader
        eyebrow={`Шаг 3 из 5 · ${fmtDate(generation.created_at)}`}
        title={variant.outline?.title || "Презентация"}
        subtitle={`${(generation.template_file ?? generation.template_id).replace(/\.pptx$/i, "")} · ${plural(n, "вариант", "варианта", "вариантов")} из одного брифа — сравните и выберите лучший`}
        actions={
          <>
            <Tabs
              variant="pills"
              value={planView ? "plan" : "variants"}
              onChange={(k) => setTab(k)}
              items={[
                { key: "variants", label: "Слайды", icon: Layers },
                { key: "plan", label: "План", icon: ListTree },
              ]}
            />
            {pptx && (
              <a href={pptx} download="deck.pptx" className="inline-flex h-11 items-center gap-2 rounded-xl bg-accent px-5 text-[15px] font-semibold text-white transition-colors hover:bg-accent-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
                <Download className="h-5 w-5" aria-hidden /> Скачать PPTX
              </a>
            )}
          </>
        }
      />

      <div className={cn("grid gap-4", n >= 3 ? "grid-cols-3" : n === 2 ? "grid-cols-2" : "grid-cols-1")}>
        {generation.variants.map((v) => (
          <VariantCover key={v.strategy} g={generation} v={v} active={v.strategy === variant.strategy} title={strategyTitle(v.strategy)} compact={agentOpen} onPick={() => setActiveStrategy(v.strategy)} />
        ))}
      </div>

      {planView ? (
        <PlanPanel embedded />
      ) : (
        <>
          {/* with the agent dock open the inspector moves under the slide: the stage keeps its size */}
          <div className={cn("grid gap-5", agentOpen ? "grid-cols-[96px_minmax(0,1fr)]" : "grid-cols-[112px_minmax(0,1fr)_360px]")}>
            <div className="relative min-h-[240px]">
              <div className="scroll-thin absolute inset-0 overflow-y-auto pr-1">
                <VariantsFilmstrip variant={variant} rev={rev} total={total} selected={selectedSlide} aspect={aspect} issueMap={issueMap} onSelect={setSelectedSlide} />
              </div>
            </div>
            <VariantsSlidePreview
              src={src}
              slide={selectedSlide}
              total={total}
              headline={outlineSlide?.headline ?? ""}
              kind={outlineSlide ? kindLabel(outlineSlide.kind) : null}
              issues={slideIssues}
              aspect={aspect}
              showIssues={showIssues}
              onToggleIssues={toggleIssues}
              highlightId={highlightId}
              onHighlight={setHighlightId}
              onSelect={setSelectedSlide}
              onAspect={setNaturalAspect}
            />
            <aside className={cn("flex min-h-0 min-w-0 flex-col gap-3", agentOpen && "col-span-2")}>
              <Tabs
                variant="pills"
                className="self-start"
                value={inspector}
                onChange={setInspector}
                items={[
                  { key: "why", label: "Почему так" },
                  { key: "issues", label: "Замечания", badge: slideIssues.length || null, badgeTone: slideIssues.some((i) => i.severity === "error") ? "error" : "warn" },
                ]}
              />
              {inspector === "why" ? (
                <VariantsExplain generationId={generation.id} strategy={variant.strategy} slide={selectedSlide} rev={rev} entry={entry} hasPlan={!!variant.plan} pattern={pattern} aspect={aspect} />
              ) : (
                <VariantsSlideIssues issues={slideIssues} audited={!!variant.audit} highlightId={highlightId} onHighlight={setHighlightId} onOpenAudit={() => setTab("audit")} />
              )}
            </aside>
          </div>
          <VariantsRunStrip variant={variant} generation={generation} score={score} strategyTitle={strategyTitle} onOpenRun={() => setTab("run")} />
        </>
      )}
    </div>
  );
}

function NoGeneration() {
  const { generations, loadGeneration, templateId, setTab } = useApp();
  // Newest finished generation; ids are time-sortable (YYYYMMDD-HHMMSS-…) so they break ties when created_at is missing.
  const newest = generations
    .filter((g) => g.status !== "running" && g.status !== "failed")
    .reduce<GenerationMeta | null>((best, g) => (!best || (g.created_at ?? 0) > (best.created_at ?? 0) || ((g.created_at ?? 0) === (best.created_at ?? 0) && g.id > best.id) ? g : best), null);
  return (
    <EmptyState
      icon={Layers}
      title="Пока нет вариантов вёрстки"
      hint={templateId ? "Напишите бриф — из него получатся три варианта колоды, каждый пройдёт аудит." : "Сначала загрузите шаблон .pptx — из него будут извлечены правила дизайна."}
      action={
        <>
          <Button variant="primary" icon={PenLine} onClick={() => setTab(templateId ? "brief" : "template")}>
            {templateId ? "Написать бриф" : "Загрузить шаблон"}
          </Button>
          {newest && (
            <Button icon={History} onClick={() => void loadGeneration(newest.id)}>
              Открыть последнюю генерацию
            </Button>
          )}
        </>
      }
    />
  );
}

function NoVariants({ generation }: { generation: Generation }) {
  const { setTab } = useApp();
  return (
    <EmptyState
      icon={FileCog}
      title="Варианты не собрались"
      hint={`Генерация ${generation.id} завершилась без готовых вариантов. Подробности — в журнале запуска; можно запустить генерацию заново.`}
      action={
        <>
          <Button variant="primary" icon={PenLine} onClick={() => setTab("brief")}>К брифу</Button>
          <Button iconRight={FileCog} onClick={() => setTab("run")}>Журнал запуска</Button>
        </>
      }
    />
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-6 animate-fade-in" aria-busy aria-label="Загрузка генерации">
      <div className="skeleton h-16 w-1/2" />
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => <div key={i} className="skeleton h-[104px] rounded-2xl" />)}
      </div>
      <div className="grid grid-cols-[112px_minmax(0,1fr)_360px] gap-5">
        <div className="space-y-2">{Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton aspect-video w-full" />)}</div>
        <div className="skeleton aspect-video w-full rounded-2xl" />
        <div className="skeleton h-80 rounded-2xl" />
      </div>
    </div>
  );
}

