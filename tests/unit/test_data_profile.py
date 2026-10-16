"""Профиль датасета (verstka/data/profile.py, описание решения §2.2): типы и роли колонок, ось времени и частота,
пропущенные периоды, выбросы, части целого, иерархии, пригодность, природа и строка карточки — на таблицах, собранных
вручную, и на семи файлах примера `examples/data-sales-2026` (природа — как в SCENARIO.md).

Чтение файлов (Task 2) здесь не используется: таблицы примера собирает маленький помощник ниже — так, как их отдаёт
чтение (числа — числами, даты и периоды — строками, единицы отделены от имени)."""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import re
import time
from pathlib import Path
from typing import Optional

import pytest

from verstka.data.profile import count_ru, parse_number_value, parse_time_value, period_iso, profile_table
from verstka.schemas.data import NATURE_LABELS, DatasetProfile, Table

EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "data-sales-2026"


def _t(columns: list[str], rows: list[list], units: Optional[list] = None, kind: str = "csv",
       file: str = "данные.csv") -> Table:
    return Table(id="t1", file=file, kind=kind, columns=columns, units=units or [None] * len(columns), rows=rows,
                 raw_header=list(columns))


def _col(p: DatasetProfile, name: str):
    return next(c for c in p.columns if c.name == name)


# ── типы колонок ──────────────────────────────────────────────────────────────────────────────────────────────────────
def test_money_by_unit_by_cells_and_by_name():
    p = profile_table(_t(
        ["Регион", "Выручка", "Сумма", "Доход"],
        [["Москва", 1433, "1 234,5 ₽", 10.5], ["Казань", 274, "980 руб.", 7.25], ["Омск", 150, "1 020,0 ₽", 3.0]],
        units=[None, "млн ₽", None, None],
    ))
    assert _col(p, "Выручка").type == "money" and _col(p, "Выручка").unit == "млн ₽"
    s = _col(p, "Сумма")
    assert s.type == "money" and s.role == "metric" and s.max == 1234.5 and s.min == 980.0
    assert _col(p, "Доход").type == "money"  # «доход» без единицы — деньги по имени


def test_percent_by_unit_and_by_raw_cells():
    p = profile_table(_t(
        ["Канал", "Доля", "Конверсия"],
        [["Прямые", 46, "4,5 %"], ["Партнёры", 28, "3,1 %"], ["Онлайн", 26, "2 %"]],
        units=[None, "%", None],
    ))
    assert _col(p, "Доля").type == "percent"
    conv = _col(p, "Конверсия")
    assert conv.type == "percent" and conv.unit == "%" and conv.max == 4.5


def test_numbers_from_raw_strings():
    p = profile_table(_t(["Город", "Население"], [["Москва", "13 149 803"], ["Казань", "1 318 604"], ["Омск", "1 104 485"]]))
    c = _col(p, "Население")
    assert c.type == "number" and c.role == "metric" and c.max == 13149803.0 and c.missing == 0


@pytest.mark.parametrize(
    "values, typ, iso",
    [
        (["2025-01-31", "2025-02-28", "2025-03-31"], "date", ["2025-01-31", "2025-02-28", "2025-03-31"]),
        (["31.01.2025", "28.02.2025", "31.03.2025"], "date", ["2025-01-31", "2025-02-28", "2025-03-31"]),
        (["31 января 2025 г.", "28 февраля 2025 г.", "31 марта 2025 г."], "date", ["2025-01-31", "2025-02-28", "2025-03-31"]),
        (["2025-01", "2025-02", "2025-03"], "period", ["2025-01", "2025-02", "2025-03"]),
        (["янв 2025", "фев 2025", "мар 2025"], "period", ["2025-01", "2025-02", "2025-03"]),
        (["Январь 2025", "Февраль 2025", "Март 2025"], "period", ["2025-01", "2025-02", "2025-03"]),
        (["01.2025", "02.2025", "03.2025"], "period", ["2025-01", "2025-02", "2025-03"]),
        (["IV кв. 2025", "I кв. 2026", "II кв. 2026"], "period", ["2025-Q4", "2026-Q1", "2026-Q2"]),
        (["Q4 2025", "Q1 2026", "Q2 2026"], "period", ["2025-Q4", "2026-Q1", "2026-Q2"]),
        (["4 кв. 2025", "1 квартал 2026", "2-й квартал 2026"], "period", ["2025-Q4", "2026-Q1", "2026-Q2"]),
        (["2025-Q4", "2026-Q1", "2026-Q2"], "period", ["2025-Q4", "2026-Q1", "2026-Q2"]),
        (["2023", "2024", "2025"], "period", ["2023", "2024", "2025"]),
        (["2025-W01", "2025-W02", "2025-W03"], "period", ["2025-W01", "2025-W02", "2025-W03"]),
    ],
)
def test_dates_and_periods_of_every_form(values, typ, iso):
    p = profile_table(_t(["Период", "Значение"], [[v, 10 + i] for i, v in enumerate(values)]))
    c = _col(p, "Период")
    assert c.type == typ and c.role == "time"
    assert (c.first, c.last, c.min, c.max) == (iso[0], iso[-1], iso[0], iso[-1])
    assert c.samples == values  # образцы — как в файле
    assert p.time_axis is not None and p.time_axis.column == "Период" and p.time_axis.points == 3


def test_years_as_numbers_need_a_hint():
    years = profile_table(_t(["Год", "Выручка"], [[2023, 10], [2024, 12], [2025, 15]]))
    assert _col(years, "Год").type == "period" and years.time_axis.freq == "year"
    amounts = profile_table(_t(["Клиент", "Сумма"], [["А", 1987], ["Б", 2014], ["В", 1999]]))
    assert (_col(amounts, "Сумма").type, _col(amounts, "Сумма").role) == ("number", "metric") and amounts.time_axis is None


def test_category_text_id_and_boolean():
    rows = []
    for i in range(80):
        rows.append([
            f"SUP-{48213 + i}",
            ["Москва", "Казань", "Омск"][i % 3],
            f"Клиент {i} долго ждал ответа и написал второе письмо в поддержку",
            "да" if i % 2 else "нет",
            30 + (i % 7),
        ])
    p = profile_table(_t(["Обращение", "Город", "Комментарий", "Решено", "Минут"], rows))
    assert (_col(p, "Обращение").type, _col(p, "Обращение").role) == ("id", "id")
    assert (_col(p, "Город").type, _col(p, "Город").role, _col(p, "Город").distinct) == ("category", "dimension", 3)
    assert (_col(p, "Комментарий").type, _col(p, "Комментарий").role) == ("text", "text")
    assert (_col(p, "Решено").type, _col(p, "Решено").role) == ("boolean", "dimension")
    assert p.metrics == ["Минут"] and p.dimensions == ["Город", "Решено"]


def test_row_numbers_are_ids_and_labels_of_a_short_table_are_categories():
    p = profile_table(_t(["№", "Регион", "Выручка"], [[i + 1, f"Регион {i}", 100 + i] for i in range(8)]))
    assert _col(p, "№").type == "id" and _col(p, "Регион").type == "category"
    long = profile_table(_t(["Клиент", "Выручка"], [[f"ООО «Клиент {i}»", float(i)] for i in range(100)]))
    assert (_col(long, "Клиент").type, _col(long, "Клиент").role) == ("text", "text")


def test_missing_cells_are_counted():
    p = profile_table(_t(["Месяц", "Выручка"], [["2025-01", 1], ["2025-02", None], ["2025-03", "н/д"], ["2025-04", ""],
                                                ["2025-05", 5]]))
    assert _col(p, "Выручка").missing == 3 and p.missing_total == 3


def test_total_row_is_not_data_but_proves_parts_of_whole():
    p = profile_table(_t(["Отдел", "Сотрудников"], [["Продажи", 40], ["Разработка", 35], ["Поддержка", 25], ["Итого", 100]]))
    c = _col(p, "Сотрудников")
    assert c.max == 40 and c.last == 25  # строка «Итого» — не данные
    assert p.parts_of_whole is True and p.nature == "shares"


# ── ось времени, частота, пропуски ────────────────────────────────────────────────────────────────────────────────────
def _days(start: dt.date, step: int, n: int) -> list[str]:
    return [(start + dt.timedelta(days=step * i)).isoformat() for i in range(n)]


@pytest.mark.parametrize(
    "values, freq, start, end",
    [
        (_days(dt.date(2025, 3, 1), 1, 30), "day", "2025-03-01", "2025-03-30"),
        (_days(dt.date(2025, 3, 3), 7, 10), "week", "2025-W10", "2025-W19"),
        ([f"2025-{m:02d}-01" for m in range(1, 13)], "month", "2025-01", "2025-12"),
        (["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"], "quarter", "2025-Q1", "2025-Q4"),
        (["2022-12-31", "2023-12-31", "2024-12-31"], "year", "2022", "2024"),
        (["2025-01-03", "2025-01-17", "2025-02-02", "2025-04-11", "2025-07-30"], "irregular", "2025-01-03", "2025-07-30"),
    ],
)
def test_time_axis_frequency(values, freq, start, end):
    p = profile_table(_t(["Дата", "Значение"], [[v, i] for i, v in enumerate(values)]))
    ax = p.time_axis
    assert (ax.freq, ax.start, ax.end, ax.points, ax.missing_periods) == (freq, start, end, len(values), [])


def test_missing_periods_without_a_row():
    months = ["2025-01", "2025-02", "2025-04", "2025-05", "2025-08"]
    p = profile_table(_t(["Месяц", "Выручка"], [[m, 10 + i] for i, m in enumerate(months)]))
    assert p.time_axis.missing_periods == ["2025-03", "2025-06", "2025-07"]
    assert p.nature == "with_gaps"


def test_missing_periods_with_an_empty_value_raw_quarters():
    rows = [["IV кв. 2024", 41], ["I кв. 2025", 43], ["II кв. 2025", None], ["III кв. 2025", 46], ["IV кв. 2025", 47],
            ["I кв. 2026", 49], ["II кв. 2026", None], ["III кв. 2026", 52]]
    p = profile_table(_t(["Квартал", "NPS"], rows))
    ax = p.time_axis
    assert (ax.freq, ax.start, ax.end, ax.points) == ("quarter", "2024-Q4", "2026-Q3", 8)
    assert ax.missing_periods == ["2025-Q2", "2026-Q2"]
    assert p.nature == "with_gaps" and p.summary == "С пропусками · 8 строк · 2 колонки"


def test_working_days_are_not_gaps():
    days = [d for d in _days(dt.date(2025, 3, 3), 1, 28) if dt.date.fromisoformat(d).weekday() < 5]
    p = profile_table(_t(["Дата", "Звонков"], [[d, 5 + i] for i, d in enumerate(days)]))
    assert p.time_axis.freq == "day" and p.time_axis.missing_periods == []


def test_long_format_keeps_the_time_axis():
    rows = [[m, r, 10 * i + j] for i, m in enumerate(["2025-01", "2025-02", "2025-03"]) for j, r in
            enumerate(["Москва", "Казань"])]
    rows = sorted(rows, key=lambda r: r[1])  # строки сгруппированы по региону — время не по порядку
    p = profile_table(_t(["Месяц", "Регион", "Выручка"], rows))
    assert p.time_axis is not None and p.time_axis.freq == "month" and p.time_axis.points == 3
    assert p.nature == "time_series" and p.dimensions == ["Регион"]


def test_contract_dates_in_a_list_are_an_attribute_not_an_axis():
    dates = ["2021-06-21", "2019-11-14", "2024-02-06", "2020-03-02", "2023-10-12", "2022-01-17"] * 10
    rows = [[f"ООО «Клиент {i}»", 100.0 - i, dates[i]] for i in range(60)]
    p = profile_table(_t(["Клиент", "Выручка", "Дата договора"], rows))
    c = _col(p, "Дата договора")
    assert (c.type, c.role) == ("date", "attribute") and p.time_axis is None


# ── выбросы ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def _exp_quantiles(n: int, scale: float) -> list[float]:
    """Сплошной длинный хвост: квантили экспоненциального распределения."""
    return [round(-math.log(1 - (i + 0.5) / n) * scale, 1) for i in range(n)]


def test_three_detached_values_above_600_of_512_are_the_outliers():
    values = _exp_quantiles(509, 60.0)  # хвост до ~400 минут — сплошной
    rows = [[f"SUP-{i}", v] for i, v in enumerate(values)]
    for at, v in ((44, 655.0), (293, 812.0), (338, 1430.0)):
        rows.insert(at, [f"SUP-x{at}", v])
    p = profile_table(_t(["Обращение", "Минут до ответа"], rows))
    assert p.rows == 512
    assert [(o.row, o.value) for o in p.outliers] == [(44, 655.0), (293, 812.0), (338, 1430.0)]
    assert all(o.column == "Минут до ответа" and "межквартильного размаха" in o.reason for o in p.outliers)
    assert _col(p, "Минут до ответа").outliers == [44, 293, 338]
    assert p.nature == "distribution"


def test_a_continuous_long_tail_is_not_outliers():
    p = profile_table(_t(["Обращение", "Минут"], [[f"SUP-{i}", v] for i, v in enumerate(_exp_quantiles(512, 60.0))]))
    assert p.outliers == []  # правило Тьюки без отрыва отметило бы десятки значений хвоста


def test_low_outlier_and_no_outliers_below_twelve_values():
    p = profile_table(_t(["Замер", "Значение"], [[f"Z{i}", 100 + (i % 9)] for i in range(40)] + [["Z-сбой", -500]]))
    assert [o.value for o in p.outliers] == [-500.0] and "первый квартиль" in p.outliers[0].reason
    few = profile_table(_t(["Регион", "Выручка"], [[f"Р{i}", v] for i, v in enumerate([1, 2, 3, 2, 1, 2, 3, 2, 1, 900])]))
    assert few.outliers == []


# ── части целого, иерархии ────────────────────────────────────────────────────────────────────────────────────────────
def test_shares_summing_to_100_are_parts_of_whole():
    shares = profile_table(_t(["Канал", "Доля"], [["Прямые", 46], ["Партнёры", 28], ["Маркетплейс", 17], ["Онлайн", 9]],
                              units=[None, "%"]))
    assert shares.parts_of_whole is True and shares.nature == "shares"
    growth = profile_table(_t(["Регион", "Рост"], [["Москва", 19], ["Казань", 38], ["Омск", 21], ["Сочи", 24]],
                              units=[None, "%"]))
    assert growth.parts_of_whole is False and growth.nature == "comparison"
    fractions = profile_table(_t(["Канал", "Доля"], [["А", 0.5], ["Б", 0.3], ["В", 0.2]]))
    assert fractions.parts_of_whole is True


def test_shares_per_period_in_long_format():
    rows = [[y, ch, v] for y, vals in (("2024", (50, 30, 20)), ("2025", (46, 34, 20))) for ch, v in
            zip(("Прямые", "Партнёры", "Онлайн"), vals)]
    p = profile_table(_t(["Год", "Канал", "Доля"], rows, units=[None, None, "%"]))
    assert p.parts_of_whole is True and p.time_axis is not None


def test_hierarchy_city_to_region():
    cities = [("Москва", "Центр"), ("Тверь", "Центр"), ("Тула", "Центр"), ("Казань", "Поволжье"), ("Самара", "Поволжье"),
              ("Пермь", "Урал"), ("Екатеринбург", "Урал"), ("Челябинск", "Урал")]
    p = profile_table(_t(["Город", "Регион", "Выручка"], [[c, r, 100 + i] for i, (c, r) in enumerate(cities)]))
    assert p.hierarchies == [("Город", "Регион")]
    long = [[c, r, m, 10 + i] for m in ("2025-01", "2025-02") for i, (c, r) in enumerate(cities)]
    p2 = profile_table(_t(["Город", "Регион", "Месяц", "Выручка"], long))
    assert p2.hierarchies == [("Город", "Регион")]


def test_hierarchy_chain_keeps_only_direct_links_and_ignores_chance():
    rows = [["Москва", "Центр", "Россия", 1], ["Тула", "Центр", "Россия", 2], ["Казань", "Поволжье", "Россия", 3],
            ["Самара", "Поволжье", "Россия", 4], ["Минск", "Минская", "Беларусь", 5], ["Брест", "Брестская", "Беларусь", 6]]
    p = profile_table(_t(["Город", "Регион", "Страна", "Выручка"], rows))
    assert p.hierarchies == [("Город", "Регион"), ("Регион", "Страна")]
    # «Тариф» — не группа: уникальная подпись строки определяет его случайно, это не иерархия
    q = profile_table(_t(["Клиент", "Тариф", "Выручка"], [[f"К{i}", "Старт" if i % 2 else "Бизнес", i] for i in range(6)]))
    assert q.hierarchies == []


# ── пригодность и природа ─────────────────────────────────────────────────────────────────────────────────────────────
def test_untypable_tables_with_a_reason():
    one = profile_table(_t(["Регион", "Выручка"], [["Москва", 10]]))
    assert (one.typable, one.untypable_reason, one.nature) == (False, "одна строка", "untypable")
    assert one.summary == "Не для графика · 1 строка · 2 колонки"
    text = profile_table(_t(["Вопрос", "Ответ"], [
        ["Как подключить облако к офисной сети?", "Через защищённый канал: настройте шлюз и маршруты по инструкции."],
        ["Можно ли перенести виртуальные машины?", "Да, мастер миграции переносит их без остановки сервисов."],
        ["Как устроена оплата за ресурсы облака?", "Посуточно по фактическому потреблению, счёт приходит раз в месяц."],
    ]))
    assert (text.typable, text.untypable_reason) == (False, "одни текстовые колонки")
    unique = profile_table(_t(["Сотрудник", "Почта"], [["Анна", "anna@x.ru"], ["Борис", "boris@x.ru"], ["Вера", "vera@x.ru"]]))
    assert (unique.typable, unique.untypable_reason) == (False, "все значения разные, чисел нет")
    empty = profile_table(_t(["А", "Б"], []))
    assert (empty.typable, empty.untypable_reason, empty.summary) == (False, "строк нет", "Не для графика · 0 строк · 2 колонки")


def test_categories_without_numbers_can_still_be_counted():
    p = profile_table(_t(["Задача", "Статус"], [[f"Задача {i}", "готово" if i % 3 else "в работе"] for i in range(9)]))
    assert p.typable and p.nature == "comparison"


def test_one_row_of_several_numbers_is_kpi():
    p = profile_table(_t(["Выручка", "Клиенты", "NPS"], [[1240, 3480, 52]], units=["млн ₽", None, None]))
    assert p.typable and p.nature == "kpi"


def test_kpi_table_and_the_same_table_inside_text():
    rows = [["Выручка", "1,24 млрд ₽", "+23%"], ["Клиенты", "3 480", "+18%"], ["Средний чек", "356 тыс. ₽", "+4%"],
            ["NPS", "52", "+6 п."]]
    kpi = profile_table(_t(["Показатель", "Значение", "Изменение"], rows))
    assert kpi.nature == "kpi" and kpi.metrics == ["Значение", "Изменение"] and kpi.dimensions == ["Показатель"]
    txt = profile_table(_t(["Показатель", "Значение", "Изменение"], rows, kind="text", file="Итоги.txt"))
    assert txt.nature == "text_table" and txt.summary == "Таблица в тексте · 4 строки · 3 колонки"


def test_relationship_and_distribution():
    rel = profile_table(_t(["Студент", "Часы подготовки", "Балл"],
                           [[f"Студент номер {i}", 2 + i % 20, 40 + (i * 7) % 60] for i in range(100)]))
    assert rel.nature == "relationship"
    dist = profile_table(_t(["Минут"], [[v] for v in _exp_quantiles(200, 30.0)]))
    assert dist.nature == "distribution" and dist.size == "large"


def test_size_and_summary_plural_forms():
    def summary(n: int) -> str:
        return profile_table(_t(["Месяц", "Выручка"], [[f"{2000 + i // 12}-{i % 12 + 1:02d}", i] for i in range(n)])).summary

    assert summary(1) == "Не для графика · 1 строка · 2 колонки"
    assert summary(2) == "Временной ряд · 2 строки · 2 колонки"
    assert summary(5) == "Временной ряд · 5 строк · 2 колонки"
    assert summary(11) == "Временной ряд · 11 строк · 2 колонки"
    assert summary(21) == "Временной ряд · 21 строка · 2 колонки"
    assert summary(22) == "Временной ряд · 22 строки · 2 колонки"
    assert [count_ru(n, "колонка", "колонки", "колонок") for n in (1, 3, 5, 12, 101, 112)] == [
        "1 колонка", "3 колонки", "5 колонок", "12 колонок", "101 колонка", "112 колонок"]
    assert count_ru(100000, "строка", "строки", "строк") == "100\u00a0000 строк"
    sizes = [profile_table(_t(["Регион", "В"], [[f"Р{i}", i] for i in range(n)])).size for n in (12, 13, 60, 61)]
    assert sizes == ["small", "medium", "medium", "large"]


# ── разбор ячеек ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "cell, value",
    [("1 234,5", 1234.5), ("1\u00a0234,5", 1234.5), ("46 %", 46.0), ("+23%", 23.0), ("−5", -5.0), ("1,24 млрд ₽", 1.24e9),
     ("356 тыс. ₽", 356e3), ("$1,200", 1200.0), ("1.234.567,8", 1234567.8), ("120 мин", 120.0), (17, 17.0), (2.5, 2.5),
     ("IV кв. 2025", None), ("abc", None), ("", None), (None, None), (True, None)],
)
def test_parse_number_value(cell, value):
    assert parse_number_value(cell) == value


def test_parse_time_value_and_iso():
    for s, iso in [("янв 2025", "2025-01"), ("IV кв. 2025", "2025-Q4"), ("Q1 2026", "2026-Q1"), ("31.01.2025", "2025-01-31"),
                   ("2025", "2025"), ("2025-W05", "2025-W05"), ("сентябрь 2026", "2026-09")]:
        gran, o = parse_time_value(s)
        assert period_iso(gran, o) == iso
    assert parse_time_value("марка 2025") is None and parse_time_value(2025) is None


# ── детерминизм и скорость ────────────────────────────────────────────────────────────────────────────────────────────
def _big_table(n: int = 100_000) -> Table:
    regions = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Краснодар", "Самара", "Омск"]
    d0 = dt.date(2024, 1, 1)
    rows = [[
        (d0 + dt.timedelta(days=i % 730)).isoformat(), f"ORD-{i:06d}", regions[(i * 7) % 8], f"Товар {(i * 13) % 300}",
        float((i * 37) % 1000) + 0.5, (i * 11) % 97, None if i % 50 == 0 else round(((i * 17) % 100) / 3, 2),
        "да" if i % 3 else "нет", f"{(i * 31) % 5000} ₽", f"Комментарий номер {i % 9000} к заказу, длинный текст",
    ] for i in range(n)]
    cols = ["Дата", "Заказ", "Регион", "Товар", "Выручка", "Штук", "Скидка", "Оплачен", "Сумма", "Комментарий"]
    # строки уже проверены чтением: model_construct не тратит время теста на проверку миллиона ячеек
    return Table.model_construct(id="big", file="big.csv", kind="csv", sheet=None, columns=cols,
                                 units=[None, None, None, None, "млн ₽", None, "%", None, None, None], rows=rows,
                                 raw_header=cols, notes="")


def test_hundred_thousand_rows_by_ten_columns_in_under_a_second():
    t = _big_table()
    profile_table(t)  # прогрев
    t0 = time.perf_counter()
    p = profile_table(t)
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"{elapsed:.2f} с"
    assert p.rows == 100_000 and p.cols == 10 and p.size == "large"
    assert [c.type for c in p.columns] == ["date", "id", "category", "category", "money", "number", "percent", "boolean",
                                           "money", "text"]
    assert p.time_axis.freq == "day" and p.time_axis.points == 730


def test_profile_is_deterministic():
    t = _big_table(5000)
    assert profile_table(t).model_dump_json() == profile_table(t).model_dump_json()
    sample = _load("Выручка по месяцам.csv")
    assert profile_table(sample).model_dump_json() == profile_table(sample).model_dump_json()


def test_raw_text_cells_give_the_same_profile_as_typed_cells():
    months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    raw = [[f"{months[i % 12]} {2025 + i // 12}", f"{1000 + 37.5 * i:,.1f}".replace(",", " ").replace(".", ",") + " ₽"]
           for i in range(15)]
    typed = [[f"{2025 + i // 12}-{i % 12 + 1:02d}", 1000 + 37.5 * i] for i in range(15)]
    a = profile_table(_t(["Месяц", "Выручка"], raw))
    b = profile_table(_t(["Месяц", "Выручка"], typed, units=[None, "₽"]))
    assert raw[0] == ["янв 2025", "1 000,0 ₽"]
    assert a.time_axis == b.time_axis and a.nature == b.nature == "time_series"
    ca, cb = _col(a, "Выручка"), _col(b, "Выручка")
    assert (ca.type, ca.unit, ca.min, ca.max, ca.median) == (cb.type, cb.unit, cb.min, cb.max, cb.median) == (
        "money", "₽", 1000.0, 1525.0, 1262.5)


def test_dates_with_repeats_and_no_numbers_are_counted_by_period():
    days = ["2025-03-03", "2025-03-03", "2025-03-04", "2025-03-05", "2025-03-05", "2025-03-05", "2025-03-06"]
    p = profile_table(_t(["Дата", "Событие"], [[d, f"Событие {i}"] for i, d in enumerate(days)]))
    assert p.typable and p.time_axis is not None and p.nature == "time_series" and p.metrics == []


def test_the_same_data_from_another_format_gives_the_same_profile():
    rows = [["Москва", 1433, 19], ["Казань", 274, 38], ["Омск", 150, 12], ["Сочи", 120, 31]]
    a = profile_table(_t(["Регион", "Выручка", "Рост"], rows, units=[None, "млн ₽", "%"], kind="csv"))
    b = profile_table(_t(["Регион", "Выручка", "Рост"], rows, units=[None, "млн ₽", "%"], kind="xlsx"))
    assert a.model_dump(exclude={"kind"}) == b.model_dump(exclude={"kind"})


# ── семь файлов примера ───────────────────────────────────────────────────────────────────────────────────────────────
def _split_unit(h: str) -> tuple[str, Optional[str]]:
    m = re.match(r"^(.*?)\s*(?:,\s*([^,]+)|\(([^()]+)\))$", h)
    return (m.group(1), (m.group(2) or m.group(3)).strip()) if m else (h, None)


def _cell(v):
    """Ячейка так, как её отдаёт чтение: число — числом, дата Excel — ISO, пусто — None, остальное — строкой."""
    if v is None or isinstance(v, (int, float)):
        return v
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s.replace(" ", "").replace(",", "."))
    except ValueError:
        return s


def _table(name: str, kind: str, header: list[str], rows: list[list]) -> Table:
    cols, units = zip(*[_split_unit(h) for h in header])
    return Table(id=name, file=name, kind=kind, columns=list(cols), units=list(units), raw_header=list(header),
                 rows=[[_cell(v) for v in r] for r in rows])


def _load(name: str) -> Table:
    path = EXAMPLES / name
    if path.suffix == ".csv":
        with path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh, delimiter=";"))
        return _table(name, "csv", rows[0], rows[1:])
    if path.suffix == ".json":
        recs = json.loads(path.read_text(encoding="utf-8"))
        return _table(name, "json", list(recs[0]), [list(r.values()) for r in recs])
    if path.suffix == ".xlsx":
        openpyxl = pytest.importorskip("openpyxl")
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        return _table(name, "xlsx", rows[0], rows[1:])
    # текст: pipe-таблица Markdown, ячейки — как в тексте («1,24 млрд ₽», «+23%»)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("|") and not set(ln) <= set("|-: ")]
    rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in lines]
    return Table(id=name, file=name, kind="text", columns=rows[0], units=[None] * len(rows[0]), rows=rows[1:],
                 raw_header=rows[0])


@pytest.mark.parametrize(
    "name, nature, summary",
    [
        ("Выручка по месяцам.csv", "time_series", "Временной ряд · 21 строка · 3 колонки"),
        ("Регионы.xlsx", "comparison", "Сравнение · 8 строк · 3 колонки"),
        ("Каналы продаж.json", "shares", "Доли · 4 строки · 4 колонки"),
        ("Время ответа поддержки.csv", "distribution", "Распределение · 512 строк · 2 колонки"),
        ("Клиенты.xlsx", "reference", "Справочник · 240 строк · 6 колонок"),
        ("NPS по кварталам.csv", "with_gaps", "С пропусками · 8 строк · 3 колонки"),
        ("Итоги квартала.txt", "text_table", "Таблица в тексте · 4 строки · 4 колонки"),
    ],
)
def test_sample_files_have_the_nature_of_the_scenario(name, nature, summary):
    p = profile_table(_load(name))
    assert p.typable and p.nature == nature and p.summary == summary
    assert p.summary.startswith(NATURE_LABELS[nature])


def test_sample_revenue_by_month():
    p = profile_table(_load("Выручка по месяцам.csv"))
    ax = p.time_axis
    assert (ax.column, ax.freq, ax.start, ax.end, ax.points, ax.missing_periods) == ("Месяц", "month", "2025-01", "2026-09",
                                                                                      21, [])
    assert p.metrics == ["Выручка", "Клиентов"] and _col(p, "Выручка").type == "money"
    assert (_col(p, "Выручка").first, _col(p, "Выручка").last) == (296, 423) and p.outliers == []


def test_sample_regions_channels_and_support():
    reg = profile_table(_load("Регионы.xlsx"))
    assert reg.dimensions == ["Регион"] and _col(reg, "Рост").type == "percent" and not reg.parts_of_whole
    chn = profile_table(_load("Каналы продаж.json"))
    assert chn.parts_of_whole and _col(chn, "Доля").type == "percent" and chn.dimensions == ["Канал"]
    sup = profile_table(_load("Время ответа поддержки.csv"))
    assert _col(sup, "Обращение").role == "id" and sup.metrics == ["Минут до ответа"]
    assert len(sup.outliers) == 3 and all(o.value > 600 for o in sup.outliers)
    assert _col(sup, "Минут до ответа").median == 54.0


def test_sample_clients_nps_and_text():
    cli = profile_table(_load("Клиенты.xlsx"))
    assert cli.time_axis is None and _col(cli, "Дата договора").role == "attribute"
    assert _col(cli, "Клиент").role == "text" and cli.dimensions == ["Отрасль", "Регион", "Тариф"]
    assert ("Клиент", "Регион") in cli.hierarchies
    nps = profile_table(_load("NPS по кварталам.csv"))
    assert nps.time_axis.missing_periods == ["2025-Q2", "2026-Q2"] and nps.time_axis.freq == "quarter"
    txt = profile_table(_load("Итоги квартала.txt"))
    assert txt.dimensions == ["Показатель"] and txt.metrics == ["III кв. 2026", "III кв. 2025", "Изменение"]
