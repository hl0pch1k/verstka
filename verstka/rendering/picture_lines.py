"""Lines and panel edges drawn inside a slide's ground picture (qa4 NEW-L1).

A template may draw its frame into the background picture of a layout: VK Tech's «3_Содержание» lays a full-slide
picture with a white panel and a hairline down its middle under every slide of that layout. The layer rules see one
calm ground there; a composed row of cards laid over it had the divider run through the cards and their caption, and
the cards overhang the panel's edge. The lines are found by their pixels, like the cut-outs (`cutouts.py`): a column
(a row) of the picture whose pixels step away from both neighbours — a hairline — or from one side — a panel's edge —
over a long run. Content keeps clear of them; the audit sees them (`content_over_art`)."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

from verstka.rendering.lru import Lru, blob_key
from verstka.schemas.common import Bbox

log = logging.getLogger(__name__)

READ_W = 960  # the picture is read at this width (a 1920 px hairline stays a step of one or two columns)
STEP = 7.0  # a luminance step (0–255) past which a pixel stands off its neighbours: a #E1E5EE hairline on white is ≈ 20
MIN_RUN = 0.22  # a line runs at least this share of the picture's height (width) without a break …
GAP = 0.012  # … gaps of this share bridged (anti-aliasing, a corner's curve)
EDGE_MARGIN = 0.012  # lines this close to the picture's border are its border, not a line inside it
_CACHE = Lru(48)  # lines and colour grids by picture content and crop (a grid ≈ 1.5 MB), least recently used out first


@dataclass(frozen=True)
class PictureLine:
    """A straight line of a ground picture in slide EMU: `vertical` at x = `pos` from `start` to `end` (y), or
    horizontal at y = `pos` from `start` to `end` (x); `strength` — its mean luminance step."""

    vertical: bool
    pos: int
    start: int
    end: int
    strength: float

    def box(self, pad: int = 0) -> Bbox:
        if self.vertical:
            return Bbox(x=self.pos - pad, y=self.start, w=2 * pad + 1, h=max(self.end - self.start, 1))
        return Bbox(x=self.start, y=self.pos - pad, w=max(self.end - self.start, 1), h=2 * pad + 1)

    def crosses(self, box: Bbox, inset: float = 0.12, span: float = 0.3) -> bool:
        """The line runs through the inside of `box` (not along its margins: `inset` of its side on each side) over
        at least `span` of the box's extent along the line."""
        if self.vertical:
            if not (box.x + inset * box.w < self.pos < box.x2 - inset * box.w):
                return False
            return min(self.end, box.y2) - max(self.start, box.y) >= span * box.h
        if not (box.y + inset * box.h < self.pos < box.y2 - inset * box.h):
            return False
        return min(self.end, box.x2) - max(self.start, box.x) >= span * box.w


def _runs(mask_col, min_len: int, gap: int) -> list[tuple[int, int]]:
    """(start, end) of the runs of True in a 1-D boolean array, gaps up to `gap` bridged, at least `min_len` long."""
    import numpy as np

    idx = np.flatnonzero(mask_col)
    if idx.size == 0:
        return []
    out = []
    s = p = int(idx[0])
    for v in idx[1:]:
        v = int(v)
        if v - p > gap + 1:
            if p - s + 1 >= min_len:
                out.append((s, p + 1))
            s = v
        p = v
    if p - s + 1 >= min_len:
        out.append((s, p + 1))
    return out


def _lum(blob: bytes, crop: tuple[float, float, float, float]):
    """The picture's luminance (over white where it is transparent) as a float array READ_W wide, crop respected."""
    import numpy as np
    from PIL import Image

    im = Image.open(io.BytesIO(blob))
    im.draft("RGB", (READ_W * 2, READ_W * 2))
    im = im.convert("RGBA")
    iw, ih = im.size
    l, t, r, b = crop
    im = im.crop((int(l * iw), int(t * ih), max(int((1 - r) * iw), int(l * iw) + 1), max(int((1 - b) * ih), int(t * ih) + 1)))
    ground = Image.new("RGBA", im.size, (255, 255, 255, 255))
    ground.alpha_composite(im)
    w, h = ground.size
    if w > READ_W:
        ground = ground.resize((READ_W, max(1, int(round(h * READ_W / w)))), Image.BILINEAR)
    return np.asarray(ground.convert("L"), dtype=np.float32)


def picture_lines(blob: bytes, crop: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)) -> list[tuple[bool, float, float, float, float]]:
    """The long straight lines of a picture, as (vertical, pos, start, end, strength) in shares of the picture (pos
    across, start/end along the line). A hairline (a column whose pixels step away from both neighbours) or an edge (a
    step between two calm sides, a panel's border) counts; texture, a photo's detail and gradients do not: the step
    must hold, unbroken, over MIN_RUN of the picture. Cached per picture and crop."""
    import numpy as np

    key = ("lines", blob_key(blob), crop)
    got = _CACHE.get(key)
    if got is not None:
        return got
    out: list[tuple[bool, float, float, float, float]] = []
    try:
        lum = _lum(blob, crop)
    except Exception:  # noqa: BLE001 - an unreadable picture (EMF, SVG): no lines read
        return _CACHE.put(key, out)
    h, w = lum.shape
    if h < 20 or w < 20:
        return _CACHE.put(key, out)
    for vertical in (True, False):
        a = lum if vertical else lum.T  # columns of `a` run along the line
        n_across, n_along = a.shape[1], a.shape[0]
        # a hairline: off both neighbours two pixels away; an edge: a step between the sides, calm on each side
        left, right = a[:, :-4], a[:, 4:]
        mid = a[:, 2:-2]
        hair = (np.abs(mid - left) >= STEP) & (np.abs(mid - right) >= STEP) & (np.sign(mid - left) == np.sign(mid - right))
        step = np.abs(a[:, 3:-1] - a[:, 1:-3])
        calm_l = np.abs(a[:, 1:-3] - a[:, :-4]) < STEP * 0.5
        calm_r = np.abs(a[:, 4:] - a[:, 3:-1]) < STEP * 0.5
        edge = (step >= STEP) & calm_l & calm_r
        hit = hair | edge  # aligned: column j of both is picture column j + 2
        min_len = max(8, int(MIN_RUN * n_along))
        gap = max(1, int(GAP * n_along))
        cols = np.flatnonzero(hit.sum(axis=0) >= min_len)
        found: list[tuple[int, int, int, float]] = []
        for j in cols:
            for s, e in _runs(hit[:, j], min_len, gap):
                strength = float(np.abs(mid[s:e, j] - (left[s:e, j] + right[s:e, j]) / 2).mean()) if hair[s:e, j].mean() > 0.5 else float(step[s:e, j].mean())
                found.append((int(j) + 2, s, e, strength))
        # neighbouring columns of one line (anti-aliased, or a two-pixel rule): one line at its strongest column
        found.sort()
        merged: list[list] = []
        for c, s, e, st in found:
            last = merged[-1] if merged else None
            if last is not None and c - last[0] <= 3 and min(e, last[2]) - max(s, last[1]) > 0.5 * min(e - s, last[2] - last[1]):
                if st > last[3]:
                    last[0] = c
                last[1], last[2], last[3] = min(s, last[1]), max(e, last[2]), max(st, last[3])
                continue
            merged.append([c, s, e, st])
        for c, s, e, st in merged:
            pos = c / float(n_across)
            if pos < EDGE_MARGIN or pos > 1 - EDGE_MARGIN:
                continue
            out.append((vertical, pos, s / float(n_along), e / float(n_along), st))
    return _CACHE.put(key, out)


def _grounds(slide) -> list[tuple[object, object, Bbox]]:
    from verstka.rendering.cutouts import _ground_pictures

    try:
        return _ground_pictures(slide)
    except Exception:  # noqa: BLE001
        return []


def is_photo_blob(blob: bytes) -> bool:
    """A photograph rather than drawn art (`synth._is_photo`'s measure): an opaque raster with many colours and fine
    mid-contrast texture, on a 128 px thumbnail. Cached by content."""
    key = ("photo", blob_key(blob))
    got = _CACHE.get(key)
    if got is not None:
        return got
    out = False
    try:
        import numpy as np
        from PIL import Image

        im = Image.open(io.BytesIO(blob)).convert("RGBA")
        im.thumbnail((128, 128))
        a = np.asarray(im)
        op = a[..., 3] > 200
        if op.mean() >= 0.5 and op.sum() >= 400:
            rgb = a[..., :3][op].astype(np.int32) >> 3
            colours = len(np.unique(rgb[:, 0] * 1024 + rgb[:, 1] * 32 + rgb[:, 2]))
            g = np.asarray(im.convert("L"), dtype=np.float32)
            d = np.abs(np.diff(g, axis=1))
            both = op[:, 1:] & op[:, :-1]
            texture = float(((d > 4) & (d < 40))[both].mean()) if both.any() else 0.0
            out = colours >= 500 and texture >= 0.2
    except Exception:  # noqa: BLE001 - an unreadable picture: no photograph
        out = False
    return _CACHE.put(key, out)


def ground_is_photo(slide) -> bool:
    """Whether a picture under the whole slide is a photograph: its «marks» are the photo itself — text over it is
    `content_over_art`'s finding, not a designed mark's (lo_candy: candies under every line, counted twice)."""
    for part, blip, _box in _grounds(slide):
        rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        if not rid:
            continue
        try:
            if is_photo_blob(part.related_part(rid).blob):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def ground_lines(slide) -> list[PictureLine]:
    """The lines the pictures under the whole slide (its ground: a full-slide picture of the slide, its layout or its
    master, or the background's picture fill) draw, in slide EMU."""
    out: list[PictureLine] = []
    for part, blip, box in _grounds(slide):
        rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        if not rid:
            continue
        try:
            img = part.related_part(rid)
        except Exception:  # noqa: BLE001
            continue
        src = blip.getparent().find("{http://schemas.openxmlformats.org/drawingml/2006/main}srcRect")
        crop = tuple(int(src.get(k) or 0) / 100000 for k in ("l", "t", "r", "b")) if src is not None else (0.0, 0.0, 0.0, 0.0)
        for vertical, pos, s, e, st in picture_lines(img.blob, crop):
            if vertical:
                out.append(PictureLine(True, int(box.x + pos * box.w), int(box.y + s * box.h), int(box.y + e * box.h), st))
            else:
                out.append(PictureLine(False, int(box.y + pos * box.h), int(box.x + s * box.w), int(box.x + e * box.w), st))
    return out


def lines_through(slide, area: Bbox, inset: float = 0.04, span: float = 0.3) -> list[PictureLine]:
    """The ground's lines that run through the inside of `area` (a content band, a card)."""
    return [ln for ln in ground_lines(slide) if ln.crosses(area, inset=inset, span=span)]


def clear_of_lines(slide, area: Bbox, pad: Optional[int] = None) -> Optional[Bbox]:
    """The largest part of `area` no ground line runs through (the line `pad` aside); None when no line crosses it."""
    from verstka.rendering.layers import largest_free

    hits = lines_through(slide, area)
    if not hits:
        return None
    W = int(slide.part.package.presentation_part.presentation.slide_width)
    p = pad if pad is not None else int(0.015 * W)
    return largest_free(area, [ln.box(p) for ln in hits])


# ---- marks the ground picture draws inside a sample's cells (qa4 NEW-L3) ----------------------------------------------

MARK_DIST = 24  # RGB distance from a cell's own colour past which a pixel is a mark (pale «01» on white: ≈ 35)
MARK_MIN = 0.015  # a mark covers at least this share of its cell (a speck, an anti-aliased corner is none)
MARK_EDGE = 0.05  # the band along a cell's sides where its own border runs: never a mark


def _rgb(blob: bytes, crop: tuple[float, float, float, float]):
    import numpy as np
    from PIL import Image

    im = Image.open(io.BytesIO(blob))
    im.draft("RGB", (READ_W * 2, READ_W * 2))
    im = im.convert("RGBA")
    iw, ih = im.size
    l, t, r, b = crop
    im = im.crop((int(l * iw), int(t * ih), max(int((1 - r) * iw), int(l * iw) + 1), max(int((1 - b) * ih), int(t * ih) + 1)))
    ground = Image.new("RGBA", im.size, (255, 255, 255, 255))
    ground.alpha_composite(im)
    w, h = ground.size
    if w > READ_W // 2:
        ground = ground.resize((READ_W // 2, max(1, int(round(h * (READ_W // 2) / w)))), Image.BILINEAR)
    return np.asarray(ground.convert("RGB"), dtype=np.int32)


def _blobs_union(mask, min_cells: int) -> Optional[tuple[int, int, int, int, int]]:
    """(x0, y0, x1, y1, cells) of the union of the 4-connected blobs of a boolean array at least `min_cells` large (the
    two digits of «01» are two blobs: one mark)."""
    import numpy as np

    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best = None
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        stack = [(x0, y0)]
        seen[y0, x0] = True
        n, bx0, by0, bx1, by1 = 0, x0, y0, x0, y0
        while stack:
            x, y = stack.pop()
            n += 1
            bx0, by0, bx1, by1 = min(bx0, x), min(by0, y), max(bx1, x), max(by1, y)
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((nx, ny))
        if n < min_cells:
            continue
        if best is None:
            best = (bx0, by0, bx1 + 1, by1 + 1, n)
        else:
            best = (min(best[0], bx0), min(best[1], by0), max(best[2], bx1 + 1), max(best[3], by1 + 1), best[4] + n)
    return best


def cell_marks(slide, cells: list[Bbox], sheet_share: float = 0.0) -> list[Optional[Bbox]]:
    """Per cell (slide EMU), the box of the marks the picture under the whole slide draws inside it — VK Tech's «01»…«04»
    watermarks in the cards its layout paints — or None. A mark is a blob of another colour than the cell's own (its
    commonest colour), off the band along the cell's sides where its border runs, covering at least 1.5 % of it."""
    import numpy as np

    out: list[Optional[Bbox]] = [None] * len(cells)
    for part, blip, box in _grounds(slide):
        rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        if not rid:
            continue
        try:
            img = part.related_part(rid)
            src = blip.getparent().find("{http://schemas.openxmlformats.org/drawingml/2006/main}srcRect")
            crop = tuple(int(src.get(k) or 0) / 100000 for k in ("l", "t", "r", "b")) if src is not None else (0.0, 0.0, 0.0, 0.0)
            key = ("rgb", blob_key(img.blob), crop)
            rgb = _CACHE.get(key)
            if rgb is None:
                rgb = _CACHE.put(key, _rgb(img.blob, crop))
        except Exception:  # noqa: BLE001 - an unreadable picture: no marks read
            continue
        ph, pw = rgb.shape[:2]
        for i, c in enumerate(cells):
            if out[i] is not None or box.w <= 0 or box.h <= 0:
                continue
            x0 = int((c.x - box.x) / box.w * pw)
            x1 = int((c.x2 - box.x) / box.w * pw)
            y0 = int((c.y - box.y) / box.h * ph)
            y1 = int((c.y2 - box.y) / box.h * ph)
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, pw), min(y1, ph)
            if x1 - x0 < 12 or y1 - y0 < 12:
                continue
            reg = rgb[y0:y1, x0:x1]
            q16 = (reg // 16).reshape(-1, 3)
            vals, counts = np.unique(q16, axis=0, return_counts=True)
            if counts.max() < sheet_share * q16.shape[0]:
                continue  # no calm sheet under the cell (a photo, a busy texture): its marks are not told from it
            own = vals[int(np.argmax(counts))] * 16 + 8
            dist = np.sqrt(((reg - own) ** 2).sum(axis=2))
            mask = dist > MARK_DIST
            ex, ey = max(1, int(MARK_EDGE * (x1 - x0))), max(1, int(MARK_EDGE * (y1 - y0)))
            mask[:ey, :] = False
            mask[-ey:, :] = False
            mask[:, :ex] = False
            mask[:, -ex:] = False
            if mask.sum() < MARK_MIN * mask.size:
                continue
            blob = _blobs_union(mask, max(4, int(0.003 * mask.size)))
            if blob is None or blob[4] < MARK_MIN * mask.size:
                continue
            bx0, by0, bx1, by1, _ = blob
            out[i] = Bbox(x=int(box.x + (x0 + bx0) / pw * box.w), y=int(box.y + (y0 + by0) / ph * box.h), w=max(int((bx1 - bx0) / pw * box.w), 1), h=max(int((by1 - by0) / ph * box.h), 1))
    return out


def mark_share(slide, cell: Bbox, inner: Bbox, sheet_share: float = 0.0) -> Optional[float]:
    """The share of `inner` (a line's letters, slide EMU) the marks of the picture under the whole slide cover —
    measured, as `cell_marks` finds them, against the commonest colour of `cell` (the line with room around it). None
    when no picture ground is read or no calm sheet lies under the cell. A watermark digit under a card's text covers
    a good part of the letters' band; a blot under the line's descenders or the specks of an old paper do not."""
    import numpy as np

    for part, blip, box in _grounds(slide):
        rid = blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
        if not rid or box.w <= 0 or box.h <= 0:
            continue
        try:
            img = part.related_part(rid)
            src = blip.getparent().find("{http://schemas.openxmlformats.org/drawingml/2006/main}srcRect")
            crop = tuple(int(src.get(k) or 0) / 100000 for k in ("l", "t", "r", "b")) if src is not None else (0.0, 0.0, 0.0, 0.0)
            key = ("rgb", blob_key(img.blob), crop)
            rgb = _CACHE.get(key)
            if rgb is None:
                rgb = _CACHE.put(key, _rgb(img.blob, crop))
        except Exception:  # noqa: BLE001 - an unreadable picture: no marks read
            continue
        ph, pw = rgb.shape[:2]

        def px(b: Bbox) -> tuple[int, int, int, int]:
            x0, x1 = int((b.x - box.x) / box.w * pw), int((b.x2 - box.x) / box.w * pw)
            y0, y1 = int((b.y - box.y) / box.h * ph), int((b.y2 - box.y) / box.h * ph)
            return max(x0, 0), max(y0, 0), min(x1, pw), min(y1, ph)

        x0, y0, x1, y1 = px(cell)
        if x1 - x0 < 12 or y1 - y0 < 12:
            continue
        q16 = (rgb[y0:y1, x0:x1] // 16).reshape(-1, 3)
        vals, counts = np.unique(q16, axis=0, return_counts=True)
        if counts.max() < sheet_share * q16.shape[0]:
            return None
        own = vals[int(np.argmax(counts))] * 16 + 8
        ix0, iy0, ix1, iy1 = px(inner)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        reg = rgb[iy0:iy1, ix0:ix1]
        return float((np.sqrt(((reg - own) ** 2).sum(axis=2)) > MARK_DIST).mean())
    return None


def designed_lines(lines: list[PictureLine], manifest, layout_part: Optional[str], W: int, H: int) -> list[PictureLine]:
    """The lines no text slot of the template's own samples on this layout crosses: a line the template writes over
    (ЛЦТ's pale towers at the right, under its wide headings) is part of the ground it designed for text; a line no
    sample writes over (VK Tech's divider between its two panels) is a line content must not cross."""
    slots = []
    for p in getattr(manifest, "patterns", []) or []:
        if layout_part and p.layout_part and p.layout_part != layout_part:
            continue
        for sl in p.slots:
            role = getattr(sl.role, "value", sl.role)
            if role in ("title", "subtitle", "body", "bullet_list", "card_title", "card_body", "number", "number_label", "caption"):
                slots.append(Bbox(x=int(sl.bbox.x * W), y=int(sl.bbox.y * H), w=max(int(sl.bbox.w * W), 1), h=max(int(sl.bbox.h * H), 1)))
    return [ln for ln in lines if not any(ln.crosses(b, inset=0.08, span=0.6) for b in slots)]
