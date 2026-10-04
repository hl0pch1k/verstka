"""The slide's headline the agent quotes in its lines: at most 60 characters, cut at a whole word."""

from verstka.planning.compile import _name
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import OutlineSlide


def _slide(headline: str) -> OutlineSlide:
    return OutlineSlide(id="s1", kind=PatternKind.bullets, headline=headline)


def test_short_headline_is_quoted_whole():
    assert _name(_slide("Итоги  пилота")) == "«Итоги пилота»"


def test_long_headline_is_cut_at_a_word():
    name = _name(_slide("Средняя месячная выручка на одного клиента составит 5 050 рублей в первый год"))
    assert name == "«Средняя месячная выручка на одного клиента составит 5 050…»"
    assert len(name) <= 62
