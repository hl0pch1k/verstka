"""Цели снаружи (раунд 10): `plan_datasets(…, goals=…)` и `build_data_story(…, goals=…)` берут готовые цели — например,
понятые моделью (`verstka/data/intent.py`) — вместо разбора брифа; разбор остаётся запасным путём."""

from __future__ import annotations

import csv
import io

from verstka.data.goals import Goal, goals_of
from verstka.data.plan import chart_spec_of, plan_datasets
from verstka.data.readers import read_bytes
from verstka.data.story import build_data_story
from verstka.schemas.data import Table


def _t(name: str, rows: list[list]) -> Table:
    buf = io.StringIO(newline="")
    csv.writer(buf, delimiter=";").writerows(rows)
    return read_bytes(name, buf.getvalue().encode("utf-8"))[0]


SALES = [["Месяц", "Регион", "Выручка, млн ₽"]] + [[f"2026-{m:02d}", r, 100 + 7 * m + 30 * k]
                                                    for m in range(1, 7) for k, r in enumerate(["Москва", "Казань"])]
PRICES = [["Тариф", "Цена без НДС, ₽", "НДС, ₽", "Цена с НДС, ₽"], ["Старт", 2450, 539, 2989],
          ["Бизнес", 9900, 2178, 12078], ["Энтерпрайз", 39500, 8690, 48190]]


def test_given_goals_replace_parsing_the_brief():
    t = _t("Выручка по регионам.csv", SALES)
    by_text = plan_datasets([t], "Сравните регионы по выручке")[0]
    assert by_text.task.task == "comparison"
    given = goals_of("Покажите рост выручки")
    p = plan_datasets([t], "Сравните регионы по выручке", goals=given)[0]  # бриф не разбирается
    assert p.task.task == "dynamics" and p.task.goal == "покажите рост выручки"
    p = plan_datasets([t], "Сравните регионы по выручке", goals=[])[0]  # целей нет — и разбора нет
    assert p.task.goal is None


def test_given_goal_fields_choose_the_column():
    """Величина цели снаружи (`head`, `metric`, `negate`) выбирает колонку сама, без разбора фразы."""
    t = _t("Тарифы.csv", PRICES)
    g = Goal(phrase="тарифы по цене для клиента", task="comparison", viz="bar", to="столбцы",
             subject=["тариф", "цен"], metric=["цен", "ндс"], head="цен")
    p = plan_datasets([t], "", goals=[g])[0]
    s = chart_spec_of(p, t)
    assert p.task.goal == "тарифы по цене для клиента" and s.series[0].name == "Цена с НДС", s.series[0].name
    g2 = g.model_copy(update={"phrase": "тарифы по цене без налога", "negate": ["ндс"]})
    s2 = chart_spec_of(plan_datasets([t], "", goals=[g2])[0], t)
    assert s2.series[0].name == "Цена без НДС", s2.series[0].name


def test_story_takes_given_goals():
    t = _t("Выручка по регионам.csv", SALES)
    st = build_data_story("Итоги продаж за полугодие", [t], goals=goals_of("Покажите рост выручки"))
    p = st.plans[0]
    assert p.task.task == "dynamics" and p.task.goal == "покажите рост выручки"
