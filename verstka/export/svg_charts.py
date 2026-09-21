"""Inline SVG charts from IRChart (bar, column, line, area, pie, doughnut)."""

from __future__ import annotations

import html
import math
from typing import Optional

from verstka.schemas.deck_ir import IRChart


def _fmt(v: float, fmt: Optional[str]) -> str:
    if fmt and "%" in fmt:
        return f"{v:g}%"
    unit = ""
    if fmt and '"' in fmt:
        unit = fmt.split('"')[1]
    if abs(v) >= 1000:
        s = f"{v:,.0f}".replace(",", " ")
    else:
        s = f"{v:g}"
    return s + unit


def chart_svg(chart: IRChart, width: float, height: float, colors: list[str], text_hex: str = "222222", font: str = "Play, Arial, sans-serif", font_px: float = 12.0) -> str:
    colors = [c for c in (chart.colors or []) if c] or colors or ["0077FF"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="100%" height="100%" font-family="{html.escape(font)}" font-size="{font_px}" fill="#{text_hex}">']
    series = chart.series or []
    cats = chart.categories or []
    n_cat = max(len(cats), max((len(s.values) for s in series), default=0))
    if chart.type in ("pie", "doughnut") and series:
        vals = series[0].values
        total = sum(v for v in vals if v) or 1.0
        cx, cy = width * 0.35, height * 0.5
        r = min(width * 0.3, height * 0.42)
        r_in = r * 0.55 if chart.type == "doughnut" else 0
        angle = -math.pi / 2
        for j, v in enumerate(vals):
            frac = (v or 0) / total
            a2 = angle + frac * 2 * math.pi
            large = 1 if frac > 0.5 else 0
            x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            col = colors[j % len(colors)]
            if r_in:
                xi1, yi1 = cx + r_in * math.cos(a2), cy + r_in * math.sin(a2)
                xi2, yi2 = cx + r_in * math.cos(angle), cy + r_in * math.sin(angle)
                d = f"M{x1:.1f},{y1:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} L{xi1:.1f},{yi1:.1f} A{r_in:.1f},{r_in:.1f} 0 {large} 0 {xi2:.1f},{yi2:.1f} Z"
            else:
                d = f"M{cx:.1f},{cy:.1f} L{x1:.1f},{y1:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} Z"
            parts.append(f'<path d="{d}" fill="#{col}" stroke="#fff" stroke-width="1"/>')
            mid = (angle + a2) / 2
            lx, ly = cx + (r + 14) * math.cos(mid), cy + (r + 14) * math.sin(mid)
            if chart.has_data_labels and frac > 0.03:
                parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" dominant-baseline="middle">{html.escape(_fmt(v, chart.number_format))}</text>')
            angle = a2
        # legend
        ly = height * 0.2
        for j, c in enumerate(cats[: len(vals)]):
            parts.append(f'<rect x="{width * 0.72:.1f}" y="{ly - 6:.1f}" width="10" height="10" fill="#{colors[j % len(colors)]}"/>')
            parts.append(f'<text x="{width * 0.72 + 16:.1f}" y="{ly + 4:.1f}">{html.escape(c)}</text>')
            ly += font_px * 1.6
        parts.append("</svg>")
        return "".join(parts)

    pad_l, pad_r, pad_t, pad_b = width * 0.04, width * 0.03, height * 0.08, height * 0.16
    pw, ph = width - pad_l - pad_r, height - pad_t - pad_b
    all_vals = [v for s in series for v in s.values if v is not None]
    vmax = max(all_vals + [0]) or 1.0
    vmin = min(all_vals + [0])
    span = (vmax - vmin) or 1.0
    if chart.type == "bar":
        row_h = ph / max(n_cat, 1)
        for i in range(n_cat):
            for k, s in enumerate(series):
                v = s.values[i] if i < len(s.values) else 0
                bh = row_h * 0.7 / max(len(series), 1)
                y = pad_t + i * row_h + row_h * 0.15 + k * bh
                w = pw * 0.75 * (v - min(vmin, 0)) / span
                parts.append(f'<rect x="{pad_l + pw * 0.22:.1f}" y="{y:.1f}" width="{w:.1f}" height="{bh:.1f}" fill="#{colors[k % len(colors)]}" rx="2"/>')
                if chart.has_data_labels:
                    parts.append(f'<text x="{pad_l + pw * 0.22 + w + 6:.1f}" y="{y + bh * 0.7:.1f}">{html.escape(_fmt(v, chart.number_format))}</text>')
            if i < len(cats):
                parts.append(f'<text x="{pad_l + pw * 0.2:.1f}" y="{pad_t + i * row_h + row_h * 0.6:.1f}" text-anchor="end">{html.escape(cats[i])}</text>')
    elif chart.type in ("line", "area"):
        step = pw / max(n_cat - 1, 1)
        for k, s in enumerate(series):
            pts = []
            for i, v in enumerate(s.values):
                x = pad_l + i * step
                y = pad_t + ph - ph * (v - vmin) / span
                pts.append((x, y))
            col = colors[k % len(colors)]
            if chart.type == "area" and pts:
                d = f"M{pts[0][0]:.1f},{pad_t + ph:.1f} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{pad_t + ph:.1f} Z"
                parts.append(f'<path d="{d}" fill="#{col}" fill-opacity="0.35"/>')
            parts.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="#{col}" stroke-width="2.5"/>')
            for i, (x, y) in enumerate(pts):
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="#{col}"/>')
                if chart.has_data_labels:
                    parts.append(f'<text x="{x:.1f}" y="{y - 8:.1f}" text-anchor="middle">{html.escape(_fmt(s.values[i], chart.number_format))}</text>')
        for i, c in enumerate(cats):
            parts.append(f'<text x="{pad_l + i * step:.1f}" y="{pad_t + ph + font_px * 1.4:.1f}" text-anchor="middle">{html.escape(c)}</text>')
    else:  # column
        group_w = pw / max(n_cat, 1)
        n_ser = max(len(series), 1)
        bar_w = group_w * 0.6 / n_ser
        for i in range(n_cat):
            for k, s in enumerate(series):
                v = s.values[i] if i < len(s.values) else 0
                h = ph * (v - min(vmin, 0)) / span
                x = pad_l + i * group_w + group_w * 0.2 + k * bar_w
                y = pad_t + ph - h
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w * 0.9:.1f}" height="{h:.1f}" fill="#{colors[k % len(colors)]}" rx="2"/>')
                if chart.has_data_labels:
                    parts.append(f'<text x="{x + bar_w * 0.45:.1f}" y="{y - 5:.1f}" text-anchor="middle">{html.escape(_fmt(v, chart.number_format))}</text>')
            if i < len(cats):
                parts.append(f'<text x="{pad_l + i * group_w + group_w / 2:.1f}" y="{pad_t + ph + font_px * 1.4:.1f}" text-anchor="middle">{html.escape(cats[i])}</text>')
        parts.append(f'<line x1="{pad_l:.1f}" y1="{pad_t + ph:.1f}" x2="{pad_l + pw:.1f}" y2="{pad_t + ph:.1f}" stroke="#{text_hex}" stroke-opacity="0.25"/>')
    if chart.has_legend and len(series) > 1:
        lx = pad_l
        ly = height - font_px * 0.6
        for k, s in enumerate(series):
            parts.append(f'<rect x="{lx:.1f}" y="{ly - 9:.1f}" width="10" height="10" fill="#{colors[k % len(colors)]}"/>')
            parts.append(f'<text x="{lx + 14:.1f}" y="{ly:.1f}">{html.escape(s.name)}</text>')
            lx += 14 + len(s.name) * font_px * 0.6 + 18
    parts.append("</svg>")
    return "".join(parts)
