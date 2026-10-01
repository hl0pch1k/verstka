// One sample slide of the template: its slot map over the full-size render (the hovered slot's name shows in the row
// under the slide, never over the slide's text), the list of places for content, repeat groups and — when several
// sources voted — how the type was set.
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Eye, EyeOff } from "lucide-react";
import { cn, fmtPct, kindLabel, plural } from "../lib/utils";
import type { Pattern, RepeatGroup, Slot } from "../types";
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

const GROUP_COLORS = ["#7C3AED", "#0891B2", "#EA580C", "#16A34A"];
const groupColor = (i: number) => GROUP_COLORS[i % GROUP_COLORS.length];

/** What a cell of a group holds, from the slots of its first cell: «заголовок карточки + текст карточки». */
function cellRoles(pattern: Pattern, g: RepeatGroup): string {
  const first = new Set(g.member_shape_ids[0] ?? []);
  const roles: string[] = [];
  for (const s of pattern.slots) {
    if (!first.has(s.shape_id)) continue;
    const label = slotRoleLabel(s.role).replace(" карточки", "");
    if (!roles.includes(label)) roles.push(label);
  }
  return roles.join(" + ");
}

/** The kind of item a group repeats, by the sample's type: cards, steps, figures, people. */
function itemWord(kind: string, n: number): string {
  if (kind === "process" || kind === "timeline" || kind === "agenda") return plural(n, "шаг", "шага", "шагов");
  if (kind === "stat_row" || kind === "big_number") return plural(n, "число", "числа", "чисел");
  if (kind === "team") return plural(n, "человек", "человека", "человек");
  return plural(n, "карточка", "карточки", "карточек");
}

type Hover = { slot: string | null; group: string | null };

/** How the sample drew its chart: «столбцы, нарисованные фигурами (11, две серии)». */
function chartDrawn(pattern: Pattern): string {
  const h = pattern.chart_hint ?? {};
  const what = h.direction === "bar" ? "полосы, нарисованные фигурами" : h.direction === "gantt" ? "диаграмма Ганта, нарисованная фигурами" : "столбцы, нарисованные фигурами";
  const series = h.series && h.series > 1 ? ` (${plural(h.series, "серия", "серии", "серий")})` : "";
  return `${what}${series}`;
}

function SlotMap({ pattern, aspect, show, hover, onHover }: { pattern: Pattern; aspect: string; show: boolean; hover: Hover; onHover(h: Hover): void }) {
  const grouped = new Set(pattern.repeat_groups.flatMap((g) => g.member_shape_ids.flat()));
  const slotGroup = (s: Slot) => pattern.repeat_groups.find((g) => g.member_shape_ids.some((c) => c.includes(s.shape_id)))?.id ?? null;
  return (
    // the thumbnail (already loaded by the gallery) stands underneath while the full-size render arrives
    <div
      className="relative overflow-hidden rounded-xl bg-zinc-100 bg-contain bg-center bg-no-repeat after:pointer-events-none after:absolute after:inset-0 after:rounded-xl after:shadow-inner-line after:content-['']"
      style={{ aspectRatio: aspect, backgroundImage: pattern.thumbnail_url ? `url("${pattern.thumbnail_url}")` : undefined }}
    >
      <PatternThumb key={pattern.id} src={fullSize(pattern.thumbnail_url)} fallback={pattern.thumbnail_url} alt={`Слайд ${pattern.source_slide}`} className="object-contain" />
      {show && pattern.data_box && (
        <div
          className="absolute rounded-md border-[1.5px] border-dashed"
          style={{ left: `${pattern.data_box.x * 100}%`, top: `${pattern.data_box.y * 100}%`, width: `${pattern.data_box.w * 100}%`, height: `${pattern.data_box.h * 100}%`, borderColor: "#DB2777", background: "#DB27770F" }}
        >
          <span className="absolute -top-px left-2 -translate-y-1/2 rounded bg-[#DB2777] px-1.5 text-[10px] font-semibold leading-4 text-white">{pattern.data_kind === "chart" ? "диаграмма" : "таблица"}</span>
        </div>
      )}
      {show &&
        pattern.repeat_groups.map((g, gi) =>
          (g.cell_boxes ?? []).map((b, ci) => {
            const color = groupColor(gi);
            const on = hover.group === g.id;
            return (
              <div
                key={`${g.id}-${ci}`}
                onMouseEnter={() => onHover({ slot: null, group: g.id })}
                onMouseLeave={() => onHover({ slot: null, group: null })}
                className="absolute rounded-md border-[1.5px] border-dashed transition-[background-color] duration-150"
                style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%`, borderColor: color, background: `${color}${on ? "24" : "0A"}` }}
              >
                <span className="absolute left-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold tabular-nums text-white" style={{ background: color }}>
                  {ci + 1}
                </span>
              </div>
            );
          }),
        )}
      {show &&
        pattern.slots.map((s) => {
          const inGroup = grouped.has(s.shape_id);
          const gid = inGroup ? slotGroup(s) : null;
          // the slots of a card show when their group is pointed at; the slide's own places always
          if (inGroup && hover.group !== gid && hover.slot !== s.id) return null;
          const color = slotColor(s.role);
          const on = hover.slot === s.id;
          return (
            <div
              key={s.id}
              onMouseEnter={() => onHover({ slot: s.id, group: gid })}
              onMouseLeave={() => onHover({ slot: null, group: null })}
              className={cn("absolute border-[1.5px] transition-[background-color] duration-150", on && "z-10", inGroup && "border-[1px]")}
              style={{ left: `${s.bbox.x * 100}%`, top: `${s.bbox.y * 100}%`, width: `${s.bbox.w * 100}%`, height: `${s.bbox.h * 100}%`, borderColor: color, background: `${color}${on ? "29" : "0F"}` }}
            />
          );
        })}
    </div>
  );
}

function SlotRow({ slot, on, onHover, note }: { slot: Slot; on: boolean; onHover(h: Hover): void; note?: "text" | "label" }) {
  return (
    <li
      onMouseEnter={() => onHover({ slot: slot.id, group: null })}
      onMouseLeave={() => onHover({ slot: null, group: null })}
      className={cn("-mx-2 rounded-lg px-2 py-2 transition-colors duration-150", on && "bg-zinc-100")}
    >
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: slotColor(slot.role) }} aria-hidden />
        <span className="text-footnote font-semibold text-zinc-900">{note === "text" ? "поле примечания" : note === "label" ? "подпись примечания" : slotRoleLabel(slot.role)}</span>
      </div>
      {slot.sample_text && <p className="truncate pl-4 text-caption text-zinc-500" title={slot.sample_text}>«{slot.sample_text}»</p>}
      {note === "text" && <p className="pl-4 text-caption text-zinc-500">сюда встанет вывод слайда</p>}
    </li>
  );
}

function GroupRow({ pattern, group, index, on, onHover }: { pattern: Pattern; group: RepeatGroup; index: number; on: boolean; onHover(h: Hover): void }) {
  const n = group.member_shape_ids.length;
  const roles = cellRoles(pattern, group);
  return (
    <li
      onMouseEnter={() => onHover({ slot: null, group: group.id })}
      onMouseLeave={() => onHover({ slot: null, group: null })}
      className={cn("-mx-2 rounded-lg px-2 py-2 transition-colors duration-150", on && "bg-zinc-100")}
    >
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: groupColor(index) }} aria-hidden />
        <span className="text-footnote font-semibold text-zinc-900">{itemWord(pattern.kind, n)}</span>
        {roles && <span className="truncate text-footnote text-zinc-600">· {roles}</span>}
      </div>
      <p className="pl-4 text-caption text-zinc-500">{groupSummary(group)}</p>
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
  const [hover, setHover] = useState<Hover>({ slot: null, group: null });
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
  useEffect(() => setHover({ slot: null, group: null }), [pattern?.id]);

  if (!pattern) return null;
  const votes = pattern.classification ? votesOf(pattern.classification) : [];
  const quality = Math.min(1, Math.max(0, pattern.quality));
  const hovered = showSlots ? pattern.slots.find((x) => x.id === hover.slot) ?? null : null;
  const grouped = new Set(pattern.repeat_groups.flatMap((g) => g.member_shape_ids.flat()));
  const ownSlots = pattern.slots.filter((s) => !grouped.has(s.shape_id));
  const places = ownSlots.length + pattern.repeat_groups.length + (pattern.data_box ? 1 : 0);

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
              {places === 0 ? (
                <h4 className={H4}>Мест для текста нет — это фон</h4>
              ) : (
                <>
                  <h4 className={H4}>{plural(places, "место", "места", "мест")} для содержания</h4>
                  <ul className="scroll-thin -mr-2 min-h-0 flex-1 overflow-y-auto pb-6 pl-2 pr-2 [mask-image:linear-gradient(to_bottom,#000_calc(100%-24px),transparent)]">
                    {ownSlots.map((s) => <SlotRow key={s.id} slot={s} on={hover.slot === s.id} onHover={setHover} note={s.shape_id === pattern.note_slot ? "text" : s.shape_id === pattern.note_label ? "label" : undefined} />)}
                    {pattern.data_box && (
                      <li className="-mx-2 rounded-lg px-2 py-2">
                        <div className="flex items-center gap-2">
                          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: "#DB2777" }} aria-hidden />
                          <span className="text-footnote font-semibold text-zinc-900">{pattern.data_kind === "chart" ? "диаграмма" : "таблица"}</span>
                        </div>
                        {pattern.data_kind === "chart" ? (
                          <p className="pl-4 text-caption text-zinc-500">{chartDrawn(pattern)} — на её месте встанет настоящая диаграмма с данными слайда</p>
                        ) : (
                          <p className="pl-4 text-caption text-zinc-500">нарисована фигурами{pattern.data_rows ? ` (${plural(pattern.data_rows, "строка", "строки", "строк")})` : ""} — на её месте встанет настоящая таблица</p>
                        )}
                      </li>
                    )}
                    {pattern.repeat_groups.map((g, gi) => <GroupRow key={g.id} pattern={pattern} group={g} index={gi} on={hover.group === g.id} onHover={setHover} />)}
                  </ul>
                </>
              )}
            </section>
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
