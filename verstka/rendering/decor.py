"""Small decor of the template under the slide's own text (qa5 №3: Yellow_Idea's confetti — ×, ▷, ○ — scattered over
its layout lay over headings, figures and legends on every slide: «кл×иентов», «Тренировоч×ный», ○ on «26%»).

The marks belong to the layout (or the master) — shared by every slide, they cannot be moved for one of them, and
hiding the master graphics of a slide (`showMasterSp="0"`) is not honoured by LibreOffice for grouped layout shapes.
A mark the slide's own content touches is covered instead: a patch in the slide's background colour, a little larger
than the mark, laid at the bottom of the slide's own shapes — over the layout, under the content. Only where the mark
stands on the plain background (a solid one, nothing else of the layout under it) and only small marks (each under
1.2 % of the slide, no side over 8 %); a logo (a picture) is never covered."""

from __future__ import annotations

import logging
from typing import Optional
from lxml import etree
from pptx.slide import Slide

from verstka.analysis.xmlns import q
from verstka.rendering.deck import element_bbox
from verstka.schemas.common import Bbox

log = logging.getLogger(__name__)

MARK_AREA = 0.012  # of the slide
MARK_SIDE = 0.08  # of the slide's width / height
_DRAWN = ("sp", "pic", "grpSp", "cxnSp")


def _shows_master(el) -> bool:
    return (el.get("showMasterSp") or "1") not in ("0", "false")


def _is_placeholder(el) -> bool:
    return next(el.iter(q("p:ph")), None) is not None


def _group_map(grp):
    """(scale_x, scale_y, off_x, off_y) mapping the group's child coordinates onto its parent's."""
    xf = grp.find(q("p:grpSpPr") + "/" + q("a:xfrm"))
    if xf is None:
        return 1.0, 1.0, 0, 0
    off, ext, choff, chext = (xf.find(q(t)) for t in ("a:off", "a:ext", "a:chOff", "a:chExt"))
    if None in (off, ext):
        return 1.0, 1.0, 0, 0
    ox, oy, ex, ey = int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))
    if choff is None or chext is None:
        return 1.0, 1.0, 0, 0
    cx, cy, cw, ch = int(choff.get("x")), int(choff.get("y")), int(chext.get("cx")), int(chext.get("cy"))
    sx = ex / cw if cw else 1.0
    sy = ey / ch if ch else 1.0
    return sx, sy, ox - cx * sx, oy - cy * sy


def _leaves(el, m=(1.0, 1.0, 0, 0)):
    """(leaf element, absolute box) of a drawn element: a group's shapes through its transforms."""
    tag = etree.QName(el).localname
    if tag == "grpSp":
        gm = _group_map(el)
        sx, sy, ox, oy = m
        cm = (sx * gm[0], sy * gm[1], ox + sx * gm[2], oy + sy * gm[3])
        for ch in el:
            if etree.QName(ch).localname in _DRAWN:
                yield from _leaves(ch, cm)
        return
    b = element_bbox(el)
    if not b:
        return
    sx, sy, ox, oy = m
    yield el, Bbox(x=int(ox + b[0] * sx), y=int(oy + b[1] * sy), w=max(int(b[2] * sx), 1), h=max(int(b[3] * sy), 1))


def _sources(slide: Slide) -> list:
    """The master and the layout whose shapes the slide shows, bottom first."""
    if not _shows_master(slide._element):
        return []
    layout = slide.slide_layout
    out = []
    if _shows_master(layout._element):
        out.append(layout.slide_master)
    out.append(layout)
    return out


def _content_boxes(slide: Slide) -> list[Bbox]:
    """The slide's own shapes — texts, charts, tables, pictures, cards, rules — the full-slide grounds aside."""
    W = int(slide.part.package.presentation_part.presentation.slide_width)
    H = int(slide.part.package.presentation_part.presentation.slide_height)
    tree = slide._element.cSld.find(q("p:spTree"))
    out = []
    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("sp", "graphicFrame", "pic", "AlternateContent", "grpSp", "cxnSp"):
            continue
        nv = el.find(".//" + q("p:cNvPr"))
        if nv is not None and (nv.get("name") or "").startswith("Decor cover"):
            continue
        b = element_bbox(el)
        if not b or b[2] < 0 or b[3] < 0 or (b[2] * b[3] >= 0.85 * W * H):
            continue
        out.append(Bbox(x=b[0], y=b[1], w=max(b[2], 1), h=max(b[3], 1)))
    return out


def small_marks(slide: Slide) -> list[tuple]:
    """(source, top-level element, leaf element, box) of every small mark the master and the layout draw on the slide."""
    W = int(slide.part.package.presentation_part.presentation.slide_width)
    H = int(slide.part.package.presentation_part.presentation.slide_height)
    out = []
    for src in _sources(slide):
        tree = src._element.cSld.find(q("p:spTree"))
        for top in tree:
            if etree.QName(top).localname not in _DRAWN or _is_placeholder(top):
                continue
            for leaf, box in _leaves(top):
                if etree.QName(leaf).localname == "pic":
                    continue  # a logo, a photo: the template's identity, never dropped
                if box.w * box.h <= MARK_AREA * W * H and box.w <= MARK_SIDE * W and box.h <= MARK_SIDE * H:
                    out.append((src, top, leaf, box))
    return out


def _hits(marks: list[tuple], boxes: list[Bbox], W: int, H: int) -> list[tuple]:
    pad_x, pad_y = int(0.004 * W), int(0.004 * H)
    out = []
    for m in marks:
        b = m[3]
        grown = Bbox(x=b.x - pad_x, y=b.y - pad_y, w=b.w + 2 * pad_x, h=b.h + 2 * pad_y)
        if any(grown.intersection(c) > 0 for c in boxes):
            out.append(m)
    return out


def _solid_background(slide: Slide) -> Optional[str]:
    """The slide's background colour when it is solid (the slide's own, else its layout's, else its master's)."""
    from verstka.rendering.charts import slide_ground

    for holder in (slide, slide.slide_layout, slide.slide_layout.slide_master):
        bg = holder._element.find(q("p:cSld") + "/" + q("p:bg"))
        if bg is None:
            continue
        if bg.find(".//" + q("a:gradFill")) is not None or bg.find(".//" + q("a:blipFill")) is not None or bg.find(".//" + q("a:pattFill")) is not None:
            return None
        break
    try:
        g = slide_ground(slide, Bbox(x=0, y=0, w=1, h=1))
    except Exception:  # noqa: BLE001
        return None
    return g.upper() if g and len(g) == 6 else None


def _layout_under(slide: Slide, mark_top, box: Bbox) -> bool:
    """Anything of the master or the layout (other than the mark's own group) painted under the mark."""
    from verstka.rendering.layers import drawn_layers, painted_share

    for lay in drawn_layers(slide):
        if lay.source == "slide" or lay.el is mark_top or lay.placeholder or not lay.paints:
            continue
        if lay.cover >= 0.85 and not lay.picture:
            return True  # a full-bleed band or panel: the patch would show
        if painted_share(lay, box) > 0.05:
            return True
    return False


def clear_small_decor(slide: Slide) -> int:
    """Cover, on this slide only, the template's small marks its own content touches (see the module's docstring).
    Returns the number of marks covered."""
    try:
        W = int(slide.part.package.presentation_part.presentation.slide_width)
        H = int(slide.part.package.presentation_part.presentation.slide_height)
        marks = small_marks(slide)
        if not marks:
            return 0
        hits = _hits(marks, _content_boxes(slide), W, H)
        if not hits:
            return 0
        bg = _solid_background(slide)
        if bg is None:
            return 0
        from verstka.rendering.compose import Canvas

        tree = slide._element.cSld.find(q("p:spTree"))
        cv = Canvas(slide)
        made = 0
        for _src, top, _leaf, b in hits:
            if _layout_under(slide, top, b):
                continue
            px, py = max(int(b.w * 0.2), int(0.003 * W)), max(int(b.h * 0.2), int(0.003 * H))
            patch = cv.rect(Bbox(x=b.x - px, y=b.y - py, w=b.w + 2 * px, h=b.h + 2 * py), bg, name="Decor cover")
            tree.remove(patch)
            tree.insert(2, patch)
            made += 1
        return made
    except Exception:  # noqa: BLE001 - decor is the template's: never lose a slide over it
        log.warning("small decor not covered", exc_info=True)
        return 0


def marks_under_text(slide: Slide) -> list[Bbox]:
    """The template's small marks that lie under the slide's own text, charts or tables (for the audit)."""
    W = int(slide.part.package.presentation_part.presentation.slide_width)
    H = int(slide.part.package.presentation_part.presentation.slide_height)
    return [m[3] for m in _hits(small_marks(slide), _content_boxes(slide), W, H)]

