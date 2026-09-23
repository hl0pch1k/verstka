// Detail view of one pattern: slot map over the thumbnail, slot list, repeat groups and the classification trace.
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Eye, EyeOff, Repeat } from "lucide-react";
import { cn, fmtPct, kindLabel, plural } from "../lib/utils";
import type { Pattern, Slot } from "../types";
import { groupSummary, PatternThumb, qualityTone, votesOf } from "./TemplatePanelShared";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Modal } from "./ui/Modal";

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

function SlotMap({ pattern, aspect, show }: { pattern: Pattern; aspect: string; show: boolean }) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-zinc-100 shadow-inner-line" style={{ aspectRatio: aspect }}>
      <PatternThumb src={pattern.thumbnail_url} alt={`Слайд ${pattern.source_slide}`} className="object-contain" />
      {show && pattern.slots.map((s) => {
        const color = slotColor(s.role);
        return (
          <div
            key={s.id}
            title={`${s.id} · ${slotRoleLabel(s.role)}`}
            className="absolute rounded-[3px] border-[1.5px]"
            style={{ left: `${s.bbox.x * 100}%`, top: `${s.bbox.y * 100}%`, width: `${s.bbox.w * 100}%`, height: `${s.bbox.h * 100}%`, borderColor: color, background: `${color}14` }}
          >
            <span className="absolute -top-px left-0 max-w-full truncate rounded-br px-1 text-[10px] font-medium leading-4 text-white" style={{ background: color }}>
              {slotRoleLabel(s.role)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SlotRow({ slot }: { slot: Slot }) {
  return (
    <li className="flex items-start gap-2.5 py-1.5">
      <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: slotColor(slot.role) }} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-[13px] font-medium text-zinc-900">{slotRoleLabel(slot.role)}</span>
          <span className="font-mono text-[11px] text-zinc-400">{slot.id}</span>
          {slot.group_id && <span className="text-[11px] text-zinc-500">группа {slot.group_id}</span>}
          <span className="ml-auto text-[11px] tabular-nums text-zinc-400">{Math.round(slot.bbox.w * 100)}×{Math.round(slot.bbox.h * 100)}%</span>
        </div>
        {slot.sample_text && <p className="truncate text-xs text-zinc-500" title={slot.sample_text}>«{slot.sample_text}»</p>}
      </div>
    </li>
  );
}

interface Props {
  pattern: Pattern | null;
  aspect: string;
  /** «3 из 12» — position inside the filtered gallery. */
  position: string;
  onClose: () => void;
  onStep: (delta: number) => void;
}

export function PatternModal({ pattern, aspect, position, onClose, onStep }: Props) {
  const [showSlots, setShowSlots] = useState(true);
  const open = !!pattern;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") onStep(1);
      else if (e.key === "ArrowLeft") onStep(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onStep]);

  if (!pattern) return null;
  const votes = pattern.classification ? votesOf(pattern.classification) : [];
  const layoutName = pattern.layout_part?.split("/").pop()?.replace(/\.xml$/, "");

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title={<span>Слайд {pattern.source_slide} · {kindLabel(pattern.kind)}</span>}
      description={`${pattern.id} · ${pattern.family === "dark" ? "тёмный фон" : "светлый фон"}${layoutName ? ` · макет ${layoutName}` : ""}${pattern.classification?.purpose ? ` · ${pattern.classification.purpose}` : ""}`}
      footer={
        <>
          <span className="mr-auto text-[13px] tabular-nums text-zinc-500">{position}</span>
          <Button size="sm" icon={ChevronLeft} onClick={() => onStep(-1)} aria-label="Предыдущий образец" />
          <Button size="sm" icon={ChevronRight} onClick={() => onStep(1)} aria-label="Следующий образец" />
          <Button size="sm" variant="primary" onClick={onClose}>Закрыть</Button>
        </>
      }
    >
      <div className="grid grid-cols-[minmax(0,3fr)_minmax(280px,2fr)] gap-6">
        <div className="space-y-3">
          <SlotMap pattern={pattern} aspect={aspect} show={showSlots} />
          <div className="flex items-center gap-3">
            <Button size="sm" variant="ghost" icon={showSlots ? EyeOff : Eye} onClick={() => setShowSlots(!showSlots)}>
              {showSlots ? "Скрыть слоты" : "Показать слоты"}
            </Button>
            <div className="ml-auto flex items-center gap-2" title="Качество образца: чистота структуры и пригодность для повторного использования">
              <span className="text-[11px] text-zinc-500">качество</span>
              <span className="h-1 w-24 overflow-hidden rounded-full bg-zinc-200">
                <span className={cn("block h-full rounded-full", qualityTone(pattern.quality))} style={{ width: `${Math.round(Math.min(1, Math.max(0, pattern.quality)) * 100)}%` }} />
              </span>
              <span className="text-[11px] font-medium tabular-nums text-zinc-700">{fmtPct(pattern.quality)}</span>
            </div>
          </div>
          {pattern.classification && (
            <div className="rounded-2xl bg-zinc-50 p-4">
              <p className="mb-2 text-xs font-semibold text-zinc-700">Голоса классификации · согласие {fmtPct(pattern.classification.agreement)}</p>
              <ul className="space-y-1.5">
                {votes.map(({ source, vote }) => (
                  <li key={source} className="text-xs leading-[18px] text-zinc-600">
                    <span className="inline-block w-20 font-medium text-zinc-800">{source}</span>
                    <Badge size="sm" tone={vote.kind === pattern.kind ? "success" : "warn"}>{kindLabel(vote.kind)}</Badge>
                    <span className="ml-1.5 tabular-nums text-zinc-900">{fmtPct(vote.confidence)}</span>
                    {vote.rationale && <span className="ml-1.5 text-zinc-500">— {vote.rationale}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <section>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">{plural(pattern.slots.length, "слот", "слота", "слотов")}</h4>
            {pattern.slots.length === 0 ? (
              <p className="text-[13px] text-zinc-500">Слотов нет — слайд используется как декоративный фон.</p>
            ) : (
              <ul className="scroll-thin max-h-72 divide-y divide-zinc-100 overflow-y-auto pr-1">{pattern.slots.map((s) => <SlotRow key={s.id} slot={s} />)}</ul>
            )}
          </section>
          {pattern.repeat_groups.length > 0 && (
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">Повторяющиеся группы</h4>
              <ul className="space-y-1">
                {pattern.repeat_groups.map((g) => (
                  <li key={g.id} className="flex items-center gap-2 text-[13px] text-zinc-700">
                    <Repeat className="h-3.5 w-3.5 shrink-0 text-zinc-400" aria-hidden />
                    <span className="font-mono text-[11px] text-zinc-400">{g.id}</span>
                    <span>{groupSummary(g)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {pattern.decor_assets.length > 0 && (
            <section>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">Декор</h4>
              <div className="flex flex-wrap gap-1">{pattern.decor_assets.map((a) => <Badge key={a} size="sm">{a}</Badge>)}</div>
            </section>
          )}
        </div>
      </div>
    </Modal>
  );
}
