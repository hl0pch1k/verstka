// The product flow as the main navigation: Шаблон → Бриф → Варианты → Аудит → Экспорт.
// A step is locked until its input exists (no template → no brief; no generation → no variants…).
import { Fragment } from "react";
import { Check, Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";
import { useApp } from "../../store";
import type { StepKey } from "../../types";
import { STEPS, stepOf } from "./steps";

export function Stepper() {
  const { tab, setTab, templateId, manifest, generationId, generation, activeJob, activeVariant, setShowLibrary } = useApp();
  const current = stepOf(tab);
  const building = !!activeJob && activeJob.kind === "generate" && (activeJob.status === "queued" || activeJob.status === "running");
  const analyzing = !!activeJob && activeJob.kind === "analyze" && (activeJob.status === "queued" || activeJob.status === "running");
  const hasVariants = !!generation && generation.variants.length > 0;

  const lock: Record<StepKey, string | null> = {
    template: null,
    brief: templateId ? null : "Сначала загрузите или выберите шаблон",
    variants: generationId || building ? null : "Варианты появятся после генерации",
    audit: hasVariants ? null : "Аудит появится после генерации",
    export: hasVariants ? null : "Файлы появятся после генерации",
  };
  const done: Record<StepKey, boolean> = {
    template: !!manifest,
    brief: !!generation,
    variants: hasVariants,
    audit: !!activeVariant?.audit && activeVariant.audit.summary.errors === 0,
    export: false,
  };
  const busy: Partial<Record<StepKey, boolean>> = { template: analyzing, variants: building };
  const currentIdx = STEPS.findIndex((s) => s.key === current);

  return (
    <nav aria-label="Шаги" className="flex items-center">
      {STEPS.map((s, i) => {
        const active = s.key === current;
        const locked = !!lock[s.key] && !active;
        const isDone = done[s.key] && !active;
        const isBusy = !!busy[s.key];
        return (
          <Fragment key={s.key}>
            {i > 0 && <span className={cn("mx-0.5 h-px w-3 shrink-0 min-[1600px]:mx-1 min-[1600px]:w-5", i <= currentIdx ? "bg-white/30" : "bg-white/10")} aria-hidden />}
            <button
              type="button"
              disabled={locked}
              title={lock[s.key] ?? undefined}
              aria-current={active ? "step" : undefined}
              onClick={() => {
                if (s.key === "template") setShowLibrary(false);
                setTab(s.tab);
              }}
              className={cn(
                "group flex h-10 cursor-pointer items-center gap-2 rounded-full pl-1.5 pr-3.5 text-[13px] font-semibold transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/40",
                active ? "bg-white text-zinc-900" : locked ? "cursor-not-allowed text-white/30" : "text-white/70 hover:bg-white/[0.08] hover:text-white",
              )}
            >
              <span
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums transition-colors",
                  active ? "bg-accent text-white" : isDone ? "bg-accent/90 text-white" : locked ? "bg-white/[0.06] text-white/30" : "bg-white/10 text-white/80",
                )}
                aria-hidden
              >
                {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : isDone ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : i + 1}
              </span>
              {s.label}
            </button>
          </Fragment>
        );
      })}
    </nav>
  );
}
