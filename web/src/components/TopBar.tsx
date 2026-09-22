// Top bar: brand, template selector + upload, recent generations, model status and version.
// Rendered by App as the first row of the full-height column: fixed height h-14, shrink-0.
import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { ChevronDown, LayoutTemplate, Upload } from "lucide-react";
import { cn, plural } from "../lib/utils";
import { useApp } from "../store";
import type { TemplateListItem } from "../types";
import { TopBarGenerations } from "./TopBarGenerations";
import { Badge, type BadgeTone } from "./ui/Badge";
import { Button } from "./ui/Button";

function templateLabel(t: TemplateListItem): string {
  const name = t.source_file ?? t.template_id.slice(0, 12);
  const parts = [name];
  if (t.n_slides !== null) parts.push(plural(t.n_slides, "слайд", "слайда", "слайдов"));
  parts.push(plural(t.n_patterns, "паттерн", "паттерна", "паттернов"));
  return parts.join(" · ");
}

function Logo() {
  return (
    <div className="flex shrink-0 items-center gap-3">
      <span className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg bg-accent text-white shadow-sm" aria-hidden>
        <svg viewBox="0 0 32 32" className="h-8 w-8" fill="none">
          <rect x="6" y="7" width="20" height="4" rx="1.2" fill="white" fillOpacity="0.95" />
          <rect x="6" y="14" width="12" height="4" rx="1.2" fill="white" fillOpacity="0.75" />
          <rect x="6" y="21" width="16" height="4" rx="1.2" fill="white" fillOpacity="0.55" />
        </svg>
      </span>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-zinc-900">Verstka</div>
        <div className="text-[11px] text-zinc-500">Цифровой дизайнер презентаций</div>
      </div>
    </div>
  );
}

export function TopBar() {
  const { health, healthError, templates, templateId, selectTemplate, uploadTemplate, generations, generationId, loadGeneration, tab, setTab, activeJob } = useApp();
  const modelsConfigured = health?.models_configured ?? false;

  const [useModels, setUseModels] = useState(modelsConfigured);
  const touched = useRef(false);
  useEffect(() => {
    if (!touched.current) setUseModels(modelsConfigured);
  }, [modelsConfigured]);

  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      await uploadTemplate(file, useModels);
    } finally {
      setUploading(false);
    }
  };

  const openGeneration = async (id: string) => {
    await loadGeneration(id);
    if (tab === "template") setTab("variants");
  };

  const jobRunning = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const sorted = [...templates].sort((a, b) => b.analyzed_at - a.analyzed_at);

  const status: { label: string; tone: BadgeTone } = healthError
    ? { label: "API недоступен", tone: "error" }
    : !health
      ? { label: "Подключение…", tone: "neutral" }
      : modelsConfigured
        ? { label: "Модели: OpenRouter", tone: "success" }
        : { label: "Модели: офлайн-режим", tone: "warn" };

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-zinc-200 bg-white px-6">
      <Logo />
      <span className="mx-1 h-6 w-px bg-zinc-200" aria-hidden />

      {/* Template selector */}
      <div className="relative flex min-w-0 items-center">
        <LayoutTemplate className="pointer-events-none absolute left-3 h-4 w-4 text-zinc-500" aria-hidden />
        <select
          aria-label="Шаблон"
          value={templateId ?? ""}
          disabled={sorted.length === 0}
          onChange={(e) => selectTemplate(e.target.value || null)}
          title={sorted.find((t) => t.template_id === templateId)?.source_file ?? undefined}
          className={cn(
            "h-9 w-[360px] appearance-none truncate rounded-lg border border-zinc-200 bg-white pl-9 pr-9 text-[13px] font-medium text-zinc-800 shadow-sm transition-colors",
            "hover:border-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/30 disabled:cursor-not-allowed disabled:text-zinc-400",
          )}
        >
          {sorted.length === 0 ? (
            <option value="">Шаблонов нет — загрузите .pptx</option>
          ) : (
            <>
              {!templateId && <option value="">Выберите шаблон…</option>}
              {sorted.map((t) => (
                <option key={t.template_id} value={t.template_id}>
                  {templateLabel(t)}
                </option>
              ))}
            </>
          )}
        </select>
        <ChevronDown className="pointer-events-none absolute right-3 h-3.5 w-3.5 text-zinc-400" aria-hidden />
      </div>

      {/* Upload */}
      <div className="flex shrink-0 items-center gap-3">
        <input ref={fileRef} type="file" accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation" className="hidden" onChange={(e) => void onFile(e)} />
        <Button variant="primary" icon={Upload} loading={uploading} disabled={jobRunning || healthError} onClick={() => fileRef.current?.click()}>
          Загрузить шаблон
        </Button>
        <label
          className={cn("flex cursor-pointer select-none items-center gap-1.5 text-xs text-zinc-600", !modelsConfigured && "cursor-not-allowed text-zinc-400")}
          title={modelsConfigured ? "Классификация паттернов с помощью LLM/VLM" : "Модели не настроены: шаблон разбирается эвристиками"}
        >
          <input
            type="checkbox"
            className="h-3.5 w-3.5 rounded border-zinc-300 text-accent focus:ring-accent/30"
            checked={useModels && modelsConfigured}
            disabled={!modelsConfigured || uploading}
            onChange={(e) => {
              touched.current = true;
              setUseModels(e.target.checked);
            }}
          />
          с моделями
        </label>
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-3">
        <TopBarGenerations generations={generations} currentId={generationId} onSelect={openGeneration} />
        <Badge tone={status.tone} dot>
          {status.label}
        </Badge>
        {health && (
          <span className="font-mono text-xs text-zinc-400" title={`workspace: ${health.workspace}`}>
            v{health.version}
          </span>
        )}
      </div>
    </header>
  );
}
