"""OOXML namespaces and small lxml helpers."""

from __future__ import annotations

from typing import Optional

from lxml import etree

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "dgm": "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
}

REL_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def q(tag: str) -> str:
    """'p:sp' → '{ns}sp'."""
    prefix, local = tag.split(":")
    return f"{{{NS[prefix]}}}{local}"


def local_name(el: etree._Element) -> str:
    return etree.QName(el).localname


def find(el: Optional[etree._Element], path: str) -> Optional[etree._Element]:
    if el is None:
        return None
    return el.find(path, NS)


def find_first(el: Optional[etree._Element], *paths: str) -> Optional[etree._Element]:
    """First non-None match among several paths (lxml elements without children are falsy, so never use `or`)."""
    if el is None:
        return None
    for path in paths:
        found = el.find(path, NS)
        if found is not None:
            return found
    return None


def findall(el: Optional[etree._Element], path: str) -> list[etree._Element]:
    if el is None:
        return []
    return el.findall(path, NS)


def attr_int(el: Optional[etree._Element], name: str, default: Optional[int] = None) -> Optional[int]:
    if el is None:
        return default
    v = el.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return default


def attr_bool(el: Optional[etree._Element], name: str, default: Optional[bool] = None) -> Optional[bool]:
    if el is None:
        return default
    v = el.get(name)
    if v is None:
        return default
    return v in ("1", "true", "on")
