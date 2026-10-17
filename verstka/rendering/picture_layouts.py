"""How a generated picture stands on its slide — chosen after the slide is laid out, from what is around its place.

The owner (18.10, п. 9): «картинки всегда прямоугольник, не подходят ни по месту, ни по форме». A designer gives a
picture a form of the slide, not a box in it:

* **bleed** — a place in a side column of the slide runs out to the slide's edge (and to the top and the bottom where
  nothing written stands above or below it): half of the slide is the picture, the other half the content;
* **circle** / **rounded** — a template that speaks in circles (large round decor, round photos) or in rounded cards
  gets its picture in the same form (the circle a square in the place's middle);
* **background** — a place that already takes most of the slide (a template's full-slide photo) covers it whole and
  the text gets a quiet underlay of the slide's ground colour;
* **template** — a place the template itself drew in a form (an oval photo, a hexagon) keeps it.

Nothing written ever goes under a picture it did not lie on: a bleed stops at any text, chart, table, picture or logo
(of the slide, its layout or its master); page numbers and footers a bleed covers are put over it. The rules are the
same for every template (no template is tuned for). The picture itself is cropped to the frame by what it shows
(images/palette.py `fit_to`), never stretched."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import median
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import q

log = logging.getLogger(__name__)

EMU_PER_PT = 12700
# a place is a side column: at most this share of the slide's width, at least this share of its height
SIDE_MAX_W = 0.62
SIDE_MIN_H = 0.32
SIDE_MAX_GAP = 0.22  # the column's distance from the slide's edge (a share of the width) a bleed bridges
GAP = 0.015  # how near (a share of the width) a bleed may come to something written
BACKGROUND_AREA = 0.5  # a place this large (a share of the slide) is the slide's background
FULL_AREA = 0.75  # … and covers the whole slide from this size
SCRIM_ALPHA = 86  # % opacity of the underlay under text on a picture
CIRCLE_ASPECT = (0.6, 1.6)  # a circle only from a place not too far from a square
MINOR_PH = {"sldNum", "dt", "ftr"}


@dataclass
class Frame:
    """The picture's frame on the slide."""

    kind: str  # bleed | background | circle | rounded | template | plain
    box: tuple[int, int, int, int]
    geom: Optional[str] = None  # the picture's preset geometry (None: the place's own)
    adj: Optional[int] = None  # roundRect's corner, 1/100000 of the shorter side
    edges: tuple[str, ...] = ()  # the slide's edges the picture touches
    scrim: Optional[tuple[int, int, int, int]] = None  # the underlay under the text over the picture
    scrim_color: Optional[str] = None
    scrim_radius: float = 0.0  # the underlay's corner (the deck's rounded cards)
    to_back: bool = False  # the picture goes under everything on the slide (a background)
    raise_ids: list[str] = field(default_factory=list)  # page numbers, footers the picture covers: put over it

    @property
    def aspect(self) -> float:
        return self.box[2] / self.box[3] if self.box[3] > 0 else 1.0

    @property
    def composition(self) -> str:
        """The composition the picture is asked in (configs/images.yaml `prompt.frames`)."""
        if self.kind in ("background", "circle"):
            return self.kind
        r = self.aspect
        return "tall" if r < 0.85 else "wide" if r > 1.3 else "square"

    def public(self) -> dict:
        return {"kind": self.kind, "box": list(self.box), "edges": list(self.edges), "geom": self.geom}


@dataclass
class Language:
    """The forms a deck speaks in: its large round decor and rounded shapes (cards, frames, photos)."""

    circles: int = 0
    rounded: int = 0
    radius: float = 0.0  # the rounded shapes' corner, a share of their shorter side (median)

    @property
    def form(self) -> Optional[str]:
        if self.circles >= 2 and self.circles >= 0.5 * self.rounded:
            return "circle"
        if self.rounded >= 3:
            return "rounded"
        return None


# ------------------------------------------------------------------ what the deck and the slide hold


def _name(el) -> str:
    nv = el.find(".//" + q("p:cNvPr"))
    return (nv.get("name") or "") if nv is not None else ""


def _id(el) -> str:
    nv = el.find(".//" + q("p:cNvPr"))
    return (nv.get("id") or "") if nv is not None else ""


def _ours(el) -> bool:
    """A free picture place or its caption (they go when the picture comes in)."""
    from verstka.schemas.outline import PHOTO_PLACE_NAME

    n = _name(el)
    return n == PHOTO_PLACE_NAME or n.startswith("Photo caption")


def _text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(q("a:t"))).strip()


def _geom(el) -> Optional[str]:
    g = el.find(q("p:spPr") + "/" + q("a:prstGeom"))
    return g.get("prst") if g is not None else None


def _adj(el) -> Optional[int]:
    gd = el.find(q("p:spPr") + "/" + q("a:prstGeom") + "/" + q("a:avLst") + "/" + q("a:gd"))
    if gd is None:
        return None
    try:
        return int((gd.get("fmla") or "").split()[-1])
    except (ValueError, IndexError):
        return None


def _bbox(el) -> Optional[tuple[int, int, int, int]]:
    from verstka.rendering.deck import element_bbox

    b = element_bbox(el)
    if not b or b[2] <= 0 or b[3] <= 0:
        return None
    return int(b[0]), int(b[1]), int(b[2]), int(b[3])


def _trees(slide) -> list:
    """The shape trees under and on the slide: its master's and its layout's (when shown), then its own."""
    out = []
    try:
        layout = slide.slide_layout
        master = layout.slide_master
        show = slide._element.get("showMasterSp") != "0"
        if show and layout._element.get("showMasterSp") != "0":
            out.append(("master", master._element.cSld.find(q("p:spTree"))))
        if show:
            out.append(("layout", layout._element.cSld.find(q("p:spTree"))))
    except Exception:  # noqa: BLE001 - the slide's own shapes still count
        pass
    out.append(("slide", slide._element.cSld.find(q("p:spTree"))))
    return out


def deck_language(prs) -> Language:
    """The deck's forms: large circles (round decor, round photos) and rounded shapes, on its slides, their layouts
    and masters (each layout and master once)."""
    W, H = int(prs.slide_width), int(prs.slide_height)
    side = min(W, H)
    lang = Language()
    radii: list[float] = []
    seen: set[int] = set()
    trees = []
    for s in prs.slides:
        for where, tree in _trees(s):
            if tree is None or (where != "slide" and id(tree) in seen):
                continue
            seen.add(id(tree))
            trees.append(tree)
    for tree in trees:
        for el in tree.iter(q("p:sp"), q("p:pic")):
            if _ours(el):
                continue
            g = _geom(el)
            b = _bbox(el)
            if not g or b is None:
                continue
            short = min(b[2], b[3])
            if g == "ellipse":
                if short >= 0.12 * side and 0.8 <= b[2] / b[3] <= 1.25 and not _text_of(el):
                    lang.circles += 2 if etree.QName(el).localname == "pic" else 1
            elif g in ("roundRect", "round2SameRect", "snipRoundRect"):
                if short >= 0.06 * side:
                    lang.rounded += 1
                    a = _adj(el)
                    radii.append(min(0.5, (a if a is not None else 16667) / 100000))
    lang.radius = float(median(radii)) if radii else 0.0
    return lang


@dataclass
class _Thing:
    box: tuple[int, int, int, int]
    kind: str  # text | minor | solid (a picture, a chart, a table, a logo) | decor
    el_id: Optional[str] = None  # the slide's own shape (None: the layout's or the master's)
    z: int = -1  # its position in the slide's tree


def _ph_type(el) -> Optional[str]:
    ph = next(iter(el.iter(q("p:ph"))), None)
    return (ph.get("type") or "body") if ph is not None else None


def _ink_box(el, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """The part of a text box its words take (a title box spans the slide, its words often half of it): the widest
    line of every paragraph measured in its font, placed by the paragraph's alignment. The box itself when a run has
    no size of its own (an inherited size is not known here)."""
    from verstka.rendering.fonts import text_width_pt, wrap_lines

    x, y, w, h = box
    body = el.find(".//" + q("p:txBody"))
    if body is None:
        return box
    bp = body.find(q("a:bodyPr"))
    l_ins = int(bp.get("lIns", 91440)) if bp is not None else 91440
    r_ins = int(bp.get("rIns", 91440)) if bp is not None else 91440
    width_pt = max(1.0, (w - l_ins - r_ins) / EMU_PER_PT)
    x0, x1 = None, None
    for p in body.iter(q("a:p")):
        runs = [r for r in p.iter(q("a:r"))]
        text = "".join((r.findtext(q("a:t")) or "") for r in runs)
        if not text.strip():
            continue
        rpr = runs[0].find(q("a:rPr"))
        if rpr is None or not rpr.get("sz"):
            return box
        size = int(rpr.get("sz")) / 100
        latin = rpr.find(q("a:latin"))
        family = latin.get("typeface") if latin is not None else None
        bold = rpr.get("b") == "1"
        caps = rpr.get("cap") == "all"
        spc = int(rpr.get("spc") or 0) / 100
        try:
            lines = wrap_lines(text, family, size, bold, width_pt, caps=caps, spc_pt=spc)
            lw = max(text_width_pt(ln, family, size, bold, caps=caps, spc_pt=spc) for ln in lines) * EMU_PER_PT
        except Exception:  # noqa: BLE001
            return box
        ppr = p.find(q("a:pPr"))
        algn = ppr.get("algn") if ppr is not None else None
        ind = int(ppr.get("marL") or 0) if ppr is not None else 0
        lw = min(lw + ind + 0.04 * size * EMU_PER_PT, w - l_ins - r_ins)
        if algn == "ctr":
            a = x + l_ins + (w - l_ins - r_ins - lw) / 2
        elif algn == "r":
            a = x + w - r_ins - lw
        else:
            a = x + l_ins
        x0 = a if x0 is None else min(x0, a)
        x1 = a + lw if x1 is None else max(x1, a + lw)
    if x0 is None:
        return box
    return int(x0), y, int(x1 - x0), h


def _covered(b: tuple[int, int, int, int], by: tuple[int, int, int, int]) -> bool:
    ox = min(b[0] + b[2], by[0] + by[2]) - max(b[0], by[0])
    oy = min(b[1] + b[3], by[1] + by[3]) - max(b[1], by[1])
    return ox > 0 and oy > 0 and ox * oy >= 0.8 * b[2] * b[3]


def _things(slide, W: int, H: int, skip: set[str], place: Optional[tuple[int, int, int, int]] = None) -> list[_Thing]:
    """What stands on the slide (and its layout and master) besides the place. A shape of the slide without words under
    the place that the place already covers (the sample's own photo left under it) is the place's: the picture covers
    it too."""
    out: list[_Thing] = []
    tree0 = slide._element.cSld.find(q("p:spTree"))
    place_z = next((z for z, e in enumerate(tree0) if _id(e) in skip), None)
    for where, tree in _trees(slide):
        if tree is None:
            continue
        for z, el in enumerate(tree):
            tag = etree.QName(el).localname
            if tag not in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp", "AlternateContent"):
                continue
            if where == "slide" and (_id(el) in skip or _ours(el)):
                continue
            ph = _ph_type(el)
            if where != "slide" and ph is not None:
                continue  # a layout's placeholder shows only through the slide's own
            b = _bbox(el)
            if b is None and where == "slide" and ph is not None:
                b = _inherited(slide, el)
            if b is None:
                continue
            if where == "slide" and place is not None and place_z is not None and z < place_z and _covered(b, place) and not _text_of(el):
                continue
            area = b[2] * b[3]
            ground = area >= 0.85 * W * H
            text = _text_of(el)
            pics = tag == "pic" or any(True for _ in el.iter(q("p:pic")))
            if tag in ("graphicFrame", "AlternateContent"):
                kind = "solid"
            elif text:
                minor = ph in MINOR_PH or (len(text) <= 4 and area < 0.012 * W * H)
                kind = "minor" if minor else "text"
                if kind == "text" and tag == "sp":
                    b = _ink_box(el, b)
            elif pics:
                kind = "decor" if ground else "solid"
            else:
                kind = "decor"
            out.append(_Thing(b, kind, _id(el) if where == "slide" else None, z if where == "slide" else -1))
    return out


def _inherited(slide, el) -> Optional[tuple[int, int, int, int]]:
    sid = _id(el)
    for shp in slide.shapes:
        if str(shp.shape_id) == sid:
            try:
                if None not in (shp.left, shp.top, shp.width, shp.height) and shp.width > 0 and shp.height > 0:
                    return int(shp.left), int(shp.top), int(shp.width), int(shp.height)
            except Exception:  # noqa: BLE001
                return None
    return None


def _hits(a: tuple[int, int, int, int], b: tuple[int, int, int, int], pad: int = 0) -> bool:
    return (min(a[0] + a[2], b[0] + b[2] + pad) - max(a[0], b[0] - pad)) > 0 and (min(a[1] + a[3], b[1] + b[3] + pad) - max(a[1], b[1] - pad)) > 0


def _free(region: tuple[int, int, int, int], things: list[_Thing], pad: int) -> bool:
    if region[2] <= 0 or region[3] <= 0:
        return True
    return not any(t.kind in ("text", "solid") and _hits(region, t.box, pad) for t in things)


# ------------------------------------------------------------------ the frame


def _bleed(box, things: list[_Thing], W: int, H: int) -> Optional[tuple[tuple[int, int, int, int], tuple[str, ...]]]:
    x, y, w, h = box
    lg, rg = x, W - (x + w)
    if w > SIDE_MAX_W * W or h < SIDE_MIN_H * H or min(lg, rg) > SIDE_MAX_GAP * W:
        return None
    pad = int(GAP * W)
    right = rg <= lg
    reach = (x + w, y, max(0, W - x - w), h) if right else (0, y, max(0, x), h)
    if not _free(reach, things, pad):
        return None
    nx, nw = (x, W - x) if right else (0, x + w)
    if nw > SIDE_MAX_W * W:
        return None
    edges = ["right" if right else "left"]
    ny, nb = y, y + h
    if _free((nx, 0, nw, y), things, pad):
        ny = 0
        edges.append("top")
    if _free((nx, y + h, nw, H - y - h), things, pad):
        nb = H
        edges.append("bottom")
    if len(edges) == 1:
        return None  # a picture touching one edge only floats as a tab (the live run of 18.10, VK Tech): not a bleed
    return (nx, ny, nw, nb - ny), tuple(edges)


def _scrim(box, things: list[_Thing], W: int) -> Optional[tuple[int, int, int, int]]:
    over = [t.box for t in things if t.kind == "text" and _hits(box, t.box)]
    if not over:
        return None
    pad = int(0.025 * W)
    x0 = max(box[0], min(b[0] for b in over) - pad)
    y0 = max(box[1], min(b[1] for b in over) - pad)
    x1 = min(box[0] + box[2], max(b[0] + b[2] for b in over) + pad)
    y1 = min(box[1] + box[3], max(b[1] + b[3] for b in over) + pad)
    return x0, y0, x1 - x0, y1 - y0


def _ground(slide, box) -> str:
    try:
        from verstka.rendering.charts import slide_ground
        from verstka.schemas.common import Bbox

        g = slide_ground(slide, Bbox(x=box[0], y=box[1], w=box[2], h=box[3]))
        if g and len(g) == 6:
            return g.upper()
    except Exception:  # noqa: BLE001
        pass
    return "FFFFFF"


def plan_frame(slide, place_id: str, box: tuple[int, int, int, int], W: int, H: int, lang: Optional[Language] = None) -> Frame:
    """The frame of the picture for the place `place_id` (its box `box`) on `slide`."""
    lang = lang or Language()
    tree = slide._element.cSld.find(q("p:spTree"))
    el = next((e for e in tree if _id(e) == place_id), None)
    own = _geom(el) if el is not None else None
    if own and own not in ("rect", "roundRect"):
        return Frame("template", box)  # the template drew the place in a form of its own: it stays
    things = _things(slide, W, H, {place_id}, box)
    x, y, w, h = box
    if w * h >= BACKGROUND_AREA * W * H:
        full = (0, 0, W, H) if w * h >= FULL_AREA * W * H else box
        scrim = _scrim(full, things, W)
        color = None
        if scrim:
            # the slide's own ground under the underlay — not the free place's quiet fill, which the picture replaces
            at = list(tree).index(el) if el is not None else None
            if el is not None:
                tree.remove(el)
            try:
                color = _ground(slide, scrim)
            finally:
                if el is not None:
                    tree.insert(at, el)
        return Frame("background", full, geom="rect", edges=("left", "top", "right", "bottom") if full == (0, 0, W, H) else (),
                     scrim=scrim, scrim_color=color, scrim_radius=lang.radius if lang.form else 0.0, to_back=True)
    if lang.form == "circle" and CIRCLE_ASPECT[0] <= w / h <= CIRCLE_ASPECT[1]:
        d = min(w, h)
        return Frame("circle", (x + (w - d) // 2, y + (h - d) // 2, d, d), geom="ellipse")
    got = _bleed(box, things, W, H)
    if got is not None:
        nb, edges = got
        raise_ids = [t.el_id for t in things if t.kind == "minor" and t.el_id and _hits(nb, t.box)]
        return Frame("bleed", nb, geom="rect", edges=edges, raise_ids=raise_ids)
    if lang.form in ("rounded", "circle") or own == "roundRect":
        r = lang.radius or 0.08
        return Frame("rounded", box, geom="roundRect", adj=int(min(0.5, max(0.04, r)) * 100000))
    return Frame("plain", box)


def frames_of(prs, places: list) -> dict[tuple[int, str], Frame]:
    """The frame of every place ({(slide, shape id): frame}) of a deck (images/places.py `Place`)."""
    W, H = int(prs.slide_width), int(prs.slide_height)
    lang = deck_language(prs)
    slides = list(prs.slides)
    out: dict[tuple[int, str], Frame] = {}
    for pl in places:
        try:
            out[(pl.slide, pl.shape_id)] = plan_frame(slides[pl.slide - 1], pl.shape_id, pl.box, W, H, lang)
        except Exception:  # noqa: BLE001 - the picture stands in its place as drawn
            log.warning("picture frame not planned on slide %s", pl.slide, exc_info=True)
    return out


# ------------------------------------------------------------------ putting it on the slide


def _next_id(slide) -> int:
    ids = [int(nv.get("id")) for nv in slide._element.iter(q("p:cNvPr")) if (nv.get("id") or "").isdigit()]
    return max(ids, default=1) + 1


def scrim_xml(slide, box: tuple[int, int, int, int], color: str, alpha: int = SCRIM_ALPHA, radius: float = 0.0):
    """The underlay under the text over a picture: the slide's ground colour, slightly see-through."""
    sp = etree.Element(q("p:sp"))
    nv = etree.SubElement(sp, q("p:nvSpPr"))
    c = etree.SubElement(nv, q("p:cNvPr"))
    c.set("id", str(_next_id(slide)))
    c.set("name", "Подложка под текст")
    etree.SubElement(nv, q("p:cNvSpPr"))
    etree.SubElement(nv, q("p:nvPr"))
    sppr = etree.SubElement(sp, q("p:spPr"))
    xf = etree.SubElement(sppr, q("a:xfrm"))
    etree.SubElement(xf, q("a:off"), x=str(int(box[0])), y=str(int(box[1])))
    etree.SubElement(xf, q("a:ext"), cx=str(int(box[2])), cy=str(int(box[3])))
    g = etree.SubElement(sppr, q("a:prstGeom"))
    g.set("prst", "roundRect" if radius else "rect")
    av = etree.SubElement(g, q("a:avLst"))
    if radius:
        etree.SubElement(av, q("a:gd"), name="adj", fmla=f"val {int(min(0.5, radius) * 100000)}")
    sf = etree.SubElement(sppr, q("a:solidFill"))
    clr = etree.SubElement(sf, q("a:srgbClr"))
    clr.set("val", color.upper())
    etree.SubElement(clr, q("a:alpha")).set("val", str(int(alpha * 1000)))
    etree.SubElement(sppr, q("a:ln")).append(etree.Element(q("a:noFill")))
    return sp


def set_geometry(pic, frame: Frame) -> None:
    """The picture's form (its box is set when it is made)."""
    sppr = pic.find(q("p:spPr"))
    if sppr is None or not frame.geom:
        return
    old = sppr.find(q("a:prstGeom"))
    g = etree.Element(q("a:prstGeom"))
    g.set("prst", frame.geom)
    av = etree.SubElement(g, q("a:avLst"))
    if frame.geom == "roundRect" and frame.adj:
        etree.SubElement(av, q("a:gd"), name="adj", fmla=f"val {int(frame.adj)}")
    if old is not None:
        sppr.replace(old, g)
    else:
        xf = sppr.find(q("a:xfrm"))
        (xf.addnext(g) if xf is not None else sppr.insert(0, g))


def stand(slide, pic, frame: Frame, at: int) -> list[str]:
    """The picture `pic` (already in its frame's box and form) put into the slide's tree: at `at` (the place's
    position), under everything for a background with the underlay over it; page numbers and footers it covers go
    over it. Returns the ids of the shapes added with it (the underlay)."""
    tree = slide._element.cSld.find(q("p:spTree"))
    added: list[str] = []
    if frame.to_back:
        first = next((i for i, e in enumerate(tree) if etree.QName(e).localname not in ("nvGrpSpPr", "grpSpPr", "extLst")), len(tree))
        tree.insert(first, pic)
        if frame.scrim:
            s = scrim_xml(slide, frame.scrim, frame.scrim_color or "FFFFFF", radius=frame.scrim_radius)
            pic.addnext(s)
            added.append(_id(s))
    else:
        tree.insert(at, pic)
    for sid in frame.raise_ids:
        el = next((e for e in tree if _id(e) == sid), None)
        if el is not None and list(tree).index(el) < list(tree).index(pic):
            tree.remove(el)
            ext = tree.find(q("p:extLst"))
            (ext.addprevious(el) if ext is not None else tree.append(el))
    return added
