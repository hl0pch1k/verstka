"""«Цель — не больше 0,5%» (ЛЦТ, письмо «склад», 20.10): знак у крупной цифры — «≤ 0,5%», а не «> 0,5%», и «не» уходит
вместе со знаком, а не остаётся обрубком подписи «Цель — не»."""

from __future__ import annotations

import pytest

from verstka.planning.meaning import tidy_values
from verstka.rendering.compose import _aside_figure, kpi_callout, label_without_figure
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent


@pytest.mark.parametrize("text,sign", [
    ("Цель — не больше 0,5%", "≤"), ("Цель — не более 0,5%", "≤"), ("Порог — не меньше 95%", "≥"),
    ("Прогноз — более 10%", ">"), ("Выручка — около 74%", "≈"),
])
def test_a_negated_hedge_is_the_reverse_sign(text, sign):
    fig = text.rsplit(" ", 1)[1]
    value, label = kpi_callout(text)
    assert value == f"{sign} {fig}" and not label.endswith(" не") and "не" not in label.split()
    assert _aside_figure(text) == f"{sign} {fig}"


def test_the_label_keeps_no_cut_off_not():
    assert label_without_figure("Цель — не больше 0,5%", "0,5%") == "Цель"


def test_tidy_values_reads_not_more_as_at_most():
    o = DeckOutline(title="t", slides=[OutlineSlide(id="a", kind="stat_row", headline="h", content=SlideContent(
        numbers=[NumberCallout(value="не больше 0,5%", label="Цель"), NumberCallout(value="более 10", label="Складов")]))])
    tidy_values(o)
    assert [n.value for n in o.slides[0].content.numbers] == ["≤ 0,5%", "> 10"]
