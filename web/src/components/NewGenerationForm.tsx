// STUB — replaced by the panel owner. Contract: named export `NewGenerationForm`, no props, state via useApp().
// Rendered by App inside the body of the collapsible card «Новая презентация» (title, chevron, border and
// paddings px-5 py-4 come from App) — render the form fields only, do not wrap them in another Card.
import { Wand2 } from "lucide-react";
import { EmptyState } from "./ui/EmptyState";

export function NewGenerationForm() {
  return <EmptyState compact icon={Wand2} title="Новая презентация" hint="Бриф, аудитория, число слайдов и стратегии вёрстки." />;
}
