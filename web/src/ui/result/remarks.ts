// Режим «Замечания», исправление слайда и изображение на слайде без React (boards/R-remarks, R-fixing, R-fixed,
// R-picture; V2 модули `rm` и `rt`): какие замечания видны на сцене и в каком порядке, их рамки и номера, бейджи
// миниатюр, ход исправления по событиям задачи, итог «Исправлено», эскиз исправляемого слайда и карточка
// «Изображение». Порядок и названия замечаний — как у сервера (verstka/api/remarks.py): «замечание 2» значит одно и то
// же на сцене, в строке критика и в ответе.
import { eventParts } from "../../lib/agent";
import { about as pictureAbout } from "../../lib/pictures";
import { sketchKind, sketchOf, stripQuoted, type SketchKind } from "../../lib/stage";
import { plural } from "../../lib/utils";
import type { AgentEvent, BboxFrac, Issue, OutlineSlide, PatternKind, Severity, SlideFixRemaining, SlideFixResult, SlidePicture, Variant } from "../../types";
import type { IconName } from "../kit/icons";

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
/** «Часть контента…» → «часть контента…» (аббревиатура «VK» остаётся). */
const lowerFirst = (s: string) => (s.length >= 2 && s[0] === s[0].toUpperCase() && s[1] === s[1].toUpperCase() && /\p{L}/u.test(s[1]) ? s : s.slice(0, 1).toLowerCase() + s.slice(1));
const noStop = (s: string) => s.replace(/[.\s]+$/, "");
const sentence = (s: string) => (/[.!?…»]$/.test(s.trim()) ? s.trim() : `${s.trim()}.`);
const pct = (n: number) => `${+(n * 100).toFixed(2)}%`;

/** Тон замечания на сцене и в списке (V2 `SEV`): ошибка — красный, предупреждение — янтарный, модель — серый. */
export type Tone = "err" | "warn" | "note";
export const toneOf = (s: Severity): Tone => (s === "error" ? "err" : s === "warn" ? "warn" : "note");
const SEV: Record<Tone, { label: string; icon: IconName }> = {
  err: { label: "Ошибка", icon: "alert" },
  warn: { label: "Предупреждение", icon: "warning" },
  note: { label: "Замечание модели", icon: "chat-note" },
};
const RANK: Record<Severity, number> = { error: 0, warn: 1, info: 2 };

/** Замечание, которое видно на сцене (сервер `is_stage`): ошибки, предупреждения и замечания модели на слайдах;
 *  заметки правил («сетка») и замечания ко всей презентации (слайд 0) — нет. */
export const isStage = (i: Issue) => i.slide >= 1 && !(i.severity === "info" && i.kind !== "model");

/** Рамка в долях слайда, обрезанная по слайду; мелкая (≤ 0,2 %) или не дробная — null (сервер `_boxes`). */
export function clampBox(b: BboxFrac): BboxFrac | null {
  if (![b.x, b.y, b.w, b.h].every((n) => typeof n === "number" && Number.isFinite(n))) return null;
  if (b.x > 1 || b.y > 1 || b.w > 1.5 || b.h > 1.5) return null;
  const x0 = Math.max(0, b.x);
  const y0 = Math.max(0, b.y);
  const x1 = Math.min(1, b.x + b.w);
  const y1 = Math.min(1, b.y + b.h);
  if (x1 - x0 <= 0.002 || y1 - y0 <= 0.002) return null;
  const r = (n: number) => Math.round(n * 1e6) / 1e6;
  return { x: r(x0), y: r(y0), w: r(x1 - x0), h: r(y1 - y0) };
}
const boxesOf = (i: Issue) => (i.bboxes ?? []).map(clampBox).filter((b): b is BboxFrac => !!b);

/** Порядок сервера (`order_remarks`): важность, затем левый верхний угол первой рамки (y, потом x); без рамки
 *  («весь слайд») — последними в своей важности; при равенстве — как пришли. */
export function orderRemarks(issues: Issue[]): Issue[] {
  const key = (i: Issue) => {
    const b = boxesOf(i)[0];
    return [RANK[i.severity] ?? 3, b ? 0 : 1, b ? Math.round(b.y * 1e4) : 0, b ? Math.round(b.x * 1e4) : 0];
  };
  return issues.map((i, k) => ({ i, k, key: key(i) })).sort((a, b) => {
    for (let j = 0; j < 4; j++) if (a.key[j] !== b.key[j]) return a.key[j] - b.key[j];
    return a.k - b.k;
  }).map((x) => x.i);
}

/** Названия, которые интерфейс говорит сам (сервер `UI_TITLES`): у проверок они слишком технические или длинные. */
const UI_TITLES: Record<string, string> = {
  slide_content: "Содержание слайда",
  deck_coherence: "Связность презентации",
  contrast_low: "Контраст текста к фону ниже 4,5:1",
  font_not_in_template: "Шрифт не из шаблона",
  fill_ratio: "Слайд слишком пустой или слишком плотный",
  chrome_moved: "Логотип или колонтитул не на месте",
};
const SEV_TITLE: Record<Severity, string> = { error: "Ошибка", warn: "Предупреждение", info: "Замечание" };

/** Название ряда: слова интерфейса, иначе название проверки (без «(VLM)», с десятичной запятой), иначе важность. */
export function remarkTitle(checkId: string, specTitle: string | null | undefined, severity: Severity): string {
  const own = UI_TITLES[checkId];
  if (own) return own;
  const spec = (specTitle ?? "").replace(/\s*\((?:VLM|LLM)\)\s*/g, " ").replace(/(\d)\.(\d)/g, "$1,$2").trim();
  return spec || SEV_TITLE[severity] || "Замечание";
}

/** Текст замечания для человека: коды цветов в скобках уходят (остаётся контраст), десятичная точка — запятая. */
export function plainMessage(text: string): string {
  const t = (text ?? "")
    .replace(/\s*\(#[0-9a-f]{3,8}\s+на\s+#[0-9a-f]{3,8}(?:,\s*([^)]*))?\)/gi, (_m, rest?: string) => (rest ? ` (${rest})` : ""))
    .replace(/(\d)\.(\d)/g, "$1,$2")
    .replace(/\s+/g, " ")
    .trim();
  return cap(t);
}

/** Текст ряда: что не так и, если модель подсказала, как исправить. */
function remarkText(i: Issue): string {
  const msg = plainMessage(i.message);
  const tip = (i.suggestion ?? "").trim();
  if (!tip) return msg;
  return [msg && sentence(msg), sentence(cap(plainMessage(tip)))].filter(Boolean).join(" ");
}

/** Замечание слайда, как его показывают сцена и панель: один номер `n` на сцене и в списке. `boxes` — его рамки на
 *  слайде; `whole` — места на слайде нет (оно обо всём слайде). */
export interface Remark {
  id: string;
  n: number;
  tone: Tone;
  title: string;
  text: string;
  label: string;
  icon: IconName;
  boxes: BboxFrac[];
  whole: boolean;
}

function asRemark(i: Issue, n: number, titleOf: (checkId: string) => string | null | undefined): Remark {
  const tone = toneOf(i.severity);
  const boxes = boxesOf(i);
  const whole = boxes.length === 0;
  return {
    id: i.id, n, tone, title: remarkTitle(i.check_id, titleOf(i.check_id), i.severity), text: remarkText(i),
    label: SEV[tone].label + (whole ? " · Весь слайд" : ""), icon: SEV[tone].icon, boxes, whole,
  };
}

/** Открытые замечания слайда `n` варианта — видимые на сцене, по порядку сервера, с номерами с 1. */
export function slideRemarks(v: Variant | null | undefined, n: number, titleOf: (checkId: string) => string | null | undefined): Remark[] {
  const own = (v?.audit?.issues ?? []).filter((i) => i.slide === n && isStage(i));
  return orderRemarks(own).map((i, k) => asRemark(i, k + 1, titleOf));
}

/** Бейджи миниатюр (`rk-tb`): у слайда с открытыми замечаниями — их число и тон худшего. */
export function slideBadges(v: Variant | null | undefined): Map<number, { count: number; tone: Tone }> {
  const by = new Map<number, Issue[]>();
  for (const i of v?.audit?.issues ?? []) if (isStage(i)) by.set(i.slide, [...(by.get(i.slide) ?? []), i]);
  const out = new Map<number, { count: number; tone: Tone }>();
  for (const n of [...by.keys()].sort((a, b) => a - b)) {
    const list = by.get(n)!;
    const worst = list.reduce((w, i) => (RANK[i.severity] < RANK[w] ? i.severity : w), "info" as Severity);
    out.set(n, { count: list.length, tone: toneOf(worst) });
  }
  return out;
}

/** Включение режима (V2 `rmToggle`): слайд с замечаниями остаётся, иначе — первый слайд с ними; их нет нигде — null. */
export function firstRemarkSlide(v: Variant | null | undefined, from: number): number | null {
  const b = slideBadges(v);
  if (b.has(from)) return from;
  const first = [...b.keys()][0];
  return first ?? null;
}

/** «3 замечания» в шапке панели; ни одного — «нет замечаний». */
export const countText = (n: number) => (n > 0 ? plural(n, "замечание", "замечания", "замечаний") : "нет замечаний");

// ---- разметка сцены -------------------------------------------------------------------------------------------------

/** Рамка на сцене (`rk-frame`): место замечания `n`; `on` — оно выбрано, `dim` — его рамка затемняет остальное
 *  (`rk-frame-on`, только у первой рамки места на слайде). «Весь слайд» рисуется по краю, только выбранным. */
export interface Frame { key: string; n: number; tone: Tone; left: string; top: string; width: string; height: string; on: boolean; dim: boolean }
/** Номер на сцене (`rk-pin`) — у левого верхнего угла первой рамки, у «всего слайда» — справа вверху, в ряд. */
export interface Pin { id: string; n: number; tone: Tone; left: string; top: string; on: boolean; label: string }
/** Галочка исправленного (`rd-okpin`) — там, где стоял его номер. */
export interface OkPin { id: string; n: number; left: string; top: string; label: string }

const PIN_GAP = 28;
const WHOLE_GAP = 32;

/** Рамки, номера и галочки сцены по рядам панели (`done` — исправлено) и выбранному ряду `sel` (индекс; −1 — нет). */
export function stageMarks(rows: Array<Remark & { done?: boolean }>, sel: number): { frames: Frame[]; pins: Pin[]; oks: OkPin[] } {
  const frames: Frame[] = [];
  const pins: Pin[] = [];
  const oks: OkPin[] = [];
  const placed: { x: number; y: number }[] = [];
  let wholes = 0;
  rows.forEach((r, k) => {
    const on = k === sel && !r.done;
    let left: string;
    let top: string;
    if (r.whole || !r.boxes.length) {
      left = `calc(100% - ${PIN_GAP + WHOLE_GAP * wholes}px)`;
      top = "28px";
      wholes += 1;
      if (on) frames.push({ key: `${r.id}:w`, n: r.n, tone: r.tone, left: "8px", top: "8px", width: "calc(100% - 16px)", height: "calc(100% - 16px)", on, dim: false });
    } else {
      const b = r.boxes[0];
      // номера на одном месте (одно и то же поле у двух проверок) расходятся вправо
      const near = placed.filter((p) => Math.abs(p.x - b.x) < 0.03 && Math.abs(p.y - b.y) < 0.05).length;
      placed.push({ x: b.x, y: b.y });
      const x = near ? `calc(${pct(b.x)} + ${near * PIN_GAP}px)` : pct(b.x);
      left = `clamp(14px, ${x}, calc(100% - 14px))`;
      top = `clamp(14px, ${pct(b.y)}, calc(100% - 14px))`;
      if (!r.done) {
        r.boxes.forEach((box, j) => frames.push({
          key: `${r.id}:${j}`, n: r.n, tone: r.tone, left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h), on, dim: on && j === 0,
        }));
      }
    }
    if (r.done) oks.push({ id: r.id, n: r.n, left, top, label: `Замечание ${r.n} исправлено` });
    else pins.push({ id: r.id, n: r.n, tone: r.tone, left, top, on, label: `Замечание ${r.n}: ${r.title}` });
  });
  return { frames, pins, oks };
}

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
  };
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

// ---- изображение на слайде ------------------------------------------------------------------------------------------

/** Изображения и места под них на слайде `n` — те, о которых сервер сказал, где они на слайде. */
export function slidePictures(v: Variant | null | undefined, n: number): Array<SlidePicture & { bbox: BboxFrac }> {
  return (v?.pictures ?? []).flatMap((p) => {
    const b = p.slide === n && p.bbox ? clampBox(p.bbox) : null;
    return b ? [{ ...p, bbox: b }] : [];
  });
}

/** Подпись места «Фото», «Изображение» ничего не говорит о картинке. */
const GENERIC = /^(?:фото|фотография|изображение|картинка|рисунок|иллюстрация|picture|image|photo)$/i;

/** Карточка «Изображение» (R-picture): заголовок, метка, что на картинке, модель, почему место пустует, главное
 *  действие и можно ли убрать картинку. */
export interface PictureView {
  title: string;
  tag: string | null;
  about: string;
  model: string | null;
  why: string | null;
  action: string;
  canRemove: boolean;
  generated: boolean;
}
export function pictureView(pic: SlidePicture): PictureView {
  const generated = pic.status === "generated";
  const original = generated && pic.model === "original";
  const own = !!pic.own && !generated;
  const words = pictureAbout(pic);
  // место исходной презентации подписано «… · 729ed8» — хвост для сервера
  const hint = (pic.hint ?? "").replace(/\s*·\s*[0-9a-f]{6,}\s*$/i, "").trim();
  const about = pic.wish?.trim() ? `По вашему описанию: ${pic.wish.trim()}`
    : hint || (words && !GENERIC.test(words) ? words : "") || (pic.headline?.trim() ? `К слайду «${pic.headline.trim()}»` : "");
  const pm = typeof pic.palette_match === "number" && Number.isFinite(pic.palette_match) ? `в палитре шаблона ${Math.round(pic.palette_match * 100)}%` : null;
  return {
    title: generated ? "Изображение" : own ? "Место под ваше фото" : "Место под изображение",
    tag: original ? "из исходной презентации" : generated ? "сгенерировано" : null,
    about,
    model: generated && !original ? [pic.model_label || pic.model || null, pm].filter(Boolean).join(" · ") || null : null,
    why: !generated && pic.why?.trim() ? cap(pic.why.trim()) : null,
    action: generated ? "Заменить" : own ? "Сгенерировать всё равно" : "Сгенерировать",
    canRemove: generated,
    generated,
  };
}
