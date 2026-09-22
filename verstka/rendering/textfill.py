"""Write paragraphs into an existing shape while keeping its run/paragraph formatting."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import NS, q

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


def fill_text(sp_el: etree._Element, paragraphs: list[ParagraphSpec], size_pt: Optional[float] = None, keep_bullets: bool = True) -> bool:
    """Replace the text of a shape. Returns False when the element has no text body."""
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
        if spec.level:
            if pPr is None:
                pPr = etree.Element(q("a:pPr"))
                p.insert(0, pPr)
            pPr.set("lvl", str(spec.level))
        r = etree.Element(q("a:r"))
        rPr = copy.deepcopy(template_rPr)
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
        t.text = spec.text
        if spec.text != spec.text.strip() or "  " in spec.text:
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        end = p.find(q("a:endParaRPr"))
        if end is not None:
            p.insert(list(p).index(end), r)
        else:
            p.append(r)
        txBody.append(p)
    return True


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
