"""«Улучшить презентацию» (Verstka 3.0): a finished deck read back as the author's text — the second way in the
organisers named («есть старая презентация — нужна улучшенная/обновлённая»).

Every slide becomes a «Слайд N. Заголовок» section of a brief: its title, its text in reading order (a list stays a
list), its tables as markdown, its charts as a chart note with their data («[Столбчатая диаграмма: выручка, млн ₽ —
2023: 1,2; 2024: 2,5]», read by planning/faithful.py like any author's note), its pictures as a place for the picture
(«[Место под изображение: Изображение со слайда 3 исходной презентации]») whose file is kept, so the improved deck
shows the original picture there (images/fill.py reuses it by its description, no picture is generated). What every
slide repeats — a footer, the company name, the page number, a logo — is the template's, not the author's: left out.
The deck itself becomes the template, so the improved deck keeps its look; the deterministic audit of the original
tells «было → стало».
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

SOURCE_IMAGES = "source_images.json"  # in the template's workspace: {hint: file name in source_images/}
_PICTURE_HINT = "Изображение со слайда {n} исходной презентации"
_MIN_PICTURE_AREA = 0.06  # a smaller picture is an icon or a logo
_CHART_RU = {
    "pie": "Круговая диаграмма", "doughnut": "Кольцевая диаграмма", "bar": "Горизонтальная диаграмма", "line": "Линейная диаграмма",
    "area": "Диаграмма с областями", "column": "Столбчатая диаграмма",
}


@dataclass
class DeckText:
    brief: str
    title: str = ""
    slides: int = 0
    tables: int = 0
    charts: int = 0
    pictures: list[tuple[str, bytes, str]] = field(default_factory=list)  # (hint, image bytes, extension)

    def summary(self) -> dict:
        return {"title": self.title, "slides": self.slides, "tables": self.tables, "charts": self.charts, "pictures": len(self.pictures)}


def _norm(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _clean(text: str) -> str:
    return " ".join((text or "").replace("\v", " ").replace("\u000b", " ").split()).strip()


def _flat(shapes: Any, offset: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)) -> list[tuple[Any, float, float, float, float]]:
    """(shape, x, y, w, h) of every shape in slide coordinates, groups opened."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    ox, oy, kx, ky = offset
    out = []
    for sh in shapes:
        try:
            x, y, w, h = (float(v or 0) for v in (sh.left, sh.top, sh.width, sh.height))
        except Exception:  # noqa: BLE001 - a shape without a position (a broken one) is read where it lies
            x = y = w = h = 0.0
        ax, ay, aw, ah = ox + x * kx, oy + y * ky, w * kx, h * ky
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            try:
                xfrm = sh._element.grpSpPr.xfrm
                ch_off, ch_ext = xfrm.chOff, xfrm.chExt
                gkx = (aw / ch_ext.cx) if ch_ext is not None and ch_ext.cx else kx
                gky = (ah / ch_ext.cy) if ch_ext is not None and ch_ext.cy else ky
                gx = ax - (ch_off.x if ch_off is not None else 0) * gkx
                gy = ay - (ch_off.y if ch_off is not None else 0) * gky
                out.extend(_flat(sh.shapes, (gx, gy, gkx, gky)))
            except Exception:  # noqa: BLE001 - a group read flat
                out.extend(_flat(sh.shapes, offset))
            continue
        out.append((sh, ax, ay, aw, ah))
    return out


def _placeholder_kind(sh: Any) -> Optional[str]:
    if not getattr(sh, "is_placeholder", False):
        return None
    try:
        t = sh.placeholder_format.type
    except Exception:  # noqa: BLE001
        return None
    name = str(t).split(".")[-1].split(" ")[0].upper()
    if name in ("TITLE", "CENTER_TITLE", "VERTICAL_TITLE"):
        return "title"
    if name in ("SUBTITLE",):
        return "subtitle"
    if name in ("DATE", "FOOTER", "SLIDE_NUMBER", "HEADER"):
        return "chrome"
    return "body"


_MONO_RE = re.compile(r"courier|consolas|menlo|monaco|mono|source code|fira code|jetbrains", re.I)
_CODE_LINE_RE = re.compile(r"^\s*(?:[{}\[\]]|\"[^\"]+\"\s*:|(?:def|class|return|import|from|if|for|while|var|let|const|function)\b|[\w.]+\s*\(.*\)\s*[:;{]?$|.*[;{]\s*$)")
# a figure alone: «300 ₽», «25,4 °C», «12 400», «+34%», «2,1 часа»
_FIGURE_RE = re.compile(r"^[+\-−]?\d[\d\s\u00a0\u202f.,]*(?:\s*(?:%|₽|\$|€|°C|°|руб\.?|рублей|тыс\.?|млн|млрд|ч|час[а-я]*|мин|сек|кг|км|м²|м|л|шт\.?|x|×|раз[а]?)){0,2}$", re.I)
_OPERATOR_RE = re.compile(r"^[×x*+=→←↑↓–—\-/:]{1,2}$")


def _paragraphs(sh: Any) -> list[tuple[int, str]]:
    """The box's paragraphs as (level, text); a paragraph that only continues the line before it (a label the layout
    wrapped: «Продукты, упаковка» / «и списания») is joined to it."""
    out: list[tuple[int, str]] = []
    for p in sh.text_frame.paragraphs:
        t = _clean(p.text)
        if not t:
            continue
        if out and t[:1].islower() and not out[-1][1].endswith((".", "!", "?", ":", ";")) and int(p.level or 0) == out[-1][0]:
            out[-1] = (out[-1][0], f"{out[-1][1]} {t}")
            continue
        out.append((int(p.level or 0), t))
    return out


def _max_size(sh: Any) -> float:
    """The largest font size set in the box, in points (12 when none is set: the inherited body size)."""
    sizes = [r.font.size.pt for p in sh.text_frame.paragraphs for r in p.runs if r.font is not None and r.font.size is not None]
    return max(sizes) if sizes else 12.0


def _is_code(sh: Any, paras: list[tuple[int, str]]) -> bool:
    fonts = {r.font.name for p in sh.text_frame.paragraphs for r in p.runs if r.font is not None and r.font.name}
    if any(_MONO_RE.search(f) for f in fonts):
        return True
    lines = [t for _, t in paras]
    return len(lines) >= 3 and sum(1 for ln in lines if _CODE_LINE_RE.match(ln)) >= 0.6 * len(lines)


def _code_text(sh: Any) -> str:
    raw = "\n".join(p.text.replace("\v", "\n") for p in sh.text_frame.paragraphs).strip("\n")
    return f"```\n{raw}\n```"


def _md_table(rows: list[list[str]]) -> str:
    rows = [[_clean(c).replace("|", "/") for c in r] for r in rows if any(_clean(c) for c in r)]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _figure(v: Any) -> str:
    if v is None:
        return ""
    f = float(v)
    s = f"{f:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return s.replace(".", ",")


def _chart_note(chart: Any) -> Optional[str]:
    """A chart as a chart note with its data, or None when it has none."""
    try:
        plot = chart.plots[0]
        cats = [_clean(str(c)) for c in plot.categories]
        series = [(s.name or "", list(s.values)) for s in plot.series]
    except Exception:  # noqa: BLE001 - a chart that python-pptx cannot read keeps only its title
        return None
    if not cats or not series:
        return None
    t = str(chart.chart_type).split(".")[-1].split(" ")[0].upper()
    kind = "pie" if "PIE" in t else "doughnut" if "DOUGHNUT" in t else "bar" if t.startswith("BAR") else "line" if "LINE" in t else "area" if "AREA" in t else "column"
    title = ""
    try:
        if chart.has_title:
            title = _clean(chart.chart_title.text_frame.text)
    except Exception:  # noqa: BLE001
        title = ""
    what = title or (_clean(series[0][0]) if len(series) == 1 else "данные слайда")
    if len(series) == 1:
        items = "; ".join(f"{c}: {_figure(v)}" for c, v in zip(cats, series[0][1]) if v is not None)
    else:
        names = " и ".join(_clean(n) or f"ряд {k}" for k, (n, _) in enumerate(series[:2], 1))
        what = f"{what} ({names})"
        items = "; ".join(f"{c}: {' и '.join(_figure(s[1][i]) for s in series[:2] if i < len(s[1]) and s[1][i] is not None)}" for i, c in enumerate(cats))
    return f"[{_CHART_RU[kind]}: {what} — {items}]"


def _plain_panel(blob: bytes) -> bool:
    """A picture that shows nothing: one flat colour (a card's ground, a rounded panel drawn as a PNG) or mostly
    transparent — decoration of the template, never a picture the author put on the slide."""
    try:
        import io

        from PIL import Image, ImageStat

        with Image.open(io.BytesIO(blob)) as im:
            im.thumbnail((64, 64))
            rgba = im.convert("RGBA")
            alpha = ImageStat.Stat(rgba.getchannel("A")).mean[0]
            if alpha < 40:
                return True
            return max(ImageStat.Stat(rgba.convert("RGB")).stddev) < 6.0
    except Exception:  # noqa: BLE001 - a picture PIL cannot read (EMF, SVG) is kept
        return False


def deck_text(pptx: Path | str) -> DeckText:
    """The deck as a «Слайд N» brief (see the module's doc)."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(pptx))
    W, H = float(prs.slide_width or 1), float(prs.slide_height or 1)
    slides = list(prs.slides)
    # what the slides repeat: texts and pictures on two or more slides out of three or more are the template's chrome
    seen_text: Counter = Counter()
    seen_pic: Counter = Counter()
    for s in slides:
        texts, pics = set(), set()
        for sh, *_ in _flat(s.shapes):
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame and _placeholder_kind(sh) not in ("title",):
                t = _norm(sh.text_frame.text)
                if t and len(t) <= 120:
                    texts.add(t)
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    pics.add(hashlib.sha1(sh.image.blob).hexdigest())
                except Exception:  # noqa: BLE001
                    pass
        seen_text.update(texts)
        seen_pic.update(pics)
    repeat = max(2, int(0.4 * len(slides) + 0.5)) if len(slides) >= 3 else 10**6
    out = DeckText(brief="", slides=len(slides))
    sections: list[str] = []
    for n, s in enumerate(slides, 1):
        title, subtitle = "", []
        parts: list[tuple[float, float, str]] = []
        for sh, x, y, w, h in _flat(s.shapes):
            kind = _placeholder_kind(sh)
            if kind == "chrome":
                continue
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                paras = _paragraphs(sh)
                if not paras:
                    continue
                joined = " ".join(t for _, t in paras)
                if kind == "title" and not title:
                    title = joined
                    continue
                page_no = re.fullmatch(r"\d{1,3}", joined) and h < 0.08 * H and (y < 0.1 * H or y + h > 0.88 * H) and _max_size(sh) <= 16
                if seen_text[_norm(sh.text_frame.text)] >= repeat or page_no or _OPERATOR_RE.match(joined):
                    continue  # a footer, the company's name, a page number (small, at an edge), the «×» of a formula's tiles
                if kind == "subtitle":
                    subtitle.append(joined)
                    continue
                if _is_code(sh, paras):
                    parts.append((y, x, _code_text(sh), w, h))
                elif len(paras) == 1:
                    parts.append((y, x, paras[0][1], w, h))
                else:
                    parts.append((y, x, "\n".join(("  " * lv) + "- " + t for lv, t in paras), w, h))
            elif getattr(sh, "has_table", False) and sh.has_table:
                md = _md_table([[c.text for c in r.cells] for r in sh.table.rows])
                if md:
                    parts.append((y, x, md, w, h))
                    out.tables += 1
            elif getattr(sh, "has_chart", False) and sh.has_chart:
                note = _chart_note(sh.chart)
                if note:
                    parts.append((y, x, note, w, h))
                    out.charts += 1
            elif sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                if w * h < _MIN_PICTURE_AREA * W * H or w * h > 0.92 * W * H:
                    continue  # an icon, a logo — or the slide's background art
                try:
                    blob, ext = sh.image.blob, sh.image.ext
                except Exception:  # noqa: BLE001 - a linked picture without its bytes
                    continue
                if seen_pic[hashlib.sha1(blob).hexdigest()] >= repeat or _plain_panel(blob):
                    continue  # a logo on every slide, or a flat panel of the template (a card's ground drawn as a picture)
                hint = _PICTURE_HINT.format(n=n) + (f" ({len([p for p in out.pictures if p[0].startswith(_PICTURE_HINT.format(n=n))]) + 1})" if any(p[0].startswith(_PICTURE_HINT.format(n=n)) for p in out.pictures) else "")
                out.pictures.append((hint, blob, ext or "png"))
                parts.append((y, x, f"[Место под изображение: {hint}]", w, h))
        heading = [p for p in parts if p[0] < 0.4 * H and "\n" not in p[2] and not p[2].startswith(("[", "|", "`")) and 3 <= len(p[2].split()) <= 16 and not _FIGURE_RE.match(p[2])]
        if title and len(title.split()) <= 2 and title.upper() == title and heading:
            # the title placeholder holds a kicker («ГЛАВНОЕ», «ПЛАН»): the slide's heading is the line under it
            title = ""
        if not title:
            # no title: the first short line high on the slide
            cand = sorted(heading or [p for p in parts if p[0] < 0.35 * H and "\n" not in p[2] and not p[2].startswith(("[", "|", "`")) and len(p[2].split()) <= 14], key=lambda p: (p[0], p[1]))
            if cand:
                title = cand[0][2]
                parts.remove(cand[0])
        parts = _paired(parts, W, H)
        parts.sort(key=lambda p: (round(p[0] / (0.04 * H)), p[1]))
        body = [*subtitle, *(p[2] for p in parts)]
        if not title and not body:
            continue
        if n == 1 and title:
            out.title = title
        sections.append("\n\n".join([f"Слайд {n}. {title}".rstrip(". ").rstrip() if title else f"Слайд {n}.", *body]))
    out.brief = "\n\n".join(sections).strip() + "\n"
    return out


def _paired(parts: list[tuple], W: float, H: float) -> list[tuple]:
    """A figure alone in its box over (or under) a short label in the box next to it — a KPI tile — is one line: «Средний
    чек — 300 ₽»; read apart, the deck's figures lost what they measure."""
    out = list(parts)
    used: set[int] = set()
    joined: list[tuple] = []
    for i, a in enumerate(out):
        if i in used or not _FIGURE_RE.match(a[2]):
            continue
        ay, ax, _, aw, ah = a
        best, gap = None, None
        # a label is a few words without figures of its own, in the figure's column: under it first (a KPI tile sets
        # the figure over its label), above it only when nothing is under it — never a sentence that carries figures
        for below in (True, False):
            for j, b in enumerate(out):
                if j == i or j in used or "\n" in b[2] or b[2].startswith(("[", "|", "`")) or len(b[2].split()) > 6 or re.search(r"\d", b[2]):
                    continue
                by, bx, _, bw, bh = b
                if abs(bx - ax) >= 0.08 * W and not (bx < ax + aw and ax < bx + bw):
                    continue
                d = by - (ay + ah) if below else ay - (by + bh)
                if (by >= ay) == below and -0.01 * H <= d <= 0.06 * H and (gap is None or d < gap):
                    best, gap = j, d
            if best is not None:
                break
        if best is None:
            continue
        b = out[best]
        used.update((i, best))
        joined.append((min(ay, b[0]), min(ax, b[1]), f"{H_strip(b[2])} — {a[2]}", max(aw, b[3]), ah + b[4]))
    return [p for k, p in enumerate(out) if k not in used] + joined


def H_strip(text: str) -> str:
    return text.rstrip(" .:;,")


def keep_pictures(text: DeckText, folder: Path) -> dict[str, str]:
    """The deck's pictures saved in `folder` (the template's workspace) with SOURCE_IMAGES: {hint: file}."""
    folder.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}
    for k, (hint, blob, ext) in enumerate(text.pictures, 1):
        name = f"picture-{k:02d}.{ext.lower().lstrip('.') or 'png'}"
        (folder / name).write_bytes(blob)
        index[hint] = name
    (folder.parent / SOURCE_IMAGES).write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def source_records(ws_root: Path, pic_dir: Path) -> list[dict]:
    """Picture records for the generation (images/fill.py `reuse`): each picture of the original deck, copied into the
    generation's pictures folder, goes to the place its description names — never generated again."""
    import shutil

    idx_file = Path(ws_root) / SOURCE_IMAGES
    if not idx_file.is_file():
        return []
    try:
        index = json.loads(idx_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pic_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for hint, name in index.items():
        src = Path(ws_root) / "source_images" / name
        if not src.is_file():
            continue
        dst = pic_dir / f"source-{name}"
        if not dst.exists():
            shutil.copy2(src, dst)
        out.append({
            "status": "generated", "file": dst.name, "hint": hint, "source": "original", "model": "original", "model_label": "исходная презентация",
            "aspect": "4:3", "key": f"source:{name}", "prompt": "", "style": "", "subject_by": "author", "seed": 0, "palette_match": None, "cost_rub": None,
        })
    return out
