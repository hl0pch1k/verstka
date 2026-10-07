"""Fit text into a box by stepping down the template's type scale."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from verstka.rendering.fonts import text_width_pt, wrap_lines
from verstka.schemas.common import EMU_PER_PT, Bbox


@dataclass
class FitResult:
    size_pt: float
    fits: bool
    lines: int
    height_pt: float  # always finite: the height of the text as it would really wrap (a broken word counts its pieces)
    broken_word: bool = False  # a word wider than the box would be broken by letters («64/0»): never a fit


_NEVER = 10 ** 6


def _measure(paragraphs: list[str], family: Optional[str], size_pt: float, bold: bool, width_pt: float, caps: bool = False, spc_pt: float = 0.0) -> tuple[int, bool]:
    """(lines the paragraphs take as they really wrap, whether a word wider than the box is broken by letters).
    `caps` / `spc_pt`: the text is set in capitals / with letter-spacing it inherits (measured as set)."""
    kw = {"caps": caps, "spc_pt": spc_pt} if (caps or spc_pt) else {}
    total, broken = 0, False
    for p in paragraphs:
        # split as `wrap_lines` breaks: at ordinary spaces only — words bound by no-break spaces («до автоматизации»)
        # are one piece, and a piece wider than the box is broken by letters
        if not broken and any(text_width_pt(w, family, size_pt, bold, **kw) > width_pt for w in re.split(r"[ \t\r\n]+", p) if w):
            broken = True
        total += max(len(wrap_lines(p, family, size_pt, bold, width_pt, **kw)), 1)
    return total, broken


def _lines_for(paragraphs: list[str], family: Optional[str], size_pt: float, bold: bool, width_pt: float) -> int:
    """Lines the paragraphs take; a word wider than the box never fits (it would be broken by letters: «64/0»)."""
    lines, broken = _measure(paragraphs, family, size_pt, bold, width_pt)
    return _NEVER if broken else lines


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
    *,
    ladder_only: bool = False,
    caps: bool = False,
    spc_pt: float = 0.0,
    head: Optional[tuple[float, bool]] = None,
) -> FitResult:
    """The largest size (the given one, then the scale's steps down to `min_ratio` of it) at which the paragraphs fit
    the box. `ladder_only`: the scale is already fine-grained (a derived ladder), no in-between ratio sizes are tried —
    they would be sizes the template does not use. When nothing fits, the smallest candidate is returned with
    fits=False and a finite height (a word too wide for the box is counted as the pieces it would break into and
    reported as `broken_word`). `head` (scale, bold): the first paragraph is a heading set over the text in the same
    box at `scale` times its size (a WorkSpace card: «Первый этап» at 20 pt bold over its text at 18 pt) — measured as
    it is set, or the box takes a line more than it was fitted for. `para_spacing_pt`: the space between paragraphs
    (the sample's spcBef/spcAft), counted between every two of them."""
    # (1.5 % of the line kept free: a line measured within a hair of the box breaks one word earlier in PowerPoint
    # and LibreOffice — «по дизайн-системе шаблона» at 198.8 pt in a 199 pt card ran a third line out of the card)
    usable_w = max((bbox.w - insets_emu[0] - insets_emu[2]) / EMU_PER_PT * 0.985, 1.0)
    usable_h = max((bbox.h - insets_emu[1] - insets_emu[3]) / EMU_PER_PT, 1.0)
    candidates: list[float] = [size_pt]
    scale_all = sorted({round(s, 2) for s in (scale_sizes or []) if s > 0})
    scale_c = sorted({s for s in scale_all if size_pt * min_ratio <= s < size_pt}, reverse=True)
    candidates.extend(scale_c)
    floor = min(scale_c) if scale_c else size_pt
    lowest = scale_all[0] if scale_all else None
    if not (ladder_only and scale_c):
        for ratio in (0.92, 0.85, 0.78, 0.7, 0.62, 0.55, 0.5):
            s = round(size_pt * ratio, 1)
            if s < size_pt * min_ratio or s >= floor:
                continue
            if lowest is not None and s >= lowest - 0.05:
                # never a size between two steps of the template's scale (Классика 40 → 24: not 36.8 / 31.2 pt): the
                # step at or under it, the next size the template sets (not under half the size); in-between sizes
                # only under the scale's smallest step, where the template has none
                s = max(x for x in scale_all if x <= s + 0.05)
                if s < 0.5 * size_pt - 0.05:
                    continue
            if all(abs(s - c) > 0.4 for c in candidates):
                candidates.append(s)
    candidates.sort(reverse=True)
    last = FitResult(size_pt, False, 0, 0.0)
    for s in candidates:
        if head and len(paragraphs) >= 2:
            l0, b0 = _measure(paragraphs[:1], family, s * head[0], head[1], usable_w, caps, spc_pt)
            l1, b1 = _measure(paragraphs[1:], family, s, bold, usable_w, caps, spc_pt)
            lines, broken = l0 + l1, b0 or b1
            height = (l0 * head[0] + l1) * s * line_spacing + (len(paragraphs) - 1) * para_spacing_pt
        else:
            lines, broken = _measure(paragraphs, family, s, bold, usable_w, caps, spc_pt)
            height = lines * s * line_spacing + max(len(paragraphs) - 1, 0) * para_spacing_pt
        # a single line that fits the width needs the glyph height only: line spacing adds nothing below it
        fits = not broken and (height <= usable_h or (lines == 1 and len(paragraphs) == 1 and usable_h >= s))
        last = FitResult(s, fits, lines, height, broken)
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
    *,
    head: Optional[tuple[float, bool]] = None,
    para_spacing_pt: float = 0.0,
) -> float:
    """The largest step of the template scale in (size_pt, cap_pt] at which the text takes at most `fill` of the box.

    Three short bullets at 12 pt in a box meant for a paragraph read as a mistake; a designer sets them larger,
    but only along the template's own scale and never past the cap of the role (body text stays body text).
    """
    # (1.5 % of the line kept free: a line measured within a hair of the box breaks one word earlier in PowerPoint
    # and LibreOffice — «по дизайн-системе шаблона» at 198.8 pt in a 199 pt card ran a third line out of the card)
    usable_w = max((bbox.w - insets_emu[0] - insets_emu[2]) / EMU_PER_PT * 0.985, 1.0)
    usable_h = max((bbox.h - insets_emu[1] - insets_emu[3]) / EMU_PER_PT, 1.0)
    best = size_pt
    for s in sorted({round(x, 2) for x in scale_sizes if size_pt < x <= cap_pt}):
        if head and len(paragraphs) >= 2:
            height = (_lines_for(paragraphs[:1], family, s * head[0], head[1], usable_w) * head[0] + _lines_for(paragraphs[1:], family, s, bold, usable_w)) * s * line_spacing
        else:
            height = _lines_for(paragraphs, family, s, bold, usable_w) * s * line_spacing
        height += max(len(paragraphs) - 1, 0) * para_spacing_pt
        if height > fill * usable_h:
            break
        best = s
    return best
