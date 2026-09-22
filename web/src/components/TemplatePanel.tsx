// STUB — replaced by the panel owner. Contract: named export `TemplatePanel`, no props, state via useApp().
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import { LayoutTemplate } from "lucide-react";
import { EmptyState } from "./ui/EmptyState";

export function TemplatePanel() {
  return <EmptyState icon={LayoutTemplate} title="Шаблон" hint="Дизайн-правила шаблона: палитра, типографика, паттерны слайдов." />;
}
