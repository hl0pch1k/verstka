"""PDF-гайдлайн → `BrandSpec`.

Без модели — по тексту (`pypdf`):
- цвета: HEX, а без HEX — RGB и CMYK; роль — по словам в той же строке перед цветом («Основной VK Blue #0077FF…»), затем
  после него, затем в соседних строках; если цвет встречается несколько раз (палитра, диаграммы), побеждает роль, за
  которую больше «голосов». Цвета только из строк-запретов («не используйте #FF0000») не берутся;
- шрифты: латинские названия рядом со словами «Заголовки», «Основной текст», «шрифт» («Заголовки — VK Sans Display, Bold
  700»); замена — после «замена», «fallback», «если … нет»;
- поля («Поля — 48 px»), сетка («12 колонок, промежуток 24 px»), место логотипа («Логотип — в правом нижнем углу») и
  правила — предложения со словами «только», «нельзя», «всегда», «не больше…» или с глаголом в повелительном наклонении;
- имя бренда — из заголовка документа («Брендбук VK Cloud» → «VK Cloud») или первой строки.

С моделью (`use_vlm`): страницы (`pypdfium2`) с палитрой, шрифтами и логотипами уходят навыку `brandbook_reader`, он уточняет
роли цветов, шрифты и правила. Модель не добавляет цветов, которых нет в тексте (кроме PDF-скана без текста), и при ошибке
остаётся чтение по тексту с предупреждением.

Логотипы: если передан `assets_dir`, картинки со страниц, где говорится о логотипе, сохраняются в `<assets_dir>/logos/`,
а версия (основной, белый, знак, монохром) определяется по самой картинке."""

from __future__ import annotations

import hashlib
import io
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from verstka.brand.common import (
    PLACE_TEXT,
    BrandReadError,
    ColorHit,
    FontHit,
    StepReporter,
    add_rule,
    as_reporter,
    brand_name,
    cmyk_hex,
    color_role,
    find_grid,
    fonts_result,
    font_role,
    is_negative,
    logo_place,
    logos_result,
    looks_like_rule,
    make_fonts,
    make_palette,
    margins_px,
    name_from_path,
    open_text,
    palette_result,
    parse_color,
    rgb_distance,
    rgb_hex,
    rules_result,
    split_weight,
    weight_of,
)
from verstka.ru import ru_count
from verstka.schemas.brand import BrandColor, BrandFont, BrandLogo, BrandRule, BrandSpec, LogoPlace

log = logging.getLogger(__name__)

_HEX = re.compile(r"(?<![0-9A-Za-z&])#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z])")
# «HEX 0052CC» без решётки — только с меткой HEX и шестью цифрами
_HEX_LABEL = re.compile(r"(?<![A-Za-z])HEX[\s:]*#?([0-9A-Fa-f]{6})(?![0-9A-Za-z])", re.I)
_SEP = r"[\s,;/·|:]+"
_RGB = re.compile(r"(?<![A-Za-z])RGB" + r"[\s:(]*(\d{1,3})" + _SEP + r"(\d{1,3})" + _SEP + r"(\d{1,3})", re.I)
# «R 0 G 82 B 204», «R:0 G:82 B:204»
_RGB_LETTERS = re.compile(r"(?<![A-Za-z])R\s*[:=]?\s*(\d{1,3})[\s,;/·|]+G\s*[:=]?\s*(\d{1,3})[\s,;/·|]+B\s*[:=]?\s*(\d{1,3})(?![0-9])")
_CMYK = re.compile(r"(?<![A-Za-z])CMYK" + r"[\s:(]*(\d{1,3})%?" + (_SEP + r"(\d{1,3})%?") * 3, re.I)
# «C100 M80 Y40 K50», «C 100 / M 80 / Y 40 / K 50»
_CMYK_LETTERS = re.compile(r"(?<![A-Za-z])C\s*[:=]?\s*(\d{1,3})%?[\s,;/·|]+M\s*[:=]?\s*(\d{1,3})%?[\s,;/·|]+Y\s*[:=]?\s*(\d{1,3})%?[\s,;/·|]+K\s*[:=]?\s*(\d{1,3})%?(?![0-9])")
# строки другого формата того же образца («Pantone 289 C») не разрывают описание образца
_OTHER_FORMAT = re.compile(r"\s*(?:pantone|pms|ral|ncs|web|css|hsl|hsb|lab)\b", re.I)
_FORMAT_LABEL = re.compile(r"\b(?:hex|rgb|cmyk)\b", re.I)

_FONT_HINT = re.compile(r"(?<![A-Za-z])(Sans|Serif|Display|Text|Grotesk|Grotesque|Mono|Gothic|Neue|Slab|Condensed|Rounded|Headline)(?![A-Za-z])")
_KNOWN_FONTS = {
    "play", "roboto", "inter", "arial", "helvetica", "montserrat", "open sans", "pt sans", "pt serif", "pt root ui", "golos",
    "manrope", "onest", "lato", "noto", "calibri", "cambria", "georgia", "verdana", "tahoma", "segoe ui", "ibm plex", "fira",
    "ubuntu", "raleway", "nunito", "rubik", "exo", "oswald", "merriweather", "lora", "unbounded", "jost", "futura", "gotham",
    "proxima nova", "gilroy", "circe", "tt norms", "times new roman", "source sans", "sf pro", "yandex sans", "aptos",
    "bebas neue", "trebuchet ms", "century gothic", "franklin gothic", "museo", "graphik", "suisse", "akzidenz", "din",
    "stem", "geometria", "helios", "comfortaa", "playfair", "spectral", "literata", "jetbrains mono", "source code",
    "poppins", "mulish", "karla", "quicksand", "barlow", "cabin", "work sans", "dm sans", "space grotesk", "plus jakarta",
    "libre baskerville", "alegreya", "cormorant", "avenir", "myriad", "frutiger", "univers", "optima", "garamond",
    "baskerville", "palatino", "bodoni", "didot", "gill sans", "lucida", "sofia pro", "cera pro", "tt commons",
}
_NOT_FONTS = {"hex", "rgb", "cmyk", "pdf", "png", "svg", "json", "pptx", "figma", "verstka", "google", "microsoft", "powerpoint",
              "keynote", "pantone", "tokens studio", "w3c", "w3c design tokens", "design tokens", "vk", "ral", "url"}
# слова-метки и обычные английские слова: одиночное слово с большой буквы после метки «шрифт» — название, но не они
_NOT_FONT_WORDS = {
    "use", "never", "always", "avoid", "only", "the", "this", "that", "all", "each", "logo", "colour", "color", "colors", "colours",
    "text", "body", "headings", "heading", "headline", "headlines", "title", "titles", "primary", "secondary", "accent", "background",
    "font", "fonts", "typeface", "typefaces", "regular", "bold", "light", "medium", "italic", "display", "typography", "weight",
    "weights", "size", "sizes", "see", "note", "when", "where", "for", "set", "our", "your", "not", "none", "same", "default",
}
_FONT_PHRASE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Za-z0-9]*(?:[ \-][A-Z0-9][A-Za-z0-9]*){0,4})")
_FONT_WORD = re.compile(r"шрифт|гарнитур|начертан|font|typeface", re.I)
_FALLBACK_AT = re.compile(r"замен\w*|fallback|запасн\w*|резервн\w*|вместо|если\s+(?:\S+\s+){0,4}?нет", re.I)
_WEIGHT_NEAR = re.compile(r"(?<![A-Za-zа-яё])(thin|extralight|light|regular|book|medium|semibold|demibold|bold|extrabold|black|heavy|"
                          r"обычн\w*|полужирн\w*|жирн\w*)(?![A-Za-zа-яё])|(?<!\d)([1-9]00)(?!\d)", re.I)
_LOGO_PAGE = re.compile(r"логотип|logo", re.I)

_MAX_RULES = 14
_VLM_PAGES = 6


class BrandbookReading(BaseModel):
    """Ответ навыка `brandbook_reader`: что модель увидела на страницах гайдлайна (часть `BrandSpec`)."""

    name: Optional[str] = None
    colors: list[BrandColor] = Field(default_factory=list)
    fonts: list[BrandFont] = Field(default_factory=list)
    logo_place: Optional[LogoPlace] = None
    margins_px: Optional[float] = None
    rules: list[BrandRule] = Field(default_factory=list)


# ---- текст ----------------------------------------------------------------------------------------------------------------
def _open(path: Path):
    import pypdf

    try:
        reader = pypdf.PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise BrandReadError(f"PDF «{path.name}» защищён паролем — снимите защиту и загрузите снова.")
        n = len(reader.pages)
    except BrandReadError:
        raise
    except Exception:  # noqa: BLE001 — pypdf бросает разные ошибки на испорченных файлах
        raise BrandReadError(f"Не удалось открыть PDF «{path.name}»: файл повреждён или это не PDF.") from None
    if n == 0:
        raise BrandReadError(f"В PDF «{path.name}» нет страниц.")
    return reader


def _page_texts(reader) -> list[str]:
    out = []
    for p in reader.pages:
        try:
            out.append(p.extract_text() or "")
        except Exception:  # noqa: BLE001
            out.append("")
    return out


def paragraphs(text: str) -> list[str]:
    """Строки PDF → абзацы: строка без точки в конце склеивается со следующей, если та начинается со строчной буквы,
    тире, кавычки или скобки (перенос внутри предложения)."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if out and not re.search(r"[.!?:;]$", out[-1]) and re.match(r"[a-zа-яё—–«(]", line):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for par in paragraphs(text):
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁ«])", par) if s.strip()]
    return out


# ---- цвета ------------------------------------------------------------------------------------------------------------------
_RANK = {"hex": 3, "rgb": 2, "cmyk": 1}


def _mentions(line: str) -> list[tuple[int, int, str, str]]:
    """Цвета в строке: (начало, конец, HEX, вид — hex / rgb / cmyk). RGB и CMYK — только если в строке нет HEX
    (это тот же цвет); CMYK — только если нет и RGB."""
    found: dict[int, tuple[int, int, str, str]] = {}
    for m in _HEX_LABEL.finditer(line):
        found[m.start(1)] = (m.start(), m.end(), "#" + m.group(1), "hex")
    for m in _HEX.finditer(line):
        found.setdefault(m.start(1), (m.start(), m.end(), "#" + m.group(1), "hex"))
    if found:
        return sorted(found.values())
    out: list[tuple[int, int, str, str]] = []
    for rx in (_RGB, _RGB_LETTERS):
        for m in rx.finditer(line):
            vals = [int(v) for v in m.groups()]
            if all(v <= 255 for v in vals):
                out.append((m.start(), m.end(), rgb_hex(*vals), "rgb"))
    if out:
        return sorted(out)
    for rx in (_CMYK, _CMYK_LETTERS):
        for m in rx.finditer(line):
            vals = [int(v) for v in m.groups()]
            if all(v <= 100 for v in vals):
                out.append((m.start(), m.end(), cmyk_hex(*vals), "cmyk"))
    return sorted(out)


_NAME_PHRASE = re.compile(r"[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,2}")
# слова, которые не бывают именем цвета: заголовки разделов, метки форматов и ролей («Colour palette», «Primary», «PANTONE»)
_NAME_JUNK = frozenset(
    "colour colours color colors palette palettes primary secondary tertiary accent text background brand brands hex rgb cmyk pantone "
    "pms ral ncs logo logos logotype typography font fonts guidelines guideline brandbook identity corporate style page main core "
    "extended additional neutral neutrals tint tints shade shades swatch swatches chart charts surface usage the and for".split()
)


def _clean_name(phrase: str) -> Optional[str]:
    ws = phrase.split()
    if len(phrase) < 3 or all(w.lower() in _NAME_JUNK for w in ws):
        return None
    return phrase


def _name_near(segment: str) -> Optional[str]:
    """Имя цвета в ячейке перед HEX: «Основной VK Blue » → «VK Blue»; «Primary — Aurora Green — PANTONE 349 C — » → «Aurora Green».
    Берётся ближайшее к цвету имя, не являющееся меткой («Colour», «Primary», «HEX», «PANTONE»)."""
    for seg in reversed(re.split(r"[·|:—–,]+", segment)):
        if _OTHER_FORMAT.match(seg):
            continue  # «PANTONE 349 C» — не имя
        for m in reversed(list(_NAME_PHRASE.finditer(seg))):
            name = _clean_name(m.group(0).strip())
            if name:
                return name
    return None


# «PANTONE 2925 C», «PMS 2925 C», «RAL 5015», «NCS S 2060-B»: номер каталога рядом с CMYK того же образца
_CATALOGUE = re.compile(r"\b(?:pantone|pms|ral|ncs)\b[\s\dA-Za-z.-]*?(?=$|[,;/·|]|\s*\([^)]*\)|\bCMYK\b|\bRGB\b|\bHEX\b)", re.I)


def _label_only(line: str, start: int, end: int) -> bool:
    """Строка — только метка формата, числа, номер Pantone/PMS/RAL/NCS и пометка в скобках («RGB 10 37 64», «PANTONE 2925 C ·
    CMYK 85 40 0 0», «CMYK 85 40 0 0 (печать)»): продолжение описания образца. «Печать: CMYK 0 35 100 0» и «CMYK 0 0 0 0 — фон
    слайдов» — со словами рядом — это уже отдельный цвет."""
    rest = _FORMAT_LABEL.sub("", line[:start] + " " + line[end:])
    rest = re.sub(r"\([^)]*\)", " ", rest)
    rest = _CATALOGUE.sub(" ", rest)
    return not re.search(r"[A-Za-zА-Яа-яЁё]", rest)


def _swatch_continuations(lines: list[str], per_line: list[list[tuple[int, int, str, str]]]) -> set[int]:
    """Номера строк, которые только повторяют цвет соседнего образца (RGB и CMYK рядом с HEX, CMYK рядом с RGB)."""
    nb = [i for i, ln in enumerate(lines) if ln]
    chains: list[list[int]] = []  # подряд идущие строки образца: с цветом или «Pantone 289 C»
    cur: list[int] = []
    for i in nb:
        if per_line[i] or _OTHER_FORMAT.match(lines[i]):
            cur.append(i)
        else:
            if cur:
                chains.append(cur)
            cur = []
    if cur:
        chains.append(cur)
    skip: set[int] = set()

    def label_only_line(i: int) -> bool:
        ms = per_line[i]
        return len(ms) == 1 and _label_only(lines[i], ms[0][0], ms[0][1])

    for chain in chains:
        pos = {i: k for k, i in enumerate(chain)}
        # RGB-строка — продолжение HEX того же образца, если рядом (до или после) HEX с тем же цветом
        for i in chain:
            ms = per_line[i]
            if ms and ms[0][3] == "rgb" and label_only_line(i):
                if any(per_line[j] and per_line[j][0][3] == "hex" and abs(pos[j] - pos[i]) <= 3
                       and any(len(h[2]) == 7 and rgb_distance(ms[0][2], h[2]) <= 18 for h in per_line[j] if h[3] == "hex")
                       for j in chain):
                    skip.add(i)
        # CMYK-строка — продолжение ближайшего образца с HEX или RGB
        for i in chain:
            ms = per_line[i]
            if ms and ms[0][3] == "cmyk" and label_only_line(i):
                if any(j not in skip and per_line[j] and per_line[j][0][3] in ("hex", "rgb") and abs(pos[j] - pos[i]) <= 3 for j in chain):
                    skip.add(i)
    # RGB-строка без HEX, равная названному где-то HEX, — дубль (RGB считается точно)
    hex_known = [m[2] for i, ms in enumerate(per_line) if i not in skip for m in ms if m[3] == "hex" and len(m[2]) == 7]
    for i, ms in enumerate(per_line):
        if i not in skip and ms and ms[0][3] == "rgb" and label_only_line(i) and any(rgb_distance(ms[0][2], h) <= 12 for h in hex_known):
            skip.add(i)
    return skip


def pdf_colors(text: str) -> list[ColorHit]:
    """Цвета гайдлайна с ролями по голосам (см. описание модуля)."""
    lines = [ln.strip() for ln in text.splitlines()]
    per_line = [_mentions(ln) for ln in lines]
    # образец цвета часто напечатан столбиком: имя, Pantone, CMYK, RGB и HEX отдельными строками — в любом порядке
    # («Pantone / CMYK / RGB / HEX» в печатных гайдлайнах, «HEX / RGB / CMYK» в экранных). Строки образца идут подряд, пока
    # не встретится строка с именем или текстом. Строка только с меткой формата и числами («RGB 10 37 64») в пределах трёх
    # строк до или после HEX (RGB — если число сходится с HEX) или RGB (CMYK) — тот же образец, отдельным цветом она не
    # считается. RGB и CMYK читаются как цвет, только если у образца нет HEX.
    skip = _swatch_continuations(lines, per_line)
    votes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    names: dict[str, str] = {}
    order: list[str] = []
    positive: set[str] = set()
    approx: dict[str, bool] = {}

    def _text_above(i: int) -> list[int]:
        """Строки с текстом над строкой i (ближайшая первой) — подписи карточки; строки того же образца (Pantone, CMYK, RGB) и
        пустые пропускаются, строка другого цвета обрывает поиск."""
        out: list[int] = []
        for k in range(i - 1, max(-1, i - 9), -1):
            if not lines[k] or k in skip or _OTHER_FORMAT.match(lines[k]):
                continue
            if per_line[k]:
                break
            out.append(k)
            if len(out) >= 3:
                break
        return out

    for i, ln in enumerate(lines):
        ms = per_line[i]
        if not ms or i in skip:
            continue
        neg = is_negative(ln)
        for j, (a, b, hx, kind) in enumerate(ms):
            hx = hx.upper() if len(hx) == 7 else "#" + "".join(c * 2 for c in hx[1:]).upper()
            if hx not in order:
                order.append(hx)
            approx[hx] = approx.get(hx, True) and kind == "cmyk"
            if neg:
                continue
            positive.add(hx)
            # слова роли берутся из того же предложения: «…цвет текста. Фон #FFFFFF» — «Фон», а не «текста»
            before = re.split(r"(?<=[.!?])\s+", ln[ms[j - 1][1] if j else 0: a])[-1]
            after = re.split(r"(?<=[.!?])\s+", ln[b: ms[j + 1][0] if j + 1 < len(ms) else len(ln)])[0]
            # строка-перечень («Порядок цветов в диаграммах: #…, #…») весит меньше строки-определения одного цвета
            single = len(ms) == 1
            r = color_role(before)
            if r:
                votes[hx][r] += (2.0 if single else 1.0) * (0.75 if r == "chart" else 1.0)
            else:
                r = color_role(after)
                if r:
                    votes[hx][r] += (1.5 if single else 0.75) * (0.75 if r == "chart" else 1.0)
                elif len(ms) == 1:
                    # карточка цвета: подпись роли — строкой выше или ниже (до другого цвета)
                    above = _text_above(i)
                    cands = [(above[0], 1.0)] if above else []
                    cands += [(above[1], 0.75)] if len(above) > 1 else []
                    cands += [(i + 1, 0.75)] if i + 1 < len(lines) and not per_line[i + 1] else []
                    for k, w in cands:
                        r = color_role(lines[k])
                        if r:
                            votes[hx][r] += w
                            break
            nm = _name_near(before)
            if not nm and single:
                # карточка: имя — одной из строк выше («VK Blue» / «Основной» / «#0077FF»); подпись роли, строки Pantone, CMYK и
                # RGB того же образца пропускаются
                for k in _text_above(i)[:3]:
                    if len(lines[k]) <= 24 and not color_role(lines[k]):
                        nm = _name_near(lines[k])
                        if nm:
                            break
            if nm and hx not in names:
                names[hx] = nm
    hits: list[ColorHit] = []
    exact = [hx for hx in order if hx in positive and not approx.get(hx)]
    for hx in order:
        if hx not in positive:
            continue
        if approx.get(hx) and any(rgb_distance(hx, e) <= 25 for e in exact):
            continue  # CMYK без профиля даёт цвет, чуть отличный от HEX того же образца: это не новый цвет
        v = votes.get(hx) or {}
        role = None
        if v:
            best = max(v.values())
            tops = [r for r in v if v[r] == best]
            role = next((r for r in tops if r != "chart"), tops[0])
        hits.append(ColorHit(hx, role, names.get(hx), approx=approx.get(hx, False)))  # type: ignore[arg-type]
    return hits


# ---- шрифты -----------------------------------------------------------------------------------------------------------------
# метка шрифта перед названием: «Шрифт заголовков:», «Headings:», «Primary typeface —», «…используется шрифт »
_LABEL_BEFORE = re.compile(
    r"(?:шрифт\w*|гарнитур\w*|начертан\w*|font\w*|typeface\w*|заголов\w*|heading\w*|headline\w*|body|текст\w*|основн\w*|"
    r"primary|secondary|display|set\s+in)\s*(?:[:—–-]\s*|\s+(?:is|are|—)\s+)?$",
    re.I,
)
# метка роли с двоеточием или тире: достаточна для названия вне списка, только если на странице вообще говорится о шрифтах
_ROLE = r"(?:heading\w*|headline\w*|title\w*|body(?:\s+(?:text|copy))?|text|заголов\w*|основн\w*\s+текст\w*|текст\w*)"
# «Headings: Poppins», «Body text — Inter», «Headlines are set in Aeonik»
_ROLE_LABEL_BEFORE = re.compile(r"(?:" + _ROLE + r"\s*[:—–-]\s*|" + _ROLE + r"\s+(?:is|are)\s+set\s+in\s+)$", re.I)
# строка таблицы ролей: слово роли открывает строку, дальше пробел и название («Заголовки Evolventa Bold»)
_ROLE_OPEN = re.compile(r"\s*" + _ROLE + r"\s+", re.I)
# «Для заголовков: Evolventa» — роль с «для» и двоеточием называет шрифт и без слов «шрифт» на странице
_FOR_LABEL_BEFORE = re.compile(r"(?:для|for)\s+(?:заголов\w*|подзаголов\w*|heading\w*|headline\w*|title\w*|основн\w*\s+текст\w*|текст\w*|body(?:\s+(?:text|copy))?|"
                               r"наборн\w*|таблиц\w*|подпис\w*)\s*[:—–-]\s*$", re.I)
# «используйте Evolventa», «набирайте …», «use …»: глагол перед названием, если в предложении есть «для заголовков», «for body»…
_VERB_BEFORE = re.compile(r"(?:используй\w*|примен[яи]\w*|набирай\w*|набир\w*\s+в|use|set\s+in|set\s+with)\s*$", re.I)
_FOR_ROLE = re.compile(r"(?:для|for)\s+(?:заголов\w*|подзаголов\w*|heading\w*|headline\w*|title\w*|основн\w*\s+текст\w*|текст\w*|body|"
                       r"наборн\w*|таблиц\w*|подпис\w*|caption\w*|table\w*)", re.I)
_LABEL_AFTER = re.compile(r"\s*(?:[—–,:-]\s*)?(?:это\s+|наш\s+|is\s+(?:the\s+|our\s+)?(?:\w+\s+)?)?(?:шрифт|гарнитур|font|typeface)", re.I)
_FONT_WORD_ANY = re.compile(r"шрифт|гарнитур|начертан|типограф|font|typeface|typograph", re.I)
# предложение про цвет — в нём названия шрифтов не ищутся: «Primary - Navy - RGB 10 37 64» (Navy — цвет, а не шрифт)
_COLOUR_SENTENCE = re.compile(r"(?<![A-Za-z])(?:RGB|CMYK|PANTONE|PMS|RAL|NCS)(?![A-Za-z])", re.I)
_LEAD_VERB = re.compile(r"(?:Use|Using|Set|Apply|Choose|Select)\s+(?=[A-Z])")
_LOWER_WORD_AFTER = re.compile(r"\s+([a-z]{3,})")
_WORD_OK_AFTER = {"is", "for", "and", "or", "and", "bold", "regular", "light", "medium", "italic", "semibold", "black", "thin"}
# названия цветов, которых нет среди имён CSS
_COLOUR_WORDS = {"sun", "ocean", "charcoal", "midnight", "mint", "snow", "sky", "coral", "teal", "slate", "ink", "paper", "rose", "sand", "lemon",
                 "amber", "berry", "forest", "graphite", "cobalt", "azure", "emerald", "ruby", "jade", "peach", "cream", "ivory", "steel", "storm"}


def _plausible_font(family: str, sent: str, brand: Optional[str], start: int, end: int, page_has_font_word: bool = False,
                    colour_next: bool = False) -> bool:
    """Похоже ли `family` на название шрифта. `colour_next` — следующая строка — про цвет («Text: Jet» / «HEX #…»): одиночное
    слово тогда, скорее всего, имя цвета."""
    low = family.lower()
    if low in _NOT_FONTS or (brand and low == brand.lower()) or len(family) < 3:
        return False
    hint = _FONT_HINT.search(family)
    if hint and hint.start() > 0 and len(family.split()) >= 2:  # «Golos Text» — да; одинокое «Text», «Display» и «Text Jet» (роль и цвет) — нет
        return True
    if low in _KNOWN_FONTS or any(low.startswith(k + " ") for k in _KNOWN_FONTS):
        return True
    if _FONT_WORD.search(sent) and len(family.split()) >= 2:
        return True
    # одно слово, которого нет в списке известных («Poppins»): нужны слова про шрифт — в предложении или на странице (метка роли,
    # строка таблицы ролей, «заголовки are set in …»), «Для заголовков: …», либо глагол «используйте …» с ролями; название
    # цвета («Navy») шрифтом не считается
    if (len(family.split()) == 1 and family.isalpha() and family[0].isupper() and low not in _NOT_FONT_WORDS and low not in _COLOUR_WORDS
            and parse_color(low, named=True) is None):
        nxt = _LOWER_WORD_AFTER.match(sent[end:])
        if nxt and nxt.group(1) not in _WORD_OK_AFTER:
            return False  # «Use sparingly» — обычная фраза, а не название
        pre = sent[max(0, start - 60):start]
        if _FONT_WORD_ANY.search(sent):
            return bool(_LABEL_BEFORE.search(pre) or _LABEL_AFTER.match(sent[end:end + 60]))
        if colour_next:
            return False
        if page_has_font_word and (_ROLE_LABEL_BEFORE.search(pre) or _ROLE_OPEN.fullmatch(sent[:start])):
            return True
        if _FOR_LABEL_BEFORE.search(pre):
            return True
        # «Для заголовков используйте Evolventa, для основного текста — Open Sans»: две роли говорят сами за себя; одна роль
        # («Use Cerulean for headings») — только на странице, где есть слова про шрифт
        roles = len(_FOR_ROLE.findall(sent))
        return bool(_VERB_BEFORE.search(pre) and (roles >= 2 or (roles == 1 and page_has_font_word)))
    return False


def _font_sentences(text: str) -> list[str]:
    """Предложения гайдлайна: роль шрифта ищется только внутри предложения («…Montserrat Bold. Для основного текста — Roboto»)."""
    return sentences(text)


def pdf_fonts(text: str, brand: Optional[str] = None) -> tuple[list[FontHit], Optional[str]]:
    """Шрифты гайдлайна и общая замена («Play»): роль — по слову-роли в том же предложении («Заголовки — …», «Для заголовков
    используется шрифт …», «… для заголовков»)."""
    hits: list[FontHit] = []
    fallback: Optional[str] = None
    page_font = bool(_FONT_WORD_ANY.search(text))
    units = _font_sentences(text)
    for n, sent in enumerate(units):
        if _HEX.search(sent) or _COLOUR_SENTENCE.search(sent) or is_negative(sent):
            continue
        following = units[n + 1] if n + 1 < len(units) else ""
        colour_next = bool(following and (_mentions(following) or _COLOUR_SENTENCE.search(following)))
        phrases = []
        for m in _FONT_PHRASE.finditer(sent):
            lead = _LEAD_VERB.match(m.group(1))  # «Use Evolventa» — глагол в начале предложения не часть названия
            start = m.start() + (lead.end() if lead else 0)
            fam, w = split_weight(m.group(1)[lead.end():] if lead else m.group(1))
            if _plausible_font(fam, sent, brand, start, start + len(fam), page_font, colour_next):
                phrases.append((start, start + len(fam), fam, w, m.end()))
        if not phrases:
            continue
        fb = _FALLBACK_AT.search(sent)
        if fb:
            after = [p for p in phrases if p[0] >= fb.end()]
            if after and not fallback:
                fallback = after[0][2]
            phrases = [p for p in phrases if p[0] < fb.start()]
        prev_took_after = False
        form_before: Optional[bool] = None  # слова «для …» в предложении стоят перед названием (True) или после него (False)
        for k, (a, b, fam, w, end) in enumerate(phrases):
            lo = phrases[k - 1][4] if k else 0
            hi = phrases[k + 1][0] if k + 1 < len(phrases) else len(sent)
            role, prev_took_after, form = _font_role_at(sent[lo:a], sent[end:hi], form_before, prev_took_after)
            form_before = form if form_before is None else form_before
            tail = sent[end:hi]
            wm = _WEIGHT_NEAR.search(tail)
            weight = w or (_weight_word(wm.group(1) or wm.group(2)) if wm else None)
            hits.append(FontHit(fam, role, weight))
    return hits, fallback


def _weight_word(word: str) -> Optional[int]:
    low = word.lower()
    if low.startswith("полужирн"):
        return 600
    if low.startswith("жирн"):
        return 700
    if low.startswith("обычн"):
        return 400
    return weight_of(word)


_ROLE_WORD = re.compile(r"(?:(для|for)\s+)?(заголов\w*|heading\w*|headline\w*|title\w*|основн\w*\s+текст\w*|текст\w*|body|наборн\w*)", re.I)


def _font_role_at(before: str, after: str, form_before: Optional[bool], prev_took_after: bool):
    """Роль шрифта по соседним словам: (роль, заняты ли слова «для …» после названия, форма предложения).

    1. слово-роль перед названием («Заголовки — VK Sans Display», «основной текст — Golos Text»);
    2. «для …» перед названием («Для заголовков используется шрифт Montserrat», «Для заголовков — Montserrat, для текста —
       Roboto»);
    3. «для …» сразу после названия («VK Sans Display для заголовков, Roboto для текста»).
    Какая из форм (2 или 3) в предложении, решает первое название с такими словами; «для …» между двумя названиями
    принадлежит следующему названию в форме 2 и предыдущему в форме 3."""
    own = [m for m in _ROLE_WORD.finditer(before) if not m.group(1)]
    fb = next((m for m in _ROLE_WORD.finditer(before) if m.group(1)), None)
    fa = next((m for m in _ROLE_WORD.finditer(after) if m.group(1)), None)
    if own:
        return font_role(own[-1].group(2)), False, True
    if form_before is None:
        if fb:
            return font_role(fb.group(2)), False, True
        if fa:
            return font_role(fa.group(2)), True, False
        return None, False, None
    if form_before:
        return (font_role(fb.group(2)) if fb else None), False, True
    if fa:
        return font_role(fa.group(2)), True, False
    if fb and not prev_took_after:
        return font_role(fb.group(2)), False, False
    return None, False, False


# ---- правила, поля, место логотипа ------------------------------------------------------------------------------------------------
def pdf_rules(text: str) -> tuple[list[BrandRule], Optional[float], Optional[str], Optional[LogoPlace]]:
    sents = sentences(text)
    place: Optional[LogoPlace] = None
    for s in sents:
        place = logo_place(s)
        if place:
            break
    margin = None
    for s in sents:
        margin = margins_px(s)
        if margin:
            break
    grid = find_grid("\n".join(paragraphs(text)))
    rules: list[BrandRule] = []
    if place:
        add_rule(rules, f"Логотип — {PLACE_TEXT[place]}", "logo")
    if margin:
        add_rule(rules, f"Поля — {margin:g} px", "grid")
    for s in sents:
        if _HEX.search(s) or _RGB.search(s) or len(re.findall(r"(?<![\d,])\d+(?![\d,])", s)) >= 5:
            continue  # строка таблицы цветов, а не правило
        if not looks_like_rule(s):
            continue
        if logo_place(s) or margins_px(s):
            continue  # уже есть коротким правилом выше
        add_rule(rules, s, limit=_MAX_RULES)
    return rules, margin, grid, place


# ---- логотипы со страниц --------------------------------------------------------------------------------------------------------
def logo_variant(img) -> tuple[str, str]:
    """Версия логотипа по картинке: (variant, ground). Белый на прозрачном — «white» (тёмный фон), одноцветный тёмный —
    «mono», почти квадратный — «mark», иначе — «primary»."""
    im = img.convert("RGBA")
    w, h = im.size
    small = im.copy()
    small.thumbnail((160, 160))
    raw = small.tobytes()
    allpx = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
    px = [p for p in allpx if p[3] > 128]
    square = 0.8 <= w / max(h, 1) <= 1.25
    has_alpha = any(p[3] < 64 for p in allpx)
    if px and has_alpha:
        light = sum(1 for p in px if min(p[:3]) >= 235) / len(px)
        if light >= 0.9:
            return "white", "dark"
        colorful = sum(1 for p in px if max(p[:3]) - min(p[:3]) > 60) / len(px)
        dark = sum(1 for p in px if max(p[:3]) <= 90) / len(px)
        if colorful < 0.05 and dark >= 0.6 and not square:
            return "mono", "light"
    if square:
        return "mark", "any"
    return "primary", "light"


LOGO_NAMES = {"primary": "Основной", "white": "Белый", "mark": "Знак", "mono": "Монохром"}


def _is_photo(img) -> bool:
    """Непрозрачная картинка с сотнями оттенков — фотография, а не логотип. У логотипа и плоской иллюстрации
    несколько цветов (даже у JPEG с шумом сжатия различных цветов в десятки раз меньше), у фотографии и текстуры —
    разных цветов больше 4 % пикселей уменьшенной копии."""
    from PIL import Image

    im = img.convert("RGBA")
    small = im.resize((96, 96), Image.NEAREST)
    raw = small.tobytes()
    px = [raw[i:i + 4] for i in range(0, len(raw), 4)]
    if sum(1 for p in px if p[3] < 200) / len(px) >= 0.05:
        return False  # прозрачный фон — вырезанный логотип
    return len({p[:3] for p in px}) / len(px) > 0.04


def pdf_logos(reader, page_texts: list[str], assets_dir: Path) -> list[BrandLogo]:
    out: list[BrandLogo] = []
    seen: set[str] = set()
    used: dict[str, int] = defaultdict(int)
    (assets_dir / "logos").mkdir(parents=True, exist_ok=True)
    for page, txt in zip(reader.pages, page_texts):
        if not _LOGO_PAGE.search(txt):
            continue
        try:
            images = list(page.images)
        except Exception:  # noqa: BLE001
            continue
        for im in images:
            if len(out) >= 6:
                return out
            digest = hashlib.sha1(im.data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            try:
                pil = im.image
            except Exception:  # noqa: BLE001
                continue
            if pil is None or min(pil.size) < 16 or pil.size[0] / max(pil.size[1], 1) > 12 or _is_photo(pil):
                continue
            variant, ground = logo_variant(pil)
            used[variant] += 1
            stem = variant if used[variant] == 1 else f"{variant}-{used[variant]}"
            rel = f"logos/{stem}.png"
            pil.save(assets_dir / rel, format="PNG")
            name = LOGO_NAMES[variant] + ("" if used[variant] == 1 else f" {used[variant]}")
            out.append(BrandLogo(name=name, file=rel, variant=variant, ground=ground))  # type: ignore[arg-type]
    return out


# ---- модель ----------------------------------------------------------------------------------------------------------------
def _page_images(path: Path, page_ids: list[int], max_w: int = 1600, on_page: Optional[Callable[[int, int], None]] = None) -> list[bytes]:
    """Страницы PDF → JPEG шириной не меньше 1600 px: HEX на образцах цвета мелкие, при 1024 px они не читаются."""
    import pypdfium2 as pdfium

    out: list[bytes] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in page_ids:
            page = pdf[i]
            w = page.get_width() or 1
            img = page.render(scale=max_w / w).to_pil().convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82)
            out.append(buf.getvalue())
            if on_page is not None:
                on_page(len(out), len(page_ids))
    finally:
        pdf.close()
    return out


def _page_scores(text: str) -> dict[str, float]:
    """Что полезного для чтения брендбука на странице: цвета (HEX, RGB, CMYK), названия шрифтов, правила, место логотипа,
    поля и сетка. Обложка, оглавление и колонтитулы набирают ноль: слова «цвет», «шрифт» и «логотип» в них не считаются."""
    sents = sentences(text)
    colours = sum(len(_mentions(ln.strip())) for ln in text.splitlines())
    fonts = len(pdf_fonts(text)[0])
    rules = sum(1 for sn in sents if looks_like_rule(sn) and not (_HEX.search(sn) or _RGB.search(sn)))
    layout = (any(logo_place(sn) for sn in sents) + any(margins_px(sn) for sn in sents) + bool(find_grid("\n".join(paragraphs(text)))))
    return {"colour": min(colours, 8), "font": min(fonts, 4), "rules": min(rules, 6), "layout": layout}


def _vlm_pages(page_texts: list[str]) -> list[int]:
    """До шести страниц для модели: по лучшей странице каждой темы (цвета, шрифты, место логотипа и сетка, правила), остальные
    места — по сумме баллов. Оглавление и обложка без цветов, шрифтов и правил не попадают. Скан без текста — шесть страниц
    поровну по документу (без обложки)."""
    n = len(page_texts)
    if n <= _VLM_PAGES:
        return list(range(n))
    scores = [_page_scores(t) for t in page_texts]
    total = [2 * sc["colour"] + 3 * sc["font"] + 1.5 * sc["rules"] + 2.5 * sc["layout"] for sc in scores]
    if not any(total):
        step = (n - 1) / _VLM_PAGES
        return sorted({min(n - 1, 1 + round(k * step)) for k in range(_VLM_PAGES)})
    picked: list[int] = []
    for topic in ("colour", "font", "layout", "rules"):
        best = max(range(n), key=lambda i: (scores[i][topic], -i))
        if scores[best][topic] > 0 and best not in picked:
            picked.append(best)
    for i in sorted(range(n), key=lambda i: (-total[i], i)):
        if len(picked) >= _VLM_PAGES:
            break
        if total[i] > 0 and i not in picked:
            picked.append(i)
    return sorted(picked)


def _ask_model(path: Path, page_texts: list[str], draft: BrandSpec, providers, skills,
               on_progress: Optional[Callable[[str, str], None]] = None) -> BrandbookReading:
    """Страницы → навык `brandbook_reader` одним запросом. `on_progress(что, итог)` — ход: «страница 3 из 6» по мере подготовки
    страниц и «модель читает …» перед запросом, который длится до двух минут."""
    import json

    pages = _vlm_pages(page_texts)
    say = on_progress or (lambda what, result: None)
    images = _page_images(path, pages, on_page=lambda k, m: say("страница", f"{k} из {m}"))
    say("модель", f"читает {ru_count(len(pages), 'страницу', 'страницы', 'страниц')}")
    draft_json = json.dumps(
        {"name": draft.name, "colors": [c.model_dump() for c in draft.colors], "fonts": [f.model_dump() for f in draft.fonts],
         "logo_place": draft.logo_place, "margins_px": draft.margins_px, "rules": [r.text for r in draft.rules]},
        ensure_ascii=False,
    )
    res = skills.run("brandbook_reader", providers, {"pages": [i + 1 for i in pages], "n_pages": len(page_texts), "draft_json": draft_json}, images=images)
    reading = res.parsed
    if not isinstance(reading, BrandbookReading):
        raise ValueError("модель вернула не разбор брендбука")
    return reading


def _merge_reading(spec: BrandSpec, r: BrandbookReading, scanned: bool, name_trusted: bool = True) -> list[str]:
    """Уточнения модели поверх чтения по тексту; модель не добавляет цветов, которых нет в тексте (кроме скана). Имя модели
    важнее имени, угаданного по имени файла или первой строке; имя из заголовка документа остаётся."""
    notes: list[str] = []
    if scanned and r.colors:
        hits = [ColorHit(c.hex, c.role, c.name) for c in r.colors]
        notes.append("Цвета прочитаны моделью по картинкам страниц (в PDF нет текста) — проверьте HEX.")
    else:
        hits = []
        for c in spec.colors:
            m = next((x for x in r.colors if x.hex == c.hex), None)
            hits.append(ColorHit(c.hex, m.role if m else c.role, c.name or (m.name if m else None)))
    if hits:
        spec.colors, w = make_palette(hits)
        notes += w
    if r.fonts and {f.role for f in r.fonts} >= {"heading"}:
        fb = next((f.fallback for f in spec.fonts if f.fallback), None)
        fonts, _ = make_fonts([FontHit(f.family, f.role, f.weight, f.fallback) for f in r.fonts], fallback=fb)
        if fonts:
            spec.fonts = fonts
    if not spec.logo_place and r.logo_place:
        spec.logo_place = r.logo_place
        add_rule(spec.rules, f"Логотип — {PLACE_TEXT[r.logo_place]}", "logo", limit=_MAX_RULES)
    if not spec.margins_px and r.margins_px and 0 < r.margins_px <= 400:
        spec.margins_px = float(r.margins_px)
    if r.name and (not spec.name or not name_trusted):
        spec.name = brand_name(r.name) or spec.name
    for rule in r.rules:
        add_rule(spec.rules, rule.text, rule.kind, limit=_MAX_RULES)
    return notes


# ---- чтение -------------------------------------------------------------------------------------------------------------------
# заголовок документа, который программа поставила сама («rgb_only.html», «Microsoft Word - Документ1»), — не имя бренда
_FILE_TITLE = re.compile(
    r"\.(?:html?|docx?|pptx?|xlsx?|indd|idml|ai|psd|pdf|key|pages|odt|rtf|md|txt|fig|sketch|tmp)\s*$|"
    r"^(?:untitled|без\s+названия|безымянн\w*|документ\s*\d*|document\s*\d*|microsoft\s+(?:word|powerpoint|excel)\b.*|"
    r"powerpoint\s+presentation|слайд\s*\d*|copy\s+of\b.*|new\s+document|новый\s+документ)\s*$",
    re.I,
)


def _guess_name(title: Any, page_texts: list[str], stem: str) -> tuple[Optional[str], bool]:
    """Имя бренда и уверенность в нём: заголовок документа (если это не имя файла и не служебная строка) и заголовок первой
    страницы («Брендбук VK Cloud») — надёжны; имя файла и первая строка — догадка, и модель вправе их заменить."""
    key = lambda x: re.sub(r"[\s_\-]+", "", str(x).lower())  # noqa: E731
    t = str(title or "").strip()
    if t and not _FILE_TITLE.search(t) and key(t) != key(stem):
        name = brand_name(t)
        if name:
            return name, True
    first_page = page_texts[0] if page_texts else ""
    lines = [ln.strip() for ln in first_page.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if re.search(r"брендбук|brand\s*book|guideline|гайдлайн|руководство", ln, re.I):
            # заголовок часто переносится: «Руководство по фирменному стилю» / ««Нева Банк»»
            name = brand_name(ln) or (brand_name(f"{ln} {lines[i + 1]}") if i + 1 < len(lines) else None)
            if name:
                return name, True
    first_line = next((ln for ln in lines if len(ln) > 2), "")
    return name_from_path(stem) or brand_name(first_line), False


def read_pdf(path: Path | str, *, providers: Any = None, skills: Any = None, use_vlm: bool = False,
             assets_dir: Optional[Path | str] = None, on_step: Any = None,
             on_progress: Optional[Callable[[str, str], None]] = None) -> BrandSpec:
    """PDF-гайдлайн → `BrandSpec` (по тексту; с `use_vlm` — ещё и по картинкам страниц).

    `on_step` — ход чтения для интерфейса (см. `StepReporter`): «открыт файл», «палитра», «шрифты», «логотипы», «правила» — каждый
    сразу, как этап по тексту готов, а не после запроса к модели; затем «страница N из M» и «модель читает …»; шаги, которые
    модель изменила (роли цветов, правила), повторяются с новым итогом. `on_progress(что, итог)` — только ход («страница»,
    «модель»), без шагов: так читает PDF внутри папки, где шаги говорит сама папка."""
    path = Path(path)
    if path.stat().st_size == 0:
        raise BrandReadError(f"Файл «{path.name}» пустой.")
    rep = as_reporter(on_step)
    progress = on_progress or (rep.progress if rep.cb is not None else None)
    reader = _open(path)
    page_texts = _page_texts(reader)
    text = "\n".join(page_texts)
    can_vlm = bool(use_vlm and providers is not None and getattr(providers, "has", lambda r: False)("vlm"))
    scanned = not text.strip()
    if scanned and not can_vlm:
        raise BrandReadError(
            f"В PDF «{path.name}» нет текста — похоже, это скан или картинки. Без модели такой гайдлайн не прочитать: "
            "включите чтение моделью или загрузите токены JSON."
        )
    title = None
    try:
        title = (reader.metadata or {}).get("/Title")
    except Exception:  # noqa: BLE001
        title = None
    name, name_trusted = _guess_name(title, page_texts, path.stem)
    rep.step("open", *open_text("pdf", path.name, len(page_texts)), {"name": name or "", "source": "pdf", "file": path.name, "pages": len(page_texts)})

    colors, w1 = make_palette(pdf_colors(text))
    rep.step("palette", "палитра", palette_result(colors), {"colors": [c.model_dump(mode="json") for c in colors]})
    font_hits, fallback = pdf_fonts(text, name)
    fonts, w2 = make_fonts(font_hits, fallback=fallback)
    rep.step("fonts", "шрифты", fonts_result(fonts), {"fonts": [f.model_dump(mode="json") for f in fonts]})
    logos: list[BrandLogo] = []
    logo_warnings: list[str] = []
    if assets_dir is not None:
        try:
            logos = pdf_logos(reader, page_texts, Path(assets_dir))
        except OSError as e:
            logo_warnings.append(f"Логотипы из PDF не сохранились: {e}.")
    rep.step("logos", "логотипы", logos_result(logos), {"logos": [lg.model_dump(mode="json") for lg in logos]})
    rules, margin, grid, place = pdf_rules(text)
    warnings = w1 + w2 + logo_warnings
    rep.step("rules", "правила", rules_result(rules),
             {"rules": [r.model_dump(mode="json") for r in rules], "margins_px": margin, "grid": grid, "logo_place": place, "warnings": list(warnings)})
    spec = BrandSpec(
        name=name or "",
        source="pdf",
        file=path.name,
        pages=len(page_texts),
        colors=colors,
        fonts=fonts,
        logos=logos,
        margins_px=margin,
        grid=grid,
        rules=rules,
        logo_place=place,
        warnings=warnings,
    )
    if can_vlm:
        if skills is None:
            from verstka.skills_registry import SkillsRegistry

            skills = SkillsRegistry.load()
        try:
            reading = _ask_model(path, page_texts, spec, providers, skills, progress)
            spec.warnings += [w for w in _merge_reading(spec, reading, scanned, name_trusted) if w not in spec.warnings]
        except Exception as e:  # noqa: BLE001 — модель необязательна: при любой её ошибке остаётся чтение по тексту
            log.warning("brandbook_reader failed: %s", e)
            if scanned:
                raise BrandReadError(f"В PDF «{path.name}» нет текста, а модель не смогла прочитать страницы — загрузите токены JSON.") from None
            spec.warnings.append("Модель не смогла прочитать страницы — оставил чтение по тексту.")
    elif use_vlm:
        spec.warnings.append("Модель для картинок не подключена — PDF прочитан по тексту.")
    if not spec.colors:
        if re.search(r"pantone|(?<![A-Za-z])RAL\b|(?<![A-Za-z])NCS\b", text, re.I):
            spec.warnings.append("Цвета в PDF заданы только по Pantone (или RAL) — без HEX, RGB или CMYK я не могу их перевести в цвета экрана: "
                                 "палитра останется из шаблона. Пришлите HEX или токены JSON.")
        else:
            spec.warnings.append("В PDF не нашёл цветов (HEX, RGB или CMYK) — палитра останется из шаблона.")
    if not spec.fonts:
        spec.warnings.append("В PDF не нашёл названий шрифтов — шрифты останутся из шаблона.")
    rep.refresh(spec)  # модель уточнила роли, правила и предупреждения: повторяются только изменившиеся шаги
    return spec


__all__ = ["BrandbookReading", "read_pdf", "pdf_colors", "pdf_fonts", "pdf_rules", "paragraphs", "sentences", "logo_variant"]
