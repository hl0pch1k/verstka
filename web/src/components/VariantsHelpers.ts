// Pure helpers shared by the «Варианты» panel pieces (filmstrip, preview overlays, slide issues).
import type { AuditReport, BboxFrac, Issue, LayoutSlide, Severity, Variant } from "../types";
import { plural, SEVERITY_LABEL } from "../lib/utils";
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
export function placeTags(
  boxes: StageBox[],
  w: number,
  h: number,
  size: (place: StageBox) => { w: number; h: number },
  avoid: Rect[] = [],
  /** The candidate spots, best first (the default: the tag spots below). */
  spotsFor?: (r: Rect, t: { w: number; h: number }) => TagSpot[],
): Map<string, TagSpot | null> {
  const out = new Map<string, TagSpot | null>();
  if (w <= 0 || h <= 0) return out;
  const px = (b: BboxFrac): Rect => ({ x: b.x * w, y: b.y * h, w: b.w * w, h: b.h * h });
  const placed: Rect[] = [...avoid];
  const order = boxes
    .filter((b) => b.tagged)
    .sort((a, b) => SEVERITY_ORDER[a.sev] - SEVERITY_ORDER[b.sev] || a.box.y - b.box.y || a.box.x - b.box.x);
  for (const b of order) {
    const r = px(b.box);
    const t = size(b);
    const others = boxes.filter((o) => o !== b).map((o) => px(o.box));
    const rect = (s: TagSpot): Rect => ({ x: r.x + s.dx, y: r.y + s.dy, w: t.w, h: t.h });
    const spots: TagSpot[] = spotsFor ? spotsFor(r, t) : [
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

// ---- remarks on the stage (the «Замечания» switch, the RemarksPanel, the lightbox) -------------------------------

/** A remark of the current slide as the stage and the panel show it: the same number `n` on the slide's pin and the
 *  list row. `boxes`: its own usable frames; `whole`: it has no place on the slide (it is about the whole slide). */
export interface StageRemark { issue: Issue; n: number; title: string; text: string; boxes: BboxFrac[]; whole: boolean }

/** A remark as a person reads it: the colour codes of a contrast note stay in the data, a decimal point is a comma. */
const plainMessage = (text: string) => {
  const t = text
    .replace(/\s*\(#[0-9a-f]{3,8}\s+на\s+#[0-9a-f]{3,8}(?:,\s*([^)]*))?\)/gi, (_m, rest?: string) => (rest ? ` (${rest})` : ""))
    .replace(/(\d)\.(\d)/g, "$1,$2")
    .trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
};

/** The titles the UI words itself (the check registry's are too technical or too long for a list row). */
const REMARK_TITLE: Record<string, string> = {
  slide_content: "Содержание слайда",
  deck_coherence: "Связность презентации",
  contrast_low: "Контраст текста к фону ниже 4,5:1",
  font_not_in_template: "Шрифт не из шаблона",
  fill_ratio: "Слайд слишком пустой или слишком плотный",
  chrome_moved: "Логотип или колонтитул не на месте",
};

/** The row title of a remark: the UI's own words, else the check's title (no «(VLM)», a decimal comma), else the
 *  severity. */
export function remarkTitle(checkId: string, specTitle?: string | null, severity: Severity = "warn"): string {
  const own = REMARK_TITLE[checkId];
  if (own) return own;
  const spec = (specTitle ?? "").replace(/\s*\((?:VLM|LLM)\)\s*/g, " ").replace(/(\d)\.(\d)/g, "$1,$2").trim();
  return spec || SEVERITY_LABEL[severity];
}

/** The remarks of one slide, numbered: errors, then warnings, then the model's notes; within a severity in reading
 *  order (the top-left of the first frame: y, then x), the whole-slide remarks last. A remark without a frame of its
 *  own that names an element of a framed remark takes that frame's place (it is not «whole»). */
export function stageRemarks(issues: Issue[], titleOf: (checkId: string) => string | null | undefined): StageRemark[] {
  const places = stagePlaces(issues);
  const loose = new Set(places.unplaced.map((i) => i.id));
  const anchor = (i: Issue): BboxFrac | null => {
    for (const b of i.bboxes) {
      const c = clampBox(b);
      if (c) return c;
    }
    return places.boxes.find((p) => p.issues.includes(i))?.box ?? null;
  };
  const rows = issues.map((issue) => ({ issue, at: anchor(issue), whole: loose.has(issue.id) }));
  rows.sort((a, b) => {
    const s = SEVERITY_ORDER[a.issue.severity] - SEVERITY_ORDER[b.issue.severity];
    if (s) return s;
    if (a.whole !== b.whole) return a.whole ? 1 : -1;
    const ay = a.at?.y ?? 2;
    const by = b.at?.y ?? 2;
    // one text line apart counts as the same row: then left to right
    if (Math.abs(ay - by) > 0.02) return ay - by;
    return (a.at?.x ?? 2) - (b.at?.x ?? 2);
  });
  return rows.map(({ issue, whole }, k) => ({
    issue,
    n: k + 1,
    title: remarkTitle(issue.check_id, titleOf(issue.check_id), issue.severity),
    text: plainMessage(issue.message),
    boxes: issue.bboxes.map(clampBox).filter((b): b is BboxFrac => !!b),
    whole,
  }));
}

export type RemarkTone = "error" | "warn" | "neutral";
/** The switch badge's colour: the worst severity among the remarks (neutral for the model's notes only). */
export function remarkTone(issues: Issue[]): RemarkTone {
  const worst = worstSeverity(issues);
  return worst === "error" ? "error" : worst === "warn" ? "warn" : "neutral";
}

/** The next slide after `from` that has remarks (wrapping around); null when no other slide has any. */
export function nextFlagged(bySlide: Map<number, Issue[]>, from: number, total: number): number | null {
  for (let k = 1; k < total; k += 1) {
    const n = ((from - 1 + k) % total) + 1;
    if ((bySlide.get(n)?.length ?? 0) > 0) return n;
  }
  return null;
}

/** Spots for the numbered pins: a pin straddles its frame's corner like a badge (8px out to the side, 10px above),
 *  top-left first; then the other corners; then inside the top corners; then just outside the frame. A frame too thin
 *  for that (one line of text, a rule) would have the pin cover the very text it flags: its pins sit just outside it
 *  first — above its start, beside it, level with its middle — and straddle a corner only when there is no room. */
export function pinSpots(r: Rect, t: { w: number; h: number }): TagSpot[] {
  const o = 8;
  const up = 10;
  const gap = 4;
  const corners: TagSpot[] = [
    { dx: -o, dy: -up, side: "above", right: false },
    { dx: r.w - t.w + o, dy: -up, side: "above", right: true },
    { dx: -o, dy: r.h - t.h + up, side: "below", right: false },
    { dx: r.w - t.w + o, dy: r.h - t.h + up, side: "below", right: true },
    { dx: 4, dy: 4, side: "inside", right: false },
    { dx: r.w - t.w - 4, dy: 4, side: "inside", right: true },
  ];
  const outside: TagSpot[] = [
    { dx: 0, dy: -t.h - gap, side: "above", right: false },
    { dx: 0, dy: r.h + gap, side: "below", right: false },
    { dx: -t.w - gap, dy: 0, side: "beside", right: false },
    { dx: r.w + gap, dy: 0, side: "beside", right: true },
  ];
  const mid = (r.h - t.h) / 2;
  if (r.h < t.h + 8) {
    return [
      { dx: 0, dy: -t.h - gap, side: "above", right: false },
      { dx: -t.w - gap, dy: mid, side: "beside", right: false },
      { dx: r.w - t.w, dy: -t.h - gap, side: "above", right: true },
      { dx: 0, dy: r.h + gap, side: "below", right: false },
      { dx: r.w + gap, dy: mid, side: "beside", right: true },
      ...corners,
    ];
  }
  if (r.w < t.w + 8) {
    return [
      { dx: -t.w - gap, dy: 0, side: "beside", right: false },
      { dx: r.w + gap, dy: 0, side: "beside", right: true },
      { dx: 0, dy: -t.h - gap, side: "above", right: false },
      { dx: 0, dy: r.h + gap, side: "below", right: false },
      ...corners,
    ];
  }
  return [...corners, ...outside];
}
