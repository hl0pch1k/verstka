// Pure helpers of «Заменить изображение» (the picture card and its job): the job's result read safely, the job's stage
// in plain words, what a picture shows in a line.
import type { PictureChangeResult, SlidePicture } from "../types";

/** The job result arrives as `unknown`: accept it only when it really is a picture change. */
export function asPictureResult(value: unknown): PictureChangeResult | null {
  if (!value || typeof value !== "object") return null;
  const r = value as Record<string, unknown>;
  if (typeof r.reply !== "string" || typeof r.slide !== "number") return null;
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    reply: r.reply,
    changed: !!r.changed,
    applied: typeof r.applied === "boolean" ? r.applied : !!r.changed,
    kind: "picture",
    action: r.action === "remove" ? "remove" : "generate",
    strategy: typeof r.strategy === "string" ? r.strategy : "",
    slide: r.slide,
    picture: r.picture && typeof r.picture === "object" ? (r.picture as PictureChangeResult["picture"]) : null,
    version: num(r.version),
    at: num(r.at),
    score_before: num(r.score_before),
    new_score: num(r.new_score),
  };
}

/** The job's stage in plain words (its own lines «Ставлю изображение на слайд», «Готовлю превью»; the agent's lines
 *  are for the timeline). */
export function stage(message: string): string {
  const m = (message || "").trim().replace(/[.…]+$/, "");
  return /^(?:Рисую|Ставлю|Проверяю|Готовлю|Убираю)(?:\s|$)/.test(m) ? m : "Рисую изображение";
}

/** What the picture shows, in a line: the person's wish for the current one, else the author's description. */
export function about(pic: SlidePicture): string {
  return (pic.wish || pic.hint || pic.label || pic.headline || "").trim();
}

