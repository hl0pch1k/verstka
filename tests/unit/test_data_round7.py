"""Регрессии проверки сходимости (Task 7, раунд 7, `.superpowers/sdd/s2/conv-findings.md`): доли по той же колонке, что
названа (C1), малые значения (C2), перечни и «держится» (C3), часы суток и счёт событий (C4), длительности — не номера
(C5), составные единицы (M1), «Показатель А/Б» (M2), главная метрика по файлу и цели (M3), сложные слова и порядок слов в
целях (M4), коды ответа (M5), все нули (M6), «Прочие» в кольце (M7), сравнение без рядов по дате (M8), пик уровня (M9),
направление «впереди» (W1), грамматика (W2), огромные числа (W3), «% г/г» (W4). Таблицы — синтетические, через настоящее
чтение и профиль."""

from __future__ import annotations

import datetime as dt
import re

from verstka.data.goals import goals_of
from verstka.data.parse import split_unit
from verstka.data.plan import chart_spec_of, plan_dataset, plan_datasets
from verstka.data.profile import profile_table
from verstka.data.readers import read_bytes
from verstka.data.words import fmt_num, stem
from verstka.schemas.data import DatasetPlan, Table
from verstka.schemas.outline import ChartSpec, TableData

NB = " "


def _csv(rows: list[list], sep: str = ";") -> str:
    return "\n".join(sep.join("" if c is None else str(c) for c in r) for r in rows) + "\n"


def _t(name: str, rows: list[list], sep: str = ";") -> Table:
    return read_bytes(name, _csv(rows, sep).encode("utf-8"))[0]


def _plan(t: Table, brief: str = "") -> DatasetPlan:
    prof = profile_table(t)
    return plan_datasets([t], brief, profiles=[prof])[0] if brief else plan_dataset(prof, t)


def _f(p: DatasetPlan) -> dict:
    return {f.id: f for f in p.headline_facts}


def _sp(s) -> str:
    return (s or "").replace(NB, " ")


# ── C1: доля — по той колонке, что названа ────────────────────────────────────────────────────────────────────────
INSURANCE = [["Вид страхования", "Число выплат", "Сумма выплат, млн руб.", "Средняя выплата, тыс. руб."],
             ["ОСАГО", 41250, "4620,5", "112,0"], ["КАСКО", 18340, "3815,2", "208,0"], ["ДМС", 96210, "2140,8", "22,3"],
             ["Имущество", 5120, "912,4", "178,2"], ["Жизнь", 2210, "1288,0", "582,8"]]


def test_share_headline_names_the_summed_column():
    t = _t("Страховые выплаты по видам.csv", INSURANCE)
    p = _plan(t, "Покажи структуру выплат по видам страхования.")
    assert p.task.task == "shares"
    amount = {r[0]: float(r[2].replace(",", ".")) for r in INSURANCE[1:]}
    lead = max(amount, key=amount.get)
    share = amount[lead] / sum(amount.values()) * 100
    assert p.headline.startswith(lead) and f"{round(share)}%" in p.headline and "суммы выплат" in p.headline
    # заголовок называет ту же колонку, что на графике: доли кольца — по суммам, не по числу выплат
    s = chart_spec_of(p, t)
    assert abs(s.series[0].values[s.categories.index(lead)] - round(share, 1)) < 0.05


def test_subject_ties_prefer_money_for_structure_and_percent_for_rates():
    t = _t("AB-тест.csv", [["Вариант", "Пользователи", "Конверсии", "Конверсия, %"], ["A", 24310, 1094, "4,50"],
                          ["B", 24188, 1258, "5,20"], ["C", 24502, 1127, "4,60"]])
    for brief in ("", "Сравни варианты по конверсии."):
        p = _plan(t, brief)
        assert _sp(p.headline) == "B впереди: 5,2%, A — 4,5%", (brief, p.headline)


# ── C2: малые значения ────────────────────────────────────────────────────────────────────────────────────────────
def test_small_values_keep_two_significant_digits_and_raw_ties():
    assert [fmt_num(x) for x in (0.012, 0.006, 0.0035, 0.004)] == ["0,012", "0,006", "0,0035", "0,004"]
    assert fmt_num(0.004, 2) == "0,004"  # ненулевое — никогда не «0»
    t = _t("Примеси.csv", [["Проба", "Свинец, мг/л"], ["Скважина 1", "0,012"], ["Скважина 2", "0,008"],
                           ["Скважина 3", "0,031"], ["Скважина 4", "0,009"], ["Скважина 6", "0,006"]])
    p = _plan(t)
    assert _sp(p.headline) == "Больше всего — Скважина 3: 0,031 мг/л, меньше всего — Скважина 6: 0,006 мг/л"


# ── C3: перечень — не ряд; «держится» — только в узкой полосе ─────────────────────────────────────────────────────
def test_milestone_list_is_a_table_and_flat_needs_a_band():
    t = _t("Вехи проекта.csv", [["Веха", "Ответственный", "Начало", "Статус"],
                                ["Сбор требований", "Иванова", "03.02.2025", "Завершено"],
                                ["Проектирование", "Петров", "03.03.2025", "Завершено"],
                                ["Разработка", "Сидоров", "14.04.2025", "Завершено"],
                                ["Тестирование", "Орлова", "28.07.2025", "В работе"],
                                ["Пилот", "Петров", "08.09.2025", "Запланировано"]])
    p = _plan(t)
    assert p.task.task == "reference" and p.options[0].kind == "table" and "держится" not in p.headline
    rows = [["Месяц", "Заявок"]] + [[f"2025-{m:02d}", v] for m, v in enumerate([10, 40, 5, 60, 10], 1)]
    p = _plan(_t("Заявки.csv", rows))
    assert "держится" not in p.headline and _sp(p.headline) == "Число заявок: от 5 до 60, в конце — 10", p.headline
    rows = [["Месяц", "Заявок"]] + [[f"2025-{m:02d}", v] for m, v in enumerate([100, 101, 100, 99, 100], 1)]
    assert "держится на уровне 100" in _plan(_t("Заявки.csv", rows)).headline


# ── C4: часы суток и счёт событий ─────────────────────────────────────────────────────────────────────────────────
def test_hour_of_day_axis_is_not_merged_and_events_add_up():
    counts = [41, 28, 19, 14, 12, 18, 52, 131, 214, 168, 121, 117, 126, 134, 142, 171, 208, 251, 236, 187, 139, 102, 81, 63]
    t = _t("ДТП по часам суток.csv", [["Час", "ДТП"]] + [[f"{h:02d}:00", v] for h, v in enumerate(counts)])
    p = _plan(t)
    s = chart_spec_of(p, t)
    assert len(s.categories) == 24 and s.type == "column" and s.series[0].values[-1] == 63
    assert _sp(p.headline) == "Больше всего — 17:00: 251, меньше всего — 04:00: 12"
    assert "из 2 775" in _sp(p.caption)  # ДТП складываются: итог — сумма


def test_merged_level_tail_is_labelled_average():
    labs = [f"{5 * i}–{5 * i + 4}" for i in range(25)]
    t = _t("Средний доход.csv", [["Возраст", "Средний доход, тыс. ₽"]] + [[a, 30 + k] for k, a in enumerate(labs)])
    cats = chart_spec_of(_plan(t), t).categories
    assert len(cats) == 20 and cats[-1].endswith("(в среднем)")


# ── C5: длительность — не номер ───────────────────────────────────────────────────────────────────────────────────
def test_duration_column_is_a_measure_not_numbers():
    rows = [["ID", "Заголовок", "Приоритет", "Статус", "Компонент", "Дней открыт"]]
    for k in range(40):
        rows.append([f"BUG-{1200 + k}", f"Ошибка {k}", ["Высокий", "Низкий"][k % 2], ["Открыт", "Закрыт"][k % 3 % 2],
                     ["API", "Платежи", "Каталог"][k % 3], [1, 3, 8, 15, 21, 40][k % 6]])
    t = _t("Баг-трекер.csv", rows)
    p = _plan(t, "Как распределено время, которое баги остаются открытыми?")
    assert not (p.message or "").startswith("Не для графика")
    assert p.task.task == "distribution" and p.options[0].kind == "histogram" and "дней" in p.headline


# ── M1/W4: составные единицы ──────────────────────────────────────────────────────────────────────────────────────
def test_compound_units_are_rates():
    assert split_unit("Город, л/100 км") == ("Город", "л/100 км")
    assert split_unit("Свинец, мг/л") == ("Свинец", "мг/л")
    assert split_unit("Потребление, л/сут на человека") == ("Потребление", "л/сут на человека")
    assert split_unit("Рост ВВП, % г/г") == ("Рост ВВП", "%")
    assert split_unit("Город, регион") == ("Город, регион", None)
    t = _t("Расход топлива.csv", [["Модель", "Город, л/100 км", "Трасса, л/100 км", "Смешанный, л/100 км"],
                                  ["Lada Vesta", "9,1", "5,9", "7,1"], ["Kia Rio", "8,0", "5,0", "6,1"],
                                  ["Lada Niva", "12,1", "8,3", "10,0"]])
    p = _plan(t, "Сравни модели по расходу топлива.")
    assert "%" not in p.headline and "л/100 км" in p.headline and "leader_share" not in _f(p)
    assert all(o.kind not in ("pie", "doughnut") for o in p.options)
    t = _t("Рост ВВП.csv", [["Квартал", "Рост ВВП, % г/г"]] + [[f"{q} кв. 2024", f"{v}".replace(".", ",")]
                                                              for q, v in ((1, 5.4), (2, 4.1), (3, 3.1), (4, 4.5))])
    assert "%" in _plan(t).headline


# ── M2: «Показатель А/Б» ──────────────────────────────────────────────────────────────────────────────────────────
def test_anonymous_measure_pair_is_a_relationship():
    import random

    r = random.Random(7)
    rows = [["№", "Показатель А", "Показатель Б"]]
    for k in range(120):
        x = r.gauss(50, 12)
        rows.append([k + 1, f"{x:.2f}".replace(".", ","), f"{0.6 * x + r.gauss(0, 9) + 10:.2f}".replace(".", ",")])
    p = _plan(_t("Измерения.csv", rows), "Есть ли связь между показателем А и показателем Б?")
    assert p.task.task == "relationship" and p.options[0].kind == "scatter" and "%" not in p.headline


# ── M3: главная метрика ───────────────────────────────────────────────────────────────────────────────────────────
def test_main_metric_follows_file_title_and_goal():
    t = _t("Пробег автопарка октябрь.csv", [["Госномер", "Одометр на 1 октября, км", "Одометр на 31 октября, км",
                                             "Пробег за месяц, км"], ["А123ВС 77", 184210, 187950, 3740],
                                            ["Е789КХ 50", 241800, 243120, 1320], ["Н987УК 99", 18700, 23950, 5250]])
    p = _plan(t)
    assert p.headline.startswith("Н987УК 99") and "пробега за месяц" in p.headline
    t = _t("Загрузка отеля 2025.csv", [["Месяц", "Загрузка, %", "Средний тариф, руб."]]
           + [[f"2025-{m:02d}", f"{50 + 2 * m},0", 5000 + 100 * m] for m in range(1, 13)])
    assert _plan(t).headline.startswith("Загрузка")
    t = _t("Водопотребление по районам.csv", [["Район", "Население, чел.", "Потребление, л/сут на человека"],
                                              ["Центральный", 182400, 212], ["Северный", 241900, 176],
                                              ["Заречный", 94300, 241]])
    p = _plan(t, "Сравни районы по потреблению воды на человека.")
    assert p.task.goal and p.headline.startswith("Заречный") and "241 л/сут на человека" in _sp(p.headline)


# ── M4: цели — сложные слова, порядок слов, падежи ────────────────────────────────────────────────────────────────
def test_goal_matching_compounds_word_order_and_cases():
    assert stem("свинцу") == stem("Свинец") == "свинц"
    assert goals_of("Какие проекты лидируют по голосам?")[0].task == "comparison"
    t = _t("Голосование.csv", [["Проект", "Голоса"], ["Сквер", 4120], ["Велодорожка", 3870], ["Фонтан", 1240]])
    assert _plan(t, "Какие проекты лидируют по голосам?").task.goal == "какие проекты лидируют по голосам"
    t = _t("Примеси.csv", [["Проба", "Свинец, мг/л", "Кадмий, мг/л"], ["Скв. 1", "0,012", "0,004"],
                           ["Скв. 3", "0,031", "0,006"], ["Скв. 6", "0,006", "0,002"]])
    p = _plan(t, "Сравни скважины по свинцу.")
    assert p.task.goal == "сравни скважины по свинцу" and "0,031" in p.headline


# ── M5: коды ответа — категории ───────────────────────────────────────────────────────────────────────────────────
def test_http_status_codes_are_categories():
    t = _t("Ошибки сайта по кодам.csv", [["Код ответа", "Число ошибок"], [400, 1840], [404, 12450], [500, 1430],
                                         [503, 2980]], sep=",")
    p = _plan(t, "Из чего складываются ошибки сайта?")
    assert p.task.task == "shares" and p.headline == "404 — две трети ошибок: 67%"


# ── M6: все нули ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_all_zero_measure_has_no_leader_and_no_chart():
    t = _t("Возвраты по магазинам.csv", [["Магазин", "Возвраты, шт."]] + [[f"Магазин {k}", 0] for k in "АБВГД"])
    p = _plan(t)
    assert p.headline == "Возвратов нет ни в одном из 5 магазинов" and p.options[0].kind == "table"
    assert "leader_value" not in _f(p) and isinstance(chart_spec_of(p, t), TableData)


# ── M7: «Прочие» в кольце ─────────────────────────────────────────────────────────────────────────────────────────
def test_doughnut_merges_others_into_one_slice():
    rows = [["Бренд", "Доля рынка, %"], ["Xiaomi", "24,1"], ["Samsung", "19,8"], ["Apple", "17,2"], ["Realme", "9,6"],
            ["Tecno", "8,3"], ["Honor", "7,4"], ["Infinix", "4,2"], ["Прочие", "9,4"]]
    t = _t("Доли рынка смартфонов.csv", rows)
    p = _plan(t, "Покажи доли рынка смартфонов.")
    s = chart_spec_of(p, t)
    assert s.type == "doughnut" and s.categories[-1] == "Прочие" and not any(c.startswith("Остальные") for c in s.categories)
    assert abs(s.series[0].values[-1] - 21.0) < 0.05 and "Прочие (вместе с Honor и Infinix) — 21%" in _sp(p.caption)


# ── M8: сравнение категорий — без рядов по дате ───────────────────────────────────────────────────────────────────
def test_comparison_does_not_pull_same_unit_columns_by_date():
    rows = [["Дата", "Смена", "Выпущено, шт.", "Брак, шт."]]
    for k in range(6):
        for sh, b, d in (("Дневная", 1240, 18), ("Ночная", 980, 30)):
            rows.append([(dt.date(2025, 10, 6) + dt.timedelta(days=k)).strftime("%d.%m.%Y"), sh, b + k, d + k])
    t = _t("Выпуск по сменам.csv", rows)
    p = _plan(t, "Сравни смены по браку.")
    s = chart_spec_of(p, t)
    assert p.task.task == "comparison" and [x.name for x in s.series] == ["Брак"]


# ── M9: уровень с пиком ───────────────────────────────────────────────────────────────────────────────────────────
def test_level_series_leads_with_interior_peak_in_units():
    vals = [240, 250, 300, 420, 520, 480, 380, 300, 280]
    rows = [["Неделя", "Уровень воды, см"]] + [[(dt.date(2025, 4, 7) + dt.timedelta(weeks=k)).isoformat(), v]
                                              for k, v in enumerate(vals)]
    p = _plan(_t("Уровень воды.csv", rows))
    assert _sp(p.headline).startswith("Уровень воды: пик 520 см (нед. 19, 2025), к концу — 280 см")
    rows = [["Неделя", "Уровень воды, см"]] + [[(dt.date(2025, 4, 7) + dt.timedelta(weeks=k)).isoformat(), 240 + 5 * k]
                                              for k in range(9)]
    p = _plan(_t("Уровень воды.csv", rows))
    assert "на 40 см" in _sp(p.headline) and "%" not in p.headline  # уровень с произвольным нулём — в см, не в %


# ── W1: направление «впереди» ─────────────────────────────────────────────────────────────────────────────────────
def test_lower_is_better_measures_name_direction():
    t = _t("Задержки.csv", [["Аэропорт", "Средняя задержка, мин"], ["Сочи", 41], ["Казань", 17], ["Пулково", 22]])
    assert _sp(_plan(t).headline) == "Дольше всего — Сочи: 41 мин, меньше всего — Казань: 17 мин"
    t = _t("Провайдеры.csv", [["Провайдер", "Пинг, мс"], ["Ростелеком", 8], ["Мегафон", 17], ["МТС", 11]])
    assert _sp(_plan(t).headline) == "Медленнее всего — Мегафон: 17 мс, быстрее всего — Ростелеком: 8 мс"
    t = _t("Тарифы на электроэнергию.csv", [["Регион", "Пиковая зона, руб./кВт·ч"], ["Москва", "9,85"],
                                            ["Новосибирская область", "6,12"], ["Краснодарский край", "8,40"]])
    assert _plan(t).headline.startswith("Дороже всего — Москва")
    t = _t("Время в пути.csv", [["Транспорт", "Время в пути, мин"], ["Метро", 52], ["Автомобиль", 39], ["Автобус", 47]])
    assert _plan(t).headline.startswith("Дольше всего — Метро") and "быстрее всего — Автомобиль" in _plan(t).headline


# ── W2: грамматика ────────────────────────────────────────────────────────────────────────────────────────────────
def test_grammar_plurals_irregular_span_and_output_noun():
    rows = [["Месяц", "Активные абонементы", "Новые"]] + [[f"2025-{m:02d}", 1800 + 60 * m, 330 - 18 * m]
                                                       for m in range(1, 11)]
    assert "новые снизились" in _plan(_t("Абонементы.csv", rows)).headline
    rows = [["Дата рассылки", "Открываемость, %", "CTR, %"]]
    for k, (o, c) in enumerate([(25.8, 2.83), (26.2, 2.7), (24.0, 2.5), (22.1, 2.2), (18.8, 1.89)]):
        rows.append([(dt.date(2025, 6, 3) + dt.timedelta(days=9 * k + (k % 3))).strftime("%d.%m.%Y"),
                     f"{o}".replace(".", ","), f"{c}".replace(".", ",")])
    p = _plan(_t("Рассылки.csv", rows))
    assert "точек" not in p.headline and "за период" in p.headline
    rows = [["Дата", "Выпущено, шт."]] + [[(dt.date(2025, 10, 6) + dt.timedelta(days=k)).isoformat(), 3300 + 10 * k]
                                         for k in range(10)]
    assert _plan(_t("Выпуск.csv", rows)).headline.startswith("Выпуск вырос")


# ── W3: огромные числа ────────────────────────────────────────────────────────────────────────────────────────────
def test_huge_money_is_scaled():
    t = _t("Капитализация.csv", [["Компания", "Капитализация, руб."], ["Сбербанк", 7345000000000],
                                 ["Роснефть", 5120000000000], ["Яндекс", 1590000000000]])
    p = _plan(t)
    assert "трлн ₽" in _sp(p.headline) and not re.search(r"\d{4}\s?\d{3}\s?\d{3}", _sp(p.headline)), p.headline
