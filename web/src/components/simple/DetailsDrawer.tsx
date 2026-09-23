// «Подробнее»: a drawer from the right with everything an expert (or a jury) wants to see, out of the way of a
// person who only needs the deck: the quality check, why a slide looks so, the plan, the template, files and runs.
import { useEffect, useRef, type ComponentType } from "react";
import { X } from "lucide-react";
import { usePresence } from "../../lib/motion";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import type { DetailKey } from "../../types";
import { AuditPanel } from "../AuditPanel";
import { ExportPanel } from "../ExportPanel";
import { PlanPanel } from "../PlanPanel";
import { RunPanel } from "../RunPanel";
import { TemplateDetails } from "../TemplatePanel";
import { Tabs } from "../ui/Tabs";
import { WhySlide } from "./WhySlide";

function Tech() {
  return (
    <div className="space-y-8">
      <section>
        <h3 className="mb-3 text-lg font-bold text-zinc-900">Файлы всех вариантов</h3>
        <ExportPanel />
      </section>
      <section>
        <h3 className="mb-3 text-lg font-bold text-zinc-900">Паспорт запуска</h3>
        <RunPanel />
      </section>
    </div>
  );
}

const TABS: Array<{ key: DetailKey; label: string; view: ComponentType; needsDeck: boolean }> = [
  { key: "quality", label: "Проверка качества", view: AuditPanel, needsDeck: true },
  { key: "why", label: "Почему слайд такой", view: WhySlide, needsDeck: true },
  { key: "plan", label: "План", view: PlanPanel, needsDeck: true },
  { key: "template", label: "Шаблон", view: TemplateDetails, needsDeck: false },
  { key: "tech", label: "Файлы и детали", view: Tech, needsDeck: true },
];

export function DetailsDrawer() {
  const { detail, setDetail, screen, generation } = useApp();
  const closeRef = useRef<HTMLButtonElement>(null);
  const hasDeck = screen === "result" && !!generation && generation.variants.length > 0;
  const tabs = TABS.filter((t) => hasDeck || !t.needsDeck);
  const current = tabs.find((t) => t.key === detail) ?? null;
  // the closing drawer keeps showing its last tab while it slides out
  const { mounted, leaving } = usePresence(!!current, 170);
  const last = useRef(current);
  if (current) last.current = current;
  const shown = current ?? last.current;

  useEffect(() => {
    if (!current) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDetail(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, setDetail]);

  if (!mounted || !shown) return null;
  const View = shown.view;
  return (
    <div className={cn("fixed inset-0 z-50", leaving && "pointer-events-none")} role="dialog" aria-modal="true" aria-label="Подробнее">
      <div className={cn("absolute inset-0 bg-ink/40 backdrop-blur-[2px]", leaving ? "animate-fade-out" : "animate-fade")} onClick={() => setDetail(null)} aria-hidden />
      <div className={cn("absolute inset-y-0 right-0 flex w-[min(920px,94vw)] flex-col bg-canvas shadow-pop", leaving ? "animate-slide-out-right" : "animate-slide-in-right")}>
        <header className="flex shrink-0 items-center gap-4 bg-white px-6 py-4 shadow-[0_1px_0_rgba(0,16,61,0.06)]">
          {tabs.length > 1 ? (
            <Tabs variant="pills" value={shown.key} onChange={setDetail} items={tabs.map((t) => ({ key: t.key, label: t.label }))} />
          ) : (
            <h2 className="text-lg font-bold text-zinc-900">Что Verstka поняла из шаблона</h2>
          )}
          <button
            ref={closeRef}
            type="button"
            onClick={() => setDetail(null)}
            aria-label="Закрыть"
            className="ml-auto flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full bg-zinc-100 text-zinc-600 transition-colors hover:bg-zinc-200 hover:text-zinc-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </header>
        <div key={shown.key} className="scroll-thin min-h-0 flex-1 overflow-y-auto px-6 py-6 animate-fade-in">
          <View />
        </div>
      </div>
    </div>
  );
}
