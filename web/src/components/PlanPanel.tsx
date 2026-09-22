// STUB — replaced by the panel owner. Contract: named export `PlanPanel`, no props, state via useApp().
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import { ListTree } from "lucide-react";
import { EmptyState } from "./ui/EmptyState";

export function PlanPanel() {
  return <EmptyState icon={ListTree} title="План" hint="Структура презентации и подбор паттерна для каждого слайда." />;
}
