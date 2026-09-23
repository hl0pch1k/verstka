// Step 1 «Шаблон»: the library (drop zone + every analysed template) or the passport of the selected template —
// what the analyser understood: palette, type, grid, rules and slide patterns.
import { useRef, useState, type DragEvent } from "react";
import { ArrowRight, Check, ExternalLink, FileWarning, ImageOff, LayoutGrid, Loader2, Plus, Sparkles, UploadCloud } from "lucide-react";
import { fontStack, useTemplateFont } from "../lib/fonts";
import { cn, fmtDate, isLightHex, plural } from "../lib/utils";
import { useApp } from "../store";
import type { TemplateListItem, TemplateManifest } from "../types";
import { PatternGallery } from "./TemplatePanelPatterns";
import { StyleRulesCard, WarningsSection } from "./TemplatePanelRules";
import { hexOf, PaletteCard, slideFormat, SpacingCard, TypographyCard } from "./TemplatePanelTokens";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { PageHeader } from "./ui/PageHeader";

const displayName = (file: string | null | undefined, fallback: string) => (file ?? fallback).replace(/\.pptx$/i, "").replace(/_/g, " ");

// ---- library --------------------------------------------------------------------------------------------------------

function DropZone() {
  const { uploadTemplate, health, healthError, activeJob } = useApp();
  const modelsConfigured = health?.models_configured ?? false;
  const [useModels, setUseModels] = useState(false);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const analyzing = !!activeJob && activeJob.kind === "analyze" && (activeJob.status === "queued" || activeJob.status === "running");
  const otherJob = !!activeJob && !analyzing && (activeJob.status === "queued" || activeJob.status === "running");
  const disabled = busy || analyzing || otherJob || healthError;

  const take = async (file: File | undefined) => {
    if (!file || disabled) return;
    setBusy(true);
    try {
      await uploadTemplate(file, useModels && modelsConfigured);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setOver(false);
    void take(e.dataTransfer.files?.[0]);
  };

  if (analyzing && activeJob) {
    return (
      <div className="relative overflow-hidden rounded-3xl bg-ink p-10 text-white">
        <div className="dot-grid-dark absolute inset-0" aria-hidden />
        <div className="relative flex items-center gap-8">
          <span className="relative flex h-20 w-20 shrink-0 items-center justify-center rounded-3xl bg-accent shadow-glow">
            <span className="absolute inset-0 rounded-3xl bg-accent animate-pulse-ring" aria-hidden />
            <Sparkles className="relative h-9 w-9" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-accent-300">Разбираю шаблон</p>
            <p className="mt-1 truncate text-2xl font-bold tracking-tight">{activeJob.label.replace(/^Анализ шаблона\s*/, "")}</p>
            <p className="mt-2 truncate text-sm text-white/60">{activeJob.message}</p>
            <div className="mt-5 flex items-center gap-4">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
                <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${Math.max(3, Math.round(activeJob.progress * 100))}%` }} />
              </div>
              <span className="w-10 text-right text-sm font-semibold tabular-nums">{Math.round(activeJob.progress * 100)}%</span>
            </div>
          </div>
        </div>
        <p className="relative mt-6 text-[13px] text-white/50">Ищу палитру и её роли, шкалу кеглей, сетку, логотипы и колонтитулы, паттерны слайдов и группы карточек.</p>
      </div>
    );
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        "dot-grid relative flex items-center gap-8 rounded-3xl border-2 border-dashed bg-white px-10 py-9 transition-colors duration-200",
        over ? "border-accent bg-accent-50" : "border-zinc-300/80",
        disabled && "opacity-70",
      )}
    >
      <input ref={input} type="file" accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation" className="hidden" onChange={(e) => void take(e.target.files?.[0])} />
      <span className={cn("flex h-20 w-20 shrink-0 items-center justify-center rounded-3xl transition-colors", over ? "bg-accent text-white" : "bg-accent-50 text-accent")}>
        {busy ? <Loader2 className="h-9 w-9 animate-spin" aria-hidden /> : <UploadCloud className="h-9 w-9" aria-hidden />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xl font-bold tracking-tight text-zinc-900">{over ? "Отпустите — начну разбор" : "Перетащите шаблон .pptx сюда"}</p>
        <p className="mt-1 text-[15px] leading-6 text-zinc-500">
          Любой фирменный шаблон, даже нарисованный от руки: разберу палитру, шрифты, сетку, логотипы и паттерны слайдов за минуту.
        </p>
        {modelsConfigured && (
          <label className="mt-3 inline-flex cursor-pointer select-none items-center gap-2 text-[13px] font-medium text-zinc-600">
            <input type="checkbox" checked={useModels} disabled={disabled} onChange={(e) => setUseModels(e.target.checked)} className="h-4 w-4 cursor-pointer rounded border-zinc-300 text-accent focus:ring-accent/30" />
            Уточнить разбор открытой моделью (дольше)
          </label>
        )}
      </div>
      <Button variant="primary" size="lg" icon={Plus} disabled={disabled} loading={busy} onClick={() => input.current?.click()}>
        Выбрать файл
      </Button>
    </div>
  );
}

function Palette({ colors, className }: { colors: string[]; className?: string }) {
  if (colors.length === 0) return null;
  return (
    <span className={cn("flex h-3 overflow-hidden rounded-full shadow-inner-line", className)} aria-label="Палитра шаблона">
      {colors.map((hex) => <span key={hex} className="h-full flex-1" style={{ background: hexOf(hex) }} title={hexOf(hex)} />)}
    </span>
  );
}

function TemplateCard({ t, current, onOpen }: { t: TemplateListItem; current: boolean; onOpen(): void }) {
  const [broken, setBroken] = useState(false);
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "group flex cursor-pointer flex-col overflow-hidden rounded-2xl bg-white text-left transition-shadow duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        current ? "shadow-[0_0_0_2px_#0077FF]" : "shadow-card hover:shadow-raise",
      )}
    >
      <span className="relative block w-full overflow-hidden bg-zinc-100" style={{ aspectRatio: String(t.aspect ?? 16 / 9) }}>
        {t.cover_url && !broken ? (
          <img src={t.cover_url} alt="" loading="lazy" decoding="async" draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
        ) : (
          <span className="flex h-full w-full items-center justify-center text-zinc-400"><ImageOff className="h-6 w-6" aria-hidden /></span>
        )}
        {current && (
          <span className="absolute right-2.5 top-2.5 inline-flex h-6 items-center gap-1 rounded-full bg-accent px-2 text-[11px] font-bold text-white shadow-glow">
            <Check className="h-3 w-3" strokeWidth={3} aria-hidden /> Выбран
          </span>
        )}
      </span>
      <span className="flex flex-1 flex-col gap-2.5 p-4">
        <span className="line-clamp-2 text-[15px] font-semibold leading-5 text-zinc-900">{displayName(t.source_file, t.template_id)}</span>
        <span className="text-[13px] text-zinc-500">
          {t.n_slides !== null ? plural(t.n_slides, "слайд", "слайда", "слайдов") : "—"} · {plural(t.n_patterns, "паттерн", "паттерна", "паттернов")}
          {t.font ? ` · ${t.font}` : ""}
        </span>
        <Palette colors={t.palette ?? []} className="mt-auto" />
      </span>
    </button>
  );
}

function Library() {
  const { templates, templateId, selectTemplate, setShowLibrary, manifest } = useApp();
  const sorted = [...templates].sort((a, b) => b.analyzed_at - a.analyzed_at);
  return (
    <div className="space-y-10">
      <PageHeader
        eyebrow="Шаг 1 из 5"
        title="Фирменный шаблон"
        subtitle="Verstka читает шаблон как свод правил: палитру с ролями цветов, шкалу кеглей, сетку, колонтитулы и паттерны слайдов. По этим правилам собирается каждая презентация."
        actions={templateId && manifest && <Button icon={ArrowRight} onClick={() => setShowLibrary(false)}>К шаблону «{displayName(manifest.source_file, "")}»</Button>}
      />
      <DropZone />
      {sorted.length > 0 && (
        <section>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-xl font-bold tracking-tight text-zinc-900">Разобранные шаблоны</h2>
            <span className="text-[13px] text-zinc-500">{plural(sorted.length, "шаблон", "шаблона", "шаблонов")} · разбор кэшируется</span>
          </div>
          <div className="grid grid-cols-3 gap-5 min-[1500px]:grid-cols-4">
            {sorted.map((t) => (
              <TemplateCard
                key={t.template_id}
                t={t}
                current={t.template_id === templateId}
                onOpen={() => {
                  selectTemplate(t.template_id);
                  setShowLibrary(false);
                }}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ---- passport -------------------------------------------------------------------------------------------------------

function Ribbon({ manifest }: { manifest: TemplateManifest }) {
  const colors = manifest.tokens.colors.slice(0, 10);
  const total = colors.reduce((s, c) => s + c.weight, 0) || 1;
  if (colors.length === 0) return null;
  return (
    <div className="flex h-14 overflow-hidden rounded-2xl shadow-inner-line" aria-label="Палитра шаблона по доле площади">
      {colors.map((c) => {
        const hex = hexOf(c.hex);
        const share = c.weight / total;
        return (
          <span
            key={c.hex}
            title={`${hex} · ${Math.round(share * 100)}%`}
            className={cn("flex min-w-[36px] items-end px-2 pb-1.5 font-mono text-[10px] font-semibold", isLightHex(hex) ? "text-zinc-900/60" : "text-white/80")}
            style={{ background: hex, flexGrow: Math.max(share, 0.04) }}
          >
            {share > 0.09 ? hex : ""}
          </span>
        );
      })}
    </div>
  );
}

function Passport({ manifest }: { manifest: TemplateManifest }) {
  const { templates, setShowLibrary, setTab } = useApp();
  const item = templates.find((t) => t.template_id === manifest.template_id);
  const family = manifest.tokens.typography.families[0]?.family ?? null;
  useTemplateFont(family);
  const cover = item?.cover_url ?? manifest.patterns[0]?.thumbnail_url ?? null;
  const [broken, setBroken] = useState(false);
  const kinds = new Set(manifest.patterns.map((p) => p.kind)).size;
  const facts: Array<[string, string]> = [
    ["Формат", slideFormat(manifest.slide_size).split(" · ")[0]],
    ["Слайдов", String(manifest.n_slides)],
    ["Паттернов", String(manifest.patterns.length)],
    ["Типов слайдов", String(kinds)],
  ];

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        eyebrow="Шаг 1 из 5 · шаблон разобран"
        title={displayName(manifest.source_file, manifest.template_id)}
        subtitle={item ? `Разобран ${fmtDate(item.analyzed_at)} · анализ v${manifest.analysis_version}` : `Анализ v${manifest.analysis_version}`}
        actions={
          <>
            <Button icon={LayoutGrid} onClick={() => setShowLibrary(true)}>Другой шаблон</Button>
            <Button variant="primary" size="lg" iconRight={ArrowRight} onClick={() => setTab("brief")}>Написать бриф</Button>
          </>
        }
      />

      <section className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-6 rounded-3xl bg-white p-6 shadow-card">
        <div className="overflow-hidden rounded-2xl bg-zinc-100 shadow-inner-line" style={{ aspectRatio: manifest.slide_size.w && manifest.slide_size.h ? `${manifest.slide_size.w} / ${manifest.slide_size.h}` : "16 / 9" }}>
          {cover && !broken ? (
            <img src={cover} alt={`Обложка шаблона ${manifest.source_file}`} className="h-full w-full object-cover" onError={() => setBroken(true)} />
          ) : (
            <div className="flex h-full items-center justify-center text-zinc-400"><ImageOff className="h-8 w-8" aria-hidden /></div>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <dl className="grid grid-cols-4 gap-3">
            {facts.map(([k, v]) => (
              <div key={k} className="rounded-2xl bg-zinc-100 px-3.5 py-3">
                <dt className="text-xs font-medium text-zinc-500">{k}</dt>
                <dd className="mt-0.5 text-xl font-bold tabular-nums tracking-tight text-zinc-900">{v}</dd>
              </div>
            ))}
          </dl>
          <div className="flex items-center gap-5 rounded-2xl bg-zinc-100 px-5 py-4">
            <span className="text-[56px] font-bold leading-none text-zinc-900" style={{ fontFamily: fontStack(family) }} aria-hidden>Аа</span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-zinc-500">Основной шрифт</p>
              <p className="truncate text-lg font-semibold text-zinc-900">{family ?? "не определён"}</p>
              <p className="truncate text-[13px] text-zinc-500">
                {manifest.tokens.typography.families.slice(1, 3).map((f) => f.family).join(", ") || "единственная гарнитура"}
                {manifest.embedded_fonts.length > 0 && ` · встроено ${plural(manifest.embedded_fonts.length, "шрифт", "шрифта", "шрифтов")}`}
              </p>
            </div>
          </div>
          <div className="rounded-2xl bg-zinc-100 p-3">
            <p className="mb-2 px-0.5 text-xs font-medium text-zinc-500">Палитра по доле площади</p>
            <Ribbon manifest={manifest} />
          </div>
          {manifest.narration && <p className="line-clamp-4 text-[13px] leading-5 text-zinc-600">{manifest.narration}</p>}
          <a href={manifest.gallery_url} target="_blank" rel="noreferrer" className="mt-auto inline-flex w-fit items-center gap-1.5 text-[13px] font-semibold text-accent-700 hover:underline">
            <ExternalLink className="h-3.5 w-3.5" aria-hidden /> Галерея всех слайдов шаблона
          </a>
        </div>
      </section>

      <PatternGallery manifest={manifest} />
      <PaletteCard manifest={manifest} />
      <div className={cn("grid gap-6", manifest.tokens.spacing ? "grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]" : "grid-cols-1")}>
        <TypographyCard manifest={manifest} />
        <SpacingCard manifest={manifest} />
      </div>
      <StyleRulesCard rules={manifest.style_rules} />
      <WarningsSection warnings={manifest.warnings} />
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Загрузка шаблона">
      <div className="skeleton h-16 w-2/3" />
      <div className="skeleton h-[360px] w-full rounded-3xl" />
      <div className="grid grid-cols-4 gap-5">{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-44 rounded-2xl" />)}</div>
    </div>
  );
}

export function TemplatePanel() {
  const { manifest, manifestLoading, templateId, healthError, showLibrary } = useApp();

  if (!templateId || showLibrary) return <Library />;
  if (manifestLoading || (!manifest && !healthError)) return <Skeleton />;
  if (!manifest) {
    return (
      <EmptyState
        icon={FileWarning}
        title="Шаблон не загрузился"
        hint="Не удалось получить разбор шаблона: API недоступен. Интерфейс повторит запрос, когда сервер вернётся."
      />
    );
  }
  return <Passport manifest={manifest} />;
}
