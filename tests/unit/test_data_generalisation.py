"""Обобщение анализа (второй набор «университет», .superpowers/sdd/s2/t12a-report.md): общие правила на синтетических
таблицах — цели к каждому названному датасету, взаимосвязь при коде вместо имени, изменение — не вторая величина,
несколько рядов и частей, иерархия, выводы без натяжек, числа как в файле, медиана у скошенных данных, короткие подписи,
ранг таблицы у разнородных KPI, цвет и наклон рассеяния, склонение многословных названий. Настоящие файлы
`examples/data-science-2026/` — только сквозная проверка в конце."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional

import numpy as np

from verstka.data.aggregate import Data
from verstka.data.goals import goals_of
from verstka.data.headline import headline_ok
from verstka.data.plan import NotBuilt, assign_goals, chart_spec_of, plan_dataset, plan_datasets
from verstka.data.profile import profile_table
from verstka.data.readers import read_file
from verstka.data.words import each_unit, phrase, verb_agree
from verstka.schemas.data import DatasetPlan, Table, VizOption
from verstka.schemas.outline import ChartSpec, TableData

SCIENCE = Path(__file__).resolve().parents[2] / "examples" / "data-science-2026"
NB = " "


def _t(columns: list[str], rows: list[list], units: Optional[list] = None, file: str = "данные.csv") -> Table:
    return Table(id=file, file=file, kind="csv", columns=columns, units=units or [None] * len(columns), rows=rows,
                 raw_header=list(columns))


def _plan(t: Table, goal: str = "") -> DatasetPlan:
    p = plan_dataset(profile_table(t), t, goals_of(goal) if goal else None)
    assert headline_ok(p.headline, p.headline_facts, [p.headline]) and 2 <= len(p.options) <= 3
    return p


def _sp(s: Optional[str]) -> str:
    return (s or "").replace(NB, " ")


def _intake(total: bool = False) -> Table:
    dirs = ["Прикладная информатика", "Программная инженерия", "Юриспруденция", "Экономика", "Машиностроение",
            "Строительство", "Менеджмент"]
    b, pay, tg = [120, 110, 40, 45, 100, 80, 35], [140, 150, 210, 190, 55, 120, 165], [25, 20, 0, 0, 60, 15, 5]
    if total:
        cols = ["Направление подготовки", "Бюджет", "Платное", "Целевое", "Всего"]
        rows = [[d, x, y, z, x + y + z] for d, x, y, z in zip(dirs, b, pay, tg)]
        return _t(cols, rows, [None, "чел.", "чел.", "чел.", "чел."], file="Приём.csv")
    cols = ["Направление подготовки", "Форма обучения Бюджет", "Форма обучения Платное", "Форма обучения Целевое"]
    return _t(cols, [[d, x, y, z] for d, x, y, z in zip(dirs, b, pay, tg)], file="Приём.csv")


def _scores_table(with_id: bool = True) -> Table:
    rnd = random.Random(5)
    rows = []
    for i in range(120):
        h = rnd.uniform(1, 25)
        rows.append(([f"АБ-{1000 + i}"] if with_id else []) + [rnd.choice(["Технический", "Гуманитарный", "Естественный"]),
                                                               round(h, 1), round(min(100, 52 + 1.9 * h + rnd.gauss(0, 6)), 1)])
    cols = (["Абитуриент"] if with_id else []) + ["Профиль", "Подготовка", "Средний балл ЕГЭ"]
    units = ([None] if with_id else []) + [None, "ч/нед.", None]
    return _t(cols, rows, units, file="Подготовка.csv")


# ── G1: цели — каждому названному датасету ────────────────────────────────────────────────────────────────────────────
def test_goals_reach_every_named_dataset():
    brief = ("Покажи, как подготовка влияет на баллы ЕГЭ, как устроен приём по формам обучения "
             "и на что ушёл бюджет НИОКР.")
    gs = goals_of(brief)
    assert [(g.task, g.phrase) for g in gs] == [
        ("relationship", "как подготовка влияет на баллы ЕГЭ"), ("shares", "как устроен приём по формам обучения"),
        ("comparison", "на что ушёл бюджет НИОКР")]
    budget = _t(["Подразделение", "Бюджет"], [["Лаборатория А", 100], ["Лаборатория Б", 60], ["Лаборатория В", 40]],
                [None, "млн ₽"], file="Бюджет НИОКР.csv")
    tables = [_intake(), budget, _scores_table()]
    per = assign_goals(gs, [Data(t, profile_table(t)) for t in tables])
    assert [g.task for g in per[0]] == ["shares"]
    assert [g.task for g in per[1]] == ["comparison"]
    assert [g.task for g in per[2]] == ["relationship"]
    plans = plan_datasets(tables, brief)
    assert [p.task.goal for p in plans] == ["как устроен приём по формам обучения", "на что ушёл бюджет НИОКР",
                                            "как подготовка влияет на баллы ЕГЭ"]


def test_goal_naming_two_files_reaches_both():
    a = _t(["Регион", "Выручка"], [["Москва", 10], ["Казань", 5], ["Омск", 3]], [None, "млн ₽"], file="Регионы.csv")
    b = _t(["Канал", "Выручка"], [["Прямые", 7], ["Партнёры", 5], ["Онлайн", 2]], [None, "млн ₽"], file="Каналы.csv")
    per = assign_goals(goals_of("Сравни регионы и каналы"), [Data(t, profile_table(t)) for t in (a, b)])
    assert per[0] and per[1]


# ── M1, M14: взаимосвязь и изменение ──────────────────────────────────────────────────────────────────────────────────
def test_id_group_two_measures_strong_r_is_relationship_without_brief():
    p = _plan(_scores_table())
    assert p.task.task == "relationship" and p.options[0].kind == "scatter"
    assert p.task.scores["relationship"] > p.task.scores["reference"]


def test_change_column_is_not_a_second_measure():
    rows = [[f"Кафедра {chr(1040 + i)}", 100 - i * 4, (i * 7 % 11) - 4] for i in range(14)]
    t = _t(["Кафедра", "Бюджет", "Изменение к 2025"], rows, [None, "млн ₽", "млн ₽"])
    d = Data(t, profile_table(t))
    assert d.xy is None
    p = _plan(t)
    assert p.task.task in ("comparison", "shares") and all(o.kind != "scatter" for o in p.options)
    assert "быстрее всех" not in p.headline  # прибавка в рублях — не темп


# ── M5, M11: несколько частей и рядов ─────────────────────────────────────────────────────────────────────────────────
def test_parts_under_one_header_are_a_composition():
    for t in (_intake(), _intake(total=True)):
        p = _plan(t)
        assert p.task.task == "shares", t.columns
        assert p.options[0].kind == "stacked_bar"
        assert [o.kind for o in p.options[1:]] == ["grouped_bar", "doughnut"]
        spec = chart_spec_of(p, t)
        assert [s.name for s in spec.series] == ["Бюджет", "Платное", "Целевое"]  # «Всего» — не ряд
        assert spec.categories[0] == "Прикладная информатика"  # порядок — по сумме частей (285)
        assert _sp(p.headline) == "Платное — 61% приёма, бюджет — 31%"  # 1 030 и 530 из 1 685
        donut = chart_spec_of(p, t, option=2)
        assert donut.categories == ["Бюджет", "Платное", "Целевое"] and donut.highlight_index == 1


def test_two_series_of_one_kind_are_two_lines():
    years = [str(y) for y in range(2005, 2026) if y != 2016]
    sc = [42 + int((y - 2005) ** 1.75) for y in range(2005, 2026) if y != 2016]
    ri = [255 + 30 * (y - 2005) for y in range(2005, 2026) if y != 2016]
    for cols, units in ((["Год", "Scopus, статей", "РИНЦ, статей"], None), (["Год", "Scopus", "РИНЦ"], [None, "статей", "статей"])):
        t = _t(cols, [[y, a, b] for y, a, b in zip(years, sc, ri)], units)
        p = _plan(t)
        spec = chart_spec_of(p, t)
        assert [s.name for s in spec.series] == ["Scopus", "РИНЦ"] and spec.gaps
        f = {x.id: x.value for x in p.headline_facts}
        assert _sp(p.headline) == f"Scopus вырос в {str(f['series_0']).replace('.', ',')} раза за 20 лет, " \
                                  f"РИНЦ — в {str(f['series_1']).replace('.', ',')} раза"
        assert "20 точек" in p.options[0].reasons[0] and "2 ряда" in p.options[0].reasons[0]  # M13: пропуск — не точка
        assert p.options[1].kind == "grouped_column"  # разные базы — не складываются


def test_long_single_series_headline_is_the_whole_period():
    t = _t(["Год", "Выручка"], [[str(y), 100 * 1.12 ** (y - 2005)] for y in range(2005, 2026)], [None, "млн ₽"])
    p = _plan(t)
    assert "за 20 лет" in p.headline and "в 9,6 раза" in p.headline


# ── M16, M18, M17: иерархия, итог, числа как в файле ──────────────────────────────────────────────────────────────────
def _shops() -> Table:
    regs = ["Центральный регион", "Северо-Западный регион", "Южный регион", "Уральский регион"]
    rows = []
    for i in range(18):
        rows.append([f"Магазин {chr(1040 + i)}", regs[i % 4], round(150 - i * 7.3, 1)])
    rows.append(["Итого", "", round(sum(r[2] for r in rows), 1)])
    t = _t(["Магазин", "Регион", "Выручка"], rows, [None, None, "млн ₽"], file="Магазины.csv")
    t.totals = [18]
    return t


def test_hierarchy_compares_parents_and_keeps_details():
    t = _shops()
    prof = profile_table(t)
    assert ("Магазин", "Регион") in prof.hierarchies
    p = _plan(t)
    assert p.task.task in ("comparison", "shares")
    if p.task.task == "shares":
        p = _plan(t, "сравни регионы")
    spec = chart_spec_of(p, t)
    assert spec.x_title == "Регион" and len(spec.categories) == 4  # сумма по магазинам
    child = next(k for k, o in enumerate(p.options) if o.title.startswith("Столбцы по магазинам"))
    assert chart_spec_of(p, t, option=child).x_title == "Магазин"
    tree = next(k for k, o in enumerate(p.options) if o.title == "Таблица «Регион → Магазин»")
    first = chart_spec_of(p, t, option=tree, part=1)
    last = chart_spec_of(p, t, option=tree, part=2)
    assert first.columns[:2] == ["Регион", "Магазин"] and last.rows[-1][0] == "Итого"
    assert isinstance(chart_spec_of(p, t, option=tree, part=3), NotBuilt)
    assert "142,7" in [r[2] for r in first.rows]  # 142,7 — как в файле, не «143»


def test_comparison_table_keeps_values_and_total_row():
    t = _t(["Кафедра", "Бюджет"], [["А", 142.6], ["Б", 118.4], ["В", 14.0], ["Г", 96.2]], [None, "млн ₽"])
    p = _plan(t)
    if not any(o.kind == "table" for o in p.options):  # таблица — четвёртый вариант: «Пересобрать слайд так»
        p.options.append(VizOption(kind="table", title="Таблица"))
    k = next(k for k, o in enumerate(p.options) if o.kind == "table")
    body = chart_spec_of(p, t, option=k)
    assert isinstance(body, TableData)
    assert [r[1] for r in body.rows] == ["142,6", "118,4", "96,2", "14", "371,2"] and body.rows[-1][0] == "Итого"


# ── M19, M20: доли и скошенные данные ─────────────────────────────────────────────────────────────────────────────────
def test_share_rounds_and_skewed_money_leads_with_median():
    vals = [3590] * 230 + [2590] * 80 + [8000] * 54 + [12000] * 20 + [20000] * 5 + [30000] * 10 + [55000] * 21
    t = _t(["Студент", "Размер стипендии"], [[f"С-{i}", v] for i, v in enumerate(vals)], [None, "₽"])
    p = _plan(t)
    assert _sp(p.headline).startswith("Половина студентов — до 3 590 ₽") and "среднее" in p.headline


def test_share_within_is_rounded_not_floored():
    rng = np.random.default_rng(1)
    x = list(np.round(rng.exponential(30, 420)))
    t = _t(["Обращение", "Минут до ответа"], [[f"Т-{i}", v] for i, v in enumerate(x)])
    p = _plan(t)
    f = {x.id: x for x in p.headline_facts}
    within = int(f["share_within"].explain.split(" из ")[0])
    assert f["share_within"].value == round(within / 420 * 100)


def test_outliers_equal_to_the_bound_say_from():
    vals = [100 + (i % 20) for i in range(200)] + [600, 600, 900]
    t = _t(["Заказ", "Минут доставки"], [[f"Z-{i}", v] for i, v in enumerate(vals)])
    p = _plan(t)
    f = {x.id: x for x in p.headline_facts}
    assert f["outlier_bound_high"].value == 600 and f["outlier_bound_high"].text.startswith("от ")


# ── M22, M23, M24: KPI без натяжек ────────────────────────────────────────────────────────────────────────────────────
def _kpi(rows: list[list[str]]) -> Table:
    return _t(["Показатель", "2026", "2025", "Изменение"], rows, file="Итоги года.txt")


def test_kpi_compares_only_same_kind():
    t = _kpi([["Принято на 1 курс", "2 425 чел.", "2 288 чел.", "+6%"], ["Средний балл", "74,1", "72,9", "+1,2"],
              ["Объём НИОКР", "1 305 млн ₽", "1 164 млн ₽", "+12%"], ["Отчислено студентов", "412 чел.", "450 чел.", "−8%"]])
    p = _plan(t)
    assert "НИОКР" not in p.headline  # люди не сравниваются с деньгами
    assert p.headline == "Принято на 1 курс: +6%, отчислено студентов: −8%"
    assert len(p.caption) <= 140
    assert [o.kind for o in p.options][:2] == ["kpi_cards", "table"]
    col = next(o for o in p.options if o.kind == "column")
    assert col.why_not and ("единицы" in col.why_not or "Масштабы" in col.why_not)


def test_kpi_related_kinds_compare_through_their_ratio():
    t = _kpi([["Выручка", "1,24 млрд ₽", "1,01 млрд ₽", "+23%"], ["Клиенты", "3 480", "2 949", "+18%"],
              ["Средний чек", "356 тыс. ₽", "342 тыс. ₽", "+4%"]])
    assert _plan(t).headline == "Выручка растёт быстрее числа клиентов: +23% против +18%"


def test_kpi_without_comparable_pair_states_the_strongest_fact():
    t = _kpi([["Выручка", "1,24 млрд ₽", "1,01 млрд ₽", "+23%"], ["Индекс удовлетворённости", "78", "74", "+4 п."]])
    assert _plan(t).headline == "Выручка выросла на 23%"


def test_captions_are_short():
    rows = [[f"Показатель {chr(1040 + i)}", f"{100 + i} чел.", f"{90 + i} чел.", f"+{i + 1}%"] for i in range(6)]
    p = _plan(_kpi(rows))
    assert p.caption and len(p.caption) <= 140


# ── M4: рассеяние ─────────────────────────────────────────────────────────────────────────────────────────────────────
def test_scatter_coloured_by_small_group_and_slope_in_headline():
    t = _scores_table()
    p = _plan(t)
    spec = chart_spec_of(p, t)
    assert sorted(s.name for s in spec.xy) == ["Гуманитарный", "Естественный", "Технический"]
    assert p.headline.startswith("Каждый час подготовки в неделю — около +1,9") or \
        p.headline.startswith("Каждый час подготовки в неделю — около +2")
    bins = next(k for k, o in enumerate(p.options) if o.title.startswith("Столбцы: средний балл ЕГЭ по группам"))
    b = chart_spec_of(p, t, option=bins)
    assert isinstance(b, ChartSpec) and len(b.categories) == 3 and b.series[0].values == sorted(b.series[0].values)
    assert each_unit("ч/нед.") == ("каждый час", "в неделю") and each_unit("млн ₽") == ("каждый миллион рублей", "")


# ── M3, M6: русский ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_multiword_names_and_agreement():
    p = phrase("Направление подготовки")
    assert (p.gen_pl, p.dat_pl, p.gen) == ("Направлений подготовки", "Направлениям подготовки", "Направления подготовки")
    forms = ("не вошёл", "не вошла", "не вошло", "не вошли")
    assert verb_agree(["Средний балл ЕГЭ"], forms) == "не вошёл" and verb_agree(["Дата договора"], forms) == "не вошла"
    assert verb_agree(["Тариф", "Дата договора"], forms) == "не вошли"
    t = _intake()
    plan = _plan(t)
    assert "направлений подготовки" in plan.task.reasons[0].lower() or "Направлений" in plan.task.reasons[0]


def test_reference_reason_agreement_and_lost_column():
    rnd = random.Random(7)
    rows = [[f"Клиент {i:03d}", ["ИТ", "Ритейл"][i % 2], 500 - i, round(rnd.uniform(40, 90), 1)] for i in range(40)]
    t = _t(["Клиент", "Отрасль", "Выручка", "Средний балл"], rows, [None, None, "млн ₽", None])
    p = _plan(t)
    text = " ".join(r for o in p.options for r in o.reasons) + " " + " ".join(o.why_not or "" for o in p.options)
    assert "Средний балл не вошёл" in text or "средний балл не вошёл" in text
    assert "теряется отрасль" in text


# ── сквозная проверка на настоящих файлах ─────────────────────────────────────────────────────────────────────────────
def test_science_set_end_to_end():
    files = ["Часы подготовки и баллы ЕГЭ.csv", "Приём по направлениям.xlsx", "Публикации по годам.json",
             "Бюджет НИОКР.csv", "Стипендии.csv", "Итоги года.txt"]
    brief = ("Итоги университета за 2026 год для учёного совета. Покажи, как подготовка влияет на баллы ЕГЭ, как устроен "
             "приём по формам обучения, как растёт наука и на что ушёл бюджет НИОКР. Данные — в приложенных файлах.")
    tables = [read_file(SCIENCE / f)[0] for f in files]
    plans = plan_datasets(tables, brief)
    tasks = [p.task.task for p in plans]
    assert tasks == ["relationship", "shares", "dynamics", "comparison", "distribution", "kpi"]
    kinds = [p.options[0].kind for p in plans]
    assert kinds == ["scatter", "stacked_bar", "line", "bar", "histogram", "kpi_cards"]
    heads = [_sp(p.headline) for p in plans]
    assert heads[1].startswith("Платное — 53%") and "бюджет — 35%" in heads[1]
    assert heads[2].startswith("Scopus вырос в 9,1 раза за 20 лет") and "РИНЦ — в 3,4 раза" in heads[2]
    if ("Кафедра", "Институт") in plans[3].profile.hierarchies:  # иерархию находит профиль
        assert "27%" in heads[3] and "349 из 1 305" in heads[3]
        assert plans[3].options[0].title == "Ранжированные горизонтальные столбцы по институтам"
    assert heads[4].startswith("Половина студентов — до 3 590 ₽")
    for p, t in zip(plans, tables):
        assert p.headline != p.plain_headline
        assert p.caption is None or len(p.caption) <= 160
        for k in range(len(p.options)):
            assert chart_spec_of(p, t, option=k) is not None
