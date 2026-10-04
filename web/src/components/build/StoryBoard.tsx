// The build's storyboard: a card per slide of the variant on show, in the template's proportions, laid on the page like
// slides on a table, as large as the column lets every slide be seen at once. A card waits empty; when the designer has
// thought the slide through it fills in
// with the sketch of its form (drawn in the template's colour) and the caption names the form; the critic's note marks
// it «Замечание», the revision that answered it «Переделан»; a laid-out slide gets a check in its caption; once the
// previews are rendered, the real slide fades in over the sketch and the caption keeps only the slide's number and the
// critic's mark (the sketch's form label and the check are the sketch's story, the real slide tells its own). The card
// the agent speaks of now is ringed (a card still being thought about shimmers) and kept in view — unless the reader is
// scrolling the board themselves. Above the cards: the title, how far the slides are, and the variants' switch (the
// same control the finished deck has).
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { AlertCircle, Check } from "lucide-react";
import { smoothScroll } from "../../lib/motion";
import { BOARD_GAP, fitColumns, KIND_LABEL, type RailSlide } from "../../lib/stage";
import { cn } from "../../lib/utils";
import { SlideSketch } from "./SlideSketch";

function useColumns(box: RefObject<HTMLElement>, n: number, aspect: number): number {
  const [cols, setCols] = useState(4);
  const last = useRef<{ w: number; h: number; cols: number } | null>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    // the width without the scrollbar's room: the columns that fit need no scrollbar, and one that appears for more
    // slides than fit never takes a column away
    const fit = () => {
      const st = getComputedStyle(el);
      const w = el.offsetWidth - parseFloat(st.paddingLeft) - parseFloat(st.paddingRight);
      const h = el.clientHeight - parseFloat(st.paddingTop) - parseFloat(st.paddingBottom);
      let next = fitColumns(w, h, n, aspect);
      // the plan's count moves by a slide or two while the agent works (13 planned, 12 laid out): the grid keeps its
      // columns instead of reflowing every card; it takes fewer only when the board itself changes size
      const prev = last.current;
      if (prev && Math.abs(prev.w - w) < 1 && Math.abs(prev.h - h) < 1 && next < prev.cols) next = prev.cols;
      last.current = { w, h, cols: next };
      setCols(next);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [box, n, aspect]);
  return cols;
}

/** The critic's note on a slide, then the revision that answered it, in the card's corner. */
function Mark({ mark, live }: { mark: "note" | "fixed"; live: boolean }) {
  return (
    <span
      className={cn(
        "absolute bottom-[7%] right-[5%] inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-[11px] font-semibold leading-none shadow-raise",
        mark === "note" ? "bg-amber-50 text-amber-800" : "bg-white text-accent-700",
        live && "animate-pop",
      )}
      title={mark === "note" ? "Критик оставил замечание к этому слайду" : "Слайд переделан по замечанию критика"}
    >
      {mark === "note" ? <AlertCircle className="h-3 w-3" strokeWidth={2.5} aria-hidden /> : <Check className="h-3 w-3" strokeWidth={3} aria-hidden />}
      {mark === "note" ? "Замечание" : "Переделан"}
    </span>
  );
}

function Card({ s, image, focus, aspect, running }: { s: RailSlide; image: string | null; focus: boolean; aspect: number; running: boolean }) {
  // what the card already showed when it mounted is shown finished; what arrives while the reader watches draws itself
  const [born] = useState(() => ({ planned: !!s.sketch, mark: s.mark }));
  const [loaded, setLoaded] = useState(false);
  const planned = !!s.sketch;
  // the real slide is on the card: the caption keeps the number and the critic's mark only
  const real = !!image && loaded;
  const label = s.sketch ? KIND_LABEL[s.sketch.kind] : null;
  const state = image && loaded ? "готов" : s.laid ? "сверстан" : planned ? "продуман" : "ещё не продуман";
  return (
    <li data-n={s.n} className="min-w-0" aria-label={`Слайд ${s.n}${s.sketch?.headline ? `, «${s.sketch.headline}»` : ""}${label ? `, ${label.toLowerCase()}` : ""}: ${state}`}>
      <div
        className={cn(
          "relative overflow-hidden rounded-xl transition-[box-shadow,background-color] duration-200",
          planned ? "bg-white shadow-card" : focus && running ? "skeleton !rounded-xl" : "bg-white shadow-[inset_0_0_0_1px_#E3E4E7]",
          focus && "!shadow-selected",
        )}
        style={{ aspectRatio: String(aspect), containerType: "inline-size" }}
      >
        {!planned && (
          <span aria-hidden className="absolute left-[7%] top-[9%] h-[7%] w-[44%] rounded-[2px] bg-zinc-900/[0.06]" />
        )}
        {s.sketch && (
          // keyed by the form: a revision that changes it draws the new one
          <div key={s.sketch.kind} className={cn("absolute inset-0", !born.planned && "animate-fill-in")}>
            <SlideSketch sketch={s.sketch} live={!born.planned} />
          </div>
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
        {/* the mark over the sketch; it leaves the card for the caption when the real slide comes (never over its content) */}
        {s.mark && (
          <span className={cn("transition-opacity duration-300 ease-out", real ? "opacity-0" : "opacity-100")}>
            <Mark key={s.mark} mark={s.mark} live={s.mark !== born.mark} />
          </span>
        )}
      </div>
      <div aria-hidden className="mt-2 flex h-4 items-center gap-1.5 text-caption">
        <span className={cn("shrink-0 font-semibold tabular-nums transition-colors duration-150", focus ? "text-accent-600" : "text-zinc-900")}>{s.n}</span>
        {label && !real && <span key={label} className={cn("min-w-0 truncate text-zinc-500", !born.planned && "animate-fade")}>{label}</span>}
        {real ? (
          s.mark && (
            <span className={cn("ml-auto inline-flex shrink-0 animate-fade items-center gap-1 font-medium", s.mark === "note" ? "text-amber-700" : "text-accent-600")}>
              {s.mark === "note" ? <AlertCircle className="h-3.5 w-3.5" strokeWidth={2.25} /> : <Check className="h-3.5 w-3.5" strokeWidth={2.75} />}
              {s.mark === "note" ? "Замечание" : "Переделан"}
            </span>
          )
        ) : (
          s.laid && <Check className="ml-auto h-3.5 w-3.5 shrink-0 text-accent-600" strokeWidth={2.5} />
        )}
      </div>
    </li>
  );
}

export function StoryBoard({ variant, slides, images, focus, aspect, ink, running, status, switcher, className, style }: {
  /** The variant on show (the cards are its own; switching shows the other's finished). */
  variant: string;
  slides: RailSlide[];
  /** Slide number → its rendered preview (once the build has rendered them). */
  images: Record<number, string>;
  /** The slide the agent speaks of now. */
  focus: number | null;
  aspect: number;
  /** The template's colours for the sketches (lib/stage sketchInk). */
  ink: { ink: string; soft: string };
  running: boolean;
  /** «продумано 7 из 12» */
  status: string;
  /** The variants' switch (more than one variant). */
  switcher?: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cols = useColumns(box, slides.length, aspect);
  // the reader scrolling the board (wheel, touch, keys, the scrollbar) holds it where they put it for 5 s
  const pausedUntil = useRef(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const pause = () => void (pausedUntil.current = performance.now() + 5000);
    const onKey = (e: KeyboardEvent) => ["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "].includes(e.key) && pause();
    el.addEventListener("wheel", pause, { passive: true });
    el.addEventListener("touchmove", pause, { passive: true });
    el.addEventListener("pointerdown", pause);
    el.addEventListener("keydown", onKey);
    return () => {
      el.removeEventListener("wheel", pause);
      el.removeEventListener("touchmove", pause);
      el.removeEventListener("pointerdown", pause);
      el.removeEventListener("keydown", onKey);
    };
  }, []);
  // the card the agent speaks of stays in view (the list scrolls by itself only when it has to)
  useEffect(() => {
    const el = box.current;
    const card = focus ? el?.querySelector<HTMLElement>(`[data-n="${focus}"]`) : null;
    if (!el || !card || performance.now() < pausedUntil.current) return;
    const top = card.offsetTop;
    if (top - 16 < el.scrollTop || top + card.offsetHeight + 16 > el.scrollTop + el.clientHeight) {
      el.scrollTo({ top: Math.max(0, top - (el.clientHeight - card.offsetHeight) / 2), behavior: smoothScroll() });
    }
  }, [focus]);
  return (
    <section aria-label="Слайды" className={cn("flex min-h-0 min-w-0 flex-col", className)} style={style}>
      {/* as tall as the agent's column header, so the two titles share a line */}
      <div className="flex h-16 shrink-0 items-center gap-3">
        <h2 className="text-title3 font-semibold text-zinc-900">Слайды</h2>
        <span className="min-w-0 truncate text-footnote tabular-nums text-zinc-500">{status}</span>
        {switcher && <div className="ml-auto shrink-0">{switcher}</div>}
      </div>
      {/* 4px of room around the cards for the focus ring and the shadows (the list's own edge clips them otherwise) */}
      <div ref={box} className="scroll-thin relative -mx-1 min-h-0 flex-1 overflow-y-auto overscroll-contain px-1 pb-1 pt-1" style={{ ["--sk" as string]: ink.ink, ["--sk-soft" as string]: ink.soft }}>
        {/* keyed by the variant: switching shows the other variant's cards as they are, without replaying their arrival */}
        <ol key={variant} className="grid" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: BOARD_GAP }}>
          {slides.map((s) => (
            <Card key={s.n} s={s} image={images[s.n] ?? null} focus={focus === s.n} aspect={aspect} running={running} />
          ))}
        </ol>
      </div>
    </section>
  );
}
