// «① Выберите шаблон»: the covers of the analysed templates in one stable row, «Разбор шаблона ›» and «Свой .pptx» in
// the step header (TemplateActions), and a .pptx dropped anywhere on the step (useTemplateDrop). While a file is being
// analysed a skeleton tile stands where the new template will appear. Motion: skeletons until the list arrives, then the
// covers fade up in a 40 ms cascade (once); «Ещё N» cascades the revealed covers; a new template's cover fades in over
// its skeleton when the picture has loaded.
import { useEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type DragEvent } from "react";
import { Check, ChevronRight, ImageOff, Plus, Upload } from "lucide-react";
import { stagger } from "../../lib/motion";
import { templateTitle } from "../../lib/plain";
import { cn, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";
import { Button } from "../ui/Button";
import { Progress } from "../ui/Progress";

const ROW = 4; // one row of four tiles
const PPTX_ACCEPT = ".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation";

// ---- the upload shared by the header button, the drop zone and the grid (a tiny module store: no store fields)

interface UploadState { name: string | null; over: boolean }
let upload: UploadState = { name: null, over: false };
const listeners = new Set<() => void>();
const setUpload = (patch: Partial<UploadState>) => {
  upload = { ...upload, ...patch };
  listeners.forEach((f) => f());
};
const subscribe = (f: () => void) => {
  listeners.add(f);
  return () => void listeners.delete(f);
};
const useUploadState = () => useSyncExternalStore(subscribe, () => upload);

function useTemplateUpload() {
  const { uploadTemplate, activeJob, healthError } = useApp();
  const state = useUploadState();
  const running = !!activeJob && (activeJob.status === "queued" || activeJob.status === "running");
  const job = running && activeJob.kind === "analyze" ? activeJob : null;
  const blocked = !!state.name || running || !!healthError;
  const take = async (file: File | undefined) => {
    if (!file || blocked) return;
    if (!/\.pptx$/i.test(file.name)) return void uploadTemplate(file, false); // the flow says what is wrong, no skeleton
    setUpload({ name: file.name });
    try {
      await uploadTemplate(file, false); // resolves once the analysis is over (or failed)
    } finally {
      setUpload({ name: null });
    }
  };
  const pick = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = PPTX_ACCEPT;
    input.onchange = () => void take(input.files?.[0]);
    input.click();
  };
  return { take, pick, blocked, job, name: state.name, over: state.over };
}

/** Drag-and-drop of a .pptx anywhere on the element the handlers go on (step 1). */
export function useTemplateDrop() {
  const { take, blocked } = useTemplateUpload();
  const files = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes("Files");
  return {
    onDragOver: (e: DragEvent<HTMLElement>) => {
      if (!files(e)) return;
      e.preventDefault();
      if (!blocked && !upload.over) setUpload({ over: true });
    },
    onDragLeave: (e: DragEvent<HTMLElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setUpload({ over: false });
    },
    onDrop: (e: DragEvent<HTMLElement>) => {
      if (!files(e)) return;
      e.preventDefault();
      setUpload({ over: false });
      void take(e.dataTransfer.files?.[0]);
    },
  };
}

/** The step header's right side: «Разбор шаблона ›» (with a loaded template) and «Свой .pptx». When the drawer the
 *  first one opened closes, the focus comes back to it (the drawer itself does not know who opened it). */
export function TemplateActions() {
  const { templates, templateId, detail, setDetail } = useApp();
  const { pick, blocked } = useTemplateUpload();
  const known = !!templateId && templates.some((t) => t.template_id === templateId);
  const opener = useRef<HTMLButtonElement>(null);
  const opened = useRef(false);
  useEffect(() => {
    if (detail || !opened.current) return;
    opened.current = false;
    requestAnimationFrame(() => {
      const el = opener.current;
      if (el?.isConnected && (!document.activeElement || document.activeElement === document.body)) el.focus();
    });
  }, [detail]);
  return (
    <>
      {known && (
        <Button
          ref={opener}
          size="sm"
          variant="ghost"
          iconRight={ChevronRight}
          onClick={() => {
            opened.current = true;
            setDetail("template");
          }}
        >
          Разбор шаблона
        </Button>
      )}
      <Button size="sm" variant="tonal" icon={Upload} disabled={blocked} onClick={pick}>
        Свой .pptx
      </Button>
    </>
  );
}

// ---- tiles

const TILE = "relative flex flex-col overflow-hidden rounded-xl bg-white text-left";

function Cover({ t, selected, onPick, fresh, className, style }: {
  t: TemplateListItem;
  selected: boolean;
  onPick(): void;
  /** A template that arrived after the row was shown (a file just analysed): its picture fades in over a skeleton. */
  fresh?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const name = templateTitle(t.source_file, t.template_id);
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={selected}
      // the ring moves between tiles in 150 ms (box-shadow through tap-soft); a press sinks the tile a touch
      className={cn(TILE, "tap-soft cursor-pointer", selected ? "shadow-selected" : "shadow-card hover:shadow-raise", className)}
      style={style}
    >
      <span className={cn("relative block aspect-video w-full overflow-hidden after:absolute after:inset-x-0 after:bottom-0 after:h-px after:bg-zinc-900/[0.06] after:content-['']", fresh && !loaded && !broken ? "skeleton rounded-none" : "bg-zinc-100")}>
        {t.cover_url && !broken ? (
          <img
            src={t.cover_url}
            alt=""
            loading="lazy"
            draggable={false}
            onLoad={() => setLoaded(true)}
            onError={() => setBroken(true)}
            className={cn("h-full w-full object-cover", fresh && (loaded ? "animate-fade" : "opacity-0"))}
          />
        ) : (
          <span className="flex h-full items-center justify-center text-zinc-400"><ImageOff className="h-6 w-6" aria-hidden /></span>
        )}
        {selected && (
          <span className="absolute right-2 top-2 flex h-6 w-6 animate-pop items-center justify-center rounded-full bg-accent-fill text-white ring-2 ring-white" aria-hidden>
            <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
          </span>
        )}
      </span>
      <span className="block min-w-0 px-3 py-2">
        <span className="block truncate text-footnote font-semibold text-zinc-900" title={name}>{name}</span>
        <span className="mt-0.5 block text-caption text-zinc-500">{t.n_slides !== null ? plural(t.n_slides, "слайд", "слайда", "слайдов") : "шаблон"}</span>
      </span>
    </button>
  );
}

function Analysing({ name, value }: { name: string; value: number | null }) {
  return (
    <div className={cn(TILE, "shadow-card animate-fade")} aria-busy="true" aria-label={`Разбираю шаблон «${templateTitle(name)}»`}>
      <span className="skeleton block aspect-video w-full rounded-none" aria-hidden />
      <span className="block min-w-0 px-3 py-2">
        <span className="block truncate text-footnote font-semibold text-zinc-900" title={name}>{templateTitle(name)}</span>
        <span className="mt-0.5 flex h-4 items-center">
          <Progress size="sm" value={value ?? 0} indeterminate={value === null} />
        </span>
      </span>
    </div>
  );
}

/** How long the first covers keep their entrance class: past the longest cascade (6 × 40 + 200 ms). */
const INTRO_MS = 800;

export function TemplatePicker() {
  const { templates, templateId, selectTemplate, healthError, strategies } = useApp();
  const { pick, blocked, job, name, over } = useTemplateUpload();
  const [all, setAll] = useState(false);

  // the covers of the first list cascade in once (40 ms apart); the ids seen then, so a template added later (a file
  // just analysed) fades its own picture in instead
  const intro = useRef<{ at: number; ids: Set<string> } | null>(null);
  if (!intro.current && templates.length > 0) intro.current = { at: performance.now(), ids: new Set(templates.map((t) => t.template_id)) };
  const introOn = !!intro.current && performance.now() - intro.current.at < INTRO_MS;
  // «Ещё N» opens: the covers it reveals cascade in (not on the first render, not on the way back)
  const [revealAt, setRevealAt] = useState(0);

  // the order is the server's (newest first) and never changes on a click
  const list = templates;
  const analysing = !!name;
  const folded = list.length > ROW && !all;
  // the file being analysed lands first (it is the newest): its skeleton stands there and the row keeps its length
  const room = all ? list.length : (folded ? ROW - 1 : ROW) - (analysing ? 1 : 0);
  let covers = list.slice(0, room);
  // a folded row still shows the selected template: it takes the last visible slot
  const chosen = list.find((t) => t.template_id === templateId);
  if (chosen && room > 0 && !covers.includes(chosen)) covers = [...covers.slice(0, room - 1), chosen];

  // the list has not arrived yet (templates and strategies come in one request) or cannot (no server): the row waits
  // for it as skeletons — the upload prompt shows only when the server really has no templates
  const waiting = list.length === 0 && !analysing && (!!healthError || strategies.length === 0);
  const revealing = all && performance.now() - revealAt < INTRO_MS;
  const tileMotion = (t: TemplateListItem, i: number): { className?: string; style?: CSSProperties } => {
    if (introOn && intro.current?.ids.has(t.template_id)) return { className: "animate-fade-in", style: stagger(i) };
    // the folded row shows ROW − 1 covers: the ones after them are the revealed ones
    if (revealing && i >= ROW - 1) return { className: "animate-fade-in", style: stagger(i - (ROW - 1)) };
    return {};
  };

  return (
    <div className={cn("rounded-xl transition-[outline-color] duration-150", over ? "outline-dashed outline-2 outline-offset-4 outline-accent" : "outline-none")}>
      {waiting ? (
        <div className="grid grid-cols-4 gap-4" aria-busy="true" aria-label="Шаблоны загружаются">
          {Array.from({ length: ROW }, (_, i) => <div key={i} className="skeleton aspect-[221/178] rounded-xl" />)}
        </div>
      ) : list.length === 0 && !analysing ? (
        <button
          type="button"
          disabled={!!blocked}
          onClick={pick}
          className="tap-soft flex h-44 w-full cursor-pointer flex-col items-center justify-center gap-2 rounded-xl bg-zinc-100 text-body font-semibold text-zinc-700 hover:bg-zinc-200/70 animate-fade disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Upload className="h-6 w-6 text-zinc-500" aria-hidden />
          Загрузите .pptx
        </button>
      ) : (
        <div className="grid grid-cols-4 gap-4">
          {analysing && <Analysing name={name} value={job ? job.progress : null} />}
          {covers.map((t, i) => (
            <Cover
              key={t.template_id}
              t={t}
              selected={t.template_id === templateId}
              onPick={() => selectTemplate(t.template_id)}
              fresh={!!intro.current && !intro.current.ids.has(t.template_id)}
              {...tileMotion(t, i)}
            />
          ))}
          {list.length > ROW && (
            <button
              type="button"
              onClick={() => {
                if (!all) setRevealAt(performance.now());
                setAll(!all);
              }}
              aria-expanded={all}
              className={cn("tap-soft flex min-h-full cursor-pointer flex-col items-center justify-center gap-2 rounded-xl bg-zinc-100 text-footnote font-semibold text-zinc-700 hover:bg-zinc-200/70", introOn && "animate-fade-in")}
              style={introOn ? stagger(covers.length) : undefined}
            >
              <Plus className={cn("h-5 w-5 text-zinc-500 transition-transform duration-300 ease-glide", all && "rotate-45")} aria-hidden />
              {all ? "Свернуть" : `Ещё ${list.length - covers.length}`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
