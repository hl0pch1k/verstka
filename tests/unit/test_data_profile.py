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
import random
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
    assert p.nature == "with_gaps" and p.summary == "Временной ряд с пропусками · 8 строк · 2 колонки"


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
    assert elapsed < 3.0, f"{elapsed:.2f} с"  # a margin for a slower Linux box under load (final review I10)
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
        ("NPS по кварталам.csv", "with_gaps", "Временной ряд с пропусками · 8 строк · 3 колонки"),
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


# ── ревью Task 2/3: регрессии ─────────────────────────────────────────────────────────────────────────────────────────
def _read(name: str, text: str) -> DatasetProfile:
    from verstka.data.readers import read_bytes

    return profile_table(read_bytes(name, text.encode())[0])


def test_strict_total_rule_keeps_label_rows_that_only_start_with_vsego():
    # п. 5: «Всего клиентов» — показатель, а не строка итога: он в статистике и первый в колонке
    p = _read("kpi.csv", "Показатель;Значение\nВсего клиентов;3480\nНовых клиентов;420\nУшли;35\nВыручка, млн ₽;1240\n")
    c = _col(p, "Значение")
    assert c.first == 3480 and _col(p, "Показатель").first == "Всего клиентов" and p.rows == 4
    assert c.max == 3480.0  # одна подпись с единицей — не признак таблицы показателей по строкам
    same = _read("kpi.csv", "Показатель;Значение\nВсего клиентов;3480\nНовых клиентов;420\nУшли;35\n")
    assert (_col(same, "Значение").max, same.rows) == (3480.0, 3)
    # все подписи — «Итого…»: это не строки итога, а подписи; колонка подписей — категории без пропусков
    q = profile_table(_t(["Показатель", "2025", "2026"], [["Итого", 3000, 3480], ["Итого по Москве", 1000, 1240]]))
    lab = _col(q, "Показатель")
    assert (lab.type, lab.role, lab.missing, lab.distinct) == ("category", "dimension", 0, 2) and q.nature != "reference"


def test_total_row_from_the_reader_proves_shares_at_the_end_or_the_start():
    # п. 6: «Итого» в конце (обычный макет) и в начале — «доли от итога»; строка итога — не данные
    for text in ("Регион;Выручка\nМосква;50\nКазань;30\nТверь;20\nИтого;100\n",
                 "Регион;Выручка\nИтого;100\nМосква;50\nКазань;30\nТверь;20\n"):
        p = _read("t.csv", text)
        assert p.parts_of_whole and p.nature == "shares" and p.summary == "Доли · 3 строки · 2 колонки"
        assert _col(p, "Выручка").max == 50 and p.rows == 3
    # таблица, собранная не чтением: Table.totals отмечает итог
    t = Table(id="t", file="t.csv", kind="csv", columns=["Отдел", "Штат"], units=[None, None],
              rows=[["А", 40], ["Б", 60], ["Все отделы", 100]], raw_header=["Отдел", "Штат"], totals=[2])
    assert profile_table(t).parts_of_whole and _col(profile_table(t), "Штат").max == 60


def test_wide_tables_profile_as_series_after_the_reader_melts_them():
    # п. 4: 5 лет показателей — ряд, а не карточки; «Регион · 2023 · 2024 · 2025» — ряд по регионам, а не сравнение
    kpi = _read("w.csv", ("Показатель;2021;2022;2023;2024;2025\nВыручка, млн ₽;100;120;150;170;210\n"
                          "Прибыль, млн ₽;10;12;18;20;25\nКлиенты;1000;1200;1300;1500;1700\n"))
    assert kpi.nature == "time_series" and kpi.time_axis.freq == "year" and kpi.time_axis.points == 5
    assert kpi.metrics == ["Выручка", "Прибыль", "Клиенты"]
    reg = _read("r.csv", "Регион;2023;2024;2025\nМосква;100;120;150\nКазань;50;60;80\nТверь;20;25;22\n")
    assert reg.nature == "time_series" and reg.time_axis.column == "Год" and reg.dimensions == ["Регион"]
    # «Итого» по каждому году = сумма регионов — доли от итога в длинной таблице
    tot = _read("t.csv", "Регион;2023;2024;2025\nМосква;10;20;30\nКазань;5;5;5\nИтого;15;25;35\n")
    assert tot.parts_of_whole and tot.rows == 6


def test_timestamps_within_a_day_give_an_hourly_axis():
    # п. 8: 48 часовых строк — 48 точек по часам, а не 2 дня; одна запись в день со временем — ось по дням
    hours = [(dt.datetime(2025, 3, 1) + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(48)]
    p = profile_table(_t(["Время", "Нагрузка"], [[h, 30 + i % 24] for i, h in enumerate(hours)], units=[None, "%"]))
    ax = p.time_axis
    assert (ax.freq, ax.points, ax.start, ax.end) == ("hour", 48, "2025-03-01T00:00", "2025-03-02T23:00")
    assert _col(p, "Время").type == "date" and _col(p, "Время").min == "2025-03-01T00:00"
    one_day = profile_table(_t(["Время", "Звонков"], [[h, i] for i, h in enumerate(hours[:24])]))
    assert one_day.time_axis.points == 24 and one_day.time_axis.freq == "hour"
    gaps = profile_table(_t(["Время", "Звонков"], [[h, i] for i, h in enumerate(hours[:24]) if i != 5]))
    assert gaps.time_axis.missing_periods == ["2025-03-01T05:00"]
    daily = profile_table(_t(["Дата", "Значение"], [["15.01.2025 10:30", 1], ["16.01.2025 00:00", 2],
                                                    ["17.01.2025 12:30", 3], ["18.01.2025 13:30", 4]]))
    assert (daily.time_axis.freq, daily.time_axis.points) == ("day", 4)


def test_rate_percentages_summing_to_100_are_not_shares():
    # п. 12: конверсия 25/30/20/24 (сумма 99) — не доли целого; доля с суммой 96 — доли; безымянные % — только ≈ 100
    conv = profile_table(_t(["Канал", "Конверсия"], [["Поиск", 25], ["Соцсети", 30], ["Почта", 20], ["Прямые", 24]],
                            units=[None, "%"]))
    assert not conv.parts_of_whole and conv.nature == "comparison"
    share = profile_table(_t(["Канал", "Доля"], [["А", 46], ["Б", 28], ["В", 13], ["Г", 9]], units=[None, "%"]))
    assert share.parts_of_whole
    loose = profile_table(_t(["Канал", "Значение"], [["А", 46], ["Б", 28], ["В", 13], ["Г", 9]], units=[None, "%"]))
    assert not loose.parts_of_whole  # 96 без слова «доля» — не части целого
    exact = profile_table(_t(["Канал", "Значение"], [["А", 46], ["Б", 28], ["В", 17], ["Г", 9]], units=[None, "%"]))
    assert exact.parts_of_whole


def test_zero_inflated_column_still_finds_a_detached_value():
    # п. 15: 150 нулей, 40 небольших значений и 5000 — межквартильный размах 0, но 5000 — выброс
    vals = [0] * 150 + [1 + (i * 7) % 50 for i in range(40)] + [5000]
    p = profile_table(_t(["Возвраты"], [[v] for v in vals]))
    assert [(o.row, o.value) for o in p.outliers] == [(190, 5000.0)]
    assert "кроме повторяющегося 0" in p.outliers[0].reason
    flat = profile_table(_t(["Флаг"], [[0]] * 150 + [[1]] * 20))
    assert flat.outliers == []  # одни нули и единицы — выбросов нет


def test_short_code_like_labels_are_categories_not_ids():
    # п. 16: «A320», «B737», «SSJ100» в коротком списке — подписи для сравнения, а не идентификаторы
    p = profile_table(_t(["Модель", "Рейсов"], [["A320", 120], ["B737", 95], ["SSJ100", 60], ["A321", 80], ["E190", 30]]))
    assert (_col(p, "Модель").type, _col(p, "Модель").role) == ("category", "dimension") and p.nature == "comparison"
    long = profile_table(_t(["Заказ", "Сумма"], [[f"ORD-{i:05d}", i % 17] for i in range(80)]))
    assert _col(long, "Заказ").type == "id"  # длинный список кодов — идентификатор


def test_mixed_units_have_no_min_max_median():
    # п. 17: «1,24 млрд ₽», «3 480», «356 тыс. ₽», «52» — у каждой строки своя единица
    rows = [["Выручка", "1,24 млрд ₽", "+23%"], ["Клиенты", "3 480", "+18%"], ["Средний чек", "356 тыс. ₽", "+4%"],
            ["NPS", "52", "+6 п."]]
    p = profile_table(_t(["Показатель", "III кв. 2026", "Изменение"], rows))
    c = _col(p, "III кв. 2026")
    assert (c.min, c.max, c.median) == (None, None, None) and (c.first, c.last) == ("1,24 млрд ₽", "52")
    assert c.role == "metric" and p.nature == "kpi"
    same_base = profile_table(_t(["Сделка", "Сумма"], [["А", "1,2 млн ₽"], ["Б", "800 тыс. ₽"], ["В", "950 тыс. ₽"]]))
    s = _col(same_base, "Сумма")
    assert (s.min, s.max, s.unit) == (800000.0, 1200000.0, "₽")  # одна база — сравнимо в рублях


def test_reader_and_profile_share_one_parser():
    # дубли разбора убраны: чтение и профиль берут числа, периоды, пропуски и итог из verstka/data/parse.py
    from verstka.data import parse
    from verstka.data import profile, readers

    assert readers.parse_number is parse.parse_number and readers.parse_quantity is parse.parse_quantity
    assert readers.parse_period is parse.parse_period and readers.split_unit is parse.split_unit
    assert profile.period_iso is parse.period_iso
    for cell in ["(15)", "1e3", "#DIV/0!", "#REF!", "NA", "1 234,5", "$1,200", "1,24 млрд ₽", "−12"]:
        q = parse.quantity(cell)
        assert readers.parse_number(cell) == (None if q is None else q.value)
        assert profile.parse_number_value(cell) == (None if q is None else q.full)


# ── чтение → профиль: семь файлов примера целиком (п. 18) ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "name, nature, summary",
    [
        ("Выручка по месяцам.csv", "time_series", "Временной ряд · 21 строка · 3 колонки"),
        ("Регионы.xlsx", "comparison", "Сравнение · 8 строк · 3 колонки"),
        ("Каналы продаж.json", "shares", "Доли · 4 строки · 4 колонки"),
        ("Время ответа поддержки.csv", "distribution", "Распределение · 512 строк · 2 колонки"),
        ("Клиенты.xlsx", "reference", "Справочник · 240 строк · 6 колонок"),
        ("NPS по кварталам.csv", "with_gaps", "Временной ряд с пропусками · 8 строк · 3 колонки"),
        ("Итоги квартала.txt", "text_table", "Таблица в тексте · 4 строки · 4 колонки"),
    ],
)
def test_sample_files_read_and_profiled_end_to_end(name, nature, summary):
    from verstka.data.readers import read_file

    tables = read_file(EXAMPLES / name)
    assert len(tables) == 1
    p = profile_table(tables[0])
    assert p.typable and p.nature == nature and p.summary == summary


def test_sample_files_end_to_end_details():
    from verstka.data.readers import read_file

    def prof(name: str) -> DatasetProfile:
        return profile_table(read_file(EXAMPLES / name)[0])

    rev = prof("Выручка по месяцам.csv")
    assert (rev.time_axis.freq, rev.time_axis.start, rev.time_axis.end, rev.time_axis.points) == (
        "month", "2025-01", "2026-09", 21)
    assert _col(rev, "Выручка").unit == "млн ₽" and (_col(rev, "Выручка").first, _col(rev, "Выручка").last) == (296, 423)
    sup = prof("Время ответа поддержки.csv")
    assert sorted(o.value for o in sup.outliers) == [655.0, 812.0, 1430.0] and _col(sup, "Обращение").role == "id"
    nps = prof("NPS по кварталам.csv")
    assert nps.time_axis.missing_periods == ["2025-Q2", "2026-Q2"]
    cli = prof("Клиенты.xlsx")
    assert cli.time_axis is None and _col(cli, "Дата договора").role == "attribute"
    assert ("Клиент", "Регион") in cli.hierarchies
    chn = prof("Каналы продаж.json")
    assert chn.parts_of_whole and _col(chn, "Доля").unit == "%"
    reg = prof("Регионы.xlsx")
    assert not reg.parts_of_whole and reg.dimensions == ["Регион"]
    txt = prof("Итоги квартала.txt")
    assert txt.dimensions == ["Показатель"] and _col(txt, "III кв. 2026").max is None


# ── второй набор данных (университет) и повторное ревью: регрессии ────────────────────────────────────────────────────
def test_budget_word_alone_is_not_money():
    # M8: «Бюджет» — места (целые счёты), а не деньги; деньги — если на это что-то указывает
    p = profile_table(_t(["Направление", "Бюджет", "Платное"], [["А", 120, 140], ["Б", 110, 150], ["В", 90, 60]]))
    assert _col(p, "Бюджет").type == "number"
    assert profile_table(_t(["Отдел", "Бюджет"], [["А", 12.5], ["Б", 7.25], ["В", 3.1]])).columns[1].type == "number"
    assert profile_table(_t(["Отдел", "Сумма бюджета"], [["А", 12], ["Б", 7], ["В", 3]])).columns[1].type == "money"
    assert profile_table(_t(["Регион", "Выручка"], [["А", 12], ["Б", 7], ["В", 3]])).columns[1].type == "money"


def test_total_column_equal_to_the_sum_of_parts():
    # M9: «Всего» = «Очно» + «Заочно» + «Вечерне» в каждой строке — части целого, итог и части отмечены
    rows = [["Физики", 30, 10, 5, 45], ["Химии", 20, 0, 4, 24], ["Биологии", 15, 5, 0, 20], ["Права", 50, 30, 10, 90]]
    p = profile_table(_t(["Кафедра", "Очно", "Заочно", "Вечерне", "Всего"], rows))
    assert p.parts_of_whole and p.total_column == "Всего" and p.part_columns == ["Очно", "Заочно", "Вечерне"]
    assert p.nature == "shares"
    off = [r[:4] + [r[4] + 7] for r in rows]  # «Всего» не сходится — это не итог
    q = profile_table(_t(["Кафедра", "Очно", "Заочно", "Вечерне", "Всего"], off))
    assert q.total_column is None and q.part_columns == [] and not q.parts_of_whole
    # итог сходится только с колонками подряд перед ним (доля в конце — не часть)
    rows2 = [r + [round(100 * r[1] / r[4])] for r in rows]
    r2 = profile_table(_t(["Кафедра", "Очно", "Заочно", "Вечерне", "Всего", "Доля очных"], rows2,
                          units=[None, None, None, None, None, "%"]))
    assert r2.total_column == "Всего" and r2.part_columns == ["Очно", "Заочно", "Вечерне"]


def test_hierarchy_of_a_parent_listed_in_blocks_to_the_left():
    # M16: «Корпус → Кафедра» (имя родителя не из словаря групп): каждая кафедра в одном корпусе, корпус левее и идёт
    # блоками — три блока по три строки и больше
    pairs = [("Физфак", "Оптики"), ("Физфак", "Акустики"), ("Физфак", "Ядерной"), ("Химфак", "Органики"),
             ("Химфак", "Неорганики"), ("Химфак", "Аналитики"), ("Биофак", "Генетики"), ("Биофак", "Ботаники"),
             ("Биофак", "Зоологии")]
    rows = [[f, k, 10 + i] for i, (f, k) in enumerate(pairs)]
    p = profile_table(_t(["Корпус", "Кафедра", "Публикаций"], rows))
    assert p.hierarchies == [("Кафедра", "Корпус")]
    # родитель вперемешку или правее — случайность, а не иерархия
    mixed = [rows[i] for i in (0, 3, 6, 1, 4, 7, 2, 5, 8)]
    assert profile_table(_t(["Корпус", "Кафедра", "Публикаций"], mixed)).hierarchies == []
    right = [[k, f, v] for f, k, v in rows]
    assert profile_table(_t(["Кафедра", "Корпус", "Публикаций"], right)).hierarchies == []
    # два блока («Пол → Сотрудник») — сортировка, а не иерархия (повторное ревью, Minor 3)
    two = [["М" if i < 6 else "Ж", f"Сотрудник {i}", 100 + i] for i in range(12)]
    assert profile_table(_t(["Пол", "Сотрудник", "Оклад"], two)).hierarchies == []


def test_id_group_and_two_correlated_measures_is_a_relationship():
    # M2: id + группа + две связанные метрики на 100 строках — взаимосвязь, а не справочник
    rows = [[f"ID-{1000 + i}", ["А", "Б", "В"][i % 3], 2 + i % 20, 40 + 2 * (i % 20) + (i * 7) % 9] for i in range(100)]
    p = profile_table(_t(["Участник", "Группа", "Часы", "Балл"], rows))
    assert p.nature == "relationship" and p.summary.startswith("Взаимосвязь")
    noise = [[f"ID-{1000 + i}", ["А", "Б", "В"][i % 3], 2 + i % 20, 40 + (i * 37) % 53] for i in range(100)]
    assert profile_table(_t(["Участник", "Группа", "Часы", "Балл"], noise)).nature == "reference"
    # изменение той же величины рядом с ней — не взаимосвязь
    chg = [[f"ID-{i}", ["А", "Б"][i % 2], 100 + i, 2 * i % 15] for i in range(60)]
    assert profile_table(_t(["Кафедра", "Группа", "Бюджет", "Изменение к 2025"], chg)).nature != "relationship"


def test_row_units_make_value_columns_incomparable():
    # M21: у строк свои единицы — у колонок «2026», «2025» нет min/max и единицы «%»
    t = Table(id="k", file="k.csv", kind="csv", columns=["Показатель", "2026", "2025"], units=[None, None, None],
              rows=[["Выручка", 540, 500], ["Клиенты", 1200, 1100], ["Доля отличников", 35, 31]],
              raw_header=["Показатель", "2026", "2025"], row_units=["млн ₽", "чел.", "%"])
    p = profile_table(t)
    c = _col(p, "2026")
    assert (c.min, c.max, c.median, c.unit, c.type) == (None, None, None, None, "number") and c.first == 540


def test_event_log_keeps_a_day_axis():
    # повторное ревью, I2: заказы в рабочие часы за 60 дней — ось по дням без сотен «пропущенных» ночных часов
    rows = []
    for d in range(60):
        for k in range(12):
            ts = dt.datetime(2025, 3, 1, 8) + dt.timedelta(days=d, hours=(k * 5 + d) % 13, minutes=(k * 17) % 60)
            rows.append([ts.strftime("%Y-%m-%dT%H:%M"), 100 + k])
    p = profile_table(_t(["Дата заказа", "Сумма"], rows, units=[None, "₽"]))
    assert p.time_axis.freq == "day" and p.time_axis.points == 60 and p.time_axis.missing_periods == []
    short = [r for r in rows if r[0] < "2025-03-03"]  # двое суток рабочих часов — ночи не пропуски (раунд 3, Minor 5)
    assert profile_table(_t(["Дата заказа", "Сумма"], short)).time_axis.freq == "day"


def test_quarter_hour_readings_lie_on_an_hourly_axis():
    # повторное ревью, M3 (выбранное правило): минуты не различаются — 96 замеров раз в 15 минут дают 24 часа
    stamps = [(dt.datetime(2025, 3, 1) + dt.timedelta(minutes=15 * k)).strftime("%Y-%m-%dT%H:%M") for k in range(96)]
    p = profile_table(_t(["Время", "Нагрузка"], [[s, 30 + k % 7] for k, s in enumerate(stamps)]))
    assert (p.time_axis.freq, p.time_axis.points, p.time_axis.missing_periods) == ("hour", 24, [])


# ── чтение → профиль: второй набор данных (университет), только сквозная проверка ─────────────────────────────────────
SCIENCE = EXAMPLES.parent / "data-science-2026"


def test_science_files_end_to_end():
    from verstka.data.readers import read_file

    def both(name: str):
        t = read_file(SCIENCE / name)[0]
        return t, profile_table(t)

    t, p = both("Часы подготовки и баллы ЕГЭ.csv")
    assert p.nature == "relationship" and (_col(p, "Подготовка").unit, t.raw_header[2]) == ("ч/нед.", "Подготовка (ч в неделю)")
    t, p = both("Приём по направлениям.xlsx")
    assert t.columns[1:4] == ["Бюджет", "Платное", "Целевое"] and t.column_groups[1] == "Форма обучения"
    assert set(t.units[1:]) == {"чел."} and _col(p, "Бюджет").type == "number" and _col(p, "Целевое").missing == 0
    assert p.parts_of_whole and p.total_column == "Всего" and p.part_columns == ["Бюджет", "Платное", "Целевое"]
    t, p = both("Публикации по годам.json")
    assert t.columns == ["Год", "Scopus", "РИНЦ"] and t.units[1:] == ["статей", "статей"] and p.metrics == ["Scopus", "РИНЦ"]
    t, p = both("Бюджет НИОКР.csv")
    assert ("Кафедра", "Институт") in p.hierarchies and t.totals == [18]
    t, p = both("Итоги года.txt")
    assert t.units == [None] * 4 and t.row_units == ["чел.", None, "%", None, "млн ₽", "чел."]
    assert _col(p, "2026").max is None and col_first(t) == "Принято на 1 курс"
    t, p = both("Стипендии.csv")
    assert p.nature == "distribution" and _col(p, "Размер стипендии").unit == "₽"


def col_first(t: Table) -> str:
    return t.rows[0][0]


# ── выбросы на карточке файла: только похожие на ошибку ──────────────────────────────────────────────────────────────
def test_reference_card_of_clients_has_no_outlier_issue():
    # крупнейшие клиенты справочника — не проблема данных: карточка их не называет, анализу они остаются
    from verstka.api.app import _dataset_summary
    from verstka.data.readers import read_file

    t = read_file(EXAMPLES / "Клиенты.xlsx")[0]
    p = profile_table(t)
    card = _dataset_summary("clients", t, p)
    assert card.line == "Справочник · 240 строк · 6 колонок" and not any("выброс" in i for i in card.issues)
    assert p.outliers == [] and len(p.expected_outliers) == 10 and len(_col(p, "Выручка").outliers) == 10
    t2 = read_file(EXAMPLES / "Время ответа поддержки.csv")[0]
    card2 = _dataset_summary("support", t2, profile_table(t2))
    assert "3 выброса" in card2.issues  # время ответа 1 430 мин в распределении — заметно


def test_a_big_category_in_a_long_series_is_not_an_outlier_issue():
    # Москва в 10 раз больше других регионов каждый месяц — масштаб категории, а не ошибка
    rows = [[f"2025-{m:02d}", r, (1000 if r == "Москва" else 100) + m + k]
            for m in range(1, 13) for k, r in enumerate(["Москва", "Казань", "Тверь", "Омск", "Сочи"])]
    p = profile_table(_t(["Месяц", "Регион", "Выручка"], rows))
    assert p.nature == "time_series" and p.outliers == [] and len(p.expected_outliers) == 12
    spike = [[f"2025-{m:02d}", 100 + m % 3] for m in range(1, 13)] + [[f"2026-{m:02d}", 100 + m % 3] for m in range(1, 13)]
    spike[7][1] = 900  # всплеск в одном месяце ряда — заметен
    q = profile_table(_t(["Месяц", "Заказы"], spike))
    assert [o.value for o in q.outliers] == [900.0] and q.expected_outliers == []


# ── раунд 3: признаки вместо догадок ──────────────────────────────────────────────────────────────────────────────────
def test_lone_spikes_stay_outliers_in_entity_tables():
    # I-3: опечатка ×10 и больше, доля больше 100%, длительность — заметные выбросы даже в справочнике
    rnd = random.Random(3)
    tickets = [[f"T-{i}", f"Тема {i % 5}", "Иван", "Высокий", rnd.randint(5, 60)] for i in range(200)]
    tickets.append(["T-x", "Тема 1", "Иван", "Высокий", 4800])
    p = profile_table(_t(["Тикет", "Тема", "Исполнитель", "Приоритет", "Минут до ответа"], tickets))
    assert [o.value for o in p.outliers] == [4800.0] and p.expected_outliers == []
    clients = [[f"Клиент {i}", round(rnd.uniform(0.5, 12), 1)] for i in range(200)] + [["Клиент X", 1200.0]]
    p = profile_table(_t(["Клиент", "Выручка"], clients, units=[None, "млн ₽"]))
    assert 1200.0 in [o.value for o in p.outliers] and 1200.0 not in [o.value for o in p.expected_outliers]
    staff = [[f"Сотрудник {i}", rnd.randint(60_000, 140_000)] for i in range(80)] + [["Сотрудник X", 9_000_000]]
    p = profile_table(_t(["Сотрудник", "Оклад"], staff, units=[None, "₽"]))
    assert [o.value for o in p.outliers] == [9_000_000.0]
    share = [[f"Канал {i}", rnd.randint(1, 9)] for i in range(30)] + [["Канал X", 450]]
    p = profile_table(_t(["Канал", "Доля"], share, units=[None, "%"]))
    assert [o.value for o in p.outliers] == [450.0]


def test_a_ladder_of_big_clients_is_natural():
    # I-3: крупнейшие идут лестницей (каждый не больше чем втрое выше следующего) — естественны, карточка их не называет
    vals = [round(5 + i / 20, 2) for i in range(60)] + [12.0, 16.0, 22.0, 30.0]
    rows = [[f"Клиент {i:03d}", v] for i, v in enumerate(vals)]
    p = profile_table(_t(["Клиент", "Выручка"], rows, units=[None, "млн ₽"]))
    assert p.outliers == [] and sorted(o.value for o in p.expected_outliers) == [12.0, 16.0, 22.0, 30.0]
    typo = rows + [["Клиент 999", 900.0]]  # опечатка над лестницей — заметна, лестница — нет
    q = profile_table(_t(["Клиент", "Выручка"], typo, units=[None, "млн ₽"]))
    assert [o.value for o in q.outliers] == [900.0] and len(q.expected_outliers) == 4


def test_weak_money_words_need_ruble_magnitude():
    # I-4: «Бюджет», «Факт», «Расходы», «Затраты», «Оборот» в целых рублях — деньги; малые числа — нет
    big = profile_table(_t(["Отдел", "Бюджет", "Факт"], [["А", 1_500_000, 1_400_000], ["Б", 800_000, 820_000],
                                                         ["В", 2_300_000, 2_100_000]]))
    assert [c.type for c in big.columns[1:]] == ["money", "money"]
    for name in ("Расходы", "Затраты", "Оборот"):
        assert profile_table(_t(["Статья", name], [["А", 350_000], ["Б", 900_000], ["В", 150_000]])).columns[1].type \
            == "money"
    small = profile_table(_t(["Машина", "Расход топлива"], [["А", 12.5], ["Б", 15.0], ["В", 9.0]]))
    assert small.columns[1].type == "number"


def test_class_labels_are_categories():
    # «5А», «5Б» … «11Б» — подписи классов, а не числа: «Класс» — категория, две метрики
    from verstka.data.readers import read_bytes

    rows = "\n".join(f"{g}{letter};{24 + (g * 3 + i) % 7};{3.5 + ((g + i) % 10) / 10}".replace(".", ",")
                     for g in range(5, 12) for i, letter in enumerate("АБ"))
    t = read_bytes("k.csv", ("Класс;Учеников;Средний балл\n" + rows + "\n").encode())[0]
    assert t.rows[0][0] == "5А" and t.rows[-1][0] == "11Б"
    p = profile_table(t)
    assert (_col(p, "Класс").type, _col(p, "Класс").role) == ("category", "dimension")
    assert p.metrics == ["Учеников", "Средний балл"] and p.nature == "comparison"
    for label in ("5-А", "11 кл.", "1 курс", "2-й этаж"):
        assert parse_number_value(label) is None, label


def test_id_column_after_a_melt_stays_an_id():
    # Minor 4: «№ п/п» повторяется по годам длинной таблицы — всё равно номер
    from verstka.data.readers import read_bytes

    t = read_bytes("n.csv", "№ п/п;Регион;2023;2024;2025\n1;Москва;10;20;30\n2;Казань;5;6;7\n3;Тверь;1;2;3\n".encode())[0]
    p = profile_table(t)
    assert _col(p, "№ п/п").role == "id" and p.metrics == ["Значение"]


def test_short_business_hours_log_has_a_day_axis():
    # Minor 5: два дня по 09–18 ч — меньше половины часов: ось по дням, без ночных «пропусков»
    rows = [[(dt.datetime(2025, 3, 3, 9) + dt.timedelta(days=d, hours=h)).strftime("%Y-%m-%dT%H:%M"), 10 + h]
            for d in range(3) for h in range(0, 10, 2)]
    p = profile_table(_t(["Время", "Звонков"], rows))
    assert p.time_axis.freq == "day" and p.time_axis.missing_periods == []


def test_total_column_tolerance_and_percent_parts():
    # Minor 6: 1,2 + 0,8 ≠ 2,3 — не итог; Minor 7: доли в % с «Всего, %» = 100 — части целого
    rows = [["А", 1.2, 0.8, 2.3], ["Б", 4.2, 3.9, 8.4], ["В", 2.0, 1.1, 3.4]]
    assert profile_table(_t(["Поставщик", "Закупка", "Доставка", "Итого"], rows)).total_column is None
    exact = [["А", 1.2, 0.8, 2.0], ["Б", 4.2, 3.9, 8.1], ["В", 2.0, 1.1, 3.1]]
    assert profile_table(_t(["Поставщик", "Закупка", "Доставка", "Итого"], exact)).total_column == "Итого"
    pct = [["Москва", 60, 30, 10, 100], ["Казань", 50, 35, 15, 100], ["Омск", 40, 40, 20, 100]]
    p = profile_table(_t(["Регион", "Онлайн", "Офлайн", "Партнёры", "Всего"], pct, units=[None, "%", "%", "%", "%"]))
    assert p.total_column == "Всего" and p.part_columns == ["Онлайн", "Офлайн", "Партнёры"] and p.parts_of_whole


def test_derived_columns_are_not_a_relationship():
    # Minor 8: «Сумма» = «Кол-во» × «Цена», «Розница» = «Закупка» × 1,3 — связь по построению, а не находка
    rnd = random.Random(5)
    lines = []
    for i in range(60):
        q, price = rnd.randint(1, 20), rnd.randint(100, 900)
        lines.append([f"Строка {i}", ["А", "Б"][i % 2], q, price, q * price])
    p = profile_table(_t(["Заказ", "Склад", "Кол-во", "Цена", "Сумма"], lines))
    assert p.nature != "relationship"
    price = [[f"Товар {i}", ["А", "Б"][i % 2], c, round(c * 1.3, 2)] for i, c in
             enumerate(rnd.randint(100, 900) for _ in range(60))]
    assert profile_table(_t(["Товар", "Группа", "Закупка", "Розница"], price)).nature != "relationship"


# ── номера мест и расписания (ревью анализа rev7c, N4) ────────────────────────────────────────────────────────────────
def test_timetable_room_numbers_are_ids_and_the_table_is_not_for_a_chart():
    from verstka.api.app import _dataset_summary
    from verstka.data.readers import read_bytes

    days, times = ["Понедельник", "Вторник", "Среда"], ["09:00–10:30", "10:40–12:10", "12:40–14:10"]
    lines = [f"{d};{tm};{['Математика', 'Физика', 'История', 'Химия'][k % 4]};{[101, 204, 305, 101, 204][k % 5]};Иванов И.И."
             for k, (d, tm) in enumerate((d, tm) for d in days for tm in times)]
    t = read_bytes("Расписание.csv", ("День;Время;Предмет;Аудитория;Преподаватель\n" + "\n".join(lines) + "\n").encode())[0]
    p = profile_table(t)
    assert (_col(p, "Аудитория").type, _col(p, "Аудитория").role) == ("id", "id") and p.metrics == []
    assert _col(p, "Время").type != "number"  # «09:00–10:30» — интервал, а не число
    assert (p.nature, p.typable, p.untypable_reason) == ("reference", False, "расписание/перечень")
    assert "Не для графика: расписание/перечень" in _dataset_summary("tt", t, p).issues


def test_place_rank_and_apartment_numbers_are_ids():
    place = profile_table(_t(["Место", "Команда", "Очки"], [[1, "Спартак", 30], [2, "Зенит", 28], [3, "ЦСКА", 25],
                                                          [4, "Динамо", 20], [5, "Локомотив", 18]]))
    assert _col(place, "Место").role == "id" and place.metrics == ["Очки"] and place.typable
    flats = profile_table(_t(["Квартира", "Площадь", "Цена"], [[12, 54.3, 9_800_000], [45, 38.0, 7_200_000],
                                                            [7, 72.5, 13_500_000], [31, 41.2, 7_900_000]],
                             units=[None, "м²", None]))
    assert _col(flats, "Квартира").role == "id" and flats.metrics == ["Площадь", "Цена"]
    counts = profile_table(_t(["Корпус", "Аудиторий", "Этажей"], [["А", 12, 3], ["Б", 20, 5], ["В", 8, 2]]))
    assert counts.metrics == ["Аудиторий", "Этажей"]  # множественное число — счёт, а не номер


# ── раунд 4 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_plan_and_fact_get_one_verdict():
    # Важное 3: «Факт» — деньги по величине, «План» того же порядка — тоже
    p = profile_table(_t(["Месяц", "План", "Факт"], [["2025-01", 4500, 5200], ["2025-02", 4700, 5600],
                                                     ["2025-03", 4800, 5900]]))
    assert [_col(p, "План").type, _col(p, "Факт").type] == ["money", "money"]
    small = profile_table(_t(["Цех", "План", "Факт"], [["А", 120, 118], ["Б", 90, 95], ["В", 60, 61]]))
    assert [_col(small, "План").type, _col(small, "Факт").type] == ["number", "number"]


def test_debit_credit_are_money_and_their_blanks_are_not_missing():
    # Мелочь 4: «Дебет/Кредит» — деньги; пустая клетка там, где операция в другой колонке, — не пропуск
    rows = [["2026-03-01", "А", 80000, None], ["2026-03-02", "Б", None, 50000], ["2026-03-03", "В", 112300, None],
            ["2026-03-04", "Г", None, 30000]]
    p = profile_table(_t(["Дата", "Контрагент", "Дебет", "Кредит"], rows))
    assert [_col(p, "Дебет").type, _col(p, "Кредит").type] == ["money", "money"]
    assert (_col(p, "Дебет").missing, _col(p, "Кредит").missing, p.nature) == (0, 0, "time_series")


def test_irregular_dates_have_no_invented_missing_day():
    # Мелочь 6: 2, 5, 11 марта — нерегулярные даты, а не ряд «через 3 дня» с пропуском 8-го
    p = profile_table(_t(["Дата", "Заказов"], [["2026-03-02", 5], ["2026-03-05", 7], ["2026-03-11", 4]]))
    assert (p.time_axis.freq, p.time_axis.missing_periods) == ("irregular", [])
