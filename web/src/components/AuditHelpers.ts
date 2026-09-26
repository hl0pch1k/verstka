// Pure helpers for the «Аудит» panel: grouping, filtering, labels for fix actions and check categories.
import type { AuditReport, Issue, Severity } from "../types";
import type { BadgeTone } from "./ui/Badge";

export const SEVERITIES: Severity[] = ["error", "warn", "info"];
export const SEVERITY_RANK: Record<Severity, number> = { error: 0, warn: 1, info: 2 };
export const SEVERITY_TONE: Record<Severity, BadgeTone> = { error: "error", warn: "warn", info: "info" };

export const ACTION_LABEL: Record<string, string> = {
  rematch: "подобрать другой макет",
  synth: "собрать слайд заново",
  condense_text: "сократить текст",
  drop_element: "убрать лишний элемент",
  move_inside: "вернуть элемент в кадр",
  recolor: "поправить цвет",
  refont: "заменить шрифт",
  shrink_text: "уменьшить шрифт",
  xml: "поправить оформление",
  rollback: "отменить неудачную правку",
  none: "без автоисправления",
};

/** The same actions as done deeds, for the history of fixes. */
export const ACTION_DONE: Record<string, string> = {
  rematch: "Подобран другой макет",
  synth: "Слайд собран заново",
  condense_text: "Сокращён текст",
  drop_element: "Убран лишний элемент",
  move_inside: "Элемент возвращён в кадр",
  recolor: "Поправлен цвет",
  refont: "Заменён шрифт",
  shrink_text: "Уменьшен шрифт",
  xml: "Поправлено оформление",
  rollback: "Неудачная правка отменена",
};

export const CATEGORY_LABEL: Record<string, string> = {
  layout: "Компоновка",
  template: "Соответствие шаблону",
  density: "Плотность",
  integrity: "Целостность",
  content: "Содержание",
};

export const actionLabel = (action: string | undefined | null): string => (action ? ACTION_LABEL[action] ?? action : "—");
export const categoryLabel = (c: string): string => CATEGORY_LABEL[c] ?? c;

/** An issue the backend can repair on request. */
export function isFixable(issue: Issue): boolean {
  return !!issue.autofix && issue.autofix.action !== "none";
}

/** A minor note of the rules (grid alignment and the like): it does not lower the score and stays folded. The model's
 *  remarks on the slide picture are never minor. */
export function isMinor(issue: Issue): boolean {
  return issue.severity === "info" && issue.kind !== "model";
}

export interface SlideGroup {
  slide: number; // 0 = deck level
  issues: Issue[];
  counts: Record<Severity, number>;
  worst: Severity | null;
  fixable: number;
}

/** Groups issues by slide (deck first, then 1..N); issues inside a group are ordered error → warn → info. */
export function groupBySlide(issues: Issue[]): SlideGroup[] {
  const map = new Map<number, Issue[]>();
  for (const issue of issues) {
    const list = map.get(issue.slide);
    if (list) list.push(issue);
    else map.set(issue.slide, [issue]);
  }
  return [...map.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([slide, list]) => {
      const sorted = [...list].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.check_id.localeCompare(b.check_id));
      const counts = countBySeverity(sorted);
      return { slide, issues: sorted, counts, worst: worstSeverity(sorted), fixable: sorted.filter(isFixable).length };
    });
}

export function countBySeverity(issues: Issue[]): Record<Severity, number> {
  const counts: Record<Severity, number> = { error: 0, warn: 0, info: 0 };
  for (const i of issues) counts[i.severity] += 1;
  return counts;
}

export function worstSeverity(issues: Issue[]): Severity | null {
  if (issues.length === 0) return null;
  return issues.reduce<Severity>((worst, i) => (SEVERITY_RANK[i.severity] < SEVERITY_RANK[worst] ? i.severity : worst), "info");
}

export const slideLabel = (slide: number): string => (slide === 0 ? "Вся презентация" : `Слайд ${slide}`);

/** Revision key of an audit report — changes whenever fixes were applied, used to reset selections. */
export function auditRev(a: AuditReport | null | undefined): string {
  if (!a) return "none";
  return [a.applied_fixes.length, a.iterations, a.issues.length, Math.round(a.summary.score * 10)].join(".");
}

/** A loose applied-fix record from the backend, normalised for display. */
export interface FixRecord {
  iteration: number | null;
  action: string | null;
  /** What exactly an in-place («xml») edit did: refont, recolor, move_inside, shrink_text, drop_element. */
  kind: string | null;
  outlineId: string | null;
  /** 1-based slide of an in-place edit (older runs wrote it only into the English result line). */
  slide: number | null;
  result: string | null;
  extra: [string, string][];
}

const KNOWN_KEYS = new Set(["iteration", "action", "kind", "outline_id", "slide", "result", "element_id"]);

export function normalizeFix(raw: Record<string, unknown>): FixRecord {
  const str = (v: unknown): string | null => {
    if (v === null || v === undefined || v === "") return null;
    return typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v) : String(v);
  };
  const iteration = typeof raw.iteration === "number" ? raw.iteration : null;
  const extra = Object.entries(raw)
    .filter(([k, v]) => !KNOWN_KEYS.has(k) && v !== null && v !== undefined && v !== "")
    .map(([k, v]) => [k, str(v) ?? ""] as [string, string]);
  const result = str(raw.result);
  const legacySlide = result?.match(/^slide (\d+):/)?.[1];
  const slide = typeof raw.slide === "number" ? raw.slide : legacySlide ? Number(legacySlide) : null;
  return { iteration, action: str(raw.action), kind: str(raw.kind), outlineId: str(raw.outline_id), slide, result, extra };
}
