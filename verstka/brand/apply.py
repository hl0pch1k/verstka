"""Брендбук → брендированная копия шаблона (описание решения §5, «Применение»).

ТЗ: палитра, типографика и фирменные элементы брендбука применяются к слайдам; при расхождении с шаблоном важнее
брендбук, если пользователь не выбрал иное. Решение — **копия шаблона**, переписанная под бренд и разобранная как
отдельный шаблон (свой id, без модели): весь конвейер, аудит палитры и шрифтов работают на ней без изменений.

Что переписывается в копии (`apply_brand`):
- тема: `clrScheme` (слоты — по тем же правилам, что и явные цвета) и `fontScheme` (заголовки, текст);
- явные цвета (`a:srgbClr`) слайдов, макетов, мастеров, диаграмм и SmartArt — по ролям из разбора шаблона
  (`tokens.colors`: role / roles): акценты палитры шаблона → хроматические цвета бренда (первый — основной цвет
  бренда, остальные — по близости тона, без повторов, пока есть свободные; «акцент» бренда — только близкому тону),
  оттенки акцентов (светлые плашки) — тем же сдвигом тона с сохранением светлоты, цвет текста → текст бренда, фон →
  фон бренда (только той же полярности: светлый фон не становится тёмным), тёмные и светлые нейтральные — тем же
  сдвигом, что текст и фон; смысловые цвета (рост / падение) → «успех» / «опасность» бренда или как были; серые —
  как были. Картинки не перекрашиваются никогда (цвета внутри `a:blip` не трогаются);
- шрифты (`a:latin`) текстов, мастеров, макетов, диаграмм — как `rendering.cyrillic.apply_to_pptx`, но по роли
  текста: заголовки (заголовок-заполнитель, стиль заголовков мастера, крупный кегль) → шрифт заголовков бренда,
  остальное → шрифт текста бренда; моноширинные и символьные шрифты не меняются. Нет шрифта бренда на этой машине —
  пишется его замена из брендбука («Play»), как велит сам брендбук; вес заголовков ≥ 600 — заголовки полужирные;
- логотипы шаблона → логотипы бренда: группа «знак + надпись» заменяется одним логотипом в той же рамке с
  сохранением пропорций; светлый или тёмный вариант — по цвету самого логотипа шаблона (белый — значит, тёмный
  фон). Логотипа в шаблоне нет — логотип бренда ставится на макеты содержательных слайдов, только если в брендбуке
  есть правило места («в правом нижнем углу»), с полями брендбука.

Приоритет «brand» (по умолчанию) — значения бренда заменяют расходящиеся значения шаблона; «template» — бренд только
дополняет то, чего у шаблона нет (стандартная тема офисного пакета, шрифты по умолчанию, логотип), расхождения
остаются как в шаблоне.

`branded_template(template_id, brand, priority)` — id брендированной копии в `workspace/templates/<id>/` (кэш по
шаблону, отпечатку брендбука и приоритету; рядом `brand.json`, `meta.txt`, `title.txt` «VK Tech · брендбук VK Cloud»).
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import json
import logging
import math
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

from lxml import etree

from verstka import pkgzip
from verstka.ingest.workspace import SAFE_ID_RE, TemplateWorkspace, default_workspace_root
from verstka.schemas.brand import BrandFont, BrandLogo, BrandPriority, BrandSpec, normalize_hex
from verstka.schemas.common import Color, contrast_ratio
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

# версия правил применения: меняется — старые копии в кэше не используются
APPLY_VERSION = "1"
BRAND_FILE = "brand.json"

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_PR = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_IMG_REL = _R + "/image"

_SRGB = f"{{{_A}}}srgbClr"
_LATIN = f"{{{_A}}}latin"
_BLIP = f"{{{_A}}}blip"
_RPR_TAGS = {f"{{{_A}}}rPr", f"{{{_A}}}defRPr", f"{{{_A}}}endParaRPr"}

# части, где живут видимые цвета и шрифты (заметки не трогаются)
_VISIBLE_RE = re.compile(
    r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+|charts/(?:chart|colors|style)\d+|"
    r"diagrams/(?:data|drawing|colors)\d+|presentation)\.xml$"
)
_THEME_RE = re.compile(r"^ppt/theme/theme\d+\.xml$")
_LOGO_PART_RE = re.compile(r"^ppt/(?:slides/slide\d+|slideLayouts/slideLayout\d+|slideMasters/slideMaster\d+)\.xml$")

_THEME_SLOTS = ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink")
_ACCENT_SLOTS = ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6")

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
_LOGO_NAME_RE = re.compile(r"logo|лого|wordmark|emblem|эмблем|brand(?!book)|бренд(?!бук)", re.I)

_ORDINALS = ("Основной акцент", "Второй акцент", "Третий акцент", "Четвёртый акцент", "Пятый акцент", "Шестой акцент")


# ============================================================================================ цвет: простые меры


def _hx(value: str) -> str:
    """«#0077ff» → «0077FF» (как в OOXML)."""
    return normalize_hex(value)[1:]


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _from_rgb(r: float, g: float, b: float) -> str:
    return "".join(f"{max(0, min(255, int(round(v)))):02X}" for v in (r, g, b))


def _hls(h: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in _rgb(h))
    return colorsys.rgb_to_hls(r, g, b)


def _chroma(h: str) -> float:
    r, g, b = _rgb(h)
    return (max(r, g, b) - min(r, g, b)) / 255


def _hue(h: str) -> float:
    return _hls(h)[0] * 360


def _hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


@lru_cache(maxsize=4096)
def _lab(h: str) -> tuple[float, float, float]:
    return Color(hex=h).to_lab()


def _de(a: str, b: str) -> float:
    return math.dist(_lab(a), _lab(b))


def _lstar(h: str) -> float:
    return _lab(h)[0]


def _same_tone(a: str, b: str) -> bool:
    """Почти тот же цвет, записанный иначе (#0187F6 и #0077FF): тон ±5°, светлота ±0,06, насыщенность ±0,15."""
    ha, la, sa = _hls(a)
    hb, lb, sb = _hls(b)
    return _hue_dist(ha * 360, hb * 360) <= 5 and abs(la - lb) <= 0.06 and abs(sa - sb) <= 0.15


def tone(h: str) -> str:
    """chromatic (насыщенный цвет) · tint (светлый оттенок цвета) · dark · light · grey."""
    c, light = _chroma(h), _hls(h)[1]
    if c >= 0.15 and light <= 0.85 and _lstar(h) >= 15:
        return "chromatic"
    if c >= 0.06 and light > 0.85:
        return "tint"
    if _lstar(h) < 20:
        return "dark"
    if _lstar(h) > 90:
        return "light"
    return "grey"


def _shift(h: str, ref: str, to: str, w: float) -> str:
    """`h` сдвинут на долю `w` разницы «`to` − `ref`» (тот же сдвиг, что сделал опорный цвет)."""
    if w <= 0:
        return h
    return _from_rgb(*(c + (t - r) * w for c, r, t in zip(_rgb(h), _rgb(ref), _rgb(to))))


# ============================================================================================ тема шаблона


@dataclass
class ThemeInfo:
    slots: dict[str, str] = field(default_factory=dict)  # dk1 … folHlink → «RRGGBB»
    major: Optional[str] = None
    minor: Optional[str] = None

    @property
    def stock(self) -> bool:
        """Тема — стандартная тема офисного пакета (её акценты не выбирал автор шаблона)."""
        from verstka.analysis.colors import is_stock_theme_color

        return sum(1 for s in _ACCENT_SLOTS if is_stock_theme_color(self.slots.get(s, ""))) >= 3

    def chromatic_accents(self) -> list[str]:
        return [self.slots[s] for s in _ACCENT_SLOTS if s in self.slots and tone(self.slots[s]) == "chromatic"]


def _slot_hex(el: etree._Element) -> Optional[str]:
    for ch in el:
        if ch.tag == _SRGB and ch.get("val"):
            return ch.get("val").upper()
        if ch.tag == f"{{{_A}}}sysClr" and ch.get("lastClr"):
            return ch.get("lastClr").upper()
    return None


def theme_info(root: etree._Element) -> ThemeInfo:
    info = ThemeInfo()
    scheme = root.find(f".//{{{_A}}}clrScheme")
    if scheme is not None:
        for el in scheme:
            name = etree.QName(el).localname
            hx = _slot_hex(el)
            if name in _THEME_SLOTS and hx and re.fullmatch(r"[0-9A-F]{6}", hx):
                info.slots[name] = hx
    for which in ("major", "minor"):
        lat = root.find(f".//{{{_A}}}fontScheme/{{{_A}}}{which}Font/{{{_A}}}latin")
        if lat is not None and lat.get("typeface"):
            setattr(info, which, lat.get("typeface"))
    return info


# ============================================================================================ план цветов


@dataclass
class ColorPlan:
    """Как меняются цвета шаблона: `map(hex)` для явных цветов и слотов темы."""

    enabled: bool = True
    # точные пары «цвет шаблона → цвет бренда» (текст, фон, акценты палитры, смысловые)
    table: dict[str, str] = field(default_factory=dict)
    # акценты палитры шаблона по порядку и их пары; `main` — главная палитра (цвета темы, у стандартной темы — заметные
    # акценты разбора): по ней — расхождения «Второй акцент»
    palette: list[str] = field(default_factory=list)
    main: list[str] = field(default_factory=list)
    anchors: dict[str, str] = field(default_factory=dict)
    brand_of: dict[str, str] = field(default_factory=dict)  # акцент шаблона → цвет бренда (до подгонки светлоты)
    text: Optional[tuple[str, str]] = None  # (опорный тёмный шаблона, текст бренда)
    background: Optional[tuple[str, str]] = None  # (опорный светлый шаблона, фон бренда)
    text_pair: Optional[tuple[str, str]] = None  # (текст шаблона, текст бренда) — как в разборе
    background_pair: Optional[tuple[str, str]] = None
    keep: set[str] = field(default_factory=set)  # цвета, которые не трогаются (смысловые без пары в бренде)
    stock_slots: dict[str, str] = field(default_factory=dict)  # слот стандартной темы → цвет бренда
    warnings: list[str] = field(default_factory=list)
    _cache: dict[str, str] = field(default_factory=dict, repr=False)

    def map(self, value: str) -> str:
        h = value.upper()
        if not self.enabled or not re.fullmatch(r"[0-9A-F]{6}", h):
            return h
        hit = self._cache.get(h)
        if hit is None:
            hit = self._cache[h] = self._map(h)
        return hit

    def _map(self, h: str) -> str:
        if h in self.table:
            return self.table[h]
        if h in self.keep:
            return h
        t = tone(h)
        if t in ("chromatic", "tint") and self.anchors:
            best = min(
                ((a, b) for a, b in self.anchors.items() if tone(a) == "chromatic"),
                key=lambda ab: _hue_dist(_hue(h), _hue(ab[0])),
                default=None,
            )
            if best and _hue_dist(_hue(h), _hue(best[0])) <= 25:
                a, b = best
                if a == b:
                    return h
                if t == "chromatic":
                    # тот же цвет, чуть иначе записанный (#007DEA при #0187F6); другой насыщенный цвет, которого нет в
                    # палитре разбора (жёлтый рядом с оранжевым), остаётся как был
                    return b if _same_tone(h, a) else h
                ha, la, sa = _hls(a)
                hb, lb, sb = _hls(b)
                hh, lh, sh = _hls(h)
                # оттенок того же акцента: тон и насыщенность — как у цвета бренда, светлота — своя (плашка остаётся
                # светлой, контраст с текстом не меняется)
                return _from_rgb(*(c * 255 for c in colorsys.hls_to_rgb((hh + hb - ha) % 1.0, lh, min(1.0, sh * (sb / sa if sa > 0.05 else 1.0)))))
            return h
        if t == "dark" and self.text:
            ref, to = self.text
            if _lstar(ref) >= 30:
                return h
            return _shift(h, ref, to, min(1.0, max(0.0, 1.0 - _lstar(h) / 30.0) / (1.0 - _lstar(ref) / 30.0)))
        if t == "light" and self.background:
            ref, to = self.background
            span = _lstar(ref) - 70.0
            return _shift(h, ref, to, min(1.0, max(0.0, (_lstar(h) - 70.0) / span)) if span > 1 else 0.0)
        return h


def _brand_hex(brand: BrandSpec, role: str) -> Optional[str]:
    c = brand.color(role)  # type: ignore[arg-type]
    return _hx(c.hex) if c else None


def brand_chromatic(brand: BrandSpec) -> list[tuple[str, str]]:
    """Хроматические цвета бренда для акцентов — (hex, роль) по порядку: основной, дополнительный, акцент, графики."""
    out: list[tuple[str, str]] = []
    for role in ("primary", "secondary", "accent", "chart"):
        for c in brand.colors:
            h = _hx(c.hex)
            if c.role == role and tone(h) == "chromatic" and h not in {x for x, _ in out}:
                out.append((h, role))
    return out


def _token_accents(manifest: TemplateManifest) -> list[str]:
    def order(t) -> int:
        m = re.match(r"accent\.(\d+)", t.role or "")
        return int(m.group(1)) if m else 99

    toks = [t for t in manifest.tokens.colors if (t.role or "").startswith("accent.") and not t.semantic]
    return [t.hex.upper() for t in sorted(toks, key=order) if tone(t.hex.upper()) == "chromatic"]


def _token_with(manifest: TemplateManifest, role: str) -> Optional[str]:
    """Цвет шаблона с этой ролью: сначала тот, у кого она главная, потом — среди всех ролей."""
    for t in manifest.tokens.colors:
        if t.role == role:
            return t.hex.upper()
    for t in manifest.tokens.colors:
        if role in t.roles:
            return t.hex.upper()
    return None


def _mostly_text(manifest: TemplateManifest, h: str) -> bool:
    for t in manifest.tokens.colors:
        if t.hex.upper() == h:
            cx = t.contexts or {}
            return cx.get("text", 0) > cx.get("fill", 0) + cx.get("line", 0)
    return False


def _main_ground(manifest: TemplateManifest) -> str:
    """light / dark — какой фон у большинства слайдов шаблона."""
    n: Counter = Counter()
    for b in manifest.tokens.backgrounds:
        fam = b.family.value if hasattr(b.family, "value") else str(b.family)
        n[fam] += len(b.slides) or 1
    if not n:
        return "light"
    return "dark" if n.get("dark", 0) > n.get("light", 0) else "light"


def _main_palette(manifest: TemplateManifest, theme: ThemeInfo, stock: bool) -> list[str]:
    if theme.slots and not stock:
        return theme.chromatic_accents()
    toks = [t for t in manifest.tokens.colors if (t.role or "").startswith("accent.") and not t.semantic and tone(t.hex.upper()) == "chromatic"]
    total = sum(t.weight for t in toks) or 1.0
    return [t.hex.upper() for t in sorted(toks, key=lambda t: -t.weight) if t.weight / total >= 0.1][:4]


def plan_colors(manifest: TemplateManifest, brand: BrandSpec, priority: BrandPriority = "brand", theme: Optional[ThemeInfo] = None) -> ColorPlan:
    theme = theme or ThemeInfo()
    plan = ColorPlan()
    chrom = brand_chromatic(brand)
    stock = theme.stock if theme.slots else False
    # слоты стандартной темы — места, которые автор шаблона не заполнял: бренд занимает их по порядку
    if stock and chrom:
        # по порядку палитры диаграмм: основной, дополнительный, цвета графиков; «акцент» бренда — последним
        order = sorted(chrom, key=lambda hr: {"primary": 0, "secondary": 1, "chart": 2}.get(hr[1], 3))
        k = 0
        for s in _ACCENT_SLOTS:
            v = theme.slots.get(s)
            if v and tone(v) == "chromatic":
                plan.stock_slots[s] = order[k % len(order)][0]
                k += 1
    if priority == "template":
        # бренд только дополняет: цвета шаблона остаются, кроме стандартной темы
        plan.enabled = bool(plan.stock_slots)
        for s, b in plan.stock_slots.items():
            plan.table.setdefault(theme.slots[s], b)
        plan.palette = _token_accents(manifest) if stock else (theme.chromatic_accents() + [x for x in _token_accents(manifest) if x not in theme.chromatic_accents()])
        plan.main = _main_palette(manifest, theme, stock)
        plan.keep = {t.hex.upper() for t in manifest.tokens.colors} - set(plan.table)
        return plan

    # --- приоритет брендбука
    light_ground = _main_ground(manifest) == "light"
    t_bg = _token_with(manifest, "background.light") or (theme.slots.get("lt1") if light_ground else None)
    # текст по умолчанию (dk1 темы) — текст шаблона, только когда фон шаблона светлый: в тёмном шаблоне тёмное — фон
    t_text = _token_with(manifest, "text.primary") or (theme.slots.get("dk1") if light_ground else None)
    b_text, b_bg = _brand_hex(brand, "text"), _brand_hex(brand, "background")
    b_surface = _brand_hex(brand, "surface")
    t_surface = _token_with(manifest, "surface")
    if t_text and b_text:
        if (_lstar(t_text) < 50) == (_lstar(b_text) < 50):
            plan.table[t_text] = b_text
            plan.text_pair = (t_text, b_text)
            dk1 = theme.slots.get("dk1")
            if dk1 and light_ground and tone(dk1) == "dark":
                plan.table.setdefault(dk1, b_text)  # слот текста темы — тоже текст
            ref = t_text if tone(t_text) == "dark" else "000000"
            if tone(b_text) == "dark" and light_ground:
                plan.text = (ref, b_text)  # тёмные нейтральные (оттенки текста) сдвигаются вместе с текстом
        else:
            plan.warnings.append(f"Текст бренда #{b_text} и текст шаблона #{t_text} разной светлоты — цвет текста оставлен как в шаблоне.")
            plan.text_pair = (t_text, t_text)
            plan.keep.add(t_text)
    if t_bg and b_bg:
        if (_lstar(t_bg) > 50) == (_lstar(b_bg) > 50) and contrast_ratio(plan.table.get(t_text or "", t_text or "000000"), b_bg) >= 3.0:
            plan.table[t_bg] = b_bg
            plan.background_pair = (t_bg, b_bg)
            ref = t_bg if tone(t_bg) in ("light", "tint") else "FFFFFF"
            if tone(b_bg) in ("light", "tint") and light_ground:
                plan.background = (ref, b_bg)
        else:
            plan.warnings.append(f"Фон бренда #{b_bg} не подходит к шаблону со светлотой фона #{t_bg} — фон оставлен как в шаблоне.")
            plan.background_pair = (t_bg, t_bg)
            plan.keep.add(t_bg)
    if t_surface and b_surface and t_surface not in plan.table and (_lstar(t_surface) > 50) == (_lstar(b_surface) > 50):
        plan.table[t_surface] = b_surface
    t_sec, b_neu = _token_with(manifest, "text.secondary"), _brand_hex(brand, "neutral")
    if t_sec and b_neu and t_sec not in plan.table and abs(_lstar(t_sec) - _lstar(b_neu)) <= 25:
        plan.table[t_sec] = b_neu

    # смысловые цвета: рост / падение
    for t in manifest.tokens.colors:
        if t.semantic in ("positive", "negative"):
            b = _brand_hex(brand, "success" if t.semantic == "positive" else "danger")
            if b:
                plan.table.setdefault(t.hex.upper(), b)
            else:
                plan.keep.add(t.hex.upper())

    # акценты палитры шаблона → хроматические цвета бренда
    tok = _token_accents(manifest)
    if stock or not theme.slots:
        palette = tok
    else:
        th = theme.chromatic_accents()
        palette = th + [x for x in tok if x not in th]
    hl = theme.slots.get("hlink")
    if hl and tone(hl) == "chromatic" and hl not in palette:
        palette.append(hl)
    palette = [p for p in dict.fromkeys(palette) if p not in plan.keep]
    plan.palette = palette
    plan.main = _main_palette(manifest, theme, stock)
    if chrom:
        by_hex = dict(chrom)
        uses: Counter = Counter()
        bg_for = b_bg or t_bg or "FFFFFF"
        for i, a in enumerate(palette):
            if a in plan.table:
                continue
            twin = next((pa for pa in plan.anchors if _same_tone(a, pa)), None)
            if a in by_hex:
                b = a
            elif twin is not None:
                b = plan.anchors[twin]  # тот же цвет шаблона, записанный иначе, — тот же цвет бренда
            elif i == 0:
                b = _brand_hex(brand, "primary") if _brand_hex(brand, "primary") in by_hex else chrom[0][0]
            else:
                text_like = _mostly_text(manifest, a) and contrast_ratio(a, t_bg or "FFFFFF") >= 3.0

                def cost(bh: str) -> float:
                    d = _hue_dist(_hue(a), _hue(bh))
                    c = d + 40.0 * uses[bh]
                    if by_hex[bh] == "accent" and d > 30:
                        c += 60.0  # «акцент» бренда — для выделения, а не для любого цвета шаблона
                    if text_like and contrast_ratio(bh, bg_for) < 3.0:
                        c += 50.0
                    return c

                b = min((h for h, _ in chrom), key=cost)
            uses[b] += 1
            plan.brand_of[a] = b
            if i > 0 and twin is None and a not in by_hex and abs(_hls(a)[1] - _hls(b)[1]) > 0.15:
                # светлый (или тёмный) акцент шаблона — тот же по светлоте оттенок цвета бренда: светлые фигуры
                # остаются светлыми, текст на них читается как прежде
                b = _retone(a, b)
            plan.anchors[a] = b
            plan.table.setdefault(a, b)
        for s, b in plan.stock_slots.items():
            plan.table.setdefault(theme.slots[s], b)
    _guard_neutrals(plan, manifest, theme)
    return plan


def _retone(a: str, b: str) -> str:
    """Цвет с тоном и насыщенностью `b` и светлотой `a`."""
    _, la, _ = _hls(a)
    hb, _, sb = _hls(b)
    return _from_rgb(*(c * 255 for c in colorsys.hls_to_rgb(hb, la, sb)))


def _guard_neutrals(plan: ColorPlan, manifest: TemplateManifest, theme: ThemeInfo) -> None:
    """Два разных нейтральных цвета шаблона не сливаются в один: плашка #EBF3F9 на белом фоне не становится белой,
    если белый у шаблона уже есть. Пара «цвет → цвет бренда» снимается, когда цвет бренда — это другой (заметно
    отличный) цвет самого шаблона, который остаётся как есть."""
    own = {t.hex.upper() for t in manifest.tokens.colors} | set(theme.slots.values())
    for x, y in list(plan.table.items()):
        if x == y or tone(x) == "chromatic" or x in plan.anchors:
            continue
        for z in own:
            if z != x and plan.table.get(z, z) == z and _de(y, z) < 2.5 and _de(x, z) > 5.0:
                del plan.table[x]
                plan.keep.add(x)
                if plan.background_pair and plan.background_pair[0] == x:
                    plan.background_pair = (x, x)
                    plan.background = None
                if plan.text_pair and plan.text_pair[0] == x:
                    plan.text_pair = (x, x)
                    plan.text = None
                break


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


def _base(name: str) -> str:
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
    bold_headings: bool = False
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
        b = _base(family or "")
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
            role = s.role.value if hasattr(s.role, "value") else str(s.role)
            if role == "title":
                heads[fam] += 1
            elif role in ("body", "bullet_list", "card_body", "subtitle", "caption"):
                bodies[fam] += 1
    main = next((f.family for f in manifest.tokens.typography.families if f.source == "text"), None) or next(
        (f.family for f in manifest.tokens.typography.families), None
    )
    head = heads.most_common(1)[0][0] if heads else main
    body = bodies.most_common(1)[0][0] if bodies else main
    return head, body


def plan_fonts(manifest: TemplateManifest, brand: BrandSpec, priority: BrandPriority = "brand") -> FontPlan:
    fp = FontPlan(priority=priority)
    fp.heading_from, fp.body_from = template_fonts(manifest)
    fp.heading = brand.font("heading") or brand.font("body")
    fp.body = brand.font("body")
    if fp.heading:
        fp.heading_to, fp.heading_fallback = written_family(fp.heading)
    if fp.body:
        fp.body_to, fp.body_fallback = written_family(fp.body)
    fp.bold_headings = priority == "brand" and fp.heading is not None and fp.heading.weight >= 600
    big = [s.size_pt for s in manifest.tokens.typography.scale if s.role in ("display", "h1") and s.size_pt]
    fp.heading_min_pt = round(min(big) * 0.85, 1) if big else 24.0
    fp.own = {_base(f.family) for f in manifest.tokens.typography.families if f.source == "text" and f.weight >= 0.02}
    return fp


def font_result(font: BrandFont, written: str, fallback: bool) -> str:
    """«VK Sans Display» или «VK Sans Display, замена — Play»."""
    return f"{font.family}, замена — {written}" if fallback else font.family


# ============================================================================================ пакет


class _Pkg:
    """Части пакета в памяти: XML разбирается один раз, изменённые части и новые записываются при сохранении."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as z:
            self.infos = z.infolist()
            self.data = {i.filename: z.read(i) for i in self.infos}
        self.trees: dict[str, etree._Element] = {}
        self.dirty: set[str] = set()
        self.added: dict[str, bytes] = {}

    def names(self) -> list[str]:
        return [i.filename for i in self.infos] + [n for n in self.added if n not in self.data]

    def has(self, name: str) -> bool:
        return name in self.data or name in self.added

    def read(self, name: str) -> bytes:
        return self.added.get(name) or self.data[name]

    def xml(self, name: str) -> Optional[etree._Element]:
        if name not in self.trees:
            try:
                self.trees[name] = etree.fromstring(self.read(name))
            except (KeyError, etree.XMLSyntaxError):
                return None
        return self.trees[name]

    def rels_name(self, part: str) -> str:
        d, f = posixpath.split(part)
        return posixpath.join(d, "_rels", f + ".rels")

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """rId → (тип, цель — имя части)."""
        root = self.xml(self.rels_name(part)) if self.has(self.rels_name(part)) else None
        out: dict[str, tuple[str, str]] = {}
        if root is None:
            return out
        for r in root:
            tgt = r.get("Target") or ""
            if r.get("TargetMode") == "External":
                continue
            full = tgt.lstrip("/") if tgt.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part), tgt))
            out[r.get("Id") or ""] = (r.get("Type") or "", full)
        return out

    def add_rel(self, part: str, rtype: str, target_part: str) -> str:
        name = self.rels_name(part)
        root = self.xml(name) if self.has(name) else None
        if root is None:
            root = etree.Element(f"{{{_PR}}}Relationships", nsmap={None: _PR})
            self.trees[name] = root
            self.added.setdefault(name, b"")
        ids = {r.get("Id") for r in root}
        n = 1
        while f"rIdBrand{n}" in ids:
            n += 1
        rid = f"rIdBrand{n}"
        rel = etree.SubElement(root, f"{{{_PR}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", rtype)
        rel.set("Target", posixpath.relpath(target_part, posixpath.dirname(part)))
        self.dirty.add(name)
        return rid

    def ensure_default_type(self, ext: str, ctype: str) -> None:
        root = self.xml("[Content_Types].xml")
        if root is None:
            return
        if any((d.get("Extension") or "").lower() == ext for d in root if etree.QName(d).localname == "Default"):
            return
        d = etree.Element(f"{{{_CT}}}Default")
        d.set("Extension", ext)
        d.set("ContentType", ctype)
        root.insert(0, d)
        self.dirty.add("[Content_Types].xml")

    def save(self, out: Path | str) -> int:
        """Пишет пакет в `out`; число изменённых и новых частей."""
        changed = {n: etree.tostring(self.trees[n], xml_declaration=True, encoding="UTF-8", standalone=True) for n in self.dirty}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in self.infos:
                data = changed.get(item.filename, self.data[item.filename])
                zout.writestr(pkgzip.entry(item), data)
            for name, data in self.added.items():
                if name in self.data:
                    continue
                zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                zi.compress_type = pkgzip.compress_type(name)
                zout.writestr(zi, changed.get(name, data))
        Path(out).write_bytes(buf.getvalue())
        return len(changed) + len([n for n in self.added if n not in changed and n not in self.data])


# ============================================================================================ цвета и шрифты в частях


def _recolor(root: etree._Element, plan: ColorPlan, counter: Counter) -> bool:
    # картинки не перекрашиваются (элементы держатся в списке: lxml сохраняет их обёртки, пока на них есть ссылки)
    inside = [c for b in root.iter(_BLIP) for c in b.iter(_SRGB)]
    skip = set(inside)
    changed = False
    for el in root.iter(_SRGB):
        if el in skip:
            continue
        v = (el.get("val") or "").upper()
        nv = plan.map(v)
        if nv != v:
            el.set("val", nv)
            counter[(v, nv)] += 1
            changed = True
    return changed


def _retheme(root: etree._Element, plan: ColorPlan, fp: FontPlan, counter: Counter) -> bool:
    changed = False
    scheme = root.find(f".//{{{_A}}}clrScheme")
    if scheme is not None:
        for slot in scheme:
            name = etree.QName(slot).localname
            if name not in _THEME_SLOTS:
                continue
            old = _slot_hex(slot)
            if not old:
                continue
            new = plan.map(old)
            if new == old:
                continue
            for ch in list(slot):
                slot.remove(ch)
            etree.SubElement(slot, _SRGB).set("val", new)
            counter[(old, new)] += 1
            changed = True
    for which, role in (("major", "heading"), ("minor", "body")):
        lat = root.find(f".//{{{_A}}}fontScheme/{{{_A}}}{which}Font/{{{_A}}}latin")
        if lat is None:
            continue
        new = fp.target(lat.get("typeface"), role)
        if new:
            lat.set("typeface", new)
            changed = True
    return changed


class _Roles:
    """Роль текста (заголовок / текст) для `a:latin` и свойств текста в части."""

    _HEAD_PH = {"title", "ctrTitle"}

    def __init__(self, fp: FontPlan) -> None:
        self.fp = fp
        self.size_cache: dict[etree._Element, Optional[int]] = {}

    def _shape_size(self, shape: etree._Element) -> Optional[int]:
        key = shape
        if key not in self.size_cache:
            sizes = [int(e.get("sz")) for e in shape.iter(*_RPR_TAGS) if (e.get("sz") or "").isdigit()]
            self.size_cache[key] = max(sizes) if sizes else None
        return self.size_cache[key]

    def role(self, el: etree._Element) -> str:
        rpr = el if el.tag in _RPR_TAGS else el.getparent()
        sz = int(rpr.get("sz")) if rpr is not None and (rpr.get("sz") or "").isdigit() else None
        shape = None
        for anc in el.iterancestors():
            tag = anc.tag
            if tag == f"{{{_P}}}titleStyle":
                return "heading"
            if tag in (f"{{{_P}}}bodyStyle", f"{{{_P}}}otherStyle", f"{{{_P}}}defaultTextStyle", f"{{{_C}}}chartSpace"):
                return "body"
            if tag in (f"{{{_P}}}sp", f"{{{_P}}}graphicFrame"):
                shape = anc
                break
        if shape is not None and shape.tag == f"{{{_P}}}sp":
            ph = shape.find(f"{{{_P}}}nvSpPr/{{{_P}}}nvPr/{{{_P}}}ph")
            if ph is not None and (ph.get("type") or "") in self._HEAD_PH:
                return "heading"
        if sz is None and shape is not None:
            sz = self._shape_size(shape)
        if sz is not None and sz / 100.0 >= self.fp.heading_min_pt:
            return "heading"
        return "body"


def _refont(root: etree._Element, fp: FontPlan, counter: Counter) -> bool:
    roles = _Roles(fp)
    changed = False
    for lat in list(root.iter(_LATIN)):
        # тема шаблона (major/minor) переписывается отдельно
        if any(a.tag == f"{{{_A}}}fontScheme" for a in lat.iterancestors()):
            continue
        new = fp.target(lat.get("typeface"), roles.role(lat))
        if new:
            counter[(lat.get("typeface"), new)] += 1
            lat.set("typeface", new)
            changed = True
    if fp.bold_headings:
        for rpr in list(root.iter(*_RPR_TAGS)):
            if rpr.get("b") == "1" or roles.role(rpr) != "heading":
                continue
            lat = rpr.find(_LATIN)
            if lat is not None and _MONO_FONT_RE.search(lat.get("typeface") or ""):
                continue
            rpr.set("b", "1")
            counter[("bold", "heading")] += 1
            changed = True
    return changed


# ============================================================================================ логотипы


@dataclass
class _Pic:
    part: str
    el: etree._Element
    box: tuple[float, float, float, float]  # x, y, w, h в EMU слайда
    media: Optional[str]
    name: str
    groups: list[etree._Element]  # группы-предки (внутренняя первой)


@dataclass
class Lockup:
    """Логотип шаблона на одной части: знак и надпись рядом — одна группа."""

    part: str
    pics: list[_Pic]
    box: tuple[float, float, float, float]
    ground: str = "light"  # light | dark — на каком фоне стоит
    duplicate: bool = False  # тот же логотип второй раз на той же части (копия группы)

    @property
    def media(self) -> list[str]:
        return [p.media for p in self.pics if p.media]


def _xfrm_box(xfrm: Optional[etree._Element]) -> Optional[tuple[float, float, float, float]]:
    if xfrm is None:
        return None
    off, ext = xfrm.find(f"{{{_A}}}off"), xfrm.find(f"{{{_A}}}ext")
    if off is None or ext is None:
        return None
    try:
        return float(off.get("x")), float(off.get("y")), float(ext.get("cx")), float(ext.get("cy"))
    except (TypeError, ValueError):
        return None


def _group_xf(g: etree._Element) -> Optional[tuple[float, float, float, float, float, float]]:
    """(ox, oy, sx, sy, chx, chy): точка группы p → ox + (p − ch)·s."""
    x = g.find(f"{{{_P}}}grpSpPr/{{{_A}}}xfrm")
    if x is None:
        return None
    off, ext = x.find(f"{{{_A}}}off"), x.find(f"{{{_A}}}ext")
    choff, chext = x.find(f"{{{_A}}}chOff"), x.find(f"{{{_A}}}chExt")
    if off is None or ext is None:
        return None
    ox, oy, ex, ey = (float(v) for v in (off.get("x", 0), off.get("y", 0), ext.get("cx", 0), ext.get("cy", 0)))
    cx = float(choff.get("x", 0)) if choff is not None else ox
    cy = float(choff.get("y", 0)) if choff is not None else oy
    cex = float(chext.get("cx", 0)) if chext is not None else ex
    cey = float(chext.get("cy", 0)) if chext is not None else ey
    return ox, oy, (ex / cex if cex else 1.0), (ey / cey if cey else 1.0), cx, cy


def _to_abs(box, groups):
    x, y, w, h = box
    for g in groups:  # изнутри наружу
        xf = _group_xf(g)
        if xf is None:
            continue
        ox, oy, sx, sy, cx, cy = xf
        x, y, w, h = ox + (x - cx) * sx, oy + (y - cy) * sy, w * sx, h * sy
    return x, y, w, h


def _to_local(box, groups):
    x, y, w, h = box
    for g in reversed(groups):  # снаружи внутрь
        xf = _group_xf(g)
        if xf is None:
            continue
        ox, oy, sx, sy, cx, cy = xf
        x, y, w, h = cx + (x - ox) / sx, cy + (y - oy) / sy, w / sx, h / sy
    return x, y, w, h


def _pics_of(pkg: _Pkg, part: str) -> list[_Pic]:
    root = pkg.xml(part)
    if root is None:
        return []
    rels = pkg.rels(part)
    out: list[_Pic] = []
    tree = root.find(f"{{{_P}}}cSld/{{{_P}}}spTree")
    if tree is None:
        return out
    for pic in tree.iter(f"{{{_P}}}pic"):
        nv = pic.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr")
        if nv is not None and nv.get("hidden") in ("1", "true"):
            continue
        xfrm = pic.find(f"{{{_P}}}spPr/{{{_A}}}xfrm")
        if xfrm is None or xfrm.get("rot") not in (None, "0"):
            continue
        box = _xfrm_box(xfrm)
        if box is None:
            continue
        groups = [a for a in pic.iterancestors() if a.tag == f"{{{_P}}}grpSp"]
        blip = pic.find(f"{{{_P}}}blipFill/{{{_A}}}blip")
        rid = blip.get(f"{{{_R}}}embed") if blip is not None else None
        media = rels.get(rid or "", ("", None))[1] if rid else None
        name = " ".join(x for x in ((nv.get("name") or "") if nv is not None else "", (nv.get("descr") or "") if nv is not None else "") if x)
        out.append(_Pic(part=part, el=pic, box=_to_abs(box, groups), media=media, name=name, groups=groups))
    return out


@lru_cache(maxsize=512)
def _image_probe(data: bytes) -> Optional[tuple]:
    """(размер, «отпечаток» 16×16 на белом, чернила: light | dark | color | empty, прозрачный фон?, «как логотип»:
    несколько плоских цветов — четыре самых частых покрывают ≥ 85 % непрозрачных точек)."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None
    import numpy as np

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
    flat_colors = sum(n for _, n in bins.most_common(4)) >= 0.85 * len(px)
    return size, print_, ink, transparent, flat_colors


def _same_picture(a: Optional[tuple], b: Optional[tuple]) -> bool:
    """Та же картинка в другом размере: те же пропорции и те же точки там, где у одной из них есть «чернила»
    (сравнение только по чернилам: у мелких значков на прозрачном фоне почти всё — пустота)."""
    if not a or not b or a[2] == "empty" or b[2] == "empty":
        return False
    (wa, ha), (wb, hb) = a[0], b[0]
    if not (ha and hb) or abs(math.log((wa / ha) / (wb / hb))) > 0.15:
        return False
    diffs = []
    for p, q in zip(a[1], b[1]):
        if max(p[3], q[3]) <= 32:
            continue
        # точка на белом и на чёрном: различие и в цвете, и в прозрачности
        for bg in (255, 0):
            pc = [c * p[3] / 255 + bg * (1 - p[3] / 255) for c in p[:3]]
            qc = [c * q[3] / 255 + bg * (1 - q[3] / 255) for c in q[:3]]
            diffs.append(sum(abs(x - y) for x, y in zip(pc, qc)) / (3 * 255))
    return bool(diffs) and sum(diffs) / len(diffs) < 0.12


def _slide_size(pkg: _Pkg) -> tuple[int, int]:
    root = pkg.xml("ppt/presentation.xml")
    sz = root.find(f"{{{_P}}}sldSz") if root is not None else None
    if sz is None:
        return 9144000, 5143500
    return int(sz.get("cx")), int(sz.get("cy"))


def find_template_logos(pkg: _Pkg, manifest: Optional[TemplateManifest] = None, slots: Optional[dict[str, str]] = None) -> list[Lockup]:
    """Логотипы шаблона: картинки с «logo» в имени, логотипы разбора (`assets` kind logo / теги), та же картинка в
    другом размере и всё, что стоит рядом с ними в одну строку (надпись к знаку). Только небольшие картинки (не фон)."""
    sw, sh = _slide_size(pkg)
    parts = [n for n in pkg.names() if _LOGO_PART_RE.match(n)]
    pics = {p: _pics_of(pkg, p) for p in parts}

    def small(pc: _Pic) -> bool:
        x, y, w, h = pc.box
        return 0 < w <= 0.3 * sw and 0 < h <= 0.2 * sh and w * h <= 0.03 * sw * sh

    def band(pc: _Pic) -> bool:
        x, y, w, h = pc.box
        return y <= 0.22 * sh or y + h >= 0.78 * sh

    probes = {m: _image_probe(pkg.read(m)) for m in {pc.media for lst in pics.values() for pc in lst if pc.media and small(pc) and pkg.has(pc.media)}}

    def logo_like(m: Optional[str]) -> bool:
        pr = probes.get(m or "")
        return bool(pr) and pr[2] != "empty" and pr[3] and pr[4]

    seeds: set[str] = set()
    if manifest is not None:
        # логотип по разбору (повторяющаяся картинка, теги навыка): только плоская картинка на прозрачном фоне —
        # «логотипом» разбор называет и макет телефона, повторённый на слайдах
        for a in manifest.assets:
            if a.media_part and (a.kind == "logo" or any(re.search(r"logo|логотип", t, re.I) for t in a.tags)) and logo_like(a.media_part):
                seeds.add(a.media_part)
    for lst in pics.values():
        for pc in lst:
            if pc.media and small(pc) and _LOGO_NAME_RE.search(pc.name + " " + posixpath.basename(pc.media)):
                seeds.add(pc.media)
    # картинка макетов и мастеров у края слайда, повторённая хотя бы на двух из них, плоская и на прозрачном фоне —
    # так шаблоны ставят свой логотип
    on_layouts: dict[str, set[str]] = {}
    for part, lst in pics.items():
        if "/slides/" in part:
            continue
        for pc in lst:
            if pc.media and small(pc) and band(pc) and logo_like(pc.media):
                on_layouts.setdefault(pc.media, set()).add(part)
    seeds |= {m for m, ps in on_layouts.items() if len(ps) >= 2}
    # та же картинка другого размера (знак на обложке крупнее, чем в углу)
    seed_probes = [probes.get(m) or (_image_probe(pkg.read(m)) if pkg.has(m) else None) for m in seeds]
    for m, pr in probes.items():
        if m not in seeds and any(_same_picture(pr, sp) for sp in seed_probes):
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
                    inter_w = max(0.0, min(ux + uw, ox + ow) - max(ux, ox))
                    inter_h = max(0.0, min(uy + uh, oy + oh) - max(uy, oy))
                    inside = inter_w * inter_h >= 0.5 * ow * oh
                    gap = max(ox - (ux + uw), ux - (ox + ow), 0.0)
                    row = inter_h >= 0.5 * min(uh, oh) and gap <= 1.2 * max(uh, oh) and oh <= 1.6 * uh
                    if inside or row:
                        group.append(o)
                        used.add(id(o.el))
                        grew = True
            box = _union([g.box for g in group])
            dup = any(l.part == part and _iou(l.box, box) >= 0.9 for l in lockups)
            lockups.append(Lockup(part=part, pics=group, box=box, ground=_ground_of(pkg, group, slots), duplicate=dup))
    return lockups


def _union(boxes):
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[0] + b[2] for b in boxes)
    y2 = max(b[1] + b[3] for b in boxes)
    return x1, y1, x2 - x1, y2 - y1


def _iou(a, b) -> float:
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0


_CLR_MAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}


def _color_of(el: Optional[etree._Element], slots: dict[str, str]) -> Optional[str]:
    """Цвет заливки фона: srgbClr или цвет темы; градиент — по первой точке; картинка — неизвестно."""
    if el is None:
        return None
    for c in el.iter(_SRGB, f"{{{_A}}}schemeClr", f"{{{_A}}}sysClr", f"{{{_A}}}blipFill"):
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


def _part_bg(pkg: _Pkg, part: str, slots: dict[str, str], depth: int = 0) -> Optional[str]:
    """Цвет фона части: свой `p:bg`, иначе — макета, иначе — мастера."""
    root = pkg.xml(part)
    if root is None or depth > 2:
        return None
    bg = root.find(f"{{{_P}}}cSld/{{{_P}}}bg")
    if bg is not None:
        return _color_of(bg.find(f"{{{_P}}}bgPr") if bg.find(f"{{{_P}}}bgPr") is not None else bg.find(f"{{{_P}}}bgRef"), slots)
    for typ, tgt in pkg.rels(part).values():
        if typ.endswith("/slideLayout") or typ.endswith("/slideMaster"):
            return _part_bg(pkg, tgt, slots, depth + 1)
    return None


def _ground_of(pkg: _Pkg, group: list[_Pic], slots: Optional[dict[str, str]] = None) -> str:
    """Фон под логотипом — по самому логотипу (белая надпись стоит на тёмном, тёмная — на светлом), иначе по фону
    слайда, иначе по светлым и тёмным точкам цветного логотипа."""
    probes = [_image_probe(pkg.read(pc.media)) for pc in group if pc.media and pkg.has(pc.media)]
    inks = [pr[2] for pr in probes if pr]
    if "light" in inks:
        return "dark"
    if "dark" in inks:
        return "light"
    bg = _part_bg(pkg, group[0].part, slots or {}) if group else None
    if bg and re.fullmatch(r"[0-9A-F]{6}", bg):
        return "dark" if _lstar(bg) < 50 else "light"
    return "light"


# ---------------------------------------------------------------------------------------- логотипы бренда


@dataclass
class _BrandImage:
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


def logo_path(logo: BrandLogo, brand_dir: Optional[Path | str]) -> Optional[Path]:
    p = Path(logo.file)
    if p.is_absolute():
        return p
    return Path(brand_dir) / p if brand_dir else None


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


def _load_logo(logo: BrandLogo, brand_dir: Optional[Path | str]) -> Optional[_BrandImage]:
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
    return _BrandImage(logo=logo, data=data, ext=ext, size=size, crop=crop)


def pick_logo(images: list[_BrandImage], ground: str, mark: bool) -> Optional[_BrandImage]:
    """Логотип бренда для места: знак — в квадратную рамку; на тёмном фоне — белый вариант, на светлом — основной."""
    if not images:
        return None
    by = lambda pred: next((im for im in images if pred(im.logo)), None)  # noqa: E731
    if mark:
        hit = by(lambda l: l.variant == "mark")
        if hit:
            return hit
    if ground == "dark":
        order = [
            lambda l: l.variant == "white",
            lambda l: l.ground == "dark" and l.variant != "mark",
            lambda l: l.variant == "mark",
            lambda l: l.ground == "any" and l.variant == "primary",
        ]
    else:
        order = [
            lambda l: l.variant == "primary" and l.ground in ("light", "any"),
            lambda l: l.variant == "mono",
            lambda l: l.ground in ("light", "any") and l.variant != "mark",
            lambda l: l.variant == "mark",
        ]
    for pred in order:
        hit = by(pred)
        if hit:
            return hit
    return None


# насколько логотип бренда может быть шире рамки логотипа шаблона: длинная надпись («VK Cloud» при «tech») иначе
# выходит мельче знака шаблона — рамка растёт в сторону от края, у которого стоит
_FIT_GROW = 1.35


def _fit(box, aspect: float, slide_w: float) -> tuple[float, float, float, float]:
    """Логотип с пропорциями `aspect` в рамке логотипа шаблона: высота — как у рамки (ширина — до `_FIT_GROW` её),
    прижат к той стороне, у которой стоит рамка."""
    x, y, w, h = box
    nh = min(h, w * _FIT_GROW / aspect)
    nw = nh * aspect
    cx = x + w / 2
    if cx < 0.4 * slide_w:
        nx = x
    elif cx > 0.6 * slide_w:
        nx = x + w - nw
    else:
        nx = x + (w - nw) / 2
    return nx, y + (h - nh) / 2, nw, nh


class _Media:
    def __init__(self, pkg: _Pkg) -> None:
        self.pkg = pkg
        self.parts: dict[int, str] = {}

    def part_for(self, img: _BrandImage) -> str:
        key = id(img)
        if key not in self.parts:
            digest = hashlib.sha256(img.data).hexdigest()[:8]
            name = f"ppt/media/brand-logo-{img.logo.variant}-{digest}.{'jpeg' if img.ext == 'jpeg' else img.ext}"
            self.pkg.added[name] = img.data
            self.pkg.ensure_default_type(img.ext if img.ext != "jpeg" else "jpeg", "image/png" if img.ext == "png" else "image/jpeg")
            self.parts[key] = name
        return self.parts[key]


def _set_box(pc_el: etree._Element, groups: list[etree._Element], box) -> None:
    x, y, w, h = _to_local(box, groups)
    xfrm = pc_el.find(f"{{{_P}}}spPr/{{{_A}}}xfrm")
    off, ext = xfrm.find(f"{{{_A}}}off"), xfrm.find(f"{{{_A}}}ext")
    off.set("x", str(int(round(x))))
    off.set("y", str(int(round(y))))
    ext.set("cx", str(max(1, int(round(w)))))
    ext.set("cy", str(max(1, int(round(h)))))


def _set_blip(pic: etree._Element, rid: str, img: _BrandImage, brand_name: str) -> None:
    blip_fill = pic.find(f"{{{_P}}}blipFill")
    blip = blip_fill.find(f"{{{_A}}}blip")
    for ch in list(blip):  # перекраска, дуотон, SVG-версия старого логотипа — не к логотипу бренда
        if etree.QName(ch).localname != "alphaModFix":
            blip.remove(ch)
    for attr in list(blip.attrib):
        if attr.startswith(f"{{{_R}}}"):
            del blip.attrib[attr]
    blip.set(f"{{{_R}}}embed", rid)
    for ch in list(blip_fill):
        if ch is not blip:
            blip_fill.remove(ch)
    l, t, r, b = img.crop
    if any(v > 0.001 for v in img.crop):
        src = etree.SubElement(blip_fill, f"{{{_A}}}srcRect")
        for k, v in (("l", l), ("t", t), ("r", r), ("b", b)):
            if v > 0.001:
                src.set(k, str(int(round(v * 100000))))
    etree.SubElement(etree.SubElement(blip_fill, f"{{{_A}}}stretch"), f"{{{_A}}}fillRect")
    nv = pic.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr")
    if nv is not None:
        label = f"Логотип {brand_name}".strip()
        nv.set("name", label)
        nv.set("descr", label)
        for ch in list(nv):  # ссылка старого логотипа
            nv.remove(ch)


def _new_pic(pkg: _Pkg, part: str, rid: str, img: _BrandImage, box, brand_name: str) -> etree._Element:
    root = pkg.xml(part)
    ids = [int(e.get("id")) for e in root.iter(f"{{{_P}}}cNvPr") if (e.get("id") or "").isdigit()]
    label = f"Логотип {brand_name}".strip()
    pic = etree.fromstring(
        f'<p:pic xmlns:p="{_P}" xmlns:a="{_A}" xmlns:r="{_R}"><p:nvPicPr><p:cNvPr id="{max(ids, default=1) + 1}" name="" descr=""/>'
        f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr userDrawn="1"/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )
    pic.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr").set("name", label)
    pic.find(f"{{{_P}}}nvPicPr/{{{_P}}}cNvPr").set("descr", label)
    _set_blip(pic, rid, img, brand_name)
    _set_box(pic, [], box)
    return pic


def _main_lockups(lockups: list[Lockup], place: Optional[str], sw: float, sh: float) -> set[int]:
    """На каждой части — один логотип бренда: из нескольких логотипов шаблона (свой и партнёра, «VK WorkSpace» и
    «VK tech») остаётся тот, что ближе к месту из брендбука, иначе самый крупный; остальные убираются."""
    keep: set[int] = set()
    by_part: dict[str, list[Lockup]] = {}
    for lk in lockups:
        if not lk.duplicate:
            by_part.setdefault(lk.part, []).append(lk)
    for lst in by_part.values():
        if place:
            cx = sw if place.endswith("right") else 0.0
            cy = sh if place.startswith("bottom") else 0.0
            best = min(lst, key=lambda lk: math.hypot(lk.box[0] + lk.box[2] / 2 - cx, lk.box[1] + lk.box[3] / 2 - cy))
        else:
            best = max(lst, key=lambda lk: lk.box[2] * lk.box[3])
        keep.add(id(best))
    return keep


def _replace_logos(
    pkg: _Pkg, lockups: list[Lockup], images: list[_BrandImage], brand_name: str, warnings: list[str], place: Optional[str] = None
) -> tuple[int, int]:
    """(заменено, убрано) логотипов шаблона."""
    sw, sh = _slide_size(pkg)
    media = _Media(pkg)
    main = _main_lockups(lockups, place, sw, sh)
    done = removed = 0
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
            warnings.append("Для логотипа шаблона не нашлось подходящего логотипа бренда — оставлен логотип шаблона.")
            continue
        keep = lk.pics[0]
        rid = pkg.add_rel(lk.part, _IMG_REL, media.part_for(img))
        _set_blip(keep.el, rid, img, brand_name)
        _set_box(keep.el, keep.groups, _fit(lk.box, img.aspect, sw))
        for pc in lk.pics[1:]:
            if pc.el.getparent() is not None:
                pc.el.getparent().remove(pc.el)
        pkg.dirty.add(lk.part)
        done += 1
    return done, removed


def _content_samples(manifest: TemplateManifest) -> dict[int, tuple[str, str]]:
    """Содержательные образцы разбора: номер слайда → (макет, фон light / dark)."""
    out: dict[int, tuple[str, str]] = {}
    for p in manifest.patterns:
        kind = p.kind.value if hasattr(p.kind, "value") else str(p.kind)
        if not p.layout_part or kind in ("title", "section", "thanks") or p.reference:
            continue
        out[p.source_slide] = (p.layout_part, p.family.value if hasattr(p.family, "value") else str(p.family))
    return out


def _slide_order(pkg: _Pkg) -> list[str]:
    """Части слайдов в порядке презентации."""
    root = pkg.xml("ppt/presentation.xml")
    rels = pkg.rels("ppt/presentation.xml")
    out = []
    lst = root.find(f"{{{_P}}}sldIdLst") if root is not None else None
    for sid in lst if lst is not None else []:
        tgt = rels.get(sid.get(f"{{{_R}}}id") or "", ("", None))[1]
        if tgt:
            out.append(tgt)
    return out


def _place_pic(pkg: _Pkg, part: str, media: "_Media", img: _BrandImage, box, brand_name: str) -> None:
    root = pkg.xml(part)
    tree = root.find(f"{{{_P}}}cSld/{{{_P}}}spTree")
    rid = pkg.add_rel(part, _IMG_REL, media.part_for(img))
    pic = _new_pic(pkg, part, rid, img, box, brand_name)
    ext_lst = tree.find(f"{{{_P}}}extLst")
    if ext_lst is not None:
        ext_lst.addprevious(pic)
    else:
        tree.append(pic)
    pkg.dirty.add(part)


def _add_logos(pkg: _Pkg, manifest: TemplateManifest, brand: BrandSpec, images: list[_BrandImage], warnings: list[str]) -> int:
    """Логотипа в шаблоне нет, а брендбук велит место — логотип бренда на содержательные слайды: на их макет, если
    образцы шаблона оставляют угол свободным (логотип макета лежит под фигурами слайда), иначе — поверх образцов,
    у которых угол свободен (фон-картинка не мешает), с полями брендбука."""
    if not brand.logo_place or not images:
        return 0
    sw, sh = _slide_size(pkg)
    margin = (brand.margins_px / 1920.0 * sw) if brand.margins_px and 0 < brand.margins_px <= 200 else 0.04 * sw
    media = _Media(pkg)
    order = _slide_order(pkg)
    samples = _content_samples(manifest)
    by_layout: dict[str, list[tuple[str, str]]] = {}
    for idx, (lp, fam) in samples.items():
        if 0 < idx <= len(order):
            by_layout.setdefault(lp, []).append((order[idx - 1], fam))
    users: dict[str, list[str]] = {}
    for part in order:
        for typ, tgt in pkg.rels(part).values():
            if typ.endswith("/slideLayout"):
                users.setdefault(tgt, []).append(part)

    def box_for(img: _BrandImage) -> tuple[float, float, float, float]:
        h = (0.06 if img.aspect < 1.6 else 0.045) * sh
        w = h * img.aspect
        place = brand.logo_place or "bottom_right"
        return (margin if place.endswith("left") else sw - margin - w, margin if place.startswith("top") else sh - margin - h, w, h)

    added = busy = 0
    for lp, slides in sorted(by_layout.items()):
        ground = Counter(f for _, f in slides).most_common(1)[0][0]
        img = pick_logo(images, "dark" if ground == "dark" else "light", mark=False)
        if img is None or pkg.xml(lp) is None:
            continue
        box = box_for(img)
        using = users.get(lp, [])
        if not using or sum(_covers(pkg, sp, box) for sp in using) <= len(using) / 3:
            _place_pic(pkg, lp, media, img, box, brand.name)
            added += 1
            continue
        for part, fam in slides:
            im2 = pick_logo(images, "dark" if fam == "dark" else "light", mark=False) or img
            b2 = box_for(im2)
            if _covers(pkg, part, b2, backgrounds=False):
                busy += 1
                continue
            _place_pic(pkg, part, media, im2, b2, brand.name)
            added += 1
    if busy:
        warnings.append(f"Логотип бренда не поставлен на {busy} слайд(а) шаблона: угол занят их содержимым.")
    return added


_FILLS = ("solidFill", "gradFill", "blipFill", "pattFill")


def _filled(sp: etree._Element) -> bool:
    """У фигуры есть видимая заливка (своя или из стиля темы)."""
    pr = sp.find(f"{{{_P}}}spPr")
    if pr is not None:
        for ch in pr:
            name = etree.QName(ch).localname
            if name in _FILLS:
                return True
            if name == "noFill":
                return False
    ref = sp.find(f"{{{_P}}}style/{{{_A}}}fillRef")
    return ref is not None and (ref.get("idx") or "0") not in ("0", "")


def _opaque_at(pkg: _Pkg, slide: str, pic: etree._Element, pbox, box) -> bool:
    """Картинка непрозрачна там, где встал бы логотип (фон-картинка с прозрачным углом логотип не закрывает)."""
    blip = pic.find(f"{{{_P}}}blipFill/{{{_A}}}blip")
    rid = blip.get(f"{{{_R}}}embed") if blip is not None else None
    media = pkg.rels(slide).get(rid or "", ("", None))[1]
    if not media or not pkg.has(media):
        return True
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(pkg.read(media)))
        if "A" not in im.getbands() and im.mode != "P":
            return True
        alpha = im.convert("RGBA").getchannel("A")
    except Exception:  # noqa: BLE001
        return True
    px, py, pw, ph = pbox
    x, y, w, h = box
    l = max(0.0, (x - px) / pw) * alpha.width
    t = max(0.0, (y - py) / ph) * alpha.height
    r = min(1.0, (x + w - px) / pw) * alpha.width
    b = min(1.0, (y + h - py) / ph) * alpha.height
    if r - l < 1 or b - t < 1:
        return False
    import numpy as np

    region = np.asarray(alpha.crop((int(l), int(t), int(math.ceil(r)), int(math.ceil(b)))))
    return bool(region.size) and float(region.mean()) > 128


def _covers(pkg: _Pkg, slide: str, box, backgrounds: bool = True) -> bool:
    """Фигура слайда закрывает место логотипа (больше 5 % его площади): залитая фигура, таблица, диаграмма, группа,
    картинка — если она там непрозрачна. `backgrounds=False` — фигуры во весь слайд (фон) не считаются: логотип
    встанет поверх них."""
    root = pkg.xml(slide)
    tree = root.find(f"{{{_P}}}cSld/{{{_P}}}spTree") if root is not None else None
    if tree is None:
        return False
    x, y, w, h = box
    for el in tree:
        tag = etree.QName(el).localname
        if tag in ("sp", "pic", "cxnSp"):
            b = _xfrm_box(el.find(f"{{{_P}}}spPr/{{{_A}}}xfrm"))
        elif tag == "graphicFrame":
            b = _xfrm_box(el.find(f"{{{_P}}}xfrm"))
        elif tag == "grpSp":
            b = _xfrm_box(el.find(f"{{{_P}}}grpSpPr/{{{_A}}}xfrm"))
        else:
            continue
        if not b:
            continue
        iw = max(0.0, min(x + w, b[0] + b[2]) - max(x, b[0]))
        ih = max(0.0, min(y + h, b[1] + b[3]) - max(y, b[1]))
        if iw * ih <= 0.05 * w * h:
            continue
        if not backgrounds and b[2] * b[3] >= 0.85 * _slide_size(pkg)[0] * _slide_size(pkg)[1]:
            continue
        if tag == "sp" and not _filled(el):
            continue  # рамка текста без заливки
        if tag == "pic" and not _opaque_at(pkg, slide, el, b, box):
            continue
        return True
    return False


# ============================================================================================ применение


@dataclass
class ApplyResult:
    """Что сделано с копией — для `brand.json`, отчёта и слоя «Брендбук»."""

    priority: str = "brand"
    changed_parts: int = 0
    colors: dict[str, str] = field(default_factory=dict)  # «#FF3885» → «#FF3985»
    fonts: dict[str, str] = field(default_factory=dict)  # heading / body → что записано
    font_swaps: dict[str, str] = field(default_factory=dict)  # «Arial» → «Play»
    bold_headings: int = 0
    logos_replaced: int = 0
    logos_removed: int = 0  # второй логотип шаблона на той же части (партнёр, соседняя марка)
    logos_added: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.changed_parts > 0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["changed"] = self.changed
        return d


def resolve_brand_dir(brand: BrandSpec, brand_dir: Optional[Path | str], workspace_root: Optional[Path | str] = None) -> Optional[Path]:
    if brand_dir:
        return Path(brand_dir)
    if brand.id and SAFE_ID_RE.fullmatch(brand.id):
        d = (Path(workspace_root) if workspace_root else default_workspace_root()) / "brandbooks" / brand.id
        if d.is_dir():
            return d
    return None


def _theme_of(src: Path | str) -> ThemeInfo:
    pkg = _Pkg(src)
    return _pkg_theme(pkg)


def _pkg_theme(pkg: _Pkg) -> ThemeInfo:
    """Тема первого мастера (у копии и шаблона одна и та же)."""
    rels = pkg.rels("ppt/slideMasters/slideMaster1.xml") if pkg.has("ppt/slideMasters/slideMaster1.xml") else {}
    name = next((t for typ, t in rels.values() if typ.endswith("/theme")), None) or next(
        (n for n in sorted(pkg.names()) if _THEME_RE.match(n)), None
    )
    root = pkg.xml(name) if name else None
    return theme_info(root) if root is not None else ThemeInfo()


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
    pkg = _Pkg(src)
    res = ApplyResult(priority=priority)
    theme = _pkg_theme(pkg)
    cp = plan_colors(manifest, brand, priority, theme)
    fp = plan_fonts(manifest, brand, priority)
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
            if root is not None and _retheme(root, cp, fp, colors):
                pkg.dirty.add(name)
        elif _VISIBLE_RE.match(name):
            root = pkg.xml(name)
            if root is None:
                continue
            a = _recolor(root, cp, colors)
            b = _refont(root, fp, fonts)
            if a or b:
                pkg.dirty.add(name)

    # логотипы
    bdir = resolve_brand_dir(brand, brand_dir)
    images = [im for im in (_load_logo(lg, bdir) for lg in brand.logos) if im is not None]
    if brand.logos and not images:
        res.warnings.append("Файлы логотипов брендбука не найдены — логотипы шаблона оставлены.")
    lockups = find_template_logos(pkg, manifest, theme.slots)
    if lockups:
        if priority == "brand" and images:
            res.logos_replaced, res.logos_removed = _replace_logos(pkg, lockups, images, brand.name, res.warnings, brand.logo_place)
    elif images:
        res.logos_added = _add_logos(pkg, manifest, brand, images, res.warnings)

    res.colors = {f"#{a}": f"#{b}" for (a, b) in sorted(colors)}
    res.font_swaps = {a: b for (a, b) in sorted(fonts) if a != "bold"}
    res.bold_headings = fonts.get(("bold", "heading"), 0)
    res.changed_parts = pkg.save(out)
    return res


def retune_manifest(copy: TemplateManifest, original: TemplateManifest, plan: ColorPlan, applied: dict[str, str]) -> bool:
    """Цвета разбора копии, оставшиеся от картинок шаблона (их пиксели не перекрашиваются: акцент шаблона в его
    фоновой картинке), заменяются по тому же плану — новые элементы колоды (диаграммы, карточки, таблицы) берут цвета
    бренда. Меняются только цвета, которые были у шаблона и не получились из бренда. True — что-то изменилось."""
    orig = {t.hex.upper() for t in original.tokens.colors}
    outputs = {v.lstrip("#").upper() for v in applied.values()} | set(plan.table.values())

    def m(h: Optional[str]) -> Optional[str]:
        if not h or not re.fullmatch(r"#?[0-9A-Fa-f]{6}", h):
            return h
        hu = h.lstrip("#").upper()
        if hu in orig and hu not in outputs:
            nh = plan.map(hu)
            return ("#" + nh) if h.startswith("#") else nh
        return h

    changed = False
    merged: dict[str, object] = {}
    out = []
    for t in copy.tokens.colors:
        nh = m(t.hex)
        if nh != t.hex:
            changed = True
            t = t.model_copy(update={"hex": nh})
        prev = merged.get(t.hex)
        if prev is None:
            merged[t.hex] = t
            out.append(t)
            continue
        # два цвета шаблона стали одним цветом бренда — один токен с общим весом
        prev.weight += t.weight  # type: ignore[attr-defined]
        for k, v in t.contexts.items():
            prev.contexts[k] = prev.contexts.get(k, 0) + v  # type: ignore[attr-defined]
        for k, v in t.context_weight.items():
            prev.context_weight[k] = prev.context_weight.get(k, 0.0) + v  # type: ignore[attr-defined]
        prev.roles = list(dict.fromkeys([*prev.roles, *t.roles]))  # type: ignore[attr-defined]
        prev.is_brand = prev.is_brand or t.is_brand  # type: ignore[attr-defined]
    copy.tokens.colors = out
    comp = copy.components
    targets = [
        (comp.chart_style, "series_colors"),
        (comp.table_style, "header_fill_hex"), (comp.table_style, "header_text_hex"), (comp.table_style, "body_text_hex"),
        (comp.table_style, "band_fill_hex"), (comp.table_style, "border_hex"),
        (comp.card, "fill_hex"), (comp.card, "line_hex"), (comp.number_callout, "color_hex"),
        (comp.icon_chip, "bg_hex"), (comp.icon_chip, "icon_color_hex"), (copy.tokens.shapes, "card_fill_hex"),
    ]
    for obj, attr in targets:
        if obj is None:
            continue
        v = getattr(obj, attr)
        nv = list(dict.fromkeys(m(x) for x in v)) if isinstance(v, list) else m(v)
        if nv != v:
            setattr(obj, attr, nv)
            changed = True
    for b in copy.tokens.backgrounds:
        nh = m(b.hex)
        if nh != b.hex:
            b.hex = nh
            changed = True
    return changed


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
    p = root / "templates" / template_id / BRAND_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
    mp = d / "manifest.json"
    if not mp.exists():
        return False
    try:
        version = json.loads(mp.read_text(encoding="utf-8")).get("analysis_version")
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
            for stale in ("manifest.json",):
                (d / stale).unlink(missing_ok=True)
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
        # цвета картинок шаблона в разборе копии → цвета бренда (сами картинки не перекрашиваются)
        try:
            info = branded_info(key, root) or {}
            theme = _theme_of(base.source)
            plan = plan_colors(manifest, brand, priority, theme)
            if retune_manifest(copy, manifest, plan, (info.get("result") or {}).get("colors") or {}):
                mp = d / "manifest.json"
                tmpm = d / ".manifest.json.tmp"
                tmpm.write_text(copy.model_dump_json(indent=2), encoding="utf-8")
                os.replace(tmpm, mp)
        except Exception as e:  # noqa: BLE001 - разбор копии остаётся как есть
            log.warning("branded manifest retune failed: %s", e)
        return key
