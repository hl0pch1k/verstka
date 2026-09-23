// «Подробнее»: a drawer from the right with everything an expert (or a jury) wants to see, out of the way of a
// person who only needs the deck: the quality check, why a slide looks so, the plan, the template, files and runs.
import { useEffect, useRef, type ComponentType } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { slideCount } from "../../lib/narrate";
import { useApp } from "../../store";
import type { DetailKey } from "../../types";
import { AuditPanel } from "../AuditPanel";
import { ExportPanel } from "../ExportPanel";
import { PlanPanel } from "../PlanPanel";
import { RunPanel } from "../RunPanel";
import { TemplateDetails } from "../TemplatePanel";
import { Button } from "../ui/Button";
import { Tabs } from "../ui/Tabs";
import { VariantsExplain, VariantsSlideIssues } from "../VariantsExplain";
import { issuesBySlide, planEntryFor, variantRev } from "../VariantsHelpers";

function WhySlide() {
  const { generation, activeVariant, selectedSlide, setSelectedSlide, manifest, setDetail } = useApp();
  const v = activeVariant ?? generation?.variants[0];
  if (!generation || !v) return null;
  const total = slideCount(v);
  const entry = planEntryFor(v, selectedSlide);
  const pattern = manifest && manifest.template_id === generation.template_id && entry?.pattern_id ? manifest.patterns.find((p) => p.id === entry.pattern_id) ?? null : null;
  const aspect = manifest ? manifest.slide_size.w / manifest.slide_size.h : 16 / 9;
  const issues = issuesBySlide(v.audit).get(selectedSlide) ?? [];
  const headline = v.outline?.slides[selectedSlide - 1]?.headline ?? "";
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 rounded-2xl bg-white px-5 py-3 shadow-card">
        <Button icon={ChevronLeft} aria-label="Предыдущий слайд" disabled={selectedSlide <= 1} onClick={() => setSelectedSlide(selectedSlide - 1)} className="rounded-full" />
        <div className="min-w-0 flex-1 text-center">
          <p className="text-xs text-zinc-500">Слайд {selectedSlide} из {total}</p>
          <p className="truncate text-[15px] font-semibold text-zinc-900">{headline || "Без заголовка"}</p>
        </div>
        <Button icon={ChevronRight} aria-label="Следующий слайд" disabled={selectedSlide >= total} onClick={() => setSelectedSlide(selectedSlide + 1)} className="rounded-full" />
      </div>
      <VariantsExplain generationId={generation.id} strategy={v.strategy} slide={selectedSlide} rev={variantRev(v)} entry={entry} hasPlan={!!v.plan} pattern={pattern} aspect={aspect} />
      <VariantsSlideIssues issues={issues} audited={!!v.audit} highlightId={null} onHighlight={() => undefined} onOpenAudit={() => setDetail("quality")} />
    </div>
  );
}

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
  { key: "plan", label: "План", view: () => <PlanPanel embedded />, needsDeck: true },
  { key: "template", label: "Шаблон", view: TemplateDetails, needsDeck: false },
  { key: "tech", label: "Файлы и детали", view: Tech, needsDeck: true },
];

export function DetailsDrawer() {
  const { detail, setDetail, screen, generation } = useApp();
  const closeRef = useRef<HTMLButtonElement>(null);
  const hasDeck = screen === "result" && !!generation && generation.variants.length > 0;
  const tabs = TABS.filter((t) => hasDeck || !t.needsDeck);
  const current = tabs.find((t) => t.key === detail) ?? null;

  useEffect(() => {
    if (!current) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDetail(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, setDetail]);

  if (!current) return null;
  const View = current.view;
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Подробнее">
      <div className="absolute inset-0 bg-ink/40 backdrop-blur-[2px] animate-fade" onClick={() => setDetail(null)} aria-hidden />
      <div className="absolute inset-y-0 right-0 flex w-[min(920px,94vw)] flex-col bg-canvas shadow-pop animate-slide-in-right">
        <header className="flex shrink-0 items-center gap-4 bg-white px-6 py-4 shadow-[0_1px_0_rgba(0,16,61,0.06)]">
          {tabs.length > 1 ? (
            <Tabs variant="pills" value={current.key} onChange={setDetail} items={tabs.map((t) => ({ key: t.key, label: t.label }))} />
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
        <div key={current.key} className="scroll-thin min-h-0 flex-1 overflow-y-auto px-6 py-6 animate-fade-in">
          <View />
        </div>
      </div>
    </div>
  );
}
