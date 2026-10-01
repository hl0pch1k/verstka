"""Repeat-group detection: rows/columns/grids of equal cells (cards, KPIs, steps, team members).

A cell is what a designer repeats: a card with its heading, its text and its icon; a step with its label and its
description; a point of a timeline. Templates draw them three ways, and all three are read here:

- on a drawn anchor — a filled or outlined shape, a picture, or an invisible frame (Google Slides exports place
  empty boxes over art drawn by the layout) — with the texts inside it and the texts right beside it;
- as text alone — a heading box repeated in a row, a column, a grid, a zigzag or a diagonal, each with the texts
  under it (a title over its text over its description);
- as rows of a table drawn with text boxes on plates (`detect_drawn_table`): not a group — a table's area.

Cells standing on art drawn for exactly them (numbered tiles, tags on a string, a staircase — a picture of the slide
or of its layout) or set in a free arrangement keep their count: the group is `fixed`.
"""

from __future__ import annotations

import re

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
    inner: list[str] = field(default_factory=list)  # the anchor and what stands on it (satellites aside)


def _similar_size(a: Bbox, b: Bbox, tol: float) -> bool:
    return abs(a.w - b.w) <= tol * max(a.w, b.w, 1) and abs(a.h - b.h) <= tol * max(a.h, b.h, 1)


def _anchor_key(s: ShapeInfo) -> tuple:
    if s.kind == ShapeKind.pic:
        return ("pic",)
    if s.image_part and s.kind == ShapeKind.sp:
        return ("sp-pic", s.geometry)
    return ("sp", s.geometry, s.fill_hex, s.line_hex)


def _draws(s: ShapeInfo) -> bool:
    """A shape that paints something: a fill, a line or a picture fill."""
    return s.is_visual_shape or (s.kind == ShapeKind.sp and bool(s.image_part))


def _composition(members: list[ShapeInfo]) -> tuple:
    """What a cell holds, for comparing cells: its texts by size and its drawn shapes. Pictures do not count — one
    card of a row may carry the template's art where the others do not, and it is a card of the row all the same."""
    items = []
    for m in members:
        if m.kind == ShapeKind.pic:
            continue
        if m.has_text:
            items.append(f"txt{round((m.text.dominant_size_pt or 0) / 2) * 2}")
        elif m.kind == ShapeKind.sp and not _draws(m):
            continue  # an empty invisible text box does not change what the cell looks like
        else:
            items.append("shape")
    return tuple(sorted(items))


def _text_composition(members: list[ShapeInfo]) -> tuple:
    return tuple(sorted(f"txt{round((m.text.dominant_size_pt or 0) / 2) * 2}" for m in members if m.has_text))


def invisible_frame(s: ShapeInfo, shapes: list[ShapeInfo], slide_area: float) -> bool:
    """An empty box that draws nothing and holds text boxes: the cell of a designer who drew the card itself
    elsewhere (the layout's picture) and marked its place on the slide."""
    if s.kind != ShapeKind.sp or s.has_text or _draws(s):
        return False
    if s.is_placeholder and s.ph_type not in (None, "body", "obj"):
        return False
    share = s.bbox.area / slide_area if slide_area else 0.0
    if not 0.012 <= share <= 0.5:
        return False
    return any(t is not s and t.has_text and t.bbox.area < 0.9 * s.bbox.area and s.bbox.contains_point(*t.bbox.center) for t in shapes)


def _clusters(values: list[float], tol: float) -> list[list[float]]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and abs(out[-1][-1] - v) <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def _axis(cells: list[Cell], slide_w: int, slide_h: int) -> tuple[str, int, int]:
    ys = [c.bbox.center[1] for c in cells]
    xs = [c.bbox.center[0] for c in cells]
    if max(ys) - min(ys) <= 0.04 * slide_h:
        return "row", 1, len(cells)
    if max(xs) - min(xs) <= 0.04 * slide_w:
        return "column", len(cells), 1
    rows = _clusters(ys, 0.04 * slide_h)
    cols = _clusters(xs, 0.04 * slide_w)
    return "grid", len(rows), len(cols)


def _free(cells: list[Cell], axis: str, rows: int, cols: int) -> bool:
    """Cells in a zigzag or on a diagonal (tags on a string, steps of a staircase): no row, column or full grid."""
    return axis == "grid" and len(cells) < 0.6 * rows * cols


def _on_art(cells: list[Cell], art_boxes: list[Bbox]) -> bool:
    """Most cells stand on one big picture drawn for them (the slide's or its layout's)."""
    if not art_boxes:
        return False
    on = sum(1 for c in cells if any(b.contains_point(*c.bbox.center) for b in art_boxes))
    return on >= max(2, 0.6 * len(cells))


def _build_group(gid: str, cells: list[Cell], slide_w: int, slide_h: int, safe: BboxFrac, art_boxes: Optional[list[Bbox]] = None) -> RepeatGroup:
    axis, rows, cols = _axis(cells, slide_w, slide_h)
    cells = sorted(cells, key=lambda c: (round(c.bbox.y / (0.04 * slide_h)), c.bbox.x))
    fixed = _free(cells, axis, rows, cols) or _on_art(cells, art_boxes or [])
    if fixed and axis == "grid" and _free(cells, axis, rows, cols):
        cells = sorted(cells, key=lambda c: c.bbox.center[0])  # a sequence reads from left to right
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
    min_n = 1
    if fixed:
        min_n = max_n = len(cells)
    first = cells[0].bbox
    return RepeatGroup(
        id=gid,
        member_shape_ids=[c.member_ids for c in cells],
        min_n=min_n,
        max_n=max_n,
        axis=axis,
        gap=round(gap, 4),
        cell_bbox=Bbox(x=first.x, y=first.y, w=cell_w, h=cell_h).to_frac(slide_w, slide_h),
        rows=rows,
        cols=cols,
        fixed=fixed,
        cell_boxes=[c.bbox.to_frac(slide_w, slide_h) for c in cells],
    )


def detect_drawn_table(shapes: list[ShapeInfo], slide_w: int, slide_h: int, chrome_ids: Optional[set[str]] = None) -> Optional[tuple[Bbox, set[str], int]]:
    """A table drawn with text boxes: at least three rows and three columns of small text boxes standing on a grid
    (columns by their left edges, rows by their middles), most places of the grid taken. Returns the table's area
    (with the plates and lines drawn under its cells), the ids of its shapes and its number of rows; None when the
    slide has none."""
    chrome_ids = chrome_ids or set()
    slide_area = float(slide_w * slide_h)
    boxes = [s for s in shapes if s.id not in chrome_ids and s.kind == ShapeKind.sp and s.has_text and not s.is_placeholder
             and s.bbox.area / slide_area < 0.03 and len(s.plain_text) <= 40 and s.bbox.y > 0.12 * slide_h]
    if len(boxes) < 9:
        return None
    rows = _clusters([b.bbox.center[1] for b in boxes], 0.012 * slide_h)
    cols = _clusters([b.bbox.x for b in boxes], 0.012 * slide_w)
    rows = [r for r in rows if len(r) >= 3]
    cols = [c for c in cols if len(c) >= 3]
    if len(rows) < 3 or len(cols) < 3:
        return None
    row_c = [sum(r) / len(r) for r in rows]
    col_c = [sum(c) / len(c) for c in cols]
    taken: dict[tuple[int, int], ShapeInfo] = {}
    for b in boxes:
        ri = min(range(len(row_c)), key=lambda k: abs(row_c[k] - b.bbox.center[1]))
        ci = min(range(len(col_c)), key=lambda k: abs(col_c[k] - b.bbox.x))
        if abs(row_c[ri] - b.bbox.center[1]) <= 0.015 * slide_h and abs(col_c[ci] - b.bbox.x) <= 0.015 * slide_w:
            taken[(ri, ci)] = b
    if len(taken) < 0.6 * len(rows) * len(cols) or len(taken) < 9:
        return None
    # rows evenly spaced: a table, not a page of headings and paragraphs
    steps = [row_c[k + 1] - row_c[k] for k in range(len(row_c) - 1)]
    if steps and max(steps) > 2.5 * max(min(steps), 1):
        return None
    # a row of ordinals «01 02 03» over a row of headings is a grid of numbered cards (WorkSpace p8), not a table
    for ri in range(len(row_c)):
        cells = [taken[(ri, ci)].plain_text.strip() for ci in range(len(col_c)) if (ri, ci) in taken]
        if len(cells) >= 3 and all(re.fullmatch(r"0?\d{1,2}", c) for c in cells):
            vals = sorted(int(c) for c in cells)
            if vals == list(range(vals[0], vals[0] + len(vals))):
                return None
    cell_ids = {b.id for b in taken.values()}
    area = None
    for b in taken.values():
        area = b.bbox if area is None else area.union(b.bbox)
    # what is drawn under the cells (plates, rules, header bars) belongs to the table
    ids = set(cell_ids)
    for s in shapes:
        if s.id in chrome_ids or s.id in ids or s.bbox.area <= 0:
            continue
        if s.has_text and s.id not in cell_ids:
            continue
        cx, cy = s.bbox.center
        if area.x - 0.02 * slide_w <= cx <= area.x2 + 0.02 * slide_w and area.y - 0.03 * slide_h <= cy <= area.y2 + 0.03 * slide_h and s.bbox.area <= 1.2 * area.area:
            ids.add(s.id)
            area = area.union(s.bbox) if s.bbox.area <= 1.1 * area.area else area
    return area, ids, len(row_c)


def detect_repeat_groups(
    shapes: list[ShapeInfo],
    slide_w: int,
    slide_h: int,
    chrome_ids: Optional[set[str]] = None,
    safe_area: Optional[BboxFrac] = None,
    size_tol: float = 0.06,
    art_boxes: Optional[list[Bbox]] = None,
    exclude_ids: Optional[set[str]] = None,
) -> list[RepeatGroup]:
    """`art_boxes`: big pictures drawn for this slide (its own or its layout's): cells standing on them are fixed.
    `exclude_ids`: shapes already read as something else (a drawn table)."""
    chrome_ids = chrome_ids or set()
    exclude_ids = exclude_ids or set()
    safe = safe_area or BboxFrac(x=0.04, y=0.06, w=0.92, h=0.88)
    slide_area = float(slide_w * slide_h)
    # (a slide number, a date or a footer is the deck's furniture, never a part of a cell: the page number under the
    # last card of a column made that card «different» and the column lost it)
    cand = [s for s in shapes if s.id not in chrome_ids and s.id not in exclude_ids and s.bbox.area > 0 and s.bbox.area / slide_area < 0.6 and not (s.is_placeholder and s.ph_type in ("sldNum", "dt", "ftr"))]
    used: set[str] = set()
    proposals: list[list[Cell]] = []
    by_id0 = {s.id: s for s in cand}

    def _union0(shapes_: list[ShapeInfo]) -> Bbox:
        b = shapes_[0].bbox
        for m in shapes_[1:]:
            b = b.union(m.bbox)
        return b

    # Stage 0: the designer's own groups — top-level group shapes of one size holding text are the cells (a card's
    # icon, heading, text and bullet dots grouped together)
    by_group: dict[str, list[ShapeInfo]] = {}
    for s in cand:
        if s.group_path:
            by_group.setdefault(s.group_path[0], []).append(s)
    gcells: list[Cell] = []
    for gid_, members in by_group.items():
        if not any(m.text is not None and m.kind == ShapeKind.sp for m in members):
            continue
        box = _union0(members)
        if box.area / slide_area >= 0.5 or box.area / slide_area < 0.004:
            continue
        gcells.append(Cell(None, [m.id for m in members], box, _composition(members)))
    gclusters: list[list[Cell]] = []
    for c in sorted(gcells, key=lambda c: -c.bbox.area):
        for cl in gclusters:
            if cl[0].composition == c.composition and _similar_size(c.bbox, cl[0].bbox, max(size_tol, 0.1)):
                cl.append(c)
                break
        else:
            gclusters.append([c])
    rank: dict[int, int] = {}  # id(proposal) → how the cells were found: 0 drawn or grouped, 1 invisible frames, 2 text alone
    for cl in gclusters:
        if len(cl) >= 2:
            proposals.append(cl)
            rank[id(cl)] = 0

    # Stage A: anchors — drawn shapes, pictures and invisible frames holding text — of equal size and style
    drawn = [s for s in cand if (_draws(s) or s.kind == ShapeKind.pic) and s.bbox.area / slide_area >= 0.004]

    def holds_cards(f: ShapeInfo) -> bool:
        """An invisible frame around drawn cards is the row's or the panel's box, not a cell."""
        inner = [d for d in drawn if d is not f and d.bbox.area < 0.6 * f.bbox.area and f.bbox.contains_point(*d.bbox.center) and d.bbox.area >= 0.01 * slide_area]
        return len(inner) >= 2

    frames = [s for s in cand if not _draws(s) and s.kind != ShapeKind.pic and invisible_frame(s, cand, slide_area) and not holds_cards(s)]
    anchors = []
    for a in drawn + [f for f in frames if f.bbox.area / slide_area >= 0.004]:
        # the same box twice (an export leaves copies of a frame on top of each other): one anchor
        if any(_anchor_key(a) == _anchor_key(b) and a.bbox.iou(b.bbox) >= 0.9 for b in anchors):
            continue
        anchors.append(a)
    clusters: list[list[ShapeInfo]] = []
    for a in sorted(anchors, key=lambda s: -s.bbox.area):
        for cl in clusters:
            if _anchor_key(a) == _anchor_key(cl[0]) and _similar_size(a.bbox, cl[0].bbox, size_tol):
                cl.append(a)
                break
        else:
            clusters.append([a])

    # an accent cell — the highlighted step of a timeline, the recommended plan of a row — is painted in another
    # colour: it joins the row of its look-alikes when it has their shape and size and stands in their line at their
    # rhythm (Education p44: the blue «2» between the pale «1», «3», «4»)
    def _in_rhythm(cl: list[ShapeInfo], a: ShapeInfo) -> bool:
        for axis in ("row", "column"):
            if axis == "row":
                line = all(abs(c.bbox.center[1] - a.bbox.center[1]) <= 0.02 * slide_h for c in cl)
                pos = sorted([c.bbox.center[0] for c in cl] + [a.bbox.center[0]])
            else:
                line = all(abs(c.bbox.center[0] - a.bbox.center[0]) <= 0.02 * slide_w for c in cl)
                pos = sorted([c.bbox.center[1] for c in cl] + [a.bbox.center[1]])
            gaps = [y - x for x, y in zip(pos, pos[1:])]
            if line and gaps and min(gaps) > 0 and max(gaps) <= 1.3 * min(gaps):
                return True
        return False

    for cl in [c for c in clusters if len(c) >= 2]:
        for other in clusters:
            if other is cl or len(other) != 1:
                continue
            a = other[0]
            if _anchor_key(a)[:2] != _anchor_key(cl[0])[:2] or not _similar_size(a.bbox, cl[0].bbox, size_tol):
                continue
            if _in_rhythm(cl, a):
                cl.append(a)
                other.clear()
    clusters = [c for c in clusters if c]

    def _satellites(a: ShapeInfo, others: list[ShapeInfo]) -> list[ShapeInfo]:
        """Text boxes right of / below the anchor that visually belong to it (icon + label rows, icon-above-text cards)."""
        out = []
        for m in others:
            if m is a or m.kind != ShapeKind.sp or m.text is None or _draws(m):
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

    def _on_other_anchor(a: ShapeInfo, m: ShapeInfo, cluster_ids: set[str]) -> bool:
        """m sits on a visual anchor other than a (a neighbouring card of the same cluster, a wider card, a picture)
        that does not also enclose a: it is that shape's member, not a's satellite. Anchors enclosing a as well (one
        big card holding an icon row) are ignored so the labels inside stay with their icons. For anchors of the same
        cluster a 30% overlap is enough; for foreign anchors only the centre counts (a label may graze the bounding
        box of a decorative picture without belonging to it)."""
        for o in anchors:
            if o is a or o.bbox.contains_point(*a.bbox.center):
                continue
            if o.bbox.contains_point(*m.bbox.center):
                return True
            if o.id in cluster_ids and m.bbox.intersection(o.bbox) > 0.3 * min(m.bbox.area, o.bbox.area):
                return True
        return False

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
                if m.id in anchor_ids or _on_other_anchor(a, m, anchor_ids):
                    continue
                prev = sat_owner.get(m.id)
                if prev is None or abs(m.bbox.center[1] - a.bbox.center[1]) + abs(m.bbox.center[0] - a.bbox.center[0]) < abs(m.bbox.center[1] - prev.bbox.center[1]) + abs(m.bbox.center[0] - prev.bbox.center[0]):
                    sat_owner[m.id] = a
        taken_ids = {m.id for a in cl for m in cand if sat_owner.get(m.id) is a} | anchor_ids
        for a in cl:
            members = [m for m in cand if m is not a and m.bbox.area <= a.bbox.area and a.bbox.contains_point(*m.bbox.center)]
            sats = [m for m in cand if sat_owner.get(m.id) is a and m not in members]
            # a text right under a satellite (a position under a name, a description under a label) is the cell's too
            for _ in range(2):
                tail = [x for x in members + sats if x.text is not None and not _draws(x)]
                for m in cand:
                    if m.id in taken_ids or m in members or m in sats or m.text is None or _draws(m) or m.kind != ShapeKind.sp:
                        continue
                    # (a text box overlapping the one above by a line's leading — WorkSpace p8's «Основной текст» under
                    # its «Заголовок» — is still the next line of the cell)
                    if any(min(x.bbox.x2, m.bbox.x2) - max(x.bbox.x, m.bbox.x) >= 0.5 * min(x.bbox.w, m.bbox.w) and -0.025 * slide_h <= m.bbox.y - x.bbox.y2 <= 0.04 * slide_h and m.bbox.y > x.bbox.y for x in tail):
                        sats.append(m)
                        taken_ids.add(m.id)
            all_members = [a] + members + sats
            cells.append(Cell(a.id, [m.id for m in all_members], _union(all_members), _composition(all_members), [m.id for m in [a] + members]))
        # keep the modal composition; a cell that differs only by a text found beside or under its card (a stray
        # label of the slide) stays as its card and what the card holds
        modal = Counter(c.composition for c in cells).most_common(1)[0][0]
        modal_cell = next(c for c in cells if c.composition == modal)
        modal_text = _text_composition([by_id0[i] for i in modal_cell.member_ids if i in by_id0])
        kept_cells = []
        for c in cells:
            if c.composition != modal:
                inner = [by_id0[i] for i in c.inner if i in by_id0]
                if inner and _composition(inner) == modal:
                    c = Cell(c.anchor_id, [m.id for m in inner], _union(inner), modal)
                elif modal_text and _text_composition([by_id0[i] for i in c.member_ids if i in by_id0]) == modal_text:
                    # the accent card of a row (WorkSpace p16: the third card painted blue all over, no header plate)
                    # holds the same texts as the others: it is a card of the row
                    c = Cell(c.anchor_id, c.member_ids, c.bbox, modal, c.inner)
            if c.composition == modal:
                kept_cells.append(c)
        cells = kept_cells
        if len(cells) >= 2:
            proposals.append(cells)
            rank[id(cells)] = 0 if (_draws(cl[0]) or cl[0].kind == ShapeKind.pic) else 1

    # Stage B: cells of text alone — a heading box repeated (a row, a column, a grid, a zigzag, a diagonal), each with
    # the texts right under it or beside it (a title over its text over its description)
    in_stage_a = {i for cells in proposals for c in cells for i in c.member_ids}
    texts = [s for s in cand if s.text is not None and not _draws(s) and s.kind == ShapeKind.sp and s.id not in in_stage_a and not invisible_frame(s, cand, slide_area)]

    def tkey(t: ShapeInfo) -> tuple:
        return (round((t.text.dominant_size_pt or 0) * 2) / 2, t.text.bold_share > 0.5)

    tclusters: list[list[ShapeInfo]] = []
    for t in texts:
        for cl in tclusters:
            ref = cl[0]
            if tkey(t) == tkey(ref) and abs(t.bbox.w - ref.bbox.w) <= 0.12 * max(t.bbox.w, ref.bbox.w, 1) and abs(t.bbox.h - ref.bbox.h) <= 0.35 * max(t.bbox.h, ref.bbox.h, 1):
                cl.append(t)
                break
        else:
            tclusters.append([t])

    def below(h: ShapeInfo, t: ShapeInfo, reach: float) -> bool:
        ov = min(h.bbox.x2, t.bbox.x2) - max(h.bbox.x, t.bbox.x)
        return ov >= 0.5 * min(h.bbox.w, t.bbox.w) and -0.01 * slide_h <= t.bbox.y - h.bbox.y2 <= reach * slide_h

    def beside(h: ShapeInfo, t: ShapeInfo) -> bool:
        ov = min(h.bbox.y2, t.bbox.y2) - max(h.bbox.y, t.bbox.y)
        return ov >= 0.5 * min(h.bbox.h, t.bbox.h) and 0 <= t.bbox.x - h.bbox.x2 <= 0.04 * slide_w

    for cl in tclusters:
        if len(cl) < 2:
            continue
        # heads stand apart: no two of them overlap (a paragraph split into boxes is not a row of cards)
        if any(a.bbox.intersection(b.bbox) > 0 for i, a in enumerate(cl) for b in cl[i + 1:]):
            continue
        heads = cl
        head_ids = {h.id for h in heads}
        owner: dict[str, ShapeInfo] = {}
        pool = [t for t in texts if t.id not in head_ids]
        for t in pool:
            best, best_d = None, None
            for h in heads:
                if below(h, t, 0.07) or beside(h, t):
                    d = abs(t.bbox.y - h.bbox.y2) + abs(t.bbox.x - h.bbox.x)
                    if best_d is None or d < best_d:
                        best, best_d = h, d
            if best is not None:
                owner[t.id] = best
        # a description under the text under the heading belongs to the same cell
        for _ in range(2):
            for t in pool:
                if t.id in owner:
                    continue
                for s in pool:
                    if s.id in owner and below(s, t, 0.05):
                        owner[t.id] = owner[s.id]
                        break
        cells = []
        for h in heads:
            members = [h] + [t for t in pool if owner.get(t.id) is h]
            cells.append(Cell(None, [m.id for m in members], _union(members), _text_composition(members)))
        modal = Counter(c.composition for c in cells).most_common(1)[0][0]
        cells = [c for c in cells if c.composition == modal]
        if len(cells) >= 2:
            proposals.append(cells)
            rank[id(cells)] = 2

    # a row of pictures with no text of their own (two halves of a 3D render, a strip of logos) is decoration, not
    # cells content could go into
    by_id = {s.id: s for s in cand}
    proposals = [p for p in proposals if all(any(by_id.get(i) is not None and by_id[i].kind == ShapeKind.sp and by_id[i].text is not None for i in c.member_ids) for c in p)]
    # a proposal whose every cell holds two or more cells of another proposal is a set of containers (rows of cards,
    # panels): the inner cells are the repeat
    def nests(outer: list[Cell], inner: list[Cell]) -> bool:
        return all(sum(1 for c in inner if o.bbox.contains_point(*c.bbox.center) and c.bbox.area < 0.7 * o.bbox.area) >= 2 for o in outer)

    proposals = [p for p in proposals if not any(q is not p and len(q) > len(p) and nests(p, q) for q in proposals)]
    # resolve overlaps: more cells first; among as many, cells that hold more (a heading with its text and its
    # description) before bare ones; then larger cells
    # (cells found on drawn cards or the designer's groups come first: an invisible frame or a heading inside a card
    # is a part of that card, and a cell without its card would move its text and leave the card behind)
    proposals.sort(key=lambda cells: (rank.get(id(cells), 2), -len(cells), -sum(len(c.member_ids) for c in cells) / max(len(cells), 1), -sum(c.bbox.area for c in cells)))
    groups: list[RepeatGroup] = []
    for cells in proposals:
        ids = {i for c in cells for i in c.member_ids}
        if ids & used:
            # what is left of a proposal another one took part of: its untouched cells, when they still repeat
            cells = [c for c in cells if not set(c.member_ids) & used]
            if len(cells) < 2:
                continue
            ids = {i for c in cells for i in c.member_ids}
        used |= ids
        cells = _without_shared(cells, by_id0)
        groups.append(_build_group(f"g{len(groups) + 1}", cells, slide_w, slide_h, safe, art_boxes))
    return groups


def _without_shared(cells: list[Cell], by_id: dict) -> list[Cell]:
    """A shape that runs across the other cells of its row (VK Tech p48: the timeline's arrow, picked up by the
    middle step) is the row's, not that cell's: the cell is what stands at its own place. Left in, the arrow made the
    middle step the widest and the first in reading order — the first item went to the middle of the line."""
    out = []
    for c in cells:
        others = [o.bbox for o in cells if o is not c]
        keep = []
        for i in c.member_ids:
            sh = by_id.get(i)
            if sh is not None and i != c.anchor_id and len(c.member_ids) > 1:
                b = sh.bbox
                crosses = sum(1 for ob in others if min(b.x2, ob.x2) - max(b.x, ob.x) >= 0.3 * ob.w and min(b.y2, ob.y2) - max(b.y, ob.y) >= 0.3 * min(ob.h, b.h))
                if crosses >= 1 and b.area < 0.5 * sum(o.area for o in others):
                    continue
            keep.append(i)
        if len(keep) == len(c.member_ids) or not keep:
            out.append(c)
            continue
        box = None
        for i in keep:
            sh = by_id.get(i)
            if sh is not None:
                box = sh.bbox if box is None else box.union(sh.bbox)
        out.append(Cell(c.anchor_id, keep, box or c.bbox, c.composition, [i for i in c.inner if i in keep]))
    return out


def group_membership(groups: list[RepeatGroup]) -> dict[str, tuple[str, int]]:
    """shape_id → (group_id, cell_index)."""
    out: dict[str, tuple[str, int]] = {}
    for g in groups:
        for ci, cell in enumerate(g.member_shape_ids):
            for sid in cell:
                out[sid] = (g.id, ci)
    return out
