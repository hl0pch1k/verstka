"""Регрессии ревью rev7c (Task 7, раунд 6): складывать только по признаку в данных (N1), недели (N2), порядковые группы
(N3), номера вместо величин (N4), цели (N5–N7), главная метрика (N8), части целого по времени (N9), план и факт другими
словами (N10), полнота по ритму ряда (N11), ориентиры (N12), колонки одной единицы (N13), единица в подписи показателя
(N14), русский язык (N15) и мелочи. Таблицы идут через настоящее чтение и профиль."""

from __future__ import annotations

import datetime as dt
import re

from verstka.data.aggregate import Data
from verstka.data.goals import goals_of
from verstka.data.plan import NotBuilt, assign_goals, chart_spec_of, plan_dataset, plan_datasets
from verstka.data.profile import profile_table
from verstka.data.readers import read_bytes
from verstka.data.units import additivity
from verstka.data.words import count_gen, is_counter, lower_first, metric_phrase, phrase
from verstka.schemas.data import DatasetPlan, Table
from verstka.schemas.outline import ChartSpec, TableData

NB = " "


def _csv(rows: list[list]) -> str:
    return "\n".join(";".join("" if c is None else str(c) for c in r) for r in rows) + "\n"


def _t(name: str, rows: list[list]) -> Table:
    return read_bytes(name, _csv(rows).encode("utf-8"))[0]


def _plan(t: Table, brief: str = "") -> DatasetPlan:
    prof = profile_table(t)
    return plan_datasets([t], brief, profiles=[prof])[0] if brief else plan_dataset(prof, t)


def _f(p: DatasetPlan) -> dict:
    return {f.id: f for f in p.headline_facts}


def _sp(s) -> str:
    return (s or "").replace(NB, " ")


def _tables(p: DatasetPlan, t: Table) -> list[TableData]:
    out = []
    for k in range(len(p.options)):
        for part in (1, 2, 3):
            b = chart_spec_of(p, t, option=k, part=part)
            if isinstance(b, TableData):
                out.append(b)
    return out


# ── N1: складывается только по признаку ───────────────────────────────────────────────────────────────────────────
def test_additivity_needs_evidence():
    level = [("Январь", "°C", "number", ""), ("Урожайность", "ц/га", "number", ""), ("Цена", "₽/м²", "money", ""),
             ("Смертность", "‰", "number", ""), ("Минимум", "тыс. ₽", "money", ""), ("Медиана зарплаты", "тыс. ₽", "money", ""),
             ("USD", "₽", "money", ""), ("Значение", None, "number", "Урожайность по культурам"),
             ("EUR", "₽", "money", "Курсы валют ЦБ"), ("Значение", None, "number", "Данные"),
             ("Доля опозданий", "%", "percent", ""), ("Средний чек", "₽", "money", "")]
    for name, unit, typ, title in level:
        assert not additivity(name, unit, typ, title)[0], (name, unit, title)
    add = [("Выручка", "млн ₽", "money", ""), ("Продажи", "шт.", "number", ""), ("Заказов", None, "number", ""),
           ("Доставлено", None, "number", ""), ("Население", "тыс. чел.", "number", ""), ("Сумма", "тыс. ₽", "money", ""),
           ("Оплатили", None, "number", ""), ("Потребление", "кВт·ч", "number", "")]
    for name, unit, typ, title in add:
        assert additivity(name, unit, typ, title)[0], (name, unit)
    # строка «Итого», равная сумме, — признак суммы даже без единицы
    assert additivity("Значение", None, "number", "", sums=True)[0]


def test_rates_are_averaged_not_summed():
    rows = [["Дата", "USD, ₽"]]
    d, k = dt.date(2025, 9, 1), 0
    while d <= dt.date(2025, 12, 31):
        if d.weekday() < 5:
            rows.append([d.isoformat(), f"{81.25 + 0.03 * k:.4f}".replace(".", ",")])
            k += 1
        d += dt.timedelta(days=1)
    t = _t("Курс доллара.csv", rows)
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert all(80 < v < 86 for v in s.series[0].values if v is not None), s.series[0].values[:5]
    assert not any(f in _f(p) for f in ("leader_share", "total", "top_share"))


def test_yields_and_temperatures_no_shares_no_total():
    t = _t("Урожайность.csv", [["Год", "Культура", "Урожайность, ц/га"]]
           + [[2021 + k, c, 30 + 10 * i + k] for k in range(5) for i, c in enumerate(["Пшеница", "Ячмень", "Рожь"])])
    p = _plan(t)
    assert "ц/га" in _sp(p.headline) and "из 3" in p.headline and not any(o.kind.startswith("stacked") for o in p.options)
    t = _t("Температура.csv", [["Город", "Январь, °C"], ["Якутск", "-38,6"], ["Москва", "-6,2"], ["Сочи", "6,1"]])
    p = _plan(t)
    assert _sp(p.headline) == "Теплее всего — Сочи: 6,1 °C, холоднее всего — Якутск: −38,6 °C, 2 города в минусе"
    assert not any(r[0] == "Итого" for tb in _tables(p, t) for r in tb.rows)
    assert all(o.kind not in ("pie", "doughnut") for o in p.options)


def test_unknown_additivity_takes_the_safe_path():
    t = _t("Данные.csv", [["Объект", "Значение"], ["А", 10], ["Б", 30], ["В", 60]])
    p = _plan(t)
    assert "%" not in p.headline and "leader_share" not in _f(p)
    assert not any(r[0] == "Итого" for tb in _tables(p, t) for r in tb.rows)


# ── N2: недели ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_weekly_kept_as_weeks_up_to_sixty_points():
    t = _t("Продажи по неделям.csv", [["Неделя", "Продажи, шт."]]
           + [[(dt.date(2025, 1, 6) + dt.timedelta(weeks=k)).isoformat(), 1000 + 10 * k] for k in range(40)])
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert len(s.categories) == 40 and p.headline == "Продажи выросли на 39% за 39 недель"


def test_long_weekly_series_is_a_monthly_average_per_week():
    t = _t("Продажи по неделям.csv", [["Неделя", "Продажи, шт."]]
           + [[(dt.date(2024, 1, 1) + dt.timedelta(weeks=k)).isoformat(), 1000] for k in range(70)])
    p = _plan(t)
    s = chart_spec_of(p, t)
    # ровные недели — ровные месяцы (в среднем за неделю), а не «5 понедельников больше 4»
    assert set(v for v in s.series[0].values if v is not None) == {1000.0}
    assert "в среднем за неделю" in _sp(p.caption) and "на уровне 1 000" in _sp(p.headline)


def test_week_on_month_border_goes_where_most_days_are():
    # неделя с понедельника 30 марта 2026: четверг 2 апреля — неделя апреля
    from verstka.data.timeaxis import _to_freq
    wk = (dt.date(2026, 3, 30).toordinal() - 1) // 7
    assert _to_freq("week", wk, "month") == 2026 * 12 + 3


# ── N3: порядковые группы ─────────────────────────────────────────────────────────────────────────────────────────
def test_ordinal_bins_are_never_cut_silently():
    ages = [f"{5 * i}–{5 * i + 4}" for i in range(14)] + ["70 и старше"]
    t = _t("Население.csv", [["Возрастная группа", "Население, тыс. чел."]] + [[a, 1000 + 100 * k] for k, a in enumerate(ages)])
    p = _plan(t)
    assert len(chart_spec_of(p, t).categories) == 15 and p.headline.startswith("Больше всего — 70 и старше")
    many = [f"{5 * i}–{5 * i + 4}" for i in range(24)] + ["120 и старше"]
    t = _t("Население.csv", [["Возрастная группа", "Население, тыс. чел."]] + [[a, 1000 + k] for k, a in enumerate(many)])
    p = _plan(t)
    cats = chart_spec_of(p, t).categories
    assert len(cats) == 20 and cats[-1] == "95–99 … 120 и старше" and "одной" in _sp(p.caption)
    assert p.headline.startswith("Больше всего — 120 и старше")  # лидер — по всем группам, не по показанным


def test_ranked_levels_beyond_twelve_say_first_of_n():
    cities = [f"Город {chr(1040 + k)}" for k in range(15)]
    t = _t("Средний чек по городам.csv", [["Город", "Средний чек, ₽"]] + [[c, 1000 + 100 * k] for k, c in enumerate(cities)])
    p = _plan(t)
    assert p.options[0].aggregation == "первые 12 из 15" and "первые 12 из 15" in _sp(p.caption)
    assert "Город А — 1 000 ₽" in _sp(p.headline)  # последний — из всех 15, а не из показанных 12


# ── N4: номера, а не величины ─────────────────────────────────────────────────────────────────────────────────────
def test_timetable_numbers_are_not_charted():
    t = _t("Расписание.csv", [["День", "Время", "Предмет", "Кабинет", "Учитель"],
                              ["Пн", "09:00", "Математика", 301, "А."], ["Пн", "10:00", "Физика", 214, "Б."],
                              ["Вт", "09:00", "Математика", 301, "А."], ["Вт", "10:00", "Химия", 220, "В."],
                              ["Ср", "09:00", "Физика", 214, "Б."], ["Ср", "10:00", "Математика", 301, "А."],
                              ["Чт", "09:00", "Химия", 220, "В."], ["Пт", "09:00", "Физика", 214, "Б."]])
    prof = profile_table(t)
    k = next(k for k, c in enumerate(prof.columns) if c.name == "Кабинет")
    prof.columns[k] = prof.columns[k].model_copy(update={"role": "metric", "type": "number"})
    p = plan_dataset(prof, t)
    assert p.options[0].kind == "table" and p.message.startswith("Не для графика")
    # профиль не узнал расписание — анализ сам видит номера (повторы, без единицы, три текстовые колонки)
    prof2 = prof.model_copy(update={"typable": True, "untypable_reason": None, "nature": "comparison"})
    p = plan_dataset(prof2, t)
    assert p.options[0].kind == "table" and p.message.startswith("Не для графика: в колонке «Кабинет» — номера")
    assert not any(f in _f(p) for f in ("leader_share", "leader_value", "top_share"))


# ── N5–N7: цели ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_goal_raises_plan_fact_bars_not_plan_only():
    t = _t("Исполнение бюджета.csv", [["Статья", "Утверждено, тыс. ₽", "Исполнено, тыс. ₽"], ["Оплата труда", 48200, 47100],
                                      ["Коммунальные услуги", 6400, 6950], ["Ремонт", 9800, 4100], ["Закупки", 12300, 11900]])
    p = _plan(t, "Покажи, как исполнен бюджет.")
    assert p.options[0].kind == "grouped_bar" and p.headline.startswith("Бюджет исполнен на 91%")


def test_goal_metric_must_be_in_the_dataset():
    checks = _t("Средний чек по городам.csv", [["Город", "Средний чек, ₽"], ["Москва", 4200], ["Тверь", 2100], ["Омск", 1800]])
    regions = _t("Выручка по регионам.csv", [["Регион", "Выручка, млн ₽"], ["Центр", 500], ["Юг", 300], ["Урал", 200]])
    datas = [Data(x, profile_table(x)) for x in (checks, regions)]
    for brief in ("Сравни классы по среднему баллу.", "Сравни регионы по прибыли."):
        # раунд 8 (M1): цель не теряется — достаётся похожему датасету как невыполнимая, с причиной; задачу она не решает
        got = assign_goals(goals_of(brief), datas)
        assert sum(len(x) for x in got) == 1 and all(g.unmet for x in got for g in x), (brief, got)


def test_goal_parsing_neuter_split_and_plan():
    phrases = [g.phrase for g in goals_of("Покажи, как менялось число клиентов. Как изменялось количество заказов?")]
    assert phrases == ["как менялось число клиентов", "как изменялось количество заказов"]
    assert goals_of("Покажи как менялось число клиентов")[0].subject == ["числ", "клиент"]
    gs = goals_of("Сравни районы по цене квадратного метра и школы по среднему баллу.")
    assert [g.phrase for g in gs] == ["сравни районы по цене квадратного метра", "сравни школы по среднему баллу"]
    assert gs[1].metric == ["средн", "балл"]
    assert goals_of("Как выполнялся план продаж?")[0].task == "dynamics"
    two = goals_of("Покажи, как менялось число пациентов по отделениям и как росли доставки по складам.")
    assert [g.phrase for g in two] == ["как менялось число пациентов по отделениям", "как росли доставки по складам"]


def test_goal_wins_ties_and_picks_most_matching_metric():
    rows = [["Неделя", "Склад", "Доставлено, шт.", "Опозданий, шт.", "Доля опозданий, %"]]
    for w in range(8):
        for s, b, late in (("Подольск", 1450, 4.1), ("Химки", 1180, 6.3), ("Казань", 760, 3.2)):
            rows.append([(dt.date(2025, 9, 1) + dt.timedelta(weeks=w)).isoformat(), s, b + w, round(b * late / 100),
                         f"{late:.1f}".replace(".", ",")])
    t = _t("Доставки по складам.csv", rows)
    p = _plan(t, "Сравни склады по доле опозданий.")
    assert p.task.task == "comparison" and p.headline.startswith("Больше всего — Химки: 6,3%")  # опоздания: не «впереди»
    t = _t("Корзины.csv", [["Устройство", "Добавили в корзину", "Оплатили", "Доля брошенных корзин, %"],
                           ["Смартфон", 48200, 12650, "73,8"], ["Компьютер", 21400, 9870, "53,9"], ["Планшет", 5300, 1710, "67,7"]])
    p = _plan(t, "Сравни устройства по доле брошенных корзин.")
    assert p.headline.startswith("Больше всего — Смартфон: 73,8%")


def test_goal_feasibility_uses_its_subject():
    rows = [["Товар", "Цена, ₽", "Продано, шт.", "Выручка, тыс. ₽"]]
    rows += [[f"Товар {k}", 100 + 50 * k, 1000 - 30 * k, (100 + 50 * k) * (1000 - 30 * k) / 1000] for k in range(6)]
    t = _t("Продажи по товарам.csv", rows)
    p = _plan(t, "Покажи структуру выручки по товарам.")
    assert p.task.task == "shares" and p.task.goal == "покажи структуру выручки по товарам"


def test_partial_goal_match_is_not_called_a_match():
    t = _t("Численность по отделам.csv", [["Месяц", "Отдел", "Численность, чел."]]
           + [[f"2026-{m:02d}", d, 100 + m] for m in range(1, 13) for d in ("ИТ", "Продажи")])
    p = _plan(t, "Покажи, как менялось число пациентов по отделениям.")
    assert not any("совпала" in r for r in p.task.reasons)


# ── N8: главная метрика ───────────────────────────────────────────────────────────────────────────────────────────
def test_additive_money_beats_price_and_other_is_never_leader():
    rows = [["Товар", "Цена, ₽", "Продано, шт.", "Выручка, тыс. ₽"]]
    rows += [[f"Товар {k}", 1500 - 100 * k, 100 * (k + 1), (1500 - 100 * k) * (k + 1) / 10] for k in range(5)]
    rows.append(["Прочее", "", 9000, 9000])
    t = _t("Продажи.csv", rows)
    p = _plan(t)
    assert p.headline.startswith("Товар 4 впереди: 550") and "Прочее" not in p.headline
    assert chart_spec_of(p, t).categories[-1] == "Прочее"


def test_comparison_uses_the_total_column():
    t = _t("Выручка по кварталам 2025.csv", [["Регион", "I кв., млн ₽", "II кв., млн ₽", "III кв., млн ₽", "IV кв., млн ₽",
                                              "Итого за год, млн ₽"], ["Центр", 100, 110, 120, 130, 460],
                                             ["Юг", 50, 60, 70, 80, 260], ["Урал", 40, 40, 40, 40, 160]])
    p = _plan(t, "Сравни регионы по выручке за год.")
    assert p.task.task == "comparison" and _sp(p.headline) == "Центр даёт 52% выручки: 460 из 880 млн ₽"


def test_quarter_columns_are_a_time_axis_when_the_goal_asks():
    t = _t("Выручка по кварталам 2025.csv", [["Регион", "I кв., млн ₽", "II кв., млн ₽", "III кв., млн ₽", "IV кв., млн ₽",
                                              "Итого за год, млн ₽"], ["Центр", 100, 110, 120, 130, 460],
                                             ["Юг", 50, 60, 70, 80, 260], ["Урал", 40, 40, 40, 40, 160]])
    assert _plan(t).task.task == "shares"
    p = _plan(t, "Покажи, как менялась выручка по кварталам.")
    s = chart_spec_of(p, t)
    assert p.task.task == "dynamics" and s.categories == ["I кв. 2025", "II кв. 2025", "III кв. 2025", "IV кв. 2025"]
    assert s.series[0].values == [190.0, 210.0, 230.0, 250.0] and p.headline == "Выручка выросла на 32% за 3 квартала"


# ── N9: части целого по времени ───────────────────────────────────────────────────────────────────────────────────
def test_composition_over_time_headlines_the_whole():
    rows = [["Месяц", "Терапия", "Хирургия", "Педиатрия", "Всего"]]
    for m in range(1, 13):
        a, b, c = 800 + 5 * m, 400, 600 - 10 * m
        rows.append([f"2025-{m:02d}", a, b, c, a + b + c])
    t = _t("Пациенты по отделениям 2025.csv", rows)
    p = _plan(t)
    assert p.headline == "Число пациентов снизилось на 3,1% за 11 месяцев, сильнее всех — педиатрия: −19%", p.headline


# ── N10: план и факт другими словами ──────────────────────────────────────────────────────────────────────────────
def test_plan_fact_synonyms():
    for pl, fa, word in (("Утверждено", "Исполнено", "Бюджет исполнен"), ("Лимит", "Освоено", "Бюджет исполнен"),
                         ("Норматив", "Фактически", "Норматив выполнен")):
        t = _t("Исполнение.csv", [["Статья", f"{pl}, тыс. ₽", f"{fa}, тыс. ₽"], ["А", 100, 90], ["Б", 200, 210], ["В", 50, 40]])
        p = _plan(t)
        assert p.headline.startswith(f"{word} на 97%"), (pl, p.headline)


# ── N11: полнота по ритму ряда ────────────────────────────────────────────────────────────────────────────────────
def test_business_days_and_closed_new_year_are_complete():
    rows = [["Дата", "Отгрузки, шт."]]
    d = dt.date(2024, 1, 1)
    while d <= dt.date(2025, 12, 31):
        if d.weekday() < 5:
            rows.append([d.isoformat(), 500])
        d += dt.timedelta(days=1)
    t = _t("Отгрузки.csv", rows)
    p = _plan(t)
    assert len(chart_spec_of(p, t).categories) == 24 and "неполн" not in _sp(p.caption)
    rows = [["Дата", "Выручка, тыс. ₽"]] + [[(dt.date(2025, 1, 2) + dt.timedelta(days=k)).isoformat(), 100]
                                            for k in range(364)]
    t = _t("Магазин.csv", rows)
    assert chart_spec_of(_plan(t), t).categories[0] == "янв 2025"


def test_partial_edge_period_note_is_in_genitive():
    rows = [["Дата", "Выручка, тыс. ₽"]] + [[(dt.date(2025, 1, 28) + dt.timedelta(days=k)).isoformat(), 100]
                                            for k in range(400)]
    t = _t("Выручка по дням.csv", rows)
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert s.categories[0] == "фев 2025" and "январь 2025 — 4 из 31 дня" in _sp(slide_note(p))
    assert count_gen(31, "дня", "дней") == "31 дня" and count_gen(30, "дня", "дней") == "30 дней"


def slide_note(p: DatasetPlan) -> str:
    return " ".join(o.aggregation or "" for o in p.options) + " " + (p.caption or "")


# ── N12: ориентир ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_benchmark_row_is_a_reference_not_a_category():
    t = _t("Баллы школ.csv", [["Школа", "Средний балл"], ["Лицей № 2", "81,4"], ["Гимназия № 5", "78,9"],
                              ["Среднее по стране", "62,3"], ["Школа № 44", "68,5"]])
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert "Среднее по стране" not in s.categories and "Среднее по стране" not in p.headline
    assert _sp(p.headline) == "Лицей № 2 впереди: 81,4, Школа № 44 — 68,5"
    assert _sp(p.caption).startswith("Среднее по стране — 62,3: выше — 3 из 3")


# ── N13: колонки одной единицы ────────────────────────────────────────────────────────────────────────────────────
def test_same_unit_columns_grouped_or_named():
    t = _t("Зарплаты.csv", [["Грейд", "Минимум, тыс. ₽", "Медиана, тыс. ₽", "Максимум, тыс. ₽"], ["Стажёр", 45, 52, 60],
                            ["Специалист", 70, 85, 105], ["Директор", 110, 132, 160]])
    p = _plan(t)
    assert p.options[0].kind in ("grouped_bar", "grouped_column")
    assert _sp(p.headline) == "Директор впереди по медиане: 132 тыс. ₽, Стажёр — 52 тыс. ₽"
    ages = [f"{10 * i}–{10 * i + 9}" for i in range(7)] + ["70 и старше"]
    t = _t("Население.csv", [["Возраст", "Мужчины, тыс. чел.", "Женщины, тыс. чел."]]
           + [[a, 1000 + 10 * k, 900 + (500 if k == 7 else 0)] for k, a in enumerate(ages)])
    p = _plan(t)
    assert len(chart_spec_of(p, t).series) == 2 and "женщины: 70 и старше" in p.headline
    t = _t("Регионы.csv", [["Регион", "Выручка, млн ₽", "Прибыль, млн ₽"], ["Москва", 1840, 312], ["Казань", 300, -12],
                           ["Омск", 95, 4]])
    p = _plan(t)
    assert any("«Прибыль» — в таблице" in r for r in p.options[0].reasons), p.options[0].reasons


# ── N14: единица в подписи показателя ─────────────────────────────────────────────────────────────────────────────
def test_kpi_unit_inside_the_label():
    t = _t("Два показателя.csv", [["Показатель", "Значение"], ["Выручка, млн ₽", "412,7"], ["Клиентов", "1 845"]])
    p = _plan(t)
    assert _sp(p.headline) == "Выручка — 413 млн ₽"
    col = next((k for k, o in enumerate(p.options) if o.kind == "column"), None)
    assert col is None or isinstance(chart_spec_of(p, t, option=col), NotBuilt)


# ── N15: русский язык ─────────────────────────────────────────────────────────────────────────────────────────────
def test_russian_names_of_events_and_plurals():
    assert is_counter("Доставок") and is_counter("Обращений") and not is_counter("Остаток")
    assert metric_phrase("Доставлено").nom == "Число доставок"
    assert metric_phrase("Добавили в корзину").gen == "добавивших в корзину"
    assert metric_phrase("Уволилось").nom == "Число уволившихся"
    assert phrase("Поступления").gender == "pl" and phrase("Компания").gender == "f"
    assert lower_first("III кв.") == "III кв." and lower_first("I кв.") == "I кв."
    t = _t("Доставки по рабочим дням.csv", [["Дата", "Доставок"]] + [[(dt.date(2025, 1, 6) + dt.timedelta(days=k)).isoformat(),
                                                                     400 + k] for k in range(60) if
                                                                    (dt.date(2025, 1, 6) + dt.timedelta(days=k)).weekday() < 5])
    assert _plan(t).headline.startswith("Число доставок выросло")
    t = _t("Денежный поток.csv", [["Месяц", "Поступления, тыс. ₽", "Платежи, тыс. ₽"]]
           + [[f"2025-{m:02d}", 4000 + 300 * m, 4500 + 100 * m] for m in range(1, 13)])
    p = _plan(t)
    assert p.headline.startswith("Поступления выросли") and ": поступления — с" in _sp(p.caption)


# ── мелочи ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_minor_wording():
    # r в причинах — не больше 0,99; «час» внутри слова — не причина
    t = _t("Коды.csv", [["Код", "Участников", "Выручка, тыс. ₽"]] + [[f"М-{100 + i}", 20 + 3 * i, 150 + 25 * i] for i in range(20)])
    p = _plan(t)
    assert "r = 0,99" in " ".join(p.options[0].reasons) and "на единицу" not in p.headline
    # ничья названа честно
    t = _t("Оценки.csv", [["Отдел", "Оценка"], ["Продажи", "3,8"], ["ИТ", "3,2"], ["Склад", "3,2"]])
    assert _sp(_plan(t).headline) == "Продажи впереди: 3,8, ИТ и Склад — 3,2"
    # год к году — прямо в подписи
    t = _t("Выручка.csv", [["Месяц", "Выручка, млн ₽"]] + [[f"{2025 + (m - 1) // 12}-{(m - 1) % 12 + 1:02d}", 100 + 3 * m]
                                                           for m in range(1, 22)])
    p = _plan(t)
    assert p.headline.endswith("к сентябрю 2025") and _sp(p.caption).startswith("Сентябрь 2026 к сентябрю 2025: 163 млн ₽ против")
    # ответы по шкале: «в среднем по N утверждениям»
    t = _t("Опрос.csv", [["Утверждение", "Не согласен", "Скорее нет", "Скорее да", "Согласен"],
                         ["Цели понятны", 10, 20, 40, 30], ["Есть рост", 20, 30, 30, 20], ["Хватает инструментов", 5, 15, 50, 30]])
    assert _plan(t).headline.startswith("В среднем по 3 утверждениям: скорее да — 40%")
    # воронка без «Итого»
    t = _t("Воронка.csv", [["Этап", "Количество"], ["Показы", 1000], ["Клики", 100], ["Заявки", 10]])
    p = _plan(t)
    assert not any(r[0] == "Итого" for tb in _tables(p, t) for r in tb.rows)
    # «..» нет ни в подписях, ни в объяснениях фактов
    t = _t("Итоги.csv", [["Показатель", "2026", "2025"], ["Охват, тыс. чел.", 450, 300], ["Выпуск, шт.", 1840, 1000]])
    p = _plan(t)
    assert not any(re.search(r"(?<!\.)\.\.(?!\.)", f.text + f.explain) for f in p.headline_facts)
    # кольцо по частям без группы шапки — без «по частям в целом»
    t = _t("Приём.csv", [["Направление", "Бюджет, чел.", "Платное, чел.", "Всего, чел."], ["А", 10, 20, 30], ["Б", 15, 5, 20],
                         ["В", 7, 3, 10]])
    p = _plan(t)
    assert all("по частям в целом" not in o.title for o in p.options)
