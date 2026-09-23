// «План» tab: the deck outline of the active variant as a document, with the matcher's layout decision per slide.
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import { useMemo, type KeyboardEvent } from "react";
import { Layers, ListTree, StickyNote } from "lucide-react";
import { cn, fmtDate, kindLabel, plural, shortSha } from "../lib/utils";
import { useApp } from "../store";
import type { DeckOutline, LayoutSlide, OutlineSlide, Pattern } from "../types";
import { FactsRegistry, SeriesRegistry } from "./PlanPanelData";
import { LayoutDecision, SlideContentView } from "./PlanPanelSlide";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card, CardBody } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { Tabs } from "./ui/Tabs";

const PURPOSE_RU: Record<string, string> = { feature: "фича", product: "продукт", project: "проект", initiative: "инициатива", report: "отчёт", other: "другое" };
const LANG_RU: Record<string, string> = { ru: "русский", en: "английский" };

function NoGeneration() {
  const { generations, loadGeneration } = useApp();
  const recent = [...generations].sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)).slice(0, 3);
  return (
    <EmptyState
      icon={ListTree}
      title="Плана пока нет"
      hint="Опишите презентацию в форме «Новая презентация» или пришлите бриф в чат — планировщик соберёт структуру слайдов, реестр фактов и подберёт паттерн шаблона для каждого слайда."
      action={
        recent.length > 0 && (
          <div className="flex flex-wrap items-center justify-center gap-1.5">
            <span className="text-xs text-zinc-500">или откройте недавнюю:</span>
            {recent.map((g) => (
              <button key={g.id} type="button" onClick={() => void loadGeneration(g.id)} className="cursor-pointer rounded-full bg-zinc-100 px-3 py-1.5 text-xs font-semibold text-zinc-700 hover:bg-zinc-200/70 hover:bg-zinc-50">
                {g.brief?.trim().slice(0, 40) || shortSha(g.id)}{g.brief && g.brief.trim().length > 40 ? "…" : ""} · {fmtDate(g.created_at)}
              </button>
            ))}
          </div>
        )
      }
    />
  );
}

function Skeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Загрузка плана">
      <div className="skeleton h-8 w-80" />
      <div className="skeleton h-32 w-full" />
      {Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-28 w-full" />)}
    </div>
  );
}

interface RowProps {
  index: number; slide: OutlineSlide; outline: DeckOutline; decision: LayoutSlide | undefined; pattern: Pattern | null; aspect: string; selected: boolean; onOpen(): void;
}

function SlideRow({ index, slide, outline, decision, pattern, aspect, selected, onOpen }: RowProps) {
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    }
  };
  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKey}
      title="Открыть слайд во вкладке «Варианты»"
      className={cn(
        "flex cursor-pointer gap-5 rounded-2xl bg-white px-5 py-4 transition-shadow duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30",
        selected ? "shadow-[0_0_0_2px_#0077FF]" : "shadow-card hover:shadow-raise",
      )}
    >
      <span className={cn("w-8 shrink-0 pt-0.5 text-right text-2xl font-bold leading-7 tabular-nums", selected ? "text-accent" : "text-zinc-300")}>{index}</span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge size="sm" tone="accent">{kindLabel(slide.kind)}</Badge>
          {slide.section && <span className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">{slide.section}</span>}
          {slide.fact_refs.length > 0 && (
            <span className="ml-auto font-mono text-[11px] text-zinc-400" title="Факты из реестра, использованные на слайде">факты: {slide.fact_refs.join(", ")}</span>
          )}
        </div>
        <h4 className="text-base font-semibold leading-6 text-zinc-900">{slide.headline || <span className="font-normal italic text-zinc-400">без заголовка</span>}</h4>
        {slide.subtitle && <p className="text-[13px] leading-5 text-zinc-600">{slide.subtitle}</p>}
        <SlideContentView content={slide.content} outline={outline} />
        {slide.notes && (
          <p className="flex items-start gap-1.5 text-xs italic leading-[18px] text-zinc-500">
            <StickyNote className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
            <span className="line-clamp-2">{slide.notes}</span>
          </p>
        )}
      </div>
      <LayoutDecision decision={decision} pattern={pattern} aspect={aspect} />
    </article>
  );
}

export function PlanPanel({ embedded = false }: { embedded?: boolean } = {}) {
  const { generation, generationLoading, activeVariant, activeStrategy, setActiveStrategy, strategies, strategyTitle, manifest, selectedSlide, setSelectedSlide, setTab } = useApp();
  const outline = activeVariant?.outline ?? null;
  const plan = activeVariant?.plan ?? null;

  const patternById = useMemo(() => {
    const map = new Map<string, Pattern>();
    if (manifest && generation && manifest.template_id === generation.template_id) manifest.patterns.forEach((p) => map.set(p.id, p));
    return map;
  }, [manifest, generation]);
  const decisionById = useMemo(() => new Map((plan?.slides ?? []).map((s) => [s.outline_id, s])), [plan]);
  const usedFacts = useMemo(() => new Set((outline?.slides ?? []).flatMap((s) => s.fact_refs)), [outline]);

  if (generationLoading) return <Skeleton />;
  if (!generation) return <NoGeneration />;
  if (generation.variants.length === 0) {
    return <EmptyState icon={ListTree} title="Варианты ещё не собраны" hint={generation.status === "running" ? "Генерация идёт — план появится, как только планировщик закончит." : "Генерация не дала ни одного варианта. Подробности — во вкладке «Запуск»."} />;
  }

  const aspect = manifest?.slide_size.w && manifest.slide_size.h ? `${manifest.slide_size.w} / ${manifest.slide_size.h}` : "16 / 9";
  const strategy = strategies.find((s) => s.name === (outline?.strategy ?? activeStrategy));
  const clones = plan ? plan.slides.filter((s) => s.mode === "clone").length : 0;
  const synths = plan ? plan.slides.length - clones : 0;
  const open = (n: number) => {
    setSelectedSlide(n);
    setTab("variants");
  };

  return (
    <div className="space-y-4 pb-6">
      <div className="flex items-center gap-3">
        {!embedded && (
          <Tabs
            variant="pills"
            value={activeStrategy ?? generation.variants[0].strategy}
            onChange={setActiveStrategy}
            items={generation.variants.map((v) => ({ key: v.strategy, label: strategyTitle(v.strategy), badge: v.outline?.slides.length ?? null }))}
          />
        )}
        {plan && (
          <span className="text-[13px] text-zinc-500">
            {plural(plan.slides.length, "слайд", "слайда", "слайдов")} · клон паттерна {clones} · синтез из токенов {synths}
          </span>
        )}
        {!embedded && <Button size="sm" icon={Layers} className="ml-auto" onClick={() => open(selectedSlide)}>Открыть слайды</Button>}
      </div>

      {!outline ? (
        <EmptyState icon={ListTree} title="У этого варианта нет плана" hint="Планировщик не сохранил структуру для выбранной стратегии — переключите вариант или запустите генерацию заново." />
      ) : (
        <>
          <Card>
            <CardBody className="space-y-3 py-5">
              <div>
                <h2 className="text-2xl font-bold leading-8 tracking-tight text-zinc-900">{outline.title}</h2>
                {outline.subtitle && <p className="mt-1 text-sm leading-5 text-zinc-600">{outline.subtitle}</p>}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {outline.audience && <Badge title="Аудитория">для: {outline.audience}</Badge>}
                {outline.purpose && <Badge title="Тип презентации">{PURPOSE_RU[outline.purpose] ?? outline.purpose}</Badge>}
                <Badge title="Язык">{LANG_RU[outline.language] ?? outline.language}</Badge>
                <Badge>{plural(outline.slides.length, "слайд", "слайда", "слайдов")}</Badge>
                <Badge>{plural(outline.facts.length, "факт", "факта", "фактов")}</Badge>
              </div>
              {strategy && (
                <p className="border-t border-zinc-100 pt-3 text-[13px] leading-5 text-zinc-700">
                  <span className="font-semibold text-zinc-900">Стратегия «{strategy.title}».</span> {strategy.description}
                </p>
              )}
            </CardBody>
          </Card>

          {outline.slides.length === 0 ? (
            <EmptyState compact icon={ListTree} title="В плане нет слайдов" hint="Планировщик вернул пустую структуру." />
          ) : (
            <ol className="space-y-2.5" aria-label="Слайды плана">
              {outline.slides.map((s, i) => {
                const d = decisionById.get(s.id);
                return (
                  <li key={s.id}>
                    <SlideRow
                      index={i + 1}
                      slide={s}
                      outline={outline}
                      decision={d}
                      pattern={d?.pattern_id ? patternById.get(d.pattern_id) ?? null : null}
                      aspect={aspect}
                      selected={selectedSlide === i + 1}
                      onOpen={() => open(i + 1)}
                    />
                  </li>
                );
              })}
            </ol>
          )}

          <FactsRegistry facts={outline.facts} used={usedFacts} />
          <SeriesRegistry series={outline.series} />
        </>
      )}
    </div>
  );
}
