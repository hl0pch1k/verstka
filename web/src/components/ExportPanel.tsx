// «Экспорт»: one card per variant with the deck files (PPTX / PDF / HTML) and the JSON artefacts.
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import type { LucideIcon } from "lucide-react";
import { Braces, Download, ExternalLink, FileText, Globe, PenLine, Presentation, Sparkles } from "lucide-react";
import { api } from "../api";
import { cn, fmtDate, fmtSeconds, plural, scoreTone } from "../lib/utils";
import { useApp } from "../store";
import type { Generation, Variant } from "../types";
import { Badge } from "./ui/Badge";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";

interface DeckFile { name: string; label: string; hint: string; icon: LucideIcon; newTab?: boolean }

const DECK_FILES: DeckFile[] = [
  { name: "deck.pptx", label: "PowerPoint", hint: "Нативные редактируемые объекты", icon: Presentation },
  { name: "deck.pdf", label: "PDF", hint: "Для печати и отправки", icon: FileText },
  { name: "deck.html", label: "HTML", hint: "Откроется в новой вкладке", icon: Globe, newTab: true },
];

const JSON_FILES: Array<{ name: string; label: string }> = [
  { name: "outline.json", label: "outline.json" },
  { name: "layout_plan.json", label: "layout_plan.json" },
  { name: "audit_report.json", label: "audit_report.json" },
  { name: "run_manifest.json", label: "run_manifest.json" },
];

function scoreOf(g: Generation, v: Variant): number | null {
  return v.audit?.summary.score ?? g.summary?.[v.strategy]?.score ?? null;
}

function DeckTile({ file, href }: { file: DeckFile; href: string | null }) {
  const Icon = file.icon;
  const base = "flex min-w-0 flex-1 items-center gap-3 rounded-lg border px-3.5 py-3 transition-colors";
  if (!href) {
    return (
      <div className={cn(base, "border-dashed border-zinc-200 bg-zinc-50/60 text-zinc-400")} title="Файл не экспортирован для этого варианта">
        <Icon className="h-5 w-5 shrink-0" aria-hidden />
        <span className="min-w-0">
          <span className="block text-[13px] font-medium">{file.label}</span>
          <span className="block truncate text-xs">не экспортирован</span>
        </span>
      </div>
    );
  }
  return (
    <a
      href={href}
      download={file.newTab ? undefined : file.name}
      target={file.newTab ? "_blank" : undefined}
      rel={file.newTab ? "noopener noreferrer" : undefined}
      className={cn(base, "group border-transparent bg-zinc-100 hover:bg-accent-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30")}
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600 transition-colors group-hover:bg-accent group-hover:text-white">
        <Icon className="h-[18px] w-[18px]" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-semibold text-zinc-900">{file.label}</span>
        <span className="block truncate text-xs text-zinc-500">{file.hint}</span>
      </span>
      {file.newTab ? <ExternalLink className="h-4 w-4 shrink-0 text-zinc-400 group-hover:text-accent" aria-hidden /> : <Download className="h-4 w-4 shrink-0 text-zinc-400 group-hover:text-accent" aria-hidden />}
    </a>
  );
}

function VariantCard({ g, v, active, title, description, onActivate }: {
  g: Generation; v: Variant; active: boolean; title: string; description?: string; onActivate(): void;
}) {
  const score = scoreOf(g, v);
  const summary = g.summary?.[v.strategy];
  const seconds = v.run_manifest?.timings_s.total ?? summary?.seconds ?? null;
  const slides = v.slides.length || v.outline?.slides.length || summary?.n_slides || 0;
  const errors = v.audit?.summary.errors ?? summary?.errors ?? null;
  return (
    <Card selected={active}>
      <CardHeader
        actions={
          <>
            {active ? (
              <Badge tone="accent" dot>Активный вариант</Badge>
            ) : (
              <button type="button" onClick={onActivate} className="text-xs font-medium text-zinc-500 hover:text-accent-700 hover:underline">
                Сделать активным
              </button>
            )}
            <Badge tone={scoreTone(score)} title="Оценка качества">
              {score === null ? "проверка не запускалась" : `Качество ${Math.round(score)} / 100`}
            </Badge>
          </>
        }
      >
        <CardTitle icon={Sparkles} hint={description}>{title}</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="flex items-stretch gap-3">
          {DECK_FILES.map((f) => (
            <DeckTile key={f.name} file={f} href={v.files[f.name] ?? null} />
          ))}
        </div>
        <div className="flex items-center gap-x-4 gap-y-1 text-xs text-zinc-500">
          <span className="flex items-center gap-1.5 font-medium text-zinc-600">
            <Braces className="h-3.5 w-3.5" aria-hidden />
            Артефакты
          </span>
          {JSON_FILES.map((f) => (
            <a
              key={f.name}
              href={api.fileUrl(g.id, v.strategy, f.name)}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-[11px] text-zinc-600 underline decoration-zinc-300 underline-offset-2 hover:text-accent-700 hover:decoration-accent"
            >
              {f.label}
            </a>
          ))}
          <span className="ml-auto flex items-center gap-3 tabular-nums">
            {slides > 0 && <span>{plural(slides, "слайд", "слайда", "слайдов")}</span>}
            {errors !== null && <span className={errors > 0 ? "text-red-600" : "text-emerald-600"}>{errors === 0 ? "без ошибок" : plural(errors, "ошибка", "ошибки", "ошибок")}</span>}
            {seconds !== null && <span>{fmtSeconds(seconds)}</span>}
          </span>
        </div>
      </CardBody>
    </Card>
  );
}

function Skeleton() {
  return (
    <div className="space-y-4" aria-busy>
      {[0, 1, 2].map((i) => (
        <div key={i} className="rounded-2xl bg-white p-6 shadow-card">
          <div className="skeleton h-4 w-48" />
          <div className="mt-4 flex gap-3">
            <div className="skeleton h-14 flex-1" />
            <div className="skeleton h-14 flex-1" />
            <div className="skeleton h-14 flex-1" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ExportPanel() {
  const { generationId, generation, generationLoading, activeStrategy, setActiveStrategy, strategies, strategyTitle } = useApp();

  if (!generationId) {
    return (
      <EmptyState
        icon={Download}
        title="Пока нечего экспортировать"
        hint="Сгенерируйте презентацию — для каждого варианта здесь появятся PPTX, PDF и HTML вместе с JSON-артефактами запуска."
      />
    );
  }
  if (generationLoading || !generation) return <Skeleton />;
  if (generation.variants.length === 0) {
    return (
      <EmptyState
        icon={Download}
        title="Варианты ещё не собраны"
        hint={generation.status === "running" ? "Генерация выполняется — файлы появятся, как только соберётся первый вариант." : "Ни один вариант не собрался. Подробности — во вкладке «Запуск»."}
      />
    );
  }

  const ordered = [...generation.variants].sort((a, b) => (a.strategy === activeStrategy ? -1 : b.strategy === activeStrategy ? 1 : 0));

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex items-center gap-3 text-[13px] text-zinc-600">
        <span className="font-medium text-zinc-900">Генерация от {fmtDate(generation.created_at)}</span>
        <span className="text-zinc-300" aria-hidden>·</span>
        <span className="truncate">шаблон «{generation.template_file ?? generation.template_id}»</span>
        <span className="text-zinc-300" aria-hidden>·</span>
        <span>{plural(generation.variants.length, "вариант", "варианта", "вариантов")}</span>
      </div>

      {ordered.map((v) => (
        <VariantCard
          key={v.strategy}
          g={generation}
          v={v}
          active={v.strategy === activeStrategy}
          title={strategyTitle(v.strategy)}
          description={strategies.find((s) => s.name === v.strategy)?.description}
          onActivate={() => setActiveStrategy(v.strategy)}
        />
      ))}

      <div className="flex items-start gap-3 rounded-2xl bg-accent-50/70 px-6 py-4 text-[13px] leading-5 text-zinc-700">
        <PenLine className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
        <p>
          <span className="font-medium text-zinc-800">PPTX содержит нативные редактируемые объекты.</span> Заголовки, текст, таблицы, карточки и числа — это
          настоящие фигуры и текстовые блоки в стиле шаблона, а не картинки: их можно править в PowerPoint, Keynote и Google Slides. PDF и HTML собираются из того же файла.
        </p>
      </div>
    </div>
  );
}
