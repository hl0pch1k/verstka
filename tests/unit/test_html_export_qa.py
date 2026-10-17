"""HTML-экспорт по живой проверке второй ступени: цифры карточек не обрезаются сверху (X1), колонки таблицы выровнены по
содержимому (X2), у кольцевой диаграммы с легендой слайда нет второй легенды, плашки легенды — оттенки среза, «%» не
переносится (X3)."""

from __future__ import annotations

import re

import pytest
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

from verstka.analysis.manifest import analyze_template
from verstka.export.html import _crop_css, _layout_pic_crop, _number_columns, _rgba, export_html
from verstka.export.svg_charts import chart_svg
from verstka.rendering.charts import TREND_SERIES
from verstka.schemas.deck_ir import IRChart, IRChartSeries
from verstka.rendering.charts import add_chart
from verstka.schemas.common import Bbox
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries
from verstka.schemas.template import ChartStyleSpec, TypeStep, Typography

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
W, H = 12192000, 6858000


@pytest.fixture
def manifest(simple_deck, tmp_path):
    return analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)


def _deck():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    return prs, prs.slides.add_slide(prs.slide_layouts[6])


def _html(prs, manifest, tmp_path) -> str:
    prs.save(str(tmp_path / "d.pptx"))
    return export_html(tmp_path / "d.pptx", manifest, tmp_path / "d.html").read_text(encoding="utf-8")


def _box(slide, x, y, w, h, text, size, insets=None, anchor=None, wrap=True):
    tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    if insets is not None:
        tf.margin_left, tf.margin_top, tf.margin_right, tf.margin_bottom = (Emu(v) for v in insets)
    if anchor is not None:
        tf.vertical_anchor = anchor
    r = tf.paragraphs[0].add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.color.rgb = RGBColor(0, 0, 0)
    return tb


def test_text_keeps_the_boxes_own_insets_and_is_never_clipped(manifest, tmp_path):
    from pptx.enum.text import MSO_ANCHOR

    prs, s = _deck()
    # a card's figure: a box as tall as its line, no insets, text at the bottom — the box clips nothing of it
    _box(s, 500000, 500000, 2400000, 200000, "2 425 чел.", 13.2, insets=(0, 0, 0, 0), anchor=MSO_ANCHOR.BOTTOM)
    _box(s, 500000, 1500000, 2400000, 400000, "С отступами", 12)  # python-pptx default 0.1" × 0.05"
    _box(s, 500000, 2500000, 480000, 250000, "46%", 15, insets=(0, 0, 0, 0), wrap=False)
    page = _html(prs, manifest, tmp_path)
    assert ".el.txt{overflow:visible}" in page
    figure = re.search(r'<div class="el txt"[^>]*><div class="tx" style="([^"]*)">(?:(?!</div>).)*2[\s\S]{0,40}425', page)
    assert figure and "padding-top:0.000cqw" in figure.group(1) and "padding-left:0.000cqw" in figure.group(1)
    assert "justify-content:flex-end" in figure.group(1)
    padded = re.search(r'<div class="tx" style="([^"]*)">(?:(?!</div>).)*С отступами', page)
    assert padded and "padding-left:0.750cqw" in padded.group(1) and "padding-top:0.375cqw" in padded.group(1)  # 91440 / 12192000, 45720 / 12192000 of the width
    nowrap = re.search(r'<div class="tx" style="([^"]*)">(?:(?!</div>).)*46%', page)
    assert nowrap and "white-space:nowrap" in nowrap.group(1)


def test_translucent_swatches_keep_their_tint(manifest, tmp_path):
    prs, s = _deck()
    for i, alpha in enumerate((100000, 76000, 26000)):
        sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(500000 + i * 400000), Emu(500000), Emu(140000), Emu(140000))
        sh.fill.solid()
        sh.fill.fore_color.rgb = RGBColor(0, 0x77, 0xFF)
        clr = sh._element.spPr.find(f"{A}solidFill/{A}srgbClr")
        if alpha < 100000:
            etree.SubElement(clr, f"{A}alpha").set("val", str(alpha))
    page = _html(prs, manifest, tmp_path)
    assert "background:#0077FF" in page and "background:rgba(0,119,255,0.760)" in page and "background:rgba(0,119,255,0.260)" in page
    assert _rgba("0077FF", 1.0) == "#0077FF" and _rgba("0077FF", 0.5) == "rgba(0,119,255,0.500)"


def test_table_columns_align_by_their_content(manifest, tmp_path):
    rows = [["Клиент", "Отрасль", "Выручка, млн ₽", "Доля, %", "Рост"], ["АО «Север»", "Банки", "212,4", "6,1", "+38%"], ["ПАО «Магистраль»", "Телеком", "1 433", "5,1", "—"], ["Итого", "", "3 495", "100", "+23%"]]
    assert _number_columns(rows) == [False, False, True, True, True]
    assert _number_columns([["a", "b"], ["423 млн ₽", "Москва"], ["344 млн ₽", "Казань"]]) == [True, False]
    assert _number_columns([["a"], ["Q3 2026"], ["2025"]]) == [False]  # (a period is a word of the row, not a figure)
    assert _number_columns([["a", "b"]]) == [False, False]
    prs, s = _deck()
    gt = s.shapes.add_table(len(rows), 5, Emu(500000), Emu(500000), Emu(9000000), Emu(2000000))
    for i, r in enumerate(rows):
        for j, c in enumerate(r):
            gt.table.cell(i, j).text = c
    page = _html(prs, manifest, tmp_path)
    head = re.findall(r"<th( class=n)? ", page)
    assert head == ["", "", " class=n", " class=n", " class=n"]  # words left under left headers, figures right under right headers
    first_row = re.search(r"<tbody><tr>(.*?)</tr>", page).group(1)
    assert re.findall(r"<td( class=n)?>", first_row) == ["", "", " class=n", " class=n", " class=n"]
    assert "td:not(:first-child)" not in page


def test_a_doughnut_with_the_slides_own_legend_has_no_second_one(manifest, tmp_path):
    style = ChartStyleSpec(series_colors=["0077FF"], font_family="Play", font_size_pt=7.0)
    typo = Typography(scale=[TypeStep(role="body", size_pt=9), TypeStep(role="small", size_pt=7)])
    spec = ChartSpec(type="doughnut", categories=["Прямые продажи", "Партнёры", "Маркетплейс", "Онлайн"], series=[InlineSeries(name="Доля", values=[46, 28, 17, 9])], unit="%")
    box = Bbox(x=500000, y=500000, w=3600000, h=3000000)
    pages = {}
    for legend in (False, True):
        prs, s = _deck()
        add_chart(s, box, spec, DeckOutline(title="t"), style, typo, text_hex="000000", legend=legend)
        pages[legend] = _html(prs, manifest, tmp_path)
    assert "Партнёры" not in pages[False]  # the circle takes the frame; the slide's own legend names the slices
    assert pages[True].count("Партнёры") == 1 and pages[False].count("<path") == pages[True].count("<path") == 4


def test_a_cards_drop_shadow_is_drawn_so_white_cards_on_a_pale_ground_stay_apart(manifest, tmp_path):
    prs, s = _deck()
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(500000), Emu(500000), Emu(2000000), Emu(1500000))
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor(255, 255, 255)
    eff = etree.SubElement(sh._element.spPr, f"{A}effectLst")
    shd = etree.SubElement(eff, f"{A}outerShdw", blurRad="154305", dist="20574", dir="5400000", algn="t", rotWithShape="0")
    clr = etree.SubElement(shd, f"{A}srgbClr", val="0B1F44")
    etree.SubElement(clr, f"{A}alpha").set("val", "9000")
    page = _html(prs, manifest, tmp_path)
    m = re.search(r"box-shadow:(-?[\d.]+)cqw (-?[\d.]+)cqw ([\d.]+)cqw rgba\(11,31,68,0\.090\)", page)
    assert m and abs(float(m.group(1))) < 0.001 and float(m.group(2)) == pytest.approx(20574 / W * 100, abs=0.002) and float(m.group(3)) == pytest.approx(154305 / W * 100, abs=0.002)
    # a shape without a shadow has none
    prs, s = _deck()
    s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(500000), Emu(500000), Emu(2000000), Emu(1500000))
    assert "box-shadow" not in _html(prs, manifest, tmp_path).split("</style>")[1]


def test_a_cropped_picture_is_drawn_cropped_not_fitted_whole():
    # srcRect r = 47.4 %, b = 3.3 % (the cover's cube): the image is drawn 190 % wide from the left edge, the frame shows its left part
    css = _crop_css((0.0, 0.0, 0.47427, 0.03311))
    assert "background-size:190.2" in css and "103.4" in css and "background-position:0.000% 0.000%" in css
    # a crop from the left and the top shifts the image the other way
    assert "background-position:100.000% 100.000%" in _crop_css((0.3, 0.2, 0.0, 0.0))
    assert _crop_css(None) == "" and _crop_css((0.0, 0.0, 0.0, 0.0)) == "" and _crop_css((-0.1, 0.0, 0.0, 0.0)) == ""

    class _Pkg:  # a layout with two pictures: the cover's image cropped, another not
        def xml(self, part):
            ns = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
            return etree.fromstring(
                f"<p:sld {ns}><p:cSld><p:spTree>"
                '<p:pic><p:blipFill><a:blip r:embed="rId2"/><a:srcRect r="47427" b="3311"/></p:blipFill></p:pic>'
                '<p:pic><p:blipFill><a:blip r:embed="rId3"/><a:srcRect b="0" l="0" r="0" t="0"/></p:blipFill></p:pic>'
                "</p:spTree></p:cSld></p:sld>"
            )

        def target_of(self, part, rid):
            return {"rId2": "ppt/media/cube.png", "rId3": "ppt/media/logo.png"}.get(rid)

    pkg = _Pkg()
    assert _layout_pic_crop(pkg, "ppt/slideLayouts/slideLayout1.xml", "ppt/media/cube.png") == pytest.approx((0.0, 0.0, 0.47427, 0.03311))
    assert _layout_pic_crop(pkg, "ppt/slideLayouts/slideLayout1.xml", "ppt/media/logo.png") is None
    assert _layout_pic_crop(pkg, "ppt/slideLayouts/slideLayout1.xml", "ppt/media/other.png") is None


def test_a_slide_picture_with_a_crop_keeps_it_in_the_html(manifest, tmp_path):
    from PIL import Image

    img = tmp_path / "p.png"
    Image.new("RGB", (400, 200), (0, 90, 220)).save(img)
    prs, s = _deck()
    pic = s.shapes.add_picture(str(img), Emu(500000), Emu(500000), Emu(2400000), Emu(1200000))
    pic.crop_right, pic.crop_bottom = 0.4, 0.1
    page = _html(prs, manifest, tmp_path)
    assert re.search(r'class="el pic im\d+" style="[^"]*background-size:166\.667% 111\.111%;background-position:0\.000% 0\.000%', page)


def _scatter_ir(points_per_series, helper: bool):
    series = []
    if helper:
        xs = [x for xs_, _ in points_per_series for x in xs_]
        ys = [y for _, ys_ in points_per_series for y in ys_]
        series.append(IRChartSeries(name=TREND_SERIES, values=ys, x_values=xs))
    for i, (xs, ys) in enumerate(points_per_series):
        series.append(IRChartSeries(name=f"Группа {i + 1}", values=ys, x_values=xs, color=("0077FF", "FF3985")[i % 2]))
    return IRChart(type="scatter", categories=[str(x) for x in points_per_series[0][0]], series=series, has_legend=len(points_per_series) > 1, has_value_axis=True)


def test_the_html_scatter_draws_the_trend_line_and_no_trend_series():
    pts = [([1, 2, 3, 4, 5, 6, 7], [10, 12, 15, 15, 19, 22, 24]), ([2, 3, 5, 6, 8], [12, 13, 17, 21, 25])]
    svg = chart_svg(_scatter_ir(pts, helper=True), 600, 300, ["0077FF"], text_hex="000000", font="Play", font_px=10.0)
    assert svg.count('stroke-dasharray="5 3"') == 1 and TREND_SERIES not in svg and "Группа 1" in svg and "Группа 2" in svg  # (the legend names the groups only)
    assert svg.count("<circle") == 12  # (no points of the trend series)
    # one series: the line only when the chart part says it has one
    one = _scatter_ir(pts[:1], helper=False)
    assert 'stroke-dasharray="5 3"' not in chart_svg(one, 600, 300, ["0077FF"], text_hex="000000", font_px=10.0)
    assert chart_svg(one, 600, 300, ["0077FF"], text_hex="000000", font_px=10.0, trend=True).count('stroke-dasharray="5 3"') == 1
    # a wide frame: the plot narrows to the near-square shape, as in the PPTX
    wide = chart_svg(one, 900, 220, ["0077FF"], text_hex="000000", font_px=10.0)
    xs_ = [float(v) for v in re.findall(r'<circle cx="([\d.]+)"', wide)]
    assert max(xs_) - min(xs_) < 220 * 1.7


def test_the_legend_begins_after_the_title_of_its_group():
    cats = ["I", "II", "III"]
    ir = IRChart(type="column", categories=cats, series=[IRChartSeries(name="Бюджет", values=[3, 4, 5], color="0077FF"), IRChartSeries(name="Платное", values=[4, 5, 6], color="FF3985")], has_legend=True)

    def legend_x(svg: str) -> float:
        return min(float(m) for m in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="7\.0" height="7\.0"', svg))

    plain = chart_svg(ir, 600, 300, ["0077FF"], text_hex="000000", font_px=10.0)
    titled = chart_svg(ir, 600, 300, ["0077FF"], text_hex="000000", font_px=10.0, legend_left=110.0)
    assert legend_x(titled) == pytest.approx(110.0, abs=0.1) and legend_x(plain) > 110.0  # (behind a title the entries start where it ends)


def test_the_legend_title_box_gives_the_html_legend_its_left_edge(manifest, tmp_path):
    style = ChartStyleSpec(series_colors=["0077FF", "FF3985"], font_family="Play", font_size_pt=7.0)
    typo = Typography(scale=[TypeStep(role="body", size_pt=9), TypeStep(role="small", size_pt=7)])
    spec = ChartSpec(type="stacked_column", categories=["I кв.", "II кв.", "III кв."], series=[InlineSeries(name="Бюджет", values=[3, 4, 5]), InlineSeries(name="Платное", values=[4, 5, 6])], unit="чел.", y_title="Принято, чел.")
    prs, s = _deck()
    gf = add_chart(s, Bbox(x=500000, y=500000, w=7000000, h=3600000), spec, DeckOutline(title="t"), style, typo, text_hex="000000", legend_title="Форма обучения")
    assert gf.verstka_legend_title is not None
    page = _html(prs, manifest, tmp_path)
    assert "Форма обучения" in page
    svg = re.search(r"<svg[^>]*>.*?</svg>", page, re.S).group(0)
    legend_x = min(float(m) for m in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="[\d.]+" height="[\d.]+" fill="#[0-9A-F]{6}" stroke', svg))
    title_end = (gf.verstka_legend_title.left + gf.verstka_legend_title.width - gf.left) / 12700
    assert legend_x >= title_end - 0.5  # the first swatch begins after the title's box ends
