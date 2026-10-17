"""Регрессии второй проверки сходимости (Task 7, раунд 8, `.superpowers/sdd/s2/conv2-findings.md` и живая проверка
`qa2-report.md`): цели не теряются (M1), связь при оси времени (M2), месяцы и кварталы без года (M3), перекрёстные
таблицы (M4), «Прочее» без выделения (M5), частотные таблицы (M6), ничьи в топе (M7), шум вместо тренда (M8),
опечатки в ряду (M9), величина на душу (M10), «растёт быстрее всех» у того, кто растёт (F1), отклонение от плана — не
рост (F2), пропуски не нули и год к году по общим месяцам (F3), слова (W1–W7), допуск воронки (V1), открытый столбец
гистограммы (A1), выделение и рост (A4), правило выбросов словами (R2). Таблицы — синтетические, через настоящее чтение
и профиль."""

from __future__ import annotations

import datetime as dt
import random
import re

from verstka.data.parse import split_unit
from verstka.data.plan import chart_spec_of, plan_dataset, plan_datasets, slide_data_of
from verstka.data.profile import profile_table
from verstka.data.readers import read_bytes
from verstka.schemas.data import DatasetPlan, Table

NB = " "
MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь",
          "Декабрь"]


def _csv(rows: list[list], sep: str = ";") -> str:
    return "\n".join(sep.join("" if c is None else str(c) for c in r) for r in rows) + "\n"


def _t(name: str, rows: list[list]) -> Table:
    return read_bytes(name, _csv(rows).encode("utf-8"))[0]


def _plan(t: Table, brief: str = "") -> DatasetPlan:
    prof = profile_table(t)
    return plan_datasets([t], brief, profiles=[prof])[0] if brief else plan_dataset(prof, t)


def _sp(s: str) -> str:
    return (s or "").replace(NB, " ")


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(NB, "").replace(",", "."))


# ── F1/F2: «растёт быстрее всех» — у того, кто растёт; отклонение от плана — не рост ─────────────────────────────────
def test_growth_clause_sits_next_to_the_grower():
    t = _t("Средний чек по магазинам.csv", [["Магазин", "Средний чек, ₽", "Рост за год, %"], ["Арбат", 1540, "12,4"],
                                            ["Тверская", 1290, "5,1"], ["Марьино", 980, "3,2"], ["Бутово", 1050, "4,0"]])
    h = _sp(_plan(t).headline)
    assert h.startswith("Арбат впереди и растёт быстрее всех"), h
    assert not re.search(r"Марьино — 980 ₽ и раст", h)


def test_plan_deviation_is_not_growth():
    rows = [["Категория", "Δ к 2024, %", "Δ к плану, %"], ["Молочная", "+4,2", "-1,5"], ["Хлеб", "+1,8", "+0,6"],
            ["Мясо", "-3,4", "-5,2"], ["Овощи", "+7,9", "+2,1"], ["Напитки", "+12,6", "+4,4"]]
    p = _plan(_t("Изменение продаж.csv", rows))
    text = _sp(p.headline + " " + (p.caption or ""))
    assert "быстрее всех" not in text and _sp(p.headline).startswith("Напитки впереди: +12,6%"), text
    rows = [["Магазин", "Выручка, млн ₽", "Отклонение от плана, %"], ["А", 120, "+9"], ["Б", 300, "-2"], ["В", 80, "+1"]]
    p = _plan(_t("Выручка магазинов.csv", rows))
    assert "быстрее всех" not in _sp(p.headline + " " + (p.caption or ""))


# ── F3: годы колонками, месяцы без года, пропуски — не нули ────────────────────────────────────────────────────────────
def test_year_columns_compare_common_months_and_keep_gaps():
    v24 = [312, 298, 341, 356, 372, 365, 381, 377, 359, 368, 374, 412]
    v25 = [334, 319, 362, 371, 395, 388, 402, 399, 381, None, None, None]
    t = _t("Перевозки пассажиров, тыс. чел.csv", [["Месяц", "2024", "2025"]]
           + [[m, a, "" if b is None else b] for m, a, b in zip(MONTHS, v24, v25)])
    for brief in ("", "Сравни 2025 год с 2024"):
        p = _plan(t, brief)
        h = _sp(p.headline)
        pct = (sum(v25[:9]) / sum(v24[:9]) - 1) * 100
        assert h.startswith(f"2025 к 2024: +{round(pct)}% за январь–сентябрь") and "выше во всех 9 месяцах" in h, h
        for k in range(len(p.options)):
            s = chart_spec_of(p, t, option=k)
            for x in getattr(s, "series", []):
                if x.name == "2025":
                    assert x.values[-3:] == [None, None, None] and 0.0 not in x.values


def test_grouped_bars_keep_missing_values_empty():
    t = _t("Продажи по каналам.csv", [["Регион", "Онлайн, млн ₽", "Офлайн, млн ₽"], ["Москва", 120, 80],
                                      ["Казань", 40, None], ["Омск", 30, 25]])
    p = _plan(t)
    for k, o in enumerate(p.options):
        if o.kind.startswith(("grouped", "stacked")):
            s = chart_spec_of(p, t, option=k)
            assert all(v != 0.0 for x in s.series for v in x.values), s.series


# ── M1/M10: цели не теряются, слова величины на душу ─────────────────────────────────────────────────────────────────
def test_unfulfillable_goal_is_noted_not_dropped():
    t = _t("Продажи по регионам.csv", [["Регион", "Продажи, шт."], ["Центр", 18420], ["Юг", 11240], ["Урал", 8650]])
    p = _plan(t, "Покажи рост продаж по годам")
    note = [r for r in p.task.reasons if r.startswith("Цель «покажи рост продаж по годам» здесь не подходит")]
    assert note and "нет оси времени" in note[0]
    assert any(r == note[0] for r in slide_data_of(p).task.reasons)  # видно в «Почему так»


def test_rate_goal_uses_per_capita_column():
    t = _t("Врачи на 1000 жителей.csv", [["Регион", "Население, тыс. чел.", "Врачей, чел.", "Врачей на 1 000 жителей"],
                                         ["Москва", "13 150", "61 200", "4,65"], ["Санкт-Петербург", "5 600", "33 800",
                                                                                 "6,04"],
                                         ["Самарская область", "3 150", "14 200", "4,51"]])
    p = _plan(t, "Сравни регионы по обеспеченности врачами")
    assert p.task.goal and _sp(p.headline).startswith("Выше всего — Санкт-Петербург: 6,04"), p.headline
    t = _t("Преступность.csv", [["Регион", "Зарегистрировано преступлений", "На 100 тыс. населения"],
                                ["Тыва", 7120, "2130,5"], ["Москва", 152300, "1158,1"], ["Дагестан", 9850, "312,4"]])
    p = _plan(t, "Сравни регионы по уровню преступности")
    assert p.task.goal and _sp(p.headline).startswith("Выше всего — Тыва: 2 130"), p.headline
    rows = [["Категория", "Δ к 2024, %"], ["Молочная", "+4,2"], ["Хлеб", "+1,8"], ["Мясо", "-3,4"]]
    assert _plan(_t("Изменение продаж.csv", rows), "Сравни категории по изменению продаж").task.goal


def test_names_and_declension_of_counters():
    t = _t("Врачи.csv", [["Регион", "Врачей, чел."], ["Москва", 61200], ["Тверь", 9000], ["Омск", 12000]])
    assert "врачей" in _sp(_plan(t).headline) and "врачея" not in _plan(t).headline


# ── M2: связь при оси времени ──────────────────────────────────────────────────────────────────────────────────────
def test_relationship_with_a_date_column_when_asked():
    r = random.Random(3)
    rows = [["Дата", "Посетители", "Выручка, ₽"]]
    for k in range(60):
        v = r.randint(400, 1400)
        rows.append([(dt.date(2026, 1, 1) + dt.timedelta(days=k)).isoformat(), v, int(v * r.uniform(950, 1050))])
    p = _plan(_t("Посещаемость и выручка.csv", rows), "Есть ли связь между посещаемостью и выручкой")
    assert p.task.task == "relationship" and "r = 0,9" in _sp(p.headline), p.headline


# ── M3: месяцы и кварталы без года ─────────────────────────────────────────────────────────────────────────────────
def test_month_names_without_year_are_a_time_axis():
    vals = [57.7, 45.9, 58.7, 46.1, 61.1, 45.3, 44.7, 38.2, 49.5, 53.7, 60.2, 45.5]
    t = _t("Продажи.csv", [["Месяц 2025", "Продажи за месяц, млн ₽"]] + [[m, str(v).replace(".", ",")]
                                                                        for m, v in zip(MONTHS, vals)])
    p = _plan(t, "Покажи рост продаж за год")
    assert p.task.task == "dynamics" and p.profile.time_axis.start == "2025-01"
    assert chart_spec_of(p, t).categories[0] == "янв 2025"
    temp = [-9.8, -8.6, -2.4, 5.3, 12.8, 17.1, 19.4, 17.2, 11.3, 4.6, -1.9, -6.7]
    t = _t("Температура.csv", [["Месяц", "Средняя температура, °C"]] + [[m, str(v).replace(".", ",")]
                                                                       for m, v in zip(MONTHS, temp)])
    p = _plan(t)
    assert p.task.task == "dynamics" and chart_spec_of(p, t).categories[:2] == ["янв", "фев"]
    h = _sp(p.headline)
    assert h == "Средняя температура: от −9,8 °C (январь) до 19,4 °C (июль), 5 месяцев ниже нуля", h
    # учебный год: сентябрь … август — ось через конец года, порядок как в файле
    t = _t("Посещаемость 2025.csv", [["Месяц", "Посещаемость, %"]] + [[m, 90 + k % 3] for k, m in
                                                                      enumerate(MONTHS[8:] + MONTHS[:8])])
    p = _plan(t)
    assert p.profile.time_axis.start == "2025-09" and p.profile.time_axis.end == "2026-08"


def test_cumulative_column_is_not_a_second_series():
    rows = [["Месяц 2025", "Продажи за месяц, млн ₽", "Нарастающим итогом, млн ₽"]]
    cum = 0.0
    for k, m in enumerate(MONTHS[:6]):
        v = 40 + 5 * k
        cum += v
        rows.append([m, v, cum])
    t = _t("Продажи.csv", rows)
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert [x.name for x in s.series] == ["Продажи за месяц"] and p.headline.startswith("Продажи за месяц")


# ── M4: перекрёстные таблицы ───────────────────────────────────────────────────────────────────────────────────────
DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def test_crosstab_compares_rows_or_columns_never_one_column():
    rows = [["Час"] + DAYS] + [[f"{h}:00"] + [10 * (h % 5 + 1) + d for d in range(7)] for h in range(11, 19)]
    t = _t("Заказы ресторана по часам.csv", rows)
    p = _plan(t)
    s = chart_spec_of(p, t)
    sums = {r[0]: sum(r[1:]) for r in rows[1:]}
    lead = max(sums, key=sums.get)
    # без цели — итог строки по всем дням (доля — от всех заказов недели), а не столбец «Пн»
    assert s.series[0].name.startswith("Сумма Пн–Вс") and lead in p.headline and "Пн:" not in p.headline
    p = _plan(t, "Сравни дни недели по числу заказов")
    s = chart_spec_of(p, t)
    col = {d: sum(r[k + 1] for r in rows[1:]) for k, d in enumerate(DAYS)}
    assert s.categories[0] == max(col, key=col.get) and s.series[0].values[0] == max(col.values())
    subj = ["Алгебра", "Геометрия", "Физика", "История"]
    rows = [["Ученик"] + subj, ["Андреев И.", "4,2", "3,9", "4,0", "4,8"], ["Белова М.", "4,8", "4,7", "4,6", "5,0"],
            ["Васильев П.", "3,4", "3,1", "3,5", "4,1"], ["Ершова Л.", "4,9", "4,8", "4,7", "4,9"]]
    p = _plan(_t("Оценки 9Б.csv", rows), "Сравни предметы по средней оценке")
    assert _sp(p.headline).startswith("История впереди: 4,7"), p.headline
    # варианты одной величины — не перекрёстная таблица: «Город · Трасса · Смешанный»
    t = _t("Расход топлива.csv", [["Модель", "Город, л/100 км", "Трасса, л/100 км", "Смешанный, л/100 км"],
                                  ["Kia Rio", "8,1", "5,2", "6,3"], ["Lada Vesta", "9,1", "5,9", "7,1"],
                                  ["Haval", "11,4", "7,2", "8,8"]])
    assert "Сумма" not in _plan(t).headline and "среднее" not in _plan(t).headline


# ── M5: «Прочее» без выделения ─────────────────────────────────────────────────────────────────────────────────────
def test_other_row_is_never_highlighted():
    t = _t("Продажи аптеки.csv", [["Группа", "Продажи, тыс. ₽"], ["Витамины", 1512], ["Анальгетики", 1284],
                                  ["Антибиотики", 936], ["Прочее", 1690]])
    p = _plan(t)
    for k in range(len(p.options)):
        s = chart_spec_of(p, t, option=k)
        if getattr(s, "highlight_index", None) is not None:
            assert s.categories[s.highlight_index] != "Прочее"


# ── M6: частотная таблица ──────────────────────────────────────────────────────────────────────────────────────────
def test_frequency_table_is_a_weighted_distribution():
    t = _t("Оценки за контрольную.csv", [["Оценка", "Число учеников"], [2, 14], [3, 61], [4, 88], [5, 47]])
    p = _plan(t, "Как распределены оценки за контрольную")
    assert p.task.task == "distribution" and p.task.goal
    assert _sp(p.headline) == "Чаще всего — оценка 4: 88 учеников из 210, 42%", p.headline
    assert "В среднем — 3,8, медиана — 4" in _sp(p.caption)
    s = chart_spec_of(p, t)
    assert s.categories == ["2", "3", "4", "5"] and s.series[0].values == [14, 61, 88, 47]


def test_reference_table_keeps_every_number_column():
    rows = [["Клиент", "Отрасль", "Выручка, млн ₽", "Сделок"]] + [[f"Клиент {k:02d}", ["ИТ", "Ритейл"][k % 2], 500 - k,
                                                                    10 + k] for k in range(40)]
    t = _t("Клиенты.csv", rows)
    p = _plan(t)
    tab = next(k for k, o in enumerate(p.options) if o.kind == "table")
    assert any("Сделок" in c for c in chart_spec_of(p, t, option=tab).columns)


# ── M7: ничья в топе ───────────────────────────────────────────────────────────────────────────────────────────────
def test_ties_at_the_top_are_named_as_ties():
    rows = [["ID клиента", "Возраст", "Средний чек, ₽"]] + [[f"C-{5000 + k}", 75 if k % 9 == 0 else 20 + k % 50,
                                                              1000 + k] for k in range(60)]
    p = _plan(_t("Возраст и чек.csv", rows))
    if p.task.task == "reference":
        k = sum(1 for r in rows[1:] if r[1] == 75)
        assert _sp(p.headline).startswith(f"{k} клиентов — по 75") and "первое место" not in p.headline, p.headline


# ── M8: шум вместо тренда ──────────────────────────────────────────────────────────────────────────────────────────
def test_noisy_series_compares_means_not_endpoints():
    vals = [57.7, 45.9, 58.7, 46.1, 61.1, 45.3, 44.7, 38.2, 49.5, 53.7, 60.2, 45.5]  # t ≈ −0,5
    t = _t("Продажи.csv", [["Месяц", "Продажи, млн ₽"]] + [[f"2025-{k + 1:02d}", v] for k, v in enumerate(vals)])
    h = _sp(_plan(t).headline)
    assert "−21%" not in h and "21%" not in h and ("без выраженного тренда" in h or "в среднем" in h), h
    t = _t("Выручка.csv", [["Месяц", "Выручка, млн ₽"]] + [[f"2025-{k + 1:02d}", 100 + 10 * k] for k in range(12)])
    assert "за 11 месяцев" in _sp(_plan(t).headline)  # настоящий тренд — по краям, как раньше


# ── M9: опечатка в ряду ────────────────────────────────────────────────────────────────────────────────────────────
def test_typo_outlier_is_named_and_left_out_of_the_series():
    vals = [4210, 4385, 4520, 4610, 4475, 4702, 4520000, 4810, 4655, 4890, 5012, 5240]
    t = _t("Продажи по месяцам.csv", [["Месяц", "Продажи, шт."]] + [[f"{m} 2025", v] for m, v in zip(MONTHS, vals)])
    p = _plan(t)
    assert _sp(p.headline) == "Продажи выросли на 24% за 11 месяцев", p.headline
    assert "Июль 2025 — 4 520 000 шт.: похоже на опечатку" in _sp(p.caption)
    s = chart_spec_of(p, t)
    assert s.series[0].values[6] is None and "без выброса: июль 2025" in s.series[0].name


# ── W2–W7: слова ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_rates_and_wording():
    assert split_unit("Ставка, % годовых") == ("Ставка", "%")
    t = _t("Ставки по ипотеке.csv", [["Банк", "Ставка, % годовых"], ["Сбербанк", "20,9"], ["Т-Банк", "24,4"],
                                     ["ДОМ.РФ", "19,5"]])
    assert _sp(_plan(t).headline) == "Выше всего — Т-Банк: 24,4%, ниже всего — ДОМ.РФ: 19,5%"
    t = _t("Воронка.csv", [["Этап", "Пользователей"], ["Визит на сайт", 184500], ["Просмотр товара", 92300],
                           ["Добавление в корзину", 21870], ["Оплата", 7215]])
    p = _plan(t)
    assert _sp(p.headline).startswith("До этапа «Оплата» доходит 3,9% от этапа «Визит на сайт»")
    # V1: 23,69% записано как «24%» — верно; подпись не понижена
    assert "дальше проходит 24%" in _sp(p.caption) and not any("не подтвердил" in r for r in p.task.reasons)
    qs = ["I кв. 2024", "II кв. 2024", "III кв. 2024", "IV кв. 2024", "I кв. 2025", "II кв. 2025", "III кв. 2025"]
    vs = ["812,4", "945,1", "1 021,7", "1 388,2", "768,9", "902,3", "984,6"]
    t = _t("Ввод жилья.csv", [["Период", "Ввод жилья, тыс. м²"]] + [[q, v] for q, v in zip(qs, vs)])
    assert _sp(_plan(t).headline).endswith("к III кварталу 2024")
    t = _t("Active users 2026.csv", [["Month", "Active users, тыс."]] + [[f"{m} 2026", v] for m, v in
                                                                        zip(["January", "February", "March", "April"],
                                                                            [184.2, 191.5, 203.8, 236.7])])
    h = _sp(_plan(t).headline)
    assert h.startswith("Active users: +") and "вырос" not in h, h


def test_target_series_is_a_reference_not_zero_change():
    sla = [81.4, 79.8, 83.2, 77.5, 74.9, 72.3, 76.8, 80.1, 82.6, 84.0, 85.3, 83.7]
    rows = [["Неделя", "Доля звонков, принятых за 20 сек, %", "Цель, %"]]
    for k, v in enumerate(sla):
        rows.append([(dt.date(2026, 6, 1) + dt.timedelta(weeks=k)).strftime("%d.%m.%Y"), str(v).replace(".", ","), "80"])
    h = _sp(_plan(_t("SLA.csv", rows)).headline)
    below = sum(1 for v in sla if v < 80)
    assert f"ниже цели 80% в {below} из 12 недель" in h and "цель: 0" not in h, h


def test_month_names_lowercase_mid_sentence():
    t = _t("Продажи по месяцам года.csv", [["Месяц", "Продажи, шт."], ["Июль", 50], ["Январь", 10], ["Май", 30],
                                           ["Ноябрь", 20]])
    p = _plan(t)
    assert not re.search(r"\S (Июль|Январь|Май|Ноябрь)", _sp(p.headline) + " " + _sp(p.caption or "")), p.headline


# ── A1/R2: открытый столбец гистограммы и правило выбросов ─────────────────────────────────────────────────────────
def test_open_bin_counts_every_value_and_caption_agrees():
    r = random.Random(5)
    vals = [round(r.gammavariate(2.0, 25.0)) for _ in range(400)] + [900, 1200, 1500]
    t = _t("Время ответа.csv", [["Обращение", "Минут до ответа"]] + [[f"T-{k}", v] for k, v in enumerate(vals)])
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert sum(s.series[0].values) == len(vals)
    last = s.categories[-1]
    assert last.startswith("больше ")
    thr = _num(last.split("больше ")[1])
    assert s.series[0].values[-1] == sum(1 for v in vals if v > thr)
    assert f"в столбце «{last}»" in p.caption and "отмечены отдельно" not in p.caption
    exp = next(f.explain for f in p.headline_facts if f.id == "outliers")
    assert "1,5 межквартильного размаха" in exp and "промежутком" in exp


# ── A4: выделен тот, кто назван ────────────────────────────────────────────────────────────────────────────────────
def test_highlighted_bar_is_named_in_the_headline():
    t = _t("Регионы.csv", [["Регион", "Выручка, млн ₽", "Рост за год, %"], ["Москва", 1400, "8"], ["Казань", 300, "38"],
                           ["Омск", 200, "5"], ["Тверь", 150, "2"]])
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert "Казань растёт быстрее всех" in p.headline
    assert s.highlight_index is None or s.categories[s.highlight_index] in p.headline


def test_goal_about_no_file_goes_to_the_deck_context():
    from verstka.data.plan import goal_notes
    from verstka.data.story import build_data_story
    from verstka.schemas.outline import Brief

    a = _t("Выручка по регионам.csv", [["Регион", "Выручка, млн ₽"], ["Центр", 500], ["Юг", 300], ["Урал", 200]])
    b = _t("Персонал по отделам.csv", [["Отдел", "Сотрудников"], ["Продажи", 48], ["ИТ", 64], ["HR", 6]])
    brief = "Сравни регионы по выручке. Покажи, как менялась погода на Марсе."
    plans = plan_datasets([a, b], brief)
    notes = goal_notes(brief, plans)
    assert notes and "погода на марсе" in notes[0].lower()
    st = build_data_story(Brief(text=brief), [a, b])
    ctx = [x for s in st.outline.slides if s.id.startswith("context") for x in s.content.bullets]
    assert any("погода на Марсе" in x or "погода на марсе" in x.lower() for x in ctx), ctx


# ── H4/H5: ось — по величине, группа рядов — в легенде; гистограмма по значениям ────────────────────────────────────
def test_stacked_axis_is_the_measure_and_group_is_the_legend():
    from pathlib import Path

    from verstka.data.readers import read_file

    t = read_file(Path(__file__).resolve().parents[2] / "examples" / "data-science-2026" / "Приём по направлениям.xlsx")[0]
    p = _plan(t)
    for k, o in enumerate(p.options):
        if o.kind.startswith(("stacked", "grouped")):
            s = chart_spec_of(p, t, option=k)
            assert s.legend_title == "Форма обучения" and s.y_title != "Форма обучения" and s.unit == "чел.", s


def test_few_distinct_values_get_a_bar_each():
    sizes = [2590] * 40 + [3090] * 8 + [4120] * 25 + [6500] * 9 + [8000] * 12 + [10000] * 6 + [55000] * 3
    t = _t("Стипендии.csv", [["Студент", "Размер, руб."]] + [[f"С-{k}", v] for k, v in enumerate(sizes)])
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert s.type == "histogram" and 0.0 not in s.series[0].values and sum(s.series[0].values) == len(sizes)
    assert s.categories[:3] == ["2 590".replace(" ", NB), "3 090".replace(" ", NB), "4 120".replace(" ", NB)]
    assert s.categories[-1].startswith("от ") and s.series[0].values[-1] == 3


# ── контекст файла на слайде данных ────────────────────────────────────────────────────────────────────────────────
def test_slide_carries_what_its_file_says():
    from pathlib import Path

    from verstka.data.plan import slide_data_of
    from verstka.data.readers import read_file

    root = Path(__file__).resolve().parents[2] / "examples" / "data-sales-2026"
    t = read_file(root / "Итоги квартала.txt")[0]
    c = slide_data_of(plan_datasets([t], "")[0], 1, t).context
    assert c and "Опрос NPS во II квартале 2025 и 2026 года не проводился" in c and len(c) <= 600
    assert "Итоги III квартала 2026 года — VK Cloud" not in c and "Подготовлено" not in c and "|" not in c
    t = read_file(root / "NPS по кварталам.csv")[0]
    assert slide_data_of(plan_datasets([t], "")[0], 1, t).context is None  # в CSV текста вокруг таблицы нет


def test_context_links_notes_across_files():
    """«Итоги квартала.txt» объясняет пропуск NPS — это предложение доходит и до слайда из «NPS по кварталам.csv», с
    названием файла-источника; в колоде — на самом слайде (`SlideData.context`)."""
    from pathlib import Path

    from verstka.data.plan import file_context
    from verstka.data.readers import read_file
    from verstka.data.story import build_data_story
    from verstka.schemas.outline import Brief

    root = Path(__file__).resolve().parents[2] / "examples" / "data-sales-2026"
    tables = [read_file(root / f)[0] for f in ("NPS по кварталам.csv", "Итоги квартала.txt")]
    plans = plan_datasets(tables, "")
    c = file_context(tables[0], plans[0], tables)
    assert c and c.startswith("«Итоги квартала.txt»: Опрос NPS во II квартале 2025 и 2026 года не проводился")
    assert len(c) <= 600
    st = build_data_story(Brief(text=""), tables)
    nps = next(s for s in st.outline.slides if s.data is not None and s.data.file == "NPS по кварталам.csv")
    assert "не проводился" in (nps.data.context or "") and "«Итоги квартала.txt»" in nps.data.context
