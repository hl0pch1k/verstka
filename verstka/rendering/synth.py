"""Synth renderer: compose a slide from template tokens and components when no sample pattern fits."""

from __future__ import annotations

import copy
import math
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from lxml import etree
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.slide import Slide
from pptx.util import Emu, Pt

from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.assets_pick import pick_asset
from verstka.rendering.charts import add_chart
from verstka.rendering.clone import _fill_hex, _SlideCtx, clear_width, renumber_page_chrome
from verstka.rendering.fonts import text_width_pt
from verstka.rendering.deck import DeckBuilder, element_bbox, is_nested, remove_element, slide_shape_elements
from verstka.rendering.fit import fit_size
from verstka.rendering.images import insert_picture
from verstka.rendering.tables import add_table
from verstka.rendering.textfill import ParagraphSpec, fill_text
from verstka.schemas.common import EMU_PER_INCH, EMU_PER_PT, Bbox, Family, PatternKind, SlotRole, contrast_ratio
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideItem
from verstka.schemas.template import Pattern, TemplateManifest

_DEFAULT_RADIUS_EMU = int(0.12 * EMU_PER_INCH)
_CONTENT_KINDS = (PatternKind.bullets, PatternKind.cards, PatternKind.freeform, PatternKind.two_column, PatternKind.stat_row)


def card_adj(radius_emu: int, w: int, h: int) -> float:
    """roundRect adjustment for an absolute corner radius: relative to the shorter side, capped so cards never turn into capsules."""
    side = min(w, h)
    if radius_emu <= 0 or side <= 0:
        return 0.0
    return min(radius_emu / side, 0.25)


def _card_radius_emu(manifest: TemplateManifest) -> int:
    """Corner radius of the template's cards as an absolute size.

    A sample's `adj` is relative to the sample's shorter side, so it is converted with the sample card size;
    when only a ratio is known (e.g. from pill-shaped chips) a conventional 0.12 inch is used instead.
    """
    card = manifest.components.card
    if card and card.radius is not None and card.width_frac and card.height_frac:
        side = min(card.width_frac * manifest.slide_size.w, card.height_frac * manifest.slide_size.h)
        return int(max(0.0, min(card.radius, 0.5)) * side)
    return _DEFAULT_RADIUS_EMU


class _Palette:
    def __init__(self, manifest: TemplateManifest, family: Family) -> None:
        t = manifest.tokens
        self.family = family
        self.bg = t.color_for("background.dark" if family == Family.dark else "background.light") or ("000000" if family == Family.dark else "FFFFFF")
        text = t.color_for("text.primary") or ("FFFFFF" if family == Family.dark else "000000")
        if contrast_ratio(text, self.bg) < 3.0:
            text = "FFFFFF" if family == Family.dark else "000000"
        self.text = text
        sec = t.color_for("text.secondary")
        self.text2 = sec if sec and contrast_ratio(sec, self.bg) >= 3.0 else self.text
        self.accent = t.accents()[0] if t.accents() else "0077FF"
        surf = t.color_for("surface")
        self.surface = surf if surf and 1.02 < contrast_ratio(surf, self.bg) < 2.5 else None
        card = manifest.components.card
        self.card_fill = (card.fill_hex if card and card.fill_hex and 1.0 < contrast_ratio(card.fill_hex, self.bg) < 3.0 else self.surface)
        self.card_line = card.line_hex if card else None
        self.radius_emu = _card_radius_emu(manifest)


def _family_for(oslide: OutlineSlide, manifest: TemplateManifest) -> Family:
    fams = Counter(p.family for p in manifest.patterns if p.kind == oslide.kind)
    if fams:
        return fams.most_common(1)[0][0]
    fams = Counter(p.family for p in manifest.patterns)
    return fams.most_common(1)[0][0] if fams else Family.light


def _layout_family(manifest: TemplateManifest, part: str, default: Family) -> Family:
    fams = Counter(p.family for p in manifest.patterns if p.layout_part == part)
    return fams.most_common(1)[0][0] if fams else default


def _layout_for(builder: DeckBuilder, manifest: TemplateManifest, family: Family, kind: PatternKind):
    """(layout, family): the layout used by the most sample slides of this family, searched over every master.

    Preference: same kind → content kinds → any kind of the family → any family (then the returned family is the
    one of the samples on that layout, so the palette matches its background). When no sample resolves to a
    layout of the package, a title-only-like layout is chosen — never blindly the last one.
    """
    by_partname = {str(l.part.partname).lstrip("/"): l for l in builder.layouts()}
    known = [p for p in manifest.patterns if p.layout_part and p.layout_part in by_partname]
    tiers = [
        [p for p in known if p.family == family and p.kind == kind],
        [p for p in known if p.family == family and p.kind in _CONTENT_KINDS],
        [p for p in known if p.family == family],
        known,
    ]
    for prefs in tiers:
        if prefs:
            part = Counter(p.layout_part for p in prefs).most_common(1)[0][0]
            return by_partname[part], _layout_family(manifest, part, family)

    def rank(layout):
        phs = list(layout.placeholders)
        titled = any(str(ph.placeholder_format.type).split(".")[-1].split(" ")[0] in ("TITLE", "CENTER_TITLE") for ph in phs)
        return (0 if titled else 1, len(phs))

    layouts = builder.layouts()
    return (min(layouts, key=rank) if layouts else builder.prs.slide_layouts[0]), family


_CANVAS_KINDS = {
    "title": (PatternKind.title, PatternKind.section, PatternKind.thanks),
    "section": (PatternKind.section,),
    "thanks": (PatternKind.thanks, PatternKind.title, PatternKind.section),
}
_NOT_CONTENT_CANVAS = {PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.quote}


def _top_title(p: Pattern) -> Optional[object]:
    titles = [s for s in p.slots if s.role == SlotRole.title]
    return min(titles, key=lambda s: s.bbox.y) if titles else None


def _canvas_for(manifest: TemplateManifest, family: Family, comp: str) -> Optional[Pattern]:
    """The sample slide a synthesized slide is drawn on: same family, a writable title at the top, as little content
    as possible. Cloning it keeps what a layout alone would lose — backgrounds and chrome that a designer drew on
    the slides themselves (hand-made decks, picture backgrounds) and the look of the template's headings."""
    kinds = _CANVAS_KINDS.get(comp)
    best: Optional[tuple] = None
    for p in manifest.patterns:
        if p.family != family or p.quality < 0.5 or p.reference:
            continue
        title = _top_title(p)
        if title is None:
            continue
        if kinds is not None:
            if p.kind not in kinds:
                continue
            rank = kinds.index(p.kind)
        else:
            if p.kind in _NOT_CONTENT_CANVAS or title.bbox.y > 0.3 or title.bbox.w < 0.2:
                continue
            rank = 0
        big_pictures = sum(1 for s in p.slots if s.role == SlotRole.image and s.bbox.area >= 0.05) + sum(1 for b in p.decor_boxes if b.area >= 0.05)
        clutter = len(p.slots) + sum(len(g.member_shape_ids) for g in p.repeat_groups) + len(p.decor_assets) + 5 * big_pictures
        key = (rank, clutter, -p.quality, p.source_slide)
        if best is None or key < best[0]:
            best = (key, p)
    return best[1] if best else None


def _readable(ground: str, preferred: list) -> str:
    cands = [c for c in preferred if c] + ["000000", "FFFFFF"]
    return next((c for c in cands if contrast_ratio(c, ground) >= 4.5), max(cands, key=lambda c: contrast_ratio(c, ground)))


def _paints(el) -> bool:
    spPr = el.find(q("p:spPr"))
    if spPr is not None:
        if spPr.find(q("a:noFill")) is not None:
            return False
        if any(spPr.find(q(t)) is not None for t in ("a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill")):
            return True
    ref = el.find(q("p:style") + "/" + q("a:fillRef"))
    return ref is not None and (ref.get("idx") or "0") != "0"


def _slide_on_canvas(builder: DeckBuilder, canvas: Pattern, W: int, H: int, keep_extra: Optional[set[str]] = None):
    """Clone the canvas sample and strip it to background + chrome + the title slot (+ the art to keep).
    Returns (slide, title shape, heading ground)."""
    slide = builder.clone_slide(canvas.source_slide)
    els = slide_shape_elements(slide)
    title = _top_title(canvas)
    keep = set(canvas.chrome_shape_ids) | ({title.shape_id} if title else set()) | set(keep_extra or ())
    # the label the heading is printed on (a pill) is part of the heading's style: its colour was chosen for it
    tb = element_bbox(els[title.shape_id]) if title and title.shape_id in els else None
    ground: Optional[tuple[Bbox, Optional[str]]] = None  # a half-slide panel the heading stands on
    if tb:
        tol = int(0.01 * W)
        for sid, el in els.items():
            b = element_bbox(el)
            if sid in keep or not b or is_nested(el) or etree.QName(el).localname != "sp":
                continue  # the heading's ground may be a small pill or a half-slide panel — it stays either way
            if "".join(t.text or "" for t in el.iter(q("a:t"))).strip() or not _paints(el):
                continue
            if b[0] - tol <= tb[0] <= b[0] + b[2] - int(0.04 * W) and b[1] - tol <= tb[1] and b[1] + b[3] + tol >= tb[1] + tb[3]:
                keep.add(sid)
                if b[2] * b[3] > 0.25 * W * H and (ground is None or b[2] * b[3] > ground[0].area):
                    ground = (Bbox(x=b[0], y=b[1], w=b[2], h=b[3]), _fill_hex(el))
    for sid, el in els.items():
        if sid in keep or is_nested(el) or el.getparent() is None:
            continue
        b = element_bbox(el)
        full_bleed = b is not None and b[2] * b[3] >= 0.9 * W * H and not "".join(t.text or "" for t in el.iter(q("a:t"))).strip()
        if full_bleed:
            continue  # a background drawn as a slide-sized rectangle or picture
        remove_element(el)
    renumber_page_chrome(slide_shape_elements(slide), canvas.chrome_shape_ids, canvas.source_slide, len(builder.created))
    title_shape = next((sh for sh in slide.shapes if title is not None and str(sh.shape_id) == title.shape_id), None)
    if title_shape is not None and is_nested(title_shape._element):
        title_shape = None
    return slide, title_shape, ground


def _adopt_canvas_colors(pal: "_Palette", canvas: Pattern, manifest: TemplateManifest) -> None:
    """On a cloned sample the ground is the sample's own (often a picture): its heading colour is known to read on it,
    so running text takes that colour too; a solid ground of the sample replaces the family's generic one."""
    bg = next((b.hex for b in manifest.tokens.backgrounds if canvas.source_slide in b.slides and b.hex), None)
    if bg:
        pal.bg = bg
    title = _top_title(canvas)
    color = title.style.color_hex if title is not None else None
    if color and contrast_ratio(color, pal.bg) >= 3.0 or (color and not bg):
        pal.text = pal.text2 = color


def _title_style(manifest: TemplateManifest, family: Family, pal: _Palette) -> tuple[float, str, bool, Optional[str]]:
    slots = [s for p in manifest.patterns if p.family == family for s in p.slots if s.role == SlotRole.title and s.style.size_pt]
    size = manifest.tokens.typography.size_for("h1", 28.0)
    color = pal.text
    bold = False
    font = manifest.tokens.typography.primary_family
    if slots:
        sizes = Counter(round(s.style.size_pt or size) for s in slots)
        size = float(sizes.most_common(1)[0][0])
        colors = Counter(s.style.color_hex for s in slots if s.style.color_hex)
        if colors:
            cand = colors.most_common(1)[0][0]
            if contrast_ratio(cand, pal.bg) >= 3.0:
                color = cand
        bold = sum(1 for s in slots if s.style.bold) > len(slots) / 2
        fonts = Counter(s.style.font_family for s in slots if s.style.font_family)
        if fonts:
            font = fonts.most_common(1)[0][0]
    return size, color, bold, font


def _textbox(slide: Slide, box: Bbox, paragraphs: list[ParagraphSpec], *, size: float, color: str, font: Optional[str], bold: bool = False, align: str = "l", anchor: str = "t", scale: Optional[list[float]] = None, line_spacing: float = 1.2, fit: bool = True):
    tb = slide.shapes.add_textbox(Emu(box.x), Emu(box.y), Emu(box.w), Emu(box.h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(45720)
    tf.margin_top = tf.margin_bottom = Emu(22860)
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "ctr": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    # a size asked as a multiple of a role («display × 0.8») lands on the next size the template really uses
    on_scale = [s for s in (scale or []) if s <= size + 0.05]
    if on_scale:
        size = max(on_scale)
    target = size
    if fit:
        res = fit_size([p.text for p in paragraphs], box, font, size, bold, scale or [], insets_emu=(45720, 22860, 45720, 22860), line_spacing=line_spacing, min_ratio=0.55)
        target = res.size_pt
    p0 = tf.paragraphs[0]
    p0.alignment = {"l": PP_ALIGN.LEFT, "ctr": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
    r = p0.add_run()
    r.text = ""
    r.font.size = Pt(target)
    r.font.bold = bold
    r.font.color.rgb = RGBColor.from_string(color)
    if font:
        r.font.name = font
    specs = [ParagraphSpec(p.text, bullet=p.bullet, level=p.level, bold=p.bold if p.bold is not None else None, size_pt=p.size_pt, color_hex=p.color_hex) for p in paragraphs]
    fill_text(tb._element, specs, size_pt=target)
    if any(p.bullet for p in paragraphs):
        for pPr in tb._element.iter(q("a:pPr")):
            if pPr.find(q("a:buChar")) is not None:
                pPr.set("marL", "285750")
                pPr.set("indent", "-285750")
    for p in tb.text_frame.paragraphs:
        p.alignment = p0.alignment
        p.space_after = Pt(max(target * 0.35, 3))
    return tb


def _rect(slide: Slide, box: Bbox, fill: Optional[str], line: Optional[str], radius_emu: int):
    adj = card_adj(radius_emu, box.w, box.h)
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if adj > 0 else MSO_SHAPE.RECTANGLE, Emu(box.x), Emu(box.y), Emu(box.w), Emu(box.h))
    if adj > 0:
        shape.adjustments[0] = adj
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    else:
        shape.fill.background()
    if line:
        shape.line.color.rgb = RGBColor.from_string(line)
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    return shape


def _circle(slide: Slide, box: Bbox, fill: str, text: str, text_color: str, size: float, font: Optional[str]):
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(box.x), Emu(box.y), Emu(box.w), Emu(box.h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    shape.line.fill.background()
    shape.shadow.inherit = False
    tf = shape.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = RGBColor.from_string(text_color)
    if font:
        r.font.name = font
    return shape


def _items(oslide: OutlineSlide) -> list[SlideItem]:
    c = oslide.content
    if c.items:
        return list(c.items)
    if c.columns:
        return list(c.columns)
    if c.numbers:
        return [SlideItem(title=n.value, text=n.label, number=n.value) for n in c.numbers]
    return [SlideItem(title=b) for b in c.bullets]


_COVER_COMPS = ("title", "section", "thanks")
# compositions that need the whole width of the slide (a half-slide panel of the canvas is too narrow for them)
_WIDE_COMPS = ("cards", "process", "agenda", "comparison", "two_column", "table", "chart_text", "stat_row")


def _needs_width(oslide: OutlineSlide, comp: str) -> bool:
    c = oslide.content
    n = len(c.items) or len(c.columns) or len(c.numbers) or len(c.bullets)
    if comp in ("table", "chart_text") or c.table is not None or c.chart is not None:
        return True
    if comp in _WIDE_COMPS and n >= 3:
        return True
    if comp == "bullets" and (len(c.bullets) >= 5 or sum(len(b) for b in c.bullets) > 320):
        return True
    return False


def _canvas_ground(builder: DeckBuilder, canvas: Pattern) -> Optional[Bbox]:
    """The half-slide panel a canvas's heading stands on (LCT: a white half next to a photo), read from the sample."""
    W, H = builder.slide_w, builder.slide_h
    try:
        els = slide_shape_elements(builder.source_slide(canvas.source_slide))
    except IndexError:
        return None
    title = _top_title(canvas)
    if title is None or title.shape_id not in els:
        return None
    tb = element_bbox(els[title.shape_id])
    if not tb:
        return None
    tol = int(0.01 * W)
    best: Optional[Bbox] = None
    for sid, el in els.items():
        b = element_bbox(el)
        if sid == title.shape_id or not b or is_nested(el) or etree.QName(el).localname != "sp":
            continue
        if "".join(t.text or "" for t in el.iter(q("a:t"))).strip() or not _paints(el):
            continue
        if b[0] - tol <= tb[0] <= b[0] + b[2] - int(0.04 * W) and b[1] - tol <= tb[1] and b[1] + b[3] + tol >= tb[1] + tb[3] and b[2] * b[3] > 0.25 * W * H:
            bb = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
            if best is None or bb.area > best.area:
                best = bb
    return best


def _layout_pictures(builder: DeckBuilder, pattern: Pattern) -> float:
    """Share of the slide covered by what the sample's layout draws besides its background — a photo collage or a
    dark code panel of the layout comes with every slide cloned from that sample."""
    W, H = builder.slide_w, builder.slide_h
    try:
        layout = builder.source_slide(pattern.source_slide).slide_layout
    except IndexError:
        return 0.0
    total = 0
    for el in layout._element.cSld.find(q("p:spTree")):
        tag = etree.QName(el).localname
        if tag not in ("sp", "pic", "grpSp", "graphicFrame") or el.find(".//" + q("p:ph")) is not None:
            continue  # placeholders of the layout are not drawn on a slide that does not use them
        if tag == "sp" and not _paints(el) and el.find(".//" + q("a:blip")) is None:
            continue
        b = element_bbox(el)
        if b and 0.03 * W * H <= b[2] * b[3] < 0.9 * W * H:
            total += b[2] * b[3]
    return total / (W * H)


def _has_pill(builder: DeckBuilder, canvas: Pattern) -> bool:
    t = _top_title(canvas)
    try:
        src = builder.source_slide(canvas.source_slide)
    except IndexError:
        return False
    el = slide_shape_elements(src).get(t.shape_id) if t else None
    return el is not None and _backing_of(src, el, builder.slide_w, builder.slide_h) is not None


def _bottom_chrome(builder: DeckBuilder, pattern: Pattern) -> int:
    """Brand marks a canvas carries at the foot of the slide (logos, footers) — its own chrome and its layout's."""
    cache = builder.__dict__.setdefault("_bottom_chrome", {})
    if pattern.id in cache:
        return cache[pattern.id]
    W, H = builder.slide_w, builder.slide_h
    n = 0
    try:
        src = builder.source_slide(pattern.source_slide)
        els = slide_shape_elements(src)
        items = [els[i] for i in pattern.chrome_shape_ids if i in els]
        items += [el for el in src.slide_layout._element.cSld.find(q("p:spTree")) if el.find(".//" + q("p:ph")) is None]
        for el in items:
            b = element_bbox(el)
            if b and b[1] >= 0.85 * H and b[2] * b[3] < 0.2 * W * H:
                n += 1
    except Exception:  # noqa: BLE001
        pass
    cache[pattern.id] = n
    return n


def _chrome_floor(builder: DeckBuilder, manifest: TemplateManifest, family: Family) -> int:
    """The foot chrome most content samples of the family have: a canvas without it would drop the brand marks."""
    counts = sorted(_bottom_chrome(builder, p) for p in _content_patterns(manifest) if p.family == family)
    return counts[len(counts) // 2] if counts else 0


def _pick_canvas(builder: DeckBuilder, manifest: TemplateManifest, family: Family, comp: str, wide: bool, need_pill: bool = False) -> Optional[Pattern]:
    """The cleanest canvas for a composition: no pictures of its layout in the content area, and — for a composition
    that needs the whole width — no half-slide panel under the heading."""
    tried: set[str] = set()
    m = manifest
    first = canvas = _canvas_for(manifest, family, comp)
    fallback = None
    while canvas is not None:
        floor = min(_chrome_floor(builder, manifest, family), 2)
        ok = _layout_pictures(builder, canvas) < 0.12 and (not need_pill or _has_pill(builder, canvas)) and _bg_art(builder, canvas.source_slide) is None and _bottom_chrome(builder, canvas) >= floor
        if ok and wide:
            g = _canvas_ground(builder, canvas)
            if g is not None and g.w < 0.7 * builder.slide_w:
                fallback = fallback or canvas
                ok = False
        if ok:
            return canvas
        tried.add(canvas.id)
        m = m.model_copy(update={"patterns": [p for p in m.patterns if p.id not in tried]})
        canvas = _canvas_for(m, family, comp)
    return fallback or first


def _scheme(builder: DeckBuilder) -> dict[str, str]:
    """Theme colours of the first master (bg1/tx1/accent1… → hex) for sample shapes painted with scheme colours."""
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT

    out: dict[str, str] = {}
    try:
        master = builder.prs.slide_masters[0]
        theme = etree.fromstring(master.part.part_related_by(RT.THEME).blob)
        cs = theme.find(".//" + q("a:clrScheme"))
        for entry in cs if cs is not None else []:
            if len(entry) == 0:
                continue
            c = entry[0]
            tag = etree.QName(c).localname
            name = etree.QName(entry).localname
            if tag == "srgbClr":
                out[name] = (c.get("val") or "000000").upper()
            elif tag == "sysClr":
                out[name] = (c.get("lastClr") or ("000000" if c.get("val") == "windowText" else "FFFFFF")).upper()
        cmap = master._element.find(q("p:clrMap"))
        for k, v in (cmap.attrib.items() if cmap is not None else [("bg1", "lt1"), ("tx1", "dk1"), ("bg2", "lt2"), ("tx2", "dk2")]):
            if v in out:
                out[k] = out[v]
    except Exception:  # noqa: BLE001
        pass
    return out


def _resolved_fill(el, scheme: dict[str, str], line: bool = False) -> Optional[str]:
    from verstka.analysis.theme import _apply_modifiers

    spPr = el.find(q("p:spPr"))
    if spPr is None:
        return None
    holder = spPr.find(q("a:ln")) if line else spPr
    if holder is None or holder.find(q("a:noFill")) is not None:
        return None
    for tag in ("a:solidFill", "a:gradFill"):
        f = holder.find(q(tag))
        if f is None:
            continue
        clr = next((c for c in f.iter() if etree.QName(c).localname in ("srgbClr", "schemeClr")), None)
        if clr is None:
            return None
        base = (clr.get("val") or "").upper() if etree.QName(clr).localname == "srgbClr" else scheme.get(clr.get("val") or "")
        return _apply_modifiers(base, clr) if base and len(base) == 6 else None
    if not line:
        ref = el.find(q("p:style") + "/" + q("a:fillRef"))
        if ref is not None and (ref.get("idx") or "0") != "0":
            clr = next((c for c in ref if etree.QName(c).localname in ("srgbClr", "schemeClr")), None)
            if clr is not None:
                base = (clr.get("val") or "").upper() if etree.QName(clr).localname == "srgbClr" else scheme.get(clr.get("val") or "")
                return _apply_modifiers(base, clr) if base and len(base) == 6 else None
    return None


_CARD_GEOMS = ("rect", "roundRect", "round2SameRect", "round1Rect", "snip1Rect", "snip2SameRect")


def _card_proto(builder: DeckBuilder, manifest: TemplateManifest, family: Family, ground: str):
    """The template's own card: the painted rectangle that holds the text of a repeat-group cell on a sample slide of
    this family. The most frequent style wins (by fill/line/geometry), so one odd sample does not define the look.
    Returned as a detached copy with its colours resolved: (element, fill, line) or None. Found once per deck."""
    cache = builder.__dict__.setdefault("_card_protos", {})
    key = (family, ground)
    if key not in cache:
        cache[key] = _find_card_proto(builder, manifest, family, ground)
    found = cache[key]
    return (copy.deepcopy(found[0]), found[1], found[2]) if found else None


def _find_card_proto(builder: DeckBuilder, manifest: TemplateManifest, family: Family, ground: str):
    W, H = builder.slide_w, builder.slide_h
    scheme = _scheme(builder)
    votes: dict[tuple, list] = {}
    for p in manifest.patterns:
        if p.reference or p.family != family or not p.repeat_groups or p.quality < 0.4:
            continue
        try:
            els = slide_shape_elements(builder.source_slide(p.source_slide))
        except IndexError:
            continue
        slot_of = {s.shape_id: s for s in p.slots}
        for g in p.repeat_groups:
            for cell in g.member_shape_ids[:1]:
                members = [(sid, els[sid]) for sid in cell if sid in els]
                text_boxes = [element_bbox(e) for sid, e in members if sid in slot_of]
                for sid, el in members:
                    if etree.QName(el).localname != "sp" or is_nested(el):
                        continue
                    geom = el.find(q("p:spPr") + "/" + q("a:prstGeom"))
                    if geom is None or geom.get("prst") not in _CARD_GEOMS:
                        continue
                    b = element_bbox(el)
                    if not b or not (0.012 <= b[2] * b[3] / (W * H) <= 0.4):
                        continue
                    fill = _resolved_fill(el, scheme)
                    line = _resolved_fill(el, scheme, line=True)
                    if not fill and not line:
                        continue
                    if not fill and not line:
                        continue
                    holds = sid in slot_of or any(tb and b[0] <= tb[0] + tb[2] / 2 <= b[0] + b[2] and b[1] <= tb[1] + tb[3] / 2 <= b[1] + b[3] for tb in text_boxes if tb)
                    if not holds:
                        continue
                    key = (fill, line, geom.get("prst"))
                    votes.setdefault(key, []).append((b[2] * b[3], el))
    if not votes:
        return None
    # the plain card wins over a highlighted one (an accent outline marks one card of a row, not every card)
    key = max(votes, key=lambda k: (len(votes[k]), k[1] is None, max(a for a, _ in votes[k])))
    el = copy.deepcopy(max(votes[key], key=lambda t: t[0])[1])
    fill, line = key[0], key[1]
    spPr = el.find(q("p:spPr"))
    if fill and not line and contrast_ratio(fill, ground) < 1.12 and spPr is not None and spPr.find(q("a:effectLst")) is None:
        # a white card on an almost white ground (VK Tech) stands apart by a soft shadow, as in the template
        eff = etree.SubElement(spPr, q("a:effectLst"))
        sh = etree.SubElement(eff, q("a:outerShdw"))
        sh.set("blurRad", str(int(0.03 * H)))
        sh.set("dist", str(int(0.004 * H)))
        sh.set("dir", "5400000")
        sh.set("algn", "t")
        sh.set("rotWithShape", "0")
        clr = etree.SubElement(sh, q("a:srgbClr"))
        clr.set("val", "0B1F44")
        etree.SubElement(clr, q("a:alpha")).set("val", "9000")
    # the copy is painted with resolved colours: a scheme colour of another master must not change on our slide
    return el, fill, line


def _title_anchor(title_shape) -> str:
    """Vertical anchor of a title shape: its own bodyPr, else the placeholder chain (layout, master)."""
    el = title_shape._element
    node = el
    for _ in range(3):
        bp = node.find(".//" + q("a:bodyPr")) if node is not None else None
        if bp is not None and bp.get("anchor"):
            return bp.get("anchor")
        try:
            base = title_shape._base_placeholder if node is el else None
        except Exception:  # noqa: BLE001
            base = None
        if base is None:
            break
        title_shape = base
        node = base._element
    return "t"


def _backing_of(slide: Slide, title_el, W: int, H: int):
    """A small label (pill) painted under the start of the heading box: (element, bbox) or None."""
    tb = element_bbox(title_el)
    if not tb:
        return None
    tol = int(0.01 * W)
    best = None
    for el in slide._element.cSld.find(q("p:spTree")):
        if el is title_el or etree.QName(el).localname != "sp":
            continue
        if "".join(t.text or "" for t in el.iter(q("a:t"))).strip() or not _paints(el):
            continue
        b = element_bbox(el)
        if not b or b[2] * b[3] > 0.1 * W * H or b[3] > 0.16 * H:
            continue
        if b[0] - tol <= tb[0] <= b[0] + b[2] - int(0.04 * W) and b[1] - tol <= tb[1] + tb[3] // 2 <= b[1] + b[3] + tol:
            if best is None or b[2] * b[3] < best[1].area:
                best = (el, Bbox(x=b[0], y=b[1], w=b[2], h=b[3]))
    return best


def render_synth(builder: DeckBuilder, plan_slide: LayoutSlide, oslide: OutlineSlide, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline) -> tuple[Slide, list[str]]:
    comp = plan_slide.composition or "bullets"
    if comp in _COVER_COMPS:
        return _render_cover(builder, plan_slide, oslide, manifest, ws, outline)
    return _render_content(builder, comp, oslide, manifest, ws, outline)


@dataclass
class Art:
    """A sample whose decorative picture stands on one side: the picture stays, the content takes the other side."""

    pattern: Pattern
    keep_ids: set[str]
    box: Bbox
    side: str  # "left" | "right"


_ART_KINDS_EXCLUDED = (PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.mockup, PatternKind.image_text, PatternKind.code, PatternKind.team, PatternKind.quote)


def _bg_art(builder: DeckBuilder, source_slide: int) -> Optional[tuple[str, float]]:
    """Art baked into the slide's background picture (the LCT city render): (side, inner edge as a share of the width)
    when one half of the picture is busy and the other calm. Measured on the picture itself — edges per column."""
    cache = builder.__dict__.setdefault("_bg_art", {})
    if source_slide in cache:
        return cache[source_slide]
    out = None
    try:
        import io

        import numpy as np
        from PIL import Image, ImageFilter

        s = builder.source_slide(source_slide)
        blip, holder = None, None
        for h in (s, s.slide_layout, s.slide_layout.slide_master):
            bg = h._element.cSld.find(q("p:bg"))
            blip = bg.find(".//" + q("a:blip")) if bg is not None else None
            if blip is not None:
                holder = h
                break
        if blip is not None:
            blob = holder.part.related_part(blip.get(q("r:embed"))).blob
            im = Image.open(io.BytesIO(blob)).convert("L").resize((320, 180))
            e = np.asarray(im.filter(ImageFilter.FIND_EDGES), dtype=float)[5:-5, 5:-5].mean(axis=0)
            bins = [float(e[j * 31 : (j + 1) * 31].mean()) for j in range(10)]
            left, right = sum(bins[:5]) / 5, sum(bins[5:]) / 5
            top = max(bins)
            if right >= 6 and right >= 4 * max(left, 0.5):
                first = next(j for j in range(10) if bins[j] >= 0.35 * top)
                out = ("right", first / 10)
            elif left >= 6 and left >= 4 * max(right, 0.5):
                last = max(j for j in range(10) if bins[j] >= 0.35 * top)
                out = ("left", (last + 1) / 10)
    except Exception:  # noqa: BLE001
        out = None
    cache[source_slide] = out
    return out


def _art_of(builder: DeckBuilder, p: Pattern, manifest: Optional[TemplateManifest] = None) -> Optional[Art]:
    """Brand art is repeated: a picture the template draws on several slides (or on a layout) is decoration; a picture
    drawn once — a screenshot in a phone, a chart snapshot — belongs to its sample's story."""
    cache = builder.__dict__.setdefault("_art_of", {})
    if (p.id, manifest is not None) not in cache:
        cache[(p.id, manifest is not None)] = _find_art(builder, p, manifest)
    return cache[(p.id, manifest is not None)]


def _find_art(builder: DeckBuilder, p: Pattern, manifest: Optional[TemplateManifest] = None) -> Optional[Art]:
    W, H = builder.slide_w, builder.slide_h
    if p.reference or p.kind in _ART_KINDS_EXCLUDED or p.quality < 0.5 or len(p.slots) > 16:
        return None
    if p.kind in (PatternKind.big_number, PatternKind.stat_row, PatternKind.chart, PatternKind.table):
        return None
    uses = {a.media_part.lstrip("/"): len(a.used_on_slides) for a in (manifest.assets if manifest else [])}
    t = _top_title(p)
    if t is None or t.bbox.y > 0.3:
        return None
    try:
        src = builder.source_slide(p.source_slide)
    except IndexError:
        return None
    if any(s.role == SlotRole.image and s.bbox.area >= 0.04 for s in p.slots):
        return None  # a picture slot is content (a screenshot to replace), not decoration
    tree = src._element.cSld.find(q("p:spTree"))
    keep: set[str] = set()
    union: Optional[Bbox] = None
    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("pic", "grpSp"):
            continue
        if tag == "grpSp" and (el.find(".//" + q("a:blip")) is None or "".join(x.text or "" for x in el.iter(q("a:t"))).strip()):
            continue
        b = element_bbox(el)
        if not b or not (0.05 * W * H <= b[2] * b[3] < 0.9 * W * H):
            continue
        if manifest is not None:
            blip = el.find(".//" + q("a:blip"))
            rid = blip.get(q("r:embed")) if blip is not None else None
            try:
                part = str(src.part.related_part(rid).partname).lstrip("/") if rid else ""
            except KeyError:
                part = ""
            if uses.get(part, 0) < 2:
                return None
        nv = el.find(".//" + q("p:cNvPr"))
        if nv is not None:
            keep.add(nv.get("id"))
        bb = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
        union = bb if union is None else union.union(bb)
    lay: list[Bbox] = []
    try:
        layout_part = str(src.slide_layout.part.partname).lstrip("/")
        usage = builder.__dict__.get("_layout_usage")
        if usage is None:
            usage = Counter(str(builder.source_slide(i).slide_layout.part.partname).lstrip("/") for i in range(1, builder.n_original + 1))
            builder.__dict__["_layout_usage"] = usage
        shared = usage.get(layout_part, 0) >= 2
        for el in src.slide_layout._element.cSld.find(q("p:spTree")):
            if el.find(".//" + q("p:ph")) is not None or el.find(".//" + q("a:blip")) is None:
                continue
            b = element_bbox(el)
            if b and 0.05 * W * H <= b[2] * b[3] < 0.9 * W * H:
                lay.append(Bbox(x=b[0], y=b[1], w=b[2], h=b[3]))
        if lay and not shared:
            # a layout of its own: only a large, broad picture reads as art (a mood collage); a narrow one is a
            # device mockup waiting for its screenshot
            u = lay[0]
            for bb in lay[1:]:
                u = u.union(bb)
            if u.area < 0.3 * W * H or any(bb.w < 0.6 * bb.h for bb in lay):
                lay = []
        for bb in lay:
            union = bb if union is None else union.union(bb)
    except Exception:  # noqa: BLE001
        pass
    if union is None:
        bga = _bg_art(builder, p.source_slide)
        if bga is not None:
            side, edge = bga
            union = Bbox(x=int(edge * W), y=0, w=W - int(edge * W), h=H) if side == "right" else Bbox(x=0, y=0, w=int(edge * W), h=H)
    if union is None or union.area < 0.15 * W * H:
        return None
    pieces = [element_bbox(el) for el in tree if (nv := el.find(".//" + q("p:cNvPr"))) is not None and nv.get("id") in keep]
    biggest = max([b[2] * b[3] for b in pieces if b] + [bb.area for bb in lay] + ([union.area] if not keep and not lay else [0]))
    if biggest < 0.15 * W * H:
        return None  # thin strips and corner patterns are chrome, not art: they cannot carry a slide
    if union.x >= 0.38 * W and union.x2 >= 0.88 * W:
        side, free = "right", union.x
    elif union.x2 <= 0.62 * W and union.x <= 0.12 * W:
        side, free = "left", W - union.x2
    else:
        return None
    if free < 0.38 * W:
        return None
    return Art(pattern=p, keep_ids=keep, box=union, side=side)


def _choose_art(builder: DeckBuilder, manifest: TemplateManifest, ds: "DeckStyle", comp: str, oslide: OutlineSlide, outline: DeckOutline) -> Optional[Art]:
    """An art canvas for a slide that carries one message (a statement, a hero figure, a few theses) — in the visual
    variant, and never two in a row: at most one slide in three stands next to the template's art."""
    strategy = outline.strategy or "structured"
    c = oslide.content
    few = len(c.bullets) <= 4 and sum(len(b) for b in c.bullets) <= 300 and not c.items and not c.table and not c.chart
    eligible = comp in ("statement", "big_number", "quote") or (comp == "bullets" and few) or (comp == "stat_row" and len(c.numbers) == 1)
    if comp == "bullets" and not c.bullets and len(c.paragraphs) == 1:
        eligible = True  # a single paragraph is set as a statement
    if not eligible or strategy == "compact":
        return None
    if strategy == "structured":
        # the structured variant keeps its grid: only its closing message (the ask, the conclusion) stands next to art
        content = [s for s in outline.slides if s.kind not in _COVER_KINDS]
        last = bool(content) and content[-1].id == oslide.id
        if not (last and comp in ("bullets", "statement") and not c.bullets and len(c.paragraphs) == 1):
            return None
    history = builder.__dict__.setdefault("_art_slides", [])
    index = len(builder.created)
    if history and index - history[-1] < 4:
        return None
    hero = comp in ("statement", "big_number", "quote") or (comp == "bullets" and not c.bullets)
    from verstka.rendering.fonts import wrap_lines
    from verstka.ru import typeset

    W = builder.slide_w
    safe = manifest.tokens.spacing.safe_area
    head = typeset(oslide.headline)
    font = manifest.tokens.typography.primary_family

    def column_fits(a: "Art") -> bool:
        """The free column beside the art holds the headline in three lines at the deck's heading size — a long
        headline squeezed into five narrow lines next to a picture reads worse than the plain grid."""
        g = int(0.04 * W)
        col = (a.box.x - g - int(safe.x * W)) if a.side == "right" else (int(safe.x2 * W) - a.box.x2 - g)
        if col < 0.3 * W:
            return False
        return len(wrap_lines(head, font, ds.head_size, ds.head_bold, col / EMU_PER_PT - 14)) <= 3

    cands = []
    for p in manifest.patterns:
        if p.family != ds.family and not hero:
            continue  # a hero slide (one statement, one figure) may stand on the other ground as an accent
        a = _art_of(builder, p, manifest)
        if a is None or (ds.pill and not _has_pill(builder, p)) or p.id in builder.__dict__.get("_art_used", []):
            continue  # one appearance per deck: a repeated picture reads as a placeholder
        if not column_fits(a):
            continue
        clutter = len(p.slots) + sum(len(g.member_shape_ids) for g in p.repeat_groups)
        cands.append((int(p.family != ds.family), -min(a.box.area / (builder.slide_w * builder.slide_h), 0.5), clutter, p.source_slide, a))
    if not cands:
        return None
    cands.sort(key=lambda t: t[:4])
    used = builder.__dict__.setdefault("_art_used", [])
    # the least used of the best art canvases: two statements do not repeat the same picture when another exists
    best = min(cands[:3], key=lambda t: used.count(t[4].pattern.id))[4]
    used.append(best.pattern.id)
    history.append(index)
    return best


def _render_content(builder: DeckBuilder, comp: str, oslide: OutlineSlide, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline) -> tuple[Slide, list[str]]:
    from verstka.rendering.compose import Composer, Kit

    warnings: list[str] = []
    ds = deck_style(builder, manifest, outline)
    family = ds.family
    if comp == "image_text" and not (oslide.content.image_hint and pick_asset(manifest, ws, oslide.content.image_hint, require_match=True)):
        comp = "bullets"  # no picture of the template says what the slide says: the text alone (an art canvas may frame it)
    wide = _needs_width(oslide, comp)
    art = _choose_art(builder, manifest, ds, comp, oslide, outline) if not wide else None
    canvas = art.pattern if art is not None else _pick_canvas(builder, manifest, family, comp, wide, need_pill=ds.pill)
    ground = None
    if canvas is not None:
        slide, title_ph, ground = _slide_on_canvas(builder, canvas, builder.slide_w, builder.slide_h, keep_extra=art.keep_ids if art else None)
        family = canvas.family
    else:
        layout, family = _layout_for(builder, manifest, family, oslide.kind)
        slide = builder.prs.slides.add_slide(layout)
        builder.created.append(slide)
        title_ph = None
        for shp in list(slide.shapes):
            if shp.is_placeholder and shp.placeholder_format.type is not None and str(shp.placeholder_format.type).split(".")[-1].split(" ")[0] in ("TITLE", "CENTER_TITLE"):
                title_ph = shp
            else:
                shp._element.getparent().remove(shp._element)
    if art is not None and title_ph is not None:
        _snap_header(builder, manifest, ds, slide, title_ph, art)
    pal = _Palette(manifest, family)
    if canvas is not None:
        _adopt_canvas_colors(pal, canvas, manifest)
    t = manifest.tokens
    typo = t.typography
    W, H = builder.slide_w, builder.slide_h
    safe = t.spacing.safe_area
    sx, sy, sw, sh = int(safe.x * W), int(safe.y * H), int(safe.w * W), int(safe.h * H)
    if ground is not None:
        gb, ghex = ground
        pad = int(0.03 * W)
        x1, x2 = max(sx, gb.x + pad), min(sx + sw, gb.x2 - pad)
        y2 = min(sy + sh, gb.y2 - pad)
        if x2 - x1 > 0.25 * W:
            sx, sw, sh = x1, x2 - x1, y2 - sy
        if ghex:
            pal.bg = ghex
            pal.text = pal.text2 = _readable(ghex, [pal.text, t.color_for("text.primary")])
    scale = sorted({s.size_pt for s in typo.scale} | {float(x) for x in (typo.sizes_used or []) if x >= 8})
    h1, title_color, title_bold, title_font = _title_style(manifest, family, pal)
    if contrast_ratio(title_color, pal.bg) < 3.0:
        title_color = pal.text
    if contrast_ratio(title_color, pal.bg) < 4.5:
        title_color = _heading_on(pal.bg, manifest, pal)
    heading_bottom, content_left, lede_used = _place_heading(builder, slide, title_ph, canvas, oslide, manifest, ws, outline, pal, (sx, sy, sw, sh), h1, title_color, title_bold, title_font, scale, warnings, ds)
    if lede_used:
        oslide = _without_lede(oslide)
    page_left = sx
    if content_left is not None and sx <= content_left < sx + sw // 2:
        sw = sx + sw - content_left
        sx = content_left
    # the right margin mirrors the left one — the page's, where the column starts past the art
    mirror = page_left if art is not None and art.side == "left" else sx
    if ground is None and sx + sw > W - mirror:
        sw = W - mirror - sx
    if art is not None:
        # the content keeps to the free side of the art, a gutter away from it
        g = int(0.04 * W)
        if art.side == "right":
            sw = max(min(sw, art.box.x - g - sx), int(0.3 * W))
        else:
            x1 = max(sx, art.box.x2 + g)
            sw, sx = max(sx + sw - x1, int(0.3 * W)), x1
    gap = max(int(0.05 * H), int(h1 * 0.8 * EMU_PER_PT))
    top = _below_rules(slide, heading_bottom, heading_bottom + gap, W, H, gap)
    bottom = sy + sh
    foot = _foot_top(slide, W, H)
    if foot is not None:
        bottom = min(bottom, foot - int(0.035 * H))  # the content keeps clear of the logos and the footer line
    area = Bbox(x=sx, y=top, w=sw, h=max(bottom - top, int(0.25 * H)))
    proto = _card_proto(builder, manifest, family, pal.bg)
    kit = Kit(manifest, W, H, pal.bg, card_proto=proto[0] if proto else None, heading_color=title_color)
    kit.head_size = ds.head_size
    if proto:
        # colours of the copied card as the analysis sees them (scheme colours resolved)
        kit.card.fill, kit.card.line = proto[1], proto[2]
        kit.card.colors = kit.colors_on(proto[1] or pal.bg, prefer=None if proto[1] else title_color, inside_card=bool(proto[1]))
    composer = Composer(slide, kit, oslide, outline, outline.strategy or "structured", manifest)
    if comp == "image_text" and oslide.content.image_hint:
        comp = _image_text(builder, slide, oslide, manifest, ws, kit, composer, area)
    if comp:
        composer.compose(comp, area)
    warnings.extend(composer.warnings)
    return slide, warnings


def _snap_header(builder: DeckBuilder, manifest: TemplateManifest, ds: "DeckStyle", slide: Slide, title_ph, art: "Art") -> None:
    """An art canvas keeps the deck's header grid: its heading (and the label under it) moves to where the heading
    of every other content slide stands — or into the free column when that spot is taken by the art."""
    W, H = builder.slide_w, builder.slide_h
    std = _pick_canvas(builder, manifest, ds.family, "bullets", False, need_pill=ds.pill)
    t = _top_title(std) if std is not None else None
    if t is None:
        return
    try:
        el_std = slide_shape_elements(builder.source_slide(std.source_slide)).get(t.shape_id)
    except IndexError:
        el_std = None
    sb = element_bbox(el_std) if el_std is not None else None
    cur = element_bbox(title_ph._element)
    if not sb or not cur:
        return
    backing = _backing_of(slide, title_ph._element, W, H)
    target_x, target_y = sb[0], sb[1]
    g = int(0.04 * W)
    if art.side == "left" and target_x < art.box.x2:
        target_x = art.box.x2 + g  # the heading moves off the art into the free column
    dx, dy = target_x - cur[0], target_y - cur[1]
    if abs(dx) < int(0.004 * W) and abs(dy) < int(0.004 * H):
        return
    from verstka.rendering.deck import shift_element

    from verstka.rendering.deck import set_element_pos

    shift_element(title_ph._element, dx, dy)
    if backing is not None:
        shift_element(backing[0], dx, dy)
    nb = element_bbox(title_ph._element)
    if nb:
        # the heading keeps inside its column: up to the art on the right, up to the right margin otherwise
        right = art.box.x - g if art.side == "right" else int(manifest.tokens.spacing.safe_area.x2 * W)
        if nb[0] + nb[2] > right:
            set_element_pos(title_ph._element, w=max(right - nb[0], int(0.25 * W)))


def _image_text(builder, slide, oslide, manifest, ws, kit, composer, area: Bbox) -> Optional[str]:
    """A picture of the template next to the text: the picture takes 42% of the width, the text the rest."""
    path = pick_asset(manifest, ws, oslide.content.image_hint, require_match=True)
    if not path:
        return "bullets"
    img_w = int(area.w * 0.42)
    insert_picture(slide, Bbox(x=area.x + area.w - img_w, y=area.y, w=img_w, h=area.h), path)
    text_area = Bbox(x=area.x, y=area.y, w=area.w - img_w - kit.gap * 2, h=area.h)
    c = oslide.content
    if c.bullets:
        composer.bullets(text_area, list(c.bullets))
    elif c.paragraphs:
        composer.paragraphs(text_area, list(c.paragraphs))
    return None


_KIND_LABEL = {
    PatternKind.stat_row: "Ключевые цифры", PatternKind.big_number: "Главная цифра", PatternKind.chart: "Динамика",
    PatternKind.table: "Сравнение", PatternKind.comparison: "Сравнение", PatternKind.two_column: "Сравнение",
    PatternKind.process: "План", PatternKind.timeline: "Этапы", PatternKind.cards: "Главное", PatternKind.bullets: "Тезисы",
    PatternKind.agenda: "Содержание", PatternKind.quote: "Цитата", PatternKind.image_text: "Пример", PatternKind.team: "Команда",
}
_COVER_KINDS = (PatternKind.title, PatternKind.section, PatternKind.thanks)


@dataclass
class DeckStyle:
    """Decisions taken once per deck, so every composed slide wears the same heading and ground."""

    family: Family
    pill: bool  # headings of the template sit on a label (a pill)
    kicker: bool  # the label carries a short kicker, the headline is set below it
    head_size: float  # size of plain headings (the whole deck)
    upper: bool  # labels in capitals, as in the samples
    head_bold: bool = False  # headlines set under a label are bold when the template's labels are




def _content_patterns(manifest: TemplateManifest) -> list[Pattern]:
    return [p for p in manifest.patterns if not p.reference and p.quality >= 0.5 and p.kind not in _NOT_CONTENT_CANVAS and (t := _top_title(p)) is not None and t.bbox.y <= 0.3]


def deck_style(builder: DeckBuilder, manifest: TemplateManifest, outline: DeckOutline) -> DeckStyle:
    cache = builder.__dict__.setdefault("_deck_styles", {})  # one deck per builder: the style lives with it
    if id(outline) in cache:
        return cache[id(outline)]
    W, H = builder.slide_w, builder.slide_h
    pats = _content_patterns(manifest)
    fams = Counter(p.family for p in pats) or Counter(p.family for p in manifest.patterns)
    family = fams.most_common(1)[0][0] if fams else Family.light
    same = [p for p in pats if p.family == family]
    pilled, sizes, uppers, texted, bolds = 0, Counter(), 0, 0, 0
    title_box: Optional[Bbox] = None
    for p in same:
        try:
            src = builder.source_slide(p.source_slide)
        except IndexError:
            continue
        els = slide_shape_elements(src)
        t = _top_title(p)
        el = els.get(t.shape_id) if t else None
        if el is None:
            continue
        if _backing_of(src, el, W, H) is not None:
            pilled += 1
            if t.style.size_pt:
                sizes[round(t.style.size_pt)] += 1
            if t.sample_text and t.sample_text.strip():
                texted += 1
                uppers += int(t.sample_text.strip().isupper())
            bolds += int(bool(t.style.bold))
            b = element_bbox(el)
            if b and title_box is None:
                title_box = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
    pill = bool(same) and pilled >= 0.5 * len(same)
    typo = manifest.tokens.typography
    scale = sorted({s.size_pt for s in typo.scale} | {float(x) for x in (typo.sizes_used or []) if x >= 8})
    pal = _Palette(manifest, family)
    h1, _, bold, font = _title_style(manifest, family, pal)
    heads = [s.headline for s in outline.slides if s.kind not in _COVER_KINDS and s.headline]
    kicker = False
    if pill and heads:
        size = float(sizes.most_common(1)[0][0]) if sizes else h1
        room = clear_width(manifest, W, H, title_box) if title_box else int(0.5 * W)
        fails = sum(1 for h in heads if len(h.split()) > 4 or text_width_pt(h, font, size, bold) * EMU_PER_PT + int(0.06 * W) > room)
        kicker = fails > len(heads) / 3
    # one heading size for every content slide of every deck: the template's own (a long headline takes a third
    # line rather than a smaller size)
    head = max(h1, _snap_heading(0.046 * H / EMU_PER_PT, scale))
    ds = DeckStyle(family=family, pill=pill, kicker=kicker, head_size=head, upper=pill and texted > 0 and uppers >= 0.6 * texted, head_bold=pill and bolds > 0)
    cache[id(outline)] = ds
    return ds


def _place_heading(builder, slide, title_ph, canvas, oslide, manifest, ws, outline, pal, safe_box, h1, title_color, title_bold, title_font, scale, warnings, ds: Optional[DeckStyle] = None) -> tuple[int, Optional[int], bool]:
    """Write the headline; returns (bottom of the heading, left edge the content aligns to, whether the slide's
    lede was set as the headline)."""
    from verstka.rendering.compose import Canvas, Para, Run, block_height_pt

    typo = manifest.tokens.typography
    W, H = builder.slide_w, builder.slide_h
    sx, sy, sw, sh = safe_box
    insets = (91440, 45720, 91440, 45720)
    if title_ph is None:
        box = Bbox(x=sx, y=sy, w=sw, h=int(H * 0.16))
        tb = _textbox(slide, box, [ParagraphSpec(oslide.headline)], size=h1, color=title_color, font=title_font, bold=title_bold, scale=scale, anchor="t")
        res = fit_size([oslide.headline], box, title_font, h1, title_bold, scale, insets_emu=(45720, 22860, 45720, 22860), line_spacing=typo.line_height)
        th = int(res.height_pt * EMU_PER_PT) + 45720
        tb.height = Emu(th)
        return box.y + th, sx + 45720, False
    if title_ph.top is not None:
        box = Bbox(x=int(title_ph.left), y=int(title_ph.top), w=int(title_ph.width), h=int(title_ph.height))
    else:
        box = Bbox(x=sx, y=sy, w=sw, h=int(H * 0.16))
    backing = _backing_of(slide, title_ph._element, W, H) if canvas is not None else None
    if backing is not None:
        back_el, bb = backing
        kicker_mode = ds.kicker if ds is not None else (len(oslide.headline) > 34)
        if kicker_mode:
            # a pill is a label: it carries the section (a kicker), the assertion is set as a heading below it
            upper = ds.upper if ds is not None else False
            head_size = ds.head_size if ds is not None else _snap_heading(max(h1 * 1.25, 0.046 * H / EMU_PER_PT), scale)
            head_bold = ds.head_bold if ds is not None else title_bold
            headline = oslide.headline.strip()
            short = len(headline.split()) <= 5
            from verstka.ru import typeset

            display = typeset(headline)
            tag = (oslide.section or "").strip() if short else _section_of(oslide, outline)
            only_label = False
            if not tag or _same_words(tag, headline):
                if len(headline.split()) <= 5:
                    tag, only_label = headline, True  # the headline is itself a section name: it goes on the label
                else:
                    tag = _KIND_LABEL.get(oslide.kind, "")
            short_tag = _short_kicker(tag)
            if only_label and short_tag.lower().strip(" .:") != headline.lower().strip(" .:"):
                # a label would cut the headline («Результаты пилота: до и после» → «Результаты пилота»): the whole
                # headline is set under a label that names the kind of slide
                only_label = False
                short_tag = _short_kicker(_KIND_LABEL.get(oslide.kind, "") or short_tag)
            tag = short_tag
            label = tag.upper() if upper else tag
            hctx = _SlideCtx(builder, slide, canvas, manifest, ws, outline)
            nb = hctx._widen_on_backing(title_ph._element, (box.x, box.y, box.w, box.h), [label], title_font, h1, title_bold, insets)
            # the label keeps the template's own size on every slide; a long kicker was shortened, never shrunk
            fill_text(title_ph._element, [ParagraphSpec(label)], size_pt=h1)
            _hug_label(back_el, title_ph._element, label, title_font, h1, title_bold, insets, W)
            b2 = element_bbox(back_el)
            below = max(bb.y2, (b2[1] + b2[3]) if b2 else bb.y2)
            y = below + int(0.022 * H)
            one_line = int(head_size * typo.line_height * EMU_PER_PT)
            if only_label:
                lede = _lede_of(oslide)
                if not lede:
                    # the content starts where it starts under a one-line headline: one rhythm for the whole deck
                    return y + one_line, bb.x, False
                display, lede_used = typeset(lede), True  # the slide's lede is its message: it takes the heading's place
            else:
                lede_used = False
            ground = pal.bg
            color = _heading_on(ground, manifest, pal)
            right = min(int(manifest.tokens.spacing.safe_area.x2 * W), W - bb.x)
            width = min(_free_width(slide, Bbox(x=bb.x, y=y, w=right - bb.x, h=int(0.1 * H)), W, H, right, skip=(title_ph._element, back_el)), int(0.86 * W))
            size = head_size
            from verstka.rendering.fonts import wrap_lines

            n = len(wrap_lines(display, title_font, size, head_bold, width / EMU_PER_PT))
            if n > 3:
                for s_ in [x for x in reversed(scale) if 0.8 * head_size <= x < head_size]:
                    size = s_
                    n = len(wrap_lines(display, title_font, size, head_bold, width / EMU_PER_PT))
                    if n <= 3:
                        break
            if 2 <= n <= 3:
                # balanced lines: the narrowest width that keeps the same number of lines
                lo, hi = int(width * 0.55), width
                for _ in range(12):
                    mid = (lo + hi) // 2
                    if len(wrap_lines(display, title_font, size, head_bold, mid / EMU_PER_PT)) <= n:
                        hi = mid
                    else:
                        lo = mid
                width = min(width, int(hi * 1.03))
            hpt = block_height_pt([Para([Run(display, size, color, head_bold, title_font)])], width / EMU_PER_PT, typo.line_height)
            hh = int(hpt * EMU_PER_PT) + int(2 * EMU_PER_PT)
            cv = Canvas(slide, font=title_font, spacing_pct=typo.line_spacing if abs(typo.line_spacing - 1.2) > 1e-6 else 1.0)
            cv.text(Bbox(x=bb.x, y=y, w=width, h=hh), [Para([Run(display, size, color, head_bold, title_font)])], name="Title")
            warnings.append("heading set under its label")
            return y + max(hh, one_line), bb.x, lede_used
        hctx = _SlideCtx(builder, slide, canvas, manifest, ws, outline)
        nb = hctx._widen_on_backing(title_ph._element, (box.x, box.y, box.w, box.h), [oslide.headline], title_font, h1, title_bold, insets)
        box = Bbox(x=nb[0], y=nb[1], w=nb[2], h=nb[3])
        warnings.extend(hctx.warnings)
        res = fit_size([oslide.headline], box, title_font, h1, title_bold, scale, insets_emu=insets, line_spacing=typo.line_height)
        fill_text(title_ph._element, [ParagraphSpec(oslide.headline)], size_pt=res.size_pt)
        b2 = element_bbox(back_el)
        return max(box.y2, (b2[1] + b2[3]) if b2 else box.y2), bb.x, False
    # the heading takes the free width of its band (up to the logos and the right margin), not the sample's box
    # (the right margin mirrors the heading's left edge — the page margin's when the heading stands in a column past art)
    safe_x = int(manifest.tokens.spacing.safe_area.x * W)
    right = min(int(manifest.tokens.spacing.safe_area.x2 * W), W - (box.x if box.x < 0.25 * W else safe_x))
    w_clear = min(_free_width(slide, box, W, H, right, skip=(title_ph._element,)), int(0.86 * W))
    if w_clear != box.w and w_clear > 0.3 * W:
        box = Bbox(x=box.x, y=box.y, w=w_clear, h=box.h)
        title_ph.width = Emu(w_clear)
    # one heading size for the whole deck (never autofitted per slide unless the headline cannot fit at all)
    h1 = ds.head_size if ds is not None else max(h1, _snap_heading(0.046 * H / EMU_PER_PT, scale))
    from verstka.rendering.fonts import wrap_lines
    from verstka.ru import typeset

    head_text = typeset(oslide.headline)
    inner = lambda w: max((w - insets[0] - insets[2]) / EMU_PER_PT, 1.0)  # noqa: E731
    n = len(wrap_lines(head_text, title_font, h1, title_bold, inner(box.w)))
    # the deck's heading size holds: a long headline takes up to three lines (the box grows downwards and the
    # content moves with it); only past three lines does the size give way
    rows = min(max(n, 2), 3)
    need = int((rows + 0.1) * h1 * typo.line_height * EMU_PER_PT) + insets[1] + insets[3]
    rule = _rule_under(slide, box, W, H)
    if rule is not None:
        need = min(need, max(rule - box.y - int(0.01 * H), box.h))  # the heading keeps above the layout's rule
    if box.h < need:
        box = Bbox(x=box.x, y=box.y, w=box.w, h=need)
    if 2 <= n <= 3:
        # balanced lines: the narrowest box that keeps the same number of lines (no one-word last line)
        lo, hi = int(box.w * 0.55), box.w
        for _ in range(12):
            mid = (lo + hi) // 2
            if len(wrap_lines(head_text, title_font, h1, title_bold, inner(mid))) <= n:
                hi = mid
            else:
                lo = mid
        balanced = min(box.w, int(hi * 1.03))
        if balanced < box.w:
            box = Bbox(x=box.x, y=box.y, w=balanced, h=box.h)
            title_ph.width = Emu(balanced)
    res = fit_size([head_text], box, title_font, h1, title_bold, scale, insets_emu=insets, line_spacing=typo.line_height, min_ratio=0.6 if rule is not None else 0.8)
    fill_text(title_ph._element, [ParagraphSpec(head_text)], size_pt=res.size_pt)
    text_h = int(res.height_pt * EMU_PER_PT) + insets[1] + insets[3]
    if text_h > box.h or title_ph.top is None:
        title_ph.left, title_ph.top, title_ph.width, title_ph.height = Emu(box.x), Emu(box.y), Emu(box.w), Emu(max(box.h, text_h))
        bottom = box.y + max(box.h, text_h)
    else:
        # the box shrinks to its text where the text is drawn (top / middle / bottom of the sample's box)
        anchor = _title_anchor(title_ph)
        y = box.y if anchor == "t" else (box.y2 - text_h if anchor == "b" else box.y + (box.h - text_h) // 2)
        title_ph.top, title_ph.height = Emu(y), Emu(text_h)
        bp = title_ph._element.find(".//" + q("a:bodyPr"))
        bottom = y + text_h
    left = box.x + insets[0]
    lins = title_ph._element.find(".//" + q("a:bodyPr"))
    if lins is not None and lins.get("lIns") is not None:
        try:
            left = box.x + int(lins.get("lIns"))
        except ValueError:
            pass
    return bottom, left, False




def _free_width(slide: Slide, box: Bbox, W: int, H: int, right: int, skip: tuple = ()) -> int:
    """Width a heading may take from box.x: up to `right`, cut before whatever really stands in its band on this
    slide — shapes of the cleaned canvas and of its layout (logos, patterns, panels), not the chrome of other layouts."""
    limit = right
    items = _drawn(slide)
    for el in items:
        if el in skip or etree.QName(el).localname not in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp"):
            continue
        b = element_bbox(el)
        if not b or b[2] * b[3] >= 0.6 * W * H:
            continue
        if b[1] < box.y2 and b[1] + b[3] > box.y and b[0] >= box.x + int(0.1 * W):
            limit = min(limit, b[0] - int(0.015 * W))
    return max(limit - box.x, int(0.25 * W))


def _foot_top(slide: Slide, W: int, H: int) -> Optional[int]:
    """The top of the brand marks drawn at the foot of this slide (logos, a footer line, a page number): small
    things in the bottom fifth, as the slide, its layout and its master draw them."""
    tops = []
    for el in _drawn(slide):
        if etree.QName(el).localname not in ("sp", "pic", "grpSp", "cxnSp"):
            continue
        b = element_bbox(el)
        if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.2 * W * H or b[3] > 0.15 * H:
            continue
        if b[1] >= 0.8 * H and b[1] + b[3] <= H * 1.01:
            tops.append(b[1])
    return min(tops) if tops else None


def _drawn(slide: Slide) -> list:
    """What is drawn on a slide besides its own shapes: the decoration of its layout and master (placeholders of
    the layout and master are not drawn on a slide that does not use them)."""
    items = list(slide._element.cSld.find(q("p:spTree")))
    try:
        for holder in (slide.slide_layout, slide.slide_layout.slide_master):
            items += [el for el in holder._element.cSld.find(q("p:spTree")) if el.find(".//" + q("p:ph")) is None]
    except Exception:  # noqa: BLE001
        pass
    return items


def _rule_under(slide: Slide, box: Bbox, W: int, H: int) -> Optional[int]:
    """The top of a rule drawn across the slide just under a heading box (the classic «title + line» layout)."""
    best = None
    for el in _drawn(slide):
        if etree.QName(el).localname not in ("sp", "cxnSp"):
            continue
        b = element_bbox(el)
        if not b or b[3] > 0.02 * H or b[2] < 0.3 * W:
            continue
        if box.y + int(0.03 * H) <= b[1] <= box.y2 + int(0.12 * H) and (best is None or b[1] < best):
            best = b[1]
    return best


def _below_rules(slide: Slide, heading_bottom: int, top: int, W: int, H: int, gap: int) -> int:
    """The content starts below a rule the layout draws under the heading (a line across the slide), never on it."""
    items = _drawn(slide)
    out = top
    for el in items:
        if etree.QName(el).localname not in ("sp", "cxnSp", "pic"):
            continue
        b = element_bbox(el)
        if not b or b[3] > 0.02 * H or b[2] < 0.3 * W:
            continue
        if heading_bottom - int(0.03 * H) <= b[1] <= top + int(0.1 * H):
            out = max(out, b[1] + b[3] + int(gap * 0.7))
    return out


def _short_kicker(tag: str, limit: int = 26) -> str:
    """A label is a few words: cut at the first colon or comma, then at a word boundary."""
    t = tag.strip()
    if len(t) <= limit:
        return t
    for sep in (":", ",", " —", " –", "("):
        if sep in t and 3 <= len(t.split(sep)[0].strip()) <= limit:
            return t.split(sep)[0].strip()
    out = ""
    for w in t.split():
        if len((out + " " + w).strip()) > limit:
            break
        out = (out + " " + w).strip()
    return out or t[:limit]


def _lede_of(oslide: OutlineSlide) -> Optional[str]:
    """The one sentence that introduces structured content (the composer's intro line)."""
    c = oslide.content
    if oslide.subtitle:
        return oslide.subtitle
    structured = c.items or c.columns or c.table is not None or c.chart is not None or c.numbers
    if structured and len(c.paragraphs) == 1 and len(c.paragraphs[0]) <= 200 and not c.bullets:
        return c.paragraphs[0]
    return None


def _without_lede(oslide: OutlineSlide) -> OutlineSlide:
    o = oslide.model_copy(deep=True)
    if o.subtitle:
        o.subtitle = None
    elif len(o.content.paragraphs) == 1:
        o.content.paragraphs = []
    return o


def _section_of(oslide: OutlineSlide, outline: DeckOutline) -> str:
    """The slide's section, else the section of its neighbours (the first slide of a section often carries none)."""
    own = (oslide.section or "").strip()
    if own:
        return own
    ids = [s.id for s in outline.slides]
    if oslide.id not in ids:
        return ""
    i = ids.index(oslide.id)
    for j in (i - 1, i + 1):
        if 0 <= j < len(outline.slides) and outline.slides[j].kind not in _COVER_KINDS and (outline.slides[j].section or "").strip():
            return outline.slides[j].section.strip()
    return ""


def _same_words(tag: str, headline: str) -> bool:
    a, b = tag.lower().strip(" .:"), headline.lower().strip(" .:")
    return a == b or b.startswith(a) or a.startswith(b)


def _hug_label(back_el, title_el, label: str, font: Optional[str], size: float, bold: bool, insets: tuple[int, int, int, int], W: int) -> None:
    """The label hugs its text: its width is the text plus the sample's side padding, never wider than it was."""
    b = element_bbox(back_el)
    tb = element_bbox(title_el)
    if not b or not tb:
        return
    pad = max(tb[0] - b[0], 0) + insets[0]
    need = int(text_width_pt(label, font, size, bold) * EMU_PER_PT * 1.06) + pad * 2
    need = max(need, int(0.1 * W))
    if need < b[2]:
        from verstka.rendering.deck import set_element_pos

        set_element_pos(back_el, w=need)
        set_element_pos(title_el, w=max(need - (tb[0] - b[0]), int(0.05 * W)))


def _heading_on(ground: str, manifest: TemplateManifest, pal: "_Palette") -> str:
    """A heading colour that reads on the ground: the brand's dark or light colour before plain black/white."""
    t = manifest.tokens
    cands = [t.color_for("background.dark"), t.color_for("text.primary"), pal.text, t.color_for("background.light"), "000000", "FFFFFF"]
    return next((c for c in cands if c and contrast_ratio(c, ground) >= 4.5), pal.text)


def _snap_heading(target: float, scale: list[float]) -> float:
    near = [s for s in scale if abs(s - target) <= 0.22 * target]
    return min(near, key=lambda s: abs(s - target)) if near else round(target)


def _render_cover(builder: DeckBuilder, plan_slide: LayoutSlide, oslide: OutlineSlide, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline) -> tuple[Slide, list[str]]:
    warnings: list[str] = []
    comp = plan_slide.composition or "bullets"
    family = _family_for(oslide, manifest)
    canvas = _canvas_for(manifest, family, comp)
    ground = None
    if canvas is not None:
        slide, title_ph, ground = _slide_on_canvas(builder, canvas, builder.slide_w, builder.slide_h)
    else:
        layout, family = _layout_for(builder, manifest, family, oslide.kind)
        slide = builder.prs.slides.add_slide(layout)
        builder.created.append(slide)
        title_ph = None
    pal = _Palette(manifest, family)  # palette of the real family: text must contrast with its background
    if canvas is not None:
        _adopt_canvas_colors(pal, canvas, manifest)
    t = manifest.tokens
    typo = t.typography
    W, H = builder.slide_w, builder.slide_h
    safe = t.spacing.safe_area
    sx, sy, sw, sh = int(safe.x * W), int(safe.y * H), int(safe.w * W), int(safe.h * H)
    if ground is not None:
        # the heading stands on a panel (LCT: white half, photo half): the composition lives inside the panel
        gb, ghex = ground
        pad = int(0.03 * W)
        x1, x2 = max(sx, gb.x + pad), min(sx + sw, gb.x2 - pad)
        y2 = min(sy + sh, gb.y2 - pad)
        if x2 - x1 > 0.25 * W:
            sx, sw, sh = x1, x2 - x1, y2 - sy
        if ghex:
            pal.bg = ghex
            pal.text = pal.text2 = _readable(ghex, [pal.text, t.color_for("text.primary")])
    # every size the template uses (not only the role scale): text fits and grows along the template's own steps
    scale = sorted({s.size_pt for s in typo.scale} | {float(x) for x in (typo.sizes_used or []) if x >= 8})
    font = typo.primary_family
    h1, title_color, title_bold, title_font = _title_style(manifest, family, pal)
    body = typo.size_for("body", 14.0)
    h2 = typo.size_for("h2", body * 1.25)
    small = typo.size_for("small", body * 0.85)
    display = typo.size_for("display", h1 * 1.8)

    # keep only the title (fill it) — everything else is drawn from tokens
    if canvas is None:
        for shp in list(slide.shapes):
            if shp.is_placeholder and shp.placeholder_format.type is not None and str(shp.placeholder_format.type).split(".")[-1].split(" ")[0] in ("TITLE", "CENTER_TITLE"):
                title_ph = shp
            else:
                shp._element.getparent().remove(shp._element)
    c = oslide.content
    title_h = int(H * (0.16 if comp not in ("title", "section", "thanks") else 0.3))
    if title_ph is not None and comp not in ("title", "section", "thanks"):
        # measure the headline against the placeholder box: the content starts below the fitted text, not below
        # the placeholder's nominal height (which is one line tall on most layouts)
        if title_ph.top is not None:
            box = Bbox(x=int(title_ph.left), y=int(title_ph.top), w=int(title_ph.width), h=int(title_ph.height))
        else:
            box = Bbox(x=sx, y=sy, w=sw, h=title_h)
        insets = (91440, 45720, 91440, 45720)
        if canvas is not None:
            # the canvas keeps the template's heading label (a pill): the same rules as on a cloned slide
            hctx = _SlideCtx(builder, slide, canvas, manifest, ws, outline)
            nb = hctx._widen_on_backing(title_ph._element, (box.x, box.y, box.w, box.h), [oslide.headline], title_font, h1, title_bold, insets)
            box = Bbox(x=nb[0], y=nb[1], w=nb[2], h=nb[3])
            warnings.extend(hctx.warnings)
        else:
            w_clear = clear_width(manifest, W, H, box)
            if w_clear < box.w:  # never under the logos: the heading wraps instead
                box = Bbox(x=box.x, y=box.y, w=w_clear, h=box.h)
                title_ph.width = Emu(w_clear)
        res = fit_size([oslide.headline], box, title_font, h1, title_bold, scale, insets_emu=insets, line_spacing=typo.line_height)
        fill_text(title_ph._element, [ParagraphSpec(oslide.headline)], size_pt=res.size_pt)
        text_h = int(res.height_pt * EMU_PER_PT) + insets[1] + insets[3]
        if text_h > box.h or title_ph.top is None:
            # keep the headline inside its own box
            title_ph.left, title_ph.top, title_ph.width, title_ph.height = Emu(box.x), Emu(box.y), Emu(box.w), Emu(max(box.h, text_h))
        y_after = box.y + max(box.h, text_h)
    elif comp not in ("title", "section", "thanks"):
        if title_ph is not None:
            title_ph._element.getparent().remove(title_ph._element)
        _textbox(slide, Bbox(x=sx, y=sy, w=sw, h=title_h), [ParagraphSpec(oslide.headline)], size=h1, color=title_color, font=title_font, bold=title_bold, scale=scale, anchor="t")
        y_after = sy + title_h
    elif canvas is not None and title_ph is not None:
        # title / section / thanks on a sample of that kind: its own title box, the subtitle right under it
        box = Bbox(x=int(title_ph.left), y=int(title_ph.top), w=int(title_ph.width), h=int(title_ph.height))
        insets = (91440, 45720, 91440, 45720)
        res = fit_size([oslide.headline], box, title_font, h1, title_bold, scale, insets_emu=insets, line_spacing=typo.line_height, min_ratio=0.6)
        fill_text(title_ph._element, [ParagraphSpec(oslide.headline)], size_pt=res.size_pt)
        text_h = int(res.height_pt * EMU_PER_PT) + insets[1] + insets[3]
        if text_h > box.h:
            title_ph.height = Emu(min(text_h, int(H * 0.95) - box.y))
        sub = oslide.subtitle or (oslide.section if comp == "section" else None)
        if sub:
            y_sub = box.y + max(box.h, text_h) + int(H * 0.02)
            _textbox(slide, Bbox(x=box.x, y=y_sub, w=box.w, h=min(int(H * 0.16), int(H * 0.92) - y_sub)), [ParagraphSpec(sub)], size=h2, color=pal.text2, font=font, scale=scale)
        return slide, warnings
    else:
        if title_ph is not None:
            title_ph._element.getparent().remove(title_ph._element)
        y_after = sy
    if title_ph is not None and title_ph.left is not None and comp not in ("title", "section", "thanks") and 0 < int(title_ph.left) < sx + sw // 2:
        # content is aligned to the heading's left edge, as the template's own slides are
        sw = sx + sw - int(title_ph.left)
        sx = int(title_ph.left)
    top = y_after + int(H * 0.02)
    avail_h = sy + sh - top
    gap = int((t.spacing.gutter or 0.03) * W)
    card_gap = min(gap, int(0.03 * W))  # the template gutter is a column gutter; card grids need a narrower one

    if comp in ("title", "section", "thanks"):
        box = Bbox(x=sx, y=int(H * 0.30), w=int(sw * 0.8), h=int(H * 0.3))
        _textbox(slide, box, [ParagraphSpec(oslide.headline)], size=max(h1, display * 0.8) if comp == "title" else h1, color=title_color, font=title_font, bold=title_bold, scale=scale, anchor="b")
        sub = oslide.subtitle or (oslide.section if comp == "section" else None)
        if sub:
            _textbox(slide, Bbox(x=sx, y=int(H * 0.62), w=int(sw * 0.8), h=int(H * 0.16)), [ParagraphSpec(sub)], size=h2, color=pal.text2, font=font, scale=scale)
        return slide, warnings

    if comp == "bullets" or (comp in ("image_text",) and not c.image_hint):
        paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p, bullet=False) for p in c.paragraphs] or [ParagraphSpec(i.title, bullet=True) for i in _items(oslide)]
        if oslide.subtitle:
            paras = [ParagraphSpec(oslide.subtitle, bullet=False, bold=True)] + paras
        _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.9), h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale, line_spacing=typo.line_height)
        return slide, warnings

    if comp == "image_text":
        path = pick_asset(manifest, ws, c.image_hint)
        img_w = int(sw * 0.42)
        if path:
            insert_picture(slide, Bbox(x=sx, y=top, w=img_w, h=avail_h), path)
            x_text = sx + img_w + gap
        else:
            x_text = sx
        paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs]
        _textbox(slide, Bbox(x=x_text, y=top, w=sx + sw - x_text, h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
        return slide, warnings

    if comp in ("cards", "process", "agenda", "comparison", "two_column"):
        items = _items(oslide)
        n = max(len(items), 1)
        cols = n if n <= 4 else math.ceil(n / 2)
        rows = math.ceil(n / cols)
        if comp in ("two_column", "comparison"):
            cols, rows = min(n, 3), 1
        cw = int((sw - card_gap * (cols - 1)) / cols)
        ch = int((avail_h - card_gap * (rows - 1)) / rows)
        for i, item in enumerate(items):
            r_, c_ = divmod(i, cols)
            box = Bbox(x=sx + c_ * (cw + card_gap), y=top + r_ * (ch + card_gap), w=cw, h=ch)
            if comp in ("cards", "comparison") and (pal.card_fill or pal.card_line):
                _rect(slide, box, pal.card_fill, pal.card_line if not pal.card_fill else None, pal.radius_emu)
            inset = int(cw * 0.07)
            head_h = int(ch * 0.3)
            y_head = box.y + inset
            if comp in ("process", "agenda"):
                d = int(min(cw, ch) * 0.28)
                _circle(slide, Bbox(x=box.x, y=box.y, w=d, h=d), pal.accent, str(i + 1), "FFFFFF" if contrast_ratio("FFFFFF", pal.accent) >= 3 else pal.text, max(small, d / 12700 * 0.45), font)
                y_head = box.y + d + int(H * 0.015)
                inset = 0
                head_h = int(ch * 0.22)
            _textbox(slide, Bbox(x=box.x + inset, y=y_head, w=cw - 2 * inset, h=head_h), [ParagraphSpec(item.title)], size=h2 if comp != "agenda" else h2, color=pal.accent if comp in ("cards", "comparison") else pal.text, font=font, bold=True, scale=scale, anchor="t")
            body_paras = [ParagraphSpec(b, bullet=True) for b in item.bullets] or ([ParagraphSpec(item.text)] if item.text else [])
            if body_paras:
                _textbox(slide, Bbox(x=box.x + inset, y=y_head + head_h, w=cw - 2 * inset, h=box.y2 - (y_head + head_h) - inset), body_paras, size=body, color=pal.text, font=font, scale=scale, line_spacing=typo.line_height)
        return slide, warnings

    if comp in ("stat_row", "big_number"):
        nums = c.numbers
        n = max(len(nums), 1)
        if comp == "big_number" or n == 1:
            num = nums[0] if nums else None
            if num:
                _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.5), h=int(avail_h * 0.55)), [ParagraphSpec(num.value)], size=display, color=pal.accent, font=font, bold=True, anchor="b", scale=scale, fit=False)
                _textbox(slide, Bbox(x=sx, y=top + int(avail_h * 0.57), w=int(sw * 0.5), h=int(avail_h * 0.3)), [ParagraphSpec(num.label)], size=h2, color=pal.text2, font=font, scale=scale)
            if c.paragraphs or c.bullets:
                paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs]
                _textbox(slide, Bbox(x=sx + int(sw * 0.55), y=top, w=int(sw * 0.45), h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
            return slide, warnings
        cw = int((sw - card_gap * (n - 1)) / n)
        for i, num in enumerate(nums):
            x = sx + i * (cw + card_gap)
            _textbox(slide, Bbox(x=x, y=top, w=cw, h=int(avail_h * 0.45)), [ParagraphSpec(num.value)], size=display * 0.8, color=pal.accent, font=font, bold=True, anchor="b", scale=scale)
            _textbox(slide, Bbox(x=x, y=top + int(avail_h * 0.47), w=cw, h=int(avail_h * 0.35)), [ParagraphSpec(num.label)], size=body, color=pal.text2, font=font, scale=scale)
        return slide, warnings

    if comp == "chart_text" and c.chart is not None:
        has_text = bool(c.paragraphs or c.bullets)
        chart_w = int(sw * (0.62 if has_text else 1.0))
        try:
            add_chart(slide, Bbox(x=sx, y=top, w=chart_w, h=avail_h), c.chart, outline, manifest.components.chart_style, typo, text_hex=pal.text, neutral_hex=t.color_for("neutral.1"))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"chart failed: {str(e)[:120]}")
        if has_text:
            paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs]
            _textbox(slide, Bbox(x=sx + chart_w + gap, y=top, w=sw - chart_w - gap, h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
        return slide, warnings

    if comp == "table" and c.table is not None:
        rows = len(c.table.rows) + 1
        tbl_h = min(avail_h, int(rows * H * 0.075))
        style = manifest.components.table_style
        if not style.body_text_hex or contrast_ratio(style.body_text_hex, pal.bg) < 4.5:
            style = style.model_copy(update={"body_text_hex": pal.text, "band_fill_hex": None})  # dark template text on a dark ground
        try:
            add_table(slide, Bbox(x=sx, y=top, w=sw, h=tbl_h), c.table, style, typo)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"table failed: {str(e)[:120]}")
        if c.paragraphs and tbl_h < avail_h - int(H * 0.08):
            _textbox(slide, Bbox(x=sx, y=top + tbl_h + int(H * 0.02), w=sw, h=avail_h - tbl_h - int(H * 0.02)), [ParagraphSpec(p) for p in c.paragraphs], size=small, color=pal.text2, font=font, scale=scale)
        return slide, warnings

    if comp == "quote" and c.quote:
        _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.85), h=int(avail_h * 0.65)), [ParagraphSpec("«" + c.quote.strip("«»\"") + "»")], size=h2 * 1.15, color=pal.text, font=font, scale=scale, anchor="ctr")
        if c.quote_author:
            _textbox(slide, Bbox(x=sx, y=top + int(avail_h * 0.68), w=int(sw * 0.85), h=int(avail_h * 0.2)), [ParagraphSpec(c.quote_author)], size=small, color=pal.accent, font=font, scale=scale)
        return slide, warnings

    # fallback: bullets
    paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs] or [ParagraphSpec(i.title, bullet=True) for i in _items(oslide)]
    if paras:
        _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.9), h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
    else:
        warnings.append("empty slide content")
    return slide, warnings
