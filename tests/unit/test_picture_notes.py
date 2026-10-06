"""A picture the author described beside the text («[Место под изображение: …]») in a brief the planners cut into
slides themselves: the note is never the deck's text, its free place goes on the slide of the author's words next to
it (verstka/planning/pictures.py). The live run of 2026-10-07 made a slide «Панель показывает три ключевых параметра»
of the note, and the deck had no picture."""

from __future__ import annotations

from verstka.planning.brief import parse_brief_text
from verstka.planning.facts import basic_facts
from verstka.planning.outline import basic_outline
from verstka.planning.pictures import picture_notes, place_pictures_by_text
from verstka.planning.strategies import load_strategies
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent

PLAIN = """Умная теплица на Arduino. Школьный проект: теплица сама поливает грядки и проветривает.

Датчики влажности грунта стоят в трёх грядках. Насос поливает их из бака на 50 литров. Вентилятор включается, когда воздух теплее 28 °C.

[Место под изображение: экран панели управления теплицей с карточками температуры, влажности и уровня воды]

За месяц расход воды снизился со 160 до 110 литров в неделю, ручной труд — с 6 до 1,5 часа в неделю.
"""


def test_a_note_about_a_picture_is_never_a_slide_of_the_rules_planner():
    brief = parse_brief_text(PLAIN)
    for st in load_strategies().values():
        o = basic_outline(brief, basic_facts(brief.text), st, 6)
        texts = " ".join(f"{s.headline} {' '.join(s.content.bullets)}" for s in o.slides)
        assert "Место под изображение" not in texts and "Экран панели" not in texts, st.name
        pictured = [s for s in o.slides if s.content.photo_slot]
        assert len(pictured) == 1 and pictured[0].kind not in (K.title, K.thanks), st.name
        assert pictured[0].content.photo_hint.startswith("Экран панели управления теплицей") and not pictured[0].content.photo_own


def test_the_place_goes_to_the_slide_of_the_sentence_before_the_note_else_after_it():
    text, notes = picture_notes("Датчики влажности грунта стоят в грядках.\n\n[Место под изображение: схема грядок]\n\nВыручка выросла на 30%.\n")
    o = DeckOutline(title="T", slides=[
        OutlineSlide(id="s1", kind=K.title, headline="Обложка"),
        OutlineSlide(id="s2", kind=K.bullets, headline="Выручка", content=SlideContent(bullets=["Выручка выросла на 30%"])),
        OutlineSlide(id="s3", kind=K.bullets, headline="Как устроено", content=SlideContent(bullets=["Датчики влажности грунта в грядках"])),
        OutlineSlide(id="s4", kind=K.thanks, headline="Спасибо"),
    ])
    place_pictures_by_text(o, text, notes, [])
    assert [s.id for s in o.slides if s.content.photo_slot] == ["s3"]  # the words before the note, wherever its slide is
    # a second note with no slide of its words: the content slide at the note's place in the brief, one per slide
    warns: list = []
    place_pictures_by_text(o, text, [(1, "Офис", "фото офиса я добавлю сам")], warns)
    s2 = o.slides[1]
    assert s2.content.photo_hint == "Офис" and s2.content.photo_own and not warns
    place_pictures_by_text(o, text, [(1, "Лишнее", "")], warns)
    assert warns and not o.slides[0].content.photo_slot and not o.slides[3].content.photo_slot  # never on a frame
