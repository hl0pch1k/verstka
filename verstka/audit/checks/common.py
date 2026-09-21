"""Helpers shared by checks."""

from __future__ import annotations

from typing import Optional

from verstka.rendering.fonts import wrap_lines
from verstka.schemas.audit import FixAction
from verstka.schemas.common import EMU_PER_PT, Bbox
from verstka.schemas.deck_ir import DeckIR, IRElement, IRSlide

CONTENT_TYPES = ("text", "picture", "chart", "table")


def is_chrome_like(e: IRElement, ir: DeckIR) -> bool:
    """Small elements near the edges (logos, footers, page numbers) are not content."""
    f = e.bbox_frac
    tiny = f.area < 0.01
    near_edge = f.y > 0.88 or f.y2 < 0.08 or f.x2 < 0.06 or f.x > 0.94
    return tiny and near_edge


def content_elements(slide: IRSlide, ir: DeckIR) -> list[IRElement]:
    return [e for e in slide.elements if e.type in CONTENT_TYPES and e.bbox.area > 0 and not is_chrome_like(e, ir)]


def text_height_needed_pt(e: IRElement, line_spacing: float = 1.2) -> tuple[float, int]:
    """(height in pt, lines) the text needs given the element width."""
    usable_w = max((e.bbox.w - e.insets_emu[0] - e.insets_emu[2]) / EMU_PER_PT, 1.0)
    height = 0.0
    lines = 0
    for p in e.paragraphs:
        size = next((r.size_pt for r in p.runs if r.size_pt), None) or e.dominant_size or 14.0
        font = next((r.font for r in p.runs if r.font), None)
        bold = any(r.bold for r in p.runs)
        if not p.text.strip():
            n = 1
        elif e.wrap:
            n = max(len(wrap_lines(p.text, font, size, bold, usable_w)), 1)
        else:
            n = 1
        lines += n
        height += n * size * line_spacing
    return height, lines


def usable_height_pt(e: IRElement) -> float:
    return max((e.bbox.h - e.insets_emu[1] - e.insets_emu[3]) / EMU_PER_PT, 1.0)


def contains(outer: Bbox, inner: Bbox, tol: float = 0.02) -> bool:
    tx = tol * max(outer.w, 1)
    ty = tol * max(outer.h, 1)
    return outer.x - tx <= inner.x and outer.y - ty <= inner.y and outer.x2 + tx >= inner.x2 and outer.y2 + ty >= inner.y2


def enclosing_fill(slide: IRSlide, e: IRElement) -> Optional[str]:
    """Fill colour of the smallest filled element that contains e (a card), else None."""
    cands = [o for o in slide.elements if o is not e and o.fill_hex and o.type in ("shape", "text") and contains(o.bbox, e.bbox, 0.01) and o.bbox.area > e.bbox.area]
    if not cands:
        return None
    return min(cands, key=lambda o: o.bbox.area).fill_hex


def title_element(slide: IRSlide) -> Optional[IRElement]:
    texts = slide.texts
    if not texts:
        return None
    ph = next((t for t in texts if t.ph_type in ("title", "ctrTitle")), None)
    if ph is not None:
        return ph
    top = [t for t in texts if t.bbox_frac.y < 0.35]
    return max(top, key=lambda t: (t.dominant_size or 0)) if top else None


def fix(action: str, description: str, **params) -> FixAction:
    return FixAction(action=action, params=params, description=description)
