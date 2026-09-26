// Small helpers shared by the template panel pieces (the layouts gallery and the pattern modal).
import { useEffect, useState } from "react";
import { ImageOff } from "lucide-react";
import { cn, plural } from "../lib/utils";
import type { ClassificationTrace, RepeatGroup, SignalVote } from "../types";
import type { ProgressTone } from "./ui/Progress";

/** «3 ячейки · ряд · до 5» */
export function groupSummary(g: RepeatGroup): string {
  const cells = g.member_shape_ids.length;
  const axis = g.axis === "row" ? "ряд" : g.axis === "column" ? "колонка" : g.axis === "grid" ? `сетка ${g.rows}×${g.cols}` : g.axis;
  const range = g.min_n > 1 && g.min_n < g.max_n ? `от ${g.min_n} до ${g.max_n}` : `до ${g.max_n}`;
  return `${plural(cells, "ячейка", "ячейки", "ячеек")} · ${axis} · ${range}`;
}

/** The tone of a sample's quality bar. */
export const qualityTone = (q: number): ProgressTone => (q >= 0.9 ? "success" : q >= 0.75 ? "accent" : q >= 0.5 ? "warn" : "error");

export function votesOf(c: ClassificationTrace): Array<{ source: string; vote: SignalVote }> {
  const list: Array<{ source: string; vote: SignalVote | null }> = [
    { source: "правила", vote: c.heuristic },
    { source: "языковая модель", vote: c.llm },
    { source: "модель зрения", vote: c.vlm },
  ];
  return list.filter((v): v is { source: string; vote: SignalVote } => !!v.vote);
}

/** Lazy slide thumbnail with a quiet fallback. Fills its positioned parent. `fallback`: a smaller picture to show when
 *  `src` fails (the full-size render → its thumbnail). */
export function PatternThumb({ src: wanted, fallback, alt, className }: { src?: string | null; fallback?: string | null; alt: string; className?: string }) {
  const [src, setSrc] = useState(wanted);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setSrc(wanted);
    setFailed(false);
  }, [wanted]);
  if (!src || failed) {
    return (
      <div className={cn("flex h-full w-full flex-col items-center justify-center gap-1 text-zinc-400", className)} role="img" aria-label={alt}>
        <ImageOff className="h-6 w-6" aria-hidden />
        <span className="text-caption text-zinc-500">нет превью</span>
      </div>
    );
  }
  const onError = () => (fallback && src !== fallback ? setSrc(fallback) : setFailed(true));
  return <img src={src} alt={alt} loading="lazy" decoding="async" draggable={false} onError={onError} className={cn("h-full w-full object-cover", className)} />;
}
