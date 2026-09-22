// Large preview of the selected slide: natural aspect, audit overlays with hover tooltips, prev/next controls.
import { useState } from "react";
import { ChevronLeft, ChevronRight, ImageOff } from "lucide-react";
import { cn, SEVERITY_LABEL } from "../lib/utils";
import type { BboxFrac, Issue, Severity } from "../types";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
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
  const tipRight = box.x + box.w / 2 > 0.5;
  const tipAbove = box.y + box.h > 0.72;
  return (
    <div
      role="note"
      aria-label={`${SEVERITY_LABEL[sev]} ${issue.check_id}: ${issue.message}`}
      onMouseEnter={() => onHighlight(issue.id)}
      onMouseLeave={() => onHighlight(null)}
      className={cn("group absolute border-2 transition-shadow", BOX[sev], highlighted ? "z-20 shadow-[0_0_0_2px_rgba(24,24,27,0.55)]" : "z-10 hover:z-20")}
      style={{ left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h) }}
    >
      <span
        className={cn(
          "absolute left-0 whitespace-nowrap px-1 font-mono text-[9px] leading-[13px] text-white",
          TAG[sev],
          tagInside ? "top-0 rounded-br" : "-top-0.5 -translate-y-full rounded-t",
        )}
      >
        {issue.check_id}
      </span>
      <div
        className={cn(
          "pointer-events-none absolute z-30 hidden w-72 rounded-lg border border-zinc-200 bg-white p-3 text-left shadow-pop group-hover:block",
          tipRight ? "right-0" : "left-0",
          tipAbove ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        <div className="flex items-center gap-1.5">
          <Badge tone={SEVERITY_TONE[sev]} size="sm" dot>
            {SEVERITY_LABEL[sev]}
          </Badge>
          <span className="font-mono text-[11px] text-zinc-500">{issue.check_id}</span>
        </div>
        <p className="mt-1.5 text-xs leading-4 text-zinc-800">{issue.message}</p>
        {issue.suggestion && <p className="mt-1 text-[11px] leading-4 text-zinc-500">{issue.suggestion}</p>}
      </div>
    </div>
  );
}

export function VariantsSlidePreview({ src, slide, total, headline, kind, issues, aspect, showIssues, onToggleIssues, highlightId, onHighlight, onSelect, onAspect }: Props) {
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

  return (
    <Card className="min-w-0">
      <CardHeader
        actions={
          <>
            {kind && <Badge>{kind}</Badge>}
            <button
              type="button"
              role="switch"
              aria-checked={showIssues}
              onClick={() => onToggleIssues(!showIssues)}
              className="inline-flex h-8 items-center gap-2 rounded-lg px-1.5 text-[13px] text-zinc-700 transition-colors hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
            >
              <span className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors", showIssues ? "bg-accent" : "bg-zinc-300")} aria-hidden>
                <span className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform", showIssues ? "translate-x-[18px]" : "translate-x-0.5")} />
              </span>
              Показывать замечания
              {issues.length > 0 && (
                <Badge size="sm" tone={worst ? SEVERITY_TONE[worst] : "neutral"}>
                  {issues.length}
                </Badge>
              )}
            </button>
            <span className="mx-1 h-5 w-px bg-zinc-200" aria-hidden />
            <span className="text-xs tabular-nums text-zinc-500">
              {slide} / {total}
            </span>
            <Button size="sm" icon={ChevronLeft} aria-label="Предыдущий слайд" title="Предыдущий слайд (←)" disabled={slide <= 1} onClick={() => onSelect(slide - 1)} />
            <Button size="sm" icon={ChevronRight} aria-label="Следующий слайд" title="Следующий слайд (→)" disabled={slide >= total} onClick={() => onSelect(slide + 1)} />
          </>
        }
      >
        <CardTitle hint={headline || "Без заголовка"}>
          Слайд {slide} из {total}
        </CardTitle>
      </CardHeader>
      <CardBody className="p-3">
        <div className="relative w-full overflow-hidden rounded-lg bg-zinc-100 ring-1 ring-zinc-200" style={{ aspectRatio: String(aspect) }}>
          {src && !failed && (
            <img
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
              className={cn("absolute inset-0 h-full w-full object-contain transition-opacity duration-200", loading ? "opacity-0" : "opacity-100")}
            />
          )}
          {loading && <div className="skeleton absolute inset-0 rounded-none" aria-hidden />}
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
        </div>
        <p className="mt-2 flex items-center gap-3 px-1 text-[11px] text-zinc-400">
          <span>← → — переключение слайдов</span>
          {showIssues && issues.length > 0 && <span>наведите на рамку, чтобы прочитать замечание</span>}
          {showIssues && issues.length > 0 && boxes.length === 0 && !loading && <span>у замечаний этого слайда нет области на макете</span>}
        </p>
      </CardBody>
    </Card>
  );
}
