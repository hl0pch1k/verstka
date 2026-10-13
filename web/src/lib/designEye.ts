// «Взгляд дизайнера» (Verstka 3.0) in words: the counts line of the quality tab, a slide's problems as the model
// named them (the closed list of codes, in Russian, with where on the slide) and why it did not look (a skip's code).
import type { AgentEvent, DesignEye, DesignEyeSlide, Variant } from "../types";
import { plural } from "./utils";

/** Why «Взгляд дизайнера» did not look at a variant, by the server's code (`eyes.skipped_code`; the same words as
 *  verstka/audit/eyes.py `SKIP_RU` — a Python test keeps them equal). The reason in English (`eyes.skipped`) is for the
 *  log and never reaches the screen. */
export const EYES_SKIP: Record<string, string> = {
  off: "выключен в настройках",
  no_model: "модель недоступна",
  no_time: "не хватило времени на сборку",
  no_images: "не получилось снять картинки слайдов",
  no_answer: "модель не ответила",
  failed: "не получилось посмотреть на слайды",
};

/** The timeline's line of a skipped review, as the server says it (eyes.py `skip_message`): «Взгляд дизайнера
 *  пропущен: не хватило времени на сборку.»; a code this interface does not know — without the reason. */
export function eyesSkipMessage(code: string | null | undefined): string {
  const why = code ? EYES_SKIP[code] : undefined;
  return why ? `Взгляд дизайнера пропущен: ${why}.` : "Взгляд дизайнера пропущен.";
}

/** A review the server skipped without a line on the timeline (runs built before it said so): the line it says now,
 *  made from the variant's record — «Подробнее» → «Агент» shows the step skipped with its reason. null — the review
 *  ran, or the timeline has its own lines (a skip said, a model that did not answer). */
export function eyesSkipEvent(v: Pick<Variant, "strategy" | "eyes" | "agent">): AgentEvent | null {
  const eye = v.eyes;
  if (!eye?.skipped) return null;
  const own = (v.agent?.events ?? []).some((e) => (e.step ?? "").toLowerCase() === "eyes" && (e.variant == null || e.variant === v.strategy));
  if (own || eye.skipped_code === "no_answer") return null;
  return { step: "eyes", message: eyesSkipMessage(eye.skipped_code), slide: null, variant: v.strategy };
}

/** «Слова разорваны посередине (карточки); пустоты и перекос композиции» — the serious ones when there are any. */
export function problemsText(s: DesignEyeSlide, majorOnly: boolean): string {
  const shown = s.problems.filter((p) => !majorOnly || p.severity === "major");
  return (shown.length ? shown : s.problems).map((p) => (p.where ? `${p.label} (${p.where})` : p.label)).join("; ");
}

/** «посмотрел на 9 слайдов · пересобрал 2 · 1 оставил как было». */
export function designEyeLine(eye: DesignEye): string {
  const fixed = eye.slides.filter((s) => s.status === "fixed").length;
  const kept = eye.slides.filter((s) => s.status === "kept").length;
  const parts = [`посмотрел на ${plural(eye.looked, "слайд", "слайда", "слайдов")}`];
  if (fixed) parts.push(`пересобрал ${fixed}`);
  if (kept) parts.push(`${kept} оставил как было`);
  if (!eye.slides.length) parts.push("замечаний нет");
  return parts.join(" · ");
}
