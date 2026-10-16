"""Вторая ступень, движок диаграмм (verstka.rendering.charts): гистограмма, рассеяние, накопительные и сгруппированные
столбцы/полосы, линия с разрывами, подписи осей, строка источника, управление выделением — родные объекты PowerPoint в
стиле шаблона; чтение пропусков аудитом (audit/ir.py, audit/checks/writing.py)."""

from __future__ import annotations

import math
import random
import re
import zipfile
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu

from verstka.audit.checks.writing import _chart_rows
from verstka.audit.ir import build_deck_ir
from verstka.rendering.charts import (
    NO_HIGHLIGHT,
    _chroma,
    _label_on,
    _label_spot,
    _scatter_range,
    add_chart,
    chart_data_ok,
    delta_e,
    eased,
    effective_chart_type,
    glue_numbers,
    label_pieces,
    prefer_bar,
    resolve_series,
    source_said,
    source_text,
    xy_series,
)
from verstka.rendering.fonts import break_pieces, text_width_pt, wrap_lines
from verstka.schemas.common import Bbox, contrast_ratio
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, OutlineSlide, SlideContent, XYSeries
from verstka.schemas.template import ChartStyleSpec, TypeStep, Typography

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
W, H = 12192000, 6858000
BOX = Bbox(x=int(W * 0.06), y=int(H * 0.22), w=int(W * 0.88), h=int(H * 0.68))
# VK Tech-like template: its chart colours and its face
PALETTE = ["0077FF", "00D3E6", "005EFF", "FF6C6C", "0563C1"]
STYLE = ChartStyleSpec(series_colors=PALETTE, font_family="Play", font_size_pt=7.0)
TYPO = Typography(scale=[TypeStep(role="display", size_pt=47), TypeStep(role="h1", size_pt=24), TypeStep(role="h2", size_pt=12), TypeStep(role="body", size_pt=9), TypeStep(role="small", size_pt=7)])
TEXT = "000000"
OUTLINE = DeckOutline(title="t")
BINS = ["0–30", "30–60", "60–90", "90–120", "120–180", "180–240", "240–360", "360–600", "> 600"]
COUNTS = [148, 121, 63, 78, 52, 22, 15, 10, 3]
QS = ["IV кв. 2024", "I кв. 2025", "II кв. 2025", "III кв. 2025", "IV кв. 2025", "I кв. 2026", "II кв. 2026", "III кв. 2026"]
NPS = [41, 43, None, 46, 48, 49, None, 52]
REG = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург"]


def _slide(bg: str = "FFFFFF"):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor.from_string(bg)
    return prs, s


def _gf(spec: ChartSpec, bg: str = "FFFFFF"):
    prs, s = _slide(bg)
    gf = add_chart(s, BOX, spec, OUTLINE, STYLE, TYPO, text_hex=TEXT if bg == "FFFFFF" else "FFFFFF")
    return prs, s, gf


def _cs(spec: ChartSpec, bg: str = "FFFFFF"):
    return _gf(spec, bg)[2].chart._chartSpace


def _hist(**kw) -> ChartSpec:
    return ChartSpec(type="histogram", categories=BINS, series=[InlineSeries(name="Обращения", values=COUNTS)], **kw)


def _stacked(kind: str = "stacked_column", **kw) -> ChartSpec:
    return ChartSpec(type=kind, categories=["I кв.", "II кв.", "III кв.", "IV кв."], series=[
        InlineSeries(name="Прямые продажи", values=[120, 134, 142, 151]), InlineSeries(name="Партнёры", values=[71, 80, 86, 92]),
        InlineSeries(name="Маркетплейс", values=[40, 46, 55, 63]), InlineSeries(name="Прочее", values=[22, 21, 25, 27])], unit="млн ₽", **kw)


def _scatter(**kw) -> ChartSpec:
    xs = [120, 180, 220, 260, 310, 350, 400, 450, 520, 590]
    ys = [110, 160, 230, 240, 300, 330, 390, 420, 500, 560]
    return ChartSpec(type="scatter", xy=[XYSeries(name="Клиенты", x=xs, y=ys)], **kw)


def _title_text(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{A}t"))


def _ser_fill(ser) -> str:
    return ser.find(f"{C}spPr/{A}solidFill/{A}srgbClr").get("val")


# ---------------------------------------------------------------------------------------------- types


def test_new_types_map_to_native_chart_kinds():
    assert effective_chart_type(_hist(), OUTLINE) == "histogram"
    assert effective_chart_type(_scatter(), OUTLINE) == "scatter"
    assert effective_chart_type(_stacked(), OUTLINE) == "stacked_column"
    assert effective_chart_type(_stacked("stacked_bar"), OUTLINE) == "stacked_bar"
    grouped = ChartSpec(type="grouped_column", categories=["I", "II"], series=[InlineSeries(name="2025", values=[1, 2]), InlineSeries(name="2026", values=[2, 3])])
    assert effective_chart_type(grouped, OUTLINE) == "column"
    assert effective_chart_type(grouped.model_copy(update={"type": "grouped_bar"}), OUTLINE) == "bar"
    # long category labels turn stacked and grouped columns horizontal, as plain columns; a histogram's bins never turn
    long_cats = ["Автоматизация обращений", "Маршрутизация звонков"]
    stacked_long = ChartSpec(type="stacked_column", categories=long_cats, series=[InlineSeries(name="a", values=[1, 2]), InlineSeries(name="b", values=[2, 1])])
    assert effective_chart_type(stacked_long, OUTLINE) == "stacked_bar"
    assert effective_chart_type(grouped.model_copy(update={"categories": ["Автоматизация обращений клиентов", "Маршрутизация звонков операторам"]}), OUTLINE) == "bar"
    many_bins = ChartSpec(type="histogram", categories=[f"{i * 10}–{i * 10 + 10}" for i in range(12)], series=[InlineSeries(name="n", values=list(range(1, 13)))])
    assert not prefer_bar(many_bins, OUTLINE) and effective_chart_type(many_bins, OUTLINE) == "histogram"


def test_histogram_bins_touch_with_a_hairline_of_the_ground():
    cs = _cs(_hist())
    bc = cs.find(f".//{C}barChart")
    assert bc.find(f"{C}barDir").get("val") == "col"
    assert bc.find(f"{C}grouping").get("val") == "clustered"
    assert bc.find(f"{C}gapWidth").get("val") == "0"
    assert bc.find(f"{C}overlap").get("val") == "0"
    ser = bc.find(f"{C}ser")
    assert _ser_fill(ser) == "0077FF"  # the template's accent
    seam = ser.find(f"{C}spPr/{A}ln")
    assert seam.find(f"{A}solidFill/{A}srgbClr").get("val") == "FFFFFF" and int(seam.get("w")) == int(0.75 * 12700)
    # the counts sit over the bins
    assert ser.find(f"{C}dLbls/{C}dLblPos").get("val") == "outEnd"


def test_histogram_highlight_steps_the_other_bins_back():
    cs = _cs(_hist(highlight_index=0))
    ser = cs.find(f".//{C}barChart/{C}ser")
    base = _ser_fill(ser)
    dpt = {int(d.find(f"{C}idx").get("val")): d.find(f"{C}spPr/{A}solidFill/{A}srgbClr").get("val") for d in ser.findall(f"{C}dPt")}
    assert dpt[0] == "0077FF" and base != "0077FF"
    assert _chroma(base) > 12 and contrast_ratio(base, "FFFFFF") >= 1.4  # a tint of the accent, never grey


def test_stacked_bars_are_parts_of_one_whole():
    for kind, bar_dir in (("stacked_column", "col"), ("stacked_bar", "bar")):
        cs = _cs(_stacked(kind))
        bc = cs.find(f".//{C}barChart")
        assert bc.find(f"{C}barDir").get("val") == bar_dir
        assert bc.find(f"{C}grouping").get("val") == "stacked"
        assert bc.find(f"{C}overlap").get("val") == "100"
        assert 40 <= int(bc.find(f"{C}gapWidth").get("val")) <= 180
        sers = bc.findall(f"{C}ser")
        fills = [_ser_fill(s) for s in sers]
        # the template's categorical colours, the accent first, every two clearly apart; «Прочее» quiet (no hue)
        assert fills[0] == "0077FF" and set(fills[:3]) <= set(PALETTE)  # (not a colour of the template: not a series colour)
        assert all(delta_e(a, b) >= 20 for i, a in enumerate(fills) for b in fills[i + 1 :])
        assert _chroma(fills[3]) < 12
        # a hairline of the ground between the segments, each value inside its segment
        assert all(s.find(f"{C}spPr/{A}ln/{A}solidFill/{A}srgbClr").get("val") == "FFFFFF" for s in sers)
        assert all(s.find(f"{C}dLbls/{C}dLblPos").get("val") == "ctr" for s in sers)
        # parts need their legend
        assert cs.find(f".//{C}legend") is not None


def test_stacked_series_never_take_the_story_paint():
    # «2025 / 2026» stacked are two parts, not a past and a lead: two template colours, not a tint of the accent
    spec = ChartSpec(type="stacked_column", categories=["I", "II", "III"], series=[InlineSeries(name="2025", values=[3, 4, 5]), InlineSeries(name="2026", values=[4, 5, 6])])
    fills = [_ser_fill(s) for s in _cs(spec).iter(f"{C}ser")]
    assert fills[0] == "0077FF" and fills[1] in PALETTE[1:]


def test_grouped_bars_highlight_a_category_and_keep_the_series_order():
    spec = ChartSpec(type="grouped_bar", categories=REG, series=[InlineSeries(name="2025", values=[480, 260, 150, 120, 98]), InlineSeries(name="2026", values=[560, 300, 207, 131, 110])], unit="млн ₽", highlight_index=2)
    cs = _cs(spec)
    bc = cs.find(f".//{C}barChart")
    assert bc.find(f"{C}grouping").get("val") == "clustered" and bc.find(f"{C}barDir").get("val") == "bar"
    sers = bc.findall(f"{C}ser")
    for ser in sers:
        base = _ser_fill(ser)
        dpt = {int(d.find(f"{C}idx").get("val")): d.find(f"{C}spPr/{A}solidFill/{A}srgbClr").get("val") for d in ser.findall(f"{C}dPt")}
        assert 2 not in dpt and set(dpt) == {0, 1, 3, 4}
        assert all(v == eased(base, "FFFFFF") for v in dpt.values())
        assert all(contrast_ratio(v, "FFFFFF") < contrast_ratio(base, "FFFFFF") for v in dpt.values())  # lighter, never darker
    # the stepped-back group keeps its order of strength: the lead stays stronger than its past
    lead, past = _ser_fill(sers[1]), _ser_fill(sers[0])
    assert contrast_ratio(eased(lead, "FFFFFF"), "FFFFFF") > contrast_ratio(eased(past, "FFFFFF"), "FFFFFF")
    # the first row still names its series («2025: 480»)
    first = [d for d in sers[0].iter(f"{C}dLbl") if d.find(f"{C}idx").get("val") == "0"][0]
    assert first.find(f"{C}showSerName").get("val") == "1"


def test_planner_bars_of_several_series_ignore_a_highlight_as_before():
    spec = ChartSpec(type="column", categories=["Q1", "Q2", "Q3"], series=[InlineSeries(name="Web", values=[12, 15, 19]), InlineSeries(name="Mobile", values=[8, 11, 16])], highlight_index=2)
    assert not list(_cs(spec).iter(f"{C}dPt"))


# ---------------------------------------------------------------------------------------------- gaps and highlight


def test_line_with_gaps_breaks_and_ends_on_its_last_value():
    spec = ChartSpec(type="line", categories=QS, series=[InlineSeries(name="NPS", values=NPS)], gaps=True)
    cs = _cs(spec)
    assert cs.find(f"{C}chart/{C}dispBlanksAs").get("val") == "gap"
    cache = cs.find(f".//{C}lineChart/{C}ser/{C}val/{C}numRef/{C}numCache")
    assert cache.find(f"{C}ptCount").get("val") == "8"
    assert sorted(int(p.get("idx")) for p in cache.findall(f"{C}pt")) == [0, 1, 3, 4, 5, 7]  # a gap, never a zero
    # a missing tail: the end (the highlight) is the last point with a value
    tail = spec.model_copy(update={"series": [InlineSeries(name="NPS", values=[41, 43, None, 46, 48, 49, 52, None])]})
    ser = _cs(tail).find(f".//{C}lineChart/{C}ser")
    big = [d for d in ser.findall(f"{C}dPt") if d.find(f"{C}marker/{C}size") is not None and d.find(f"{C}marker/{C}size").get("val") == "11"]
    assert [int(d.find(f"{C}idx").get("val")) for d in big] == [6]


def test_every_kind_writes_blanks_as_gaps():
    for spec in (_hist(), _stacked(), ChartSpec(type="column", categories=["a", "b"], series=[InlineSeries(name="x", values=[1, None])])):
        assert _cs(spec).find(f"{C}chart/{C}dispBlanksAs").get("val") == "gap"


def test_no_highlight_leaves_the_line_without_an_accented_point():
    spec = ChartSpec(type="line", categories=QS[:5], series=[InlineSeries(name="NPS", values=[41, 43, 45, 46, 48])], highlight_index=NO_HIGHLIGHT)
    ser = _cs(spec).find(f".//{C}lineChart/{C}ser")
    assert not ser.findall(f"{C}dPt")
    default = _cs(spec.model_copy(update={"highlight_index": None})).find(f".//{C}lineChart/{C}ser")
    assert [int(d.find(f"{C}idx").get("val")) for d in default.findall(f"{C}dPt")] == [4]  # the last point by default


# ---------------------------------------------------------------------------------------------- axis titles


def _axis_title(cs, axis: str):
    t = cs.find(f".//{C}plotArea/{C}{axis}/{C}title")
    return t


def test_axis_titles_in_the_template_face_and_muted_colour():
    cs = _cs(_hist(x_title="Минут до ответа", y_title="Число обращений"))
    for axis, text, rot in (("catAx", "Минут до ответа", "0"), ("valAx", "Число обращений", "-5400000")):
        t = _axis_title(cs, axis)
        assert t is not None and _title_text(t) == text
        r = t.find(f".//{A}r/{A}rPr")
        assert r.find(f"{A}latin").get("typeface") == "Play"
        color = r.find(f"{A}solidFill/{A}srgbClr").get("val")
        assert color != TEXT and contrast_ratio(color, "FFFFFF") >= 4.5  # the muted text colour, still readable
        assert r.get("b") == "0"
        assert t.find(f"{C}tx/{C}rich/{A}bodyPr").get("rot") == rot
        assert t.find(f"{C}overlay").get("val") == "0"
        assert t.find(f"{C}layout/{C}manualLayout") is not None
    # the value axis's ticks are replaced by the labels: the axis stays only to carry its title
    va = cs.find(f".//{C}valAx")
    assert va.find(f"{C}delete").get("val") == "0" and va.find(f"{C}tickLblPos").get("val") == "none"
    assert va.find(f"{C}majorGridlines") is None


def test_value_axis_title_carries_the_word_unit_once():
    spec = ChartSpec(type="line", categories=[f"м{i}" for i in range(12)], series=[InlineSeries(name="Выручка", values=[float(300 + 5 * i) for i in range(12)])], unit="млн ₽", y_title="Выручка")
    cs = _cs(spec)
    assert _title_text(_axis_title(cs, "valAx")) == "Выручка, млн ₽"
    assert cs.find(f"{C}chart/{C}title") is None  # no unit caption above: the axis says it
    # a title that names its unit already is kept as written
    cs = _cs(spec.model_copy(update={"y_title": "Выручка, млн ₽"}))
    assert _title_text(_axis_title(cs, "valAx")) == "Выручка, млн ₽"
    # horizontal bars: the categories' title along the left axis, the values' under the bars
    bars = ChartSpec(type="bar", categories=REG, series=[InlineSeries(name="Выручка", values=[508, 214, 131, 98, 87])], unit="млн ₽", x_title="Регион", y_title="Выручка")
    cs = _cs(bars)
    assert cs.find(f".//{C}catAx/{C}title/{C}tx/{C}rich/{A}bodyPr").get("rot") == "-5400000"
    assert cs.find(f".//{C}valAx/{C}title/{C}tx/{C}rich/{A}bodyPr").get("rot") == "0"


def test_axis_titles_take_room_so_the_plot_moves_in():
    plain = _cs(_hist())
    titled = _cs(_hist(x_title="Минут до ответа", y_title="Число обращений"))

    def ml(cs):
        el = cs.find(f".//{C}plotArea/{C}layout/{C}manualLayout")
        return {k: float(el.find(f"{C}{k}").get("val")) for k in ("x", "y", "w", "h")}

    a, b = ml(plain), ml(titled)
    assert b["x"] > a["x"] and b["y"] + b["h"] < a["y"] + a["h"]
    # the left title sits left of the plot, the bottom one under it
    yl = titled.find(f".//{C}valAx/{C}title/{C}layout/{C}manualLayout")
    xl = titled.find(f".//{C}catAx/{C}title/{C}layout/{C}manualLayout")
    assert float(yl.find(f"{C}x").get("val")) < b["x"]
    assert float(xl.find(f"{C}y").get("val")) > b["y"] + b["h"]


def test_pies_take_no_axis_titles():
    spec = ChartSpec(type="pie", categories=["a", "b"], series=[InlineSeries(name="s", values=[60, 40])], unit="%", x_title="x", y_title="y")
    cs = _cs(spec)
    assert not list(cs.iter(f"{C}title")) or all(_title_text(t) not in ("x", "y") for t in cs.iter(f"{C}title"))


# ---------------------------------------------------------------------------------------------- scatter


def test_scatter_is_native_xy_points_with_quiet_axes():
    assert chart_data_ok(_scatter(), OUTLINE) and resolve_series(_scatter(), OUTLINE) == []
    assert not chart_data_ok(ChartSpec(type="scatter"), OUTLINE)
    assert xy_series(ChartSpec(type="scatter", xy=[XYSeries(name="a", x=[1, 2, 3], y=[4, 5])])) == [("a", [1.0, 2.0], [4.0, 5.0])]
    cs = _cs(_scatter(x_title="Средний чек, тыс. ₽", y_title="Выручка на клиента", unit="тыс. ₽"))
    sc = cs.find(f".//{C}scatterChart")
    assert sc is not None
    ser = sc.find(f"{C}ser")
    xs = [float(p.find(f"{C}v").text) for p in ser.findall(f"{C}xVal//{C}pt")]
    ys = [float(p.find(f"{C}v").text) for p in ser.findall(f"{C}yVal//{C}pt")]
    assert xs[:3] == [120.0, 180.0, 220.0] and ys[:3] == [110.0, 160.0, 230.0]
    # points only: the series has no line, its markers are ringed circles in the accent
    assert ser.find(f"{C}spPr/{A}ln/{A}noFill") is not None
    mk = ser.find(f"{C}marker")
    assert mk.find(f"{C}symbol").get("val") == "circle"
    assert mk.find(f"{C}spPr/{A}solidFill/{A}srgbClr").get("val") == "0077FF"
    # two value axes: X under a hairline baseline, Y with quiet gridlines; both titled
    axes = cs.findall(f".//{C}plotArea/{C}valAx")
    assert len(axes) == 2
    by_pos = {a.find(f"{C}axPos").get("val"): a for a in axes}
    assert by_pos["l"].find(f"{C}majorGridlines") is not None and by_pos["b"].find(f"{C}majorGridlines") is None
    assert _title_text(by_pos["b"].find(f"{C}title")) == "Средний чек, тыс. ₽"
    assert _title_text(by_pos["l"].find(f"{C}title")) == "Выручка на клиента, тыс. ₽"
    # every axis id pairs with the other (LibreOffice reads them as signed 32-bit)
    ids = {a.find(f"{C}axId").get("val") for a in axes}
    assert all(a.find(f"{C}crossAx").get("val") in ids for a in axes) and all(int(i) < 2**31 for i in ids)


def test_scatter_highlight_is_one_larger_point_with_its_value():
    cs = _cs(_scatter(highlight_index=3))
    ser = cs.find(f".//{C}scatterChart/{C}ser")
    dpt = ser.find(f"{C}dPt")
    assert dpt.find(f"{C}idx").get("val") == "3"
    assert dpt.find(f"{C}marker/{C}spPr/{A}solidFill/{A}srgbClr").get("val") == "0077FF"
    assert ser.find(f"{C}marker/{C}spPr/{A}solidFill/{A}srgbClr").get("val") != "0077FF"
    labels = ser.findall(f"{C}dLbls/{C}dLbl")
    assert [d.find(f"{C}idx").get("val") for d in labels] == ["3"]
    assert ser.find(f"{C}dLbls/{C}showVal").get("val") == "0"
    # (the series' label list sits before its X values: schema order)
    names = [c.tag.split("}")[1] for c in ser]
    assert names.index("dLbls") < names.index("xVal")


def test_scatter_of_several_series_uses_the_palette_and_a_legend():
    spec = ChartSpec(type="scatter", xy=[XYSeries(name="Москва", x=[1, 2, 3], y=[3, 4, 5]), XYSeries(name="Регионы", x=[1, 2, 3], y=[1, 2, 2])])
    cs = _cs(spec)
    fills = [s.find(f"{C}marker/{C}spPr/{A}solidFill/{A}srgbClr").get("val") for s in cs.iter(f"{C}ser")]
    assert fills[0] == "0077FF" and delta_e(fills[0], fills[1]) >= 20
    assert cs.find(f".//{C}legend") is not None


# ---------------------------------------------------------------------------------------------- source line


def test_source_line_under_the_chart_inside_its_frame():
    assert source_text("Выручка по месяцам.csv") == "Источник: Выручка по месяцам.csv"
    assert source_text("Источник: Росстат") == "Источник: Росстат"
    assert source_text("  ") is None
    prs, s, gf = _gf(_hist(source="Время ответа поддержки.csv"))
    src = gf.verstka_source
    assert src is not None and src.name == "Chart source"
    assert src.text_frame.text == "Источник: Время ответа поддержки.csv"
    # under the chart, both inside the caller's frame
    assert gf.top == BOX.y and gf.top + gf.height <= src.top and src.top + src.height <= BOX.y + BOX.h + 1
    run = src.text_frame.paragraphs[0].runs[0]
    # small print: the template's face, never larger than the chart's category labels
    cat_size = int(gf.chart._chartSpace.find(f".//{C}catAx/{C}txPr/{A}p/{A}pPr/{A}defRPr").get("sz")) / 100
    assert run.font.name == "Play" and run.font.size.pt <= cat_size
    color = str(run.font.color.rgb)
    assert color != TEXT and contrast_ratio(color, "FFFFFF") >= 4.5
    # no source, no line; the chart keeps the whole frame
    prs, s, gf = _gf(_hist())
    assert gf.verstka_source is None and gf.height == BOX.h
    assert not [sh for sh in s.shapes if sh.name == "Chart source"]


def test_source_said_by_the_slide_is_not_repeated():
    assert source_said("Выручка по месяцам.csv", "Источник: Выручка по месяцам.csv")
    assert source_said("Источник: Регионы.xlsx", "Данные: регионы.xlsx, выгрузка CRM")
    assert not source_said("Регионы.xlsx", "Все цифры условные")
    assert not source_said("Регионы.xlsx", None)
    assert source_said(None, None)  # nothing to print


def test_source_line_on_a_dark_ground_stays_readable():
    prs, s, gf = _gf(_hist(source="Время ответа поддержки.csv"), bg="0B1220")
    color = str(gf.verstka_source.text_frame.paragraphs[0].runs[0].font.color.rgb)
    assert contrast_ratio(color, "0B1220") >= 4.5


# ---------------------------------------------------------------------------------------------- audit reads gaps


def _save(prs, tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    prs.save(str(p))
    return p


def _ir_chart(path: Path):
    ir = build_deck_ir(path)
    return next(e.chart for e in ir.slides[0].elements if e.type == "chart")


def test_audit_reads_a_gap_in_place(tmp_path):
    spec = ChartSpec(type="line", categories=QS, series=[InlineSeries(name="NPS", values=NPS)], gaps=True, y_title="NPS", x_title="Квартал")
    prs, s, gf = _gf(spec)
    ch = _ir_chart(_save(prs, tmp_path, "gaps.pptx"))
    assert ch.categories == QS
    assert ch.series[0].values == [41.0, 43.0, None, 46.0, 48.0, 49.0, None, 52.0]  # every value against its own quarter
    assert ch.title is None  # an axis title is not the chart's title
    assert not ch.has_value_axis  # (the axis kept for its title shows no values)


def test_audit_reads_a_scatter_and_a_histogram(tmp_path):
    prs, s, gf = _gf(_scatter(y_title="Выручка на клиента", x_title="Средний чек"))
    ch = _ir_chart(_save(prs, tmp_path, "xy.pptx"))
    assert ch.type == "scatter" and ch.series[0].values[:3] == [110.0, 160.0, 230.0]
    assert ch.categories[:3] == ["120", "180", "220"] and ch.has_value_axis
    prs, s, gf = _gf(_hist())
    ch = _ir_chart(_save(prs, tmp_path, "hist.pptx"))
    assert ch.type == "column" and ch.categories == BINS and ch.series[0].values == [float(v) for v in COUNTS]


def test_chart_rows_keep_values_with_their_categories():
    class Ctx:
        outline = None

    osl = OutlineSlide(id="s1", kind="chart", headline="NPS", content=SlideContent(chart=ChartSpec(type="line", categories=QS, series=[InlineSeries(name="NPS", values=NPS)])))
    rows = _chart_rows(osl, Ctx())
    assert rows == [[(c, v, 1.0) for c, v in zip(QS, NPS) if v is not None]]
    assert ("III кв. 2025", 46, 1.0) in rows[0]  # not shifted onto «II кв. 2025»


# ---------------------------------------------------------------------------------------------- the slide composer


def _compose(env, oslide: OutlineSlide):
    from verstka.rendering.deck import DeckBuilder
    from verstka.rendering.synth import render_synth
    from verstka.schemas.layout import LayoutSlide

    deck, manifest, ws = env
    b = DeckBuilder(deck)
    outline = DeckOutline(title="T", strategy="structured", slides=[oslide])
    slide, _ = render_synth(b, LayoutSlide(outline_id=oslide.id, mode="synth", composition="chart"), oslide, manifest, ws, outline)
    return slide


@pytest.fixture
def env(simple_deck, tmp_path):
    from verstka.analysis.manifest import analyze_template
    from verstka.ingest.workspace import TemplateWorkspace

    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    return simple_deck, manifest, ws


def test_composer_prints_the_source_once(env):
    chart = ChartSpec(type="line", categories=QS, series=[InlineSeries(name="NPS", values=NPS)], gaps=True, source="NPS по кварталам.csv", y_title="NPS")
    with_foot = OutlineSlide(id="s1", kind="chart", headline="NPS вырос до 52", footnote="Источник: NPS по кварталам.csv", content=SlideContent(chart=chart))
    slide = _compose(env, with_foot)
    texts = [" ".join(sh.text_frame.text.replace("\u00a0", " ").split()) for sh in slide.shapes if getattr(sh, "has_text_frame", False)]
    assert sum("NPS по кварталам.csv" in t for t in texts) == 1  # the slide's footnote
    assert not [sh for sh in slide.shapes if sh.name == "Chart source"]
    # no footnote: the chart prints its own source line
    slide = _compose(env, with_foot.model_copy(update={"footnote": None}))
    assert [sh.text_frame.text for sh in slide.shapes if sh.name == "Chart source"] == ["Источник: NPS по кварталам.csv"]
    # the value axis's title names the measure: no unit caption repeats it over the chart
    assert not [sh for sh in slide.shapes if sh.name in ("Unit", "Chart title")]


# ---------------------------------------------------------------------------------------------- LibreOffice preview


def test_libreoffice_renders_every_new_kind(tmp_path):
    from verstka.ingest.render import find_soffice, render_slides

    if not find_soffice():
        pytest.skip("LibreOffice is not installed")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    specs = [
        _hist(x_title="Минут до ответа", y_title="Число обращений", source="Время ответа поддержки.csv"),
        _stacked(y_title="Выручка"), _stacked("stacked_bar"),
        ChartSpec(type="grouped_column", categories=["I", "II", "III"], series=[InlineSeries(name="2025", values=[3, 4, 5]), InlineSeries(name="2026", values=[4, 5, None])], highlight_index=1),
        ChartSpec(type="line", categories=QS, series=[InlineSeries(name="NPS", values=NPS)], gaps=True, y_title="NPS"),
        _scatter(x_title="Средний чек", y_title="Выручка", highlight_index=2),
    ]
    for spec in specs:
        s = prs.slides.add_slide(prs.slide_layouts[6])
        add_chart(s, BOX, spec, OUTLINE, STYLE, TYPO, text_hex=TEXT)
    pngs = render_slides(_save(prs, tmp_path, "kinds.pptx"), tmp_path / "png", dpi=40, keep_pdf=False)
    assert len(pngs) == len(specs) and all(p.stat().st_size > 0 for p in pngs)


# ---------------------------------------------------------------------------------------------- review fixes (round 2)

NBSP = "\u00a0"
NARROW = Bbox(x=int(W * 0.06), y=int(H * 0.22), w=int(W * 0.30), h=int(H * 0.45))
BINS12 = [f"{i * 250:,}–{(i + 1) * 250:,}".replace(",", NBSP) for i in range(11)] + [f"больше 2{NBSP}750"]
COUNTS12 = [5, 18, 44, 80, 121, 140, 118, 77, 41, 20, 9, 4]


def _in(box: Bbox, spec: ChartSpec, bg: str = "FFFFFF", **kw):
    prs, s = _slide(bg)
    gf = add_chart(s, box, spec, OUTLINE, STYLE, TYPO, text_hex=TEXT if bg == "FFFFFF" else "FFFFFF", **kw)
    return prs, s, gf


def _axis(cs, pos: str):
    """The axis of a chart whose c:axPos is `pos` (bar charts: a catAx and a valAx; scatter: two valAx)."""
    return next(a for a in cs.findall(f".//{C}plotArea/*") if a.tag in (f"{C}catAx", f"{C}valAx") and a.find(f"{C}axPos").get("val") == pos)


def _neg_scatter(**kw) -> ChartSpec:
    return ChartSpec(type="scatter", xy=[XYSeries(name="a", x=[-5, -3, 0, 2, 4], y=[-20, -5, 3, 10, 30])], x_title="Изменение цены, %", y_title="Изменение спроса, %", **kw)


def test_scatter_y_axis_stands_at_the_left_when_x_spans_zero():
    cs = _cs(_neg_scatter())
    y_axis = _axis(cs, "l")
    # it crosses X at X's minimum and writes its ticks low: never in the middle of the points
    assert y_axis.find(f"{C}crosses").get("val") == "min"
    assert y_axis.find(f"{C}tickLblPos").get("val") == "low"
    # the X axis keeps its hairline at Y = 0 (a negative Y reads against it), its ticks low
    x_axis = _axis(cs, "b")
    assert x_axis.find(f"{C}tickLblPos").get("val") == "low"
    assert float(x_axis.find(f"{C}scaling/{C}min").get("val")) < 0 < float(x_axis.find(f"{C}scaling/{C}max").get("val"))


def test_scatter_axes_use_the_room_they_have():
    # 137…590 reads 100…600 (not 0…800); −24…517 stays within −100…600 (not −200…600)
    assert _scatter_range([137, 300, 590])[:2] == (100.0, 600.0)
    lo, hi, step = _scatter_range([-24, 100, 300, 517])
    assert -100 <= lo <= -24 and 517 <= hi <= 600 and step == 100
    # data near zero still start at zero; steps are round and bounded by the room the labels have
    assert _scatter_range([2, 40, 95])[0] == 0.0
    for vals, room in (([137, 590], 5), ([0.012, 0.047], 9), ([-3, 4], 4)):
        lo, hi, step = _scatter_range(vals, room)
        n = round((hi - lo) / step)
        assert 3 <= n <= max(3, room) and lo <= min(vals) and hi >= max(vals)


def _cloud(n: int = 500):
    rnd = random.Random(3)
    xs = [rnd.gauss(300, 90) for _ in range(n)]
    ys = [x * 0.8 + rnd.gauss(0, 40) for x in xs]
    return xs, ys


def test_scatter_of_500_points_renders_and_keeps_its_highlight_label_off_the_cloud():
    xs, ys = _cloud()
    spec = ChartSpec(type="scatter", xy=[XYSeries(name="Клиенты", x=xs, y=ys)], x_title="Средний чек", y_title="Выручка", highlight_index=7)
    cs = _cs(spec)
    ser = cs.find(f".//{C}scatterChart/{C}ser")
    assert len(ser.findall(f"{C}xVal//{C}pt")) == 500
    lbl = ser.find(f"{C}dLbls/{C}dLbl")
    assert lbl.find(f"{C}idx").get("val") == "7"
    # the label is nudged to free ground (or sits on a chip of the ground where it must touch a marker)
    nudged = lbl.find(f"{C}layout/{C}manualLayout") is not None
    chip = lbl.find(f"{C}spPr/{A}solidFill/{A}srgbClr")
    assert nudged or (chip is not None and chip.get("val") == "FFFFFF")


def test_label_spot_finds_the_free_ground_nearest_the_point():
    rnd = random.Random(5)
    pts = [(rnd.gauss(400, 90), rnd.gauss(250, 60)) for _ in range(500)]
    me = pts[7]
    bounds = (0.0, 0.0, 900.0, 520.0)
    cx, cy, touched = _label_spot(me, (24.0, 14.0), pts, 3.5, 7.5, bounds, 9.0)
    box = (cx - 12, cy - 7, cx + 12, cy + 7)
    assert bounds[0] <= box[0] and box[2] <= bounds[2] and bounds[1] <= box[1] and box[3] <= bounds[3]
    hits = sum(1 for q in pts if q != me and box[0] - 3.5 <= q[0] <= box[2] + 3.5 and box[1] - 3.5 <= q[1] <= box[3] + 3.5)
    assert hits == touched
    # an isolated point (the cloud's outlier) gets a free spot right beside it
    lone = (60.0, 480.0)
    cx, cy, touched = _label_spot(lone, (24.0, 14.0), pts + [lone], 3.5, 7.5, bounds, 9.0)
    assert touched == 0 and math.hypot(cx - lone[0], cy - lone[1]) < 45


def test_value_axis_of_top_down_bars_stands_at_the_bottom():
    # a narrow slot cannot hold the values inside the segments: the quiet axis comes — under the bars, not above them
    spec = ChartSpec(type="stacked_bar", categories=["Москва", "Казань", "Самара"], series=[InlineSeries(name="Прибыль", values=[50, 20, -10]), InlineSeries(name="Убыток", values=[-30, -40, -5])], unit="млн ₽")
    cs = _in(NARROW, spec)[2].chart._chartSpace
    cat, val = cs.find(f".//{C}catAx"), cs.find(f".//{C}valAx")
    assert cat.find(f"{C}scaling/{C}orientation").get("val") == "maxMin"  # read top-down
    assert val.find(f"{C}delete").get("val") == "0" and val.find(f"{C}tickLblPos").get("val") == "nextTo"
    assert val.find(f"{C}crosses").get("val") == "max"  # «max» of reversed categories: the bottom edge
    # the room is reserved at the bottom as well: the plot ends above the axis labels
    ml = cs.find(f".//{C}plotArea/{C}layout/{C}manualLayout")
    assert float(ml.find(f"{C}y").get("val")) + float(ml.find(f"{C}h").get("val")) < 0.95
    # the planner's horizontal bars with an axis (several series) cross the same way
    bars = ChartSpec(type="bar", categories=REG, series=[InlineSeries(name="2025", values=[480, 260, 150, 120, 98]), InlineSeries(name="2026", values=[560, 300, 207, 131, 110])], unit="млн ₽")
    val = _in(NARROW, bars)[2].chart._chartSpace.find(f".//{C}valAx")
    assert val.find(f"{C}crosses").get("val") == "max"


def _label_pieces_fit(cs, frame_w_pt: float, n: int) -> bool:
    rot = cs.find(f".//{C}catAx/{C}txPr/{A}bodyPr").get("rot")
    if rot not in (None, "0"):
        return True  # turned: a label is never broken
    size = int(cs.find(f".//{C}catAx/{C}txPr/{A}p/{A}pPr/{A}defRPr").get("sz")) / 100
    pw = float(cs.find(f".//{C}plotArea/{C}layout/{C}manualLayout/{C}w").get("val")) * frame_w_pt
    labels = [v.text for v in cs.findall(f".//{C}catAx/../{C}barChart/{C}ser/{C}cat//{C}pt/{C}v")]
    return all(text_width_pt(p, "Play", size) <= pw / n * 0.95 for t in labels for p in label_pieces(t))


def test_histogram_bin_labels_never_break_inside_a_number():
    all_nbsp = [b.replace(" ", NBSP) for b in BINS12[:-1]] + [f"больше{NBSP}2{NBSP}750"]  # («больше 2 750» one piece)
    for box in (BOX, NARROW):
        for cats in (BINS12, all_nbsp):
            prs, s, gf = _in(box, ChartSpec(type="histogram", categories=cats, series=[InlineSeries(name="Заказы", values=COUNTS12)], x_title="Сумма заказа, ₽", y_title="Число заказов"))
            cs = gf.chart._chartSpace
            labels = [v.text for v in cs.findall(f".//{C}barChart/{C}ser/{C}cat//{C}pt/{C}v")]
            assert len(labels) == 12 and not [t for t in labels if re.search(r"\d \d{3}", t)]  # (no ordinary space inside a number)
            # either every piece a renderer may break between fits its slot (so it breaks after the dash, before a
            # word), or the labels are turned: the labels are whole
            assert _label_pieces_fit(cs, box.w / 12700, 12), (box, cats[-1])
    # the labels of the full-width chart stay straight and wrap after the dash (two short lines each)
    cs = _in(BOX, ChartSpec(type="histogram", categories=BINS12, series=[InlineSeries(name="Заказы", values=COUNTS12)]))[2].chart._chartSpace
    assert cs.find(f".//{C}catAx/{C}txPr/{A}bodyPr").get("rot") in (None, "0")
    # ordinary spaces written into the bins are bound too
    cs = _cs(ChartSpec(type="histogram", categories=[b.replace(NBSP, " ") for b in BINS12], series=[InlineSeries(name="Заказы", values=COUNTS12)]))
    texts = [v.text for v in cs.findall(f".//{C}barChart/{C}ser/{C}cat//{C}pt/{C}v")]
    assert f"1{NBSP}000–1{NBSP}250" in texts and not [t for t in texts if re.search(r"\d \d{3}", t)]


def test_wrap_breaks_after_a_range_dash_and_never_inside_a_number():
    n = NBSP
    assert glue_numbers("1 250–1 500") == f"1{n}250–1{n}500" and glue_numbers("2026") == "2026" and glue_numbers("Янв 2026") == "Янв 2026"
    assert label_pieces(f"1{n}250–1{n}500") == [f"1{n}250–", f"1{n}500"]
    assert label_pieces(f"больше 2{n}750") == ["больше", f"2{n}750"]
    assert break_pieces(f"2{n}750 тыс.") == [(f"2{n}750", " "), ("тыс.", " ")]
    # default behaviour of the other callers is unchanged: no break after a dash, none at a no-break space
    label = f"1{n}000–1{n}250"
    assert wrap_lines(label, "Play", 9, False, 400) == [label]
    assert wrap_lines(label, "Play", 9, False, 40, dashes=True) == [f"1{n}000–", f"1{n}250"]
    assert wrap_lines(f"в{n}VK 27{n}млн рублей", "Play", 9, False, 60) == [f"в{n}VK 27{n}млн", "рублей"]


def test_stacked_columns_with_negatives_span_both_sides_and_read_on_their_fills():
    spec = ChartSpec(type="stacked_column", categories=["I кв.", "II кв.", "III кв.", "IV кв."], series=[
        InlineSeries(name="Выручка", values=[120, 134, 142, 151]), InlineSeries(name="Расходы", values=[-90, -110, -150, -100]), InlineSeries(name="Прочее", values=[10, -15, 5, 20])], unit="млн ₽", y_title="Результат")
    for bg, text in (("FFFFFF", TEXT), ("0B1220", "FFFFFF")):
        cs = _in(BOX, spec, bg)[2].chart._chartSpace
        va = cs.find(f".//{C}valAx")
        lo, hi = float(va.find(f"{C}scaling/{C}min").get("val")), float(va.find(f"{C}scaling/{C}max").get("val"))
        assert lo <= -150 and hi >= 160  # every stack fits: positives up, negatives down
        for ser in cs.iter(f"{C}ser"):
            fill = _ser_fill(ser)
            ink = ser.find(f"{C}dLbls/{C}txPr//{A}defRPr/{A}solidFill/{A}srgbClr").get("val")
            if ser.find(f"{C}tx//{C}v").text != "Прочее":
                assert contrast_ratio(ink, fill) >= 4.5, (bg, fill, ink)
    # a 12 pt value on the template's pink or blue: never the 3:1 of large print
    for fill in ("FF3D8B", "0077FF", "FF6C6C", "00D3E6"):
        assert contrast_ratio(_label_on(fill, "000000", "FFFFFF", 4.5), fill) >= 4.5
    assert contrast_ratio(_label_on("FF3D8B", "000000", "FFFFFF"), "FF3D8B") < 4.5  # (the pie's larger figures keep 3:1: white)


def test_dark_ground_charts_keep_their_titles_and_labels_readable():
    ground = "0B1220"
    for spec in (_hist(x_title="Минут", y_title="Число", source="Файл.csv"), _scatter(x_title="x", y_title="y", highlight_index=2),
                 ChartSpec(type="stacked_bar", categories=REG, series=[InlineSeries(name="a", values=[3, 2, 4, 1, 5]), InlineSeries(name="b", values=[1, 2, 1, 2, 1])], y_title="Объём")):
        prs, s, gf = _in(BOX, spec, ground)
        for r in gf.chart._chartSpace.iter(f"{A}rPr"):
            clr = r.find(f"{A}solidFill/{A}srgbClr")
            if clr is not None:
                assert contrast_ratio(clr.get("val"), ground) >= 4.5


def test_axis_titles_ticks_legend_and_source_share_one_grey():
    muted = "6B7280"
    spec = _hist(x_title="Минут до ответа", y_title="Число обращений", source="Файл.csv")
    prs, s, gf = _in(BOX, spec, muted_hex=muted)
    cs = gf.chart._chartSpace
    for axis in ("catAx", "valAx"):
        assert _axis_title(cs, axis).find(f".//{A}rPr/{A}solidFill/{A}srgbClr").get("val") == muted
    assert cs.find(f".//{C}catAx/{C}txPr//{A}defRPr/{A}solidFill/{A}srgbClr").get("val") == muted
    assert str(gf.verstka_source.text_frame.paragraphs[0].runs[0].font.color.rgb) == muted
    # a secondary colour too faint for small print is not used: the chart's own readable grey stays
    prs, s, gf = _in(BOX, spec, muted_hex="D1D5DB")
    assert _axis_title(gf.chart._chartSpace, "catAx").find(f".//{A}rPr/{A}solidFill/{A}srgbClr").get("val") not in ("D1D5DB",)


def test_gaps_flag_decides_how_a_line_meets_a_missing_value():
    line = ChartSpec(type="line", categories=QS, series=[InlineSeries(name="NPS", values=NPS)])
    assert _cs(line).find(f"{C}chart/{C}dispBlanksAs").get("val") == "span"  # no break asked: the line runs through
    assert _cs(line.model_copy(update={"gaps": True})).find(f"{C}chart/{C}dispBlanksAs").get("val") == "gap"
    area = ChartSpec(type="area", categories=QS, series=[InlineSeries(name="NPS", values=NPS)])
    assert _cs(area).find(f"{C}chart/{C}dispBlanksAs").get("val") == "span"
    assert _cs(area.model_copy(update={"gaps": True})).find(f"{C}chart/{C}dispBlanksAs").get("val") == "gap"
    # bars have nothing to draw at a missing value either way; no zero is ever written
    bars = ChartSpec(type="column", categories=["a", "b", "c"], series=[InlineSeries(name="x", values=[1, None, 3])])
    cs = _cs(bars)
    assert cs.find(f"{C}chart/{C}dispBlanksAs").get("val") == "gap"
    assert sorted(int(p.get("idx")) for p in cs.findall(f".//{C}barChart/{C}ser/{C}val//{C}pt")) == [0, 2]


def test_area_marker_and_label_sit_on_the_last_value():
    spec = ChartSpec(type="area", categories=QS, series=[InlineSeries(name="NPS", values=[41, 43, 44, 46, 48, 49, 52, None])], gaps=True)
    cs = _cs(spec)
    edge = cs.find(f".//{C}lineChart/{C}ser")
    assert edge.find(f"{C}dPt/{C}idx").get("val") == "6"
    assert [d.find(f"{C}idx").get("val") for d in edge.findall(f"{C}dLbls/{C}dLbl")] == ["6"]
    full = ChartSpec(type="area", categories=QS, series=[InlineSeries(name="NPS", values=[41, 43, 44, 46, 48, 49, 52, 53])])
    assert _cs(full).find(f".//{C}lineChart/{C}ser/{C}dPt/{C}idx").get("val") == "7"


def test_source_line_survives_a_small_frame_or_is_handed_back():
    spec = _hist(source="Время ответа поддержки.csv")
    small = Bbox(x=BOX.x, y=BOX.y, w=int(W * 0.5), h=int(H * 0.17))  # ≈ 92 pt: a chart and a line, the line kept
    gf = _in(small, spec)[2]
    assert gf.verstka_source is not None and gf.verstka_source_dropped is None
    assert gf.top + gf.height <= gf.verstka_source.top and gf.verstka_source.top + gf.verstka_source.height <= small.y + small.h + 1
    tiny = Bbox(x=BOX.x, y=BOX.y, w=int(W * 0.5), h=int(H * 0.05))  # ≈ 27 pt: no room for both — the line is handed back
    gf = _in(tiny, spec)[2]
    assert gf.verstka_source is None and gf.verstka_source_dropped == "Источник: Время ответа поддержки.csv"
    assert gf.height == tiny.h
    assert _in(BOX, _hist())[2].verstka_source_dropped is None


def test_narrow_slot_keeps_every_new_kind_inside_its_frame():
    specs = [
        _hist(x_title="Минут до ответа", y_title="Число обращений", source="Файл.csv"), _stacked(y_title="Выручка"), _stacked("stacked_bar", x_title="Квартал"),
        _scatter(x_title="Средний чек", y_title="Выручка", highlight_index=2), _neg_scatter(),
        ChartSpec(type="grouped_bar", categories=REG, series=[InlineSeries(name="2025", values=[480, 260, 150, 120, 98]), InlineSeries(name="2026", values=[560, 300, 207, 131, 110])], unit="млн ₽", highlight_index=2),
    ]
    for spec in specs:
        gf = _in(NARROW, spec)[2]
        cs = gf.chart._chartSpace
        ml = cs.find(f".//{C}plotArea/{C}layout/{C}manualLayout")
        x, y, w, h = (float(ml.find(f"{C}{k}").get("val")) for k in ("x", "y", "w", "h"))
        assert 0 <= x and x + w <= 1.0001 and 0 <= y and y + h <= 1.0001 and w >= 0.3, spec.type
        for t in cs.iter(f"{C}title"):
            tl = t.find(f"{C}layout/{C}manualLayout")
            if tl is not None:
                assert 0 <= float(tl.find(f"{C}x").get("val")) <= 1 and 0 <= float(tl.find(f"{C}y").get("val")) <= 1


# ---------------------------------------------------------------------------------------------- schema order

C_ORDER = {
    "title": ["tx", "layout", "overlay", "spPr", "txPr", "extLst"],
    "valAx": ["axId", "scaling", "delete", "axPos", "majorGridlines", "minorGridlines", "title", "numFmt", "majorTickMark", "minorTickMark", "tickLblPos", "spPr", "txPr", "crossAx", "crosses", "crossesAt", "crossBetween", "majorUnit", "minorUnit", "dispUnits", "extLst"],
    "catAx": ["axId", "scaling", "delete", "axPos", "majorGridlines", "minorGridlines", "title", "numFmt", "majorTickMark", "minorTickMark", "tickLblPos", "spPr", "txPr", "crossAx", "crosses", "crossesAt", "auto", "lblAlgn", "lblOffset", "tickLblSkip", "tickMarkSkip", "noMultiLvlLbl", "extLst"],
    "barChart": ["barDir", "grouping", "varyColors", "ser", "dLbls", "gapWidth", "overlap", "serLines", "axId", "extLst"],
    "lineChart": ["grouping", "varyColors", "ser", "dLbls", "dropLines", "hiLowLines", "upDownBars", "marker", "smooth", "axId", "extLst"],
    "areaChart": ["grouping", "varyColors", "ser", "dLbls", "dropLines", "axId", "extLst"],
    "scatterChart": ["scatterStyle", "varyColors", "ser", "dLbls", "axId", "extLst"],
    "chart": ["title", "autoTitleDeleted", "pivotFmts", "view3D", "floor", "sideWall", "backWall", "plotArea", "legend", "plotVisOnly", "dispBlanksAs", "showDLblsOverMax", "extLst"],
    "marker": ["symbol", "size", "spPr", "extLst"],
    "dPt": ["idx", "invertIfNegative", "marker", "bubble3D", "explosion", "spPr", "pictureOptions", "extLst"],
    "dLbl": ["idx", "delete", "layout", "tx", "numFmt", "spPr", "txPr", "dLblPos", "showLegendKey", "showVal", "showCatName", "showSerName", "showPercent", "showBubbleSize", "separator", "extLst"],
    "dLbls": ["dLbl", "delete", "numFmt", "spPr", "txPr", "dLblPos", "showLegendKey", "showVal", "showCatName", "showSerName", "showPercent", "showBubbleSize", "separator", "showLeaderLines", "leaderLines", "extLst"],
}
C_SER = {
    "barChart": ["idx", "order", "tx", "spPr", "invertIfNegative", "pictureOptions", "dPt", "dLbls", "trendline", "errBars", "cat", "val", "shape", "extLst"],
    "scatterChart": ["idx", "order", "tx", "spPr", "marker", "dPt", "dLbls", "trendline", "errBars", "xVal", "yVal", "smooth", "extLst"],
    "lineChart": ["idx", "order", "tx", "spPr", "marker", "dPt", "dLbls", "trendline", "errBars", "cat", "val", "smooth", "extLst"],
    "areaChart": ["idx", "order", "tx", "spPr", "pictureOptions", "dPt", "dLbls", "trendline", "errBars", "cat", "val", "extLst"],
}


def _order_problems(chart_space) -> list[str]:
    """Children of the chart elements this module writes against the sequences of the DrawingML chart schema."""
    bad = []
    for el in chart_space.iter():
        if not isinstance(el.tag, str) or etree.QName(el).namespace != C[1:-1]:
            continue
        loc = etree.QName(el).localname
        seq = C_SER.get(etree.QName(el.getparent()).localname) if loc == "ser" else C_ORDER.get(loc)
        if not seq:
            continue
        kids = [etree.QName(k).localname for k in el if isinstance(k.tag, str)]
        pos = [seq.index(k) if k in seq else -1 for k in kids]
        if -1 in pos or pos != sorted(pos):
            bad.append(f"{loc}: {kids}")
    return bad


def _every_kind():
    xs, ys = _cloud(60)
    return [
        _hist(x_title="Минут", y_title="Число", source="Файл.csv", highlight_index=2),
        ChartSpec(type="histogram", categories=BINS12, series=[InlineSeries(name="n", values=COUNTS12)], x_title="Сумма", y_title="Число"),
        _stacked(y_title="Выручка"), _stacked("stacked_bar", x_title="Квартал", y_title="Выручка"),
        ChartSpec(type="stacked_column", categories=["a", "b", "c"], series=[InlineSeries(name="x", values=[3, -2, 4]), InlineSeries(name="y", values=[-1, 2, 2])]),
        ChartSpec(type="grouped_column", categories=["I", "II", "III"], series=[InlineSeries(name="2025", values=[3, 4, 5]), InlineSeries(name="2026", values=[4, 5, None])], highlight_index=1),
        ChartSpec(type="grouped_bar", categories=REG, series=[InlineSeries(name="2025", values=[480, 260, 150, 120, 98]), InlineSeries(name="2026", values=[560, 300, 207, 131, 110])], unit="млн ₽", highlight_index=2),
        ChartSpec(type="line", categories=QS, series=[InlineSeries(name="NPS", values=NPS)], gaps=True, y_title="NPS", x_title="Квартал"),
        ChartSpec(type="area", categories=QS, series=[InlineSeries(name="NPS", values=NPS[:-1] + [None])], y_title="NPS"),
        ChartSpec(type="column", categories=["a", "b", "c"], series=[InlineSeries(name="x", values=[1, None, 3])], unit="%"),
        _scatter(x_title="Средний чек", y_title="Выручка", highlight_index=2), _neg_scatter(),
        ChartSpec(type="scatter", xy=[XYSeries(name="Клиенты", x=xs, y=ys)], highlight_index=7),
    ]


def test_every_chart_part_keeps_the_schema_order():
    for box in (BOX, NARROW):
        for spec in _every_kind():
            cs = _in(box, spec)[2].chart._chartSpace
            assert _order_problems(cs) == [], (spec.type, box.w)


def _chart_xsd():
    for root in (Path.home() / ".claude/skills/pptx/scripts/office/schemas/ISO-IEC29500-4_2016",):
        if (root / "dml-chart.xsd").is_file():
            return root / "dml-chart.xsd"
    return None


def test_every_chart_part_validates_against_the_iso_chart_schema(tmp_path):
    xsd = _chart_xsd()
    if xsd is None:
        pytest.skip("ISO 29500 dml-chart.xsd is not installed here")
    schema = etree.XMLSchema(etree.parse(str(xsd)))
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    for box in (BOX, NARROW):
        for spec in _every_kind():
            s = prs.slides.add_slide(prs.slide_layouts[6])
            add_chart(s, box, spec, OUTLINE, STYLE, TYPO, text_hex=TEXT, muted_hex="6B7280")
    path = _save(prs, tmp_path, "xsd.pptx")
    bad = []
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            if name.startswith("ppt/charts/chart") and name.endswith(".xml"):
                doc = etree.fromstring(z.read(name))
                if not schema.validate(doc):
                    bad.append((name, schema.error_log[0].message[:160]))
    assert not bad, bad[:3]
