// The build's rail: a tile per slide of the variant on show, the same column the deck's thumbnails will take. A tile
// waits as a shimmering skeleton with its number; when the designer has thought the slide through it fills in (a
// short pop and a ring flash) with the form's icon and the slide's headline; the critic's note marks it amber, the
// revision blue; a laid-out slide gets a thin bar at its foot; once the previews are rendered the real thumbnail fades
// in over the sketch. The slide the stage speaks of is ringed, and the rail scrolls to keep it in view.
import { useEffect, useRef, useState } from "react";
import {
  AlignLeft, Bookmark, ChartBar, ChartColumn, ChartLine, ChartPie, Columns2, Hash, Image, LayoutGrid, List, ListOrdered, Milestone, Presentation, Quote, Table2,
  type LucideIcon,
} from "lucide-react";
import { smoothScroll } from "../../lib/motion";
import type { RailSlide, SketchKind } from "../../lib/stage";
import { cn } from "../../lib/utils";

const ICON: Record<SketchKind, LucideIcon> = {
  cover: Presentation, bars: ChartColumn, hbars: ChartBar, pie: ChartPie, line: ChartLine, table: Table2, numbers: Hash,
  cards: LayoutGrid, list: List, timeline: Milestone, compare: Columns2, quote: Quote, image: Image, agenda: ListOrdered,
  section: Bookmark, text: AlignLeft,
};

const FADE = {
  both: "[mask-image:linear-gradient(to_bottom,transparent,#000_28px,#000_calc(100%-28px),transparent)]",
  top: "[mask-image:linear-gradient(to_bottom,transparent,#000_28px)]",
  bottom: "[mask-image:linear-gradient(to_bottom,#000_calc(100%-28px),transparent)]",
};

/** The critic's note (amber) or the revision that answered it (blue). */
function MarkDot({ mark, inline = false }: { mark: "note" | "fixed"; inline?: boolean }) {
  return (
    <span
      key={mark}
      className={cn("block h-2 w-2 shrink-0 animate-pop rounded-full", mark === "note" ? "bg-amber-500" : "bg-accent", !inline && "absolute right-1.5 top-1.5 ring-2 ring-white")}
      title={mark === "note" ? "Критик оставил замечание" : "Слайд переделан по замечанию"}
      aria-hidden
    />
  );
}

function Tile({ s, image, focus, aspect }: { s: RailSlide; image: string | null; focus: boolean; aspect: number }) {
  const [loaded, setLoaded] = useState(false);
  const Icon = s.sketch ? ICON[s.sketch.kind] : null;
  const label = `Слайд ${s.n}${s.sketch?.headline ? `: ${s.sketch.headline}` : s.sketch ? "" : " — ещё не продуман"}`;
  return (
    <li data-n={s.n} aria-label={label} aria-current={focus || undefined}>
      {/* keyed by the sketch: a tile that fills in plays its pop (the tile) and its ring flash (the frame) once */}
      <span key={s.sketch ? `s-${s.sketch.kind}` : "wait"} className={cn("relative block rounded-lg", s.sketch && "animate-tile-pulse")}>
      <span
        className={cn(
          "relative block w-full overflow-hidden rounded-lg transition-shadow duration-300",
          s.sketch ? "animate-fill-in bg-white ring-1 ring-zinc-900/[0.08]" : "skeleton !rounded-lg",
          focus && "!shadow-[0_0_0_2px_#0077FF]",
        )}
        style={{ aspectRatio: String(aspect) }}
      >
        {s.sketch && Icon && (
          <span className="flex h-full flex-col gap-1 p-2" aria-hidden>
            <span className="flex items-center gap-1.5">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-accent-50 text-accent-700">
                <Icon className="h-3 w-3" strokeWidth={2.25} />
              </span>
              <span className="ml-auto flex items-center gap-1.5">
                {s.mark && <MarkDot mark={s.mark} inline />}
                <span className="font-mono text-caption font-semibold tabular-nums text-zinc-400">{String(s.n).padStart(2, "0")}</span>
              </span>
            </span>
            <span className="line-clamp-2 text-caption font-semibold leading-[15px] text-zinc-800">{s.sketch.headline ?? "Слайд"}</span>
          </span>
        )}
        {image && (
          <img
            src={image}
            alt=""
            draggable={false}
            onLoad={() => setLoaded(true)}
            className={cn("absolute inset-0 h-full w-full object-cover transition-opacity duration-500 ease-out", loaded ? "opacity-100" : "opacity-0")}
          />
        )}
        {/* the number badge of a skeleton and of a preview (a sketch carries its number in its own top row) */}
        {(!s.sketch || (image && loaded)) && (
          <span className={cn("absolute bottom-1 left-1 rounded px-1 text-caption font-semibold leading-4 tabular-nums text-white transition-colors duration-150", focus ? "bg-accent-fill" : "bg-zinc-900/55")} aria-hidden>
            {s.n}
          </span>
        )}
        {/* a sketch carries the mark in its top row; a preview in its corner */}
        {s.mark && image && loaded && <MarkDot mark={s.mark} />}
        {/* laid out: a thin bar along the tile's foot */}
        {s.laid && !image && <span className="absolute inset-x-0 bottom-0 h-[3px] origin-left animate-grow-x bg-brand" aria-hidden />}
      </span>
      </span>
    </li>
  );
}

export function StageRail({ slides, images, focus, aspect, className }: {
  slides: RailSlide[];
  /** Slide number → the rendered preview (once the build has rendered them). */
  images: Record<number, string>;
  /** The slide the stage speaks of now (ringed, kept in view). */
  focus: number | null;
  aspect: number;
  className?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ top: false, bottom: false });
  const measure = () => {
    const el = box.current;
    if (!el) return;
    const top = el.scrollTop > 1;
    const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
    setEdges((e) => (e.top === top && e.bottom === bottom ? e : { top, bottom }));
  };
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    return () => ro.disconnect();
  }, [slides.length]);
  // the slide the stage speaks of stays in view (the rail scrolls by itself only)
  useEffect(() => {
    const el = box.current;
    const tile = focus ? el?.querySelector<HTMLElement>(`[data-n="${focus}"]`) : null;
    if (!el || !tile) return;
    const top = tile.offsetTop;
    if (top - 32 < el.scrollTop || top + tile.offsetHeight + 32 > el.scrollTop + el.clientHeight) {
      el.scrollTo({ top: Math.max(0, top - (el.clientHeight - tile.offsetHeight) / 2), behavior: smoothScroll() });
    }
  }, [focus]);
  const fade = edges.top && edges.bottom ? FADE.both : edges.top ? FADE.top : edges.bottom ? FADE.bottom : "";
  const planned = slides.filter((s) => s.sketch).length;
  return (
    <nav aria-label={`Слайды: продумано ${planned} из ${slides.length}`} className={cn("flex min-h-0 flex-col overflow-hidden rounded-2xl bg-white shadow-card", className)}>
      <div ref={box} onScroll={measure} className={cn("relative min-h-0 flex-1 overflow-y-auto overflow-x-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", fade)}>
        <ol className="relative flex flex-col gap-3 p-3">
          {slides.map((s) => (
            <Tile key={s.n} s={s} image={images[s.n] ?? null} focus={focus === s.n} aspect={aspect} />
          ))}
        </ol>
      </div>
    </nav>
  );
}
