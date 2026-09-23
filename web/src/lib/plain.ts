// Plain words for the interface: what a variant is, in one line a non-designer understands.
export const VARIANT_HINT: Record<string, string> = {
  structured: "Классика: одна мысль на слайд, разделы по порядку",
  visual: "Наглядно: крупные цифры, диаграммы и карточки",
  compact: "Коротко: меньше слайдов, плотнее содержание",
};

export const variantHint = (name: string, fallback?: string) => VARIANT_HINT[name] ?? fallback ?? "";

export const templateName = (file: string | null | undefined, fallback = "Шаблон") => (file ?? fallback).replace(/\.pptx$/i, "").replace(/_/g, " ");
