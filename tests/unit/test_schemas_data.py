"""Контракты второй ступени (verstka/schemas/data.py, brand.py и расширения outline.py / GenerateRequest): круговой JSON,
значения по умолчанию, подписи, и то, что старые пути (планировщик, агент, компилятор, проверка чисел) видят прежнее."""

from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from verstka.schemas.brand import (
    BrandColor,
    BrandConflict,
    BrandFont,
    BrandLogo,
    BrandRule,
    BrandSpec,
    normalize_hex,
)
from verstka.schemas.common import PatternKind
from verstka.schemas.data import (
    NATURE_LABELS,
    TASK_TITLES,
    VIZ_TITLES,
    ColumnProfile,
    DatasetPlan,
    DatasetProfile,
    DatasetSummary,
    HeadlineFact,
    Nature,
    Outlier,
    SlideData,
    Table,
    TaskDecision,
    TaskKind,
    TimeAxis,
    VizKind,
    VizOption,
)
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, OutlineSlide, PlannedDeck, SlideContent, XYSeries


def _round(model):
    """JSON туда и обратно: та же модель."""
    back = type(model).model_validate_json(model.model_dump_json())
    assert back == model
    return back


# ---------------------------------------------------------------------------- образцы (данные продаж, SCENARIO.md)


def _table() -> Table:
    return Table(
        id="t_rev", file="Выручка по месяцам.csv", kind="csv", columns=["Месяц", "Выручка", "Клиенты", "Сделка закрыта"],
        units=[None, "млн ₽", None, None], raw_header=["Месяц", "Выручка, млн ₽", "Клиенты", "Сделка закрыта"],
        rows=[["2025-01", 297.5, 2950, True], ["2025-02", None, 2984, False], ["2025-03", 311, None, None]],
        notes="Данные — по закрытым сделкам",
    )


def _profile() -> DatasetProfile:
    return DatasetProfile(
        table_id="t_rev", file="Выручка по месяцам.csv", kind="csv", rows=21, cols=3,
        columns=[
            ColumnProfile(name="Месяц", type="period", role="time", distinct=21, min="2025-01", max="2026-09", first="2025-01", last="2026-09", samples=["2025-01", "2025-02"]),
            ColumnProfile(name="Выручка", unit="млн ₽", type="money", role="metric", distinct=21, min=297.0, max=423.0, median=352.0, first=297, last=423.0, outliers=[11], samples=[297, 302.5]),
        ],
        time_axis=TimeAxis(column="Месяц", freq="month", start="2025-01", end="2026-09", points=21),
        metrics=["Выручка", "Клиенты"], dimensions=[], hierarchies=[("город", "регион")], missing_total=1,
        outliers=[Outlier(column="Выручка", row=11, value=378.0, reason="больше соседей на 7%")],
        size="medium", nature="time_series", summary="Временной ряд · 21 строка · 3 колонки",
    )


def _plan() -> DatasetPlan:
    return DatasetPlan(
        profile=_profile(),
        task=TaskDecision(task="dynamics", reasons=["Есть ось времени и одна главная метрика"], goal="покажи рост выручки",
                          scores={"dynamics": 0.92, "comparison": 0.31}),
        options=[
            VizOption(kind="line", score=0.94, reasons=["Дата и одна метрика, 21 точка — тренд виден сразу"]),
            VizOption(kind="column", score=0.61, why_not="За 21 столбцом тренд виден хуже"),
            VizOption(kind="table", score=0.2, why_not="21 строка — тренд не читается", aggregation="по месяцам"),
        ],
        headline="Выручка выросла на 23% к сентябрю",
        headline_facts=[HeadlineFact(id="f1", text="Выручка выросла на 23% к сентябрю 2026", value=23.0, unit="%", kind="change",
                                     explain="Сентябрь 2026 к сентябрю 2025: 423 млн ₽ — на 23% больше.")],
        plain_headline="Выручка по месяцам", caption="Выручка, млн ₽, по месяцам", source="Источник: Выручка по месяцам.csv",
    )


# ---------------------------------------------------------------------------- данные


def test_the_labels_name_every_kind_in_the_briefs_words():
    assert set(NATURE_LABELS) == set(get_args(Nature))
    assert list(NATURE_LABELS.values()) == ["Временной ряд", "Сравнение", "Доли", "Распределение", "Справочник",
                                            "Временной ряд с пропусками", "Таблица в тексте", "Взаимосвязь", "Ключевые показатели", "Не для графика"]
    assert set(VIZ_TITLES) == set(get_args(VizKind))
    assert list(VIZ_TITLES.values()) == ["Линейный график", "Столбцы", "Полосы", "Гистограмма", "Круговая", "Кольцевая", "Рассеяние",
                                         "Сгруппированные столбцы", "Сгруппированные полосы", "Накопительные столбцы",
                                         "Накопительные полосы", "Карточки показателей", "Таблица", "Область"]
    assert set(TASK_TITLES) == set(get_args(TaskKind))


def test_a_table_keeps_its_cells_types_through_json():
    t = _round(_table())
    assert [type(c) for c in t.rows[0]] == [str, float, int, bool]
    assert t.rows[1][1] is None and t.rows[2][1] == 311 and isinstance(t.rows[2][1], int)
    assert t.column_values("Выручка") == [297.5, None, 311] and t.column_values(3) == [True, False, None]
    assert t.unit_of("Выручка") == "млн ₽" and t.unit_of(0) is None
    short = Table(id="x", file="a.csv", kind="csv", columns=["a", "b"], rows=[[1]])
    assert short.column_values("b") == [None] and short.unit_of("b") is None


def test_a_table_needs_only_its_id_file_and_kind():
    t = Table(id="x", file="a.json", kind="json")
    assert (t.sheet, t.columns, t.units, t.rows, t.raw_header, t.notes) == (None, [], [], [], [], "")
    with pytest.raises(ValidationError):
        Table(id="x", file="a.xls", kind="xls")


def test_a_profile_round_trips_with_dates_as_iso_and_numbers_as_numbers():
    p = _round(_profile())
    month, rev = p.columns
    assert month.min == "2025-01" and month.max == "2026-09" and month.median is None
    assert rev.min == 297.0 and rev.first == 297 and rev.last == 423.0 and rev.outliers == [11]
    assert p.hierarchies == [("город", "регион")]
    assert json.loads(p.model_dump_json())["hierarchies"] == [["город", "регион"]]


def test_profile_defaults():
    p = DatasetProfile(table_id="t", file="a.csv", kind="csv", rows=0, cols=0, nature="untypable")
    assert p.typable is True and p.untypable_reason is None and p.time_axis is None and p.parts_of_whole is False
    assert p.size == "small" and p.summary == "" and p.missing_total == 0 and p.hierarchies == [] and p.outliers == []
    c = ColumnProfile(name="a", type="text", role="text")
    assert (c.unit, c.missing, c.distinct, c.min, c.first, c.outliers, c.samples) == (None, 0, 0, None, None, [], [])
    assert TimeAxis(column="m", freq="quarter", start="2024-Q4", end="2026-Q3", points=8).missing_periods == []
    assert Outlier(column="a", row=3, value=612).reason == ""
    with pytest.raises(ValidationError):
        DatasetProfile(table_id="t", file="a.csv", kind="csv", rows=0, cols=0, nature="table")


def test_a_plan_round_trips_and_names_its_chosen_option():
    plan = _round(_plan())
    assert plan.chosen == 0 and plan.chosen_option is not None and plan.chosen_option.kind == "line"
    assert [o.title for o in plan.options] == ["Линейный график", "Столбцы", "Таблица"]  # пустое название — по виду
    assert plan.task.scores == {"dynamics": 0.92, "comparison": 0.31} and plan.task.goal == "покажи рост выручки"
    assert plan.slides == 1 and plan.message is None
    plan.chosen = 5
    assert plan.chosen_option is None


def test_an_option_keeps_its_own_title():
    o = VizOption(kind="bar", title="Ранжированные горизонтальные столбцы")
    assert o.title == "Ранжированные горизонтальные столбцы" and o.score == 0.0 and o.reasons == [] and o.why_not is None and o.aggregation is None
    with pytest.raises(ValidationError):
        VizOption(kind="radar")
    with pytest.raises(ValidationError):
        HeadlineFact(id="f", text="…", value=1, kind="trend")
    with pytest.raises(ValidationError):
        TaskDecision(task="dynamics", scores={"trend": 1.0})


def test_slide_data_round_trips_and_labels_its_nature():
    plan = _plan()
    sd = SlideData(dataset_id="ds1", file=plan.profile.file, profile_line="CSV · 21 строка × 3 колонки · временной ряд",
                   nature="time_series", columns=plan.profile.columns, time_axis=plan.profile.time_axis, metrics=plan.profile.metrics,
                   missing_total=1, outliers=plan.profile.outliers, task=plan.task, options=plan.options, chosen=0,
                   headline_facts=plan.headline_facts, plain_headline=plan.plain_headline, aggregation="по месяцам", part=(2, 3))
    back = _round(sd)
    assert back.nature_label == "Временной ряд" and back.part == (2, 3)
    assert json.loads(back.model_dump_json())["part"] == [2, 3]
    bare = SlideData(dataset_id="ds2", file="a.csv")
    assert bare.part == (1, 1) and bare.chosen == 0 and bare.task is None and bare.nature is None and bare.nature_label == ""
    assert SlideData(dataset_id="d", file="f", nature="with_gaps", nature_label="Свой").nature_label == "Свой"


def test_a_dataset_summary_labels_its_nature():
    s = _round(DatasetSummary(id="ds1", file="NPS по кварталам.csv", kind="csv", rows=8, cols=2, nature="with_gaps",
                              line="Временной ряд с пропусками · 8 строк · 2 колонки", issues=["2 пропуска"]))
    assert s.nature_label == "Временной ряд с пропусками" and s.sheet is None
    assert DatasetSummary(id="x", file="Итоги квартала.txt", kind="text", nature="text_table").nature_label == "Таблица в тексте"


# ---------------------------------------------------------------------------- брендбук


def _brand() -> BrandSpec:
    return BrandSpec(
        id="bb1", name="VK Cloud", source="pdf", file="Брендбук VK Cloud.pdf", pages=24,
        colors=[BrandColor(hex="#0077FF", role="primary", name="VK Blue"), BrandColor(hex="2787f5", role="secondary"),
                BrandColor(hex="#0B1220", role="text"), BrandColor(hex="#FFF", role="background"),
                BrandColor(hex="#FF3985", role="accent"), BrandColor(hex="#00C2FF")],
        fonts=[BrandFont(role="heading", family="VK Sans Display", fallback="Play", weight=700), BrandFont(role="body", family="VK Sans Text")],
        logos=[BrandLogo(name="Основной", file="logos/main.svg"), BrandLogo(name="Белый", file="logos/white.svg", variant="white", ground="dark")],
        margins_px=48, rules=[BrandRule(text="Логотип — в правом нижнем углу", kind="logo"), BrandRule(text="Акцент — только для главного числа")],
        logo_place="bottom_right",
    )


def test_a_brandbook_round_trips():
    b = _round(_brand())
    assert [c.hex for c in b.colors] == ["#0077FF", "#2787F5", "#0B1220", "#FFFFFF", "#FF3985", "#00C2FF"]
    assert b.colors[-1].role == "chart" and b.colors[1].name is None
    assert b.color("accent").hex == "#FF3985" and b.color("danger") is None
    assert b.font("heading").fallback == "Play" and b.font("body").weight == 400 and b.font("body").fallback is None
    assert b.logos[0].variant == "primary" and b.logos[0].ground == "any" and b.logos[1].ground == "dark"
    assert b.rules[1].kind == "other" and b.margins_px == 48 and b.grid is None and b.warnings == []


def test_brandbook_defaults_and_bad_values():
    b = BrandSpec(source="tokens")
    assert (b.id, b.name, b.file, b.pages, b.colors, b.fonts, b.logos, b.margins_px, b.rules, b.logo_place) == ("", "", None, 0, [], [], [], None, [], None)
    for bad in ("blue", "#12345", "#GGGGGG", ""):
        with pytest.raises(ValidationError):
            BrandColor(hex=bad)
    with pytest.raises(ValidationError):
        BrandSpec(source="sketch")
    with pytest.raises(ValidationError):
        BrandSpec(source="pdf", logo_place="center")
    with pytest.raises(ValidationError):
        BrandFont(role="caption", family="Play")
    assert normalize_hex(" #07f ") == "#0077FF"


def test_a_conflict_round_trips():
    c = _round(BrandConflict(what="Второй акцент", template="#FF3885", brand="#FF3985", result="#FF3985", kind="color"))
    assert c.kind == "color"
    assert BrandConflict(what="Шрифт заголовков", template="Play", brand="VK Sans Display", result="VK Sans Display").kind == "other"


# ---------------------------------------------------------------------------- outline: графики и данные слайда


def test_the_chart_takes_the_new_types_and_fields():
    for t in ("histogram", "scatter", "stacked_column", "stacked_bar", "grouped_column", "grouped_bar", "column", "doughnut"):
        assert ChartSpec(type=t).type == t
    with pytest.raises(ValidationError):
        ChartSpec(type="radar")
    c = ChartSpec()
    assert (c.type, c.x_title, c.y_title, c.gaps, c.source, c.xy) == ("column", None, None, False, None, [])
    full = _round(ChartSpec(type="scatter", x_title="Цена, ₽", y_title="Продажи, шт.", source="Источник: цены.csv",
                            xy=[XYSeries(name="Магазины", x=[1, 2.5], y=[10, 12])]))
    assert full.xy[0].x == [1.0, 2.5] and all(isinstance(v, float) for v in full.xy[0].y)
    gaps = _round(ChartSpec(type="line", gaps=True, categories=["I кв.", "II кв.", "III кв."], series=[InlineSeries(name="NPS", values=[41, None, 52])]))
    assert gaps.series[0].values == [41.0, None, 52.0] and gaps.gaps is True


def test_old_paths_see_floats():
    """Без пропусков серия — прежние числа: целые становятся float, валидированные Series рисуются как раньше."""
    from verstka.rendering.charts import inline_series

    s = InlineSeries(name="Выручка", values=[1, 2, 3])
    assert all(type(v) is float for v in s.values)
    spec = ChartSpec(type="column", categories=["a", "b", "c"], series=[s])
    out = inline_series(spec)
    assert len(out) == 1 and out[0].values == [1.0, 2.0, 3.0]
    # пропуск из файла с данными: разрыв, не ноль
    out = inline_series(ChartSpec(type="line", categories=["a", "b", "c"], series=[InlineSeries(values=[1, None, 3])]))
    assert out[0].values == [1.0, None, 3.0]


def test_grounding_and_compile_keep_working():
    from verstka.planning.compile import _compile_charts, _Run
    from verstka.planning.grounding import BriefIndex, inline_ok

    idx = BriefIndex("Выручка выросла со 120 до 150 млн рублей, затем до 180.")
    assert inline_ok(ChartSpec(categories=["a", "b", "c"], series=[InlineSeries(values=[120, 150, 180])]), idx)
    # пропуск не проходит проверку по тексту (и не роняет её): серия с пропусками — только из файлов с данными
    assert not inline_ok(ChartSpec(categories=["a", "b", "c"], series=[InlineSeries(values=[120, None, 180])]), idx)
    o = DeckOutline(title="t", slides=[OutlineSlide(id="s1", kind=PatternKind.chart, headline="Рост",
                                                    content=SlideContent(chart=ChartSpec(categories=["a", "b"], series=[InlineSeries(name="x", values=[120, 150])])))])
    assert _compile_charts(o, _Run(o, None)) == 1
    assert o.series[0].id == "s_s1_1" and o.series[0].values == [120.0, 150.0]
    assert o.slides[0].content.chart.series_ids == ["s_s1_1"]


def test_the_slide_carries_its_data_through_the_deck_json():
    sd = SlideData(dataset_id="ds1", file="Регионы.xlsx", nature="comparison", options=[VizOption(kind="bar"), VizOption(kind="column")])
    o = DeckOutline(title="Продажи", slides=[OutlineSlide(id="s1", kind=PatternKind.chart, headline="Москва даёт 41% выручки", data=sd),
                                             OutlineSlide(id="s2", kind=PatternKind.title, headline="Продажи")])
    back = _round(o)
    assert back.slides[0].data == sd and back.slides[1].data is None
    assert OutlineSlide(id="x", kind=PatternKind.bullets, headline="h").data is None


def test_the_planner_model_sees_the_schema_it_saw_before():
    """Поля и типы второй ступени заполняет код, не модель: схема PlannedDeck для планировщика прежняя."""
    shown = json.dumps(PlannedDeck.model_json_schema(), ensure_ascii=False)
    for word in ("SlideData", "histogram", "scatter", "stacked_", "grouped_", "x_title", "y_title", "gaps", "XYSeries", '"xy"', "DatasetProfile"):
        assert word not in shown, word
    schema = PlannedDeck.model_json_schema()
    assert schema["$defs"]["InlineSeries"]["properties"]["values"]["items"] == {"type": "number"}
    assert schema["$defs"]["ChartSpec"]["properties"]["type"]["enum"] == ["bar", "column", "line", "area", "pie", "doughnut"]


# ---------------------------------------------------------------------------- запрос генерации


def test_the_request_takes_datasets_and_a_brandbook_and_keeps_them():
    from verstka.api.app import GenerateRequest, _request_options

    req = GenerateRequest(template_id="t1", brief="Итоги продаж")
    assert req.dataset_ids == [] and req.brandbook_id is None and req.brand_priority == "brand"
    opts = _request_options(req)
    assert opts["dataset_ids"] == [] and opts["brandbook_id"] is None and opts["brand_priority"] == "brand"
    req = GenerateRequest(template_id="t1", brief="Итоги продаж", dataset_ids=["ds1", "ds2"], brandbook_id="bb1", brand_priority="template")
    opts = _request_options(req)
    assert opts["dataset_ids"] == ["ds1", "ds2"] and opts["brandbook_id"] == "bb1" and opts["brand_priority"] == "template"
    assert json.loads(json.dumps(opts))["dataset_ids"] == ["ds1", "ds2"]  # пишется в generation.json
    with pytest.raises(ValidationError):
        GenerateRequest(template_id="t1", brand_priority="both")
