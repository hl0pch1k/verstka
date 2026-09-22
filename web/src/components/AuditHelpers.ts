// Pure helpers for the «Аудит» panel: grouping, filtering, labels for fix actions and check categories.
import type { AuditReport, Issue, IssueKind, Severity } from "../types";
import { plural } from "../lib/utils";
import type { BadgeTone } from "./ui/Badge";

export const SEVERITIES: Severity[] = ["error", "warn", "info"];
export const SEVERITY_RANK: Record<Severity, number> = { error: 0, warn: 1, info: 2 };
export const SEVERITY_TONE: Record<Severity, BadgeTone> = { error: "error", warn: "warn", info: "info" };
export const KIND_SHORT: Record<IssueKind, string> = { deterministic: "детерм.", model: "модель" };

export const ACTION_LABEL: Record<string, string> = {
  rematch: "перевыбрать макет",
  synth: "пересобрать слайд",
  condense_text: "сократить текст",
  drop_element: "убрать элемент",
  move_inside: "вернуть в кадр",
  recolor: "перекрасить",
  refont: "заменить шрифт",
  xml: "правка XML",
  none: "без автоисправления",
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

export interface IssueFilter {
  severities: Set<Severity>;
  fixableOnly: boolean;
}

export const DEFAULT_FILTER: IssueFilter = { severities: new Set<Severity>(SEVERITIES), fixableOnly: false };

export function applyFilter(issues: Issue[], f: IssueFilter): Issue[] {
  return issues.filter((i) => f.severities.has(i.severity) && (!f.fixableOnly || isFixable(i)));
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

export const slideLabel = (slide: number): string => (slide === 0 ? "Колода" : `Слайд ${slide}`);

/** «2 ошибки · 1 предупреждение · 3 заметки» */
export function countsText(counts: Record<Severity, number>): string {
  const parts: string[] = [];
  if (counts.error) parts.push(plural(counts.error, "ошибка", "ошибки", "ошибок"));
  if (counts.warn) parts.push(plural(counts.warn, "предупреждение", "предупреждения", "предупреждений"));
  if (counts.info) parts.push(plural(counts.info, "заметка", "заметки", "заметок"));
  return parts.join(" · ");
}

/** Revision key of an audit report — changes whenever fixes were applied, used to reset selections. */
export function auditRev(a: AuditReport | null | undefined): string {
  if (!a) return "none";
  return [a.applied_fixes.length, a.iterations, a.issues.length, Math.round(a.summary.score * 10)].join(".");
}

export function scoreText(score: number | null | undefined): string {
  if (score === null || score === undefined || !Number.isFinite(score)) return "—";
  return String(Math.round(score));
}

/** A loose applied-fix record from the backend, normalised for display. */
export interface FixRecord {
  iteration: number | null;
  action: string | null;
  outlineId: string | null;
  result: string | null;
  extra: [string, string][];
}

const KNOWN_KEYS = new Set(["iteration", "action", "outline_id", "result"]);

export function normalizeFix(raw: Record<string, unknown>): FixRecord {
  const str = (v: unknown): string | null => {
    if (v === null || v === undefined || v === "") return null;
    return typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v) : String(v);
  };
  const iteration = typeof raw.iteration === "number" ? raw.iteration : null;
  const extra = Object.entries(raw)
    .filter(([k, v]) => !KNOWN_KEYS.has(k) && v !== null && v !== undefined && v !== "")
    .map(([k, v]) => [k, str(v) ?? ""] as [string, string]);
  return { iteration, action: str(raw.action), outlineId: str(raw.outline_id), result: str(raw.result), extra };
}

export function resultTone(result: string | null): BadgeTone {
  if (!result) return "neutral";
  const r = result.toLowerCase();
  if (r === "skip" || r.startsWith("skip") || r.startsWith("noop")) return "neutral";
  if (r.startsWith("fail") || r.startsWith("error")) return "error";
  return "success";
}
