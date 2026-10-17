"""Цвета брендированной копии: тон и светлота цвета, тема шаблона, план замены цветов шаблона цветами бренда по ролям и
защита контраста текста.

Правила плана (приоритет «brand» — брендбук важнее на любом шаблоне):
- акценты палитры шаблона (цвета темы по порядку, акценты разбора по весу, в т. ч. насыщенные цвета фона и плашек,
  гиперссылка) → хроматические цвета бренда: первый и цвета фона → основной цвет бренда; остальные — ближайший тон в
  пределах 60° без повторов, пока есть свободные, а если близкого тона нет — по порядку роли (основной,
  дополнительный, цвета графиков). «Акцент» бренда (у VK Cloud — только для главного числа) достаётся только близкому
  по тону выделению, никогда — первому цвету и фону. Акцент, заметно отличный по светлоте (L* > 20), получает тон
  бренда своей светлоты: светлое остаётся светлым, тёмное — тёмным;
- смысловые цвета (рост / падение) → «успех» / «опасность» бренда; без пары остаются, только если это не цвет темы,
  не главная палитра и не первые цвета диаграмм шаблона — иначе это фирменный цвет шаблона, и его заменяет бренд;
- текст → текст бренда, фон → фон бренда — только той же светлоты и с читаемым текстом; иначе остаются, с причиной;
- нейтральные с оттенком (тёплые серые, беж, оливково-коричневые фоны) получают оттенок нейтральных цветов бренда при
  той же светлоте; чистые серые — как были; два разных нейтральных шаблона не сливаются в один;
- светлые оттенки акцентов (плашки) — тем же сдвигом тона при той же светлоте;
- контраст: для каждой пары «текст — то, на чём он стоит» в образцах шаблона (`text_pairs`, по правилу аудита
  `contrast_low`) новый контраст не ниже 4,5 : 1 (3 : 1 для крупного текста), если был не ниже, и не хуже прежнего,
  если был ниже; нарушение — цвет бренда в этой паре берётся со светлотой цвета шаблона (та же яркость — тот же
  контраст), а нейтральная пара (текст, фон) остаётся как в шаблоне.
Приоритет «template»: меняются только места, которые автор шаблона не заполнял (стандартная тема офисного пакета).
"""

from __future__ import annotations

import colorsys
import logging
import math
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from lxml import etree

from verstka.brand.package import A, Package
from verstka.schemas.brand import BrandPriority, BrandSpec, normalize_hex
from verstka.schemas.common import contrast_ratio, lab_to_rgb, rgb_to_lab
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

SRGB = f"{{{A}}}srgbClr"
THEME_SLOTS = ("dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink")
ACCENT_SLOTS = ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6")
ACCENT_ORDINALS = ("Основной акцент", "Второй акцент", "Третий акцент", "Четвёртый акцент", "Пятый акцент", "Шестой акцент")


def kept_reason_text(plan: "ColorPlan", h: str) -> Optional[str]:
    """Почему цвет шаблона остался — по-человечески (для расхождений и предупреждений), или None."""
    code = plan.kept_reason.get(h)
    target = plan.kept_target.get(h)
    what = "текст" if plan.text_pair and plan.text_pair[0] == h else ("фон" if plan.background_pair and plan.background_pair[0] == h else "цвет")
    if code == "polarity":
        mine = "светлый" if lightness(h) > 50 else "тёмный"
        theirs = "тёмный" if mine == "светлый" else "светлый"
        return f"у шаблона {what} {mine}, у бренда — {theirs}"
    if code == "guard":
        return f"#{target} у шаблона — другой цвет, они бы слились" if target else "у шаблона рядом другой похожий цвет"
    if code == "contrast":
        return "с цветом бренда текст шаблона стал бы нечитаемым"
    if code == "tone":
        return "у шаблона текст серый, а не чёрный — его светлота сохранена"
    if code == "semantic":
        return "смысловой цвет, в брендбуке нет пары"
    if code == "no_brand_colors":
        return "в брендбуке нет фирменных цветов"
    return None


# заметная разница цветов (ΔE76): ближе — для человека один цвет
NEUTRAL_DE = 15.0
# текст шаблона заметно светлее или темнее текста бренда (по L*) — своя светлота, оттенок бренда
TEXT_TONE_DL = 25.0


# ============================================================================================ цвет: меры


def hx(value: str) -> str:
    """«#0077ff» → «0077FF» (как в OOXML)."""
    return normalize_hex(value)[1:]


def rgb(h: str) -> tuple[int, int, int]:
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def from_rgb(r: float, g: float, b: float) -> str:
    return "".join(f"{max(0, min(255, int(round(v)))):02X}" for v in (r, g, b))


def hls(h: str) -> tuple[float, float, float]:
    r, g, b = (c / 255 for c in rgb(h))
    return colorsys.rgb_to_hls(r, g, b)


def chroma(h: str) -> float:
    r, g, b = rgb(h)
    return (max(r, g, b) - min(r, g, b)) / 255


def hue(h: str) -> float:
    return hls(h)[0] * 360


def hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


@lru_cache(maxsize=8192)
def lab(h: str) -> tuple[float, float, float]:
    return rgb_to_lab(*rgb(h))


def delta_e(a: str, b: str) -> float:
    return math.dist(lab(a), lab(b))


def lightness(h: str) -> float:
    """L* (CIE Lab): светлота для глаза; одинаковая L* — одинаковая яркость и контраст с любым цветом."""
    return lab(h)[0]


def lab_chroma(h: str) -> float:
    _, a, b = lab(h)
    return math.hypot(a, b)


def tone(h: str) -> str:
    """chromatic (насыщенный цвет) · tint (светлый оттенок цвета) · dark · light · grey."""
    c, light = chroma(h), hls(h)[1]
    if c >= 0.15 and light <= 0.85 and lightness(h) >= 15:
        return "chromatic"
    if c >= 0.06 and light > 0.85:
        return "tint"
    if lightness(h) < 20:
        return "dark"
    if lightness(h) > 90:
        return "light"
    return "grey"


def same_tone(a: str, b: str) -> bool:
    """Почти тот же цвет, записанный иначе (#0187F6 и #0077FF): тон ±5°, светлота ±0,06, насыщенность ±0,15."""
    ha, la, sa = hls(a)
    hb, lb, sb = hls(b)
    return hue_dist(ha * 360, hb * 360) <= 5 and abs(la - lb) <= 0.06 and abs(sa - sb) <= 0.15


def _lab_hex(L: float, a: float, b: float) -> str:
    """Цвет Lab в sRGB: насыщенность уменьшается, пока цвет не войдёт в охват с той же светлотой (±1)."""
    for k in (1.0, 0.92, 0.85, 0.78, 0.7, 0.62, 0.55, 0.47, 0.4, 0.32, 0.25, 0.17, 0.1, 0.0):
        r, g, bb = lab_to_rgb(L, a * k, b * k)
        h = from_rgb(r, g, bb)
        if abs(lightness(h) - L) <= 1.0 and all(0 < v < 255 for v in (r, g, bb)) or k == 0.0:
            return h
    return from_rgb(*lab_to_rgb(L, 0, 0))


def at_lightness(h: str, L: float) -> str:
    """Тон и насыщенность `h` (как в RGB: синий не уходит в сиреневый) при светлоте L* — та же яркость, что у цвета
    со светлотой L*, а значит, тот же контраст с любым цветом."""
    target = max(0.0, min(100.0, L))
    hh, _, ss = hls(h)
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if lightness(from_rgb(*(c * 255 for c in colorsys.hls_to_rgb(hh, mid, ss)))) < target:
            lo = mid
        else:
            hi = mid
    return from_rgb(*(c * 255 for c in colorsys.hls_to_rgb(hh, (lo + hi) / 2, ss)))


def tinted_like(h: str, ref: str) -> str:
    """Нейтральный `h` с оттенком нейтрального бренда `ref`: светлота `h`, направление оттенка `ref`, насыщенность —
    не больше своей и не больше, чем у `ref` (тёплый серый становится холодным серым той же яркости)."""
    L, a, b = lab(h)
    _, ra, rb = lab(ref)
    c_ref = math.hypot(ra, rb)
    c = min(math.hypot(a, b), c_ref)
    if c_ref < 1e-6 or c < 0.5:
        return _lab_hex(L, 0.0, 0.0)
    return _lab_hex(L, ra / c_ref * c, rb / c_ref * c)


def shifted_tint(h: str, a: str, b: str) -> str:
    """Оттенок акцента `a` (светлая плашка) → тот же оттенок цвета бренда `b`: светлота своя, тон сдвинут как у пары."""
    L, ha, hb_ = lab(h)
    _, aa, ab = lab(a)
    _, ba, bb = lab(b)
    ca, cb, ch = math.hypot(aa, ab), math.hypot(ba, bb), math.hypot(ha, hb_)
    ang = math.atan2(hb_, ha) + (math.atan2(bb, ba) - math.atan2(ab, aa))
    c = ch * (cb / ca if ca > 1 else 1.0)
    return _lab_hex(L, c * math.cos(ang), c * math.sin(ang))


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

        return sum(1 for s in ACCENT_SLOTS if is_stock_theme_color(self.slots.get(s, ""))) >= 3

    def chromatic_accents(self) -> list[str]:
        return list(dict.fromkeys(self.slots[s] for s in ACCENT_SLOTS if s in self.slots and tone(self.slots[s]) == "chromatic"))


def slot_hex(el: etree._Element) -> Optional[str]:
    for ch in el:
        if ch.tag == SRGB and ch.get("val"):
            return ch.get("val").upper()
        if ch.tag == f"{{{A}}}sysClr" and ch.get("lastClr"):
            return ch.get("lastClr").upper()
    return None


def theme_info(root: etree._Element) -> ThemeInfo:
    info = ThemeInfo()
    scheme = root.find(f".//{{{A}}}clrScheme")
    if scheme is not None:
        for el in scheme:
            name = etree.QName(el).localname
            h = slot_hex(el)
            if name in THEME_SLOTS and h and re.fullmatch(r"[0-9A-F]{6}", h):
                info.slots[name] = h
    for which in ("major", "minor"):
        lat = root.find(f".//{{{A}}}fontScheme/{{{A}}}{which}Font/{{{A}}}latin")
        if lat is not None and lat.get("typeface"):
            setattr(info, which, lat.get("typeface"))
    return info


_THEME_RE = re.compile(r"^ppt/theme/theme\d+\.xml$")


def package_theme(pkg: Package) -> ThemeInfo:
    """Тема первого мастера."""
    name = pkg.related("ppt/slideMasters/slideMaster1.xml", "theme") if pkg.has("ppt/slideMasters/slideMaster1.xml") else None
    name = name or next((n for n in sorted(pkg.names()) if _THEME_RE.match(n)), None)
    root = pkg.xml(name) if name else None
    return theme_info(root) if root is not None else ThemeInfo()


def template_theme(src: Path | str) -> ThemeInfo:
    """Тема шаблона по файлу (пустая, если файл не читается); кэш по файлу."""
    key = file_key(src)
    if key is not None:
        with _CACHE_LOCK:
            hit = _THEMES.get(key)
        if hit is not None:
            return hit
    try:
        theme = package_theme(Package(src))
    except Exception as e:  # noqa: BLE001
        log.warning("theme unreadable: %s", e)
        theme = ThemeInfo()
    if key is not None:
        with _CACHE_LOCK:
            if len(_THEMES) > 32:
                _THEMES.clear()
            _THEMES[key] = theme
    return theme


# ============================================================================================ пары «текст — фон»


@dataclass(frozen=True)
class TextPair:
    """Текст образца шаблона и то, на чём он стоит: цвет текста, цвет под ним, нужный контраст, контраст в шаблоне."""

    text: str
    ground: str
    need: float
    ratio: float
    fixed_ground: bool = False  # под текстом картинка — её цвет не меняется


# кэши живут в долгоживущем сервере, где копии строятся параллельно: чтение и вытеснение — под замком (вычисление —
# без него: два потока посчитают одно и то же, но не уронят друг друга KeyError)
_CACHE_LOCK = threading.RLock()
_PAIRS: dict[tuple, list[TextPair]] = {}
_IRS: "OrderedDict[tuple, object]" = OrderedDict()
IR_CACHE_SIZE = 2  # IR большого шаблона с картинками — десятки мегабайт (ЛЦТ ≈ 70, VK Education ≈ 140): сервер живёт долго
_THEMES: dict[tuple, ThemeInfo] = {}


def file_key(src: Path | str) -> Optional[tuple]:
    """(путь, время изменения, размер) — ключ кэшей по файлу шаблона; None — файла нет."""
    p = Path(src)
    try:
        st = p.stat()
    except OSError:
        return None
    return str(p.resolve()), st.st_mtime_ns, st.st_size


def source_ir(src: Path | str):
    """IR аудита для файла шаблона (рамки заполнителей — через макет и мастер, слои макета и мастера, фон, картинки),
    кэш по файлу; None — не строится."""
    key = file_key(src)
    if key is None:
        return None
    with _CACHE_LOCK:
        if key in _IRS:
            _IRS.move_to_end(key)
            return _IRS[key]
    try:
        from verstka.audit.ir import build_deck_ir

        ir = build_deck_ir(Path(src), with_images=True)
    except Exception as e:  # noqa: BLE001
        log.warning("deck IR unavailable: %s", e)
        ir = None
    with _CACHE_LOCK:
        _IRS[key] = ir
        while len(_IRS) > IR_CACHE_SIZE:
            _IRS.popitem(last=False)
    return ir


def text_pairs(src: Path | str, manifest: Optional[TemplateManifest] = None) -> list[TextPair]:
    """Пары «текст — фон» всех текстов образцов шаблона (как аудит `contrast_low`: фон — карточка, полоса макета,
    картинка или фон слайда; крупный текст — от 18 пт или полужирный от 14 пт). Кэш по файлу."""
    key = file_key(src)
    if key is None:
        return []
    with _CACHE_LOCK:
        hit = _PAIRS.get(key)
    if hit is not None:
        return hit
    out: dict[tuple, TextPair] = {}
    try:
        from verstka.audit.checks.common import composite_hex, fill_alpha, ground_of, text_elements

        ir = source_ir(src)
        for s in ir.slides if ir is not None else []:
            dark = getattr(s.family, "value", s.family) == "dark"
            role = "background.dark" if dark else "background.light"
            bg_slide = s.background_hex or (manifest.tokens.color_for(role) if manifest else None) or ("000000" if dark else "FFFFFF")
            for e in text_elements(s):
                color = e.dominant_color
                if not color or not (e.text or "").strip():
                    continue
                enclosing, kind = ground_of(s, e, bg_slide)
                under = enclosing or bg_slide
                try:
                    ground = composite_hex(e.fill_hex, fill_alpha(e), under) if e.fill_hex else under
                    ratio = contrast_ratio(color, ground)
                except ValueError:
                    continue
                size = e.dominant_size or 14.0
                bold = any(r.bold for par in e.paragraphs for r in par.runs if (r.text or "").strip())
                need = 3.0 if size >= 18 or (bold and size >= 14) else 4.5
                fixed = kind == "picture" and not e.fill_hex
                k = (color.upper(), ground.upper(), need, fixed)
                if k not in out or out[k].ratio > ratio:
                    out[k] = TextPair(color.upper(), ground.upper(), need, ratio, fixed)
    except Exception as e:  # noqa: BLE001 - без пар план строится без проверки контраста
        log.warning("text pairs unavailable: %s", e)
    res = list(out.values())
    with _CACHE_LOCK:
        if len(_PAIRS) > 32:
            _PAIRS.clear()
        _PAIRS[key] = res
    return res


# ============================================================================================ план цветов


@dataclass
class ColorPlan:
    """Как меняются цвета шаблона: `map(hex)` для явных цветов и слотов темы."""

    enabled: bool = True
    table: dict[str, str] = field(default_factory=dict)  # точные пары «цвет шаблона → цвет копии»
    keep: set[str] = field(default_factory=set)  # цвета, которые остаются
    kept_reason: dict[str, str] = field(default_factory=dict)  # почему остался: polarity, guard, contrast, semantic…
    kept_target: dict[str, str] = field(default_factory=dict)  # каким был бы цвет бренда
    palette: list[str] = field(default_factory=list)  # акценты шаблона по порядку
    main: list[str] = field(default_factory=list)  # главная палитра (по ней — «Второй акцент»)
    anchors: dict[str, str] = field(default_factory=dict)  # акцент шаблона → цвет копии
    brand_of: dict[str, str] = field(default_factory=dict)  # акцент шаблона → цвет бренда (до подгонки светлоты)
    text_pair: Optional[tuple[str, str]] = None  # (текст шаблона, текст бренда)
    background_pair: Optional[tuple[str, str]] = None
    neutral_ref: Optional[str] = None  # нейтральный бренда, чей оттенок получают нейтральные шаблона
    stock_slots: dict[str, str] = field(default_factory=dict)  # слот стандартной темы → цвет бренда
    chart_order: list[str] = field(default_factory=list)  # цвета диаграмм бренда по порядку (основной первым)
    brand_accents: set[str] = field(default_factory=set)  # «акцент» бренда — не раньше остальных цветов диаграмм
    link: Optional[str] = None  # цвет ссылок бренда — основной
    danger: Optional[str] = None  # цвет ошибки бренда (роль danger), если он есть
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
        if t == "chromatic" and self.danger and status_red(h):
            return self.danger  # красный ошибки и падения — цвет ошибки бренда
        if t == "chromatic" and self.anchors:
            # тот же цвет, чуть иначе записанный (#007DEA при #0187F6, маркер списка #FD0C50 при #FF0053); другой
            # насыщенный цвет, которого нет в палитре разбора (жёлтый рядом с оранжевым), остаётся как был
            twin = next((a for a in self.anchors if same_tone(h, a)), None)
            return self.anchors[twin] if twin is not None else h
        if t == "tint" and self.anchors:
            best = min((a for a in self.anchors if tone(a) == "chromatic"), key=lambda a: hue_dist(hue(h), hue(a)), default=None)
            if best is not None and hue_dist(hue(h), hue(best)) <= 25 and self.anchors[best] != best:
                return shifted_tint(h, best, self.anchors[best])
            return h
        if t in ("dark", "grey", "light") and self.neutral_ref and lab_chroma(h) >= 4.0:
            return tinted_like(h, self.neutral_ref)
        return h

    def map_strict(self, value: str) -> str:
        """Как `map`, но насыщенный цвет вне палитры шаблона (стили таблиц: зелёная, коричневая шапка) тоже получает
        цвет бренда — ближайший по тону из цветов диаграмм, своей светлоты."""
        h = self.map(value)
        if h != value.upper() or not self.enabled or not self.anchors or h in self.keep or tone(h) != "chromatic":
            return h
        if status_red(h):
            return self.danger or h  # смысловой красный (ошибка, падение) — не в синий бренда
        plain = [c for c in self.chart_order if c not in self.brand_accents] or self.chart_order
        if not plain:
            return h
        near = min(plain, key=lambda c: hue_dist(hue(c), hue(h)))
        return at_lightness(near, lightness(h))

    def map_link(self, value: str, near: float = 2.0) -> str:
        """Цвет ссылки (слот `hlink` темы, явный цвет текста со ссылкой): основной цвет бренда, если он не дальше `near`
        по светлоте, иначе его оттенок своей светлоты (контраст с фоном тот же), а не розовый акцент или офисный синий
        #0563C1."""
        h = self.map(value)
        v = value.upper()
        if not self.enabled or not self.link or v in self.keep or tone(v) != "chromatic":
            return h
        if h != v and tone(h) == "chromatic" and hue_dist(hue(h), hue(self.link)) <= 8:
            return h  # слот темы уже в семье основного (со своей подгонкой контраста)
        own = lightness(v)
        return self.link if abs(lightness(self.link) - own) <= near else at_lightness(self.link, own)

    def kept(self, h: str, reason: str, target: Optional[str] = None) -> None:
        was = self.table.pop(h, None)
        self.keep.add(h)
        self.kept_reason[h] = reason
        if target or was:
            self.kept_target[h] = target or was  # type: ignore[assignment]
        self._cache.clear()


def status_red(h: str) -> bool:
    """Красный «ошибки и падения» (тон 350–15°, насыщенный, средней светлоты): так шаблон отмечает отрицательное;
    розово-малиновый фирменный акцент (ЛЦТ #FF0053, 340°) — не он."""
    h = (h or "").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", h) or tone(h) != "chromatic":
        return False
    hu = hue(h)
    return (hu >= 350 or hu <= 15) and lab_chroma(h) >= 30 and 30 <= lightness(h) <= 70


def _brand_hex(brand: BrandSpec, role: str) -> Optional[str]:
    c = brand.color(role)  # type: ignore[arg-type]
    return hx(c.hex) if c else None


def brand_chromatic(brand: BrandSpec) -> list[tuple[str, str]]:
    """Хроматические цвета бренда — (hex, роль) по порядку: основной, дополнительный, акцент, графики."""
    out: list[tuple[str, str]] = []
    for role in ("primary", "secondary", "accent", "chart"):
        for c in brand.colors:
            h = hx(c.hex)
            if c.role == role and tone(h) == "chromatic" and h not in {x for x, _ in out}:
                out.append((h, role))
    return out


def brand_chart_order(brand: BrandSpec) -> list[str]:
    """Цвета диаграмм бренда: основной, дополнительный, цвета графиков; «акцент» — последним."""
    chrom = brand_chromatic(brand)
    return [h for h, r in sorted(chrom, key=lambda hr: {"primary": 0, "secondary": 1, "chart": 2}.get(hr[1], 3))]


def _accent_index(roles: list[str]) -> int:
    for r in roles:
        m = re.match(r"accent\.(\d+)", r or "")
        if m:
            return int(m.group(1))
    return 99


def _token_with(manifest: TemplateManifest, role: str) -> Optional[str]:
    """Цвет шаблона с этой ролью: сначала тот, у кого она главная, потом — среди всех ролей."""
    for t in manifest.tokens.colors:
        if t.role == role:
            return t.hex.upper()
    for t in manifest.tokens.colors:
        if role in t.roles:
            return t.hex.upper()
    return None


def _is_ground(manifest: TemplateManifest, h: str) -> bool:
    """Цвет — фон слайдов шаблона (роль фона или заливка фона слайда), а не акцент на плашке или в тексте."""
    for t in manifest.tokens.colors:
        if t.hex.upper() == h:
            return any(r.startswith("background") for r in t.roles) or (t.contexts or {}).get("background", 0) > 0
    return any(b.hex and b.hex.upper() == h for b in manifest.tokens.backgrounds)


def _is_accent(manifest: TemplateManifest, h: str, main: list[str]) -> bool:
    """Цвет — акцент шаблона (главная палитра или роль акцента в разборе), а не гиперссылка или цвет фона."""
    if h in main:
        return True
    return any(t.hex.upper() == h and any(r.startswith("accent.") for r in t.roles) for t in manifest.tokens.colors)


def _main_ground(manifest: TemplateManifest) -> str:
    """light / dark — какой фон у большинства слайдов шаблона."""
    n: Counter = Counter()
    for b in manifest.tokens.backgrounds:
        n[getattr(b.family, "value", b.family)] += len(b.slides) or 1
    if not n:
        return "light"
    return "dark" if n.get("dark", 0) > n.get("light", 0) else "light"


def _token_palette(manifest: TemplateManifest) -> list[str]:
    """Насыщенные цвета разбора с ролью акцента, фона или плашки — по порядку акцентов, затем по весу."""
    toks = [
        t for t in manifest.tokens.colors
        if tone(t.hex.upper()) == "chromatic" and any(r.startswith("accent.") or r.startswith("background") or r == "surface" for r in t.roles)
    ]
    toks.sort(key=lambda t: (_accent_index(t.roles), -t.weight))
    return [t.hex.upper() for t in toks]


def main_palette(manifest: TemplateManifest, theme: ThemeInfo) -> list[str]:
    """Главная палитра шаблона: насыщенные цвета темы, а у стандартной темы — заметные акценты разбора."""
    if theme.slots and not theme.stock and theme.chromatic_accents():
        return theme.chromatic_accents()
    toks = [t for t in manifest.tokens.colors if any(r.startswith("accent.") for r in t.roles) and tone(t.hex.upper()) == "chromatic"]
    total = sum(t.weight for t in toks) or 1.0
    return [t.hex.upper() for t in sorted(toks, key=lambda t: -t.weight) if t.weight / total >= 0.1][:4]


def plan_colors(
    manifest: TemplateManifest,
    brand: BrandSpec,
    priority: BrandPriority = "brand",
    theme: Optional[ThemeInfo] = None,
    pairs: Optional[list[TextPair]] = None,
) -> ColorPlan:
    theme = theme or ThemeInfo()
    plan = ColorPlan()
    chrom = brand_chromatic(brand)
    plan.chart_order = brand_chart_order(brand)
    plan.brand_accents = {h for h, r in chrom if r == "accent"}
    stock = theme.stock if theme.slots else False
    plan.danger = _brand_hex(brand, "danger")
    # слоты стандартной темы — места, которые автор шаблона не заполнял: бренд занимает их по порядку диаграмм;
    # красный слот (ошибка, отрицательное значение) — цвет ошибки бренда, а без него остаётся красным
    plain_order = [h for h in plan.chart_order if h not in plan.brand_accents] or plan.chart_order
    if stock and plain_order:
        k = 0
        for s in ACCENT_SLOTS:
            v = theme.slots.get(s)
            if v and tone(v) == "chromatic":
                if status_red(v):
                    if plan.danger:
                        plan.stock_slots[s] = plan.danger
                    continue
                plan.stock_slots[s] = plain_order[k % len(plain_order)]
                k += 1
    plan.main = main_palette(manifest, theme)
    if priority == "template":
        plan.enabled = bool(plan.stock_slots)
        for s, b in plan.stock_slots.items():
            plan.table.setdefault(theme.slots[s], b)
        plan.palette = list(plan.main)
        plan.keep = {t.hex.upper() for t in manifest.tokens.colors} - set(plan.table)
        return plan

    # --- приоритет брендбука: текст и фон
    light_ground = _main_ground(manifest) == "light"
    t_bg = _token_with(manifest, "background.light") or (theme.slots.get("lt1") if light_ground else None)
    t_text = _token_with(manifest, "text.primary") or (theme.slots.get("dk1") if light_ground else None)
    b_text, b_bg = _brand_hex(brand, "text"), _brand_hex(brand, "background")
    if t_text and b_text:
        if (lightness(t_text) < 50) == (lightness(b_text) < 50) and tone(t_text) != "chromatic" and abs(lightness(t_text) - lightness(b_text)) > TEXT_TONE_DL:
            # серый текст шаблона (#666666 у lo_focus) — его тон, а не чёрный бренда: своя светлота в оттенке бренда.
            # Иначе подписи обложки темнеют там, где шаблон рассчитывал на серый, и вёрстка обложки ведёт себя иначе,
            # чем на самом шаблоне (README, lo_focus с брендбуком VK Cloud)
            tinted = tinted_like(t_text, b_text) if lab_chroma(b_text) >= 4.0 else t_text
            plan.text_pair = (t_text, tinted)
            if tinted != t_text:
                plan.table[t_text] = tinted
            else:
                plan.kept(t_text, "tone", b_text)
        elif (lightness(t_text) < 50) == (lightness(b_text) < 50):
            plan.table[t_text] = b_text
            plan.text_pair = (t_text, b_text)
            dk1 = theme.slots.get("dk1")
            if dk1 and light_ground and tone(dk1) == "dark":
                plan.table.setdefault(dk1, b_text)  # слот текста темы — тоже текст
        else:
            plan.text_pair = (t_text, t_text)
            plan.kept(t_text, "polarity", b_text)
    if t_bg and b_bg:
        text_now = plan.table.get(t_text or "", t_text or "000000")
        if (lightness(t_bg) > 50) != (lightness(b_bg) > 50):
            plan.background_pair = (t_bg, t_bg)
            plan.kept(t_bg, "polarity", b_bg)
        elif contrast_ratio(text_now, b_bg) < 3.0:
            plan.background_pair = (t_bg, t_bg)
            plan.kept(t_bg, "contrast", b_bg)
        else:
            plan.table[t_bg] = b_bg
            plan.background_pair = (t_bg, b_bg)
    b_surface, t_surface = _brand_hex(brand, "surface"), _token_with(manifest, "surface")
    if t_surface and b_surface and t_surface not in plan.table and tone(t_surface) != "chromatic" and (lightness(t_surface) > 50) == (lightness(b_surface) > 50):
        plan.table[t_surface] = b_surface
    t_sec, b_neu = _token_with(manifest, "text.secondary"), _brand_hex(brand, "neutral")
    if t_sec and b_neu and t_sec not in plan.table and tone(t_sec) != "chromatic" and abs(lightness(t_sec) - lightness(b_neu)) <= 25:
        plan.table[t_sec] = b_neu
    # оттенок нейтральных бренда: текст бренда, его нейтральный, плашка, фон
    plan.neutral_ref = next((h for h in (b_text, b_neu, _brand_hex(brand, "surface"), b_bg) if h and tone(h) != "chromatic"), None)

    # --- смысловые цвета
    series = [s.upper() for s in manifest.components.chart_style.series_colors[:3]]
    theme_vals = set(theme.slots.values())
    semantic_mapped: list[str] = []
    for t in manifest.tokens.colors:
        if t.semantic not in ("positive", "negative"):
            continue
        h = t.hex.upper()
        b = _brand_hex(brand, "success" if t.semantic == "positive" else "danger")
        if b:
            plan.table.setdefault(h, b)
        elif t.semantic == "negative" and status_red(h) and h != (plan.main[0] if plan.main else None):
            plan.kept(h, "semantic")  # красный «падения» без пары в брендбуке остаётся красным, а не синим бренда
        elif h in theme_vals or h in plan.main or h in series:
            semantic_mapped.append(h)  # фирменный цвет шаблона, а не только «падение» — его заменяет бренд
        else:
            plan.kept(h, "semantic")

    # --- акценты палитры шаблона
    th = theme.chromatic_accents() if theme.slots and not stock else []
    palette = th + _token_palette(manifest) + semantic_mapped
    for slot in ("hlink", "folHlink"):
        hl = theme.slots.get(slot)
        if hl and tone(hl) == "chromatic":
            palette.append(hl)
    main0 = plan.main[0] if plan.main else None
    for h in dict.fromkeys(palette):
        if status_red(h) and h != main0 and h not in plan.table and h not in plan.keep:
            if plan.danger:
                plan.table[h] = plan.danger
            else:
                plan.kept(h, "semantic")  # красный акцент темы — цвет ошибки и падения; пары в брендбуке нет
    plan.palette = [p for p in dict.fromkeys(palette) if p not in plan.keep and p not in plan.table]
    if not chrom:
        for a in plan.main:
            if a not in plan.table:
                plan.kept(a, "no_brand_colors")
    else:
        plan.link = _brand_hex(brand, "primary") or next((h for h, r in chrom if r != "accent"), chrom[0][0])
        _assign_accents(plan, manifest, brand, chrom, {theme.slots[k] for k in ("hlink", "folHlink") if k in theme.slots})
        for s, b in plan.stock_slots.items():
            plan.table.setdefault(theme.slots[s], b)
    _guard_neutrals(plan, manifest, theme)
    if pairs:
        _guard_contrast(plan, pairs)
    for h in list(plan.kept_reason):
        role = "Текст" if plan.text_pair and plan.text_pair[0] == h else ("Фон" if plan.background_pair and plan.background_pair[0] == h else None)
        target = plan.kept_target.get(h)
        if target and delta_e(h, target) <= NEUTRAL_DE:
            continue  # для человека это тот же цвет — предупреждать не о чем
        if role and plan.kept_reason[h] in ("polarity", "guard", "contrast", "tone"):
            if h in plan.keep:
                plan.warnings.append(f"{role} шаблона #{h} оставлен: {kept_reason_text(plan, h)}.")
            else:
                plan.warnings.append(f"{role} шаблона #{h} — своей светлоты, в оттенке бренда #{plan.table.get(h, h)}: {kept_reason_text(plan, h)}.")
    plan._cache.clear()
    return plan


def _assign_accents(plan: ColorPlan, manifest: TemplateManifest, brand: BrandSpec, chrom: list[tuple[str, str]], links: set[str] = frozenset()) -> None:
    by_hex = dict(chrom)
    primary = _brand_hex(brand, "primary")
    if primary not in by_hex:
        primary = next((h for h, r in chrom if r != "accent"), chrom[0][0])
    plain = [h for h, r in chrom if r != "accent"] or [h for h, _ in chrom]
    order = sorted(plain, key=lambda h: {"primary": 0, "secondary": 1, "chart": 2}.get(by_hex[h], 3))
    uses: Counter = Counter()
    for i, a in enumerate(plan.palette):
        ground = _is_ground(manifest, a)
        twin = next((pa for pa in plan.anchors if same_tone(a, pa)), None)
        if a in by_hex:
            b = a
        elif twin is not None:
            b = plan.brand_of[twin]  # тот же цвет шаблона, записанный иначе, — тот же цвет бренда
        elif i == 0 or ground or a in links:
            # главный цвет, цвета фона и ссылки — основной цвет бренда (тёмный фон — его тёмный оттенок)
            b = primary
        else:
            d = {h: hue_dist(hue(a), hue(h)) for h, _ in chrom}
            near = [h for h in plain if d[h] <= 60]
            # «акцент» бренда — для выделения: только близкому по тону и светлоте акценту шаблона (не фону и не
            # ссылке); подгонять его светлоту нельзя — тёмный «акцент» уже не цвет бренда
            if _is_accent(manifest, a, plan.main):
                near += [h for h, r in chrom if r == "accent" and d[h] <= 30 and abs(lightness(a) - lightness(h)) <= 20]
            if near:
                b = min(near, key=lambda h: (d[h] + 40.0 * uses[h] + (10.0 if by_hex[h] == "accent" else 0.0), order.index(h) if h in order else 9))
                if b != primary and lightness(a) < 50 and lightness(b) - lightness(a) > (10 if ground else 20):
                    # близкий тон бренда получается только затемнением ниже L* 50 (голубой → петрольный у lo_focus) —
                    # тёмный оттенок основного: одна семья цветов
                    b = primary
            elif lightness(a) < 45:
                # тёмное без близкого тона (фиолетовые карточки) — тёмный оттенок основного: одна семья цветов,
                # а не бирюза из затемнённого голубого
                b = primary
            else:
                b = min(order, key=lambda h: (abs(lightness(h) - lightness(a)), order.index(h)))  # ближайший по светлоте
        uses[b] += 1
        plan.brand_of[a] = b
        final = b
        if b != a and (i > 0 or ground) and twin is None and abs(lightness(a) - lightness(b)) > (10 if ground else 20):
            # светлый акцент шаблона остаётся светлым, тёмный фон — тёмным: тон бренда при своей светлоте
            final = at_lightness(b, lightness(a))
        plan.anchors[a] = final
        plan.table.setdefault(a, final)


def _guard_neutrals(plan: ColorPlan, manifest: TemplateManifest, theme: ThemeInfo) -> None:
    """Два разных нейтральных цвета шаблона не сливаются в один: плашка #EBF3F9 на белом фоне не становится белой,
    если белый у шаблона уже есть."""
    own = {t.hex.upper() for t in manifest.tokens.colors} | set(theme.slots.values())
    for x, y in list(plan.table.items()):
        if x == y or tone(x) == "chromatic" or x in plan.anchors:
            continue
        for z in own:
            if z != x and plan.table.get(z, z) == z and delta_e(y, z) < 2.5 and delta_e(x, z) > 5.0:
                plan.kept(x, "guard", z)
                # точный цвет бренда занят — остаётся своя светлота, а оттенок — нейтральных бренда
                tinted = tinted_like(x, plan.neutral_ref) if plan.neutral_ref and lab_chroma(x) >= 4.0 else x
                if tinted != x:
                    plan.keep.discard(x)
                    plan.table[x] = tinted
                for attr in ("background_pair", "text_pair"):
                    pair = getattr(plan, attr)
                    if pair and pair[0] == x:
                        setattr(plan, attr, (x, tinted))
                break


def _guard_contrast(plan: ColorPlan, pairs: list[TextPair]) -> None:
    """Текст образцов шаблона остаётся читаемым: пара хуже нормы (4,5 : 1, крупный 3 : 1), которая была в норме, или
    заметно хуже прежнего → цвет бренда в паре получает светлоту цвета шаблона; нейтральный текст или фон остаётся."""
    neutral = {p[0] for p in (plan.text_pair, plan.background_pair) if p}
    step: Counter = Counter()
    for _ in range(6):
        plan._cache.clear()
        bad = []
        for p in pairs:
            t1 = plan.map(p.text)
            g1 = p.ground if p.fixed_ground else plan.map(p.ground)
            r1 = contrast_ratio(t1, g1)
            if (r1 < p.need and p.ratio >= p.need) or (p.ratio < p.need and r1 < p.ratio * 0.8):
                bad.append((p, t1, g1))
        if not bad:
            return
        for p, t1, g1 in bad:
            changed = [(o, n, q) for o, n, q in ((p.ground, g1, t1), (p.text, t1, g1)) if o != n and not (o == p.ground and p.fixed_ground)]
            # сначала подгоняется цвет бренда (акцент, оттенок); нейтральный текст или фон шаблона возвращается, только
            # если в паре нечего подогнать
            fixable = [c for c in changed if c[0] not in neutral]
            for orig, new, partner in fixable:
                # та же светлота, что у цвета шаблона, — тот же контраст; если партнёр тоже изменился, ещё на шаг дальше
                target = lightness(orig)
                if abs(lightness(new) - target) < 1.0:
                    step[orig] += 1
                    away = 1.0 if lightness(orig) >= lightness(partner) else -1.0
                    target += away * 4.0 * step[orig]
                nh = at_lightness(new, target)
                plan.table[orig] = nh
                if orig in plan.anchors:
                    plan.anchors[orig] = nh
            if not fixable:
                for orig, _, _ in changed:
                    plan.kept(orig, "contrast")
    plan._cache.clear()


# ============================================================================================ разбор копии


def retune_manifest(copy: TemplateManifest, original: TemplateManifest, plan: ColorPlan, applied: dict[str, str]) -> bool:
    """Разбор копии под бренд: цвета, оставшиеся от картинок шаблона и заливок с модификаторами, заменяются по тому же
    плану; цвета диаграмм начинаются с цветов бренда (основной первым, «акцент» бренда — не раньше остальных). True —
    что-то изменилось."""
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
    merged: dict = {}
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
        prev.weight += t.weight
        for k, v in t.contexts.items():
            prev.contexts[k] = prev.contexts.get(k, 0) + v
        for k, v in t.context_weight.items():
            prev.context_weight[k] = prev.context_weight.get(k, 0.0) + v
        prev.roles = list(dict.fromkeys([*prev.roles, *t.roles]))
        prev.is_brand = prev.is_brand or t.is_brand
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
    if plan.enabled and plan.chart_order and plan.anchors:
        old = [s.upper().lstrip("#") for s in comp.chart_style.series_colors]
        lead = [h for h in plan.chart_order if h not in plan.brand_accents]
        rest = [h for h in old if h not in plan.chart_order]
        tail = [h for h in plan.chart_order if h in plan.brand_accents and h in old]
        series = list(dict.fromkeys(lead + rest + tail))[: max(6, len(lead))]
        if series != old:
            comp.chart_style.series_colors = series
            changed = True
    return changed
