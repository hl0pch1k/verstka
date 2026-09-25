"""Compose: lay out a content slide from the template's design system.

A sample slide of the template is a good source of style but a poor mould for new content: its cards are as tall as
its designer needed, its text as small as a placeholder allows. Here the content decides the geometry. The slide's
free area (below the heading, clear of chrome) is divided on a grid; text is measured with the template's fonts; sizes
come from the template's own type scale with readable minimums; cards, badges, dividers and accents take the
template's colours — and its card shape itself when a sample has one.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Optional

from lxml import etree
from pptx.slide import Slide

from verstka.analysis.xmlns import q
from verstka.planning.heuristics import label_beside
from verstka.rendering.charts import add_chart
from verstka.rendering.fonts import figure_metrics_em, left_bearing_em, text_width_pt, wrap_lines
from verstka.rendering.tables import add_table
from verstka.schemas.common import EMU_PER_PT, Bbox, PatternKind, contrast_ratio, relative_luminance
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideItem, TableData
from verstka.schemas.template import TemplateManifest
from verstka.ru import typeset

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"


# ---------------------------------------------------------------------------------------------- text model


@dataclass
class Run:
    text: str
    size: float
    color: str
    bold: bool = False
    font: Optional[str] = None


@dataclass
class Para:
    runs: list[Run]
    align: str = "l"
    space_after: float = 0.0  # pt
    marker: Optional[str] = None  # bullet character
    marker_color: Optional[str] = None

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def size(self) -> float:
        return max((r.size for r in self.runs), default=12.0)

    @property
    def bold(self) -> bool:
        return any(r.bold for r in self.runs)


def para_lines(p: Para, width_pt: float) -> int:
    font = p.runs[0].font if p.runs else None
    indent = p.size * 1.1 if p.marker else 0.0
    return max(len(wrap_lines(p.text, font, p.size, p.bold, max(width_pt - indent, 1.0))), 1)


def block_height_pt(paras: list[Para], width_pt: float, line: float) -> float:
    h = 0.0
    for i, p in enumerate(paras):
        h += para_lines(p, width_pt) * p.size * line
        if i < len(paras) - 1:
            h += p.space_after
    return h


def widest_word_pt(text: str, font: Optional[str], size: float, bold: bool) -> float:
    return max((text_width_pt(w, font, size, bold) for w in text.split()), default=0.0)


# ---------------------------------------------------------------------------------------------- kit


def _mix(fg: str, bg: str, share: float) -> str:
    a = [int(fg[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg[i : i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{int(round(x * share + y * (1 - share))):02X}" for x, y in zip(a, b))


@dataclass
class Colors:
    """Colours that read on one ground (the slide background or a card)."""

    ground: str
    text: str
    muted: str
    accent: str  # for large figures and markers (≥ 3:1)
    accent_text: str  # for small text in the accent colour (≥ 4.5:1)
    divider: str
    heading: str = ""  # titles of blocks (card titles, step titles): the template's own colour for them when it reads
    figure: str = ""  # figures (KPI values, indices)

    def __post_init__(self) -> None:
        self.heading = self.heading or self.text
        self.figure = self.figure or self.accent


@dataclass
class CardStyle:
    proto: Optional[etree._Element]  # a sample card shape to copy (keeps gradients, shadows, corner shape)
    fill: Optional[str]
    line: Optional[str]
    radius_emu: int
    colors: Colors  # colours inside the card


class Kit:
    """The template's design system as the composer needs it: sizes, colours, card style, grid steps."""

    def __init__(self, manifest: TemplateManifest, W: int, H: int, ground: str, card_proto: Optional[etree._Element] = None, heading_color: Optional[str] = None) -> None:
        self.manifest = manifest
        t = manifest.tokens
        typo = t.typography
        self.W, self.H = W, H
        self.hpt = H / EMU_PER_PT
        self.font = typo.primary_family
        self.line = typo.line_height
        self.spacing_pct = typo.line_spacing if abs(typo.line_spacing - 1.2) > 1e-6 else 1.0
        self.sizes = sorted({round(s.size_pt, 2) for s in typo.scale if s.size_pt >= 7} | {round(float(x), 2) for x in (typo.sizes_used or []) if x >= 7})
        hp = self.hpt
        body_t = max(typo.size_for("body", 14.0), 0.027 * hp)
        self.body = self.snap(body_t, 0.025 * hp, 0.037 * hp)
        self.small = self.snap(max(typo.size_for("small", self.body * 0.85), 0.022 * hp), 0.019 * hp, self.body - 0.4)
        self.h3 = self.snap(max(self.body * 1.18, 0.032 * hp), self.body * 1.07, 0.044 * hp)
        self.lead = self.snap(0.037 * hp, self.body * 1.12, 0.05 * hp)
        self.h2 = self.snap(0.046 * hp, self.lead * 1.08, 0.06 * hp)
        self.statement = self.snap(0.068 * hp, self.h2 * 1.1, 0.085 * hp)
        self.display = self.snap(0.09 * hp, 0.062 * hp, 0.13 * hp)
        self.mega = self.snap(0.2 * hp, max(self.display * 1.3, 0.11 * hp), 0.26 * hp)
        # the template's weight habits: VK decks set headings and figures in regular weight, the LCT deck in bold
        fam = typo.families[0] if typo.families else None
        heads_bold = max((st.weight_bold_share for st in typo.scale if st.role in ("h1", "h2", "display")), default=0.0)
        self.bold = bool((fam and fam.bold_share >= 0.06) or heads_bold >= 0.3)
        nums = [sl.style.bold for pt in manifest.patterns if not pt.reference for sl in pt.slots if sl.role.value == "number"]
        self.figure_bold = (sum(nums) > len(nums) / 2) if nums else self.bold  # figures weigh what the samples' figures weigh
        # grid steps
        self.gap = int(0.024 * W)  # between cards
        self.vgap = int(0.03 * H)  # between rows / blocks
        # colours
        self.accents = [a for a in t.accents()] or ["0077FF"]
        self.palette = [c.hex for c in t.colors]
        self.heading_color = heading_color
        self.head_size: Optional[float] = None  # the deck's heading size (set by the caller): statements stay under it
        self.colors = self.colors_on(ground, prefer=heading_color)
        self.card = self._card_style(ground, card_proto)

    # ---- sizes -------------------------------------------------------------------------------------------------
    def snap(self, target: float, lo: float, hi: float) -> float:
        """The template size closest to `target` inside [lo, hi]; outside the window the nearest template size when it
        is within a quarter of the target, else the target itself (rounded to half a point)."""
        inside = [s for s in self.sizes if lo - 0.05 <= s <= hi + 0.05]
        if inside:
            return min(inside, key=lambda s: (abs(s - target), -s))
        # nothing of the template's own in the window: the nearest size of the template that keeps the order of the
        # roles (never above hi — a «small» size must stay smaller than the body), else the target itself
        near = [s for s in self.sizes if abs(s - target) <= 0.25 * target and lo * 0.9 <= s <= hi + 0.05]
        if near:
            return min(near, key=lambda s: abs(s - target))
        return round(min(max(target, lo), hi) * 2) / 2

    def steps_down(self, size: float, floor: float) -> list[float]:
        """size and every template size below it down to floor (largest first)."""
        out = [size] + [s for s in reversed(self.sizes) if floor - 0.05 <= s < size - 0.05]
        return out

    _NICE = (40.0, 44.0, 48.0, 54.0, 60.0, 66.0, 72.0, 80.0, 88.0, 96.0, 110.0, 120.0, 140.0, 160.0)

    def figure_sizes(self, cap: float, floor: float) -> list[float]:
        """Sizes for figures, largest first: the template's own sizes plus display steps above them (a figure may be
        set larger than any text of the template — the audit's display rule)."""
        top = max(self.sizes) if self.sizes else 36.0
        cands = {s for s in self.sizes if floor - 0.05 <= s <= cap + 0.05} | {s for s in self._NICE if top < s <= cap + 0.05 and s >= floor}
        return sorted(cands, reverse=True) or [max(floor, min(cap, top))]

    def figure_cap(self, n: int, in_tiles: bool, strategy: str) -> float:
        cap = {1: 0.30, 2: 0.20, 3: 0.15, 4: 0.11}.get(n, 0.08) * self.hpt
        if in_tiles:
            cap = min(cap, 0.11 * self.hpt)
        return cap * {"visual": 1.2, "compact": 0.85}.get(strategy, 1.0)

    def steps_up(self, size: float, cap: float) -> list[float]:
        return [s for s in self.sizes if size + 0.05 < s <= cap + 0.05]

    # ---- colours -----------------------------------------------------------------------------------------------
    def _slot_colors(self, *roles: str) -> list[str]:
        """Colours the template gives a role in its samples, most frequent first."""
        from collections import Counter

        cnt: Counter = Counter()
        for p in self.manifest.patterns:
            if p.reference:
                continue
            for sl in p.slots:
                if sl.role.value in roles and sl.style.color_hex:
                    cnt[sl.style.color_hex.upper()] += 1
        return [c for c, _ in cnt.most_common()]

    def colors_on(self, ground: str, prefer: Optional[str] = None, inside_card: bool = False) -> Colors:
        """Colours for one ground. Running text prefers a neutral (black, white, greys): body copy in a brand colour
        reads as decoration. Headings of blocks and figures take the colours the template's samples give them."""
        t = self.manifest.tokens
        dark_ground = relative_luminance(ground) < 0.4

        def sat(hex_: str) -> float:
            r, g, b = (int(hex_[i : i + 2], 16) / 255 for i in (0, 2, 4))
            mx, mn = max(r, g, b), min(r, g, b)
            return 0.0 if mx == 0 else (mx - mn) / mx

        cands = [t.color_for("text.primary"), t.color_for("text.secondary")] + [c.hex for c in t.colors] + ["FFFFFF", "000000"]
        cands = [c for c in dict.fromkeys(c for c in cands if c)]
        strong = [c for c in cands if contrast_ratio(c, ground) >= 7.0] or [c for c in cands if contrast_ratio(c, ground) >= 4.5]
        neutral = [c for c in strong if sat(c) < 0.25]
        text = (neutral or strong or ["FFFFFF" if dark_ground else "000000"])[0]
        if prefer and not inside_card and contrast_ratio(prefer, ground) >= 4.5 and sat(prefer) < 0.25:
            text = prefer  # the slide heading is neutral: the body follows it
        muted_c = [c for c in [t.color_for("text.secondary")] + [x.hex for x in t.colors if x.role and x.role.startswith("neutral")] if c and c != text]
        muted = next((c for c in muted_c if 4.5 <= contrast_ratio(c, ground) and contrast_ratio(c, text) >= 1.25), text)
        acc_big = next((a for a in self.accents if contrast_ratio(a, ground) >= 3.0), None)
        acc_small = next((a for a in self.accents if contrast_ratio(a, ground) >= 4.5), None)
        accent = acc_big or text
        accent_text = acc_small or (acc_big if acc_big and contrast_ratio(acc_big, ground) >= 3.8 else text)
        div_c = [x.hex for x in t.colors if x.hex not in (ground,)]
        divider = next((c for c in sorted(div_c, key=lambda c: contrast_ratio(c, ground)) if 1.25 <= contrast_ratio(c, ground) <= 2.6), None)
        if divider is None:
            divider = _mix(text, ground, 0.22)
        head_roles = ("card_title",) if inside_card else ("card_title", "title")
        heading = next((c for c in self._slot_colors(*head_roles) if contrast_ratio(c, ground) >= 4.5), None)
        if not inside_card and prefer and contrast_ratio(prefer, ground) >= 4.5:
            heading = prefer
        figure = next((c for c in self._slot_colors("number") if contrast_ratio(c, ground) >= 3.0 and sat(c) >= 0.25), None) or accent
        return Colors(ground=ground, text=text, muted=muted, accent=accent, accent_text=accent_text, divider=divider, heading=heading or text, figure=figure)

    def _card_style(self, ground: str, proto: Optional[etree._Element]) -> CardStyle:
        card = self.manifest.components.card
        fill = line = None
        radius = int(0.12 * 914400)
        if proto is not None:
            fill = _shape_fill_hex(proto)
            line = _shape_line_hex(proto)
        elif card is not None:
            fill = card.fill_hex
            line = card.line_hex
            if card.radius is not None and card.width_frac and card.height_frac:
                side = min(card.width_frac * self.W, card.height_frac * self.H)
                radius = int(max(0.0, min(card.radius, 0.5)) * side)
        surface = self.manifest.tokens.color_for("surface")
        if proto is None:
            # a card must stand apart from its ground: its own fill, else the surface colour, else an outline
            if not fill or contrast_ratio(fill, ground) < 1.04:
                fill = surface if surface and 1.04 <= contrast_ratio(surface, ground) <= 6 else None
            if fill and contrast_ratio(fill, ground) > 12:
                fill = surface if surface and 1.04 <= contrast_ratio(surface, ground) <= 6 else fill
            if not fill:
                line = line if line and contrast_ratio(line, ground) >= 1.5 else self.colors.divider
            else:
                line = None
        inner = self.colors_on(fill or ground, prefer=self.heading_color if fill is None else None, inside_card=fill is not None)
        return CardStyle(proto=proto, fill=fill, line=line, radius_emu=radius, colors=inner)


def _solid_hex(fill_parent: Optional[etree._Element]) -> Optional[str]:
    if fill_parent is None:
        return None
    sf = fill_parent.find(q("a:solidFill"))
    if sf is not None:
        c = sf.find(q("a:srgbClr"))
        if c is not None:
            return (c.get("val") or "").upper() or None
    gf = fill_parent.find(q("a:gradFill"))
    if gf is not None:
        stops = gf.findall(".//" + q("a:srgbClr"))
        if stops:
            return (stops[0].get("val") or "").upper() or None
    return None


def _shape_fill_hex(el: etree._Element) -> Optional[str]:
    return _solid_hex(el.find(q("p:spPr")))


def _shape_line_hex(el: etree._Element) -> Optional[str]:
    spPr = el.find(q("p:spPr"))
    ln = spPr.find(q("a:ln")) if spPr is not None else None
    if ln is None or ln.find(q("a:noFill")) is not None:
        return None
    return _solid_hex(ln)


# ---------------------------------------------------------------------------------------------- primitives


class Canvas:
    """Adds shapes to a slide with fresh ids."""

    def __init__(self, slide: Slide, kit: Optional[Kit] = None, *, font: Optional[str] = None, spacing_pct: Optional[float] = None) -> None:
        self.slide = slide
        self.kit = kit
        self.font = font if font is not None else (kit.font if kit else None)
        self.spacing_pct = spacing_pct if spacing_pct is not None else (kit.spacing_pct if kit else 1.0)
        self.tree = slide._element.cSld.find(q("p:spTree"))
        ids = [int(el.get("id")) for el in slide._element.iter(q("p:cNvPr")) if (el.get("id") or "").isdigit()]
        self.next_id = (max(ids) + 1) if ids else 2
        self.added: list[etree._Element] = []

    def _id(self) -> int:
        i = self.next_id
        self.next_id += 1
        return i

    def _append(self, el: etree._Element) -> etree._Element:
        """Content goes on top of the canvas — as python-pptx's own element classes, so that `slide.shapes` can read
        the slide while it is being composed (a chart looks for the unit caption written above it)."""
        from pptx.oxml import parse_xml

        el = parse_xml(etree.tostring(el))
        self.tree.append(el)
        self.added.append(el)
        return el

    # ---- text --------------------------------------------------------------------------------------------------
    def text(self, box: Bbox, paras: list[Para], *, anchor: str = "t", name: str = "Text", insets: tuple[int, int, int, int] = (0, 0, 0, 0)) -> etree._Element:
        sp = etree.Element(q("p:sp"))
        nv = etree.SubElement(sp, q("p:nvSpPr"))
        c = etree.SubElement(nv, q("p:cNvPr"))
        c.set("id", str(self._id()))
        c.set("name", f"{name} {c.get('id')}")
        etree.SubElement(nv, q("p:cNvSpPr")).set("txBox", "1")
        etree.SubElement(nv, q("p:nvPr"))
        spPr = etree.SubElement(sp, q("p:spPr"))
        _xfrm(spPr, box)
        geom = etree.SubElement(spPr, q("a:prstGeom"))
        geom.set("prst", "rect")
        etree.SubElement(geom, q("a:avLst"))
        etree.SubElement(spPr, q("a:noFill"))
        self._txbody(sp, paras, anchor, insets)
        return self._append(sp)

    def _txbody(self, sp: etree._Element, paras: list[Para], anchor: str, insets: tuple[int, int, int, int]) -> None:
        tx = etree.SubElement(sp, q("p:txBody"))
        bp = etree.SubElement(tx, q("a:bodyPr"))
        bp.set("wrap", "square")
        for n, v in zip(("lIns", "tIns", "rIns", "bIns"), insets):
            bp.set(n, str(int(v)))
        bp.set("anchor", anchor)
        bp.set("rtlCol", "0")
        etree.SubElement(bp, q("a:noAutofit"))
        etree.SubElement(tx, q("a:lstStyle"))
        for para in paras or [Para([Run("", 12.0, "000000")])]:
            p = etree.SubElement(tx, q("a:p"))
            pPr = etree.SubElement(p, q("a:pPr"))
            pPr.set("algn", para.align)
            ln = etree.SubElement(pPr, q("a:lnSpc"))
            etree.SubElement(ln, q("a:spcPct")).set("val", str(int(round(self.spacing_pct * 100000))))
            if para.space_after:
                sa = etree.SubElement(pPr, q("a:spcAft"))
                etree.SubElement(sa, q("a:spcPts")).set("val", str(int(round(para.space_after * 100))))
            if para.marker:
                hang = int(para.size * 1.1 * EMU_PER_PT)
                pPr.set("marL", str(hang))
                pPr.set("indent", str(-hang))
                if para.marker_color:
                    bc = etree.SubElement(pPr, q("a:buClr"))
                    etree.SubElement(bc, q("a:srgbClr")).set("val", para.marker_color)
                bf = etree.SubElement(pPr, q("a:buFont"))
                bf.set("typeface", "Arial")
                etree.SubElement(pPr, q("a:buChar")).set("char", para.marker)
            else:
                pPr.set("marL", "0")
                pPr.set("indent", "0")
                etree.SubElement(pPr, q("a:buNone"))
            for r in para.runs:
                if not r.text:
                    continue
                re_ = etree.SubElement(p, q("a:r"))
                rPr = etree.SubElement(re_, q("a:rPr"))
                rPr.set("lang", "ru-RU")
                rPr.set("sz", str(int(round(r.size * 100))))
                rPr.set("b", "1" if r.bold else "0")
                rPr.set("dirty", "0")
                sf = etree.SubElement(rPr, q("a:solidFill"))
                etree.SubElement(sf, q("a:srgbClr")).set("val", r.color.upper())
                font = r.font or self.font
                if font:
                    etree.SubElement(rPr, q("a:latin")).set("typeface", font)
                    etree.SubElement(rPr, q("a:cs")).set("typeface", font)
                t = etree.SubElement(re_, q("a:t"))
                t.text = r.text
            end = etree.SubElement(p, q("a:endParaRPr"))
            end.set("lang", "ru-RU")
            end.set("sz", str(int(round(para.size * 100))))

    # ---- shapes ------------------------------------------------------------------------------------------------
    def rect(self, box: Bbox, fill: Optional[str], line: Optional[str] = None, radius_emu: int = 0, line_w_pt: float = 0.75, name: str = "Shape", geom: Optional[str] = None) -> etree._Element:
        sp = etree.Element(q("p:sp"))
        nv = etree.SubElement(sp, q("p:nvSpPr"))
        c = etree.SubElement(nv, q("p:cNvPr"))
        c.set("id", str(self._id()))
        c.set("name", f"{name} {c.get('id')}")
        etree.SubElement(nv, q("p:cNvSpPr"))
        etree.SubElement(nv, q("p:nvPr"))
        spPr = etree.SubElement(sp, q("p:spPr"))
        _xfrm(spPr, box)
        prst = geom or ("roundRect" if radius_emu > 0 else "rect")
        g = etree.SubElement(spPr, q("a:prstGeom"))
        g.set("prst", prst)
        av = etree.SubElement(g, q("a:avLst"))
        if prst == "roundRect":
            side = max(min(box.w, box.h), 1)
            gd = etree.SubElement(av, q("a:gd"))
            gd.set("name", "adj")
            gd.set("fmla", f"val {int(min(radius_emu / side, 0.5) * 100000)}")
        if fill:
            sf = etree.SubElement(spPr, q("a:solidFill"))
            etree.SubElement(sf, q("a:srgbClr")).set("val", fill.upper())
        else:
            etree.SubElement(spPr, q("a:noFill"))
        ln = etree.SubElement(spPr, q("a:ln"))
        if line:
            ln.set("w", str(int(line_w_pt * EMU_PER_PT)))
            sf = etree.SubElement(ln, q("a:solidFill"))
            etree.SubElement(sf, q("a:srgbClr")).set("val", line.upper())
        else:
            etree.SubElement(ln, q("a:noFill"))
        return self._append(sp)

    def card(self, box: Bbox, style: CardStyle, name: str = "Card") -> etree._Element:
        if style.proto is not None:
            el = copy.deepcopy(style.proto)
            for tag in ("p:txBody",):
                for old in el.findall(q(tag)):
                    el.remove(old)
            nv = el.find(".//" + q("p:cNvPr"))
            if nv is not None:
                nv.set("id", str(self._id()))
                nv.set("name", f"{name} {nv.get('id')}")
                for k in ("descr", "title"):
                    nv.attrib.pop(k, None)
                for child in list(nv):
                    nv.remove(child)  # no hyperlinks of the sample
            spPr = el.find(q("p:spPr"))
            old_box = _xfrm_box(spPr)
            _xfrm(spPr, box, replace=True)
            geom = spPr.find(q("a:prstGeom"))
            if geom is not None and geom.get("prst") in ("roundRect", "snip1Rect", "snip2SameRect", "round2SameRect", "round1Rect") and old_box is not None:
                # the corner keeps its absolute size: the sample's ratio is relative to the sample's shorter side
                av = geom.find(q("a:avLst"))
                gds = av.findall(q("a:gd")) if av is not None else []
                old_side = max(min(old_box.w, old_box.h), 1)
                new_side = max(min(box.w, box.h), 1)
                # (capped at a quarter of the shorter side: a small card never turns into a capsule)
                for gd in gds:
                    m = re.match(r"val (\d+)", gd.get("fmla") or "")
                    if m:
                        gd.set("fmla", f"val {min(int(int(m.group(1)) * old_side / new_side), 25000)}")
                if not gds and geom.get("prst") == "roundRect":
                    # default roundRect corner is 16.667% of the sample's shorter side
                    if av is None:
                        av = etree.SubElement(geom, q("a:avLst"))
                    gd = etree.SubElement(av, q("a:gd"))
                    gd.set("name", "adj")
                    gd.set("fmla", f"val {min(int(16667 * old_side / new_side), 25000)}")
            # a group-transformed or rotated sample must not carry its rotation/flip
            xfrm = spPr.find(q("a:xfrm"))
            for a in ("rot", "flipH", "flipV"):
                xfrm.attrib.pop(a, None)
            return self._append(el)
        return self.rect(box, style.fill, style.line, style.radius_emu, name=name)

    def ellipse(self, box: Bbox, fill: str, name: str = "Badge") -> etree._Element:
        return self.rect(box, fill, None, 0, name=name, geom="ellipse")

    def line(self, x1: int, y1: int, x2: int, y2: int, color: str, width_pt: float = 1.0, name: str = "Line") -> etree._Element:
        cx = etree.Element(q("p:cxnSp"))
        nv = etree.SubElement(cx, q("p:nvCxnSpPr"))
        c = etree.SubElement(nv, q("p:cNvPr"))
        c.set("id", str(self._id()))
        c.set("name", f"{name} {c.get('id')}")
        etree.SubElement(nv, q("p:cNvCxnSpPr"))
        etree.SubElement(nv, q("p:nvPr"))
        spPr = etree.SubElement(cx, q("p:spPr"))
        xfrm = etree.SubElement(spPr, q("a:xfrm"))
        if y2 < y1:
            xfrm.set("flipV", "1")
        off = etree.SubElement(xfrm, q("a:off"))
        off.set("x", str(int(min(x1, x2))))
        off.set("y", str(int(min(y1, y2))))
        ext = etree.SubElement(xfrm, q("a:ext"))
        ext.set("cx", str(int(abs(x2 - x1))))
        ext.set("cy", str(int(abs(y2 - y1))))
        g = etree.SubElement(spPr, q("a:prstGeom"))
        g.set("prst", "line")
        etree.SubElement(g, q("a:avLst"))
        ln = etree.SubElement(spPr, q("a:ln"))
        ln.set("w", str(int(width_pt * EMU_PER_PT)))
        sf = etree.SubElement(ln, q("a:solidFill"))
        etree.SubElement(sf, q("a:srgbClr")).set("val", color.upper())
        return self._append(cx)


def _xfrm(spPr: etree._Element, box: Bbox, replace: bool = False) -> None:
    xfrm = spPr.find(q("a:xfrm"))
    if xfrm is None:
        xfrm = etree.Element(q("a:xfrm"))
        spPr.insert(0, xfrm)
    elif replace:
        for child in list(xfrm):
            xfrm.remove(child)
    off = xfrm.find(q("a:off"))
    if off is None:
        off = etree.SubElement(xfrm, q("a:off"))
    off.set("x", str(int(box.x)))
    off.set("y", str(int(box.y)))
    ext = xfrm.find(q("a:ext"))
    if ext is None:
        ext = etree.SubElement(xfrm, q("a:ext"))
    ext.set("cx", str(max(int(box.w), 0)))
    ext.set("cy", str(max(int(box.h), 0)))


def _xfrm_box(spPr: Optional[etree._Element]) -> Optional[Bbox]:
    xfrm = spPr.find(q("a:xfrm")) if spPr is not None else None
    if xfrm is None:
        return None
    off, ext = xfrm.find(q("a:off")), xfrm.find(q("a:ext"))
    if off is None or ext is None:
        return None
    return Bbox(x=int(off.get("x")), y=int(off.get("y")), w=int(ext.get("cx")), h=int(ext.get("cy")))


# ---------------------------------------------------------------------------------------------- helpers

_FIG_RE = re.compile(r"(?<![\w])([+\-−–]?\d[\d\s  ]*(?:[.,]\d+)?\s?(?:%|млн|млрд|тыс\.?|₽|руб\.?|ч|мин|сек|дн(?:ей|я)?|мес(?:\.|яц(?:а|ев)?)?|раз[а]?|×)?(?:\s?₽)?)", re.I)


def highlight_runs(text: str, size: float, color: str, accent: str, bold: bool = False, accent_bold: bool = True, font: Optional[str] = None) -> list[Run]:
    """Figures inside a statement («27 млн ₽», «4 GPU») set in the accent colour: the eye finds the ask."""
    out: list[Run] = []
    pos = 0
    text = typeset(text)
    for m in _FIG_RE.finditer(text):
        s, e = m.span(1)
        val = text[s:e].strip()
        if not any(ch.isdigit() for ch in val) or (len(val) <= 2 and not re.search(r"%|₽", val) and not re.match(r"\d{2}", val)):
            continue
        if s > pos:
            out.append(Run(text[pos:s], size, color, bold, font))
        out.append(Run(text[s:e], size, accent, accent_bold or bold, font))
        pos = e
    if pos < len(text):
        out.append(Run(text[pos:], size, color, bold, font))
    return out or [Run(text, size, color, bold, font)]


_HERO_FIG_RE = re.compile(r"(?<![\w])([+\-−–]?\d[\d\s\u00a0]*(?:[.,]\d+)?\s?(?:%|×|раз[а]?\b|(?:тыс\.?|млн|млрд)?\s?(?:₽|руб\.?|\$|€)|млн|млрд))", re.I)


def single_figure(text: str) -> Optional[tuple[str, str]]:
    """(figure, label) when a short sentence carries exactly one money/percent/multiple figure — the label is the
    sentence without it («Экономия в год на одну площадку»)."""
    t = " ".join(text.split())
    if len(t) > 90:
        return None
    found = [m for m in _HERO_FIG_RE.finditer(t) if any(ch.isdigit() for ch in m.group(1))]
    digits = re.findall(r"\d+(?:[.,]\d+)?", t)
    if len(found) != 1 or len(digits) > len(re.findall(r"\d+(?:[.,]\d+)?", found[0].group(1))):
        return None
    m = found[0]
    value = m.group(1).strip()
    before = t[: m.start(1)].rstrip()
    last = before.split()[-1].lower() if before.split() else ""
    if last in ("на", "в", "до", "с", "от", "за", "по", "около", "почти", "более", "менее"):
        before = before[: -len(last)]  # «рост на 34%» → «рост …»: the preposition leaves with its figure
    rest = (before + " " + t[m.end(1) :]).replace("—", " ").replace("–", " ")
    rest = " ".join(rest.split()).strip(" ,.:;")
    if len(rest.split()) < 2:
        return None
    return value, rest[:1].upper() + rest[1:]


_FIG_UNIT_RE = re.compile(r"^([+\-−–~≈×]?\s?\d[\d\s\u00a0]*(?:[.,]\d+)?\s?%?)\s*([A-Za-zА-Яа-яЁё₽$€].{0,12})$")


def distinct_label(value: str, label: str, headline: str) -> str:
    """A figure's label that does not repeat the heading above it: when the label is the heading's own sentence
    («оператор тратит в среднем 6,5 минуты» under «Оператор тратит в среднем 6,5 минуты на одно обращение»), the
    words around the figure in the heading say what it measures («минуты на одно обращение»). One rule shared with the
    planner (heuristics.label_beside): the figure is found as whole words («3 мес» is «3 месяца», never a piece of
    «13 месяцев»), so the plan says what the slide shows."""
    return label_beside(value, label, headline)


def _pt(emu: int) -> float:
    return emu / EMU_PER_PT


def _emu(pt: float) -> int:
    return int(round(pt * EMU_PER_PT))


# ---------------------------------------------------------------------------------------------- composer


class Composer:
    def __init__(self, slide: Slide, kit: Kit, oslide: OutlineSlide, outline: DeckOutline, strategy: str, manifest: TemplateManifest) -> None:
        self.slide = slide
        self.kit = kit
        self.cv = Canvas(slide, kit)
        self.o = oslide
        self.outline = outline
        self.strategy = strategy
        self.manifest = manifest
        self.warnings: list[str] = []

    # ---- measurement helpers ----------------------------------------------------------------------------------
    def h(self, paras: list[Para], width_emu: int) -> int:
        return _emu(block_height_pt(paras, _pt(width_emu), self.kit.line)) + _emu(2)

    def P(self, text: str, size: float, color: str, bold: bool = False, align: str = "l", space_after: float = 0.0, marker: Optional[str] = None, marker_color: Optional[str] = None) -> Para:
        # the run names the template font: measuring and rendering see the same face (Montserrat is 20% wider than Play)
        return Para([Run(typeset(text), size, color, bold, self.kit.font)], align=align, space_after=space_after, marker=marker, marker_color=marker_color)

    def fits_width(self, texts: list[str], size: float, bold: bool, width_emu: int) -> bool:
        w = _pt(width_emu)
        return all(widest_word_pt(t, self.kit.font, size, bold) <= w for t in texts)

    # ---- entry -------------------------------------------------------------------------------------------------
    def compose(self, comp: str, area: Bbox) -> None:
        c = self.o.content
        kind = self.o.kind
        intro = self._intro_text()
        if intro and comp not in ("statement", "quote"):
            area = self._intro(intro, area)
        if comp in ("table",) and c.table is not None:
            self.table(area, c.table)
        elif comp in ("chart_text", "chart") and c.chart is not None:
            self.chart(area)
        elif comp in ("stat_row", "big_number") and c.numbers:
            if len(c.numbers) == 1 or comp == "big_number":
                self.big_number(area, c.numbers[0], extra=self._running(skip_intro=bool(intro)), others=c.numbers[1:])
            else:
                self.kpis(area, c.numbers, extra=self._running(skip_intro=bool(intro)))
        elif comp in ("process",) or kind in (PatternKind.process, PatternKind.timeline):
            items = self._items()
            if items:
                self.process(area, items)
            else:
                self.bullets(area, self._running())
        elif comp == "agenda" or kind == PatternKind.agenda:
            self.agenda(area, self._items() or [SlideItem(title=b) for b in c.bullets])
        elif comp in ("comparison", "two_column") or kind in (PatternKind.comparison, PatternKind.two_column):
            items = self._items()
            if len(items) >= 2:
                self.columns(area, items)
            else:
                self.bullets(area, self._running())
        elif comp in ("cards",) or kind in (PatternKind.cards, PatternKind.team):
            items = self._items()
            if items:
                self.cards(area, items)
            else:
                self.bullets(area, self._running())
        elif comp == "quote" and c.quote:
            self.quote(area, c.quote, c.quote_author)
        elif comp == "statement" or (not c.bullets and not c.items and len(c.paragraphs) == 1 and len(c.paragraphs[0]) <= 260):
            text = (c.paragraphs or [c.quote or ""])[0]
            hero = single_figure(text)
            if hero is not None:
                # «Экономия — 18 млн ₽ в год на одну площадку»: one figure carries the message — it is set as one
                value, label = hero
                self.big_number(area, NumberCallout(value=value, label=label), extra=[], others=[])
            else:
                self.statement(area, text)
        else:
            items = self._items()
            if c.bullets:
                self.bullets(area, list(c.bullets) + ([p for p in c.paragraphs] if c.paragraphs and not intro else []))
            elif items:
                self.cards(area, items)
            elif c.paragraphs:
                self.paragraphs(area, c.paragraphs)
            elif c.numbers:
                self.kpis(area, c.numbers, extra=[])
            else:
                self.warnings.append("empty slide content")

    # ---- content accessors -------------------------------------------------------------------------------------
    def _items(self) -> list[SlideItem]:
        c = self.o.content
        if c.items:
            return list(c.items)
        if c.columns:
            return list(c.columns)
        if c.numbers and self.o.kind not in (PatternKind.stat_row, PatternKind.big_number):
            return [SlideItem(title=n.value, text=n.label, number=n.value) for n in c.numbers]
        return [SlideItem(title=b) for b in c.bullets]

    def _intro_text(self) -> Optional[str]:
        """A subtitle, or the one paragraph that stands next to structured content (cards, a table, a chart)."""
        c = self.o.content
        if self.o.subtitle and self.o.kind not in (PatternKind.title, PatternKind.section, PatternKind.thanks):
            return self.o.subtitle
        structured = c.items or c.columns or c.table is not None or c.chart is not None or c.numbers
        if structured and len(c.paragraphs) == 1 and len(c.paragraphs[0]) <= 200 and not c.bullets:
            return c.paragraphs[0]
        return None

    def _running(self, skip_intro: bool = False) -> list[str]:
        c = self.o.content
        out = list(c.bullets)
        if not skip_intro:
            out += list(c.paragraphs)
        return out

    # ---- blocks ------------------------------------------------------------------------------------------------
    def _intro(self, text: str, area: Bbox) -> Bbox:
        k = self.kit
        width = min(area.w, int(area.w * 0.78))
        size = k.lead if len(text) <= 120 else k.body
        para = [self.P(text, size, k.colors.muted if k.colors.muted != k.colors.text else k.colors.text)]
        hh = self.h(para, width)
        self.cv.text(Bbox(x=area.x, y=area.y, w=width, h=hh), para, name="Intro")
        dy = hh + int(k.vgap * 1.1)
        return Bbox(x=area.x, y=area.y + dy, w=area.w, h=max(area.h - dy, int(area.h * 0.4)))

    def _place_v(self, area: Bbox, block_h: int, fill_top: bool = False) -> int:
        """Top of a block: always the content line under the heading. Flipping through the deck, content starts at
        the same height on every slide; the air a short block leaves stays at the bottom (the type grows first)."""
        return area.y

    # ---- cards --------------------------------------------------------------------------------------------------
    def _grid(self, n: int, area: Bbox, longest: int) -> tuple[int, int]:
        if n <= 1:
            return 1, 1
        wide = area.w / max(area.h, 1) >= 1.6
        if n <= 3:
            return n, 1
        if n == 4:
            return (4, 1) if wide and longest <= 140 else (2, 2)
        if n == 5:
            return (5, 1) if wide and longest <= 70 else (3, 2)
        if n == 6:
            return 3, 2
        if n <= 8:
            return 4, 2
        return math.ceil(n / 3), 3

    def cards(self, area: Bbox, items: list[SlideItem], badge: Optional[str] = None) -> None:
        k = self.kit
        st = k.card
        n = len(items)
        if all(not i.text and not i.bullets and not i.number for i in items) and max(len(i.title.split()) for i in items) > 6:
            # theses, not titled items: each card holds its sentence as running text (regular weight, text colour)
            items = [SlideItem(title="", text=i.title, icon_hint=i.icon_hint) for i in items]
        longest = max(len(i.title) + len(i.text) + sum(len(b) for b in i.bullets) for i in items)
        cols, rows = self._grid(n, area, longest)
        if badge is None:
            # circles with digits say «in this order» — only steps get them; theses and risks carry an index numeral
            sequence = self.o.kind in (PatternKind.process, PatternKind.timeline)
            badge = {"visual": "number" if sequence else "index", "structured": "index", "compact": None}.get(self.strategy, "index")
            if self.o.kind in (PatternKind.team,):
                badge = None
            if all(i.number for i in items):
                badge = "figure"
        gap = k.gap
        colors = st.colors
        title_color = colors.heading

        def pick(cols: int, rows: int):
            cw = int((area.w - gap * (cols - 1)) / cols)
            pad = max(int(min(cw * 0.085, 0.05 * k.H)), int(0.026 * k.H))
            inner_w = cw - 2 * pad
            # sizes: the largest pair at which every card reads well (title ≤ 3 lines, text ≤ 7) and the row fits
            max_row_h = int((area.h - k.vgap * (rows - 1)) / rows)
            ladders = [(k.h2, k.lead), (k.lead, k.lead), (k.lead, k.body), (k.h3, k.body), (k.h3, k.small), (k.body, k.small)]
            if n <= 3 and longest <= 70:
                ladders.insert(0, (k.statement, k.h2))  # three short items: the type grows before the card does
            chosen = None
            fallback = None
            long_ok = None  # fits, but with more lines than we like: kept when the next step down is a big drop
            for ts, bs in ladders:
                if not self.fits_width([i.title for i in items], ts, k.bold, inner_w):
                    continue
                h = max(self._card_content_h(it, inner_w, ts, bs, badge, colors, i) for i, it in enumerate(items)) + 2 * pad
                if h > max_row_h:
                    continue
                t_lines = max(para_lines(self.P(i.title, ts, colors.text, bold=k.bold), _pt(inner_w)) for i in items)
                b_lines = max((sum(para_lines(self.P(b, bs, colors.text), _pt(inner_w)) for b in ([i.text] if i.text else []) + list(i.bullets)) for i in items), default=0)
                words = sum(len(t.split()) for i in items for t in [i.title, i.text] + list(i.bullets) if t)
                lines_all = sum(para_lines(self.P(i.title, ts, colors.text, bold=k.bold), _pt(inner_w)) for i in items if i.title) + sum(para_lines(self.P(b, bs, colors.text), _pt(inner_w)) for i in items for b in ([i.text] if i.text else []) + list(i.bullets))
                if lines_all and words / lines_all < 1.8 and (ts, bs) != ladders[-1]:
                    continue  # one or two words a line reads as a column of words, not as text
                fallback = fallback or (ts, bs, h)
                t_max = 3 if b_lines else 5  # a title that is the whole card may take more lines
                if t_lines <= t_max and b_lines <= 7:
                    chosen = (ts, bs, h)
                    break
                if t_lines <= t_max and b_lines <= 10 and long_ok is None:
                    long_ok = (ts, bs, h)
            if long_ok is not None and (chosen is None or chosen[1] < 0.8 * long_ok[1]):
                chosen = long_ok  # a template with sparse sizes (18 → 12) keeps 18 pt in nine lines rather than 12 pt
            chosen = chosen or fallback
            if chosen is None:
                ts, bs = k.body, k.small
                chosen = (ts, bs, max(self._card_content_h(it, inner_w, ts, bs, badge, colors, i) for i, it in enumerate(items)) + 2 * pad)

            return cw, pad, inner_w, chosen

        cw, pad, inner_w, chosen = pick(cols, rows)
        if n == 4 and cols == 4 and chosen[1] < k.body:
            # four cards that only fit in small type read better as a 2×2 block
            cw2, pad2, inner2, chosen2 = pick(2, 2)
            if chosen2[1] > chosen[1]:
                cols, rows, cw, pad, inner_w, chosen = 2, 2, cw2, pad2, inner2, chosen2
        ts, bs, content_h = chosen
        max_row_h = int((area.h - k.vgap * (rows - 1)) / rows)
        # cards hug their content (the tallest one sets the row): a card is never a half-empty slab
        ch = min(content_h, max_row_h)
        block_h = rows * ch + (rows - 1) * k.vgap
        y0 = self._place_v(area, block_h)
        last_row_n = n - cols * (rows - 1)
        for i, it in enumerate(items):
            r, cidx = divmod(i, cols)
            x_off = 0
            if r == rows - 1 and last_row_n < cols:
                x_off = int((cols - last_row_n) * (cw + gap) / 2)  # an incomplete last row is centred
            box = Bbox(x=area.x + x_off + cidx * (cw + gap), y=y0 + r * (ch + k.vgap), w=cw, h=ch)
            if st.fill or st.line or st.proto is not None:
                self.cv.card(box, st)
            else:
                # no card style: an accent rule over each item keeps the columns apart
                self.cv.rect(Bbox(x=box.x, y=box.y, w=box.w, h=max(_emu(2.25), 1)), colors.accent, name="Rule")
            self._card_content(it, Bbox(x=box.x + pad, y=box.y + pad, w=inner_w, h=ch - 2 * pad), ts, bs, badge, colors, i, title_color)

    def figure_para(self, value: str, size: float, color: str, muted: str) -> tuple[Para, float]:
        """A figure as one line: «31% → 12%» is two figures — the old one small and muted, the new one in the
        accent at full size. Returns the paragraph and its width in points."""
        k = self.kit
        b = k.figure_bold
        parts = re.split(r"\s*(?:→|->|⟶)\s*", value.strip())
        if len(parts) == 2 and all(any(ch.isdigit() for ch in x) for x in parts):
            small = k.snap(size * 0.55, k.h3, size * 0.7)
            runs = [Run(typeset(parts[0]), small, muted, b, k.font), Run("\u00a0→\u00a0", small, muted, False, k.font)]
            width = text_width_pt(parts[0], k.font, small, b) + text_width_pt(" → ", k.font, small, False)
            m = _FIG_UNIT_RE.match(parts[1])
            if m and m.group(2).strip() and size >= 1.6 * k.h2:
                # «47 → 29 минут»: the new figure leads, its word unit rides on the baseline at the old figure's size
                num, unit = m.group(1).strip(), m.group(2).strip()
                runs += [Run(typeset(num), size, color, b, k.font), Run("\u00a0" + typeset(unit), small, color, b, k.font)]
                return Para(runs), width + text_width_pt(num, k.font, size, b) + text_width_pt(" " + unit, k.font, small, b)
            runs.append(Run(typeset(parts[1]), size, color, b, k.font))
            return Para(runs), width + text_width_pt(parts[1], k.font, size, b)
        m = _FIG_UNIT_RE.match(value.strip())
        if m and m.group(2).strip() and size >= 1.6 * k.h2:
            # the unit is set smaller on the figure's baseline: «145 000 ₽», «2,1 ч», «4,6 из 5»
            num, unit = m.group(1).strip(), m.group(2).strip()
            usz = k.snap(size * 0.5, k.h3, size * 0.62)
            runs = [Run(typeset(num), size, color, b, k.font), Run("\u00a0" + typeset(unit), usz, color, b, k.font)]
            return Para(runs), text_width_pt(num, k.font, size, b) + text_width_pt(" " + unit, k.font, usz, b)
        v = typeset(value)
        return Para([Run(v, size, color, b, k.font)]), text_width_pt(v, k.font, size, b)

    def _under_heading(self) -> float:
        """The largest size a callout (a statement, a quote) may take under the slide's heading: a clear step below it."""
        k = self.kit
        return k.snap(k.head_size * 0.84, k.lead, max(k.lead, k.head_size * 0.9))

    def _figure_optics(self, para: Para, box_h: int) -> tuple[int, int]:
        """(left, top) EMU a large figure set bottom-anchored in a box `box_h` tall is moved by, so that its digits —
        not the empty side bearing and ascender room of the font — stand on the left edge and the top line of the
        content. The measuring font's metrics (Play); other families are moved a little less."""
        k = self.kit
        if not para.runs or not para.runs[0].text:
            return 0, 0
        first = para.runs[0]
        big = max(r.size for r in para.runs)
        bold = bool(first.bold)
        damp = 1.0 if not k.font or k.font.lower().startswith("play") else 0.7
        ref = 0.07 * (k.head_size or k.h2)  # the heading's own letters stand off its edge about this much
        left = max(0.0, left_bearing_em(first.text.lstrip()[:1], bold) * first.size - ref) * damp
        descent, digit_h = figure_metrics_em(bold)
        top = max(0.0, _pt(box_h) - (descent + digit_h) * big) * damp
        return _emu(left), _emu(top * 0.95)

    def _index_size(self, ts: float) -> float:
        """The «01» over a card: the accent numeral, a step above the card title (never the small accent text)."""
        k = self.kit
        return k.snap(max(ts * 1.4, k.h2), ts * 1.2, max(k.statement, ts * 1.8))

    def _badge_size(self, ts: float) -> int:
        """One badge for the deck (cards, steps): 7.5% of the slide height (never under 36 pt, so its digit can be
        set as large text), whatever the text size of the slide."""
        return _emu(max(self.kit.hpt * 0.075, 36.0))

    def _badge_digit(self) -> float:
        k = self.kit
        d = max(k.hpt * 0.075, 36.0)
        return k.snap(max(18.0, d * 0.48), 18.0, d * 0.6)

    def _card_paras(self, it: SlideItem, ts: float, bs: float, colors: Colors, title_color: Optional[str] = None) -> list[Para]:
        paras: list[Para] = []
        head = it.title if it.title and it.title != it.number else ""
        body_texts = ([it.text] if it.text else []) + list(it.bullets)
        if head:
            paras.append(self.P(head, ts, title_color or colors.heading, bold=self.kit.bold, space_after=bs * 0.55 if body_texts else 0))
        for j, b in enumerate(body_texts):
            last = j == len(body_texts) - 1
            marker = "•" if (it.bullets and j >= (1 if it.text else 0)) else None
            paras.append(self.P(b, bs, colors.muted if head else colors.text, space_after=0 if last else bs * 0.4, marker=marker, marker_color=colors.accent))
        return paras

    def _card_content_h(self, it: SlideItem, inner_w: int, ts: float, bs: float, badge: Optional[str], colors: Colors, i: int) -> int:
        h = self.h(self._card_paras(it, ts, bs, colors), inner_w)
        if badge == "number":
            h += self._badge_size(ts) + int(self.kit.vgap * 0.7)
        elif badge == "index":
            h += _emu(self._index_size(ts) * self.kit.line) + int(self.kit.vgap * 0.35)
        elif badge == "figure" and it.number:
            fs = self._figure_size(it.number, inner_w)
            h += _emu(fs * max(1.1, self.kit.line)) + int(self.kit.vgap * 0.3)
        return h

    def _figure_size(self, value: str, width: int) -> float:
        k = self.kit
        for s in k.figure_sizes(k.figure_cap(4, True, self.strategy), k.h3):
            if self.figure_para(value, s, "000000", "000000")[1] <= _pt(width) * 0.88:
                return s
        return k.h3

    def _card_content(self, it: SlideItem, box: Bbox, ts: float, bs: float, badge: Optional[str], colors: Colors, i: int, title_color: str) -> None:
        k = self.kit
        y = box.y
        if badge == "number":
            d = self._badge_size(ts)
            fill = colors.accent
            num_color = "FFFFFF" if contrast_ratio("FFFFFF", fill) >= 3 else colors.text
            el = self.cv.ellipse(Bbox(x=box.x, y=y, w=d, h=d), fill)
            self._label_in(el, str(i + 1), self._badge_digit(), num_color)
            y += d + int(k.vgap * 0.7)
        elif badge == "index":
            idx = f"{i + 1:02d}"
            isz = self._index_size(ts)
            hh = _emu(isz * k.line)
            self.cv.text(Bbox(x=box.x, y=y, w=box.w, h=hh), [self.P(idx, isz, colors.accent, bold=k.bold)], name="Index")
            y += hh + int(k.vgap * 0.35)
        elif badge == "figure" and it.number:
            fs = self._figure_size(it.number, box.w)
            hh = _emu(fs * max(1.1, k.line))
            self.cv.text(Bbox(x=box.x, y=y, w=box.w, h=hh), [self.figure_para(it.number, fs, colors.figure, colors.muted)[0]], name="Figure", anchor="b")
            y += hh + int(k.vgap * 0.3)
        paras = self._card_paras(it, ts, bs, colors, title_color)
        if paras:
            hh = self.h(paras, box.w)
            self.cv.text(Bbox(x=box.x, y=y, w=box.w, h=max(hh, box.y2 - y)), paras, name="Card text")

    def _label_in(self, el: etree._Element, text: str, size: float, color: str) -> None:
        """Centered text inside a drawn shape (a badge)."""
        tx = etree.SubElement(el, q("p:txBody"))
        bp = etree.SubElement(tx, q("a:bodyPr"))
        for n in ("lIns", "tIns", "rIns", "bIns"):
            bp.set(n, "0")
        bp.set("anchor", "ctr")
        bp.set("wrap", "none")
        etree.SubElement(tx, q("a:lstStyle"))
        p = etree.SubElement(tx, q("a:p"))
        pPr = etree.SubElement(p, q("a:pPr"))
        pPr.set("algn", "ctr")
        r = etree.SubElement(p, q("a:r"))
        rPr = etree.SubElement(r, q("a:rPr"))
        rPr.set("lang", "ru-RU")
        rPr.set("sz", str(int(round(size * 100))))
        rPr.set("b", "1" if self.kit.bold else "0")
        sf = etree.SubElement(rPr, q("a:solidFill"))
        etree.SubElement(sf, q("a:srgbClr")).set("val", color.upper())
        if self.kit.font:
            etree.SubElement(rPr, q("a:latin")).set("typeface", self.kit.font)
            etree.SubElement(rPr, q("a:cs")).set("typeface", self.kit.font)
        etree.SubElement(r, q("a:t")).text = text

    # ---- KPI tiles ---------------------------------------------------------------------------------------------
    def kpis(self, area: Bbox, numbers: list[NumberCallout], extra: list[str]) -> None:
        k = self.kit
        n = len(numbers)
        extra_block = None
        if extra:
            # the running text goes under the tiles as a short note
            paras = [self.P(t, k.body, k.colors.text, space_after=k.body * 0.5) for t in extra]
            eh = self.h(paras, int(area.w * 0.8))
            extra_block = (paras, eh)
        avail = Bbox(x=area.x, y=area.y, w=area.w, h=area.h - ((extra_block[1] + k.vgap) if extra_block else 0))
        st = k.card
        use_cards = bool(st.fill or st.proto is not None) and self.strategy != "compact"
        colors = st.colors if use_cards else k.colors
        gap = k.gap
        hero_min = 1.5 * (k.head_size or k.h2)  # a figure smaller than this stops being the hero of the slide

        def layout(cols: int):
            cw = int((avail.w - gap * (cols - 1)) / cols)
            pad = int(min(cw * 0.1, 0.05 * k.H)) if use_cards else 0
            inner = cw - 2 * pad
            rows_ = math.ceil(n / cols)
            max_tile_ = int((avail.h - k.vgap * (rows_ - 1)) / rows_)
            lab = max(self.h([self.P(distinct_label(x.value, x.label, self.o.headline), k.body, colors.muted)], inner) for x in numbers)
            # one figure size for the row: the largest size under the cap for this many figures at which every
            # figure fits its tile on one line and the tiles fit the area
            fs = k.h3
            for s_ in k.figure_sizes(k.figure_cap(max(cols, 2) if cols < n else n, use_cards, self.strategy), k.h3):
                fs = s_
                # slack for the rendering font: a figure that breaks («12 40 / 0») is the worst thing a slide can show
                wide_ok = all(self.figure_para(x.value, s_, colors.figure, colors.muted)[1] <= _pt(inner) * (0.88 if use_cards else 0.8) for x in numbers)
                tall_ok = _emu(s_ * max(1.15, k.line)) + lab + int(k.vgap * 1.4) + 2 * pad <= max_tile_
                if wide_ok and tall_ok:
                    break
            return cw, pad, inner, fs

        cols = n if n <= 4 else math.ceil(n / 2)
        cw, pad, inner, fs = layout(cols)
        if n == 4 and fs < hero_min and avail.h > 0.55 * area.h:
            cols = 2  # four long figures read as a 2×2 block, not as four small numbers in a row
            cw, pad, inner, fs = layout(cols)
        rows = math.ceil(n / cols)
        label_size = k.body
        for ls in (k.lead, k.body):
            label_size = ls
            if max(para_lines(self.P(x.label, ls, colors.muted), _pt(inner)) for x in numbers) <= 3:
                break
        fig_h = _emu(fs * max(1.15, k.line))
        rule = 0 if use_cards else _emu(3)
        lab_h = max(self.h([self.P(distinct_label(x.value, x.label, self.o.headline), label_size, colors.muted)], inner) for x in numbers)
        figs = [self.figure_para(x.value, fs, colors.figure, colors.muted)[0] for x in numbers]
        # the ascender room over the digits is not part of the tile's padding: every figure of the row moves up by
        # the same amount (one size), each one left by its own first glyph's bearing
        tg = min(self._figure_optics(f, fig_h)[1] for f in figs)
        content_h = rule + (int(k.vgap * 0.6) if rule else 0) + fig_h - tg + int(k.vgap * 0.35) + lab_h
        tile_h = content_h + 2 * pad
        max_tile = int((avail.h - k.vgap * (rows - 1)) / rows)
        tile_h = min(tile_h, max_tile)
        block_h = rows * tile_h + (rows - 1) * k.vgap + ((extra_block[1] + k.vgap * 1.4) if extra_block else 0)
        y0 = self._place_v(area, int(block_h))
        for i, num in enumerate(numbers):
            r, cidx = divmod(i, cols)
            box = Bbox(x=avail.x + cidx * (cw + gap), y=y0 + r * (tile_h + k.vgap), w=cw, h=tile_h)
            y = box.y + pad
            if use_cards:
                self.cv.card(box, st)
            else:
                self.cv.rect(Bbox(x=box.x, y=y, w=min(_emu(k.hpt * 0.09), inner), h=rule), colors.accent, name="Rule")
                y += rule + int(k.vgap * 0.6)
            lsb = self._figure_optics(figs[i], fig_h)[0]
            self.cv.text(Bbox(x=box.x + pad - lsb, y=y - tg, w=inner + lsb, h=fig_h), [figs[i]], anchor="b", name="Figure")
            y += fig_h - tg + int(k.vgap * 0.35)
            self.cv.text(Bbox(x=box.x + pad, y=y, w=inner, h=max(lab_h, box.y2 - pad - y)), [self.P(distinct_label(num.value, num.label, self.o.headline), label_size, colors.muted)], name="Label")
        if extra_block:
            paras, eh = extra_block
            ey = y0 + rows * tile_h + (rows - 1) * k.vgap + int(k.vgap * 1.4)
            self.cv.text(Bbox(x=area.x, y=ey, w=int(area.w * 0.8), h=eh), paras, name="Note")

    def big_number(self, area: Bbox, num: NumberCallout, extra: list[str], others: list[NumberCallout]) -> None:
        k = self.kit
        colors = k.colors
        has_side = bool(extra or others)
        left_w = int(area.w * (0.46 if has_side else 0.9))
        fs = k.display
        for s in k.figure_sizes(k.figure_cap(1, False, self.strategy), k.display):
            fs = s
            if self.figure_para(num.value, s, colors.figure, colors.muted)[1] <= _pt(left_w) * 0.88:
                break
        fig_h = _emu(fs * max(1.12, k.line))
        fig = self.figure_para(num.value, fs, colors.figure, colors.muted)[0]
        lsb, tg = self._figure_optics(fig, fig_h)
        label = [self.P(distinct_label(num.value, num.label, self.o.headline), k.lead, colors.text)]
        lab_h = self.h(label, int(left_w * 0.92))
        left_h = fig_h - tg + int(k.vgap * 0.4) + lab_h
        right_paras: list[Para] = []
        rw = area.w - left_w - k.gap * 2
        for o in others:
            right_paras.append(self.P(o.value, k.snap(k.h3 * 1.4, k.h3, k.display), colors.accent, bold=k.bold, space_after=2))
            right_paras.append(self.P(o.label, k.body, colors.muted, space_after=k.body * 1.1))
        size = k.lead if sum(len(t) for t in extra) <= 260 else k.body
        for t in extra:
            right_paras.append(self.P(t, size, colors.text, space_after=size * 0.6, marker="•" if len(extra) > 1 else None, marker_color=colors.accent))
        right_h = self.h(right_paras, rw) if right_paras else 0
        block_h = max(left_h, right_h)
        y0 = self._place_v(area, block_h)
        self.cv.text(Bbox(x=area.x - lsb, y=y0 - tg, w=left_w + lsb, h=fig_h), [fig], anchor="b", name="Figure")
        self.cv.text(Bbox(x=area.x, y=y0 + fig_h - tg + int(k.vgap * 0.4), w=int(left_w * 0.92), h=lab_h), label, name="Label")
        if right_paras:
            x = area.x + left_w + k.gap * 2
            # a hairline divides the figure from its explanation
            self.cv.line(x - k.gap, y0, x - k.gap, y0 + max(left_h, right_h), colors.divider, 1.0)
            self.cv.text(Bbox(x=x, y=y0 + (max(0, (left_h - right_h) // 2) if right_h < left_h else 0), w=rw, h=right_h), right_paras, name="Explanation")

    # ---- lists ---------------------------------------------------------------------------------------------------
    def bullets(self, area: Bbox, texts: list[str]) -> None:
        k = self.kit
        texts = [t for t in texts if t and t.strip()]
        if not texts:
            self.warnings.append("empty slide content")
            return
        n = len(texts)
        total = sum(len(t) for t in texts)
        if self.strategy == "visual" and 2 <= n <= 6 and max(len(t) for t in texts) <= 140 and area.w >= 0.6 * k.W:
            # a visual variant turns theses into cards: each thesis its own block
            self.cards(area, [SlideItem(title=t) for t in texts], badge="index")
            return
        two_cols = n >= 5 and total > 360 or n >= 7
        col_gap = k.gap * 2
        cols = 2 if two_cols else 1
        col_w = int((area.w - col_gap * (cols - 1)) / cols)
        text_w = col_w if cols == 2 else min(col_w, int(area.w * 0.8))
        per_col = math.ceil(n / cols)
        # the largest size at which the list fits; rows separated by hairlines
        sizes = [k.h2, k.lead, k.body, k.small] if n <= 4 and total <= 260 else ([k.lead, k.body, k.small] if total <= 700 else [k.body, k.small])
        for size in sizes:
            marker_w = _emu(size * 1.6)
            row_pad = int(max(size * 0.75, 6) * EMU_PER_PT)
            heights = [self.h([self.P(t, size, k.colors.text)], text_w - marker_w) for t in texts]
            col_h = max(sum(heights[c * per_col : (c + 1) * per_col]) + (min(per_col, n - c * per_col) - 1) * 2 * row_pad for c in range(cols))
            if col_h <= area.h:
                break
        # the rows breathe: the gap between them grows (up to 2.5 lines) until the list fills about 60% of the band
        rows_n = max(min(per_col, n), 1)
        if rows_n > 1 and col_h < 0.6 * area.h:
            extra = min(int((0.6 * area.h - col_h) / (rows_n - 1) / 2), _emu(size * k.line * 1.25) - row_pad)
            if extra > 0:
                row_pad += extra
                col_h += extra * 2 * (rows_n - 1)
        block_h = col_h
        y0 = self._place_v(area, block_h, fill_top=True)
        for c in range(cols):
            x = area.x + c * (col_w + col_gap)
            y = y0
            chunk = list(enumerate(texts))[c * per_col : (c + 1) * per_col]
            for j, (i, t) in enumerate(chunk):
                hh = heights[i]
                mk = _emu(size * 0.38)
                # a round accent marker on the first line's x-height (one bullet glyph for the deck)
                self.cv.ellipse(Bbox(x=x, y=y + _emu(size * k.line * 0.5) - mk // 2, w=mk, h=mk), k.colors.accent, name="Marker")
                self.cv.text(Bbox(x=x + marker_w, y=y, w=text_w - marker_w, h=hh), [self.P(t, size, k.colors.text)], name="Item")
                y += hh
                if j < len(chunk) - 1:
                    self.cv.line(x + marker_w, y + row_pad, x + text_w, y + row_pad, k.colors.divider, 0.75)
                    y += 2 * row_pad

    def paragraphs(self, area: Bbox, texts: list[str]) -> None:
        k = self.kit
        total = sum(len(t) for t in texts)
        width = min(area.w, int(area.w * 0.78))
        for size in (k.lead, k.body, k.small) if total <= 500 else (k.body, k.small):
            paras = [self.P(t, size, k.colors.text, space_after=size * 0.8) for t in texts]
            hh = self.h(paras, width)
            if hh <= area.h:
                break
        self.cv.text(Bbox(x=area.x, y=self._place_v(area, hh, fill_top=True), w=width, h=hh), paras, name="Text")

    def statement(self, area: Bbox, text: str) -> None:
        """One message — an ask, a conclusion: large type, figures in the accent colour, an accent bar or panel."""
        k = self.kit
        panel = self.strategy == "visual" and bool(k.card.fill or k.card.proto is not None)
        colors = k.card.colors if panel else k.colors
        width = int(area.w * (0.9 if panel else (0.86 if area.w > 0.6 * k.W else 1.0)))
        pad = int(0.06 * k.H) if panel else 0
        bar = 0 if panel else _emu(max(k.hpt * 0.011, 4))
        inset = bar + int(k.gap * 1.2) if bar else 0
        top = k.statement
        if k.head_size:
            # one headline per slide: the statement is larger than running text and a step below the heading — a
            # callout set above the heading turns the hierarchy upside down
            top = min(top, self._under_heading())
        size = top
        for s in k.steps_down(top, k.body):
            size = s
            paras = [Para(highlight_runs(text, s, colors.text, colors.accent if s >= 18 else colors.accent_text, bold=False, accent_bold=k.bold, font=k.font), space_after=0)]
            hh = self.h(paras, width - inset - 2 * pad)
            if hh + 2 * pad <= area.h * 0.8 and (para_lines(paras[0], _pt(width - inset - 2 * pad)) <= 5 or s <= k.lead):
                break
        block_h = hh + 2 * pad
        y0 = self._place_v(area, block_h)
        if panel:
            self.cv.card(Bbox(x=area.x, y=y0, w=width, h=block_h), k.card)
        elif bar:
            self.cv.rect(Bbox(x=area.x, y=y0 + _emu(size * 0.15), w=bar, h=max(hh - _emu(size * 0.3), bar)), k.colors.accent, name="Accent bar")
        self.cv.text(Bbox(x=area.x + inset + pad, y=y0 + pad, w=width - inset - 2 * pad, h=hh), paras, name="Statement", anchor="ctr" if panel else "t")

    def quote(self, area: Bbox, text: str, author: Optional[str]) -> None:
        """A large accent quotation mark hanging to the left of the words (set at statement size, without their own
        quotes), the author under them."""
        k = self.kit
        mark_size = k.figure_sizes(0.16 * k.hpt, k.display)[0]
        mark_w = _emu(mark_size * 0.75)
        width = int(area.w * 0.82) - mark_w
        words = text.strip().strip("«»\"“”„")
        top = min(k.statement, self._under_heading()) if k.head_size else k.statement
        size = top
        for s_ in k.steps_down(top, k.body):
            size = s_
            body = [self.P(words, s_, k.colors.text)]
            hh = self.h(body, width)
            if hh <= area.h * 0.7 and para_lines(body[0], _pt(width)) <= 5:
                break
        auth = [self.P(author, k.lead, k.colors.muted)] if author else []
        ah = self.h(auth, width) if auth else 0
        block = hh + (int(k.vgap) + ah if auth else 0)
        y = self._place_v(area, block)
        # an opening quote that hangs at the cap height of the first line (a guillemet sits on the x-height and
        # reads as a small bracket at any size)
        self.cv.text(Bbox(x=area.x, y=y - _emu(mark_size * 0.08), w=mark_w, h=_emu(mark_size * k.line)), [self.P("“", mark_size, k.colors.accent, bold=k.bold)], name="Quote mark")
        x = area.x + mark_w
        self.cv.text(Bbox(x=x, y=y, w=width, h=hh), body, name="Quote")
        if auth:
            self.cv.rect(Bbox(x=x, y=y + hh + int(k.vgap * 0.9), w=_emu(k.hpt * 0.06), h=_emu(2)), k.colors.accent, name="Rule")
            self.cv.text(Bbox(x=x, y=y + hh + int(k.vgap * 1.3), w=width, h=ah), auth, name="Author")

    # ---- process / agenda / columns -------------------------------------------------------------------------------
    def process(self, area: Bbox, items: list[SlideItem]) -> None:
        k = self.kit
        n = len(items)
        if all(not i.text and not i.bullets for i in items) and max(len(i.title.split()) for i in items) > 6:
            items = [SlideItem(title="", text=i.title) for i in items]  # steps told as sentences read as text
        if n > 6:
            self.cards(area, items, badge="number")
            return
        gap = k.gap
        cw = int((area.w - gap * (n - 1)) / n)
        colors = k.colors
        st = k.card
        in_cards = self.strategy == "visual" and bool(st.fill or st.proto is not None)
        pad = int(min(cw * 0.09, 0.045 * k.H)) if in_cards else 0
        inner = cw - 2 * pad
        tcolors = st.colors if in_cards else colors
        for ts, bs in ((k.h2, k.lead), (k.lead, k.lead), (k.lead, k.body), (k.h3, k.body), (k.h3, k.small), (k.body, k.small)):
            if not self.fits_width([i.title for i in items], ts, k.bold, inner):
                continue
            text_h = max(self.h(self._card_paras(it, ts, bs, tcolors), inner) for it in items)
            d = self._badge_size(ts)
            total = d + int(k.vgap * 0.9) + text_h + 2 * pad
            t_lines = max(para_lines(self.P(i.title, ts, tcolors.text, bold=k.bold), _pt(inner)) for i in items)
            titled = any(i.text or i.bullets for i in items)
            if total <= area.h and t_lines <= (2 if titled else 4):
                break
        block_h = total
        y0 = self._place_v(area, block_h)
        # the axis runs through the badges' centres, behind them
        cy = y0 + d // 2
        first_cx = area.x + (pad if in_cards else 0) + d // 2
        last_cx = area.x + (n - 1) * (cw + gap) + (pad if in_cards else 0) + d // 2
        if n > 1 and not in_cards:
            self.cv.line(first_cx, cy, last_cx, cy, colors.accent, 1.5, name="Axis")
        for i, it in enumerate(items):
            x = area.x + i * (cw + gap)
            by = y0
            if in_cards:
                # the step is a card; its badge sits inside it, a padding from the corner (never on the edge)
                self.cv.card(Bbox(x=x, y=y0, w=cw, h=block_h), st)
                by = y0 + pad
            bx = x + pad
            el = self.cv.ellipse(Bbox(x=bx, y=by, w=d, h=d), colors.accent)
            self._label_in(el, str(i + 1), self._badge_digit(), "FFFFFF" if contrast_ratio("FFFFFF", colors.accent) >= 3 else colors.text)
            ty = by + d + int(k.vgap * 0.9)
            paras = self._card_paras(it, ts, bs, tcolors)
            self.cv.text(Bbox(x=bx, y=ty, w=inner, h=max(text_h, y0 + block_h - pad - ty)), paras, name="Step")

    def agenda(self, area: Bbox, items: list[SlideItem]) -> None:
        k = self.kit
        n = len(items)
        cols = 1 if n <= 4 else 2
        per = math.ceil(n / cols)
        col_gap = k.gap * 3
        col_w = int((area.w - col_gap * (cols - 1)) / cols)
        for ts in (k.statement if n <= 3 else k.h2, k.h2, k.lead, k.h3, k.body):
            idx_w = _emu(ts * 2.4)
            heights = [self.h([self.P(it.title, ts, k.colors.text)], col_w - idx_w) for it in items]
            row_gap = _emu(ts * 0.9)
            col_h = max(sum(heights[c * per : (c + 1) * per]) + (min(per, n - c * per) - 1) * 2 * row_gap for c in range(cols))
            if col_h <= area.h:
                break
        y0 = self._place_v(area, col_h)
        for c in range(cols):
            x = area.x + c * (col_w + col_gap)
            y = y0
            chunk = list(range(c * per, min((c + 1) * per, n)))
            for j, i in enumerate(chunk):
                hh = heights[i]
                self.cv.text(Bbox(x=x, y=y, w=idx_w, h=hh), [self.P(f"{i + 1:02d}", ts, k.colors.accent, bold=k.bold)], name="Index")
                self.cv.text(Bbox(x=x + idx_w, y=y, w=col_w - idx_w, h=hh), [self.P(items[i].title, ts, k.colors.text)], name="Agenda item")
                y += hh
                if j < len(chunk) - 1:
                    self.cv.line(x, y + row_gap, x + col_w, y + row_gap, k.colors.divider, 0.75)
                    y += 2 * row_gap

    def columns(self, area: Bbox, items: list[SlideItem]) -> None:
        """Two or three columns side by side (options, before/after, pros/cons): the first column carries the accent."""
        k = self.kit
        n = min(len(items), 3)
        items = items[:n]
        gap = k.gap
        cw = int((area.w - gap * (n - 1)) / n)
        st = k.card
        pad = int(min(cw * 0.07, 0.05 * k.H))
        inner = cw - 2 * pad
        rule_h = _emu(3) + int(k.vgap * 0.6)
        for ts, bs in ((k.h2, k.lead), (k.lead, k.lead), (k.lead, k.body), (k.h3, k.body), (k.h3, k.small), (k.body, k.small)):
            heights = [self.h(self._card_paras(it, ts, bs, st.colors), inner) for it in items]
            lines = max(sum(para_lines(p, _pt(inner)) for p in self._card_paras(it, ts, bs, st.colors)) for it in items)
            if max(heights) + 2 * pad + rule_h <= area.h * 0.9 and lines <= 11:
                break
        # titles share one band (as tall as the longest title), so every body starts on one line across the columns
        heads = [self._card_paras(SlideItem(title=it.title), ts, bs, st.colors) if it.title else [] for it in items]
        bodies = [self._card_paras(SlideItem(title="", text=it.text, bullets=it.bullets), ts, bs, st.colors) for it in items]
        head_h = max((self.h(hp, inner) for hp in heads if hp), default=0)
        head_gap = int(bs * 0.55 * EMU_PER_PT) if head_h else 0
        body_h = max((self.h(bp, inner) for bp in bodies if bp), default=0)
        # the columns are as tall as their content, never a tall empty frame
        ch = min(rule_h + head_h + head_gap + body_h + 2 * pad, area.h)
        y0 = self._place_v(area, ch, fill_top=True)
        for i, it in enumerate(items):
            box = Bbox(x=area.x + i * (cw + gap), y=y0, w=cw, h=ch)
            if st.fill or st.line or st.proto is not None:
                self.cv.card(box, st)
            self.cv.rect(Bbox(x=box.x + pad, y=box.y + pad, w=_emu(k.hpt * 0.07), h=_emu(3)), st.colors.accent, name="Rule")
            y = box.y + pad + rule_h
            if heads[i]:
                self.cv.text(Bbox(x=box.x + pad, y=y, w=inner, h=head_h), heads[i], name="Column title")
            y += head_h + head_gap
            if bodies[i]:
                self.cv.text(Bbox(x=box.x + pad, y=y, w=inner, h=max(body_h, box.y2 - pad - y)), bodies[i], name="Column")

    # ---- data ----------------------------------------------------------------------------------------------------
    def table(self, area: Bbox, table: TableData) -> None:
        """A native table measured for its content (tables.measure_table): one size, columns by content, rows that
        grow to fill about half the area; a note or the caption under it."""
        from verstka.rendering.tables import measure_table, table_style_for_ground, template_bold

        k = self.kit
        style = self.manifest.components.table_style
        n_cols = max(len(table.columns), 1)
        n_rows = len(table.rows) + 1
        width = area.w if n_cols >= 3 else int(area.w * 0.72)
        deltas = table_deltas(table) if self.strategy == "visual" and area.w * 0.36 >= 0.3 * k.W else []
        if deltas:
            width = int(area.w * 0.64)  # the table and, beside it, what changed most
        floor = 0.022 * k.hpt
        # a table reads at body size; dense tables step down to the small size. A small one (a few rows, a few
        # columns) set at body size is a thin strip over an empty slide: it may take the lead size when nothing wraps
        header_bold = template_bold(k.manifest.tokens.typography)

        def sizes_for(t: TableData) -> list[float]:
            small_table = len(t.rows) + 1 <= 5 and len(t.columns) <= 4
            lead = [k.lead] if small_table and k.lead > k.body and (not k.head_size or k.lead <= 0.7 * k.head_size) else []
            return [s for s in (*lead, k.body, k.small) if s >= floor] or [k.small]

        def measure(t: TableData, sizes: list[float]):
            return measure_table(
                t, width, k.font, sizes, k.line,
                max_h_emu=area.h, fill_h_emu=int(0.62 * area.h), min_row_h_emu=int(0.065 * k.H), max_row_h_emu=int(0.10 * k.H),
                header_bold=header_bold,
            )

        # one table size for the deck: every table is set at the size the densest one allows (two tables of one deck
        # at 15 and 11 pt read as two designers)
        cache = self.slide.part.package.__dict__.setdefault("_verstka_table_size", {})  # one deck, one build
        key = (width, area.h)
        if key not in cache:
            tables = [s.content.table for s in self.outline.slides if s.content.table is not None and s.content.table.columns]
            cache[key] = min((measure(t, sizes_for(t))[0] for t in tables), default=None)
        cap = cache[key]
        sizes = sizes_for(table)
        if cap:
            sizes = [s for s in sizes if s <= cap + 0.05] or [min(sizes)]
        size, widths, heights = measure(table, sizes)
        spec = table_style_for_ground(style, ground_hex=k.colors.ground, text_hex=k.colors.text, accent_hex=k.colors.accent, divider_hex=k.colors.divider)
        total_h = sum(heights)
        add_table(
            self.slide, Bbox(x=area.x, y=area.y, w=sum(widths), h=total_h), table, spec, k.manifest.tokens.typography,
            font_family=k.font, col_widths=widths, row_heights=heights, size_pt=size,
            accent_hex=k.colors.accent, muted_hex=k.colors.muted, ground_hex=k.colors.ground, header_bold=header_bold,
            accent_text_hex=k.colors.accent_text,
        )
        if table.caption and total_h + k.vgap + _emu(k.small * 2) <= area.h:
            self.cv.text(Bbox(x=area.x, y=area.y + total_h + int(k.vgap * 0.6), w=width, h=_emu(k.small * 1.6)), [self.P(table.caption, k.small, k.colors.muted)], name="Caption")
        if deltas:
            x = area.x + width + k.gap * 2
            w = area.x + area.w - x
            paras: list[Para] = []
            for value, label, span in deltas[:2]:
                fs = k.display
                for s_ in k.figure_sizes(k.figure_cap(2, False, self.strategy), k.h3):
                    fs = s_
                    if self.figure_para(value, s_, k.colors.figure, k.colors.muted)[1] <= _pt(w) * 0.8:
                        break
                paras.append(Para(self.figure_para(value, fs, k.colors.figure, k.colors.muted)[0].runs, space_after=2))
                paras.append(self.P(label, k.body, k.colors.text, space_after=1))
                paras.append(self.P(span, k.small, k.colors.muted, space_after=k.body * 1.3))
            hh = self.h(paras, w)
            self.cv.line(x - k.gap, area.y, x - k.gap, area.y + total_h, k.colors.divider, 1.0)  # as tall as the table
            self.cv.text(Bbox(x=x, y=area.y, w=w, h=min(hh, area.h)), paras, name="Takeaway")

    def chart(self, area: Bbox) -> None:
        k = self.kit
        c = self.o.content
        spec = c.chart
        side_texts = [t for t in (list(c.bullets) + list(c.paragraphs)) if t.strip()]
        takeaway = _series_takeaway(spec, self.outline, self.o.headline)
        show_side = bool(side_texts) or (takeaway is not None and self.strategy != "structured")
        from verstka.rendering.charts import effective_chart_type, unit_caption

        chart_w = int(area.w * (0.64 if show_side else 1.0))
        bars = effective_chart_type(spec, self.outline) == "bar"
        chart_h = int(area.h * 0.92) if (show_side or bars) else min(int(area.h * 0.82), int(area.w * 0.42))
        y = area.y
        caption = unit_caption(spec, self.outline)
        cap_h = 0
        if caption:
            # the full unit once, above the chart; the labels carry its short form
            cap_h = _emu(k.small * k.line) + _emu(2)
            y += cap_h + int(k.vgap * 0.3)
            chart_h = min(chart_h, area.y2 - y)
        box = Bbox(x=area.x, y=y, w=chart_w, h=chart_h)
        style = self.manifest.components.chart_style
        style = style.model_copy(update={"font_size_pt": max(style.font_size_pt or 0, k.small), "font_family": k.font or style.font_family})
        tree = self.slide.shapes._spTree
        n0 = len(tree)
        try:
            add_chart(self.slide, box, spec, self.outline, style, k.manifest.tokens.typography, text_hex=k.colors.text, neutral_hex=k.colors.divider, ground_hex=k.colors.ground)
        except Exception as e:  # noqa: BLE001
            # no chart, no unit caption over an empty frame: a half-built chart goes, the slide shows what else it has
            for el in list(tree)[n0:]:
                for ref in el.iter("{http://schemas.openxmlformats.org/drawingml/2006/chart}chart"):
                    rid = ref.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                    if rid:
                        try:
                            self.slide.part.drop_rel(rid)
                        except KeyError:
                            pass
                tree.remove(el)
            self.warnings.append(f"chart failed: {str(e)[:120]}; shown as {self._chart_fallback(area)}")
            return
        if caption:
            self.cv.text(Bbox(x=area.x, y=area.y, w=chart_w, h=cap_h), [self.P(caption, k.small, k.colors.muted)], name="Unit")
        if not show_side:
            return
        x = area.x + chart_w + k.gap * 2
        w = area.x + area.w - x
        paras: list[Para] = []
        if takeaway is not None:
            value, label = takeaway
            fs = k.display
            for s in k.steps_down(k.display, k.h3):
                fs = s
                if text_width_pt(value, k.font, s, k.bold) <= _pt(w) * 0.95:
                    break
            paras.append(self.P(value, fs, k.colors.accent, bold=k.bold, space_after=4))
            paras.append(self.P(label, k.body, k.colors.muted, space_after=k.body * 1.4))
        for t in side_texts:
            paras.append(self.P(t, k.body if len(t) > 90 else k.lead, k.colors.text, space_after=k.body * 0.7, marker="•" if len(side_texts) > 1 else None, marker_color=k.colors.accent))
        hh = self.h(paras, w)
        y = area.y + max(0, int((area.h - hh) * 0.35))
        # a hairline as tall as what it sets apart
        self.cv.line(x - k.gap, y, x - k.gap, y + min(hh, area.h), k.colors.divider, 1.0)
        self.cv.text(Bbox(x=x, y=y, w=w, h=min(hh, area.h)), paras, name="Takeaway")


    def _chart_fallback(self, area: Bbox) -> str:
        """A chart that could not be drawn gives its area to the slide's figures (its numbers, else the facts the chart
        names) as tiles or one big number, else to its text or its cards. Returns what was set, for the warning."""
        from verstka.rendering.fallbacks import fact_numbers

        c = self.o.content
        numbers = list(c.numbers) or fact_numbers(self.o, self.outline, chart_only=True)
        running = [t for t in self._running() if t.strip()]
        items = [it for it in (c.items or c.columns)]
        if len(numbers) == 1:
            self.big_number(area, numbers[0], extra=running, others=[])
            return "one big number"
        if numbers:
            self.kpis(area, numbers[:4], extra=running)
            return f"{len(numbers[:4])} KPI tiles"
        if running:
            self.bullets(area, running)
            return "bullets"
        if items:
            self.cards(area, items)
            return "cards"
        self.warnings.append("empty slide content")
        return "nothing"


# ---------------------------------------------------------------------------------------------- data helpers


def _num(cell: str) -> Optional[float]:
    m = re.match(r"^\s*[+\-−]?\d[\d\s\u00a0]*(?:[.,]\d+)?", cell or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace("\u00a0", "").replace(" ", "").replace(",", ".").replace("−", "-"))
    except ValueError:
        return None


def table_deltas(table: TableData) -> list[tuple[str, str, str]]:
    """What changed most in a before/after table (a label column and exactly two numeric columns): the change of
    each row, largest first — in percentage points for percentages, as a relative change otherwise. Computed from
    the cells, never invented."""
    if len(table.columns) != 3 or not 2 <= len(table.rows) <= 5:
        return []
    out = []
    for row in table.rows:
        if len(row) < 3:
            return []
        a, b = _num(row[1]), _num(row[2])
        if a is None or b is None:
            return []
        if "%" in row[1] and "%" in row[2]:
            d = b - a
            if abs(d) < 0.5:
                continue
            value = (f"+{d:g}" if d > 0 else f"−{abs(d):g}").replace(".", ",") + " п.п."
            size = abs(d) / 100
        elif a:
            r = (b - a) / abs(a)
            if abs(r) < 0.05:
                continue
            value = (f"+{r * 100:.0f}%" if r > 0 else f"−{abs(r) * 100:.0f}%")
            size = abs(r)
        else:
            continue
        out.append((size, value, row[0].strip(), f"{row[1].strip()} → {row[2].strip()}"))
    out.sort(key=lambda t: -t[0])
    return [(v, lab, span) for _, v, lab, span in out]


_MONTHS = ("январ", "феврал", "март", "апрел", "май", "мая", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")


def _in_sentence(cat: str) -> str:
    """A category inside a sentence: month names are lower case in Russian («рост за период июль → сентябрь»)."""
    c = cat.strip()
    return c[:1].lower() + c[1:] if c.lower().startswith(_MONTHS) else c


def _series_takeaway(spec, outline: DeckOutline, headline: str = "") -> Optional[tuple[str, str]]:
    """The figure a reader takes from a series: its growth (last/first) or its last value. Computed, never invented.
    When the heading already names the multiple («рост в 5 раз»), the panel gives the last value instead of a
    second, differently rounded multiple."""
    from verstka.rendering.charts import resolve_series

    try:
        series = resolve_series(spec, outline)
    except Exception:  # noqa: BLE001
        return None
    if not series or len(series) > 1:
        return None
    s = series[0]
    vals = list(s.values)
    if len(vals) < 2 or any(v is None for v in vals):
        return None
    first, last = vals[0], vals[-1]
    span = f"{_in_sentence(s.categories[0])} → {_in_sentence(s.categories[-1])}" if s.categories else ""
    says_multiple = bool(re.search(r"\bв\s+\d+([.,]\d+)?\s*раз|[×x]\s?\d", headline or "", re.I))
    if first > 0 and last > 0 and not says_multiple:
        ratio = last / first
        if ratio >= 1.5:
            txt = f"×{ratio:.1f}".replace(".", ",").replace(",0", "")
            return txt, f"рост за период {span}".strip()
        if ratio <= 0.67:
            pct = int(round((1 - ratio) * 100))
            return f"−{pct}%", f"снижение за период {span}".strip()
    # the change in the series' own unit — never the last value, which the highlighted bar already shows
    delta = last - first
    if not delta:
        return None
    unit = f" {s.unit}" if s.unit and s.unit not in ("%",) else (s.unit or "")
    mag = abs(delta)
    v = f"{mag:,.0f}".replace(",", " ") if mag >= 100 else f"{mag:g}".replace(".", ",")
    if re.sub(r"\s", "", v) in re.sub(r"\s", "", headline or ""):
        return None  # the heading already says it
    return f"{'+' if delta > 0 else '−'}{v}{unit}", f"{'прирост' if delta > 0 else 'снижение'} за период {span}".strip()
