"""План датасета (verstka/data/plan.py, описание решения §2.3–2.6) на семи файлах примера `examples/data-sales-2026`:
настоящее чтение → профиль → задача, ранжирование вариантов и заголовок-вывод — как в SCENARIO.md (числа совпадают,
формулировка может немного отличаться). Плюс инвариантность к формату файла, влияние цели, данные слайда
(`chart_spec_of`), «Почему так» (`slide_data_of`), детерминизм и скорость."""

from __future__ import annotations

import csv
import inspect
import json
import time
from pathlib import Path

import pytest

from verstka.data.goals import goals_of
from verstka.data.headline import headline_ok, numbers_in
from verstka.data.plan import chart_spec_of, plan_dataset, plan_datasets, slide_data_of
from verstka.data.profile import profile_table
from verstka.data.readers import read_file
from verstka.schemas.data import DatasetPlan, Table
from verstka.schemas.outline import ChartSpec, NumberCallout, TableData

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "data-sales-2026"
BRIEF = ("Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, что даёт "
         "выручку и где узкие места. Данные — в приложенных файлах.")
FILES = ["Выручка по месяцам.csv", "Регионы.xlsx", "Каналы продаж.json", "Время ответа поддержки.csv", "Клиенты.xlsx",
         "NPS по кварталам.csv", "Итоги квартала.txt"]


@pytest.fixture(scope="module")
def tables() -> dict[str, Table]:
    return {name: read_file(EXAMPLES / name)[0] for name in FILES}


@pytest.fixture(scope="module")
def plans(tables) -> dict[str, DatasetPlan]:
    ps = plan_datasets([tables[n] for n in FILES], BRIEF)
    return {n: p for n, p in zip(FILES, ps)}


def _kinds(p: DatasetPlan) -> list[str]:
    return [o.kind for o in p.options]


def _nums(text: str) -> set[float]:
    return set(numbers_in(text))


def _sp(s: str) -> str:
    """Неразрывные пробелы (между разрядами и перед единицей) — обычными, для сравнения с ожидаемым текстом."""
    return (s or "").replace("\u00a0", " ")


# ── семь файлов: задача, ранжирование, заголовок ──────────────────────────────────────────────────────────────────────
def test_revenue_by_month_dynamics_line(plans):
    p = plans["Выручка по месяцам.csv"]
    assert p.task.task == "dynamics"
    assert _kinds(p) == ["line", "column", "table"]
    assert p.task.goal == "покажи рост выручки"
    line = p.options[0]
    assert "21 точка" in line.reasons[0] and "тренд виден сразу" in line.reasons[0]
    assert any("покажи рост выручки" in r for r in line.reasons)
    assert "21 столбцом" in p.options[1].why_not and "21 строка" in p.options[2].why_not
    assert p.headline == "Выручка выросла на 23% к сентябрю"
    assert p.plain_headline == "Выручка по месяцам"
    ch = next(f for f in p.headline_facts if f.id == "change")
    assert ch.value == 23 and ch.unit == "%" and "Сентябрь 2026 к сентябрю 2025: 423 млн ₽" in _sp(ch.explain)


def test_regions_comparison_ranked_bars(plans):
    p = plans["Регионы.xlsx"]
    assert p.task.task == "comparison"
    assert _kinds(p) == ["bar", "column", "pie"]
    assert p.options[0].title == "Ранжированные горизонтальные столбцы"
    assert "длинными названиями" in p.options[0].reasons[0] and "по выручке" in p.options[0].reasons[0]
    assert "сравни регионы" in " ".join(p.options[0].reasons)
    assert p.options[1].why_not == "Названия регионов не помещаются под столбцами."
    assert p.options[2].why_not == "8 долей — мелкие сектора нечитаемы."
    assert p.headline == "Москва даёт 41% выручки, Казань растёт быстрее всех"
    assert {f.id: f.value for f in p.headline_facts}["growth_max"] == 38


def test_channels_shares_doughnut(plans):
    p = plans["Каналы продаж.json"]
    assert p.task.task == "shares"
    assert _kinds(p) == ["doughnut", "stacked_column", "column"]
    assert "4 доли в сумме дают 100%" in p.options[0].reasons[0]
    assert p.options[1].why_not == "Те же доли, но отрезки сравнивать труднее."
    assert p.options[2].why_not == "Не видно, что вместе это 100%."
    assert "Прямые продажи" in p.headline and "почти половину выручки" in p.headline and _nums(p.headline) == {46}


def test_support_time_distribution_histogram(plans):
    p = plans["Время ответа поддержки.csv"]
    assert p.task.task == "distribution"
    assert _kinds(p) == ["histogram", "kpi_cards", "table"]
    assert "512 значений" in p.options[0].reasons[0] and "3 выброса" in " ".join(p.options[0].reasons)
    assert p.options[2].why_not == "512 строк не показать."
    assert p.headline.startswith("80% обращений") and p.headline.endswith("за 2 часа")
    facts = {f.id: f for f in p.headline_facts}
    assert facts["share_within"].value == 80 and "410 из 512" in facts["share_within"].explain
    assert facts["outliers"].value == 3 and facts["outlier_bound_high"].value == 600
    assert "outlier_bound_low" not in facts
    assert "3 обращения" in p.caption and "выброс" in p.caption


def test_clients_reference_top10_table(plans, tables):
    p = plans["Клиенты.xlsx"]
    assert p.task.task == "reference"
    assert _kinds(p) == ["table", "bar", "table"]
    assert p.options[0].title == "Таблица топ-10 и итог «остальные 230»"
    assert "2 167 млн ₽ и 62%" in p.options[0].reasons[0]
    assert p.options[2].title == "Разбиение на 24 слайда" and "слишком много" in p.options[2].why_not
    assert p.headline == "Топ-10 клиентов дают 38% выручки"
    assert p.plain_headline == "Список клиентов"
    # топ-10 в справочнике — не выбросы
    assert not any(f.kind == "outliers" for f in p.headline_facts)
    assert slide_data_of(p).outliers == []
    t = chart_spec_of(p, tables["Клиенты.xlsx"])
    assert isinstance(t, TableData)
    assert t.columns == ["Клиент", "Отрасль", "Регион", "Выручка, млн ₽", "Доля, %"]
    assert len(t.rows) == 11 and t.rows[-1][0] == "Остальные 230 клиентов" and t.rows[0][3] == "212,4"


def test_nps_with_gaps_line_with_breaks(plans, tables):
    p = plans["NPS по кварталам.csv"]
    assert p.task.task == "dynamics"
    assert _kinds(p) == ["line", "column", "table"]
    assert [o.title for o in p.options] == ["Линейный график с разрывами", "Столбцы с пустыми местами",
                                            "Таблица с прочерками"]
    assert "разрывы линии" in " ".join(p.options[0].reasons)
    assert p.headline == "NPS вырос до 52, за два квартала данных нет"
    spec = chart_spec_of(p, tables["NPS по кварталам.csv"])
    assert isinstance(spec, ChartSpec) and spec.gaps
    assert spec.series[0].values == [41, 43, None, 46, 47, 49, None, 52]


def test_quarter_results_text_kpi_cards(plans, tables):
    p = plans["Итоги квартала.txt"]
    assert p.task.task == "kpi"
    assert _kinds(p) == ["kpi_cards", "table", "column"]
    assert p.options[2].why_not == "Разные единицы — сравнивать нельзя."
    assert p.headline.startswith("Выручка растёт быстрее") and _nums(p.headline) == {23, 18}
    cards = chart_spec_of(p, tables["Итоги квартала.txt"])
    assert isinstance(cards, list) and all(isinstance(c, NumberCallout) for c in cards)
    assert [c.value for c in cards] == ["1,24 млрд ₽", "3 480", "356 тыс. ₽", "52"]
    assert "+23%" in cards[0].label and "+6 п." in cards[3].label


def test_every_headline_number_is_a_fact(plans):
    for p in plans.values():
        assert p.headline and headline_ok(p.headline, p.headline_facts), p.headline
        assert p.headline != p.plain_headline
        assert p.source == f"Источник: {p.profile.file}"
        assert 2 <= len(p.options) <= 3 and p.options[0].why_not is None
        assert all(o.why_not for o in p.options[1:])
        assert p.options[0].score >= max(o.score for o in p.options)


def test_chart_specs_for_chosen_options(plans, tables):
    for name, p in plans.items():
        body = chart_spec_of(p, tables[name])
        if p.chosen_option.kind == "kpi_cards":
            assert isinstance(body, list)
        elif p.chosen_option.kind == "table":
            assert isinstance(body, TableData) and len(body.rows) <= 11
        else:
            assert isinstance(body, ChartSpec) and body.type == p.chosen_option.kind
            assert body.source == p.source and body.x_title
    rev = chart_spec_of(plans["Выручка по месяцам.csv"], tables["Выручка по месяцам.csv"])
    assert rev.categories[0] == "янв 2025" and len(rev.categories) == 21 and rev.unit == "млн ₽"
    assert rev.y_title == "Выручка" and rev.x_title == "Месяц" and rev.highlight_index == 20
    hist = chart_spec_of(plans["Время ответа поддержки.csv"], tables["Время ответа поддержки.csv"])
    assert hist.type == "histogram" and 7 <= len(hist.categories) <= 12 and hist.categories[-1] == "больше 180"
    assert sum(hist.series[0].values) == 509  # без трёх выбросов


def test_other_options_rebuild_the_slide(plans, tables):
    """«Пересобрать слайд так»: любой из вариантов даёт данные слайда."""
    for name, p in plans.items():
        for k in range(len(p.options)):
            body = chart_spec_of(p, tables[name], option=k)
            assert body is not None, (name, k)
            if isinstance(body, TableData):
                assert len(body.rows) <= 11


def test_slide_data_for_why(plans):
    sd = slide_data_of(plans["Выручка по месяцам.csv"])
    assert sd.profile_line == "CSV · 21 строка × 3 колонки · временной ряд"
    assert sd.task.task == "dynamics" and sd.options[0].kind == "line" and sd.headline_facts
    assert sd.plain_headline == "Выручка по месяцам" and sd.nature_label == "Временной ряд"


# ── инвариантность: формат файла и шаблон не влияют ───────────────────────────────────────────────────────────────────
def _write_variants(t: Table, tmp: Path, stem: str) -> list[Path]:
    header = t.raw_header or t.columns
    rows = [["" if v is None else v for v in r] for r in t.rows]
    out = []
    p_csv = tmp / f"{stem}.csv"
    with p_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)
    out.append(p_csv)
    p_json = tmp / f"{stem}.json"
    p_json.write_text(json.dumps([dict(zip(header, r)) for r in t.rows], ensure_ascii=False), encoding="utf-8")
    out.append(p_json)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    p_x = tmp / f"{stem}.xlsx"
    wb.save(p_x)
    out.append(p_x)
    return out


@pytest.mark.parametrize("name", ["Выручка по месяцам.csv", "Регионы.xlsx", "Каналы продаж.json",
                                  "NPS по кварталам.csv", "Время ответа поддержки.csv"])
def test_same_data_in_csv_xlsx_json_gives_same_choice(name, tables, tmp_path):
    t = tables[name]
    base = plan_dataset(profile_table(t), t)
    for path in _write_variants(t, tmp_path, "данные"):
        t2 = read_file(path)[0]
        p2 = plan_dataset(profile_table(t2), t2)
        assert p2.task.task == base.task.task, path.suffix
        assert [o.kind for o in p2.options] == [o.kind for o in base.options], path.suffix
        assert p2.headline == base.headline, path.suffix


def test_template_is_not_an_input():
    for fn in (plan_dataset, plan_datasets, chart_spec_of):
        params = set(inspect.signature(fn).parameters)
        assert not any("template" in x or "manifest" in x or "brand" in x for x in params)


# ── цели из текста ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_goals_go_to_their_datasets(plans):
    assert plans["Выручка по месяцам.csv"].task.goal == "покажи рост выручки"
    assert plans["Регионы.xlsx"].task.goal == "сравни регионы"
    assert plans["Каналы продаж.json"].task.goal == "что даёт выручку"
    for n in ("Клиенты.xlsx", "Время ответа поддержки.csv", "NPS по кварталам.csv", "Итоги квартала.txt"):
        assert plans[n].task.goal is None, n


def test_goal_structure_changes_regions_ranking(tables):
    t = tables["Регионы.xlsx"]
    prof = profile_table(t)
    plain = plan_dataset(prof, t)
    shaped = plan_dataset(prof, t, goals_of("Покажи структуру выручки по регионам."))
    assert plain.task.task == "comparison" and plain.options[0].kind == "bar"
    assert shaped.task.task == "shares" and shaped.options[0].kind == "doughnut"
    assert "подняла" in " ".join(shaped.options[0].reasons)
    assert any("подняла эту задачу" in r for r in shaped.task.reasons)
    assert headline_ok(shaped.headline, shaped.headline_facts)


def test_goal_compare_changes_channels_ranking(tables):
    t = tables["Каналы продаж.json"]
    prof = profile_table(t)
    assert plan_dataset(prof, t).options[0].kind == "doughnut"
    p = plan_dataset(prof, t, goals_of("Сравни каналы продаж между собой"))
    assert p.task.task == "comparison" and p.options[0].kind in ("bar", "column")


def test_goal_about_other_data_is_ignored(tables):
    t = tables["Время ответа поддержки.csv"]
    prof = profile_table(t)
    base = plan_dataset(prof, t)
    p = plan_dataset(prof, t, goals_of("Сравни регионы и покажи рост выручки"))
    assert p.task == base.task and [o.kind for o in p.options] == [o.kind for o in base.options]


def test_infeasible_goal_is_explained(tables):
    t = tables["Регионы.xlsx"]
    p = plan_dataset(profile_table(t), t, goals_of("Покажи динамику выручки по регионам"))
    assert p.task.task == "comparison"
    assert any("здесь не подходит" in r and "оси времени" in r for r in p.task.reasons)


# ── детерминизм и скорость ────────────────────────────────────────────────────────────────────────────────────────────
def test_deterministic(tables):
    a = plan_datasets([tables[n] for n in FILES], BRIEF)
    b = plan_datasets([tables[n] for n in FILES], BRIEF)
    assert [p.model_dump_json() for p in a] == [p.model_dump_json() for p in b]


def test_seven_files_planned_under_a_second(tables):
    """Только планирование (профили посчитаны заранее), лучшее из трёх: на этой машине ~0,02 с, запас — 50 раз."""
    ts = [tables[n] for n in FILES]
    profs = [profile_table(t) for t in ts]
    best = 9.0
    for _ in range(3):
        t0 = time.perf_counter()
        plan_datasets(ts, BRIEF, profiles=profs)
        best = min(best, time.perf_counter() - t0)
    assert best < 1.0, best
