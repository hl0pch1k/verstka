"""Deterministic reading of briefs (verstka.planning.heuristics) — the offline planner's eyes."""

from __future__ import annotations

from verstka.planning.heuristics import enumeration, kpis_of, labelled_items, parse_sections, series_headline, steps_of, table_series
from verstka.schemas.outline import TableData


def test_sections_tables_and_their_lead_line():
    title, secs = parse_sections("# Отчёт\n\n## Результаты\n\nВсё выросло.\n\nДинамика:\n\n| Месяц | Май | Июнь | Июль |\n|---|---|---|---|\n| Клиенты | 10 | 20 | 40 |\n")
    assert title == "Отчёт" and [s.title for s in secs] == ["Результаты"]
    sec = secs[0]
    assert sec.sentences == ["Всё выросло."] and sec.table_leads == ["Динамика"] and sec.tables[0].caption == "Динамика"


def test_steps_keep_ranges_in_the_marker():
    steps, rest = steps_of(["Этап 1, месяц 1–2: пилот на копии хранилища.", "Этап 2, месяц 3–4: перенос расчётов.", "Этап 3, месяц 5–6: отключение кластера.", "Команда: 4 инженера."])
    assert [s.title for s in steps] == ["Этап 1, месяц 1–2", "Этап 2, месяц 3–4", "Этап 3, месяц 5–6"]
    assert steps[0].text == "Пилот на копии хранилища" and rest == ["Команда: 4 инженера."]
    assert steps_of(["Неделя 1: старт.", "Итог."]) == ([], ["Неделя 1: старт.", "Итог."])  # fewer than three steps is not a process


def test_labelled_items_and_enumerations():
    items, rest = labelled_items(["Совместимость: 2 из 140 отчётов переписываем.", "Безопасность: данные остаются в РФ.", "Итог понятен."])
    assert [i.title for i in items] == ["Совместимость", "Безопасность"] and rest == ["Итог понятен."]
    lead, parts = enumeration("Функция «Умные напоминания» превращает сообщение в задачу, предлагает срок по контексту, эскалирует просроченные задачи и присылает утренний дайджест.")
    assert lead == "Функция «Умные напоминания»" and len(parts) == 4 and parts[-1].startswith("Присылает")
    # one statement with clauses is not a list; a noun tail after «и» stays in its part
    assert enumeration("Загрузка в среднем 23%, но в пиковые дни 97%, из-за чего расчёты не успевают.") == (None, [])
    _, parts = enumeration("Онлайн-лекции по вечерам, практикумы по субботам, карьерный трек с разбором резюме и пробными собеседованиями.")
    assert parts[-1] == "Карьерный трек с разбором резюме и пробными собеседованиями"


def test_kpis_get_short_labels_and_signs():
    got = {k.value: k.label for s in [
        "Доля завершённых в срок задач выросла на 34%.",
        "Экономия составила 2,1 часа в неделю на человека.",
        "Средняя оценка удобства 4,6 из 5, 91% участников готовы рекомендовать функцию коллегам.",
        "Функция снижает срывы дедлайнов с 31% до 12% и окупает разработку за квартал.",
        "Продление поддержки железа на следующий год стоит 38 млн рублей.",
        "В пилоте участвовали 12 400 сотрудников из 37 компаний.",
    ] for k in kpis_of(s)}
    assert got["+34%"] == "доля завершённых в срок задач"
    assert got["2,1 ч"] == "экономия в неделю на человека"
    assert got["4,6 из 5"] == "средняя оценка удобства" and got["91%"].startswith("участников готовы")
    assert got["31% → 12%"] == "срывы дедлайнов"
    assert got["38 млн ₽"] == "продление поддержки железа на следующий год"
    assert got["12 400"] == "сотрудников из 37 компаний в пилоте"
    assert kpis_of("Программа из 4 модулей стартует в 2026 году.") == []  # a lone digit and a year are not KPIs


def test_tables_become_series_only_when_they_are_charts():
    ts = TableData(columns=["Месяц", "Май", "Июнь", "Июль", "Август"], rows=[["Активные пользователи, чел.", "1200", "3400", "6100", "12400"]])
    series, kind = table_series(ts)
    assert kind == "column" and series[0].values == [1200, 3400, 6100, 12400] and series[0].unit == "чел."
    assert series_headline(series[0]) == "Активные пользователи: с 1 200 до 12 400, рост в 10 раз"
    cmp = TableData(columns=["Статья, млн ₽", "Сейчас", "В облаке"], rows=[["Железо", "38", "0"], ["Свет", "9", "0"], ["Облако", "0", "27"], ["Итого", "47", "27"]])
    series, kind = table_series(cmp)
    assert kind == "bar" and [s.name for s in series] == ["Сейчас", "В облаке"] and series[0].categories == ["Железо", "Свет", "Облако"]
    matrix = TableData(columns=["Сценарий", "Базовый", "Про"], rows=[["Напоминание", "да", "да"], ["Эскалация", "нет", "да"], ["Дайджест", "нет", "да"]])
    assert table_series(matrix) == ([], None)
    mixed = TableData(columns=["Показатель", "2024", "2025"], rows=[["Студентов", "640", "1 100"], ["Дошли", "71%", "76%"], ["Работают", "58%", "63%"]])
    assert table_series(mixed) == ([], None)  # different units in one column: a table, not a chart
