"""Inline SVG charts from IRChart (bar, column, line, area, pie, doughnut), drawn to the same design as the native
charts of verstka.rendering.charts, so the web version and the PPTX read as one deck: each bar and slice in the colour
the chart gives it (the highlight in the accent, the rest stepped back), the labels exactly as the chart formats them
(the unit once, Russian number format: «12 400», «4,8»), zero labels hidden, a hairline baseline, square bars, pie
slices parted by gaps rather than by strokes of a guessed background colour, the unit caption at the top left."""

from __future__ import annotations

import html
import math
from typing import Optional

from verstka.rendering.fonts import text_width_pt, wrap_lines
from verstka.schemas.deck_ir import IRChart, IRChartSeries, IRPointLabel

_MINUS = "−"


# ---------------------------------------------------------------------------------------------- numbers


def _sections(code: str) -> list[str]:
    out, cur, quoted = [], "", False
    for ch in code:
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _render_section(v: float, sec: str) -> str:
    """One number-format section applied to |v|: literals kept, digits grouped and decimals as Russian text does."""
    pre, suf, num = "", "", ""
    pct = False
    i = 0
    seen_digit = False
    while i < len(sec):
        ch = sec[i]
        if ch == '"':
            j = sec.find('"', i + 1)
            lit = sec[i + 1 : j if j >= 0 else len(sec)]
            i = (j + 1) if j >= 0 else len(sec)
        elif ch == "\\" and i + 1 < len(sec):
            lit = sec[i + 1]
            i += 2
        elif ch == "[":
            j = sec.find("]", i)
            i = (j + 1) if j >= 0 else len(sec)
            continue
        elif ch in "0#?,." and (seen_digit or ch in "0#?"):
            num += ch
            seen_digit = True
            i += 1
            continue
        elif ch == "%":
            pct = True
            lit = "%"
            i += 1
        elif ch in "_*":
            i += 2
            continue
        else:
            lit = ch
            i += 1
        if seen_digit:
            suf += lit
        else:
            pre += lit
    val = abs(v) * (100 if pct else 1)
    if not num:
        return pre + suf
    int_part, _, dec_part = num.partition(".")
    decimals = sum(1 for c in dec_part if c in "0#?")
    group = "," in int_part
    s = f"{val:,.{decimals}f}" if group else f"{val:.{decimals}f}"
    s = s.replace(",", " ").replace(".", ",")
    return pre + s + suf


def format_value(v: Optional[float], code: Optional[str]) -> str:
    """A value as an Excel number format prints it, in the Russian convention (space-grouped thousands, a decimal
    comma, a true minus), honouring an empty zero section; «General» shows up to two decimals."""
    if v is None:
        return ""
    if not code or code.strip().lower() == "general":
        s = f"{abs(v):,.2f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else f"{abs(v):,.0f}"
        return (_MINUS if v < 0 else "") + s.replace(",", " ").replace(".", ",")
    secs = _sections(code)
    if v > 0 or (v < 0 and len(secs) == 1) or (v == 0 and len(secs) < 3):
        body = _render_section(v, secs[0])
        return (_MINUS + body) if v < 0 else body
    if v < 0:
        return _render_section(v, secs[1])
    return _render_section(v, secs[2]) if secs[2] else ""


def _nice(lo: float, hi: float) -> tuple[float, float, float]:
    if hi <= lo:
        hi = lo + (abs(lo) or 1.0)
    raw = (hi - lo) / 4.5
    mag = 10 ** math.floor(math.log10(raw))
    step = next((b * mag for b in (1, 2, 2.5, 5, 10) if b * mag >= raw), 10 * mag)
    return math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step, step


# ---------------------------------------------------------------------------------------------- drawing helpers


def _txt(x: float, y: float, s: str, size: float, color: str, anchor: str = "middle", bold: bool = False, baseline: str = "middle") -> str:
    w = ' font-weight="700"' if bold else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}" fill="#{color}" text-anchor="{anchor}" dominant-baseline="{baseline}"{w}>{html.escape(s)}</text>'


def _width(s: str, size: float, bold: bool = False) -> float:
    return text_width_pt(s, None, size, bold) * 1.05


def _lines_txt(x: float, y: float, lines: list[str], size: float, color: str, anchor: str) -> str:
    """Several lines centred on y."""
    lh = size * 1.2
    y0 = y - lh * (len(lines) - 1) / 2
    spans = "".join(f'<tspan x="{x:.1f}" y="{y0 + i * lh:.1f}">{html.escape(t)}</tspan>' for i, t in enumerate(lines))
    return f'<text font-size="{size:.1f}" fill="#{color}" text-anchor="{anchor}" dominant-baseline="middle">{spans}</text>'


def _cat_step(cats: list[str], slot: float, size: float) -> int:
    """Show every k-th category label when they would run into each other (a line is continuous)."""
    longest = max((_width(c, size) for c in cats), default=0.0)
    return max(1, math.ceil(longest / (slot * 0.9))) if longest > slot * 0.9 else 1


def _legend_rows(parts: list, items: list[tuple[str, str, bool]], width: float, y_bottom: float, size: float, muted: str) -> None:
    """A bottom legend, wrapped into centred rows; items = (name, colour, hollow)."""
    rows: list[list] = [[]]
    used = 0.0
    for it in items:
        w = _width(it[0], size) + size * 2.2
        if rows[-1] and used + w > width:
            rows.append([])
            used = 0.0
        rows[-1].append((it, w))
        used += w
    for r, row in enumerate(rows):
        total = sum(w for _, w in row)
        lx = max(0.0, (width - total) / 2)
        ly = y_bottom - (len(rows) - 1 - r) * size * 1.5
        for (name, col, hollow), w in row:
            fill = "none" if hollow else f"#{col}"
            parts.append(f'<rect x="{lx:.1f}" y="{ly - size * 0.35:.1f}" width="{size * 0.7:.1f}" height="{size * 0.7:.1f}" fill="{fill}" stroke="#{col}" stroke-width="{1 if hollow else 0}"/>')
            parts.append(_txt(lx + size, ly, name, size, muted, anchor="start"))
            lx += w


class _Labels:
    """What each point's label says and how it looks, from the series' c:dLbls and its per-point overrides."""

    def __init__(self, chart: IRChart, text_hex: str, font_px: float):
        self.chart, self.text, self.size = chart, text_hex, font_px

    def get(self, s: IRChartSeries, j: int) -> Optional[tuple[str, str, bool, float, Optional[str]]]:
        v = s.values[j] if j < len(s.values) else None
        pl: Optional[IRPointLabel] = s.point_labels.get(j)
        if pl is not None and pl.deleted:
            return None
        shown = pl is not None or (s.labels_shown if s.labels_shown is not None else self.chart.has_data_labels)
        if not shown or v is None:
            return None
        fmt = (pl.format if pl is not None and pl.format else None) or s.label_format or self.chart.number_format
        t = format_value(v, fmt)
        if pl is not None and pl.series_name:
            t = f"{s.name}: {t}" if t else s.name
        if not t:
            return None
        color = (pl.color if pl is not None and pl.color else None) or s.label_color or self.text
        bold = bool(pl.bold if pl is not None and pl.bold is not None else s.label_bold)
        size = (pl.size_pt if pl is not None and pl.size_pt else None) or s.label_size_pt or self.size
        return t, color, bold, size, (pl.position if pl is not None else None)


def _series_color(chart: IRChart, s: IRChartSeries, k: int, colors: list[str]) -> str:
    return s.color or (chart.colors[k] if k < len(chart.colors) else None) or colors[k % len(colors)]


# ---------------------------------------------------------------------------------------------- the chart


def chart_svg(chart: IRChart, width: float, height: float, colors: list[str], text_hex: str = "222222", font: str = "Play, Arial, sans-serif", font_px: float = 12.0) -> str:
    colors = [c for c in (colors or []) if c] or ["0077FF"]
    series = chart.series or []
    cats = chart.categories or []
    n_cat = max(len(cats), max((len(s.values) for s in series), default=0))
    muted = chart.axis_color or text_hex
    rule = chart.rule_color
    labels = _Labels(chart, text_hex, font_px)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="100%" height="100%" font-family="{html.escape(font)}" font-size="{font_px}" fill="#{text_hex}">']
    top = 2.0
    if chart.title:
        parts.append(_txt(0, font_px * 0.7, chart.title, font_px, muted, anchor="start"))
        top += font_px * 1.6
    k_ser = len(series)
    legend_names = [s.name for s in series] if (chart.has_legend and k_ser > 1 and chart.type not in ("pie", "doughnut")) else []
    bottom_legend = font_px * 1.9 if legend_names else 0.0
    if legend_names and sum(_width(nm, font_px) + font_px * 2.2 for nm in legend_names) > width:
        bottom_legend += font_px * 1.5

    if chart.type in ("pie", "doughnut") and series:
        parts += _pie(chart, series[0], cats, width, height, top, colors, text_hex, muted, font_px, labels)
        parts.append("</svg>")
        return "".join(parts)

    all_vals = [v for s in series for v in s.values if v is not None]
    vmax = max(all_vals + [0.0])
    vmin = min(all_vals + [0.0])
    base_rule = f'stroke="#{rule}"' if rule else f'stroke="#{text_hex}" stroke-opacity="0.25"'
    if chart.type == "bar":
        parts += _hbars(chart, series, cats, n_cat, width, height - bottom_legend, top, colors, muted, base_rule, font_px, labels, vmin, vmax)
    elif chart.type in ("line", "area"):
        parts += _lines(chart, series, cats, n_cat, width, height - bottom_legend, top, colors, text_hex, muted, font_px, labels, vmin, vmax)
    else:
        parts += _columns(chart, series, cats, n_cat, width, height - bottom_legend, top, colors, muted, base_rule, font_px, labels, vmin, vmax)
    if legend_names:
        _legend_rows(parts, [(s.name, _series_color(chart, s, k, colors), s.outline_only) for k, s in enumerate(series)], width, height - font_px * 0.7, font_px, muted)
    parts.append("</svg>")
    return "".join(parts)


def _value_axis(parts: list, x0: float, x1: float, y_of, lo: float, hi: float, step: float, muted: str, font_px: float, fmt: Optional[str]) -> None:
    v = lo
    while v <= hi + step * 1e-6:
        y = y_of(v)
        parts.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="#{muted}" stroke-opacity="0.18" stroke-width="0.5"/>')
        t = format_value(v, fmt) if v else "0"
        parts.append(_txt(x0 - font_px * 0.5, y, t, font_px, muted, anchor="end"))
        v += step


def _plain_tick_format(chart: IRChart) -> Optional[str]:
    fmt = chart.number_format or ""
    return '0"%"' if "%" in fmt else "#,##0"


def _columns(chart, series, cats, n_cat, width, height, top, colors, muted, base_rule, font_px, labels, vmin, vmax) -> list:
    parts: list = []
    k_ser = max(len(series), 1)
    label_room = max((labels.get(s, j) or ("", "", False, font_px, None))[3] for s in series for j in range(len(s.values))) if series else font_px
    left = 0.0
    lo, hi = vmin, vmax
    if chart.has_value_axis:
        lo, hi, step = _nice(vmin, vmax)
        left = _width(format_value(hi, "#,##0"), font_px) + font_px
    pad_t = top + label_room * 1.6
    pad_b = font_px * 2.2 + (label_room * 1.5 if vmin < 0 else 0.0)
    pw, ph = width - left - 2, height - pad_t - pad_b
    span = (hi - lo) or 1.0
    y_of = lambda v: pad_t + ph * (hi - v) / span  # noqa: E731
    if chart.has_value_axis:
        _value_axis(parts, left, width, y_of, lo, hi, step, muted, font_px, _plain_tick_format(chart))
    slot = pw / max(n_cat, 1)
    group = min(slot / 1.7, width * 0.16 * min(k_ser, 3) * 0.9 if k_ser > 1 else width * 0.16)
    bar = group / k_ser
    for i in range(n_cat):
        x_g = left + i * slot + (slot - group) / 2
        for k, s in enumerate(series):
            v = s.values[i] if i < len(s.values) else None
            if v is None:
                continue
            col = s.point_colors.get(i) or _series_color(chart, s, k, colors)
            y0, y1 = sorted((y_of(0.0), y_of(v)))
            x = x_g + k * bar
            gap = bar * 0.08 if k_ser > 1 else 0.0
            if s.outline_only:
                parts.append(f'<rect x="{x + gap / 2 + 0.75:.1f}" y="{y0 + 0.75:.1f}" width="{max(0.0, bar - gap - 1.5):.1f}" height="{max(0.0, y1 - y0 - 0.75):.1f}" fill="none" stroke="#{col}" stroke-width="1.5"/>')
            else:
                parts.append(f'<rect x="{x + gap / 2:.1f}" y="{y0:.1f}" width="{bar - gap:.1f}" height="{y1 - y0:.1f}" fill="#{col}"/>')
            lab = labels.get(s, i)
            if lab:
                t, c, b, size, _ = lab
                y = (y0 - size * 0.7) if v >= 0 else (y1 + size * 0.8)
                parts.append(_txt(x + bar / 2, y, t, size, c, bold=b))
        if i < len(cats) and i % _cat_step(cats, slot, font_px) == 0:
            parts.append(_txt(left + i * slot + slot / 2, height - font_px * 1.0, cats[i], font_px, muted))
    y_base = y_of(0.0)
    parts.append(f'<line x1="{left:.1f}" y1="{y_base:.1f}" x2="{left + pw:.1f}" y2="{y_base:.1f}" {base_rule} stroke-width="0.75"/>')
    return parts


def _hbars(chart, series, cats, n_cat, width, height, top, colors, muted, base_rule, font_px, labels, vmin, vmax) -> list:
    parts: list = []
    k_ser = max(len(series), 1)
    cat_w = min(max((_width(c, font_px) for c in cats), default=20.0), width * 0.36)
    wrapped = [wrap_lines(c, None, font_px, False, cat_w / 1.05)[:3] for c in cats]
    lab_w = max((_width(lab[0], lab[3], lab[2]) for s in series for j in range(len(s.values)) if (lab := labels.get(s, j))), default=0.0)
    left = cat_w + font_px * 0.8
    pw = max(width - left - lab_w - font_px * 0.8, width * 0.3)
    ph = height - top - font_px * 0.6
    span = (vmax - min(vmin, 0.0)) or 1.0
    x_of = lambda v: left + pw * (v - min(vmin, 0.0)) / span  # noqa: E731
    row = ph / max(n_cat, 1)
    group = min(row / 1.7, font_px * 2.6 * (min(k_ser, 3) * 0.9 if k_ser > 1 else 1))
    bar = group / k_ser
    for i in range(n_cat):
        y_g = top + i * row + (row - group) / 2
        for k, s in enumerate(series):
            v = s.values[i] if i < len(s.values) else None
            if v is None:
                continue
            col = s.point_colors.get(i) or _series_color(chart, s, k, colors)
            x0, x1 = sorted((x_of(0.0), x_of(v)))
            y = y_g + k * bar
            gap = bar * 0.08 if k_ser > 1 else 0.0
            if s.outline_only:
                parts.append(f'<rect x="{x0:.1f}" y="{y + gap / 2 + 0.75:.1f}" width="{max(0.0, x1 - x0 - 0.75):.1f}" height="{max(0.0, bar - gap - 1.5):.1f}" fill="none" stroke="#{col}" stroke-width="1.5"/>')
            elif x1 > x0:
                parts.append(f'<rect x="{x0:.1f}" y="{y + gap / 2:.1f}" width="{x1 - x0:.1f}" height="{bar - gap:.1f}" fill="#{col}"/>')
            lab = labels.get(s, i)
            if lab:
                t, c, b, size, _ = lab
                parts.append(_txt(x1 + size * 0.4, y + bar / 2, t, size, c, anchor="start", bold=b))
        if i < len(cats):
            parts.append(_lines_txt(cat_w, top + i * row + row / 2, wrapped[i], font_px, muted, "end"))
    if vmin < 0:
        x = x_of(0.0)
        parts.append(f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{top + ph:.1f}" {base_rule} stroke-width="0.75"/>')
    return parts


def _lines(chart, series, cats, n_cat, width, height, top, colors, text_hex, muted, font_px, labels, vmin, vmax) -> list:
    parts: list = []
    data = [v for s in series for v in s.values if v is not None]
    vmin = min(data) if data else vmin
    lo, hi = min(vmin, 0.0) if vmin < 0 else vmin, vmax
    left = 2.0
    if chart.has_value_axis:
        lo, hi, step = _nice(0.0 if (vmin >= 0 and (chart.type == "area" or vmin <= 0.45 * vmax)) else vmin, vmax)
        left = _width(format_value(hi, "#,##0"), font_px) + font_px
    elif vmin > 0:
        lo = 0.0 if vmin <= 0.45 * vmax else vmin - (vmax - vmin) * 0.25
    end_w = max((_width(lab[0], lab[3], lab[2]) for s in series if s.values and (lab := labels.get(s, len(s.values) - 1)) and (lab[4] == "r")), default=0.0)
    pad_t = top + font_px * 1.8
    pad_b = font_px * 2.2
    pw = width - left - max(end_w + font_px, font_px * 1.5)
    ph = height - pad_t - pad_b
    span = (hi - lo) or 1.0
    step_x = pw / max(n_cat, 1)
    x_of = lambda j: left + (j + 0.5) * step_x  # noqa: E731
    y_of = lambda v: pad_t + ph * (hi - v) / span  # noqa: E731
    if chart.has_value_axis:
        _value_axis(parts, left, left + pw, y_of, lo, hi, step, muted, font_px, _plain_tick_format(chart))
    # end labels right of the last point, pushed apart where two lines end close together
    ends = {}
    for k, s in enumerate(series):
        j = len(s.values) - 1
        lab = labels.get(s, j) if j >= 0 else None
        if lab and lab[4] == "r" and s.values[j] is not None:
            ends[k] = y_of(s.values[j])
    lab_h = font_px * 1.25
    moved = dict(ends)
    order = sorted(ends, key=lambda k: ends[k])
    for _ in range(30):
        for a, b in zip(order, order[1:]):
            if moved[b] - moved[a] < lab_h:
                push = (lab_h - (moved[b] - moved[a])) / 2 + 0.01
                moved[a] -= push
                moved[b] += push
    for k, s in enumerate(series):
        col = _series_color(chart, s, k, colors)
        pts = [(x_of(j), y_of(v)) for j, v in enumerate(s.values) if v is not None]
        if not pts:
            continue
        if chart.type == "area":
            d = f"M{pts[0][0]:.1f},{y_of(max(lo, 0.0)):.1f} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{y_of(max(lo, 0.0)):.1f} Z"
            parts.append(f'<path d="{d}" fill="#{col}" fill-opacity="0.3"/>')
        dash = ' stroke-dasharray="5 4"' if s.dashed else ""
        parts.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="#{col}" stroke-width="{1.5 if s.dashed else 2.25}" stroke-linejoin="round"{dash}/>')
        for j, v in enumerate(s.values):
            if v is None:
                continue
            x, y = x_of(j), y_of(v)
            lab = labels.get(s, j)
            big = bool(lab and (lab[2] or lab[3] > labels.size * 1.05))
            if chart.type == "line" and not s.dashed:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5 if big else 3.5}" fill="#{s.point_colors.get(j, col)}"/>')
            elif chart.type == "area" and j == len(s.values) - 1:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#{col}"/>')
            if lab:
                t, c, b, size, pos = lab
                if pos == "r":
                    parts.append(_txt(x + 7, moved.get(k, y) if j == len(s.values) - 1 else y, t, size, c, anchor="start", bold=b))
                elif pos == "b":
                    parts.append(_txt(x, y + size * 1.1, t, size, c, bold=b))
                elif pos == "l":
                    parts.append(_txt(x - 7, y, t, size, c, anchor="end", bold=b))
                else:
                    parts.append(_txt(x, y - size * 1.0, t, size, c, bold=b))
    skip = _cat_step(cats, step_x, font_px)
    for i, c in enumerate(cats):
        if i % skip == 0:
            parts.append(_txt(x_of(i), pad_t + ph + font_px * 1.2, c, font_px, muted))
    return parts


def _pie(chart, s, cats, width, height, top, colors, text_hex, muted, font_px, labels) -> list:
    parts: list = []
    vals = s.values
    total = sum(v for v in vals if v) or 1.0
    side_legend = width / max(height, 1.0) >= 1.45
    leg_w = (max((_width(c, font_px) for c in cats), default=40.0) + font_px * 2) if side_legend else 0.0
    leg_rows = 1 if side_legend or sum(_width(c, font_px) + font_px * 2.2 for c in cats) <= width else 2
    leg_h = 0.0 if side_legend else font_px * (0.5 + 1.5 * leg_rows)
    r = max(10.0, min((width - leg_w - font_px * 2) / 2, (height - top - leg_h - font_px) / 2))
    cx = (width - leg_w - font_px * 1.5) / 2 if side_legend else width / 2
    cy = top + (height - top - leg_h) / 2
    r_in = r * 0.56 if chart.type == "doughnut" else 0.0
    angle = -math.pi / 2
    gap = 1.2 / r  # slices parted by a thin gap: the ground shows through, whatever it is
    for j, v in enumerate(vals):
        frac = (v or 0) / total
        if frac <= 0:
            continue
        a1, a2 = angle + gap / 2, angle + frac * 2 * math.pi - gap / 2
        if a2 <= a1:
            a2 = a1 + 1e-3
        large = 1 if (a2 - a1) > math.pi else 0
        col = s.point_colors.get(j) or (chart.colors[j] if j < len(chart.colors) else None) or colors[j % len(colors)]
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        if r_in:
            xi1, yi1 = cx + r_in * math.cos(a2), cy + r_in * math.sin(a2)
            xi2, yi2 = cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)
            d = f"M{x1:.1f},{y1:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} L{xi1:.1f},{yi1:.1f} A{r_in:.1f},{r_in:.1f} 0 {large} 0 {xi2:.1f},{yi2:.1f} Z"
        else:
            d = f"M{cx:.1f},{cy:.1f} L{x1:.1f},{y1:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} Z"
        parts.append(f'<path d="{d}" fill="#{col}"/>')
        lab = labels.get(s, j)
        if lab:
            t, c, b, size, pos = lab
            mid = angle + frac * math.pi
            rho = (r + size * 1.2) if pos == "outEnd" else ((r + r_in) / 2 if r_in else (r * 0.5 if pos == "ctr" or frac >= 0.25 else r * 0.72))
            parts.append(_txt(cx + rho * math.cos(mid), cy + rho * math.sin(mid), t, size, c if pos != "outEnd" else (c or text_hex), bold=b))
        angle += frac * 2 * math.pi
    if side_legend:
        lx = cx + r + font_px * 2
        ly = cy - len(cats) * font_px * 1.5 / 2 + font_px * 0.75
        for j, c in enumerate(cats[: len(vals)]):
            col = s.point_colors.get(j) or colors[j % len(colors)]
            parts.append(f'<rect x="{lx:.1f}" y="{ly - font_px * 0.35:.1f}" width="{font_px * 0.7:.1f}" height="{font_px * 0.7:.1f}" fill="#{col}"/>')
            parts.append(_txt(lx + font_px, ly, c, font_px, muted, anchor="start"))
            ly += font_px * 1.5
    else:
        _legend_rows(parts, [(c, s.point_colors.get(j) or colors[j % len(colors)], False) for j, c in enumerate(cats[: len(vals)])], width, height - font_px * 0.7, font_px, muted)
    return parts
