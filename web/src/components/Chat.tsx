// STUB — replaced by the panel owner. Contract: named export `Chat`, no props, state via useApp().
// Rendered by App inside the left column: <aside class="flex w-[420px] flex-col bg-white border-r"> — fill it with `flex-1 min-h-0`.
import { MessagesSquare } from "lucide-react";
import { EmptyState } from "./ui/EmptyState";

export function Chat() {
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center">
      <EmptyState icon={MessagesSquare} title="Чат" hint="Диалог с ассистентом: загрузка шаблона, бриф, правки." />
    </div>
  );
}
