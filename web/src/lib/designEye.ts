// «Взгляд дизайнера» (Verstka 3.0) in words: the counts line of the quality tab and a slide's problems as the model
// named them (the closed list of codes, in Russian, with where on the slide).
import type { DesignEye, DesignEyeSlide } from "../types";
import { plural } from "./utils";

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
