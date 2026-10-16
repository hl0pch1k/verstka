"""Крайние случаи для tests/unit/test_data_readers.py. Файлы лежат в репозитории; пересоздать:
`../../.venv/bin/python tests/fixtures/data/make_fixtures.py` (книги Excel — двоичные, поэтому генератор рядом)."""
import datetime as dt
import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
out.mkdir(parents=True, exist_ok=True)
NB = " "

# 1. cp1251, «;», десятичная запятая, неразрывные пробелы в тысячах, «46 %», «руб.», заголовок отчёта над шапкой,
#    пустые строки, пустая колонка, пропуски «—»/«н/д», строка «Итого» и сноска
csv1 = "\r\n".join([
    "Продажи по каналам за 2025 год;;;;;",
    ";;;;;",
    "",
    "Канал;Выручка, руб.;Доля;Рост, %;;Комментарий",
    f"Прямые продажи;1{NB}608{NB}000,50;46 %;12,5;;крупные клиенты",
    f"Партнёры;978{NB}250,00;28 %;-3,1;;",
    f"Маркетплейс;594{NB}000;17 %;н/д;;новый канал",
    "Онлайн;—;9 %;0;;",
    "",
    f"Итого;3{NB}180{NB}250,50;100 %;;;",
    "* Данные по закрытым актам, без НДС.",
]) + "\r\n"
(out / "sales_cp1251.csv").write_bytes(csv1.encode("cp1251"))

# 2. CSV через запятую: дроби с точкой, тысячи запятой в кавычках, месяцы по-английски, доллары
csv2 = 'Month,"Revenue, $",Users\nJan 2025,"1,234.5",1200\nFeb 2025,"2,345.25",1350\nMar 2025,"12,000",1410\n'
(out / "revenue_en.csv").write_text(csv2, encoding="utf-8")

# 3. двухэтажная шапка: группы над годами
csv3 = ";Выручка, млн ₽;;Клиенты;\nРегион;2024;2025;2024;2025\nМосква;1 210;1 433;1 480;1 650\nКазань;198;274;310;402\nСочи;87;95;120;131\n"
(out / "two_row_header.csv").write_text(csv3, encoding="utf-8")

# 4. книга с несколькими листами: даты Excel, проценты и рубли по формату ячейки, заголовок над шапкой,
#    пустой и скрытый листы
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Продажи"
ws["A1"] = "Продажи по месяцам"
ws["A1"].font = Font(bold=True)
ws.merge_cells("A1:D1")
ws.append([])
ws.append(["Месяц", "Выручка", "Маржа", "Средний чек"])
for i, (rev, marg, check) in enumerate([(296.4, 0.214, 351000), (301.0, 0.22, 355500), (312.75, 0.205, 349990)]):
    ws.append([dt.datetime(2025, i + 1, 1), rev, marg, check])
    r = ws.max_row
    ws.cell(r, 1).number_format = "DD.MM.YYYY"
    ws.cell(r, 3).number_format = "0.0%"
    ws.cell(r, 4).number_format = '#,##0 "₽"'
ws2 = wb.create_sheet("Регионы")
ws2.append(["Регион", "Выручка, млн ₽", "Дата договора"])
ws2.append(["Москва", 1433, dt.date(2019, 11, 14)])
ws2.append(["Казань", 274, dt.date(2021, 6, 21)])
ws2.append(["Итого", 1707, None])
wb.create_sheet("Пусто")
ws4 = wb.create_sheet("Служебный")
ws4.append(["Ключ", "Значение"])
ws4.append(["a", 1])
ws4.sheet_state = "hidden"
wb.save(out / "workbook.xlsx")

wb = openpyxl.Workbook()
wb.active.title = "Лист1"
wb.save(out / "empty_sheet.xlsx")

# 5. JSON: массив записей, {columns, rows}, «ключ → записи», «категория → число»
(out / "records.json").write_text(json.dumps([
    {"Канал": "Прямые продажи", "Выручка, млн ₽": 1608, "Доля, %": 46},
    {"Канал": "Партнёры", "Выручка, млн ₽": 978, "Доля, %": 28},
    {"Канал": "Маркетплейс", "Выручка, млн ₽": 594, "Доля, %": 17},
    {"Канал": "Онлайн", "Выручка, млн ₽": 315, "Доля, %": 9},
], ensure_ascii=False, indent=2), encoding="utf-8")
(out / "columns_rows.json").write_text(json.dumps({
    "title": "Регионы",
    "columns": ["Регион", {"name": "Выручка", "unit": "млн ₽"}, "Рост, %"],
    "rows": [["Москва", 1433, 19], ["Казань", 274, 38], ["Сочи", 95, None]],
}, ensure_ascii=False, indent=2), encoding="utf-8")
(out / "keyed.json").write_text(json.dumps({
    "source": "CRM, выгрузка 6 октября 2026",
    "Регионы": [{"Регион": "Москва", "Выручка, млн ₽": 1433}, {"Регион": "Казань", "Выручка, млн ₽": 274}],
    "Каналы": [{"Канал": "Онлайн", "Доля, %": 9}, {"Канал": "Партнёры", "Доля, %": 91}],
}, ensure_ascii=False, indent=2), encoding="utf-8")
(out / "categories.json").write_text(json.dumps(
    {"Прямые продажи": 46, "Партнёры": 28, "Маркетплейс": 17, "Онлайн": 9}, ensure_ascii=False, indent=2,
), encoding="utf-8")

# 6. текст: Markdown-таблица в отчёте; блок через табуляцию; выровненные пробелами столбцы; без таблицы
(out / "report.md").write_text(
    "# Итоги квартала\n\nВыручка выросла на 23%, данные — по закрытым актам.\n\n"
    "| Показатель | III кв. 2026 | III кв. 2025 | Изменение |\n|---|---:|---:|---:|\n"
    "| **Выручка** | 1,24 млрд ₽ | 1,01 млрд ₽ | +23% |\n| Клиенты | 3 480 | 2 949 | +18% |\n"
    "| Средний чек | 356 тыс. ₽ | 342 тыс. ₽ | +4% |\n| NPS | 52 | 46 | +6 п. |\n\n"
    "Опрос NPS во II квартале не проводился.\n",
    encoding="utf-8",
)
(out / "tabs.txt").write_text(
    "Выручка по месяцам, вставлено из Excel.\n\nМесяц\tВыручка, млн ₽\tКлиентов\n"
    "Январь 2025\t296\t2 610\nФевраль 2025\t301\t2 648\nМарт 2025\t312\t2 702\n\nДальше — прогноз.\n",
    encoding="utf-8",
)
(out / "aligned.txt").write_text(
    "Сводка по NPS\n\nКвартал         NPS    Ответов\nI кв. 2025      43     287\nII кв. 2025     —      —\n"
    "III кв. 2025    46     341\n",
    encoding="utf-8",
)
(out / "no_table.txt").write_text(
    "Итоги продаж за 9 месяцев. Выручка выросла на 23%, клиентов стало больше на 18%.\n"
    "Таблицы здесь нет — только текст.\n",
    encoding="utf-8",
)
(out / "empty.csv").write_bytes(b"")
print(sorted(p.name for p in out.iterdir() if p.suffix != ".py"))
