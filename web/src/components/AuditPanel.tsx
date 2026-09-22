// STUB — replaced by the panel owner. Contract: named export `AuditPanel`, no props, state via useApp().
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import { ShieldCheck } from "lucide-react";
import { EmptyState } from "./ui/EmptyState";

export function AuditPanel() {
  return <EmptyState icon={ShieldCheck} title="Аудит" hint="Замечания проверки качества и автоисправления." />;
}
