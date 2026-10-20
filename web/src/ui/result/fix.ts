// Исправление слайда без React (boards/R-fixing, R-fixed; V2 `rm-fx`): ход исправления по событиям задачи, разбор
// ответа `slide_fix`, итог «Исправлено», можно ли «Вернуть как было» и эскиз, в который сворачивается сцена.
import { eventParts } from "../../lib/agent";
import { sketchKind, sketchOf, stripQuoted, type SketchKind } from "../../lib/stage";
import { plural } from "../../lib/utils";
import type { AgentEvent, OutlineSlide, PatternKind, SlideFixRemaining, SlideFixResult, Variant } from "../../types";
import { plainMessage, type Remark } from "./marks";

/** «Часть контента…» → «часть контента…» (аббревиатура «VK» остаётся). */
const lowerFirst = (s: string) => (s.length >= 2 && s[0] === s[0].toUpperCase() && s[1] === s[1].toUpperCase() && /\p{L}/u.test(s[1]) ? s : s.slice(0, 1).toLowerCase() + s.slice(1));
const noStop = (s: string) => s.replace(/[.\s]+$/, "");

// ---- ход исправления ------------------------------------------------------------------------------------------------

export type StepState = "done" | "act" | "wait";
export interface FixStep { name: string; line: string; state: StepState }

/** Роли исправления (сервер `fix_slide`): шаги агента `critic`, `designer`/`revise`, `compile`, `check`; строки
 *  ждущего и идущего шага, пока он ещё ничего не сказал. */
const ROLES: { name: string; steps: string[]; act: string; wait: string }[] = [
  { name: "Критик", steps: ["critic"], act: "читает замечания", wait: "прочитает замечания" },
  { name: "Дизайнер", steps: ["designer", "revise"], act: "переделывает слайд", wait: "переделает слайд" },
  { name: "Вёрстка", steps: ["compile"], act: "собирает слайд", wait: "соберёт слайд по макету" },
  { name: "Проверка", steps: ["check"], act: "проверяет слайд", wait: "проверит слайд и соседние" },
];
const PREVIEW = /готовлю превью/i;

/** Шаги карточки «Агент исправляет слайд» по событиям задачи (V2 `rmSteps`): шаги до последнего заговорившего —
 *  готовы, он — идёт, после — ждут; строка шага — его последние слова. `preview` — строка «Готовлю превью слайда»:
 *  идёт, когда проверка сказала, что готовит превью. `ended` — задача кончилась: всё готово. */
export function fixSteps(events: AgentEvent[], ended: boolean): { steps: FixStep[]; preview: StepState } {
  const last = ROLES.map((r) => [...events].reverse().find((e) => r.steps.includes((e.step ?? "").toLowerCase())) ?? null);
  const reached = Math.max(0, ...last.map((e, k) => (e ? k : -1)));
  const steps = ROLES.map((r, k): FixStep => {
    const state: StepState = ended || k < reached ? "done" : k === reached ? "act" : "wait";
    const said = last[k] ? noStop(lowerFirst(eventParts(last[k]!).text)) : "";
    return { name: r.name, state, line: said || (state === "wait" ? r.wait : r.act) };
  });
  const previewing = !!last[3] && events.some((e) => (e.step ?? "").toLowerCase() === "check" && PREVIEW.test(e.message));
  return { steps, preview: ended ? "done" : previewing ? "act" : "wait" };
}

/** Время для часов хода: секундная стрелка или текущее время, что позже. Стрелка — таймер раз в секунду, а фоновая вкладка
 *  его придерживает (Chromium — до раза в минуту): любая перерисовка (событие задачи, ход полосы) показывает верное время,
 *  а не то, что было на последнем тике (жюри 5: «Агент исправляет слайд» 45 с показывал 0:00–0:01). */
export const liveNow = (tick: number): number => Math.max(tick, Date.now());

/** Часы хода: «0:14», «1:05». */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// ---- итог исправления -----------------------------------------------------------------------------------------------

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const numOrNull = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
function asRemaining(v: unknown): SlideFixRemaining | null {
  if (!v || typeof v !== "object") return null;
  const r = v as Partial<SlideFixRemaining>;
  if (typeof r.id !== "string" || typeof r.check_id !== "string") return null;
  const severity = r.severity === "error" || r.severity === "warn" || r.severity === "info" ? r.severity : "warn";
  return { id: r.id, check_id: r.check_id, severity, message: String(r.message ?? ""), new: !!r.new };
}

/** Ответ задачи `slide_fix` приходит как `unknown`: берётся, только если это и правда исправление слайда. */
export function asSlideFixResult(value: unknown): SlideFixResult | null {
  if (!value || typeof value !== "object") return null;
  const r = value as Record<string, unknown>;
  if (typeof r.reply !== "string" || typeof r.slide !== "number") return null;
  return {
    reply: r.reply,
    changed: !!r.changed,
    applied: typeof r.applied === "boolean" ? r.applied : !!r.changed,
    kind: "fix",
    strategy: String(r.strategy ?? ""),
    slide: r.slide,
    requested: strings(r.requested),
    fixed: strings(r.fixed),
    remaining: (Array.isArray(r.remaining) ? r.remaining : []).map(asRemaining).filter((x): x is SlideFixRemaining => !!x),
    score_before: numOrNull(r.score_before),
    new_score: numOrNull(r.new_score),
    errors: numOrNull(r.errors) ?? undefined,
    warnings: numOrNull(r.warnings) ?? undefined,
    changed_other_slides: !!r.changed_other_slides,
    other_slides: Array.isArray(r.other_slides) ? r.other_slides.filter((x): x is number => typeof x === "number") : [],
    how: r.how === "model" || r.how === "rules" || r.how === "autofix" ? r.how : "autofix",
    notes: strings(r.notes),
    why: typeof r.why === "string" && r.why ? r.why : null,
    version: numOrNull(r.version),
    at: numOrNull(r.at),
    cleared: !!r.cleared,
  };
}

/** Итог исправления меняет вариант на сервере — его надо перечитать: слайд исправлен (`applied`) или слайд прежний,
 *  а замечания сняты (`cleared` и `fixed` не пуст) — без перечитывания они остались бы на экране. */
export const fixRereads = (r: SlideFixResult): boolean => r.applied || (!!r.cleared && r.fixed.length > 0);

/** Строка у панели, когда слайд не изменился: ответ сервера (`reply`) — он знает, что сделано («Замечаний больше
 *  нет…»); ответа нет — запасной текст «Слайд остался прежним: <почему>». */
export function fixUnchangedText(r: SlideFixResult): string {
  const said = r.reply.trim();
  if (said) return said;
  const why = (r.why ?? "замечания остались").replace(/\.\s*$/, "");
  return `Слайд остался прежним: ${why.charAt(0).toLowerCase()}${why.slice(1)}`;
}

/** Ряды «Исправлено» (V2 `rmItems` после исправления): замечания, которые просили исправить, в их порядке —
 *  исправленные галочкой, оставшиеся — как они сейчас (новый текст); замечания слайда, которых не было в просьбе
 *  (появились после исправления), — в конце. Номера — заново по рядам. */
export function fixedRows(requested: Remark[], res: SlideFixResult, current: Remark[]): Array<Remark & { done: boolean }> {
  const fixed = new Set(res.applied ? res.fixed : []);
  const now = new Map(current.map((r) => [r.id, r]));
  const left = new Map(res.remaining.map((r) => [r.id, r]));
  const rows = requested.map((r) => {
    if (fixed.has(r.id)) return { ...r, done: true };
    const cur = now.get(r.id);
    if (cur) return { ...cur, done: false };
    const rest = left.get(r.id);
    return { ...r, text: rest ? plainMessage(rest.message) : r.text, done: false };
  });
  const asked = new Set(requested.map((r) => r.id));
  for (const r of current) if (!asked.has(r.id)) rows.push({ ...r, done: false });
  return rows.map((r, k) => ({ ...r, n: k + 1 }));
}

const slidesList = (ns: number[]) => (ns.length < 2 ? ns.join("") : `${ns.slice(0, -1).join(", ")} и ${ns[ns.length - 1]}`);

/** Итог «Исправлено» (R-fixed): «N из M» замечаний исправлены, оценка было → стало, какие ещё слайды изменились
 *  («Показать» ведёт к первому из них). */
export interface FixSummary {
  fixedN: number;
  of: number;
  cap: string;
  was: number | null;
  now: number | null;
  line: string;
  show: number | null;
  showTip: string;
}
export function fixSummary(res: SlideFixResult): FixSummary {
  const fixedN = res.fixed.length;
  const other = [...new Set(res.other_slides)].sort((a, b) => a - b);
  const many = other.length > 1;
  return {
    fixedN,
    of: res.requested.length,
    cap: plural(fixedN, "замечание исправлено", "замечания исправлены", "замечаний исправлены").replace(/^\d+\s/, ""),
    was: res.score_before === null ? null : Math.round(res.score_before),
    now: res.new_score === null ? null : Math.round(res.new_score),
    line: other.length ? `${many ? "Изменились слайды" : "Изменился слайд"} ${slidesList(other)}` : "Другие слайды не изменились",
    show: other[0] ?? null,
    showTip: other.length ? `Показать ${many ? "слайды" : "слайд"} ${slidesList(other)}` : "",
  };
}

/** «Вернуть как было» отменяет последнее изменение варианта: предлагается, только пока последнее — это (`version`
 *  того же `kind`, не отмена). */
export function lastEditIs(v: Variant | null | undefined, version: number | null | undefined, kind: string): boolean {
  const last = v?.edits?.[v.edits.length - 1];
  return !!last && version != null && last.version === version && last.kind === kind && last.undo_of == null;
}

/** Изменение `version` (исправление слайда, изображение) уже вернули как было — где угодно: «Вернуть как было» листа
 *  «Подробнее» (вкладка «Агент»), «верни как было» помощнику. Тогда его итог («Исправлено», «Новое изображение на
 *  слайде») больше не верен: слайд снова прежний, со своими замечаниями. */
export function undoneIn(v: Variant | null | undefined, version: number | null | undefined): boolean {
  return version != null && (v?.edits ?? []).some((e) => e.undo_of === version);
}

/** «Вернуть как было» без итога этой страницы (перезагрузка, возврат на экран): последнее изменение варианта —
 *  исправление слайда `n` (`kind` «fix», не отмена, с сохранённой версией) — его и вернёт «верни как было». */
export function fixToRevert(v: Variant | null | undefined, n: number): boolean {
  const last = v?.edits?.[v.edits.length - 1];
  return !!last && last.kind === "fix" && last.undo_of == null && last.version != null && (last.slides ?? []).includes(n);
}

/** Что вернёт «Вернуть как было» слайда `n` (подхваченный возврат на экране результата): последнее изменение варианта —
 *  замена изображения на этом слайде — `picture` (ход в карточке «Изображение»); иначе — `fix` (панель замечаний). */
export function slideEditKind(v: Variant | null | undefined, n: number): "fix" | "picture" {
  const last = (v?.edits ?? []).filter((e) => e.undo_of == null).pop();
  return last && last.kind === "picture" && (last.slides ?? []).includes(n) ? "picture" : "fix";
}

// ---- эскиз исправляемого слайда -------------------------------------------------------------------------------------

/** Форма слайда по плану → эскиз раскадровки (ui/build/SlideSketch). */
const KIND_SKETCH: Record<PatternKind, SketchKind> = {
  title: "cover", section: "section", agenda: "agenda", bullets: "list", cards: "cards", two_column: "compare", big_number: "numbers",
  stat_row: "numbers", comparison: "compare", timeline: "timeline", process: "timeline", table: "table", chart: "bars", image_text: "image",
  team: "cards", quote: "quote", code: "code", mockup: "image", thanks: "closing", freeform: "text",
};
function planSketch(s: OutlineSlide): SketchKind {
  if (s.kind !== "chart") return KIND_SKETCH[s.kind] ?? "text";
  const t = s.content?.chart?.type;
  return t === "bar" ? "hbars" : t === "pie" || t === "doughnut" ? "pie" : t === "line" || t === "area" ? "line" : "bars";
}

/** Эскиз слайда `n`, в который сворачивается сцена при исправлении (как карточка раскадровки сборки): форма, которую
 *  назвал дизайнер этого исправления (`events` задачи), иначе форма слайда по плану; слайда нет — текст. */
export function slideSketch(v: Variant | null | undefined, n: number, events: AgentEvent[] = []): { kind: SketchKind; formula: boolean } {
  for (let k = events.length - 1; k >= 0; k--) {
    const e = events[k];
    if (e.slide !== n || !sketchOf(e)) continue;
    // строка дизайнера без формы («переделываю по замечаниям», «правлю оформление») эскиз не меняет
    const said = stripQuoted(e.message);
    const kind = sketchKind(said);
    if (kind === "text" && !/текст|абзац/i.test(said)) continue;
    return { kind, formula: /формул/i.test(e.message) };
  }
  const s = v?.outline?.slides[n - 1];
  if (!s) return { kind: "text", formula: false };
  return { kind: planSketch(s), formula: !!s.content?.formula };
}

/** Место строки панели замечаний — одно на вид: в «Замечаниях» сразу под списком (место отдаёт список — поле, «Исправить
 *  слайд» и «Вернуть как было» не сдвигаются), в «Замечаний нет» последним (под ним ничего нет). Строка «Вернуть как
 *  было» (не вернулось или не обновилась после возврата) — итог последнего действия здесь, она стоит на этом месте;
 *  иначе — строка работы слайда; пока возврат идёт — пусто (прежняя строка не мигает между двумя попытками); null —
 *  строки нет. */
export function panelSlot(revert: { refresh?: unknown; error?: string | null; busy?: boolean } | null, line: unknown): "revert" | "line" | null {
  if (revert?.busy) return null;
  if (revert && (revert.refresh || revert.error)) return "revert";
  return line ? "line" : null;
}
