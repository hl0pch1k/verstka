"""The places a rendered deck keeps for pictures, and a picture put into one (or taken out again).

A place is the shape named PHOTO_PLACE_NAME (synth._empty_photo_place / _photo_frame_beside: the template's own
picture place or a quiet frame beside the content) with its caption inside («Место под изображение» over the author's
description, a text box named «Photo caption N»). The picture takes the place's position in the shape tree (what
lies over it — a device's frame around a screen — stays over it), its box and its geometry (the frame's rounded
corners clip it); the caption goes. The place's own XML and its caption's are kept with the picture's record, so
«Убрать изображение» puts the free place back exactly."""

from __future__ import annotations

import copy
import io
import re
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import q
from verstka.schemas.outline import PHOTO_PLACE_NAME, DeckOutline

CAPTION_PREFIX = "Photo caption"
PICTURE_PREFIX = "Изображение"  # the picture's shape name: «Изображение: экран панели управления»
# a place for something that is not a picture — a chart, a table, a video the author will add: never generated
_NOT_PICTURE_RE = re.compile(r"диаграмм|график|таблиц|видео|ролик|chart|table|video", re.I)


@dataclass
class Place:
    slide: int  # 1-based, the deck's order (= the outline's)
    shape_id: str
    box: tuple[int, int, int, int]  # x, y, w, h (EMU)
    caption_ids: list[str] = field(default_factory=list)
    outline_id: Optional[str] = None
    headline: str = ""
    label: str = ""
    hint: str = ""
    own: bool = False  # the author's own photo (or a chart, a table, a video): never filled by itself

    @property
    def aspect(self) -> float:
        return self.box[2] / self.box[3] if self.box[3] > 0 else 1.0


def _name(el) -> str:
    nv = el.find(".//" + q("p:cNvPr"))
    return (nv.get("name") or "") if nv is not None else ""


def _id(el) -> str:
    nv = el.find(".//" + q("p:cNvPr"))
    return (nv.get("id") or "") if nv is not None else ""


def _box(el) -> Optional[tuple[int, int, int, int]]:
    from verstka.rendering.deck import element_bbox

    b = element_bbox(el)
    if not b or b[2] <= 0 or b[3] <= 0:
        return None
    return int(b[0]), int(b[1]), int(b[2]), int(b[3])


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def _distance(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    return ((a[0] + a[2] / 2 - b[0] - b[2] / 2) ** 2 + (a[1] + a[3] / 2 - b[1] - b[3] / 2) ** 2) ** 0.5


def _owner(cap: tuple[int, int, int, int], boxes: list[tuple[int, int, int, int]]) -> int:
    """The place a caption belongs to: the one it overlaps most, else the nearest. A caption is only ever made for a
    picture place, but the place may be trimmed after it (a frame aligned to the content's foot) — its caption then
    hangs out of it and must still go with it."""
    best = max(range(len(boxes)), key=lambda i: (_overlap(cap, boxes[i]), -_distance(cap, boxes[i])))
    return best


def is_own(label: Optional[str], own_flag: bool) -> bool:
    return bool(own_flag) or bool(_NOT_PICTURE_RE.search(label or ""))


def places_on(slide, index: int, oslide=None) -> list[Place]:
    """The free picture places of one slide (top-level shapes of its tree)."""
    tree = slide._element.cSld.find(q("p:spTree"))
    out: list[Place] = []
    for el in tree:
        if _name(el) != PHOTO_PLACE_NAME or etree.QName(el).localname != "sp":
            continue
        box = _box(el)
        if box is None:
            continue
        c = getattr(oslide, "content", None)
        label = (getattr(c, "photo_slot", None) or "") if c is not None else ""
        out.append(Place(
            slide=index, shape_id=_id(el), box=box,
            outline_id=getattr(oslide, "id", None), headline=getattr(oslide, "headline", "") or "", label=label,
            hint=(getattr(c, "photo_hint", None) or "") if c is not None else "",
            own=is_own(label, bool(getattr(c, "photo_own", False))) if c is not None else False,
        ))
    if out:
        boxes = [pl.box for pl in out]
        for el in tree:
            if not _name(el).startswith(CAPTION_PREFIX):
                continue
            cb = _box(el)
            if cb is not None:
                out[_owner(cb, boxes)].caption_ids.append(_id(el))
    return out


def places_in(prs, outline: Optional[DeckOutline]) -> list[Place]:
    """Every free picture place of a deck, slide by slide (the deck's slides are the outline's, in order)."""
    slides = list(outline.slides) if outline is not None else []
    out: list[Place] = []
    for i, slide in enumerate(prs.slides, 1):
        out.extend(places_on(slide, i, slides[i - 1] if i - 1 < len(slides) else None))
    return out


def _by_id(tree, sid: str):
    for el in tree:
        if _id(el) == sid:
            return el
    return None


def _picture_xml(slide, data: bytes, box: tuple[int, int, int, int]):
    """A p:pic of `data` at `box` (python-pptx makes the image part and its relationship), detached from the tree."""
    pic = slide.shapes.add_picture(io.BytesIO(data), box[0], box[1], box[2], box[3])
    el = pic._element
    el.getparent().remove(el)
    return el


def put_picture(slide, place: Place, data: bytes, *, descr: str) -> Optional[dict]:
    """The picture `data` (already cropped to the place's proportions) in the place: its z-position, box and geometry;
    the caption goes. Returns what puts the place back (the place's and the captions' XML), None when the place is gone."""
    tree = slide._element.cSld.find(q("p:spTree"))
    el = _by_id(tree, place.shape_id)
    if el is None or _name(el) != PHOTO_PLACE_NAME:
        return None
    at = list(tree).index(el)
    pic = _picture_xml(slide, data, place.box)
    nv = pic.find(".//" + q("p:cNvPr"))
    nv.set("id", place.shape_id)
    nv.set("name", f"{PICTURE_PREFIX}: {(place.hint or place.label or place.headline)[:80]}".rstrip(": "))
    nv.set("descr", descr[:900])
    geom = el.find(q("p:spPr") + "/" + q("a:prstGeom"))
    sppr = pic.find(q("p:spPr"))
    if geom is not None and sppr is not None:
        old = sppr.find(q("a:prstGeom"))
        if old is not None:
            sppr.replace(old, copy.deepcopy(geom))
    kept = {"place_xml": etree.tostring(el, encoding="unicode"), "caption_xml": []}
    tree.remove(el)
    tree.insert(at, pic)
    for cid in place.caption_ids:
        cel = _by_id(tree, cid)
        if cel is not None:
            kept["caption_xml"].append(etree.tostring(cel, encoding="unicode"))
            tree.remove(cel)
    return kept


def swap_picture(slide, shape_id: str, data: bytes, *, descr: Optional[str] = None) -> bool:
    """A new picture in place of the one at `shape_id` (the same box, geometry and position): a new image part."""
    tree = slide._element.cSld.find(q("p:spTree"))
    el = _by_id(tree, shape_id)
    if el is None or etree.QName(el).localname != "pic":
        return False
    box = _box(el)
    if box is None:
        return False
    new = _picture_xml(slide, data, box)
    blip_new = new.find(".//" + q("a:blip"))
    blip_old = el.find(".//" + q("a:blip"))
    if blip_new is None or blip_old is None:
        return False
    rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    old_rid = blip_old.get(rid_attr)
    blip_old.set(rid_attr, blip_new.get(rid_attr))
    if descr is not None:
        nv = el.find(".//" + q("p:cNvPr"))
        if nv is not None:
            nv.set("descr", descr[:900])
    # the old picture's relationship goes when nothing else on the slide uses it (python-pptx drops the part on save)
    if old_rid and not any(b.get(rid_attr) == old_rid for b in slide._element.iter(q("a:blip"))):
        try:
            slide.part.drop_rel(old_rid)
        except Exception:  # noqa: BLE001 - an unused relationship is harmless
            pass
    return True


def take_picture_out(slide, shape_id: str, kept: dict) -> bool:
    """The free place (and its caption) back where the picture stands."""
    tree = slide._element.cSld.find(q("p:spTree"))
    el = _by_id(tree, shape_id)
    xml = kept.get("place_xml") if isinstance(kept, dict) else None
    if el is None or not xml:
        return False
    at = list(tree).index(el)
    place = etree.fromstring(xml)
    rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    blip = el.find(".//" + q("a:blip"))
    tree.remove(el)
    tree.insert(at, place)
    for i, cx in enumerate(kept.get("caption_xml") or []):
        tree.insert(at + 1 + i, etree.fromstring(cx))
    if blip is not None and blip.get(rid_attr) and not any(b.get(rid_attr) == blip.get(rid_attr) for b in slide._element.iter(q("a:blip"))):
        try:
            slide.part.drop_rel(blip.get(rid_attr))
        except Exception:  # noqa: BLE001
            pass
    return True
