"""Shared geometry, colour and enum types used by all schemas.

Geometry inside the package is always EMU (English Metric Units, 914400 per inch).
Pattern comparisons use fractions of the slide size (0..1).
"""

from __future__ import annotations

import math
from enum import Enum

from pydantic import BaseModel, field_validator

EMU_PER_INCH = 914400
EMU_PER_PT = 12700


class Bbox(BaseModel):
    """Axis-aligned box in EMU."""

    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def area(self) -> int:
        return max(self.w, 0) * max(self.h, 0)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def contains_point(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2

    def intersection(self, other: "Bbox") -> int:
        ix = max(0, min(self.x2, other.x2) - max(self.x, other.x))
        iy = max(0, min(self.y2, other.y2) - max(self.y, other.y))
        return ix * iy

    def iou(self, other: "Bbox") -> float:
        inter = self.intersection(other)
        union = self.area + other.area - inter
        return inter / union if union else 0.0

    def union(self, other: "Bbox") -> "Bbox":
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        return Bbox(x=x, y=y, w=max(self.x2, other.x2) - x, h=max(self.y2, other.y2) - y)

    def to_frac(self, slide_w: int, slide_h: int) -> "BboxFrac":
        return BboxFrac(x=self.x / slide_w, y=self.y / slide_h, w=self.w / slide_w, h=self.h / slide_h)


class BboxFrac(BaseModel):
    """Box as fractions of slide width/height."""

    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)

    def intersection(self, other: "BboxFrac") -> float:
        ix = max(0.0, min(self.x2, other.x2) - max(self.x, other.x))
        iy = max(0.0, min(self.y2, other.y2) - max(self.y, other.y))
        return ix * iy

    def close_to(self, other: "BboxFrac", tol: float = 0.01) -> bool:
        return (
            abs(self.x - other.x) <= tol
            and abs(self.y - other.y) <= tol
            and abs(self.w - other.w) <= tol
            and abs(self.h - other.h) <= tol
        )

    def to_emu(self, slide_w: int, slide_h: int) -> Bbox:
        return Bbox(x=round(self.x * slide_w), y=round(self.y * slide_h), w=round(self.w * slide_w), h=round(self.h * slide_h))


def _srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(r: int, g: int, b: int) -> str:
    clamp = lambda v: max(0, min(255, int(round(v))))  # noqa: E731
    return f"{clamp(r):02X}{clamp(g):02X}{clamp(b):02X}"


def rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    rl, gl, bl = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x = (rl * 0.4124 + gl * 0.3576 + bl * 0.1805) / 0.95047
    y = (rl * 0.2126 + gl * 0.7152 + bl * 0.0722) / 1.00000
    z = (rl * 0.0193 + gl * 0.1192 + bl * 0.9505) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def lab_to_rgb(L: float, a: float, b: float) -> tuple[int, int, int]:
    fy = (L + 16) / 116
    fx = a / 500 + fy
    fz = fy - b / 200

    def finv(t: float) -> float:
        t3 = t**3
        return t3 if t3 > 0.008856 else (t - 16 / 116) / 7.787

    x = finv(fx) * 0.95047
    y = finv(fy) * 1.00000
    z = finv(fz) * 1.08883
    rl = x * 3.2406 + y * -1.5372 + z * -0.4986
    gl = x * -0.9689 + y * 1.8758 + z * 0.0415
    bl = x * 0.0557 + y * -0.2040 + z * 1.0570

    def gamma(c: float) -> float:
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055

    return (round(gamma(rl) * 255), round(gamma(gl) * 255), round(gamma(bl) * 255))


def relative_luminance(hex_str: str) -> float:
    r, g, b = hex_to_rgb(hex_str)
    return 0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g) + 0.0722 * _srgb_to_linear(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class Color(BaseModel):
    """Normalized 6-digit uppercase hex colour."""

    hex: str

    @field_validator("hex")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = v.strip().lstrip("#").upper()
        if len(v) == 3:
            v = "".join(ch * 2 for ch in v)
        if len(v) == 8:  # ARGB → drop alpha
            v = v[2:]
        if len(v) != 6 or any(ch not in "0123456789ABCDEF" for ch in v):
            raise ValueError(f"invalid hex colour: {v!r}")
        return v

    def to_rgb(self) -> tuple[int, int, int]:
        return hex_to_rgb(self.hex)

    def to_lab(self) -> tuple[float, float, float]:
        return rgb_to_lab(*self.to_rgb())

    @property
    def luminance(self) -> float:
        return relative_luminance(self.hex)

    @staticmethod
    def delta_e(a: "Color", b: "Color") -> float:
        la, lb = a.to_lab(), b.to_lab()
        return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb)))


class ShapeKind(str, Enum):
    sp = "sp"
    pic = "pic"
    graphic_frame = "graphic_frame"
    group = "group"
    connector = "connector"


class SlotRole(str, Enum):
    title = "title"
    subtitle = "subtitle"
    body = "body"
    bullet_list = "bullet_list"
    card_title = "card_title"
    card_body = "card_body"
    number = "number"
    number_label = "number_label"
    caption = "caption"
    image = "image"
    icon = "icon"
    decoration = "decoration"
    chrome = "chrome"


class PatternKind(str, Enum):
    title = "title"
    section = "section"
    agenda = "agenda"
    bullets = "bullets"
    cards = "cards"
    two_column = "two_column"
    big_number = "big_number"
    stat_row = "stat_row"
    comparison = "comparison"
    timeline = "timeline"
    process = "process"
    table = "table"
    chart = "chart"
    image_text = "image_text"
    team = "team"
    quote = "quote"
    code = "code"
    mockup = "mockup"
    thanks = "thanks"
    freeform = "freeform"


class Family(str, Enum):
    light = "light"
    dark = "dark"
