// The five steps of the product flow and how views (TabKey) map onto them.
import type { LucideIcon } from "lucide-react";
import { Download, Layers, LayoutTemplate, PenLine, ShieldCheck } from "lucide-react";
import type { StepKey, TabKey } from "../../types";

export interface StepDef { key: StepKey; label: string; icon: LucideIcon; tab: TabKey }

export const STEPS: StepDef[] = [
  { key: "template", label: "Шаблон", icon: LayoutTemplate, tab: "template" },
  { key: "brief", label: "Бриф", icon: PenLine, tab: "brief" },
  { key: "variants", label: "Варианты", icon: Layers, tab: "variants" },
  { key: "audit", label: "Аудит", icon: ShieldCheck, tab: "audit" },
  { key: "export", label: "Экспорт", icon: Download, tab: "export" },
];

export function stepOf(tab: TabKey): StepKey {
  if (tab === "plan") return "variants";
  if (tab === "run") return "export";
  return tab;
}
