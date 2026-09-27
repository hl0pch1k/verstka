"""Colour tokens: collect, cluster and assign roles.

Roles are NOT exclusive: black can be both the dark background of title slides and the primary text colour
of content slides; the brand blue can be both a divider background and the first accent.
"""

from __future__ import annotations

import colorsys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import Color, Family, ShapeKind, contrast_ratio, hex_to_rgb, relative_luminance
from verstka.schemas.template import ColorToken


@dataclass
class ColorSample:
    hex: str
    context: str  # fill, text, line, background
    weight: float


def collect_color_samples(shapes: list[ShapeInfo], slide_w: int, slide_h: int, bg_hex: Optional[str] = None, chrome_ids: Optional[set[str]] = None) -> list[ColorSample]:
    area = float(slide_w * slide_h)
    chrome_ids = chrome_ids or set()
    out: list[ColorSample] = []
    if bg_hex:
        out.append(ColorSample(bg_hex.upper(), "background", 100.0))
    for s in shapes:
        if s.id in chrome_ids:
            continue
        if s.kind == ShapeKind.sp and s.fill_hex:
            frac = s.bbox.area / area if area else 0.0
            if frac >= 0.85 and not s.has_text:
                out.append(ColorSample(s.fill_hex.upper(), "background", 100.0))
            else:
                out.append(ColorSample(s.fill_hex.upper(), "fill", max(frac * 100.0, 0.2)))
            for hx in _pattern_colors(s):
                # a pattern fill (a hatched band) reads as a blend, but its ink is the template's colour
                out.append(ColorSample(hx, "fill", max(frac * 50.0, 0.2)))
        if s.line_hex:
            out.append(ColorSample(s.line_hex.upper(), "line", 0.5))
        if s.text:
            for p in s.text.paragraphs:
                for r in p.runs:
                    if r.color_hex and r.text.strip():
                        out.append(ColorSample(r.color_hex.upper(), "text", max(len(r.text) / 50.0, 0.05)))
    return out


def _pattern_colors(s: ShapeInfo) -> list[str]:
    el = s.element
    if el is None:
        return []
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    patt = el.find("{http://schemas.openxmlformats.org/presentationml/2006/main}spPr/" + ns + "pattFill")
    if patt is None:
        return []
    out = []
    for tag in ("fgClr", "bgClr"):
        c = patt.find(ns + tag + "/" + ns + "srgbClr")
        if c is not None and c.get("val") and len(c.get("val")) == 6:
            out.append(c.get("val").upper())
    return out


def cluster_colors(samples: list[ColorSample], delta_e_tol: float = 1.8) -> list[ColorToken]:
    """Greedy clustering by ΔE (tight: visually identical only, so white cards on an off-white background stay distinct);
    the heaviest observed hex represents each cluster (keeps exact brand colours)."""
    by_hex: dict[str, float] = defaultdict(float)
    ctx_count: dict[str, Counter] = defaultdict(Counter)
    ctx_weight: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for s in samples:
        by_hex[s.hex] += s.weight
        ctx_count[s.hex][s.context] += 1
        ctx_weight[s.hex][s.context] += s.weight
    ordered = sorted(by_hex.items(), key=lambda kv: -kv[1])
    clusters: list[dict] = []
    for hex_, w in ordered:
        c = Color(hex=hex_)
        for cl in clusters:
            if Color.delta_e(c, cl["color"]) <= delta_e_tol:
                cl["weight"] += w
                cl["contexts"].update(ctx_count[hex_])
                for k, v in ctx_weight[hex_].items():
                    cl["cw"][k] += v
                break
        else:
            clusters.append({"color": c, "hex": hex_, "weight": w, "contexts": Counter(ctx_count[hex_]), "cw": defaultdict(float, ctx_weight[hex_])})
    tokens = [
        ColorToken(hex=cl["hex"], weight=round(cl["weight"], 3), contexts=dict(cl["contexts"]), context_weight={k: round(v, 3) for k, v in cl["cw"].items()})
        for cl in clusters
    ]
    tokens.sort(key=lambda t: -t.weight)
    return tokens


def _saturation(hex_: str) -> float:
    """HSV saturation (HLS saturation explodes near white/black)."""
    r, g, b = hex_to_rgb(hex_)
    _, s, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return s


def _hue_deg(hex_: str) -> float:
    r, g, b = hex_to_rgb(hex_)
    h, _, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return h * 360


def assign_color_roles(tokens: list[ColorToken], primary_family: Family = Family.light) -> list[ColorToken]:
    """Assign roles in place (a token may carry several) and return the list."""
    for t in tokens:
        t.roles = []
        t.role = None
        t.semantic = None
        t.is_brand = False
    if not tokens:
        return tokens

    def cw(t: ColorToken, ctx: str) -> float:
        return t.context_weight.get(ctx, 0.0)

    # backgrounds
    light_bgs = [t for t in tokens if cw(t, "background") > 0 and relative_luminance(t.hex) >= 0.3]
    dark_bgs = [t for t in tokens if cw(t, "background") > 0 and relative_luminance(t.hex) < 0.3]
    bg_light = max(light_bgs, key=lambda t: cw(t, "background"), default=None)
    bg_dark = max(dark_bgs, key=lambda t: cw(t, "background"), default=None)
    if bg_light is None and primary_family == Family.light:
        bg_light = ColorToken(hex="FFFFFF", weight=0.0)
        tokens.append(bg_light)
    if bg_dark is None and primary_family == Family.dark:
        bg_dark = ColorToken(hex="000000", weight=0.0)
        tokens.append(bg_dark)
    if bg_light is not None:
        bg_light.roles.append("background.light")
    if bg_dark is not None:
        bg_dark.roles.append("background.dark")
    primary_bg = (bg_dark if primary_family == Family.dark else bg_light) or bg_light or bg_dark
    bg_hex = primary_bg.hex if primary_bg else "FFFFFF"

    # text colours (may overlap with backgrounds)
    text_tokens = sorted([t for t in tokens if cw(t, "text") > 0], key=lambda t: -cw(t, "text"))
    primary_text = next((t for t in text_tokens if contrast_ratio(t.hex, bg_hex) >= 4.5), None)
    if primary_text is not None:
        primary_text.roles.append("text.primary")
        secondary = next(
            (
                t
                for t in text_tokens
                if t is not primary_text and contrast_ratio(t.hex, bg_hex) >= 3.0 and Color.delta_e(Color(hex=t.hex), Color(hex=primary_text.hex)) > 10 and _saturation(t.hex) < 0.35
            ),
            None,
        )
        if secondary is not None:
            secondary.roles.append("text.secondary")

    # surface: a fill close to the background but distinct
    surfaces = [t for t in tokens if not t.roles and cw(t, "fill") > 0 and 1.0 < contrast_ratio(t.hex, bg_hex) < 1.6]
    if surfaces:
        max(surfaces, key=lambda t: cw(t, "fill")).roles.append("surface")

    # accents: saturated colours by weight; saturated backgrounds (brand dividers) count too
    def is_accent_candidate(t: ColorToken) -> bool:
        if _saturation(t.hex) < 0.25 or not (0.05 < relative_luminance(t.hex) < 0.95):
            return False
        return not any(r.startswith("text.") for r in t.roles) or cw(t, "fill") > 0

    accents = [t for t in tokens if is_accent_candidate(t)]

    def accent_rank(t: ColorToken) -> tuple[bool, float]:
        # a colour that barely stands out from the ground (a card surface, 1.3:1) never leads the accents,
        # however much area it covers: charts, KPI figures and ticks take accent.1 and must be visible
        blends_in = "surface" in t.roles or contrast_ratio(t.hex, bg_hex) < 1.6
        return blends_in, -((cw(t, "fill") + cw(t, "text") + cw(t, "line") + 0.05 * cw(t, "background")) * (0.5 + _saturation(t.hex)))

    accents.sort(key=accent_rank)
    for n, t in enumerate(accents[:6], 1):
        t.roles.append(f"accent.{n}")
        if n == 1:
            t.is_brand = True
        hue = _hue_deg(t.hex)
        if n > 1:
            if hue >= 340 or hue <= 15:
                t.semantic = "negative"
            elif 95 <= hue <= 160:
                t.semantic = "positive"
    # neutrals
    k = 0
    for t in tokens:
        if not t.roles:
            k += 1
            t.roles.append(f"neutral.{k}")
    for t in tokens:
        t.role = t.roles[0] if t.roles else None
    return tokens


# accent colours of the stock themes the office suites put into every new file: in a template that never draws
# them they are not the brand (LibreOffice green on a red-bookmark template, Office blue on an orange one)
STOCK_THEME_COLORS = frozenset(
    # LibreOffice
    "18A303 0369A3 A33E03 8E03A3 C99C00 C9211E 729FCF "
    # Office 2013–2022
    "4472C4 ED7D31 A5A5A5 FFC000 5B9BD5 70AD47 "
    # Office 2007–2010
    "4F81BD C0504D 9BBB59 8064A2 4BACC6 F79646 "
    # Office 2023+ (Aptos)
    "156082 E97132 196B24 0F9ED5 A02B93 4EA72E".split()
)


def is_stock_theme_color(hex_: str) -> bool:
    return (hex_ or "").upper() in STOCK_THEME_COLORS


def is_drawn(hex_: str, samples: list[ColorSample], tol: float = 3.0) -> bool:
    """The colour (within ΔE `tol`) is painted somewhere: a fill, a line or text of a slide, layout or master."""
    c = Color(hex=hex_)
    return any(s.context in ("fill", "line", "text") and Color.delta_e(c, Color(hex=s.hex)) <= tol for s in samples)


def has_saturated_drawn(samples: list[ColorSample]) -> bool:
    """Some saturated colour (an accent candidate) is drawn in the template."""
    return any(s.context in ("fill", "line", "text") and _saturation(s.hex) >= 0.25 and 0.05 < relative_luminance(s.hex) < 0.95 for s in samples)


def dominant_saturated_hex(rgb_pixels) -> Optional[str]:
    """The main saturated colour among pixels (N×3 array, 0–255): the median of the most populated hue sector of the
    pixels with HSV saturation ≥ 0.35 and value ≥ 0.2; None when fewer than 3 % of the pixels are saturated."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return None
    px = np.asarray(rgb_pixels, dtype=np.float32).reshape(-1, 3)
    if not len(px):
        return None
    mx = px.max(axis=1)
    mn = px.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    keep = (sat >= 0.35) & (mx >= 51)
    if keep.sum() < max(0.03 * len(px), 4):
        return None
    sel = px[keep]
    r, g, b = sel[:, 0], sel[:, 1], sel[:, 2]
    mxs, mns = sel.max(axis=1), sel.min(axis=1)
    d = np.maximum(mxs - mns, 1e-6)
    hue = np.where(mxs == r, ((g - b) / d) % 6, np.where(mxs == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    sector = (hue // 30).astype(int) % 12
    best = np.bincount(sector, minlength=12).argmax()
    med = np.median(sel[sector == best], axis=0)
    return "".join(f"{int(v):02X}" for v in med)


def nearest_palette_color(hex_: str, palette: list[str]) -> tuple[str, float]:
    c = Color(hex=hex_)
    best = min(palette, key=lambda p: Color.delta_e(c, Color(hex=p)))
    return best, Color.delta_e(c, Color(hex=best))
