import { useEffect, useState, type ComponentType } from "react";
import { WifiOff } from "lucide-react";
import { AuditPanel } from "./components/AuditPanel";
import { Chat } from "./components/Chat";
import { ExportPanel } from "./components/ExportPanel";
import { NewGenerationForm } from "./components/NewGenerationForm";
import { RunPanel } from "./components/RunPanel";
import { Header } from "./components/shell/Header";
import { stepOf } from "./components/shell/steps";
import { TemplatePanel } from "./components/TemplatePanel";
import { PageHeader } from "./components/ui/PageHeader";
import { Tabs } from "./components/ui/Tabs";
import { Toasts } from "./components/ui/Toasts";
import { VariantsPanel } from "./components/VariantsPanel";
import { cn } from "./lib/utils";
import { useApp } from "./store";
import type { StepKey } from "./types";

function AuditStep() {
  return (
    <div className="space-y-6 pb-6">
      <PageHeader
        eyebrow="Шаг 4 из 5"
        title="Аудит качества"
        subtitle="Детерминированные проверки по правилам шаблона: контраст, сетка и поля, шкала кеглей, переполнение, логотипы и колонтитулы. Исправимое чинится одной кнопкой."
      />
      <AuditPanel />
    </div>
  );
}

function ExportStep() {
  const { tab, setTab, generation } = useApp();
  const run = tab === "run";
  return (
    <div className="space-y-6 pb-6">
      <PageHeader
        eyebrow="Шаг 5 из 5"
        title={run ? "Паспорт запуска" : "Готовые файлы"}
        subtitle={
          run
            ? "Воспроизводимость: версии навыков и агентов, модели, тайминги этапов, автофиксы и сравнение с другим запуском."
            : "PPTX из нативных редактируемых объектов, PDF и HTML — для каждого варианта, плюс JSON-артефакты запуска."
        }
        actions={
          generation && (
            <Tabs
              variant="pills"
              value={run ? "run" : "export"}
              onChange={(k) => setTab(k)}
              items={[
                { key: "export", label: "Файлы" },
                { key: "run", label: "Паспорт запуска" },
              ]}
            />
          )
        }
      />
      {run ? <RunPanel /> : <ExportPanel />}
    </div>
  );
}

const STEP_VIEW: Record<StepKey, ComponentType> = {
  template: TemplatePanel,
  brief: NewGenerationForm,
  variants: VariantsPanel,
  audit: AuditStep,
  export: ExportStep,
};

export default function App() {
  const { healthError, tab, agentOpen, setAgentOpen, messages } = useApp();
  const step = stepOf(tab);
  const View = STEP_VIEW[step];

  // Agent replies that arrived while the dock was closed light a counter on the «Агент» button.
  const replies = messages.filter((m) => m.role === "assistant").length;
  const [seen, setSeen] = useState(replies);
  useEffect(() => {
    if (agentOpen) setSeen(replies);
  }, [agentOpen, replies]);
  const unread = agentOpen ? 0 : Math.max(0, replies - seen);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Header unread={unread} />
      {healthError && (
        <div role="alert" className="flex shrink-0 items-center justify-center gap-2.5 bg-red-600 px-6 py-2 text-[13px] text-white">
          <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
          <span className="font-semibold">API недоступен на /api.</span>
          <span className="text-red-100">
            Запустите сервер <code className="rounded-md bg-red-700/60 px-1.5 py-0.5 font-mono text-xs text-white">verstka serve</code> — интерфейс переподключится сам.
          </span>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <main key={step} className="scroll-thin min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] px-10 py-9 animate-fade-in">
            <View />
          </div>
        </main>
        <aside aria-label="Агент Verstka" className={cn("w-[400px] shrink-0 flex-col border-l border-zinc-200/80 bg-white", agentOpen ? "flex animate-slide-in-right" : "hidden")}>
          <Chat onClose={() => setAgentOpen(false)} />
        </aside>
      </div>

      <Toasts />
    </div>
  );
}
