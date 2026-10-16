"""Логотип бренда на собранных слайдах.

Брендированная копия шаблона (`verstka.brand`) ставит логотип бренда на образцы — картинкой с меткой
`BRAND_LOGO_MARK` в `p:cNvPr/@title`. Сборка колоды клонирует образец (или берёт его холстом для своей композиции) и
убирает картинки образца как содержимое; логотип бренда она откладывает (`hold_brand_logos`), собирает слайд без
него — ни одно решение раскладки его не видит — и возвращает на то же место (`put_back_brand_logos`), если новое
содержимое слайда туда не зашло. Заход решает та же проверка, что ставила логотип в копии: IR слайда (рамки
заполнителей, текст, фигуры, картинки, таблицы, диаграммы, группы; края рамок-контуров; линии, в том числе нулевой
толщины) и охранное поле вокруг логотипа. Слой макета и мастера у клона тот же, что у образца, — его копия уже
проверила.

Обычная колода (на слайдах нет метки) не меняется ни в одном байте части: обе функции тогда ничего не делают."""

from __future__ import annotations

import logging
from typing import Optional

from lxml import etree

from verstka.brand.package import BRAND_LOGO_MARK
from verstka.ingest.package import PptxPackage, Rel

log = logging.getLogger(__name__)

_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_KEY = "_verstka_brand_logos"
DROPPED = "brand logo left out: the slide's new content reaches its place"


def is_brand_logo(el: etree._Element) -> bool:
    """Картинка — логотип бренда, поставленный брендированной копией."""
    if etree.QName(el).localname != "pic":
        return False
    nv = el.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr")
    return nv is not None and nv.get("title") == BRAND_LOGO_MARK


def _tree(slide) -> etree._Element:
    return slide._element.find(f"{{{_P}}}cSld/{{{_P}}}spTree")


def hold_brand_logos(slide) -> int:
    """Отложить логотипы бренда только что склонированного слайда (верхний уровень дерева фигур) до конца сборки.
    Сколько отложено; 0 — слайд не тронут."""
    tree = _tree(slide)
    held = [el for el in tree if is_brand_logo(el)] if tree is not None else []
    if not held:
        return 0
    for el in held:
        tree.remove(el)
    slide.__dict__.setdefault(_KEY, []).extend(held)
    return len(held)


def put_back_brand_logos(slide, warnings: list[str]):
    """Вернуть отложенные логотипы поверх собранного слайда; тот, на чьё место (с охранным полем) зашло новое
    содержимое, не возвращается. (slide, warnings) — как у отрисовщиков."""
    held = slide.__dict__.pop(_KEY, None) if slide is not None else None
    if not held:
        return slide, warnings
    tree = _tree(slide)
    ids = [int(e.get("id")) for e in slide._element.iter(f"{{{_P}}}cNvPr") if (e.get("id") or "").isdigit()]
    top = max(ids, default=1)
    taken = set(ids)
    ext = tree.find(f"{{{_P}}}extLst")
    for el in held:
        nv = el.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr")
        if not (nv.get("id") or "").isdigit() or int(nv.get("id")) in taken:
            top += 1
            nv.set("id", str(top))
        taken.add(int(nv.get("id")))
        if ext is not None:
            ext.addprevious(el)
        else:
            tree.append(el)
    try:
        bad = _colliding(slide, held)
    except Exception as e:  # noqa: BLE001 - без проверки логотип не возвращается: так было до брендбука
        log.warning("brand logo check failed: %s", e)
        bad = list(held)
    for el in bad:
        _remove(slide, el)
    if bad:
        warnings.append(DROPPED)
    return slide, warnings


def _remove(slide, el: etree._Element) -> None:
    blip = el.find(f"{{{_P}}}blipFill/{{{_A}}}blip")
    rid = blip.get(f"{{{_R}}}embed") if blip is not None else None
    el.getparent().remove(el)
    if rid and rid in slide.part.rels and not any(v == rid for e in slide._element.iter() for k, v in e.attrib.items() if k.startswith(f"{{{_R}}}")):
        slide.part.drop_rel(rid)


def _box(el: etree._Element) -> Optional[tuple[float, float, float, float]]:
    xfrm = el.find(f"{{{_P}}}spPr/{{{_A}}}xfrm")
    off = xfrm.find(f"{{{_A}}}off") if xfrm is not None else None
    ext = xfrm.find(f"{{{_A}}}ext") if xfrm is not None else None
    if off is None or ext is None:
        return None
    return float(off.get("x")), float(off.get("y")), float(ext.get("cx")), float(ext.get("cy"))


def _colliding(slide, logos: list[etree._Element]) -> list[etree._Element]:
    """Логотипы, на чьё место (с охранным полем) зашло содержимое слайда, — по IR живого слайда, как у копии."""
    from verstka.analysis.shapes import SlideContext, extract_shapes
    from verstka.audit.ir import _ir_element
    from verstka.brand.logos import CLEAR, _clear, _edges, tree_lines

    pkg = _LivePackage(slide)
    part = str(slide.part.partname).lstrip("/")
    W, H = pkg.slide_size
    own = {el.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr").get("id") for el in logos}
    hard: list = []
    for s in extract_shapes(pkg, part, SlideContext(pkg, part)):
        if s.id in own:
            continue
        e = _ir_element(s, W, H)
        b = (float(e.bbox.x), float(e.bbox.y), float(e.bbox.w), float(e.bbox.h))
        if e.type == "shape" and e.line_hex and not e.fill_hex and e.geometry != "custom":
            hard += _edges(b, W)  # рамка-контур: мешают её края
            continue
        if e.bbox.w * e.bbox.h >= 0.85 * W * H:
            continue  # фон слайда под логотипом
        if e.type == "shape" and not e.fill_hex and not e.line_hex and e.geometry != "custom":
            continue  # пустая рамка без заливки и обводки
        hard.append(b)
    hard += tree_lines(_tree(slide), W)
    return [el for el in logos if (b := _box(el)) is None or not _clear(b, hard, CLEAR * H)]


class _LivePackage(PptxPackage):
    """Пакет собираемой колоды (python-pptx) в виде, который читает разбор слайда (`PptxPackage`): части, связи,
    размер слайда — без сохранения файла."""

    def __init__(self, slide) -> None:  # noqa: D107 - без zip: части живой колоды
        self.path = None
        self._parts = {str(p.partname).lstrip("/"): p for p in slide.part.package.iter_parts()}
        self._names = set(self._parts)
        self._xml_cache: dict[str, etree._Element] = {}
        self._rels_cache: dict[str, dict[str, Rel]] = {}

    def close(self) -> None:
        pass

    def read(self, part: str) -> bytes:
        return self._parts[part].blob

    def media_bytes(self, part: str) -> bytes:
        return self.read(part)

    def xml(self, part: str) -> etree._Element:
        if part not in self._xml_cache:
            p = self._parts[part]
            el = getattr(p, "_element", None)
            self._xml_cache[part] = el if el is not None else etree.fromstring(p.blob)
        return self._xml_cache[part]

    def rels(self, part: str) -> dict[str, Rel]:
        if part in self._rels_cache:
            return self._rels_cache[part]
        out: dict[str, Rel] = {}
        p = self._parts.get(part)
        for rid, rel in (p.rels.items() if p is not None else []):
            kind = rel.reltype.rsplit("/", 1)[-1]
            if rel.is_external:
                out[rid] = Rel(rid=rid, type=kind, target=rel.target_ref, external=True)
            else:
                out[rid] = Rel(rid=rid, type=kind, target=str(rel.target_part.partname).lstrip("/"))
        self._rels_cache[part] = out
        return out
