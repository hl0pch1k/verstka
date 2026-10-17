"""QA6: ложные срабатывания аудита содержания — заголовки таблицы, ставшей графиком, и процент изменения двух чисел
своей же строки («1 840 млн ₽ против 1 750 (+5%)»)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_audit_facts import _ctx, _deck  # noqa: E402
from test_review_audit import _el, _ir, _manifest  # noqa: E402

from verstka.audit.checks.facts import figure_not_in_brief  # noqa: E402
from verstka.audit.checks.integrity import content_missing  # noqa: E402
from verstka.audit.registry import AuditContext  # noqa: E402
from verstka.schemas.deck_ir import IRChart, IRChartSeries, IRSlide  # noqa: E402
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideContent, TableData  # noqa: E402


def test_the_heads_of_a_table_drawn_as_a_chart_are_not_lost_lines():
    table = TableData(columns=["Направление", "План, млн ₽", "Факт, млн ₽"], rows=[["Облако", "700", "760"], ["Почта", "500", "470"]])
    outline = DeckOutline(title="t", slides=[OutlineSlide(id="sl3", kind="table", headline="Облако перевыполнило план", content=SlideContent(table=table))])
    chart = _el("2", "", 0.1, 0.3, 0.8, 0.5, etype="chart")
    chart.chart = IRChart(type="column", categories=["Облако", "Почта"], series=[IRChartSeries(name="План", values=[700, 500]), IRChartSeries(name="Факт", values=[760, 470])])
    drawn = IRSlide(index=1, outline_id="sl3", elements=[_el("1", "Облако перевыполнило план", 0.1, 0.1, 0.8, 0.1, size=32), chart])
    assert content_missing(AuditContext(ir=_ir(drawn), manifest=_manifest(), outline=outline)) == []
    # as a table the heads are lines of it: lost heads are still reported
    lost = IRSlide(index=1, outline_id="sl3", elements=[_el("1", "Облако перевыполнило план", 0.1, 0.1, 0.8, 0.1, size=32)])
    assert content_missing(AuditContext(ir=_ir(lost), manifest=_manifest(), outline=outline))


def test_a_percent_of_two_figures_of_its_own_line_is_derived(tmp_path):
    ir = _deck(tmp_path, [["Расходы 780 000 ₽ против 900 000 ₽ выручки (−13%)", "Выручка 900 000 ₽ против 780 000 ₽ (+40%)"]])
    issues = figure_not_in_brief(_ctx(ir))
    assert len(issues) == 1 and "40" in issues[0].message and "13" not in issues[0].message


def test_the_closing_heading_is_the_inputs_ask_or_goal_never_the_plans_line():
    from verstka.data.answer import steps_head
    from verstka.planning.plan_data import _closing_head

    basis = "удержать темп роста в IV квартале за счёт партнёрского канала и регионов, где выручка растёт быстрее средней, — Казани и Краснодара"
    assert steps_head(basis) == "Удержать темп роста в IV квартале"
    assert _closing_head(["Удержать темп роста в IV квартале за счёт партнёрского канала"]) == "Удержать темп роста в IV квартале"
    assert _closing_head(["Просим утвердить перенос 85 млн ₽ в облачные сервисы"]) == "Просим утвердить перенос 85 млн ₽ в облачные сервисы"
    assert _closing_head(["Ничего"]) == "Что дальше"


def test_a_plan_and_data_deck_closes_on_the_inputs_own_words():
    from verstka.data.readers import read_file
    from verstka.data.story import build_data_story
    from verstka.planning.brief import parse_brief_text

    root = Path(__file__).resolve().parents[2]
    folder = root / "examples" / "data-sales-2026"
    tables = [t for p in sorted(folder.iterdir()) if p.suffix.lower() in {".csv", ".xlsx", ".json", ".txt"} for t in read_file(p)]
    plan = ("Закрытие 3 квартала — для финдиректора, примерный план:\n\n- итоги квартала: главные цифры\n- выручка по месяцам\n"
            "- регионы — кто тянет, кто отстаёт\n- каналы продаж\n- что делаем в 4 квартале и что просим у правления\n")
    last = build_data_story(parse_brief_text(plan), tables).outline.slides[-1]
    assert "что просим у правления" not in last.headline.lower()  # the slide asks nothing: the plan's line would promise it
    assert last.headline == "Удержать темп роста в IV квартале"
