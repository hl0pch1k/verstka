"""Файл Figma `.fig` («Сохранить локальную копию») → `BrandSpec` без Figma и без токена.

Новый `.fig` — ZIP: `canvas.fig` (kiwi: схема + сообщение, см. `kiwi.py`), `thumbnail.png`, `meta.json`, `images/<sha1>`;
старый — сам `canvas.fig`. Из документа берутся:
- переменные (коллекции и режимы; режим по умолчанию — первый; ссылки раскрываются) — тем же разбором, что ответ REST API
  Figma (`figma._parse_variables`): цвета с ролями по именам, семейства шрифтов, поля/колонки/промежутки;
- стили: заливки (`styleType FILL`, сплошной цвет) и текста (`TEXT`: семейство, начертание, размер — самый крупный стиль
  без роли в имени — заголовки, самый частый размер текста — основной);
- сетка (`layoutGrids` стилей сетки и фреймов 16:9: колонки, промежуток, поле) и отступы автолейаута фреймов 16:9 (поле
  слайда в пересчёте на ширину 1920 px), шкала отступов «Space/…» — правилом;
- если стилей и переменных нет — палитра и шрифты по самим макетам (заливки по площади, шрифты по объёму текста);
- логотипы: узлы с «logo / логотип» в имени — картинка заливки из `images/` или вектор (контуры `fillGeometry` /
  `strokeGeometry`, экземпляры — по своему компоненту) → SVG → PNG; значки соцсетей не берутся;
- превью `thumbnail.png` — палитра по пикселям, когда документ не прочитался.

Любая неудача разбора документа не роняет чтение: остаются превью и картинки и честное предупреждение."""

from __future__ import annotations

import io
import json
import re
import struct
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from verstka.brand.common import (
    BrandReadError,
    ColorHit,
    FontHit,
    add_rule,
    brand_name,
    color_role,
    font_role,
    make_fonts,
    make_palette,
    name_from_path,
    parse_color,
    rgb_hex,
    usable_color_name,
    weight_of,
    words,
)
from verstka.schemas.brand import BrandSpec

PREVIEW_ONLY = ("Из .fig взяты цвета превью и картинки: сам документ Figma прочитать не удалось. Для точных токенов дайте "
                "ссылку на файл Figma (нужен FIGMA_TOKEN) или экспорт переменных JSON.")
_SOCIAL = re.compile(r"(?<![a-z])(instagram|insta|youtube|twitter|facebook|linkedin|tiktok|whatsapp|github|dribbble|behance|"
                     r"pinterest|reddit|discord|slack|snapchat|threads|x)(?![a-z])", re.I)
_LOGO_NAME = re.compile(r"(?<![a-z])(logo|logos|logotype|wordmark|lockup|brandmark)(?![a-z])|логотип\w*|лого(?![а-яё])", re.I)
_STATE = re.compile(r"(?<![a-z])(hover|pressed|active|focus|disabled|overlay|shadow|scrim|skeleton)(?![a-z])")
_SPACE_NAME = re.compile(r"(?<![a-z])(space|spacing|gap|отступ\w*)(?![a-z])", re.I)
_MAX_LOGOS = 3
_PATH_ARGS = {0: 0, 1: 2, 2: 2, 3: 4, 4: 6}


def _gid(g: Any) -> Optional[str]:
    if isinstance(g, dict) and "guid" in g and isinstance(g["guid"], dict):
        g = g["guid"]
    if isinstance(g, dict) and "sessionID" in g:
        return f"{g['sessionID']}:{g['localID']}"
    return None


def _hex(c: Any) -> Optional[str]:
    if not isinstance(c, dict) or not all(k in c for k in ("r", "g", "b")):
        return None
    try:
        return rgb_hex(float(c["r"]) * 255, float(c["g"]) * 255, float(c["b"]) * 255)
    except (TypeError, ValueError):
        return None


def _solid(paints: Any) -> Optional[tuple[str, float]]:
    """Первая видимая сплошная заливка: (HEX, непрозрачность)."""
    for p in paints or []:
        if isinstance(p, dict) and p.get("type") == "SOLID" and p.get("visible", True) is not False:
            hx = _hex(p.get("color"))
            if hx:
                a = float((p.get("color") or {}).get("a", 1) or 0) * float(p.get("opacity", 1) if p.get("opacity") is not None else 1)
                return hx, a
    return None


# ------------------------------------------------------------------------------------------------- the document's parts
class _Doc:
    def __init__(self, message: dict) -> None:
        self.nodes: list[dict] = [n for n in message.get("nodeChanges") or [] if isinstance(n, dict)]
        self.blobs: list[bytes] = [b.get("bytes", b"") if isinstance(b, dict) else b"" for b in message.get("blobs") or []]
        self.by_id: dict[str, dict] = {}
        self.kids: dict[str, list[dict]] = defaultdict(list)
        for n in self.nodes:
            i = _gid(n.get("guid"))
            if i:
                self.by_id[i] = n
        for n in self.nodes:
            p = _gid((n.get("parentIndex") or {}).get("guid"))
            if p:
                self.kids[p].append(n)
        for v in self.kids.values():
            v.sort(key=lambda n: str((n.get("parentIndex") or {}).get("position") or ""))

    def children(self, n: dict) -> list[dict]:
        return self.kids.get(_gid(n.get("guid")) or "", [])

    def path(self, idx: Any) -> Optional[str]:
        """Контур из blob: 0 Z, 1 M x y, 2 L x y, 3 Q, 4 C — float32."""
        if not isinstance(idx, int) or not 0 <= idx < len(self.blobs):
            return None
        b = self.blobs[idx]
        p, out = 0, []
        while p < len(b):
            op = b[p]
            p += 1
            n = _PATH_ARGS.get(op)
            if n is None or p + 4 * n > len(b):
                return None
            vals = struct.unpack_from(f"<{n}f", b, p)
            p += 4 * n
            out.append("ZMLQC"[op] + (" " + " ".join(f"{v:.3f}" for v in vals) if vals else ""))
        return " ".join(out) or None


def _variables_rest(doc: _Doc) -> dict:
    """Переменные `.fig` → форма ответа REST `variables/local` (её разбирает `figma._parse_variables`). Устаревшие
    коллекции («deprecated») не берутся; цвета ролей идут первыми, примитивы шкал — последними."""
    sets: dict[str, dict] = {}
    for n in doc.nodes:
        if n.get("type") == "VARIABLE_SET":
            i = _gid(n.get("guid"))
            modes = [m for m in n.get("variableSetModes") or [] if isinstance(m, dict)]
            if i and modes:
                sets[i] = {"id": i, "name": str(n.get("name") or ""), "defaultModeId": _gid(modes[0].get("id")),
                           "modes": [{"modeId": _gid(m.get("id")), "name": m.get("name")} for m in modes]}
    variables: dict[str, dict] = {}
    for n in doc.nodes:
        if n.get("type") != "VARIABLE":
            continue
        i = _gid(n.get("guid"))
        sid = _gid(n.get("variableSetID"))
        col = sets.get(sid or "")
        if not i or col is None or re.search(r"deprecat|устар", col["name"], re.I):
            continue
        vbm: dict[str, Any] = {}
        for e in ((n.get("variableDataValues") or {}).get("entries") or []):
            mode = _gid(e.get("modeID"))
            val = ((e.get("variableData") or {}).get("value")) or {}
            if not mode or not isinstance(val, dict):
                continue
            if "alias" in val:
                vbm[mode] = {"type": "VARIABLE_ALIAS", "id": _gid(val["alias"])}
            elif "colorValue" in val:
                vbm[mode] = val["colorValue"]
            elif "floatValue" in val:
                vbm[mode] = val["floatValue"]
            elif "textValue" in val:
                vbm[mode] = val["textValue"]
            elif "boolValue" in val:
                vbm[mode] = val["boolValue"]
        if not vbm:
            continue
        variables[i] = {"id": i, "name": str(n.get("name") or ""), "resolvedType": str(n.get("variableResolvedType") or ""),
                        "variableCollectionId": sid, "valuesByMode": vbm, "description": str(n.get("description") or "")}
        if col["defaultModeId"] not in vbm:
            col["defaultModeId"] = next(iter(vbm))

    def order(v: dict) -> tuple:
        cname = sets[v["variableCollectionId"]]["name"]
        prim = bool(re.search(r"primitive|примитив|palette|scale|base", cname, re.I))
        named = color_role(words(v["name"])) is not None
        return (prim, not named)

    ordered = dict(sorted(variables.items(), key=lambda kv: order(kv[1])))
    return {"meta": {"variables": ordered, "variableCollections": sets}}


def _drop_translucent(data: dict) -> None:
    """Полупрозрачные цвета (подложки, тени, «Black/100» с альфой 5%) — не цвета бренда."""
    from verstka.brand.figma import _value

    meta = data["meta"]
    for k, v in list(meta["variables"].items()):
        if v["resolvedType"] == "COLOR":
            val = _value(v, meta["variables"], meta["variableCollections"])
            if isinstance(val, dict) and float(val.get("a", 1)) < 0.6:
                del meta["variables"][k]


_CAT = {"background": "bg", "bg": "bg", "surface": "bg", "fill": "bg", "canvas": "bg", "text": "text", "foreground": "text",
        "fg": "text", "content": "text", "icon": "icon", "border": "border", "stroke": "border", "outline": "border"}
_VARIANT = {"default": "default", "neutral": "neutral", "brand": "brand", "primary": "brand", "accent": "accent",
            "positive": "success", "success": "success", "warning": "warning", "danger": "danger", "error": "danger",
            "negative": "danger", "critical": "danger", "info": "info", "disabled": "skip", "utilities": "skip", "utility": "skip"}
_SKIP_SEG = re.compile(r"(?<![a-z])(hover|pressed|active|focus|disabled|on\s+\w+|inverse|inverted|blanket|scrim|overlay|"
                       r"measurement|selected|shadow)(?![a-z])")
# category, variant, level → role and rank (smaller wins)
_SEMANTIC = [
    (("bg", "default", "default"), "background", 0), (("bg", "default", "primary"), "background", 0),
    (("bg", "default", "secondary"), "surface", 0), (("text", "default", "default"), "text", 0),
    (("text", "default", "primary"), "text", 0), (("text", "neutral", "default"), "text", 1),
    (("bg", "brand", "default"), "primary", 0), (("border", "brand", "default"), "primary", 1), (("icon", "brand", "default"), "primary", 2),
    (("text", "brand", "default"), "primary", 3), (("bg", "accent", "default"), "accent", 0), (("text", "accent", "default"), "accent", 1),
    (("bg", "success", "default"), "success", 0), (("bg", "warning", "default"), "warning", 0), (("bg", "danger", "default"), "danger", 0),
    (("bg", "neutral", "default"), "neutral", 0), (("bg", "info", "default"), "chart", 0),
]


def _semantic_colors(rest: dict) -> list[ColorHit]:
    """Семантические переменные «Категория/Вариант/Уровень» (Background/Brand/Default, Text/Default/Default — как в дизайн-
    системах Figma) → цвета ролей: основной — фон бренда, текст — текст по умолчанию, фон — фон по умолчанию, статусы —
    свои. Состояния (hover, disabled), «on brand» и служебные — не цвета бренда."""
    from verstka.brand.figma import _value

    meta = rest["meta"]
    best: dict[str, tuple[int, str, str]] = {}
    for v in meta["variables"].values():
        if v["resolvedType"] != "COLOR":
            continue
        segs = [words(x) for x in str(v["name"]).split("/") if x.strip()]
        if len(segs) < 2 or any(_SKIP_SEG.search(x) for x in segs):
            continue
        cat = _CAT.get(segs[0])
        var = _VARIANT.get(segs[1])
        level = segs[2] if len(segs) > 2 else "default"
        if cat is None or var is None or var == "skip":
            continue
        level = "default" if level in ("default", "base", "main", "500") else level
        hx = parse_color(_value(v, meta["variables"], meta["variableCollections"]))
        if not hx:
            continue
        for key, role, rank in _SEMANTIC:
            if key == (cat, var, level) and (role not in best or rank < best[role][0]):
                best[role] = (rank, hx, str(v["name"]))
    order = ["primary", "accent", "background", "surface", "text", "neutral", "success", "warning", "danger", "chart"]
    return [ColorHit(best[r][1], r, None) for r in order if r in best]  # type: ignore[arg-type]


def _styles(doc: _Doc, parts: Any, have_colors: bool, have_fonts: bool) -> None:
    sized: list[tuple[float, FontHit]] = []
    for n in doc.nodes:
        st = n.get("styleType")
        if st not in ("FILL", "TEXT"):
            continue
        name = str(n.get("name") or "")
        w = words(name)
        if st == "FILL" and not _STATE.search(w):
            s = _solid(n.get("fillPaints"))
            role = color_role(w)
            if s and s[1] >= 0.6 and (role is not None or not have_colors):
                parts.colors.append(ColorHit(s[0], role, usable_color_name(name.split("/")[-1])))
        elif st == "TEXT" and not have_fonts:
            fam = str(((n.get("fontName") or {}).get("family")) or "").strip()
            if not fam or re.search(r"mono|code", fam + " " + name, re.I):
                continue
            hit = FontHit(fam, font_role(w), weight_of(((n.get("fontName") or {}).get("style"))))
            if hit.role:
                parts.fonts.append(hit)
            else:
                sized.append((float(n.get("fontSize") or 0), hit))
    if sized and not have_fonts:
        sized.sort(key=lambda x: -x[0])
        parts.fonts.append(FontHit(sized[0][1].family, "heading", sized[0][1].weight))
        sizes = Counter(round(s) for s, _ in sized)
        body_size = max(sizes, key=lambda s: (sizes[s], -abs(s - 16)))
        body = next(h for s, h in sized if round(s) == body_size)
        parts.fonts.append(FontHit(body.family, "body", body.weight))


def _usage(doc: _Doc, parts: Any, need_colors: bool, need_fonts: bool) -> None:
    """Без стилей и переменных: цвета — по площади заливок, шрифты — по объёму текста и кеглю."""
    if need_colors:
        area: Counter = Counter()
        for n in doc.nodes:
            if n.get("type") in ("FRAME", "RECTANGLE", "ROUNDED_RECTANGLE", "ELLIPSE", "VECTOR", "TEXT", "SECTION", "SYMBOL"):
                s = _solid(n.get("fillPaints"))
                size = n.get("size") or {}
                if s and s[1] >= 0.6:
                    a = float(size.get("x") or 0) * float(size.get("y") or 0)
                    if n.get("type") == "TEXT":
                        a = max(a * 0.3, len(str(((n.get("textData") or {}).get("characters")) or "")) * 50.0)
                    area[s[0]] += a
        parts.colors += [ColorHit(hx) for hx, _ in area.most_common(8)]
    if need_fonts:
        vol: Counter = Counter()
        big: list[tuple[float, str, Any]] = []
        for n in doc.nodes:
            if n.get("type") != "TEXT":
                continue
            fam = str(((n.get("fontName") or {}).get("family")) or "").strip()
            if not fam:
                continue
            chars = len(str(((n.get("textData") or {}).get("characters")) or ""))
            vol[fam] += chars
            big.append((float(n.get("fontSize") or 0), fam, ((n.get("fontName") or {}).get("style"))))
        if vol:
            body = vol.most_common(1)[0][0]
            big.sort(key=lambda x: -x[0])
            head = big[0]
            parts.fonts += [FontHit(head[1], "heading", weight_of(head[2])), FontHit(body, "body")]


def _layout(doc: _Doc, parts: Any) -> None:
    """Сетка и поля: стили сетки, сетки и автолейаут фреймов 16:9 (в пересчёте на ширину 1920)."""
    frames = [n for n in doc.nodes if n.get("type") in ("FRAME", "SYMBOL") and isinstance(n.get("size"), dict)
              and float(n["size"].get("x") or 0) >= 960 and abs(float(n["size"]["x"]) / max(float(n["size"].get("y") or 1), 1) - 16 / 9) < 0.04]
    grids = [(n, 1920.0) for n in doc.nodes if n.get("styleType") == "GRID"]
    grids += [(n, float(n["size"]["x"])) for n in frames]
    for n, width in grids:
        for g in n.get("layoutGrids") or []:
            if not isinstance(g, dict) or g.get("visible") is False or str(g.get("axis") or "X") not in ("X", "0"):
                continue
            cols = int(g.get("numSections") or 0)
            if 2 <= cols <= 24 and parts.columns is None:
                parts.columns = cols
                k = 1920.0 / width if width else 1.0
                if g.get("gutterSize"):
                    parts.gutter = round(float(g["gutterSize"]) * k, 1)
                off = float(g.get("offset") or 0)
                if 0 < off * k <= 400 and parts.margins is None and str(g.get("type") or "") != "CENTER":
                    parts.margins = round(off * k, 1)
    if parts.margins is None:
        pads = Counter()
        for n in frames:
            pad = n.get("stackHorizontalPadding") or n.get("stackPaddingLeft")
            if pad and n.get("stackMode"):
                pads[round(float(pad) * 1920.0 / float(n["size"]["x"]))] += 1
        if pads:
            m = pads.most_common(1)[0][0]
            if 0 < m <= 400:
                parts.margins = float(m)


def _space_scale(rest: dict) -> Optional[str]:
    """«Space/100…» переменные → «Шаг отступов: 4, 8, 12, 16, 24 px»."""
    vals = []
    for v in rest["meta"]["variables"].values():
        if v["resolvedType"] == "FLOAT" and _SPACE_NAME.search(v["name"]):
            from verstka.brand.figma import _value

            x = _value(v, rest["meta"]["variables"], rest["meta"]["variableCollections"])
            if isinstance(x, (int, float)) and 0 < x <= 400:
                vals.append(float(x))
    vals = sorted(set(vals))
    if len(vals) < 3:
        return None
    return "Шаг отступов: " + ", ".join(f"{v:g}" for v in vals[:8]) + " px"


# ------------------------------------------------------------------------------------------------------------------ logos
def _matrix(n: dict) -> tuple[float, float, float, float, float, float]:
    t = n.get("transform") or {}
    g = lambda k, d: float(t.get(k, d) or 0) if t.get(k) is not None else d  # noqa: E731
    return (g("m00", 1.0), g("m10", 0.0), g("m01", 0.0), g("m11", 1.0), g("m02", 0.0), g("m12", 0.0))


def _vector_svg(doc: _Doc, root: dict) -> Optional[str]:
    """Узел-логотип → SVG из контуров (заливки и обводки как заливки контуров), без текста и эффектов."""
    seen: set[str] = set()
    count = [0]

    def walk(n: dict, depth: int) -> str:
        if depth > 12 or n.get("visible") is False or count[0] > 400:
            return ""
        i = _gid(n.get("guid")) or ""
        if i in seen:
            return ""
        seen.add(i)
        body: list[str] = []
        for geo_key, paint_key in (("fillGeometry", "fillPaints"), ("strokeGeometry", "strokePaints")):
            s = _solid(n.get(paint_key))
            if not s or s[1] < 0.05:
                continue
            for g in n.get(geo_key) or []:
                d = doc.path(g.get("commandsBlob")) if isinstance(g, dict) else None
                if d:
                    rule = "evenodd" if str(g.get("windingRule")) in ("ODD", "EVENODD") else "nonzero"
                    op = f' fill-opacity="{s[1]:.3f}"' if s[1] < 0.999 else ""
                    body.append(f'<path d="{d}" fill="{s[0]}" fill-rule="{rule}"{op}/>')
                    count[0] += 1
        kids = doc.children(n)
        if not kids and n.get("type") == "INSTANCE":
            sym = doc.by_id.get(_gid(((n.get("symbolData") or {}).get("symbolID"))) or "")
            kids = doc.children(sym) if sym else []
        for k in kids:
            inner = walk(k, depth + 1)
            if inner:
                a, b, c, d_, e, f = _matrix(k)
                body.append(f'<g transform="matrix({a:.5f} {b:.5f} {c:.5f} {d_:.5f} {e:.3f} {f:.3f})">{inner}</g>')
        return "".join(body)

    content = walk(root, 0)
    size = root.get("size") or {}
    w, h = float(size.get("x") or 0), float(size.get("y") or 0)
    if not content or w <= 1 or h <= 1:
        return None
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}" height="{h:.2f}" viewBox="0 0 {w:.3f} {h:.3f}">'
            + content + "</svg>")


def _has_text(doc: _Doc, n: dict, depth: int = 0) -> bool:
    if n.get("type") == "TEXT":
        return True
    return depth < 12 and any(_has_text(doc, k, depth + 1) for k in doc.children(n))


def _image_of(n: dict) -> Optional[str]:
    for p in n.get("fillPaints") or []:
        if isinstance(p, dict) and p.get("type") == "IMAGE" and p.get("visible", True) is not False:
            h = (p.get("image") or {}).get("hash")
            if isinstance(h, (bytes, bytearray)) and h:
                return bytes(h).hex()
    return None


def _logo_files(doc: _Doc, images: dict[str, bytes], out_dir: Path) -> list[Path]:
    """Логотипы-кандидаты → файлы `out_dir/logos/*.svg|png` (до трёх, без повторов и значков соцсетей)."""
    cands = []
    for n in doc.nodes:
        name = str(n.get("name") or "")
        if not _LOGO_NAME.search(name) or _SOCIAL.search(name) or n.get("visible") is False:
            continue
        size = n.get("size") or {}
        if float(size.get("x") or 0) < 8 or float(size.get("y") or 0) < 8:
            continue
        cands.append(n)
    # компоненты и главные фреймы — раньше экземпляров; крупнее — раньше
    cands.sort(key=lambda n: (n.get("type") == "INSTANCE", -float((n.get("size") or {}).get("x") or 0) * float((n.get("size") or {}).get("y") or 0)))
    files: list[Path] = []
    sigs: set = set()
    (out_dir / "logos").mkdir(parents=True, exist_ok=True)
    for n in cands:
        if len(files) >= _MAX_LOGOS:
            break
        stem = re.sub(r"[^\w-]+", "-", str(n.get("name") or "logo")).strip("-")[:40] or "logo"
        img = _image_of(n)
        if img and img in images:
            if img in sigs:
                continue
            sigs.add(img)
            p = out_dir / "logos" / f"{stem}-{len(files) + 1}.png"
            p.write_bytes(images[img])
            files.append(p)
            continue
        if _has_text(doc, n):
            continue  # a wordmark set in text: its letters are not in the file as contours
        svg = _vector_svg(doc, n)
        if not svg:
            continue
        sig = re.sub(r"\d+\.\d+", "", svg)[:4000]
        if sig in sigs:
            continue
        sigs.add(sig)
        p = out_dir / "logos" / f"{stem}-{len(files) + 1}.svg"
        p.write_text(svg, encoding="utf-8")
        files.append(p)
    return files


def _image_logos(images: dict[str, bytes], out_dir: Path) -> list[Path]:
    from PIL import Image

    (out_dir / "logos").mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for i, (h, data) in enumerate(sorted(images.items())):
        try:
            with Image.open(io.BytesIO(data)) as im:
                w, hh = im.size
                alpha = ("A" in im.getbands() and im.getchannel("A").getextrema()[0] < 250) or "transparency" in im.info
        except Exception:  # noqa: BLE001 - not a picture
            continue
        if alpha and 16 <= w <= 4000 and 16 <= hh <= 4000:
            p = out_dir / "logos" / f"logo-{i + 1}.png"
            p.write_bytes(data)
            files.append(p)
        if len(files) >= _MAX_LOGOS:
            break
    return files


# --------------------------------------------------------------------------------------------------------------- reading
def _container(data: bytes, label: str) -> tuple[Optional[bytes], Optional[bytes], dict, dict[str, bytes]]:
    """(canvas, thumbnail, meta, images) из ZIP нового `.fig` или из старого бинарного."""
    if data[:4] == b"fig-":
        return data, None, {}, {}
    if data[:2] != b"PK":
        raise BrandReadError(f"«{label}» не похож на файл Figma: это не ZIP и не «fig-kiwi». Сохраните файл в Figma заново "
                             "(Файл → Сохранить локальную копию) или дайте ссылку на файл.")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BrandReadError(f"Файл «{label}» повреждён: архив .fig не открывается.") from None
    canvas = thumb = None
    meta: dict = {}
    images: dict[str, bytes] = {}
    total = 0
    with z:
        for info in z.infolist():
            if info.is_dir():
                continue
            total += info.file_size
            if total > 600 * 1024 * 1024:
                raise BrandReadError(f"«{label}» слишком большой: файл Figma — до 600 МБ в распакованном виде.")
            nm = PurePosixPath(info.filename)
            try:
                if nm.name == "canvas.fig" or (canvas is None and nm.suffix == ".fig"):
                    canvas = z.read(info)
                elif nm.name == "thumbnail.png":
                    thumb = z.read(info)
                elif nm.name == "meta.json":
                    try:
                        meta = json.loads(z.read(info).decode("utf-8", "replace"))
                    except ValueError:
                        meta = {}
                elif nm.parts and nm.parts[0] == "images" and len(images) < 400 and info.file_size <= 30 * 1024 * 1024:
                    images[nm.name.lower()] = z.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError):
                raise BrandReadError(f"Файл «{label}» повреждён или защищён паролем.") from None
    return canvas, thumb, meta if isinstance(meta, dict) else {}, images


def read_fig(path: Path | str, *, assets_dir: Optional[Path | str] = None, time_budget: float = 75.0,
             on_progress: Optional[Callable[[str, str], None]] = None) -> BrandSpec:
    """`.fig` → `BrandSpec` (источник «figma»). Логотипы — в `<assets_dir>/logos/` (PNG; SVG рядом)."""
    from verstka.brand.figma import _assemble, _parse_variables, _Parts
    from verstka.brand.folder import _collect_logos, image_colors
    from verstka.brand.kiwi import KiwiError, read_fig_archive
    from verstka.brand.zstd import ZstdError

    path = Path(path)
    data = path.read_bytes()
    canvas, thumb, meta, images = _container(data, path.name)
    file_name = re.sub(r"\s*\((?:community|copy|копия)\)\s*$", "", str(meta.get("file_name") or ""), flags=re.I)
    name = brand_name(file_name) or name_from_path(path.stem) or ""
    warnings: list[str] = []
    parts = _Parts()
    doc: Optional[_Doc] = None
    note = None
    if canvas is not None:
        if on_progress:
            on_progress("Открыт файл", "документ Figma")
        try:
            arc = read_fig_archive(canvas, deadline=time.monotonic() + time_budget)
            doc = _Doc(arc.message)
            if arc.partial:
                warnings.append("Файл Figma очень большой — прочитал его начало за отведённое время; проверьте палитру и шрифты.")
        except (KiwiError, ZstdError, MemoryError, struct.error, KeyError, IndexError, TypeError, ValueError) as e:
            note = str(e)
            doc = None
    if doc is not None and not doc.nodes:
        doc = None
    rest = None
    if doc is not None:
        rest = _variables_rest(doc)
        _drop_translucent(rest)
        semantic = _semantic_colors(rest)
        if len(semantic) >= 2:  # a design system of semantic tokens: its roles, not the first dozen of its scales
            parts.colors += semantic
            meta = rest["meta"]
            _parse_variables({"meta": {**meta, "variables": {k: v for k, v in meta["variables"].items() if v["resolvedType"] != "COLOR"}}}, parts)
        else:
            _parse_variables(rest, parts)
        _styles(doc, parts, have_colors=bool(parts.colors), have_fonts=bool(parts.fonts))
        if not parts.colors or not parts.fonts:
            had_colors = bool(parts.colors)
            _usage(doc, parts, need_colors=not parts.colors, need_fonts=not parts.fonts)
            if not had_colors and parts.colors:
                warnings.append("В файле Figma нет стилей и переменных цвета — палитра посчитана по заливкам макетов, роли угаданы. Проверьте.")
        _layout(doc, parts)
        scale = _space_scale(rest)
        if scale:
            add_rule(parts.rules, scale, "grid")
    if not parts.colors and thumb:
        tmp = Path(tempfile.mkdtemp(prefix="fig-thumb-"))
        try:
            (tmp / "t.png").write_bytes(thumb)
            parts.colors = [ColorHit(hx) for hx, share in image_colors(tmp / "t.png") if share >= 0.01]
        except Exception:  # noqa: BLE001 - a broken preview: no colours from it
            pass
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
        if doc is None:
            warnings.append(PREVIEW_ONLY)
    if not parts.colors and not parts.fonts:
        if note:
            import logging

            logging.getLogger(__name__).warning("fig not read: %s: %s", path.name, note)
        raise BrandReadError(f"Не удалось прочитать файл Figma «{path.name}»: он повреждён или сохранён в незнакомом виде. Дайте ссылку на файл (нужен FIGMA_TOKEN) "
                             "или экспорт переменных JSON (Tokens Studio → Export).")
    spec = _assemble(parts, file=path.name, source="figma", name=name)
    # logos: vector or image nodes named «logo»; with no store for them — none (the reader that has no folder keeps none).
    # The document unread: the file's pictures that look like logos (transparent, not slide-like)
    if assets_dir is not None:
        with tempfile.TemporaryDirectory(prefix="fig-logos-") as tmp:
            files = _logo_files(doc, images, Path(tmp)) if doc is not None else _image_logos(images, Path(tmp))
            if files:
                logos, w = _collect_logos([(PurePosixPath("logos") / f.name, f) for f in files], Path(assets_dir))
                spec.logos = logos
                warnings += w
    spec.warnings = warnings + spec.warnings
    return spec
