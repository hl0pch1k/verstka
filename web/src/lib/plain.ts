// Plain words for the interface: what a variant is, in one line a non-designer understands.
export const VARIANT_HINT: Record<string, string> = {
  structured: "Одна мысль на слайд, по порядку",
  visual: "Крупные цифры и диаграммы",
  compact: "Меньше слайдов, плотнее текст",
};

export const variantHint = (name: string, fallback?: string) => VARIANT_HINT[name] ?? fallback ?? "";

/** Who wrote the plan of a variant, in words (outline.planned_by). */
export function plannedByText(plannedBy: string | undefined, strategyTitle: (name: string) => string): string {
  if (plannedBy === "model") return "модель";
  if (plannedBy === "skeleton") return "каркас по теме";
  if (plannedBy?.startsWith("shared:")) return `модель, план варианта «${strategyTitle(plannedBy.slice(7))}»`;
  return "встроенный планировщик";
}

export const templateName = (file: string | null | undefined, fallback = "Шаблон") => (file ?? fallback).replace(/\.pptx$/i, "").replace(/_/g, " ");
