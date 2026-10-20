// Режим «Замечания» без React (boards/R-remarks, R-fixed; V2 модуль `rm`): какие замечания видны на сцене и в каком
// порядке, их названия и тексты, рамки и номера на слайде, бейджи миниатюр и переключатель в шапке. Порядок и названия
// замечаний — как у сервера (verstka/api/remarks.py): «замечание 2» значит одно и то же на сцене, в строке критика и в
// ответе. Исправление слайда — fix.ts, изображение на слайде — picture.ts.
import { issueTone } from "../../lib/auditCounts";
import { plural } from "../../lib/utils";
import type { BboxFrac, Issue, Severity, Variant } from "../../types";
import type { IconName } from "../kit/icons";

export const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const sentence = (s: string) => (/[.!?…»]$/.test(s.trim()) ? s.trim() : `${s.trim()}.`);
const pct = (n: number) => `${+(n * 100).toFixed(2)}%`;

/** Тон замечания на сцене и в списке (V2 `SEV`): ошибка — красный, предупреждение — янтарный, модель — серый. */
export type Tone = "err" | "warn" | "note";
/** Тон — то же правило, что у листа «Подробнее» и карточки «Качество» (`issueTone`): ошибка — всегда ошибка, замечание
 *  модели — серое «Замечание модели», даже с важностью «предупреждение» (так их присылают взгляд дизайнера и проверка
 *  содержания), правила — по важности. Порядок и номера — по важности, как у сервера (`orderRemarks`). */
export const remarkTone = (i: Issue): Tone => {
  const t = issueTone(i);
  return t === "err" ? "err" : t === "warn" ? "warn" : "note";
};
const TONE_RANK: Record<Tone, number> = { err: 0, warn: 1, note: 2 };
const SEV: Record<Tone, { label: string; icon: IconName }> = {
  err: { label: "Ошибка", icon: "alert" },
  warn: { label: "Предупреждение", icon: "warning" },
  note: { label: "Замечание модели", icon: "chat-note" },
};
const RANK: Record<Severity, number> = { error: 0, warn: 1, info: 2 };

/** Замечание, которое видно на сцене (сервер `is_stage`): ошибки, предупреждения и замечания модели на слайдах;
 *  заметки правил («сетка») и замечания ко всей презентации (слайд 0) — нет. Одно правило для счётчика в шапке
 *  (resultView `remarkCount`), бейджей, панели и разметки сцены. */
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
/** Название ряда: слова интерфейса, иначе название проверки (без «(VLM)», с десятичной запятой), иначе — по тону, то же
 *  слово, что у метки ряда (`SEV`): пока реестр проверок не ответил, замечание модели с важностью «предупреждение» —
 *  «Замечание модели», а не «Предупреждение» над серой меткой. */
export function remarkTitle(checkId: string, specTitle: string | null | undefined, tone: Tone): string {
  const own = UI_TITLES[checkId];
  if (own) return own;
  const spec = (specTitle ?? "").replace(/\s*\((?:VLM|LLM)\)\s*/g, " ").replace(/(\d)\.(\d)/g, "$1,$2").trim();
  return spec || SEV[tone]?.label || "Замечание";
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
  const tone = remarkTone(i);
  const boxes = boxesOf(i);
  const whole = boxes.length === 0;
  return {
    id: i.id, n, tone, title: remarkTitle(i.check_id, titleOf(i.check_id), tone), text: remarkText(i),
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
    const worst = list.reduce<Tone>((w, i) => {
      const t = remarkTone(i);
      return TONE_RANK[t] < TONE_RANK[w] ? t : w;
    }, "note");
    out.set(n, { count: list.length, tone: worst });
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

/** Строка панели, когда включение «Замечаний» перешло с открытого слайда на другой (молча уводить нельзя): на открытом
 *  замечаний не было — первый слайд с ними; агент исправляет другой слайд — его слайд. */
export function jumpText(from: number, to: number, fixing = false): string {
  return fixing ? `Открыт слайд ${to}: агент исправляет его (были на слайде ${from})`
    : `Открыт слайд ${to} — на слайде ${from} замечаний нет`;
}

/** «3 замечания» в шапке панели; ни одного — «нет замечаний». */
export const countText = (n: number) => (n > 0 ? plural(n, "замечание", "замечания", "замечаний") : "нет замечаний");

/** «Замечания» в шапке рабочей области: виден, когда замечания есть или режим включён; счётчик — только когда их
 *  больше нуля (янтарный, в режиме при ошибке — красный), ни одного — числа нет (не «0»). */
export function remarksSwitch(r: { count: number; errors: boolean }, on: boolean): { shown: boolean; counter: "err" | "warn" | null } {
  return { shown: r.count > 0 || on, counter: r.count > 0 ? (on && r.errors ? "err" : "warn") : null };
}

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
