// «Что Verstka поняла из шаблона» (details drawer): the overview a person reads first — cover, format, main font,
// palette by area — then the expert sections: slide layouts with slots and votes, palette roles, type scale, grid,
// designer rules, analysis warnings.
import { useState } from "react";
import { FileWarning, ImageOff } from "lucide-react";
import { fontStack, useTemplateFont } from "../lib/fonts";
import { templateName } from "../lib/plain";
import { cn, fmtWhen, isLightHex, plural } from "../lib/utils";
import { useApp } from "../store";
import type { TemplateManifest } from "../types";
import { PatternGallery } from "./TemplatePanelPatterns";
import { StyleRulesCard, WarningsSection } from "./TemplatePanelRules";
import { hexOf, PaletteCard, slideFormat, SpacingCard, TypographyCard } from "./TemplatePanelTokens";
import { EmptyState } from "./ui/EmptyState";

function Ribbon({ manifest }: { manifest: TemplateManifest }) {
  const colors = manifest.tokens.colors.slice(0, 10);
  const total = colors.reduce((s, c) => s + c.weight, 0) || 1;
  if (colors.length === 0) return null;
  return (
    <div className="flex h-12 overflow-hidden rounded-xl shadow-inner-line" aria-label="Палитра шаблона по доле площади">
      {colors.map((c) => {
        const hex = hexOf(c.hex);
        const share = c.weight / total;
        return (
          <span
            key={c.hex}
            title={`${hex} · ${Math.round(share * 100)}%`}
            className={cn("flex min-w-[32px] items-end px-2 pb-1.5 font-mono text-[10px] font-semibold", isLightHex(hex) ? "text-zinc-900/60" : "text-white/80")}
            style={{ background: hex, flexGrow: Math.max(share, 0.04) }}
          >
            {share > 0.12 ? hex : ""}
          </span>
        );
      })}
    </div>
  );
}

function Overview({ manifest }: { manifest: TemplateManifest }) {
  const { templates } = useApp();
  const item = templates.find((t) => t.template_id === manifest.template_id);
  const family = manifest.tokens.typography.families[0]?.family ?? null;
  useTemplateFont(family);
  const cover = item?.cover_url ?? manifest.patterns[0]?.thumbnail_url ?? null;
  const [broken, setBroken] = useState(false);
  const kinds = new Set(manifest.patterns.map((p) => p.kind)).size;
  const facts: Array<[string, string]> = [
    ["Формат", slideFormat(manifest.slide_size).split(" · ")[0]],
    ["Слайдов", String(manifest.n_slides)],
    ["Макетов", String(manifest.patterns.length)],
    ["Типов слайдов", String(kinds)],
  ];

  return (
    <section className="space-y-5 rounded-3xl bg-white p-6 shadow-card">
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-5">
        <div className="overflow-hidden rounded-2xl bg-zinc-100 shadow-inner-line" style={{ aspectRatio: manifest.slide_size.w && manifest.slide_size.h ? `${manifest.slide_size.w} / ${manifest.slide_size.h}` : "16 / 9" }}>
          {cover && !broken ? (
            <img src={cover} alt={`Обложка шаблона ${manifest.source_file}`} className="h-full w-full object-cover" onError={() => setBroken(true)} />
          ) : (
            <div className="flex h-full items-center justify-center text-zinc-400"><ImageOff className="h-8 w-8" aria-hidden /></div>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-3">
          <h3 className="text-xl font-bold leading-7 tracking-tight text-zinc-900">{templateName(manifest.source_file, manifest.template_id)}</h3>
          <p className="text-[13px] text-zinc-500" title={`Версия анализа ${manifest.analysis_version}`}>{item ? `Разобран ${fmtWhen(item.analyzed_at)}` : "Шаблон разобран"}</p>
          <dl className="grid grid-cols-2 gap-2">
            {facts.map(([k, v]) => (
              <div key={k} className="rounded-xl bg-zinc-100 px-3 py-2">
                <dt className="text-xs font-medium text-zinc-500">{k}</dt>
                <dd className="text-lg font-bold tabular-nums tracking-tight text-zinc-900">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-5">
        <div className="flex items-center gap-4 rounded-2xl bg-zinc-100 px-4 py-3">
          <span className="text-[44px] font-bold leading-none text-zinc-900" style={{ fontFamily: fontStack(family) }} aria-hidden>Аа</span>
          <div className="min-w-0">
            <p className="text-xs font-medium text-zinc-500">Основной шрифт</p>
            <p className="truncate text-base font-semibold text-zinc-900">{family ?? "не определён"}</p>
            <p className="truncate text-xs text-zinc-500">
              {manifest.tokens.typography.families.slice(1, 3).map((f) => f.family).join(", ") || "единственный шрифт"}
              {manifest.embedded_fonts.length > 0 && ` · встроено ${plural(manifest.embedded_fonts.length, "шрифт", "шрифта", "шрифтов")}`}
            </p>
          </div>
        </div>
        <div className="rounded-2xl bg-zinc-100 p-3">
          <p className="mb-2 px-0.5 text-xs font-medium text-zinc-500">Цвета по доле площади</p>
          <Ribbon manifest={manifest} />
        </div>
      </div>
    </section>
  );
}

export function TemplateDetails() {
  const { manifest, manifestLoading, templateId, healthError } = useApp();
  if (!templateId) return <EmptyState icon={FileWarning} title="Шаблон не выбран" hint="Выберите или загрузите шаблон на первом экране." />;
  if (manifestLoading || (!manifest && !healthError)) {
    return (
      <div className="space-y-5" aria-busy="true" aria-label="Загрузка шаблона">
        <div className="skeleton h-[300px] w-full rounded-3xl" />
        <div className="skeleton h-64 w-full rounded-3xl" />
      </div>
    );
  }
  if (!manifest) return <EmptyState icon={FileWarning} title="Шаблон не загрузился" hint="Сервер недоступен — интерфейс повторит запрос, когда он вернётся." />;
  return (
    <div className="space-y-6">
      <Overview manifest={manifest} />
      <PatternGallery manifest={manifest} />
      <PaletteCard manifest={manifest} />
      <TypographyCard manifest={manifest} />
      <SpacingCard manifest={manifest} />
      <StyleRulesCard rules={manifest.style_rules} />
      <WarningsSection warnings={manifest.warnings} />
    </div>
  );
}
