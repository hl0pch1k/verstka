"""Чтение файлов с данными (verstka/data/readers.py, описание решения §2.1): семь файлов примера продаж, крайние случаи
(кодировки, разделители, десятичная запятая, единицы, шапка не в первой строке, несколько листов, даты Excel, JSON
разных форм, таблицы в тексте), человеческие ошибки и скорость на 100 тысячах строк."""

from __future__ import annotations

import datetime as dt
import io
import json
import random
import time
from pathlib import Path

import openpyxl
import pytest

from verstka.data.readers import (
    DataReadError,
    parse_number,
    parse_period,
    parse_quantity,
    read_bytes,
    read_file,
    split_unit,
)
from verstka.schemas.data import Table

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
FIX = ROOT / "tests" / "fixtures" / "data"


def one(path: Path) -> Table:
    tables = read_file(path)
    assert len(tables) == 1, [t.sheet for t in tables]
    return tables[0]


def col(t: Table, name: str) -> list:
    return t.column_values(name)


# ------------------------------------------------------------------------------------------------ пример продаж


def test_revenue_by_month_csv():
    t = one(SALES / "Выручка по месяцам.csv")
    assert t.kind == "csv" and t.sheet is None and t.file == "Выручка по месяцам.csv"
    assert t.columns == ["Месяц", "Выручка", "Клиентов"]
    assert t.units == [None, "млн ₽", None]
    assert t.raw_header == ["Месяц", "Выручка, млн ₽", "Клиентов"]
    assert len(t.rows) == 21
    assert t.rows[0] == ["2025-01-01", 296, 2610] and t.rows[-1] == ["2026-09-01", 423, 3480]
    assert all(isinstance(v, int) for v in col(t, "Выручка"))


def test_regions_xlsx():
    t = one(SALES / "Регионы.xlsx")
    assert t.kind == "xlsx" and t.sheet is None  # один лист — одна таблица
    assert t.columns == ["Регион", "Выручка", "Рост"] and t.units == [None, "млн ₽", "%"]
    assert len(t.rows) == 8
    assert t.rows[0] == ["Москва", 1433, 19]
    assert max(col(t, "Рост")) == 38 and col(t, "Регион")[col(t, "Рост").index(38)] == "Казань"


def test_sales_channels_json():
    t = one(SALES / "Каналы продаж.json")
    assert t.kind == "json"
    assert t.columns == ["Канал", "Выручка", "Доля", "Сделок"]
    assert t.units == [None, "млн ₽", "%", None]
    assert col(t, "Канал") == ["Прямые продажи", "Партнёры", "Маркетплейс", "Онлайн"]
    assert sum(col(t, "Доля")) == 100


def test_support_response_csv():
    t = one(SALES / "Время ответа поддержки.csv")
    assert t.columns == ["Обращение", "Минут до ответа"]
    assert len(t.rows) == 512
    minutes = col(t, "Минут до ответа")
    assert all(isinstance(v, int) for v in minutes)
    assert sum(v > 600 for v in minutes) == 3
    assert col(t, "Обращение")[0] == "SUP-48213"  # номер обращения — строка, не число


def test_clients_xlsx():
    t = one(SALES / "Клиенты.xlsx")
    assert t.columns == ["Клиент", "Отрасль", "Регион", "Выручка", "Тариф", "Дата договора"]
    assert t.units == [None, None, None, "млн ₽", None, None]
    assert len(t.rows) == 240
    assert t.rows[0] == ["АО «Северный капитал»", "Банки и финансы", "Москва", 212.4, "Корпоративный", "2019-11-14"]
    assert all(isinstance(v, str) and len(v) == 10 for v in col(t, "Дата договора"))


def test_nps_by_quarter_with_gaps():
    t = one(SALES / "NPS по кварталам.csv")
    assert t.columns == ["Квартал", "NPS", "Ответов"]
    assert col(t, "Квартал") == ["2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"]
    assert col(t, "NPS") == [41, 43, None, 46, 47, 49, None, 52]  # пропуск — None, а не ноль
    assert t.rows[2] == ["2025-Q2", None, None]


def test_quarter_results_text_table():
    t = one(SALES / "Итоги квартала.txt")
    assert t.kind == "text"
    assert t.columns == ["Показатель", "III кв. 2026", "III кв. 2025", "Изменение"]
    assert col(t, "Показатель") == ["Выручка", "Клиенты", "Средний чек", "NPS"]
    # у каждой строки своя единица — ячейки как в файле, число и единицу даёт parse_quantity
    assert col(t, "III кв. 2026") == ["1,24 млрд ₽", "3 480", "356 тыс. ₽", "52"]
    assert [parse_quantity(v) for v in col(t, "Изменение")] == [(23.0, "%"), (18.0, "%"), (4.0, "%"), (6.0, "п.")]
    assert parse_quantity(t.rows[0][1]) == (1.24, "млрд ₽")
    # текст вокруг таблицы — контекст
    assert "Подготовлено для правления" in t.notes and "Казани и Краснодара" in t.notes
    assert "|" not in t.notes


def test_all_sample_files_read_and_ids_are_unique():
    tables = [t for p in sorted(SALES.iterdir()) if p.suffix != ".md" for t in read_file(p)]
    assert len(tables) == 7
    assert len({t.id for t in tables}) == 7
    assert [t.id for t in read_file(SALES / "Регионы.xlsx")] == [t.id for t in read_file(SALES / "Регионы.xlsx")]
    for t in tables:  # таблицы проходят валидацию контракта и не теряют типы через JSON
        again = Table.model_validate_json(t.model_dump_json())
        assert again.rows == t.rows and again.units == t.units


# ------------------------------------------------------------------------------------------------ числа, периоды, единицы


@pytest.mark.parametrize(
    "text, value",
    [
        ("1 234,5", 1234.5), ("1 234,5", 1234.5), ("1 234 567", 1234567), ("46 %", 46), ("46%", 46),
        ("+23%", 23), ("−12", -12), ("-12,5", -12.5), ("(15)", -15), ("1,2 млн ₽", 1.2), ("356 тыс. ₽", 356),
        ("1 234 руб.", 1234), ("$1,234.56", 1234.56), ("1.234,56", 1234.56), ("1,234,567", 1234567),
        ("0,5", 0.5), (",5", 0.5), ("1e5", 100000), ("+6 п.", 6), ("25 мин", 25), ("12", 12), (7, 7), (2.5, 2.5),
        ("SUP-48213", None), ("2025-01", None), ("Москва", None), ("007", None), ("8 800 555 35 35", None),
        ("10:30", None), ("1/2", None), ("12345678901234567", None), ("", None), (None, None), (True, None),
    ],
)
def test_parse_number(text, value):
    assert parse_number(text) == value


@pytest.mark.parametrize(
    "text, iso",
    [
        ("янв 2025", "2025-01"), ("Январь 2025", "2025-01"), ("январь 2025 г.", "2025-01"), ("янв. 25", "2025-01"),
        ("Jan 2025", "2025-01"), ("2025-01", "2025-01"), ("01.2025", "2025-01"), ("май 2025", "2025-05"),
        ("IV кв. 2025", "2025-Q4"), ("I кв. 2026", "2026-Q1"), ("Q1 2026", "2026-Q1"), ("1Q 2026", "2026-Q1"),
        ("2026-Q1", "2026-Q1"), ("1 квартал 2026", "2026-Q1"), ("III квартал 2025 года", "2025-Q3"),
        ("2025", "2025"), ("2025 г.", "2025"), ("31.01.2025", "2025-01-31"), ("31.01.25", "2025-01-31"),
        ("2025-01-31", "2025-01-31"), ("2025-01-31 00:00:00", "2025-01-31"), ("31 января 2025", "2025-01-31"),
        ("2025-01-31T10:30:00", "2025-01-31T10:30"), (dt.date(2025, 3, 8), "2025-03-08"), (2025, "2025"),
        ("30.02.2025", None), ("1.02", None), ("Москва", None), ("1850", None), ("IV кв.", None), (None, None),
    ],
)
def test_parse_period(text, iso):
    assert parse_period(text) == iso


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Выручка, млн ₽", ("Выручка", "млн ₽")), ("Доля (%)", ("Доля", "%")), ("Доля, %", ("Доля", "%")),
        ("Цена, руб.", ("Цена", "₽")), ("Количество, шт.", ("Количество", "шт.")),
        ("Выручка, млн. руб.", ("Выручка", "млн ₽")), ("Выручка [млн руб]", ("Выручка", "млн ₽")),
        ("Доля в %", ("Доля", "%")), ("Рост %", ("Рост", "%")), ("Выручка млн ₽", ("Выручка", "млн ₽")),
        ("Население, тыс. чел.", ("Население", "тыс. чел.")), ("Скорость, км/ч", ("Скорость", "км/ч")),
        ("Тариф, ₽/мес.", ("Тариф", "₽/мес.")), ("Выручка, млн ₽, план", ("Выручка, план", "млн ₽")),
        ("Рост, п.п.", ("Рост", "п.п.")), ("Сумма, т.р.", ("Сумма", "тыс. ₽")),
        # скобки и запятые без единицы остаются в имени
        ("Выручка (план)", ("Выручка (план)", None)), ("Город, регион", ("Город, регион", None)),
        ("Минут до ответа", ("Минут до ответа", None)), ("III кв. 2026", ("III кв. 2026", None)),
        ("Выручка (2025)", ("Выручка (2025)", None)), ("", ("", None)),
    ],
)
def test_split_unit(header, expected):
    assert split_unit(header) == expected


# ------------------------------------------------------------------------------------------------ CSV: крайние случаи


def test_cp1251_semicolon_decimal_comma_title_total_and_footnote():
    t = one(FIX / "sales_cp1251.csv")
    assert t.columns == ["Канал", "Выручка", "Доля", "Рост", "Комментарий"]  # пустая колонка ушла
    assert t.units == [None, "₽", "%", "%", None]  # «руб.» → ₽, «46 %» → % из ячеек
    assert col(t, "Канал") == ["Прямые продажи", "Партнёры", "Маркетплейс", "Онлайн"]  # «Итого» — не данные
    assert col(t, "Выручка") == [1608000.5, 978250.0, 594000, None]  # «—» — пропуск
    assert col(t, "Доля") == [46, 28, 17, 9]
    assert col(t, "Рост") == [12.5, -3.1, None, 0]  # «н/д» — пропуск
    assert t.notes.splitlines() == ["Продажи по каналам за 2025 год", "* Данные по закрытым актам, без НДС."]


def test_comma_csv_with_quoted_thousands_and_english_months():
    t = one(FIX / "revenue_en.csv")
    assert t.columns == ["Month", "Revenue", "Users"] and t.units == [None, "$", None]
    assert t.rows == [["2025-01", 1234.5, 1200], ["2025-02", 2345.25, 1350], ["2025-03", 12000, 1410]]


def test_two_row_header_is_merged():
    t = one(FIX / "two_row_header.csv")
    assert t.columns == ["Регион", "Выручка 2024", "Выручка 2025", "Клиенты 2024", "Клиенты 2025"]
    assert t.units == [None, "млн ₽", "млн ₽", None, None]
    assert t.rows[0] == ["Москва", 1210, 1433, 1480, 1650]


def test_units_row_under_header():
    t = read_bytes("u.csv", "Месяц;Выручка;Клиенты\n;млн ₽;чел.\nянв 2025;296;2610\nфев 2025;301;2648\n".encode())[0]
    assert t.columns == ["Месяц", "Выручка", "Клиенты"] and t.units == [None, "млн ₽", "чел."]
    assert t.rows == [["2025-01", 296, 2610], ["2025-02", 301, 2648]]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-le", "cp1251", "koi8_r", "cp866"])
def test_encodings(encoding):
    text = "Регион;Выручка, млн руб.\nМосква;1 433\nНижний Новгород;198\nЕкатеринбург;318\n"
    t = read_bytes("e.csv", text.encode(encoding))[0]
    assert t.columns == ["Регион", "Выручка"] and t.units == [None, "млн ₽"]
    assert col(t, "Регион") == ["Москва", "Нижний Новгород", "Екатеринбург"]


def test_header_detection_without_header_and_with_pandas_index():
    t = read_bytes("n.csv", b"1;2;3\n4;5;6\n")[0]
    assert t.columns == ["Колонка 1", "Колонка 2", "Колонка 3"] and t.rows == [[1, 2, 3], [4, 5, 6]]
    t = read_bytes("p.csv", b",Value\n0,10\n1,20\n2,30\n")[0]
    assert t.columns == ["Value"] and t.rows == [[10], [20], [30]]  # безымянная нумерация строк — не данные
    t = read_bytes("d.csv", b",Value\n2025-01-01,10\n2025-02-01,20\n")[0]
    assert t.columns == ["Дата", "Value"]  # безымянная ось времени получает имя


def test_wide_header_with_years_and_year_column():
    t = read_bytes("w.csv", "Регион;2023;2024;2025\nМосква;1200;1300;1433\nКазань;200;250;274\n".encode())[0]
    assert t.columns == ["Регион", "2023", "2024", "2025"] and t.rows[0] == ["Москва", 1200, 1300, 1433]
    t = read_bytes("y.csv", "Год;Выручка\n2024;10\n2025;12\n".encode())[0]
    assert col(t, "Год") == ["2024", "2025"]  # годы под «Год» — периоды
    t = read_bytes("y2.csv", "Регион;Выручка\nМосква;2024\nКазань;1999\n".encode())[0]
    assert col(t, "Выручка") == [2024, 1999]  # без «года» в шапке — числа


def test_typing_codes_booleans_scales_and_mixed_units():
    t = read_bytes("c.csv", "Код;Ответ;Сумма;Итог\n001;да;1,2 млн ₽;5 %\n002;нет;800 тыс. ₽;7 п.\n010;да;900 тыс. ₽;9 %\n".encode())[0]
    assert col(t, "Код") == ["001", "002", "010"]  # ведущие нули — код, не число
    assert col(t, "Ответ") == [True, False, True]
    assert col(t, "Сумма") == [1200, 800, 900] and t.unit_of("Сумма") == "тыс. ₽"  # к общему множителю
    assert col(t, "Итог") == ["5 %", "7 п.", "9 %"]  # разные единицы — как в файле


def test_day_first_and_month_first_dates():
    t = read_bytes("d.csv", b"Date;V\n02/03/2025;1\n25/03/2025;2\n")[0]
    assert col(t, "Date") == ["2025-03-02", "2025-03-25"]
    t = read_bytes("d.csv", b"Date;V\n02/03/2025;1\n03/25/2025;2\n")[0]
    assert col(t, "Date") == ["2025-02-03", "2025-03-25"]


def test_duplicate_and_empty_header_names():
    t = read_bytes("d.csv", "Регион;Выручка;Выручка;\nМосква;1;2;3\nКазань;4;5;6\n".encode())[0]
    assert t.columns == ["Регион", "Выручка", "Выручка (2)", "Колонка 4"]


def test_messy_exports():
    # шапка «1 тур, 2 тур» — названия, а не числа
    t = read_bytes("t.csv", "Команда;1 тур;2 тур\nАльфа;3;1\nБета;1;1\n".encode())[0]
    assert t.columns == ["Команда", "1 тур", "2 тур"] and t.rows[0] == ["Альфа", 3, 1]
    # таблица со второй колонки и заголовок отчёта над ней
    t = read_bytes("o.csv", ";Отчёт;\n;;\n;Регион;Выручка\n;Москва;5\n;Казань;6\n".encode())[0]
    assert t.columns == ["Регион", "Выручка"] and t.notes == "Отчёт"
    # склеенные выгрузки повторяют шапку; сноска из двух ячеек
    t = read_bytes("r.csv", "Регион;Выручка\nМосква;5\nРегион;Выручка\nКазань;6\nИсточник:;CRM\n".encode())[0]
    assert t.rows == [["Москва", 5], ["Казань", 6]] and t.notes == "Источник: CRM"
    # «sep=;» от Excel и перенос строки внутри заголовка
    t = read_bytes("s.csv", 'sep=;\nРегион;"Выручка,\nмлн ₽"\nМосква;"1 433,5"\n'.encode())[0]
    assert t.columns == ["Регион", "Выручка"] and t.units == [None, "млн ₽"] and t.rows == [["Москва", 1433.5]]
    assert t.raw_header == ["Регион", "Выручка, млн ₽"]
    # «Всего лишь» — не строка итога
    t = read_bytes("v.csv", "Тариф;Клиентов\nСтарт;5\nВсего лишь пробный;2\n".encode())[0]
    assert len(t.rows) == 2


def test_text_disguised_as_excel_and_cover_sheet():
    t = read_bytes("export.xls", "Регион\tВыручка\nМосква\t5\nКазань\t6\n".encode("cp1251"))[0]
    assert t.columns == ["Регион", "Выручка"] and t.rows == [["Москва", 5], ["Казань", 6]]
    with pytest.raises(DataReadError, match="страница HTML"):
        read_bytes("export.xls", b"<html><table><tr><td>1</td></tr></table></html>")
    wb = openpyxl.Workbook()
    wb.active.title = "Титул"
    wb.active.append(["Отчёт о продажах за 9 месяцев"])
    wb.active.append(["Подготовлено для правления"])
    data = wb.create_sheet("Данные")
    for r in (["Регион", "Выручка"], ["Москва", 5], ["Казань", 6]):
        data.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    tables = read_bytes("c.xlsx", buf.getvalue())
    assert [t.columns for t in tables] == [["Регион", "Выручка"]]  # титульный лист — не данные


def test_cells_are_plain_json_types():
    files = [p for p in sorted(FIX.iterdir()) if p.name not in ("empty.csv", "empty_sheet.xlsx", "no_table.txt")]
    files += [p for p in sorted(SALES.iterdir()) if p.suffix != ".md"]
    for path in files:
        for t in read_file(path):
            assert len(t.columns) == len(t.units) == len(t.raw_header), path.name
            for row in t.rows:
                assert len(row) == len(t.columns), path.name
                assert all(v is None or type(v) in (bool, int, float, str) for v in row), (path.name, row)


def test_big_csv_is_fast():
    rnd = random.Random(7)
    regions = ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург", "Новосибирск", "Краснодар"]
    lines = ["Дата;Регион;Выручка, млн ₽;Клиентов;Доля, %;Комментарий"]
    for i in range(100_000):
        d = dt.date(2020, 1, 1) + dt.timedelta(days=i % 2000)
        v = format(rnd.random() * 20000, ",.1f").replace(",", " ").replace(".", ",")
        share = str(round(rnd.random() * 100, 1)).replace(".", ",")
        lines.append(f"{d:%d.%m.%Y};{rnd.choice(regions)};{v};{rnd.randint(1, 5000)};{share};заказ {i}")
    data = "\r\n".join(lines).encode("utf-8")
    best = 1e9
    for _ in range(2):
        start = time.perf_counter()
        t = read_bytes("big.csv", data)[0]
        best = min(best, time.perf_counter() - start)
    assert best < 2.0, f"{best:.2f} с"
    assert len(t.rows) == 100_000
    assert t.units == [None, None, "млн ₽", None, "%", None]
    assert t.rows[0][0] == "2020-01-01" and isinstance(t.rows[0][2], float) and isinstance(t.rows[0][3], int)


# ------------------------------------------------------------------------------------------------ XLSX


def test_workbook_with_several_sheets_dates_and_formats():
    tables = read_file(FIX / "workbook.xlsx")
    assert [t.sheet for t in tables] == ["Продажи", "Регионы"]  # пустой и скрытый листы — не таблицы
    sales, regions = tables
    assert sales.notes == "Продажи по месяцам"  # объединённый заголовок над шапкой
    assert sales.columns == ["Месяц", "Выручка", "Маржа", "Средний чек"]
    assert sales.units == [None, None, "%", "₽"]  # из формата ячейки: 0.0% и «₽»
    assert col(sales, "Месяц") == ["2025-01-01", "2025-02-01", "2025-03-01"]  # даты Excel → ISO
    assert col(sales, "Маржа") == [21.4, 22, 20.5]
    assert regions.rows == [["Москва", 1433, "2019-11-14"], ["Казань", 274, "2021-06-21"]]  # без «Итого»
    assert len({t.id for t in tables}) == 2


def test_empty_workbook_and_broken_xlsx():
    with pytest.raises(DataReadError, match="^Лист без данных$"):
        read_file(FIX / "empty_sheet.xlsx")
    with pytest.raises(DataReadError, match="повреждён"):
        read_bytes("x.xlsx", b"PK\x03\x04 not really a zip")


def test_xlsx_years_column_and_percent_strings():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Год", "Доля"])
    ws.append([2024, "46 %"])
    ws.append([2025, "54 %"])
    buf = io.BytesIO()
    wb.save(buf)
    t = read_bytes("y.xlsx", buf.getvalue())[0]
    assert t.rows == [["2024", 46], ["2025", 54]] and t.units == [None, "%"]


# ------------------------------------------------------------------------------------------------ JSON


def test_json_records_columns_rows_keyed_and_categories():
    t = one(FIX / "records.json")
    assert t.columns == ["Канал", "Выручка", "Доля"] and t.units == [None, "млн ₽", "%"] and len(t.rows) == 4

    t = one(FIX / "columns_rows.json")
    assert t.columns == ["Регион", "Выручка", "Рост"] and t.units == [None, "млн ₽", "%"]
    assert t.rows[-1] == ["Сочи", 95, None] and t.notes == "title: Регионы"

    tables = read_file(FIX / "keyed.json")
    assert [t.sheet for t in tables] == ["Регионы", "Каналы"]
    assert tables[0].units == [None, "млн ₽"] and tables[1].rows == [["Онлайн", 9], ["Партнёры", 91]]
    assert tables[0].notes == "source: CRM, выгрузка 6 октября 2026"

    t = one(FIX / "categories.json")
    assert t.columns == ["Категория", "Значение"] and t.rows[0] == ["Прямые продажи", 46]


def test_json_other_shapes():
    def rd(obj, name="x.json"):
        return read_bytes(name, json.dumps(obj, ensure_ascii=False).encode())

    t = rd({"Месяц": ["2025-01", "2025-02"], "Выручка": [296, 301]})[0]  # колонки-массивы
    assert t.rows == [["2025-01", 296], ["2025-02", 301]]
    t = rd([["Регион", "Выручка"], ["Москва", 1433], ["Казань", 274]])[0]  # массив строк
    assert t.columns == ["Регион", "Выручка"] and t.rows[1] == ["Казань", 274]
    t = rd({"Выручка": {"Москва": 1433, "Казань": 274, "Сочи": 95}, "Рост": {"Москва": 19, "Казань": 38, "Сочи": 7}})[0]
    assert t.columns == ["Категория", "Выручка", "Рост"] and t.rows[1] == ["Казань", 274, 38]
    t = rd({"meta": {"page": 1}, "data": [{"a": 1}, {"a": 2}]})[0]  # обёртка API: метаданные — не таблица
    assert t.columns == ["a"] and t.rows == [[1], [2]]
    t = read_bytes("l.jsonl", b'{"a": 1, "b": 2}\n{"a": 3, "b": 4}\n')[0]  # JSON Lines
    assert t.rows == [[1, 2], [3, 4]]


def test_json_errors():
    with pytest.raises(DataReadError, match="^Не получилось прочитать JSON: ошибка в строке 1"):
        read_bytes("bad.json", b'{"a": 1,, }')
    with pytest.raises(DataReadError, match="^В JSON нет таблицы"):
        read_bytes("n.json", b'{"name": "x", "tags": ["a", "b"]}')


# ------------------------------------------------------------------------------------------------ текст


def test_markdown_table_keeps_text_as_notes():
    t = one(FIX / "report.md")
    assert t.kind == "text"
    assert t.columns == ["Показатель", "III кв. 2026", "III кв. 2025", "Изменение"]
    assert col(t, "Показатель")[0] == "Выручка"  # **жирный** снят
    assert t.notes.startswith("# Итоги квартала") and t.notes.endswith("не проводился.")


def test_text_with_tab_block_and_aligned_columns():
    t = one(FIX / "tabs.txt")
    assert t.kind == "text" and t.columns == ["Месяц", "Выручка", "Клиентов"] and t.units == [None, "млн ₽", None]
    assert t.rows[0] == ["2025-01", 296, 2610]
    assert "вставлено из Excel" in t.notes and "прогноз" in t.notes

    t = one(FIX / "aligned.txt")
    assert t.columns == ["Квартал", "NPS", "Ответов"]
    assert t.rows == [["2025-Q1", 43, 287], ["2025-Q2", None, None], ["2025-Q3", 46, 341]]


def test_text_with_several_tables_and_whole_file_tables():
    text = "# Отчёт\n\n| Регион | Выручка |\n|---|---|\n| Москва | 1 433 |\n\n| Канал | Доля, % |\n| --- | --- |\n| Онлайн | 9 |\n"
    tables = read_bytes("two.md", text.encode())
    assert [t.sheet for t in tables] == ["Таблица 1", "Таблица 2"]
    assert tables[1].units == [None, "%"] and tables[0].notes == "# Отчёт"
    t = read_bytes("t.txt", "Месяц\tВыручка\nянв 2025\t296\nфев 2025\t301\n".encode())[0]
    assert t.kind == "tsv"  # весь файл — таблица: это не «таблица в тексте»
    t = read_bytes("c.txt", "Регион,Выручка\nМосква,1433\nКазань,274\n".encode())[0]
    assert t.kind == "csv" and t.rows[1] == ["Казань", 274]
    box = "┌────────┬─────────┐\n│ Регион │ Выручка │\n├────────┼─────────┤\n│ Москва │ 1433    │\n└────────┴─────────┘\n"
    assert read_bytes("b.txt", box.encode())[0].rows == [["Москва", 1433]]


# ------------------------------------------------------------------------------------------------ ошибки


@pytest.mark.parametrize(
    "name, data, message",
    [
        ("empty.csv", b"", "Файл пустой"),
        ("blank.csv", b"\n \n\n", "Файл пустой"),
        ("h.csv", "Регион;Выручка\n".encode(), "В таблице только заголовок — строк с данными нет"),
        ("no.txt", (FIX / "no_table.txt").read_bytes(), "Не нашёл таблицу в тексте"),
        ("old.xls", b"\xd0\xcf\x11\xe0", "Старый формат Excel (.xls) не читается — сохраните файл как .xlsx или .csv"),
        ("deck.pdf", b"%PDF-1.4", "Файлы .pdf с данными не читаю — приложите таблицу как CSV, XLSX, JSON или текст с таблицей"),
        ("bin.csv", bytes(range(256)) * 20, "Файл не похож на таблицу: внутри двоичные данные, а не текст"),
    ],
)
def test_human_errors(name, data, message):
    with pytest.raises(DataReadError) as e:
        read_bytes(name, data)
    assert str(e.value) == message and e.value.file == name


def test_read_file_errors(tmp_path):
    with pytest.raises(DataReadError, match="^Файл пустой$"):
        read_file(FIX / "empty.csv")
    with pytest.raises(DataReadError, match="не найден"):
        read_file(tmp_path / "нет.csv")


# ------------------------------------------------------------------------------------------------ формат не меняет таблицу


def test_same_data_in_any_format_reads_the_same(tmp_path):
    xlsx = one(SALES / "Регионы.xlsx")
    header = ["Регион", "Выручка, млн ₽", "Рост, %"]
    # в cp1251 нет «₽» — там пишут «руб.»; единица всё равно та же
    csv_text = "Регион;Выручка, млн руб.;Рост, %\n" + "\n".join(";".join(str(v) for v in r) for r in xlsx.rows) + "\n"
    as_json = json.dumps([dict(zip(header, r)) for r in xlsx.rows], ensure_ascii=False)
    md = "| " + " | ".join(header) + " |\n|---|---|---|\n" + "\n".join(
        "| " + " | ".join(str(v) for v in r) + " |" for r in xlsx.rows) + "\n"
    for name, data in (("r.csv", csv_text.encode("cp1251")), ("r.json", as_json.encode()), ("r.md", md.encode())):
        t = read_bytes(name, data)[0]
        assert (t.columns, t.units, t.rows) == (xlsx.columns, xlsx.units, xlsx.rows), name
