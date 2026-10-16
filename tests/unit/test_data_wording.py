"""Слова слоя данных: русские числа и формы, падежи названий колонок, род глагола, периоды (verstka/data/words.py),
проверка «каждое число заголовка — среди фактов», и цели из текста (verstka/data/goals.py): разбор фраз, предмет,
сопоставление с датасетом и распределение целей по датасетам (verstka/data/plan.py, `assign_goals`)."""

from __future__ import annotations

import pytest

from verstka.data.aggregate import Data
from verstka.data.goals import goal_match, goals_of, stem, stems_match
from verstka.data.headline import headline_ok, numbers_in
from verstka.data.words import (
    fmt_num, fmt_pct, fmt_signed, is_counter, is_plural_value, metric_phrase, period_dative, period_label, phrase,
    plural, verb,
)
from verstka.data.plan import assign_goals
from verstka.data.profile import profile_table
from verstka.schemas.data import HeadlineFact, Table

NB = " "


# ── числа ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_numbers_in_russian():
    assert fmt_num(1433) == f"1{NB}433"
    assert fmt_num(1.24) == "1,24" and fmt_num(52.0) == "52" and fmt_num(12.345) == "12,3"
    assert fmt_num(-15) == "−15" and fmt_num(1_240_000) == f"1{NB}240{NB}000"
    assert fmt_pct(22.97) == "23" and fmt_pct(4.23) == "4,2" and fmt_pct(9.96) == "10"
    assert fmt_signed(23, "%") == "+23%" and fmt_signed(-4.2, "п.п.") == f"−4,2{NB}п.п." and fmt_signed(6, "п.") == f"+6{NB}п."


@pytest.mark.parametrize("n,form", [(1, "строка"), (2, "строки"), (5, "строк"), (11, "строк"), (21, "строка"),
                                    (22, "строки"), (112, "строк"), (2.5, "строки")])
def test_plural(n, form):
    assert plural(n, "строка", "строки", "строк") == form


def test_numbers_in_text_and_headline_check():
    text = f"Москва даёт 41% выручки, топ-10 клиентов, 1{NB}433 млн ₽, NPS вырос до 52, за два квартала, 4,2%, III кв."
    assert numbers_in(text) == [41, 10, 1433, 52, 4.2, 2]
    facts = [HeadlineFact(id="a", text="", value=41.0, kind="share"), HeadlineFact(id="b", text="", value=-12.0,
                                                                                   kind="change")]
    assert headline_ok("Москва даёт 41% выручки", facts)
    assert headline_ok("Выручка снизилась на 12%", facts)
    assert not headline_ok("Москва даёт 42% выручки", facts)
    assert not headline_ok("Выручка снизилась на 12% за два года", facts)  # «два» — не факт
    assert headline_ok("Рост на 22,97%", [HeadlineFact(id="c", text="", value=22.97, kind="change")])


# ── падежи и род ──────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,gen,dat,gen_pl,dat_pl,gender", [
    ("Выручка", "Выручки", "Выручке", None, None, "f"),
    ("Регион", "Региона", "Региону", "Регионов", "Регионам", "m"),
    ("Отрасль", "Отрасли", None, "Отраслей", "Отраслям", "f"),
    ("Обращение", "Обращения", None, "Обращений", "Обращениям", "n"),
    ("Категория", "Категории", None, "Категорий", "Категориям", "f"),
    ("Средний чек", "Среднего чека", "Среднему чеку", None, None, "m"),
    ("Канал продаж", "Канала продаж", None, "Каналов продаж", "Каналам продаж", "m"),
    ("Продажи", "Продаж", "Продажам", "Продаж", None, "pl"),
    ("Клиенты", "Клиентов", None, "Клиентов", "Клиентам", "pl"),
    ("Сделки", "Сделок", None, "Сделок", None, "pl"),
    ("Сделка", "Сделки", None, "Сделок", None, "f"),
    ("Прибыль", "Прибыли", None, None, None, "f"),
    ("Показатель", "Показателя", None, "Показателей", None, "m"),
    ("Время ответа", "Времени ответа", None, None, None, "n"),
    ("Страна", "Страны", None, "Стран", "Странам", "f"),
    ("Месяц", "Месяца", None, "Месяцев", None, "m"),
])
def test_phrase_cases(name, gen, dat, gen_pl, dat_pl, gender):
    p = phrase(name)
    assert p is not None and p.gender == gender
    assert p.gen == gen
    if dat:
        assert p.dat == dat
    if gen_pl:
        assert p.gen_pl == gen_pl
    if dat_pl:
        assert p.dat_pl == dat_pl


def test_phrase_units_abbreviations_and_counters():
    assert phrase("Выручка, млн ₽").gen == "Выручки"
    nps = phrase("NPS")
    assert nps is not None and not nps.sure and nps.gen == "NPS" and nps.gender == "m"
    assert phrase("Клиентов") is None and is_counter("Клиентов") and is_counter("Минут до ответа")
    assert metric_phrase("Клиентов").nom == "Число клиентов" and metric_phrase("Клиентов").gender == "n"
    assert metric_phrase("Довольных клиентов", "percent").dat == "Доле довольных клиентов"
    assert phrase("Выручка").low.gen == "выручки"
    assert not is_counter("Выручка") and not is_counter("Регион")


@pytest.mark.parametrize("value,plural_", [("Прямые продажи", True), ("Партнёры", True), ("Прямые", True),
                                           ("Набережные Челны", True), ("Москва", False), ("Сочи", False),
                                           ("Онлайн", False), ("Нижний Новгород", False), ("Маркетплейс", False),
                                           ("Германии", False)])
def test_plural_category_values(value, plural_):
    assert is_plural_value(value) is plural_


def test_verbs_agree():
    assert verb("grow", "f") == "выросла" and verb("grow", "m") == "вырос" and verb("grow", "n") == "выросло"
    assert verb("grow", "pl") == "выросли" and verb("give", "pl", past=False) == "дают"
    assert verb("give", "m", past=False) == "даёт" and verb("fall", "f") == "снизилась"


def test_periods():
    assert period_label("2025-01", "month") == "янв 2025" and period_label("2024-Q4", "quarter") == "IV кв. 2024"
    assert period_label("2025", "year") == "2025"
    assert period_dative("2026-09") == "к сентябрю" and period_dative("2026-Q3") == "к III кварталу"
    assert period_dative("2026") is None


# ── цели из текста ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_goals_of_scenario_brief():
    gs = goals_of("Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, "
                  "что даёт выручку и где узкие места. Данные — в приложенных файлах.")
    assert [(g.phrase, g.task, g.viz) for g in gs] == [
        ("покажи рост выручки", "dynamics", "line"), ("сравни регионы", "comparison", "bar"),
        ("что даёт выручку", "shares", "doughnut")]
    assert gs[0].subject == ["выручк"] and gs[1].subject == ["регион"]


@pytest.mark.parametrize("text,task", [
    ("Из чего складывается выручка?", "shares"), ("Покажите структуру затрат", "shares"),
    ("Как распределено время ответа", "distribution"), ("Есть ли связь между ценой и спросом", "relationship"),
    ("Справочно — полный список клиентов", "reference"), ("Ключевые показатели квартала", "kpi"),
    ("Как менялась конверсия по месяцам", "dynamics"), ("Сопоставьте филиалы", "comparison"),
    ("Покажи доли каналов", "shares"),
])
def test_goal_kinds(text, task):
    gs = goals_of(text)
    assert gs and gs[0].task == task, gs


def test_no_goals_in_plain_text():
    assert goals_of("Итоги продаж за квартал для правления.") == []
    assert goals_of("") == []


def test_stems():
    assert stem("выручки") == stem("выручка") == stem("выручку") == "выручк"
    assert stem("регионы") == stem("регион") == "регион"
    assert stems_match(["выручк"], "Выручка, млн ₽") and not stems_match(["регион"], "Канал продаж")


def _t(name: str, columns: list[str], rows: list[list], units=None) -> Table:
    return Table(id=name, file=name, kind="csv", columns=columns, units=units or [None] * len(columns), rows=rows)


def test_goal_match_by_file_columns_and_values():
    t = _t("Регионы.csv", ["Регион", "Выручка"], [["Москва", 10], ["Казань", 5], ["Омск", 3]])
    p = profile_table(t)
    g_reg, = goals_of("сравни регионы")
    g_city, = goals_of("сравни Москву и Казань")
    g_other, = goals_of("сравни каналы")
    g_any, = goals_of("покажи структуру")
    assert goal_match(g_reg, p) == pytest.approx(1.6)  # файл + колонка
    assert goal_match(g_city, p, ["Москва", "Казань", "Омск"]) > 0
    assert goal_match(g_other, p) == 0
    assert goal_match(g_any, p) == 0.5


def test_assign_goals_to_best_dataset():
    rev = _t("Выручка по месяцам.csv", ["Месяц", "Выручка"], [[f"2025-{m:02d}", 100 + m] for m in range(1, 13)],
             [None, "млн ₽"])
    reg = _t("Регионы.csv", ["Регион", "Выручка"], [["Москва", 10], ["Казань", 5], ["Омск", 3]], [None, "млн ₽"])
    ch = _t("Каналы.csv", ["Канал", "Выручка", "Доля"], [["Прямые", 460, 46], ["Партнёры", 280, 28], ["Онлайн", 260, 26]],
            [None, "млн ₽", "%"])
    datas = [Data(t, profile_table(t)) for t in (rev, reg, ch)]
    goals = goals_of("Покажи рост выручки, сравни регионы, что даёт выручку")
    per = assign_goals(goals, datas)
    assert [g.phrase for g in per[0]] == ["покажи рост выручки"]
    assert [g.phrase for g in per[1]] == ["сравни регионы"]
    assert [g.phrase for g in per[2]] == ["что даёт выручку"]
