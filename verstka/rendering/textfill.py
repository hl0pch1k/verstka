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


def _set_bullet(pPr: etree._Element, on: bool) -> None:
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum", "a:buBlip"):
        for el in pPr.findall(q(tag)):
            pPr.remove(el)
    if on:
        # bullet elements must come after spacing/indent elements but before extLst; append is fine when no extLst
        bu = etree.SubElement(pPr, q("a:buChar"))
        bu.set("char", "•")
    else:
        etree.SubElement(pPr, q("a:buNone"))


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
                _set_bullet(pPr, True)
            elif not spec.bullet and _has_bullet(p):
                _set_bullet(pPr, False)
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
