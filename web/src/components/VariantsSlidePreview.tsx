// Large preview of the selected slide: natural aspect, audit overlays with hover tooltips, prev/next controls and
// the way to the full screen.
import { useState } from "react";
import { ChevronLeft, ChevronRight, ImageOff, Maximize2 } from "lucide-react";
import { cn, plural, SEVERITY_LABEL } from "../lib/utils";
import type { BboxFrac, Issue, Severity } from "../types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card, CardBody } from "./ui/Card";
import { clampBox, pct, SEVERITY_TONE, worstSeverity } from "./VariantsHelpers";

interface Props {
  src: string | null;
  slide: number; // 1-based
  total: number;
  headline: string;
  kind: string | null;
  issues: Issue[];
  /** Width / height of the slide; refined from the image's natural size through `onAspect`. */
  aspect: number;
  showIssues: boolean;
  onToggleIssues(v: boolean): void;
  highlightId: string | null;
  onHighlight(id: string | null): void;
  onSelect(n: number): void;
  onAspect(a: number): void;
  onZoom(): void;
  /** Opens the full list of remarks (the quality check). */
  onOpenIssues(): void;
  /** Extra height taken above the slide on this screen (a notice): the slide shrinks so the thumbnails stay in view. */
  reserve?: number;
  /** Why the agent chose the slide's form (Agent v2), shown after the slide number; `onWhy` opens the whole story. */
  why?: string | null;
  onWhy?: () => void;
}

const BOX: Record<Severity, string> = {
  error: "border-red-500 bg-red-500/15",
  warn: "border-amber-400 bg-amber-400/20",
  info: "border-sky-500 bg-sky-500/15",
};
const TAG: Record<Severity, string> = { error: "bg-red-600", warn: "bg-amber-500", info: "bg-sky-600" };

function Overlay({ issue, box, highlighted, onHighlight }: { issue: Issue; box: BboxFrac; highlighted: boolean; onHighlight(id: string | null): void }) {
  const sev = issue.severity;
  const tagInside = box.y < 0.035; // no room above the box — keep the label inside the slide
  const tagRight = box.x > 0.86; // a label hung from the left edge would run off the slide
  const tipRight = box.x + box.w / 2 > 0.5;
  const tipAbove = box.y + box.h > 0.72;
  return (
    <div
      role="note"
      aria-label={`${SEVERITY_LABEL[sev]}: ${issue.message}`}
      onClick={(e) => e.stopPropagation()}
      onMouseEnter={() => onHighlight(issue.id)}
      onMouseLeave={() => onHighlight(null)}
      className={cn("group absolute border-2 transition-shadow", BOX[sev], highlighted ? "z-20 shadow-[0_0_0_2px_rgba(24,24,27,0.55)]" : "z-10 hover:z-20")}
      style={{ left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h) }}
    >
      <span
        className={cn(
          "absolute whitespace-nowrap px-1.5 text-[10px] font-semibold leading-4 text-white",
          TAG[sev],
          tagRight ? "right-0" : "left-0",
          tagInside ? (tagRight ? "top-0 rounded-bl" : "top-0 rounded-br") : "-top-0.5 -translate-y-full rounded-t",
        )}
      >
        {SEVERITY_LABEL[sev]}
      </span>
      <div
        className={cn(
          "pointer-events-none absolute z-30 hidden w-72 rounded-2xl bg-white p-3.5 text-left shadow-pop group-hover:block",
          tipRight ? "right-0" : "left-0",
          tipAbove ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        <Badge tone={SEVERITY_TONE[sev]} size="sm" dot>
          {SEVERITY_LABEL[sev]}
        </Badge>
        <p className="mt-2 text-[13px] leading-5 text-zinc-800">{issue.message}</p>
        {issue.suggestion && <p className="mt-1 text-xs leading-4 text-zinc-500">{issue.suggestion}</p>}
      </div>
    </div>
  );
}

export function VariantsSlidePreview({ src, slide, total, headline, kind, issues, aspect, showIssues, onToggleIssues, highlightId, onHighlight, onSelect, onAspect, onZoom, onOpenIssues, reserve = 0, why, onWhy }: Props) {
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const failed = !src || failedSrc === src;
  const loading = !failed && loadedSrc !== src;
  const worst = worstSeverity(issues);

  const boxes: Array<{ issue: Issue; box: BboxFrac; key: string }> = [];
  if (showIssues && !loading) {
    for (const issue of issues) {
      issue.bboxes.forEach((raw, i) => {
        const box = clampBox(raw);
        if (box) boxes.push({ issue, box, key: `${issue.id}:${i}` });
      });
    }
  }

  const unplaced = issues.length - new Set(boxes.map((b) => b.issue.id)).size;

  return (
    <Card className="min-w-0">
      <div className="flex items-center gap-3 px-5 pb-3 pt-4">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold leading-5 text-zinc-900">{headline || "Без заголовка"}</p>
          <p className="truncate text-xs text-zinc-500">
            Слайд {slide} из {total}
            {kind ? ` · ${kind}` : ""}
            {why && (
              <>
                {" · "}
                {/* an inline span, not a button: a button is one unbreakable box and the ellipsis would swallow it whole */}
                <span
                  role="button"
                  tabIndex={0}
                  onClick={onWhy}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onWhy?.();
                    }
                  }}
                  title={why}
                  className="cursor-pointer text-zinc-600 hover:text-accent-700 hover:underline focus:outline-none focus-visible:underline"
                >
                  почему: {/^.\p{Ll}/u.test(why) ? why.charAt(0).toLowerCase() + why.slice(1) : why}
                </span>
              </>
            )}
          </p>
        </div>
        {issues.length > 0 && (
          <button
            type="button"
            role="switch"
            aria-checked={showIssues}
            onClick={() => onToggleIssues(!showIssues)}
            className="inline-flex h-9 shrink-0 cursor-pointer items-center gap-2 rounded-full px-2.5 text-[13px] font-semibold text-zinc-700 transition-colors hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
          >
            <span className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors", showIssues ? "bg-accent" : "bg-zinc-300")} aria-hidden>
              <span className={cn("absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", showIssues ? "translate-x-[18px]" : "translate-x-0.5")} />
            </span>
            Показать замечания
            <Badge size="sm" tone={worst ? SEVERITY_TONE[worst] : "neutral"}>
              {issues.length}
            </Badge>
          </button>
        )}
        <div className="flex shrink-0 items-center gap-1">
          <Button icon={ChevronLeft} aria-label="Предыдущий слайд" title="Предыдущий слайд (←)" disabled={slide <= 1} onClick={() => onSelect(slide - 1)} className="rounded-full" />
          <Button icon={ChevronRight} aria-label="Следующий слайд" title="Следующий слайд (→)" disabled={slide >= total} onClick={() => onSelect(slide + 1)} className="rounded-full" />
          <Button icon={Maximize2} aria-label="На весь экран" title="На весь экран" disabled={failed} onClick={onZoom} className="rounded-full" />
        </div>
      </div>
      <CardBody className="px-4 pb-4 pt-1">
        <div
          onClick={failed ? undefined : onZoom}
          className={cn("relative mx-auto overflow-hidden rounded-xl bg-zinc-100 shadow-inner-line", !failed && "cursor-zoom-in")}
          // the slide shrinks with the window height so the thumbnails under it stay on screen
          style={{ aspectRatio: String(aspect), width: `min(100%, max(520px, calc((100vh - ${500 + reserve}px) * ${aspect.toFixed(4)})))` }}
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
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-8 text-center text-zinc-400">
              <ImageOff className="h-6 w-6" aria-hidden />
              <span className="text-xs">Превью слайда не отрендерено</span>
              {headline && <span className="max-w-md text-sm font-medium text-zinc-600">{headline}</span>}
            </div>
          )}
          {boxes.map(({ issue, box, key }) => (
            <Overlay key={key} issue={issue} box={box} highlighted={highlightId === issue.id} onHighlight={onHighlight} />
          ))}
          {/* remarks without a place on the slide (a font size, the whole slide) get a pill instead of a frame */}
          {showIssues && !loading && unplaced > 0 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onOpenIssues();
              }}
              className="absolute bottom-3 left-3 z-20 inline-flex cursor-pointer items-center gap-2 rounded-full bg-white/95 py-1.5 pl-3 pr-3.5 text-xs font-semibold text-zinc-800 shadow-raise backdrop-blur-sm transition-colors hover:bg-white animate-fade focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              <span className={cn("h-2 w-2 rounded-full", worst === "error" ? "bg-red-500" : worst === "warn" ? "bg-amber-400" : "bg-sky-500")} aria-hidden />
              {unplaced === issues.length ? plural(unplaced, "замечание", "замечания", "замечаний") : `Ещё ${plural(unplaced, "замечание", "замечания", "замечаний")} без места на слайде`}
              <span className="font-medium text-accent-700">Открыть список</span>
            </button>
          )}
        </div>
      </CardBody>
    </Card>
  );
}
