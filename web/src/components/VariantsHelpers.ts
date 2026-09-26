// Pure helpers shared by the «Варианты» panel pieces (filmstrip, preview overlays, slide issues).
import type { AuditReport, BboxFrac, Issue, LayoutSlide, Severity, Variant } from "../types";
import { plural } from "../lib/utils";
import type { BadgeTone } from "./ui/Badge";

export const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warn: 1, info: 2 };
/** Badge tone per severity: info is VK blue (no sky), see the colour rules. */
export const SEVERITY_TONE: Record<Severity, BadgeTone> = { error: "error", warn: "warn", info: "accent" };
/** localStorage key of the «Показывать замечания» switch ("0" = hidden). */
export const KEY_ISSUES = "verstka.variants.issues";

/** Plan entry of a 1-based slide: outline slide id → layout_plan.slides[].outline_id. */
export function planEntryFor(v: Variant, slide: number): LayoutSlide | null {
  const id = v.outline?.slides[slide - 1]?.id;
  if (!id) return null;
  return v.plan?.slides.find((s) => s.outline_id === id) ?? null;
}

/** Issues grouped by 1-based slide number (0 = deck level), each group sorted error → warn → info. `keep` picks the
 *  issues to group (the result stage leaves the minor notes to the drawer); a slide with none kept has no entry. */
export function issuesBySlide(audit: AuditReport | null | undefined, keep?: (issue: Issue) => boolean): Map<number, Issue[]> {
  const map = new Map<number, Issue[]>();
  for (const issue of audit?.issues ?? []) {
    if (keep && !keep(issue)) continue;
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
  return [a.applied_fixes.length, a.iterations, a.issues.length, Math.round(a.summary.score * 10), v.edits?.length ?? 0].join(".");
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

/** Intersection over union of two boxes (0 when they do not touch). */
export function iou(a: BboxFrac, b: BboxFrac): number {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  if (w <= 0 || h <= 0) return 0;
  const inter = w * h;
  return inter / (a.w * a.h + b.w * b.h - inter);
}

/** One marked place on the slide: a frame and every remark about it, worst first (the frame takes that severity).
 *  `tagged`: the place names itself with a tag; a remark with several frames names itself on the first one only. */
export interface StageBox { key: string; box: BboxFrac; issues: Issue[]; sev: Severity; ids: Set<string>; tagged: boolean }
/** The remarks of a slide as the stage shows them: the frames, the remarks with no place on the slide (a pill), and
 *  the count on the «Замечания» chip — the places a person sees (tagged frames) plus the pill's remarks. */
export interface StagePlaces { boxes: StageBox[]; unplaced: Issue[]; count: number }

/** Remarks on the same spot share one place: the same element, or frames that are the same or nearly so (IoU > 0.8),
 *  as text_clipped and margin_violation on one text box. A remark without a frame joins the frame of its element. */
export function stagePlaces(issues: Issue[]): StagePlaces {
  const sorted = [...issues].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
  const boxes: StageBox[] = [];
  const loose: Issue[] = [];
  for (const issue of sorted) {
    let drawn = false;
    issue.bboxes.forEach((raw, k) => {
      const box = clampBox(raw);
      if (!box) return;
      drawn = true;
      // the element this frame outlines, when the check names one per frame
      const el = issue.bboxes.length === issue.element_ids.length ? issue.element_ids[k] : undefined;
      const hit = boxes.find((b) => (!!el && b.ids.has(el)) || iou(b.box, box) > 0.8);
      if (hit) {
        if (!hit.issues.includes(issue)) hit.issues.push(issue);
        if (el) hit.ids.add(el);
        return;
      }
      const key = [box.x, box.y, box.w, box.h].map((n) => n.toFixed(3)).join(",");
      boxes.push({ key, box, issues: [issue], sev: issue.severity, ids: new Set(el ? [el] : []), tagged: false });
    });
    if (!drawn) loose.push(issue);
  }
  const unplaced = loose.filter((issue) => {
    const hit = boxes.find((b) => issue.element_ids.some((id) => b.ids.has(id)));
    if (hit) hit.issues.push(issue);
    return !hit;
  });
  const named = new Set<string>();
  for (const b of boxes) {
    b.issues.sort((x, y) => SEVERITY_ORDER[x.severity] - SEVERITY_ORDER[y.severity]);
    b.sev = b.issues[0].severity;
    b.tagged = b.issues.some((i) => !named.has(i.id));
    b.issues.forEach((i) => named.add(i.id));
  }
  return { boxes, unplaced, count: boxes.filter((b) => b.tagged).length + unplaced.length };
}

export interface Rect { x: number; y: number; w: number; h: number }
/** Where a place's tag sits, in px from the frame's outer top-left corner: above it, inside its top corner, below it,
 *  or beside its top edge (`right`: the tag hangs from the frame's right side). */
export interface TagSpot { dx: number; dy: number; side: "above" | "inside" | "below" | "beside"; right: boolean }

const hits = (a: Rect, b: Rect, gap = 0) => a.x < b.x + b.w + gap && b.x < a.x + a.w + gap && a.y < b.y + b.h + gap && b.y < a.y + a.h + gap;

/**
 * Tags that never collide: places by severity (an error gets its tag before a warning), then in reading order (by y,
 * then x). Each tag tries above its frame (left, then right), inside its top corner, below it, then beside it. A spot must
 * stay whole inside the slide (`w`×`h` px) and clear the tags placed before it and the `avoid` rects (the stage's own
 * pills); one that also leaves the other frames uncovered wins. No spot left: null — the frame stays, its remarks are
 * in its tooltip. A label is never cut.
 */
export function placeTags(boxes: StageBox[], w: number, h: number, size: (sev: Severity) => { w: number; h: number }, avoid: Rect[] = []): Map<string, TagSpot | null> {
  const out = new Map<string, TagSpot | null>();
  if (w <= 0 || h <= 0) return out;
  const px = (b: BboxFrac): Rect => ({ x: b.x * w, y: b.y * h, w: b.w * w, h: b.h * h });
  const placed: Rect[] = [...avoid];
  const order = boxes
    .filter((b) => b.tagged)
    .sort((a, b) => SEVERITY_ORDER[a.sev] - SEVERITY_ORDER[b.sev] || a.box.y - b.box.y || a.box.x - b.box.x);
  for (const b of order) {
    const r = px(b.box);
    const t = size(b.sev);
    const others = boxes.filter((o) => o !== b).map((o) => px(o.box));
    const rect = (s: TagSpot): Rect => ({ x: r.x + s.dx, y: r.y + s.dy, w: t.w, h: t.h });
    const spots: TagSpot[] = [
      { dx: 0, dy: -t.h, side: "above", right: false },
      { dx: r.w - t.w, dy: -t.h, side: "above", right: true },
      { dx: 0, dy: 0, side: "inside", right: false },
      { dx: r.w - t.w, dy: 0, side: "inside", right: true },
      { dx: 0, dy: r.h, side: "below", right: false },
      { dx: r.w - t.w, dy: r.h, side: "below", right: true },
      { dx: -t.w, dy: 0, side: "beside", right: false },
      { dx: r.w, dy: 0, side: "beside", right: true },
      // a frame on the slide's bottom edge: beside it, level with its bottom
      { dx: -t.w, dy: r.h - t.h, side: "beside", right: false },
      { dx: r.w, dy: r.h - t.h, side: "beside", right: true },
    ];
    const fits = spots.filter((s) => {
      const q = rect(s);
      return q.x >= -0.5 && q.y >= -0.5 && q.x + q.w <= w + 0.5 && q.y + q.h <= h + 0.5 && !placed.some((p) => hits(q, p, 2));
    });
    const spot = fits.find((s) => !others.some((o) => hits(rect(s), o))) ?? fits[0] ?? null;
    out.set(b.key, spot);
    if (spot) placed.push(rect(spot));
  }
  return out;
}

/** Audit score of a variant: the live audit report wins over the numbers frozen in generation meta / run manifest. */
export function variantScore(v: Variant, metaScore?: number | null): number | null {
  const score = v.audit?.summary.score ?? metaScore ?? v.run_manifest?.audit?.score ?? null;
  return typeof score === "number" && Number.isFinite(score) ? score : null;
}
