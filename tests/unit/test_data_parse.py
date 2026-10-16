"""Общий разбор ячеек (verstka/data/parse.py): числа и единицы, десятичный знак колонки, даты и периоды с зернистостью,
даты Excel числами, пропуски, логические значения и строгое правило строки итога. Чтение и профиль берут всё отсюда."""

from __future__ import annotations

import datetime as dt

import pytest

from verstka.data.parse import (
    BOOL,
    MISSING,
    dayfirst_hint,
    decimal_hint,
    excel_serial_iso,
    is_missing,
    is_total_label,
    iso_ord,
    parse_number,
    parse_period,
    parse_quantity,
    period_iso,
    period_parts,
    quantity,
    split_unit,
)


@pytest.mark.parametrize(
    "cell, value, unit, full",
    [
        ("1 234,5", 1234.5, None, 1234.5),
        ("1 234 567", 1234567.0, None, 1234567.0),
        ("1.234.567,8", 1234567.8, None, 1234567.8),
        ("(15)", -15.0, None, -15.0),
        ("1e3", 1000.0, None, 1000.0),
        ("−12,5", -12.5, None, -12.5),
        ("+23%", 23.0, "%", 23.0),
        ("1,24 млрд ₽", 1.24, "млрд ₽", 1.24e9),
        ("356 тыс. ₽", 356.0, "тыс. ₽", 356000.0),
        ("$1,200", 1200.0, "$", 1200.0),
        ("5K", 5.0, "тыс.", 5000.0),
        ("+6 п.", 6.0, "п.", 6.0),
        ("120 мин", 120.0, "мин", 120.0),
    ],
)
def test_quantity(cell, value, unit, full):
    q = quantity(cell)
    assert (q.value, q.unit, q.full) == (value, unit, full)
    assert parse_quantity(cell) == (value, unit) and parse_number(cell) == value


@pytest.mark.parametrize("cell", ["", "+", "-", "*", "$", "₽", "~", "()", "≈", "(+)", "$-", "1²", "SUP-48213",
                                  "2025-01", "007", "15-20", "1,2,3", "∞", "0x1F", "<5"])
def test_not_numbers_and_no_crash(cell):
    assert quantity(cell) is None and parse_number(cell) is None


def test_plus_sign_money_and_percent_flags():
    assert quantity("+23%").plus and quantity("+23%").pct and not quantity("23%").plus
    assert quantity("1,2 млн ₽").money and quantity("2,5 п.п.").pct and not quantity("120 мин").money


def test_decimal_hint_by_column():
    assert decimal_hint(["1 234,5", "17"]) == "," and decimal_hint(["0.25", "1.5"]) == "."
    # одна группа из трёх цифр + «…00» или целые от 100 — разделитель тысяч
    assert decimal_hint(["1.234", "2.500", "12.000", "950"]) == ","
    assert decimal_hint(["1,234", "2,500", "950"]) is None  # запятая с тремя знаками — дробь («75,500»)
    assert decimal_hint(["1.234", "2.345"]) is None  # неясно — решает запись
    assert decimal_hint(["1.234", "2.500"], ".") == "."  # CSV через запятую: точка — дробь


def test_dayfirst_hint():
    assert dayfirst_hint(["02/03/2025", "25/03/2025"]) is True
    assert dayfirst_hint(["02/03/2025", "03/25/2025"]) is False
    assert dayfirst_hint(["01/02/2025"]) is True and dayfirst_hint(["01/02/2025"], english=True) is False
    assert dayfirst_hint(["01.02.2025"], english=True) is True  # точки пишут день первым


@pytest.mark.parametrize(
    "text, iso",
    [("янв 2025", "2025-01"), ("Январь 2025", "2025-01"), ("сентябрь 2026", "2026-09"), ("янв.25", "2025-01"),
     ("IV кв. 2025", "2025-Q4"), ("Q1'26", "2026-Q1"), ("3-й квартал 2025", "2025-Q3"), ("2025, II кв.", "2025-Q2"),
     ("31.01.2025", "2025-01-31"), ("31 января 2025 г.", "2025-01-31"), ("2025 г.", "2025"), ("2025-W03", "2025-W03"),
     ("31.01.2025 10:30", "2025-01-31T10:30"), ("2025.01", "2025-01"), ("марка 2025", None), ("2025-W53", None),
     ("Январь", None), ("abc", None)],
)
def test_parse_period(text, iso):
    assert parse_period(text) == iso


def test_period_parts_and_iso_round_trip():
    for text, gran, back in [("2025", "year", "2025"), ("2025-Q4", "quarter", "2025-Q4"), ("2025-03", "month", "2025-03"),
                             ("2025-W05", "week", "2025-W05"), ("2025-01-31", "day", "2025-01-31"),
                             ("IV кв. 2025", "quarter", "2025-Q4")]:
        g, o = period_parts(text)
        assert g == gran and period_iso(g, o) == back
    assert period_parts("2025-01-31T10:30") == ("day", dt.date(2025, 1, 31).toordinal())
    g, o = period_parts("2025-01-31T10:30", with_time=True)
    assert g == "hour" and period_iso(g, o) == "2025-01-31T10:00"
    assert period_parts("2025-01-31T00:00", with_time=True)[0] == "day"  # полночь — день
    assert iso_ord("2025-q1") == ("quarter", 2025 * 4) and iso_ord("2025-13") is None and iso_ord("Москва") is None


def test_excel_serial_dates():
    assert excel_serial_iso(45658) == "2025-01-01" and excel_serial_iso(45658.5) == "2025-01-01T12:00"
    assert excel_serial_iso(2025) is None and excel_serial_iso(99999) is None and excel_serial_iso(True) is None
    assert excel_serial_iso(45658, dt.datetime(1904, 1, 1)) == "2029-01-02"  # книга Mac считает от 1904 года


def test_missing_and_bool_tokens_are_shared():
    for tok in ["", "—", "н/д", "#DIV/0!", "#REF!", "#Н/Д", "NA", "NaN", "null", "нет данных"]:
        assert is_missing(tok), tok
        assert tok.strip().lower() in MISSING
    assert not is_missing("0") and not is_missing("Москва") and is_missing(None) and is_missing(float("nan"))
    assert BOOL["да"] is True and BOOL["нет"] is False and BOOL["yes"] is True


@pytest.mark.parametrize(
    "label, total",
    [("Итого", True), ("ИТОГО:", True), ("Всего", True), ("Всего:", True), ("Итого по России", True),
     ("Всего за 2025 год", True), ("Total", True), ("Grand total", True), ("В целом по компании", True),
     ("Общий итог", True), ("Общая сумма", True), ("Итого, млн ₽", True), ("Итого общее", True),
     ("Всего клиентов", False), ("Итого выручка", False), ("Всего лишь пробный", False), ("Итоговый отчёт", False),
     ("Москва", False), (None, False), (100, False)],
)
def test_strict_total_rule(label, total):
    assert is_total_label(label) is total


def test_split_unit():
    assert split_unit("Выручка, млн ₽") == ("Выручка", "млн ₽") and split_unit("Доля (%)") == ("Доля", "%")
    assert split_unit("Город, регион") == ("Город, регион", None) and split_unit("2023, млн ₽") == ("2023", "млн ₽")
    # счётные слова и темп: «Scopus, статей», «Подготовка (ч в неделю)», «Зарплата, руб. в месяц»
    assert split_unit("Scopus, статей") == ("Scopus", "статей") and split_unit("Приём, человек") == ("Приём", "чел.")
    assert split_unit("Подготовка (ч в неделю)") == ("Подготовка", "ч/нед.")
    assert split_unit("Зарплата, руб. в месяц") == ("Зарплата", "₽/мес.")
    assert split_unit("Выручка за месяц") == ("Выручка за месяц", None)  # «за месяц» без единицы — часть имени
