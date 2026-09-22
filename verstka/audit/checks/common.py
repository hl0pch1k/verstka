"""Helpers shared by checks."""

from __future__ import annotations

from typing import Optional

from verstka.rendering.fonts import wrap_lines
from verstka.schemas.audit import FixAction
from verstka.schemas.common import EMU_PER_PT, Bbox, hex_to_rgb, rgb_to_hex
from verstka.schemas.deck_ir import DeckIR, IRElement, IRSlide
from verstka.schemas.template import TemplateManifest

CONTENT_TYPES = ("text", "picture", "chart", "table")


def text_elements(slide: IRSlide) -> list[IRElement]:
    """Real text boxes only: tables and charts carry text too but are audited by their own checks."""
    return [e for e in slide.elements if e.type == "text" and e.has_text]


def fill_alpha(e: IRElement) -> float:
    """Opacity of the element fill (0..1); `fill_alpha` is optional on the IR, missing means opaque."""
    a = getattr(e, "fill_alpha", None)
    try:
        return max(0.0, min(1.0, float(a))) if a is not None else 1.0
    except (TypeError, ValueError):
        return 1.0


def composite_hex(fg_hex: str, alpha: float, under_hex: str) -> str:
    """Colour of a translucent fill seen over an opaque colour: alpha·fg + (1−alpha)·under."""
    if alpha >= 1.0:
        return fg_hex.upper()
    r1, g1, b1 = hex_to_rgb(fg_hex)
    r2, g2, b2 = hex_to_rgb(under_hex)
    return rgb_to_hex(alpha * r1 + (1 - alpha) * r2, alpha * g1 + (1 - alpha) * g2, alpha * b1 + (1 - alpha) * b2)


def is_chrome_like(e: IRElement, ir: DeckIR, manifest: Optional["TemplateManifest"] = None) -> bool:
    """Logos, footers, page numbers are not content: small elements near the edges, and anything standing where the
    template analysis found slide chrome (a footer may be a third of the slide wide and still belong to the template)."""
    f = e.bbox_frac
    tiny = f.area < 0.01
    near_edge = f.y > 0.88 or f.y2 < 0.08 or f.x2 < 0.06 or f.x > 0.94
    if tiny and near_edge:
        return True
    if manifest is not None:
        for c in manifest.tokens.chrome:
            if c.source != "slide" or (c.kind == "pic") != (e.type == "picture"):
                continue
            if f.close_to(c.bbox, 0.015):
                return True
    return False


def at_template_position(e: IRElement, manifest: Optional["TemplateManifest"]) -> bool:
    """The element starts exactly where the template itself places a slot (any sample): the template's geometry,
    not a layout mistake — margin estimates never override it."""
    if manifest is None:
        return False
    f = e.bbox_frac
    for p in manifest.patterns:
        for s in p.slots:
            if abs(s.bbox.x - f.x) <= 0.006 and abs(s.bbox.y - f.y) <= 0.006:
                return True
    return False


def content_elements(slide: IRSlide, ir: DeckIR, manifest: Optional["TemplateManifest"] = None) -> list[IRElement]:
    return [e for e in slide.elements if e.type in CONTENT_TYPES and e.bbox.area > 0 and not is_chrome_like(e, ir, manifest)]


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


def enclosing_fill(slide: IRSlide, e: IRElement, bg_slide: Optional[str] = None) -> Optional[str]:
    """Effective colour behind e: the fill of the smallest filled element containing e (a card), translucent cards
    composited over what lies under them (outer card or the slide background). None when nothing encloses e."""
    cands = [o for o in slide.elements if o is not e and o.fill_hex and o.type in ("shape", "text") and contains(o.bbox, e.bbox, 0.01) and o.bbox.area > e.bbox.area]
    if not cands:
        return None
    color = bg_slide or slide.background_hex
    for o in sorted(cands, key=lambda o: o.bbox.area, reverse=True):  # outermost → innermost
        a = fill_alpha(o)
        if a >= 1.0 or not color:
            color = o.fill_hex.upper()
            continue
        try:
            color = composite_hex(o.fill_hex, a, color)
        except ValueError:
            color = o.fill_hex.upper()
    return color


def title_element(slide: IRSlide) -> Optional[IRElement]:
    texts = text_elements(slide)
    if not texts:
        return None
    ph = next((t for t in texts if t.ph_type in ("title", "ctrTitle")), None)
    if ph is not None:
        return ph
    top = [t for t in texts if t.bbox_frac.y < 0.35]
    return max(top, key=lambda t: (t.dominant_size or 0)) if top else None


def fix(action: str, description: str, **params) -> FixAction:
    return FixAction(action=action, params=params, description=description)
