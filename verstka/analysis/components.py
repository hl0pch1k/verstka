"""Component specs derived from patterns (card, bullet, number callout, icon chip, table and chart styles)."""

from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Optional

from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import EMU_PER_PT, PatternKind, ShapeKind, SlotRole, contrast_ratio, relative_luminance
from verstka.schemas.template import BulletSpec, CardSpec, ChartStyleSpec, Components, IconChipSpec, NumberSpec, Pattern, TableStyleSpec, Tokens


def _med(values: list[float]) -> Optional[float]:
    vals = [v for v in values if v]
    return round(median(vals), 2) if vals else None


def _mode(values: list) -> Optional[object]:
    vals = [v for v in values if v]
    return Counter(vals).most_common(1)[0][0] if vals else None


def _table_rule(tokens: Tokens, text_hex: str) -> Optional[str]:
    """A hairline colour for table rows: a quiet neutral of the palette on the ground the table text sits on (1.12–2.2:1,
    lighter than a dark ground), not merely the first neutral (LCT's neutral.1 is black: rows ruled like a form)."""
    dark_text = relative_luminance(text_hex) < 0.4
    ground = (tokens.color_for("background.light") or "FFFFFF") if dark_text else (tokens.color_for("background.dark") or tokens.color_for("surface") or "000000")

    def sat(h: str) -> float:
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
        return 0.0 if max(r, g, b) == 0 else (max(r, g, b) - min(r, g, b)) / max(r, g, b)

    cands = []
    for c in tokens.colors:
        if not (c.role and c.role.startswith("neutral")) or sat(c.hex) >= 0.25:
            continue
        cr = contrast_ratio(c.hex, ground)
        if not 1.12 <= cr <= 2.2 or (not dark_text and relative_luminance(c.hex) < relative_luminance(ground)):
            continue
        cands.append((abs(cr - 1.6), c.hex))
    return min(cands)[1] if cands else None


def derive_components(patterns: list[Pattern], shapes_by_slide: dict[int, list[ShapeInfo]], tokens: Tokens, *, slide_h: Optional[int] = None) -> Components:
    comp = Components()
    card_fills: list[str] = []
    card_lines: list[Optional[str]] = []
    card_radii: list[float] = []
    card_title_sizes: list[float] = []
    card_body_sizes: list[float] = []
    card_w: list[float] = []
    card_h: list[float] = []
    bullet_sizes: list[float] = []
    bullet_space_after: list[float] = []
    number_sizes: list[float] = []
    number_colors: list[str] = []
    label_sizes: list[float] = []
    chip_fills: list[str] = []
    chip_sizes: list[float] = []

    for p in patterns:
        shapes = {s.id: s for s in shapes_by_slide.get(p.source_slide, [])}
        for g in p.repeat_groups:
            for cell in g.member_shape_ids:
                anchor = shapes.get(cell[0])
                if anchor is None:
                    continue
                if anchor.kind == ShapeKind.sp and (anchor.fill_hex or anchor.line_hex) and len(cell) >= 2 and p.kind in (PatternKind.cards, PatternKind.comparison, PatternKind.process, PatternKind.stat_row, PatternKind.team):
                    if anchor.fill_hex:
                        card_fills.append(anchor.fill_hex)
                    card_lines.append(anchor.line_hex)
                    if anchor.corner_radius is not None:
                        card_radii.append(anchor.corner_radius)
                    card_w.append(g.cell_bbox.w)
                    card_h.append(g.cell_bbox.h)
                # icon chips: small ellipse/rounded rect with a picture inside
                if anchor.kind == ShapeKind.sp and anchor.geometry in ("ellipse", "roundRect") and anchor.fill_hex and anchor.bbox.w < 0.1 * 12192000:
                    if any(shapes.get(m) and shapes[m].kind == ShapeKind.pic for m in cell[1:]):
                        chip_fills.append(anchor.fill_hex)
                        chip_sizes.append(g.cell_bbox.w)
        for s in p.slots:
            if s.role == SlotRole.card_title and s.style.size_pt:
                card_title_sizes.append(s.style.size_pt)
            elif s.role == SlotRole.card_body and s.style.size_pt:
                card_body_sizes.append(s.style.size_pt)
            elif s.role == SlotRole.bullet_list and s.style.size_pt:
                bullet_sizes.append(s.style.size_pt)
                sh = shapes.get(s.shape_id)
                if sh and sh.text:
                    bullet_space_after.extend(pp.space_after_pt for pp in sh.text.paragraphs if pp.space_after_pt)
            elif s.role == SlotRole.number and s.style.size_pt:
                number_sizes.append(s.style.size_pt)
                if s.style.color_hex:
                    number_colors.append(s.style.color_hex)
            elif s.role == SlotRole.number_label and s.style.size_pt:
                label_sizes.append(s.style.size_pt)

    typo = tokens.typography
    if card_fills or card_title_sizes:
        comp.card = CardSpec(
            fill_hex=_mode(card_fills) or tokens.color_for("surface"),
            line_hex=_mode([l for l in card_lines if l]),
            radius=_med(card_radii),
            title_size_pt=_med(card_title_sizes) or typo.size_for("h2", typo.size_for("body") * 1.15),
            body_size_pt=_med(card_body_sizes) or typo.size_for("body"),
            width_frac=_med(card_w),
            height_frac=_med(card_h),
        )
    comp.bullet_item = BulletSpec(marker="•", size_pt=_med(bullet_sizes) or typo.size_for("body"), space_after_pt=_med(bullet_space_after) or 6.0)
    if number_sizes:
        comp.number_callout = NumberSpec(size_pt=_med(number_sizes), color_hex=_mode(number_colors) or tokens.color_for("accent.1"), label_size_pt=_med(label_sizes) or typo.size_for("small", typo.size_for("body")))
    else:
        comp.number_callout = NumberSpec(size_pt=typo.size_for("display", typo.size_for("h1") * 2), color_hex=tokens.color_for("accent.1"), label_size_pt=typo.size_for("small", typo.size_for("body")))
    if chip_fills:
        comp.icon_chip = IconChipSpec(bg_hex=_mode(chip_fills), size_frac=_med(chip_sizes), icon_color_hex=tokens.color_for("accent.1"))

    accent = tokens.color_for("accent.1") or "0077FF"
    text_primary = tokens.color_for("text.primary") or "000000"
    header_text = "FFFFFF" if contrast_ratio("FFFFFF", accent) >= 3.0 else text_primary
    comp.table_style = TableStyleSpec(
        header_fill_hex=accent,
        header_text_hex=header_text,
        body_text_hex=text_primary,
        band_fill_hex=tokens.color_for("surface"),
        border_hex=_table_rule(tokens, text_primary),
        font_size_pt=typo.size_for("small", typo.size_for("body") * 0.85),
        numbers_align="right",
    )
    series = tokens.accents() or [accent]
    comp.chart_style = ChartStyleSpec(
        series_colors=series[:6],
        gridlines=False,
        data_labels=True,
        font_family=typo.primary_family,
        font_size_pt=typo.size_for("small", typo.size_for("body") * 0.85),
        legend_position="bottom",
    )
    if slide_h:
        cap = data_text_cap(typo.sizes_used, slide_h)
        comp.chart_style.font_size_pt = min(comp.chart_style.font_size_pt, cap)
        comp.table_style.font_size_pt = min(comp.table_style.font_size_pt, cap)
    return comp


def data_text_cap(sizes_used: list[float], slide_h: int) -> float:
    """The largest size chart and table text may take: 2.6 % of the slide height, snapped down to the template's
    sizes (derived ladder included). Chart labels sized from a 24 pt bullet placeholder (20.4 pt on a 6.2-inch slide)
    stack category letters and push legends off the slide; the dataset templates set theirs at 1.7–2.2 % H."""
    cap = 0.026 * slide_h / EMU_PER_PT
    below = [s for s in sizes_used if 6 <= s <= cap + 1e-6]
    return max(below) if below else round(cap * 2) / 2
