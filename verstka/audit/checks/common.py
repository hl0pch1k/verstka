"""Helpers shared by checks."""

from __future__ import annotations

from typing import Optional

from verstka.rendering.fonts import wrap_lines
from verstka.ru import ru_count, ru_times  # noqa: F401  (re-exported for the checks)
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


CHROME_PH_TYPES = ("sldNum", "dt", "ftr")


def is_template_chrome(e: IRElement, manifest: Optional["TemplateManifest"] = None) -> bool:
    """The template's own service elements, whatever their size: the slide-number, date and footer placeholders, and
    anything standing exactly where the template analysis found chrome (slide, layout or master — a slide keeps its
    own copy of the layout's page number). Such elements are the template's design, not the deck's content: checks
    of the deck's typography, colours and geometry leave them alone."""
    if e.ph_type in CHROME_PH_TYPES:
        return True
    if manifest is not None:
        f = e.bbox_frac
        for c in manifest.tokens.chrome:
            if (c.kind == "pic") != (e.type == "picture"):
                continue
            if f.close_to(c.bbox, 0.015):
                return True
    return False


def is_chrome_like(e: IRElement, ir: DeckIR, manifest: Optional["TemplateManifest"] = None) -> bool:
    """Logos, footers, page numbers are not content: small elements near the edges, and anything standing where the
    template analysis found chrome (a footer may be a third of the slide wide and still belong to the template)."""
    f = e.bbox_frac
    tiny = f.area < 0.01
    near_edge = f.y > 0.88 or f.y2 < 0.08 or f.x2 < 0.06 or f.x > 0.94
    if tiny and near_edge:
        return True
    return is_template_chrome(e, manifest)


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
    """(height in pt, lines) the text needs given the element width. `line_spacing` is the template's line height in
    em; a paragraph that sets its own spacing (a:lnSpc spcPct, e.g. a display heading at 90 %) is measured with it —
    a single-spaced line is 1.2 em, so 90 % sets lines 1.08 em apart, as the renderers size such boxes."""
    usable_w = max((e.bbox.w - e.insets_emu[0] - e.insets_emu[2]) / EMU_PER_PT, 1.0)
    height = 0.0
    lines = 0
    caps = bool(getattr(e, "caps", False))  # shown in capitals: measured as shown
    for p in e.paragraphs:
        size = next((r.size_pt for r in p.runs if r.size_pt), None) or e.dominant_size or 14.0
        font = next((r.font for r in p.runs if r.font), None)
        bold = any(r.bold for r in p.runs)
        sizes = {r.size_pt for r in p.runs if r.size_pt and r.text.strip()}
        if not p.text.strip():
            n = 1
        elif e.wrap and len(sizes) > 1:
            # runs of different sizes («145 000» with a small «₽»): the line holds the sum of their widths
            from verstka.rendering.fonts import text_width_pt

            total = sum(text_width_pt(r.text.upper() if caps else r.text, r.font or font, r.size_pt or size, r.bold) for r in p.runs)
            n = max(1, -(-int(total) // max(int(usable_w), 1)))
            size = max(sizes)
        elif e.wrap:
            n = max(len(wrap_lines(p.text.upper() if caps else p.text, font, size, bold, usable_w)), 1)
        else:
            n = 1
        lines += n
        height += n * size * (1.2 * p.line_spacing if p.line_spacing else line_spacing)
    return height, lines


def usable_height_pt(e: IRElement) -> float:
    return max((e.bbox.h - e.insets_emu[1] - e.insets_emu[3]) / EMU_PER_PT, 1.0)


def contains(outer: Bbox, inner: Bbox, tol: float = 0.02) -> bool:
    tx = tol * max(outer.w, 1)
    ty = tol * max(outer.h, 1)
    return outer.x - tx <= inner.x and outer.y - ty <= inner.y and outer.x2 + tx >= inner.x2 and outer.y2 + ty >= inner.y2


def _holds(o: IRElement, e: IRElement) -> bool:
    """o lies under most of e — a text box a hair wider than its card is still on the card."""
    return o.bbox.area > e.bbox.area and (contains(o.bbox, e.bbox, 0.01) or o.bbox.intersection(e.bbox) >= 0.8 * max(e.bbox.area, 1))


# geometries that paint their whole box (a triangle, an ellipse or a freeform paints only part of it: whether text
# stands on it is not a question its box can answer)
RECT_GEOMETRIES = frozenset({None, "rect", "roundRect", "snip1Rect", "snip2SameRect", "snip2DiagRect", "snipRoundRect", "round1Rect", "round2SameRect", "round2DiagRect", "flowChartProcess", "flowChartAlternateProcess", "plaque"})


def region_paint(o: IRElement, box: Bbox) -> Optional[tuple[str, float]]:
    """(colour, opacity) a template layer with `cells` (a picture, a gradient) paints over `box`: its cells weighted
    by their overlap with the box and their opacity. None without cells, when the box misses the layer, or when the
    layer is fully transparent there."""
    c = o.cells
    b = o.bbox
    if c is None or b.w <= 0 or b.h <= 0 or not (c.w * c.h == len(c.alpha) == len(c.hex)):
        return None
    cw, ch = b.w / c.w, b.h / c.h
    i0, i1 = max(int((box.x - b.x) // cw), 0), min(int((box.x2 - b.x) // cw), c.w - 1)
    j0, j1 = max(int((box.y - b.y) // ch), 0), min(int((box.y2 - b.y) // ch), c.h - 1)
    tot_w = tot_a = 0.0
    acc = [0.0, 0.0, 0.0]
    for j in range(j0, j1 + 1):
        oy = min(box.y2, b.y + (j + 1) * ch) - max(box.y, b.y + j * ch)
        if oy <= 0:
            continue
        for i in range(i0, i1 + 1):
            ox = min(box.x2, b.x + (i + 1) * cw) - max(box.x, b.x + i * cw)
            if ox <= 0:
                continue
            w = ox * oy
            a = c.alpha[j * c.w + i]
            tot_w += w
            tot_a += w * a
            r, g, bl = hex_to_rgb(c.hex[j * c.w + i])
            acc[0] += w * a * r
            acc[1] += w * a * g
            acc[2] += w * a * bl
    if tot_w <= 0 or tot_a <= 0:
        return None
    return rgb_to_hex(acc[0] / tot_a, acc[1] / tot_a, acc[2] / tot_a), tot_a / tot_w


def _inside_poly(px: float, py: float, poly) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def outline_share(o: IRElement, box: Bbox, nx: int = 12, ny: int = 6) -> float:
    """Share of `box` inside the outline a non-rectangular template shape paints (a triangle, an ellipse)."""
    if not o.outline or box.w <= 0 or box.h <= 0:
        return 0.0
    hit = 0
    for i in range(nx):
        px = box.x + (i + 0.5) * box.w / nx
        for j in range(ny):
            py = box.y + (j + 0.5) * box.h / ny
            if sum(1 for poly in o.outline if len(poly) > 2 and _inside_poly(px, py, poly)) % 2 == 1:
                hit += 1
    return hit / float(nx * ny)


def template_grounds(slide: IRSlide, e: IRElement) -> list[IRElement]:
    """Painted layout/master elements (rectangular bands, panels, picture grounds, and a triangle or an ellipse whose
    real outline holds nearly all of e) under most of e, bottom first. A picture or gradient that is transparent
    elsewhere still counts where it paints under e."""
    out = []
    for o in getattr(slide, "template_elements", []) or []:
        if not (o.fill_hex and o.type in ("shape", "text", "picture") and _holds(o, e)):
            continue
        if not (o.type == "picture" or o.geometry in RECT_GEOMETRIES or (o.outline and outline_share(o, e.bbox) >= 0.9)):
            continue
        rp = region_paint(o, e.bbox) if o.cells is not None else None
        if o.opaque if rp is None else rp[1] >= 0.5:
            out.append(o)
    return out


def ground_of(slide: IRSlide, e: IRElement, bg_slide: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """(colour, kind) of what lies under e: kind «card» (a filled element of the slide), «template» (a layout/master
    band or panel), «picture» (a layout/master picture or picture-filled shape — its median colour), or (None, None)
    when nothing encloses e (the slide's own ground applies). Translucent fills are composited over what lies under
    them."""
    cands = [o for o in slide.elements if o is not e and o.fill_hex and o.type in ("shape", "text") and _holds(o, e)]
    # the layout and master paint under every shape of the slide: a picture or a card of the slide under e hides them
    hidden = any(o is not e and o.z < e.z and (o.type == "picture" or (o.fill_hex and o.type in ("shape", "text"))) and _holds(o, e) for o in slide.elements)
    tpl = [] if hidden else template_grounds(slide, e)
    if not cands and not tpl:
        return None, None
    color = bg_slide or slide.background_hex
    kind = None
    # the layout and master paint first, in z-order (master before layout); the slide's own cards over them
    order = sorted(tpl, key=lambda o: (0 if o.source == "master" else 1, o.z)) + sorted(cands, key=lambda o: o.bbox.area, reverse=True)
    for o in order:
        hx, a = o.fill_hex, fill_alpha(o)
        local = region_paint(o, e.bbox) if o.source != "slide" and o.cells is not None else None
        if local is not None:
            hx, a = local[0], min(a, local[1]) if o.type != "picture" else local[1]
        if a >= 0.995 or not color:
            color = hx.upper()
        else:
            try:
                color = composite_hex(hx, a, color)
            except ValueError:
                color = hx.upper()
        if o.source != "slide":
            if o.type == "picture" or o.busy or (o.paint_kind or "") == "image":
                kind = "picture"
            elif (o.paint_kind or "") == "gradient":
                # the gradient's own colour at the text's place when it could be evaluated, else only its mean
                kind = "gradient" if local is not None else "picture"
            else:
                kind = "template"
        else:
            kind = "card"
    return color, kind


def enclosing_fill(slide: IRSlide, e: IRElement, bg_slide: Optional[str] = None) -> Optional[str]:
    """Effective colour behind e: the fill of the smallest filled element containing e (a card of the slide, else a
    band or panel its layout or master paints), translucent cards composited over what lies under them (outer card or
    the slide background). None when nothing encloses e."""
    return ground_of(slide, e, bg_slide)[0]


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


def line_boxes(e: IRElement) -> list[tuple[Bbox, float]]:
    """(box, size) of every line a text shows: the width its letters take at the paragraph's alignment and a line's
    height, stacked at the box's anchor — what the reader sees of the text line by line (a centred heading's short
    second line is narrower than its box, and may stand on another ground than the first)."""
    import re as _re

    from verstka.rendering.fonts import text_width_pt

    ins = e.insets_emu
    usable_w = max((e.bbox.w - ins[0] - ins[2]) / EMU_PER_PT, 1.0)
    caps = bool(getattr(e, "caps", False))
    rows: list[tuple[float, float, Optional[str], float]] = []  # (width pt, size, align, line height pt)
    for p in e.paragraphs:
        size = next((r.size_pt for r in p.runs if r.size_pt), None) or e.dominant_size or 14.0
        font = next((r.font for r in p.runs if r.font), None)
        bold = any(r.bold for r in p.runs)
        lh = size * (1.2 * p.line_spacing if p.line_spacing else 1.2)
        indent = size * 1.1 if p.bullet else 0.0
        if not p.text.strip():
            rows.append((0.0, size, p.align, lh))
            continue
        for seg in _re.split(r"[\n\x0b]", p.text):
            shown = seg.upper() if caps else seg
            lines = wrap_lines(shown, font, size, bold, max(usable_w - indent, 1.0)) if e.wrap else [shown]
            for ln in lines or [""]:
                rows.append((indent + text_width_pt(ln, font, size, bold) if ln.strip() else 0.0, size, p.align, lh))
    total = int(sum(r[3] for r in rows) * EMU_PER_PT)
    top, inner_h = e.bbox.y + ins[1], e.bbox.h - ins[1] - ins[3]
    anchor = e.anchor or "t"
    y = top if anchor == "t" else (top + inner_h - total if anchor == "b" else top + (inner_h - total) // 2)
    x0, x1 = e.bbox.x + ins[0], e.bbox.x2 - ins[2]
    out: list[tuple[Bbox, float]] = []
    for w_pt, size, align, lh in rows:
        h = max(int(lh * EMU_PER_PT), 1)
        w = int(w_pt * EMU_PER_PT)
        if w > 0:
            x = x1 - w if align == "r" else ((x0 + x1) // 2 - w // 2 if align in ("ctr", "c") else x0)
            out.append((Bbox(x=int(x), y=int(y), w=w, h=h), size))
        y += h
    return out
