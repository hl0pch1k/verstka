"""Подбор шрифтов под шаблон: шаблон, набранный стандартными шрифтами (Arial, Calibri, Times New Roman, шрифты
LibreOffice по умолчанию…), получает пару «заголовки / основной текст» из шрифтов Verstka (`verstka/fonts/`, OFL,
с кириллицей), подобранную по характеру самого шаблона.

Правила (владелец, 17.10):
- меняются ТОЛЬКО стандартные/системные шрифты (`STANDARD_FONTS`): у шаблона есть свой шрифт (Play у VK, Montserrat
  и Lato у ЛЦТ, любой не из списка) — оформление по шаблону, шрифты остаются как есть;
- есть брендбук со шрифтами — главнее брендбук (подбор не делается, `fonted_template(..., brand_fonts=True)`);
- выключатель «Подобрать шрифты» выключен — шаблон как есть.

Характер шаблона (`template_look`) — только общие признаки, без имени шаблона: геометрия фигур (скругления, острые
углы, косые линии, кривые), тонкие линии, картинки, пиксели миниатюр (тёмный фон, насыщенность, тёплые / холодные /
зелёные / землистые тона) и класс исходного шрифта (антиква, узкий). Каждая пара (`PAIRS`) — характер со своими
весами признаков; выбирается пара с наибольшим баллом (при равенстве — первая по списку), так что тот же шаблон всегда
получает ту же пару. Причина выбора — строкой («Почему так»).

Применение — как брендбук (`verstka.brand.apply`): копия шаблона с новыми шрифтами темы (`fontScheme`) и явных
`a:latin` по роли текста (заголовок / текст), подгонка строк образцов после смены шрифта (`_refit`), шрифты
встраиваются в копию (`verstka.brand.fontembed`) — колоды, собранные на копии, несут их в себе (PowerPoint у жюри,
LibreOffice при рендере превью и PDF). Копия разбирается как свой шаблон: вся вёрстка меряет текст новым шрифтом
(`rendering.fonts` знает файлы `verstka/fonts`).
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import logging
import math
import os
import re
import shutil
import tempfile
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from lxml import etree

from verstka.brand.apply import _LATIN, ApplyResult, FontPlan, _refit, _Roles, _SLIDE_LIKE_RE, _VISIBLE_RE, _THEME_RE, _lock, _manifest_ok, _title_of, font_base
from verstka.brand.package import A, P, Package
from verstka.ingest.workspace import SAFE_ID_RE, TemplateWorkspace, default_workspace_root
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

PICK_VERSION = "4"
FONTS_FILE = "fonts.json"

# Стандартные/системные шрифты — их ставит программа, а не дизайнер, поэтому их место свободно для подбора:
# - по умолчанию в офисных пакетах: PowerPoint (Calibri, Calibri Light, Aptos…; в старых темах Arial, Times New Roman,
#   Cambria), Google Slides (Arial), Keynote (Helvetica, Helvetica Neue);
# - по умолчанию в LibreOffice и его метрические двойники: Liberation Sans/Serif/Sans Narrow, DejaVu, Carlito, Caladea,
#   Noto Sans/Serif (шаблоны LibreOffice 7+), Open Sans и Source Sans Pro (шрифты стандартных тем Impress);
# - системные шрифты интерфейса Windows/macOS: Segoe UI, Tahoma, Verdana, Times, Arial Narrow.
# Не в списке (= шрифт дизайнера, остаётся): Georgia, Trebuchet MS, Century Gothic, Gill Sans… — их выбирают
# намеренно (темы Office «Грань», «Ион»…), и все не системные гарнитуры (Play, Montserrat, Lato, Roboto, Inter…).
STANDARD_FONTS = frozenset(
    x.lower()
    for x in (
        "Calibri", "Calibri Light", "Aptos", "Aptos Display", "Aptos Narrow", "Cambria", "Arial", "Arial Narrow",
        "Helvetica", "Helvetica Neue", "Times New Roman", "Times", "Segoe UI", "Segoe UI Light", "Segoe UI Semibold",
        "Tahoma", "Verdana", "Liberation Sans", "Liberation Serif", "Liberation Sans Narrow", "DejaVu Sans",
        "DejaVu Serif", "DejaVu Sans Condensed", "Carlito", "Caladea", "Noto Sans", "Noto Serif", "Open Sans",
        "Source Sans Pro", "Source Sans 3",
    )
)
_SYMBOL_RE = re.compile(r"symbol|wingding|webding|dingbat|marlett|mt extra|zapf|emoji|icons?\b|awesome|glyph", re.I)
_MONO_RE = re.compile(r"mono|consol|courier|menlo|monaco|\bcode\b|typewriter|fixed", re.I)
_OWN_MIN_SHARE = 0.02  # своим шрифт шаблона считается, когда им набрано ≥ 2 % знаков образцов


def is_standard(family: Optional[str]) -> bool:
    """Шрифт стандартный/системный (его можно заменить подобранным)."""
    name = (family or "").strip().lower()
    return bool(name) and (name in STANDARD_FONTS or font_base(name) in STANDARD_FONTS)


# ============================================================================================ пары


@dataclass(frozen=True)
class FontPair:
    key: str
    character: str  # характер словами — для «Почему так»
    heading: str
    body: str
    weights: tuple[tuple[str, float], ...]  # признак → вес
    bias: float = 0.0


# Признаки (0…1): dark — тёмный фон; colorful — насыщенные цвета; warm / cool / green / purple — доли тонов среди
# насыщенных пикселей; earthy — бежевые, песочные, коричневые тона; achrom — палитра без цвета; round — скругления
# среди фигур; angular — острые углы; diagonal — косые края и повёрнутые фигуры; curvy — свободные кривые;
# thin — тонкие линии; photo — фотографии и фоновые картинки; serif — шрифт шаблона антиква; narrow — узкий.
# Каждый шрифт пар — с выравненными (лайнинговыми) цифрами и знаками «→ ₽ № ×» (тест test_pairs_cover_figures_and_signs):
# KPI, таблицы и стрелки «61 → 35» не берутся из запасного шрифта и не «прыгают» по высоте. Шрифт заголовков ставится
# только заголовкам (и крупным цифрам), всё остальное — основным шрифтом.
PAIRS: tuple[FontPair, ...] = (
    FontPair("modern", "современный нейтральный", "Manrope", "Onest", (), bias=0.35),
    FontPair("strict", "строгий деловой", "IBM Plex Sans", "IBM Plex Sans", (("cool", 0.45), ("angular", 0.35), ("achrom", 0.25), ("round", -0.4), ("warm", -0.3), ("dark", -0.15))),
    FontPair("tech", "технологичный", "Geologica", "Manrope", (("dark_cool", 1.1), ("angular", 0.25), ("round", -0.2), ("earthy", -0.5))),
    FontPair("bright", "яркий, смелый", "Unbounded", "Onest", (("colorful_warm", 0.95), ("colorful", 0.25), ("earthy", -0.6), ("dark", -0.2))),
    FontPair("friendly", "мягкий, дружелюбный", "Comfortaa", "Manrope", (("round", 0.75), ("colorful", 0.2), ("angular", -0.35), ("achrom", -0.3))),
    FontPair("natural", "природный, живой", "Literata", "Fira Sans", (("green", 0.85), ("curvy", 0.35), ("dark", -0.3))),
    FontPair("elegant", "элегантный, контрастный", "Spectral", "Manrope", (("achrom_contrast", 0.85), ("thin", 0.25), ("serif", 0.2), ("colorful", -0.4))),
    FontPair("warm", "тёплый, человечный", "Bitter", "Fira Sans", (("warm", 0.45), ("curvy", 0.3), ("colorful", -0.15), ("dark", -0.3), ("cool", -0.3))),
    FontPair("vintage", "винтажный", "Old Standard TT", "Source Serif 4", (("earthy", 1.2), ("serif", 0.25), ("photo", 0.15), ("cool", -0.3))),
    FontPair("academic", "классический, академический", "IBM Plex Serif", "IBM Plex Sans", (("serif", 0.85), ("cool", 0.15), ("earthy", -0.3))),
    FontPair("dynamic", "динамичный", "Fira Sans Condensed", "IBM Plex Sans", (("diagonal", 0.8), ("narrow", 0.7), ("round", -0.3))),
    FontPair("geometric", "геометрический минимализм", "Geologica", "Onest", (("circles_light", 0.7), ("thin", 0.2), ("colorful", -0.2))),
)
PAIR_BY_KEY = {p.key: p for p in PAIRS}

_FEATURE_RU = {
    "dark": "тёмный фон", "colorful": "насыщенные цвета", "warm": "тёплые тона", "cool": "холодные тона",
    "green": "зелёные тона", "purple": "пурпурные тона", "earthy": "бежевые и коричневые тона", "achrom": "палитра без цвета",
    "round": "скруглённые фигуры", "angular": "острые углы", "diagonal": "косые края", "curvy": "свободные кривые",
    "thin": "тонкие линии", "photo": "фотографии и фоновые картинки", "serif": "антиква в шаблоне", "narrow": "узкий шрифт в шаблоне",
    "dark_cool": "тёмный фон в холодных тонах", "colorful_warm": "насыщенные тёплые цвета", "achrom_contrast": "чёрно-белая контрастная палитра",
    "circles_light": "круги и линии на светлом фоне",
}


# ============================================================================================ характер шаблона


_ROUND_PRST = {
    "ellipse", "roundRect", "round1Rect", "round2SameRect", "round2DiagRect", "flowChartTerminator", "flowChartConnector",
    "flowChartAlternateProcess", "donut", "arc", "pie", "chord", "blockArc", "wave", "doubleWave", "cloud", "cloudCallout",
    "wedgeRoundRectCallout", "wedgeEllipseCallout", "moon", "smileyFace", "heart", "teardrop", "ellipseRibbon", "ellipseRibbon2",
    "snipRoundRect", "flowChartMagneticDisk", "can", "noSmoking",
}
_CIRCLE_PRST = {"ellipse", "donut", "arc", "pie", "chord", "blockArc", "flowChartConnector"}
_ANGULAR_PRST = {
    "triangle", "rtTriangle", "parallelogram", "trapezoid", "diamond", "pentagon", "hexagon", "heptagon", "octagon",
    "decagon", "dodecagon", "homePlate", "chevron", "snip1Rect", "snip2SameRect", "snip2DiagRect", "star4", "star5",
    "star6", "star7", "star8", "star10", "star12", "flowChartDecision", "flowChartPreparation", "flowChartExtract",
    "flowChartMerge", "flowChartManualOperation", "flowChartPunchedCard", "rightArrow", "leftArrow", "upArrow",
    "downArrow", "notchedRightArrow", "stripedRightArrow", "flowChartInputOutput", "corner", "diagStripe", "plus", "cross",
}
_DIAGONAL_PRST = {"parallelogram", "trapezoid", "rtTriangle", "triangle", "diagStripe", "snip1Rect", "snip2DiagRect", "flowChartManualOperation"}
_GEOM_PARTS_RE = re.compile(r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+)\.xml$")


def _geometry(src: Path | str) -> dict[str, float]:
    """Признаки фигур шаблона: доли скруглённых / острых / косых фигур, кривые, тонкие линии, картинки."""
    shapes: Counter = Counter()
    seen: set = set()
    pic_area = 0.0
    bg_images = 0
    bg_total = 0
    thin = lines = 0
    with zipfile.ZipFile(src) as z:
        try:
            pres = etree.fromstring(z.read("ppt/presentation.xml"))
            sz = pres.find(f"{{{P}}}sldSz")
            slide_area = float(sz.get("cx")) * float(sz.get("cy")) if sz is not None else 9144000.0 * 5143500.0
        except (KeyError, etree.XMLSyntaxError, TypeError, ValueError):
            slide_area = 9144000.0 * 5143500.0
        parts = [n for n in z.namelist() if _GEOM_PARTS_RE.match(n)]
        for name in parts:
            try:
                root = etree.fromstring(z.read(name))
            except etree.XMLSyntaxError:
                continue
            bg = root.find(f".//{{{P}}}bg")
            if bg is not None:
                bg_total += 1
                if bg.find(f".//{{{A}}}blip") is not None:
                    bg_images += 1
            for sp in root.iter(f"{{{P}}}sp", f"{{{P}}}cxnSp"):
                sppr = sp.find(f"{{{P}}}spPr")
                if sppr is None:
                    continue
                xfrm = sppr.find(f"{{{A}}}xfrm")
                ext = xfrm.find(f"{{{A}}}ext") if xfrm is not None else None
                off = xfrm.find(f"{{{A}}}off") if xfrm is not None else None
                prst = sppr.find(f"{{{A}}}prstGeom")
                cust = sppr.find(f"{{{A}}}custGeom")
                kind = None
                if prst is not None:
                    pv = prst.get("prst") or "rect"
                    if pv in _ROUND_PRST:
                        kind = "circle" if pv in _CIRCLE_PRST else "round"
                    elif pv in _ANGULAR_PRST:
                        kind = "diagonal" if pv in _DIAGONAL_PRST else "angular"
                    elif pv in ("line", "straightConnector1"):
                        kind = "line"
                    elif pv == "rect":
                        rot = int(xfrm.get("rot") or 0) if xfrm is not None and (xfrm.get("rot") or "0").lstrip("-").isdigit() else 0
                        kind = "diagonal" if rot % 5400000 not in (0,) and abs(rot % 5400000) > 60000 else None
                elif cust is not None:
                    curved = cust.find(f".//{{{A}}}cubicBezTo") is not None or cust.find(f".//{{{A}}}arcTo") is not None or cust.find(f".//{{{A}}}quadBezTo") is not None
                    kind = "curvy" if curved else "angular_free"
                ln = sppr.find(f"{{{A}}}ln")
                if ln is not None and ln.find(f"{{{A}}}noFill") is None and (ln.get("w") or "").isdigit():
                    lines += 1
                    if int(ln.get("w")) <= 12700:
                        thin += 1
                if kind is None:
                    continue
                # одна и та же фигура на многих макетах (соты, повторы) считается один раз
                sig = (kind, ext.get("cx") if ext is not None else None, ext.get("cy") if ext is not None else None, off.get("x") if off is not None else None, off.get("y") if off is not None else None)
                if sig in seen:
                    continue
                seen.add(sig)
                shapes[kind] += 1
            for pic in root.iter(f"{{{P}}}pic"):
                ext = pic.find(f"{{{P}}}spPr/{{{A}}}xfrm/{{{A}}}ext")
                if ext is not None and (ext.get("cx") or "").isdigit() and (ext.get("cy") or "").isdigit():
                    pic_area += int(ext.get("cx")) * int(ext.get("cy")) / slide_area
    total = sum(shapes.values())
    n_parts = max(1, len(parts))

    def share(*kinds: str) -> float:
        return sum(shapes[k] for k in kinds) / total if total else 0.0

    # мало фигур — признак слабый: доля умножается на «уверенность» (8 и больше разных фигур — полная)
    conf = min(1.0, total / 8.0)
    return {
        "round": round(share("round", "circle") * conf, 3),
        "circles": round(share("circle") * conf, 3),
        "angular": round(share("angular", "diagonal", "angular_free") * conf, 3),
        "diagonal": round(share("diagonal") * conf, 3),
        "curvy": round(share("curvy") * conf, 3),
        "thin": round(thin / lines, 3) if lines >= 3 else 0.0,
        "photo": round(min(1.0, bg_images / max(1, bg_total) * 0.6 + pic_area / n_parts * 0.8), 3),
        "shapes": float(total),
    }


def _pixels(images: list[Path]) -> Optional[dict[str, float]]:
    """Признаки цвета по миниатюрам шаблона: тёмный фон, насыщенность, доли тонов. None — миниатюр нет."""
    from PIL import Image

    px: list[tuple[float, float, float]] = []
    for p in images[:16]:
        try:
            with Image.open(p) as im:
                small = im.convert("RGB").resize((48, 27), Image.BILINEAR)
                raw = small.tobytes()
                px.extend(colorsys.rgb_to_hsv(raw[i] / 255, raw[i + 1] / 255, raw[i + 2] / 255) for i in range(0, len(raw), 3))
        except Exception:  # noqa: BLE001 - битая миниатюра пропускается
            continue
    if not px:
        return None
    n = len(px)
    dark = sum(1 for h, s, v in px if v < 0.28) / n
    colorful = [(h, s, v) for h, s, v in px if s > 0.35 and v > 0.3]
    cf = len(colorful) / n
    earthy = sum(1 for h, s, v in px if 15 / 360 <= h <= 55 / 360 and 0.12 <= s <= 0.6 and 0.4 <= v <= 0.97) / n

    def hue_share(lo: float, hi: float) -> float:
        if not colorful:
            return 0.0
        return sum(1 for h, s, v in colorful if lo <= h * 360 < hi) / len(colorful)

    warm = hue_share(0, 65) + hue_share(330, 360)
    green = hue_share(65, 170)
    cool = hue_share(170, 270)
    purple = hue_share(270, 330)
    # тон акцентов — по насыщенным пикселям, сколько бы их ни было (оранжевый карандаш на белом — тёплый шаблон);
    # совсем без цвета (< 0,5 % пикселей) тона нет
    k = 1.0 if cf >= 0.005 else 0.0
    return {
        "dark": round(dark, 3),
        "colorful": round(min(1.0, cf / 0.4), 3),
        "warm": round(warm * k, 3),
        "green": round(green * k, 3),
        "cool": round(cool * k, 3),
        "purple": round(purple * k, 3),
        "earthy": round(min(1.0, earthy / 0.35), 3),
        "achrom": round(max(0.0, 1.0 - cf / 0.06), 3),
    }


def _palette(manifest: TemplateManifest) -> dict[str, float]:
    """Те же признаки цвета по цветам разбора (нет миниатюр): веса цветов вместо пикселей."""
    tot = 0.0
    acc: Counter = Counter()
    for c in manifest.tokens.colors:
        try:
            r, g, b = (int(c.hex[i : i + 2], 16) / 255 for i in (0, 2, 4))
        except (ValueError, TypeError):
            continue
        w = math.log1p(max(0.0, c.weight))
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        tot += w
        if v < 0.28 and "background" in (c.role or ""):
            acc["dark"] += w
        if s > 0.35 and v > 0.3:
            acc["colorful"] += w
            hd = h * 360
            acc["warm" if hd < 65 or hd >= 330 else "green" if hd < 170 else "cool" if hd < 270 else "purple"] += w
        if 15 <= h * 360 <= 55 and 0.12 <= s <= 0.6 and 0.4 <= v <= 0.97:
            acc["earthy"] += w
    if not tot:
        return {k: 0.0 for k in ("dark", "colorful", "warm", "green", "cool", "purple", "earthy", "achrom")}
    out = {k: round(acc[k] / tot, 3) for k in ("dark", "colorful", "earthy")}
    col = acc["colorful"] or 1.0
    k = 1.0 if out["colorful"] > 0 else 0.0
    out.update({h: round(acc[h] / col * k, 3) for h in ("warm", "green", "cool", "purple")})
    out["achrom"] = round(max(0.0, 1.0 - out["colorful"] / 0.06), 3)
    out["colorful"] = round(min(1.0, out["colorful"] / 0.4), 3)
    return out


def template_fonts_used(manifest: TemplateManifest, src: Optional[Path | str] = None) -> tuple[list[str], list[str]]:
    """(шрифты текста образцов с долей ≥ 2 %, шрифты темы major/minor) шаблона."""
    text = [f.family for f in manifest.tokens.typography.families if f.source == "text" and f.weight >= _OWN_MIN_SHARE]
    theme: list[str] = [f.family for f in manifest.tokens.typography.families if f.source == "theme"]
    if src:
        try:
            with zipfile.ZipFile(src) as z:
                for n in sorted(z.namelist()):
                    if _THEME_RE.match(n):
                        root = etree.fromstring(z.read(n))
                        for which in ("major", "minor"):
                            lat = root.find(f".//{{{A}}}fontScheme/{{{A}}}{which}Font/{{{A}}}latin")
                            if lat is not None and lat.get("typeface"):
                                theme.append(lat.get("typeface"))
                        break  # тема первого мастера
        except (zipfile.BadZipFile, OSError, KeyError, etree.XMLSyntaxError):
            pass
    return list(dict.fromkeys(text)), list(dict.fromkeys(theme))


def template_look(manifest: TemplateManifest, src: Path | str, thumbs: Optional[list[Path]] = None) -> dict[str, float]:
    """Характер шаблона — признаки 0…1 (см. `PAIRS`)."""
    from verstka.brand.apply import template_fonts
    from verstka.rendering.fonts import font_class

    feats = dict(_geometry(src))
    color = _pixels(thumbs) if thumbs else None
    feats.update(color if color is not None else _palette(manifest))
    head, body = template_fonts(manifest)
    classes = [font_class(f) for f in (head, body) if f]
    feats["serif"] = 1.0 if "serif" in classes else 0.0
    feats["narrow"] = 1.0 if any(c in ("condensed", "display_condensed") for c in classes) else 0.0
    # составные признаки
    feats["dark_cool"] = round(feats["dark"] * min(1.0, feats["cool"] + feats["purple"]) * 1.6, 3)
    feats["colorful_warm"] = round(feats["colorful"] * feats["warm"], 3)
    feats["achrom_contrast"] = round(feats["achrom"] * min(1.0, feats["dark"] * 3.0), 3)
    feats["circles_light"] = round(feats["circles"] * (1.0 - feats["dark"]) * (1.0 - feats["colorful"]), 3)
    return {k: min(1.0, max(0.0, v)) if k != "shapes" else v for k, v in feats.items()}


def score_pairs(look: dict[str, float]) -> list[tuple[float, FontPair, list[tuple[str, float]]]]:
    """Пары по убыванию балла: (балл, пара, вклады признаков)."""
    out = []
    for i, pair in enumerate(PAIRS):
        contrib = [(f, w * look.get(f, 0.0)) for f, w in pair.weights]
        out.append((round(pair.bias + sum(c for _, c in contrib), 4), -i, pair, contrib))
    out.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [(s, p, c) for s, _, p, c in out]


# ============================================================================================ решение


@dataclass
class FontChoice:
    """Решение о шрифтах шаблона — для копии, `fonts.json` и «Почему так»."""

    apply: bool = False
    heading: Optional[str] = None
    body: Optional[str] = None
    heading_from: Optional[str] = None
    body_from: Optional[str] = None
    pair: Optional[str] = None
    character: Optional[str] = None
    reason: str = ""
    look: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def choose_fonts(manifest: TemplateManifest, src: Path | str, thumbs: Optional[list[Path]] = None, *, brand_fonts: bool = False, enabled: bool = True) -> FontChoice:
    """Пара шрифтов для шаблона или решение оставить его шрифты (с причиной)."""
    from verstka.brand.apply import template_fonts

    head, body = template_fonts(manifest)
    ch = FontChoice(heading_from=head, body_from=body)
    if not enabled:
        ch.reason = "Подбор шрифтов выключен — шрифты шаблона как есть."
        return ch
    if brand_fonts:
        ch.reason = "Шрифты заданы брендбуком — подбор не нужен."
        return ch
    text, theme = template_fonts_used(manifest, src)
    fams = [f for f in dict.fromkeys([*text, *theme, *(x for x in (head, body) if x)]) if f and not f.startswith("+")]
    own = [f for f in fams if not is_standard(f) and not _SYMBOL_RE.search(f) and not _MONO_RE.search(f)]
    if own:
        ch.reason = f"У шаблона свой шрифт ({', '.join(own[:3])}) — оформление по шаблону, шрифты не меняются."
        return ch
    if not fams:
        ch.reason = "Шрифты шаблона не определены — оставлены как есть."
        return ch
    look = template_look(manifest, src, thumbs)
    ranked = score_pairs(look)
    score, pair, contrib = ranked[0]
    ch.apply = True
    ch.heading, ch.body, ch.pair, ch.character = pair.heading, pair.body, pair.key, pair.character
    ch.look = look
    ch.scores = {p.key: s for s, p, _ in ranked}
    signs = [_FEATURE_RU.get(f, f) for f, c in sorted(contrib, key=lambda x: -x[1]) if c >= 0.08]
    std = ", ".join(dict.fromkeys(font_base(f).title() if f.lower() == font_base(f) else f for f in fams[:3]))
    pair_txt = f"«{pair.heading}»" if pair.heading == pair.body else f"заголовки «{pair.heading}», текст «{pair.body}»"
    why = f" по признакам шаблона: {', '.join(signs[:3])}" if signs else " (ярких признаков у шаблона нет — нейтральная пара)"
    ch.reason = f"Шрифты шаблона стандартные ({std}) — подобрана пара «{pair.character}»: {pair_txt}{why}."
    return ch


# ============================================================================================ копия шаблона


class _PickPlan(FontPlan):
    """План брендбука, но меняются только стандартные шрифты (шрифт дизайнера внутри шаблона остаётся)."""

    def target(self, family: Optional[str], role: str) -> Optional[str]:
        name = (family or "").strip()
        if not name or name.startswith("+") or _SYMBOL_RE.search(name) or _MONO_RE.search(name) or not is_standard(name):
            return None
        to = self.heading_to if role == "heading" else self.body_to
        return None if not to or name == to else to


def _plan(manifest: TemplateManifest, ch: FontChoice) -> _PickPlan:
    fp = _PickPlan(priority="brand")
    fp.heading_from, fp.body_from = ch.heading_from, ch.body_from
    fp.heading_to, fp.body_to = ch.heading, ch.body
    fp.heading_min_pt = heading_threshold(manifest)
    return fp


class _PickRoles(_Roles):
    """Роль текста для подбора: заголовок-заполнитель (title, ctrTitle) — шрифт заголовков, любой другой заполнитель
    (текст, подзаголовок, объект, подпись) — шрифт текста при любом кегле (у шаблонов LibreOffice основной текст
    макета 32 пт); надпись вне заполнителя — по кеглю (`heading_min_pt`)."""

    def role(self, el: etree._Element) -> str:
        for anc in el.iterancestors():
            if anc.tag in (f"{{{P}}}titleStyle", f"{{{P}}}bodyStyle", f"{{{P}}}otherStyle"):
                break
            if anc.tag == f"{{{P}}}sp":
                ph = anc.find(f"{{{P}}}nvSpPr/{{{P}}}nvPr/{{{P}}}ph")
                if ph is not None:
                    return "heading" if (ph.get("type") or "") in self._HEAD_PH else "body"
                break
        return super().role(el)


def _refont(root: etree._Element, fp: FontPlan, counter: Counter, swapped: Optional[dict] = None) -> bool:
    """Как `brand.apply._refont`, с ролями подбора (`_PickRoles`)."""
    roles = _PickRoles(fp)
    changed = False
    for lat in list(root.iter(_LATIN)):
        if any(a.tag == f"{{{A}}}fontScheme" for a in lat.iterancestors()):
            continue
        old = lat.get("typeface")
        new = fp.target(old, roles.role(lat))
        if new:
            counter[(old, new)] += 1
            lat.set("typeface", new)
            changed = True
            if swapped is not None and lat.getparent() is not None:
                swapped[lat.getparent()] = old
    return changed


def _master_body_pt(pkg: Package) -> Optional[float]:
    """Кегль первого уровня основного текста мастера (`p:bodyStyle`), пт — когда разбор шкалы не дал."""
    for name in sorted(pkg.names()):
        if re.match(r"^ppt/slideMasters/slideMaster\d+\.xml$", name):
            root = pkg.xml(name)
            el = root.find(f".//{{{P}}}bodyStyle/{{{A}}}lvl1pPr/{{{A}}}defRPr") if root is not None else None
            if el is not None and (el.get("sz") or "").isdigit():
                return int(el.get("sz")) / 100.0
    return None


def heading_threshold(manifest: TemplateManifest, body_pt: Optional[float] = None) -> float:
    """Кегль, начиная с которого текст вне заголовка-заполнителя набирается шрифтом заголовков: заметно крупнее
    основного текста шаблона (×1,25) или около его заголовков (×0,85), в пределах 20…36 пт. Шкала разбора у шаблона
    с пустыми образцами бывает «заголовок 14 пт = текст 14 пт» — тогда весь текст был бы «заголовком»."""
    scale = manifest.tokens.typography.scale
    big = [s.size_pt for s in scale if s.role in ("display", "h1") and s.size_pt]
    body = [s.size_pt for s in scale if s.role == "body" and s.size_pt]
    h1 = min(big) if big else None
    b = body[0] if body else body_pt
    if h1 and b and h1 > b * 1.2:
        thr = h1 * 0.85
    elif b:
        thr = b * 1.25
    else:
        thr = (h1 or 28.0) * 0.85
    return round(min(36.0, max(20.0, thr)), 1)


def apply_fonts(src: Path | str, out: Path | str, manifest: TemplateManifest, ch: FontChoice, *, embed: bool = True) -> ApplyResult:
    """Пишет в `out` копию шаблона `src` с подобранными шрифтами (тема, явные шрифты по роли, подгонка строк образцов)
    и встраивает их файлы."""
    pkg = Package(src)
    res = ApplyResult(priority="brand")
    fp = _plan(manifest, ch)
    fp.heading_min_pt = heading_threshold(manifest, _master_body_pt(pkg))
    fonts: Counter = Counter()
    for name in pkg.names():
        root = pkg.xml(name) if (_THEME_RE.match(name) or _VISIBLE_RE.match(name)) else None
        if root is None:
            continue
        changed = False
        if _THEME_RE.match(name):
            for which, role in (("major", "heading"), ("minor", "body")):
                lat = root.find(f".//{{{A}}}fontScheme/{{{A}}}{which}Font/{{{A}}}latin")
                new = fp.target(lat.get("typeface"), role) if lat is not None else None
                if new:
                    fonts[(lat.get("typeface"), new)] += 1
                    lat.set("typeface", new)
                    changed = True
            od = root.find(f".//{{{A}}}objectDefaults")
            if od is not None:
                changed |= _refont(od, fp, fonts)
        else:
            swapped: dict = {}
            changed = _refont(root, fp, fonts, swapped)
            if swapped and _SLIDE_LIKE_RE.match(name):
                _refit(root, swapped, res)
        if changed:
            pkg.dirty.add(name)
    res.fonts = {"heading": ch.heading or "", "body": ch.body or ""}
    res.font_swaps = {f"{a} → {b}": n for (a, b), n in sorted(fonts.items())}
    res.changed_parts = pkg.save(out)
    if embed and res.changed_parts:
        from verstka.brand.fontembed import embed_fonts

        embed_fonts(out, [x for x in (ch.heading, ch.body) if x])
    return res


# роли образцов, которые остаются в шрифте заголовков; крупная цифра — если у шрифта заголовков выравненные цифры
_HEAD_ROLES = {"title"}
_FIGURE_ROLES = {"number"}


def heading_figures_ok(family: Optional[str]) -> bool:
    """У шрифта заголовков выравненные цифры и все знаки колоды (`fontembed.SIGNS`) — им можно набрать крупную цифру."""
    from verstka.brand.fontembed import figures_report

    if not family:
        return False
    lining, missing = figures_report(family)
    return lining and not missing


def retune_roles(manifest: TemplateManifest, ch: FontChoice) -> bool:
    """Разбор копии → роли шрифтов: основной шрифт — первым в `typography.families` (`primary_family` — шрифт, которым
    вёрстка набирает свой текст: списки, карточки, подписи, таблицы, графики), слоты образцов и стиль графиков не в
    роли заголовка — основным шрифтом. У копии без текста на образцах разбор ставит первым шрифт темы major
    (заголовков) — и весь текст колоды шёл бы шрифтом заголовков. True — разбор изменён."""
    from verstka.schemas.template import FontUsage

    head, body = ch.heading, ch.body
    if not ch.apply or not body:
        return False
    changed = False
    fams = manifest.tokens.typography.families
    i = next((k for k, f in enumerate(fams) if f.family == body), None)
    if i is None:
        fams.insert(0, FontUsage(family=body, weight=0.0, source="theme"))
        changed = True
    elif i:
        fams.insert(0, fams.pop(i))
        changed = True
    if head and head != body:
        keep = _HEAD_ROLES | (_FIGURE_ROLES if heading_figures_ok(head) else set())
        for pat in manifest.patterns:
            for sl in pat.slots:
                role = getattr(sl.role, "value", sl.role)
                if sl.style.font_family == head and role not in keep:
                    sl.style.font_family = body
                    changed = True
        cs = manifest.components.chart_style
        if cs.font_family == head:
            cs.font_family = body
            changed = True
    return changed


def fonted_id(template_id: str, ch: FontChoice) -> str:
    return hashlib.sha256(f"{template_id}|{ch.heading}|{ch.body}|{PICK_VERSION}|fonts".encode()).hexdigest()[:16]


def fonts_info(template_id: str, workspace_root: Optional[Path | str] = None) -> Optional[dict]:
    """`fonts.json` копии с подобранными шрифтами (исходный шаблон, пара, причина) или None — обычный шаблон."""
    if not SAFE_ID_RE.fullmatch(template_id or ""):
        return None
    root = Path(workspace_root) if workspace_root else default_workspace_root()
    try:
        return json.loads((root / "templates" / template_id / FONTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def font_reason(template_id: str, workspace_root: Optional[Path | str] = None) -> Optional[str]:
    """Строка «Почему так» о шрифтах колоды, собранной на копии `template_id`, или None."""
    info = fonts_info(template_id, workspace_root)
    return (info or {}).get("choice", {}).get("reason") or None


ProgressFn = Callable[[str, float], None]


def pick_for_template(template_id: str, *, workspace_root: Optional[Path | str] = None, brand_fonts: bool = False, enabled: bool = True) -> FontChoice:
    """Решение о шрифтах для разобранного шаблона (без копии) — для показа в интерфейсе до сборки."""
    root = Path(workspace_root) if workspace_root else default_workspace_root()
    base = TemplateWorkspace.open(template_id, root)
    info = fonts_info(template_id, root)
    if info and info.get("choice"):
        return FontChoice(**info["choice"])  # шаблон — сама копия: решение уже принято
    manifest = TemplateManifest.model_validate_json(base.manifest_path.read_text(encoding="utf-8"))
    thumbs = sorted(base.thumbs_dir.glob("*.jpg")) or sorted(base.slides_dir.glob("*.jpg"))
    return choose_fonts(manifest, base.source, thumbs, brand_fonts=brand_fonts, enabled=enabled)


def fonted_template(
    template_id: str,
    *,
    enabled: bool = True,
    brand_fonts: bool = False,
    workspace_root: Optional[Path | str] = None,
    render: bool = True,
    progress: Optional[ProgressFn] = None,
) -> tuple[str, FontChoice]:
    """(id шаблона, на котором собирать колоду; решение о шрифтах). Подбор не нужен (выключен, брендбук со шрифтами,
    у шаблона свой шрифт) — id самого шаблона. Иначе — id копии с подобранными шрифтами: создаётся и разбирается без
    модели при первом вызове, дальше — из кэша. Шаблон не разобран — разбирается."""
    from verstka.analysis.manifest import analyze_template

    root = Path(workspace_root) if workspace_root else default_workspace_root()
    base = TemplateWorkspace.open(template_id, root)

    def report(stage: str, frac: float) -> None:
        if progress:
            progress(stage, frac)

    if fonts_info(template_id, root):  # уже копия с подобранными шрифтами
        return template_id, FontChoice(**fonts_info(template_id, root)["choice"])
    if not base.is_analyzed:
        report("разбираю шаблон", 0.0)
        analyze_template(base.source, workspace_root=root, use_llm=False, use_vlm=False, render=render)
    manifest = TemplateManifest.model_validate_json(base.manifest_path.read_text(encoding="utf-8"))
    thumbs = sorted(base.thumbs_dir.glob("*.jpg")) or sorted(base.slides_dir.glob("*.jpg"))
    ch = choose_fonts(manifest, base.source, thumbs, brand_fonts=brand_fonts, enabled=enabled)
    if not ch.apply:
        return template_id, ch
    key = fonted_id(template_id, ch)
    d = root / "templates" / key
    with _lock(key):
        info = fonts_info(key, root)
        fresh = bool(info) and info.get("base_template_id") == template_id and info.get("pick_version") == PICK_VERSION and (d / "source.pptx").exists()
        if fresh and _manifest_ok(d):
            report("шрифты подобраны — копия из кэша", 1.0)
            return key, FontChoice(**info["choice"])
        d.mkdir(parents=True, exist_ok=True)
        if not fresh:
            report(f"ставлю шрифты {ch.heading} / {ch.body}", 0.02)
            fd, tmp_name = tempfile.mkstemp(prefix=".source.", suffix=".pptx", dir=d)
            os.close(fd)
            tmp = Path(tmp_name)
            try:
                res = apply_fonts(base.source, tmp, manifest, ch)
                if not res.changed:
                    # стандартных шрифтов в частях не нашлось (только в разборе) — копия не нужна
                    shutil.rmtree(d, ignore_errors=True)
                    ch.apply = False
                    ch.reason = "Шрифты шаблона не найдены в его частях — оставлены как есть."
                    return template_id, ch
                os.replace(tmp, d / "source.pptx")
            finally:
                tmp.unlink(missing_ok=True)
            pair = ch.heading if ch.heading == ch.body else f"{ch.heading} / {ch.body}"
            (d / "meta.txt").write_text(f"{base.original_name}\n", encoding="utf-8")
            (d / "title.txt").write_text(f"{_title_of(base.dir)} · шрифты {pair}\n", encoding="utf-8")
            (d / "manifest.json").unlink(missing_ok=True)
            data = {"base_template_id": template_id, "pick_version": PICK_VERSION, "choice": ch.as_dict(), "result": res.as_dict()}
            tmpj = d / f".{FONTS_FILE}.tmp"
            tmpj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmpj, d / FONTS_FILE)
        report("разбираю шаблон с новыми шрифтами", 0.05)
        copy = analyze_template(
            d / "source.pptx", workspace_root=root, use_llm=False, use_vlm=False, render=render, force=True,
            progress=(lambda stage, frac: report(stage, 0.05 + 0.95 * frac)) if progress else None,
        )
        if retune_roles(copy, ch):
            tmpm = d / ".manifest.json.tmp"
            tmpm.write_text(copy.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmpm, d / "manifest.json")
        return key, ch
