"""Native PowerPoint charts styled from template tokens."""

from __future__ import annotations

from typing import Optional

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.slide import Slide
from pptx.util import Emu, Pt

from verstka.schemas.common import Bbox, relative_luminance
from verstka.schemas.outline import ChartSpec, DeckOutline, Series
from verstka.schemas.template import ChartStyleSpec, Typography

_TYPE_MAP = {
    "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "bar": XL_CHART_TYPE.BAR_CLUSTERED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "area": XL_CHART_TYPE.AREA,
    "pie": XL_CHART_TYPE.PIE,
    "doughnut": XL_CHART_TYPE.DOUGHNUT,
}


def number_format(unit: Optional[str]) -> str:
    u = (unit or "").strip()
    if u == "%":
        return '0"%"'
    if u in ("₽", "руб", "руб.", "RUB"):
        return '#,##0" ₽"'
    if u in ("$", "USD"):
        return '"$"#,##0'
    if u:
        return f'#,##0" {u}"'
    return "#,##0"


def _rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_.upper())


def _lighten(hex_: str, factor: float = 0.55) -> str:
    r, g, b = int(hex_[0:2], 16), int(hex_[2:4], 16), int(hex_[4:6], 16)
    mix = lambda c: int(c + (255 - c) * factor)  # noqa: E731
    return f"{mix(r):02X}{mix(g):02X}{mix(b):02X}"


def resolve_series(spec: ChartSpec, outline: DeckOutline) -> list[Series]:
    out = [s for sid in spec.series_ids if (s := outline.series_by_id(sid)) is not None]
    if not out and outline.series:
        out = outline.series[:1]
    return out


_AX_TAGS = ("axId", "crossAx")


def fix_axis_ids(chart_space) -> None:
    """python-pptx writes negative axis ids (-2068027336); the schema wants xs:unsignedInt. Every id is mapped to a
    positive one consistently, so c:axId / c:crossAx pairs keep pointing at each other."""
    ns = "http://schemas.openxmlformats.org/drawingml/2006/chart"
    mapping: dict[str, str] = {}
    for el in chart_space.iter(*(f"{{{ns}}}{t}" for t in _AX_TAGS)):
        v = el.get("val")
        if v is None or not v.lstrip("-").isdigit() or int(v) >= 0:
            continue
        if v not in mapping:
            mapping[v] = str(int(v) & 0xFFFFFFFF)
        el.set("val", mapping[v])


def _mix(fg: str, bg: str, share: float) -> str:
    """`share` of fg over bg."""
    a = [int(fg[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg[i : i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{int(round(x * share + y * (1 - share))):02X}" for x, y in zip(a, b))


def add_ring(slide: Slide, bbox: Bbox, percent: float, color_hex: str, ground_hex: Optional[str] = None):
    """A native doughnut showing `percent` — the true value in place of a ring drawn as a picture. The track is a
    faint tint of the colour over the ground; no legend, no labels (the figure sits in the hole), transparent back."""
    percent = max(0.0, min(100.0, percent))
    data = CategoryChartData()
    data.categories = ["value", "rest"]
    data.add_series("share", (percent, 100.0 - percent))
    gf = slide.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, Emu(bbox.x), Emu(bbox.y), Emu(bbox.w), Emu(bbox.h), data)
    chart = gf.chart
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.has_data_labels = False
    track = _mix(color_hex, ground_hex or "FFFFFF", 0.14)
    for j, pt in enumerate(plot.series[0].points):
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = _rgb(color_hex if j == 0 else track)
        pt.format.line.fill.background()
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
    dn = chart._chartSpace.find(f".//{ns}doughnutChart")
    if dn is not None:
        for tag, val in (("firstSliceAng", "0"), ("holeSize", "78")):
            el = dn.find(f"{ns}{tag}")
            if el is not None:
                el.set("val", val)
    from lxml import etree

    # the ring fills its frame, centred: the figure placed in the middle of the frame sits in the hole
    plot_area = chart._chartSpace.find(f".//{ns}plotArea")
    if plot_area is not None:
        layout = plot_area.find(f"{ns}layout")
        if layout is None:
            layout = etree.Element(f"{ns}layout")
            plot_area.insert(0, layout)
        for child in list(layout):
            layout.remove(child)
        ml = etree.SubElement(layout, f"{ns}manualLayout")
        for tag, val in (("layoutTarget", "inner"), ("xMode", "edge"), ("yMode", "edge"), ("x", "0.02"), ("y", "0.02"), ("w", "0.96"), ("h", "0.96")):
            etree.SubElement(ml, f"{ns}{tag}").set("val", val)
    # no white box behind the ring: the chart and its plot area are transparent

    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    for holder in (chart._chartSpace, chart._chartSpace.find(f".//{ns}plotArea")):
        if holder is None:
            continue
        sp = holder.find(f"{ns}spPr")
        if sp is None:
            sp = etree.SubElement(holder, f"{ns}spPr")
            # c:spPr goes before c:txPr/c:externalData/… in chartSpace; after the plot content in plotArea
            if holder is chart._chartSpace:
                chart_el = holder.find(f"{ns}chart")
                if chart_el is not None:
                    chart_el.addnext(sp)
        for child in list(sp):
            sp.remove(child)
        etree.SubElement(sp, f"{a}noFill")
        ln = etree.SubElement(sp, f"{a}ln")
        etree.SubElement(ln, f"{a}noFill")
    return gf


def add_chart(slide: Slide, bbox: Bbox, spec: ChartSpec, outline: DeckOutline, style: ChartStyleSpec, typography: Typography, text_hex: Optional[str] = None, neutral_hex: Optional[str] = None):
    series = resolve_series(spec, outline)
    if not series:
        raise ValueError("chart has no series data")
    data = CategoryChartData()
    data.categories = list(series[0].categories)
    for s in series:
        vals = list(s.values)[: len(series[0].categories)]
        data.add_series(s.name, vals)
    chart_type = _TYPE_MAP.get(spec.type, XL_CHART_TYPE.COLUMN_CLUSTERED)
    gf = slide.shapes.add_chart(chart_type, Emu(bbox.x), Emu(bbox.y), Emu(bbox.w), Emu(bbox.h), data)
    chart = gf.chart
    fix_axis_ids(chart._chartSpace)
    colors = style.series_colors or ["0077FF"]
    font_size = style.font_size_pt or typography.size_for("small", 12.0)
    chart.font.size = Pt(font_size)
    if style.font_family or typography.primary_family:
        chart.font.name = style.font_family or typography.primary_family
    if text_hex:
        chart.font.color.rgb = _rgb(text_hex)
    chart.has_title = bool(spec.title)
    if spec.title:
        chart.chart_title.text_frame.text = spec.title
        chart.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(font_size + 2)
    multi = len(series) > 1
    chart.has_legend = multi or spec.type in ("pie", "doughnut")
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM if style.legend_position == "bottom" else XL_LEGEND_POSITION.RIGHT
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(font_size)
    plot = chart.plots[0]
    unit = spec.unit or series[0].unit
    fmt = number_format(unit)
    plot.has_data_labels = style.data_labels
    if style.data_labels:
        dl = plot.data_labels
        dl.number_format = fmt
        dl.number_format_is_linked = False
        dl.font.size = Pt(font_size)
        if text_hex:
            dl.font.color.rgb = _rgb(text_hex)
        if spec.type in ("column", "bar"):
            dl.position = XL_LABEL_POSITION.OUTSIDE_END
        elif spec.type in ("pie", "doughnut"):
            dl.position = XL_LABEL_POSITION.OUTSIDE_END if spec.type == "pie" else XL_LABEL_POSITION.CENTER
    if spec.type in ("column", "bar"):
        plot.gap_width = 60
        plot.overlap = -10 if multi else 0
    if spec.type not in ("pie", "doughnut"):
        va = chart.value_axis
        va.has_major_gridlines = bool(style.gridlines)
        va.has_minor_gridlines = False
        va.tick_labels.font.size = Pt(font_size)
        va.tick_labels.number_format = fmt
        va.tick_labels.number_format_is_linked = False
        if style.data_labels and not multi and spec.type in ("column", "bar"):
            va.visible = False  # labels replace the axis (Education rule)
        va.format.line.fill.background()
        ca = chart.category_axis
        ca.tick_labels.font.size = Pt(font_size)
        ca.has_major_gridlines = False
        if neutral_hex:
            ca.format.line.color.rgb = _rgb(neutral_hex)
    # colours
    if spec.type in ("pie", "doughnut"):
        for ser in plot.series:
            for j, pt in enumerate(ser.points):
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = _rgb(colors[j % len(colors)])
    else:
        for i, ser in enumerate(plot.series):
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = _rgb(colors[i % len(colors)])
            if spec.type in ("line",):
                ser.format.line.color.rgb = _rgb(colors[i % len(colors)])
                ser.format.line.width = Pt(2.25)
                ser.smooth = False
        if spec.highlight_index is not None and not multi and spec.type in ("column", "bar"):
            ser = plot.series[0]
            # the other bars step back: a mid grey of the template, never its black (LCT and Education name black
            # «neutral») — a heavy black next to the accent reads as the point of the chart
            muted = neutral_hex if neutral_hex and 0.12 <= relative_luminance(neutral_hex) <= 0.75 else _lighten(colors[0])
            for j, pt in enumerate(ser.points):
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = _rgb(colors[0] if j == spec.highlight_index else muted)
    return gf
