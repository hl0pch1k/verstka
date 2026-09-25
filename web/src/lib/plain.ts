import type { PlannerInfo } from "../types";

// Plain words for the interface: what a variant is, in one line a non-designer understands.
export const VARIANT_HINT: Record<string, string> = {
  structured: "Одна мысль на слайд, по порядку",
  visual: "Крупные цифры и диаграммы",
  compact: "Меньше слайдов, плотнее текст",
};

export const variantHint = (name: string, fallback?: string) => VARIANT_HINT[name] ?? fallback ?? "";

/** Who wrote the plan of a variant, in words (outline.planned_by; the model's name and the reason when known). */
export function plannedByText(plannedBy: string | undefined, strategyTitle: (name: string) => string, planner?: PlannerInfo | null): string {
  const by = planner?.planned_by === "supplied" ? "supplied" : plannedBy ?? planner?.planned_by ?? null;
  const model = planner?.model_label ? `модель ${planner.model_label}` : "модель";
  if (by === "supplied") return "ваш готовый план";
  if (by === "model") return model;
  if (by === "agent") return planner?.model_label ? `агент: слайды продумала модель ${planner.model_label}` : "агент: слайды продумала модель";
  if (by === "skeleton") return "каркас по теме";
  if (by?.startsWith("shared:")) return `${model}, план варианта «${strategyTitle(by.slice(7))}»`;
  if (!by) return "не записано";
  return planner?.reason && planner.reason_code !== "off" ? `встроенный планировщик: ${planner.reason}` : "встроенный планировщик";
}

export const templateName = (file: string | null | undefined, fallback = "Шаблон") => (file ?? fallback).replace(/\.pptx$/i, "").replace(/_/g, " ");
