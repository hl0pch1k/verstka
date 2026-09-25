// The second screen: the deck. Three variants to switch, the slide big with thumbnails under it, one «Скачать»
// button. What an expert wants (quality check, why a slide looks so, plan, template, files) opens in the drawer.
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ChevronRight, Download, FileText, HelpCircle, Info, LayoutTemplate, ListTree, PenLine, RotateCcw, ShieldCheck, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { deckNotice } from "../../lib/modelText";
import { slideCount } from "../../lib/narrate";
import { templateName, variantHint } from "../../lib/plain";
import { cn, fmtWhen, kindLabel, plural, storage } from "../../lib/utils";
import { useApp } from "../../store";
import type { DetailKey, Generation, Issue } from "../../types";
import { BuildScreen } from "../BuildScreen";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { ScoreRing } from "../ui/ScoreRing";
import { issuesBySlide, KEY_ISSUES, variantRev, variantScore, withRev } from "../VariantsHelpers";
import { VariantsSlidePreview } from "../VariantsSlidePreview";
import { AgentCard } from "./AgentPanel";
import { useRetryIn } from "./ModelStatus";
import { SlideLightbox } from "./SlideLightbox";
import { SlideStrip } from "./SlideStrip";

const NO_ISSUES: Issue[] = [];
const isEditable = (el: EventTarget | null) => {
  const t = el as HTMLElement | null;
  if (!t || typeof t.closest !== "function") return false;
  return t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable || !!t.closest('[role="tablist"], [role="dialog"]');
};

function MoreLink({ icon: Icon, label, hint, onClick }: { icon: LucideIcon; label: string; hint: string; onClick(): void }) {
  return (
    <button type="button" onClick={onClick} className="group flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-1.5 text-left transition-colors hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600 transition-colors group-hover:bg-white">
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold text-zinc-900">{label}</span>
        <span className="block truncate text-xs text-zinc-500">{hint}</span>
      </span>
      <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400 transition-transform group-hover:translate-x-0.5" aria-hidden />
    </button>
  );
}

function Deck({ generation }: { generation: Generation }) {
  const { activeVariant, setActiveStrategy, selectedSlide, setSelectedSlide, strategyTitle, strategies, manifest, setScreen, setDetail, health, modelStatus, refreshModelStatus, startGeneration, activeJob, generations } = useApp();
  const variant = activeVariant ?? generation.variants[0];
  const total = slideCount(variant);
  const rev = variantRev(variant);
  const issueMap = useMemo(() => issuesBySlide(variant.audit), [variant.audit]);
  const slideIssues = issueMap.get(selectedSlide) ?? NO_ISSUES;
  const [showIssues, setShowIssues] = useState(() => storage.get(KEY_ISSUES) === "1");
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [naturalAspect, setNaturalAspect] = useState<number | null>(null);
  const [zoom, setZoom] = useState(false);
  useEffect(() => setNaturalAspect(null), [generation.id]);
  const templateLoaded = !!manifest && manifest.template_id === generation.template_id;
  const aspect = naturalAspect ?? (templateLoaded && manifest ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9);

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

  // warm the cache with the neighbours: ← and → show the next slide at once
  useEffect(() => {
    for (const n of [selectedSlide + 1, selectedSlide - 1]) {
      const url = variant.slides[n - 1];
      if (url) new Image().src = withRev(url, rev);
    }
  }, [selectedSlide, variant, rev]);

  const outlineSlide = variant.outline?.slides[selectedSlide - 1] ?? null;
  // why the designer chose this form (Agent v2): one line under the headline, the whole story in «Почему слайд такой»
  const why = variant.design?.find((d) => d.index === selectedSlide)?.rationale ?? outlineSlide?.rationale ?? null;
  const raw = variant.slides[selectedSlide - 1];
  const src = raw ? withRev(raw, rev) : null;
  const score = variantScore(variant, generation.summary?.[variant.strategy]?.score);
  const errors = variant.audit?.summary.errors ?? generation.summary?.[variant.strategy]?.errors ?? null;
  const warnings = variant.audit?.summary.warnings ?? 0;
  const pptx = variant.files["deck.pptx"] ?? null;
  const pdf = variant.files["deck.pdf"] ?? null;
  const quality =
    errors === null ? "Проверка не запускалась" : errors === 0 ? (warnings ? `Ошибок нет, ${plural(warnings, "мелкое замечание", "мелких замечания", "мелких замечаний")}` : "Ошибок нет") : `${plural(errors, "ошибка", "ошибки", "ошибок")} — можно исправить автоматически`;
  const open = (d: DetailKey) => setDetail(d);
  // the newest deck built with the model: the live model state is about the same failure
  const latest = useMemo(() => {
    if (!generations.some((x) => x.id === generation.id)) return false;
    const t = generation.created_at ?? 0;
    return !generations.some((x) => x.id !== generation.id && x.use_models && x.status === "done" && (x.created_at ?? 0) > t);
  }, [generations, generation.id, generation.created_at]);
  // every model was marked paused a moment ago: a new build before the pause is over would get the same answer
  const retryIn = useRetryIn(modelStatus);
  // why the deck is thin, when it is: the model did not plan it (and why), a topic without theses, or a short text.
  // The rebuild button and the advice beside it follow the live model state, so they never disagree
  const notice = deckNotice(generation, variant, total, { status: modelStatus, latest, retryIn });
  const failed = !!generation.use_models && generation.planner?.by_model === false;
  useEffect(() => {
    if (failed) void refreshModelStatus();
  }, [failed, generation.id, refreshModelStatus]);
  const recheckIn = modelStatus?.state === "down" && modelStatus.retry_in ? Math.min(modelStatus.retry_in + 2, 600) : 0;
  useEffect(() => {
    if (!failed || !recheckIn) return;
    const t = window.setTimeout(() => void refreshModelStatus(), recheckIn * 1000);
    return () => window.clearTimeout(t);
  }, [failed, recheckIn, refreshModelStatus]);
  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  // one rebuild at a time: a double click must not start two generations (each spends model requests)
  const inFlight = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const rebuild = async () => {
    if (inFlight.current) return;
    if (!generation.brief || !health?.models_configured) return setScreen("create");
    inFlight.current = true;
    setSubmitting(true);
    try {
      // the same inputs as the deck on screen, only the model gets another chance
      await startGeneration({
        template_id: generation.template_id,
        brief: generation.brief,
        audience: generation.audience ?? null,
        purpose: generation.purpose ?? null,
        slides: generation.slides ?? null,
        language: generation.language,
        extra_instructions: generation.extra_instructions ?? null,
        strategies: generation.strategies,
        use_models: true,
        audit_models: generation.audit_models ?? false,
        autofix: generation.autofix ?? true,
        exports: generation.exports ?? ["pdf", "html"],
      });
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1280px] space-y-5 pb-10">
      <div className="flex items-end gap-6">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[28px] font-bold leading-9 tracking-tight text-zinc-900" title={variant.outline?.title || undefined}>{variant.outline?.title || "Презентация"}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 text-[15px] text-zinc-500">
            <span>Шаблон «{templateName(generation.template_file, generation.template_id)}» · {fmtWhen(generation.created_at)}</span>
            <button type="button" onClick={() => setScreen("create")} className="inline-flex cursor-pointer items-center gap-1 font-semibold text-accent-700 hover:underline">
              <ArrowLeft className="h-4 w-4" aria-hidden /> Изменить текст или шаблон
            </button>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {pdf && (
            <a href={pdf} download="deck.pdf" className="inline-flex h-12 items-center gap-2 rounded-xl bg-zinc-100 px-4 text-[15px] font-semibold text-zinc-900 transition-colors hover:bg-zinc-200/80 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30">
              <FileText className="h-5 w-5" aria-hidden /> PDF
            </a>
          )}
          {pptx && (
            <a href={pptx} download="deck.pptx" className="inline-flex h-12 items-center gap-2 rounded-xl bg-accent px-6 text-[15px] font-semibold text-white transition-[background-color,transform] hover:-translate-y-px hover:bg-accent-600 active:translate-y-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40">
              <Download className="h-5 w-5" aria-hidden /> Скачать PowerPoint
            </a>
          )}
        </div>
      </div>

      {notice && (
        <div role="status" className="flex items-start gap-3 rounded-2xl bg-amber-50 py-3 pl-4 pr-3 text-amber-950 animate-fade">
          <Info className="mt-px h-[18px] w-[18px] shrink-0 text-amber-600" aria-hidden />
          <div className="min-w-0 flex-1 text-[13px] leading-5">
            <p className="text-[14px] font-semibold">{notice.title}</p>
            <p className="text-amber-950/85">{notice.basis}</p>
            {notice.help && (
              <p className="text-amber-900/75">
                <span className="font-semibold text-amber-950/85">Что поможет:</span> {notice.help}
              </p>
            )}
          </div>
          <div className="flex shrink-0 flex-col items-stretch gap-1.5 self-center">
            {notice.retry && (
              <Button size="sm" variant="secondary" icon={RotateCcw} loading={submitting} disabled={jobRunning || notice.retryWait > 0} className="bg-white shadow-card hover:bg-zinc-50" onClick={() => void rebuild()} title={notice.retryWait > 0 ? "Модель только что не ответила — повторная попытка имеет смысл чуть позже" : "Собрать ту же презентацию заново"}>
                {notice.retryLabel}
              </Button>
            )}
            {notice.rewrite && (
              <Button size="sm" variant="secondary" icon={PenLine} className="bg-white shadow-card hover:bg-zinc-50" onClick={() => setScreen("create")}>Дописать текст</Button>
            )}
          </div>
        </div>
      )}

      {generation.variants.length > 1 && (
        <div role="radiogroup" aria-label="Вариант оформления" className={cn("grid gap-3", generation.variants.length >= 3 ? "grid-cols-3" : "grid-cols-2")}>
          {generation.variants.map((v, i) => {
            const active = v.strategy === variant.strategy;
            const s = variantScore(v, generation.summary?.[v.strategy]?.score);
            return (
              <button
                key={v.strategy}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setActiveStrategy(v.strategy)}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-2xl px-4 py-3 text-left transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
                  active ? "bg-white shadow-[0_0_0_2px_#0077FF]" : "bg-white/60 shadow-card hover:bg-white",
                )}
              >
                <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[15px] font-bold", active ? "bg-accent text-white" : "bg-zinc-100 text-zinc-600")}>{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[15px] font-semibold text-zinc-900">
                    Вариант {i + 1} · {strategyTitle(v.strategy)}
                  </span>
                  <span className="block truncate text-xs text-zinc-500">{variantHint(v.strategy, strategies.find((x) => x.name === v.strategy)?.description)}</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block text-xs text-zinc-500">{plural(slideCount(v), "слайд", "слайда", "слайдов")}</span>
                  {s !== null && <span className={cn("block text-[13px] font-bold tabular-nums", s >= 90 ? "text-emerald-600" : s >= 70 ? "text-amber-600" : "text-red-600")}>{Math.round(s)}/100</span>}
                </span>
              </button>
            );
          })}
        </div>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-6">
        <div className="min-w-0 space-y-2">
          <VariantsSlidePreview
            src={src}
            slide={selectedSlide}
            total={total}
            headline={outlineSlide?.headline ?? ""}
            kind={outlineSlide ? kindLabel(outlineSlide.kind) : null}
            issues={slideIssues}
            aspect={aspect}
            showIssues={showIssues}
            onToggleIssues={(v) => {
              setShowIssues(v);
              storage.set(KEY_ISSUES, v ? "1" : "0");
            }}
            highlightId={highlightId}
            onHighlight={setHighlightId}
            onSelect={setSelectedSlide}
            onAspect={setNaturalAspect}
            onZoom={() => setZoom(true)}
            onOpenIssues={() => open("quality")}
            why={why}
            onWhy={() => open("why")}
            reserve={notice ? (notice.help ? 104 : 84) : 0}
          />
          <SlideStrip variant={variant} rev={rev} total={total} selected={selectedSlide} aspect={aspect} issueMap={issueMap} onSelect={setSelectedSlide} />
          <SlideLightbox open={zoom} src={src} slide={selectedSlide} total={total} headline={outlineSlide?.headline ?? ""} aspect={aspect} onSelect={setSelectedSlide} onClose={() => setZoom(false)} />
        </div>

        <aside className="space-y-4">
          <section className="rounded-2xl bg-white p-4 shadow-card">
            <div className="flex items-center gap-4">
              <ScoreRing score={score} size={56} stroke={5} />
              <div className="min-w-0">
                <p className="text-[15px] font-semibold text-zinc-900">Проверка качества</p>
                <p className="text-[13px] leading-5 text-zinc-500">{quality}</p>
                <button type="button" onClick={() => open("quality")} className="mt-0.5 inline-flex cursor-pointer items-center gap-1 text-[13px] font-semibold text-accent-700 hover:underline focus:outline-none focus-visible:underline">
                  <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> {errors ? "Посмотреть и исправить" : "Что проверено"}
                </button>
              </div>
            </div>
          </section>

          <AgentCard variant={variant} onOpen={() => open("agent")} />

          <section className="rounded-2xl bg-white p-2 shadow-card">
            <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Подробнее</p>
            <MoreLink icon={HelpCircle} label="Почему слайд такой" hint={why ? `Слайд ${selectedSlide}: замысел и макет` : `Слайд ${selectedSlide}: макет и причины`} onClick={() => open("why")} />
            <MoreLink icon={ListTree} label="План презентации" hint="Структура и цифры из текста" onClick={() => open("plan")} />
            <MoreLink icon={LayoutTemplate} label="Что понято из шаблона" hint="Цвета, шрифты, макеты" onClick={() => open("template")} />
            <MoreLink icon={Wrench} label="Файлы и детали" hint="PPTX, PDF, HTML, JSON" onClick={() => open("tech")} />
          </section>
        </aside>
      </div>
    </div>
  );
}

export function ResultScreen() {
  const { generation, generationLoading, activeJob, setScreen } = useApp();
  const building = !!activeJob && activeJob.kind === "generate" && (activeJob.status === "queued" || activeJob.status === "running");
  if (building && activeJob) return <div className="mx-auto max-w-[1100px] pt-6"><BuildScreen job={activeJob} /></div>;
  if (!generation) {
    if (generationLoading) {
      return (
        <div className="mx-auto max-w-[1320px] space-y-6" aria-busy aria-label="Загрузка презентации">
          <div className="skeleton h-20 w-2/3" />
          <div className="grid grid-cols-3 gap-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-16 rounded-2xl" />)}</div>
          <div className="grid grid-cols-[minmax(0,1fr)_300px] gap-6"><div className="skeleton aspect-video rounded-2xl" /><div className="skeleton h-72 rounded-2xl" /></div>
        </div>
      );
    }
    return (
      <EmptyState
        icon={FileText}
        title="Здесь появится презентация"
        hint="Выберите шаблон и напишите, о чём рассказать, — Verstka соберёт три варианта."
        action={<Button variant="primary" onClick={() => setScreen("create")}>Создать презентацию</Button>}
      />
    );
  }
  if (generation.variants.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title="Не получилось собрать презентацию"
        hint="Попробуйте ещё раз или измените текст. Причина записана в технических деталях."
        action={<Button variant="primary" onClick={() => setScreen("create")}>Вернуться к тексту</Button>}
      />
    );
  }
  return <Deck generation={generation} />;
}
