// STUB — replaced by the panel owner. Contract: named export `RunPanel`, no props, state via useApp().
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import { FileCog } from "lucide-react";
import { EmptyState } from "./ui/EmptyState";

export function RunPanel() {
  return <EmptyState icon={FileCog} title="Запуск" hint="Манифест запуска: версии навыков, модели, тайминги, сравнение запусков." />;
}
