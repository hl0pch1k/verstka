// «Варианты»: sub-tabs by strategy, filmstrip + large preview with audit overlays, layout explanation,
// slide issues and the run_manifest strip. State (generation, active variant, selected slide) lives in the store.
import { useEffect, useMemo, useState } from "react";
import { FileCog, History, Layers, Upload } from "lucide-react";
import { slideCount } from "../lib/narrate";
import { fmtDate, kindLabel, plural, scoreTone, storage } from "../lib/utils";
import { useApp } from "../store";
import type { Generation, GenerationMeta, Issue } from "../types";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { Tabs, type TabItem } from "./ui/Tabs";
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
  const { generation, generationLoading } = useApp();
  if (!generation) return generationLoading ? <PanelSkeleton /> : <NoGeneration />;
  if (generation.variants.length === 0) return <NoVariants generation={generation} />;
  return <Loaded generation={generation} />;
}

function Loaded({ generation }: { generation: Generation }) {
  const { activeVariant, setActiveStrategy, selectedSlide, setSelectedSlide, strategyTitle, manifest, setTab } = useApp();
  const variant = activeVariant ?? generation.variants[0];
  const total = slideCount(variant);
  const rev = variantRev(variant);
  const issueMap = useMemo(() => issuesBySlide(variant.audit), [variant.audit]);
  const slideIssues = issueMap.get(selectedSlide) ?? NO_ISSUES;

  const [showIssues, setShowIssues] = useState(() => storage.get(KEY_ISSUES) !== "0");
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [naturalAspect, setNaturalAspect] = useState<number | null>(null);
  useEffect(() => setNaturalAspect(null), [generation.id]);

  const templateLoaded = !!manifest && manifest.template_id === generation.template_id;
  const aspect = naturalAspect ?? (templateLoaded && manifest ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9);

  const items = useMemo<TabItem<string>[]>(
    () =>
      generation.variants.map((v) => {
        const score = variantScore(v, generation.summary?.[v.strategy]?.score);
        return { key: v.strategy, label: strategyTitle(v.strategy), badge: score === null ? "—" : Math.round(score), badgeTone: scoreTone(score) };
      }),
    [generation, strategyTitle],
  );

  // ←/→ (and Home/End) walk the deck unless the user is typing or inside a widget that owns arrow keys.
  useEffect(() => {
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
  }, [selectedSlide, total, setSelectedSlide]);

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <Tabs items={items} value={variant.strategy} onChange={setActiveStrategy} variant="pills" />
        <div className="min-w-0 text-right">
          <p className="truncate text-sm font-semibold text-zinc-900">{variant.outline?.title || "Презентация"}</p>
          <p className="truncate text-xs text-zinc-500">
            {plural(total, "слайд", "слайда", "слайдов")} · {fmtDate(generation.created_at)} · {generation.template_file ?? generation.template_id}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-4">
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
      </div>

      <div className="grid grid-cols-2 gap-4">
        <VariantsExplain
          generationId={generation.id}
          strategy={variant.strategy}
          slide={selectedSlide}
          rev={rev}
          entry={entry}
          hasPlan={!!variant.plan}
          pattern={pattern}
          aspect={aspect}
        />
        <VariantsSlideIssues issues={slideIssues} audited={!!variant.audit} highlightId={highlightId} onHighlight={setHighlightId} onOpenAudit={() => setTab("audit")} />
      </div>

      <VariantsRunStrip variant={variant} generation={generation} score={score} strategyTitle={strategyTitle} onOpenRun={() => setTab("run")} />
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
      hint={
        templateId
          ? "Раскройте блок «Новая презентация» над вкладками, опишите тему и нажмите «Сгенерировать» — или попросите ассистента слева. Получатся три варианта макета, каждый пройдёт аудит."
          : "Сначала загрузите шаблон .pptx во вкладке «Шаблон» — из него будут извлечены правила дизайна. Затем опишите тему в блоке «Новая презентация» или в чате слева."
      }
      action={
        <>
          {!templateId && (
            <Button variant="primary" icon={Upload} onClick={() => setTab("template")}>
              Загрузить шаблон
            </Button>
          )}
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
        <Button iconRight={FileCog} onClick={() => setTab("run")}>
          Открыть вкладку «Запуск»
        </Button>
      }
    />
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-4 animate-fade-in" aria-busy aria-label="Загрузка генерации">
      <div className="flex gap-1.5">
        {[0, 1, 2].map((i) => (
          <div key={i} className="skeleton h-8 w-32" />
        ))}
      </div>
      <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-4">
        <div className="space-y-2">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="skeleton aspect-video w-full" />
          ))}
        </div>
        <div className="skeleton aspect-video w-full rounded-xl" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="skeleton h-44 rounded-xl" />
        <div className="skeleton h-44 rounded-xl" />
      </div>
    </div>
  );
}
