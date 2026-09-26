// One sample slide of the template: its slot map over the full-size render (the hovered slot's name shows in the row
// under the slide, never over the slide's text), the list of places for content, repeat groups and — when several
// sources voted — how the type was set.
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Eye, EyeOff, Repeat } from "lucide-react";
import { cn, fmtPct, kindLabel, plural } from "../lib/utils";
import type { Pattern, Slot } from "../types";
import { groupSummary, PatternThumb, qualityTone, votesOf } from "./TemplatePanelShared";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Modal } from "./ui/Modal";
import { Progress } from "./ui/Progress";

const SLOT_ROLE_RU: Record<string, string> = {
  title: "заголовок", subtitle: "подзаголовок", body: "текст", bullet_list: "список", paragraph: "абзац",
  card_title: "заголовок карточки", card_body: "текст карточки", card_text: "текст карточки", card_number: "число карточки", number: "число", number_label: "подпись числа", label: "подпись",
  caption: "подпись", image: "изображение", picture: "изображение", chart: "диаграмма", table: "таблица", quote: "цитата",
  author: "автор", section: "раздел", agenda_item: "пункт повестки", step: "шаг", date: "дата", logo: "логотип", icon: "иконка",
  footer: "колонтитул", page_number: "номер слайда", code: "код", name: "имя", position: "должность",
};
export const slotRoleLabel = (role: string) => SLOT_ROLE_RU[role] ?? role.replace(/_/g, " ");

/** Overlay colour per slot role family — one hue for text, one for media, one for numbers. */
function slotColor(role: string): string {
  if (role.startsWith("title") || role === "section") return "#0077FF";
  if (/image|picture|logo|icon|chart|table|code/.test(role)) return "#DB2777";
  if (/number/.test(role)) return "#D97706";
  return "#059669";
}

const H4 = "mb-2 text-footnote font-semibold text-zinc-700";

/** The full-size render of a sample slide (1467 px wide) beside its 480 px thumbnail: sharp at the modal's size. */
const fullSize = (url: string | null | undefined) => (url ? url.replace("/thumbs/", "/slides/") : url);

function SlotMap({ pattern, aspect, show, hover, onHover }: { pattern: Pattern; aspect: string; show: boolean; hover: string | null; onHover(id: string | null): void }) {
  return (
    // the thumbnail (already loaded by the gallery) stands underneath while the full-size render arrives
    <div
      className="relative overflow-hidden rounded-xl bg-zinc-100 bg-contain bg-center bg-no-repeat after:pointer-events-none after:absolute after:inset-0 after:rounded-xl after:shadow-inner-line after:content-['']"
      style={{ aspectRatio: aspect, backgroundImage: pattern.thumbnail_url ? `url("${pattern.thumbnail_url}")` : undefined }}
    >
      <PatternThumb key={pattern.id} src={fullSize(pattern.thumbnail_url)} fallback={pattern.thumbnail_url} alt={`Слайд ${pattern.source_slide}`} className="object-contain" />
      {show &&
        pattern.slots.map((s) => {
          const color = slotColor(s.role);
          const on = hover === s.id;
          return (
            <div
              key={s.id}
              onMouseEnter={() => onHover(s.id)}
              onMouseLeave={() => onHover(null)}
              className={cn("absolute border-[1.5px] transition-[background-color] duration-150", on && "z-10")}
              style={{ left: `${s.bbox.x * 100}%`, top: `${s.bbox.y * 100}%`, width: `${s.bbox.w * 100}%`, height: `${s.bbox.h * 100}%`, borderColor: color, background: `${color}${on ? "29" : "0F"}` }}
            />
          );
        })}
    </div>
  );
}

function SlotRow({ slot, on, onHover }: { slot: Slot; on: boolean; onHover(id: string | null): void }) {
  return (
    <li
      onMouseEnter={() => onHover(slot.id)}
      onMouseLeave={() => onHover(null)}
      className={cn("-mx-2 rounded-lg px-2 py-2 transition-colors duration-150", on && "bg-zinc-100")}
    >
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: slotColor(slot.role) }} aria-hidden />
        <span className="text-footnote font-semibold text-zinc-900">{slotRoleLabel(slot.role)}</span>
        {slot.group_id && <Repeat className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-label="в повторяющейся группе" />}
      </div>
      {slot.sample_text && <p className="truncate pl-4 text-caption text-zinc-500" title={slot.sample_text}>«{slot.sample_text}»</p>}
    </li>
  );
}

interface Props {
  pattern: Pattern | null;
  aspect: string;
  /** «3 / 12» — position inside the gallery's set. */
  position: string;
  onClose: () => void;
  onStep: (delta: number) => void;
}

export function PatternModal({ pattern: current, aspect, position, onClose, onStep }: Props) {
  const [showSlots, setShowSlots] = useState(true);
  const [hover, setHover] = useState<string | null>(null);
  const open = !!current;
  // the modal plays its exit animation after the gallery has let go of the pattern: keep showing the last one
  const last = useRef(current);
  if (current) last.current = current;
  const pattern = current ?? last.current;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") onStep(1);
      else if (e.key === "ArrowLeft") onStep(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onStep]);
  useEffect(() => setHover(null), [pattern?.id]);

  if (!pattern) return null;
  const votes = pattern.classification ? votesOf(pattern.classification) : [];
  const quality = Math.min(1, Math.max(0, pattern.quality));
  const hovered = showSlots ? pattern.slots.find((x) => x.id === hover) ?? null : null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={<span>Слайд {pattern.source_slide} шаблона · {kindLabel(pattern.kind)}</span>}
      description={pattern.family === "dark" ? "Тёмный фон" : "Светлый фон"}
      footer={
        <>
          <span className="mr-auto text-footnote tabular-nums text-zinc-500">{position}</span>
          <Button shape="circle" icon={ChevronLeft} onClick={() => onStep(-1)} aria-label="Предыдущий образец" />
          <Button shape="circle" icon={ChevronRight} onClick={() => onStep(1)} aria-label="Следующий образец" />
        </>
      }
    >
      <div className="grid grid-cols-[minmax(0,3fr)_minmax(280px,2fr)] gap-6 pt-4">
        <div className="space-y-4">
          <SlotMap pattern={pattern} aspect={aspect} show={showSlots} hover={hover} onHover={setHover} />
          <div className="flex items-center gap-3">
            <Button size="sm" variant="ghost" icon={showSlots ? EyeOff : Eye} onClick={() => setShowSlots(!showSlots)} className="-ml-3">
              {showSlots ? "Скрыть разметку" : "Показать разметку"}
            </Button>
            {hovered && (
              <span className="flex min-w-0 items-center gap-2 text-footnote font-semibold text-zinc-900 animate-fade" aria-live="polite">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: slotColor(hovered.role) }} aria-hidden />
                <span className="truncate">{slotRoleLabel(hovered.role)}</span>
              </span>
            )}
            <div className="ml-auto flex items-center gap-2" title="Насколько чистая структура у образца и насколько он пригоден для новых слайдов">
              <span className="whitespace-nowrap text-caption text-zinc-500">Качество образца</span>
              <span className="block w-24 shrink-0">
                <Progress size="sm" value={quality} tone={qualityTone(quality)} appear={120} />
              </span>
              <span className="text-caption font-semibold tabular-nums text-zinc-700">{fmtPct(quality)}</span>
            </div>
          </div>
          {pattern.classification && votes.length >= 2 && (
            <div className="rounded-xl bg-zinc-50 p-4">
              <p className={H4}>Как определён тип слайда · согласие {fmtPct(pattern.classification.agreement)}</p>
              <ul className="space-y-2">
                {votes.map(({ source, vote }) => (
                  <li key={source} className="flex items-baseline gap-2 text-caption text-zinc-700">
                    <span className="w-32 shrink-0 font-semibold text-zinc-900">{source}</span>
                    <Badge size="sm" tone={vote.kind === pattern.kind ? "success" : "warn"}>{kindLabel(vote.kind)}</Badge>
                    <span className="tabular-nums text-zinc-900">{fmtPct(vote.confidence)}</span>
                    {vote.rationale && <span className="min-w-0 text-zinc-500">— {vote.rationale}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* the list fills the column's height (set by the slide on the left) and scrolls inside it */}
        <div className="relative min-h-[240px]">
          <div className="absolute inset-0 flex flex-col gap-4">
            <section className="flex min-h-0 flex-1 flex-col">
              {/* a background slide says so once: no «0 мест» heading over it */}
              {pattern.slots.length === 0 ? (
                <h4 className={H4}>Мест для текста нет — это фон</h4>
              ) : (
                <>
                  <h4 className={H4}>{plural(pattern.slots.length, "место", "места", "мест")} для содержания</h4>
                  <ul className="scroll-thin -mr-2 min-h-0 flex-1 overflow-y-auto pb-6 pl-2 pr-2 [mask-image:linear-gradient(to_bottom,#000_calc(100%-24px),transparent)]">
                    {pattern.slots.map((s) => <SlotRow key={s.id} slot={s} on={hover === s.id} onHover={setHover} />)}
                  </ul>
                </>
              )}
            </section>
            {pattern.repeat_groups.length > 0 && (
              <section className="shrink-0">
                <h4 className={H4}>Повторяющиеся группы</h4>
                <ul className="space-y-1">
                  {pattern.repeat_groups.map((g) => (
                    <li key={g.id} className="flex items-center gap-2 text-footnote text-zinc-700">
                      <Repeat className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-hidden />
                      <span>{groupSummary(g)}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {pattern.decor_assets.length > 0 && (
              <section className="shrink-0">
                <h4 className={H4}>Декор</h4>
                <p className="text-footnote text-zinc-700">{plural(pattern.decor_assets.length, "декоративный элемент сохраняется", "декоративных элемента сохраняются", "декоративных элементов сохраняются")} как в образце</p>
              </section>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
