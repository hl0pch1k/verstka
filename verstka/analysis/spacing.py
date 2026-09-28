"""Spacing tokens: safe area and column grid."""

from __future__ import annotations

from collections import Counter
from typing import Optional

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import BboxFrac, ShapeKind
from verstka.schemas.template import Spacing


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    k = (len(vs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)


def compute_spacing(
    shapes_per_slide: dict[int, list[ShapeInfo]],
    chrome_ids_per_slide: dict[int, set[str]],
    slide_w: int,
    slide_h: int,
    gaps: Optional[list[float]] = None,
    min_column_share: float = 0.25,
) -> Spacing:
    area = float(slide_w * slide_h)
    lefts: list[float] = []
    rights: list[float] = []
    tops: list[float] = []
    bottoms: list[float] = []
    left_edges_by_slide: dict[int, set[float]] = {}
    for idx, shapes in shapes_per_slide.items():
        chrome = chrome_ids_per_slide.get(idx, set())
        edges: set[float] = set()
        s_left, s_right, s_top, s_bottom = [], [], [], []
        # a slide whose placeholders are all empty (a LibreOffice template's own slides) says where its text goes by
        # those placeholders — its decorations alone (a pencil in a corner) would set the margins
        empty = not any(s.has_text for s in shapes if s.id not in chrome and not (s.is_placeholder and s.ph_type in ("dt", "ftr", "sldNum")))
        for s in shapes:
            if s.id in chrome or s.bbox.area <= 0 or s.bbox.area / area >= 0.8:
                continue
            placeholder = empty and s.is_placeholder and (s.ph_type or "body") not in ("dt", "ftr", "sldNum", "pic")
            if not (s.has_text or placeholder or s.is_visual_shape or s.kind == ShapeKind.pic):
                continue
            if s.kind == ShapeKind.pic and s.bbox.area / area >= 0.3:
                continue  # large pictures often bleed to the edge
            f = s.bbox.to_frac(slide_w, slide_h)
            if f.x < -0.01 or f.y < -0.01 or f.x2 > 1.01 or f.y2 > 1.01:
                continue  # bleeding decor
            s_left.append(f.x)
            s_right.append(f.x2)
            s_top.append(f.y)
            s_bottom.append(f.y2)
            edges.add(round(f.x, 2))
        left_edges_by_slide[idx] = edges
        if s_left:
            # one vote per slide: where this slide's content starts and ends (an icon sheet with 200 icons in the
            # middle must not pull the margins inwards)
            lefts.append(min(s_left))
            rights.append(max(s_right))
            tops.append(min(s_top))
            bottoms.append(max(s_bottom))
    if lefts:
        x1 = max(0.02, min(0.2, _percentile(lefts, 0.25)))
        x2 = min(0.98, max(0.8, _percentile(rights, 0.75)))
        y1 = max(0.02, min(0.3, _percentile(tops, 0.25)))
        y2 = min(0.98, max(0.7, _percentile(bottoms, 0.75)))
        safe = BboxFrac(x=round(x1, 3), y=round(y1, 3), w=round(x2 - x1, 3), h=round(y2 - y1, 3))
    else:
        safe = BboxFrac(x=0.05, y=0.08, w=0.9, h=0.84)
    # columns: left edges seen on ≥ min_column_share of slides (merge within 0.01)
    counts: Counter = Counter()
    for edges in left_edges_by_slide.values():
        for e in edges:
            counts[e] += 1
    n_slides = max(len(left_edges_by_slide), 1)
    cols: list[float] = []
    for e, c in sorted(counts.items(), key=lambda kv: -kv[1]):
        if c / n_slides < min_column_share:
            break
        if all(abs(e - existing) > 0.015 for existing in cols):
            cols.append(e)
    cols.sort()
    gutter = None
    if gaps:
        gs = sorted(g for g in gaps if g > 0)
        if gs:
            gutter = round(gs[len(gs) // 2], 4)
    return Spacing(safe_area=safe, columns=[round(c, 3) for c in cols], gutter=gutter)


_BOOKENDS = {"title", "section", "thanks", "quote"}


def extend_safe_bottom(spacing: Spacing, patterns, shapes_by_slide: dict[int, list[ShapeInfo]], layout_body_bottoms: dict[int, list[float]], chrome, slide_w: int, slide_h: int) -> Spacing:
    """Extend (never shrink) the safe area's foot to where the template's content really reaches.

    The 75th percentile of a few samples (covers and thanks slides vote too; charts and tables are not counted) can
    leave the bottom quarter of the slide unused (Gradient: y2 0.73 with the footer at 0.93). When the template has
    at most six content samples, or its content layouts' body placeholders (and its samples' charts, tables and body
    slots) reach at least 3 % lower than y2, y2 goes down to that foot — bounded by the top of the bottom chrome
    (footer, page number) less 2 % of the slide."""
    content = [p for p in patterns if getattr(p.kind, "value", p.kind) not in _BOOKENDS]
    feet: list[float] = []
    for p in content:
        feet.extend(layout_body_bottoms.get(p.source_slide, []))
        feet.extend(sl.bbox.y2 for sl in p.slots if getattr(sl.role, "value", sl.role) in ("body", "bullet_list", "image") and sl.bbox.h >= 0.3)
        for sh in shapes_by_slide.get(p.source_slide, []):
            if sh.kind == ShapeKind.graphic_frame and sh.bbox.area > 0:
                f = sh.bbox.to_frac(slide_w, slide_h)
                if 0 <= f.y and f.y2 <= 1.0:
                    feet.append(f.y2)
    if not feet:
        return spacing
    sa = spacing.safe_area
    target = max(feet)
    if not (len(content) <= 6 or sa.y2 < target - 0.03) or target <= sa.y2:
        return spacing
    # the footer marks standing under the content column (an ornament strip at the slide's edge is not a foot)
    foot_chrome = [c.bbox.y for c in chrome if c.bbox.y >= 0.75 and c.bbox.h < 0.2 and c.bbox.area > 0 and min(c.bbox.x2, sa.x2) - max(c.bbox.x, sa.x) >= 0.01]
    bound = min(foot_chrome) - 0.02 if foot_chrome else 0.98
    y2 = min(target, bound, 0.98)
    if y2 <= sa.y2:
        return spacing
    return spacing.model_copy(update={"safe_area": sa.model_copy(update={"h": round(y2 - sa.y, 3)})})
