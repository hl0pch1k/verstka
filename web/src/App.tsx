import { useEffect, useMemo, useState, type ComponentType } from "react";
import { Download, FileCog, Layers, LayoutTemplate, ListTree, ShieldCheck, Sparkles, WifiOff } from "lucide-react";
import { AuditPanel } from "./components/AuditPanel";
import { Chat } from "./components/Chat";
import { ExportPanel } from "./components/ExportPanel";
import { JobBar } from "./components/JobBar";
import { NewGenerationForm } from "./components/NewGenerationForm";
import { PlanPanel } from "./components/PlanPanel";
import { RunPanel } from "./components/RunPanel";
import { TemplatePanel } from "./components/TemplatePanel";
import { TopBar } from "./components/TopBar";
import { VariantsPanel } from "./components/VariantsPanel";
import { Collapsible } from "./components/ui/Collapsible";
import { Tabs, type TabItem } from "./components/ui/Tabs";
import { Toasts } from "./components/ui/Toasts";
import { useApp } from "./store";
import type { TabKey } from "./types";

const PANELS: Record<TabKey, ComponentType> = {
  template: TemplatePanel,
  plan: PlanPanel,
  variants: VariantsPanel,
  audit: AuditPanel,
  export: ExportPanel,
  run: RunPanel,
};

export default function App() {
  const { healthError, tab, setTab, generationId, generation, activeVariant, manifest, templateId } = useApp();

  // The form is the main call to action until a generation exists; afterwards it yields the space to the results.
  const [formOpen, setFormOpen] = useState(() => !generationId);
  useEffect(() => setFormOpen(!generationId), [generationId]);

  const auditSummary = activeVariant?.audit?.summary ?? null;
  const items = useMemo<TabItem<TabKey>[]>(
    () => [
      { key: "template", label: "Шаблон", icon: LayoutTemplate },
      { key: "plan", label: "План", icon: ListTree },
      { key: "variants", label: "Варианты", icon: Layers, badge: generation?.variants.length || null },
      { key: "audit", label: "Аудит", icon: ShieldCheck, badge: auditSummary ? auditSummary.errors : null, badgeTone: auditSummary && auditSummary.errors > 0 ? "error" : "success" },
      { key: "export", label: "Экспорт", icon: Download },
      { key: "run", label: "Запуск", icon: FileCog },
    ],
    [generation, auditSummary],
  );

  const formHint = manifest ? `по шаблону «${manifest.source_file}»` : templateId ? "шаблон загружается…" : "сначала загрузите шаблон .pptx";
  const Panel = PANELS[tab];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopBar />
      <JobBar />
      {healthError && (
        <div role="alert" className="flex shrink-0 items-center gap-2.5 border-b border-red-700 bg-red-600 px-6 py-2 text-[13px] text-white">
          <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
          <span className="font-semibold">API недоступен на /api</span>
          <span className="text-red-100">
            Запустите сервер: <code className="rounded bg-red-700/60 px-1.5 py-0.5 font-mono text-xs text-white">verstka serve</code> — интерфейс переподключится сам.
          </span>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[420px] shrink-0 flex-col border-r border-zinc-200 bg-white">
          <Chat />
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <div className="shrink-0 px-6 pt-5">
            <Collapsible
              title="Новая презентация"
              hint={formHint}
              icon={Sparkles}
              open={formOpen}
              onOpenChange={setFormOpen}
              bodyClassName="scroll-thin max-h-[48vh] overflow-y-auto"
            >
              <NewGenerationForm />
            </Collapsible>
          </div>

          <div className="shrink-0 px-6 pt-2">
            <Tabs items={items} value={tab} onChange={setTab} />
          </div>

          <div key={tab} role="tabpanel" className="scroll-thin min-h-0 flex-1 overflow-y-auto px-6 py-5 animate-fade-in">
            <Panel />
          </div>
        </main>
      </div>

      <Toasts />
    </div>
  );
}
