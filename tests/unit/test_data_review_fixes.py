"""Регрессии по ревью Task 7 (.superpowers/sdd/s2/rev7-findings.md): справочник с одним упорядочением, лидер долей по
значению, цифры в подписях категорий, почасовые ряды, выбросы снизу, изменения индексов в пунктах, остатки и потоки,
2–3 варианта всегда, гистограмма не из одного интервала, id-колонка → справочник, мелкие формулировки и `NotBuilt`."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

from verstka.data.aggregate import Data
from verstka.data.goals import goals_of
from verstka.data.headline import headline_ok, numbers_in
from verstka.data.plan import NotBuilt, chart_spec_of, plan_dataset, slide_data_of
from verstka.data.profile import profile_table
from verstka.data.readers import read_file
from verstka.data.words import times_word
from verstka.schemas.data import DatasetPlan, Table
from verstka.schemas.outline import ChartSpec, NumberCallout, TableData

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "data-sales-2026"
NB = " "


def _t(columns: list[str], rows: list[list], units: Optional[list] = None, file: str = "данные.csv") -> Table:
    return Table(id="t1", file=file, kind="csv", columns=columns, units=units or [None] * len(columns), rows=rows,
                 raw_header=list(columns))


def _plan(t: Table, goal: str = "") -> DatasetPlan:
    p = plan_dataset(profile_table(t), t, goals_of(goal) if goal else None)
    assert 2 <= len(p.options) <= 3 or p.slides == 0, [o.kind for o in p.options]
    return p


def _facts(p: DatasetPlan) -> dict:
    return {f.id: f for f in p.headline_facts}


def _sp(s: str) -> str:
    return (s or "").replace(NB, " ")


# ── Critical #1: справочник — одно упорядочение ───────────────────────────────────────────────────────────────────────
def _ref_rows(metric_vals):
    return [[f"Клиент {i:03d}", ["ИТ", "Ритейл"][i % 2], ["Москва", "Казань", "Омск"][i % 3], v, "x"]
            for i, v in enumerate(metric_vals)]


def _check_ref_consistency(p: DatasetPlan, t: Table, metric: str):
    table = chart_spec_of(p, t, option=0)
    bar_k = next(k for k, o in enumerate(p.options) if o.kind == "bar")
    bar = chart_spec_of(p, t, option=bar_k)
    assert isinstance(table, TableData) and isinstance(bar, ChartSpec)
    src = {r[0]: r[3] for r in t.rows}
    # подписи и значения столбцов — из одних и тех же строк файла
    for lab, v in zip(bar.categories, bar.series[0].values):
        assert src[lab] == v, (lab, v)
    assert bar.series[0].values == sorted(bar.series[0].values, reverse=True)
    assert [r[0] for r in table.rows[:10]] == bar.categories
    assert table.rows[0][0] == max(src, key=lambda k: (src[k], -int(k[-3:])))


def test_reference_with_negative_metric_ranks_by_value_without_shares():
    vals = [(i * 37 % 100) - 30 for i in range(40)]
    t = _t(["Клиент", "Отрасль", "Регион", "Прибыль", "Тариф"], _ref_rows(vals), [None, None, None, "млн ₽", None])
    p = _plan(t)
    assert p.task.task == "reference"
    assert "дают" not in p.headline and "%" not in p.headline
    assert _sp(p.headline) == "Клиент 027 — первое место по прибыли: 69 млн ₽, 12 клиентов в минусе"
    assert "top_share" not in _facts(p) and headline_ok(p.headline, p.headline_facts, ["Клиент 027"])
    assert d_ref(t).top_share is None and "Доля, %" not in chart_spec_of(p, t).columns
    _check_ref_consistency(p, t, "Прибыль")


def test_reference_with_level_metric_ranks_by_value():
    rng = np.random.default_rng(3)
    vals = [round(float(x), 1) for x in rng.uniform(1, 5, 40)]
    t = _t(["Клиент", "Отрасль", "Регион", "Рейтинг", "Тариф"], _ref_rows(vals))
    p = _plan(t)
    assert p.options[0].title == "Таблица топ-10 по рейтингу"
    _check_ref_consistency(p, t, "Рейтинг")


def d_ref(t: Table):
    return Data(t, profile_table(t)).ref


def test_groups_option_counts_rows_by_group():
    rows = [[f"Сотрудник {i}", ["Продажи", "Маркетинг", "Юристы"][i % 3], ["Менеджер", "Аналитик"][i % 2]]
            for i in range(25)]
    t = _t(["Сотрудник", "Отдел", "Должность"], rows)
    p = _plan(t)
    k = next(k for k, o in enumerate(p.options) if o.title.startswith("Столбцы: число строк по группам"))
    spec = chart_spec_of(p, t, option=k)
    assert isinstance(spec, ChartSpec) and sorted(spec.categories) == ["Маркетинг", "Продажи", "Юристы"]
    assert sum(spec.series[0].values) == 25


# ── Important #2: лидер долей — по значению ───────────────────────────────────────────────────────────────────────────
def test_ordinal_shares_leader_by_value():
    t = _t(["Возраст", "Доля"], [["18–24", 15], ["25–34", 35], ["35–44", 30], ["45–54", 12], ["55+", 8]], [None, "%"])
    p = _plan(t)
    f = _facts(p)
    assert p.task.task == "shares"
    assert f["leader_share"].value == 35 and f["leader_share"].text.startswith("25–34")
    assert f["second_share"].value == 30 and f["top2_share"].value == 65
    spec = chart_spec_of(p, t)
    assert spec.categories[:2] == ["18–24", "25–34"] and spec.highlight_index == 1
    assert p.headline == "25–34 — крупнейшая доля: 35%"


def test_ordinal_comparison_highlights_the_max():
    t = _t(["Возраст", "Клиентов"], [["до 25", 150], ["25–34", 350], ["35–44", 300], ["45 и старше", 200]])
    p = _plan(t)
    assert p.headline == "25–34 даёт 35% клиентов"
    assert p.plain_headline == "Число клиентов по возрастам"
    assert chart_spec_of(p, t).highlight_index == 1


# ── Important #3: цифры в подписях категорий ──────────────────────────────────────────────────────────────────────────
def test_digits_in_labels_keep_the_conclusion():
    t = _t(["Филиал", "Выручка"], [["Филиал 1", 500], ["Филиал 2", 300], ["Филиал 3", 150], ["Филиал 4", 50]],
           [None, "млн ₽"])
    p = _plan(t)
    assert p.headline == "Филиал 1 даёт 50% выручки"
    # проверка перефразировки модели — строгая: без подписей цифра «1» не из фактов
    assert not headline_ok(p.headline, p.headline_facts)
    assert headline_ok(p.headline, p.headline_facts, ["Филиал 1"])
    # подпись вырезается целиком, а не внутри числа: «3» не съедает «30»
    assert numbers_in("3 — первое место: 30", ["3"]) == [30]


# ── Important #4: почасовые ряды ──────────────────────────────────────────────────────────────────────────────────────
def test_hourly_series_is_not_year_over_year():
    t0 = datetime(2026, 1, 1)
    t = _t(["Время", "Запросов"], [[(t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"), 100 + i] for i in range(30)])
    p = _plan(t)
    assert "за год" not in p.headline and "год к году" not in _facts(p)["change"].text
    spec = chart_spec_of(p, t)
    assert len(spec.categories) == 30 and not spec.gaps  # полночь — час 00:00, а не пропуск
    assert p.headline == "Число запросов выросло на 29% за 29 часов"


def test_hourly_data_over_days_resampled_to_days():
    t0 = datetime(2026, 3, 2)
    rows = [[(t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M"), 10] for i in range(24 * 5)]
    t = _t(["Время", "Запросов"], rows)
    p = _plan(t)
    spec = chart_spec_of(p, t)
    assert spec.categories == ["2 мар 2026", "3 мар 2026", "4 мар 2026", "5 мар 2026", "6 мар 2026"]
    assert spec.series[0].values == [240.0] * 5  # все 24 часа каждого дня, сумма
    assert p.options[0].aggregation.startswith("по дням: 120 часов → 5 дней, сумма")
    assert "за год" not in p.headline and p.headline == "Число запросов держится на уровне 240"


# ── Important #5: выбросы снизу ───────────────────────────────────────────────────────────────────────────────────────
def test_low_outliers_are_worded_as_less():
    rng = np.random.default_rng(5)
    vals = [int(x) for x in rng.normal(100, 8, 200)] + [2, 3, 1]
    t = _t(["Заказ", "Минут доставки"], [[f"Z-{1000 + i}", v] for i, v in enumerate(vals)])
    p = _plan(t)
    f = _facts(p)
    assert "outlier_bound_low" in f and "outlier_bound_high" not in f
    assert f["outlier_bound_low"].value <= min(v for v in vals if v > 10)
    assert "меньше" in p.caption and "больше" not in p.caption
    assert "3 заказа — меньше 80 минут" in p.caption


# ── Important #6: изменения индексов и долей — в пунктах ──────────────────────────────────────────────────────────────
def test_kpi_index_and_percent_changes_in_points():
    wide = [["Выручка", "1,24 млрд ₽", "1,01 млрд ₽"], ["Конверсия", "2,6%", "2,1%"], ["NPS", "52", "46"]]
    t = _t(["Показатель", "III кв. 2026", "III кв. 2025"], wide, file="Итоги.txt")
    p = _plan(t)
    cards = chart_spec_of(p, t)
    labels = [c.label for c in cards]
    assert labels[1] == f"Конверсия, +0,5{NB}п.п. к III кв. 2025" and labels[2] == f"NPS, +6{NB}п. к III кв. 2025"
    assert p.headline == "Выручка выросла на 23%"  # проценты не сравниваются с пунктами


def test_real_quarter_results_nps_in_points():
    t = read_file(EXAMPLES / "Итоги квартала.txt")[0]  # текущее чтение
    p = _plan(t)
    cards = chart_spec_of(p, t)
    assert cards[-1].label.startswith(f"NPS, +6{NB}п.")


def test_melted_quarter_results_nps_in_points_with_and_without_change_column():
    base = [("Выручка", "1,01 млрд ₽", "1,24 млрд ₽", "+23%"), ("Клиенты", "2 949", "3 480", "+18%"),
            ("Средний чек", "342 тыс. ₽", "356 тыс. ₽", "+4%"), ("NPS", "46", "52", "+6 п.")]
    with_change = [[lab, ch, per, v] for lab, a, b, ch in base for per, v in (("2025-Q3", a), ("2026-Q3", b))]
    without = [[lab, per, v] for lab, a, b, _ in base for per, v in (("2025-Q3", a), ("2026-Q3", b))]
    for cols, rows in ((["Показатель", "Изменение", "Квартал", "Значение"], with_change),
                       (["Показатель", "Квартал", "Значение"], without)):
        t = _t(cols, rows, file="Итоги квартала.txt")
        p = _plan(t)
        assert p.task.task == "kpi", cols
        cards = chart_spec_of(p, t)
        nps = next(c for c in cards if c.label.startswith("NPS"))
        assert nps.label.startswith(f"NPS, +6{NB}п."), (cols, nps.label)
        assert p.headline == "Выручка растёт быстрее числа клиентов: +23% против +18%"


# ── Important #7: деньги — не остаток ─────────────────────────────────────────────────────────────────────────────────
def test_money_named_after_clients_is_a_flow():
    d0 = date(2025, 1, 1)
    t = _t(["Дата", "Выручка от клиентов"], [[(d0 + timedelta(days=i)).isoformat(), 10] for i in range(400)],
           [None, "млн ₽"])
    d = Data(t, profile_table(t))
    assert not d.main.stock and d.main.how == "sum"
    p = _plan(t)
    spec = chart_spec_of(p, t)
    assert spec.series[0].values[0] == 310  # январь — сумма 31 дня, а не последнее значение
    assert "сумма" in p.options[0].aggregation


def test_stock_needs_the_counted_noun_to_head_the_name():
    rows = [[f"2025-{m:02d}", 1000 + m, 50 + m, 10 + m] for m in range(1, 13)]
    t = _t(["Месяц", "Клиентов", "Активные клиенты", "Выручка от клиентов"], rows, [None, None, None, "млн ₽"])
    d = Data(t, profile_table(t))
    assert d.measure("Клиентов").stock and d.measure("Активные клиенты").stock
    assert not d.measure("Выручка от клиентов").stock


# ── спецификация: 2–3 варианта, гистограмма ≥ 5 интервалов, id-колонка ───────────────────────────────────────────────
def test_small_tables_always_get_two_or_three_options():
    cases = [
        _t(["Сотрудник", "Комментарий"], [["Иванов", "в отпуске до пятницы"], ["Петрова", "ведёт проект Альфа"],
                                         ["Сидоров", "на больничном"], ["Орлова", "новый сотрудник"]]),
        _t(["Сумма"], [[10], [20], [30]]),
        _t(["Выручка"], [[1240]], ["млн ₽"]),
    ]
    for t in cases:
        p = _plan(t)
        assert 2 <= len(p.options) <= 3, [o.kind for o in p.options]
        first = chart_spec_of(p, t, option=0)
        assert first is not None and not isinstance(first, NotBuilt)
        for k, o in enumerate(p.options[1:], start=1):
            assert o.why_not
            body = chart_spec_of(p, t, option=k)
            assert body is not None
            if isinstance(body, NotBuilt):
                assert body.reason == o.why_not


def test_constant_column_is_not_a_histogram():
    t = _t(["Минут до ответа"], [[30] for _ in range(50)])
    p = _plan(t)
    assert p.options[0].kind == "kpi_cards"
    k = next(k for k, o in enumerate(p.options) if o.kind == "histogram")
    body = chart_spec_of(p, t, option=k)
    assert isinstance(body, NotBuilt) and "не различаются" in body.reason
    assert p.headline == "Все значения — 30 минут"


def test_id_column_makes_a_reference():
    rows = [[f"ART-{100 + i}", f"Товар {chr(1040 + i)}", 100 + i * 7] for i in range(20)]
    t = _t(["Артикул", "Название", "Цена"], rows, [None, None, "₽"])
    p = _plan(t)
    assert p.task.task == "reference" and p.task.scores["reference"] >= 0.7


# ── мелкие ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_rest_row_plural():
    for n, word in ((33, "клиента"), (31, "клиент"), (35, "клиентов")):
        t = _t(["Клиент", "Отрасль", "Регион", "Выручка", "Тариф"], _ref_rows([100 - i for i in range(n)]),
               [None, None, None, "млн ₽", None])
        assert chart_spec_of(_plan(t), t).rows[-1][0] == f"Остальные {n - 10} {word}"


def test_times_word_and_spread_fact():
    assert [times_word(x) for x in (2, 5, 13, 21, 2.5, 10)] == ["раза", "раз", "раз", "раз", "раза", "раз"]
    t = _t(["Город", "Выручка"], [["Москва", 1300], ["Казань", 400], ["Омск", 100]], [None, "млн ₽"])
    assert _facts(_plan(t))["spread"].text == "Разрыв — в 13 раз"


def test_small_wordings():
    # «От января», а не «От январь»
    t = _t(["Месяц", "Выручка"], [[f"2025-{m:02d}", 100 + m] for m in range(1, 8)], [None, "млн ₽"])
    assert _facts(_plan(t))["span"].explain == "От января 2025 до июля 2025."
    # равные значения — «держится на уровне»
    t = _t(["Месяц", "Выручка"], [[f"2025-{m:02d}", 310] for m in range(1, 8)], [None, "млн ₽"])
    p = _plan(t)
    assert "держится на уровне 310" in _sp(p.caption) and "с 310" not in _sp(p.caption)
    # группы — «2 значения»
    rows = [[f"Сотрудник {i}", ["Продажи", "Маркетинг"][i % 2], ["Менеджер", "Аналитик", "Юрист"][i % 3]]
            for i in range(25)]
    t = _t(["Сотрудник", "Отдел", "Должность"], rows)
    assert _facts(_plan(t))["groups"].text == "«Отдел»: 2 значения"
    # объяснение доли топ-10 — своей метрикой
    t = _t(["Клиент", "Отрасль", "Регион", "Доход", "Тариф"], _ref_rows([100 - i for i in range(40)]),
           [None, None, None, "млн ₽", None])
    assert _facts(_plan(t))["top_share"].explain.startswith("Доход 10 крупнейших из 40")


def test_no_entity_no_predicate():
    rng = np.random.default_rng(2)
    t = _t(["Минут до ответа"], [[int(x)] for x in rng.exponential(40, 100)])
    p = _plan(t)
    assert "получают ответ" not in p.headline and "значений — не дольше" in p.headline


def test_infeasible_option_returns_reason():
    t = read_file(EXAMPLES / "Регионы.xlsx")[0]
    p = _plan(t)
    k = next(k for k, o in enumerate(p.options) if o.kind == "pie")
    body = chart_spec_of(p, t, option=k)
    assert isinstance(body, NotBuilt) and body.reason == "8 долей — мелкие сектора нечитаемы."


def test_many_shares_collapse_once():
    t = _t(["Канал", "Выручка"], [[f"Канал {chr(1040 + i)}", 100 - i * 5] for i in range(15)], [None, "млн ₽"])
    p = _plan(t, "покажи доли каналов")
    assert p.task.task == "shares" and p.options[0].kind == "doughnut"
    spec = chart_spec_of(p, t)
    assert len(spec.categories) == 6 and spec.categories[-1] == "Остальные 10"
    assert abs(sum(spec.series[0].values) - 100) < 0.5 and spec.highlight_index == 0


def test_axis_titles_on_kpi_columns_and_stacked_shares():
    t = _t(["Показатель", "Значение"], [["Выручка", 100], ["Расходы", 60], ["Прибыль", 40]], [None, "млн ₽"])
    p = _plan(t)
    assert p.task.task == "kpi"
    k = next(k for k, o in enumerate(p.options) if o.kind == "column")
    spec = chart_spec_of(p, t, option=k)
    assert spec.x_title == "Показатель" and spec.y_title == "Значение"
    t = read_file(EXAMPLES / "Каналы продаж.json")[0]
    p = _plan(t)
    k = next(k for k, o in enumerate(p.options) if o.kind == "stacked_column")
    spec = chart_spec_of(p, t, option=k)
    assert spec.x_title == "Канал" and spec.y_title == "Доля"


def test_part_is_an_int_everywhere():
    rows = [[f"Сотрудник {i}", ["Продажи", "Маркетинг"][i % 2], ["Менеджер", "Аналитик", "Юрист"][i % 3]]
            for i in range(25)]
    t = _t(["Сотрудник", "Отдел", "Должность"], rows)
    p = _plan(t)
    assert p.slides == 3
    assert slide_data_of(p, 2).part == (2, 3) and slide_data_of(p).part == (1, 3)
    assert len(chart_spec_of(p, t, part=2).rows) == 10


def test_cards_use_numbers_callouts():
    t = _t(["Сумма"], [[10], [20], [30]])
    p = _plan(t)
    k = next(k for k, o in enumerate(p.options) if o.kind == "kpi_cards")
    cards = chart_spec_of(p, t, option=k)
    assert all(isinstance(c, NumberCallout) for c in cards) and cards[0].value == "60"
