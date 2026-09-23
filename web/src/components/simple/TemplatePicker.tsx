// «① Выберите шаблон»: covers of the analysed templates to click, and one tile to add your own .pptx
// (click or drop a file anywhere on the section). While a file is being analysed the tile shows the progress.
import { useRef, useState, type DragEvent } from "react";
import { Check, ImageOff, Loader2, Plus } from "lucide-react";
import { templateName } from "../../lib/plain";
import { cn, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";

const VISIBLE = 3; // one tidy row: three covers and the «свой шаблон» tile

function Cover({ t, selected, onPick }: { t: TemplateListItem; selected: boolean; onPick(): void }) {
  const [broken, setBroken] = useState(false);
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={selected}
      className={cn(
        "group relative flex cursor-pointer flex-col overflow-hidden rounded-2xl bg-white text-left transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        selected ? "shadow-[0_0_0_3px_#0077FF]" : "shadow-card hover:-translate-y-0.5 hover:shadow-raise",
      )}
    >
      <span className="relative block w-full overflow-hidden bg-zinc-100" style={{ aspectRatio: "16 / 9" }}>
        {t.cover_url && !broken ? (
          <img src={t.cover_url} alt="" loading="lazy" draggable={false} onError={() => setBroken(true)} className="h-full w-full object-cover" />
        ) : (
          <span className="flex h-full items-center justify-center text-zinc-400"><ImageOff className="h-6 w-6" aria-hidden /></span>
        )}
        {selected && (
          <span className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-accent text-white shadow-glow" aria-hidden>
            <Check className="h-4 w-4" strokeWidth={3} />
          </span>
        )}
      </span>
      <span className="block px-3 py-2.5">
        <span className="block truncate text-[13px] font-semibold text-zinc-900">{templateName(t.source_file, t.template_id)}</span>
        <span className="block truncate text-xs text-zinc-500">{t.n_slides !== null ? plural(t.n_slides, "слайд", "слайда", "слайдов") : "шаблон"}</span>
      </span>
    </button>
  );
}

export function TemplatePicker() {
  const { templates, templateId, selectTemplate, uploadTemplate, activeJob, healthError, setDetail, manifest } = useApp();
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const analyzing = !!activeJob && activeJob.kind === "analyze" && (activeJob.status === "queued" || activeJob.status === "running");
  const blocked = busy || analyzing || healthError || (!!activeJob && (activeJob.status === "queued" || activeJob.status === "running"));

  const sorted = [...templates].sort((a, b) => b.analyzed_at - a.analyzed_at);
  // the selected template is always visible, even when the list is folded
  const shown = all ? sorted : [...sorted.filter((t) => t.template_id === templateId), ...sorted.filter((t) => t.template_id !== templateId)].slice(0, VISIBLE);

  const take = async (file: File | undefined) => {
    if (!file || blocked) return;
    setBusy(true);
    try {
      await uploadTemplate(file, false);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  const onDrop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    setOver(false);
    void take(e.dataTransfer.files?.[0]);
  };

  const uploadTile = (
    <button
      type="button"
      disabled={blocked && !analyzing}
      onClick={() => input.current?.click()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-3 text-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        over ? "border-accent bg-accent-50" : "border-zinc-300 bg-white/60 hover:border-accent hover:bg-accent-50/60",
        sorted.length === 0 ? "min-h-[180px] w-full py-10" : "min-h-full py-6",
      )}
    >
      {analyzing && activeJob ? (
        <>
          <Loader2 className="h-7 w-7 animate-spin text-accent" aria-hidden />
          <span className="text-[13px] font-semibold text-zinc-900">Разбираю шаблон… {Math.round(activeJob.progress * 100)}%</span>
          <span className="line-clamp-2 text-xs text-zinc-500">{activeJob.message}</span>
        </>
      ) : (
        <>
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent-50 text-accent">
            {busy ? <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> : <Plus className="h-5 w-5" strokeWidth={2.5} aria-hidden />}
          </span>
          <span className="text-[13px] font-semibold text-zinc-900">{sorted.length === 0 ? "Загрузите шаблон .pptx" : "Свой шаблон"}</span>
          <span className="text-xs text-zinc-500">{sorted.length === 0 ? "Нажмите или перетащите файл сюда" : "нажмите или перетащите .pptx"}</span>
        </>
      )}
    </button>
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!blocked) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <input ref={input} type="file" accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation" className="hidden" onChange={(e) => void take(e.target.files?.[0])} />
      {sorted.length === 0 ? (
        uploadTile
      ) : (
        <div className="grid grid-cols-4 gap-4">
          {shown.map((t) => (
            <Cover key={t.template_id} t={t} selected={t.template_id === templateId} onPick={() => selectTemplate(t.template_id)} />
          ))}
          {uploadTile}
        </div>
      )}
      <div className="mt-3 flex items-center gap-4 text-[13px]">
        {sorted.length > VISIBLE && (
          <button type="button" onClick={() => setAll(!all)} className="cursor-pointer font-semibold text-accent-700 hover:underline">
            {all ? "Свернуть" : `Показать все шаблоны (${sorted.length})`}
          </button>
        )}
        {manifest && (
          <button type="button" onClick={() => setDetail("template")} className="ml-auto cursor-pointer font-semibold text-accent-700 hover:underline">
            Что Verstka поняла из шаблона →
          </button>
        )}
      </div>
    </div>
  );
}
