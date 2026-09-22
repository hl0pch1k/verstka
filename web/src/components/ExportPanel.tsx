// STUB — replaced by the panel owner. Contract: named export `ExportPanel`, no props, state via useApp().
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import { Download } from "lucide-react";
import { EmptyState } from "./ui/EmptyState";

export function ExportPanel() {
  return <EmptyState icon={Download} title="Экспорт" hint="Файлы PPTX, PDF и HTML для выбранного варианта." />;
}
