"""Resize a repeat group (row/column/grid of equal cells) to the number of content items."""

from __future__ import annotations

import copy
from typing import Optional

from lxml import etree
from pptx.slide import Slide

from verstka.rendering.deck import element_bbox, is_nested, remove_element, renumber_ids, set_element_pos, shift_element, slide_shape_elements
from verstka.schemas.common import Bbox
from verstka.schemas.template import RepeatGroup


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


def adjust_group(slide: Slide, group: RepeatGroup, n_needed: int, slide_w: int, slide_h: int, next_id: int) -> tuple[list[list[etree._Element]], int]:
    """Delete or duplicate cells so that exactly n cells remain (clamped to [1, max_n]).

    Returns (cells in reading order, next free shape id). Nested (grouped) cells are left untouched.
    """
    cells = cells_elements(slide, group)
    if not cells:
        return cells, next_id
    nested = any(is_nested(e) for c in cells for e in c)
    n = max(1, min(n_needed, max(group.max_n, len(cells))))
    n_orig = len(cells)
    if nested:
        # grouped cells: deleting members is safe, moving/duplicating them is not (child coordinate space)
        cells.sort(key=lambda c: ((cell_bbox(c).y if cell_bbox(c) else 0), (cell_bbox(c).x if cell_bbox(c) else 0)))
        if n < n_orig:
            for c in cells[n:]:
                for e in c:
                    remove_element(e)
            cells = cells[:n]
        return cells, next_id
    # order cells by reading order
    def key(c):
        b = cell_bbox(c)
        return (round(b.y / max(slide_h * 0.04, 1)), b.x) if b else (0, 0)

    cells.sort(key=key)
    if n < n_orig:
        for c in cells[n:]:
            for e in c:
                remove_element(e)
        cells = cells[:n]
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
        ys = sorted({round(b.y / max(slide_h * 0.02, 1)) for b in boxes})
        cols = len(xs) if group.axis == "grid" else (n_orig if group.axis == "row" else 1)
        tree = cells[-1][0].getparent()
        for k in range(n_orig, n):
            src = cells[-1]
            src_box = cell_bbox(src)
            new_els = []
            for e in src:
                ne = copy.deepcopy(e)
                next_id = renumber_ids(ne, next_id)
                new_els.append(ne)
            if step is not None:
                dx, dy = step
            else:
                col = k % cols
                row = k // cols
                first = boxes[0]
                gx = (boxes[min(1, len(boxes) - 1)].x - first.x) if cols > 1 else 0
                gy = (boxes[min(cols, len(boxes) - 1)].y - first.y) if len(boxes) > cols else int(ch * 1.15)
                target_x = first.x + col * gx
                target_y = first.y + row * gy
                dx, dy = target_x - src_box.x, target_y - src_box.y
            new_box = cell_bbox(new_els)
            if new_box is not None and (new_box.x + dx + new_box.w > slide_w * 0.995 or new_box.y + dy + new_box.h > slide_h * 0.995 or new_box.x + dx < 0):
                break  # no room on the slide for another cell
            for ne in new_els:
                shift_element(ne, dx, dy)
                anchor = src[-1]
                anchor.addnext(ne) if anchor.getparent() is tree else tree.append(ne)
            cells.append(new_els)
            boxes.append(cell_bbox(new_els))
    # redistribute evenly across the original span when fewer cells remain (row/column only)
    if n < n_orig and n >= 2 and group.axis == "row":
        boxes = [cell_bbox(c) for c in cells]
        if group.axis == "row":
            span_x0 = boxes[0].x
            span_x1 = int(group.cell_bbox.x * slide_w) + (n_orig - 1) * (boxes[0].w + int(group.gap * slide_w)) + boxes[0].w
            gap = (span_x1 - span_x0 - n * boxes[0].w) / (n - 1)
            for i, c in enumerate(cells):
                target = int(span_x0 + i * (boxes[0].w + gap))
                dx = target - boxes[i].x
                for e in c:
                    shift_element(e, dx, 0)
        else:
            span_y0 = boxes[0].y
            span_y1 = int(group.cell_bbox.y * slide_h) + (n_orig - 1) * (boxes[0].h + int(group.gap * slide_h)) + boxes[0].h
            gap = (span_y1 - span_y0 - n * boxes[0].h) / (n - 1)
            for i, c in enumerate(cells):
                target = int(span_y0 + i * (boxes[0].h + gap))
                dy = target - boxes[i].y
                for e in c:
                    shift_element(e, 0, dy)
    return cells, next_id
