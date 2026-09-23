// Plain words for the interface: what a variant is, in one line a non-designer understands.
export const VARIANT_HINT: Record<string, string> = {
  structured: "Одна мысль на слайд, по порядку",
  visual: "Крупные цифры и диаграммы",
  compact: "Меньше слайдов, плотнее текст",
};

export const variantHint = (name: string, fallback?: string) => VARIANT_HINT[name] ?? fallback ?? "";

export const templateName = (file: string | null | undefined, fallback = "Шаблон") => (file ?? fallback).replace(/\.pptx$/i, "").replace(/_/g, " ");
