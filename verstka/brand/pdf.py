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
from typing import Any, Optional

from pydantic import BaseModel, Field

from verstka.brand.common import (
    PLACE_TEXT,
    BrandReadError,
    ColorHit,
    FontHit,
    add_rule,
    brand_name,
    cmyk_hex,
    color_role,
    find_grid,
    font_role,
    is_negative,
    logo_place,
    looks_like_rule,
    make_fonts,
    make_palette,
    margins_px,
    name_from_path,
    rgb_hex,
    split_weight,
    weight_of,
)
from verstka.schemas.brand import BrandColor, BrandFont, BrandLogo, BrandRule, BrandSpec, LogoPlace

log = logging.getLogger(__name__)

_HEX = re.compile(r"(?<![0-9A-Za-z&])#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z])")
_SEP = r"[\s,;/·|:]+"
_RGB = re.compile(r"(?<![A-Za-z])RGB" + r"[\s:(]*(\d{1,3})" + _SEP + r"(\d{1,3})" + _SEP + r"(\d{1,3})", re.I)
_CMYK = re.compile(r"(?<![A-Za-z])CMYK" + r"[\s:(]*(\d{1,3})%?" + (_SEP + r"(\d{1,3})%?") * 3, re.I)

_FONT_HINT = re.compile(r"(?<![A-Za-z])(Sans|Serif|Display|Text|Grotesk|Grotesque|Mono|Gothic|Neue|Slab|Condensed|Rounded|Headline)(?![A-Za-z])")
_KNOWN_FONTS = {
    "play", "roboto", "inter", "arial", "helvetica", "montserrat", "open sans", "pt sans", "pt serif", "pt root ui", "golos",
    "manrope", "onest", "lato", "noto", "calibri", "cambria", "georgia", "verdana", "tahoma", "segoe ui", "ibm plex", "fira",
    "ubuntu", "raleway", "nunito", "rubik", "exo", "oswald", "merriweather", "lora", "unbounded", "jost", "futura", "gotham",
    "proxima nova", "gilroy", "circe", "tt norms", "times new roman", "source sans", "sf pro", "yandex sans", "aptos",
    "bebas neue", "trebuchet ms", "century gothic", "franklin gothic", "museo", "graphik", "suisse", "akzidenz", "din",
    "stem", "geometria", "helios", "comfortaa", "playfair", "spectral", "literata", "jetbrains mono", "source code",
}
_NOT_FONTS = {"hex", "rgb", "cmyk", "pdf", "png", "svg", "json", "pptx", "figma", "verstka", "google", "microsoft", "powerpoint",
              "keynote", "pantone", "tokens studio", "w3c", "w3c design tokens", "design tokens", "vk", "ral", "url"}
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
def _mentions(line: str) -> list[tuple[int, int, str]]:
    """Цвета в строке: (начало, конец, HEX). RGB и CMYK — только если в строке нет HEX (это тот же цвет)."""
    found = [(m.start(), m.end(), "#" + m.group(1)) for m in _HEX.finditer(line)]
    if found:
        return found
    for m in _RGB.finditer(line):
        vals = [int(v) for v in m.groups()]
        if all(v <= 255 for v in vals):
            found.append((m.start(), m.end(), rgb_hex(*vals)))
    if found:
        return found
    for m in _CMYK.finditer(line):
        vals = [int(v) for v in m.groups()]
        if all(v <= 100 for v in vals):
            found.append((m.start(), m.end(), cmyk_hex(*vals)))
    return found


def _name_near(segment: str) -> Optional[str]:
    """Имя цвета в ячейке перед HEX: «Основной VK Blue » → «VK Blue»."""
    seg = re.sub(r"[·|:—–,]", " ", segment)
    m = list(re.finditer(r"([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,2})", seg))
    if m:
        cand = m[-1].group(1).strip()
        if cand.upper() not in ("HEX", "RGB", "CMYK") and len(cand) >= 3:
            return cand
    return None


def pdf_colors(text: str) -> list[ColorHit]:
    """Цвета гайдлайна с ролями по голосам (см. описание модуля)."""
    lines = [ln.strip() for ln in text.splitlines()]
    per_line = [_mentions(ln) for ln in lines]
    votes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    names: dict[str, str] = {}
    order: list[str] = []
    positive: set[str] = set()
    for i, ln in enumerate(lines):
        ms = per_line[i]
        if not ms:
            continue
        neg = is_negative(ln)
        for j, (a, b, hx) in enumerate(ms):
            hx = hx.upper() if len(hx) == 7 else "#" + "".join(c * 2 for c in hx[1:]).upper()
            if hx not in order:
                order.append(hx)
            if neg:
                continue
            positive.add(hx)
            before = ln[ms[j - 1][1] if j else 0: a]
            after = ln[b: ms[j + 1][0] if j + 1 < len(ms) else len(ln)]
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
                    for k, w in ((i - 1, 1.0), (i - 2, 0.75), (i + 1, 0.75)):
                        if 0 <= k < len(lines) and not per_line[k]:
                            r = color_role(lines[k])
                            if r:
                                votes[hx][r] += w
                                break
            nm = _name_near(before)
            if not nm and single:
                # карточка: имя — одной из двух строк выше («VK Blue» / «Основной» / «#0077FF»), подпись роли пропускается
                for k in (i - 1, i - 2):
                    if k < 0 or per_line[k]:
                        break
                    if len(lines[k]) <= 24 and not color_role(lines[k]):
                        nm = _name_near(lines[k])
                        if nm:
                            break
            if nm and hx not in names:
                names[hx] = nm
    hits: list[ColorHit] = []
    for hx in order:
        if hx not in positive:
            continue
        v = votes.get(hx) or {}
        role = None
        if v:
            best = max(v.values())
            tops = [r for r in v if v[r] == best]
            role = next((r for r in tops if r != "chart"), tops[0])
        hits.append(ColorHit(hx, role, names.get(hx)))  # type: ignore[arg-type]
    return hits


# ---- шрифты -----------------------------------------------------------------------------------------------------------------
def _plausible_font(family: str, line: str, brand: Optional[str]) -> bool:
    low = family.lower()
    if low in _NOT_FONTS or (brand and low == brand.lower()) or len(family) < 3:
        return False
    if _FONT_HINT.search(family):
        return True
    if low in _KNOWN_FONTS or any(low.startswith(k + " ") for k in _KNOWN_FONTS):
        return True
    return bool(_FONT_WORD.search(line)) and len(family.split()) >= 2


def pdf_fonts(text: str, brand: Optional[str] = None) -> tuple[list[FontHit], Optional[str]]:
    """Шрифты гайдлайна и общая замена («Play»): роль — по ближайшему к названию слову («для заголовков», «Основной текст —»)."""
    hits: list[FontHit] = []
    fallback: Optional[str] = None
    for line in (ln.strip() for ln in text.splitlines()):
        if not line or _HEX.search(line) or is_negative(line):
            continue
        phrases = []
        for m in _FONT_PHRASE.finditer(line):
            fam, w = split_weight(m.group(1))
            if _plausible_font(fam, line, brand):
                phrases.append((m.start(), m.start() + len(fam), fam, w, m.end()))
        if not phrases:
            continue
        fb = _FALLBACK_AT.search(line)
        if fb:
            after = [p for p in phrases if p[0] >= fb.end()]
            if after and not fallback:
                fallback = after[0][2]
            phrases = [p for p in phrases if p[0] < fb.start()]
        for k, (a, b, fam, w, end) in enumerate(phrases):
            lo = phrases[k - 1][4] if k else 0
            hi = phrases[k + 1][0] if k + 1 < len(phrases) else len(line)
            role = _nearest_font_role(line[lo:a], line[end:hi])
            tail = line[end:hi]
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


def _nearest_font_role(before: str, after: str):
    """Роль шрифта: слово-роль перед названием («Заголовки — VK Sans Display», «основной текст — Golos Text») или
    «для …» после него («VK Sans Display для заголовков»). «Для заголовков» перед названием относится к предыдущему шрифту."""
    own = [m for m in _ROLE_WORD.finditer(before) if not m.group(1)]
    if own:
        return font_role(own[-1].group(2))
    m = next((m for m in _ROLE_WORD.finditer(after) if m.group(1)), None)
    if m:
        return font_role(m.group(2))
    return None


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
            if pil is None or min(pil.size) < 16 or pil.size[0] / max(pil.size[1], 1) > 12:
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
def _page_images(path: Path, page_ids: list[int], max_w: int = 1024) -> list[bytes]:
    import pypdfium2 as pdfium

    out: list[bytes] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in page_ids:
            page = pdf[i]
            w = page.get_width() or 1
            img = page.render(scale=max_w / w).to_pil().convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            out.append(buf.getvalue())
    finally:
        pdf.close()
    return out


def _vlm_pages(page_texts: list[str]) -> list[int]:
    want = re.compile(r"#[0-9A-Fa-f]{6}|RGB|CMYK|палитр|цвет|colou?r|шрифт|font|typeface|логотип|logo|правил|нельзя|rules", re.I)
    picked = [i for i, t in enumerate(page_texts) if want.search(t)]
    if not picked:
        picked = list(range(len(page_texts)))
    return picked[:_VLM_PAGES]


def _ask_model(path: Path, page_texts: list[str], draft: BrandSpec, providers, skills) -> BrandbookReading:
    import json

    pages = _vlm_pages(page_texts)
    images = _page_images(path, pages)
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


def _merge_reading(spec: BrandSpec, r: BrandbookReading, scanned: bool) -> list[str]:
    """Уточнения модели поверх чтения по тексту; модель не добавляет цветов, которых нет в тексте (кроме скана)."""
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
    if not spec.name and r.name:
        spec.name = brand_name(r.name) or ""
    for rule in r.rules:
        add_rule(spec.rules, rule.text, rule.kind, limit=_MAX_RULES)
    return notes


# ---- чтение -------------------------------------------------------------------------------------------------------------------
def read_pdf(path: Path | str, *, providers: Any = None, skills: Any = None, use_vlm: bool = False,
             assets_dir: Optional[Path | str] = None) -> BrandSpec:
    """PDF-гайдлайн → `BrandSpec` (по тексту; с `use_vlm` — ещё и по картинкам страниц)."""
    path = Path(path)
    if path.stat().st_size == 0:
        raise BrandReadError(f"Файл «{path.name}» пустой.")
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
    first_line = next((ln.strip() for ln in page_texts[0].splitlines() if len(ln.strip()) > 2), "") if page_texts else ""
    name = brand_name(str(title)) if title else None
    if not name:
        cand = next((ln.strip() for ln in page_texts[0].splitlines() if re.search(r"брендбук|brand\s*book|guideline|гайдлайн|руководство", ln, re.I)), "") if page_texts else ""
        name = brand_name(cand) or name_from_path(path.stem) or brand_name(first_line)

    colors, w1 = make_palette(pdf_colors(text))
    font_hits, fallback = pdf_fonts(text, name)
    fonts, w2 = make_fonts(font_hits, fallback=fallback)
    rules, margin, grid, place = pdf_rules(text)
    warnings = w1 + w2
    spec = BrandSpec(
        name=name or "",
        source="pdf",
        file=path.name,
        pages=len(page_texts),
        colors=colors,
        fonts=fonts,
        margins_px=margin,
        grid=grid,
        rules=rules,
        logo_place=place,
        warnings=warnings,
    )
    if assets_dir is not None:
        try:
            spec.logos = pdf_logos(reader, page_texts, Path(assets_dir))
        except OSError as e:
            spec.warnings.append(f"Логотипы из PDF не сохранились: {e}.")
    if can_vlm:
        if skills is None:
            from verstka.skills_registry import SkillsRegistry

            skills = SkillsRegistry.load()
        try:
            reading = _ask_model(path, page_texts, spec, providers, skills)
            spec.warnings += _merge_reading(spec, reading, scanned)
        except Exception as e:  # noqa: BLE001 — модель необязательна: при любой её ошибке остаётся чтение по тексту
            log.warning("brandbook_reader failed: %s", e)
            if scanned:
                raise BrandReadError(f"В PDF «{path.name}» нет текста, а модель не смогла прочитать страницы — загрузите токены JSON.") from None
            spec.warnings.append("Модель не смогла прочитать страницы — оставил чтение по тексту.")
    elif use_vlm:
        spec.warnings.append("Модель для картинок не подключена — PDF прочитан по тексту.")
    if not spec.colors:
        spec.warnings.append("В PDF не нашёл цветов (HEX, RGB или CMYK) — палитра останется из шаблона.")
    if not spec.fonts:
        spec.warnings.append("В PDF не нашёл названий шрифтов — шрифты останутся из шаблона.")
    return spec


__all__ = ["BrandbookReading", "read_pdf", "pdf_colors", "pdf_fonts", "pdf_rules", "paragraphs", "sentences", "logo_variant"]
