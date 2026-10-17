"""Inline SVG charts from IRChart — bar, column, line, area, pie, doughnut and the data layer's histogram, stacked and
grouped bars and scatter — drawn to the same design as the native charts of verstka.rendering.charts, so the web
version and the PPTX read as one deck: each bar, point and slice in the colour the chart gives it (the highlight in the
accent, the rest stepped back), the labels exactly as the chart formats them (the unit once, Russian number format:
«12 400», «4,8»), zero labels hidden, a hairline baseline, square bars, pie slices parted by gaps rather than by strokes
of a guessed background colour, the unit caption at the top left.

What the PPTX wrote is drawn as written: the bars' gap and overlap (in % of one bar's width, as PowerPoint reads them),
the value axis's ends, step and tick format, a scatter's markers (size, translucent fill, the ring of the ground) and a
label's nudge off its point. A histogram's bins touch and stacked segments sit one on another, parted by a hairline
where the ground shows through (SEAM_PT: a gap, never a stroke of a guessed colour), each stacked value inside its
segment (like a pie slice's) in the ink the PPTX charts choose for that fill, charts.label_on — one rule for both; a
scatter's points stand on two value axes, the highlighted one larger and on top; a missing value is a break in the line,
never a zero, and a line ends (and is labelled) on its last point with a value; axis titles stand along their axes in
the muted label colour, the vertical one turned to read bottom-up. The source line («Источник: …») is a
text box of the slide under the chart frame: the HTML exporter draws it with the slide's text, never inside the chart."""

from __future__ import annotations

import html
import math
from typing import Optional

from verstka.rendering.charts import SCATTER_ASPECT, SEAM_PT, TITLE_LINE, TREND_SERIES, label_on, thin_picks
from verstka.rendering.fonts import text_width_pt, wrap_lines
from verstka.schemas.common import contrast_ratio
from verstka.schemas.deck_ir import IRAxisScale, IRChart, IRChartSeries, IRPointLabel

_MINUS = "−"
_MAX_TICKS = 40


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


def _ticks(lo: float, hi: float, step: Optional[float]) -> list[float]:
    """The tick values from `lo` to `hi` by `step` (the ends alone without a step)."""
    if not step or step <= 0 or hi <= lo:
        return [lo, hi] if hi > lo else [lo]
    n = min(int(math.floor((hi - lo) / step + 1e-6)), _MAX_TICKS)
    return [lo + i * step for i in range(n + 1)]


def _tick_text(v: float, fmt: Optional[str]) -> str:
    """What a tick prints: the axis's own format; a zero is «0», never blank (a label format hides its zeros)."""
    return format_value(0.0 if abs(v) < 1e-9 else v, fmt) or "0"


def _written_scale(scale: Optional[IRAxisScale]) -> Optional[tuple[float, float, Optional[float]]]:
    """(min, max, step) of an axis as the PPTX wrote it; None where its ends are the reader's choice."""
    if scale is None or scale.min is None or scale.max is None or scale.max <= scale.min:
        return None
    ok = scale.step is not None and scale.step > 0 and (scale.max - scale.min) / scale.step <= _MAX_TICKS
    return scale.min, scale.max, (scale.step if ok else None)


def _value_range(chart: IRChart, lo: float, hi: float, axis: bool) -> tuple[float, float, Optional[float]]:
    """The value range of bars: the axis as written, else the data's (round ticks where the axis shows)."""
    ws = _written_scale(chart.value_scale)
    if ws is not None:
        a, b, step = ws
        return a, b, (step or (_nice(a, b)[2] if axis else None))
    if axis:
        return _nice(lo, hi)
    return lo, hi, None


def _scale_format(chart: IRChart, scale: Optional[IRAxisScale]) -> Optional[str]:
    f = scale.format if scale is not None else None
    return f if f and f.strip().lower() != "general" else _plain_tick_format(chart)


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


def _cat_shown(cats: list[str], slot: float, size: float) -> set[int]:
    """Which category labels are drawn: those the chart wrote (the PPTX keeps the labels of a thinned time axis and blanks
    the others — each is drawn), else every k-th when they would run into each other, always with the first and the last."""
    if any(not c.strip() for c in cats):
        return {i for i, c in enumerate(cats) if c.strip()}
    step = _cat_step(cats, slot, size)
    return set(thin_picks(len(cats), step)) if step > 1 else set(range(len(cats)))


def _legend_rows(parts: list, items: list[tuple[str, str, bool]], width: float, y_bottom: float, size: float, muted: str, x0: float = 0.0) -> None:
    """A bottom legend, wrapped into centred rows; items = (name, colour, hollow). `x0`: the legend begins there (a title
    of its group stands in front of it)."""
    width = max(width - x0, 1.0)
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
        lx = x0 if x0 > 0 else max(0.0, (width - total) / 2)  # (behind its group's title the entries start where the title ends)
        ly = y_bottom - (len(rows) - 1 - r) * size * 1.5
        for (name, col, hollow), w in row:
            fill = "none" if hollow else f"#{col}"
            parts.append(f'<rect x="{lx:.1f}" y="{ly - size * 0.35:.1f}" width="{size * 0.7:.1f}" height="{size * 0.7:.1f}" fill="{fill}" stroke="#{col}" stroke-width="{1 if hollow else 0}"/>')
            parts.append(_txt(lx + size, ly, name, size, muted, anchor="start"))
            lx += w


def _ground_of(text_hex: str) -> str:
    """The ground a chart stands on when the caller does not say: the one of white and black the text reads better on."""
    return "FFFFFF" if contrast_ratio(text_hex, "FFFFFF") >= contrast_ratio(text_hex, "000000") else "000000"


class _Labels:
    """What each point's label says and how it looks, from the series' c:dLbls and its per-point overrides; its nudge
    is a fraction of the chart frame (`frame_w` × `frame_h`). A label printed on a filled segment or slice takes its ink
    from `on_fill` — the rule of the PPTX charts (charts.label_on), on the fill drawn here."""

    def __init__(self, chart: IRChart, text_hex: str, font_px: float, frame_w: float = 0.0, frame_h: float = 0.0, ground: Optional[str] = None):
        self.chart, self.text, self.size = chart, text_hex, font_px
        self.frame_w, self.frame_h = frame_w, frame_h
        self.ground = ground or _ground_of(text_hex)

    def on_fill(self, fill: str, written: str) -> str:
        """The ink of a value inside a segment or slice painted `fill`; `written` (the label's own colour in the file)
        stays when the fill is not a plain hex colour."""
        h = (fill or "").lstrip("#").upper()
        if len(h) != 6 or any(ch not in "0123456789ABCDEF" for ch in h):
            return written
        return label_on(h, self.text, self.ground)

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

    def nudge(self, s: IRChartSeries, j: int) -> tuple[float, float]:
        pl = s.point_labels.get(j)
        return (pl.dx * self.frame_w, pl.dy * self.frame_h) if pl is not None else (0.0, 0.0)


def _series_color(chart: IRChart, s: IRChartSeries, k: int, colors: list[str]) -> str:
    return s.color or (chart.colors[k] if k < len(chart.colors) else None) or colors[k % len(colors)]


def _last_value(vals: list[Optional[float]]) -> Optional[int]:
    return next((j for j in range(len(vals) - 1, -1, -1) if vals[j] is not None), None)


def _runs(vals: list[Optional[float]]) -> list[list[int]]:
    """The unbroken stretches of a series: the indices between its gaps (a missing value breaks the line)."""
    out: list[list[int]] = []
    cur: list[int] = []
    for j, v in enumerate(vals):
        if v is None:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(j)
    if cur:
        out.append(cur)
    return out


def _is_stacked(chart: IRChart) -> bool:
    return chart.type in ("bar", "column") and chart.grouping in ("stacked", "percentStacked")


def _stack_spans(series: list[IRChartSeries], n_cat: int, pct: bool) -> tuple[dict[tuple[int, int], tuple[float, float]], list[float], list[float]]:
    """Where each stacked segment runs ((series, category) → (from, to) in values: positives up from zero, negatives
    down; a percent stack in shares of its category) and how far each stack reaches up and down."""
    spans: dict[tuple[int, int], tuple[float, float]] = {}
    tops: list[float] = []
    bots: list[float] = []
    for j in range(n_cat):
        vals = [(k, s.values[j]) for k, s in enumerate(series) if j < len(s.values) and s.values[j] is not None]
        total = sum(abs(v) for _, v in vals) or 1.0
        up = down = 0.0
        for k, v in vals:
            if pct:
                v = v / total * 100.0
            if v >= 0:
                spans[(k, j)] = (up, up + v)
                up += v
            else:
                spans[(k, j)] = (down + v, down)
                down += v
        tops.append(up)
        bots.append(down)
    return spans, tops, bots


def _bar_geometry(chart: IRChart, slot: float, k_ser: int, stacked: bool, fallback_group: float) -> tuple[float, float, float, float]:
    """(cluster width, bar width, pitch between the bars of a cluster, gap inside a bar's own room) across one category
    `slot` — c:gapWidth and c:overlap as PowerPoint reads them, in % of one bar's width (a histogram: 0, the bins
    touch; stacked: one bar). A chart that wrote neither keeps the designed proportions."""
    nb = 1 if stacked else max(k_ser, 1)
    if chart.gap_width is not None:
        ov = 1.0 if stacked else max(-1.0, min(1.0, (chart.overlap or 0) / 100.0))
        bar = slot / (nb - (nb - 1) * ov + max(0, chart.gap_width) / 100.0)
        pitch = bar * (1.0 - ov)
        return bar + (nb - 1) * pitch, bar, pitch, 0.0
    bar = fallback_group / nb
    return fallback_group, bar, bar, (bar * 0.08 if nb > 1 else 0.0)


def _circle(x: float, y: float, r: float, fill: str, alpha: Optional[float] = None, ring: Optional[str] = None, ring_w: float = 0.0) -> str:
    op = f' fill-opacity="{alpha:.2f}"' if alpha is not None and alpha < 0.999 else ""
    st = f' stroke="#{ring}" stroke-width="{ring_w:g}"' if ring and ring_w else ""
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="#{fill}"{op}{st}/>'


# ---------------------------------------------------------------------------------------------- the chart


def chart_svg(chart: IRChart, width: float, height: float, colors: list[str], text_hex: str = "222222", font: str = "Play, Arial, sans-serif", font_px: float = 12.0, ground: Optional[str] = None, legend_left: float = 0.0, trend: bool = False) -> str:
    """`trend`: the one series of a scatter has a trend line of its own (the chart part says so; the renderer fits it).
    `legend_left`: where the bottom legend may begin (pt from the left): a title of the legend's group stands before it
    on its row (the slide's text box «Chart legend title»), the entries centre in what is left."""
    colors = [c for c in (colors or []) if c] or ["0077FF"]
    series = chart.series or []
    # a scatter's trend line rides on a series of its own that draws nothing: not a group, not a legend entry
    helper = next((s for s in series if chart.type == "scatter" and (s.name or "") == TREND_SERIES), None)
    if helper is not None:
        series = [s for s in series if s is not helper]
    trend_series = helper if helper is not None else (series[0] if (trend and chart.type == "scatter" and len(series) == 1) else None)
    cats = chart.categories or []
    n_cat = max(len(cats), max((len(s.values) for s in series), default=0))
    muted = chart.axis_color or text_hex
    rule = chart.rule_color
    labels = _Labels(chart, text_hex, font_px, width, height, ground)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="100%" height="100%" font-family="{html.escape(font)}" font-size="{font_px}" fill="#{text_hex}">']
    top = 2.0
    if chart.title:
        parts.append(_txt(0, font_px * 0.7, chart.title, font_px, muted, anchor="start"))
        top += font_px * 1.6
    k_ser = len(series)
    pie = chart.type in ("pie", "doughnut")
    legend_names = [s.name for s in series] if (chart.has_legend and k_ser > 1 and not pie) else []
    bottom_legend = font_px * 1.9 if legend_names else 0.0
    if legend_names and sum(_width(nm, font_px) + font_px * 2.2 for nm in legend_names) > width:
        bottom_legend += font_px * 1.5

    if pie and series:
        parts += _pie(chart, series[0], cats, width, height, top, colors, text_hex, muted, font_px, labels)
        parts.append("</svg>")
        return "".join(parts)

    # axis titles take a line of room along their axes: the left one at the frame's left edge (turned), the bottom one
    # above the legend; horizontal bars carry the categories' title on the left
    horizontal = chart.type == "bar"
    left_t, bottom_t = (chart.x_title, chart.y_title) if horizontal else (chart.y_title, chart.x_title)
    inset_l = font_px * (TITLE_LINE + 0.45) if left_t else 0.0
    inset_b = font_px * (TITLE_LINE + 0.35) if bottom_t else 0.0
    w_in, h_in = width - inset_l, height - bottom_legend - inset_b

    all_vals = [v for s in series for v in s.values if v is not None]
    vmax = max(all_vals + [0.0])
    vmin = min(all_vals + [0.0])
    base_rule = f'stroke="#{rule}"' if rule else f'stroke="#{text_hex}" stroke-opacity="0.25"'
    geo: dict = {}
    if chart.type == "bar":
        body = _hbars(chart, series, cats, n_cat, w_in, h_in, top, colors, muted, base_rule, font_px, labels, vmin, vmax, geo)
    elif chart.type in ("line", "area"):
        body = _lines(chart, series, cats, n_cat, w_in, h_in, top, colors, text_hex, muted, font_px, labels, vmin, vmax, geo)
    elif chart.type == "scatter":
        body = _scatter(chart, series, w_in, h_in, top, colors, muted, base_rule, font_px, labels, geo, trend_series, text_hex)
    else:
        body = _columns(chart, series, cats, n_cat, w_in, h_in, top, colors, muted, base_rule, font_px, labels, vmin, vmax, geo)
    if inset_l:
        parts.append(f'<g transform="translate({inset_l:.1f},0)">')
        parts += body
        parts.append("</g>")
    else:
        parts += body
    _axis_titles(parts, left_t, bottom_t, geo, inset_l, inset_b, width, h_in, muted, font_px)
    if legend_names:
        _legend_rows(parts, [(s.name, _series_color(chart, s, k, colors), s.outline_only) for k, s in enumerate(series)], width, height - font_px * 0.7, font_px, muted, legend_left)
    parts.append("</svg>")
    return "".join(parts)


def _title_size(text: str, side: float, font_px: float) -> float:
    """An axis title longer than its side steps down a size or two (as the PPTX sets it)."""
    size = font_px
    for s in (font_px, font_px * 0.9, font_px * 0.82):
        size = s
        if _width(text, s) + 4 <= side * 0.98:
            break
    return size


def _axis_titles(parts: list, left_t: Optional[str], bottom_t: Optional[str], geo: dict, inset_l: float, inset_b: float, width: float, h_in: float, muted: str, font_px: float) -> None:
    """The left title turned to read bottom-up, centred on the plot's height at the frame's left edge; the bottom one
    centred under the plot, just above the legend. Both in the muted label colour, not bold."""
    left, top, pw, ph = geo.get("plot") or (0.0, 0.0, width - inset_l, h_in)
    if left_t:
        size = _title_size(left_t, ph, font_px)
        half = min(_width(left_t, size), h_in) / 2
        cx = size * TITLE_LINE / 2 + geo.get("title_x0", 0.0)  # (a narrowed scatter's plot: its title stands beside it)
        cy = min(max(top + ph / 2, half), max(half, h_in - half))
        parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" transform="rotate(-90 {cx:.1f} {cy:.1f})" font-size="{size:.1f}" fill="#{muted}" text-anchor="middle" dominant-baseline="middle">{html.escape(left_t)}</text>')
    if bottom_t:
        size = _title_size(bottom_t, pw, font_px)
        half = min(_width(bottom_t, size), width) / 2
        cx = min(max(inset_l + left + pw / 2, half), max(half, width - half))
        parts.append(_txt(cx, h_in + inset_b - size * TITLE_LINE / 2, bottom_t, size, muted))


def _value_axis(parts: list, x0: float, x1: float, y_of, ticks: list[float], muted: str, font_px: float, fmt: Optional[str]) -> None:
    for v in ticks:
        y = y_of(v)
        parts.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="#{muted}" stroke-opacity="0.18" stroke-width="0.5"/>')
        parts.append(_txt(x0 - font_px * 0.5, y, _tick_text(v, fmt), font_px, muted, anchor="end"))


def _plain_tick_format(chart: IRChart) -> Optional[str]:
    fmt = chart.number_format or ""
    return '0"%"' if "%" in fmt else "#,##0"


def _columns(chart, series, cats, n_cat, width, height, top, colors, muted, base_rule, font_px, labels, vmin, vmax, geo) -> list:
    """Columns: one series, several side by side, stacked parts of a whole, or a histogram's touching bins."""
    parts: list = []
    k_ser = max(len(series), 1)
    stacked = _is_stacked(chart)
    spans: dict = {}
    if stacked:
        spans, tops, bots = _stack_spans(series, n_cat, chart.grouping == "percentStacked")
        vmin, vmax = min([0.0] + bots), max([0.0] + tops)
    label_room = max((labels.get(s, j) or ("", "", False, font_px, None))[3] for s in series for j in range(len(s.values))) if series else font_px
    lo, hi, step = _value_range(chart, vmin, vmax, chart.has_value_axis)
    fmt = _scale_format(chart, chart.value_scale)
    ticks = _ticks(lo, hi, step) if chart.has_value_axis else []
    left = (max(_width(_tick_text(v, fmt), font_px) for v in ticks) + font_px) if ticks else 0.0
    # stacked values sit inside their segments: no room above the bars for them
    pad_t = top + (font_px * 0.7 if stacked else label_room * 1.6)
    pad_b = font_px * 2.2 + (label_room * 1.5 if vmin < 0 and not stacked else 0.0)
    pw, ph = width - left - 2, height - pad_t - pad_b
    span = (hi - lo) or 1.0
    y_of = lambda v: pad_t + ph * (hi - v) / span  # noqa: E731
    geo["plot"] = (left, pad_t, pw, ph)
    if ticks:
        _value_axis(parts, left, width, y_of, ticks, muted, font_px, fmt)
    slot = pw / max(n_cat, 1)
    group, bar, pitch, inner = _bar_geometry(chart, slot, k_ser, stacked, min(slot / 1.7, width * 0.16 * min(k_ser, 3) * 0.9 if k_ser > 1 else width * 0.16))
    seam = SEAM_PT if (stacked or chart.gap_width == 0) else 0.0
    shown_cats = _cat_shown(cats, slot, font_px)
    for i in range(n_cat):
        x_g = left + i * slot + (slot - group) / 2
        for k, s in enumerate(series):
            v = s.values[i] if i < len(s.values) else None
            if v is None:
                continue
            col = s.point_colors.get(i) or _series_color(chart, s, k, colors)
            if stacked:
                y0, y1 = sorted((y_of(spans[(k, i)][0]), y_of(spans[(k, i)][1])))
                x = x_g
            else:
                y0, y1 = sorted((y_of(0.0), y_of(v)))
                x = x_g + k * pitch
            if s.outline_only:
                parts.append(f'<rect x="{x + inner / 2 + 0.75:.1f}" y="{y0 + 0.75:.1f}" width="{max(0.0, bar - inner - 1.5):.1f}" height="{max(0.0, y1 - y0 - 0.75):.1f}" fill="none" stroke="#{col}" stroke-width="1.5"/>')
            else:
                parts.append(f'<rect x="{x + inner / 2 + seam / 2:.1f}" y="{y0 + seam / 2:.1f}" width="{max(0.0, bar - inner - seam):.1f}" height="{max(0.0, y1 - y0 - seam):.1f}" fill="#{col}"/>')
            lab = labels.get(s, i)
            if lab:
                t, c, b, size, _ = lab
                if stacked:
                    y = (y0 + y1) / 2  # inside its segment
                    c = c if s.outline_only else labels.on_fill(col, c)  # (a hollow segment: its value stands on the ground)
                else:
                    y = (y0 - size * 0.7) if v >= 0 else (y1 + size * 0.8)
                parts.append(_txt(x + bar / 2, y, t, size, c, bold=b))
        if i < len(cats) and i in shown_cats:
            parts.append(_txt(left + i * slot + slot / 2, height - font_px * 1.0, cats[i], font_px, muted))
    y_base = y_of(0.0) if lo <= 0.0 <= hi else y_of(lo)
    parts.append(f'<line x1="{left:.1f}" y1="{y_base:.1f}" x2="{left + pw:.1f}" y2="{y_base:.1f}" {base_rule} stroke-width="0.75"/>')
    return parts


def _hbars(chart, series, cats, n_cat, width, height, top, colors, muted, base_rule, font_px, labels, vmin, vmax, geo) -> list:
    """Horizontal bars read top-down: one series, several side by side, or stacked parts of a whole."""
    parts: list = []
    k_ser = max(len(series), 1)
    stacked = _is_stacked(chart)
    spans: dict = {}
    if stacked:
        spans, tops, bots = _stack_spans(series, n_cat, chart.grouping == "percentStacked")
        vmin, vmax = min([0.0] + bots), max([0.0] + tops)
    cat_w = min(max((_width(c, font_px) for c in cats), default=20.0), width * 0.36)
    wrapped = [wrap_lines(c, None, font_px, False, cat_w / 1.05)[:3] for c in cats]
    lab_w = 0.0 if stacked else max((_width(lab[0], lab[3], lab[2]) for s in series for j in range(len(s.values)) if (lab := labels.get(s, j))), default=0.0)
    left = cat_w + font_px * 0.8
    lo, hi, step = _value_range(chart, min(vmin, 0.0), vmax, chart.has_value_axis)
    fmt = _scale_format(chart, chart.value_scale)
    ticks = _ticks(lo, hi, step) if chart.has_value_axis else []
    right = max(lab_w, (_width(_tick_text(ticks[-1], fmt), font_px) / 2) if ticks else 0.0)
    pw = max(width - left - right - font_px * 0.8, width * 0.3)
    ph = height - top - font_px * 0.6 - (font_px * 1.8 if ticks else 0.0)
    span = (hi - lo) or 1.0
    x_of = lambda v: left + pw * (v - lo) / span  # noqa: E731
    geo["plot"] = (left, top, pw, ph)
    for v in ticks:  # a value axis under the bars: quiet vertical gridlines, the ticks below
        x = x_of(v)
        parts.append(f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{top + ph:.1f}" stroke="#{muted}" stroke-opacity="0.18" stroke-width="0.5"/>')
        parts.append(_txt(x, top + ph + font_px * 0.9, _tick_text(v, fmt), font_px, muted))
    row = ph / max(n_cat, 1)
    group, bar, pitch, inner = _bar_geometry(chart, row, k_ser, stacked, min(row / 1.7, font_px * 2.6 * (min(k_ser, 3) * 0.9 if k_ser > 1 else 1)))
    seam = SEAM_PT if (stacked or chart.gap_width == 0) else 0.0
    for i in range(n_cat):
        y_g = top + i * row + (row - group) / 2
        for k, s in enumerate(series):
            v = s.values[i] if i < len(s.values) else None
            if v is None:
                continue
            col = s.point_colors.get(i) or _series_color(chart, s, k, colors)
            if stacked:
                x0, x1 = sorted((x_of(spans[(k, i)][0]), x_of(spans[(k, i)][1])))
                y = y_g
            else:
                x0, x1 = sorted((x_of(0.0), x_of(v)))
                y = y_g + k * pitch
            if s.outline_only:
                parts.append(f'<rect x="{x0:.1f}" y="{y + inner / 2 + 0.75:.1f}" width="{max(0.0, x1 - x0 - 0.75):.1f}" height="{max(0.0, bar - inner - 1.5):.1f}" fill="none" stroke="#{col}" stroke-width="1.5"/>')
            elif x1 - x0 > seam:
                parts.append(f'<rect x="{x0 + seam / 2:.1f}" y="{y + inner / 2 + seam / 2:.1f}" width="{x1 - x0 - seam:.1f}" height="{max(0.0, bar - inner - seam):.1f}" fill="#{col}"/>')
            lab = labels.get(s, i)
            if lab:
                t, c, b, size, _ = lab
                if stacked:
                    parts.append(_txt((x0 + x1) / 2, y + bar / 2, t, size, c if s.outline_only else labels.on_fill(col, c), bold=b))  # inside its segment
                else:
                    parts.append(_txt(x1 + size * 0.4, y + bar / 2, t, size, c, anchor="start", bold=b))
        if i < len(cats):
            parts.append(_lines_txt(cat_w, top + i * row + row / 2, wrapped[i], font_px, muted, "end"))
    if vmin < 0:
        x = x_of(0.0)
        parts.append(f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" y2="{top + ph:.1f}" {base_rule} stroke-width="0.75"/>')
    return parts


def _lines(chart, series, cats, n_cat, width, height, top, colors, text_hex, muted, font_px, labels, vmin, vmax, geo) -> list:
    """Lines and areas: a missing value breaks the line (and the area) — never a zero; the end label sits on the last
    point with a value."""
    parts: list = []
    data = [v for s in series for v in s.values if v is not None]
    vmin = min(data) if data else vmin
    lo, hi = min(vmin, 0.0) if vmin < 0 else vmin, vmax
    step = None
    left = 2.0
    ws = _written_scale(chart.value_scale)
    fmt = _scale_format(chart, chart.value_scale)
    if ws is not None:
        lo, hi = ws[0], ws[1]
    if chart.has_value_axis:
        if ws is not None:
            step = ws[2] or _nice(lo, hi)[2]
        else:
            lo, hi, step = _nice(0.0 if (vmin >= 0 and (chart.type == "area" or vmin <= 0.45 * vmax)) else vmin, vmax)
        left = max(_width(_tick_text(v, fmt), font_px) for v in _ticks(lo, hi, step)) + font_px
    elif ws is None and vmin > 0:
        lo = 0.0 if vmin <= 0.45 * vmax else vmin - (vmax - vmin) * 0.25
    lasts = [_last_value(s.values) for s in series]
    end_w = max((_width(lab[0], lab[3], lab[2]) for s, j in zip(series, lasts) if j is not None and (lab := labels.get(s, j)) and (lab[4] == "r")), default=0.0)
    # room over the highest point for a label set above it (the highlight's, a size up, stays whole)
    over = max((lab[3] for s in series for j in range(len(s.values)) if (lab := labels.get(s, j)) and lab[4] not in ("r", "l", "b")), default=0.0)
    pad_t = top + max(font_px * 1.8, over * 1.5 + 2)
    pad_b = font_px * 2.2
    pw = width - left - max(end_w + font_px, font_px * 1.5)
    ph = height - pad_t - pad_b
    span = (hi - lo) or 1.0
    step_x = pw / max(n_cat, 1)
    x_of = lambda j: left + (j + 0.5) * step_x  # noqa: E731
    y_of = lambda v: pad_t + ph * (hi - v) / span  # noqa: E731
    geo["plot"] = (left, pad_t, pw, ph)
    if chart.has_value_axis:
        _value_axis(parts, left, left + pw, y_of, _ticks(lo, hi, step), muted, font_px, fmt)
    # end labels right of the last point with a value, pushed apart where two lines end close together
    ends = {}
    for k, (s, j) in enumerate(zip(series, lasts)):
        lab = labels.get(s, j) if j is not None else None
        if lab and lab[4] == "r":
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
        runs = _runs(s.values)
        if not runs:
            continue
        dash = ' stroke-dasharray="5 4"' if s.dashed else ""
        for run in runs:  # one stretch between gaps: its own area and its own polyline
            pts = [(x_of(j), y_of(s.values[j])) for j in run]
            if chart.type == "area":
                base = y_of(max(lo, 0.0))
                d = f"M{pts[0][0]:.1f},{base:.1f} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{base:.1f} Z"
                parts.append(f'<path d="{d}" fill="#{col}" fill-opacity="0.3"/>')
            if len(pts) >= 2:
                parts.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="#{col}" stroke-width="{1.5 if s.dashed else 2.25}" stroke-linejoin="round"{dash}/>')
        for j, v in enumerate(s.values):
            if v is None:
                continue
            x, y = x_of(j), y_of(v)
            lab = labels.get(s, j)
            big = bool(lab and (lab[2] or lab[3] > labels.size * 1.05))
            if chart.type == "line" and not s.dashed:
                # the markers as the PPTX sizes them (the highlight larger), ringed in the ground's colour
                r = ((s.point_sizes.get(j) or s.marker_size) / 2) if s.marker_size else (5 if big else 3.5)
                parts.append(_circle(x, y, r, s.point_colors.get(j, col), ring=s.marker_line, ring_w=2.0 if j in s.point_sizes else 1.5))
            elif chart.type == "area" and j == lasts[k]:
                parts.append(_circle(x, y, 3.5, col))
            if lab:
                t, c, b, size, pos = lab
                if pos == "r":
                    parts.append(_txt(x + 7, moved.get(k, y) if j == lasts[k] else y, t, size, c, anchor="start", bold=b))
                    continue
                x += labels.nudge(s, j)[0]  # (a label moved aside off a neighbouring segment)
                if pos == "b":
                    parts.append(_txt(x, y + size * 1.1, t, size, c, bold=b))
                elif pos == "l":
                    parts.append(_txt(x - 7, y, t, size, c, anchor="end", bold=b))
                else:
                    parts.append(_txt(x, y - size * 1.0, t, size, c, bold=b))
    shown_cats = _cat_shown(cats, step_x, font_px)
    for i, c in enumerate(cats):
        if i in shown_cats:
            parts.append(_txt(x_of(i), pad_t + ph + font_px * 1.2, c, font_px, muted))
    return parts


def _xy_range(scale: Optional[IRAxisScale], vals: list[float]) -> tuple[float, float, float]:
    """A scatter axis: as the PPTX wrote it, else round ticks from zero when the data sit near it (as a line's axis),
    else from a round value under the lowest point."""
    ws = _written_scale(scale)
    if ws is not None:
        return ws[0], ws[1], (ws[2] or _nice(ws[0], ws[1])[2])
    vals = vals or [0.0]
    mn, mx = min(vals), max(vals)
    lo_raw = 0.0 if (mn >= 0 and mn <= 0.45 * mx) else mn - (mx - mn) * 0.08
    hi_raw = mx + (mx - mn) * 0.04
    lo, hi, step = _nice(lo_raw, hi_raw if hi_raw > lo_raw else lo_raw + (abs(lo_raw) or 1.0))
    return (max(0.0, lo) if mn >= 0 else lo), hi, step


def _num(t: str) -> Optional[float]:
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def _scatter(chart, series, width, height, top, colors, muted, base_rule, font_px, labels, geo, trend=None, text_hex: str = "222222") -> list:
    """Points only, no lines: translucent ringed markers on two quiet value axes on the PPTX's round ticks — Y with
    gridlines, X on a hairline baseline; the highlighted point larger, in the accent, on top, with its value beside it."""
    parts: list = []
    cat_x = [_num(c) for c in chart.categories]
    pts = [
        (k, j, x, y)
        for k, s in enumerate(series)
        for j, (x, y) in enumerate(zip(s.x_values or (cat_x if k == 0 else []), s.values))
        if x is not None and y is not None
    ]
    x_lo, x_hi, x_step = _xy_range(chart.x_scale, [p[2] for p in pts])
    y_lo, y_hi, y_step = _xy_range(chart.value_scale, [p[3] for p in pts])
    x_fmt, y_fmt = _scale_format(chart, chart.x_scale), _scale_format(chart, chart.value_scale)
    x_ticks, y_ticks = _ticks(x_lo, x_hi, x_step), _ticks(y_lo, y_hi, y_step)
    left = max((_width(_tick_text(v, y_fmt), font_px) for v in y_ticks), default=font_px) + font_px * 0.8
    right = max(2.0, _width(_tick_text(x_ticks[-1], x_fmt), font_px) / 2 + 2)
    pad_t = top + font_px * 0.9
    pad_b = font_px * TITLE_LINE + font_px * 0.6
    pw = max(width - left - right, width * 0.3)
    ph = max(height - pad_t - pad_b, height * 0.3)
    if pw > ph * SCATTER_ASPECT:  # as the PPTX: a plot of a near-square shape stands in the middle of its frame
        geo["title_x0"] = (pw - ph * SCATTER_ASPECT) / 2
        left, pw = left + geo["title_x0"], ph * SCATTER_ASPECT
    x_of = lambda v: left + pw * (v - x_lo) / ((x_hi - x_lo) or 1.0)  # noqa: E731
    y_of = lambda v: pad_t + ph * (y_hi - v) / ((y_hi - y_lo) or 1.0)  # noqa: E731
    geo["plot"] = (left, pad_t, pw, ph)
    if chart.has_value_axis:
        _value_axis(parts, left, left + pw, y_of, y_ticks, muted, font_px, y_fmt)
    y_base = y_of(0.0) if y_lo <= 0.0 <= y_hi else y_of(y_lo)
    parts.append(f'<line x1="{left:.1f}" y1="{y_base:.1f}" x2="{left + pw:.1f}" y2="{y_base:.1f}" {base_rule} stroke-width="0.75"/>')
    for v in x_ticks:
        parts.append(_txt(x_of(v), pad_t + ph + font_px * 0.95, _tick_text(v, x_fmt), font_px, muted))
    marks: list[tuple[int, str]] = []  # (layer, svg): the highlighted points over the others
    for k, j, x, y in pts:
        s = series[k]
        col = _series_color(chart, s, k, colors)
        r = (s.marker_size or 7.0) / 2
        if j in s.point_sizes or j in s.point_colors:
            marks.append((1, _circle(x_of(x), y_of(y), (s.point_sizes.get(j) or s.marker_size or 7.0) / 2, s.point_colors.get(j, col), None, s.marker_line, 1.5)))
        else:
            marks.append((0, _circle(x_of(x), y_of(y), r, col, s.marker_alpha, s.marker_line, 0.75)))
    if trend is not None:
        # the least-squares line through all the points the trend series holds, over the data's own reach, dashed
        t_xs = trend.x_values or cat_x
        tx = [x for x, y in zip(t_xs, trend.values) if x is not None and y is not None]
        ty = [y for x, y in zip(t_xs, trend.values) if x is not None and y is not None]
        n = len(tx)
        if n >= 3 and max(tx) > min(tx):
            mx, my = sum(tx) / n, sum(ty) / n
            sxx = sum((x - mx) ** 2 for x in tx)
            slope = sum((x - mx) * (y - my) for x, y in zip(tx, ty)) / sxx
            xa, xb = min(tx), max(tx)
            ya, yb = my + slope * (xa - mx), my + slope * (xb - mx)
            tcol = _series_color(chart, series[0], 0, colors) if len(series) == 1 else text_hex
            marks.append((0, f'<line x1="{x_of(xa):.1f}" y1="{y_of(ya):.1f}" x2="{x_of(xb):.1f}" y2="{y_of(yb):.1f}" stroke="#{tcol}" stroke-width="1.5" stroke-dasharray="5 3"/>'))
    parts += [m for _, m in sorted(marks, key=lambda m: m[0])]
    for k, j, x, y in pts:
        s = series[k]
        lab = labels.get(s, j)
        if not lab:
            continue
        t, c, b, size, pos = lab
        dx, dy = labels.nudge(s, j)
        cx, cy = x_of(x) + dx, y_of(y) + dy
        gap = (s.point_sizes.get(j) or s.marker_size or 7.0) / 2 + 3
        if pos == "b":
            parts.append(_txt(cx, cy + gap + size * 0.6, t, size, c, bold=b))
        elif pos == "r":
            parts.append(_txt(cx + gap, cy, t, size, c, anchor="start", bold=b))
        elif pos == "l":
            parts.append(_txt(cx - gap, cy, t, size, c, anchor="end", bold=b))
        else:
            parts.append(_txt(cx, cy - gap - size * 0.6, t, size, c, bold=b))
    return parts


def _pie(chart, s, cats, width, height, top, colors, text_hex, muted, font_px, labels) -> list:
    parts: list = []
    vals = s.values
    total = sum(v for v in vals if v) or 1.0
    # a pie the slide gives its own legend (the composer's swatches and shares beside it: the chart has none) is a circle
    # on the whole frame — no second legend under it
    legend_on = bool(chart.has_legend)
    side_legend = legend_on and width / max(height, 1.0) >= 1.45
    leg_w = (max((_width(c, font_px) for c in cats), default=40.0) + font_px * 2) if side_legend else 0.0
    leg_rows = 1 if side_legend or sum(_width(c, font_px) + font_px * 2.2 for c in cats) <= width else 2
    leg_h = 0.0 if (side_legend or not legend_on) else font_px * (0.5 + 1.5 * leg_rows)
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
            ink = (c or text_hex) if pos == "outEnd" else labels.on_fill(col, c)  # outside: on the ground; inside: on the slice
            parts.append(_txt(cx + rho * math.cos(mid), cy + rho * math.sin(mid), t, size, ink, bold=b))
        angle += frac * 2 * math.pi
    if side_legend:
        lx = cx + r + font_px * 2
        ly = cy - len(cats) * font_px * 1.5 / 2 + font_px * 0.75
        for j, c in enumerate(cats[: len(vals)]):
            col = s.point_colors.get(j) or colors[j % len(colors)]
            parts.append(f'<rect x="{lx:.1f}" y="{ly - font_px * 0.35:.1f}" width="{font_px * 0.7:.1f}" height="{font_px * 0.7:.1f}" fill="#{col}"/>')
            parts.append(_txt(lx + font_px, ly, c, font_px, muted, anchor="start"))
            ly += font_px * 1.5
    elif legend_on:
        _legend_rows(parts, [(c, s.point_colors.get(j) or colors[j % len(colors)], False) for j, c in enumerate(cats[: len(vals)])], width, height - font_px * 0.7, font_px, muted)
    return parts
