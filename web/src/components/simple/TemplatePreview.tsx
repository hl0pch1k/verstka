// A template, every slide of it: the gallery card's «Слайды» opens this window. The name, the slide count, the font and
// the palette on top; the slides as a grid of thumbnails (the analysis renders one per slide, they load as they scroll
// in); «Подробный разбор» (the drawer's template tab) and «Выбрать шаблон» at the bottom.
import { useRef, useState } from "react";
import { Check, ImageOff, ScanSearch } from "lucide-react";
import { templateTitle } from "../../lib/plain";
import { cn, isLightHex, plural } from "../../lib/utils";
import { useApp } from "../../store";
import type { TemplateListItem } from "../../types";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const thumbUrl = (id: string, n: number) => `/api/templates/${encodeURIComponent(id)}/files/thumbs/slide-${String(n).padStart(3, "0")}.jpg`;

/** The template's colours as overlapping dots (a white one keeps a hairline so it reads on white). */
export function PaletteDots({ colors, max = 5, size = 14, className }: { colors?: string[]; max?: number; size?: number; className?: string }) {
  const list = (colors ?? []).filter((c) => /^[0-9a-f]{6}$/i.test(c)).slice(0, max);
  if (list.length === 0) return null;
  return (
    <span className={cn("flex shrink-0 items-center", className)} aria-hidden>
      {list.map((c, i) => (
        <span
          key={`${c}-${i}`}
          className={cn("block rounded-full ring-2 ring-white", i > 0 && "-ml-1", isLightHex(c) && "shadow-[inset_0_0_0_1px_rgba(16,24,40,0.14)]")}
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
    <figure className="relative overflow-hidden rounded-xl bg-zinc-100 ring-1 ring-zinc-900/[0.06]" style={{ aspectRatio: String(aspect) }}>
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
      <figcaption className="absolute bottom-1.5 left-1.5 rounded-md bg-zinc-900/60 px-1.5 text-caption font-semibold leading-5 tabular-nums text-white">{n}</figcaption>
    </figure>
  );
}

export function TemplatePreview({ t, onClose }: { t: TemplateListItem | null; onClose(): void }) {
  const { templateId, selectTemplate, setDetail } = useApp();
  // the window keeps its template while it closes
  const shown = useRef<TemplateListItem | null>(t);
  if (t) shown.current = t;
  const view = shown.current;
  if (!view) return null;
  const name = templateTitle(view.source_file, view.template_id);
  const n = Math.max(0, view.n_slides ?? 0);
  const aspect = view.aspect && view.aspect > 0 ? view.aspect : 16 / 9;
  const selected = view.template_id === templateId;
  const meta = [n ? plural(n, "слайд", "слайда", "слайдов") : null, view.font ? `шрифт ${view.font}` : null].filter(Boolean).join(" · ");
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
        <span className="flex items-center gap-3">
          <span className="min-w-0 truncate">{name}</span>
          <PaletteDots colors={view.palette} max={6} size={16} />
        </span>
      }
      description={meta || undefined}
      footer={
        <>
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
          <Button variant="brand" icon={selected ? Check : undefined} onClick={choose}>
            {selected ? "Шаблон выбран" : "Выбрать шаблон"}
          </Button>
        </>
      }
    >
      {n > 0 ? (
        <div className="grid grid-cols-4 gap-3 pt-2">
          {Array.from({ length: n }, (_, i) => <Thumb key={i} id={view.template_id} n={i + 1} aspect={aspect} />)}
        </div>
      ) : (
        <p className="py-10 text-center text-body text-zinc-500">Слайды шаблона не сохранились</p>
      )}
    </Modal>
  );
}
