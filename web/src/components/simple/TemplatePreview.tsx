// A template, every slide of it: a cover's «Слайды» opens this window. The name (the pencil renames it), the slide
// count, the font and the palette on top; the slides as a grid of thumbnails (the analysis renders one per slide, they
// load as they scroll in); «Удалить» on the left of the footer (it asks first), «Подробный разбор» (the drawer's
// template tab) and «Выбрать шаблон» on the right.
import { useLayoutEffect, useRef, useState } from "react";
import { Check, ImageOff, Pencil, ScanSearch, Trash2 } from "lucide-react";
import { errText } from "../../lib/narrate";
import { templateTitle, tplLabel } from "../../lib/plain";
import { cn, isLightHex, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const thumbUrl = (id: string, n: number) => `/api/templates/${encodeURIComponent(id)}/files/thumbs/slide-${String(n).padStart(3, "0")}.jpg`;

const rgb = (hex: string) => [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
/** Two colours a person would not tell apart in a 12px dot («FAFCFF» and «FFFFFF»). */
const near = (a: string, b: string) => rgb(a).reduce((sum, v, i) => sum + Math.abs(v - rgb(b)[i]), 0) < 36;

/** The template's colours as a row of dots, near-duplicates dropped; every dot keeps a hairline, so white reads on
 *  white and black on a dark cover. */
export function PaletteDots({ colors, max = 5, size = 12, className }: { colors?: string[]; max?: number; size?: number; className?: string }) {
  const list: string[] = [];
  for (const c of colors ?? []) if (/^[0-9a-f]{6}$/i.test(c) && !list.some((x) => near(x, c))) list.push(c);
  if (list.length === 0) return null;
  return (
    <span className={cn("flex shrink-0 items-center gap-1", className)} aria-hidden>
      {list.slice(0, max).map((c) => (
        <span
          key={c}
          className={cn("block rounded-full", isLightHex(c) ? "shadow-[inset_0_0_0_1px_rgba(16,24,40,0.18)]" : "shadow-[inset_0_0_0_1px_rgba(255,255,255,0.12)]")}
          style={{ width: size, height: size, background: `#${c}` }}
        />
      ))}
    </span>
  );
}

function Thumb({ id, n, aspect }: { id: string; n: number; aspect: number }) {
  const [broken, setBroken] = useState(false);
  const [loaded, setLoaded] = useState(false);
  return (
    <figure>
      <span className="relative block overflow-hidden rounded-xl bg-zinc-100 ring-1 ring-zinc-900/[0.06]" style={{ aspectRatio: String(aspect) }}>
        {broken ? (
          <span className="flex h-full items-center justify-center text-zinc-400"><ImageOff className="h-5 w-5" aria-hidden /></span>
        ) : (
          <img
            src={thumbUrl(id, n)}
            alt={`Слайд ${n} шаблона`}
            loading="lazy"
            decoding="async"
            draggable={false}
            onLoad={() => setLoaded(true)}
            onError={() => setBroken(true)}
            className={cn("h-full w-full object-cover transition-opacity duration-300", loaded ? "opacity-100" : "opacity-0")}
          />
        )}
      </span>
      {/* the number under the slide, never over its own corner (a logo, a page number) */}
      <figcaption className="mt-1.5 text-caption font-medium tabular-nums text-zinc-500">{n}</figcaption>
    </figure>
  );
}

/** The template's name in the window's title, with a pencil: it turns into a field (Enter or leaving it saves, Esc puts
 *  the name back); an empty field brings back the file's name, which the field shows as its placeholder. */
function TemplateName({ t }: { t: TemplateListItem }) {
  const { renameTemplate, toast } = useApp();
  const name = tplLabel(t);
  const fileName = templateTitle(t.source_file, t.template_id);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const [busy, setBusy] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const pencil = useRef<HTMLButtonElement>(null);
  // the field takes the focus when it opens; when it closes (saved or not) the focus goes back to the pencil, never to
  // the page behind the window
  const wasEditing = useRef(false);
  useLayoutEffect(() => {
    if (editing) {
      wasEditing.current = true;
      field.current?.focus();
      field.current?.select();
    } else if (wasEditing.current) {
      wasEditing.current = false;
      pencil.current?.focus();
    }
  }, [editing]);
  const save = async () => {
    if (busy) return;
    const next = value.trim().replace(/\s+/g, " ");
    if (next === name || (!next && !t.title)) return setEditing(false);
    setBusy(true);
    try {
      await renameTemplate(t.template_id, next === fileName ? "" : next);
      setEditing(false);
    } catch (e) {
      toast("error", `Не удалось переименовать шаблон: ${errText(e)}`);
      field.current?.focus();
    } finally {
      setBusy(false);
    }
  };
  if (editing) {
    return (
      <input
        ref={field}
        data-own-escape
        value={value}
        maxLength={80}
        disabled={busy}
        aria-label="Название шаблона"
        placeholder={fileName}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void save();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setEditing(false);
          }
        }}
        // as wide as the name (a field across the whole title bar reads as a form), 36px tall on the title's 28px line
        style={{ width: `${Math.min(36, Math.max(12, value.length + 3))}ch` }}
        className="-my-1 -ml-2.5 h-9 min-w-0 max-w-full rounded-lg border border-accent bg-white px-2 text-title2 font-semibold text-zinc-900 shadow-[0_0_0_3px_rgba(0,119,255,0.12)] outline-none placeholder:font-normal placeholder:text-zinc-500 disabled:opacity-60"
      />
    );
  }
  return (
    <>
      <span className="min-w-0 truncate" title={t.title ? `Файл: ${t.source_file ?? fileName}` : undefined}>{name}</span>
      <Button
        ref={pencil}
        variant="ghost"
        size="sm"
        shape="circle"
        icon={Pencil}
        aria-label="Переименовать шаблон"
        title="Переименовать"
        onClick={() => {
          setValue(name);
          setEditing(true);
        }}
        // -my-1: the 32px button sits on the title's 28px line, so the field and the name keep the same height
        className="-my-1 -ml-1.5 shrink-0 text-zinc-500"
      />
    </>
  );
}

export function TemplatePreview({ t, onClose, onDelete }: { t: TemplateListItem | null; onClose(): void; /** «Удалить»: the caller asks first. */ onDelete?(t: TemplateListItem): void }) {
  const { templateId, selectTemplate, setDetail, templates } = useApp();
  // the window keeps its template while it closes; while open it follows the library (a new name shows at once)
  const shown = useRef<TemplateListItem | null>(t);
  if (t) shown.current = templates.find((x) => x.template_id === t.template_id) ?? t;
  const view = shown.current;
  if (!view) return null;
  const n = Math.max(0, view.n_slides ?? 0);
  const aspect = view.aspect && view.aspect > 0 ? view.aspect : 16 / 9;
  const selected = view.template_id === templateId;
  const meta = [n ? plural(n, "слайд", "слайда", "слайдов") : null, view.font ? `шрифт ${view.font}` : null].filter(Boolean).join(", ");
  const choose = () => {
    selectTemplate(view.template_id);
    onClose();
  };
  return (
    <Modal
      open={!!t}
      onClose={onClose}
      size="xl"
      title={
        <span className="flex min-w-0 items-center gap-3">
          <TemplateName key={view.template_id} t={view} />
          <PaletteDots colors={view.palette} max={6} size={16} />
        </span>
      }
      description={meta || undefined}
      footer={
        <>
          {onDelete && (
            <Button variant="danger-ghost" icon={Trash2} onClick={() => onDelete(view)} className="mr-auto">
              Удалить
            </Button>
          )}
          <Button
            variant="secondary"
            icon={ScanSearch}
            onClick={() => {
              choose();
              setDetail("template");
            }}
          >
            Подробный разбор
          </Button>
          <Button variant="primary" icon={selected ? Check : undefined} onClick={choose}>
            {selected ? "Шаблон выбран" : "Выбрать шаблон"}
          </Button>
        </>
      }
    >
      {n > 0 ? (
        <div className="grid grid-cols-4 gap-x-3 gap-y-4 pt-2">
          {Array.from({ length: n }, (_, i) => <Thumb key={i} id={view.template_id} n={i + 1} aspect={aspect} />)}
        </div>
      ) : (
        <p className="py-10 text-center text-body text-zinc-500">Слайды шаблона не сохранились</p>
      )}
    </Modal>
  );
}
