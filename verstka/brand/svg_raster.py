"""Растр SVG-логотипа без внешних программ: контуры, простые фигуры, заливки, прозрачность, преобразования.

PowerPoint не вставляет SVG-логотип как есть (нужен PNG), а на машине, где работает Verstka, нет ни `rsvg-convert`, ни Inkscape.
Поэтому для логотипов из папки брендбука здесь есть небольшой растеризатор на Pillow: `<path>` (все команды, дуги), `<rect>`,
`<circle>`, `<ellipse>`, `<polygon>`, `<polyline>`, группы с `transform`, заливки (`fill`, `fill-opacity`, `opacity`, `fill-rule`),
стили из атрибута `style` и из `<style>` по классам, градиент заменяется цветом своей средней остановки. Не поддерживаются
обводки, текст, фильтры и обрезка — такой SVG не растрируется (`render_svg` вернёт None), и вызывающий оставит SVG как есть.
Внешний `rsvg-convert` или Inkscape, если они есть, точнее: `rasterize_svg` в `folder.py` пробует их первыми."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageDraw

from verstka.brand.common import parse_color

_NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
_SKIP_TAGS = {"defs", "clippath", "mask", "symbol", "title", "desc", "metadata", "style", "script", "filter", "pattern", "marker", "lineargradient",
              "radialgradient", "text", "tspan", "image", "foreignobject", "switch"}
Matrix = tuple[float, float, float, float, float, float]
_IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


def _mul(m: Matrix, n: Matrix) -> Matrix:
    """m · n: сначала n, затем m."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2, a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _transform(text: str) -> Matrix:
    m = _IDENTITY
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text or ""):
        v = [float(x) for x in re.findall(_NUM, args)]
        name = name.lower()
        if name == "translate" and v:
            n: Matrix = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "scale" and v:
            n = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            r = math.radians(v[0])
            cx, cy = (v[1], v[2]) if len(v) >= 3 else (0, 0)
            rot: Matrix = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            n = _mul(_mul((1, 0, 0, 1, cx, cy), rot), (1, 0, 0, 1, -cx, -cy))
        elif name == "matrix" and len(v) == 6:
            n = (v[0], v[1], v[2], v[3], v[4], v[5])
        elif name == "skewx" and v:
            n = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewy" and v:
            n = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        m = _mul(m, n)
    return m


# ---- контуры ------------------------------------------------------------------------------------------------------------------
Point = tuple[float, float]


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point, n: int = 20) -> list[Point]:
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _arc(p0: Point, rx: float, ry: float, rot: float, large: bool, sweep: bool, p1: Point) -> list[Point]:
    """Дуга SVG (конечные точки) → ломаная (спецификация SVG, F.6.5)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rot)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx, cy = cp * cx1 - sp * cy1 + (p0[0] + p1[0]) / 2, sp * cx1 + cp * cy1 + (p0[1] + p1[1]) / 2

    def ang(ux: float, uy: float, vx: float, vy: float) -> float:
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(8, int(abs(dt) / (math.pi / 24)))
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
    out[-1] = p1
    return out


def _path_subpaths(d: str) -> list[list[Point]]:
    """Атрибут d → список подконтуров (ломаных); каждый подконтур замыкается при заливке."""
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + _NUM, d or "")
    subs: list[list[Point]] = []
    cur: list[Point] = []
    pos: Point = (0.0, 0.0)
    start: Point = pos
    last_ctrl: Optional[Point] = None
    last_cmd = ""
    i = 0
    cmd = ""

    def num() -> float:
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    def flag() -> bool:
        """Флаг дуги — один символ 0 или 1 (слитно с соседним числом: «a1 1 0 01.5.5»)."""
        nonlocal i
        t = tokens[i]
        if t[0] in "01":
            if len(t) > 1:
                tokens[i] = t[1:]
            else:
                i += 1
            return t[0] == "1"
        raise ValueError("flag")

    while i < len(tokens):
        if re.fullmatch(r"[A-Za-z]", tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    subs.append(cur)
                    cur = []
                pos = start
                last_ctrl = None
                last_cmd = "z"
                continue
        elif not cmd:
            raise ValueError("path")
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = pos if rel else (0.0, 0.0)
        if c == "M":
            if cur:
                subs.append(cur)
            pos = (ox + num(), oy + num())
            start = pos
            cur = [pos]
            cmd = "l" if rel else "L"  # следующие пары — линии
            last_ctrl = None
        elif c == "L":
            pos = (ox + num(), oy + num())
            cur.append(pos)
            last_ctrl = None
        elif c == "H":
            pos = ((pos[0] if rel else 0.0) + num(), pos[1])
            cur.append(pos)
            last_ctrl = None
        elif c == "V":
            pos = (pos[0], (pos[1] if rel else 0.0) + num())
            cur.append(pos)
            last_ctrl = None
        elif c == "C":
            p1, p2, p3 = (ox + num(), oy + num()), (ox + num(), oy + num()), (ox + num(), oy + num())
            cur += _bezier(pos, p1, p2, p3)
            pos, last_ctrl = p3, p2
        elif c == "S":
            p1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl and last_cmd in "CcSs" else pos
            p2, p3 = (ox + num(), oy + num()), (ox + num(), oy + num())
            cur += _bezier(pos, p1, p2, p3)
            pos, last_ctrl = p3, p2
        elif c in "QT":
            if c == "Q":
                q1 = (ox + num(), oy + num())
            else:
                q1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl and last_cmd in "QqTt" else pos
            q2 = (ox + num(), oy + num())
            cur += _bezier(pos, (pos[0] + 2 / 3 * (q1[0] - pos[0]), pos[1] + 2 / 3 * (q1[1] - pos[1])),
                           (q2[0] + 2 / 3 * (q1[0] - q2[0]), q2[1] + 2 / 3 * (q1[1] - q2[1])), q2)
            pos, last_ctrl = q2, q1
        elif c == "A":
            rx, ry, rot = num(), num(), num()
            large, sweep = flag(), flag()
            p1 = (ox + num(), oy + num())
            cur += _arc(pos, rx, ry, rot, large, sweep, p1)
            pos = p1
            last_ctrl = None
        else:
            raise ValueError("path")
        last_cmd = cmd
    if cur:
        subs.append(cur)
    return [s for s in subs if len(s) >= 2]


# ---- стили -------------------------------------------------------------------------------------------------------------------
def _css_rules(root) -> dict[str, dict[str, str]]:
    rules: dict[str, dict[str, str]] = {}
    for st in root.iter():
        if not isinstance(st.tag, str) or st.tag.split("}")[-1].lower() != "style" or not st.text:
            continue
        text = re.sub(r"/\*.*?\*/", "", st.text, flags=re.S)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            props = dict((k.strip().lower(), v.strip()) for k, _, v in (p.partition(":") for p in body.split(";")) if k.strip())
            for one in sel.split(","):
                one = one.strip()
                if re.fullmatch(r"\.[\w-]+|#[\w-]+|[a-zA-Z]+", one):
                    rules.setdefault(one, {}).update(props)
    return rules


_INHERITED = ("fill", "fill-opacity", "fill-rule", "stroke")


def _style_of(el, parent: dict[str, str], rules: dict[str, dict[str, str]]) -> dict[str, str]:
    st = dict(parent)  # непрозрачность группы не наследуется, а перемножается — см. draw
    props: dict[str, str] = {}
    tag = el.tag.split("}")[-1]
    props.update(rules.get(tag, {}))
    for cls in (el.get("class") or "").split():
        props.update(rules.get("." + cls, {}))
    if el.get("id"):
        props.update(rules.get("#" + el.get("id"), {}))
    for k in ("fill", "fill-opacity", "fill-rule", "opacity", "display", "visibility", "stroke"):
        if el.get(k) is not None:
            st[k] = el.get(k).strip()
    st.update(props)
    for part in (el.get("style") or "").split(";"):
        k, _, v = part.partition(":")
        if k.strip():
            st[k.strip().lower()] = v.strip()
    return st


def _gradient_colour(root, ref: str) -> Optional[str]:
    m = re.fullmatch(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)", ref.strip())
    if not m:
        return None
    by_id = {e.get("id"): e for e in root.iter() if isinstance(e.tag, str) and e.get("id")}
    node = by_id.get(m.group(1))
    for _ in range(5):
        if node is None:
            return None
        stops = [s for s in node if isinstance(s.tag, str) and s.tag.split("}")[-1] == "stop"]
        if stops:
            s = stops[len(stops) // 2]
            style = dict((k.strip(), v.strip()) for k, _, v in (p.partition(":") for p in (s.get("style") or "").split(";")) if k.strip())
            return parse_color(style.get("stop-color") or s.get("stop-color") or "#000000", named=True)
        href = node.get("{http://www.w3.org/1999/xlink}href") or node.get("href")
        node = by_id.get((href or "").lstrip("#"))
    return None


# ---- фигуры ---------------------------------------------------------------------------------------------------------------------
def _f(el, name: str, default: float = 0.0) -> float:
    m = re.match(_NUM, str(el.get(name) or "").strip())
    return float(m.group(0)) if m else default


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> list[Point]:
    return [(cx + rx * math.cos(2 * math.pi * k / 96), cy + ry * math.sin(2 * math.pi * k / 96)) for k in range(96)]


def _shape(el) -> Optional[list[list[Point]]]:
    tag = el.tag.split("}")[-1].lower()
    if tag == "path":
        return _path_subpaths(el.get("d") or "")
    if tag == "rect":
        x, y, w, h = _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
        rx, ry = _f(el, "rx", -1), _f(el, "ry", -1)
        rx, ry = (ry if rx < 0 else rx), (rx if ry < 0 else ry)
        rx, ry = min(max(rx, 0), w / 2), min(max(ry, 0), h / 2)
        if w <= 0 or h <= 0:
            return []
        if rx == 0 or ry == 0:
            return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
        d = (f"M{x + rx} {y}H{x + w - rx}A{rx} {ry} 0 0 1 {x + w} {y + ry}V{y + h - ry}A{rx} {ry} 0 0 1 {x + w - rx} {y + h}"
             f"H{x + rx}A{rx} {ry} 0 0 1 {x} {y + h - ry}V{y + ry}A{rx} {ry} 0 0 1 {x + rx} {y}Z")
        return _path_subpaths(d)
    if tag == "circle":
        r = _f(el, "r")
        return [_ellipse(_f(el, "cx"), _f(el, "cy"), r, r)] if r > 0 else []
    if tag == "ellipse":
        rx, ry = _f(el, "rx"), _f(el, "ry")
        return [_ellipse(_f(el, "cx"), _f(el, "cy"), rx, ry)] if rx > 0 and ry > 0 else []
    if tag in ("polygon", "polyline"):
        v = [float(x) for x in re.findall(_NUM, el.get("points") or "")]
        pts = list(zip(v[0::2], v[1::2]))
        return [pts] if len(pts) >= 3 else []
    return None


def _area(poly: list[Point]) -> float:
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))) / 2


class _Unsupported(Exception):
    pass


def render_svg(path: Path | str, height: int = 480, *, max_width: int = 4000) -> Optional[Image.Image]:
    """SVG-файл → RGBA-картинка высотой `height` (прозрачный фон, сглаживание 4×) или None, если файл не прочитан или в нём
    есть то, чего растеризатор не умеет (обводки без заливки, текст, картинки)."""
    from lxml import etree

    try:
        root = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)).getroot()
    except (etree.XMLSyntaxError, OSError):
        return None
    if not isinstance(root.tag, str) or root.tag.split("}")[-1].lower() != "svg":
        return None
    vb = [float(x) for x in re.findall(_NUM, root.get("viewBox") or "")]
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        minx, miny, vw, vh = vb
    else:
        vw, vh, minx, miny = _f(root, "width", 100.0), _f(root, "height", 100.0), 0.0, 0.0
    if vw <= 0 or vh <= 0:
        return None
    out_h = max(16, int(height))
    out_w = max(1, round(out_h * vw / vh))
    if out_w > max_width:
        out_w = max_width
        out_h = max(1, round(out_w * vh / vw))
    ss = 4 if out_w * out_h <= 1_500_000 else 2
    k = out_h * ss / vh
    base: Matrix = (k, 0, 0, k, -minx * k, -miny * k)
    canvas = Image.new("RGBA", (out_w * ss, out_h * ss), (0, 0, 0, 0))
    rules = _css_rules(root)
    drawn = 0

    def draw(el, m: Matrix, parent_style: dict[str, str], group_opacity: float) -> None:
        nonlocal drawn
        if not isinstance(el.tag, str):
            return
        tag = el.tag.split("}")[-1].lower()
        if tag in _SKIP_TAGS:
            if tag in ("text", "image"):
                raise _Unsupported(tag)
            return
        st = _style_of(el, parent_style, rules)
        if st.get("display") == "none" or st.get("visibility") == "hidden":
            return
        m2 = _mul(m, _transform(el.get("transform") or ""))
        own = st.get("opacity")
        opacity = group_opacity
        try:
            opacity = group_opacity * (float(own.rstrip("%")) / (100 if own.endswith("%") else 1) if own else 1.0)
        except ValueError:
            opacity = group_opacity
        if tag in ("g", "svg", "a"):
            child_style = {k: v for k, v in st.items() if k in _INHERITED}
            for ch in el:
                draw(ch, m2, child_style, opacity)
            return
        subs = _shape(el)
        if subs is None:
            return
        fill = st.get("fill", "#000000")
        if fill.lower() == "none":
            if st.get("stroke", "none").lower() not in ("none", ""):
                raise _Unsupported("stroke")
            return
        colour = _gradient_colour(root, fill) if fill.lower().startswith("url(") else parse_color(fill if fill.lower() != "currentcolor" else "#000000", named=True)
        if colour is None:
            return
        try:
            alpha = float(st.get("fill-opacity", "1").rstrip("%")) * opacity
        except ValueError:
            alpha = opacity
        alpha = max(0.0, min(1.0, alpha))
        if not subs or alpha <= 0:
            return
        polys = [[(m2[0] * x + m2[2] * y + m2[4], m2[1] * x + m2[3] * y + m2[5]) for x, y in sub] for sub in subs]
        xs = [p[0] for poly in polys for p in poly]
        ys = [p[1] for poly in polys for p in poly]
        x0, y0 = max(0, int(math.floor(min(xs))) - 1), max(0, int(math.floor(min(ys))) - 1)
        x1, y1 = min(canvas.width, int(math.ceil(max(xs))) + 2), min(canvas.height, int(math.ceil(max(ys))) + 2)
        if x1 <= x0 or y1 <= y0:
            return
        size = (x1 - x0, y1 - y0)
        masks = []
        for poly in polys:
            mk = Image.new("L", size, 0)
            ImageDraw.Draw(mk).polygon([(x - x0, y - y0) for x, y in poly], fill=255)
            masks.append((_area(poly), mk))
        if st.get("fill-rule", "nonzero") == "evenodd":
            mask = masks[0][1]
            for _, mk in masks[1:]:
                mask = ImageChops.logical_xor(mask.convert("1"), mk.convert("1")).convert("L")
        else:
            outer = max(masks, key=lambda a: abs(a[0]))[0]
            mask = Image.new("L", size, 0)
            for area, mk in masks:
                mask = ImageChops.lighter(mask, mk) if (area >= 0) == (outer >= 0) else ImageChops.subtract(mask, mk)
        if alpha < 1:
            mask = mask.point(lambda v: int(v * alpha))
        layer = Image.new("RGBA", size, tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5)) + (0,))
        layer.putalpha(mask)
        canvas.alpha_composite(layer, dest=(x0, y0))
        drawn += 1

    try:
        root_style = {"fill": "#000000", "fill-opacity": "1", "fill-rule": "nonzero"}
        for ch in root:
            draw(ch, base, root_style, 1.0)
    except (_Unsupported, ValueError, IndexError, ZeroDivisionError, OverflowError):
        return None
    if not drawn or canvas.getchannel("A").getbbox() is None:
        return None
    return canvas.resize((out_w, out_h), Image.LANCZOS)
