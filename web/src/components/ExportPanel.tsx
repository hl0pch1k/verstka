// «Файлы и детали»: every variant's deck files (PPTX, PDF, HTML) and the JSON artefacts of the run.
import type { LucideIcon } from "lucide-react";
import { ArrowUpRight, Download, FileText, Globe, Presentation } from "lucide-react";
import { api } from "../api";
import { cn, fmtSeconds, plural } from "../lib/utils";
import { useApp } from "../store";
import type { Generation, Variant } from "../types";
import { EmptyState } from "./ui/EmptyState";
import { variantScore } from "./VariantsHelpers";

interface DeckFile { name: string; label: string; hint: string; icon: LucideIcon; newTab?: boolean }

const DECK_FILES: DeckFile[] = [
  { name: "deck.pptx", label: "PowerPoint", hint: "редактируемые объекты", icon: Presentation },
  { name: "deck.pdf", label: "PDF", hint: "для печати и отправки", icon: FileText },
  { name: "deck.html", label: "Веб-версия", hint: "откроется в браузере", icon: Globe, newTab: true },
];

const JSON_FILES: Array<{ name: string; label: string }> = [
  { name: "outline.json", label: "план" },
  { name: "layout_plan.json", label: "раскладка" },
  { name: "audit_report.json", label: "проверка" },
  { name: "run_manifest.json", label: "паспорт запуска" },
];

function FileTile({ file, href }: { file: DeckFile; href: string | null }) {
  const Icon = file.icon;
  if (!href) {
    return (
      <div className="flex min-w-0 flex-1 items-center gap-3 rounded-2xl bg-zinc-50 px-4 py-3 text-zinc-400" title="Файл не сохранён для этого варианта">
        <Icon className="h-5 w-5 shrink-0" aria-hidden />
        <span className="text-[13px] font-medium">{file.label} — нет</span>
      </div>
    );
  }
  return (
    <a
      href={href}
      download={file.newTab ? undefined : file.name}
      target={file.newTab ? "_blank" : undefined}
      rel={file.newTab ? "noopener noreferrer" : undefined}
      className="group flex min-w-0 flex-1 items-center gap-3 rounded-2xl bg-zinc-100 px-4 py-3 transition-colors hover:bg-accent-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30"
    >
      <Icon className="h-5 w-5 shrink-0 text-zinc-600 transition-colors group-hover:text-accent" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold text-zinc-900">{file.label}</span>
        <span className="block truncate text-xs text-zinc-500">{file.hint}</span>
      </span>
      {file.newTab ? <ArrowUpRight className="h-4 w-4 shrink-0 text-zinc-400 group-hover:text-accent" aria-hidden /> : <Download className="h-4 w-4 shrink-0 text-zinc-400 group-hover:text-accent" aria-hidden />}
    </a>
  );
}

function VariantFiles({ g, v, index, active, title }: { g: Generation; v: Variant; index: number; active: boolean; title: string }) {
  const score = variantScore(v, g.summary?.[v.strategy]?.score);
  const summary = g.summary?.[v.strategy];
  const seconds = v.run_manifest?.timings_s.total ?? summary?.seconds ?? null;
  const slides = v.slides.length || v.outline?.slides.length || summary?.n_slides || 0;
  return (
    <section className={cn("rounded-3xl bg-white p-5 transition-shadow", active ? "shadow-[0_0_0_2px_#0077FF]" : "shadow-card")}>
      <div className="mb-4 flex items-baseline gap-3">
        <h3 className="text-[17px] font-semibold text-zinc-900">Вариант {index} · {title}</h3>
        <span className="text-[13px] text-zinc-500">
          {[slides ? plural(slides, "слайд", "слайда", "слайдов") : null, score !== null ? `качество ${Math.round(score)}/100` : null, seconds !== null ? `собран за ${fmtSeconds(seconds)}` : null].filter(Boolean).join(" · ")}
        </span>
      </div>
      <div className="flex items-stretch gap-3">
        {DECK_FILES.map((f) => <FileTile key={f.name} file={f} href={v.files[f.name] ?? null} />)}
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
        <span>Для разработчиков:</span>
        {JSON_FILES.map((f) => (
          <a key={f.name} href={api.fileUrl(g.id, v.strategy, f.name)} target="_blank" rel="noopener noreferrer" title={f.name} className="font-medium text-zinc-600 underline decoration-zinc-300 underline-offset-2 hover:text-accent-700 hover:decoration-accent">
            {f.label}
          </a>
        ))}
      </p>
    </section>
  );
}

export function ExportPanel() {
  const { generation, generationLoading, activeStrategy, strategyTitle } = useApp();
  if (generationLoading && !generation) return <div className="space-y-3" aria-busy>{[0, 1, 2].map((i) => <div key={i} className="skeleton h-40 rounded-3xl" />)}</div>;
  if (!generation || generation.variants.length === 0) return <EmptyState compact icon={Download} title="Файлов пока нет" hint="Они появятся, как только соберётся презентация." />;
  return (
    <div className="space-y-3">
      {generation.variants.map((v, i) => (
        <VariantFiles key={v.strategy} g={generation} v={v} index={i + 1} active={v.strategy === activeStrategy} title={strategyTitle(v.strategy)} />
      ))}
      <p className="px-1 text-[13px] leading-5 text-zinc-500">
        PowerPoint состоит из настоящих фигур, текстовых блоков, таблиц и диаграмм в стиле шаблона — их можно править в PowerPoint, Keynote и Google Slides.
      </p>
    </div>
  );
}
