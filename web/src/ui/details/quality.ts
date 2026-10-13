// Вкладка «Качество» листа «Подробнее» без React (boards/D-quality, V2 модуль details `dlQ`): сводка проверки, чипы,
// замечания по слайдам с флажками, «Взгляд дизайнера», мелкие заметки и «Что проверяется». Всё — по настоящему отчёту
// проверки варианта (`audit`) и записи взгляда дизайнера (`eyes`); чего в данных нет, того нет и на экране.
import { designEyeLine, problemsText } from "../../lib/designEye";
import { plural } from "../../lib/utils";
import type { AuditReport, CheckSpec, DesignEye, Issue, Variant } from "../../types";
import type { IconName } from "../kit/icons";
import { cap, plainMessage } from "../result/marks";
import { slideHeadline, slideSrc } from "../result/resultView";

/** Тон замечания на вкладке (V2 `SEV`): ошибка — красная при любом виде, замечание модели — серое, остальное —
 *  предупреждение (янтарное). */
export type QTone = "err" | "warn" | "model";
export const qTone = (i: Issue): QTone => (i.severity === "error" ? "err" : i.kind === "model" ? "model" : "warn");

/** Метка, класс метки, цвет точки и значок тона (V2 `SEV`; красной метки на доске нет — `dd-tag-e`, своя). */
export const SEV: Record<QTone, { label: string; cls: string; color: string; icon: IconName }> = {
  err: { label: "Ошибка", cls: "dd-tag-e", color: "#DC2626", icon: "alert" },
  warn: { label: "Предупреждение", cls: "dd-tag-w", color: "#B45309", icon: "warning" },
  model: { label: "Замечание модели", cls: "dd-tag-n", color: "#5A6272", icon: "eye" },
};
const RANK: Record<QTone, number> = { err: 0, warn: 1, model: 2 };

/** Замечание, которое сервер исправит сам (у него есть автоисправление). */
export const isFixable = (i: Issue) => !!i.autofix && i.autofix.action !== "none";
/** Мелкая заметка правил («сетка», контраст подписи): в список не идёт, она в разделе «Мелкие заметки». */
export const isMinorIssue = (i: Issue) => i.severity === "info" && i.kind !== "model";

export function splitIssues(issues: Issue[]): { main: Issue[]; minor: Issue[] } {
  return { main: issues.filter((i) => !isMinorIssue(i)), minor: issues.filter(isMinorIssue) };
}

// ---- сводка ---------------------------------------------------------------------------------------------------------

/** Длина окружности кольца 88 (r = 40): 2π·40 ≈ 251.3. */
const RING = 251.3;

export interface QSummary { score: number; dash: string; head: string; nErr: string; nWarn: string; nModel: string; hasErr: boolean }

export function qualitySummary(score: number, main: Issue[]): QSummary {
  const s = Math.round(Math.max(0, Math.min(100, score)));
  const n = (t: QTone) => main.filter((i) => qTone(i) === t).length;
  const err = n("err");
  const warn = n("warn");
  return {
    score: s,
    dash: `${((s / 100) * RING).toFixed(1)} ${RING}`,
    head: err + warn > 0 ? "Есть что поправить" : "Ошибок и предупреждений нет",
    nErr: plural(err, "ошибка", "ошибки", "ошибок"),
    nWarn: plural(warn, "предупреждение", "предупреждения", "предупреждений"),
    nModel: plural(n("model"), "замечание модели", "замечания модели", "замечаний модели"),
    hasErr: err > 0,
  };
}

// ---- чипы и группы ---------------------------------------------------------------------------------------------------

export type QFilter = "all" | "err" | "warn" | "fix";
const keep = (f: QFilter) => (i: Issue) => f === "all" || (f === "fix" ? isFixable(i) : qTone(i) === f);

export interface QChip { key: QFilter; label: string; n: number; on: boolean }
export function chipsOf(main: Issue[], filter: QFilter): QChip[] {
  const list: [QFilter, string][] = [["all", "Все"], ["err", "Ошибки"], ["warn", "Предупреждения"], ["fix", "Исправимые"]];
  return list.map(([key, label]) => ({ key, label, n: main.filter(keep(key)).length, on: key === filter }));
}

export interface QItem { id: string; tone: QTone; label: string; cls: string; color: string; icon: IconName; msg: string; fixable: boolean; checked: boolean; busy: boolean }
export interface QGroup { slide: number; label: string; sub: string; img: string | null; count: string; current: boolean; aria: string; items: QItem[] }

/** Текст замечания: что не так и, если проверка подсказала, как исправить — словами человека. */
export function issueText(i: Issue): string {
  const msg = plainMessage(i.message);
  const tip = plainMessage(i.suggestion ?? "");
  if (!tip) return msg;
  const end = (s: string) => (/[.!?…»]$/.test(s) ? s : `${s}.`);
  return `${end(msg)} ${end(tip)}`;
}

/** Замечания по слайдам (слайды по порядку, «Вся презентация» последней); внутри — по важности. `unmarked` — снятые
 *  флажки (по умолчанию отмечено всё исправимое, как на доске), `busy` — над чем идёт исправление («all» — всё). */
export function qualityGroups(v: Variant, main: Issue[], filter: QFilter, cur: number, unmarked: Set<string>, busy: string[] | "all" | null): QGroup[] {
  const by = new Map<number, Issue[]>();
  for (const i of main.filter(keep(filter))) by.set(i.slide, [...(by.get(i.slide) ?? []), i]);
  const order = [...by.keys()].sort((a, b) => (a === 0 ? 1 : b === 0 ? -1 : a - b));
  return order.map((n) => {
    const list = by.get(n)!.map((i, k) => ({ i, k })).sort((a, b) => RANK[qTone(a.i)] - RANK[qTone(b.i)] || a.k - b.k).map((x) => x.i);
    const title = n ? slideHeadline(v, n) : "";
    const label = n ? `Слайд ${n}` : "Вся презентация";
    const current = n > 0 && n === cur;
    return {
      slide: n, label, sub: title ? ` · ${title}` : "", img: n ? slideSrc(v, n) : null, current,
      count: plural(list.length, "замечание", "замечания", "замечаний"),
      aria: label + (title ? `: ${title}` : "") + (current ? " — открыт сейчас" : ""),
      items: list.map((i) => {
        const tone = qTone(i);
        const fixable = isFixable(i);
        return {
          id: i.id, tone, ...SEV[tone], msg: issueText(i), fixable, checked: fixable && !unmarked.has(i.id),
          busy: fixable && (busy === "all" || (!!busy && busy.includes(i.id))),
        };
      }),
    };
  });
}

/** Исправимые замечания списка, отмеченные (без снятых флажков) — их и отправит «Исправить отмеченные». */
export const fixableIds = (main: Issue[], unmarked: Set<string> = new Set()) => main.filter((i) => isFixable(i) && !unmarked.has(i.id)).map((i) => i.id);

const many = (n: number) => plural(n, "замечание", "замечания", "замечаний");
export const fixLabel = (n: number) => `Исправить отмеченные (${n})`;
export const fixingLabel = (n: number) => `Исправляю ${many(n)}…`;
export const fixedText = (n: number) => `Исправлено ${many(n)}`;

/** Сколько запрошенных замечаний исправлено: их нет в отчёте после исправления (оставшиеся сохраняют свои id). */
export function fixedCount(requested: string[], after: AuditReport | null | undefined): number {
  const left = new Set((after?.issues ?? []).map((i) => i.id));
  return requested.filter((id) => !left.has(id)).length;
}

/** Пустой список под чипом: что сказать и предложить ли «Показать все замечания» (они есть под другим чипом). */
export function emptyOf(filter: QFilter, total: number): { title: string; text: string; showAll: boolean } {
  if (filter === "all" || total === 0) return { title: "Замечаний нет", text: "Проверка не нашла на слайдах ни ошибок, ни предупреждений.", showAll: false };
  if (filter === "err") return { title: "Ошибок нет", text: "В этом варианте ни одной ошибки — только предупреждения и замечания модели.", showAll: true };
  if (filter === "warn") return { title: "Предупреждений нет", text: "В этом варианте нет предупреждений — остальные замечания под чипом «Все».", showAll: true };
  return { title: "Исправимых нет", text: "Эти замечания автоматически не исправить — откройте слайд и нажмите «Исправить слайд».", showAll: true };
}

// ---- раскрываемые разделы --------------------------------------------------------------------------------------------

/** Ряд раздела (V2 `dq-row`): метка «Слайд N» / «Все», жирное начало и продолжение. */
export interface QRow { tag: string | null; b: string; c: string }

export const slideTag = (n: number | null | undefined) => (n ? `Слайд ${n}` : "Все");

export function minorRows(minor: Issue[]): QRow[] {
  return minor.slice().sort((a, b) => a.slide - b.slide).map((i) => ({ tag: slideTag(i.slide), b: "", c: issueText(i) }));
}

const CATEGORY: Array<{ key: string; label: string; hint: string }> = [
  { key: "layout", label: "Компоновка", hint: "поля, наложения, выход за кадр, переносы слов" },
  { key: "template", label: "Соответствие шаблону", hint: "шрифты, цвета, контраст, логотип и колонтитулы" },
  { key: "density", label: "Плотность", hint: "сколько пунктов, строк и серий на слайде" },
  { key: "integrity", label: "Целостность", hint: "файл, пустые слайды, пропавший текст, порядок дат" },
  { key: "content", label: "Содержание", hint: "числа из текста, обрывки фраз, повторы заголовков" },
];

/** «Что проверяется»: категории проверок, что прошли в этом варианте (`checks_run`), с их числом; категория, где
 *  смотрела модель, помечена «моделью». */
export function checkRows(checks: CheckSpec[], run: string[]): QRow[] {
  const ran = new Set(run);
  const rows: QRow[] = [];
  for (const cat of CATEGORY) {
    const list = checks.filter((c) => c.category === cat.key && ran.has(c.id));
    if (!list.length) continue;
    const model = list.some((c) => c.kind === "model");
    rows.push({ tag: null, b: cat.label, c: ` · ${list.length} — ${cat.hint}${model ? " · моделью" : ""}` });
  }
  return rows;
}

// ---- взгляд дизайнера ------------------------------------------------------------------------------------------------

export interface EyeFixed { slide: number; tag: string; title: string; text: string; pics: { before: string; after: string } | null; redone: boolean; why: string | null }
export interface EyeView { line: string; fixed: EyeFixed[]; kept: { slide: number; tag: string; text: string }[]; seen: { slide: number; tag: string; text: string }[] }

const noStop = (s: string) => s.trim().replace(/[.\s]+$/, "");

/** «Взгляд дизайнера» (Verstka 3.0): что модель зрения увидела на готовых слайдах. Не смотрела — null. */
export function eyeView(eye: DesignEye | null | undefined, v: Variant): EyeView | null {
  if (!eye || eye.skipped || eye.looked <= 0) return null;
  const at = (st: string) => eye.slides.filter((s) => s.status === st).sort((a, b) => a.slide - b.slide);
  return {
    line: designEyeLine(eye),
    fixed: at("fixed").map((s) => ({
      slide: s.slide, tag: `Слайд ${s.slide}`, title: slideHeadline(v, s.slide), text: `${cap(problemsText(s, true))} — собрал заново.`,
      pics: !s.redone && s.before && s.after ? { before: s.before, after: s.after } : null, redone: !!s.redone, why: s.reason?.trim() || null,
    })),
    kept: at("kept").map((s) => ({
      slide: s.slide, tag: `Слайд ${s.slide}`,
      text: `${cap(problemsText(s, true))} — пробовал другую вёрстку, оставил прежнюю${s.reason?.trim() ? `: ${noStop(s.reason)}` : ""}.`,
    })),
    seen: at("seen").map((s) => ({ slide: s.slide, tag: `Слайд ${s.slide}`, text: cap(problemsText(s, false)) })),
  };
}
