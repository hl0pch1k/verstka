// Ревизия отрисованных файлов варианта (перенесено дословно из старого components/VariantsHelpers.ts).
import type { Variant } from "../types";

/**
 * Revision of a variant's rendered artefacts. Autofix rewrites slide JPEGs and the plan under the same URLs, so the
 * revision is appended to image URLs (cache busting) and to the explain-cache keys.
 */
export function variantRev(v: Variant): string {
  const a = v.audit;
  if (!a) return "0";
  return [a.applied_fixes.length, a.iterations, a.issues.length, Math.round(a.summary.score * 10), v.edits?.length ?? 0].join(".");
}

export function withRev(url: string, rev: string): string {
  return `${url}${url.includes("?") ? "&" : "?"}v=${encodeURIComponent(rev)}`;
}
