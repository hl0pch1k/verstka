"""Проверки аудита для слайдов из данных (описание решения §7, verstka/audit/checks/data.py): каждая — на колоде,
которая её проходит, и на испорченной копии, которую она ловит. Колода — план из семи файлов примера и её «прочтение»
(DeckIR), собранное прямо из плана: без шаблона и без LibreOffice."""

from __future__ import annotations

from pathlib import Path

import pytest

from verstka.audit.registry import AuditContext, all_checks, run_checks
from verstka.data.readers import read_file
from verstka.data.story import build_data_story
from verstka.schemas.common import Bbox, BboxFrac
from verstka.schemas.data import Table
from verstka.schemas.deck_ir import DeckIR, IRChart, IRChartSeries, IRElement, IRParagraph, IRSlide, IRTable
from verstka.schemas.outline import Brief
from verstka.schemas.template import TemplateManifest

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
BRIEF = "Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, что даёт выручку."
DATA_CHECKS = {"headline_no_conclusion", "headline_figure_not_in_data", "data_text_figure_not_in_data", "chart_values_mismatch", "chart_no_units",
               "chart_no_source", "chart_overloaded", "table_raw_dump", "chart_from_untypable", "data_split_inconsistent"}
BOX = Bbox(x=0, y=0, w=100, h=100)
FRAC = BboxFrac(x=0, y=0, w=0.5, h=0.5)


def _text(eid: str, text: str, name: str = "") -> IRElement:
    return IRElement(id=eid, type="text", bbox=BOX, bbox_frac=FRAC, paragraphs=[IRParagraph(text=text)], name=name or eid)


def _slide_ir(k: int, s) -> IRSlide:
    els = [_text(f"{k}-h", s.headline, "Title")]
    c = s.content
    if c.chart is not None:
        ch = c.chart
        kind = {"histogram": "column", "stacked_column": "column", "stacked_bar": "bar"}.get(ch.type, ch.type)
        series = [IRChartSeries(name=x.name, values=list(x.values)) for x in ch.series]
        if ch.type == "scatter":
            series = [IRChartSeries(name=x.name, values=list(x.y), x_values=list(x.x)) for x in ch.xy]
        els.append(IRElement(id=f"{k}-c", type="chart", bbox=BOX, bbox_frac=FRAC, chart=IRChart(
            type=kind, categories=list(ch.categories), series=series, x_title=ch.x_title,
            # the engine writes the unit on the value axis («Выручка, млн ₽»)
            y_title=f"{ch.y_title}, {ch.unit}" if ch.unit and ch.y_title and ch.type != "scatter" else ch.y_title)))
    if c.table is not None:
        els.append(IRElement(id=f"{k}-t", type="table", bbox=BOX, bbox_frac=FRAC, table=IRTable(rows=[list(c.table.columns)] + [list(r) for r in c.table.rows])))
    for j, n in enumerate(c.numbers):
        els.append(_text(f"{k}-n{j}", n.value, "Figure"))
        els.append(_text(f"{k}-l{j}", n.label, "Label"))
    if s.footnote:
        els.append(_text(f"{k}-f", s.footnote, "Footnote"))
    return IRSlide(index=k, elements=els, outline_id=s.id)


def _ctx(outline) -> AuditContext:
    ir = DeckIR(source="x.pptx", slide_w=12192000, slide_h=6858000, slides=[_slide_ir(k, s) for k, s in enumerate(outline.slides, 1)])
    return AuditContext(ir=ir, manifest=TemplateManifest.model_construct(template_id="t"), outline=outline)


def _issues(outline) -> list:
    issues, ran = run_checks(_ctx(outline), only=DATA_CHECKS)
    assert set(ran) == DATA_CHECKS
    return issues


@pytest.fixture(scope="module")
def story():
    tables = [t for p in sorted(SALES.iterdir()) if p.suffix in (".csv", ".xlsx", ".json", ".txt") for t in read_file(p)]
    return build_data_story(Brief(text=BRIEF, slide_count=9), tables)


@pytest.fixture
def outline(story):
    return story.outline.model_copy(deep=True)


def _slide(outline, file: str):
    return next(s for s in outline.slides if s.data is not None and s.data.file == file)


def test_the_checks_are_registered_with_russian_titles():
    specs = {spec.id: spec for spec, _ in all_checks()}
    assert DATA_CHECKS <= set(specs)
    assert all(any("а" <= ch <= "я" for ch in specs[i].title.lower()) for i in DATA_CHECKS)


def test_the_story_as_planned_passes_every_data_check(outline):
    assert _issues(outline) == []


def test_a_topic_instead_of_a_conclusion(outline):
    s = _slide(outline, "Выручка по месяцам.csv")
    s.headline = s.data.plain_headline
    got = [i for i in _issues(outline) if i.check_id == "headline_no_conclusion"]
    assert len(got) == 1 and "называет тему" in got[0].message


def test_a_number_the_data_does_not_give(outline):
    s = _slide(outline, "Регионы.xlsx")
    s.headline = "Москва даёт 45% выручки"
    got = [i for i in _issues(outline) if i.check_id == "headline_figure_not_in_data"]
    assert len(got) == 1 and "«45»" in got[0].message and got[0].severity == "error"
    s.headline = "Москва даёт 41% выручки, Нижний Новгород — 198 млн ₽"  # both are facts
    assert not [i for i in _issues(outline) if i.check_id == "headline_figure_not_in_data"]


def test_the_digits_of_a_name_are_no_figure():
    t = Table(id="f", file="Филиалы.csv", kind="csv", columns=["Филиал", "Выручка"], units=[None, "млн ₽"],
              rows=[["Филиал 1", 50.0], ["Филиал 2", 30.0], ["Филиал 3", 20.0]])
    st = build_data_story("Сравни филиалы", [t])
    s = next(x for x in st.outline.slides if x.data is not None)
    s.headline = "Филиал 1 даёт 50% выручки"
    assert not [i for i in _issues(st.outline) if i.check_id == "headline_figure_not_in_data"]


def test_a_chart_value_that_is_not_the_files(outline):
    s = _slide(outline, "Регионы.xlsx")
    ctx = _ctx(outline)
    k = outline.slides.index(s)
    chart = next(e.chart for e in ctx.ir.slides[k].elements if e.chart)
    chart.series[0].values[0] = 1430.0
    issues, _ = run_checks(ctx, only={"chart_values_mismatch"})
    assert len(issues) == 1 and "«Москва»: в данных 1433, на слайде 1430" in issues[0].message


def test_a_gap_drawn_as_zero_is_caught(outline):
    s = _slide(outline, "NPS по кварталам.csv")
    ctx = _ctx(outline)
    k = outline.slides.index(s)
    chart = next(e.chart for e in ctx.ir.slides[k].elements if e.chart)
    chart.series[0].values = [0.0 if v is None else v for v in chart.series[0].values]
    issues, _ = run_checks(ctx, only={"chart_values_mismatch"})
    assert len(issues) == 1 and "пропуск" in issues[0].message


def test_reversed_bars_and_thinned_labels_are_the_same_data(outline):
    ctx = _ctx(outline)
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.chart is not None and e.chart.type == "bar":
                e.chart.categories.reverse()
                e.chart.series[0].values.reverse()
            if e.chart is not None and e.chart.type == "line" and len(e.chart.categories) > 12:
                e.chart.categories = [c if k % 2 == 0 else "" for k, c in enumerate(e.chart.categories)]
    issues, _ = run_checks(ctx, only={"chart_values_mismatch"})
    assert issues == []


def test_a_table_row_and_a_key_figure_are_checked(outline):
    ctx = _ctx(outline)
    k = outline.slides.index(_slide(outline, "Клиенты.xlsx"))
    t = next(e.table for e in ctx.ir.slides[k].elements if e.table)
    t.rows[1][3] = "999"
    k2 = outline.slides.index(_slide(outline, "Итоги квартала.txt"))
    ctx.ir.slides[k2].elements = [e for e in ctx.ir.slides[k2].elements if e.text != "3 480"]
    issues, _ = run_checks(ctx, only={"chart_values_mismatch"})
    msgs = sorted(i.message for i in issues)
    assert len(issues) == 2 and any("другие числа" in m for m in msgs) and any("нет карточки «3 480»" in m for m in msgs)


def test_axes_and_source(outline):
    ctx = _ctx(outline)
    k = outline.slides.index(_slide(outline, "Выручка по месяцам.csv"))
    chart = next(e.chart for e in ctx.ir.slides[k].elements if e.chart)
    chart.x_title = chart.y_title = None
    ctx.ir.slides[k].elements = [e for e in ctx.ir.slides[k].elements if e.name != "Footnote"]
    issues, _ = run_checks(ctx, only={"chart_no_units", "chart_no_source"})
    assert {i.check_id for i in issues} == {"chart_no_units", "chart_no_source"}
    assert all(i.slide == k + 1 for i in issues)
    # a doughnut needs no axes; its source stays required
    k2 = outline.slides.index(_slide(outline, "Каналы продаж.json"))
    assert not [i for i in issues if i.slide == k2 + 1]


def test_an_overloaded_chart_and_a_raw_table(outline):
    s = _slide(outline, "Каналы продаж.json")
    ch = s.content.chart
    ch.categories = [f"Канал {k}" for k in range(1, 9)]
    ch.series[0].values = [12.5] * 8
    rows = [[f"Клиент {k}", "Москва", str(k)] for k in range(1, 16)]
    t = _slide(outline, "Клиенты.xlsx")
    t.content.table = t.content.table.model_copy(update={"columns": ["Клиент", "Регион", "Выручка"], "rows": rows})
    t.data.aggregation = None
    got = {i.check_id: i.message for i in _issues(outline) if i.check_id in ("chart_overloaded", "table_raw_dump")}
    assert "8 долей" in got["chart_overloaded"] and "15 строк без агрегации" in got["table_raw_dump"]


def test_no_chart_from_untypable_data(outline):
    s = _slide(outline, "Регионы.xlsx")
    s.data.nature = "untypable"
    got = [i for i in _issues(outline) if i.check_id == "chart_from_untypable"]
    assert len(got) == 1 and got[0].severity == "error"


def _split_story():
    rows = [[f"Сотрудник {i}", ["Москва", "Казань", "Пермь"][i % 3], f"Отдел {i % 5}"] for i in range(1, 26)]
    t = Table(id="people", file="Сотрудники.csv", kind="csv", columns=["Имя", "Город", "Отдел"], rows=rows, units=[None] * 3)
    return build_data_story("Справка по сотрудникам", [t]).outline


def test_split_parts_are_consistent_and_a_lost_part_is_caught():
    o = _split_story()
    assert [i for i in _issues(o) if i.check_id == "data_split_inconsistent"] == []
    lost = o.model_copy(deep=True)
    lost.slides.pop(2)
    got = [i for i in _issues(lost) if i.check_id == "data_split_inconsistent"]
    assert len(got) == 1 and "частей 2 из 3" in got[0].message
    moved = o.model_copy(deep=True)
    moved.slides[1], moved.slides[2] = moved.slides[2], moved.slides[1]
    assert [i.message for i in _issues(moved) if i.check_id == "data_split_inconsistent"] == ["Таблица «Сотрудники.csv» на нескольких слайдах: части идут не подряд"]


def test_slides_without_data_are_not_this_checks_business(outline):
    for s in outline.slides:
        s.data = None
    assert _issues(outline) == []


# ── review of Task 10: the data, not the plan; the slide's own title; checks as strong as their titles ────────────
def test_a_value_changed_in_both_plan_and_deck_is_still_caught(outline):
    s = _slide(outline, "Регионы.xlsx")
    s.content.chart.series[0].values[0] = 1500.0  # the plan says it, the deck draws it — the file says 1 433
    got = [i for i in _issues(outline) if i.check_id == "chart_values_mismatch"]
    assert len(got) == 1 and got[0].severity == "error" and "в данных 1433, на слайде 1500" in got[0].message


def test_a_table_cell_changed_in_both_plan_and_deck_is_caught(outline):
    s = _slide(outline, "Клиенты.xlsx")
    s.content.table.rows[0][3] = "999"
    got = [i for i in _issues(outline) if i.check_id == "chart_values_mismatch"]
    assert len(got) == 1 and "другие числа" in got[0].message


def test_the_title_the_slide_shows_is_checked_not_the_plan(outline):
    ctx = _ctx(outline)
    k = outline.slides.index(_slide(outline, "Регионы.xlsx"))
    title = next(e for e in ctx.ir.slides[k].elements if e.name == "Title")
    title.paragraphs = [IRParagraph(text="Москва даёт 45% выручки, Казань растёт быстрее всех")]
    issues, _ = run_checks(ctx, only={"headline_figure_not_in_data"})
    assert len(issues) == 1 and issues[0].severity == "error" and "«45»" in issues[0].message
    # a title placeholder wins over any other text
    title.ph_type = "title"
    title.paragraphs = [IRParagraph(text="Выручка по регионам")]
    issues, _ = run_checks(ctx, only={"headline_no_conclusion"})
    assert len(issues) == 1 and "называет тему" in issues[0].message


def test_both_axis_titles_and_a_named_source_are_required(outline):
    ctx = _ctx(outline)
    k = outline.slides.index(_slide(outline, "Выручка по месяцам.csv"))
    chart = next(e.chart for e in ctx.ir.slides[k].elements if e.chart)
    chart.x_title = None  # the value axis alone is not enough
    foot = next(e for e in ctx.ir.slides[k].elements if e.name == "Footnote")
    foot.paragraphs = [IRParagraph(text="Источник: внутренние данные")]  # «источник», but not the file
    issues, _ = run_checks(ctx, only={"chart_no_units", "chart_no_source"})
    by = {i.check_id: i.message for i in issues}
    assert "оси категорий" in by["chart_no_units"] and "Выручка по месяцам.csv" in by["chart_no_source"]


def test_an_aggregated_table_over_ten_rows_is_flagged_too(outline):
    t = _slide(outline, "Клиенты.xlsx")
    rows = [[f"Клиент {k}", "Москва", str(k)] for k in range(1, 16)]
    t.content.table = t.content.table.model_copy(update={"columns": ["Клиент", "Регион", "Выручка"], "rows": rows})
    t.data.prepared = None
    assert t.data.aggregation
    got = [i for i in _issues(outline) if i.check_id == "table_raw_dump"]
    assert len(got) == 1 and "15 строк даже после агрегации" in got[0].message


# ── review 2: the slide's other words; the digits of names and the years of the data ──────────────────────────────
def test_numbers_in_a_data_slides_text_must_be_the_datas(outline):
    ctx = _ctx(outline)
    k = outline.slides.index(_slide(outline, "Регионы.xlsx"))
    els = ctx.ir.slides[k].elements
    els.append(_text("x1", "Выручка выросла на 99%", "Bullet"))
    els.append(_text("x2", "Рост в 5 раз", "Subtitle"))
    k2 = outline.slides.index(_slide(outline, "NPS по кварталам.csv"))
    ctx.ir.slides[k2].elements.append(_text("x3", "NPS — 99", "Card"))
    issues, _ = run_checks(ctx, only={"data_text_figure_not_in_data"})
    by = {i.slide: i for i in issues}
    assert set(by) == {k + 1, k2 + 1} and all(i.severity == "error" for i in issues)
    assert "«99»" in by[k + 1].message and "«5»" in by[k + 1].message and "«99»" in by[k2 + 1].message


def test_the_layers_own_words_values_names_and_years_pass(outline):
    ctx = _ctx(outline)
    k = outline.slides.index(_slide(outline, "Выручка по месяцам.csv"))
    els = ctx.ir.slides[k].elements
    els.append(_text("c1", outline.slides[k].takeaway or "", "Conclusion"))  # «… с 296 млн ₽ до 423 млн ₽»
    els.append(_text("c2", "Москва — 1 433 млн ₽", "Note"))  # a value of another slide: not this one's
    issues, _ = run_checks(ctx, only={"data_text_figure_not_in_data"})
    assert len(issues) == 1 and "«1433»" in issues[0].message.replace("\u00a0", "")


def test_a_label_digit_and_a_data_year_are_no_figures():
    from verstka.data.readers import read_file as rf
    from verstka.data.story import bad_numbers

    root = Path(__file__).resolve().parents[2] / "examples" / "data-science-2026"
    tables = [t for p in sorted(root.iterdir()) if p.suffix in (".csv", ".xlsx", ".json", ".txt") for t in rf(p)]
    o = build_data_story("Итоги университета за 2026 год. Покажи, на что ушёл бюджет НИОКР.", tables).outline
    for s in o.slides:
        if s.data is not None:
            assert bad_numbers(s.headline, s) == [], s.headline  # «на 1 курс», «бюджета 2026»
    kpi = next(s for s in o.slides if s.data is not None and s.data.file == "Итоги года.txt")
    assert bad_numbers("Принято на 1 курс: +7%", kpi) == [7.0]
    assert _issues(o) == []


# ── live QA (U1): what the data checks missed ───────────────────────────────────────────────────────────────────────
def test_a_histogram_whose_bins_miss_values_is_caught(outline):
    s = _slide(outline, "Время ответа поддержки.csv")
    assert not run_checks(_ctx(outline), only={"chart_values_mismatch"})[0]
    # the bins built from the inliers only (the outliers «marked apart», nowhere on the chart)
    s.data.prepared.series[0][1][-1] -= 3
    s.content.chart.series[0].values[-1] -= 3
    issues, _ = run_checks(_ctx(outline), only={"chart_values_mismatch"})
    assert len(issues) == 1 and "509 значений из 512" in issues[0].message and issues[0].severity == "error"
    # unless the slide says they are not drawn
    s.takeaway = "Медиана — 54 минуты. 3 обращения — больше 10 часов: на графике не показаны."
    assert not run_checks(_ctx(outline), only={"chart_values_mismatch"})[0]


def test_the_unit_is_on_the_value_axis_itself(outline):
    s = _slide(outline, "Выручка по месяцам.csv")
    ctx = _ctx(outline)
    k = outline.slides.index(s)
    chart = next(e.chart for e in ctx.ir.slides[k].elements if e.chart)
    chart.y_title = "Выручка"  # the headline says «423 млн ₽» — the axis does not
    issues, _ = run_checks(ctx, only={"chart_no_units"})
    assert len(issues) == 1 and "нет единицы" in issues[0].message and "млн ₽" in issues[0].message
    chart.title = "млн ₽"  # the chart's own unit caption above the plot names it
    assert not run_checks(ctx, only={"chart_no_units"})[0]


def test_a_value_axis_named_by_a_kind_of_category_is_caught(outline):
    ctx = _ctx(outline)
    k = outline.slides.index(_slide(outline, "Регионы.xlsx"))
    chart = next(e.chart for e in ctx.ir.slides[k].elements if e.chart)
    assert not run_checks(ctx, only={"chart_axis_title_wrong"})[0]
    for wrong in ("Регион, млн ₽", "Форма обучения, чел."):
        chart.y_title = wrong
        issues, _ = run_checks(ctx, only={"chart_axis_title_wrong"})
        assert len(issues) == 1 and issues[0].severity == "error" and wrong in issues[0].message


def test_the_science_stacked_chart_names_its_axis_by_the_legend():
    """The live QA's H4: «Форма обучения, чел.» on the value axis — the legend's word. Until the data layer names the
    measure, the check says so."""
    root = Path(__file__).resolve().parents[2] / "examples" / "data-science-2026"
    tables = [t for p in sorted(root.iterdir()) if p.suffix in (".csv", ".xlsx", ".json", ".txt") for t in read_file(p)]
    o = build_data_story("Итоги университета за 2026 год. Покажи приём по формам обучения.", tables).outline
    s = next(x for x in o.slides if x.data is not None and x.data.file == "Приём по направлениям.xlsx")
    issues, _ = run_checks(_ctx(o), only={"chart_axis_title_wrong"})
    wrong = s.content.chart.y_title.split(",")[0].strip().lower().startswith(("форм", "тип", "вид"))
    assert bool(issues) is wrong


def test_a_data_conclusion_pushed_to_the_notes_is_an_error(outline):
    s = _slide(outline, "Клиенты.xlsx")
    ctx = _ctx(outline)
    k = outline.slides.index(s)
    ctx.ir.slides[k].notes = s.takeaway or ""
    issues, _ = run_checks(ctx, only={"content_in_notes"})
    mine = [i for i in issues if i.slide == k + 1 and i.details.get("line") == "takeaway"]
    assert len(mine) == 1 and mine[0].severity == "error" and "только в заметках" in mine[0].message
    ctx.ir.slides[k].elements.append(_text("cap", s.takeaway, "Caption"))
    issues, _ = run_checks(ctx, only={"content_in_notes"})
    assert not [i for i in issues if i.slide == k + 1 and i.details.get("line") == "takeaway"]


def test_a_promised_count_the_slide_does_not_keep():
    from verstka.audit.checks.integrity import promised_count
    from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent, SlideItem

    assert promised_count("Программа из 4 модулей ведёт от SQL к ML-пайплайнам") == 4
    assert promised_count("Три шага к запуску") == 3 and promised_count("из четырёх последовательных модулей") == 4
    assert promised_count("Выручка за 4 месяца") is None and promised_count("Топ-10 клиентов дают 38%") is None

    def deck(n_items: int):
        items = [SlideItem(title=f"Модуль {k}", text=t) for k, t in enumerate(["Основы SQL", "Потоковая обработка", "Хранилища", "ML-пайплайны"][:n_items], 1)]
        return DeckOutline(title="x", slides=[OutlineSlide(id="m", kind="process", headline="Программа из 4 модулей ведёт от SQL к ML", content=SlideContent(items=items))])

    for n, bad in ((3, True), (4, False)):
        o = deck(n)
        ir = DeckIR(source="x.pptx", slide_w=12192000, slide_h=6858000, slides=[IRSlide(index=1, elements=[_text("h", o.slides[0].headline, "Title")], outline_id="m")])
        issues, _ = run_checks(AuditContext(ir=ir, manifest=TemplateManifest.model_construct(template_id="t"), outline=o), only={"promised_count_mismatch"})
        assert bool(issues) is bad
        if bad:
            assert issues[0].severity == "error" and "обещает 4, а на слайде 3" in issues[0].message
