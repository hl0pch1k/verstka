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

from verstka.brand.package import A, IMG_REL, P, R, Box, Package, overlap, shape_box, xfrm_box
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
    while len(_PROBES) > 256:
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


def _fill_hex(el: Optional[etree._Element], slots: dict[str, str]) -> Optional[str]:
    """Цвет заливки: srgbClr или цвет темы; градиент — по первой точке; картинка — None."""
    if el is None:
        return None
    for c in el.iter(_SRGB, f"{{{A}}}schemeClr", f"{{{A}}}sysClr", f"{{{A}}}blipFill"):
        tag = etree.QName(c).localname
        if tag == "blipFill":
            return None
        if tag == "srgbClr":
            return (c.get("val") or "").upper() or None
        if tag == "sysClr":
            return (c.get("lastClr") or "").upper() or None
        v = c.get("val") or ""
        return slots.get(_CLR_MAP.get(v, v))
    return None


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
    """light / dark — настоящий цвет под рамкой: верхняя залитая фигура или картинка под ней (слайд, его макет, мастер),
    иначе фон."""
    sw, sh = pkg.slide_size()
    for p in _chain(pkg, part):
        root = pkg.xml(p)
        tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
        if tree is None:
            continue
        for el in reversed(list(tree)):
            b = shape_box(el)
            if not b or overlap(b, box) < 0.5 * box[2] * box[3]:
                continue
            tag = etree.QName(el).localname
            if tag == "pic":
                got = _picture_under(pkg, p, el, b, box)
                if got and got[1] >= 0.5:
                    return "dark" if got[0] < 55 else "light"
            elif tag == "sp" and _filled(el):
                h = _fill_hex(el.find(f"{{{P}}}spPr"), slots)
                if h and re.fullmatch(r"[0-9A-F]{6}", h):
                    return "dark" if lightness(h) < 55 else "light"
    bg = part_bg(pkg, part, slots)
    if bg and re.fullmatch(r"[0-9A-F]{6}", bg):
        return "dark" if lightness(bg) < 55 else "light"
    return "light"


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


def has_template_logo(src: Path | str, manifest: Optional[TemplateManifest] = None) -> bool:
    """В шаблоне есть логотип-картинка (для расхождений)."""
    try:
        pkg = Package(src)
        from verstka.brand.palette import package_theme

        return any(not lk.duplicate for lk in find_template_logos(pkg, manifest, package_theme(pkg).slots))
    except Exception as e:  # noqa: BLE001
        log.warning("template logos not found: %s", e)
        return bool(manifest and any(a.kind == "logo" for a in manifest.assets))


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


_FILLS = ("solidFill", "gradFill", "blipFill", "pattFill")
_FOOTER_PH = ("sldNum", "ftr", "dt")
_LINE_GEOMS = re.compile(r"^(?:line|straightConnector\d*|bentConnector\d*|curvedConnector\d*)$")


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


def _has_text(sp: etree._Element) -> bool:
    return any((t.text or "").strip() for t in sp.iter(f"{{{A}}}t")) or sp.find(f".//{{{A}}}fld") is not None


def _is_line(el: etree._Element, b: Box) -> bool:
    if etree.QName(el).localname == "cxnSp":
        return True
    geom = el.find(f"{{{P}}}spPr/{{{A}}}prstGeom")
    return (geom is not None and bool(_LINE_GEOMS.match(geom.get("prst") or ""))) or b[2] < 1 or b[3] < 1


@dataclass
class Obstacle:
    box: Box
    kind: str  # text | line | fill | picture | frame | group
    el: etree._Element
    part: str


def obstacles(pkg: Package, part: str, *, only_marks: bool = False) -> list[Obstacle]:
    """Что занимает место на части: текст (и пустые заполнители номера слайда, колонтитула, даты), линии, залитые
    фигуры, картинки, таблицы и диаграммы, группы. `only_marks` — только текст и линии (рисунок макета и мастера
    лежит под логотипом и ему не мешает)."""
    root = pkg.xml(part)
    tree = root.find(f"{{{P}}}cSld/{{{P}}}spTree") if root is not None else None
    if tree is None:
        return []
    sw, sh = pkg.slide_size()
    tol = 0.004 * sw
    out: list[Obstacle] = []
    for el in tree:
        tag = etree.QName(el).localname
        b = shape_box(el)
        if b is None:
            # заполнитель макета или мастера без своей рамки — номер слайда и колонтитулы мастера
            continue
        ph = el.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph") if tag == "sp" else None
        if ph is not None and "/slides/" not in part and (ph.get("type") or "body") not in _FOOTER_PH:
            continue  # заполнитель макета или мастера с подсказкой («Образец текста») — место содержимого слайда, а не текст
        if tag in ("sp", "cxnSp") and _is_line(el, b):
            out.append(Obstacle((b[0] - tol, b[1] - tol, b[2] + 2 * tol, b[3] + 2 * tol), "line", el, part))
        elif tag == "sp" and ((ph is not None and (ph.get("type") or "") in _FOOTER_PH) or _has_text(el)):
            out.append(Obstacle(b, "text", el, part))
        elif only_marks:
            continue
        elif tag == "sp" and _filled(el):
            out.append(Obstacle(b, "fill", el, part))
        elif tag == "pic":
            out.append(Obstacle(b, "picture", el, part))
        elif tag in ("graphicFrame", "grpSp"):
            out.append(Obstacle(b, "frame" if tag == "graphicFrame" else "group", el, part))
    return out


def _blocks(pkg: Package, ob: Obstacle, box: Box, *, under_ok: bool) -> bool:
    """Препятствие заходит на рамку логотипа (больше 3 % её площади). `under_ok` — логотип встанет поверх: фон во
    весь слайд и картинка, прозрачная в этом месте, не мешают."""
    if overlap(ob.box, box) <= 0.03 * box[2] * box[3]:
        return False
    if ob.kind in ("text", "line", "frame", "group", "fill"):
        if under_ok and ob.kind == "fill":
            sw, sh = pkg.slide_size()
            return ob.box[2] * ob.box[3] < 0.85 * sw * sh
        return True
    if ob.kind == "picture":
        sw, sh = pkg.slide_size()
        if under_ok and ob.box[2] * ob.box[3] >= 0.85 * sw * sh:
            return False
        got = _picture_under(pkg, ob.part, ob.el, ob.box, box)
        return got is None or got[1] >= 0.3
    return True


def _candidates(place: LogoPlace, w: float, h: float, margin: float, sw: float, sh: float) -> list[Box]:
    """Угол из брендбука, затем — шагами вдоль того же края к середине, затем — чуть выше (ниже) края, над полосой
    колонтитула, не дальше пятой части слайда от края."""
    left, top = place.endswith("left"), place.startswith("top")
    y0 = margin if top else sh - margin - h
    xs = []
    for k in range(0, 7):
        x = margin + k * 0.5 * w if left else sw - margin - w - k * 0.5 * w
        if x < margin - 1 or x + w > sw - margin + 1 or (left and x + w > 0.5 * sw) or (not left and x < 0.5 * sw):
            break
        xs.append(x)
    out = [(x, y0, w, h) for x in xs]
    for j in range(1, 5):
        y = y0 + j * 0.6 * h if top else y0 - j * 0.6 * h
        if (top and y + h > 0.2 * sh) or (not top and y < 0.8 * sh):
            break
        out += [(x, y, w, h) for x in xs[:3]]
    return out


def _content_samples(manifest: TemplateManifest) -> dict[int, tuple[str, str]]:
    """Содержательные образцы разбора: номер слайда → (макет, фон light / dark); у шаблона без них — все образцы."""
    every = {p.source_slide: (p.layout_part, getattr(p.family, "value", p.family)) for p in manifest.patterns if p.layout_part and not p.reference}
    content = {
        p.source_slide: every[p.source_slide]
        for p in manifest.patterns
        if p.source_slide in every and getattr(p.kind, "value", p.kind) not in ("title", "section", "thanks")
    }
    return content or every


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


def add_logos(pkg: Package, manifest: TemplateManifest, brand: BrandSpec, images: list[BrandImage], warnings: list[str], slots: Optional[dict[str, str]] = None) -> int:
    """Логотипа в шаблоне нет, а брендбук велит место — логотип бренда на содержательные слайды: на их макет, если там
    свободно и у макета, и у мастера, и у всех образцов на нём (логотип макета лежит под фигурами слайда); иначе —
    поверх образцов со свободным местом. Место одно на макет; некуда — не ставится, с объяснением."""
    from verstka.data.words import plural

    if not brand.logo_place or not images:
        return 0
    slots = slots or {}
    sw, sh = pkg.slide_size()
    margin = (brand.margins_px / 1920.0 * sw) if brand.margins_px and 0 < brand.margins_px <= 200 else 0.04 * sw
    media = Media(pkg)
    order = pkg.slide_order()
    by_layout: dict[str, list[str]] = {}
    for idx, (lp, _fam) in _content_samples(manifest).items():
        if 0 < idx <= len(order):
            by_layout.setdefault(lp, []).append(order[idx - 1])
    users: dict[str, list[str]] = {}
    for part in order:
        lp = pkg.related(part, "slideLayout")
        if lp:
            users.setdefault(lp, []).append(part)
    wordmark = pick_logo(images, "light", mark=False) or images[0]
    h = (0.06 if wordmark.mark else 0.045) * sh
    w = h * wordmark.aspect

    def marks_of(part: str) -> list[Obstacle]:
        out = []
        for p in _chain(pkg, part)[1:]:
            out += obstacles(pkg, p, only_marks=True)
        return out

    def free_on_layout(lp: str, box: Box) -> bool:
        own = obstacles(pkg, lp, only_marks=True) + marks_of(lp)
        if any(_blocks(pkg, ob, box, under_ok=False) for ob in own):
            return False
        # логотип макета лежит под фигурами слайда: место должно быть свободно у всех образцов на этом макете
        return not any(any(_blocks(pkg, ob, box, under_ok=False) for ob in obstacles(pkg, sp)) for sp in users.get(lp, []))

    def free_on_slide(sp: str, box: Box) -> bool:
        return not any(_blocks(pkg, ob, box, under_ok=True) for ob in obstacles(pkg, sp) + marks_of(sp))

    added = skipped = 0
    for lp, slides in sorted(by_layout.items()):
        if pkg.xml(lp) is None:
            continue
        cands = _candidates(brand.logo_place, w, h, margin, sw, sh)
        box = next((b for b in cands if free_on_layout(lp, b)), None)
        if box is not None:
            img = pick_logo(images, ground_under(pkg, lp, box, slots), mark=False) or wordmark
            _place_pic(pkg, lp, media, img, box, brand.name)
            added += 1
            continue
        # одно место на все образцы макета, иначе — своё у каждого
        common = next((b for b in cands if all(free_on_slide(sp, b) for sp in slides)), None)
        for sp in slides:
            b = common if common is not None else next((c for c in cands if free_on_slide(sp, c)), None)
            if b is None:
                skipped += 1
                continue
            img = pick_logo(images, ground_under(pkg, sp, b, slots), mark=False) or wordmark
            _place_pic(pkg, sp, media, img, b, brand.name)
            added += 1
    if skipped:
        warnings.append(
            f"Логотип бренда не поставлен на {skipped} {plural(skipped, 'слайд', 'слайда', 'слайдов')} шаблона: "
            "у края, где ему место по брендбуку, нет свободного места."
        )
    return added
