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
from verstka.export.html import _number_columns, _rgba, export_html
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
