"""Write paragraphs into an existing shape while keeping its run/paragraph formatting."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import NS, q
from verstka.ru import typeset_figures

_RUN_TAGS = {"r", "br", "fld"}


@dataclass
class ParagraphSpec:
    text: str
    bullet: Optional[bool] = None
    level: int = 0
    bold: Optional[bool] = None
    size_pt: Optional[float] = None
    color_hex: Optional[str] = None


def _txBody(sp_el: etree._Element) -> Optional[etree._Element]:
    tag = etree.QName(sp_el).localname
    if tag == "sp":
        return sp_el.find(q("p:txBody"))
    return None


def _has_bullet(p: etree._Element) -> bool:
    pPr = p.find(q("a:pPr"))
    if pPr is None:
        return False
    return pPr.find(q("a:buChar")) is not None or pPr.find(q("a:buAutoNum")) is not None or pPr.find(q("a:buBlip")) is not None


def _strip_runs(p: etree._Element) -> None:
    for child in list(p):
        if etree.QName(child).localname in _RUN_TAGS:
            p.remove(child)


def _first_rpr(p: etree._Element) -> Optional[etree._Element]:
    for r in p.findall(q("a:r")):
        rPr = r.find(q("a:rPr"))
        if rPr is not None:
            return rPr
    end = p.find(q("a:endParaRPr"))
    return end


# child order of a:pPr (CT_TextParagraphProperties): PowerPoint repairs files that break it
_PPR_ORDER = ["lnSpc", "spcBef", "spcAft", "buClrTx", "buClr", "buSzTx", "buSzPct", "buSzPts", "buFontTx", "buFont", "buNone", "buAutoNum", "buChar", "buBlip", "tabLst", "defRPr", "extLst"]


def insert_ordered(parent: etree._Element, child: etree._Element, order: list[str]) -> etree._Element:
    """Insert `child` before the first existing child that the schema orders after it."""
    rank = order.index(etree.QName(child).localname)
    for i, c in enumerate(parent):
        name = etree.QName(c).localname
        if name in order and order.index(name) > rank:
            parent.insert(i, child)
            return child
    parent.append(child)
    return child


def _set_bullet(pPr: etree._Element, on: bool, size_pt: Optional[float] = None) -> None:
    had_marker = any(pPr.find(q(t)) is not None for t in ("a:buChar", "a:buAutoNum", "a:buBlip"))
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum", "a:buBlip"):
        for el in pPr.findall(q(tag)):
            pPr.remove(el)
    if on:
        bu = etree.Element(q("a:buChar"))
        bu.set("char", "•")
        insert_ordered(pPr, bu, _PPR_ORDER)
        if not had_marker and pPr.get("indent") is None:
            # the source paragraph was plain text: give the marker a hanging indent of about one em
            hang = int(max(size_pt or 14.0, 8.0) * 1.1 * 12700)
            pPr.set("marL", str(int(pPr.get("marL") or 0) + hang))
            pPr.set("indent", str(-hang))
    else:
        insert_ordered(pPr, etree.Element(q("a:buNone")), _PPR_ORDER)


def _rpr_size(rPr: Optional[etree._Element]) -> Optional[float]:
    try:
        return int(rPr.get("sz")) / 100.0 if rPr is not None and rPr.get("sz") else None
    except ValueError:
        return None


def fill_text(sp_el: etree._Element, paragraphs: list[ParagraphSpec], size_pt: Optional[float] = None, keep_bullets: bool = True, *, reset_indent: bool = False, neutral_runs: bool = False) -> bool:
    """Replace the text of a shape. Returns False when the element has no text body.

    `reset_indent`: every written paragraph without a marker starts at the box's edge (`marL="0" indent="0"`) — for a
    heading written into a moved or widened sample shape whose own indent belonged to another design.
    `neutral_runs`: every written run switches off inherited capitals, letter-spacing and baseline shift
    (`cap="none" spc="0" baseline="0"`): a master body style with `cap="all" spc="500"` must not respace the text."""
    txBody = _txBody(sp_el)
    if txBody is None:
        return False
    ps = txBody.findall(q("a:p"))
    if not ps:
        ps = [etree.SubElement(txBody, q("a:p"))]
    template_p = next((p for p in ps if p.find(q("a:r")) is not None), ps[0])
    bullet_p = next((p for p in ps if _has_bullet(p)), None)
    template_rPr = _first_rpr(template_p)
    if template_rPr is None:
        template_rPr = etree.Element(q("a:rPr"))
        template_rPr.set("lang", "ru-RU")
    template_rPr = copy.deepcopy(template_rPr)
    template_rPr.tag = q("a:rPr")
    # the sample's hyperlink (and the underline that came with it) must not turn our text into someone else's link
    links = template_rPr.findall(q("a:hlinkClick")) + template_rPr.findall(q("a:hlinkMouseOver"))
    for h in links:
        template_rPr.remove(h)
    if links and template_rPr.get("u"):
        del template_rPr.attrib["u"]
    for p in ps:
        txBody.remove(p)
    # stale autofit scaling would shrink the new text unpredictably
    bodyPr = txBody.find(q("a:bodyPr"))
    if bodyPr is not None:
        na = bodyPr.find(q("a:normAutofit"))
        if na is not None:
            for a in ("fontScale", "lnSpcReduction"):
                if a in na.attrib:
                    del na.attrib[a]
    for spec in paragraphs:
        use_bullet_template = keep_bullets and spec.bullet and bullet_p is not None
        p = copy.deepcopy(bullet_p if use_bullet_template else template_p)
        _strip_runs(p)
        pPr = p.find(q("a:pPr"))
        if spec.bullet is not None:
            if pPr is None:
                pPr = etree.Element(q("a:pPr"))
                p.insert(0, pPr)
            if spec.bullet and not _has_bullet(p):
                _set_bullet(pPr, True, spec.size_pt or size_pt or _rpr_size(template_rPr))
            elif not spec.bullet and _has_bullet(p):
                _set_bullet(pPr, False)
                for attr in ("marL", "indent"):  # a plain line under a bulleted list starts at the markers' edge
                    pPr.attrib.pop(attr, None)
            elif not spec.bullet and pPr.find(q("a:buNone")) is None:
                # the marker may come from the layout/master list style (a body placeholder): switch it off explicitly
                _set_bullet(pPr, False)
                if pPr.get("marL") is None and pPr.get("indent") is None:
                    pPr.set("marL", "0")  # the inherited hanging indent belonged to the marker
                    pPr.set("indent", "0")
        if spec.level:
            if pPr is None:
                pPr = etree.Element(q("a:pPr"))
                p.insert(0, pPr)
            pPr.set("lvl", str(spec.level))
        if reset_indent and not _has_bullet(p):
            if pPr is None:
                pPr = etree.Element(q("a:pPr"))
                p.insert(0, pPr)
            pPr.set("marL", "0")
            pPr.set("indent", "0")
        r = etree.Element(q("a:r"))
        rPr = copy.deepcopy(template_rPr)
        if neutral_runs:
            neutralize_rpr(rPr)
        sz = spec.size_pt or size_pt
        if sz:
            rPr.set("sz", str(int(round(sz * 100))))
        if spec.bold is not None:
            rPr.set("b", "1" if spec.bold else "0")
        if spec.color_hex:
            for tag in ("a:solidFill", "a:gradFill", "a:noFill"):
                for el in rPr.findall(q(tag)):
                    rPr.remove(el)
            sf = etree.Element(q("a:solidFill"))
            clr = etree.SubElement(sf, q("a:srgbClr"))
            clr.set("val", spec.color_hex.upper())
            # solidFill must precede latin/ea/cs; insert at the position after ln (if any)
            insert_at = 0
            for i, child in enumerate(list(rPr)):
                if etree.QName(child).localname == "ln":
                    insert_at = i + 1
            rPr.insert(insert_at, sf)
        r.append(rPr)
        t = etree.SubElement(r, q("a:t"))
        t.text = typeset_figures(spec.text)  # ranges, a true minus, the deck's percent style (G5-16)
        if spec.text != spec.text.strip() or "  " in spec.text:
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        end = p.find(q("a:endParaRPr"))
        if neutral_runs and end is not None:
            neutralize_rpr(end)
        if end is not None:
            p.insert(list(p).index(end), r)
        else:
            p.append(r)
        txBody.append(p)
    return True


def neutralize_rpr(rPr: etree._Element) -> etree._Element:
    """Explicit `cap="none" spc="0" baseline="0"` on a run's properties: nothing inherited respaces or recases it."""
    rPr.set("cap", "none")
    rPr.set("spc", "0")
    rPr.set("baseline", "0")
    return rPr


def _shape_and_el(shape) -> tuple[object, Optional[etree._Element]]:
    el = getattr(shape, "_element", None)
    if el is None and isinstance(shape, etree._Element):
        return None, shape
    return shape, el


def effective_insets(shape) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) text insets in EMU as the renderer applies them: the shape's own `a:bodyPr`, then
    the layout's and the master's placeholder it inherits from (python-pptx shape), else the OOXML defaults
    (91440, 45720, 91440, 45720). An lxml element alone gives only its own insets over the defaults."""
    from verstka.rendering.deck import placeholder_chain

    shp, el = _shape_and_el(shape)
    chain = [el] if el is not None else []
    if shp is not None:
        try:
            chain += placeholder_chain(shp)
        except Exception:  # noqa: BLE001
            pass
    out = []
    for name, default in (("lIns", 91440), ("tIns", 45720), ("rIns", 91440), ("bIns", 45720)):
        val = None
        for holder in chain:
            bp = holder.find(q("p:txBody") + "/" + q("a:bodyPr"))
            if bp is not None and bp.get(name) is not None:
                try:
                    val = int(bp.get(name))
                except ValueError:
                    val = None
                if val is not None:
                    break
        out.append(default if val is None else val)
    return out[0], out[1], out[2], out[3]


def _level_defrpr(holder: Optional[etree._Element], level: int = 1) -> Optional[etree._Element]:
    """`a:lvlNpPr/a:defRPr` of a list style (a:lstStyle, p:titleStyle, p:bodyStyle, p:otherStyle)."""
    if holder is None:
        return None
    lvl = holder.find(q(f"a:lvl{level}pPr"))
    return lvl.find(q("a:defRPr")) if lvl is not None else None


def inherited_caps_spc(shape) -> tuple[bool, float]:
    """(capitals, letter-spacing in pt) the first run of a text shape is set with: its own `a:rPr`, the shape's list
    style, the layout's and the master's placeholder list styles, then the master's text style (title style for a
    title placeholder, body style for other placeholders, «other» style for plain text boxes). `cap="small"` counts
    as capitals (the glyphs are capitals)."""
    from verstka.rendering.deck import _ph_of, placeholder_chain

    shp, el = _shape_and_el(shape)
    if el is None:
        return False, 0.0
    holders: list[Optional[etree._Element]] = []
    txb = el.find(q("p:txBody"))
    if txb is not None:
        p0 = txb.find(q("a:p"))
        if p0 is not None:
            r0 = next((r for r in p0.findall(q("a:r")) if r.find(q("a:rPr")) is not None), None)
            holders.append(r0.find(q("a:rPr")) if r0 is not None else p0.find(q("a:endParaRPr")))
            ppr = p0.find(q("a:pPr"))
            holders.append(ppr.find(q("a:defRPr")) if ppr is not None else None)
        holders.append(_level_defrpr(txb.find(q("a:lstStyle"))))
    chain = []
    if shp is not None:
        try:
            chain = placeholder_chain(shp)
        except Exception:  # noqa: BLE001
            chain = []
    for base in chain:
        btx = base.find(q("p:txBody"))
        holders.append(_level_defrpr(btx.find(q("a:lstStyle"))) if btx is not None else None)
    ph = _ph_of(el)
    try:
        master = shp.part.slide.slide_layout.slide_master if shp is not None and hasattr(shp.part, "slide") else None
    except Exception:  # noqa: BLE001
        master = None
    if master is not None:
        styles = master._element.find(q("p:txStyles"))
        if styles is not None:
            typ = (ph.get("type") or "body") if ph is not None else None
            name = "p:titleStyle" if typ in ("title", "ctrTitle") else ("p:bodyStyle" if ph is not None else "p:otherStyle")
            holders.append(_level_defrpr(styles.find(q(name))))
    cap = spc = None
    for h in holders:
        if h is None:
            continue
        if cap is None and h.get("cap") is not None:
            cap = h.get("cap")
        if spc is None and h.get("spc") is not None:
            try:
                spc = int(h.get("spc")) / 100.0
            except ValueError:
                spc = None
        if cap is not None and spc is not None:
            break
    return (cap in ("all", "small")), float(spc or 0.0)


def clear_text(sp_el: etree._Element) -> bool:
    return fill_text(sp_el, [ParagraphSpec("")])


def set_text_size(sp_el: etree._Element, size_pt: float) -> None:
    txBody = _txBody(sp_el)
    if txBody is None:
        return
    for rPr in txBody.iter(q("a:rPr")):
        rPr.set("sz", str(int(round(size_pt * 100))))
    for end in txBody.iter(q("a:endParaRPr")):
        end.set("sz", str(int(round(size_pt * 100))))


def shape_text(sp_el: etree._Element) -> str:
    txBody = _txBody(sp_el)
    if txBody is None:
        return ""
    paras = []
    for p in txBody.findall(q("a:p")):
        paras.append("".join(t.text or "" for t in p.iter(q("a:t"))))
    return "\n".join(paras)


def has_visible_style(sp_el: etree._Element) -> bool:
    """True when the shape has a fill or line (a card), False for an invisible text box."""
    spPr = sp_el.find(q("p:spPr"))
    if spPr is None:
        return False
    if spPr.find(q("a:solidFill")) is not None or spPr.find(q("a:gradFill")) is not None or spPr.find(q("a:blipFill")) is not None:
        return True
    ln = spPr.find(q("a:ln"))
    if ln is not None and ln.find(q("a:noFill")) is None and (ln.find(q("a:solidFill")) is not None or ln.find(q("a:gradFill")) is not None):
        return True
    style = sp_el.find(q("p:style"))
    if style is not None and spPr.find(q("a:noFill")) is None:
        fill_ref = style.find(q("a:fillRef"))
        if fill_ref is not None and (fill_ref.get("idx") or "0") not in ("0",):
            return True
    return False


# child order of a:rPr (CT_TextCharacterProperties)
_RPR_ORDER = ["ln", "noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill", "effectLst", "effectDag", "highlight", "uLnTx", "uLn", "uFillTx", "uFill", "latin", "ea", "cs", "sym", "hlinkClick", "hlinkMouseOver", "rtl", "extLst"]


def ensure_txbody(sp_el: etree._Element, insets: tuple[int, int, int, int], anchor: str = "t") -> Optional[etree._Element]:
    """Give a drawn shape (an empty card of the template) a text body: wrapped, padded, anchored at the top."""
    if etree.QName(sp_el).localname != "sp":
        return None
    txBody = sp_el.find(q("p:txBody"))
    if txBody is None:
        txBody = etree.Element(q("p:txBody"))
        etree.SubElement(txBody, q("a:bodyPr"))
        etree.SubElement(txBody, q("a:lstStyle"))
        etree.SubElement(txBody, q("a:p"))
        ext = sp_el.find(q("p:extLst"))  # p:sp = nvSpPr, spPr, style?, txBody?, extLst?
        if ext is not None:
            ext.addprevious(txBody)
        else:
            sp_el.append(txBody)
    bodyPr = txBody.find(q("a:bodyPr"))
    if bodyPr is None:
        bodyPr = etree.Element(q("a:bodyPr"))
        txBody.insert(0, bodyPr)
    for child in list(bodyPr):
        if etree.QName(child).localname in ("spAutoFit", "normAutofit", "noAutofit"):
            bodyPr.remove(child)
    bodyPr.set("wrap", "square")
    bodyPr.set("anchor", anchor)
    for name, v in zip(("lIns", "tIns", "rIns", "bIns"), insets):
        bodyPr.set(name, str(int(v)))
    return txBody


def style_runs(sp_el: etree._Element, family: Optional[str], color_hex: Optional[str], align: Optional[str] = "l") -> None:
    """Explicit font, colour and alignment for text written into a shape that has no text style of its own."""
    txBody = _txBody(sp_el)
    if txBody is None:
        return
    for p in txBody.findall(q("a:p")):
        if align:
            pPr = p.find(q("a:pPr"))
            if pPr is None:
                pPr = etree.Element(q("a:pPr"))
                p.insert(0, pPr)
            pPr.set("algn", align)
        for rPr in list(p.iter(q("a:rPr"))) + list(p.iter(q("a:endParaRPr"))):
            if color_hex:
                for tag in ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"):
                    for el in rPr.findall(q(tag)):
                        rPr.remove(el)
                sf = etree.Element(q("a:solidFill"))
                etree.SubElement(sf, q("a:srgbClr")).set("val", color_hex.upper())
                insert_ordered(rPr, sf, _RPR_ORDER)
            if family:
                for el in rPr.findall(q("a:latin")) + rPr.findall(q("a:cs")):
                    rPr.remove(el)
                latin = etree.Element(q("a:latin"))
                latin.set("typeface", family)
                insert_ordered(rPr, latin, _RPR_ORDER)
