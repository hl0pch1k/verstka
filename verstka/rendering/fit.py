"""Fit text into a box by stepping down the template's type scale."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from verstka.rendering.fonts import wrap_lines
from verstka.schemas.common import EMU_PER_PT, Bbox


@dataclass
class FitResult:
    size_pt: float
    fits: bool
    lines: int
    height_pt: float


def _lines_for(paragraphs: list[str], family: Optional[str], size_pt: float, bold: bool, width_pt: float) -> int:
    total = 0
    for p in paragraphs:
        total += max(len(wrap_lines(p, family, size_pt, bold, width_pt)), 1)
    return total


def fit_size(
    paragraphs: list[str],
    bbox: Bbox,
    family: Optional[str],
    size_pt: float,
    bold: bool = False,
    scale_sizes: Optional[list[float]] = None,
    insets_emu: tuple[int, int, int, int] = (91440, 45720, 91440, 45720),
    line_spacing: float = 1.2,
    para_spacing_pt: float = 0.0,
    min_ratio: float = 0.6,
) -> FitResult:
    usable_w = max((bbox.w - insets_emu[0] - insets_emu[2]) / EMU_PER_PT, 1.0)
    usable_h = max((bbox.h - insets_emu[1] - insets_emu[3]) / EMU_PER_PT, 1.0)
    candidates: list[float] = [size_pt]
    scale_c = sorted({round(s, 2) for s in (scale_sizes or []) if s < size_pt and s >= size_pt * min_ratio}, reverse=True)
    candidates.extend(scale_c)
    floor = min(scale_c) if scale_c else size_pt
    for ratio in (0.92, 0.85, 0.78, 0.7, 0.62, 0.55, 0.5):
        s = round(size_pt * ratio, 1)
        if s >= size_pt * min_ratio and s < floor and all(abs(s - c) > 0.4 for c in candidates):
            candidates.append(s)
    candidates.sort(reverse=True)
    last = FitResult(size_pt, False, 0, 0.0)
    for s in candidates:
        lines = _lines_for(paragraphs, family, s, bold, usable_w)
        height = lines * s * line_spacing + max(len(paragraphs) - 1, 0) * para_spacing_pt
        # a single line that fits the width needs the glyph height only: line spacing adds nothing below it
        fits = height <= usable_h or (lines == 1 and len(paragraphs) == 1 and usable_h >= s)
        last = FitResult(s, fits, lines, height)
        if last.fits:
            return last
    return last


def grow_size(
    paragraphs: list[str],
    bbox: Bbox,
    family: Optional[str],
    size_pt: float,
    bold: bool,
    scale_sizes: list[float],
    cap_pt: float,
    insets_emu: tuple[int, int, int, int] = (91440, 45720, 91440, 45720),
    line_spacing: float = 1.2,
    fill: float = 0.7,
) -> float:
    """The largest step of the template scale in (size_pt, cap_pt] at which the text takes at most `fill` of the box.

    Three short bullets at 12 pt in a box meant for a paragraph read as a mistake; a designer sets them larger,
    but only along the template's own scale and never past the cap of the role (body text stays body text).
    """
    usable_w = max((bbox.w - insets_emu[0] - insets_emu[2]) / EMU_PER_PT, 1.0)
    usable_h = max((bbox.h - insets_emu[1] - insets_emu[3]) / EMU_PER_PT, 1.0)
    best = size_pt
    for s in sorted({round(x, 2) for x in scale_sizes if size_pt < x <= cap_pt}):
        height = _lines_for(paragraphs, family, s, bold, usable_w) * s * line_spacing
        if height > fill * usable_h:
            break
        best = s
    return best
