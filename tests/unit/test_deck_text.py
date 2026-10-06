"""«Улучшить готовую презентацию» (verstka/ingest/deck_text.py): a finished deck read back as the author's «Слайд N»
text — its titles, lists, tables, charts with their data, pictures kept for the improved deck, a KPI tile read as one
line; what every slide repeats (a footer, a logo, the page number) left out."""

from __future__ import annotations

import io
import json

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Emu, Pt

from verstka.ingest.deck_text import SOURCE_IMAGES, deck_text, keep_pictures, source_records
from verstka.planning.brief_structure import read_structure

W, H = 12192000, 6858000


def _png(color=(30, 120, 200), size=(320, 200), flat: bool = False) -> io.BytesIO:
    """A picture: a gradient (a photo has detail); `flat` — one colour, as a template draws a card's ground."""
    im = Image.new("RGB", size, color)
    if not flat:
        for x in range(size[0]):
            for y in range(0, size[1], 4):
                im.putpixel((x, y), ((color[0] + x) % 256, (color[1] + y) % 256, color[2]))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return buf


def _box(slide, x, y, w, h, text, size=18, font=None):
    tb = slide.shapes.add_textbox(Emu(int(W * x)), Emu(int(H * y)), Emu(int(W * w)), Emu(int(H * h)))
    tf = tb.text_frame
    lines = text if isinstance(text, list) else [text]
    tf.text = lines[0]
    for ln in lines[1:]:
        tf.add_paragraph().text = ln
    for p in tf.paragraphs:
        for r in p.runs:
            r.font.size = Pt(size)
            if font:
                r.font.name = font
    return tb


def _deck(tmp_path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    blank = prs.slide_layouts[6]
    logo = _png((200, 30, 30), (60, 60))

    def footer(s):
        _box(s, 0.05, 0.93, 0.3, 0.05, "ООО «Ромашка» · конфиденциально", 10)
        logo.seek(0)
        s.shapes.add_picture(logo, Emu(int(W * 0.9)), Emu(int(H * 0.9)), Emu(int(W * 0.05)), Emu(int(H * 0.08)))

    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "Итоги квартала"
    s1.placeholders[1].text = "Отдел продаж, октябрь 2026"
    footer(s1)

    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Что сделали"
    body = s2.placeholders[1].text_frame
    body.text = "Запустили онлайн-заказ"
    body.add_paragraph().text = "Открыли две новые точки"
    body.add_paragraph().text = "Обучили 40 сотрудников"
    footer(s2)

    s3 = prs.slides.add_slide(blank)
    _box(s3, 0.05, 0.05, 0.9, 0.12, "Выручка выросла на 34%", 32)
    rows = [["Месяц", "Выручка, млн ₽"], ["Июль", "1,2"], ["Август", "1,5"], ["Сентябрь", "1,9"]]
    tbl = s3.shapes.add_table(len(rows), 2, Emu(int(W * 0.05)), Emu(int(H * 0.25)), Emu(int(W * 0.5)), Emu(int(H * 0.4))).table
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            tbl.cell(i, j).text = v
    footer(s3)

    s4 = prs.slides.add_slide(blank)
    _box(s4, 0.05, 0.05, 0.9, 0.12, "Доли каналов продаж", 32)
    cd = CategoryChartData()
    cd.categories = ["Онлайн", "Офлайн", "Партнёры"]
    cd.add_series("Доля, %", (55, 35, 10))
    s4.shapes.add_chart(XL_CHART_TYPE.PIE, Emu(int(W * 0.1)), Emu(int(H * 0.2)), Emu(int(W * 0.6)), Emu(int(H * 0.6)), cd)
    footer(s4)

    s5 = prs.slides.add_slide(blank)
    _box(s5, 0.05, 0.05, 0.9, 0.12, "Новая точка на Тверской", 32)
    s5.shapes.add_picture(_png(), Emu(int(W * 0.5)), Emu(int(H * 0.2)), Emu(int(W * 0.45)), Emu(int(H * 0.6)))
    # a flat panel drawn as a picture (a card's ground of the template): decoration, never a picture place
    s4.shapes.add_picture(_png((235, 238, 244), flat=True), Emu(int(W * 0.72)), Emu(int(H * 0.2)), Emu(int(W * 0.25)), Emu(int(H * 0.5)))
    _box(s5, 0.05, 0.3, 0.4, 0.1, "300 ₽", 40)
    _box(s5, 0.05, 0.41, 0.4, 0.08, "Средний чек", 16)
    _box(s5, 0.05, 0.6, 0.4, 0.2, ['{', '  "zone": "bed_1",', '  "tank_level_pct": 72', '}'], 12, font="Courier New")
    footer(s5)
    path = tmp_path / "old.pptx"
    prs.save(str(path))
    return path


def test_a_deck_reads_back_as_the_authors_slides(tmp_path):
    d = deck_text(_deck(tmp_path))
    assert d.summary() == {"title": "Итоги квартала", "slides": 5, "tables": 1, "charts": 1, "pictures": 1}
    b = d.brief
    assert b.startswith("Слайд 1. Итоги квартала\n\nОтдел продаж, октябрь 2026")
    assert "Слайд 2. Что сделали\n\n- Запустили онлайн-заказ\n- Открыли две новые точки\n- Обучили 40 сотрудников" in b
    assert "| Месяц | Выручка, млн ₽ |\n|---|---|\n| Июль | 1,2 |" in b
    assert "[Круговая диаграмма: Доля, % — Онлайн: 55; Офлайн: 35; Партнёры: 10]" in b
    assert "[Место под изображение: Изображение со слайда 5 исходной презентации]" in b
    assert "Средний чек — 300 ₽" in b  # a KPI tile is one line: the figure keeps what it measures
    assert "```\n{\n  \"zone\": \"bed_1\"," in b  # code stays code
    # what every slide repeats is the template's: never the author's text, never a picture place
    assert "Ромашка" not in b and b.count("[Место под изображение") == 1


def test_the_read_back_text_is_a_dictated_deck_with_its_chart_and_picture(tmp_path):
    d = deck_text(_deck(tmp_path))
    st = read_structure(d.brief)
    assert [sp.number for sp in st.specs] == [1, 2, 3, 4, 5] and st.specs[1].title == "Что сделали"


def test_the_decks_pictures_go_back_to_their_places_of_the_improved_deck(tmp_path):
    d = deck_text(_deck(tmp_path))
    ws = tmp_path / "ws"
    index = keep_pictures(d, ws / "source_images")
    assert index == {"Изображение со слайда 5 исходной презентации": "picture-01.png"}
    assert json.loads((ws / SOURCE_IMAGES).read_text(encoding="utf-8")) == index
    pics = tmp_path / "gen" / "images"
    recs = source_records(ws, pics)
    assert len(recs) == 1 and recs[0]["status"] == "generated" and recs[0]["model"] == "original"
    assert recs[0]["hint"] == "Изображение со слайда 5 исходной презентации" and (pics / recs[0]["file"]).is_file()
    assert source_records(tmp_path / "nothing", pics) == []
