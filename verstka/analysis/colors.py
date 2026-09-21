"""Colour tokens: collect, cluster and assign roles."""

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
        if s.line_hex:
            out.append(ColorSample(s.line_hex.upper(), "line", 0.5))
        if s.text:
            for p in s.text.paragraphs:
                for r in p.runs:
                    if r.color_hex and r.text.strip():
                        out.append(ColorSample(r.color_hex.upper(), "text", max(len(r.text) / 50.0, 0.05)))
    return out


def cluster_colors(samples: list[ColorSample], delta_e_tol: float = 1.8) -> list[ColorToken]:
    """Greedy clustering by ΔE (tight: visually identical only, so white cards on an off-white background stay distinct);
    the heaviest observed hex represents each cluster (keeps exact brand colours)."""
    by_hex: dict[str, float] = defaultdict(float)
    ctx_by_hex: dict[str, Counter] = defaultdict(Counter)
    for s in samples:
        by_hex[s.hex] += s.weight
        ctx_by_hex[s.hex][s.context] += 1
    ordered = sorted(by_hex.items(), key=lambda kv: -kv[1])
    clusters: list[dict] = []
    for hex_, w in ordered:
        c = Color(hex=hex_)
        placed = False
        for cl in clusters:
            if Color.delta_e(c, cl["color"]) <= delta_e_tol:
                cl["weight"] += w
                cl["contexts"].update(ctx_by_hex[hex_])
                cl["members"].append(hex_)
                placed = True
                break
        if not placed:
            clusters.append({"color": c, "hex": hex_, "weight": w, "contexts": Counter(ctx_by_hex[hex_]), "members": [hex_]})
    tokens = [ColorToken(hex=cl["hex"], weight=round(cl["weight"], 3), contexts=dict(cl["contexts"])) for cl in clusters]
    tokens.sort(key=lambda t: -t.weight)
    return tokens


def _saturation(hex_: str) -> float:
    r, g, b = hex_to_rgb(hex_)
    _, _, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return s


def _hue_deg(hex_: str) -> float:
    r, g, b = hex_to_rgb(hex_)
    h, _, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return h * 360


def assign_color_roles(tokens: list[ColorToken], primary_family: Family = Family.light) -> list[ColorToken]:
    """Assign background/text/surface/accent roles in place and return the list."""
    for t in tokens:
        t.role = None
    if not tokens:
        return tokens

    def ctx_weight(t: ColorToken, ctx: str) -> float:
        return t.weight * (t.contexts.get(ctx, 0) / max(sum(t.contexts.values()), 1))

    # backgrounds
    light_bgs = [t for t in tokens if t.contexts.get("background") and relative_luminance(t.hex) >= 0.3]
    dark_bgs = [t for t in tokens if t.contexts.get("background") and relative_luminance(t.hex) < 0.3]
    bg_light = max(light_bgs, key=lambda t: t.contexts["background"], default=None)
    bg_dark = max(dark_bgs, key=lambda t: t.contexts["background"], default=None)
    if bg_light is None and primary_family == Family.light:
        bg_light = ColorToken(hex="FFFFFF", weight=0.0, contexts={"background": 0})
        tokens.append(bg_light)
    if bg_dark is None and primary_family == Family.dark:
        bg_dark = ColorToken(hex="000000", weight=0.0, contexts={"background": 0})
        tokens.append(bg_dark)
    if bg_light is not None:
        bg_light.role = "background.light"
    if bg_dark is not None:
        bg_dark.role = "background.dark"
    primary_bg = (bg_dark if primary_family == Family.dark else bg_light) or bg_light or bg_dark
    bg_hex = primary_bg.hex if primary_bg else "FFFFFF"

    # text colours
    text_tokens = sorted([t for t in tokens if t.role is None and t.contexts.get("text")], key=lambda t: -ctx_weight(t, "text"))
    primary_text = next((t for t in text_tokens if contrast_ratio(t.hex, bg_hex) >= 4.5), None)
    if primary_text is not None:
        primary_text.role = "text.primary"
        secondary = next(
            (t for t in text_tokens if t is not primary_text and contrast_ratio(t.hex, bg_hex) >= 3.0 and Color.delta_e(Color(hex=t.hex), Color(hex=primary_text.hex)) > 10 and _saturation(t.hex) < 0.35),
            None,
        )
        if secondary is not None:
            secondary.role = "text.secondary"

    # surface: a fill close to the background but distinct
    surfaces = [t for t in tokens if t.role is None and t.contexts.get("fill") and 1.0 < contrast_ratio(t.hex, bg_hex) < 1.6]
    if surfaces:
        max(surfaces, key=lambda t: ctx_weight(t, "fill")).role = "surface"

    # accents: saturated colours by weight
    accents = [t for t in tokens if t.role is None and _saturation(t.hex) >= 0.25 and 0.05 < relative_luminance(t.hex) < 0.95]
    accents.sort(key=lambda t: -(t.weight * (0.5 + _saturation(t.hex))))
    n = 0
    for t in accents:
        n += 1
        if n <= 6:
            t.role = f"accent.{n}"
    # semantic hints: a red-ish and a green-ish accent that are not the primary accent
    for t in tokens:
        if t.role and t.role.startswith("accent.") and t.role != "accent.1":
            hue = _hue_deg(t.hex)
            if hue >= 340 or hue <= 15:
                t.role = t.role + "|semantic.negative"
            elif 95 <= hue <= 160:
                t.role = t.role + "|semantic.positive"
    # neutrals
    k = 0
    for t in tokens:
        if t.role is None:
            k += 1
            t.role = f"neutral.{k}"
    return tokens


def nearest_palette_color(hex_: str, palette: list[str]) -> tuple[str, float]:
    c = Color(hex=hex_)
    best = min(palette, key=lambda p: Color.delta_e(c, Color(hex=p)))
    return best, Color.delta_e(c, Color(hex=best))
