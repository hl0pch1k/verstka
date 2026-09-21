"""Repeat-group detection: rows/columns/grids of equal cells (cards, KPIs, steps, team members)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import Optional

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import Bbox, BboxFrac, ShapeKind
from verstka.schemas.template import RepeatGroup


@dataclass
class Cell:
    anchor_id: Optional[str]
    member_ids: list[str]
    bbox: Bbox
    composition: tuple = field(default_factory=tuple)


def _similar_size(a: Bbox, b: Bbox, tol: float) -> bool:
    return abs(a.w - b.w) <= tol * max(a.w, b.w, 1) and abs(a.h - b.h) <= tol * max(a.h, b.h, 1)


def _anchor_key(s: ShapeInfo) -> tuple:
    if s.kind == ShapeKind.pic:
        return ("pic",)
    return ("sp", s.geometry, s.fill_hex, s.line_hex)


def _composition(members: list[ShapeInfo]) -> tuple:
    items = []
    for m in members:
        if m.kind == ShapeKind.pic:
            items.append("pic")
        elif m.has_text:
            items.append(f"txt{round((m.text.dominant_size_pt or 0) / 2) * 2}")
        else:
            items.append("shape")
    return tuple(sorted(items))


def _axis(cells: list[Cell], slide_w: int, slide_h: int) -> tuple[str, int, int]:
    ys = [c.bbox.center[1] for c in cells]
    xs = [c.bbox.center[0] for c in cells]
    if max(ys) - min(ys) <= 0.04 * slide_h:
        return "row", 1, len(cells)
    if max(xs) - min(xs) <= 0.04 * slide_w:
        return "column", len(cells), 1
    # grid: cluster rows by y
    rows: list[list[float]] = []
    for y in sorted(ys):
        if rows and abs(rows[-1][0] - y) <= 0.04 * slide_h:
            rows[-1].append(y)
        else:
            rows.append([y])
    cols: list[list[float]] = []
    for x in sorted(xs):
        if cols and abs(cols[-1][0] - x) <= 0.04 * slide_w:
            cols[-1].append(x)
        else:
            cols.append([x])
    return "grid", len(rows), len(cols)


def _build_group(gid: str, cells: list[Cell], slide_w: int, slide_h: int, safe: BboxFrac) -> RepeatGroup:
    axis, rows, cols = _axis(cells, slide_w, slide_h)
    cells = sorted(cells, key=lambda c: (round(c.bbox.y / (0.04 * slide_h)), c.bbox.x))
    cell_w = int(median(c.bbox.w for c in cells))
    cell_h = int(median(c.bbox.h for c in cells))
    gap = 0.0
    max_n = len(cells)
    if axis == "row":
        xs = sorted(c.bbox.x for c in cells)
        gaps = [xs[i + 1] - (xs[i] + cell_w) for i in range(len(xs) - 1)]
        gap_emu = max(int(median(gaps)), 0) if gaps else 0
        gap = gap_emu / slide_w
        avail = safe.x2 * slide_w - xs[0]
        max_n = int((avail + gap_emu) // (cell_w + gap_emu)) if cell_w + gap_emu > 0 else len(cells)
    elif axis == "column":
        ys = sorted(c.bbox.y for c in cells)
        gaps = [ys[i + 1] - (ys[i] + cell_h) for i in range(len(ys) - 1)]
        gap_emu = max(int(median(gaps)), 0) if gaps else 0
        gap = gap_emu / slide_h
        avail = safe.y2 * slide_h - ys[0]
        max_n = int((avail + gap_emu) // (cell_h + gap_emu)) if cell_h + gap_emu > 0 else len(cells)
    else:
        gap = 0.0
        max_n = len(cells)  # a grid is not extended: the sample defines its capacity
    max_n = max(min(max_n, 8 if axis != "grid" else 12), len(cells))
    first = cells[0].bbox
    return RepeatGroup(
        id=gid,
        member_shape_ids=[c.member_ids for c in cells],
        min_n=1,
        max_n=max_n,
        axis=axis,
        gap=round(gap, 4),
        cell_bbox=Bbox(x=first.x, y=first.y, w=cell_w, h=cell_h).to_frac(slide_w, slide_h),
        rows=rows,
        cols=cols,
    )


def detect_repeat_groups(
    shapes: list[ShapeInfo],
    slide_w: int,
    slide_h: int,
    chrome_ids: Optional[set[str]] = None,
    safe_area: Optional[BboxFrac] = None,
    size_tol: float = 0.06,
) -> list[RepeatGroup]:
    chrome_ids = chrome_ids or set()
    safe = safe_area or BboxFrac(x=0.04, y=0.06, w=0.92, h=0.88)
    slide_area = float(slide_w * slide_h)
    cand = [s for s in shapes if s.id not in chrome_ids and s.bbox.area > 0 and s.bbox.area / slide_area < 0.6]
    by_id = {s.id: s for s in cand}
    used: set[str] = set()
    proposals: list[list[Cell]] = []

    # Stage A: visual anchors (filled/outlined shapes or pictures) of equal size and style
    anchors = [s for s in cand if (s.is_visual_shape or s.kind == ShapeKind.pic) and s.bbox.area / slide_area >= 0.004]
    clusters: list[list[ShapeInfo]] = []
    for a in sorted(anchors, key=lambda s: -s.bbox.area):
        for cl in clusters:
            if _anchor_key(a) == _anchor_key(cl[0]) and _similar_size(a.bbox, cl[0].bbox, size_tol):
                cl.append(a)
                break
        else:
            clusters.append([a])
    def _satellites(a: ShapeInfo, others: list[ShapeInfo]) -> list[ShapeInfo]:
        """Text boxes right of / below the anchor that visually belong to it (icon + label rows, icon-above-text cards)."""
        out = []
        for m in others:
            if m is a or m.kind != ShapeKind.sp or m.text is None or m.is_visual_shape:
                continue
            vert_overlap = m.bbox.y < a.bbox.y2 and m.bbox.y2 > a.bbox.y
            gap_x = m.bbox.x - a.bbox.x2
            if vert_overlap and -0.01 * slide_w <= gap_x <= 0.06 * slide_w and m.bbox.w <= 0.6 * slide_w:
                out.append(m)
                continue
            horiz_overlap = m.bbox.x < a.bbox.x2 and m.bbox.x2 > a.bbox.x
            gap_y = m.bbox.y - a.bbox.y2
            if horiz_overlap and -0.01 * slide_h <= gap_y <= 0.05 * slide_h and m.bbox.h <= 0.35 * slide_h and m.bbox.w <= max(a.bbox.w * 2.5, 0.3 * slide_w):
                out.append(m)
        return out

    def _union(shapes_: list[ShapeInfo]) -> Bbox:
        b = shapes_[0].bbox
        for m in shapes_[1:]:
            b = b.union(m.bbox)
        return b

    for cl in clusters:
        if len(cl) < 2:
            continue
        cells: list[Cell] = []
        anchor_ids = {a.id for a in cl}
        # satellites: each text box goes to its nearest adjacent anchor
        sat_owner: dict[str, ShapeInfo] = {}
        for a in cl:
            for m in _satellites(a, cand):
                if m.id in anchor_ids:
                    continue
                prev = sat_owner.get(m.id)
                if prev is None or abs(m.bbox.center[1] - a.bbox.center[1]) + abs(m.bbox.center[0] - a.bbox.center[0]) < abs(m.bbox.center[1] - prev.bbox.center[1]) + abs(m.bbox.center[0] - prev.bbox.center[0]):
                    sat_owner[m.id] = a
        for a in cl:
            members = [m for m in cand if m is not a and m.bbox.area <= a.bbox.area and a.bbox.contains_point(*m.bbox.center)]
            sats = [m for m in cand if sat_owner.get(m.id) is a and m not in members]
            all_members = [a] + members + sats
            cells.append(Cell(a.id, [m.id for m in all_members], _union(all_members), _composition(all_members)))
        # keep the modal composition
        modal = Counter(c.composition for c in cells).most_common(1)[0][0]
        cells = [c for c in cells if c.composition == modal]
        if len(cells) >= 2:
            proposals.append(cells)

    # Stage B: text-only rows/columns (equal style, aligned); empty text boxes count too
    in_stage_a = {i for cells in proposals for c in cells for i in c.member_ids}
    texts = [s for s in cand if s.text is not None and not s.is_visual_shape and s.kind == ShapeKind.sp and s.id not in in_stage_a]
    tclusters: list[list[ShapeInfo]] = []
    for t in texts:
        key = (round((t.text.dominant_size_pt or 0) * 2) / 2, t.text.bold_share > 0.5)
        for cl in tclusters:
            ref = cl[0]
            rkey = (round((ref.text.dominant_size_pt or 0) * 2) / 2, ref.text.bold_share > 0.5)
            if key == rkey and abs(t.bbox.w - ref.bbox.w) <= 0.1 * max(t.bbox.w, ref.bbox.w, 1):
                cl.append(t)
                break
        else:
            tclusters.append([t])
    for cl in tclusters:
        if len(cl) < 2:
            continue
        ys = [s.bbox.center[1] for s in cl]
        xs = [s.bbox.center[0] for s in cl]
        aligned = (max(ys) - min(ys) <= 0.04 * slide_h) or (max(xs) - min(xs) <= 0.04 * slide_w)
        if not aligned:
            continue
        proposals.append([Cell(None, [s.id], s.bbox, _composition([s])) for s in cl])

    # resolve overlaps: prefer proposals with more cells, then larger cells
    proposals.sort(key=lambda cells: (-len(cells), -sum(c.bbox.area for c in cells)))
    groups: list[RepeatGroup] = []
    for cells in proposals:
        ids = {i for c in cells for i in c.member_ids}
        if ids & used:
            continue
        used |= ids
        groups.append(_build_group(f"g{len(groups) + 1}", cells, slide_w, slide_h, safe))
    return groups


def group_membership(groups: list[RepeatGroup]) -> dict[str, tuple[str, int]]:
    """shape_id → (group_id, cell_index)."""
    out: dict[str, tuple[str, int]] = {}
    for g in groups:
        for ci, cell in enumerate(g.member_shape_ids):
            for sid in cell:
                out[sid] = (g.id, ci)
    return out
