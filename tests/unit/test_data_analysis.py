"""Задача, варианты, подготовка данных, факты и заголовок (verstka/data/task.py, viz.py, aggregate.py, facts.py,
headline.py) на таблицах, собранных вручную: крайние случаи (нетипизируемое, одна строка, два числа, 200+ строк,
пропуски, выбросы, отрицательные значения, проценты не в сумме 100), агрегация (топ + «Остальные», 7–12 интервалов,
ресэмплинг, строка «Итого»), длинный формат, взаимосвязь, влияние цели. Каждое число каждого заголовка — среди фактов."""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pytest

from verstka.data.aggregate import Data, histogram_bins
from verstka.data.goals import goals_of
from verstka.data.headline import headline_ok, numbers_in
from verstka.data.plan import chart_spec_of, plan_dataset, slide_data_of
from verstka.data.profile import profile_table
from verstka.data.task import task_scores
from verstka.schemas.data import DatasetPlan, Table
from verstka.schemas.outline import ChartSpec, NumberCallout, TableData


def _t(columns: list[str], rows: list[list], units: Optional[list] = None, file: str = "данные.csv",
       kind: str = "csv") -> Table:
    return Table(id="t1", file=file, kind=kind, columns=columns, units=units or [None] * len(columns), rows=rows,
                 raw_header=list(columns))


def _plan(t: Table, goal: str = "") -> DatasetPlan:
    p = plan_dataset(profile_table(t), t, goals_of(goal) if goal else None)
    assert headline_ok(p.headline, p.headline_facts), p.headline
    return p


def _kinds(p: DatasetPlan) -> list[str]:
    return [o.kind for o in p.options]


# ── нетипизируемое ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_text_only_is_skipped_with_message():
    t = _t(["Отзыв"], [["Очень понравилось обслуживание, всё быстро и вежливо, спасибо команде"],
                      ["Долго ждал ответа, но вопрос решили, хотя пришлось звонить дважды"],
                      ["Нормально в целом, без особых впечатлений, но цена кажется высокой"]])
    p = _plan(t)
    assert p.slides == 0 and p.options == [] and p.message == "Не для графика: одни текстовые колонки"
    assert chart_spec_of(p, t) is None


def test_untypable_but_meaningful_table_is_a_reference_table():
    t = _t(["Сотрудник", "Комментарий"], [["Иванов", "в отпуске до пятницы"], ["Петрова", "ведёт проект Альфа"],
                                         ["Сидоров", "на больничном"], ["Орлова", "новый сотрудник"]])
    p = _plan(t)
    assert p.task.task == "reference" and p.options[0].kind == "table"
    assert p.message.startswith("Не для графика") and "таблицей" in p.message
    body = chart_spec_of(p, t)
    assert isinstance(body, TableData) and len(body.rows) == 4


# ── одна строка, два числа ────────────────────────────────────────────────────────────────────────────────────────────
def test_single_row_of_numbers_is_kpi_cards():
    t = _t(["Выручка", "Клиенты", "NPS"], [[1240, 3480, 52]], units=["млн ₽", None, None])
    p = _plan(t)
    assert p.task.task == "kpi" and p.options[0].kind == "kpi_cards"
    cards = chart_spec_of(p, t)
    assert [c.value for c in cards] == ["1 240 млн ₽", "3 480", "52"]
    assert [c.label for c in cards] == ["Выручка", "Клиенты", "NPS"]
    assert 1240 in numbers_in(p.headline)


def test_two_numbers_in_one_row_and_two_periods():
    p = _plan(_t(["Выручка", "Клиенты"], [[1240, 3480]], units=["млн ₽", None]))
    assert p.options[0].kind == "kpi_cards" and len(p.options) >= 2
    t = _t(["Год", "Выручка"], [["2024", 100], ["2025", 123]], units=[None, "млн ₽"])
    p = _plan(t)
    assert p.task.task == "dynamics"
    assert p.options[0].kind == "column"  # две точки — линия не годится
    assert p.headline == "Выручка выросла на 23% за год"


# ── 200+ строк: ресэмплинг ────────────────────────────────────────────────────────────────────────────────────────────
def test_400_days_resampled_to_months_without_partial_month():
    random.seed(1)
    d0 = date(2025, 1, 1)
    t = _t(["Дата", "Заказов"], [[(d0 + timedelta(days=i)).isoformat(), 100 + i // 3 + random.randint(-10, 10)]
                                for i in range(400)])
    p = _plan(t)
    assert p.task.task == "dynamics" and p.options[0].kind == "line"
    agg = p.options[0].aggregation
    assert agg.startswith("по месяцам: 400 дней → 13 месяцев, сумма") and "неполный" in agg
    spec = chart_spec_of(p, t)
    assert len(spec.categories) == 13 <= 36 and spec.categories[0] == "янв 2025"
    # неполный февраль 2026 (4 дня) не превратился в «падение»
    assert "больше, чем в январе 2025" in p.headline and "Число заказов" in p.headline


def test_hourly_or_long_series_never_exceed_36_points():
    d0 = date(2020, 1, 1)
    t = _t(["Дата", "Выручка"], [[(d0 + timedelta(days=7 * i)).isoformat(), 50 + i] for i in range(300)],
           units=[None, "млн ₽"])
    p = _plan(t)
    spec = chart_spec_of(p, t)
    assert isinstance(spec, ChartSpec) and len(spec.categories) <= 36


# ── пропуски, выбросы, отрицательные, проценты не 100 ─────────────────────────────────────────────────────────────────
def test_gaps_are_none_not_zero_and_named_in_headline():
    t = _t(["Месяц", "Конверсия"], [["2025-01", 2.1], ["2025-02", 2.3], ["2025-03", None], ["2025-04", 2.6],
                                    ["2025-05", 2.8], ["2025-06", 3.0]], units=[None, "%"])
    p = _plan(t)
    spec = chart_spec_of(p, t)
    assert spec.gaps and spec.series[0].values[2] is None
    assert p.options[0].title == "Линейный график с разрывами"
    assert p.headline == "Конверсия выросла до 3%"  # один пропуск — в подписи, не в заголовке
    assert "данных нет" in p.caption


def test_outliers_counted_apart_from_bins():
    rng = np.random.default_rng(7)
    vals = [int(x) for x in rng.gamma(2.0, 20.0, 300)] + [900, 1200]
    t = _t(["Заказ", "Минут доставки"], [[f"Z-{1000 + i}", v] for i, v in enumerate(vals)])
    p = _plan(t)
    assert p.task.task == "distribution" and p.options[0].kind == "histogram"
    facts = {f.id: f for f in p.headline_facts}
    assert facts["outliers"].value == 2
    spec = chart_spec_of(p, t)
    # раунд 8 (A1): выбросы — в крайнем столбце «больше X», он считает все значения за X: всего на графике — 302
    assert 7 <= len(spec.categories) <= 12 and sum(spec.series[0].values) == 302
    assert spec.categories[-1].startswith("больше ")
    assert p.headline.startswith(f"{int(facts['share_within'].value)}% заказов ")


def test_negative_values_never_become_shares():
    t = _t(["Регион", "Прибыль"], [["Москва", 120], ["Казань", 40], ["Омск", -15], ["Тверь", 22], ["Пермь", -5],
                                   ["Самара", 30]], units=[None, "млн ₽"])
    p = _plan(t)
    assert task_scores(Data(t, profile_table(t)))["shares"] == 0
    assert p.task.task == "comparison" and p.options[0].kind in ("bar", "column")
    assert not any(o.kind in ("pie", "doughnut") and o is p.options[0] for o in p.options)
    assert "2 региона в минусе" in p.headline and "Москва впереди" in p.headline


def test_percentages_not_summing_to_100_are_compared_not_shared():
    t = _t(["Продукт", "Довольных клиентов"], [["Облако", 80], ["Почта", 75], ["Диск", 90], ["Видео", 64]],
           units=[None, "%"])
    p = _plan(t)
    assert p.task.task == "comparison"
    assert all(o.kind not in ("pie", "doughnut") for o in p.options)
    assert p.headline == "Диск впереди: 90%, Видео — 64%"
    assert "по доле довольных клиентов" in " ".join(r for o in p.options for r in o.reasons)


# ── агрегация ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_many_categories_top_and_rest():
    t = _t(["Город", "Заказов"], [[f"Город {chr(1040 + i)}", 1000 - i * 50] for i in range(15)])
    p = _plan(t)
    spec = chart_spec_of(p, t)
    assert len(spec.categories) == 12 and spec.categories[-1] == "Остальные 4"
    assert spec.series[0].values[-1] == 1500
    assert p.options[0].aggregation == "топ-11 и «Остальные 4»"


@pytest.mark.parametrize("seed,kind", [(1, "normal"), (2, "exp"), (3, "uniform"), (4, "lognormal")])
def test_histogram_has_7_to_12_bins(seed, kind):
    rng = np.random.default_rng(seed)
    x = {"normal": rng.normal(100, 15, 500), "exp": rng.exponential(30, 500), "uniform": rng.uniform(0, 1, 200),
         "lognormal": rng.lognormal(3, 0.6, 1000)}[kind]
    b = histogram_bins(np.round(x, 2))
    assert 7 <= b.n <= 12, (kind, b.labels)
    assert sum(b.counts) == len(x)


def test_histogram_bins_of_support_time_shape():
    rng = np.random.default_rng(3)
    x = np.round(rng.exponential(60, 512))
    b = histogram_bins(x, "мин")
    assert 7 <= b.n <= 12 and b.width in (5, 10, 15, 20, 30, 60)
    if b.open_from is not None:
        assert b.labels[-1] == f"больше {int(b.open_from)}"


def test_total_row_gives_shares_and_stays_off_the_chart():
    t = _t(["Канал", "Выручка"], [["Прямые", 50], ["Партнёры", 30], ["Онлайн", 20], ["Итого", 100]],
           units=[None, "млн ₽"])
    p = _plan(t)
    assert p.task.task == "shares" and p.options[0].kind == "doughnut"
    spec = chart_spec_of(p, t)
    assert spec.categories == ["Прямые", "Партнёры", "Онлайн"] and spec.series[0].values == [50, 30, 20]
    assert p.headline == "Прямые приносят половину выручки — 50%"


def test_marked_total_rows_are_excluded_when_reader_keeps_them():
    t = _t(["Канал", "Выручка"], [["Прямые", 50], ["Партнёры", 30], ["Все каналы", 100], ["Онлайн", 20]],
           units=[None, "млн ₽"])
    t.totals = [2]
    d = Data(t, profile_table(t))
    assert d.totals == {2} and d.n == 3
    assert d.cats is not None and d.cats.labels == ["Прямые", "Партнёры", "Онлайн"] and d.cats.total == 100


def test_reference_table_keeps_values_as_written_and_rest_row():
    rows = [[f"Клиент {i:03d}", ["ИТ", "Ритейл", "Банки"][i % 3], ["Москва", "Казань"][i % 2], round(500 / (i + 1), 1),
             "Стандарт"] for i in range(220)]
    t = _t(["Клиент", "Отрасль", "Регион", "Выручка", "Тариф"], rows, units=[None, None, None, "млн ₽", None])
    p = _plan(t)
    assert p.task.task == "reference" and p.options[0].kind == "table"
    assert p.headline.startswith("Топ-10 клиентов дают ") and p.headline.endswith("% выручки")
    body = chart_spec_of(p, t)
    assert len(body.rows) == 10 and "Остальные 210 клиентов —" in p.caption  # остальные — в подписи, не 11-й строкой
    assert body.columns[-1] == "Доля, %" and "Тариф" not in body.columns
    assert p.options[-1].title == "Разбиение на 22 слайда" and "слишком много" in p.options[-1].why_not


def test_short_reference_without_numbers_is_paged():
    rows = [[f"Сотрудник {i}", ["Продажи", "Маркетинг"][i % 2], ["Менеджер", "Аналитик", "Юрист"][i % 3]]
            for i in range(25)]
    t = _t(["Сотрудник", "Отдел", "Должность"], rows)
    p = _plan(t)
    assert p.task.task == "reference" and p.options[0].kind == "table"
    assert p.options[0].aggregation == "3 слайда по 10 строк" and p.slides == 3
    assert [len(chart_spec_of(p, t, part=k).rows) for k in (1, 2, 3)] == [10, 10, 5]
    assert p.headline == "25 сотрудников из 2 отделов"


# ── длинный формат, взаимосвязь, ключевые показатели ──────────────────────────────────────────────────────────────────
def test_long_format_series_by_category():
    rows = [[f"2025-{m:02d}", reg, base + m * 2] for m in range(1, 13) for reg, base in
            (("Москва", 100), ("Казань", 40), ("Омск", 20))]
    t = _t(["Месяц", "Регион", "Выручка"], rows, units=[None, None, "млн ₽"])
    p = _plan(t)
    assert p.task.task == "dynamics"
    spec = chart_spec_of(p, t)
    assert [s.name for s in spec.series] == ["Москва", "Казань", "Омск"] and len(spec.categories) == 12
    assert "stacked_column" in _kinds(p)
    assert p.headline == "Выручка выросла на 40% за 2025 год"


def test_relationship_scatter():
    # безымянные наблюдения (коды) — взаимосвязь; одна единица у обеих осей — без «каждый X даёт Y», только связь
    t = _t(["Кампания", "Расходы на рекламу", "Выручка"],
           [[f"К-{100 + i}", i * 10, 3 * i * 10 + 50 + (i % 5) * 20] for i in range(20)],
           units=[None, "тыс. ₽", "тыс. ₽"])
    p = _plan(t)
    assert p.task.task == "relationship" and p.options[0].kind == "scatter"
    assert p.headline == "Расходы на рекламу и выручка связаны: r = 0,99"
    spec = chart_spec_of(p, t)
    assert spec.type == "scatter" and len(spec.xy[0].x) == 20 and spec.x_title == "Расходы на рекламу, тыс. ₽"
    # именованные строки (магазины) — сравнение, а не взаимосвязь
    named = _t(["Магазин", "Расходы на рекламу", "Выручка"], [[f"Магазин {chr(1040 + i)}", r[1], r[2]]
                                                             for i, r in enumerate(t.rows)], units=[None, "тыс. ₽", "тыс. ₽"])
    assert plan_dataset(profile_table(named), named).task.task == "comparison"


def test_melted_kpi_table_still_gives_cards():
    """Широкую таблицу «Показатель | III кв. 2026 | III кв. 2025» чтение может развернуть в длинную."""
    melt = [["Выручка", "2025-Q3", "1,01 млрд ₽"], ["Выручка", "2026-Q3", "1,24 млрд ₽"], ["Клиенты", "2025-Q3", "2 949"],
            ["Клиенты", "2026-Q3", "3 480"], ["Средний чек", "2025-Q3", "342 тыс. ₽"],
            ["Средний чек", "2026-Q3", "356 тыс. ₽"], ["NPS", "2025-Q3", "46"], ["NPS", "2026-Q3", "52"]]
    t = _t(["Показатель", "Квартал", "Значение"], melt, file="Итоги квартала.txt", kind="text")
    p = _plan(t)
    assert p.task.task == "kpi" and p.options[0].kind == "kpi_cards"
    assert p.headline == "Выручка растёт быстрее числа клиентов: +23% против +18%"
    cards = chart_spec_of(p, t)
    assert all(isinstance(c, NumberCallout) for c in cards) and cards[0].value == "1,24 млрд ₽"


def test_counts_by_category_without_numbers():
    t = _t(["Обращение", "Канал"], [[f"A-{i}", ["Почта", "Чат", "Телефон"][i % 3 if i % 7 else 0]] for i in range(60)])
    p = _plan(t)
    assert p.task.task == "comparison"
    # «даёт» — только про выручку; доля — словами и «всех»: доля счёта не читается как уровень (раунд 10, M3)
    assert p.headline == "Почта — почти половина всех обращений: 43%"


# ── цель ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_goal_shares_changes_ranking_for_either_dataset():
    t = _t(["Направление", "Выручка"], [["Облако", 500], ["Почта", 200], ["Диск", 150], ["Видео", 100], ["Игры", 50]],
           units=[None, "млн ₽"])
    plain = _plan(t)
    assert plain.task.task == "comparison" and plain.options[0].kind in ("column", "bar")
    shaped = _plan(t, "Покажи доли направлений в выручке")
    assert shaped.task.task == "shares" and shaped.options[0].kind == "doughnut"
    assert "подняла его на первое место" in " ".join(shaped.options[0].reasons)
    assert shaped.headline == "Облако приносит половину выручки — 50%"
    structure = _plan(t, "Покажи структуру")
    assert structure.options[0].kind == "doughnut"


def test_goal_with_subject_of_a_metric_picks_that_metric():
    rows = [[f"2025-{m:02d}", 100 + m * 5, 1000 + m * 10] for m in range(1, 13)]
    t = _t(["Месяц", "Выручка", "Клиентов"], rows, units=[None, "млн ₽", None])
    assert "Выручка" in _plan(t).headline
    p = _plan(t, "Покажи рост клиентов")
    assert p.headline.startswith("Число клиентов выросло")
    assert chart_spec_of(p, t).series[0].name == "Клиентов"


def test_slide_data_keeps_outliers_for_distribution_only():
    rng = np.random.default_rng(7)
    vals = [int(x) for x in rng.gamma(2.0, 20.0, 300)] + [900, 1200]
    t = _t(["Заказ", "Минут доставки"], [[f"Z-{1000 + i}", v] for i, v in enumerate(vals)])
    sd = slide_data_of(_plan(t))
    assert len(sd.outliers) == 2 and sd.aggregation and "интервал" in sd.aggregation
