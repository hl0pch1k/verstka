"""Shortened headings and bullets end on a word that finishes a phrase — never on «за», «в», «и» — and a bullet does
not repeat the heading of its slide."""

from verstka.planning import heuristics as H
from verstka.planning.condense import trim_words
from verstka.planning.outline import validate_outline
from verstka.ru import clip_words
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent

LONG = "Функция снижает срывы дедлайнов с 31% до 12% и окупает разработку за один квартал за счёт роста конверсии в тариф «Про»"


def test_clipping_stops_before_a_new_phrase_not_after_a_preposition():
    assert clip_words(LONG, 12) == "Функция снижает срывы дедлайнов с 31% до 12% и окупает разработку"
    assert clip_words(LONG, 14) == "Функция снижает срывы дедлайнов с 31% до 12% и окупает разработку за один квартал"
    assert clip_words(LONG, 15) == "Функция снижает срывы дедлайнов с 31% до 12% и окупает разработку за один квартал"
    assert clip_words("коротко и ясно", 5) == "коротко и ясно"
    for n in range(4, 20):
        last = clip_words(LONG, n).split()[-1].lower()
        assert last not in {"за", "в", "и", "с", "до", "на", "а", "но"}, (n, last)


def test_heading_and_bullet_helpers_use_it():
    assert H.short(LONG, 12).split()[-1] == "разработку"
    assert trim_words(LONG, 15).endswith("за один квартал")


def test_a_bullet_that_repeats_the_heading_leaves():
    s = OutlineSlide(id="x", kind=PatternKind.bullets, headline=LONG, content=SlideContent(bullets=[LONG + ".", "Просим утвердить запуск и бюджет на продвижение"]))
    o = validate_outline(DeckOutline(title="T", slides=[s]), None, 12)
    body = next(sl for sl in o.slides if sl.id == "x")
    assert not body.headline.split()[-1] in {"за", "в", "и"}
    assert body.content.bullets == ["Просим утвердить запуск и бюджет на продвижение"]
