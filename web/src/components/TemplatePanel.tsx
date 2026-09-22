// «Шаблон» tab: what the analyser understood about the selected template — narration, tokens, rules, patterns.
// Rendered by App inside the scrollable tab area (paddings px-6 py-5 are already applied there).
import { useRef, useState } from "react";
import { FileWarning, LayoutTemplate, MessageSquareText, Upload } from "lucide-react";
import { cn, fmtDate, plural, shortSha } from "../lib/utils";
import { useApp } from "../store";
import type { TemplateManifest } from "../types";
import { PatternGallery } from "./TemplatePanelPatterns";
import { StyleRulesCard, WarningsSection } from "./TemplatePanelRules";
import { PaletteCard, slideFormat, SpacingCard, TypographyCard } from "./TemplatePanelTokens";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card, CardBody, CardHeader, CardTitle } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";

function UploadButton() {
  const { uploadTemplate, health } = useApp();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      await uploadTemplate(file, health?.models_configured ?? true);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <>
      <input ref={input} type="file" accept=".pptx" className="hidden" onChange={(e) => void onFile(e.target.files?.[0])} />
      <Button variant="primary" icon={Upload} loading={busy} onClick={() => input.current?.click()}>Загрузить шаблон .pptx</Button>
    </>
  );
}

function NoTemplate() {
  const { templates, selectTemplate } = useApp();
  const recent = [...templates].sort((a, b) => b.analyzed_at - a.analyzed_at).slice(0, 5);
  return (
    <EmptyState
      icon={LayoutTemplate}
      title="Шаблон не выбран"
      hint="Загрузите корпоративный шаблон .pptx — Verstka разберёт его на палитру, типографику, сетку и паттерны слайдов и будет собирать презентации в этом стиле."
      action={
        <div className="flex flex-col items-center gap-3">
          <UploadButton />
          {recent.length > 0 && (
            <div className="flex flex-wrap items-center justify-center gap-1.5">
              <span className="text-xs text-zinc-500">или откройте разобранный:</span>
              {recent.map((t) => (
                <button key={t.template_id} type="button" onClick={() => selectTemplate(t.template_id)} className="rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50">
                  {t.source_file ?? shortSha(t.template_id)}
                </button>
              ))}
            </div>
          )}
        </div>
      }
    />
  );
}

function Skeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Загрузка шаблона">
      <div className="skeleton h-28 w-full" />
      <div className="grid grid-cols-4 gap-3">{Array.from({ length: 8 }, (_, i) => <div key={i} className="skeleton h-28" />)}</div>
      <div className="grid grid-cols-3 gap-5"><div className="skeleton col-span-2 h-64" /><div className="skeleton h-64" /></div>
      <div className="grid grid-cols-4 gap-4">{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-44" />)}</div>
    </div>
  );
}

const NARRATION_LIMIT = 700;

function NarrationCard({ manifest, analyzedAt }: { manifest: TemplateManifest; analyzedAt: number | undefined }) {
  const [full, setFull] = useState(false);
  const text = manifest.narration?.trim() ?? "";
  const long = text.length > NARRATION_LIMIT;
  const families = manifest.tokens.typography.families.slice(0, 2).map((f) => f.family).join(", ");
  return (
    <Card>
      <CardHeader
        actions={
          <div className="flex items-center gap-1.5">
            <Badge tone="accent">{plural(manifest.patterns.length, "паттерн", "паттерна", "паттернов")}</Badge>
            <Badge>{plural(manifest.n_slides, "слайд", "слайда", "слайдов")}</Badge>
            <Badge title="Идентификатор шаблона">{shortSha(manifest.template_id)}</Badge>
          </div>
        }
      >
        <CardTitle
          icon={MessageSquareText}
          hint={[
            slideFormat(manifest.slide_size),
            families && `шрифты ${families}`,
            manifest.embedded_fonts.length > 0 && `встроено ${plural(manifest.embedded_fonts.length, "шрифт", "шрифта", "шрифтов")}`,
            analyzedAt && `разобран ${fmtDate(analyzedAt)}`,
            `анализ v${manifest.analysis_version}`,
          ].filter(Boolean).join(" · ")}
        >
          {manifest.source_file}
        </CardTitle>
      </CardHeader>
      <CardBody>
        {text ? (
          <>
            <p className={cn("whitespace-pre-wrap text-[13px] leading-6 text-zinc-800", !full && long && "line-clamp-6")}>{text}</p>
            {long && <Button size="sm" variant="ghost" className="mt-2 -ml-2.5" onClick={() => setFull(!full)}>{full ? "Свернуть" : "Читать полностью"}</Button>}
          </>
        ) : (
          <p className="text-[13px] text-zinc-500">Описание шаблона не сформировано.</p>
        )}
      </CardBody>
    </Card>
  );
}

export function TemplatePanel() {
  const { manifest, manifestLoading, templateId, templates, healthError } = useApp();

  if (!templateId) return <NoTemplate />;
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

  const analyzedAt = templates.find((t) => t.template_id === manifest.template_id)?.analyzed_at;
  return (
    <div className="space-y-5 pb-6">
      <NarrationCard manifest={manifest} analyzedAt={analyzedAt} />
      <PaletteCard manifest={manifest} />
      <div className={cn("grid gap-5", manifest.tokens.spacing ? "grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]" : "grid-cols-1")}>
        <TypographyCard manifest={manifest} />
        <SpacingCard manifest={manifest} />
      </div>
      <StyleRulesCard rules={manifest.style_rules} />
      <PatternGallery manifest={manifest} />
      <WarningsSection warnings={manifest.warnings} />
    </div>
  );
}
