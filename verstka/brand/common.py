"""Общее для чтения брендбуков: ошибка с текстом для человека, роли цветов и шрифтов по словам, правила, поля, сетка.

Каждый читатель (`tokens.py`, `pdf.py`, `folder.py`, `figma.py`) находит «сырые» цвета и шрифты со своими подсказками,
а здесь из них собирается чистая палитра (`make_palette`) и пара шрифтов (`make_fonts`): без повторов, по одному цвету на
единственные роли (основной, фон, текст…), с угаданными по яркости ролями, если брендбук их не подписал. Всё — детерминированный
код без модели."""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from verstka.ru import ru_count
from verstka.schemas.brand import BrandColor, BrandColorRole, BrandFont, BrandFontRole, BrandRule, BrandRuleKind, LogoPlace, normalize_hex
from verstka.schemas.common import relative_luminance


class BrandReadError(ValueError):
    """Брендбук не прочитан; текст ошибки — для человека, по-русски («Файл пустой», «Нужен FIGMA_TOKEN…»)."""


# ---- роли цветов ---------------------------------------------------------------------------------------------------
# Порядок важен только при равенстве: побеждает слово, которое встретилось раньше, а среди начатых в одном месте — более
# длинное («основной текст» — текст, а не «основной»).
_L = r"(?<![a-zа-яё0-9])"  # начало слова (подчёркивания и точки путей заменены пробелами заранее)
_ROLE_PATTERNS: list[tuple[BrandColorRole, str]] = [
    ("text", r"основн\w*\s+текст\w*|текст\w*|text|foreground|fg|ink|copy"),
    ("primary", r"primary|основн\w*|главн\w*\s+цвет\w*"),
    ("secondary", r"secondary|дополнительн\w*|вторичн\w*|втор\w*\s+цвет\w*"),
    ("accent", r"accent|highlight|втор\w*\s+акцент\w*|акцент\w*"),
    ("background", r"background|bg|backdrop|canvas|фон\w*"),
    ("surface", r"surface|card|panel|container|подложк\w*|плашк\w*"),
    ("chart", r"chart|charts|data\s*viz|dataviz|series|диаграмм\w*|график\w*|инфограф\w*"),
    ("neutral", r"neutral|gray|grey|muted|нейтральн\w*|сер(?:ый|ая|ое|ые|ого|ой)|приглушённ\w*|приглушенн\w*"),
    ("success", r"success|positive|успех\w*|успешн\w*|позитивн\w*"),
    ("warning", r"warning|caution|предупрежд\w*"),
    ("danger", r"danger|error|negative|critical|ошибк\w*|опасн\w*|негативн\w*"),
]
_ROLE_RES = [(role, re.compile(_L + "(?:" + pat + r")(?![a-zа-яё])", re.I)) for role, pat in _ROLE_PATTERNS]
# слабые слова: «brand», «фирменный» — имя группы, а не роль; «основной» — только если других слов-ролей нет
# («color.brand.secondary» — дополнительный, «color.brand» — основной)
_WEAK_PRIMARY = re.compile(_L + r"(?:brand|main|фирменн\w*|бренд\w*)(?![a-zа-яё])", re.I)

ROLE_LABELS: dict[str, str] = {
    "primary": "основной", "secondary": "дополнительный", "accent": "акцент", "text": "текст", "background": "фон",
    "surface": "подложка", "chart": "графики", "neutral": "нейтральный", "success": "успех", "warning": "предупреждение",
    "danger": "ошибка",
}
# у этих ролей один цвет; второй такой же уходит в графики (цветные) или в нейтральные (текст, фон, подложка)
_SINGLE_ROLES = {"primary": "chart", "secondary": "chart", "accent": "chart", "text": "neutral", "background": "neutral", "surface": "neutral"}


def words(s: str) -> str:
    """«color.brandPrimary/hover» → «color brand primary hover»: пути токенов и имена стилей — словами."""
    s = re.sub(r"(?<=[a-zа-яё0-9])(?=[A-ZА-ЯЁ])", " ", str(s))
    return re.sub(r"[._/\\\-–—:]+", " ", s).lower()


def color_role(text: str) -> Optional[BrandColorRole]:
    """Роль цвета по словам рядом с ним: первое по месту слово-роль, при равенстве — самое длинное."""
    w = words(text)
    best: Optional[tuple[int, int, BrandColorRole]] = None
    for role, rx in _ROLE_RES:
        m = rx.search(w)
        if m and (best is None or (m.start(), -(m.end() - m.start())) < (best[0], best[1])):
            best = (m.start(), -(m.end() - m.start()), role)
    if best:
        return best[2]
    return "primary" if _WEAK_PRIMARY.search(w) else None


# ---- цвета ------------------------------------------------------------------------------------------------------------
_HEX_ANY = re.compile(r"#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z])")
_RGB_FN = re.compile(r"rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})", re.I)
_HSL_FN = re.compile(r"hsla?\(\s*(-?\d+(?:\.\d+)?)(?:deg)?\s*[, ]\s*(\d+(?:\.\d+)?)%\s*[, ]\s*(\d+(?:\.\d+)?)%", re.I)


def parse_color(value: object, *, named: bool = False) -> Optional[str]:
    """«#0077ff», «#0077FFCC», «rgb(0, 119, 255)», «hsl(217, 100%, 50%)», {"hex": …}, {"colorSpace": "srgb", "components": [0, .47, 1]},
    {"r": 0, "g": .47, "b": 1} (Figma) → «#0077FF»; не цвет — None. Названия CSS («blue») читаются только с `named=True`:
    без него слово вроде «bold» или «left» цветом не считается."""
    if isinstance(value, dict):
        if isinstance(value.get("hex"), str):
            return parse_color(value["hex"], named=named)
        comps = value.get("components")
        if isinstance(comps, (list, tuple)) and len(comps) >= 3 and all(isinstance(c, (int, float)) for c in comps[:3]):
            if str(value.get("colorSpace", "srgb")).lower() not in ("srgb", ""):
                return None
            return rgb_hex(*(c * 255 for c in comps[:3]))
        if all(isinstance(value.get(k), (int, float)) for k in ("r", "g", "b")):
            r, g, b = value["r"], value["g"], value["b"]
            scale = 255 if max(r, g, b) <= 1 else 1
            return rgb_hex(r * scale, g * scale, b * scale)
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    m = _HEX_ANY.fullmatch(s)
    if m:
        h = m.group(1)
        return normalize_hex(h[:6] if len(h) == 8 else h)
    m = _RGB_FN.match(s)
    if m:
        return rgb_hex(*(int(x) for x in m.groups()))
    m = _HSL_FN.match(s)
    if m:
        h, sat, lig = float(m.group(1)) % 360, float(m.group(2)), float(m.group(3))
        if sat <= 100 and lig <= 100:
            r, g, b = colorsys.hls_to_rgb(h / 360, lig / 100, sat / 100)
            return rgb_hex(r * 255, g * 255, b * 255)
    if named and re.fullmatch(r"[A-Za-z]{3,25}", s):
        try:
            from PIL import ImageColor

            r, g, b = ImageColor.getrgb(s.lower())[:3]
            return rgb_hex(r, g, b)
        except ValueError:
            return None
    return None


def rgb_hex(r: float, g: float, b: float) -> str:
    c = lambda v: max(0, min(255, int(round(v))))  # noqa: E731
    return f"#{c(r):02X}{c(g):02X}{c(b):02X}"


def cmyk_hex(c: float, m: float, y: float, k: float) -> str:
    """CMYK в процентах (0–100) → HEX по простой формуле (без профиля печати — приблизительно)."""
    c, m, y, k = (max(0.0, min(100.0, v)) / 100 for v in (c, m, y, k))
    return rgb_hex(255 * (1 - c) * (1 - k), 255 * (1 - m) * (1 - k), 255 * (1 - y) * (1 - k))


def saturation(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[2]


def hue(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


def lightness(hex_: str) -> float:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[1]


def rgb_distance(a: str, b: str) -> float:
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5


# слова, которые не бывают именем цвета: «Default», «Base», «blue-500»
_NAME_JUNK_WORDS = {"default", "base", "main", "normal", "regular", "standard", "color", "colour", "colors", "colours", "palette", "brand"}


def usable_color_name(name: Optional[str]) -> Optional[str]:
    """Имя цвета для людей («VK Blue», «Acme Coral»): не слово-роль («Primary», «Основной»), не «Default» и не шкала («blue-500»)."""
    n = (name or "").strip()
    if not n or len(n) > 30 or color_role(words(n)) is not None or n.lower() in _NAME_JUNK_WORDS:
        return None
    if re.fullmatch(r"[a-zа-яё]+[\s_-]?\d{2,3}", n.lower()):
        return None
    return n


@dataclass
class ColorHit:
    """Цвет, найденный читателем: HEX, роль, если брендбук её назвал, имя («VK Blue»). `approx` — HEX пересчитан из CMYK
    без цветового профиля; `rank` — 0 для обычного цвета роли и 1 для «второго» («text.secondary», «background.muted»):
    при двух цветах одной роли побеждает меньший `rank`."""

    hex: str
    role: Optional[BrandColorRole] = None
    name: Optional[str] = None
    approx: bool = False
    rank: int = 0


def _colorful(hex_: str) -> bool:
    return saturation(hex_) >= 0.35 and 0.18 <= lightness(hex_) <= 0.85


_WEAK_ROLES = (None, "chart", "neutral")


def make_palette(hits: Iterable[ColorHit], *, max_colors: int = 12) -> tuple[list[BrandColor], list[str]]:
    """Палитра без повторов: один HEX — один цвет (конкретная роль важнее «графиков», «нейтрального» и неподписанной), по
    одному цвету на единственные роли; роли «основной», «текст», «фон» угадываются по насыщенности и яркости, если
    брендбук их не назвал. HEX, пересчитанные из CMYK, помечаются предупреждением (приблизительно)."""
    warnings: list[str] = []
    order: list[str] = []
    by_hex: dict[str, ColorHit] = {}
    for h in hits:
        try:
            hx = normalize_hex(h.hex)
        except ValueError:
            continue
        cur = by_hex.get(hx)
        if cur is None:
            by_hex[hx] = ColorHit(hx, h.role, h.name, h.approx, h.rank)
            order.append(hx)
            continue
        if cur.role in _WEAK_ROLES and h.role not in _WEAK_ROLES:
            cur.role, cur.rank = h.role, h.rank
        elif cur.role is None and h.role:
            cur.role, cur.rank = h.role, h.rank
        elif cur.role == h.role:
            cur.rank = min(cur.rank, h.rank)
        if not cur.name and h.name:
            cur.name = h.name
        cur.approx = cur.approx and h.approx  # точное значение (HEX, RGB) важнее пересчёта из CMYK
    items = [by_hex[hx] for hx in order]
    if len(items) > max_colors:
        warnings.append(f"В брендбуке {ru_count(len(items), 'цвет', 'цвета', 'цветов')} — взял первые {max_colors}.")
        items = items[:max_colors]
    taken: set[str] = set()
    for role, demoted in _SINGLE_ROLES.items():
        cands = [(it.rank, i) for i, it in enumerate(items) if it.role == role]
        if not cands:
            continue
        taken.add(role)
        win = min(cands)[1]
        for _, i in cands:
            if i != win:
                items[i].role = demoted  # type: ignore[assignment]
    free = [it for it in items if it.role is None]
    guessed: list[str] = []
    if free and len(items) >= 2:
        if "background" not in taken:
            light = [it for it in free if relative_luminance(it.hex) >= 0.85]
            if light:
                pick = max(light, key=lambda it: relative_luminance(it.hex))
                pick.role = "background"
                guessed.append(f"{pick.hex} — фон")
                free.remove(pick)
        if "text" not in taken:
            dark = [it for it in free if relative_luminance(it.hex) <= 0.06]
            if dark:
                pick = min(dark, key=lambda it: relative_luminance(it.hex))
                pick.role = "text"
                guessed.append(f"{pick.hex} — текст")
                free.remove(pick)
        if "primary" not in taken:
            bright = [it for it in free if _colorful(it.hex)]
            if bright:
                pick = bright[0]
                pick.role = "primary"
                guessed.append(f"{pick.hex} — основной")
                free.remove(pick)
                if "accent" not in taken:
                    far = [it for it in free if _colorful(it.hex) and min(abs(hue(it.hex) - hue(pick.hex)), 360 - abs(hue(it.hex) - hue(pick.hex))) >= 60]
                    if far:
                        far[0].role = "accent"
                        guessed.append(f"{far[0].hex} — акцент")
                        free.remove(far[0])
    if guessed:
        warnings.append("Роли цветов в брендбуке не подписаны — угадал по яркости и насыщенности: " + ", ".join(guessed) + ". Проверьте.")
    approx = [it.hex for it in items if it.approx]
    if approx:
        warnings.append(f"{', '.join(approx)} — пересчитано из CMYK приблизительно, без цветового профиля печати: сверьте с HEX из брендбука.")
    colors = [BrandColor(hex=it.hex, role=it.role or "chart", name=it.name) for it in items]
    return colors, warnings


# ---- шрифты -------------------------------------------------------------------------------------------------------------
GENERIC_FAMILIES = {
    "sans-serif", "serif", "monospace", "system-ui", "cursive", "fantasy", "ui-sans-serif", "ui-serif", "ui-monospace",
    "-apple-system", "blinkmacsystemfont", "inherit", "initial", "unset", "emoji", "math",
}
_WEIGHT_WORDS = {
    "thin": 100, "hairline": 100, "extralight": 200, "extra light": 200, "ultralight": 200, "light": 300, "regular": 400,
    "normal": 400, "book": 400, "roman": 400, "medium": 500, "semibold": 600, "semi bold": 600, "demibold": 600,
    "demi bold": 600, "bold": 700, "extrabold": 800, "extra bold": 800, "ultrabold": 800, "black": 900, "heavy": 900,
    "тонкий": 100, "светлый": 300, "обычный": 400, "нормальный": 400, "средний": 500, "полужирный": 600, "жирный": 700,
}
# «Montserrat Bold», «Montserrat Bold Italic», «Montserrat Bold 32» (размер в таблице ролей — не часть названия), «Montserrat 32pt»
_SIZE_TAIL = r"\s+\d{1,3}(?:[.,]\d+)?\s*(?:pt|px|пт)?"
_WEIGHT_TAIL = re.compile(r"\s+(" + "|".join(sorted((re.escape(k) for k in _WEIGHT_WORDS), key=len, reverse=True)) + r")(?:\s+italic)?(?:" + _SIZE_TAIL + r")?\s*$", re.I)
_UNIT_SIZE_TAIL = re.compile(r"\s+\d{1,3}(?:[.,]\d+)?\s*(?:pt|px|пт)\s*$", re.I)

_HEADING_WORDS = re.compile(_L + r"(?:heading|headings|header|display|title|headline|h[1-3]|заголов\w*|акцидентн\w*)(?![a-zа-яё])", re.I)
_BODY_WORDS = re.compile(_L + r"(?:body|paragraph|text|copy|base|regular\s+text|основн\w*\s+текст\w*|текст\w*|наборн\w*)(?![a-zа-яё])", re.I)


def font_role(text: str) -> Optional[BrandFontRole]:
    """«heading», «Заголовки», «typography.h1» → heading; «body», «Основной текст» → body; по первому слову-роли."""
    w = words(text)
    mh, mb = _HEADING_WORDS.search(w), _BODY_WORDS.search(w)
    if mh and (not mb or mh.start() <= mb.start()):
        return "heading"
    if mb:
        return "body"
    return None


def weight_of(value: object) -> Optional[int]:
    """700, «700», «Bold», «semi-bold» → число; не вес — None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and 1 <= value <= 1000:
        return int(round(value / 100.0) * 100) or 100
    if isinstance(value, str):
        s = value.strip().lower().replace("-", " ").replace("_", " ")
        if s.isdigit():
            return weight_of(int(s))
        return _WEIGHT_WORDS.get(s) or _WEIGHT_WORDS.get(s.replace(" ", ""))
    return None


def split_weight(family: str) -> tuple[str, Optional[int]]:
    """«VK Sans Display Bold» → («VK Sans Display», 700)."""
    m = _WEIGHT_TAIL.search(family)
    if m and m.start() > 0:
        return family[: m.start()].strip(), weight_of(m.group(1))
    u = _UNIT_SIZE_TAIL.search(family)
    if u and u.start() > 0:  # «Montserrat 32pt»; число без единицы и без веса — часть названия («Source Sans 3»)
        return split_weight(family[: u.start()])
    return family.strip(), None


def font_stack(value: object) -> list[str]:
    """«"VK Sans Display", Play, sans-serif» или ["VK Sans Display", "Play"] → семейства без общих («sans-serif»)."""
    parts: list[str] = []
    if isinstance(value, (list, tuple)):
        raw = [str(v) for v in value]
    elif isinstance(value, str):
        raw = value.split(",")
    else:
        return parts
    for p in raw:
        p = p.strip().strip("'\"«»").strip()
        if p and p.lower() not in GENERIC_FAMILIES and p not in parts:
            parts.append(p)
    return parts


@dataclass
class FontHit:
    family: str
    role: Optional[BrandFontRole] = None
    weight: Optional[int] = None
    fallback: Optional[str] = None


def _name_role(family: str) -> Optional[BrandFontRole]:
    w = family.lower()
    if re.search(r"display|heading|title|head\b", w):
        return "heading"
    if re.search(r"\btext\b|body", w):
        return "body"
    return None


def _one_font_note(family: str, role: str) -> str:
    """Спокойное предупреждение: брендбук назвал шрифт только одной роли, на вторую поставлен тот же."""
    return (f"Назван только шрифт {'текста' if role == 'text' else 'заголовков'} — «{family}»: "
            f"{'для заголовков' if role == 'text' else 'для текста'} поставил тот же. Проверьте.")


def make_fonts(hits: Iterable[FontHit], *, fallback: Optional[str] = None) -> tuple[list[BrandFont], list[str]]:
    """Шрифт заголовков и шрифт текста: подписанные роли, затем подсказки в названии («Display» — заголовки, «Text» —
    текст), затем порядок. Одно семейство на всё — у обеих ролей; общая замена («Play») — тем, у кого своей нет."""
    warnings: list[str] = []
    by_role: dict[str, FontHit] = {}
    loose: list[FontHit] = []
    for h in hits:
        fam = (h.family or "").strip()
        if not fam or fam.lower() in GENERIC_FAMILIES:
            continue
        fam, w = split_weight(fam)
        hit = FontHit(fam, h.role, h.weight or w, h.fallback)
        if hit.fallback and hit.fallback.lower() == fam.lower():
            hit.fallback = None
        if hit.role:
            cur = by_role.get(hit.role)
            if cur is None:
                by_role[hit.role] = hit
            elif cur.family.lower() == fam.lower():
                cur.weight = cur.weight or hit.weight
                cur.fallback = cur.fallback or hit.fallback
            continue
        if not any(x.family.lower() == fam.lower() for x in loose):
            loose.append(hit)
    known = {h.family.lower() for h in by_role.values()}
    rest = [h for h in loose if h.family.lower() not in known]
    for h in list(rest):
        r = _name_role(h.family)
        if r and r not in by_role:
            h.role = r
            by_role[r] = h
            rest.remove(h)
    explicit = set(by_role)  # роли, названные брендбуком или читаемые по названию («Display», «Text»)
    for r in ("heading", "body"):
        if r not in by_role and rest:
            h = rest.pop(0)
            h.role = r  # type: ignore[assignment]
            by_role[r] = h
    if not by_role:
        return [], warnings
    if "heading" not in by_role:
        b = by_role["body"]
        by_role["heading"] = FontHit(b.family, "heading", None, b.fallback)
        if "body" in explicit:  # шрифт без роли («Шрифт: Circe») — один на всё, это не догадка
            warnings.append(_one_font_note(b.family, "text"))
    elif "body" not in by_role:
        hd = by_role["heading"]
        by_role["body"] = FontHit(hd.family, "body", None, hd.fallback)
        if "heading" in explicit:
            warnings.append(_one_font_note(hd.family, "headings"))
    common_fb = fallback or next((h.fallback for h in by_role.values() if h.fallback), None)
    fonts: list[BrandFont] = []
    for r in ("heading", "body"):
        h = by_role[r]
        fb = h.fallback or common_fb
        if fb and fb.lower() == h.family.lower():
            fb = None
        fonts.append(BrandFont(role=r, family=h.family, fallback=fb, weight=h.weight or (700 if r == "heading" else 400)))  # type: ignore[arg-type]
    return fonts, warnings


# ---- правила, поля, сетка, место логотипа -----------------------------------------------------------------------------------
_PLACE_RU = re.compile(r"(прав|лев)\w*\s+(верхн|нижн)\w*|(верхн|нижн)\w*\s+(прав|лев)\w*", re.I)
_PLACE_EN = re.compile(r"(top|bottom|upper|lower)[\s_\-]*(left|right)|(left|right)[\s_\-]*(top|bottom)", re.I)
_LOGO_WORDS = re.compile(r"логотип|logo|знак|wordmark", re.I)


def logo_place(text: str, *, need_logo_word: bool = True) -> Optional[LogoPlace]:
    """«Логотип — в правом нижнем углу», «logo: bottom-right» → bottom_right."""
    if need_logo_word and not _LOGO_WORDS.search(text):
        return None
    m = _PLACE_RU.search(text)
    if m:
        side = (m.group(1) or m.group(4) or "").lower()
        vert = (m.group(2) or m.group(3) or "").lower()
        return f"{'top' if vert.startswith('верх') else 'bottom'}_{'right' if side.startswith('прав') else 'left'}"  # type: ignore[return-value]
    m = _PLACE_EN.search(text)
    if m:
        vert = (m.group(1) or m.group(4) or "").lower()
        side = (m.group(2) or m.group(3) or "").lower()
        return f"{'top' if vert in ('top', 'upper') else 'bottom'}_{side}"  # type: ignore[return-value]
    return None


PLACE_TEXT = {
    "top_left": "в левом верхнем углу", "top_right": "в правом верхнем углу",
    "bottom_left": "в левом нижнем углу", "bottom_right": "в правом нижнем углу",
}

_UNIT_PX = {"px": 1.0, "пикс": 1.0, "pt": 96 / 72, "пт": 96 / 72, "mm": 96 / 25.4, "мм": 96 / 25.4, "rem": 16.0}
_MARGIN_RE = re.compile(
    r"(?<![а-яёa-z])(пол[яеь]\w*|отступ\w*\s+от\s+края\w*|отступ\w*|margins?|safe[\s\-]?area|page\s+padding|slide\s+padding)"
    r"[^\d\n]{0,30}?(\d{1,3}(?:[.,]\d+)?)\s*(px|пикс\w*|pt|пт|mm|мм|rem)(?![a-zа-яё])",
    re.I,
)
_CLEAR_SPACE = re.compile(r"охранн|clear\s*space|логотип|logo|знак", re.I)


def to_px(number: float, unit: str) -> float:
    u = unit.lower()
    k = next((v for key, v in _UNIT_PX.items() if u.startswith(key)), 1.0)
    return round(number * k, 1)


def margins_px(text: str) -> Optional[float]:
    """«Поля — 48 px», «margins: 36pt» → 48.0 / 48.0; охранное поле логотипа не считается полями слайда."""
    for line in re.split(r"[\n;]|(?<=[.!?])\s", text):
        if _CLEAR_SPACE.search(line):
            continue
        m = _MARGIN_RE.search(line)
        if m:
            return to_px(float(m.group(2).replace(",", ".")), m.group(3))
    return None


_COLS_RE = re.compile(r"(\d{1,2})\s*(?:-?\s*)(колон\w*|columns?|cols?)(?![a-zа-яё])", re.I)
_GUTTER_RE = re.compile(r"(промежут\w*|межколон\w*|gutter|gap|интервал\w*|просвет\w*)[^\d\n]{0,20}?(\d{1,3}(?:[.,]\d+)?)\s*(px|пикс\w*|pt|пт|mm|мм)", re.I)


def grid_text(columns: Optional[int], gutter_px: Optional[float]) -> Optional[str]:
    if not columns:
        return None
    s = ru_count(columns, "колонка", "колонки", "колонок")
    if gutter_px:
        s += f", промежуток {gutter_px:g} px"
    return s


def find_grid(text: str) -> Optional[str]:
    """«Сетка: 12 колонок, промежуток 24 px» → «12 колонок, промежуток 24 px»."""
    for line in re.split(r"\n", text):
        m = _COLS_RE.search(line)
        if not m:
            continue
        cols = int(m.group(1))
        if not 2 <= cols <= 24:
            continue
        g = _GUTTER_RE.search(line) or _GUTTER_RE.search(text)
        gutter = to_px(float(g.group(2).replace(",", ".")), g.group(3)) if g else None
        return grid_text(cols, gutter)
    return None


_RULE_MARK = re.compile(
    r"(?<![а-яёa-z])(только|нельзя|всегда|никогда|обязательно|должн\w*|запрещ\w*|минимальн\w*|максимальн\w*|"
    r"не\s+(?:меньше|больше|ближе|дальше|выше|ниже|более|менее)|"
    r"only|never|always|must|do not|don't|avoid|at least|no more than)(?![а-яёa-z])",
    re.I,
)
# повелительное наклонение: «используйте», «не ставьте», «держите», «оставляйте»
_IMPERATIVE = re.compile(r"(?<![а-яё])[а-яё]{3,}(?:йте|ите|ьте)(?![а-яё])", re.I)
_NEGATION = re.compile(r"(?<![а-яёa-z])(не\s+использ\w*|нельзя|запрещ\w*|never\s+use|do not use|don't use|avoid)", re.I)


def is_negative(text: str) -> bool:
    """Строка запрета («Не используйте #FF0000») — её цвета и шрифты не берутся в брендбук."""
    return bool(_NEGATION.search(text))


_KIND_RES: list[tuple[BrandRuleKind, re.Pattern]] = [
    ("logo", re.compile(_L + r"(?:логотип\w*|знак\w*|logo\w*|wordmark)", re.I)),
    ("type", re.compile(_L + r"(?:шрифт\w*|кегл\w*|начертан\w*|заголов\w*|интерлиньяж\w*|font\w*|typeface|type|heading\w*)(?![a-zа-яё])", re.I)),
    ("grid", re.compile(_L + r"(?:пол(?:я|ей|ях|ям|е)|сетк\w*|колон\w*|отступ\w*|выравн\w*|grid|margins?|columns?|spacing)(?![a-zа-яё])", re.I)),
    ("color", re.compile(_L + r"(?:цвет\w*|акцент\w*|палитр\w*|фон\w*|оттен\w*|контраст\w*|colou?rs?|accent|palette|background)(?![a-zа-яё])", re.I)),
]
_LABEL = re.compile(r"^(?:\d+\s+)?(?:как|так)\s+(?:правильно|можно|нельзя)(?:\s+и\s+(?:как|так)\s+(?:правильно|можно|нельзя))?$|"
                    r"^do'?s\s*(?:and|&)\s*don'?ts$", re.I)


def rule_kind(text: str) -> BrandRuleKind:
    for kind, rx in _KIND_RES:
        if rx.search(text):
            return kind
    return "other"


def clean_rule(text: str) -> str:
    s = re.sub(r"\s+", " ", text).strip()
    s = re.sub(r"^[\s•·▪●○◦✓✔✗✕✖×+\-–—*>\d.)]+", "", s).strip()
    s = re.sub(r"^(да|нет|так можно|так нельзя|так правильно|правильно|неправильно|можно|нельзя)\s*[:—–-]\s*", "", s, flags=re.I).strip()
    s = s.rstrip(" .;,:")
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) > 0.8 * len(letters):
        s = s.lower()  # подпись капителью («ИСПОЛЬЗУЙТЕ ЦВЕТА…») — обычным регистром
    return s[:1].upper() + s[1:] if s else s


def rule_key(text: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", "", text.lower().replace("ё", "е"))


_STOP = frozenset("для при над под без про как так что это или and the for with from все всех его она они оно".split())


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-zа-яё0-9]+", text.lower().replace("ё", "е")) if len(w) >= 3 and w not in _STOP}


def _same_rule(a: str, b: str) -> bool:
    """«Акцент — только для главного числа» и «Только для главного числа на слайде» — одно правило (общих основ ≥ 75 %)."""
    sa, sb = _stems(a), _stems(b)
    if len(sa) < 3 or len(sb) < 3:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= 0.75


def add_rule(rules: list[BrandRule], text: str, kind: Optional[BrandRuleKind] = None, *, limit: int = 12) -> bool:
    """Правило без повторов: то же по буквам или часть уже взятого — пропускается; полнее взятого («Акцент — только для
    главного числа» после «Только для главного числа») — заменяет его на том же месте. Не больше `limit`."""
    text = clean_rule(text)
    if len(text) < 6 or len(text.split()) < 3 and "—" not in text:
        return False
    key = rule_key(text)
    for i, r in enumerate(rules):
        k = rule_key(r.text)
        if key == k or (len(key) > 12 and key in k):
            return False
        if len(k) > 12 and k in key:
            rules[i] = BrandRule(text=text, kind=kind or rule_kind(text))
            return True
        if _same_rule(text, r.text):
            return False
    if len(rules) >= limit:
        return False
    rules.append(BrandRule(text=text, kind=kind or rule_kind(text)))
    return True


def looks_like_rule(sentence: str) -> bool:
    """Предложение-правило: «только», «нельзя», «всегда», «не больше…» или глагол в повелительном наклонении."""
    s = sentence.strip()
    if not 12 <= len(s) <= 180 or len(s.split()) < 3 or _LABEL.match(clean_rule(s)):
        return False
    return bool(_RULE_MARK.search(s) or _IMPERATIVE.search(s))


# ---- имя бренда ------------------------------------------------------------------------------------------------------------
_NAME_NOISE = re.compile(
    r"брендбук\w*|brand\s*book|brandbook|guidelines?|гайдлайн\w*|руководство\s+по\s+\w+(\s+стилю)?|фирменн\w+\s+стил\w*|"
    r"style\s*guide|design\s*system|дизайн[\s-]*систем\w*|design\s*tokens?|дизайн[\s-]*токен\w*|токен\w*|tokens?|variables|"
    r"переменн\w*|бренд(а|у)?(?![a-zа-яё])|(?<![a-z])brand(?![a-z])|версия\s*[\d.]+|v\d+(\.\d+)*|\b20\d\d\b",
    re.I,
)
_GENERIC_STEMS = {"tokens", "design-tokens", "tokens-studio", "variables", "guideline", "guidelines", "brandbook", "brand", "styles", "theme", "export"}


def brand_name(text: Optional[str]) -> Optional[str]:
    """«Брендбук VK Cloud», «VK Cloud — руководство по фирменному стилю» → «VK Cloud»; пусто — None."""
    if not text:
        return None
    s = _NAME_NOISE.sub(" ", str(text))
    s = re.sub(r"\s+", " ", s).strip(" \t-–—:·|,.«»\"'()")
    return s[:60] or None


def name_from_path(stem: str) -> Optional[str]:
    if stem.lower() in _GENERIC_STEMS:
        return None
    return brand_name(stem.replace("_", " ").replace("-", " ") if " " not in stem else stem)
