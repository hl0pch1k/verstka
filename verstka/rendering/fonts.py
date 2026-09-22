"""Font metrics for text fitting (bundled Play, OFL) with width factors for other common families."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import ImageFont

FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"

# relative average width vs Play for families we cannot bundle (empirical, conservative)
_WIDTH_FACTORS = {
    "play": 1.0,
    "arial": 1.0,
    "helvetica": 1.0,
    "calibri": 0.93,
    "segoe ui": 0.98,
    "roboto": 0.98,
    "inter": 1.03,
    "montserrat": 1.2,  # a wide geometric sans: 1.08 let LCT headings overflow their pills
    "vk sans display": 1.02,
    "vk sans": 1.0,
    "golos": 1.02,
    "pt sans": 0.98,
    "open sans": 1.08,
    "verdana": 1.25,
    "tahoma": 1.05,
    "georgia": 1.12,
    "consolas": 1.12,
    "courier new": 1.2,
    "times new roman": 0.92,
}
_UNKNOWN_FACTOR = 1.08  # a family we cannot measure is assumed a little wider than Play: overflow costs more than air
_MEASURE_PX = 64  # render size used for measuring; widths scale linearly


def font_path(family: Optional[str] = None, bold: bool = False) -> Path:
    name = "Play-Bold.ttf" if bold else "Play-Regular.ttf"
    return FONT_DIR / name


def width_factor(family: Optional[str]) -> float:
    if not family:
        return 1.0
    key = family.lower().strip()
    if key.startswith("+"):
        return 1.0  # a theme font reference: resolved elsewhere, measured as Play
    for k, v in _WIDTH_FACTORS.items():
        if key.startswith(k):
            return v
    return _UNKNOWN_FACTOR


@lru_cache(maxsize=8)
def _font(bold: bool) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path(None, bold)), _MEASURE_PX)


def text_width_pt(text: str, family: Optional[str], size_pt: float, bold: bool = False) -> float:
    if not text:
        return 0.0
    f = _font(bold)
    px = f.getlength(text)
    return px / _MEASURE_PX * size_pt * width_factor(family)


def wrap_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float) -> list[str]:
    """Greedy word wrap; over-long words are split by characters."""
    if width_pt <= 0:
        return [text]
    lines: list[str] = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip()
            if text_width_pt(cand, family, size_pt, bold) <= width_pt:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            if text_width_pt(w, family, size_pt, bold) <= width_pt:
                cur = w
            else:
                piece = ""
                for ch in w:
                    if text_width_pt(piece + ch, family, size_pt, bold) <= width_pt:
                        piece += ch
                    else:
                        lines.append(piece)
                        piece = ch
                cur = piece
        lines.append(cur)
    return lines


def measure_text_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float) -> int:
    return len(wrap_lines(text, family, size_pt, bold, width_pt))
