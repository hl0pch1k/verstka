"""Брендбук → брендированная копия шаблона (описание решения §5, «Применение»).

ТЗ: палитра, типографика и фирменные элементы брендбука применяются к слайдам; при расхождении с шаблоном важнее
брендбук, если пользователь не выбрал иное. Решение — **копия шаблона**, переписанная под бренд и разобранная как
отдельный шаблон (свой id, без модели): весь конвейер, аудит палитры и шрифтов работают на ней без изменений.

Что переписывается в копии (`apply_brand`):
- цвета — тема (`clrScheme`, цвета `objectDefaults`), явные цвета слайдов, макетов, мастеров, диаграмм, SmartArt,
  стилей таблиц — по плану `verstka.brand.palette` (роли разбора, контраст текста); картинки не перекрашиваются;
- шрифты (`a:latin`) — роль по месту текста (стиль заголовков мастера, заголовок-заполнитель, крупный кегль →
  шрифт заголовков, остальное → шрифт текста), как `rendering.cyrillic.apply_to_pptx`; моноширинные и символьные не
  меняются; начертание (полужирный, курсив) — как у шаблона: меняется только семейство. Нет шрифта бренда на этой
  машине — пишется его замена из брендбука («Play»), как велит сам брендбук;
- логотипы — `verstka.brand.logos`.

Приоритет «brand» (по умолчанию) — значения бренда заменяют расходящиеся значения шаблона на любом шаблоне;
«template» — бренд только дополняет то, чего у шаблона нет (стандартная тема офисного пакета, шрифты по умолчанию,
логотип), расхождения остаются как в шаблоне.

`branded_template(template_id, brand, priority)` — id брендированной копии в `workspace/templates/<id>/` (кэш по
шаблону, отпечатку брендбука и приоритету; рядом `brand.json`, `meta.txt`, `title.txt` «VK Tech · брендбук VK Cloud»).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from lxml import etree

from verstka.brand.logos import brand_logos, find_template_logos, find_text_logos, load_logo, logo_path
from verstka.brand.package import A, C, P, Package
from verstka.brand.palette import (
    SRGB,
    THEME_SLOTS,
    ColorPlan,
    TextPair,
    ThemeInfo,
    package_theme,
    plan_colors,
    retune_manifest,
    slot_hex,
    template_theme,
    text_pairs,
)
from verstka.ingest.workspace import SAFE_ID_RE, TemplateWorkspace, default_workspace_root
from verstka.schemas.brand import BrandFont, BrandPriority, BrandSpec
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

# версия правил применения: меняется — старые копии в кэше не используются
APPLY_VERSION = "10"
BRAND_FILE = "brand.json"

_LATIN = f"{{{A}}}latin"
_RPR_TAGS = {f"{{{A}}}rPr", f"{{{A}}}defRPr", f"{{{A}}}endParaRPr"}

# части, где живут видимые цвета и шрифты (заметки не трогаются)
_VISIBLE_RE = re.compile(
    r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+|charts/(?:chart|colors|style)\d+|"
    r"diagrams/(?:data|drawing|colors)\d+|presentation|tableStyles)\.xml$"
)
_THEME_RE = re.compile(r"^ppt/theme/theme\d+\.xml$")

# шрифты «по умолчанию» офисных пакетов: в шаблоне без своего шрифта их место свободно для бренда
STOCK_FONTS = frozenset(
    x.lower()
    for x in (
        "Calibri", "Calibri Light", "Arial", "Aptos", "Aptos Display", "Aptos Narrow", "Times New Roman", "Helvetica",
        "Helvetica Neue", "Liberation Sans", "Liberation Serif", "Carlito", "Caladea", "Cambria", "DejaVu Sans",
    )
)
_SYMBOL_FONT_RE = re.compile(r"symbol|wingding|webding|dingbat|marlett|mt extra|zapf|emoji|icons?\b|awesome|glyph", re.I)
_MONO_FONT_RE = re.compile(r"mono|consol|courier|menlo|monaco|\bcode\b|typewriter|fixed", re.I)


# ============================================================================================ план шрифтов


def font_available(family: Optional[str]) -> bool:
    """На этой машине есть сам шрифт (установлен, идёт с LibreOffice или с Verstka — Play)."""
    name = (family or "").strip()
    if not name:
        return False
    try:
        from verstka.rendering.fonts import FONT_DIR, is_installed

        if name.lower() in {f.stem.split("-")[0].lower() for f in FONT_DIR.glob("*.[ot]tf")}:
            return True
        return is_installed(name)
    except Exception:  # noqa: BLE001 - без шрифтовой подсистемы считаем, что шрифта нет
        return False


def written_family(font: BrandFont) -> tuple[str, bool]:
    """(шрифт, который пишется в копию; это замена из брендбука?). Нет шрифта бренда на машине — его замена, если она есть."""
    if not font.fallback or font_available(font.family):
        return font.family, False
    if font_available(font.fallback):
        return font.fallback, True
    return font.family, False


def font_base(name: Optional[str]) -> str:
    """«Inter Light» → «inter»: семейство без начертания."""
    from verstka.rendering.cyrillic import base_family

    return base_family(name or "")


@dataclass
class FontPlan:
    priority: str = "brand"
    heading_from: Optional[str] = None  # шрифт заголовков шаблона
    body_from: Optional[str] = None
    heading: Optional[BrandFont] = None  # шрифт бренда
    body: Optional[BrandFont] = None
    heading_to: Optional[str] = None  # что пишется в копию
    body_to: Optional[str] = None
    heading_fallback: bool = False
    body_fallback: bool = False
    heading_min_pt: float = 24.0
    own: set[str] = field(default_factory=set)  # свои шрифты шаблона (base)

    def target(self, family: Optional[str], role: str) -> Optional[str]:
        """Новый шрифт для текста в `family` с ролью heading / body, или None — оставить."""
        name = (family or "").strip()
        if not name or name.startswith("+") or _SYMBOL_FONT_RE.search(name) or _MONO_FONT_RE.search(name):
            return None
        to = self.heading_to if role == "heading" else self.body_to
        if not to or name == to:
            return None
        if self.priority == "template" and not self.lacking(name):
            return None
        return to

    def lacking(self, family: Optional[str]) -> bool:
        """Шрифт — «по умолчанию» и не свой у шаблона: его место бренд может занять и при приоритете шаблона."""
        b = font_base(family)
        return not b or (b in STOCK_FONTS and b not in self.own)


def template_fonts(manifest: TemplateManifest) -> tuple[Optional[str], Optional[str]]:
    """(шрифт заголовков, шрифт текста) шаблона — по слотам образцов, иначе главный шрифт разбора."""
    heads: Counter = Counter()
    bodies: Counter = Counter()
    for p in manifest.patterns:
        for s in p.slots:
            fam = s.style.font_family
            if not fam:
                continue
            role = getattr(s.role, "value", s.role)
            if role == "title":
                heads[fam] += 1
            elif role in ("body", "bullet_list", "card_body", "subtitle", "caption"):
                bodies[fam] += 1
    fams = manifest.tokens.typography.families
    main = next((f.family for f in fams if f.source == "text"), None) or next((f.family for f in fams), None)
    return (heads.most_common(1)[0][0] if heads else main), (bodies.most_common(1)[0][0] if bodies else main)


def plan_fonts(manifest: TemplateManifest, brand: BrandSpec, priority: BrandPriority = "brand") -> FontPlan:
    fp = FontPlan(priority=priority)
    fp.heading_from, fp.body_from = template_fonts(manifest)
    fp.heading = brand.font("heading") or brand.font("body")
    fp.body = brand.font("body")
    if fp.heading:
        fp.heading_to, fp.heading_fallback = written_family(fp.heading)
    if fp.body:
        fp.body_to, fp.body_fallback = written_family(fp.body)
    big = [s.size_pt for s in manifest.tokens.typography.scale if s.role in ("display", "h1") and s.size_pt]
    fp.heading_min_pt = round(min(big) * 0.85, 1) if big else 24.0
    fp.own = {font_base(f.family) for f in manifest.tokens.typography.families if f.source == "text" and f.weight >= 0.02}
    return fp


def font_result(font: BrandFont, written: str, fallback: bool) -> str:
    """«VK Sans Display» или «VK Sans Display, замена — Play»."""
    return f"{font.family}, замена — {written}" if fallback else font.family


# ============================================================================================ цвета и шрифты в частях


def _recolor(root: etree._Element, plan: ColorPlan, counter: Counter, strict: bool = False) -> bool:
    # картинки не перекрашиваются (элементы держатся в списке: lxml сохраняет их обёртки, пока на них есть ссылки)
    inside = [c for b in root.iter(f"{{{A}}}blip", f"{{{A}}}clrScheme") for c in b.iter(SRGB)]
    skip = set(inside)
    # явный цвет текста со ссылкой (розовые ссылки ЛЦТ) — как слот ссылок темы: семья основного цвета бренда
    links = [c for r in root.iter(f"{{{A}}}rPr", f"{{{A}}}defRPr", f"{{{A}}}endParaRPr") if r.find(f"{{{A}}}hlinkClick") is not None
             for c in r.findall(f"{{{A}}}solidFill/{SRGB}")]
    link_els = set(links)
    changed = False
    for el in root.iter(SRGB):
        if el in skip:
            continue
        v = (el.get("val") or "").upper()
        nv = plan.map_link(v) if el in link_els else (plan.map_strict(v) if strict else plan.map(v))
        if nv != v:
            el.set("val", nv)
            counter[(v, nv)] += 1
            changed = True
    return changed


def _retheme(root: etree._Element, plan: ColorPlan, fp: FontPlan, counter: Counter, fonts: Counter) -> bool:
    """Тема: слоты `clrScheme`, шрифты `fontScheme`, цвета и шрифты `objectDefaults` (фигуры, линии и надписи, которые
    человек добавит в PowerPoint)."""
    changed = False
    scheme = root.find(f".//{{{A}}}clrScheme")
    if scheme is not None:
        for slot in scheme:
            name = etree.QName(slot).localname
            if name not in THEME_SLOTS:
                continue
            old = slot_hex(slot)
            if not old:
                continue
            # слот ссылок темы (и у темы заметок — офисный #0563C1) — основной цвет бренда
            new = plan.map_link(old, near=12.0) if name in ("hlink", "folHlink") else plan.map(old)
            if new == old:
                continue
            for ch in list(slot):
                slot.remove(ch)
            etree.SubElement(slot, SRGB).set("val", new)
            counter[(old, new)] += 1
            changed = True
    for which, role in (("major", "heading"), ("minor", "body")):
        lat = root.find(f".//{{{A}}}fontScheme/{{{A}}}{which}Font/{{{A}}}latin")
        if lat is None:
            continue
        new = fp.target(lat.get("typeface"), role)
        if new:
            fonts[(lat.get("typeface"), new)] += 1
            lat.set("typeface", new)
            changed = True
    defaults = root.find(f".//{{{A}}}objectDefaults")
    if defaults is not None:
        changed |= _recolor(defaults, plan, counter)
        changed |= _refont(defaults, fp, fonts)
    return changed


class _Roles:
    """Роль текста (заголовок / текст) для `a:latin` в части."""

    _HEAD_PH = {"title", "ctrTitle"}

    def __init__(self, fp: FontPlan) -> None:
        self.fp = fp
        self.size_cache: dict[etree._Element, Optional[int]] = {}

    def _shape_size(self, shape: etree._Element) -> Optional[int]:
        if shape not in self.size_cache:
            sizes = [int(e.get("sz")) for e in shape.iter(*_RPR_TAGS) if (e.get("sz") or "").isdigit()]
            self.size_cache[shape] = max(sizes) if sizes else None
        return self.size_cache[shape]

    def role(self, el: etree._Element) -> str:
        rpr = el if el.tag in _RPR_TAGS else el.getparent()
        sz = int(rpr.get("sz")) if rpr is not None and (rpr.get("sz") or "").isdigit() else None
        shape = None
        for anc in el.iterancestors():
            tag = anc.tag
            if tag == f"{{{P}}}titleStyle":
                return "heading"
            if tag in (f"{{{P}}}bodyStyle", f"{{{P}}}otherStyle", f"{{{P}}}defaultTextStyle", f"{{{C}}}chartSpace"):
                return "body"
            if tag in (f"{{{P}}}sp", f"{{{P}}}graphicFrame"):
                shape = anc
                break
        if shape is not None and shape.tag == f"{{{P}}}sp":
            ph = shape.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
            if ph is not None and (ph.get("type") or "") in self._HEAD_PH:
                return "heading"
        if sz is None and shape is not None:
            sz = self._shape_size(shape)
        if sz is not None and sz / 100.0 >= self.fp.heading_min_pt:
            return "heading"
        return "body"


def _refont(root: etree._Element, fp: FontPlan, counter: Counter, swapped: Optional[dict] = None) -> bool:
    """Шрифты по роли текста; начертание (полужирный, курсив) — как у шаблона. `swapped` — свойства текста, где шрифт
    сменился, → прежний шрифт (для проверки, помещается ли строка)."""
    roles = _Roles(fp)
    changed = False
    for lat in list(root.iter(_LATIN)):
        if any(a.tag == f"{{{A}}}fontScheme" for a in lat.iterancestors()):
            continue  # шрифты темы — `_retheme`
        old = lat.get("typeface")
        new = fp.target(old, roles.role(lat))
        if new:
            counter[(old, new)] += 1
            lat.set("typeface", new)
            changed = True
            if swapped is not None and lat.getparent() is not None:
                swapped[lat.getparent()] = old
    return changed


_SLIDE_LIKE_RE = re.compile(r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+)\.xml$")


def _refit(root: etree._Element, swapped: dict, res: "ApplyResult") -> None:
    """Строка образца шаблона, которая помещалась в свою рамку, после смены семейства тоже помещается: кегль
    уменьшается (не больше чем на 20 %), иначе у этой строки остаётся шрифт шаблона («16M» не переносится)."""
    from verstka.rendering.fonts import text_width_pt

    for sp in root.iter(f"{{{P}}}sp"):
        xfrm = sp.find(f"{{{P}}}spPr/{{{A}}}xfrm")
        body = sp.find(f"{{{P}}}txBody")
        ext = xfrm.find(f"{{{A}}}ext") if xfrm is not None else None
        if body is None or ext is None:
            continue
        bpr = body.find(f"{{{A}}}bodyPr")
        if bpr is not None and bpr.get("wrap") == "none":
            continue
        ins = lambda k, d=91440: int(bpr.get(k)) if bpr is not None and (bpr.get(k) or "").lstrip("-").isdigit() else d  # noqa: E731
        inner = (int(ext.get("cx", "0")) - ins("lIns") - ins("rIns")) / 12700.0
        if inner <= 0:
            continue
        for par in body.iter(f"{{{A}}}p"):
            runs = [r for r in par.iter(f"{{{A}}}r") if (r.findtext(f"{{{A}}}t") or "")]
            rprs = [r.find(f"{{{A}}}rPr") for r in runs]
            if not runs or not any(rp is not None and rp in swapped for rp in rprs):
                continue
            if any(rp is None or not (rp.get("sz") or "").isdigit() for rp in rprs):
                continue  # кегль наследуется — подгонку делает конвейер
            def width(use_old: bool) -> float:
                total = 0.0
                for r, rp in zip(runs, rprs):
                    lat = rp.find(_LATIN)
                    fam = swapped.get(rp) if use_old and rp in swapped else (lat.get("typeface") if lat is not None else None)
                    total += text_width_pt(r.findtext(f"{{{A}}}t") or "", fam, int(rp.get("sz")) / 100.0, rp.get("b") == "1")
                return total
            before, after = width(True), width(False)
            if before > inner or after <= inner:
                continue
            k = inner / after * 0.98
            if k >= 0.8:
                for rp in rprs:
                    rp.set("sz", str(int(int(rp.get("sz")) * k)))
                res.refit += 1
            else:
                for rp in rprs:
                    if rp in swapped:
                        rp.find(_LATIN).set("typeface", swapped[rp])
                res.refit += 1


# ============================================================================================ применение


@dataclass
class ApplyResult:
    """Что сделано с копией — для `brand.json`, отчёта и слоя «Брендбук»."""

    priority: str = "brand"
    changed_parts: int = 0
    colors: dict[str, str] = field(default_factory=dict)  # «#FF3885» → «#FF3985»
    fonts: dict[str, str] = field(default_factory=dict)  # heading / body → что записано
    font_swaps: dict[str, str] = field(default_factory=dict)  # «Arial» → «Play»
    logos_replaced: int = 0
    logos_removed: int = 0  # второй логотип шаблона на той же части (партнёр, соседняя марка)
    # Добавленный логотип (в шаблоне своего не было). Человеку показывать «на `logo_covered` из `logo_samples`
    # содержательных слайдов» и `logo_where`; `logos_added` — число картинок, вместе с макетами без образцов (у
    # «Кофейни» их 56 при 6 слайдах), для людей не годится.
    logos_added: int = 0  # картинок логотипа бренда: на слайдах и макетах
    logo_layouts: int = 0  # из них на макетах (их получат и новые слайды, собранные по макету)
    logo_samples: int = 0  # содержательных образцов шаблона
    logo_covered: int = 0  # из них с логотипом бренда (добавленным, перенесённым или заменённым на месте)
    logo_place: Optional[str] = None  # brand — угол из брендбука, brand_edge — у того же угла, fallback — у другого
    logo_where: Optional[str] = None  # то же словами: «в углу из брендбука», «в правом верхнем углу: …»
    # логотип шаблона в другом углу, чем велит брендбук: «в шаблоне слева внизу, по брендбуку — справа внизу;
    # поставлен справа внизу» (или «оставлен слева внизу: угол из брендбука занят»)
    logo_note: Optional[str] = None
    logo_covers: int = 0  # обложек, разделов и финальных слайдов, получивших логотип бренда (у шаблона там его не было)
    caps_changed: int = 0  # стилей заголовков, где капс снят или поставлен по правилу брендбука
    refit: int = 0  # строк образцов, подогнанных после смены шрифта
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.changed_parts > 0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["changed"] = self.changed
        return d


_NO_CAPS_RE = re.compile(
    r"(без|не\s+(?:используйте|набирайте|пишите|ставьте|делайте)[^.;]{0,40}?)\s*(?:капс\w*|заглавн\w*|прописн\w*|caps|верхн\w+\s+регистр\w*)"
    r"|(?:no|avoid|don'?t\s+use|never\s+use)\s+(?:all[\s-]*)?caps|sentence\s+case"
    r"|заголовк\w*[^.;]{0,30}(?:строчн\w*|как\s+в\s+предложении)",
    re.I,
)
_CAPS_RE = re.compile(r"заголовк\w*[^.;]{0,30}(?:капс\w*|заглавн\w*|прописн\w*|верхн\w+\s+регистр\w*)|headings?[^.;]{0,30}(?:all\s*caps|uppercase)", re.I)


def caps_rule(brand: BrandSpec) -> Optional[bool]:
    """Что брендбук говорит о капсе заголовков: False — не капсом, True — капсом, None — ничего (стиль шаблона
    остаётся: капс ЛЦТ — его оформление)."""
    for r in brand.rules:
        if getattr(r, "kind", "other") not in ("type", "other"):
            continue
        if _NO_CAPS_RE.search(r.text):
            return False
        if _CAPS_RE.search(r.text):
            return True
    return None


def _set_title_caps(pkg: Package, caps: bool) -> int:
    """Капс заголовков по правилу брендбука: стиль заголовка мастера (`p:titleStyle`) и заголовки макетов и слайдов;
    число изменённых частей."""
    done = 0
    for name in pkg.names():
        if not re.match(r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+)\.xml$", name):
            continue
        root = pkg.xml(name)
        if root is None:
            continue
        holders = [e for e in root.iter(f"{{{P}}}titleStyle")]
        for sp in root.iter(f"{{{P}}}sp"):
            ph = sp.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
            if ph is not None and (ph.get("type") or "") in ("title", "ctrTitle"):
                holders.append(sp)
        changed = False
        for h in holders:
            for rpr in h.iter(f"{{{A}}}defRPr", f"{{{A}}}rPr", f"{{{A}}}endParaRPr"):
                if not caps and rpr.get("cap") == "all":
                    del rpr.attrib["cap"]
                    changed = True
            if caps and h.tag == f"{{{P}}}titleStyle":
                lvl = h.find(f"{{{A}}}lvl1pPr/{{{A}}}defRPr")
                if lvl is not None and lvl.get("cap") != "all":
                    lvl.set("cap", "all")
                    changed = True
        if changed:
            pkg.dirty.add(name)
            done += 1
    return done


def resolve_brand_dir(brand: BrandSpec, brand_dir: Optional[Path | str], workspace_root: Optional[Path | str] = None) -> Optional[Path]:
    """Папка, относительно которой лежат файлы логотипов: заданная, иначе `workspace/brandbooks/<id>/`."""
    if brand_dir:
        return Path(brand_dir)
    if brand.id and SAFE_ID_RE.fullmatch(brand.id):
        d = (Path(workspace_root) if workspace_root else default_workspace_root()) / "brandbooks" / brand.id
        if d.is_dir():
            return d
    return None


@dataclass
class BrandPlan:
    """Всё, что брендбук делает с шаблоном: тема шаблона, пары «текст — фон», планы цветов и шрифтов."""

    theme: ThemeInfo
    pairs: list[TextPair]
    colors: ColorPlan
    fonts: FontPlan


def brand_plan(src: Optional[Path | str], manifest: TemplateManifest, brand: BrandSpec, priority: BrandPriority = "brand") -> BrandPlan:
    """План применения брендбука к шаблону `src` (одни и те же правила для копии, расхождений и разбора копии)."""
    theme = template_theme(src) if src else ThemeInfo()
    pairs = text_pairs(src, manifest) if src and priority == "brand" else []
    return BrandPlan(theme, pairs, plan_colors(manifest, brand, priority, theme, pairs), plan_fonts(manifest, brand, priority))


def apply_brand(
    src: Path | str,
    out: Path | str,
    brand: BrandSpec,
    *,
    manifest: TemplateManifest,
    priority: BrandPriority = "brand",
    brand_dir: Optional[Path | str] = None,
) -> ApplyResult:
    """Пишет в `out` копию шаблона `src`, переписанную под брендбук (см. описание модуля)."""
    pkg = Package(src)
    res = ApplyResult(priority=priority)
    plan = brand_plan(src, manifest, brand, priority)
    cp, fp = plan.colors, plan.fonts
    res.warnings.extend(cp.warnings)
    if fp.heading_to:
        res.fonts["heading"] = fp.heading_to
    if fp.body_to:
        res.fonts["body"] = fp.body_to
    colors: Counter = Counter()
    fonts: Counter = Counter()
    for name in pkg.names():
        if _THEME_RE.match(name):
            root = pkg.xml(name)
            if root is not None and _retheme(root, cp, fp, colors, fonts):
                pkg.dirty.add(name)
        elif _VISIBLE_RE.match(name):
            root = pkg.xml(name)
            if root is None:
                continue
            a = _recolor(root, cp, colors, strict=name == "ppt/tableStyles.xml")
            swapped: dict = {}
            b = _refont(root, fp, fonts, swapped)
            if swapped and _SLIDE_LIKE_RE.match(name):
                _refit(root, swapped, res)
            if a or b:
                pkg.dirty.add(name)

    # логотипы
    bdir = resolve_brand_dir(brand, brand_dir)
    images = [im for im in (load_logo(lg, bdir) for lg in brand.logos) if im is not None]
    theme = package_theme(pkg)
    slots = theme.slots or plan.theme.slots
    fonts_pair = (theme.major or plan.theme.major or "", theme.minor or plan.theme.minor or "")
    if priority == "brand" and images:
        out_logos = brand_logos(pkg, manifest, brand, images, res.warnings, src, slots, fonts_pair)
        res.logos_replaced, res.logos_removed = out_logos.replaced, out_logos.removed
        rep, cov = out_logos.add, out_logos.covers
        res.logos_added, res.logo_layouts, res.logo_place, res.logo_where = rep.added + cov.added, rep.layouts + cov.layouts, rep.place, rep.where
        res.logo_covers = cov.covered
        res.logo_samples, res.logo_covered, res.logo_note = out_logos.samples, out_logos.covered, out_logos.note
    elif not images:
        has_own = bool(find_template_logos(pkg, manifest, slots) or find_text_logos(pkg, manifest, fonts_pair, src))
        if brand.logos:
            res.warnings.append("Файлы логотипов брендбука не найдены — " + ("логотип шаблона оставлен." if has_own else "логотип бренда не поставлен."))
        else:
            from verstka.brand.read import NO_LOGO_FILES

            res.warnings.append(NO_LOGO_FILES)  # то же, что в предупреждениях самого брендбука, — одной фразой везде

    # знаки партнёров шаблона (у ЛЦТ — организаторы, впечатаны в фоны) не трогаются: брендбук заменяет логотип самого
    # шаблона, а не чужие знаки, которые принадлежат содержанию
    caps = caps_rule(brand) if priority == "brand" else None
    if caps is not None:
        res.caps_changed = _set_title_caps(pkg, caps)
    res.colors = {f"#{a}": f"#{b}" for (a, b) in sorted(colors)}
    res.font_swaps = {a: b for (a, b) in sorted(fonts)}
    res.changed_parts = pkg.save(out)
    return res


# ============================================================================================ хранилище и кэш


def brand_fingerprint(brand: BrandSpec, brand_dir: Optional[Path | str] = None) -> str:
    """Отпечаток всего, что влияет на копию: цвета, шрифты (и что из них есть на машине), логотипы (содержимое файлов),
    место логотипа, поля, правила."""
    data = brand.model_dump(mode="json", exclude={"id", "warnings", "file", "pages", "source"})
    logos = []
    for lg in brand.logos:
        p = logo_path(lg, brand_dir)
        logos.append(hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else None)
    written = [written_family(f)[0] for f in brand.fonts]
    payload = json.dumps({"brand": data, "logos": logos, "written": written, "v": APPLY_VERSION}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def branded_id(template_id: str, fingerprint: str, priority: str) -> str:
    return hashlib.sha256(f"{template_id}|{fingerprint}|{priority}|brand".encode()).hexdigest()[:16]


def branded_info(template_id: str, workspace_root: Optional[Path | str] = None) -> Optional[dict]:
    """`brand.json` брендированной копии (исходный шаблон, брендбук, приоритет, что сделано) или None — обычный шаблон."""
    if not SAFE_ID_RE.fullmatch(template_id or ""):
        return None
    root = Path(workspace_root) if workspace_root else default_workspace_root()
    try:
        return json.loads((root / "templates" / template_id / BRAND_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def branded_warnings(template_id: str, workspace_root: Optional[Path | str] = None) -> list[str]:
    """Предупреждения брендированной копии для человека — чтения брендбука и применения, без повторов: их печатает CLI
    и пишет run_manifest («Файлов логотипа в брендбуке нет — …»). [] — обычный шаблон."""
    info = branded_info(template_id, workspace_root) or {}
    out = list(info.get("brand_warnings") or []) + list((info.get("result") or {}).get("warnings") or [])
    return list(dict.fromkeys(w for w in out if w))


def _title_of(d: Path) -> str:
    for name in ("title.txt", "meta.txt"):
        try:
            t = (d / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if t:
            return Path(t).stem if name == "meta.txt" and t.lower().endswith((".pptx", ".potx")) else t
    return "Шаблон"


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _manifest_ok(d: Path) -> bool:
    try:
        version = json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("analysis_version")
    except (OSError, ValueError):
        return False
    return version == TemplateManifest.model_fields["analysis_version"].default


def _reuse_analysis(base: Path, d: Path, new_id: str) -> bool:
    """Копия совпала с шаблоном байт в байт: разбор шаблона годится и ей — копируется с новым id."""
    if not _manifest_ok(base):
        return False
    for sub in ("slides", "thumbs", "assets"):
        if (base / sub).is_dir() and not (d / sub).exists():
            shutil.copytree(base / sub, d / sub)
    for f in ("pictures.json", "gallery.html"):
        if (base / f).exists():
            shutil.copyfile(base / f, d / f)
    m = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    m["template_id"] = new_id
    tmp = d / ".manifest.json.tmp"
    tmp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / "manifest.json")
    return True


ProgressFn = Callable[[str, float], None]


def branded_template(
    template_id: str,
    brand: BrandSpec,
    priority: BrandPriority = "brand",
    *,
    workspace_root: Optional[Path | str] = None,
    brand_dir: Optional[Path | str] = None,
    render: bool = True,
    progress: Optional[ProgressFn] = None,
) -> str:
    """Id брендированной копии шаблона `template_id` (создаёт и разбирает без модели при первом вызове; дальше — из
    кэша по паре «шаблон + отпечаток брендбука» и приоритету). Шаблона нет — FileNotFoundError."""
    from verstka.analysis.manifest import analyze_template

    if priority not in ("brand", "template"):
        raise ValueError(f"неизвестный приоритет: {priority!r}")
    root = Path(workspace_root) if workspace_root else default_workspace_root()
    base = TemplateWorkspace.open(template_id, root)
    bdir = resolve_brand_dir(brand, brand_dir, root)
    fp = brand_fingerprint(brand, bdir)
    key = branded_id(template_id, fp, priority)
    d = root / "templates" / key

    def report(stage: str, frac: float) -> None:
        if progress:
            progress(stage, frac)

    with _lock(key):
        info = branded_info(key, root)
        fresh = (
            info is not None
            and info.get("brand_fingerprint") == fp
            and info.get("priority") == priority
            and info.get("base_template_id") == template_id
            and info.get("apply_version") == APPLY_VERSION
            and (d / "source.pptx").exists()
        )
        if fresh and _manifest_ok(d):
            report("брендированная копия — из кэша", 1.0)
            return key
        if not base.is_analyzed:
            report("разбираю шаблон", 0.0)
            analyze_template(base.source, workspace_root=root, use_llm=False, use_vlm=False, render=render)
        manifest = TemplateManifest.model_validate_json(base.manifest_path.read_text(encoding="utf-8"))
        d.mkdir(parents=True, exist_ok=True)
        if not fresh:
            report("применяю брендбук к шаблону", 0.02)
            fd, tmp_name = tempfile.mkstemp(prefix=".source.", suffix=".pptx", dir=d)
            os.close(fd)
            tmp = Path(tmp_name)
            try:
                res = apply_brand(base.source, tmp, brand, manifest=manifest, priority=priority, brand_dir=bdir)
                if not res.changed:
                    shutil.copyfile(base.source, tmp)
                os.replace(tmp, d / "source.pptx")
            finally:
                tmp.unlink(missing_ok=True)
            base_title = _title_of(base.dir)
            title = f"{base_title} · брендбук {brand.name}".strip() if brand.name else f"{base_title} · брендбук"
            (d / "meta.txt").write_text(f"{base.original_name}\n", encoding="utf-8")
            (d / "title.txt").write_text(title + "\n", encoding="utf-8")
            (d / "manifest.json").unlink(missing_ok=True)
            try:
                from verstka.brand.conflicts import brand_conflicts

                conflicts = [c.model_dump() for c in brand_conflicts(manifest, brand, priority=priority, source=base.source, workspace_root=root, brand_dir=bdir)]
            except Exception as e:  # noqa: BLE001 - расхождения — справка, копия от них не зависит
                log.warning("brand conflicts failed: %s", e)
                conflicts = []
            data = {
                "base_template_id": template_id,
                "brand_id": brand.id or None,
                "brand_name": brand.name,
                "brand_fingerprint": fp,
                "priority": priority,
                "apply_version": APPLY_VERSION,
                "title": title,
                "result": res.as_dict(),
                "conflicts": conflicts,
                "brand_warnings": list(brand.warnings),  # что сказало чтение брендбука (нет файлов логотипа…)
            }
            tmpj = d / f".{BRAND_FILE}.tmp"
            tmpj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmpj, d / BRAND_FILE)
            if not res.changed and _reuse_analysis(base.dir, d, key):
                report("брендбук ничего не меняет — разбор шаблона подходит копии", 1.0)
                return key
        report("разбираю брендированную копию", 0.05)
        copy = analyze_template(
            d / "source.pptx",
            workspace_root=root,
            use_llm=False,
            use_vlm=False,
            render=render,
            force=True,
            progress=(lambda stage, frac: report(stage, 0.05 + 0.95 * frac)) if progress else None,
        )
        # цвета картинок шаблона в разборе копии → цвета бренда (сами картинки не перекрашиваются), цвета диаграмм — бренда
        try:
            info = branded_info(key, root) or {}
            plan = brand_plan(base.source, manifest, brand, priority).colors
            if retune_manifest(copy, manifest, plan, (info.get("result") or {}).get("colors") or {}):
                tmpm = d / ".manifest.json.tmp"
                tmpm.write_text(copy.model_dump_json(indent=2), encoding="utf-8")
                os.replace(tmpm, d / "manifest.json")
        except Exception as e:  # noqa: BLE001 - разбор копии остаётся как есть
            log.warning("branded manifest retune failed: %s", e)
        return key
