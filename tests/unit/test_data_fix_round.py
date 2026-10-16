"""Правки после живого прогона (Task 10, fix round): выбранный вид диаграммы движок не поворачивает, а данные и итог
колоды не сверяются с текстом брифа."""

from __future__ import annotations

from pathlib import Path

from verstka.data.readers import read_file
from verstka.data.story import build_data_story
from verstka.rendering.charts import effective_chart_type, prefer_bar
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, PlannedDeck

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
REGIONS = ["Москва", "Санкт-Петербург", "Екатеринбург", "Казань", "Новосибирск", "Краснодар", "Ростов-на-Дону", "Нижний Новгород"]


def _spec(**kw) -> ChartSpec:
    return ChartSpec(type="column", categories=REGIONS, series=[InlineSeries(name="Выручка", values=[1433, 612, 318, 274, 236, 214, 210, 198])], **kw)


def test_long_labels_turn_columns_into_bars_unless_the_kind_was_chosen():
    o = DeckOutline(title="x")
    assert prefer_bar(_spec(), o) and effective_chart_type(_spec(), o) == "bar"
    locked = _spec(kind_locked=True)
    assert not prefer_bar(locked, o) and effective_chart_type(locked, o) == "column"
    # a bar stays a bar, a histogram a column, locked or not
    assert effective_chart_type(locked.model_copy(update={"type": "bar"}), o) == "bar"
    assert effective_chart_type(locked.model_copy(update={"type": "stacked_column"}), o) == "stacked_column"


def test_the_flag_stays_out_of_the_planners_schema():
    assert "kind_locked" not in str(PlannedDeck.model_json_schema())


def test_every_chart_of_a_data_deck_is_locked():
    tables = [t for p in sorted(SALES.iterdir()) if p.suffix in (".csv", ".xlsx", ".json", ".txt") for t in read_file(p)]
    o = build_data_story("Покажи рост выручки", tables).outline
    charts = [s.content.chart for s in o.slides if s.data is not None and s.content.chart is not None]
    assert charts and all(ch.kind_locked for ch in charts)
