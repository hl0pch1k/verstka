"""Логотипы в брендированной копии: найти логотип шаблона, заменить его логотипом бренда (светлый или тёмный — по
фону), а если логотипа нет и брендбук задаёт место — поставить логотип бренда так, чтобы он ни с чем не столкнулся.

- Логотип шаблона — картинка с «logo / лого» в имени, логотип разбора (плоская картинка на прозрачном фоне), картинка
  у края слайда, повторённая хотя бы на двух макетах, та же картинка другого размера и всё, что стоит рядом в строку
  (знак + надпись — одна группа, в т. ч. внутри групп с преобразованием). Логотип из текста и автофигуры («mybrand.»)
  не распознаётся: он остаётся, бренд ставит свой по правилу места.
- Замена: один логотип бренда в рамке логотипа шаблона (пропорции свои, высота — как у рамки, но не меньше читаемой,
  прижат к своей стороне); на части — один логотип бренда; место — то, где у шаблона логотип стоит на большинстве
  частей (не прыгает слева направо между слайдами).
- Добавление: в угол из брендбука с его полями, а если там текст (номер слайда, колонтитул, дата — и у макета, и у
  мастера), линия, карточка или непрозрачная картинка — дальше вдоль края; некуда — не ставится, с объяснением.
  Вариант логотипа — по настоящему цвету под ним.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import posixpath
import re
import shutil
import subprocess
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

from lxml import etree

from verstka.brand.package import A, BRAND_LOGO_MARK, IMG_REL, P, R, Box, Package, overlap, shape_box, xfrm_box
from verstka.brand.palette import lightness
from verstka.schemas.brand import BrandLogo, BrandSpec, LogoPlace
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

_LOGO_PART_RE = re.compile(r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+)\.xml$")
_LOGO_NAME_RE = re.compile(r"logo|лого|wordmark|emblem|эмблем|brand(?!book)|бренд(?!бук)", re.I)
_SRGB = f"{{{A}}}srgbClr"

# высота логотипа бренда не меньше этой доли высоты слайда (надпись «VK Cloud» в рамке маленького «tech» иначе не
# читается; брендбук VK Cloud: не меньше 32 px на 1080)
MIN_WORDMARK_H = 0.032
MIN_MARK_H = 0.05
# насколько логотип бренда может быть шире рамки логотипа шаблона (растёт в сторону от своего края)
FIT_GROW = 1.35


# ============================================================================================ картинки


@dataclass
class Pic:
    part: str
    el: etree._Element
    box: Box  # в EMU слайда
    media: Optional[str]
    name: str
    groups: list[etree._Element]  # группы-предки (внутренняя первой)


@dataclass
class Lockup:
    """Логотип шаблона на одной части: знак и надпись рядом — одна группа."""

    part: str
    pics: list[Pic]
    box: Box
    ground: str = "light"  # light | dark — на каком фоне стоит
    duplicate: bool = False  # тот же логотип второй раз на той же части (копия группы)

    @property
    def media(self) -> list[str]:
        return [p.media for p in self.pics if p.media]


def _group_xf(g: etree._Element):
    """(ox, oy, sx, sy, chx, chy): точка группы p → ox + (p − ch)·s."""
    x = g.find(f"{{{P}}}grpSpPr/{{{A}}}xfrm")
    if x is None:
        return None
    off, ext = x.find(f"{{{A}}}off"), x.find(f"{{{A}}}ext")
    choff, chext = x.find(f"{{{A}}}chOff"), x.find(f"{{{A}}}chExt")
    if off is None or ext is None:
        return None
    ox, oy, ex, ey = (float(v) for v in (off.get("x", 0), off.get("y", 0), ext.get("cx", 0), ext.get("cy", 0)))
    cx = float(choff.get("x", 0)) if choff is not None else ox
    cy = float(choff.get("y", 0)) if choff is not None else oy
    cex = float(chext.get("cx", 0)) if chext is not None else ex
    cey = float(chext.get("cy", 0)) if chext is not None else ey
    return ox, oy, (ex / cex if cex else 1.0), (ey / cey if cey else 1.0), cx, cy


def to_abs(box: Box, groups: list[etree._Element]) -> Box:
    x, y, w, h = box
    for g in groups:  # изнутри наружу
        xf = _group_xf(g)
        if xf is None:
            continue
        ox, oy, sx, sy, cx, cy = xf
        x, y, w, h = ox + (x - cx) * sx, oy + (y - cy) * sy, w * sx, h * sy
    return x, y, w, h


def to_local(box: Box, groups: list[etree._Element]) -> Box:
    x, y, w, h = box
    for g in reversed(groups):  # снаружи внутрь
        xf = _group_xf(g)
        if xf is None:
            continue
        ox, oy, sx, sy, cx, cy = xf
        x, y, w, h = cx + (x - ox) / sx, cy + (y - oy) / sy, w / sx, h / sy
    return x, y, w, h


def pics_of(pkg: Package, part: str) -> list[Pic]:
    root = pkg.xml(part)
    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
    if tree is None:
        return []
    rels = pkg.rels(part)
    out: list[Pic] = []
    for pic in tree.iter(f"{{{P}}}pic"):
        nv = pic.find(f"{{{P}}}nvPicPr/{{{P}}}cNvPr")
        if nv is not None and nv.get("hidden") in ("1", "true"):
            continue
        xfrm = pic.find(f"{{{P}}}spPr/{{{A}}}xfrm")
        if xfrm is None or xfrm.get("rot") not in (None, "0"):
            continue
        box = xfrm_box(xfrm)
        if box is None:
            continue
        groups = [a for a in pic.iterancestors() if a.tag == f"{{{P}}}grpSp"]
        blip = pic.find(f"{{{P}}}blipFill/{{{A}}}blip")
        rid = blip.get(f"{{{R}}}embed") if blip is not None else None
        media = rels.get(rid or "", ("", None))[1] if rid else None
        name = " ".join(x for x in ((nv.get("name") or "") if nv is not None else "", (nv.get("descr") or "") if nv is not None else "") if x)
        out.append(Pic(part=part, el=pic, box=to_abs(box, groups), media=media, name=name, groups=groups))
    return out


# кэш по отпечатку содержимого: сами байты картинок в кэше не держатся
_PROBES: "OrderedDict[str, Optional[tuple]]" = OrderedDict()


def image_probe(data: bytes) -> Optional[tuple]:
    """(размер, «отпечаток» 16×16, чернила: light | dark | color | empty, прозрачный фон?, «как логотип»: несколько
    плоских цветов — четыре самых частых покрывают ≥ 85 % непрозрачных точек)."""
    key = hashlib.sha256(data).hexdigest()
    if key in _PROBES:
        _PROBES.move_to_end(key)
        return _PROBES[key]
    res = _probe(data)
    _PROBES[key] = res
    while len(_PROBES) > 4096:  # ЛЦТ — 815 мелких картинок: кэш не должен вытеснять их по кругу
        _PROBES.popitem(last=False)
    return res


def _probe(data: bytes) -> Optional[tuple]:
    try:
        import numpy as np
        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    size = im.size
    print_ = tuple(tuple(int(v) for v in p) for p in np.asarray(im.resize((16, 16))).reshape(-1, 4))
    allpx = [tuple(int(v) for v in p) for p in np.asarray(im.resize((min(96, size[0]), min(96, size[1])))).reshape(-1, 4)]
    px = [p for p in allpx if p[3] > 128]
    transparent = sum(1 for p in allpx if p[3] < 16) >= 0.1 * len(allpx)
    if len(px) < 0.02 * len(allpx):
        return size, print_, "empty", transparent, False
    lum = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b, _ in px) / len(px) / 255
    chroma = sum(max(r, g, b) - min(r, g, b) for r, g, b, _ in px) / len(px) / 255
    ink = "color" if chroma > 0.25 else ("light" if lum > 0.75 else ("dark" if lum < 0.35 else "color"))
    bins = Counter((r >> 5, g >> 5, b >> 5) for r, g, b, _ in px)
    flat = sum(n for _, n in bins.most_common(4)) >= 0.85 * len(px)
    return size, print_, ink, transparent, flat


def same_picture(a: Optional[tuple], b: Optional[tuple]) -> bool:
    """Та же картинка в другом размере: те же пропорции и те же точки там, где у одной из них есть «чернила»."""
    if not a or not b or a[2] == "empty" or b[2] == "empty":
        return False
    (wa, ha), (wb, hb) = a[0], b[0]
    if not (ha and hb) or abs(math.log((wa / ha) / (wb / hb))) > 0.15:
        return False
    diffs = []
    for p, q in zip(a[1], b[1]):
        if max(p[3], q[3]) <= 32:
            continue
        for bg in (255, 0):
            pc = [c * p[3] / 255 + bg * (1 - p[3] / 255) for c in p[:3]]
            qc = [c * q[3] / 255 + bg * (1 - q[3] / 255) for c in q[:3]]
            diffs.append(sum(abs(x - y) for x, y in zip(pc, qc)) / (3 * 255))
    return bool(diffs) and sum(diffs) / len(diffs) < 0.12


def _union(boxes: list[Box]) -> Box:
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[0] + b[2] for b in boxes)
    y2 = max(b[1] + b[3] for b in boxes)
    return x1, y1, x2 - x1, y2 - y1


def _iou(a: Box, b: Box) -> float:
    inter = overlap(a, b)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


# ============================================================================================ фон


_CLR_MAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
_MAP_KEYS = ("bg1", "tx1", "bg2", "tx2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink")


def _map_of(el: Optional[etree._Element]) -> dict[str, str]:
    return {k: v for k, v in (el.attrib.items() if el is not None else []) if k in _MAP_KEYS and v}


def clr_map(pkg: Package, part: str) -> dict[str, str]:
    """Карта цветов части (bg1 → lt1 …): `p:clrMap` мастера, поверх — `overrideClrMapping` макета, поверх — слайда.
    Тёмный макет («Title with Picture 6» у «Кофейни»: bg2 → dk2) красит фон и фигуры тёмным при светлой теме;
    `masterClrMapping` у слайда — без своей карты (как у PowerPoint и LibreOffice: действует карта макета)."""
    cache = pkg.__dict__.setdefault("_clr_maps", {})
    if part in cache:
        return cache[part]
    chain = _chain(pkg, part)
    master = next((p for p in chain if p.startswith("ppt/slideMasters/")), None)
    root = pkg.xml(master) if master else None
    out = dict(_CLR_MAP)
    out.update(_map_of(root.find(f"{{{P}}}clrMap") if root is not None else None))
    for p in reversed([c for c in chain if c != master]):  # макет, затем слайд
        r = pkg.xml(p)
        ovr = r.find(f"{{{P}}}clrMapOvr/{{{A}}}overrideClrMapping") if r is not None else None
        out.update(_map_of(ovr))
    cache[part] = out
    return out


def master_map(pkg: Package, part: str) -> dict[str, str]:
    """Карта цветов мастера части — по ней красит IR аудита."""
    master = next((p for p in _chain(pkg, part) if p.startswith("ppt/slideMasters/")), None)
    root = pkg.xml(master) if master else None
    return {**_CLR_MAP, **_map_of(root.find(f"{{{P}}}clrMap") if root is not None else None)}


def part_slots(pkg: Package, part: str, slots: dict[str, str]) -> dict[str, str]:
    """Слоты темы с bg1/tx1/bg2/tx2 по карте цветов части."""
    out = dict(slots)
    for k, v in clr_map(pkg, part).items():
        if v in slots:
            out[k] = slots[v]
    return out


def _with_mods(h: Optional[str], el: etree._Element) -> Optional[str]:
    """Модификаторы цвета (lumMod, lumOff, satMod, tint, shade) — как их применяет PowerPoint (accent6 с lumMod 20 %
    и lumOff 80 % — почти белый, а не цвет акцента)."""
    if not h or not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        return h
    import colorsys

    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    rgb = (r, g, b)
    for ch in el:
        tag, val = etree.QName(ch).localname, ch.get("val")
        try:
            v = int(val) / 100000.0 if val is not None else None
        except ValueError:
            v = None
        if v is None:
            continue
        if tag == "lumMod":
            ll = max(0.0, min(1.0, ll * v))
            rgb = colorsys.hls_to_rgb(hh, ll, ss)
        elif tag == "lumOff":
            ll = max(0.0, min(1.0, ll + v))
            rgb = colorsys.hls_to_rgb(hh, ll, ss)
        elif tag == "satMod":
            ss = max(0.0, min(1.0, ss * v))
            rgb = colorsys.hls_to_rgb(hh, ll, ss)
        elif tag == "tint":
            rgb = tuple(c * v + (1 - v) for c in rgb)
            hh, ll, ss = colorsys.rgb_to_hls(*rgb)
        elif tag == "shade":
            rgb = tuple(c * v for c in rgb)
            hh, ll, ss = colorsys.rgb_to_hls(*rgb)
    return "".join(f"{max(0, min(255, int(round(c * 255)))):02X}" for c in rgb)


def _fill_hex(el: Optional[etree._Element], slots: dict[str, str]) -> Optional[str]:
    """Цвет заливки: srgbClr или цвет темы с модификаторами; градиент — по первой точке; картинка — None."""
    if el is None:
        return None
    for c in el.iter(_SRGB, f"{{{A}}}schemeClr", f"{{{A}}}sysClr", f"{{{A}}}blipFill"):
        tag = etree.QName(c).localname
        if tag == "blipFill":
            return None
        if tag == "srgbClr":
            return _with_mods((c.get("val") or "").upper() or None, c)
        if tag == "sysClr":
            return _with_mods((c.get("lastClr") or "").upper() or None, c)
        v = c.get("val") or ""
        return _with_mods(slots.get(v) or slots.get(_CLR_MAP.get(v, v)), c)
    return None


_FILLS = ("solidFill", "gradFill", "blipFill", "pattFill")


def _filled(sp: etree._Element) -> bool:
    """У фигуры есть видимая заливка (своя или из стиля темы)."""
    pr = sp.find(f"{{{P}}}spPr")
    if pr is not None:
        for ch in pr:
            name = etree.QName(ch).localname
            if name in _FILLS:
                return True
            if name == "noFill":
                return False
    ref = sp.find(f"{{{P}}}style/{{{A}}}fillRef")
    return ref is not None and (ref.get("idx") or "0") not in ("0", "")


def part_bg(pkg: Package, part: str, slots: dict[str, str], depth: int = 0) -> Optional[str]:
    """Цвет фона части: свой `p:bg`, иначе — макета, иначе — мастера."""
    root = pkg.xml(part)
    if root is None or depth > 2:
        return None
    bg = root.find(f"{{{P}}}cSld/{{{P}}}bg")
    if bg is not None:
        pr = bg.find(f"{{{P}}}bgPr")
        return _fill_hex(pr if pr is not None else bg.find(f"{{{P}}}bgRef"), slots)
    for kind in ("slideLayout", "slideMaster"):
        nxt = pkg.related(part, kind)
        if nxt:
            return part_bg(pkg, nxt, slots, depth + 1)
    return None


def _chain(pkg: Package, part: str) -> list[str]:
    """Часть, её макет и мастер — сверху вниз по слоям."""
    out = [part]
    for kind in ("slideLayout", "slideMaster"):
        nxt = pkg.related(out[-1], kind)
        if nxt and nxt not in out:
            out.append(nxt)
    return out


def _picture_under(pkg: Package, part: str, pic: etree._Element, pbox: Box, box: Box) -> Optional[tuple[float, float]]:
    """(L* видимых точек, доля непрозрачных) картинки там, где стоит рамка `box`."""
    blip = pic.find(f"{{{P}}}blipFill/{{{A}}}blip")
    rid = blip.get(f"{{{R}}}embed") if blip is not None else None
    media = pkg.rels(part).get(rid or "", ("", None))[1]
    if not media or not pkg.has(media):
        return None
    try:
        import numpy as np
        from PIL import Image

        im = Image.open(io.BytesIO(pkg.read(media))).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    px, py, pw, ph = pbox
    x, y, w, h = box
    if pw <= 0 or ph <= 0:
        return None
    l = max(0.0, (x - px) / pw) * im.width
    t = max(0.0, (y - py) / ph) * im.height
    r = min(1.0, (x + w - px) / pw) * im.width
    b = min(1.0, (y + h - py) / ph) * im.height
    if r - l < 1 or b - t < 1:
        return None
    reg = np.asarray(im.crop((int(l), int(t), int(math.ceil(r)), int(math.ceil(b)))).convert("RGBA"), dtype=float).reshape(-1, 4)
    alpha = reg[:, 3] / 255.0
    opaque = float(alpha.mean())
    if opaque < 0.05:
        return 0.0, opaque
    rgb = (reg[:, :3] * alpha[:, None]).sum(axis=0) / max(alpha.sum(), 1e-6)
    return lightness("".join(f"{int(round(v)):02X}" for v in rgb)), opaque


def ground_under(pkg: Package, part: str, box: Box, slots: dict[str, str]) -> str:
    """light / dark — настоящий цвет под рамкой (см. `_xml_spot`)."""
    return _xml_spot(pkg, part, box, slots, with_part=True).ground


def _xml_spot(pkg: Package, part: str, box: Box, slots: dict[str, str], *, with_part: bool) -> "Spot":
    """Что под рамкой — по самому файлу: верхняя залитая фигура или картинка (слайд, если `with_part`, его макет,
    мастер; `showMasterSp="0"` скрывает нижние слои), иначе фон-фото, иначе цвет фона. Цвета темы — по карте цветов
    части (тёмный макет с `overrideClrMapping`)."""
    ps = part_slots(pkg, part, slots)
    chain = _chain(pkg, part)
    for k, p in enumerate(chain):
        root = pkg.xml(p)
        tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
        if tree is not None and (with_part or k > 0):
            for el in reversed(list(tree)):
                b = shape_box(el)
                if not b or overlap(b, box) < 0.5 * box[2] * box[3]:
                    continue
                tag = etree.QName(el).localname
                if tag == "pic":
                    got = _picture_under(pkg, p, el, b, box)
                    if got and got[1] >= 0.5:
                        return Spot(got[0])
                elif tag == "sp" and _filled(el):
                    h = _fill_hex(el.find(f"{{{P}}}spPr"), ps)
                    if h and re.fullmatch(r"[0-9A-F]{6}", h):
                        return Spot(lightness(h))
        if root is not None and root.get("showMasterSp") in ("0", "false"):
            break
    photo = _bg_photo_under(pkg, part, box)
    if photo is not None:
        return photo
    bg = part_bg(pkg, part, ps)
    if bg and re.fullmatch(r"[0-9A-F]{6}", bg):
        return Spot(lightness(bg))
    return Spot(95.0)


def _ground_of_lockup(pkg: Package, group: list[Pic], slots: dict[str, str]) -> str:
    """Фон под логотипом шаблона — по самому логотипу (белая надпись стоит на тёмном), иначе по цвету под ним."""
    inks = [pr[2] for pr in (image_probe(pkg.read(pc.media)) for pc in group if pc.media and pkg.has(pc.media)) if pr]
    if "light" in inks:
        return "dark"
    if "dark" in inks:
        return "light"
    return ground_under(pkg, group[0].part, _union([g.box for g in group]), slots) if group else "light"


# ============================================================================================ логотипы шаблона


def find_template_logos(pkg: Package, manifest: Optional[TemplateManifest] = None, slots: Optional[dict[str, str]] = None) -> list[Lockup]:
    sw, sh = pkg.slide_size()
    slots = slots or {}
    parts = [n for n in pkg.names() if _LOGO_PART_RE.match(n)]
    pics = {p: pics_of(pkg, p) for p in parts}

    def small(pc: Pic) -> bool:
        x, y, w, h = pc.box
        return 0 < w <= 0.3 * sw and 0 < h <= 0.2 * sh and w * h <= 0.03 * sw * sh

    def band(pc: Pic) -> bool:
        x, y, w, h = pc.box
        return y <= 0.22 * sh or y + h >= 0.78 * sh

    probes = {m: image_probe(pkg.read(m)) for m in {pc.media for lst in pics.values() for pc in lst if pc.media and small(pc) and pkg.has(pc.media)}}

    def logo_like(m: Optional[str]) -> bool:
        pr = probes.get(m or "")
        return bool(pr) and pr[2] != "empty" and pr[3] and pr[4]

    seeds: set[str] = set()
    if manifest is not None:
        # логотип по разбору — только плоская картинка на прозрачном фоне: «логотипом» разбор называет и макет
        # телефона, повторённый на слайдах
        for a in manifest.assets:
            if a.media_part and (a.kind == "logo" or any(re.search(r"logo|логотип", t, re.I) for t in a.tags)) and logo_like(a.media_part):
                seeds.add(a.media_part)
    for lst in pics.values():
        for pc in lst:
            if pc.media and small(pc) and _LOGO_NAME_RE.search(pc.name + " " + posixpath.basename(pc.media)):
                seeds.add(pc.media)
    on_layouts: dict[str, set[str]] = {}
    for part, lst in pics.items():
        if "/slides/" in part:
            continue
        for pc in lst:
            if pc.media and small(pc) and band(pc) and logo_like(pc.media):
                on_layouts.setdefault(pc.media, set()).add(part)
    seeds |= {m for m, ps in on_layouts.items() if len(ps) >= 2}
    seed_probes = [probes.get(m) or (image_probe(pkg.read(m)) if pkg.has(m) else None) for m in seeds]
    for m, pr in probes.items():
        if m not in seeds and any(same_picture(pr, sp) for sp in seed_probes):
            seeds.add(m)
    if not seeds:
        return []

    lockups: list[Lockup] = []
    for part, lst in pics.items():
        cand = [pc for pc in lst if small(pc)]
        used: set[int] = set()
        for pc in cand:
            if id(pc.el) in used or pc.media not in seeds:
                continue
            group = [pc]
            used.add(id(pc.el))
            grew = True
            while grew:
                grew = False
                ux, uy, uw, uh = _union([g.box for g in group])
                for o in cand:
                    if id(o.el) in used:
                        continue
                    ox, oy, ow, oh = o.box
                    inter_h = max(0.0, min(uy + uh, oy + oh) - max(uy, oy))
                    inside = overlap((ux, uy, uw, uh), o.box) >= 0.5 * ow * oh
                    gap = max(ox - (ux + uw), ux - (ox + ow), 0.0)
                    row = inter_h >= 0.5 * min(uh, oh) and gap <= 1.2 * max(uh, oh) and oh <= 1.6 * uh
                    if inside or row:
                        group.append(o)
                        used.add(id(o.el))
                        grew = True
            box = _union([g.box for g in group])
            dup = any(lk.part == part and _iou(lk.box, box) >= 0.9 for lk in lockups)
            lockups.append(Lockup(part=part, pics=group, box=box, ground=_ground_of_lockup(pkg, group, slots), duplicate=dup))
    return lockups


_HAS_LOGO: dict[tuple, bool] = {}


def has_template_logo(src: Path | str, manifest: Optional[TemplateManifest] = None) -> bool:
    """В шаблоне есть логотип-картинка (для расхождений); кэш по файлу и разбору."""
    from verstka.brand.palette import file_key, package_theme

    key = file_key(src)
    mkey = (key, manifest.template_id if manifest else None)
    if key is not None and mkey in _HAS_LOGO:
        return _HAS_LOGO[mkey]
    try:
        pkg = Package(src)
        got = any(not lk.duplicate for lk in find_template_logos(pkg, manifest, package_theme(pkg).slots))
    except Exception as e:  # noqa: BLE001
        log.warning("template logos not found: %s", e)
        got = bool(manifest and any(a.kind == "logo" for a in manifest.assets))
    if key is not None:
        if len(_HAS_LOGO) > 64:
            _HAS_LOGO.clear()
        _HAS_LOGO[mkey] = got
    return got


# ============================================================================================ логотипы бренда


@dataclass
class BrandImage:
    logo: BrandLogo
    data: bytes
    ext: str
    size: tuple[int, int]
    crop: tuple[float, float, float, float]  # l, t, r, b — доли прозрачных полей

    @property
    def aspect(self) -> float:
        w = self.size[0] * (1 - self.crop[0] - self.crop[2])
        h = self.size[1] * (1 - self.crop[1] - self.crop[3])
        return w / h if h else 1.0

    @property
    def mark(self) -> bool:
        return self.aspect < 1.6


def logo_path(logo: BrandLogo, brand_dir: Optional[Path | str]) -> Optional[Path]:
    """Файл логотипа — только внутри папки брендбука: без абсолютных путей и «..» (BrandSpec может прийти из API)."""
    if not brand_dir:
        return None
    rel = PurePosixPath(str(logo.file).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or re.match(r"^[A-Za-z]:", str(logo.file)):
        return None
    base = Path(brand_dir).resolve()
    p = (base / Path(*rel.parts)).resolve()
    return p if p.is_relative_to(base) else None


def _raster(path: Path) -> Optional[tuple[bytes, str]]:
    """PNG/JPEG как есть; SVG — соседний PNG с тем же именем, иначе растр через rsvg-convert (если есть)."""
    ext = path.suffix.lower().lstrip(".")
    if ext in ("png", "jpg", "jpeg"):
        return path.read_bytes(), ("jpeg" if ext == "jpg" else ext)
    if ext == "svg":
        twin = path.with_suffix(".png")
        if twin.exists():
            return twin.read_bytes(), "png"
        exe = shutil.which("rsvg-convert")
        if exe:
            try:
                res = subprocess.run([exe, "-h", "512", str(path)], capture_output=True, timeout=20)
                if res.returncode == 0 and res.stdout:
                    return res.stdout, "png"
            except Exception:  # noqa: BLE001
                return None
    return None


def load_logo(logo: BrandLogo, brand_dir: Optional[Path | str]) -> Optional[BrandImage]:
    p = logo_path(logo, brand_dir)
    if p is None or not p.exists():
        return None
    got = _raster(p)
    if not got:
        return None
    data, ext = got
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        size = im.size
        bbox = im.convert("RGBA").getchannel("A").getbbox() if im.mode in ("RGBA", "LA", "P") else None
    except Exception:  # noqa: BLE001
        return None
    crop = (0.0, 0.0, 0.0, 0.0)
    if bbox and size[0] and size[1]:
        crop = (bbox[0] / size[0], bbox[1] / size[1], 1 - bbox[2] / size[0], 1 - bbox[3] / size[1])
    return BrandImage(logo=logo, data=data, ext=ext, size=size, crop=crop)


def pick_logo(images: list[BrandImage], ground: str, mark: bool) -> Optional[BrandImage]:
    """Логотип бренда для места: знак — в квадратную рамку; на тёмном фоне — белый вариант, на светлом — основной."""
    if not images:
        return None

    def by(pred) -> Optional[BrandImage]:
        return next((im for im in images if pred(im.logo)), None)

    if mark:
        hit = by(lambda lg: lg.variant == "mark")
        if hit:
            return hit
    if ground == "dark":
        order = [
            lambda lg: lg.variant == "white",
            lambda lg: lg.ground == "dark" and lg.variant != "mark",
            lambda lg: lg.variant == "mark",
            lambda lg: lg.ground == "any" and lg.variant == "primary",
        ]
    else:
        order = [
            lambda lg: lg.variant == "primary" and lg.ground in ("light", "any"),
            lambda lg: lg.variant == "mono",
            lambda lg: lg.ground in ("light", "any") and lg.variant != "mark",
            lambda lg: lg.variant == "mark",
        ]
    for pred in order:
        hit = by(pred)
        if hit:
            return hit
    return None


def _fit(box: Box, img: BrandImage, sw: float, sh: float) -> Box:
    """Логотип бренда в рамке логотипа шаблона: высота — как у рамки (ширина — до FIT_GROW её), но не меньше читаемой;
    прижат к той стороне, у которой стоит рамка."""
    x, y, w, h = box
    aspect = img.aspect
    nh = min(h, w * FIT_GROW / aspect)
    nh = max(nh, (MIN_MARK_H if img.mark else MIN_WORDMARK_H) * sh)
    nw = nh * aspect
    cx = x + w / 2
    if cx < 0.4 * sw:
        nx = x
    elif cx > 0.6 * sw:
        nx = x + w - nw
    else:
        nx = x + (w - nw) / 2
    ny = y + (h - nh) / 2
    return max(0.0, min(nx, sw - nw)), max(0.0, min(ny, sh - nh)), nw, nh


class Media:
    """Файлы логотипов бренда в пакете — по одному на картинку."""

    def __init__(self, pkg: Package) -> None:
        self.pkg = pkg
        self.parts: dict[int, str] = {}

    def part_for(self, img: BrandImage) -> str:
        key = id(img)
        if key not in self.parts:
            digest = hashlib.sha256(img.data).hexdigest()[:8]
            name = f"ppt/media/brand-logo-{img.logo.variant}-{digest}.{img.ext}"
            self.pkg.added[name] = img.data
            self.pkg.ensure_default_type(img.ext, "image/png" if img.ext == "png" else "image/jpeg")
            self.parts[key] = name
        return self.parts[key]


def _set_box(pic: etree._Element, groups: list[etree._Element], box: Box) -> None:
    x, y, w, h = to_local(box, groups)
    xfrm = pic.find(f"{{{P}}}spPr/{{{A}}}xfrm")
    off, ext = xfrm.find(f"{{{A}}}off"), xfrm.find(f"{{{A}}}ext")
    off.set("x", str(int(round(x))))
    off.set("y", str(int(round(y))))
    ext.set("cx", str(max(1, int(round(w)))))
    ext.set("cy", str(max(1, int(round(h)))))


def _set_blip(pic: etree._Element, rid: str, img: BrandImage, brand_name: str) -> None:
    blip_fill = pic.find(f"{{{P}}}blipFill")
    blip = blip_fill.find(f"{{{A}}}blip")
    for ch in list(blip):  # перекраска, дуотон, SVG-версия старого логотипа — не к логотипу бренда
        if etree.QName(ch).localname != "alphaModFix":
            blip.remove(ch)
    for attr in list(blip.attrib):
        if attr.startswith(f"{{{R}}}"):
            del blip.attrib[attr]
    blip.set(f"{{{R}}}embed", rid)
    for ch in list(blip_fill):
        if ch is not blip:
            blip_fill.remove(ch)
    if any(v > 0.001 for v in img.crop):
        src = etree.SubElement(blip_fill, f"{{{A}}}srcRect")
        for k, v in zip(("l", "t", "r", "b"), img.crop):
            if v > 0.001:
                src.set(k, str(int(round(v * 100000))))
    etree.SubElement(etree.SubElement(blip_fill, f"{{{A}}}stretch"), f"{{{A}}}fillRect")
    nv = pic.find(f"{{{P}}}nvPicPr/{{{P}}}cNvPr")
    if nv is not None:
        label = f"Логотип {brand_name}".strip()
        nv.set("name", label)
        nv.set("descr", label)
        for ch in list(nv):  # ссылка старого логотипа
            nv.remove(ch)


def _new_pic(pkg: Package, part: str, rid: str, img: BrandImage, box: Box, brand_name: str) -> etree._Element:
    root = pkg.xml(part)
    ids = [int(e.get("id")) for e in root.iter(f"{{{P}}}cNvPr") if (e.get("id") or "").isdigit()]
    pic = etree.fromstring(
        f'<p:pic xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:nvPicPr><p:cNvPr id="{max(ids, default=1) + 1}" name="" descr=""/>'
        f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr userDrawn="1"/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )
    _set_blip(pic, rid, img, brand_name)
    pic.find(f"{{{P}}}nvPicPr/{{{P}}}cNvPr").set("title", BRAND_LOGO_MARK)
    _set_box(pic, [], box)
    return pic


def _slot(box: Box, sw: float, sh: float) -> tuple[str, str]:
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    return ("l" if cx < 0.4 * sw else ("r" if cx > 0.6 * sw else "c")), ("t" if cy < 0.5 * sh else "b")


def _main_lockups(lockups: list[Lockup], place: Optional[str], sw: float, sh: float) -> set[int]:
    """На каждой части — один логотип бренда: из нескольких логотипов шаблона (свой и партнёра) остаётся тот, чьё место
    у шаблона встречается на большинстве частей (логотип не прыгает между сторонами), затем — ближе к месту из
    брендбука, затем — крупнее."""
    by_part: dict[str, list[Lockup]] = {}
    for lk in lockups:
        if not lk.duplicate:
            by_part.setdefault(lk.part, []).append(lk)
    votes: Counter = Counter()
    for lst in by_part.values():
        for s in {_slot(lk.box, sw, sh) for lk in lst}:
            votes[s] += 1
    cx = sw if (place or "").endswith("right") else 0.0
    cy = sh if (place or "").startswith("bottom") else 0.0
    keep: set[int] = set()
    for lst in by_part.values():
        best = min(
            lst,
            key=lambda lk: (
                -votes[_slot(lk.box, sw, sh)],
                math.hypot(lk.box[0] + lk.box[2] / 2 - cx, lk.box[1] + lk.box[3] / 2 - cy) if place else 0.0,
                -lk.box[2] * lk.box[3],
            ),
        )
        keep.add(id(best))
    return keep


def replace_logos(pkg: Package, lockups: list[Lockup], images: list[BrandImage], brand_name: str, warnings: list[str], place: Optional[str] = None) -> tuple[int, int]:
    """(заменено, убрано) логотипов шаблона."""
    sw, sh = pkg.slide_size()
    media = Media(pkg)
    main = _main_lockups(lockups, place, sw, sh)
    done = removed = 0
    missing = False
    for lk in lockups:
        if lk.duplicate or id(lk) not in main:
            removed += 0 if lk.duplicate else 1
            for pc in lk.pics:
                if pc.el.getparent() is not None:
                    pc.el.getparent().remove(pc.el)
            pkg.dirty.add(lk.part)
            continue
        x, y, w, h = lk.box
        img = pick_logo(images, lk.ground, mark=w / h < 1.6 if h else False)
        if img is None:
            missing = True
            continue
        keep = lk.pics[0]
        rid = pkg.add_rel(lk.part, IMG_REL, media.part_for(img))
        _set_blip(keep.el, rid, img, brand_name)
        _set_box(keep.el, keep.groups, _fit(lk.box, img, sw, sh))
        for pc in lk.pics[1:]:
            if pc.el.getparent() is not None:
                pc.el.getparent().remove(pc.el)
        pkg.dirty.add(lk.part)
        done += 1
    if missing:
        warnings.append("Для части логотипов шаблона не нашлось подходящего варианта логотипа бренда — там оставлен логотип шаблона.")
    return done, removed


# ============================================================================================ добавление логотипа
# Препятствия и фон — по IR аудита исходного шаблона (`verstka.audit.ir`): рамки заполнителей там уже взяты из макета и
# мастера, у слоёв макета и мастера — их настоящая краска (градиент, картинка, «пёстрость» фото), у фона — цвет с
# модификаторами. Тот же IR смотрит и независимая проверка столкновений.

_FOOTER_PH = ("sldNum", "ftr", "dt")
BUSY_STD = 40.0  # «пёстрое» фото (как у IR: стандартное отклонение яркости точек > 40) — логотип на нём не читается
BUSY_CELLS = 20.0  # то же по сетке IR (среднее отклонение клеток в рамке): конфеты lo_candy — 30, спокойный фон — < 10


@dataclass
class Spot:
    """Что лежит под рамкой логотипа: светлота (L*), пёстрость, и можно ли туда ставить."""

    lightness: float
    busy: bool = False

    @property
    def ground(self) -> str:
        return "dark" if self.lightness < 55 else "light"


def _ebox(e) -> Box:
    return float(e.bbox.x), float(e.bbox.y), float(e.bbox.w), float(e.bbox.h)


def _full(e, sw: float, sh: float) -> bool:
    return e.bbox.w * e.bbox.h >= 0.85 * sw * sh


def _cells_under(e, box: Box) -> Optional[Spot]:
    """Светлота и пёстрость картинки (или градиента) IR в рамке — по сетке `cells`."""
    c = getattr(e, "cells", None)
    if c is None or not c.w or not c.h or not c.hex:
        return None
    ex, ey, ew, eh = _ebox(e)
    cw, ch = ew / c.w, eh / c.h
    acc = [0.0, 0.0, 0.0]
    wsum = std = 0.0
    for j in range(c.h):
        for i in range(c.w):
            k = j * c.w + i
            o = overlap((ex + i * cw, ey + j * ch, cw, ch), box)
            if o <= 0 or k >= len(c.hex):
                continue
            a = c.alpha[k] if k < len(c.alpha) else 1.0
            wgt = o * a
            if wgt <= 0:
                continue
            h = c.hex[k]
            for t in range(3):
                acc[t] += int(h[2 * t:2 * t + 2], 16) * wgt
            std += (c.std[k] if k < len(c.std) else 0.0) * wgt
            wsum += wgt
    if wsum <= 0 or wsum < 0.5 * box[2] * box[3]:
        return None
    hexv = "".join(f"{int(round(v / wsum)):02X}" for v in acc)
    return Spot(lightness(hexv), busy=std / wsum > BUSY_CELLS)


def _bg_photo_under(pkg: Package, part: str, box: Box) -> Optional[Spot]:
    """Фон-фото (`p:bg` с картинкой) части, её макета или мастера — настоящие точки под рамкой."""
    sw, sh = pkg.slide_size()
    for p in _chain(pkg, part):
        root = pkg.xml(p)
        bg = root.find(f"{{{P}}}cSld/{{{P}}}bg") if root is not None else None
        if bg is None:
            continue
        blip = bg.find(f".//{{{A}}}blip")
        if blip is None:
            return None  # свой фон без картинки — его цвет даёт IR
        rid = blip.get(f"{{{R}}}embed")
        media = pkg.rels(p).get(rid or "", ("", None))[1]
        if not media or not pkg.has(media):
            return None
        import numpy as np

        cache = pkg.__dict__.setdefault("_bg_images", {})
        if media not in cache:
            try:
                from PIL import Image

                im = Image.open(io.BytesIO(pkg.read(media))).convert("RGB")
                im.thumbnail((640, 640))
                cache[media] = im
            except Exception:  # noqa: BLE001
                cache[media] = None
        im = cache[media]
        if im is None:
            return None
        x, y, w, h = box
        crop = im.crop((int(x / sw * im.width), int(y / sh * im.height), max(int(x / sw * im.width) + 1, int((x + w) / sw * im.width)),
                        max(int(y / sh * im.height) + 1, int((y + h) / sh * im.height))))
        arr = np.asarray(crop, dtype=float).reshape(-1, 3)
        mean = arr.mean(axis=0)
        lum = arr @ np.array([0.299, 0.587, 0.114])
        return Spot(lightness("".join(f"{int(round(v)):02X}" for v in mean)), busy=float(lum.std()) > BUSY_STD)
    return None


def _spot(pkg: Package, part: str, slide, box: Box, *, with_slide: bool) -> Spot:
    """Что под рамкой: верхний слой во весь слайд (картинка, градиент, заливка — слайда, если логотип на слайде, затем
    макета и мастера), иначе фон-фото, иначе цвет фона слайда (с модификаторами цвета темы). IR красит цвета темы по
    карте мастера; у слайда с другой картой (тёмный макет с `overrideClrMapping`) — по самому файлу."""
    sw, sh = pkg.slide_size()
    if {k: v for k, v in clr_map(pkg, part).items() if k in _CLR_MAP} != {k: v for k, v in master_map(pkg, part).items() if k in _CLR_MAP}:
        return _xml_spot(pkg, part, box, package_slots(pkg), with_part=with_slide)
    layers = (list(slide.elements) if with_slide else []) + list(slide.template_elements)
    for e in sorted((e for e in layers if _full(e, sw, sh) or overlap(_ebox(e), box) >= 0.9 * box[2] * box[3]), key=lambda e: (e.source == "slide", e.z), reverse=True):
        got = _cells_under(e, box)
        if got is not None:
            return got
        if e.fill_hex and getattr(e, "opaque", True) and e.type in ("shape", "text", "picture"):
            return Spot(lightness(e.fill_hex), busy=bool(getattr(e, "busy", False)))
    got = _bg_photo_under(pkg, part, box)
    if got is not None:
        return got
    if slide.background_hex:
        return Spot(lightness(slide.background_hex), busy=False)
    return Spot(95.0)


_HARD_PH = ("title", "ctrTitle", "sldNum", "ftr", "dt")


def _ir_obstacles(slide, sw: float, sh: float, *, under_slide: bool) -> tuple[list[Box], list[tuple[Box, str]]]:
    """(жёсткие препятствия, заполнители содержимого) под рамку логотипа. Жёсткие — тексты, линии, контуры, фигуры,
    картинки, таблицы, диаграммы, группы слайда и его макета и мастера, заголовки и колонтитулы; заполнители
    содержимого (текст, объект, картинка, таблица; рамка — из макета и мастера) логотип может «подвинуть»: их рамка
    уменьшается, оставляя логотипу охранное поле. Фон во весь слайд — не препятствие, если логотип лежит поверх
    (`under_slide=False`); логотип макета лежит под фигурами слайда — тогда непрозрачная картинка или заливка слайда во
    весь слайд его закрывает."""
    hard: list[Box] = []
    soft: list[tuple[Box, str]] = []
    for e in list(slide.elements) + list(slide.template_elements):
        own = e.source == "slide"
        if e.type == "shape" and e.line_hex and not e.fill_hex and e.geometry != "custom" and not (own and e.is_placeholder):
            # рамка-контур (в том числе во весь слайд, как у «Классики»): мешают её края, а не то, что внутри
            hard += _edges(_ebox(e), sw)
            continue
        if _full(e, sw, sh):
            if under_slide and own and (e.fill_hex or e.type == "picture") and getattr(e, "opaque", True):
                hard.append(_ebox(e))
            continue
        if own and e.is_placeholder and (e.ph_type or "body") not in _HARD_PH and e.type in ("text", "shape"):
            # рамка текста отступает; таблица, диаграмма, картинка в заполнителе — уже содержимое, препятствие
            soft.append((_ebox(e), e.id))
            continue
        if e.type == "shape" and not e.fill_hex and not e.line_hex and e.geometry != "custom":
            continue  # пустая рамка без заливки и обводки (контур — `line_hex`, произвольная фигура — препятствие всегда)
        hard.append(_ebox(e))
    return hard, soft


class Thin(tuple):
    """Линия или край рамки — тонкая полоса с допуском толщины `tol`: охранное поле логотипа от неё то же, что от
    карточки, но допуск в него уже входит."""

    tol: float

    def __new__(cls, box, tol: float):
        o = super().__new__(cls, box)
        o.tol = tol
        return o


def _thin(b: Box, tol: float) -> "Thin":
    return Thin((b[0] - tol, b[1] - tol, b[2] + 2 * tol, b[3] + 2 * tol), tol)


def _edges(b: Box, sw: float) -> list[Box]:
    """Четыре края рамки — тонкие полосы (с допуском толщины линии)."""
    t = 0.004 * sw
    x, y, w, h = b
    return [_thin((x, y, w, 0), t), _thin((x, y + h, w, 0), t), _thin((x, y, 0, h), t), _thin((x + w, y, 0, h), t)]


CLEAR = 0.01  # охранное поле логотипа — доля высоты слайда: ни карточка, ни текст не подходят к нему ближе


def _padded(box: Box, pad: float) -> Box:
    return box[0] - pad, box[1] - pad, box[2] + 2 * pad, box[3] + 2 * pad


def _shrunk(frame: Box, logo: Box, sh: float) -> Optional[Box]:
    """Рамка заполнителя, отступившая от логотипа (охранное поле) — сверху, снизу или сбоку; не больше чем на 30 %
    высоты или 25 % ширины. None — так не получится."""
    if overlap(frame, _padded(logo, CLEAR * sh)) <= 0.03 * logo[2] * logo[3]:
        return frame
    gap = 0.012 * sh
    x, y, w, h = frame
    lx, ly, lw, lh = logo
    opts = []
    if ly >= y + 0.4 * h and ly - gap - y >= 0.7 * h:
        opts.append((x, y, w, ly - gap - y))
    if ly + lh <= y + 0.6 * h and y + h - (ly + lh + gap) >= 0.7 * h:
        opts.append((x, ly + lh + gap, w, y + h - (ly + lh + gap)))
    if lx >= x + 0.4 * w and lx - gap - x >= 0.75 * w:
        opts.append((x, y, lx - gap - x, h))
    if lx + lw <= x + 0.6 * w and x + w - (lx + lw + gap) >= 0.75 * w:
        opts.append((lx + lw + gap, y, x + w - (lx + lw + gap), h))
    return max(opts, key=lambda b: b[2] * b[3]) if opts else None


def _set_frame(sp: etree._Element, box: Box) -> None:
    """Своя рамка заполнителя (вместо унаследованной или прежней)."""
    pr = sp.find(f"{{{P}}}spPr")
    if pr is None:
        pr = etree.SubElement(sp, f"{{{P}}}spPr")
        sp.insert(1, pr)
    xfrm = pr.find(f"{{{A}}}xfrm")
    if xfrm is None:
        xfrm = etree.Element(f"{{{A}}}xfrm")
        pr.insert(0, xfrm)
        etree.SubElement(xfrm, f"{{{A}}}off")
        etree.SubElement(xfrm, f"{{{A}}}ext")
    off, ext = xfrm.find(f"{{{A}}}off"), xfrm.find(f"{{{A}}}ext")
    off.set("x", str(int(round(box[0]))))
    off.set("y", str(int(round(box[1]))))
    ext.set("cx", str(max(1, int(round(box[2])))))
    ext.set("cy", str(max(1, int(round(box[3])))))


def _sp_by_id(pkg: Package, part: str, sid: str) -> Optional[etree._Element]:
    root = pkg.xml(part)
    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
    if tree is None:
        return None
    for nv in tree.iter(f"{{{P}}}cNvPr"):
        if nv.get("id") == sid:
            sp = nv.getparent().getparent()
            return sp if etree.QName(sp).localname == "sp" else None
    return None


def _resolved_frame(pkg: Package, part: str, sp: etree._Element) -> Optional[Box]:
    """Рамка заполнителя: своя, иначе — заполнителя мастера того же типа (номер, колонтитул, дата)."""
    b = shape_box(sp)
    if b is not None:
        return b
    ph = sp.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
    if ph is None:
        return None
    master = pkg.related(part, "slideMaster")
    root = pkg.xml(master) if master else None
    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
    if tree is None:
        return None
    want_type, want_idx = ph.get("type") or "body", ph.get("idx")
    for el in tree.iter(f"{{{P}}}sp"):
        mph = el.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
        if mph is not None and ((mph.get("type") or "body") == want_type or (want_idx and mph.get("idx") == want_idx)):
            return shape_box(el)
    return None


_FOOTER_ALIGN = {"sldNum": "r", "dt": "l", "ftr": "ctr"}
_FOOTER_CHARS = {"sldNum": 3, "dt": 10, "ftr": 12}


def _master_ph(pkg: Package, part: str, kind: str) -> Optional[etree._Element]:
    master = pkg.related(part, "slideMaster") if not part.startswith("ppt/slideMasters/") else part
    root = pkg.xml(master) if master else None
    if root is None:
        return None
    for el in root.iter(f"{{{P}}}sp"):
        ph = el.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
        if ph is not None and (ph.get("type") or "body") == kind:
            return el
    return None


def _first_attr(sps: list[Optional[etree._Element]], paths: tuple[str, ...], attr: str) -> Optional[str]:
    for sp in sps:
        if sp is None:
            continue
        for path in paths:
            for el in sp.iterfind(path, {"a": A, "p": P}):
                if el.get(attr):
                    return el.get(attr)
    return None


def _footer_text_box(pkg: Package, part: str, sp: etree._Element, frame: Box, kind: str) -> Box:
    """Где встанет текст колонтитула, когда его включат: у края рамки по её выравниванию (номер — справа, дата — слева,
    подпись — посередине, если рамка не говорит иного), шириной в свой текст (номер — 3 знака, дата — 10, подпись —
    своя, а пустая — короткая, 12 знаков) при своём кегле. На собранных слайдах колонтитулы пусты — логотипу место рядом с ними есть,
    пока он не заходит туда, где встанет их текст."""
    msp = _master_ph(pkg, part, kind)
    sps = [sp, msp]
    algn = _first_attr(sps, ("p:txBody/a:lstStyle/a:lvl1pPr", "p:txBody/a:p/a:pPr"), "algn") or _FOOTER_ALIGN.get(kind, "l")
    sz = _first_attr(sps, ("p:txBody/a:lstStyle/a:lvl1pPr/a:defRPr", "p:txBody/a:p/a:r/a:rPr", "p:txBody/a:p/a:fld/a:rPr", "p:txBody/a:p/a:endParaRPr"), "sz")
    try:
        pt = int(sz) / 100.0 if sz else 12.0
    except ValueError:
        pt = 12.0
    text = "".join(t.text or "" for t in sp.iter(f"{{{A}}}t")).strip()
    chars = 3 if kind == "sldNum" else max(len(text), _FOOTER_CHARS.get(kind, 10)) if kind == "dt" else (len(text) or _FOOTER_CHARS.get(kind, 12))
    ins = 0
    for k, d in (("lIns", 91440), ("rIns", 91440)):
        v = _first_attr(sps, ("p:txBody/a:bodyPr",), k)
        ins += int(v) if v and v.lstrip("-").isdigit() else d
    x, y, w, h = frame
    tw = min(w, chars * 0.6 * pt * 12700 + ins)
    if algn == "r":
        return x + w - tw, y, tw, h
    if algn == "ctr":
        return x + (w - tw) / 2, y, tw, h
    return x, y, tw, h


def _layout_obstacles(pkg: Package, layout: str) -> tuple[list[Box], list[tuple[Box, etree._Element]]]:
    """(жёсткие, заполнители содержимого макета): туда ляжет содержимое собранных слайдов (текст, картинка, таблица,
    кружок с номером); заголовки макета — жёсткие; колонтитулы макета и мастера — там, где встанет их текст, когда их
    включат. Рамки — у мастера, если своих нет."""
    hard: list[Box] = []
    soft: list[tuple[Box, etree._Element]] = []
    for part in (layout, pkg.related(layout, "slideMaster")):
        root = pkg.xml(part) if part else None
        tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
        if tree is None:
            continue
        for sp in tree.iter(f"{{{P}}}sp"):
            ph = sp.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
            kind = (ph.get("type") or "body") if ph is not None else None
            if ph is None or (part != layout and kind not in _FOOTER_PH):
                continue
            b = _resolved_frame(pkg, part, sp)
            if b is None:
                continue
            if kind in _FOOTER_PH:
                hard.append(_footer_text_box(pkg, part, sp, b, kind))
            elif part == layout and kind not in _HARD_PH:
                soft.append((b, sp))
            else:
                hard.append(b)
    return hard, soft


def _clear(box: Box, obstacles: list[Box], pad: float = 0.0) -> bool:
    """Ни одно препятствие не заходит в рамку с охранным полем `pad` (допуск — 3 % площади логотипа)."""
    area = 0.03 * box[2] * box[3]
    big = _padded(box, pad)
    for o in obstacles:
        tol = getattr(o, "tol", 0.0)
        if overlap(o, big if not tol else _padded(box, max(0.0, pad - tol))) > area:
            return False
    return True


SMALLER = 0.85  # запасной размер логотипа: 0,045 → 0,038 высоты слайда — всё ещё крупнее читаемого минимума


def _smaller(corner: str, box: Box, k: float) -> Box:
    """Та же рамка, уменьшенная в `k` раз, прижатая к тому же углу."""
    x, y, w, h = box
    w2, h2 = w * k, h * k
    return (x if corner.endswith("left") else x + w - w2, y if corner.startswith("top") else y + h - h2, w2, h2)


def _candidates(place: LogoPlace, w: float, h: float, margin: float, sw: float, sh: float) -> list[tuple[str, str, Box]]:
    """(угол, где, рамка): угол из брендбука (`corner`), шагами вдоль края к середине (`edge`), затем над полосой
    колонтитула (`lifted`), потом — тот же край с другой стороны, другой край и противоположный угол: одно запасное
    место на весь шаблон, если угол брендбука занят."""
    out: list[tuple[str, str, Box]] = []
    corners = [place]
    v, hside = place.split("_")
    other_h = "left" if hside == "right" else "right"
    other_v = "top" if v == "bottom" else "bottom"
    corners += [f"{v}_{other_h}", f"{other_v}_{hside}", f"{other_v}_{other_h}"]
    for corner in corners:
        left, top = corner.endswith("left"), corner.startswith("top")
        y0 = margin if top else sh - margin - h
        xs = []
        for k in range(0, 7):
            x = margin + k * 0.5 * w if left else sw - margin - w - k * 0.5 * w
            if x < margin - 1 or x + w > sw - margin + 1 or (left and x + w > 0.5 * sw) or (not left and x < 0.5 * sw):
                break
            xs.append(x)
        out += [(corner, "corner" if k == 0 else "edge", (x, y0, w, h)) for k, x in enumerate(xs)]
        for j in range(1, 5):
            y = y0 + j * 0.6 * h if top else y0 - j * 0.6 * h
            if (top and y + h > 0.2 * sh) or (not top and y < 0.8 * sh):
                break
            out += [(corner, "lifted", (x, y, w, h)) for x in xs[:3]]
    return out


_CORNER_RU = {"bottom_right": "правом нижнем", "bottom_left": "левом нижнем", "top_right": "правом верхнем", "top_left": "левом верхнем"}
_CORNER_NEAR_RU = {"bottom_right": "правым нижним", "bottom_left": "левым нижним", "top_right": "правым верхним", "top_left": "левым верхним"}


def logo_where(place: str, corner: str, kind: str) -> str:
    """Где встал логотип — словами для предупреждения: в углу из брендбука, у того же края ближе к середине, рядом с
    углом (выше или ниже) или в другом углу."""
    if corner == place:
        if kind == "corner":
            return "в углу из брендбука"
        if kind == "edge":
            return f"у {'верхнего' if corner.startswith('top') else 'нижнего'} края ближе к середине: в самом углу из брендбука занято"
        return f"{'чуть ниже' if corner.startswith('top') else 'чуть выше'} угла из брендбука: в самом углу занято"
    if kind == "corner":
        return f"в {_CORNER_RU[corner]} углу: угол из брендбука занят"
    if kind == "edge":
        side = "левой" if corner.endswith("left") else "правой"
        return f"у {'верхнего' if corner.startswith('top') else 'нижнего'} края, в {side} половине: угол из брендбука занят"
    return f"рядом с {_CORNER_NEAR_RU[corner]} углом: угол из брендбука занят"


def package_slots(pkg: Package) -> dict[str, str]:
    from verstka.brand.palette import package_theme

    return package_theme(pkg).slots


def _part_shapes(pkg: Package, part: Optional[str]) -> list[Box]:
    """Видимые фигуры части без заполнителей (рисунок макета или мастера): заливка, обводка, текст, картинка, линия,
    таблица, группа; фон во весь слайд — нет."""
    root = pkg.xml(part) if part else None
    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
    if tree is None:
        return []
    sw, sh = pkg.slide_size()
    out: list[Box] = []
    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("sp", "pic", "cxnSp", "graphicFrame", "grpSp"):
            continue
        if tag == "sp" and el.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph") is not None:
            continue
        b = shape_box(el)
        if not b:
            continue
        if tag == "sp":
            ln = el.find(f"{{{P}}}spPr/{{{A}}}ln")
            stroked = ln is not None and ln.find(f"{{{A}}}noFill") is None and len(ln)
            text = any((t.text or "").strip() for t in el.iter(f"{{{A}}}t"))
            custom = el.find(f"{{{P}}}spPr/{{{A}}}custGeom") is not None
            if stroked and not _filled(el) and not text and not custom:
                out += _edges(b, sw)  # рамка-контур: мешают её края
                continue
            if not (_filled(el) or stroked or text or custom):
                continue
        if b[2] * b[3] >= 0.85 * sw * sh:
            continue
        if b[2] < 1 or b[3] < 1:
            b = _thin(b, 0.004 * sw)
        out.append(b)
    return out


def part_lines(pkg: Package, part: Optional[str]) -> list[Box]:
    """Линии части (в том числе внутри групп и нулевой толщины — IR их пропускает) и края рамок-контуров — тонкими
    полосами: логотип не встаёт на линию макета или мастера («Классика»: рамка и линейки вокруг слайда)."""
    root = pkg.xml(part) if part else None
    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
    if tree is None:
        return []
    return tree_lines(tree, pkg.slide_size()[0])


def tree_lines(tree: etree._Element, sw: float) -> list[Box]:
    """То же для дерева фигур (`p:spTree`) — части пакета или живого слайда собираемой колоды."""
    tol = 0.004 * sw
    out: list[Box] = []
    for el in tree.iter(f"{{{P}}}sp", f"{{{P}}}cxnSp"):
        if el.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph") is not None:
            continue
        b = xfrm_box(el.find(f"{{{P}}}spPr/{{{A}}}xfrm"))
        if b is None:
            continue
        b = to_abs(b, [a for a in el.iterancestors() if a.tag == f"{{{P}}}grpSp"])
        ln = el.find(f"{{{P}}}spPr/{{{A}}}ln")
        styled = el.find(f"{{{P}}}style/{{{A}}}lnRef") is not None and (el.find(f"{{{P}}}style/{{{A}}}lnRef").get("idx") or "0") != "0"
        stroked = (ln is not None and ln.find(f"{{{A}}}noFill") is None and (len(ln) or styled)) or (ln is None and styled)
        if not stroked:
            continue
        geom = el.find(f"{{{P}}}spPr/{{{A}}}prstGeom")
        is_line = etree.QName(el).localname == "cxnSp" or b[2] < 1 or b[3] < 1 or (geom is not None and _LINE_GEOM_RE.match(geom.get("prst") or ""))
        if is_line:
            out.append(_thin(b, tol))
        elif not _filled(el) and el.find(f"{{{P}}}spPr/{{{A}}}custGeom") is None:
            out += _edges(b, sw)
    return out


_LINE_GEOM_RE = re.compile(r"^(?:line|straightConnector\d*|bentConnector\d*|curvedConnector\d*)$")


def _content_samples(manifest: TemplateManifest) -> list[int]:
    """Номера содержательных образцов разбора; у шаблона без них — все образцы."""
    every = [p.source_slide for p in manifest.patterns if not p.reference]
    content = [p.source_slide for p in manifest.patterns if not p.reference and getattr(p.kind, "value", p.kind) not in ("title", "section", "thanks")]
    return sorted(set(content or every))


def _place_pic(pkg: Package, part: str, media: Media, img: BrandImage, box: Box, brand_name: str) -> None:
    tree = pkg.xml(part).find(f"{{{P}}}cSld/{{{P}}}spTree")
    rid = pkg.add_rel(part, IMG_REL, media.part_for(img))
    pic = _new_pic(pkg, part, rid, img, box, brand_name)
    ext_lst = tree.find(f"{{{P}}}extLst")
    if ext_lst is not None:
        ext_lst.addprevious(pic)
    else:
        tree.append(pic)
    pkg.dirty.add(part)


@dataclass
class AddReport:
    added: int = 0  # картинок логотипа (на макетах, в том числе без образцов, и на слайдах)
    layouts: int = 0  # из них на макетах
    samples: int = 0  # содержательных образцов
    covered: int = 0  # из них с логотипом
    place: Optional[str] = None  # brand — в углу брендбука, brand_edge — у того же угла, fallback — у другого
    where: Optional[str] = None  # то же словами


def add_logos(pkg: Package, manifest: TemplateManifest, brand: BrandSpec, images: list[BrandImage], warnings: list[str], src: Path | str) -> AddReport:
    """Логотипа в шаблоне нет, а брендбук велит место — логотип бренда на содержательные слайды. Одно место на весь
    шаблон: угол брендбука, если он свободен хотя бы у половины образцов, иначе — запасной угол, свободный у
    большинства. Свободно — значит ни текст, ни заголовок, ни колонтитул (рамки — из макета и мастера), ни линия, ни
    контур, ни фигура, ни картинка туда не заходят и фон под ним не пёстрый; заполнители содержимого отступают,
    оставляя охранное поле (не больше чем на 30 % высоты или 25 % ширины), — тогда и содержимое собранных слайдов
    туда не зайдёт. На макет — если так получается у макета, мастера и всех слайдов на нём (логотип макета лежит под
    фигурами слайда); иначе — поверх образцов, где получается. Вариант логотипа — по настоящему цвету под ним."""
    from verstka.brand.palette import source_ir
    from verstka.data.words import plural

    rep = AddReport()
    if not brand.logo_place or not images:
        return rep
    ir = source_ir(src)
    if ir is None:
        warnings.append("Логотип бренда не поставлен: не удалось разобрать раскладку шаблона.")
        return rep
    sw, sh = pkg.slide_size()
    margin = (brand.margins_px / 1920.0 * sw) if brand.margins_px and 0 < brand.margins_px <= 200 else 0.04 * sw
    order = pkg.slide_order()
    slides = {s.index: s for s in ir.slides}
    samples = [i for i in _content_samples(manifest) if i in slides and 0 < i <= len(order)]
    rep.samples = len(samples)
    if not samples:
        return rep
    wordmark = pick_logo(images, "light", mark=False) or images[0]
    h = (0.06 if wordmark.mark else 0.045) * sh
    w = h * wordmark.aspect
    lines_cache: dict[str, list[Box]] = {}

    def lines_of(part: Optional[str]) -> list[Box]:
        """Линии слайда, его макета и мастера (IR пропускает линии нулевой толщины)."""
        out: list[Box] = []
        for p in _chain(pkg, part) if part else []:
            if p not in lines_cache:
                lines_cache[p] = part_lines(pkg, p)
            out += lines_cache[p]
        return out

    def with_lines(obst: tuple[list[Box], list], part: str) -> tuple[list[Box], list]:
        return obst[0] + lines_of(part), obst[1]

    on_top = {i: with_lines(_ir_obstacles(slides[i], sw, sh, under_slide=False), order[i - 1]) for i in samples}
    by_layout: dict[str, list[int]] = {}
    for i in samples:
        by_layout.setdefault(slides[i].layout_part or pkg.related(order[i - 1], "slideLayout") or "", []).append(i)
    users: dict[str, list[int]] = {}
    for s in ir.slides:
        if s.layout_part:
            users.setdefault(s.layout_part, []).append(s.index)
    under = {j: with_lines(_ir_obstacles(slides[j], sw, sh, under_slide=True), order[j - 1]) for lp in by_layout for j in users.get(lp, by_layout[lp])}
    lay_obst = {lp: with_lines(_layout_obstacles(pkg, lp), lp) for lp in by_layout if lp and pkg.xml(lp) is not None}
    # макеты без образцов (по ним собирает слайды синтез: «Заголовок и объект», пустой макет…); обложки и разделы — нет
    title_layouts = {p.layout_part for p in manifest.patterns if p.layout_part and getattr(p.kind, "value", p.kind) in ("title", "section", "thanks")}
    unused: dict[str, tuple[list[Box], list[tuple[Box, etree._Element]]]] = {}
    for lp in sorted(n for n in pkg.names() if re.match(r"^ppt/slideLayouts/slideLayout\d+\.xml$", n)):
        root = pkg.xml(lp)
        if lp in by_layout or lp in users or lp in title_layouts or root is None or (root.get("type") or "") in ("title", "secHead"):
            continue
        hard, soft = _layout_obstacles(pkg, lp)
        master = pkg.related(lp, "slideMaster")
        hard = hard + _part_shapes(pkg, lp) + part_lines(pkg, lp)
        if root.get("showMasterSp") not in ("0", "false"):
            hard += _part_shapes(pkg, master) + part_lines(pkg, master)
        unused[lp] = (hard, soft)
    spot_cache: dict[tuple, Spot] = {}

    def spot(i: int, box: Box, with_slide: bool) -> Spot:
        key = (i, box, with_slide)
        if key not in spot_cache:
            spot_cache[key] = _spot(pkg, order[i - 1], slides[i], box, with_slide=with_slide)
        return spot_cache[key]

    def fits(hard: list[Box], soft, box: Box) -> bool:
        return _clear(box, hard, CLEAR * sh) and all(_shrunk(b, box, sh) is not None for b, _ in soft)

    def free_on(i: int, box: Box) -> bool:
        return fits(*on_top[i], box) and not spot(i, box, True).busy

    slots = package_slots(pkg)
    own_cache: dict[tuple, Spot] = {}

    def on_layout(lp: str, box: Box) -> Optional[Spot]:
        """Логотип на макет: свободно у его заголовков и колонтитулов (и мастера) и у всех слайдов на нём (логотип
        макета лежит под фигурами слайда; заполнители содержимого отступают); фон под ним у всех слайдов один и тот же,
        что и у самого макета (новый слайд, собранный по макету, своего фона не имеет), и не пёстрый. Что под
        логотипом, или None."""
        if lp not in lay_obst or not fits(*lay_obst[lp], box):
            return None
        everyone = users.get(lp, by_layout[lp])
        if not all(fits(*under[j], box) for j in everyone):
            return None
        if (lp, box) not in own_cache:
            own_cache[(lp, box)] = _xml_spot(pkg, lp, box, slots, with_part=True)
        spots = [spot(j, box, False) for j in everyone] + [own_cache[(lp, box)]]
        if any(sp.busy for sp in spots) or len({sp.ground for sp in spots}) != 1:
            return None
        return spots[0]

    def coverage(box: Box) -> tuple[int, int]:
        """(сколько содержательных слайдов получат логотип, сколько макетов без образцов)."""
        got = 0
        for lp, idxs in by_layout.items():
            got += len(idxs) if on_layout(lp, box) is not None else sum(free_on(i, box) for i in idxs)
        return got, sum(fits(*unused[lp], box) for lp in unused)

    def score(cov: tuple[int, int]) -> float:
        return cov[0] + 0.25 * cov[1]  # макеты без образцов — с весом ¼: какие из них возьмёт сборка, заранее не известно

    # одно место на весь шаблон: первое (по порядку) место, где логотип получат хотя бы 60 % содержательных слайдов и
    # 60 % всего вместе с макетами без образцов (по ним собираются слайды колоды); иначе — где больше всего
    # содержательных слайдов
    total = len(samples) + 0.25 * len(unused)
    best, best_cov, corner, kind = None, (-1, -1), None, None
    for cn, kd, c in _candidates(brand.logo_place, w, h, margin, sw, sh):
        cov = coverage(c)
        # то же место чуть меньшим логотипом (у того же угла), если так охранное поле есть у заметно большего числа
        # слайдов и макетов (хотя бы у десятой части): ради одного слайда логотип не мельчает на всех
        small = _smaller(cn, c, SMALLER)
        cov2 = coverage(small)
        if cov2[0] >= cov[0] and score(cov2) - score(cov) >= max(1.0, 0.1 * total):
            c, cov = small, cov2
        if (cov[0], score(cov)) > (best_cov[0], score(best_cov)):
            best, best_cov, corner, kind = c, cov, cn, kd
        if cov[0] >= 0.6 * len(samples) and score(cov) >= 0.6 * total:
            break
    if best is not None and best_cov[0] == 0 and best_cov[1] == 0:
        best = None
    if best is None:
        warnings.append("Логотип бренда не поставлен: у краёв слайдов шаблона нет свободного места.")
        return rep
    rep.place = ("brand" if kind == "corner" else "brand_edge") if corner == brand.logo_place else "fallback"
    rep.where = logo_where(brand.logo_place, corner, kind)
    media = Media(pkg)

    def shrink(part: str, items, by_sid: bool) -> None:
        for b, ref in items:
            nb = _shrunk(b, best, sh)
            if nb == b:
                continue
            sp = _sp_by_id(pkg, part, ref) if by_sid else ref
            if sp is not None and (not by_sid or shape_box(sp) is not None or part.startswith("ppt/slides/")):
                _set_frame(sp, nb)
                pkg.dirty.add(part)

    covered: set[int] = set()
    for lp, idxs in sorted(by_layout.items()):
        sp_layout = on_layout(lp, best)
        if sp_layout is not None:
            shrink(lp, lay_obst[lp][1], by_sid=False)
            for j in users.get(lp, idxs):
                # у слайдов со своей рамкой заполнителя — своя отступившая рамка (унаследованные отступят с макетом)
                own = [(b, sid) for b, sid in under[j][1] if (el := _sp_by_id(pkg, order[j - 1], sid)) is not None and shape_box(el) is not None]
                shrink(order[j - 1], own, by_sid=True)
            _place_pic(pkg, lp, media, pick_logo(images, sp_layout.ground, mark=False) or wordmark, best, brand.name)
            rep.added += 1
            rep.layouts += 1
            covered.update(idxs)
            continue
        for i in idxs:
            if not free_on(i, best):
                continue
            shrink(order[i - 1], on_top[i][1], by_sid=True)
            _place_pic(pkg, order[i - 1], media, pick_logo(images, spot(i, best, True).ground, mark=False) or wordmark, best, brand.name)
            rep.added += 1
            covered.add(i)
    for lp, (hard, soft) in unused.items():
        if not fits(hard, soft, best):
            continue
        shrink(lp, soft, by_sid=False)
        _place_pic(pkg, lp, media, pick_logo(images, ground_under(pkg, lp, best, slots), mark=False) or wordmark, best, brand.name)
        rep.added += 1
        rep.layouts += 1
    rep.covered = len(covered)
    missing = rep.samples - rep.covered
    where = rep.where
    if missing:
        warnings.append(
            f"Логотип бренда стоит {where} — на {rep.covered} из {rep.samples} {plural(rep.samples, 'содержательного слайда', 'содержательных слайдов', 'содержательных слайдов')} "
            f"шаблона; на {missing} {plural(missing, 'слайде', 'слайдах', 'слайдах')} там нет свободного места."
        )
    elif rep.place != "brand":
        warnings.append(f"Логотип бренда стоит {where}.")
    return rep
