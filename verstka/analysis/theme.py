"""Resolve theme colours and fonts for a slide master."""

from __future__ import annotations

import colorsys
from functools import cached_property
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import NS, find, local_name, q
from verstka.ingest.package import PptxPackage
from verstka.schemas.common import hex_to_rgb, rgb_to_hex

_PRESET_COLORS = {
    "black": "000000", "white": "FFFFFF", "red": "FF0000", "green": "008000", "blue": "0000FF", "yellow": "FFFF00",
    "gray": "808080", "grey": "808080", "silver": "C0C0C0", "orange": "FFA500", "purple": "800080", "navy": "000080",
    "teal": "008080", "maroon": "800000", "olive": "808000", "lime": "00FF00", "aqua": "00FFFF", "fuchsia": "FF00FF",
    "ltGray": "D3D3D3", "dkGray": "A9A9A9", "darkGray": "A9A9A9", "lightGray": "D3D3D3",
}

_SYS_DEFAULTS = {"windowText": "000000", "window": "FFFFFF"}


def _apply_modifiers(hex_color: str, color_el: etree._Element) -> str:
    """Apply lumMod/lumOff/tint/shade/satMod children of a colour element."""
    r, g, b = hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    rgb = (r / 255, g / 255, b / 255)
    for child in color_el:
        tag = local_name(child)
        val = child.get("val")
        if val is None:
            continue
        try:
            v = int(val) / 100000.0
        except ValueError:
            continue
        if tag == "lumMod":
            l = max(0.0, min(1.0, l * v))
            rgb = colorsys.hls_to_rgb(h, l, s)
        elif tag == "lumOff":
            l = max(0.0, min(1.0, l + v))
            rgb = colorsys.hls_to_rgb(h, l, s)
        elif tag == "satMod":
            s = max(0.0, min(1.0, s * v))
            rgb = colorsys.hls_to_rgb(h, l, s)
        elif tag == "tint":  # mix towards white: v = fraction of original colour kept
            rgb = tuple(c * v + (1 - v) for c in rgb)
            h, l, s = colorsys.rgb_to_hls(*rgb)
        elif tag == "shade":  # mix towards black
            rgb = tuple(c * v for c in rgb)
            h, l, s = colorsys.rgb_to_hls(*rgb)
    return rgb_to_hex(rgb[0] * 255, rgb[1] * 255, rgb[2] * 255)


class ThemeResolver:
    """Colour/font resolution for shapes under one slide master."""

    def __init__(self, package: PptxPackage, master_part: str) -> None:
        self.package = package
        self.master_part = master_part
        self.theme_part = package.theme_of(master_part)

    @cached_property
    def master(self) -> etree._Element:
        return self.package.xml(self.master_part)

    @cached_property
    def theme(self) -> Optional[etree._Element]:
        return self.package.xml(self.theme_part) if self.theme_part else None

    @cached_property
    def scheme(self) -> dict[str, str]:
        out: dict[str, str] = {}
        cs = find(self.theme, ".//a:clrScheme") if self.theme is not None else None
        if cs is None:
            return {"dk1": "000000", "lt1": "FFFFFF", "dk2": "44546A", "lt2": "E7E6E6", "accent1": "4472C4", "accent2": "ED7D31",
                    "accent3": "A5A5A5", "accent4": "FFC000", "accent5": "5B9BD5", "accent6": "70AD47", "hlink": "0563C1", "folHlink": "954F72"}
        for entry in cs:
            name = local_name(entry)
            if len(entry) == 0:
                continue
            c = entry[0]
            tag = local_name(c)
            if tag == "srgbClr":
                out[name] = (c.get("val") or "000000").upper()
            elif tag == "sysClr":
                out[name] = (c.get("lastClr") or _SYS_DEFAULTS.get(c.get("val") or "", "000000")).upper()
        return out

    @cached_property
    def clr_map(self) -> dict[str, str]:
        cm = find(self.master, "p:clrMap")
        default = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2", "accent1": "accent1", "accent2": "accent2", "accent3": "accent3",
                   "accent4": "accent4", "accent5": "accent5", "accent6": "accent6", "hlink": "hlink", "folHlink": "folHlink"}
        if cm is None:
            return default
        return {**default, **{k: v for k, v in cm.attrib.items()}}

    def scheme_hex(self, name: str) -> Optional[str]:
        mapped = self.clr_map.get(name, name)
        return self.scheme.get(mapped) or self.scheme.get(name)

    @cached_property
    def major_font(self) -> str:
        el = find(self.theme, ".//a:fontScheme/a:majorFont/a:latin") if self.theme is not None else None
        return (el.get("typeface") if el is not None else None) or "Calibri"

    @cached_property
    def minor_font(self) -> str:
        el = find(self.theme, ".//a:fontScheme/a:minorFont/a:latin") if self.theme is not None else None
        return (el.get("typeface") if el is not None else None) or "Calibri"

    def font_for(self, typeface: Optional[str]) -> Optional[str]:
        if not typeface:
            return None
        if typeface.startswith("+mj"):
            return self.major_font
        if typeface.startswith("+mn"):
            return self.minor_font
        return typeface

    # ---- colours ---------------------------------------------------------------
    def resolve_color(self, color_el: Optional[etree._Element]) -> Optional[str]:
        """color_el is one of a:srgbClr, a:schemeClr, a:sysClr, a:prstClr, a:scrgbClr, a:hslClr."""
        if color_el is None:
            return None
        tag = local_name(color_el)
        base: Optional[str] = None
        if tag == "srgbClr":
            base = (color_el.get("val") or "").upper()
        elif tag == "schemeClr":
            base = self.scheme_hex(color_el.get("val") or "")
        elif tag == "sysClr":
            base = (color_el.get("lastClr") or _SYS_DEFAULTS.get(color_el.get("val") or "", None) or "").upper() or None
        elif tag == "prstClr":
            base = _PRESET_COLORS.get(color_el.get("val") or "")
        elif tag == "scrgbClr":
            try:
                r = int(color_el.get("r", "0")) / 100000 * 255
                g = int(color_el.get("g", "0")) / 100000 * 255
                b = int(color_el.get("b", "0")) / 100000 * 255
                base = rgb_to_hex(r, g, b)
            except ValueError:
                base = None
        elif tag == "hslClr":
            try:
                h = int(color_el.get("hue", "0")) / 60000 / 360
                s = int(color_el.get("sat", "0")) / 100000
                l = int(color_el.get("lum", "0")) / 100000
                r, g, b = colorsys.hls_to_rgb(h, l, s)
                base = rgb_to_hex(r * 255, g * 255, b * 255)
            except ValueError:
                base = None
        if not base or len(base) != 6:
            return None
        return _apply_modifiers(base, color_el)

    def resolve_fill(self, parent: Optional[etree._Element]) -> Optional[str]:
        """First solid colour under parent (solidFill, or first gradient stop). None for noFill/absent."""
        if parent is None:
            return None
        sf = find(parent, "a:solidFill")
        if sf is not None and len(sf):
            return self.resolve_color(sf[0])
        gf = find(parent, "a:gradFill")
        if gf is not None:
            gs = find(gf, "a:gsLst/a:gs")
            if gs is not None and len(gs):
                return self.resolve_color(gs[0])
        return None

    def has_no_fill(self, parent: Optional[etree._Element]) -> bool:
        return parent is not None and find(parent, "a:noFill") is not None
