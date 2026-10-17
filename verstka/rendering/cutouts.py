"""Cut-out art inside a picture ground (live QA, L1).

A template whose whole background is one picture — Blueprint: a blue grid, a paper sheet on it and a pencil and an
eraser lying on the sheet — keeps its decor inside the ground, where the layer rules (`layers.art_layers`) see only a
ground and no art. The objects are found by their pixels: on the sheet the content stands on (the ground's own colour
over the slide's middle), the blobs of another colour large enough to be an object, not a texture. A chart, a table or
a heading of a data slide keeps clear of them like of any other decor."""

from __future__ import annotations

import io
import logging
from typing import Optional

from verstka.schemas.common import Bbox

log = logging.getLogger(__name__)

GRID_W, GRID_H = 192, 108  # the ground read on this grid (one cell ≈ 0.5 % of the slide)
COLOR_DIST = 26  # RGB distance from the sheet's colour past which a cell is paint, not the sheet (a pale eraser: ≈ 50)
EDGE_JUMP = 10  # the median colour jump across a blob's edge under which it is a shade, not an object
MIN_CELLS = 40  # a blob smaller than this (≈ 0.2 % of the slide) is a texture, a speck — not an object
_CACHE: dict = {}


def _ground_pictures(slide) -> list[tuple[object, object, Bbox]]:
    """(part, blip element, box) of the pictures laid under the whole slide — the ground — by the slide, its layout
    or its master: a full-slide `pic` or the background's picture fill."""
    from verstka.rendering.layers import drawn_layers

    out = []
    try:
        layers = drawn_layers(slide)
    except Exception:  # noqa: BLE001
        layers = []
    owners = {"slide": slide, "layout": slide.slide_layout, "master": slide.slide_layout.slide_master}
    for lay in layers:
        if lay.kind != "pic" or lay.placeholder or lay.cover < 0.85:
            continue
        blip = next(iter(lay.el.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")), None)
        if blip is not None:
            out.append((owners[lay.source].part, blip, lay.box))
    if not out:
        W, H = int(slide.part.package.presentation_part.presentation.slide_width), int(slide.part.package.presentation_part.presentation.slide_height)
        for owner in (slide, slide.slide_layout, slide.slide_layout.slide_master):
            bg = owner._element.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}bg")
            blip = next(iter(bg.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")), None) if bg is not None else None
            if blip is not None:
                out.append((owner.part, blip, Bbox(x=0, y=0, w=W, h=H)))
                break
    return out


def _grid(part, blip):
    """The picture as a GRID_W × GRID_H list of RGB rows (its crop respected), or None."""
    from PIL import Image

    rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
    if not rid:
        return None
    img_part = part.related_part(rid)
    src = blip.getparent().find("{http://schemas.openxmlformats.org/drawingml/2006/main}srcRect")
    crop = tuple(int(src.get(k) or 0) / 100000 for k in ("l", "t", "r", "b")) if src is not None else (0.0, 0.0, 0.0, 0.0)
    key = (img_part.partname, len(img_part.blob), crop)
    if key in _CACHE:
        return _CACHE[key]
    im = Image.open(io.BytesIO(img_part.blob))
    im.draft("RGB", (GRID_W * 4, GRID_H * 4))
    im = im.convert("RGBA")
    iw, ih = im.size
    l, t, r, b = crop
    im = im.crop((int(l * iw), int(t * ih), max(int((1 - r) * iw), int(l * iw) + 1), max(int((1 - b) * ih), int(t * ih) + 1)))
    ground = Image.new("RGBA", im.size, (255, 255, 255, 255))
    ground.alpha_composite(im)
    small = ground.convert("RGB").resize((GRID_W, GRID_H))
    raw = small.tobytes()
    px = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
    rows = [px[y * GRID_W:(y + 1) * GRID_W] for y in range(GRID_H)]
    _CACHE[key] = rows
    return rows


def _dist(a, b) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _sheet(rows, box: Bbox, area: Optional[Bbox]):
    """(paint mask, the area's cells, the sheet's cells) of a ground read on the grid: the sheet — the commonest colour
    (in 16-step bins) under `area` — and its extent, the columns and rows where its colour holds (paint off the sheet,
    the grid around it, is the ground, not an object on the sheet). None without a sheet."""
    cw, ch = box.w / GRID_W, box.h / GRID_H
    a = area or Bbox(x=box.x + box.w // 5, y=box.y + box.h // 4, w=box.w * 3 // 5, h=box.h // 2)
    ax0, ax1 = max(0, int((a.x - box.x) / cw)), min(GRID_W, int((a.x2 - box.x) / cw) + 1)
    ay0, ay1 = max(0, int((a.y - box.y) / ch)), min(GRID_H, int((a.y2 - box.y) / ch) + 1)
    if ax1 - ax0 < 4 or ay1 - ay0 < 4:
        return None
    counts: dict = {}
    for y in range(ay0, ay1):
        for x in range(ax0, ax1):
            p = rows[y][x]
            k = (p[0] // 16, p[1] // 16, p[2] // 16)
            counts[k] = counts.get(k, 0) + 1
    top = max(counts, key=counts.get)
    if counts[top] < 0.4 * (ax1 - ax0) * (ay1 - ay0):
        return None  # no sheet: a busy photo under the whole area is a ground of its own kind (`content_over_art`)
    sheet = (top[0] * 16 + 8, top[1] * 16 + 8, top[2] * 16 + 8)
    paint = [[_dist(rows[y][x], sheet) > COLOR_DIST for x in range(GRID_W)] for y in range(GRID_H)]
    cols = [x for x in range(GRID_W) if sum(1 for y in range(GRID_H) if not paint[y][x]) >= 0.3 * GRID_H]
    lines = [y for y in range(GRID_H) if sum(1 for x in range(GRID_W) if not paint[y][x]) >= 0.3 * GRID_W]
    if not cols or not lines:
        return None
    return paint, (ax0, ax1, ay0, ay1), (min(cols), max(cols) + 1, min(lines), max(lines) + 1)


def sheet_box(slide, area: Optional[Bbox] = None) -> Optional[Bbox]:
    """The sheet a picture ground lays under the content (Blueprint's paper on its grid), in slide EMU — None when the
    ground is no picture, has no sheet, or the sheet is the whole slide."""
    try:
        grounds = _ground_pictures(slide)
    except Exception:  # noqa: BLE001
        return None
    for part, blip, box in grounds:
        try:
            rows = _grid(part, blip)
        except Exception:  # noqa: BLE001
            rows = None
        got = _sheet(rows, box, area) if rows else None
        if got is None:
            continue
        sx0, sx1, sy0, sy1 = got[2]
        if (sx0, sy0, sx1, sy1) == (0, 0, GRID_W, GRID_H):
            return None
        cw, ch = box.w / GRID_W, box.h / GRID_H
        return Bbox(x=int(box.x + sx0 * cw), y=int(box.y + sy0 * ch), w=int((sx1 - sx0) * cw), h=int((sy1 - sy0) * ch))
    return None


def cutout_boxes(slide, area: Optional[Bbox] = None, pad: Optional[int] = None) -> list[Bbox]:
    """The boxes (slide EMU, `pad` around them) of the objects the slide's picture ground draws on the sheet under
    `area` (default: the middle of the slide): blobs of another colour than the sheet's, touching the area. [] when
    the slide has no picture ground or the ground is plain."""
    try:
        grounds = _ground_pictures(slide)
    except Exception:  # noqa: BLE001
        log.debug("ground pictures not read", exc_info=True)
        return []
    out: list[Bbox] = []
    for part, blip, box in grounds:
        try:
            rows = _grid(part, blip)
        except Exception:  # noqa: BLE001 - an unreadable picture (EMF, SVG): no cut-outs read
            rows = None
        if not rows:
            continue
        cw, ch = box.w / GRID_W, box.h / GRID_H
        got = _sheet(rows, box, area)
        if got is None:
            continue
        paint, (ax0, ax1, ay0, ay1), (sx0, sx1, sy0, sy1) = got
        seen = [[not (sx0 <= x < sx1 and sy0 <= y < sy1) for x in range(GRID_W)] for y in range(GRID_H)]
        for y0 in range(ay0, ay1):
            for x0 in range(ax0, ax1):
                if not paint[y0][x0] or seen[y0][x0]:
                    continue
                stack, cells = [(x0, y0)], []
                seen[y0][x0] = True
                while stack:
                    x, y = stack.pop()
                    cells.append((x, y))
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if 0 <= nx < GRID_W and 0 <= ny < GRID_H and paint[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                if len(cells) < MIN_CELLS:
                    continue
                # an object has an edge: the colour jumps where it ends; a shade of the sheet (a soft gradient in a
                # corner) fades into it cell by cell
                jumps = [_dist(rows[y][x], rows[ny][nx]) for x, y in cells for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                         if 0 <= nx < GRID_W and 0 <= ny < GRID_H and not paint[ny][nx]]
                if not jumps or sorted(jumps)[len(jumps) // 2] < EDGE_JUMP:
                    continue
                xs, ys = [c[0] for c in cells], [c[1] for c in cells]
                bx0, bx1, by0, by1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
                if (bx1 - bx0) * (by1 - by0) >= 0.5 * GRID_W * GRID_H:
                    continue  # the paint around the whole sheet (its frame, the grid), not an object on it
                p_ = pad if pad is not None else int(0.012 * box.w)
                out.append(Bbox(x=int(box.x + bx0 * cw) - p_, y=int(box.y + by0 * ch) - p_, w=int((bx1 - bx0) * cw) + 2 * p_, h=int((by1 - by0) * ch) + 2 * p_))
    return out
