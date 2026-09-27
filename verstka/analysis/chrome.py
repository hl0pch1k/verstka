"""Chrome detection: logos, footers, page numbers and decorations that repeat at the same place."""

from __future__ import annotations

import re
from collections import defaultdict

from verstka.analysis.shapes import ShapeInfo, looks_like_placeholder
from verstka.schemas.common import BboxFrac, ShapeKind
from verstka.schemas.template import ChromeElement

_NUM_RE = re.compile(r"^[\d\s‹›#/]+$")
_CONTENT_PH = {"title", "ctrTitle", "subTitle", "body", "obj", "pic", "chart", "tbl", "dgm", "media"}


def _text_sig(text: str) -> str:
    t = text.strip().lower()
    if not t:
        return ""
    if _NUM_RE.match(t):
        return "num"
    return t[:24]


def shape_signature(s: ShapeInfo, slide_w: int, slide_h: int) -> str:
    f = s.bbox.to_frac(slide_w, slide_h)
    geo = f"{round(f.x, 2)},{round(f.y, 2)},{round(f.w, 2)},{round(f.h, 2)}"
    if s.kind == ShapeKind.pic:
        content = "img:" + (s.image_part or "").rsplit("/", 1)[-1]
    elif s.has_text:
        content = "txt:" + _text_sig(s.plain_text)
    else:
        content = f"fill:{s.fill_hex or ''}/{s.line_hex or ''}/{s.geometry or ''}"
    return f"{s.kind.value}|{geo}|{content}"


def _title_box(shapes: list[ShapeInfo], slide_h: int):
    """The heading of a sample: its title placeholder, else the largest text in the top 40 % of the slide."""
    t = next((s for s in shapes if s.ph_type in ("title", "ctrTitle") and s.bbox.area > 0), None)
    if t is not None:
        return t.bbox
    texts = [s for s in shapes if s.has_text and s.bbox.area > 0 and s.bbox.y < 0.4 * slide_h and not _NUM_RE.match(s.plain_text.strip())]
    if not texts:
        return None
    return max(texts, key=lambda s: ((s.text.dominant_size_pt or 0.0) if s.text else 0.0, -s.bbox.y)).bbox


def is_kicker(s: ShapeInfo, title, slide_h: int) -> bool:
    """A short text standing in the content band right above or below the slide's heading, over the same columns:
    the sample's kicker («DEMO SLIDE», a section label) — content of the sample, not chrome to keep on every slide."""
    if title is None or s.bbox is title or not s.has_text:
        return False
    if s.bbox.x == title.x and s.bbox.y == title.y and s.bbox.w == title.w and s.bbox.h == title.h:
        return False
    if not 0.08 * slide_h < s.bbox.y < 0.85 * slide_h:
        return False
    gap = max(title.y - s.bbox.y2, s.bbox.y - title.y2, 0)
    overlaps_x = s.bbox.x < title.x2 and s.bbox.x2 > title.x
    return gap <= 0.12 * slide_h and overlaps_x


def detect_chrome(shapes_per_slide: dict[int, list[ShapeInfo]], slide_w: int, slide_h: int, min_share: float = 0.4, min_slides: int = 3) -> list[ChromeElement]:
    n = len(shapes_per_slide)
    if n == 0:
        return []
    seen: dict[str, set[int]] = defaultdict(set)
    sample: dict[str, tuple[int, ShapeInfo]] = {}
    for idx, shapes in shapes_per_slide.items():
        title = None
        for s in shapes:
            if s.ph_type in _CONTENT_PH:
                continue
            if s.has_text and len(s.plain_text.strip()) > 40:
                continue
            if s.bbox.area <= 0:
                continue
            if s.has_text and _text_sig(s.plain_text) != "num":
                # sample copy repeated on every sample («DEMO SLIDE», «Your logo») and kickers over the heading are
                # the sample's content: kept as chrome, they would stand above every generated heading
                if looks_like_placeholder(s.plain_text):
                    continue
                if title is None:
                    title = _title_box(shapes, slide_h) or False
                if title and is_kicker(s, title, slide_h):
                    continue
            sig = shape_signature(s, slide_w, slide_h)
            seen[sig].add(idx)
            sample.setdefault(sig, (idx, s))
    out: list[ChromeElement] = []
    for sig, slides in seen.items():
        share = len(slides) / n
        if len(slides) >= min_slides and share >= min_share:
            idx, s = sample[sig]
            kind = "pic" if s.kind == ShapeKind.pic else ("text" if s.has_text else "sp")
            out.append(
                ChromeElement(
                    signature=sig,
                    bbox=s.bbox.to_frac(slide_w, slide_h),
                    share=round(share, 3),
                    kind=kind,
                    sample_slide=idx,
                    text=s.plain_text[:40] if s.has_text else None,
                    image_part=s.image_part,
                )
            )
    out.sort(key=lambda c: -c.share)
    return out


def chrome_ids(shapes: list[ShapeInfo], chrome: list[ChromeElement], slide_w: int, slide_h: int) -> set[str]:
    sigs = {c.signature for c in chrome if c.source == "slide"}
    return {s.id for s in shapes if shape_signature(s, slide_w, slide_h) in sigs}


def inherited_chrome(part_shapes: dict[str, list[ShapeInfo]], slides_using: dict[str, list[int]], n_slides: int, slide_w: int, slide_h: int, source_kind: str) -> list[ChromeElement]:
    """Chrome that lives on layouts/masters: every non-placeholder shape with content (logo, footer, decoration)."""
    out: list[ChromeElement] = []
    slide_area = float(slide_w * slide_h)
    for part, shapes in part_shapes.items():
        users = slides_using.get(part, [])
        if not users:
            continue
        share = round(len(users) / max(n_slides, 1), 3)
        tiny: dict[tuple[int, int], list[ShapeInfo]] = {}
        for s in shapes:
            if s.is_placeholder or s.bbox.area <= 0:
                continue
            if not (s.kind == ShapeKind.pic or s.has_text or s.fill_hex or s.line_hex):
                continue
            if s.has_text and len(s.plain_text.strip()) > 60:
                continue
            if s.bbox.area / slide_area < 0.002 and not s.has_text and s.kind != ShapeKind.pic:
                f = s.bbox.to_frac(slide_w, slide_h)
                tiny.setdefault((int(f.x * 5), int(f.y * 5)), []).append(s)  # decorative dots/lines: merge per 5x5 cell
                continue
            kind = "pic" if s.kind == ShapeKind.pic else ("text" if s.has_text else "sp")
            out.append(
                ChromeElement(
                    signature=f"{source_kind}:{part}:{shape_signature(s, slide_w, slide_h)}",
                    bbox=s.bbox.to_frac(slide_w, slide_h),
                    share=share,
                    kind=kind,
                    sample_slide=users[0],
                    text=s.plain_text[:40] if s.has_text else None,
                    image_part=s.image_part,
                    source=f"{source_kind}:{part}",
                )
            )
        for cell, members in tiny.items():
            u = members[0].bbox
            for m in members[1:]:
                u = u.union(m.bbox)
            out.append(
                ChromeElement(
                    signature=f"{source_kind}:{part}:pattern:{cell[0]},{cell[1]}",
                    bbox=u.to_frac(slide_w, slide_h),
                    share=share,
                    kind="pattern",
                    sample_slide=users[0],
                    text=f"{len(members)} decorative shapes",
                    source=f"{source_kind}:{part}",
                )
            )
    return out


def visual_chrome(image_paths: list[str], min_share: float = 0.4, grid: tuple[int, int] = (160, 90)) -> list[ChromeElement]:
    """Logos and marks baked into background pictures: no shape carries them, but the renders do.

    Edges that stand at the same place on at least `min_share` of the rendered slides, inside the top or bottom
    band (where templates put logos, contacts, page marks), are joined into boxes and returned as background chrome.
    Text must keep clear of them just as of logo shapes.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:  # pragma: no cover
        return []
    w, h = grid
    maps = []
    for p in image_paths:
        try:
            with Image.open(p) as im:
                g = np.asarray(im.convert("L").resize((w, h)), dtype=np.float32)
        except Exception:  # noqa: BLE001
            continue
        gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
        gy = np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
        maps.append((gx + gy) > 40)
    if len(maps) < 3:
        return []
    share = np.mean(np.stack(maps), axis=0)
    mask = share >= min_share
    band = np.zeros_like(mask)
    band[: int(h * 0.2), :] = True
    band[int(h * 0.85) :, :] = True
    mask &= band
    # join nearby edges (a logo is many strokes): dilate by 2 cells, then label connected regions
    from itertools import product

    dil = mask.copy()
    for dy, dx in product(range(-2, 3), repeat=2):
        dil |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    seen = np.zeros_like(dil)
    out: list[ChromeElement] = []
    for y0 in range(h):
        for x0 in range(w):
            if not dil[y0, x0] or seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            ys, xs = [], []
            while stack:
                y, x = stack.pop()
                ys.append(y)
                xs.append(x)
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < h and 0 <= nx < w and dil[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(ys) < 12:
                continue
            bx, by, bw, bh = min(xs) / w, min(ys) / h, (max(xs) - min(xs) + 1) / w, (max(ys) - min(ys) + 1) / h
            if bw * bh > 0.25 or bw > 0.9:
                continue  # a band-wide stripe is ornament of the whole slide, not an obstacle
            out.append(ChromeElement(signature=f"visual:{round(bx, 2)},{round(by, 2)},{round(bw, 2)},{round(bh, 2)}", bbox=BboxFrac(x=round(bx, 4), y=round(by, 4), w=round(bw, 4), h=round(bh, 4)), share=round(float(share[ys, xs].mean()), 3), kind="pic", sample_slide=1, source="background"))
    return out
