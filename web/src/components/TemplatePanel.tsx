// «Разбор шаблона» (the drawer tab «Шаблон», also opened from the create screen): the overview first — the name, three
// facts, the main font and the palette — then 6 of the layouts, up to 5 rules, and the folded «Шрифты и поля».
import { FileWarning } from "lucide-react";
import { fontStack, useTemplateFont } from "../lib/fonts";
import { templateTitle } from "../lib/plain";
import { cn, plural } from "../lib/utils";
import type { TemplateManifest } from "../types";
import { PatternGallery } from "./TemplatePanelPatterns";
import { StyleRulesCard } from "./TemplatePanelRules";
import { FontsAndMargins, PaletteRibbon, slideFormat } from "./TemplatePanelTokens";
import { EmptyState } from "./ui/EmptyState";
import { useApp } from "../store";

const TILE = "rounded-xl bg-zinc-100 px-4 py-3";

function Overview({ manifest }: { manifest: TemplateManifest }) {
  const family = manifest.tokens.typography.families[0]?.family ?? null;
  useTemplateFont(family);
  const kinds = new Set(manifest.patterns.map((p) => p.kind)).size;
  // the layouts' count is the title of the next card («Макеты 53»): three facts here, never a fourth
  const facts: Array<[string, string]> = [
    [slideFormat(manifest.slide_size).split(" · ")[0], "формат"],
    [String(manifest.n_slides), plural(manifest.n_slides, "слайд", "слайда", "слайдов").replace(/^\d+\s/, "")],
    [String(kinds), `${plural(kinds, "тип", "типа", "типов").replace(/^\d+\s/, "")} слайдов`],
  ];
  const name = templateTitle(manifest.source_file, manifest.template_id);

  return (
    <section className="rounded-2xl bg-white p-6 shadow-card">
      <h3 className="truncate text-title2 font-bold text-zinc-900" title={manifest.source_file}>{name}</h3>
      <dl className="mt-4 grid grid-cols-3 gap-3">
        {facts.map(([value, label]) => (
          <div key={label} className={cn(TILE, "flex flex-col-reverse")}>
            <dt className="text-caption text-zinc-500">{label}</dt>
            <dd className="text-title3 font-bold tabular-nums text-zinc-900">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className={cn(TILE, "flex min-w-0 items-center gap-4")}>
          <span className="text-display font-bold text-zinc-900" style={{ fontFamily: fontStack(family) }} aria-hidden>Аа</span>
          <span className="min-w-0">
            <span className="block truncate text-body font-semibold text-zinc-900" title={family ?? undefined}>{family ?? "Шрифт не определён"}</span>
            <span className="block text-caption text-zinc-500">основной шрифт</span>
          </span>
        </div>
        <div className={cn(TILE, "flex min-w-0 flex-col justify-center")}>
          <span className="mb-2 block text-caption text-zinc-500">Палитра</span>
          <PaletteRibbon manifest={manifest} className="h-6" />
        </div>
      </div>
    </section>
  );
}

export function TemplateDetails() {
  const { manifest, manifestLoading, templateId, healthError } = useApp();
  if (!templateId) return <EmptyState icon={FileWarning} title="Шаблон не выбран" hint="Выберите шаблон на первом экране" />;
  if (manifestLoading || (!manifest && !healthError)) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Загрузка шаблона">
        <div className="skeleton h-60 w-full rounded-2xl" />
        <div className="skeleton h-[424px] w-full rounded-2xl" />
      </div>
    );
  }
  if (!manifest) return <EmptyState icon={FileWarning} title="Шаблон не загрузился" hint="Повторю, когда сервер ответит" />;
  return (
    <div className="space-y-4">
      <Overview manifest={manifest} />
      <PatternGallery manifest={manifest} />
      <StyleRulesCard rules={manifest.style_rules} />
      <FontsAndMargins manifest={manifest} />
    </div>
  );
}
