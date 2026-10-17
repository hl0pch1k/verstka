"""Раунд 10 (четвёртая проверка сходимости, conv4): шапка «год, единица», прогноз по колонке статуса, устойчивый
тренд (Тейл — Сен, Манн — Кендалл, разброс по MAD) и всплеск по MAD, слова цены — только по самой величине, допуск у
целых средних, вес удельной величины — колонка её знаменателя."""

from __future__ import annotations

import csv
import io

import pytest

from tests.unit.test_data_factcheck import corpus_conv4
from verstka.data.aggregate import Data, per_unit_denominator, status_column
from verstka.data.goals import goal_focus, goals_of, strip_lead
from verstka.data.plan import chart_spec_of, data_of, plan_datasets
from verstka.data.profile import profile_table
from verstka.data.readers import read_bytes
from verstka.data.verify import verify
from verstka.schemas.data import DatasetPlan, HeadlineFact, Table

_C4 = None


def _sp(s: str) -> str:
    return " ".join((s or "").replace(" ", " ").split())


def _t(name: str, rows: list[list], delim: str = ";") -> Table:
    buf = io.StringIO(newline="")
    csv.writer(buf, delimiter=delim).writerows(rows)
    return read_bytes(name, buf.getvalue().encode("utf-8"))[0]


def _conv4(key: str, which: str = "0") -> tuple[Table, DatasetPlan]:
    """Таблица корпуса conv4 и её план: без брифа («0») или с брифом A, B, C."""
    global _C4
    if _C4 is None:
        _C4 = {k: (files, briefs) for k, files, briefs in corpus_conv4()}
    files, briefs = _C4[key]
    t = read_bytes(*files[0])[0]
    brief = "" if which == "0" else briefs["ABC".index(which)]
    return t, plan_datasets([t], brief, profiles=[profile_table(t)])[0]


# ── F1: «2024, ГВт·ч» в шапке — год, а не данные ──────────────────────────────────────────────────────────────────
def test_year_with_a_unit_in_the_header_is_a_year_column():
    for rows in ([["Сектор", "2024, ГВт·ч", "2025, ГВт·ч", "Изменение, %"], ["Промышленность", "412,5", "398,1", "-3,5"],
                  ["Население", "188,2", "196,4", "4,4"], ["Транспорт", "64,8", "66,0", "1,9"]],
                 [["Сектор", "2024 (ГВт·ч)", "2025 (ГВт·ч)"], ["Промышленность", 412, 398], ["Население", 188, 196],
                  ["Транспорт", 65, 66]]):
        t = _t("Потребление.csv", rows)
        assert t.columns[:3] == ["Сектор", "2024", "2025"] and t.units[1] == "ГВт·ч", (t.columns, t.units)
        assert t.rows[0][0] == "Промышленность"
    t, p = _conv4("28")
    assert _sp(p.headline) == "Промышленность — почти половина энергопотребления за 2025 год: 45%", p.headline
    assert "Сектор" not in chart_spec_of(p, t).categories


# ── F2: колонка статуса «Тип: Факт / Прогноз» ─────────────────────────────────────────────────────────────────────
def test_status_column_marks_forecast_rows():
    t, p = _conv4("27")
    assert status_column(t) == 2
    assert _sp(p.headline) == "Выручка — на 6% больше, чем во II квартале 2024", p.headline
    assert "Прогноз на IV кв. 2025 — 760 млн ₽, не в выводе." in _sp(p.caption)
    s = chart_spec_of(p, t)
    assert s.series[0].values[-2:] == [None, None] and s.series[-1].name == "Выручка (прогноз)"
    # проверка своим правилом: строка «Прогноз» в ряду фактов не подтверждается
    d = data_of(p, t)
    from verstka.data.facts import facts_for

    fs = facts_for("dynamics", d)
    ch = next(f for f in fs.facts if f.id == "change")
    planted = {"change": {**fs.prov["change"], "skip": [], "to": "2025-Q4", "from": "2024-Q4"}}
    v = verify(t, [ch], planted, "", None)
    assert "прогноз" in v.failed["change"]


# ── F3: устойчивый тренд и всплеск ────────────────────────────────────────────────────────────────────────────────
def test_robust_trend_and_a_named_spike():
    """Неделями растущие продажи с «чёрной пятницей»: рост (по Манну — Кендаллу ряд растёт и со всплеском), всплеск
    назван — а не «без выраженного тренда»."""
    for which in ("0", "A"):
        t, p = _conv4("22", which)
        assert _sp(p.headline) == "Выручка выросла на 34% за 9 недель, всплеск — нед. 48, 2025", p.headline
        assert "Всплеск — 48-я неделя 2025: 6 640 тыс. ₽, в 1,9 раза выше медианы." in _sp(p.caption)
        assert not any("не подтвердил" in r for r in p.task.reasons)
    # ровный ряд с одним всплеском — всплеск главное; постоянный ряд — «держится на уровне»
    rows = [["Дата", "Ошибок"]] + [[f"2026-09-{d + 1:02d}", 1800 + 40 * (d % 3) + (7800 if d == 7 else 0)] for d in range(14)]
    p = plan_datasets([_t("Ошибки.csv", rows)], "")[0]
    assert "всплеск" in p.headline and "выше медианы" in p.headline, p.headline


# ── F4: «дороже» — только у цены ──────────────────────────────────────────────────────────────────────────────────
def test_price_words_come_from_the_measure_not_the_file():
    t = _t("Абоненты тарифов.csv", [["Тариф", "Абонентов, тыс."], ["Базовый", 820], ["Оптимальный", 2451],
                                    ["Безлимит", 1127], ["Для дома", 298]])
    p = plan_datasets([t], "")[0]
    assert not p.headline.startswith("Дороже"), p.headline
    t = _t("Тарифы.csv", [["Тариф", "Цена, ₽/мес."], ["Старт", 2450], ["Бизнес", 9900], ["Энтерпрайз", 39500]])
    assert plan_datasets([t], "")[0].headline.startswith("Дороже всего — Энтерпрайз")


# ── V1, V2 ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_integer_mean_tolerance_and_per_unit_weight():
    """V1: среднее от 100 хранится целым — проверка допускает полцелого. V2: «л/100 км» взвешивается километрами
    («Пробег, км»), а не рейсами; проверка — тем же правилом."""
    t = _t("Средние.csv", [["Месяц", "Выручка, тыс. ₽"]] + [[f"2026-{m:02d}", 5340 + (m % 3)] for m in range(1, 8)])
    f = HeadlineFact(id="mean", text="В среднем — 5 341", value=5341.0, unit="тыс. ₽", kind="median")
    prov = {"mean": {"op": "series", "time": 0, "freq": "month", "col": 1, "agg": "mean", "mode": "mean",
                     "from": "2026-01", "to": "2026-07", "tol": 0.51}}
    assert not verify(t, [f], prov, "", "В среднем — 5 341").failed
    assert per_unit_denominator("л/100 км") == "км" and per_unit_denominator("₽/кВт·ч") == "квт·ч"
    t, p = _conv4("05", "B")
    d = Data(t, profile_table(t))
    rate = next(m for m in d.measures if m.name.startswith("Расход"))
    assert d.weight_of(rate).name.startswith("Пробег")
    # ряд падает (тренд выражен), а последняя неделя — два дня с высоким расходом: вывод — по средним концов ряда,
    # а не «вырос на 1,3%» по неполной неделе
    assert _sp(p.headline) == "Расход топлива в среднем снизился на 5,1%: последние 3 недели к первым 3", p.headline
    assert not any("не подтвердил" in r for r in p.task.reasons)


# ── M1–M6: панели, подгруппы, доли счёта, ставки «на одного», выброс в топе, одинаковые имена ─────────────────────
def test_panel_compares_the_latest_period_or_the_sum():
    """M1: тарифы регионов по годам — сравнение по 2025 году (и год назван), а не среднее 2021–2025; простои линий по
    месяцам — сумма за период (накопленное время складывается), а не «быстрее всего — 28,2 ч в месяц»."""
    t, p = _conv4("09", "B")
    assert "8,07 ₽/кВт·ч (2025 год)" in _sp(p.headline) and "1,97 ₽/кВт·ч" in _sp(p.headline), p.headline
    t, p = _conv4("03", "A")
    assert _sp(p.headline) == "Линия 3 — больше всех: 38% всех простоев (январь 2025 – сентябрь 2025)", p.headline
    assert "683 ч из 1 784 ч" in _sp(p.caption)


def test_overall_column_and_departments_of_a_survey():
    """M2: «Все сотрудники» рядом с «Продажи (n=120)» — величина таблицы; «в каком отделе хуже всего» сравнивает
    отделы-колонки, «по удовлетворённости зарплатой» — по строке зарплаты, и это названо."""
    t, p = _conv4("04")
    assert _sp(p.headline) == "Я понимаю цели своего отдела впереди: 81%, Моя зарплата справедлива — 40%"
    t, p = _conv4("04", "A")
    assert _sp(p.headline).startswith("Меньше всего — Логистика (n=150): 51,1% (в среднем по 8 строкам)"), p.headline
    t, p = _conv4("04", "B")
    assert _sp(p.headline) == "ИТ (n=85) впереди: 48% («Моя зарплата справедлива»), Логистика (n=150) — 30%"


def test_rate_over_count_and_share_wording():
    """M3: при колонке уровня («Брак, ppm», «Доля возвратов, %») сравнивают уровень; доля счёта — «всех/всего»."""
    t, p = _conv4("23")
    assert _sp(p.headline) == "Выше нормы — 3 из 6: Линия Б, Линия Г и Линия Е", p.headline
    t, p = _conv4("15")
    assert _sp(p.headline) == "Больше всего — Одежда: 23,1%, меньше всего — Книги: 1,2%"
    t, p = _conv4("15", "A")  # «больше всего возвратов» — счёт, его и сравнивают
    assert _sp(p.headline) == "Одежда — половина всех возвратов: 52%", p.headline


def test_per_entity_columns_are_not_summed():
    """M4: «Посещений на врача» — величина на одного: без итога и «из 261», без круговой."""
    t, p = _conv4("10", "C")
    d = Data(t, profile_table(t))
    m = next(x for x in d.measures if "на врача" in x.name)
    assert not m.additive and "из" not in _sp(p.caption or "") and "pie" not in [o.kind for o in p.options]


def test_typo_row_is_out_of_the_top_share():
    """M5: строка в 1 546 раз больше медианы, больше половины суммы — в подписи, в долях топа её нет."""
    t, p = _conv4("19")
    assert _sp(p.headline) == "10 крупнейших дают 30% суммы", p.headline
    assert _sp(p.caption).startswith("Строка № 137 — 1 500 000 ₽, в 1 546 раз больше медианы (970 ₽)")
    t, p = _conv4("19", "A")
    assert "среднее до 1 991 ₽" in _sp(p.headline)


def test_same_name_columns_keep_their_units():
    """M6: «Экспорт, тыс. т» и «Экспорт, млн $» — «Экспорт, т» и «Экспорт, $»; «по объёму» — тонны, единица названа."""
    t, p = _conv4("13")
    assert t.columns[1:] == ["Экспорт, т", "Экспорт, $"]
    assert _sp(p.headline) == "Пшеница — почти половина экспорта в долларах: 44%"
    t, p = _conv4("13", "B")
    assert _sp(p.headline) == "Пшеница — две трети экспорта в тоннах: 69%", p.headline


# ── W: формулировки ───────────────────────────────────────────────────────────────────────────────────────────────
def test_wording_of_round_10():
    t, p = _conv4("30")  # мера и единица таблицы из текста над ней, «Абоненты» — счёт людей
    assert t.columns[-1] == "Абоненты" and _sp(p.headline) == "Абоненты выросли на 6,1% за 3 квартала"
    t, p = _conv4("30", "B")
    assert _sp(p.headline).startswith("Всего — 5 449 тыс.")
    t, p = _conv4("11", "A")  # «Среднее … в среднем» — без повтора
    assert _sp(p.headline).startswith("Среднее время решения — 6,9 ч"), p.headline
    t, p = _conv4("18", "A")  # перерасход, а не «план исполнен на 104%»
    assert _sp(p.headline) == "Перерасход 4,1%: 820 млн ₽ при плане 788"
    assert _sp(p.caption) == "Сверх плана — 5 из 9; больше всех — Фасад: +19,6%."
    t, p = _conv4("17")  # месяцы — не части; итог за квартал — величина таблицы
    assert "часть" not in p.headline and p.headline.startswith("Виртуальные машины"), p.headline
    t, p = _conv4("17", "B")
    assert _sp(p.headline).startswith("Расходы: от 4 645 тыс. ₽ (июль)"), p.headline


# ── G: цели без модели — вводные, вопросы «ли», пороги, хвосты, слова величины, годы в шапке ───────────────────────
def _g(text: str) -> list[tuple]:
    return [(g.task, g.ask, g.head) for g in goals_of(text)]


@pytest.mark.parametrize("text,task,ask", [
    ("Хотим понять, какие специальности оцениваются хуже всего.", "comparison", "min"),
    ("Главный вопрос — сколько всего заработали за ноябрь и как это соотносится с октябрём.", "dynamics", "total"),
    ("Хотим понять, снизился ли расход топлива после замены шин в середине августа.", "dynamics", "yesno"),
    ("Вырос ли турпоток по сравнению с прошлым годом?", "dynamics", "yesno"),
    ("Важно понять, стал ли летний сезон 2025 сильнее, чем в 2024 году.", "dynamics", "yesno"),
    ("Нужно показать, в каких регионах рассмотрение занимает больше 15 дней, чтобы направить туда проверку.",
     "comparison", "above:15"),
    ("Нужно найти категории, где возвращают больше 10% заказов.", "comparison", "above:10"),
    ("Хотим показать, где SLA проседает ниже 90%.", "comparison", "below:90"),
    ("Где электричество дорожает быстрее всего?", "dynamics", "fastest"),
    ("Какой средний рейтинг клиники по всем врачам?", "comparison", "mean"),
    ("Какой у нас средний процент завершения курсов по всей платформе?", "comparison", "mean"),
    ("Нужно показать, какая доля отправлений доставлена вовремя в целом.", "comparison", "mean"),
    ("Нужно показать, что конверсия стала больше", "dynamics", None),
])
def test_goal_phrasings_without_a_model(text, task, ask):
    """G1–G3, G6: вводные («Хотим понять,», «Главный вопрос —») снимаются, вопросы «ли» — динамика с ответом да/нет,
    порог — и после вводных, «дорожает» — рост, «по всей платформе», «в целом» — одно среднее."""
    got = _g(text)
    assert any(t_ == task and a_ == ask for t_, a_, _ in got), (text, got)


def test_trailing_clauses_are_not_the_metric():
    """G4: «и стоит ли …», «по сравнению с …», «и насколько он вырос» — не величина цели."""
    assert goal_focus("какая линия работает хуже всех по oee и стоит ли её модернизировать")[0] == ["oee"]
    assert "сравнен" not in goal_focus("покажи продажи квартир по сравнению с прошлым годом")[0]
    assert goal_focus("в каком регионе самый низкий тариф и насколько он вырос с 2021 года")[:2] == (["тариф"], "тариф")
    assert goal_focus("где не хватает врачей — то есть где на одного врача приходится больше всего посещений")[1] == \
        "посещен"
    assert strip_lead("Главное — какой сервис дорожает быстрее всех") == "какой сервис дорожает быстрее всех"


def test_goal_column_by_meaning_never_a_false_match():
    """G5: «дольше ждут» — колонка срока, а не «Заявлений» (слово «заявлению» — о предмете); «по отклонению от плана»
    — колонка отклонения, а не «План»; «самая загруженная» — посещения; «на одного врача» — «Посещений на врача».
    Колонку не по цели не называют «совпала»: величины нет — так и сказано."""
    t, p = _conv4("07", "A")
    assert _sp(p.headline) == "Дольше всего — Горный: 21,5 дн., быстрее всего — Центральный: 7,5 дн.", p.headline
    t, p = _conv4("18", "B")
    assert data_of(p, t).main.name == "Отклонение, %"
    assert _sp(p.headline).startswith("Больше всего сверх плана — Фасад: +19,6%"), p.headline
    t, p = _conv4("10", "A")
    assert _sp(p.headline).startswith("Поликлиника № 3 впереди: 1 510"), p.headline
    t, p = _conv4("10", "B")
    assert data_of(p, t).main.name == "Посещений на врача"
    # в таблице нет срока: цель «дольше ждут» не «совпала» с числом заявлений
    t = _t("Заявления.csv", [["Регион", "Заявлений, тыс."], ["Северный", 182], ["Южный", 240], ["Восточный", 96]])
    p = plan_datasets([t], "Где дольше всего ждут решения по заявлению?", profiles=[profile_table(t)])[0]
    why = " ".join(p.task.reasons)
    assert "совпала" not in why and "той же задаче" not in why, why
    assert "нет величины" in why or "в колонках нет" in why, why


def test_words_mapped_to_columns():
    """G6: «дорожает быстрее всех» — темп, а не наибольшее значение (и по колонкам-месяцам); «денег» — рубли;
    «рейтинг» — оценка; «процент … по всей платформе» — среднее с весом; «аудитории», «зрителей» — счёт аудитории."""
    t, p = _conv4("09", "A")
    assert _sp(p.headline) == "Иркутская обл. растёт быстрее всех: +68%", p.headline
    t, p = _conv4("17", "C")
    assert _sp(p.headline) == "GPU-инстансы растут быстрее всех: в 3,1 раза — июль → сентябрь", p.headline
    t, p = _conv4("17", "A")
    assert not any("нет величины" in r for r in p.task.reasons), p.task.reasons
    t, p = _conv4("29", "A")
    assert _sp(p.headline).startswith("Средняя оценка — 4,6"), p.headline
    t, p = _conv4("01", "A")
    assert _sp(p.headline).startswith("Доля завершивших в среднем — 20,8%"), p.headline
    t, p = _conv4("08", "B")
    assert data_of(p, t).main.name.startswith("Аудитория") and not any("нет величины" in r for r in p.task.reasons)


def test_year_groups_in_a_two_level_header_are_a_time_axis():
    """G7: шапка «2024: Штат · Вакансии | 2025: Штат · Вакансии» — ось «Год», а не колонки «2025 Штат»."""
    t, p = _conv4("24")
    assert t.columns == ["Отдел", "Год", "Штат", "Вакансии"]
    assert _sp(p.headline) == "Разработка — крупнейшая доля штата (2025 год): 39%", p.headline
    t, p = _conv4("24", "A")
    assert _sp(p.headline) == "Разработка — почти половина всех вакансий (2025 год): 48%", p.headline
    t, p = _conv4("24", "B")
    assert _sp(p.headline) == "Штат вырос на 15% за год", p.headline
    t, p = _conv4("24", "C")
    assert _sp(p.headline) == "Аналитика растёт быстрее всех: +62%", p.headline


def test_answers_to_the_asked_question():
    """Ответ — на вопрос брифа: итог месяца и сравнение с другим месяцем; кто не выполнил план; кто в пределах нормы;
    отрыв лидера; ряд названной категории; порог в процентах — по колонке в процентах; опечатка не в суммах."""
    t, p = _conv4("22", "C")
    assert _sp(p.headline) == "За ноябрь 2025 — 18 452 тыс. ₽: на 31% больше, чем за октябрь", p.headline
    t, p = _conv4("02", "A")
    assert _sp(p.headline).startswith("Не выполнили план — 6 из 12: «ул. Ленина, 12»"), p.headline
    t, p = _conv4("23", "A")
    assert _sp(p.headline) == "В пределах нормы — 3 из 6: Линия А, Линия В и Линия Д", p.headline
    t, p = _conv4("20", "A")
    assert _sp(p.headline) == "Сокол впереди: 47, отрыв от второго места — 2", p.headline
    t, p = _conv4("30", "C")
    assert _sp(p.headline) == "Базовый: −14% за 3 квартала", p.headline
    t, p = _conv4("11", "C")
    assert _sp(p.headline) == "Ниже 90% — 3 категории из 7: CRM, 1С и Принтеры", p.headline
    t, p = _conv4("19", "B")
    assert _sp(p.headline) == "Сайт — половина всех пожертвований: 50%" and "в суммах её нет" in _sp(p.caption)
    t, p = _conv4("28", "A")  # «сократил сильнее всех» — наибольшее снижение, а не наибольшее значение
    assert _sp(p.headline) == "Сильнее всех снижение — Строительство: −20% — 2024 → 2025", p.headline
    t, p = _conv4("16", "A")  # «стало ли меньше уходить абонентов» — отток
    assert _sp(p.headline) == "Отток снизился до 1,85%", p.headline
    t, p = _conv4("25", "C")  # «хуже всего» у задержки — наибольшая
    assert _sp(p.headline).startswith("Дольше всего — СеверКарго: 11,8 ч"), p.headline
    t, p = _conv4("29", "C")  # «какие специальности» — разрез по специальностям, а не по врачам
    assert _sp(p.headline).startswith("Меньше всего — Хирург: 3,49"), p.headline
    t, p = _conv4("20", "C")
    assert _sp(p.headline).startswith("Меньше всего очков — Волга: 14"), p.headline
    t, p = _conv4("03", "C")  # «хуже всех по OEE» — наименьший
    assert _sp(p.headline).startswith("Меньше всего — Линия 3: 64,3%"), p.headline
    for k, w in (("02", "A"), ("22", "C"), ("23", "A"), ("30", "C"), ("11", "C"), ("19", "B"), ("17", "C"),
                 ("28", "A"), ("16", "A"), ("25", "C")):
        t, p = _conv4(k, w)
        assert not any("не подтвердил" in r for r in p.task.reasons), (k, w, p.task.reasons)
