"""The agent's compiler (planning/compile.py) on the user's two coffee briefs: the designer's slides (hand-written
fixtures tests/fixtures/agent_v2_*.json, with the faults live runs show) become a deck whose charts have the brief's
data, whose figures are all the brief's, whose titles are the user's and whose slides are the ones the user asked for,
in the user's order."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from verstka.planning.compile import apply_alternative, compile_outline, fallback_slide
from verstka.planning.grounding import BriefIndex, figures, ground_outline, rounding_step, title_line, unit_scale, value_ok
from verstka.planning.outline import polish_plan, validate_outline
from verstka.schemas.brief_structure import BriefStructure
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import Brief, ChartSpec, DeckOutline, InlineSeries, OutlineSlide, SlideAlternative, SlideContent

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> tuple[Brief, BriefStructure, DeckOutline]:
    d = json.loads((FIX / f"agent_v2_{name}.json").read_text(encoding="utf-8"))
    return Brief(**d["brief"]), BriefStructure.model_validate(d["structure"]), DeckOutline.model_validate(d["outline"])


@pytest.fixture(scope="module")
def long_deck():
    brief, st, o = _load("long")
    events: list[dict] = []
    out, warnings = compile_outline(o, st, brief, progress=events.append)
    return brief, st, out, warnings, events


@pytest.fixture(scope="module")
def short_deck():
    brief, st, o = _load("short")
    out, warnings = compile_outline(o, st, brief)
    return brief, st, out, warnings


def _by_spec(o: DeckOutline) -> dict[int, OutlineSlide]:
    return {s.spec_ref: s for s in o.slides if s.spec_ref is not None}


def _texts(s: OutlineSlide) -> list[str]:
    c = s.content
    out = [s.headline, s.subtitle or "", s.takeaway or "", s.footnote or "", c.formula or ""] + c.bullets + c.paragraphs
    out += [f"{n.value} {n.label}" for n in c.numbers]
    out += [" ".join([it.title, it.text, *it.bullets]) for it in c.items + c.columns]
    if c.table is not None:
        out += [" | ".join(r) for r in c.table.rows]
    return [t for t in out if t]


def _charts(o: DeckOutline):
    for s in o.slides:
        for ch in (s.content.chart, s.content.chart2):
            if ch is not None:
                yield s, ch


def _every_figure_is_the_briefs(o: DeckOutline, brief: Brief, st: BriefStructure) -> None:
    idx = BriefIndex.of(brief)
    step = rounding_step(st.rounding)
    for s in o.slides:
        for t in _texts(s):
            for f in figures(t):
                assert idx.verdict(f) != "bad", (s.id, t)
    reg = {x.id: x for x in o.series}
    for s, ch in _charts(o):
        for sid in ch.series_ids:
            ser = reg[sid]
            assert all(value_ok(idx, v, unit_scale(ser.unit), step) for v in ser.values), (s.id, ser)


# ------------------------------------------------------------------ the long brief (10 slides dictated)


def test_long_brief_keeps_the_users_title_subtitle_and_disclaimer(long_deck):
    _, _, out, warnings, _ = long_deck
    assert out.title == "Больше прибыли с каждой чашки"  # not «Это учебный бизнес-кейс…» (the user's run)
    cover = out.slides[0]
    assert cover.kind == K.title and cover.spec_ref == 1
    assert cover.headline == "Больше прибыли с каждой чашки"
    assert cover.subtitle == "План развития кофейни “Точка кофе” на 6 месяцев"
    assert "Все исходные данные и прогнозы условные" in (cover.footnote or "")
    assert not any("deck title" in w for w in warnings)


def test_long_brief_slides_are_the_users_ten_in_order(long_deck):
    _, _, out, warnings, _ = long_deck
    assert [s.spec_ref for s in out.slides] == list(range(1, 11))  # the designer sent 9 before 8, a divider, a thanks
    assert not any(s.kind in (K.section, K.thanks) for s in out.slides)
    assert any("«План роста» dropped" in w for w in warnings)
    # validate_outline and polish_plan keep them: no cover or closing slide added, none dropped for the count
    v = validate_outline(out.model_copy(deep=True), None, 10, hard_limit=True)
    assert [s.spec_ref for s in v.slides] == list(range(1, 11))
    tight = validate_outline(out.model_copy(deep=True), None, 7, hard_limit=True)
    assert [s.spec_ref for s in tight.slides] == list(range(1, 11))
    assert [s.spec_ref for s in polish_plan(out).slides] == list(range(1, 11))


def test_long_brief_charts_have_the_briefs_data_as_registry_series(long_deck):
    _, _, out, _, _ = long_deck
    reg = {x.id: x for x in out.series}
    charts = list(_charts(out))
    assert len(charts) >= 4
    for s, ch in charts:
        assert ch.series_ids and all(i in reg for i in ch.series_ids), s.id
        assert all(re.fullmatch(rf"s_{re.escape(s.id)}_\d+", i) for i in ch.series_ids)
        first = reg[ch.series_ids[0]]
        assert ch.categories == first.categories and [x.values for x in ch.series] == [reg[i].values for i in ch.series_ids]
    sp = _by_spec(out)
    costs = sp[3].content.chart
    assert costs.type == "doughnut" and reg[costs.series_ids[0]].values == [315000, 270000, 120000, 25000, 20000, 30000]
    check = sp[5].content
    assert reg[check.chart.series_ids[0]].values == [300, 330] and reg[check.chart2.series_ids[0]].values == [20, 30]


def test_long_brief_every_figure_is_the_briefs(long_deck):
    brief, st, out, _, _ = long_deck
    _every_figure_is_the_briefs(out, brief, st)
    sp = _by_spec(out)
    assert sp[2].content.formula == "100 × 300 × 30 = 900 000 рублей"
    assert sp[9].content.table is not None and len(sp[9].content.table.rows) == 7
    assert sp[9].content.table.rows[4] == ["Постоянные операционные расходы", "465 000 рублей", "508 000 рублей"]  # the unit written once
    assert sp[9].headline == "К шестому месяцу прибыль вырастет примерно на 112%"  # a conclusion the brief states


def test_long_brief_what_the_user_asked_for_is_on_its_slide(long_deck):
    _, _, out, _, _ = long_deck
    sp = _by_spec(out)
    assert sp[3].footnote == "Налоги, проценты по кредитам и амортизация в упрощенной модели не учитываются."  # «Укажи, что …»
    assert sp[9].takeaway and "26,5%" in sp[9].takeaway  # «Вывод: …» the designer left out
    assert sp[10].takeaway == "Рост прибыли зависит от трех измеримых изменений: больше покупок, выше средний чек и меньше потерь"
    assert all(s.takeaway for s in out.slides[1:])  # a short conclusion on every slide


def test_long_brief_variety_pass_breaks_three_charts_in_a_row(long_deck):
    _, _, out, warnings, _ = long_deck
    kinds = [s.kind for s in out.slides]
    assert not any(kinds[i] == kinds[i + 1] == kinds[i + 2] for i in range(len(kinds) - 2))
    losses = _by_spec(out)[7]
    assert losses.kind == K.big_number and losses.content.chart is None
    assert losses.content.numbers[0].value == "27 000 → 15 000 ₽"
    assert losses.rationale.startswith("крупно")
    assert any(a.kind == "chart" for a in losses.alternatives)  # the form it had is an alternative now
    assert any("d7: chart → big_number" in w for w in warnings)


def test_compiler_reports_its_work_as_agent_events(long_deck):
    _, _, out, _, events = long_deck
    assert events and all(e["type"] == "agent" and e["step"] == "compile" and e["variant"] == "structured" for e in events)
    # the log line names its step, the event does not (the timeline shows it under «Сборка»)
    assert [f"Сборка: {e['message'][:1].lower() + e['message'][1:]}" for e in events] == out.agent_log
    assert events[0]["message"] == "Собрал 10 слайдов в том порядке, который задан в брифе."
    assert out.agent_log[0] == "Сборка: собрал 10 слайдов в том порядке, который задан в брифе."
    assert any(e["slide"] == 7 and "крупная цифра" in e["message"] for e in events)
    assert all(not re.search(r"[A-Za-z_]{4,}", m) for m in out.agent_log)  # plain Russian, no ids or kind names


def test_compile_is_idempotent(long_deck):
    brief, st, out, _, _ = long_deck
    again, _ = compile_outline(out, st, brief)
    assert [(s.id, s.kind, s.headline) for s in again.slides] == [(s.id, s.kind, s.headline) for s in out.slides]
    assert len({x.id for x in again.series}) == len(again.series) == len(out.series)


# ------------------------------------------------------------------ the short brief (5 slides, charts ordered)


def test_short_brief_every_chart_slide_stays_with_its_data(short_deck):
    brief, st, out, warnings = short_deck
    assert out.slides[0].kind == K.title and out.slides[0].spec_ref is None  # a cover: the user's five are content
    assert out.slides[0].headline == out.title == "Кофейня «Точка кофе»: план увеличения прибыли за 6 месяцев"
    assert out.slides[0].footnote == "Все цифры условные."
    assert [s.spec_ref for s in out.slides[1:]] == [1, 2, 3, 4, 5]  # the designer's answers came back shuffled
    assert all(s.kind == K.chart for s in out.slides[1:])  # five charts in a row: all asked for, none varied away
    reg = {x.id: x for x in out.series}
    sp = _by_spec(out)
    assert sp[1].content.chart.type == "pie"  # the designer drew columns; the user asked for a pie
    assert reg[sp[2].content.chart.series_ids[0]].values == [315000, 270000, 120000, 25000, 20000, 30000]  # it had none
    assert sp[3].content.chart and sp[3].content.chart2  # «два небольших столбчатых графика»
    line = sp[4].content.chart
    assert line.type == "line" and line.unit == "тыс. ₽" and reg[line.series_ids[0]].values[-1] == 1138.5
    assert sp[4].content.chart2.type == "doughnut"
    _every_figure_is_the_briefs(out, brief, st)
    assert any("v1: chart type column → pie" in w for w in warnings)


def test_short_brief_only_invented_figures_go_from_the_users_slides(short_deck):
    _, _, out, warnings = short_deck
    result = _by_spec(out)[5]
    assert result.content.bullets == ["Рентабельность вырастет с 13,3% до 22,4%"]  # «Окупаемость вложений — 2 месяца» went
    assert result.headline == "Прибыль вырастет на 112,3%"  # «Рост составит 112,3%» in the brief
    assert _by_spec(out)[3].takeaway == "Выручка вырастет на 238 500 рублей в месяц"  # «на 238 500 рублей больше»
    assert any("«2 месяца»" in w for w in warnings)


def test_a_chart_with_numbers_not_in_the_brief_takes_the_briefs_series():
    brief, st, o = _load("short")
    v5 = next(s for s in o.slides if s.spec_ref == 5)
    v5.content.chart.series[0].values = [120000, 260000]  # a model's rounding the brief does not allow
    out, warnings = compile_outline(o, st, brief)
    ch = _by_spec(out)[5].content.chart
    assert ch.series_ids == ["s7"] and [x.values for x in ch.series] == [[120000, 254795]]
    assert any("numbers not in the brief" in w for w in warnings)


def test_a_slide_the_designer_did_not_send_is_built_from_the_brief():
    brief, st, o = _load("short")
    o.slides = [s for s in o.slides if s.spec_ref != 4]
    o.slides.append(o.slides[1].model_copy(update={"id": "again"}))  # a second answer for the same slide
    out, warnings = compile_outline(o, st, brief)
    assert [s.spec_ref for s in out.slides[1:]] == [1, 2, 3, 4, 5]
    s4 = _by_spec(out)[4]
    assert s4.kind == K.chart and s4.content.chart.type == "line" and s4.content.chart2.type == "pie"
    assert s4.content.chart.series_ids == ["s5"] and s4.content.chart2.series_ids == ["s6"]
    assert s4.headline == "Вложения и прогноз роста" and "без модели" in s4.rationale
    assert all(not b.startswith(("Нужен", "Нужна", "Покажи")) for b in s4.content.bullets)
    assert any("had no designed slide" in w for w in warnings) and any("a second slide" in w for w in warnings)


def test_fallback_slide_of_a_cover_spec_is_the_title_slide():
    _, st, _ = _load("long")
    s = fallback_slide(st.specs[0], st)
    assert s.kind == K.title and s.headline == "Больше прибыли с каждой чашки" and s.spec_ref == 1
    s3 = fallback_slide(st.specs[2], st)
    assert s3.kind == K.chart and s3.content.chart.series_ids == ["s1"] and s3.footnote


# ------------------------------------------------------------------ grounding with the structure


def test_the_title_line_of_the_brief_is_its_title():
    brief, _, _ = _load("long")
    assert title_line(brief.text) == "Больше прибыли с каждой чашки"
    assert BriefIndex.of(brief).title == "Больше прибыли с каждой чашки"
    o = DeckOutline(title="Больше прибыли с каждой чашки", planned_by="model", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Больше прибыли с каждой чашки"),
        OutlineSlide(id="a", kind=K.bullets, headline="Как работает кофейня сейчас", content=SlideContent(bullets=["100 покупок в день", "Средний чек — 300 рублей"])),
    ])
    g, warnings = ground_outline(o, brief)
    assert g.title == "Больше прибыли с каждой чашки" and not any("deck title" in w for w in warnings)


def _money_chart_deck(values: list[float], spec_ref=9) -> DeckOutline:
    ch = ChartSpec(type="column", categories=["Сейчас", "Цель"], series=[InlineSeries(name="Месячная выручка", values=values)], unit="тыс. ₽")
    return DeckOutline(title="Больше прибыли с каждой чашки", planned_by="agent", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Больше прибыли с каждой чашки"),
        OutlineSlide(id="r", kind=K.chart, headline="Выручка вырастет на 26,5%", content=SlideContent(chart=ch), spec_ref=spec_ref),
    ])


def test_chart_values_may_be_rounded_only_as_the_brief_allows():
    brief, st, _ = _load("long")
    idx = BriefIndex.of(brief)
    assert rounding_step(st.rounding) == 1000.0 and rounding_step(None) is None
    assert value_ok(idx, 1138.5, 1000.0) and value_ok(idx, 1139, 1000.0, 1000.0) and value_ok(idx, 1138, 1000.0, 1000.0)
    assert not value_ok(idx, 1139, 1000.0) and not value_ok(idx, 1140, 1000.0, 1000.0) and not value_ok(idx, 376, 1000.0)
    assert value_ok(idx, 376, 1000.0, 1000.0)  # 375 705 to thousands
    kept, _ = ground_outline(_money_chart_deck([900, 1139]), brief, structure=st)
    assert kept.slides[1].content.chart is not None and kept.slides[1].content.chart.series[0].values == [900, 1139]
    no_rule = st.model_copy(update={"rounding": None})
    gone, warnings = ground_outline(_money_chart_deck([900, 1139]), brief, structure=no_rule)
    assert gone.slides[1].content.chart is None and any("chart data not in the brief" in w for w in warnings)


def test_a_slide_the_user_asked_for_is_never_dropped_for_its_words():
    brief, st, _ = _load("long")
    def deck(spec_ref):
        return DeckOutline(title="Больше прибыли с каждой чашки", planned_by="agent", slides=[
            OutlineSlide(id="t", kind=K.title, headline="Больше прибыли с каждой чашки"),
            OutlineSlide(id="x", kind=K.bullets, headline="Гостям нужен повод зайти днем", spec_ref=spec_ref,
                         content=SlideContent(bullets=["Уютная атмосфера привлекает соседей", "Тихая музыка помогает работать с ноутбуком"]),
                         takeaway="Днем зал ждет новых гостей"),
        ])
    kept, _ = ground_outline(deck(6), brief, structure=st)
    assert [s.id for s in kept.slides] == ["t", "x"] and len(kept.slides[1].content.bullets) == 2
    assert kept.slides[1].takeaway == "Днем зал ждет новых гостей"
    dropped, _ = ground_outline(deck(None), brief, structure=st)
    assert [s.id for s in dropped.slides] == ["t"]  # the same slide nobody asked for is the model's invention


def test_a_formula_with_an_invented_operand_goes_whole():
    brief, st, _ = _load("long")
    o = DeckOutline(title="Больше прибыли с каждой чашки", planned_by="agent", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Больше прибыли с каждой чашки"),
        OutlineSlide(id="f", kind=K.big_number, headline="Как работает кофейня сейчас", spec_ref=2, content=SlideContent(formula="100 × 310 × 30 = 930 000 рублей")),
    ])
    g, warnings = ground_outline(o, brief, structure=st)
    assert g.slides[1].content.formula is None and any("formula" in w for w in warnings)
    o.slides[1].content.formula = "100 покупок × 300 ₽ × 30 дней = 900 000 ₽"
    g, _ = ground_outline(o, brief, structure=st)
    assert g.slides[1].content.formula == "100 покупок × 300 ₽ × 30 дней = 900 000 ₽" and g.slides[1].kind == K.big_number


# ------------------------------------------------------------------ alternatives and the polish


def test_apply_alternative_uses_the_alternatives_content_or_converts_the_slides_own():
    _, st, o = _load("long")
    timeline = next(s for s in o.slides if s.id == "d8")
    as_chart = apply_alternative(timeline, timeline.alternatives[0])
    assert as_chart.kind == K.chart and as_chart.content.chart.type == "doughnut" and not as_chart.content.items
    as_cards = apply_alternative(timeline, SlideAlternative(kind="cards", change="шаги карточками"))
    assert as_cards.kind == K.cards and len(as_cards.content.items) == 6 and as_cards.rationale == "шаги карточками"
    listed = apply_alternative(timeline, {"kind": "bullets"})
    assert listed.kind == K.bullets and listed.content.bullets[0] == "1-й месяц — Учет показателей и обновление меню"
    assert apply_alternative(timeline, {"kind": "stat_row"}) is None  # nothing to show as figures
    assert apply_alternative(timeline, {"kind": "freeform"}) is None and apply_alternative(timeline, {"kind": "timeline"}) is None
    costs = next(s for s in o.slides if s.id == "d3")
    asked = st.specs[2]  # «Покажи структуру расходов на диаграмме»
    table = SlideAlternative(kind="table", content=SlideContent(table={"columns": ["Статья", "Сумма"], "rows": [["Аренда", "120 000 рублей"]]}))
    assert apply_alternative(costs, table) is not None and apply_alternative(costs, table, asked) is None


def test_polish_does_not_undo_the_compiler(short_deck):
    _, _, out, _ = short_deck
    o = out.model_copy(deep=True)
    o.slides.insert(1, OutlineSlide(id="sec", kind=K.section, headline="Как работает кофейня сейчас", spec_ref=None))
    o.slides[2].content.bullets = ["100 покупок в день"]
    o.slides[2].kind = K.bullets
    o.slides[2].content.chart = None
    o.slides[2].content.formula = "100 × 300 × 30 = 900 000 рублей"
    p = polish_plan(o)
    assert any(s.kind == K.section for s in p.slides)  # a deck of the user's slides keeps its dividers
    assert p.slides[2].kind == K.bullets and p.slides[2].content.formula and not p.slides[2].content.numbers


def test_a_full_count_leaves_no_room_for_a_cover_and_the_disclaimer_goes_on_the_first_slide():
    brief, st, o = _load("short")
    st = st.model_copy(update={"slide_count": 5})  # «на 5 слайдов», the user's five are content slides
    out, _ = compile_outline(o, st, brief)
    assert [s.spec_ref for s in out.slides] == [1, 2, 3, 4, 5]
    assert out.slides[0].footnote == "Все цифры условные."


def test_a_deck_the_architect_planned_gets_a_cover_and_compiled_charts():
    brief, st, _ = _load("short")
    st = st.model_copy(update={"specs": []})
    ch = ChartSpec(type="pie", categories=["Кофе", "Десерты и выпечка", "Чай и другие напитки"], series=[InlineSeries(name="Выручка", values=[60, 25, 15])], unit="%")
    o = DeckOutline(title="Кофейня «Точка кофе»: план увеличения прибыли за 6 месяцев", planned_by="agent", strategy="compact", slides=[
        OutlineSlide(id="a", kind=K.chart, headline="Кофе приносит 60% выручки", content=SlideContent(chart=ch)),
        OutlineSlide(id="b", kind=K.bullets, headline="Рекомендации по действию", content=SlideContent(bullets=["Нанять бариста мирового уровня", "Открыть вторую точку в центре"])),
    ])
    out, warnings = compile_outline(o, st, brief)
    assert [s.kind for s in out.slides] == [K.title, K.chart]  # the invented slide nobody asked for goes, as before
    assert out.slides[0].footnote == "Все цифры условные."
    assert out.slides[1].content.chart.series_ids == ["s_a_1"]


def test_a_chart_that_counts_items_as_one_each_is_no_data_and_the_slide_keeps_its_items():
    # «кольцевые диаграммы» in a card's text reads as a chart request; the designer drew the three cards as a doughnut
    # of 1, 1, 1 («одна мысль на слайд» grounds the 1): that is no data, so no chart
    from verstka.planning.brief_structure import read_structure
    from verstka.schemas.outline import SlideItem, TableData

    text = ("Слайд 1. Три варианта вёрстки\n\nОдинаковое содержание, разная подача. Нужны три карточки: «Структурный» — "
            "одна мысль на слайд; «Визуальный» — крупные цифры и кольцевые диаграммы; «Компактный» — вывод первой строкой.")
    items = [SlideItem(title="Структурный", text="Одна мысль на слайд"), SlideItem(title="Визуальный", text="Крупные цифры"),
             SlideItem(title="Компактный", text="Вывод первой строкой")]
    ch = ChartSpec(type="doughnut", categories=["Вывод", "Текст", "Данные"], series=[InlineSeries(name="Распределение", values=[1, 1, 1])])
    o = DeckOutline(title="Три варианта вёрстки", planned_by="agent", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Три варианта вёрстки"),
        OutlineSlide(id="v", kind=K.chart, headline="Одинаковое содержание, разная подача", spec_ref=1,
                     content=SlideContent(items=items, chart=ch, table=TableData(columns=["Вариант", "Подача"], rows=[[x.title, x.text] for x in items]))),
    ])
    out, warnings = compile_outline(o, read_structure(text), Brief(text=text))
    v = next(s for s in out.slides if s.id == "v")
    assert v.content.chart is None and v.kind in (K.table, K.cards)
    assert not any(all(x == 1 for x in ser.values) for ser in out.series)
    assert any("a count of items, not data" in w for w in warnings)
