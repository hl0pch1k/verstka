"""Template slides used as they are designed: what the analysis reads on a sample (pictures, accent cells, note fields,
icon frames), how the matcher keeps a sample's story off new content, and the gate that keeps a cloned slide from
leaving a hole where the sample had its content."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

from verstka.analysis.groups import detect_repeat_groups
from verstka.analysis.pictures import _Stats, _glyphs, classify_blob
from verstka.analysis.patterns import note_field
from verstka.analysis.roles import is_empty_frame
from verstka.analysis.shapes import ParagraphInfo, RunInfo, ShapeInfo, TextInfo
from verstka.rendering.clone_check import _GRID_C, _GRID_R, largest_hole
from verstka.rendering.groups import staggered_axis
from verstka.ru import NBSP, no_orphan, typeset
from verstka.schemas.common import Bbox, BboxFrac, Family, PatternKind, ShapeKind, SlotRole
from verstka.schemas.template import Capacity, Pattern, Slot, SlotStyle

W, H = 12192000, 6858000


def _box(x, y, w, h) -> Bbox:
    return Bbox(x=int(x * W), y=int(y * H), w=int(w * W), h=int(h * H))


def _text(sid, text, size, x, y, w, h, **kw) -> ShapeInfo:
    ti = TextInfo(paragraphs=[ParagraphInfo(text=text, runs=[RunInfo(text=text, font="Play", size_pt=size, bold=False, color_hex="000000")])])
    return ShapeInfo(id=sid, name=sid, kind=ShapeKind.sp, bbox=_box(x, y, w, h), z=kw.pop("z", 5), text=ti, **kw)


def _shape(sid, x, y, w, h, fill="EBF3F9", geometry="ellipse", line=None, z=1, **kw) -> ShapeInfo:
    return ShapeInfo(id=sid, name=sid, kind=ShapeKind.sp, bbox=_box(x, y, w, h), z=z, geometry=geometry, fill_hex=fill, line_hex=line, **kw)


# ---------------------------------------------------------------------------- pictures


def _png(draw) -> np.ndarray:
    im = Image.new("RGBA", (600, 300), (0, 0, 0, 0))
    draw(ImageDraw.Draw(im))
    return np.asarray(im).astype(np.int32)


def test_a_chart_drawn_as_a_picture_shows_its_labels_a_render_does_not():
    def chart(d):
        for i, y in enumerate(range(40, 260, 44)):
            d.line([(60, y), (580, y)], fill=(200, 220, 200, 255), width=1)
            d.text((10, y - 6), str(40 - 10 * i), fill=(200, 220, 200, 255))
        for i in range(5):
            d.text((90 + i * 100, 270), f"Item {i + 1}", fill=(200, 220, 200, 255))
        d.line([(80, 200), (200, 120), (320, 160), (440, 60), (560, 70)], fill=(190, 230, 120, 255), width=3)

    def render(d):
        d.ellipse([150, 30, 450, 280], fill=(40, 120, 255, 255))
        d.ellipse([250, 90, 350, 190], fill=(200, 230, 255, 255))

    assert _glyphs(_png(chart)) >= 12
    assert _glyphs(_png(render)) <= 2


def test_glyphs_make_a_picture_the_samples_content_and_ground_needs_the_whole_slide():
    st = _Stats(coverage=0.02, colours=40, texture=0.0, sharp=0.0, hue_sd=0.0, white=0.0, glyphs=20)
    assert classify_blob(st, 0.9, 0.6) == "content"  # a transparent line chart with its axis labels
    faint = _Stats(coverage=0.02, colours=40, texture=0.0, sharp=0.0, hue_sd=0.0, white=0.0, glyphs=0)
    assert classify_blob(faint, 0.9, 0.6) == "art"  # a glow, a hairline ornament
    # a picture as large as the slide, but running off its foot, is not the slide's background
    assert classify_blob(faint, 1.0, 0.79, covers=False) == "art"
    assert classify_blob(faint, 1.0, 1.0, covers=True) == "ground"


def test_muted_photographs_are_photographs():
    toned = _Stats(coverage=1.0, colours=900, texture=0.35, sharp=0.08, hue_sd=12.0, white=0.0, lum_sd=60.0)
    assert classify_blob(toned, 0.4, 0.4) == "photo"
    portrait = _Stats(coverage=1.0, colours=460, texture=0.1, sharp=0.03, hue_sd=18.0, white=0.0, lum_sd=86.0)
    assert classify_blob(portrait, 0.44, 0.8) == "photo"
    dark_lines = _Stats(coverage=1.0, colours=444, texture=0.13, sharp=0.03, hue_sd=7.0, white=0.0, lum_sd=44.0)
    assert classify_blob(dark_lines, 1.0, 0.5) == "art"


# ---------------------------------------------------------------------------- groups, roles, note fields


def test_the_accent_step_of_a_timeline_joins_its_row():
    shapes = [_text("t", "Нумерация", 36, 0.05, 0.1, 0.9, 0.09)]
    for i, x in enumerate((0.055, 0.288, 0.521, 0.754)):
        fill = "0077FF" if i == 1 else "EBF3F9"
        shapes.append(_shape(f"c{i}", x, 0.46, 0.071, 0.127, fill=fill))
        shapes.append(_text(f"l{i}", "Здесь можно добавить пояснение", 16, x, 0.62, 0.209, 0.087))
    groups = detect_repeat_groups(shapes, W, H)
    assert len(groups) == 1 and len(groups[0].member_shape_ids) == 4
    assert any("c1" in cell for cell in groups[0].member_shape_ids)


def test_the_page_number_under_the_last_card_does_not_cost_the_card_its_column():
    shapes = [_text("t", "Заголовок", 20, 0.04, 0.06, 0.8, 0.05)]
    for i in range(5):
        y = 0.2 + i * 0.147
        shapes.append(_shape(f"f{i}", 0.488, y, 0.484, 0.115, fill="FFFFFF", geometry="roundRect", line="520977"))
        shapes.append(_text(f"b{i}", "Текст", 14, 0.506, y + 0.012, 0.448, 0.088))
    shapes.append(_text("num", "20", 12, 0.954, 0.927, 0.046, 0.053, is_placeholder=True, ph_type="sldNum"))
    groups = detect_repeat_groups(shapes, W, H)
    assert len(groups) == 1 and len(groups[0].member_shape_ids) == 5


def test_an_outline_round_an_icon_is_its_frame_not_a_text_container():
    frame = _shape("fr", 0.766, 0.204, 0.123, 0.204, fill=None, geometry="roundRect", line="FD0C50", z=9)
    icon = _shape("ic", 0.80, 0.255, 0.061, 0.101, fill="FD0C50", geometry="custom", z=3)
    assert not is_empty_frame(frame, [frame, icon], W, H)
    card = _shape("card", 0.05, 0.45, 0.27, 0.35, fill=None, geometry="roundRect", line="FD0C50", z=9)
    corner = _shape("dot", 0.06, 0.46, 0.02, 0.03, fill="FD0C50", z=3)  # a mark in the card's corner
    assert is_empty_frame(card, [card, corner], W, H)


def _slot(sid, role, x, y, w, h, text="", size=14.0, group=None) -> Slot:
    return Slot(id=sid, role=role, shape_id=sid, bbox=BboxFrac(x=x, y=y, w=w, h=h), capacity=Capacity(max_chars=100, max_lines=3), sample_text=text, style=SlotStyle(size_pt=size), group_id=group)


def test_the_note_band_at_the_foot_is_found_by_its_label():
    slots = [
        _slot("t", SlotRole.title, 0.035, 0.06, 0.64, 0.17, "Заголовок", 36),
        _slot("c1", SlotRole.card_title, 0.035, 0.27, 0.3, 0.3, "Заголовок", 18, "g1"),
        _slot("c2", SlotRole.card_title, 0.346, 0.27, 0.3, 0.3, "Заголовок", 18, "g1"),
        _slot("lab", SlotRole.body, 0.035, 0.719, 0.146, 0.058, "Примечание", 14),
        _slot("txt", SlotRole.body, 0.035, 0.807, 0.539, 0.058, "Текст", 14),
    ]
    p = Pattern(id="p15", source_slide=15, kind=PatternKind.cards, family=Family.dark, slots=slots)
    assert note_field(p, 14.0) == ("txt", "lab")
    # a speaker's name and position low on a slide is no note field
    slots2 = slots[:3] + [_slot("n", SlotRole.body, 0.15, 0.75, 0.47, 0.05, "Имя Фамилия", 16), _slot("pos", SlotRole.body, 0.15, 0.81, 0.47, 0.05, "Должность", 14)]
    assert note_field(Pattern(id="p10", source_slide=10, kind=PatternKind.cards, family=Family.dark, slots=slots2), 14.0) == (None, None)


# ---------------------------------------------------------------------------- rendering helpers


def test_a_zigzag_of_cards_is_read_along_its_line():
    top = [_box(x, 0.21, 0.207, 0.215) for x in (0.028, 0.396, 0.765)]
    bottom = [_box(x, 0.70, 0.207, 0.215) for x in (0.213, 0.581)]
    assert staggered_axis(top + bottom) == "row"
    grid = [_box(x, y, 0.4, 0.3) for y in (0.2, 0.55) for x in (0.05, 0.5)]
    assert staggered_axis(grid) is None
    assert staggered_axis([_box(0.05 + 0.3 * i, 0.3, 0.25, 0.3) for i in range(3)]) is None  # a plain row


def test_the_largest_hole_is_measured_in_the_content_area():
    grid = np.zeros((_GRID_R, _GRID_C), dtype=bool)
    area = (2, 5, _GRID_C - 2, _GRID_R - 2)
    full = largest_hole(grid, area)
    assert abs(full - (_GRID_C - 4) * (_GRID_R - 7) / (_GRID_C * _GRID_R)) < 1e-9
    grid[5:14, :] = True  # the upper part filled: the lower band stays free
    lower = largest_hole(grid, area)
    assert abs(lower - (_GRID_C - 4) * (_GRID_R - 2 - 14) / (_GRID_C * _GRID_R)) < 1e-9


def test_headings_keep_brands_compounds_and_their_last_two_words_together():
    assert f"VK{NBSP}Tech" in typeset("Пилот на шаблонах VK Tech")
    assert "Qwen3.8-⁠27B" in typeset("модель Qwen3.8-27B")
    t = no_orphan("Десятки презентаций в неделю требуют ручной вёрстки")
    assert t.endswith(f"ручной{NBSP}вёрстки")
    assert no_orphan("Два слова") == "Два слова"


# ---------------------------------------------------------------------------- the matcher keeps a sample's story off new content


def _cards_pattern(pid="pc", kind=PatternKind.bullets, **kw) -> Pattern:
    slots = [Slot(id="t", role=SlotRole.title, shape_id="t", bbox=BboxFrac(x=0.05, y=0.06, w=0.9, h=0.1), capacity=Capacity(max_chars=60, max_lines=2))]
    slots += [Slot(id=f"b{i}", role=SlotRole.body, shape_id=f"b{i}", bbox=BboxFrac(x=0.05, y=0.2, w=0.4, h=0.6), capacity=Capacity(max_chars=400, max_lines=10)) for i in range(1)]
    return Pattern(id=pid, source_slide=3, kind=kind, family=Family.light, slots=slots, **kw)


def test_a_samples_own_chart_keeps_it_off_text_but_not_off_a_chart(simple_deck, tmp_path):
    from verstka.analysis.manifest import analyze_template
    from verstka.analysis.pictures import SamplePicture
    from verstka.matching.scorer import score_pattern
    from verstka.planning.strategies import get_strategy
    from verstka.schemas.outline import ChartSpec, OutlineSlide, SlideContent

    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    p = _cards_pattern(kind=PatternKind.image_text)
    pics = [SamplePicture(shape_id="g", x=0.5, y=0.2, w=0.45, h=0.6, kind="content")]
    text = OutlineSlide(id="s", kind=PatternKind.bullets, headline="Три шага после финала", content=SlideContent(bullets=["Инференс VK", "Картинки внутри слайдов", "Пилот на шаблонах"]))
    res = score_pattern(text, p, manifest, get_strategy("structured"), pictures=pics)
    assert res.score == 0.0 and any("не относятся к содержанию" in r for r in res.reasons)
    chart = OutlineSlide(id="c", kind=PatternKind.chart, headline="Рост", content=SlideContent(chart=ChartSpec(series_ids=["s1"])))
    assert score_pattern(chart, p, manifest, get_strategy("structured"), pictures=pics).score > 0


def test_an_empty_device_mockup_and_an_unused_note_band_weigh_on_a_content_sample(simple_deck, tmp_path):
    from verstka.analysis.manifest import analyze_template
    from verstka.matching.scorer import score_pattern
    from verstka.planning.strategies import get_strategy
    from verstka.schemas.outline import OutlineSlide, SlideContent

    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    s = OutlineSlide(id="s", kind=PatternKind.bullets, headline="Три шага после финала", content=SlideContent(bullets=["Инференс VK", "Картинки внутри слайдов"]))
    plain = score_pattern(s, _cards_pattern(), manifest, get_strategy("structured")).score
    mock = score_pattern(s, _cards_pattern(mockup_boxes=[BboxFrac(x=0.55, y=0.2, w=0.3, h=0.6)]), manifest, get_strategy("structured"))
    assert mock.score == 0.0 and any("пустым экраном" in r for r in mock.reasons)
    noted = score_pattern(s, _cards_pattern(note_slot="b0"), manifest, get_strategy("structured"))
    assert noted.score < plain and any("поле примечания" in r for r in noted.reasons)
    s2 = s.model_copy(update={"takeaway": "Шаблон задаёт правила, Verstka их соблюдает"})
    with_take = score_pattern(s2, _cards_pattern(note_slot="b0"), manifest, get_strategy("structured"))
    assert any("встанет в поле примечания" in r for r in with_take.reasons)


# ---------------------------------------------------------------------------- reading templates: more of what samples say


def test_numbered_cards_are_not_a_drawn_table_and_keep_their_text():
    from verstka.analysis.groups import detect_drawn_table

    shapes = [_text("t", "Заголовок", 36, 0.035, 0.06, 0.64, 0.17)]
    for r, y in enumerate((0.232, 0.537)):
        for c, x in enumerate((0.036, 0.358, 0.681)):
            k = r * 3 + c
            shapes.append(_shape(f"n{k}", x, y, 0.055, 0.099, fill="212121", geometry="roundRect", z=1))
            shapes[-1].text = TextInfo(paragraphs=[ParagraphInfo(text=f"0{k + 1}", runs=[RunInfo(text=f"0{k + 1}", font="Play", size_pt=16, bold=False, color_hex="FFFFFF")])])
            shapes.append(_text(f"h{k}", "Заголовок", 20, x, y + 0.13, 0.282, 0.074))
            shapes.append(_text(f"b{k}", "Основной текст", 16, x, y + 0.189, 0.282, 0.117))  # overlaps the heading's foot
    assert detect_drawn_table(shapes, W, H) is None
    groups = detect_repeat_groups(shapes, W, H)
    assert len(groups) == 1 and len(groups[0].member_shape_ids) == 6
    assert all(len(cell) == 3 for cell in groups[0].member_shape_ids)


def test_the_accent_card_of_a_row_without_its_header_plate_stays_in_the_row():
    shapes = [_text("t", "Заголовок", 36, 0.035, 0.06, 0.64, 0.17)]
    for i, x in enumerate((0.035, 0.339)):
        shapes.append(_shape(f"c{i}", x, 0.287, 0.282, 0.502, fill="000000", geometry="roundRect", line="70C3FF", z=1))
        shapes.append(_shape(f"p{i}", x, 0.287, 0.282, 0.107, fill="00AEE8", geometry="round2SameRect", z=2))
        shapes.append(_text(f"h{i}", "Заголовок", 20, x + 0.013, 0.318, 0.257, 0.045))
        shapes.append(_text(f"b{i}", "Текст", 12, x + 0.013, 0.414, 0.257, 0.126))
    shapes.append(_shape("c2", 0.642, 0.287, 0.295, 0.502, fill="00AEE8", geometry="roundRect", line="70C3FF", z=1))
    shapes.append(_text("h2", "Заголовок", 20, 0.655, 0.32, 0.282, 0.045))
    shapes.append(_text("b2", "Текст", 12, 0.655, 0.414, 0.257, 0.126))
    groups = detect_repeat_groups(shapes, W, H)
    assert len(groups) == 1 and len(groups[0].member_shape_ids) == 3


def test_kinds_of_a_quote_an_agenda_and_a_picture_page():
    from verstka.analysis.kinds import heuristic_kind

    quote_mark = _text("q", "“", 60, 0.1, 0.2, 0.1, 0.1)
    statement = _text("s", "Write an original statement or inspiring quote.", 28, 0.1, 0.35, 0.8, 0.2)
    credit = _text("c", "— Include a credit, citation, or supporting message", 14, 0.1, 0.6, 0.8, 0.05)
    roles = {"q": SlotRole.title, "s": SlotRole.body, "c": SlotRole.body}
    assert heuristic_kind([quote_mark, statement, credit], roles, [], 18, 21, W, H)[0] == PatternKind.quote
    title = ShapeInfo(id="a", name="a", kind=ShapeKind.sp, bbox=_box(0.1, 0.2, 0.5, 0.5), z=1, text=TextInfo(paragraphs=[ParagraphInfo(text=t, has_bullet=True, runs=[RunInfo(text=t, font="Play", size_pt=32, bold=False, color_hex="FFFFFF")]) for t in ("Introduction", "About Us", "Our Projects")]))
    assert heuristic_kind([title], {"a": SlotRole.title}, [], 3, 21, W, H)[0] == PatternKind.agenda
    head = _text("h", "Заголовок в две строчки", 32, 0.02, 0.1, 0.5, 0.1)
    sub = _text("d", "Описание", 16, 0.02, 0.22, 0.4, 0.05)
    pic = ShapeInfo(id="p", name="p", kind=ShapeKind.pic, bbox=_box(0.2, 0.3, 0.6, 0.6), z=1, image_part="/ppt/media/image1.png")
    kind = heuristic_kind([head, sub, pic], {"h": SlotRole.title, "d": SlotRole.subtitle, "p": SlotRole.image}, [], 43, 54, W, H)[0]
    assert kind != PatternKind.section


def test_a_header_whose_boxes_vary_in_width_is_the_decks_furniture():
    from verstka.analysis.chrome import chrome_ids, detect_chrome

    per_slide = {}
    for i in range(1, 9):
        w = 0.08 + 0.01 * (i % 4)
        per_slide[i] = [_text(f"h{i}", "Dark Minimalist", 12, 0.5 - w / 2, 0.041, w, 0.018), _text(f"t{i}", f"Заголовок {i}", 36, 0.05, 0.2, 0.6, 0.1)]
    chrome = detect_chrome(per_slide, W, H)
    assert all(f"h{i}" in chrome_ids(per_slide[i], chrome, W, H) for i in per_slide)
