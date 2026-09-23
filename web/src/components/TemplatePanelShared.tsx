// Small helpers shared by the template panel pieces (gallery, pattern modal) and reused by the plan panel.
import { useState } from "react";
import { ImageOff } from "lucide-react";
import { cn, plural } from "../lib/utils";
import type { ClassificationTrace, RepeatGroup, SignalVote } from "../types";

/** «3 ячейки · ряд · до 5» */
export function groupSummary(g: RepeatGroup): string {
  const cells = g.member_shape_ids.length;
  const axis = g.axis === "row" ? "ряд" : g.axis === "column" ? "колонка" : g.axis === "grid" ? `сетка ${g.rows}×${g.cols}` : g.axis;
  const range = g.min_n > 1 && g.min_n < g.max_n ? `от ${g.min_n} до ${g.max_n}` : `до ${g.max_n}`;
  return `${plural(cells, "ячейка", "ячейки", "ячеек")} · ${axis} · ${range}`;
}

export const qualityTone = (q: number) => (q >= 0.9 ? "bg-emerald-500" : q >= 0.75 ? "bg-accent" : q >= 0.5 ? "bg-amber-500" : "bg-red-500");

export function votesOf(c: ClassificationTrace): Array<{ source: string; vote: SignalVote }> {
  const list: Array<{ source: string; vote: SignalVote | null }> = [
    { source: "правила", vote: c.heuristic },
    { source: "языковая модель", vote: c.llm },
    { source: "модель зрения", vote: c.vlm },
  ];
  return list.filter((v): v is { source: string; vote: SignalVote } => !!v.vote);
}

/** Lazy slide thumbnail with a graceful «нет превью» fallback. Fills its positioned parent. */
export function PatternThumb({ src, alt, className }: { src?: string | null; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <div className={cn("flex h-full w-full flex-col items-center justify-center gap-1 text-zinc-400", className)}>
        <ImageOff className="h-5 w-5" aria-hidden />
        <span className="text-[11px]">нет превью</span>
      </div>
    );
  }
  return <img src={src} alt={alt} loading="lazy" decoding="async" draggable={false} onError={() => setFailed(true)} className={cn("h-full w-full object-cover", className)} />;
}
