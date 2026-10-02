// The gallery of templates on the create screen: a large card per analysed template (its cover, name, slide count and
// font, palette dots), the one chosen ringed and checked; «Слайды» on a card opens every slide of it (TemplatePreview);
// the last tile takes a template file (a click or a file dropped anywhere on the section, useTemplateDrop: .pptx,
// .potx, .ppt, .odp …). While a file is being analysed a tile with its progress stands first, where the new template
// will appear. Five templates show (the chosen one always among them), «Показать все» opens the rest. Motion: skeletons
// until the list arrives, then the cards fade up in a 40 ms cascade (once); revealed cards cascade too; a new
// template's cover fades in over its skeleton; a deleted card shrinks away and the others glide into its place.
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type DragEvent } from "react";
import { Check, ChevronDown, ChevronRight, Eye, ImageOff, Trash2, Upload } from "lucide-react";
import { api } from "../../api";
import { errText } from "../../lib/narrate";
import { EASE, MOTION, prefersReducedMotion, stagger } from "../../lib/motion";
import { templateTitle } from "../../lib/plain";
import { isTemplateFile, TEMPLATE_ACCEPT } from "../../lib/templateFiles";
import { cn, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";
import { Progress } from "../ui/Progress";
import { PaletteDots, TemplatePreview } from "./TemplatePreview";

const COLS = 3;
const SHOW = 5; // two rows of three: five templates and the upload tile

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

/** The gallery header's right side: «Разбор шаблона ›» (with a loaded template). When the drawer it opened closes, the
 *  focus comes back to it (the drawer itself does not know who opened it). */
export function TemplateActions() {
  const { templates, templateId, detail, setDetail } = useApp();
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
  if (!known) return null;
  return (
    <Button
      ref={opener}
      size="md"
      variant="ghost"
      iconRight={ChevronRight}
      onClick={() => {
        opened.current = true;
        setDetail("template");
      }}
    >
      Разбор шаблона
    </Button>
  );
}

// ---- tiles

const CARD = "relative flex w-full flex-col rounded-[20px] bg-white p-2 text-left";

function Card({ t, selected, onPick, onPreview, onDelete, fresh, leaving, className, style }: {
  t: TemplateListItem;
  selected: boolean;
  onPick(): void;
  /** «Слайды»: every slide of the template in a window. */
  onPreview(): void;
  /** The trash button: asks first (the picker's dialog). */
  onDelete(): void;
  /** A template that arrived after the gallery was shown (a file just analysed): its picture fades in over a skeleton. */
  fresh?: boolean;
  /** Deleted: the card shrinks away before it leaves the grid (the others then glide into its place). */
  leaving?: boolean;
  className?: string;
  style?: CSSProperties;
}) {
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const name = templateTitle(t.source_file, t.template_id);
  const meta = [t.n_slides !== null ? plural(t.n_slides, "слайд", "слайда", "слайдов") : "шаблон", t.font].filter(Boolean).join(" · ");
  return (
    // the preview and the trash are siblings of the card's button (a button never holds another): they show on hover
    // and on keyboard focus inside the card, always on touch screens
    <div data-tile={t.template_id} className={cn("group relative", leaving && "pointer-events-none animate-pop-out rm-fade-out", className)} style={style}>
      <button
        type="button"
        onClick={onPick}
        aria-pressed={selected}
        // the ring moves between cards in 150 ms (box-shadow through tap-soft); a press sinks the card a touch
        className={cn(CARD, "tap-soft cursor-pointer", selected ? "shadow-selected" : "shadow-card hover:shadow-raise")}
      >
        <span className={cn("relative block aspect-video w-full overflow-hidden rounded-[14px]", fresh && !loaded && !broken ? "skeleton rounded-[14px]" : "bg-zinc-100")}>
          {t.cover_url && !broken ? (
            <img
              src={t.cover_url}
              alt=""
              loading="lazy"
              draggable={false}
              onLoad={() => setLoaded(true)}
              onError={() => setBroken(true)}
              className={cn("h-full w-full object-cover transition-transform duration-600 ease-out group-hover:scale-[1.03]", fresh && (loaded ? "animate-fade" : "opacity-0"))}
            />
          ) : (
            <span className="flex h-full items-center justify-center text-zinc-400"><ImageOff className="h-6 w-6" aria-hidden /></span>
          )}
          {/* a hairline over the picture's edge: a white cover still has a shape */}
          <span className="pointer-events-none absolute inset-0 rounded-[14px] ring-1 ring-inset ring-zinc-900/[0.06]" aria-hidden />
          {selected && (
            <span className="absolute right-2.5 top-2.5 flex h-7 w-7 animate-pop items-center justify-center rounded-full bg-accent-fill text-white shadow-raise ring-2 ring-white" aria-hidden>
              <Check className="h-4 w-4" strokeWidth={2.5} />
            </span>
          )}
        </span>
        <span className="flex items-center gap-3 px-2 pb-1.5 pt-3">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-title3 font-semibold text-zinc-900" title={name}>{name}</span>
            <span className="mt-0.5 block truncate text-footnote text-zinc-500">{meta}</span>
          </span>
          <PaletteDots colors={t.palette} />
        </span>
      </button>
      {/* over the cover (the card's p-2 and the cover's 16:9): «Слайды» at its foot, the trash in its corner */}
      <div className="pointer-events-none absolute inset-x-2 top-2 aspect-video">
        <button
          type="button"
          onClick={onPreview}
          aria-label={`Слайды шаблона «${name}»`}
          className="tap pointer-events-auto absolute bottom-2.5 right-2.5 inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full bg-white/90 px-3 text-footnote font-semibold text-zinc-900 opacity-0 shadow-raise backdrop-blur hover:bg-white focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <Eye className="h-4 w-4" aria-hidden />
          Слайды
        </button>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Удалить шаблон «${name}»`}
          title="Удалить шаблон"
          className="tap pointer-events-auto absolute left-2.5 top-2.5 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full bg-white/90 text-zinc-600 opacity-0 shadow-raise backdrop-blur hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 active:bg-red-100 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <Trash2 className="h-4 w-4" aria-hidden />
        </button>
      </div>
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
  const name = templateTitle(view.source_file, view.template_id);
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

function Analysing({ name, value }: { name: string; value: number | null }) {
  return (
    <div className={cn(CARD, "shadow-card animate-fade")} aria-busy="true" aria-label={`Разбираю шаблон «${templateTitle(name)}»`}>
      <span className="skeleton block aspect-video w-full rounded-[14px]" aria-hidden />
      <span className="block min-w-0 px-2 pb-1.5 pt-3">
        <span className="block truncate text-title3 font-semibold text-zinc-900" title={name}>{templateTitle(name)}</span>
        <span className="mt-1.5 flex h-5 items-center gap-3">
          <Progress size="sm" value={value ?? 0} indeterminate={value === null} className="flex-1" />
          <span className="shrink-0 text-footnote text-zinc-500">разбираю</span>
        </span>
      </span>
    </div>
  );
}

/** The last tile: a template file by a click, or dropped anywhere on the section (the tile lights up while it is over). */
function UploadTile({ onPick, blocked, over, className, style }: { onPick(): void; blocked: boolean; over: boolean; className?: string; style?: CSSProperties }) {
  return (
    <button
      type="button"
      onClick={onPick}
      disabled={blocked}
      className={cn(
        "tap-soft group flex min-h-[240px] w-full cursor-pointer flex-col items-center justify-center gap-3 rounded-[20px] border-2 border-dashed px-6 text-center transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40",
        over ? "border-accent bg-accent-50" : "border-zinc-300 hover:border-accent-300 hover:bg-white/70",
        className,
      )}
      style={style}
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand text-white shadow-brand transition-transform duration-300 ease-spring group-hover:scale-105" aria-hidden>
        <Upload className="h-5 w-5" />
      </span>
      <span className="text-title3 font-semibold text-zinc-900">Свой шаблон</span>
      <span className="text-footnote text-zinc-500">
        .pptx, .potx, .ppt или .odp —
        <br />
        или перетащите файл сюда
      </span>
    </button>
  );
}

/** How long the first cards keep their entrance class: past the longest cascade (6 × 40 + 200 ms). */
const INTRO_MS = 800;

export function TemplatePicker() {
  const { templates, templateId, selectTemplate, forgetTemplate, healthError, strategies } = useApp();
  const { pick, blocked, job, name, over } = useTemplateUpload();
  const [all, setAll] = useState(false);
  const [preview, setPreview] = useState<TemplateListItem | null>(null);
  // deleting: the dialog's template, then the card that shrinks away before it leaves the grid
  const [asking, setAsking] = useState<TemplateListItem | null>(null);
  const [leaving, setLeaving] = useState<string | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  const flipFrom = useRef<Map<string, DOMRect> | null>(null);
  const removed = (id: string) => {
    setAsking(null);
    if (prefersReducedMotion()) return forgetTemplate(id);
    setLeaving(id);
    window.setTimeout(() => {
      // FLIP: the other cards' places before the grid closes up, so they glide into the gap
      const rects = new Map<string, DOMRect>();
      grid.current?.querySelectorAll<HTMLElement>("[data-tile]").forEach((el) => rects.set(el.dataset.tile as string, el.getBoundingClientRect()));
      flipFrom.current = rects;
      setLeaving(null);
      forgetTemplate(id);
    }, MOTION.fast + 20);
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

  // the cards of the first list cascade in once (40 ms apart); the ids seen then, so a template added later (a file
  // just analysed) fades its own picture in instead
  const intro = useRef<{ at: number; ids: Set<string> } | null>(null);
  if (!intro.current && templates.length > 0) intro.current = { at: performance.now(), ids: new Set(templates.map((t) => t.template_id)) };
  const introOn = !!intro.current && performance.now() - intro.current.at < INTRO_MS;
  // «Показать все» opens: the cards it reveals cascade in (not on the first render, not on the way back)
  const [revealAt, setRevealAt] = useState(0);

  // the order is the server's (newest first) and never changes on a click
  const list = templates;
  const analysing = !!name;
  const folded = list.length > SHOW && !all;
  // the file being analysed lands first (it is the newest): its tile stands there and the grid keeps its length
  const room = all ? list.length : SHOW - (analysing ? 1 : 0);
  let cards = list.slice(0, room);
  // a folded gallery still shows the chosen template: it takes the last visible place
  const chosen = list.find((t) => t.template_id === templateId);
  if (chosen && room > 0 && !cards.includes(chosen)) cards = [...cards.slice(0, room - 1), chosen];

  // the list has not arrived yet (templates and strategies come in one request) or cannot (no server): the grid waits
  // for it as skeletons — the upload prompt shows only when the server really has no templates
  const waiting = list.length === 0 && !analysing && (!!healthError || strategies.length === 0);
  const revealing = all && performance.now() - revealAt < INTRO_MS;
  const tileMotion = (t: TemplateListItem, i: number): { className?: string; style?: CSSProperties } => {
    if (introOn && intro.current?.ids.has(t.template_id)) return { className: "animate-fade-in", style: stagger(i) };
    if (revealing && i >= SHOW) return { className: "animate-fade-in", style: stagger(i - SHOW) };
    return {};
  };

  return (
    <div>
      {waiting ? (
        <div className="grid grid-cols-3 gap-5" aria-busy="true" aria-label="Шаблоны загружаются">
          {Array.from({ length: COLS * 2 }, (_, i) => <div key={i} className="skeleton aspect-[16/12] rounded-[20px]" />)}
        </div>
      ) : (
        <div ref={grid} className="grid grid-cols-3 gap-5">
          {analysing && <Analysing name={name} value={job ? job.progress : null} />}
          {cards.map((t, i) => (
            <Card
              key={t.template_id}
              t={t}
              selected={t.template_id === templateId}
              onPick={() => selectTemplate(t.template_id)}
              onPreview={() => setPreview(t)}
              onDelete={() => setAsking(t)}
              leaving={leaving === t.template_id}
              fresh={!!intro.current && !intro.current.ids.has(t.template_id)}
              {...tileMotion(t, i)}
            />
          ))}
          <UploadTile
            onPick={pick}
            blocked={!!blocked}
            over={over}
            className={cn(list.length === 0 && !analysing && "col-span-3 min-h-[200px]", introOn && "animate-fade-in")}
            style={introOn ? stagger(cards.length) : undefined}
          />
        </div>
      )}
      {list.length > SHOW && (
        <div className="mt-5 flex justify-center">
          <Button
            variant="white"
            shape="pill"
            iconRight={<ChevronDown className={cn("transition-transform duration-300 ease-glide", all && "rotate-180")} />}
            aria-expanded={all}
            onClick={() => {
              if (!all) setRevealAt(performance.now());
              setAll(!all);
            }}
          >
            {all || !folded ? "Свернуть" : `Показать все шаблоны (${list.length})`}
          </Button>
        </div>
      )}
      <TemplatePreview t={preview} onClose={() => setPreview(null)} />
      <DeleteTemplateDialog t={asking} onCancel={() => setAsking(null)} onDeleted={removed} />
    </div>
  );
}
