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


# ── review 2 (Task 10, round 3) ──────────────────────────────────────────────────────────────────────────────────
from verstka.schemas.common import PatternKind  # noqa: E402
from verstka.schemas.outline import SlideItem  # noqa: E402

BRIEF = "Итоги продаж VK Cloud за 9 месяцев 2026 года. Покажи рост выручки, сравни регионы, что даёт выручку."


def _sales_outline():
    tables = [t for p in sorted(SALES.iterdir()) if p.suffix in (".csv", ".xlsx", ".json", ".txt") for t in read_file(p)]
    return build_data_story(BRIEF, tables).outline


def _slide(o, file):
    return next(s for s in o.slides if s.data is not None and s.data.file == file)


def test_the_designers_words_on_a_data_slide_keep_only_the_datas_numbers():
    from verstka.planning.slide_edit import keep_data

    old = _slide(_sales_outline(), "NPS по кварталам.csv")
    new = old.model_copy(deep=True, update={"data": None, "kind": PatternKind.bullets, "takeaway": None,
                                             "subtitle": "Клиентов стало в 5 раз больше", "headline": "NPS вырос до 52"})
    new.content.chart = None
    new.content.bullets = ["Выручка выросла на 99%", "Пропуски — разрывы линии, а не ноль", "NPS: 41 → 52"]
    new.content.items = [SlideItem(title="Рост", text="в 5 раз"), SlideItem(title="NPS — 99"), SlideItem(title="Последний квартал", text="52")]
    got = keep_data(old, new)
    assert got.data is not None and got.content.chart == old.content.chart and got.kind == old.kind
    assert got.headline == "NPS вырос до 52"
    assert got.subtitle == old.subtitle  # «в 5 раз» is no fact
    assert got.content.bullets == ["Пропуски — разрывы линии, а не ноль", "NPS: 41 → 52"]
    assert [it.title for it in got.content.items] == ["Последний квартал"]
    assert got.takeaway == old.takeaway  # the designer left the caption out: the data layer's stays


def test_tidy_design_skips_the_gaps_of_a_data_chart():
    from verstka.planning import agent as AG

    s = _slide(_sales_outline(), "NPS по кварталам.csv").model_copy(deep=True)
    s.content.bullets = ["NPS достиг 77 пунктов"]
    d = AG._Design(unit=AG._Unit(key="u1", title=s.headline), slide=s, by="model")
    AG.tidy_design(d, None)  # used to raise TypeError on abs(v - None)


def test_a_summary_line_names_its_slide_and_its_category():
    from verstka.data.story import _Attribution

    o = _sales_outline()
    a = _Attribution([s for s in o.slides if s.data is not None and s.data.part[0] == 1])
    refused = ["Клиенты выросли на 23%", "Москва выросла на 23% к сентябрю", "Казань выросла на 41%",
               "Выручка выросла на 41% к сентябрю", "Москва даёт 23% выручки", "Прямые продажи — 52% выручки"]
    for line in refused:
        assert a.of(line)[0] is None, line
    assert a.of("Нужно ускорить рост")[0] is None  # no subject: no card topic
    assert a.free_or_attributed("Нужно ускорить рост") == (True, "")  # a step without numbers stands
    ok = {"Москва даёт 41% выручки": "Регионы.xlsx", "Казань растёт быстрее всех: +38%": "Регионы.xlsx",
          "Прямые продажи приносят почти половину выручки — 46%": "Каналы продаж.json",
          "Выручка выросла на 23% к сентябрю": "Выручка по месяцам.csv"}
    for line, file in ok.items():
        src, why = a.of(line)
        assert src is not None and src.data.file == file, (line, why)


def test_only_a_form_said_as_the_way_to_show_rebuilds_the_slide():
    from verstka.data.rebuild import option_for_request
    from verstka.schemas.data import VizOption

    class D:
        options = [VizOption(kind="column"), VizOption(kind="line"), VizOption(kind="table")]

    cases = {
        "на слайде 7 покажи таблицей": 2, "покажи столбцами": 0, "в виде таблицы": 2, "покажи линейным графиком": 1,
        "покажи не таблицей, а столбцами": 0, "замени таблицу на график": 1, "замени столбцы на линейный график": 1,
        "сделай график крупнее": None, "убери легенду у графика": None, "добавь заголовок к таблице": None,
        "сделай таблицу покрупнее": None, "сделай заголовок короче": None, "покажи круговой диаграммой": None,
    }
    for text, want in cases.items():
        assert option_for_request(text, D) == want, text


def test_the_renderers_reasons_reach_why_this_in_russian():
    from verstka.rendering.renderer import reasons_ru

    got = reasons_ru("p21 (failed: native object failed: no room for it on the sample (12% of the slide)); "
                     "p23 (4 plates of the layout's placeholders stay empty on the slide); p9 (something odd)")
    assert got == "p21 — для диаграммы или таблицы мало места (12% слайда); p23 — плашки макета (4) остались бы пустыми; p9 — образец не подошёл"
