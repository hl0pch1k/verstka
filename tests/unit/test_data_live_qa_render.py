"""Живой прогон второй ступени (live QA), вёрстка: годы не выделяются акцентом, «чел. ,» не бывает, вывод слайда с
данными говорит первым предложением, а не уходит в заметки; рисунок на подложке-картинке (карандаш и ластик Blueprint)
находится по пикселям и не ложится под заголовок и диаграмму; подсказки плейсхолдеров макета не видны в LibreOffice;
рисунок образца о своём (карта США) не встаёт рядом с данными колоды."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import etree
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Emu

from verstka.rendering.compose import _first_sentence, highlight_runs, label_without_figure
from verstka.rendering.cutouts import cutout_boxes, sheet_box
from verstka.schemas.common import Bbox

ROOT = Path(__file__).resolve().parents[2]


# ── B3 / L6: typography of the composed words ──────────────────────────────────────────────────────────────────────
def test_a_year_is_not_set_in_the_accent():
    runs = highlight_runs("Сентябрь 2026 к сентябрю 2025: +23%, 423 млн ₽", 12, "000000", "FF0000")
    accent = [r.text.strip() for r in runs if r.color == "FF0000"]
    assert accent == ["+23%", "423 млн ₽"]


def test_a_figure_cut_out_of_brackets_leaves_no_space_before_the_comma():
    got = label_without_figure("Принято на 1 курс — 2 425 чел. (+6%), отчислено студентов — 412 чел. (−8%). Сравнение с 2025.", "+6%")
    assert "чел., отчислено" in got and " ," not in got


def test_the_first_sentence_of_a_conclusion():
    assert _first_sentence("Остальные 230 клиентов — 2 167 млн ₽, 62%. Крупнейший — АО «Северный капитал».") == "Остальные 230 клиентов — 2 167 млн ₽, 62%"
    assert _first_sentence("Выручка выросла на 23%") == ""
    assert _first_sentence("Рост 5 млн. Это хорошо.") == ""  # «млн.» ends no sentence


# ── L1: the objects a picture ground draws on its sheet ───────────────────────────────────────────────────────────
def _ground(shade: bool = False) -> bytes:
    """A blue grid ground with a white sheet; a yellow «pencil» and a pale «eraser» lying on its top right corner, or
    (`shade`) only a soft grey shade in its top left corner."""
    im = Image.new("RGB", (1600, 900), (47, 136, 167))
    d = ImageDraw.Draw(im)
    d.rectangle([60, 50, 1540, 860], fill=(255, 255, 255))
    if shade:
        for k in range(300):
            g = 255 - int(40 * (1 - k / 300))
            d.line([(60 + k, 50), (60, 50 + k)], fill=(g, g, g), width=2)
    else:
        d.polygon([(1150, 190), (1180, 160), (1500, 0), (1530, 30)], fill=(240, 200, 60), outline=(180, 140, 20))
        d.rounded_rectangle([1380, 120, 1520, 230], radius=20, fill=(250, 222, 210), outline=(225, 170, 150), width=4)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _slide_on(png: bytes):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    pic = slide.shapes.add_picture(io.BytesIO(png), 0, 0, prs.slide_width, prs.slide_height)
    tree = slide.shapes._spTree
    tree.remove(pic._element)
    tree.insert(2, pic._element)  # under everything: the ground
    return prs, slide


def test_the_pencil_and_the_eraser_are_found_and_a_shade_is_not():
    prs, slide = _slide_on(_ground())
    W, H = int(prs.slide_width), int(prs.slide_height)
    area = Bbox(x=int(0.05 * W), y=int(0.03 * H), w=int(0.9 * W), h=int(0.9 * H))
    cuts = cutout_boxes(slide, area, pad=0)
    assert cuts and all(c.x >= 0.65 * W and c.y2 <= 0.3 * H for c in cuts)
    assert any(c.x <= 0.75 * W for c in cuts) and any(c.x2 >= 0.93 * W for c in cuts)  # the pencil and the eraser
    sheet = sheet_box(slide, area)
    assert sheet is not None and abs(sheet.x - 0.0375 * W) < 0.01 * W and abs(sheet.y - 0.056 * H) < 0.015 * H
    prs2, slide2 = _slide_on(_ground(shade=True))
    assert cutout_boxes(slide2, area, pad=0) == []


def test_a_plain_slide_has_no_cutouts():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    assert cutout_boxes(slide) == [] and sheet_box(slide) is None


# ── L5: the layouts' prompts are not drawn ────────────────────────────────────────────────────────────────────────
def test_the_layout_prompts_are_emptied_but_not_the_fields():
    from verstka.rendering.renderer import _quiet_layout_prompts

    prs = Presentation()
    layout = prs.slide_layouts[1]
    for ph in layout.placeholders:
        if ph.has_text_frame and not ph.text_frame.text:
            ph.text_frame.text = "Альтернативные решения"
    prs.slides.add_slide(layout)
    fields = {ph.placeholder_format.idx: ph.text_frame.text for ph in layout.placeholders
              if (ph._element.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}ph").get("type") or "body") in ("dt", "ftr", "sldNum")}
    n = _quiet_layout_prompts(SimpleNamespace(prs=prs))
    assert n >= 2
    for ph in layout.placeholders:
        kind = ph._element.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}ph").get("type") or "body"
        if kind in ("dt", "ftr", "sldNum"):
            assert ph.text_frame.text == fields[ph.placeholder_format.idx]
        else:
            assert ph.text_frame.text.strip() == ""


# ── B4: a sample's drawing of its own subject ─────────────────────────────────────────────────────────────────────
def test_a_drawing_of_many_outlines_is_a_subject_and_a_few_shapes_are_decor():
    from verstka.rendering.clone import _subject_drawing

    def ctx_with(n_parts: int):
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        shapes = []
        for k in range(n_parts):
            fb = slide.shapes.build_freeform(Emu(900000 + (k % 8) * 500000), Emu(1200000 + (k // 8) * 500000))
            fb.add_line_segments([(Emu(1300000 + (k % 8) * 500000), Emu(1300000 + (k // 8) * 500000)), (Emu(1000000 + (k % 8) * 500000), Emu(1600000 + (k // 8) * 500000))])
            shapes.append(fb.convert_to_shape())
        slide.shapes.add_group_shape(shapes)
        W, H = int(prs.slide_width), int(prs.slide_height)
        return SimpleNamespace(slide=slide, W=W, H=H, pattern=SimpleNamespace(chrome_shape_ids=set()), id_of=lambda el: None)

    assert _subject_drawing(ctx_with(40)) is not None
    assert _subject_drawing(ctx_with(5)) is None


# ── ordinary decks (live QA, fidelity report): key figures large, no near-empty cards ────────────────────────────────
def _fake_ctx(slide, W, H, **kw):
    from verstka.schemas.common import PatternKind

    base = dict(slide=slide, W=W, H=H, kind=PatternKind.cards, typo=SimpleNamespace(primary_family=None, size_for=lambda role, default=0.0: {"h1": 24.0}.get(role, default)),
                els={str(k): sh._element for k, sh in enumerate(slide.shapes)})
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_key_figure_never_lands_in_a_small_card_heading():
    from verstka.rendering.clone import _kpi_room
    from verstka.schemas.common import SlotRole
    from verstka.schemas.outline import NumberCallout, SlideContent, SlideItem

    def ctx_with(size: float):
        slot = SimpleNamespace(role=SlotRole.card_title, group_id="g", style=SimpleNamespace(size_pt=size), shape_id="t1")
        return SimpleNamespace(oslide_content=SlideContent(numbers=[NumberCallout(value="18%", label="Сотрудников")]), slots=lambda *roles: [],
                               slot_of={"t1": slot}, typo=SimpleNamespace(size_for=lambda role, default=0.0: 24.0))

    group = SimpleNamespace(id="g", member_shape_ids=[["t1"]])
    items = [SlideItem(title="18%", text="Сотрудников", number="18%")]
    with pytest.raises(RuntimeError, match="крупной цифры"):
        _kpi_room(ctx_with(13.2), group, items, numbers_in_cells=False)
    _kpi_room(ctx_with(28.0), group, items, numbers_in_cells=False)  # a heading slot at the figure's size takes it
    _kpi_room(ctx_with(13.2), group, items, numbers_in_cells=True)  # the cards' own figure slots take it


def test_tall_cards_two_thirds_empty_are_no_place_for_the_content():
    from verstka.rendering.clone import _cards_not_empty

    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    W, H = int(prs.slide_width), int(prs.slide_height)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    cells = []
    for k, text in enumerate(["Практика", "Наставники"]):
        card = slide.shapes.add_shape(1, Emu(int((0.05 + 0.47 * k) * W)), Emu(int(0.4 * H)), Emu(int(0.43 * W)), Emu(int(0.5 * H)))
        tb = slide.shapes.add_textbox(Emu(int((0.07 + 0.47 * k) * W)), Emu(int(0.43 * H)), Emu(int(0.39 * W)), Emu(int(0.45 * H)))
        tb.text_frame.text = text
        cells.append([tb._element])
    with pytest.raises(RuntimeError, match="почти пустыми"):
        _cards_not_empty(_fake_ctx(slide, W, H), cells)
    for c in cells:  # a card filled with its text
        tb = next(sh for sh in slide.shapes if sh._element is c[0])
        tb.text_frame.text = "\n".join(["Каждый модуль заканчивается проектом на реальных данных"] * 7)
    _cards_not_empty(_fake_ctx(slide, W, H), cells)


# ── qa3: the hero figure, the no-break spaces, the brand logo's one corner ───────────────────────────────────────
def test_the_hero_figure_is_the_headings():
    from verstka.rendering.compose import _aside_figure

    take = "Медиана — 54 минуты. 3 обращения — больше 10 часов: на графике они в столбце «больше 180» (там всего 51)."
    assert _aside_figure(take, "80% обращений получают ответ за 2 часа") is None  # never «180» or «51»
    assert _aside_figure("Остальные 230 клиентов — 2 167 млн ₽, 62%", "Топ-10 клиентов дают 38% выручки") is None
    assert _aside_figure("Сентябрь 2026 к сентябрю 2025: 423 млн ₽ против 344 млн ₽", "Выручка в сентябре 2026 достигла 423 млн ₽") == "423 млн ₽"
    assert _aside_figure("Сентябрь 2026 к сентябрю 2025: 423 млн ₽ против 344 млн ₽") is not None  # the author's slides as before


def test_collapsing_spaces_keeps_the_no_break_ones():
    from verstka.rendering.compose import squash

    assert squash("  Сравнение с III кв. 2025 \n и  дальше ") == "Сравнение с III кв. 2025 и дальше"


def _logo_pic(slide, x: float, y: float, w: float, h: float, png: bytes):
    from verstka.brand.package import BRAND_LOGO_MARK

    pic = slide.shapes.add_picture(io.BytesIO(png), Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    pic._element.find(".//{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr").set("title", BRAND_LOGO_MARK)
    return pic


def test_the_brand_logo_comes_back_in_the_decks_one_corner():
    from verstka.rendering.brand_logo import held_logo_box, hold_brand_logos, put_back_brand_logos

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (0, 119, 255)).save(buf, "PNG")
    png = buf.getvalue()
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    W, H = 12192000, 6858000
    for _ in range(3):  # the samples: the logo bottom right
        _logo_pic(prs.slides.add_slide(prs.slide_layouts[6]), 0.88 * W, 0.9 * H, 0.08 * W, 0.04 * H, png)
    odd = prs.slides.add_slide(prs.slide_layouts[6])
    _logo_pic(odd, 0.03 * W, 0.9 * H, 0.08 * W, 0.04 * H, png)  # one sample had it bottom left
    assert hold_brand_logos(odd) == 1
    box = held_logo_box(odd)
    assert box is not None and box[0] > 0.8 * W and box[1] > 0.85 * H  # the deck's corner, known while the slide is laid out
    put_back_brand_logos(odd, [])
    pic = next(sh for sh in odd.shapes if sh.shape_type == 13)
    assert pic.left > 0.8 * W and pic.top > 0.85 * H


def test_the_audit_sees_a_logo_missing_or_in_another_corner(tmp_path):
    from verstka.audit.ir import build_deck_ir
    from verstka.audit.registry import AuditContext, run_checks

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (0, 119, 255)).save(buf, "PNG")
    png = buf.getvalue()
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    W, H = 12192000, 6858000
    for k in range(6):  # (the first and the last slide — cover and closing — are not counted)
        sl = prs.slides.add_slide(prs.slide_layouts[6])
        sl.shapes.add_textbox(Emu(600000), Emu(600000), Emu(6000000), Emu(800000)).text_frame.text = f"Слайд {k + 1}"
        if k in (0, 1, 2, 5):
            _logo_pic(sl, 0.88 * W, 0.9 * H, 0.08 * W, 0.04 * H, png)
        elif k == 3:
            _logo_pic(sl, 0.03 * W, 0.9 * H, 0.08 * W, 0.04 * H, png)
    path = tmp_path / "deck.pptx"
    prs.save(path)
    ir = build_deck_ir(path)
    got, _ = run_checks(AuditContext(ir=ir, manifest=None, outline=None), only={"brand_logo_place"})
    by = {i.slide: i.message for i in got}
    assert set(by) == {4, 5} and "снизу слева" in by[4] and "нет логотипа" in by[5]
