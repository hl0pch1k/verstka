"""The chat agent's slide edit without a model (planning/slide_edit.py): the form a request names, made by the rules."""

from verstka.planning.slide_edit import keep_what_was_asked, requested_form, rules_form
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, OutlineSlide, SlideContent, SlideItem


def _chart_slide() -> OutlineSlide:
    ch = ChartSpec(type="pie", categories=["Кофе", "Десерты", "Чай"], series=[InlineSeries(name="Доля", values=[60, 25, 15])], unit="%")
    return OutlineSlide(id="sl2", kind=PatternKind.chart, headline="Кофе — 60% выручки", content=SlideContent(chart=ch, bullets=["Средний чек — 300 рублей"]))


def test_requested_form():
    assert requested_form("покажи расходы таблицей") == ("table", None)
    assert requested_form("сделай круговую диаграмму") == ("chart", "pie")
    assert requested_form("перепиши заголовок") is None


def test_chart_as_table_keeps_the_lines():
    s = _chart_slide()
    new = rules_form(DeckOutline(title="x", slides=[s]), s, "table", None)
    assert new is not None and new.kind == PatternKind.table
    assert new.content.table.rows[0][0] == "Кофе" and new.content.chart is None
    assert new.content.bullets == ["Средний чек — 300 рублей"]


def test_kept_chart_comes_back_with_the_cards_as_lines():
    old = _chart_slide()
    new = OutlineSlide(id="sl2", kind=PatternKind.cards, headline="Вложения", content=SlideContent(items=[SlideItem(title="Витрина", text="70 000 ₽")]))
    out = keep_what_was_asked(old, new, "покажи вложения карточками, а диаграмму оставь", DeckOutline(title="x", slides=[old]))
    assert out.kind == PatternKind.chart and out.content.chart is not None
    assert out.content.bullets == ["Витрина — 70 000 ₽"]
