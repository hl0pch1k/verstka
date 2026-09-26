// «План» (details drawer): the deck as a document — every slide with its thumbnail, headline and content — then the
// figures taken from the text and the data behind the charts. The variant follows the drawer's menu.
import { useMemo, useState, type KeyboardEvent } from "react";
import { ImageOff, ListTree } from "lucide-react";
import { figuresLine } from "../lib/narrate";
import { cn, kindLabel, plural } from "../lib/utils";
import { useApp } from "../store";
import type { DeckOutline, OutlineSlide } from "../types";
import { FactsRegistry, SeriesRegistry } from "./PlanPanelData";
import { SlideContentView } from "./PlanPanelSlide";
import { EmptyState } from "./ui/EmptyState";
import { variantRev, withRev } from "./VariantsHelpers";

function Thumb({ src, aspect, n }: { src: string | null; aspect: string; n: number }) {
  const [broken, setBroken] = useState(false);
  return (
    <div className="relative w-40 shrink-0 self-start overflow-hidden rounded-lg bg-zinc-100 ring-1 ring-zinc-900/[0.08]" style={{ aspectRatio: aspect }}>
      {src && !broken ? (
        <img src={src} alt="" loading="lazy" draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full items-center justify-center text-zinc-400" aria-hidden>
          <ImageOff className="h-5 w-5" />
        </div>
      )}
      <span className="absolute bottom-1 left-1 rounded bg-zinc-900/60 px-1 text-caption font-semibold leading-4 tabular-nums text-white">{n}</span>
    </div>
  );
}

function SlideRow({ index, slide, outline, thumb, aspect, selected, onOpen }: {
  index: number; slide: OutlineSlide; outline: DeckOutline; thumb: string | null; aspect: string; selected: boolean; onOpen(): void;
}) {
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
      aria-label={`Слайд ${index}: ${slide.headline || "без заголовка"}`}
      className={cn("flex cursor-pointer gap-4 rounded-xl p-4 transition-[background-color,box-shadow] duration-150", selected ? "shadow-selected" : "hover:bg-zinc-50")}
    >
      <Thumb src={thumb} aspect={aspect} n={index} />
      <div className="min-w-0 flex-1">
        <p className="text-caption text-zinc-500">{kindLabel(slide.kind)}</p>
        <h4 className="mt-0.5 text-body font-semibold text-zinc-900">{slide.headline || <span className="font-normal text-zinc-500">Без заголовка</span>}</h4>
        {slide.subtitle && <p className="mt-0.5 text-footnote text-zinc-700">{slide.subtitle}</p>}
        <div className="mt-2">
          <SlideContentView content={slide.content} outline={outline} />
        </div>
      </div>
    </article>
  );
}

export function PlanPanel() {
  const { generation, generationLoading, activeVariant, manifest, selectedSlide, setSelectedSlide, setDetail } = useApp();
  const outline = activeVariant?.outline ?? null;
  const usedFacts = useMemo(() => new Set((outline?.slides ?? []).flatMap((s) => s.fact_refs)), [outline]);

  if (generationLoading) return <div className="space-y-4" aria-busy>{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-32 w-full rounded-2xl" />)}</div>;
  if (!generation || !activeVariant) return <EmptyState icon={ListTree} title="Плана пока нет" />;
  if (!outline) return <EmptyState icon={ListTree} title="У этого варианта нет плана" hint="Соберите презентацию заново" />;

  const aspect = manifest?.slide_size.w && manifest.slide_size.h ? `${manifest.slide_size.w} / ${manifest.slide_size.h}` : "16 / 9";
  const rev = variantRev(activeVariant);
  const audience = outline.audience?.trim();
  // the audience is written as the person wrote it (nominative): «аудитория: генеральный директор»
  const meta = [plural(outline.slides.length, "слайд", "слайда", "слайдов"), audience ? `аудитория: ${audience.charAt(0).toLowerCase()}${audience.slice(1)}` : null].filter(Boolean).join(" · ");
  const open = (n: number) => {
    setSelectedSlide(n);
    setDetail(null);
  };

  return (
    <div className="space-y-4">
      <section className="rounded-2xl bg-white p-6 shadow-card">
        <h2 className="text-title2 font-bold text-zinc-900">{outline.title}</h2>
        {outline.subtitle && <p className="mt-1 max-w-[680px] text-body text-zinc-700">{outline.subtitle}</p>}
        <p className="mt-1 text-footnote text-zinc-500">{meta}</p>
        {outline.slides.length === 0 ? (
          <EmptyState compact icon={ListTree} title="В плане нет слайдов" />
        ) : (
          <ol className="-mx-4 mt-4 space-y-1" aria-label="Слайды плана">
            {outline.slides.map((s, i) => (
              <li key={s.id}>
                <SlideRow
                  index={i + 1}
                  slide={s}
                  outline={outline}
                  thumb={activeVariant.slides[i] ? withRev(activeVariant.slides[i], rev) : null}
                  aspect={aspect}
                  selected={selectedSlide === i + 1}
                  onOpen={() => open(i + 1)}
                />
              </li>
            ))}
          </ol>
        )}
      </section>

      <FactsRegistry facts={outline.facts} used={usedFacts} hint={figuresLine(activeVariant.audit?.summary.figures)?.text ?? null} />
      <SeriesRegistry series={outline.series} />
    </div>
  );
}
