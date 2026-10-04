// Step 1 of the create screen, the template: the four latest analysed templates as covers in a row (the chosen one
// ringed and checked, always among them) and a tile that opens every template in a window; «Слайды» on a cover shows
// every slide of that template (TemplatePreview: there it can be chosen, read in detail or deleted). A template file is
// taken by «Загрузить свой» or dropped anywhere on the step (useTemplateDrop: .pptx, .potx, .ppt, .odp …); while it is
// analysed, a card with its progress stands first, where the new template will appear. Motion is kept to what
// explains a change: the ring moves to the chosen cover, a new template's picture fades in over its skeleton, a
// deleted card leaves and the others close the gap.
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type DragEvent } from "react";
import { Check, Eye, ImageOff, LayoutGrid, Trash2, Upload } from "lucide-react";
import { api } from "../../api";
import { errText } from "../../lib/narrate";
import { EASE, MOTION, prefersReducedMotion } from "../../lib/motion";
import { templateTitle, tplLabel } from "../../lib/plain";
import { isTemplateFile, TEMPLATE_ACCEPT } from "../../lib/templateFiles";
import { cn, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { Progress } from "../ui/Progress";
import { TemplatePreview } from "./TemplatePreview";

/** Covers in the step's row (a fifth place holds «Все шаблоны»). */
const ROW = 4;

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
    if (!isTemplateFile(file.name)) return void uploadTemplate(file, false); // the flow says what is wrong, no skeleton
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
    input.accept = TEMPLATE_ACCEPT;
    input.onchange = () => void take(input.files?.[0]);
    input.click();
  };
  return { take, pick, blocked, job, name: state.name, over: state.over };
}

/** Drag-and-drop of a template file anywhere on the element the handlers go on (step 1). */
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

/** The step's header action: a template file from the disk. */
export function TemplateUploadButton() {
  const { pick, blocked } = useTemplateUpload();
  return (
    <Button size="sm" variant="ghost" icon={Upload} disabled={blocked} onClick={pick}>
      Загрузить свой
    </Button>
  );
}

const meta = (t: TemplateListItem) => [t.n_slides !== null ? plural(t.n_slides, "слайд", "слайда", "слайдов") : "шаблон", t.font].filter(Boolean).join(", ");

function Cover({ t, selected, onPick, onPreview, fresh }: {
  t: TemplateListItem;
  selected: boolean;
  onPick(): void;
  /** «Слайды»: every slide of the template in a window. */
  onPreview(): void;
  /** A template that arrived after the step was shown (a file just analysed): its picture fades in over a skeleton. */
  fresh?: boolean;
}) {
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const name = tplLabel(t);
  return (
    // «Слайды» is a sibling of the cover's button (a button never holds another); it shows while the pointer is over the
    // card or the focus is inside it, always on touch screens
    <div data-tile={t.template_id} className="group relative min-w-0">
      <button type="button" onClick={onPick} aria-pressed={selected} className="tap-soft block w-full cursor-pointer text-left">
        <span
          className={cn(
            "relative block aspect-video overflow-hidden rounded-xl bg-zinc-100 transition-shadow duration-150",
            selected ? "shadow-selected" : "shadow-inner-line group-hover:shadow-selected-hover",
            fresh && !loaded && !broken && "skeleton",
          )}
        >
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
        <span className="mt-2.5 block truncate text-body font-medium text-zinc-900" title={name}>{name}</span>
        <span className="mt-0.5 block truncate text-footnote text-zinc-500">{meta(t)}</span>
      </button>
      {/* a layer of the cover's own box over it: «Слайды» sits in the cover's corner */}
      <div className="pointer-events-none absolute inset-x-0 top-0 aspect-video">
        <button
          type="button"
          onClick={onPreview}
          aria-label={`Слайды шаблона «${name}»`}
          className="tap pointer-events-auto absolute bottom-2 right-2 inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-lg bg-white px-2 text-footnote font-medium text-zinc-900 opacity-0 shadow-raise hover:bg-zinc-50 focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <Eye className="h-3.5 w-3.5" aria-hidden />
          Слайды
        </button>
      </div>
    </div>
  );
}

function Analysing({ name, value }: { name: string; value: number | null }) {
  return (
    <div className="min-w-0 animate-fade" aria-busy="true" aria-label={`Разбираю шаблон «${templateTitle(name)}»`}>
      <span className="skeleton block aspect-video w-full rounded-xl" aria-hidden />
      <span className="mt-2.5 block truncate text-body font-medium text-zinc-900" title={name}>{templateTitle(name)}</span>
      <span className="mt-1.5 flex h-4 items-center gap-2">
        <Progress size="sm" value={value ?? 0} indeterminate={value === null} className="flex-1" />
        <span className="shrink-0 text-footnote text-zinc-500">разбираю…</span>
      </span>
    </div>
  );
}

/** A template file by a click (in the row when there are few templates, first in the window). */
function UploadTile({ onPick, blocked, className }: { onPick(): void; blocked: boolean; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <button
        type="button"
        onClick={onPick}
        disabled={blocked}
        className="tap-soft flex aspect-video w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed border-zinc-300 bg-white/60 text-center hover:border-accent-300 hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Upload className="h-5 w-5 text-accent" aria-hidden />
        <span className="text-footnote font-medium text-zinc-900">Загрузить свой</span>
      </button>
      <span className="mt-2.5 block text-footnote text-zinc-500">.pptx, .potx, .ppt или .odp</span>
    </div>
  );
}

/** «Удалить шаблон?»: the tile's cover and name, one line on what stays, «Отмена» and a red «Удалить». While the
 *  request runs the dialog stays (not dismissible) and the button spins; a failure says why in the dialog. */
function DeleteTemplateDialog({ t, onCancel, onDeleted }: { t: TemplateListItem | null; onCancel(): void; onDeleted(id: string): void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shown = useRef<TemplateListItem | null>(t);
  if (t) shown.current = t;
  const view = shown.current;
  useEffect(() => {
    if (t) {
      setBusy(false);
      setError(null);
    }
  }, [t]);
  if (!view) return null;
  const name = tplLabel(view);
  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteTemplate(view.template_id);
      onDeleted(view.template_id);
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  };
  return (
    <Modal
      open={!!t}
      onClose={onCancel}
      dismissible={!busy}
      size="sm"
      title="Удалить шаблон?"
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>Отмена</Button>
          <Button variant="danger" icon={Trash2} loading={busy} onClick={() => void confirm()}>Удалить</Button>
        </>
      }
    >
      <div className="flex items-center gap-4">
        <span className="block aspect-video w-28 shrink-0 overflow-hidden rounded-lg bg-zinc-100 shadow-card">
          {view.cover_url ? <img src={view.cover_url} alt="" className="h-full w-full object-cover" draggable={false} /> : null}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-body font-semibold text-zinc-900" title={name}>{name}</span>
          <span className="mt-0.5 block text-footnote text-zinc-500">{view.n_slides !== null ? plural(view.n_slides, "слайд", "слайда", "слайдов") : "шаблон"}</span>
        </span>
      </div>
      <p className="mt-4 text-footnote text-zinc-500">Уже собранные презентации останутся.</p>
      {error && <p role="alert" className="mt-3 text-footnote text-red-600">{error}</p>}
    </Modal>
  );
}


export function TemplatePicker() {
  const { templates, templateId, selectTemplate, forgetTemplate, healthError, strategies } = useApp();
  const { pick, blocked, job, name, over } = useTemplateUpload();
  const [gallery, setGallery] = useState(false);
  const [preview, setPreview] = useState<TemplateListItem | null>(null);
  // deleting: the dialog's template, then the list closes up (the others glide into the gap)
  const [asking, setAsking] = useState<TemplateListItem | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  const flipFrom = useRef<Map<string, DOMRect> | null>(null);
  const removed = (id: string) => {
    setAsking(null);
    setPreview(null);
    if (prefersReducedMotion()) return forgetTemplate(id);
    const rects = new Map<string, DOMRect>();
    grid.current?.querySelectorAll<HTMLElement>("[data-tile]").forEach((el) => rects.set(el.dataset.tile as string, el.getBoundingClientRect()));
    flipFrom.current = rects;
    forgetTemplate(id);
  };
  useLayoutEffect(() => {
    const was = flipFrom.current;
    if (!was || !grid.current) return;
    flipFrom.current = null;
    grid.current.querySelectorAll<HTMLElement>("[data-tile]").forEach((el) => {
      const from = was.get(el.dataset.tile as string);
      if (!from) return;
      const now = el.getBoundingClientRect();
      const dx = from.left - now.left;
      const dy = from.top - now.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
      el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: MOTION.slow, easing: EASE.glide });
    });
  }, [templates]);

  // the ids of the first list: a template added later (a file just analysed) fades its own picture in
  const intro = useRef<Set<string> | null>(null);
  if (!intro.current && templates.length > 0) intro.current = new Set(templates.map((t) => t.template_id));
  useEffect(() => {
    if (!preview) return;
    // the window follows the list (a deleted template closes it)
    if (!templates.some((t) => t.template_id === preview.template_id)) setPreview(null);
  }, [templates, preview]);

  // the order is the server's (newest first) and never changes on a click; the chosen template keeps a place in the row
  const list = templates;
  const analysing = !!name;
  const room = ROW - (analysing ? 1 : 0);
  let row = list.slice(0, room);
  const chosen = list.find((t) => t.template_id === templateId);
  if (chosen && room > 0 && !row.includes(chosen)) row = [...row.slice(0, room - 1), chosen];
  const more = list.length - row.length;
  // the list has not arrived yet (templates and strategies come in one request) or cannot (no server)
  const waiting = list.length === 0 && !analysing && (!!healthError || strategies.length === 0);
  const fresh = (t: TemplateListItem) => !!intro.current && !intro.current.has(t.template_id);

  return (
    <div className={cn("relative rounded-xl transition-[outline-color] duration-150", over ? "outline-dashed outline-2 outline-offset-8 outline-accent" : "outline-none")}>
      {waiting ? (
        <div className="grid grid-cols-5 gap-5" aria-busy="true" aria-label="Шаблоны загружаются">
          {Array.from({ length: ROW + 1 }, (_, i) => (
            <div key={i}>
              <div className="skeleton aspect-video rounded-xl" />
              <div className="skeleton mt-3 h-4 w-3/4 rounded" />
              <div className="skeleton mt-2 h-3 w-1/2 rounded" />
            </div>
          ))}
        </div>
      ) : (
        <div ref={grid} className="grid grid-cols-5 gap-5">
          {analysing && <Analysing name={name} value={job ? job.progress : null} />}
          {row.map((t) => (
            <Cover key={t.template_id} t={t} selected={t.template_id === templateId} onPick={() => selectTemplate(t.template_id)} onPreview={() => setPreview(t)} fresh={fresh(t)} />
          ))}
          {more > 0 ? (
            <div className="min-w-0">
              <button
                type="button"
                onClick={() => setGallery(true)}
                className="tap-soft flex aspect-video w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl bg-zinc-100 text-center hover:bg-zinc-200/70"
              >
                <LayoutGrid className="h-5 w-5 text-zinc-500" aria-hidden />
                <span className="text-footnote font-medium text-zinc-900">Все шаблоны</span>
              </button>
              <span className="mt-2.5 block text-footnote text-zinc-500">ещё {plural(more, "шаблон", "шаблона", "шаблонов")}</span>
            </div>
          ) : (
            Array.from({ length: Math.max(1, ROW + 1 - row.length - (analysing ? 1 : 0)) }, (_, i) => (i === 0 ? <UploadTile key="up" onPick={pick} blocked={!!blocked} /> : <span key={i} aria-hidden />))
          )}
        </div>
      )}
      {/* a file over the step: where it will go */}
      {over && (
        <div className="pointer-events-none absolute inset-0 flex animate-fade items-center justify-center rounded-xl bg-accent-50/90" aria-hidden>
          <span className="inline-flex items-center gap-2 text-body font-medium text-accent-700">
            <Upload className="h-5 w-5" />
            Отпустите файл — разберу шаблон
          </span>
        </div>
      )}
      <Modal
        open={gallery}
        onClose={() => setGallery(false)}
        size="xl"
        title="Шаблоны"
        description={`${plural(list.length, "шаблон", "шаблона", "шаблонов")}. Выберите оформление или загрузите своё.`}
      >
        <div className="grid grid-cols-4 gap-x-5 gap-y-6 pb-2 pt-2">
          <UploadTile
            onPick={() => {
              setGallery(false);
              pick();
            }}
            blocked={!!blocked}
          />
          {list.map((t) => (
            <Cover
              key={t.template_id}
              t={t}
              selected={t.template_id === templateId}
              onPick={() => {
                selectTemplate(t.template_id);
                setGallery(false);
              }}
              onPreview={() => setPreview(t)}
            />
          ))}
        </div>
      </Modal>
      <TemplatePreview t={preview} onClose={() => setPreview(null)} onDelete={(t) => setAsking(t)} />
      <DeleteTemplateDialog t={asking} onCancel={() => setAsking(null)} onDeleted={removed} />
    </div>
  );
}
