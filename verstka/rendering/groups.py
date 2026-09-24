"""Resize a repeat group (row/column/grid of equal cells) to the number of content items."""

from __future__ import annotations

import copy
from typing import Optional

from lxml import etree
from pptx.slide import Slide

from verstka.analysis.xmlns import q
from verstka.rendering.deck import element_bbox, is_nested, remove_element, renumber_ids, set_element_pos, shift_element, slide_shape_elements
from verstka.schemas.common import Bbox
from verstka.schemas.template import RepeatGroup

_DRAWABLE = {"sp", "pic", "grpSp", "graphicFrame", "cxnSp"}


def cells_elements(slide: Slide, group: RepeatGroup) -> list[list[etree._Element]]:
    by_id = slide_shape_elements(slide)
    cells: list[list[etree._Element]] = []
    for cell in group.member_shape_ids:
        els = [by_id[sid] for sid in cell if sid in by_id]
        if els:
            cells.append(els)
    return cells


def cell_bbox(els: list[etree._Element]) -> Optional[Bbox]:
    boxes = [element_bbox(e) for e in els]
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return None
    x = min(b[0] for b in boxes)
    y = min(b[1] for b in boxes)
    x2 = max(b[0] + b[2] for b in boxes)
    y2 = max(b[1] + b[3] for b in boxes)
    return Bbox(x=x, y=y, w=x2 - x, h=y2 - y)


def reading_order_key(cells: list[list[etree._Element]], slide_h: int):
    """Reading order for cells: rows top to bottom (a row = cells whose tops differ by less than half a cell height
    or 4% of the slide), cells left to right inside a row. Rounding the top alone split rows whose cells differ by
    a few EMU, which scrambled the item order and the companion-cell mapping."""
    boxes = {id(c): cell_bbox(c) for c in cells}
    band_of: dict[int, int] = {}
    band, band_y, band_h = -1, None, 0
    for c in sorted((c for c in cells if boxes[id(c)] is not None), key=lambda c: boxes[id(c)].y):
        b = boxes[id(c)]
        tol = max(slide_h * 0.04, 0.5 * b.h, 0.5 * band_h)
        if band_y is None or b.y - band_y > tol:
            band, band_y, band_h = band + 1, b.y, b.h
        band_of[id(c)] = band

    def key(c):
        b = boxes.get(id(c))
        if b is None:
            return (0, 0)
        return (band_of.get(id(c), 0), b.x)

    return key


def cell_riders(slide: Slide, group: RepeatGroup, cells: list[list[etree._Element]], protected_ids: Optional[set[str]] = None) -> list[list[etree._Element]]:
    """Companion shapes of every cell (icon chips, avatars, markers) that are not group members.

    A rider is a top-level spTree element whose centre along the group axis lies inside exactly one cell's band,
    whose size along the axis is at most 1.2× the cell and which sits next to the cell across the axis
    (within one cell height for a row, one cell width for a column). Chrome, titles etc. are excluded via
    `protected_ids`. Grid groups have no riders.
    """
    out: list[list[etree._Element]] = [[] for _ in cells]
    if group.axis not in ("row", "column") or not cells:
        return out
    protected = protected_ids or set()
    members = {sid for cell in group.member_shape_ids for sid in cell}
    tree = cells[0][0].getparent()
    if tree is None or etree.QName(tree).localname != "spTree":
        return out
    boxes = [cell_bbox(c) for c in cells]
    if any(b is None for b in boxes):
        return out
    row = group.axis == "row"
    for sid, el in slide_shape_elements(slide).items():
        if el.getparent() is not tree or etree.QName(el).localname not in _DRAWABLE:
            continue
        if sid in members or sid in protected:
            continue
        bb = element_bbox(el)
        if bb is None:
            continue
        cx, cy = bb[0] + bb[2] / 2, bb[1] + bb[3] / 2
        hits = []
        for i, b in enumerate(boxes):
            if row:
                inside = b.x <= cx <= b.x2 and bb[2] <= 1.2 * b.w
                near = bb[1] + bb[3] >= b.y - b.h and bb[1] <= b.y2 + b.h
            else:
                inside = b.y <= cy <= b.y2 and bb[3] <= 1.2 * b.h
                near = bb[0] + bb[2] >= b.x - b.w and bb[0] <= b.x2 + b.w
            if inside and near:
                hits.append(i)
        if len(hits) == 1:
            out[hits[0]].append(el)
    return out


def _is_card_cell(cell: list[etree._Element], box: Bbox) -> bool:
    """A cell drawn as a card: one of its shapes paints at least half of the cell area."""
    for e in cell:
        if etree.QName(e).localname not in ("sp", "grpSp"):
            continue
        b = element_bbox(e)
        if not b or b[2] * b[3] < 0.5 * box.area:
            continue
        spPr = e.find(q("p:spPr"))
        painted = spPr is not None and spPr.find(q("a:noFill")) is None and any(spPr.find(q(t)) is not None for t in ("a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill"))
        ln = spPr.find(q("a:ln")) if spPr is not None else None
        outlined = ln is not None and ln.find(q("a:noFill")) is None and len(ln) > 0
        styled = e.find(q("p:style")) is not None
        if painted or outlined or styled or etree.QName(e).localname == "grpSp":
            return True
    return False


def transform_element(e: etree._Element, old: Bbox, new: Bbox, axis: str) -> None:
    """Map an element of a cell from the cell's old box to its new one along the group axis.

    Elements spanning at least half of the cell (card background, text boxes, dividers) stretch with it; small ones
    (icons, ticks, ordinals) keep their size and their anchoring — centred, left/top or right/bottom. Pictures never
    stretch: they keep their aspect ratio and only move.
    """
    b = element_bbox(e)
    if b is None:
        return
    row = axis == "row"
    pos, size = (b[0], b[2]) if row else (b[1], b[3])
    o_pos, o_size = (old.x, old.w) if row else (old.y, old.h)
    n_pos, n_size = (new.x, new.w) if row else (new.y, new.h)
    k = n_size / o_size if o_size else 1.0
    stretch = size >= 0.5 * o_size and etree.QName(e).localname != "pic"
    if stretch:
        p2, s2 = n_pos + int((pos - o_pos) * k), max(int(size * k), 1)
    else:
        centre = pos + size / 2 - o_pos
        if abs(centre - o_size / 2) <= 0.12 * o_size:
            p2 = n_pos + int(n_size / 2 - size / 2)
        elif centre > 0.6 * o_size:
            p2 = n_pos + n_size - (o_pos + o_size - pos)
        else:
            p2 = n_pos + (pos - o_pos)
        s2 = size
    cross = (new.y - old.y) if row else (new.x - old.x)
    if row:
        set_element_pos(e, x=p2, y=b[1] + cross, w=s2)
    else:
        set_element_pos(e, x=b[0] + cross, y=p2, h=s2)


def _clusters(values: list[int], tol: int) -> list[int]:
    out: list[int] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _rebalance_grid(cells: list[list[etree._Element]], riders: list[list[etree._Element]], boxes_all: list[Optional[Bbox]], slide_w: int, slide_h: int) -> None:
    """A grid that keeps fewer cells than it had rows × columns: whole rows of wider cells instead of a full row and a
    lone cell under it (a 3×2 grid with four figures becomes 2+2, not 3+1). Rows keep their places and heights."""
    n = len(cells)
    if n == 0 or any(b is None for b in boxes_all):
        return
    xs = _clusters([b.x for b in boxes_all], int(0.02 * slide_w))
    ys = _clusters([b.y for b in boxes_all], int(0.02 * slide_h))
    cols0, rows0 = len(xs), len(ys)
    if rows0 < 2 or cols0 < 2 or n <= cols0 or n % cols0 == 0:
        return
    cols = -(-n // rows0)
    if cols >= cols0:
        return
    w0 = sorted(b.w for b in boxes_all)[len(boxes_all) // 2]
    gx = max(xs[1] - xs[0] - w0, 0)
    x0, x1 = xs[0], xs[-1] + w0
    w_new = (x1 - x0 - (cols - 1) * gx) / cols
    for i, (c, r) in enumerate(zip(cells, riders)):
        old = cell_bbox(c)
        row_i, col_i = divmod(i, cols)
        if old is None or row_i >= rows0:
            continue
        new = Bbox(x=int(x0 + col_i * (w_new + gx)), y=ys[row_i], w=int(w_new), h=old.h)
        mid = Bbox(x=new.x, y=old.y, w=new.w, h=old.h)
        for e in c + r:
            if is_nested(e):
                continue
            transform_element(e, old, mid, "row")
            transform_element(e, mid, new, "column")


def adjust_group(slide: Slide, group: RepeatGroup, n_needed: int, slide_w: int, slide_h: int, next_id: int, protected_ids: Optional[set[str]] = None, origin: Optional[dict[str, str]] = None) -> tuple[list[list[etree._Element]], int]:
    """Delete or duplicate cells so that exactly n cells remain, then let rows/columns reflow over the group's span.

    Row groups (and column groups of cards) keep their span: two cards of three grow to fill it, four narrower
    cards replace three instead of merging items (cells shrink to 60% at most, which bounds n). Column groups of plain
    text rows (agenda lines) keep their rhythm and are compressed only when they run out of room. Companion shapes
    (riders, see `cell_riders`) leave and move together with their cell; ids in `protected_ids` (title, subtitle,
    chrome) are never riders. Returns (cells in reading order, next free shape id). Nested (grouped) cells are only
    deleted, never moved.
    """
    cells = cells_elements(slide, group)
    if not cells:
        return cells, next_id
    nested = any(is_nested(e) for c in cells for e in c)
    n_orig = len(cells)
    n = max(1, min(n_needed, max(group.max_n, n_orig)))
    if nested:
        # grouped cells: deleting members is safe, moving/duplicating them is not (child coordinate space)
        cells.sort(key=reading_order_key(cells, slide_h))
        if n < n_orig:
            for c in cells[n:]:
                for e in c:
                    remove_element(e)
            cells = cells[:n]
        return cells, next_id
    cells.sort(key=reading_order_key(cells, slide_h))
    riders = cell_riders(slide, group, cells, protected_ids)
    linear = group.axis in ("row", "column")
    row = group.axis == "row"
    boxes0 = [cell_bbox(c) for c in cells]
    if linear and all(b is not None for b in boxes0):
        starts = sorted((b.x if row else b.y) for b in boxes0)
        size0 = sorted((b.w if row else b.h) for b in boxes0)[len(boxes0) // 2]
        pitch0 = (starts[1] - starts[0]) if n_orig > 1 else size0 + int(group.gap * (slide_w if row else slide_h))
        gap = max(pitch0 - size0, 0)
        span_end0 = starts[-1] + size0
        edge = int((slide_w if row else slide_h) * (0.95 if row else 0.92))
        # free room runs to the slide margin; whatever stands in the band (below) cuts it short
        room_end = max(span_end0, edge)
        # never reflow over something else standing in the group's band after its last cell (a highlighted card,
        # a picture): the free room ends a gap before it
        cross0 = min((b.y if row else b.x) for b in boxes0)
        cross1 = max((b.y2 if row else b.x2) for b in boxes0)
        own = {id(e) for c in cells for e in c} | {id(e) for r in riders for e in r}
        tree0 = cells[0][0].getparent()
        for other in (tree0 if tree0 is not None else []):
            if id(other) in own or etree.QName(other).localname not in _DRAWABLE:
                continue
            ob = element_bbox(other)
            if not ob or ob[2] * ob[3] >= 0.6 * slide_w * slide_h:
                continue
            o_start, o_c0, o_c1 = (ob[0], ob[1], ob[1] + ob[3]) if row else (ob[1], ob[0], ob[0] + ob[2])
            if o_start >= span_end0 - int(0.005 * (slide_w if row else slide_h)) and o_c0 < cross1 and o_c1 > cross0:
                room_end = min(room_end, max(span_end0, o_start - gap))
        cards = any(_is_card_cell(c, b) for c, b in zip(cells, boxes0))
        n_fit = max(1, int((room_end - starts[0] + gap) // max(0.6 * size0 + gap, 1)))
        n = max(1, min(n_needed, max(n_fit, n_orig)))
    if n < n_orig:
        boxes_all = [cell_bbox(c) for c in cells]
        for c, r in zip(cells[n:], riders[n:]):
            for e in c + r:
                remove_element(e)
        cells = cells[:n]
        riders = riders[:n]
        if group.axis == "grid":
            _rebalance_grid(cells, riders, boxes_all, slide_w, slide_h)
    elif n > n_orig:
        boxes = [cell_bbox(c) for c in cells]
        cw = boxes[-1].w
        ch = boxes[-1].h
        if group.axis == "row":
            step = (cw + int(group.gap * slide_w), 0)
        elif group.axis == "column":
            step = (0, ch + int(group.gap * slide_h))
        else:
            step = None  # grid: place after the last cell following the grid
        xs = sorted({round(b.x / max(slide_w * 0.02, 1)) for b in boxes})
        cols = len(xs) if group.axis == "grid" else (n_orig if group.axis == "row" else 1)
        tree = cells[-1][0].getparent()
        order = list(tree)
        for k in range(n_orig, n):
            src = cells[-1]
            src_box = cell_bbox(src)
            new_els = []
            for e in src:
                ne = copy.deepcopy(e)
                next_id = renumber_ids(ne, next_id)
                if origin is not None:
                    # every copied shape remembers the shape it was taken from (roles and slots follow it)
                    for a, b in zip(e.iter(q("p:cNvPr")), ne.iter(q("p:cNvPr"))):
                        origin[b.get("id")] = origin.get(a.get("id"), a.get("id"))
                new_els.append(ne)
            if step is not None:
                dx, dy = step
            else:
                col = k % cols
                row_i = k // cols
                first = boxes[0]
                gx = (boxes[min(1, len(boxes) - 1)].x - first.x) if cols > 1 else 0
                gy = (boxes[min(cols, len(boxes) - 1)].y - first.y) if len(boxes) > cols else int(ch * 1.15)
                dx, dy = first.x + col * gx - src_box.x, first.y + row_i * gy - src_box.y
            new_box = cell_bbox(new_els)
            if not linear and new_box is not None and (new_box.x + dx + new_box.w > slide_w * 0.995 or new_box.y + dy + new_box.h > slide_h * 0.995 or new_box.x + dx < 0):
                break  # a grid has no room for another cell (linear groups reflow below)
            # keep the cell's own z-order: insert the copies in the source's tree order, one after another behind it
            # (new_els itself stays in member order — the clone renderer maps roles by position)
            pairs = sorted(zip(src, new_els), key=lambda t: order.index(t[0]) if t[0] in order else len(order))
            anchor = pairs[-1][0]
            for _, ne in pairs:
                shift_element(ne, dx, dy)
                if anchor.getparent() is tree:
                    anchor.addnext(ne)
                else:
                    tree.append(ne)
                anchor = ne
            cells.append(new_els)
            riders.append([])
            boxes.append(cell_bbox(new_els))
            order = list(tree)
    if linear and all(b is not None for b in boxes0) and len(cells) != n_orig:
        m = len(cells)
        if row or cards:
            end = span_end0 if m <= n_orig else min(room_end, starts[0] + m * pitch0 - gap)
            size_new = min((end - starts[0] - (m - 1) * gap) / m, 2.0 * size0)
        else:
            fits = starts[0] + m * pitch0 - gap <= room_end
            size_new = size0 if fits else (room_end - starts[0] - (m - 1) * gap) / m
        for i, (c, r) in enumerate(zip(cells, riders)):
            old = cell_bbox(c)
            if old is None:
                continue
            p_new = int(starts[0] + i * (size_new + gap))
            new = Bbox(x=p_new, y=old.y, w=int(size_new), h=old.h) if row else Bbox(x=old.x, y=p_new, w=old.w, h=int(size_new))
            if (new.x, new.y, new.w, new.h) == (old.x, old.y, old.w, old.h):
                continue
            for e in c + r:
                transform_element(e, old, new, group.axis)
    return cells, next_id
