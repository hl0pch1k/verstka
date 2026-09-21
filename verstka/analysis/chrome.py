"""Chrome detection: logos, footers, page numbers and decorations that repeat at the same place."""

from __future__ import annotations

import re
from collections import defaultdict

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import ShapeKind
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


def detect_chrome(shapes_per_slide: dict[int, list[ShapeInfo]], slide_w: int, slide_h: int, min_share: float = 0.4, min_slides: int = 3) -> list[ChromeElement]:
    n = len(shapes_per_slide)
    if n == 0:
        return []
    seen: dict[str, set[int]] = defaultdict(set)
    sample: dict[str, tuple[int, ShapeInfo]] = {}
    for idx, shapes in shapes_per_slide.items():
        for s in shapes:
            if s.ph_type in _CONTENT_PH:
                continue
            if s.has_text and len(s.plain_text.strip()) > 40:
                continue
            if s.bbox.area <= 0:
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
    sigs = {c.signature for c in chrome}
    return {s.id for s in shapes if shape_signature(s, slide_w, slide_h) in sigs}
