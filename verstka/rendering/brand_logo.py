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


def is_brand_logo_any(el: etree._Element) -> bool:
    """A brand logo the branded copy put or put in place of the template's own: marked (`is_brand_logo`) or named
    «Логотип <бренд>» with the same description (`brand.logos._set_blip`)."""
    if is_brand_logo(el):
        return True
    if etree.QName(el).localname != "pic":
        return False
    nv = el.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr")
    name = (nv.get("name") or "") if nv is not None else ""
    return name.startswith("Логотип ") and (nv.get("descr") or "") == name


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


def deck_logo_box(slide) -> Optional[tuple[float, float, float, float]]:
    """Место логотипа бренда в этой колоде — один угол на всю колоду (qa3 N-B2): угол, в котором брендированная копия
    ставила логотип на большинстве образцов (там, где брендбук велит и угол свободен, — его угол), с медианными
    размером и отступами от краёв. Считается один раз на пакет; None — у образцов нет логотипа бренда."""
    pkg = slide.part.package
    cache = pkg.__dict__.get("_verstka_logo_box", "unset")
    if cache != "unset":
        return cache
    box = None
    try:
        prs = pkg.presentation_part.presentation
        W, H = float(prs.slide_width), float(prs.slide_height)
        by: dict = {}
        for sl in prs.slides:
            for el in sl._element.iter(f"{{{_P}}}pic"):
                if not is_brand_logo(el):
                    continue
                b = _box(el)
                if b is None or b[2] <= 0 or b[3] <= 0:
                    continue
                corner = ("l" if b[0] + b[2] / 2 < W / 2 else "r", "t" if b[1] + b[3] / 2 < H / 2 else "b")
                by.setdefault(corner, []).append(b)
        if by:
            corner, boxes = max(by.items(), key=lambda kv: len(kv[1]))

            def med(xs):
                xs = sorted(xs)
                return xs[len(xs) // 2]

            w, h = med([b[2] for b in boxes]), med([b[3] for b in boxes])
            dx = med([b[0] if corner[0] == "l" else W - (b[0] + b[2]) for b in boxes])
            dy = med([b[1] if corner[1] == "t" else H - (b[1] + b[3]) for b in boxes])
            x = dx if corner[0] == "l" else W - dx - w
            y = dy if corner[1] == "t" else H - dy - h
            box = (x, y, w, h)
    except Exception as e:  # noqa: BLE001 - без общего угла: логотип остаётся на месте образца
        log.debug("deck logo corner not read: %s", e)
        box = None
    pkg.__dict__["_verstka_logo_box"] = box
    return box


def held_logo_box(slide) -> Optional[tuple[float, float, float, float]]:
    """Место, куда вернётся отложенный логотип бренда (угол колоды), — его не занимает раскладка (qa3 N-B1); None —
    логотипа на слайде нет."""
    if slide is None or not slide.__dict__.get(_KEY):
        return None
    return deck_logo_box(slide)


def put_back_brand_logos(slide, warnings: list[str], corner: bool = True):
    """Вернуть отложенные логотипы поверх собранного слайда — в угол колоды (`deck_logo_box`; `corner=False` — на место
    образца: обложка, раздел, финал), один раз; тот, на чьё место (с охранным полем) зашло новое содержимое, не
    возвращается. (slide, warnings) — как у отрисовщиков."""
    held = slide.__dict__.pop(_KEY, None) if slide is not None else None
    if not held:
        return slide, warnings
    target = deck_logo_box(slide) if corner else None
    if target is not None:
        held = held[:1]  # one logo a slide, in the deck's corner
        own = _box(held[0])
        if own is not None and own[2] > 0 and own[3] > 0:
            # its own proportions at the deck's height, against the corner's edge
            W = float(slide.part.package.presentation_part.presentation.slide_width)
            w = target[3] * own[2] / own[3]
            x = target[0] if target[0] + target[2] / 2 < W / 2 else target[0] + target[2] - w
            target = (x, target[1], w, target[3])
        _place(held[0], target)
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


def _xfrm(el: etree._Element):
    """A picture's or a group's own frame (spPr / grpSpPr)."""
    return el.find(f"{{{_P}}}spPr/{{{_A}}}xfrm") if etree.QName(el).localname != "grpSp" else el.find(f"{{{_P}}}grpSpPr/{{{_A}}}xfrm")


def _place(el: etree._Element, box: tuple[float, float, float, float]) -> None:
    xfrm = _xfrm(el)
    off = xfrm.find(f"{{{_A}}}off") if xfrm is not None else None
    ext = xfrm.find(f"{{{_A}}}ext") if xfrm is not None else None
    if off is None or ext is None:
        return
    off.set("x", str(int(box[0])))
    off.set("y", str(int(box[1])))
    ext.set("cx", str(int(box[2])))
    ext.set("cy", str(int(box[3])))


def _remove(slide, el: etree._Element) -> None:
    blip = el.find(f"{{{_P}}}blipFill/{{{_A}}}blip")
    rid = blip.get(f"{{{_R}}}embed") if blip is not None else None
    el.getparent().remove(el)
    if rid and rid in slide.part.rels and not any(v == rid for e in slide._element.iter() for k, v in e.attrib.items() if k.startswith(f"{{{_R}}}")):
        slide.part.drop_rel(rid)


def _box(el: etree._Element) -> Optional[tuple[float, float, float, float]]:
    xfrm = _xfrm(el)
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


def one_corner(prs, skip: frozenset | set = frozenset()) -> int:
    """The finished deck's brand logos in ONE corner (qa3 N-B2): the corner most content slides show it in — the
    slides' own logos and the ones their layouts draw — and every layout logo elsewhere moved there, at the deck's size,
    when that place is clear on the layout and on every slide using it (else it stays where the copy put it). Covers
    and dividers are not counted. Returns how many layout logos moved."""
    from verstka.rendering.deck import element_bbox

    W, H = float(prs.slide_width), float(prs.slide_height)

    def corner_of(b) -> tuple[str, str]:
        return ("l" if b[0] + b[2] / 2 < W / 2 else "r", "t" if b[1] + b[3] / 2 < H / 2 else "b")

    def logos(holder) -> list:
        # top-level pictures, or the top-level group a logo picture sits in (the template's own lockup kept with the
        # brand's picture in it — VK Tech «логотип как в шаблоне»): the group moves whole
        out = []
        tree = holder._element.find(f".//{{{_P}}}spTree")
        for el in (tree if tree is not None else []):
            tag = etree.QName(el).localname
            if tag == "pic" and is_brand_logo_any(el):
                out.append(el)
            elif tag == "grpSp" and any(is_brand_logo_any(x) for x in el.iter(f"{{{_P}}}pic")):
                b = _box(el)
                if b is not None and b[2] * b[3] < 0.05 * W * H:
                    out.append(el)
        return out

    shown: dict = {}
    layouts: dict = {}
    for i, sl in enumerate(prs.slides):
        if i in skip:
            continue  # (a cover, a divider, the closing slide: their logo is their sample's)
        lay = sl.slide_layout
        own = logos(sl)
        els = own or logos(lay)
        for el in els[:1]:
            b = _box(el)
            if b is not None and b[2] > 0 and b[3] > 0:
                shown.setdefault(corner_of(b), []).append(b)
        if not own:
            layouts.setdefault(id(lay.part), (lay, []))[1].append(sl)
    if len(shown) < 2:
        return 0
    corner, boxes = max(shown.items(), key=lambda kv: len(kv[1]))
    h = sorted(b[3] for b in boxes)[len(boxes) // 2]
    dx = sorted((b[0] if corner[0] == "l" else W - (b[0] + b[2])) for b in boxes)[len(boxes) // 2]
    dy = sorted((b[1] if corner[1] == "t" else H - (b[1] + b[3])) for b in boxes)[len(boxes) // 2]
    moved = 0
    targets: list = [(lay, slides) for lay, slides in layouts.values()]
    for i, sl in enumerate(prs.slides):
        if i not in skip and logos(sl):
            targets.append((sl, []))  # the slide's own logo: checked against the slide itself
    for lay, slides in targets:
        for el in logos(lay):
            b = _box(el)
            if b is None or b[3] <= 0 or corner_of(b) == corner:
                continue
            pad = 0.01 * H

            def hits(holder, tgt) -> bool:
                for o in holder._element.iter(f"{{{_P}}}sp", f"{{{_P}}}pic", f"{{{_P}}}graphicFrame", f"{{{_P}}}grpSp"):
                    if o is el or o.getparent() is None or etree.QName(o.getparent()).localname not in ("spTree",):
                        continue
                    ob = element_bbox(o)
                    if not ob or ob[2] * ob[3] >= 0.85 * W * H:
                        continue
                    if ob[0] + ob[2] > 1.15 * W or ob[1] + ob[3] > 1.15 * H or ob[2] * ob[3] >= 0.25 * W * H:
                        continue  # a band or a shape bleeding off the slide: the ground the template draws under its corner
                    if min(ob[0] + ob[2], tgt[0] + tgt[2]) - max(ob[0], tgt[0]) > 0 and min(ob[1] + ob[3], tgt[1] + tgt[3]) - max(ob[1], tgt[1]) > 0:
                        return True
                return False

            # the deck's place first; then a little smaller, or nudged inside the corner's zone (up, in), when that
            # is what frees it (qa3: VK Tech's layout keeps a mark at the very corner)
            for scale, ux, uy in ((1.0, 0, 0), (0.85, 0, 0), (1.0, 0, 0.04), (1.0, 0.05, 0), (0.85, 0.05, 0.04), (0.7, 0, 0)):
                hh = h * scale
                w = hh * b[2] / b[3]
                x = (dx + ux * W) if corner[0] == "l" else W - dx - ux * W - w
                y = (dy + uy * H) if corner[1] == "t" else H - dy - uy * H - hh
                tgt = (x - pad, y - pad, w + 2 * pad, hh + 2 * pad)
                if not hits(lay, tgt) and not any(hits(sl, tgt) for sl in slides):
                    _place(el, (x, y, w, hh))
                    moved += 1
                    break
    return moved
