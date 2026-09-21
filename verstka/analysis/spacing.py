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
        for s in shapes:
            if s.id in chrome or s.bbox.area <= 0 or s.bbox.area / area >= 0.8:
                continue
            if not (s.has_text or s.is_visual_shape or s.kind == ShapeKind.pic):
                continue
            if s.kind == ShapeKind.pic and s.bbox.area / area >= 0.3:
                continue  # large pictures often bleed to the edge
            f = s.bbox.to_frac(slide_w, slide_h)
            if f.x < -0.01 or f.y < -0.01 or f.x2 > 1.01 or f.y2 > 1.01:
                continue  # bleeding decor
            lefts.append(f.x)
            rights.append(f.x2)
            tops.append(f.y)
            bottoms.append(f.y2)
            edges.add(round(f.x, 2))
        left_edges_by_slide[idx] = edges
    if lefts:
        x1 = max(0.02, min(0.2, _percentile(lefts, 0.05)))
        x2 = min(0.98, max(0.8, _percentile(rights, 0.95)))
        y1 = max(0.02, min(0.3, _percentile(tops, 0.05)))
        y2 = min(0.98, max(0.7, _percentile(bottoms, 0.95)))
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
