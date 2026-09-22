// Pure helpers shared by the «Варианты» panel pieces (filmstrip, preview overlays, slide issues).
import type { AuditReport, BboxFrac, Issue, LayoutSlide, Severity, Variant } from "../types";
import { plural } from "../lib/utils";
import type { BadgeTone } from "./ui/Badge";

export const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warn: 1, info: 2 };
export const SEVERITY_TONE: Record<Severity, BadgeTone> = { error: "error", warn: "warn", info: "info" };
export const MODE_LABEL: Record<LayoutSlide["mode"], string> = { clone: "Клон паттерна", synth: "Синтез из токенов" };
/** localStorage key of the «Показывать замечания» switch ("0" = hidden). */
export const KEY_ISSUES = "verstka.variants.issues";

/** Plan entry of a 1-based slide: outline slide id → layout_plan.slides[].outline_id. */
export function planEntryFor(v: Variant, slide: number): LayoutSlide | null {
  const id = v.outline?.slides[slide - 1]?.id;
  if (!id) return null;
  return v.plan?.slides.find((s) => s.outline_id === id) ?? null;
}

/** Tone of a planner fit score (0..1). */
export function fitTone(score: number): BadgeTone {
  if (!Number.isFinite(score)) return "neutral";
  return score >= 0.8 ? "success" : score >= 0.6 ? "warn" : "error";
}

/** Issues grouped by 1-based slide number (0 = deck level), each group sorted error → warn → info. */
export function issuesBySlide(audit: AuditReport | null | undefined): Map<number, Issue[]> {
  const map = new Map<number, Issue[]>();
  for (const issue of audit?.issues ?? []) {
    const list = map.get(issue.slide);
    if (list) list.push(issue);
    else map.set(issue.slide, [issue]);
  }
  map.forEach((list) => list.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]));
  return map;
}

export function worstSeverity(issues: Issue[] | undefined): Severity | null {
  if (!issues || issues.length === 0) return null;
  return issues.reduce<Severity>((worst, i) => (SEVERITY_ORDER[i.severity] < SEVERITY_ORDER[worst] ? i.severity : worst), "info");
}

/** «2 ошибки · 1 предупреждение» — empty string when there is nothing to report. */
export function issuesSummary(issues: Issue[] | undefined): string {
  if (!issues || issues.length === 0) return "";
  const n = (s: Severity) => issues.filter((i) => i.severity === s).length;
  const parts: string[] = [];
  if (n("error")) parts.push(plural(n("error"), "ошибка", "ошибки", "ошибок"));
  if (n("warn")) parts.push(plural(n("warn"), "предупреждение", "предупреждения", "предупреждений"));
  if (n("info")) parts.push(plural(n("info"), "заметка", "заметки", "заметок"));
  return parts.join(" · ");
}

/**
 * Revision of a variant's rendered artefacts. Autofix rewrites slide JPEGs and the plan under the same URLs, so the
 * revision is appended to image URLs (cache busting) and to the explain-cache keys.
 */
export function variantRev(v: Variant): string {
  const a = v.audit;
  if (!a) return "0";
  return [a.applied_fixes.length, a.iterations, a.issues.length, Math.round(a.summary.score * 10)].join(".");
}

export function withRev(url: string, rev: string): string {
  return `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(rev)}`;
}

/** Clamps a fractional bbox into the slide; returns null for degenerate or non-fractional boxes. */
export function clampBox(b: BboxFrac): BboxFrac | null {
  if (![b.x, b.y, b.w, b.h].every((n) => Number.isFinite(n))) return null;
  if (b.w > 1.5 || b.h > 1.5 || b.x > 1 || b.y > 1) return null; // not fractions — do not draw nonsense
  const x = Math.min(1, Math.max(0, b.x));
  const y = Math.min(1, Math.max(0, b.y));
  const w = Math.min(b.w - (x - b.x), 1 - x);
  const h = Math.min(b.h - (y - b.y), 1 - y);
  return w > 0.004 && h > 0.004 ? { x, y, w, h } : null;
}

export const pct = (n: number) => `${(n * 100).toFixed(3)}%`;

/** Audit score of a variant: the live audit report wins over the numbers frozen in generation meta / run manifest. */
export function variantScore(v: Variant, metaScore?: number | null): number | null {
  const score = v.audit?.summary.score ?? metaScore ?? v.run_manifest?.audit?.score ?? null;
  return typeof score === "number" && Number.isFinite(score) ? score : null;
}
