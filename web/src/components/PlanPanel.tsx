// «План» (details drawer): the deck as a document — every slide with its thumbnail, headline and content, how it was
// laid out in one phrase, then the figures taken from the text and the data behind the charts.
import { useMemo, useState, type KeyboardEvent } from "react";
import { ListTree } from "lucide-react";
import { variantHint } from "../lib/plain";
import { cn, kindLabel, plural } from "../lib/utils";
import { useApp } from "../store";
import type { DeckOutline, LayoutSlide, OutlineSlide, Pattern } from "../types";
import { FactsRegistry, SeriesRegistry } from "./PlanPanelData";
import { SlideContentView } from "./PlanPanelSlide";
import { EmptyState } from "./ui/EmptyState";
import { variantRev, withRev } from "./VariantsHelpers";

function Thumb({ src, aspect, n }: { src: string | null; aspect: string; n: number }) {
  const [broken, setBroken] = useState(false);
  return (
    <div className="relative w-44 shrink-0 self-start overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line" style={{ aspectRatio: aspect }}>
      {src && !broken && <img src={src} alt="" loading="lazy" draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover" />}
      <span className="absolute bottom-1.5 left-1.5 rounded-md bg-ink/70 px-1.5 text-[11px] font-semibold tabular-nums text-white backdrop-blur-sm">{n}</span>
    </div>
  );
}

function SlideRow({ index, slide, outline, decision, pattern, thumb, aspect, selected, onOpen }: {
  index: number; slide: OutlineSlide; outline: DeckOutline; decision: LayoutSlide | undefined; pattern: Pattern | null; thumb: string | null; aspect: string; selected: boolean; onOpen(): void;
}) {
  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    }
  };
  const how = !decision ? null : decision.mode === "clone" && pattern ? `по образцу слайда ${pattern.source_slide} шаблона` : decision.mode === "clone" ? "по образцу из шаблона" : "собран из стиля шаблона";
  return (
    <article
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKey}
      title="Открыть этот слайд"
      className={cn(
        "group flex cursor-pointer gap-5 rounded-2xl bg-white p-4 transition-shadow duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        selected ? "shadow-[0_0_0_2px_#0077FF]" : "shadow-card hover:shadow-raise",
      )}
    >
      <Thumb src={thumb} aspect={aspect} n={index} />
      <div className="min-w-0 flex-1 space-y-2">
        <p className="text-xs font-medium text-zinc-500">
          {kindLabel(slide.kind)}
          {slide.section && ` · ${slide.section}`}
          {how && <span className="text-zinc-400"> · {how}</span>}
        </p>
        <h4 className="text-[15px] font-semibold leading-5 text-zinc-900">{slide.headline || <span className="font-normal italic text-zinc-400">без заголовка</span>}</h4>
        {slide.subtitle && <p className="text-[13px] leading-5 text-zinc-600">{slide.subtitle}</p>}
        <SlideContentView content={slide.content} outline={outline} />
      </div>
    </article>
  );
}

export function PlanPanel() {
  const { generation, generationLoading, activeVariant, strategyTitle, manifest, selectedSlide, setSelectedSlide, setDetail } = useApp();
  const outline = activeVariant?.outline ?? null;
  const plan = activeVariant?.plan ?? null;

  const patternById = useMemo(() => {
    const map = new Map<string, Pattern>();
    if (manifest && generation && manifest.template_id === generation.template_id) manifest.patterns.forEach((p) => map.set(p.id, p));
    return map;
  }, [manifest, generation]);
  const decisionById = useMemo(() => new Map((plan?.slides ?? []).map((s) => [s.outline_id, s])), [plan]);
  const usedFacts = useMemo(() => new Set((outline?.slides ?? []).flatMap((s) => s.fact_refs)), [outline]);

  if (generationLoading) return <div className="space-y-4" aria-busy>{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-32 w-full rounded-2xl" />)}</div>;
  if (!generation || !activeVariant) return <EmptyState icon={ListTree} title="Плана пока нет" hint="План появится вместе с первой презентацией." />;
  if (!outline) return <EmptyState icon={ListTree} title="У этого варианта нет плана" hint="Планировщик не сохранил структуру — попробуйте собрать презентацию заново." />;

  const aspect = manifest?.slide_size.w && manifest.slide_size.h ? `${manifest.slide_size.w} / ${manifest.slide_size.h}` : "16 / 9";
  const rev = variantRev(activeVariant);
  const variantIndex = generation.variants.findIndex((v) => v.strategy === activeVariant.strategy) + 1;
  const open = (n: number) => {
    setSelectedSlide(n);
    setDetail(null);
  };

  return (
    <div className="space-y-4">
      <section className="rounded-3xl bg-white p-6 shadow-card">
        <h2 className="text-2xl font-bold leading-8 tracking-tight text-zinc-900">{outline.title}</h2>
        {outline.subtitle && <p className="mt-1 text-[15px] leading-6 text-zinc-600">{outline.subtitle}</p>}
        <p className="mt-3 text-[13px] text-zinc-500">
          {[
            `Вариант ${variantIndex} · ${strategyTitle(activeVariant.strategy)} — ${variantHint(activeVariant.strategy).replace(/^[^:]+:\s*/, "")}`,
            plural(outline.slides.length, "слайд", "слайда", "слайдов"),
            outline.facts.length ? plural(outline.facts.length, "цифра из текста", "цифры из текста", "цифр из текста") : null,
            outline.audience ? `для: ${outline.audience}` : null,
          ].filter(Boolean).join(" · ")}
        </p>
      </section>

      {outline.slides.length === 0 ? (
        <EmptyState compact icon={ListTree} title="В плане нет слайдов" hint="Планировщик вернул пустую структуру." />
      ) : (
        <ol className="space-y-3" aria-label="Слайды плана">
          {outline.slides.map((s, i) => {
            const d = decisionById.get(s.id);
            const url = activeVariant.slides[i] ? withRev(activeVariant.slides[i], rev) : null;
            return (
              <li key={s.id}>
                <SlideRow
                  index={i + 1}
                  slide={s}
                  outline={outline}
                  decision={d}
                  pattern={d?.pattern_id ? patternById.get(d.pattern_id) ?? null : null}
                  thumb={url}
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
    </div>
  );
}
