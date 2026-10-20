"""Вопрос плана → правильная метрика (жюри 5): последний срез — «сейчас», рост сегментов вместо размера, конверсия этапов
воронки вместо «у кого больше пилотов», затраты на одного клиента вместо «0 ₽ меньше всего», цены не складываются, план
в млн ₽ и факт в тыс. ₽ сводятся к одной единице, имя файла транслитом — не подпись. Маленькие общие таблицы, не файлы
жюри."""

from __future__ import annotations

from pathlib import Path

from verstka.data.plan import chart_spec_of, plan_datasets
from verstka.data.readers import read_file
from verstka.data.units import additivity, period_tag
from verstka.data.words import file_title


def _t(tmp_path: Path, name: str, text: str):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return read_file(p)[0]


def _plan(t, brief: str = ""):
    return plan_datasets([t], brief)[0]


SEG = "Отрасль;Клиентов на 30.06;Клиентов на 30.09\nРитейл;420;465\nФинансы;180;192\nГоссектор;95;131\nПрочие;610;640\n"


def test_period_slices_in_column_names():
    assert period_tag("Время первого ответа Q3")[:2] == ("quarter", (0, 3))
    assert period_tag("Клиентов на 30.09")[1:] == ((0, 930), "Клиентов")
    assert period_tag("MRR сентябрь 2026")[:2] == ("month", (2026, 9))
    assert period_tag("Стоимость за врача в месяц") is None and period_tag("Школ") is None


def test_segment_that_shot_up_is_answered_by_growth_not_size(tmp_path):
    t = _t(tmp_path, "klienty_po_otraslyam.csv", SEG)
    p = _plan(t, "- клиенты по отраслям — госсектор выстрелил, проверь")
    assert p.headline == "Госсектор растёт быстрее всех: +38% за квартал"
    assert "Медленнее всех — Финансы" in (p.caption or "")
    # без вопроса — последний срез, а не первый
    assert "30.09" in _plan(t).headline or "30.06" not in _plan(t).headline


def test_where_do_we_grow_fastest_takes_the_sliced_measure(tmp_path):
    t = _t(tmp_path, "regiony.csv", "Регион;Школ;Учеников на 30.06.2026;Учеников на 30.09.2026\nА;42;2900;3600\n"
                                     "Б;35;2100;2750\nВ;38;2400;2600\nГ;27;1300;2100\n")
    p = _plan(t, "Где растём быстрее всего, где буксуем")
    assert p.headline.startswith("Г растёт быстрее всех: +62%")
    assert chart_spec_of(p, t).y_title == "Учеников"


def test_series_growing_fastest_leads_not_the_named_one(tmp_path):
    t = _t(tmp_path, "vyruchka_po_mesyacam.csv", "Месяц;Compute, млн ₽;PaaS, млн ₽;ML, млн ₽\nЯнварь 2026;210;60;12\n"
                                                 "Февраль 2026;215;64;14\nМарт 2026;222;69;15\nАпрель 2026;230;74;18\n"
                                                 "Май 2026;238;80;21\nИюнь 2026;245;86;27\n")
    p = _plan(t, "- какие сервисы тянут рост — по-моему PaaS быстрее всех")
    assert p.headline.startswith("ML") and "быстрее всех" in p.headline
    assert chart_spec_of(p, t).y_title == "Выручка"  # не «Vyruchka_po_mesyacam»


def test_funnel_question_gets_stage_conversion(tmp_path):
    t = _t(tmp_path, "voronka.csv", "Сегмент;Лиды;Пилоты;Контракты\nКрупный;140;38;17\nСредний;620;95;41\n"
                                    "Госсектор;85;30;6\nИтого;845;163;64\n")
    p = _plan(t, "Воронка: где теряем?")
    assert "конверсия «Пилоты» → «Контракты» — Госсектор: 20%" in p.headline


def test_cheapest_channel_is_cost_per_client_and_zero_is_no_answer(tmp_path):
    t = _t(tmp_path, "kanaly.csv", "Канал;Новых клиентов;Затраты, тыс. ₽\nКонтекст;22;1980\nПартнёры;27;1080\n"
                                   "Конференции;6;1080\nРекомендации;14;0\n")
    p = _plan(t, "каналы: какой самый дешёвый, от какого отказаться")
    p.headline = p.headline.replace("\xa0", " ")
    assert "Партнёры: 40 тыс. ₽" in p.headline and "Конференции: 180 тыс. ₽" in p.headline
    assert "Рекомендации" not in p.headline


def test_prices_are_not_summed(tmp_path):
    assert additivity("Стоимость за врача в месяц", "₽", "money")[0] is False
    assert additivity("Выручка за месяц", "₽", "money")[0] is True
    t = _t(tmp_path, "konkurenty.csv", "Решение;Стоимость за врача в месяц, ₽\nМы;900\nА;2400\nБ;1100\nExcel;0\n")
    p = _plan(t)
    assert " из " not in p.headline and "%" not in p.headline


def test_plan_in_millions_and_fact_in_thousands_are_one_unit(tmp_path):
    t = _t(tmp_path, "rashody.csv", "Статья;План, млн ₽;Факт, тыс. ₽\nЗарплата;18;17400\nОборудование;9;12300\n"
                                    "Материалы;3;2100\nИтого;30;31800\n")
    p = _plan(t)
    assert p.task.task == "comparison" and p.headline.replace("\xa0", " ") == "План исполнен на 106%: 31,8 из 30 млн ₽"


def test_transliterated_file_names_read_in_russian():
    assert file_title("vyruchka_po_mesyacam.csv") == "Выручка по месяцам"
    assert file_title("Zayavki.csv") == "Заявки"
    assert file_title("Csat_moduli.csv") == "CSAT модули"
    assert file_title("sales_2025.csv") == "Sales_2025" and file_title("revenue.csv") == "Revenue"
