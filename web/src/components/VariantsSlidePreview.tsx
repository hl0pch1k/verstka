// The slide on the result stage: the largest frame the stage allows (a size container, no magic numbers), the audit
// overlays with hover tooltips, and the stage controls (‹ 3 / 10 ›, «Замечания», full screen).
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ImageOff, Maximize2, MessageSquareWarning } from "lucide-react";
import { cn, plural, SEVERITY_LABEL } from "../lib/utils";
import type { Issue, Severity } from "../types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Chip } from "./ui/Chip";
import { pct, placeTags, SEVERITY_ORDER, SEVERITY_TONE, stagePlaces, worstSeverity } from "./VariantsHelpers";
import type { Rect, StageBox, TagSpot } from "./VariantsHelpers";

interface Props {
  src: string | null;
  slide: number; // 1-based
  headline: string;
  issues: Issue[];
  /** Width / height of the slide; refined from the image's natural size through `onAspect`. */
  aspect: number;
  showIssues: boolean;
  highlightId: string | null;
  onHighlight(id: string | null): void;
  onAspect(a: number): void;
  /** The frame's width and the well's width, in CSS pixels, whenever either changes. */
  onBox?(frame: number, well: number): void;
  onZoom(): void;
  /** Opens the full list of remarks (the quality check). */
  onOpenIssues(): void;
}

const BOX: Record<Severity, string> = {
  error: "border-red-500 bg-red-500/15",
  warn: "border-amber-500 bg-amber-500/20",
  info: "border-accent bg-accent/10",
};
const TAG: Record<Severity, string> = {
  error: "bg-red-600 text-white",
  warn: "bg-amber-500 text-amber-950",
  info: "bg-accent-fill text-white",
};
const DOT: Record<Severity, string> = { error: "bg-red-500", warn: "bg-amber-500", info: "bg-accent" };

const SEVERITIES: Severity[] = ["error", "warn", "info"];
/** The tag's corner that meets the frame stays square: a tab on the frame's edge, a label in its corner. */
const tagRadius = (s: TagSpot) =>
  s.side === "above" ? "rounded-t" : s.side === "below" ? "rounded-b" : s.side === "beside" ? (s.right ? "rounded-r" : "rounded-l") : s.right ? "rounded-bl" : "rounded-br";

/** One marked place on the slide. Remarks on the same spot share it: the frame and the tag take the worst severity, the
 *  tooltip lists every message. The tag sits where placeTags found room (null: the frame alone); it paints above
 *  every frame, so a later frame never tints or crosses it. */
function Overlay({ place, spot, highlighted, onHighlight }: { place: StageBox; spot: TagSpot | null; highlighted: boolean; onHighlight(id: string | null): void }) {
  const { issues, sev, box } = place;
  const tipRight = box.x + box.w / 2 > 0.5;
  const tipAbove = box.y + box.h > 0.72;
  return (
    <div
      role="note"
      aria-label={issues.map((i) => `${SEVERITY_LABEL[i.severity]}: ${i.message}`).join(" · ")}
      onClick={(e) => e.stopPropagation()}
      onMouseEnter={() => onHighlight(issues[0].id)}
      onMouseLeave={() => onHighlight(null)}
      className={cn("group absolute border-2 transition-shadow duration-150 hover:z-30", BOX[sev], highlighted && "z-20 ring-2 ring-zinc-900/50")}
      style={{ left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h) }}
    >
      {spot && (
        // offsets from the frame's outer corner; the -2px is its border (the tag is placed in the padding box)
        <span className={cn("absolute z-[15] whitespace-nowrap px-1 text-caption font-semibold", TAG[sev], tagRadius(spot))} style={{ left: spot.dx - 2, top: spot.dy - 2 }}>
          {SEVERITY_LABEL[sev]}
        </span>
      )}
      <div
        className={cn(
          "pointer-events-none absolute z-30 hidden w-72 space-y-3 rounded-2xl bg-white p-4 text-left shadow-pop group-hover:block",
          tipRight ? "right-0" : "left-0",
          tipAbove ? "bottom-full mb-2" : "top-full mt-2",
        )}
      >
        {issues.map((issue) => (
          <div key={issue.id}>
            <Badge tone={SEVERITY_TONE[issue.severity]} size="sm" dot>
              {SEVERITY_LABEL[issue.severity]}
            </Badge>
            <p className="mt-2 text-footnote text-zinc-900">{issue.message}</p>
            {issue.suggestion && <p className="mt-1 text-caption text-zinc-500">{issue.suggestion}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

/** The well of the stage: takes every pixel the stage leaves and fits the slide into it (container query units). */
export function VariantsSlidePreview({ src, slide, headline, issues, aspect, showIssues, highlightId, onHighlight, onAspect, onBox, onZoom, onOpenIssues }: Props) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const failed = !src || failedSrc === src;
  const loading = !failed && loadedSrc !== src;

  const wellRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const onBoxRef = useRef(onBox);
  onBoxRef.current = onBox;
  // the frame's size in px: the tags are placed in it
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const well = wellRef.current;
    const frame = frameRef.current;
    if (!well || !frame) return;
    const run = () => {
      const r = frame.getBoundingClientRect();
      setSize((s) => (s.w === r.width && s.h === r.height ? s : { w: r.width, h: r.height }));
      onBoxRef.current?.(r.width, well.getBoundingClientRect().width);
    };
    run();
    const ro = new ResizeObserver(run);
    ro.observe(well);
    ro.observe(frame);
    return () => ro.disconnect();
  }, []);

  // the tags' own sizes, from hidden copies (again once the web font is in)
  const probes = useRef<HTMLDivElement>(null);
  const [tagSize, setTagSize] = useState<Partial<Record<Severity, { w: number; h: number }>>>({});
  useLayoutEffect(() => {
    const el = probes.current;
    if (!el) return;
    const run = () => {
      const next: Partial<Record<Severity, { w: number; h: number }>> = {};
      el.querySelectorAll<HTMLElement>("[data-probe]").forEach((p) => {
        next[p.dataset.probe as Severity] = { w: p.offsetWidth, h: p.offsetHeight };
      });
      setTagSize((cur) => (SEVERITIES.every((k) => cur[k]?.w === next[k]?.w && cur[k]?.h === next[k]?.h) ? cur : next));
    };
    run();
    let live = true;
    void document.fonts?.ready.then(() => live && run());
    return () => {
      live = false;
    };
  }, []);

  // remarks on the same spot share one place (the chip counts the same places); the worst paints last (on top)
  const places = useMemo(() => stagePlaces(issues), [issues]);
  const shown = showIssues && !loading;
  const boxes = shown ? [...places.boxes].sort((a, b) => SEVERITY_ORDER[b.sev] - SEVERITY_ORDER[a.sev]) : [];
  const unplaced = shown ? places.unplaced.length : 0;
  const unplacedText = places.boxes.length === 0 ? plural(unplaced, "замечание", "замечания", "замечаний") : `Ещё ${plural(unplaced, "замечание", "замечания", "замечаний")}`;

  // the pill of the remarks without a place is an obstacle for the tags (bottom-3 left-3, 32px high)
  const pill = useRef<HTMLButtonElement>(null);
  const [pillW, setPillW] = useState(0);
  useLayoutEffect(() => {
    const w = unplaced > 0 ? pill.current?.offsetWidth ?? 0 : 0;
    setPillW((cur) => (cur === w ? cur : w));
  }, [unplaced, unplacedText, size.w]);

  const spots = useMemo(() => {
    if (!shown) return new Map<string, TagSpot | null>();
    // before the probes are measured: the label's width at 12px semibold, about 7px a letter
    const sz = (sev: Severity) => tagSize[sev] ?? { w: SEVERITY_LABEL[sev].length * 7 + 8, h: 16 };
    const avoid: Rect[] = pillW > 0 ? [{ x: 12, y: size.h - 12 - 32, w: pillW, h: 32 }] : [];
    return placeTags(places.boxes, size.w, size.h, sz, avoid);
  }, [shown, places, size.w, size.h, tagSize, pillW]);

  return (
    <div ref={wellRef} className="relative grid min-h-0 min-w-0 flex-1 place-items-center" style={{ containerType: "size" }}>
      <div ref={probes} aria-hidden className="pointer-events-none invisible absolute left-0 top-0">
        {SEVERITIES.map((sev) => (
          <span key={sev} data-probe={sev} className="absolute left-0 top-0 whitespace-nowrap px-1 text-caption font-semibold">
            {SEVERITY_LABEL[sev]}
          </span>
        ))}
      </div>
      <div
        ref={frameRef}
        onClick={failed ? undefined : onZoom}
        className={cn(
          "relative overflow-hidden rounded-xl bg-white shadow-[0_1px_3px_rgba(0,16,61,0.08)] ring-1 ring-zinc-900/[0.08]",
          !failed && "cursor-zoom-in",
        )}
        style={{ aspectRatio: String(aspect), width: `min(100cqw, calc(100cqh * ${aspect.toFixed(4)}))` }}
      >
        {/* the previous slide stays under the next one until it has loaded: no flash of a placeholder */}
        {loading && loadedSrc && loadedSrc !== src && (
          <img src={loadedSrc} alt="" aria-hidden draggable={false} className="absolute inset-0 h-full w-full object-contain" />
        )}
        {src && !failed && (
          <img
            key={src}
            src={src}
            alt={`Слайд ${slide}${headline ? `: ${headline}` : ""}`}
            draggable={false}
            decoding="async"
            onLoad={(e) => {
              const im = e.currentTarget;
              if (im.naturalWidth > 0 && im.naturalHeight > 0) onAspect(im.naturalWidth / im.naturalHeight);
              setLoadedSrc(src);
            }}
            onError={() => setFailedSrc(src)}
            className={cn("absolute inset-0 h-full w-full object-contain transition-opacity duration-200 ease-out", loading ? "opacity-0" : "opacity-100")}
          />
        )}
        {loading && !loadedSrc && <div className="skeleton absolute inset-0 rounded-none" aria-hidden />}
        {failed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-zinc-50 px-8 text-center">
            <ImageOff className="h-6 w-6 text-zinc-400" aria-hidden />
            <span className="text-footnote text-zinc-500">Превью не сохранилось</span>
            {headline && <span className="max-w-md text-body font-semibold text-zinc-700">{headline}</span>}
          </div>
        )}
        {boxes.map((place) => (
          <Overlay key={place.key} place={place} spot={spots.get(place.key) ?? null} highlighted={place.issues.some((i) => i.id === highlightId)} onHighlight={onHighlight} />
        ))}
        {/* remarks without a place on the slide (a font size, the whole slide) get a pill instead of a frame */}
        {unplaced > 0 && (
          <button
            ref={pill}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onOpenIssues();
            }}
            title={`${unplacedText} · Список`}
            className="absolute bottom-3 left-3 z-20 inline-flex h-8 max-w-[60%] cursor-pointer items-center gap-2 rounded-full bg-white/95 px-3 text-caption font-semibold text-zinc-900 shadow-raise backdrop-blur-sm transition-colors duration-150 hover:bg-white animate-fade"
          >
            <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT[worstSeverity(places.unplaced) ?? "info"])} aria-hidden />
            <span className="truncate">
              {unplacedText} · <span className="text-accent-700">Список</span>
            </span>
          </button>
        )}
      </div>
    </div>
  );
}

/** The right side of the stage header: «Замечания» (only with remarks), ‹ 3 / 10 › and full screen. The chip comes
 *  first, so the arrows never move when a slide with remarks follows one without. `compact`: a narrow stage (the helper
 *  is open) keeps only the chip's icon and count, so the variant switch never runs under it. */
export function SlideControls({ slide, total, issues, showIssues, canZoom, compact = false, onToggleIssues, onSelect, onZoom }: {
  slide: number;
  total: number;
  issues: Issue[];
  showIssues: boolean;
  canZoom: boolean;
  compact?: boolean;
  onToggleIssues(v: boolean): void;
  onSelect(n: number): void;
  onZoom(): void;
}) {
  // the places the overlay marks, not the raw remarks: two remarks on one text box are one frame and one tag
  const count = useMemo(() => stagePlaces(issues).count, [issues]);
  return (
    <div className="ml-auto flex shrink-0 items-center gap-2">
      {count > 0 && (
        <Chip data-remarks selected={showIssues} aria-pressed={showIssues} count={count} icon={MessageSquareWarning} title={compact ? "Замечания" : undefined} onClick={() => onToggleIssues(!showIssues)}>
          {compact ? <span className="sr-only">Замечания</span> : "Замечания"}
        </Chip>
      )}
      <div data-fixed className="flex items-center gap-2">
        <div className="inline-flex items-center gap-1">
          <Button variant="ghost" shape="circle" size="md" icon={ChevronLeft} aria-label="Предыдущий слайд" title="Предыдущий слайд (←)" disabled={slide <= 1} onClick={() => onSelect(slide - 1)} />
          {/* 48px holds «12 / 30»; the header then fits the slide's width at 1280×720 with the remarks chip */}
          <span className="w-12 text-center text-footnote tabular-nums text-zinc-700">
            {slide} / {total}
          </span>
          <Button variant="ghost" shape="circle" size="md" icon={ChevronRight} aria-label="Следующий слайд" title="Следующий слайд (→)" disabled={slide >= total} onClick={() => onSelect(slide + 1)} />
        </div>
        <Button variant="ghost" shape="circle" size="md" icon={Maximize2} aria-label="На весь экран" title="На весь экран" disabled={!canZoom} onClick={onZoom} />
      </div>
    </div>
  );
}
