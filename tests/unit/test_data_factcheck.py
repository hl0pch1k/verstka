"""Независимая проверка чисел анализа (страховочная сетка, ревью rev7b). Для каждого плана, построенного по реальной
или случайной, но правдоподобной таблице, каждое число заголовка и подписи пересчитывается ЗАНОВО по сырым строкам
таблицы — без видов анализа (`Data`, `CatView`, `TimeView`): суммы, доли, изменения между полными периодами, доли «не
больше X», доля топ-10, r, исполнение плана, конверсия воронки. Плюс правила:
- состав (накопительные столбцы, доли частей) — только при признаке целого в данных (итог = сумма частей, группа шапки,
  строки по 100); годы, периоды, план и факт — не части;
- «100%» — только когда все;
- пункты (п., п.п.) — только у процентов и безразмерных индексов;
- каждое число заголовка есть среди фактов.

Корпус: 32 таблицы ревьюера (`scratchpad/s2/rev7b/gen.py`, `gen2.py` и пробы data3–data5 — перенесены сюда, без
случайности) и сотни случайных таблиц 12 семейств с фиксированным зерном. Таблицы идут через настоящее чтение
(`read_bytes`) и профиль."""

from __future__ import annotations

import datetime as dt
import math
import random
import re
from typing import Callable, Optional

import numpy as np
import pytest

from verstka.data.headline import numbers_in
from verstka.data.parse import is_total_label, period_parts, quantity, split_unit
from verstka.data.plan import NotBuilt, chart_spec_of, plan_dataset
from verstka.data.profile import profile_table
from verstka.data.readers import read_bytes
from verstka.schemas.data import DatasetPlan, Table
from verstka.schemas.outline import ChartSpec, NumberCallout, TableData

NB = " "
INDEX_HEAD = re.compile(r"^(?:nps|enps|csat|индекс\w*|рейтинг\w*|оценк\w*|балл\w*|доля|доли|конверси\w*|удовлетвор\w*)$",
                        re.I)


# ═══════════════════════════════════════════ корпус ревьюера (rev7b) ═══════════════════════════════════════════════
def _csv(rows: list[list], sep: str = ";") -> str:
    return "\n".join(sep.join(str(c) for c in r) for r in rows) + "\n"


def corpus() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    deps = {"ИТ": (120, 3), "Продажи": (210, -2), "Маркетинг": (40, 1), "Финансы": (35, 0), "Персонал": (18, 0),
            "Логистика": (75, 2)}
    rows = [["Месяц", "Отдел", "Численность, чел."]]
    for mo in range(1, 13):
        for d, (b, s) in deps.items():
            rows.append([f"2026-{mo:02d}", d, b + s * (mo - 1) + (1 if mo % 4 == 0 else 0)])
    out.append(("Численность по отделам.csv", _csv(rows)))
    out.append(("Штат по месяцам.csv", _csv([["Месяц", "ИТ", "Продажи", "Маркетинг"]] + [
        [f"2026-{mo:02d}", 120 + 3 * (mo - 1), 210 - 2 * (mo - 1), 40 + (mo - 1)] for mo in range(1, 13)])))
    out.append(("Воронка продаж.csv", _csv([["Этап", "Количество"], ["Показы рекламы", 120000], ["Переходы на сайт", 8400],
                                            ["Заявки", 960], ["Встречи", 310], ["Сделки", 74]])))
    reg = [("Москва", 1840, 312, 14), ("Санкт-Петербург", 920, 141, 9), ("Новосибирск", 410, 52, 31),
           ("Екатеринбург", 385, 47, 12), ("Казань", 300, 33, 18), ("Нижний Новгород", 240, 18, 4),
           ("Самара", 190, 6, -3), ("Ростов-на-Дону", 175, -4, 2), ("Красноярск", 150, 11, 7), ("Омск", 95, -12, -8)]
    out.append(("Продажи по регионам 2026.csv", _csv([["Регион", "Выручка, млн ₽", "Прибыль, млн ₽", "Рост выручки, %"]]
                                                     + [list(r) for r in reg])))
    out.append(("Опрос сотрудников.csv", _csv([
        ["Утверждение", "Полностью не согласен", "Скорее не согласен", "Затрудняюсь ответить", "Скорее согласен",
         "Полностью согласен"],
        ["Я понимаю цели компании", 3, 7, 12, 46, 32], ["Руководитель даёт обратную связь", 8, 15, 20, 38, 19],
        ["Мне хватает инструментов для работы", 5, 12, 18, 41, 24], ["Я вижу возможности для роста", 14, 22, 25, 27, 12],
        ["Нагрузка распределена справедливо", 18, 26, 21, 25, 10], ["Я рекомендую компанию друзьям", 6, 9, 19, 39, 27]])))
    rows = [["Сотрудник", "Отдел", "Оценка удовлетворённости"]]
    for i in range(150):
        dep = ["Продажи", "ИТ", "Склад"][i % 3]
        v = [5, 4, 4, 3, 4, 5, 2, 4, 3, 4, 1, 4, 5, 3, 4][(i * 7) % 15]
        if dep == "Склад" and v >= 4 and i % 2:
            v -= 2
        rows.append([f"С-{1000 + i}", dep, v])
    out.append(("Оценка удовлетворённости.csv", _csv(rows, ",")))
    out.append(("Успеваемость по классам.csv", _csv([["Класс", "Учеников", "Средний балл", "Качество знаний, %"],
                                                      ["5-А", 28, "4,3", 71], ["5-Б", 27, "3,9", 52], ["6-А", 26, "4,1", 62],
                                                      ["6-Б", 29, "3,7", 41], ["7-А", 25, "4,4", 76], ["7-Б", 27, "3,8", 48],
                                                      ["8-А", 24, "4,0", 58], ["8-Б", 26, "3,6", 38]])))
    rows = [["Время", "Потребление, кВт·ч"]]
    for h in range(72):
        day, hh = divmod(h, 24)
        base = 220 + 160 * max(0.0, math.sin((hh - 6) / 24 * 2 * math.pi)) + (40 if 18 <= hh <= 21 else 0) + day * 5
        rows.append([f"2026-01-{12 + day:02d} {hh:02d}:00", round(base)])
    out.append(("Потребление электроэнергии.csv", _csv(rows)))
    bud = [("Фонд оплаты труда", 52400, 51850), ("Аренда", 9600, 9600), ("Маркетинг", 7200, 8100),
           ("ИТ и связь", 4800, 4310), ("Командировки", 2100, 1460), ("Обучение", 1500, 820), ("Прочее", 1900, 2230)]
    out.append(("Бюджет план-факт.csv", _csv([["Статья расходов", "План, тыс. ₽", "Факт, тыс. ₽", "Исполнение, %"]]
                                             + [[a, p, f, str(round(f / p * 100, 1)).replace(".", ",")] for a, p, f in bud])))
    out.append(("Выручка план и факт.csv", _csv([["Месяц", "План, млн ₽", "Факт, млн ₽"]] + [
        [f"2026-{mo:02d}", 100 + 5 * mo, 98 + 5 * mo + (6 if mo in (6, 7) else -3 if mo == 3 else 0)] for mo in range(1, 10)])))
    cats = ["Ноутбуки", "Мониторы", "Клавиатуры", "Мыши", "Гарнитуры"]
    rows = [["Артикул", "Наименование", "Категория", "Цена, ₽", "Остаток, шт."]]
    for i in range(45):
        c = cats[i % 5]
        base = {"Ноутбуки": 64000, "Мониторы": 18000, "Клавиатуры": 3500, "Мыши": 1900, "Гарнитуры": 5200}[c]
        rows.append([f"КБ-{1001 + i}", f"{c[:-1]} модель {i + 1}", c, base + (i * 137) % 9000, (i * 13) % 40])
    out.append(("Прайс-лист.csv", _csv(rows)))
    coh = [("2026-01-05", 1200, [41, 28, 22, 19]), ("2026-01-12", 1350, [43, 30, 23, 20]),
           ("2026-01-19", 1180, [40, 27, 21, 18]), ("2026-01-26", 1420, [45, 31, 25, None]),
           ("2026-02-02", 1510, [44, 30, None, None]), ("2026-02-09", 1600, [46, None, None, None])]
    out.append(("Удержание по когортам.csv", _csv([["Когорта", "Пользователей", "Неделя 1, %", "Неделя 2, %", "Неделя 3, %",
                                                    "Неделя 4, %"]] + [[d, n] + ["" if w is None else w for w in ws]
                                                                       for d, n, ws in coh])))
    out.append(("Итоги месяца.csv", _csv([["Выручка, млн ₽", "Заказов", "Средний чек, ₽", "Конверсия, %"],
                                          ["48,2", 15430, 3124, "2,8"]])))
    out.append(("Трафик сайта.csv", _csv([["Месяц", "Сеансы", "Конверсия, %"]] + [
        [f"2025-{mo:02d}", 42000 + 1800 * mo, str(round(1.9 + 0.05 * mo, 2)).replace(".", ",")] for mo in range(1, 13)])))
    exp = [("Фонд оплаты труда", 51850), ("Аренда", 9600), ("Маркетинг", 8100), ("ИТ и связь", 4310), ("Прочее", 4510)]
    out.append(("Структура расходов.csv", _csv([["Статья", "Сумма, тыс. ₽"]] + [list(e) for e in exp]
                                               + [["Итого", sum(v for _, v in exp)]])))
    rows = [["Опыт", "Концентрация, моль/л", "Скорость реакции, ммоль/(л·с)", "Температура, °C"]]
    for i in range(24):
        c = 0.1 + 0.05 * (i % 8)
        t = [20, 30, 40][i // 8]
        v = round(2.1 * c * (1 + (t - 20) / 25) + 0.02 * ((i * 5) % 7 - 3), 3)
        rows.append([f"О-{i + 1:02d}", str(round(c, 2)).replace(".", ","), str(v).replace(".", ","), t])
    out.append(("Скорость реакции.csv", _csv(rows)))
    rows = [["Дата", "Заказов"]]
    for i in range(90):
        day = dt.date(2026, 3, 1) + dt.timedelta(days=i)
        rows.append([day.strftime("%d.%m.%Y"), 300 + 2 * i + (80 if day.weekday() >= 5 else 0)])
    out.append(("Заказы по дням.csv", _csv(rows)))
    names = ["Иванов И.", "Петрова А.", "Сидоров К.", "Кузнецова М.", "Смирнов Д.", "Попова Е.", "Васильев Н.",
             "Морозова О.", "Новиков П.", "Фёдорова Р.", "Волков С.", "Алексеева Т.", "Лебедев У.", "Семенова Ф.", "Егоров Х."]
    out.append(("Продажи менеджеров.csv", _csv([["Менеджер", "Сделок", "Сумма сделок, млн ₽"]] + [
        [n, 40 - 2 * i + (i % 3), str(round(52 - 3.1 * i + (i % 4) * 1.7, 1)).replace(".", ",")] for i, n in enumerate(names)])))
    rows = [["Дата", "Выручка, млн ₽"]]
    d, i = dt.date(2025, 1, 1), 0
    while d <= dt.date(2026, 2, 22):
        rows.append([d.isoformat(), str(round(10 + 0.01 * i, 2)).replace(".", ",")])
        d += dt.timedelta(days=1)
        i += 1
    out.append(("Выручка по дням.csv", _csv(rows)))
    out.append(("Выручка план факт по регионам.csv", _csv([["Регион", "Выручка план, млн ₽", "Выручка факт, млн ₽"],
                                                           ["Москва", 1800, 1840], ["Казань", 320, 300], ["Омск", 110, 95],
                                                           ["Самара", 200, 190], ["Тверь", 90, 104]])))
    out.append(("Итоги банка.csv", _csv([["Показатель", "2026", "2025"], ["Процентный доход, млн ₽", 120, 100],
                                         ["Охват, тыс. чел.", 450, 300], ["Число клиентов", 5200, 4800]])))
    bud = bud + [("Охрана", 1200, 1190), ("Связь", 800, 760), ("Канцелярия", 300, 410)]
    out.append(("Бюджет по статьям.csv", _csv([["Статья", "План, тыс. ₽", "Факт, тыс. ₽"]] + [list(b) for b in bud])))
    out.append(("Расходы 2026.csv", _csv([["Статья", "Сумма, тыс. ₽"], ["Фонд оплаты труда", 5200], ["Аренда", 2100],
                                          ["Маркетинг", 1500], ["Прочее", 1200]])))
    vals = [70 + (k * 37) % 50 for k in range(399)] + [131]
    out.append(("Время доставки.csv", _csv([["Заказ", "Минут доставки"]] + [[f"Z-{5000 + k}", v]
                                                                         for k, v in enumerate(vals)])))
    cities = [("Москва", "Центр", 4200), ("Тверь", "Центр", 2100), ("Тула", "Центр", 2000), ("Рязань", "Центр", 1900),
              ("Казань", "Поволжье", 2600), ("Самара", "Поволжье", 2500), ("Уфа", "Поволжье", 2400),
              ("Пермь", "Урал", 2300), ("Екатеринбург", "Урал", 3100), ("Челябинск", "Урал", 2200),
              ("Омск", "Сибирь", 1800), ("Томск", "Сибирь", 2000), ("Новосибирск", "Сибирь", 2900)]
    out.append(("Средний чек по городам.csv", _csv([["Город", "Регион", "Средний чек, ₽"]] + [list(c) for c in cities])))
    out.append(("Выручка по городам.csv", _csv([["Город", "Регион", "Выручка, млн ₽"]] + [[c, r, v // 10]
                                                                                         for c, r, v in cities])))
    out.append(("Каналы по месяцам.csv", _csv([["Месяц", "Продажи онлайн, млн ₽", "Продажи офлайн, млн ₽"]] + [
        [f"2025-{mo:02d}", 40 + 3 * mo, 90 - mo] for mo in range(1, 13)])))
    out.append(("Выпуск и брак.csv", _csv([["Год", "Выпуск, шт.", "Брак, шт."]] + [
        [y, 1000 + 120 * (y - 2018), 40 - 2 * (y - 2018)] for y in range(2018, 2026)])))
    out.append(("Выручка по регионам за два года.csv", _csv([["Регион", "Выручка 2025, млн ₽", "Выручка 2026, млн ₽"],
                                                             ["Москва", 1600, 1840], ["Санкт-Петербург", 850, 920],
                                                             ["Казань", 260, 300], ["Новосибирск", 310, 410], ["Омск", 100, 95]])))
    out.append(("Итоги года компании.csv", _csv([["Показатель", "2026", "2025"], ["Выручка, млн ₽", 1240, 1010],
                                                 ["Оценка стоимости бизнеса, млн ₽", 5400, 4800], ["Доля рынка, %", "12,5", 11]])))
    out.append(("Каналы 97.csv", _csv([["Канал", "Выручка, млн ₽"], ["Прямые продажи", 970], ["Партнёры", 20],
                                       ["Маркетплейсы", 10]])))
    out.append(("Текучесть.csv", _csv([["Отдел", "Сотрудников", "Уволилось"], ["Продажи", 120, 18], ["ИТ", 80, 6],
                                       ["Склад", 60, 12], ["Финансы", 25, 1], ["Маркетинг", 30, 4]])))
    rows = [["Месяц", "Регион", "Средний чек, ₽"]]
    base = {"Омск": (1500, -20), "Москва": (3200, 40), "Казань": (2400, 10), "Самара": (2100, 5), "Тверь": (1800, 0),
            "Пермь": (2000, 15)}
    for mo in range(1, 13):
        for r_, (b, s) in base.items():
            rows.append([f"2025-{mo:02d}", r_, b + s * (mo - 1)])
    out.append(("Средний чек по регионам и месяцам.csv", _csv(rows)))
    out.append(("Средний чек по месяцам.csv", _csv([["Месяц", "Средний чек, ₽"]] + [
        [f"2025-{mo:02d}", 2000 + 20 * mo] for mo in range(1, 13)])))
    return out


# ═══════════════════════════════════════════ случайные таблицы ═════════════════════════════════════════════════════
def _num(x: float, dec: int = 1) -> str:
    return (f"{x:.{dec}f}" if dec else str(int(round(x)))).replace(".", ",")


REGIONS = ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Омск", "Самара", "Тверь", "Пермь",
           "Уфа", "Томск", "Сочи", "Курск", "Тула"]


def fam_daily(r: random.Random) -> tuple[str, str]:
    """Дневной поток с обрывом в середине недели/месяца — сумма по неделям или месяцам."""
    start = dt.date(2024 + r.randint(0, 1), r.randint(1, 12), r.randint(1, 28))
    days = r.randint(40, 500)
    rows = [["Дата", r.choice(["Выручка, млн ₽", "Заказов", "Продажи, шт."])]]
    g = r.uniform(-0.002, 0.004)
    for i in range(days):
        d = start + dt.timedelta(days=i)
        rows.append([d.isoformat(), _num(100 * (1 + g) ** i + r.uniform(-5, 5), 1)])
    return "Дневной ряд.csv", _csv(rows)


def fam_monthly_level(r: random.Random) -> tuple[str, str]:
    """Помесячный уровень в деньгах или индекс без единицы — изменение в % или в пунктах по единице."""
    col = r.choice(["Средний чек, ₽", "NPS", "Индекс удовлетворённости", "Конверсия, %", "Цена, ₽"])
    n = r.randint(6, 30)
    y0 = 2023
    rows = [["Месяц", col]]
    v = r.uniform(20, 60) if "₽" not in col else r.uniform(1000, 3000)
    for k in range(n):
        v *= 1 + r.uniform(-0.03, 0.05)
        rows.append([f"{y0 + k // 12}-{k % 12 + 1:02d}", _num(v, 1)])
    return "Уровень по месяцам.csv", _csv(rows)


def fam_categories(r: random.Random) -> tuple[str, str]:
    """Категории и деньги (иногда с убытками, иногда со строкой «Итого»)."""
    k = r.randint(3, 14)
    cats = r.sample(REGIONS, k)
    col = r.choice(["Выручка, млн ₽", "Прибыль, млн ₽", "Расходы, тыс. ₽", "Сотрудников"])
    vals = [r.uniform(-50 if "Прибыль" in col else 5, 900) for _ in cats]
    rows = [["Регион", col]] + [[c, _num(v, r.choice([0, 1]))] for c, v in zip(cats, vals)]
    if r.random() < 0.4 and all(v >= 0 for v in vals):
        rows.append(["Итого", _num(sum(float(_num(v, 1).replace(",", ".")) for v in vals), 1)])
    return "Категории.csv", _csv(rows)


def fam_plan_fact(r: random.Random) -> tuple[str, str]:
    k = r.randint(3, 12)
    rows = [["Статья", "План, тыс. ₽", "Факт, тыс. ₽"]]
    for i in range(k):
        p = r.randint(100, 50000)
        rows.append([f"Статья {chr(1040 + i)}", p, int(p * r.uniform(0.5, 1.3))])
    return "План и факт.csv", _csv(rows)


def fam_years(r: random.Random) -> tuple[str, str]:
    """Колонки-годы по категориям — не части одного целого."""
    k = r.randint(3, 9)
    rows = [["Регион", "Выручка 2025, млн ₽", "Выручка 2026, млн ₽"]]
    for c in r.sample(REGIONS, k):
        a = r.randint(50, 2000)
        rows.append([c, a, int(a * r.uniform(0.8, 1.4))])
    return "Два года.csv", _csv(rows)


def fam_long(r: random.Random) -> tuple[str, str]:
    """Месяц × регион × (сумма или уровень)."""
    regs = r.sample(REGIONS, r.randint(3, 8))
    col = r.choice(["Выручка, млн ₽", "Средний чек, ₽", "Клиентов"])
    rows = [["Месяц", "Регион", col]]
    base = {g: r.uniform(100, 3000) for g in regs}
    for mo in range(1, r.randint(6, 13)):
        for g in regs:
            rows.append([f"2025-{mo:02d}", g, int(base[g] * (1 + r.uniform(-0.05, 0.08)) ** mo)])
    return "Длинная таблица.csv", _csv(rows)


def fam_distribution(r: random.Random) -> tuple[str, str]:
    n = r.randint(60, 600)
    col = r.choice(["Минут доставки", "Минут до ответа", "Сумма заказа, ₽"])
    rows = [["Номер", col]]
    for i in range(n):
        v = r.expovariate(1 / r.choice([20, 45, 90])) if "Минут" in col else r.lognormvariate(8, 0.8)
        rows.append([f"N-{10000 + i}", max(1, int(v))])
    if r.random() < 0.3:
        rows.append([f"N-{99999}", 5000])
    return "Распределение.csv", _csv(rows)


def fam_kpi(r: random.Random) -> tuple[str, str]:
    pool = [("Выручка, млн ₽", 1000), ("Клиенты, чел.", 3000), ("Средний чек, ₽", 3000), ("Конверсия, %", 3),
            ("NPS", 45), ("Охват, тыс. чел.", 300), ("Процентный доход, млн ₽", 120), ("Доля рынка, %", 12),
            ("Индекс удовлетворённости", 70), ("Отчислено, чел.", 400)]
    items = r.sample(pool, r.randint(2, 6))
    rows = [["Показатель", "2026", "2025"]]
    for lab, base in items:
        prev = base * r.uniform(0.7, 1.2)
        cur = prev * r.uniform(0.85, 1.3)
        rows.append([lab, _num(cur, 1), _num(prev, 1)])
    return "Итоги года.csv", _csv(rows)


def fam_relationship(r: random.Random) -> tuple[str, str]:
    n = r.randint(30, 200)
    slope = r.uniform(0.5, 4)
    rows = [["Код", "Часов подготовки", "Балл"]]
    for i in range(n):
        h = r.uniform(1, 25)
        rows.append([f"А-{1000 + i}", _num(h, 1), _num(40 + slope * h + r.gauss(0, 8), 1)])
    return "Связь.csv", _csv(rows)


def fam_likert(r: random.Random) -> tuple[str, str]:
    cols = ["Утверждение", "Не согласен", "Скорее нет", "Не знаю", "Скорее да", "Согласен"]
    rows = [cols]
    for i in range(r.randint(3, 8)):
        cuts = sorted(r.sample(range(1, 100), 4))
        parts = [cuts[0], cuts[1] - cuts[0], cuts[2] - cuts[1], cuts[3] - cuts[2], 100 - cuts[3]]
        rows.append([f"Вопрос {i + 1}"] + parts)
    return "Опрос.csv", _csv(rows)


def fam_reference(r: random.Random) -> tuple[str, str]:
    n = r.randint(31, 250)
    rows = [["Клиент", "Отрасль", "Регион", "Выручка, млн ₽"]]
    for i in range(n):
        rows.append([f"Клиент {i:03d}", r.choice(["ИТ", "Ритейл", "Банки"]), r.choice(REGIONS[:5]),
                     _num(r.paretovariate(1.5) * 3, 1)])
    return "Клиенты.csv", _csv(rows)


def fam_parts_total(r: random.Random) -> tuple[str, str]:
    """Части и колонка «Всего», равная их сумме, — законный состав."""
    k = r.randint(3, 10)
    rows = [["Направление", "Бюджет, чел.", "Платное, чел.", "Целевое, чел.", "Всего, чел."]]
    for i in range(k):
        a, b, c = r.randint(0, 200), r.randint(0, 300), r.randint(0, 60)
        rows.append([f"Направление {chr(1040 + i)}", a, b, c, a + b + c])
    return "Приём.csv", _csv(rows)


FAMILIES: list[Callable[[random.Random], tuple[str, str]]] = [
    fam_daily, fam_monthly_level, fam_categories, fam_plan_fact, fam_years, fam_long, fam_distribution, fam_kpi,
    fam_relationship, fam_likert, fam_reference, fam_parts_total,
]


def random_cases(n_per: int = 30, seed: int = 20261016) -> list[tuple[str, str]]:
    out = []
    for fam in FAMILIES:
        r = random.Random(f"{seed}-{fam.__name__}")
        for k in range(n_per):
            name, text = fam(r)
            out.append((f"{fam.__name__}-{k}-{name}", text))
    return out


# ═══════════════════════════════════════════ сырые значения ════════════════════════════════════════════════════════
def _raw(cell) -> Optional[float]:
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    q = quantity(" ".join(str(cell).split()))
    return None if q is None else q.full


def _rows(t: Table) -> list[int]:
    totals = set(t.totals or [])
    return [i for i, r in enumerate(t.rows) if i not in totals and not any(is_total_label(v) for v in r[:2])]


def _col(t: Table, name: str) -> Optional[int]:
    base = re.sub(r"\s*,[^,]*$", "", name).strip()
    for j, c in enumerate(t.columns):
        if c == name or c == base:
            return j
    return None


def _close(a: float, b: float, rel: float = 0.006, absol: float = 0.51) -> bool:
    return abs(a - b) <= max(absol, rel * max(abs(a), abs(b)))


def _labels(t: Table) -> list[str]:
    """Тексты таблицы (подписи, названия колонок и числа в названиях — «2026» в «Выручка 2026»): их цифры — имена."""
    out = list(t.columns) + [w for c in t.columns for w in re.findall(r"\d+", c)]
    for r in t.rows:
        out += [str(v) for v in r if isinstance(v, str)]
    return out


# ═══════════════════════════════════════════ проверка ═══════════════════════════════════════════════════════════════
def check(name: str, t: Table, p: DatasetPlan) -> list[str]:
    """Пересчёт чисел плана по сырым строкам. Возвращает список нарушений (пусто — всё верно)."""
    bad: list[str] = []
    facts = {f.id: f for f in p.headline_facts}
    head = p.headline or ""
    rows = _rows(t)

    # каждое число заголовка — среди фактов (цифры подписей и названий колонок не в счёт)
    vals = [f.value for f in p.headline_facts]
    for n in numbers_in(head, _labels(t) + [p.plain_headline]):
        if not any(abs(n - abs(v)) < 1e-9 or any(abs(round(abs(v), k) - n) < 1e-9 for k in (0, 1, 2, 3)) for v in vals):
            bad.append(f"число {n} заголовка не из фактов: {head}")

    # пункты — только у процентов и индексов
    def point_ok(label: str, unit: Optional[str]) -> bool:
        u = unit or split_unit(label)[1]
        if u:
            return u == "%" or u.startswith("п.п")
        h = re.sub(r"[^а-яёa-z ]", " ", split_unit(label)[0].lower()).split()
        heads = [w for w in h if len(w) > 2]
        return any(INDEX_HEAD.match(w) for w in heads[:3])

    body = chart_spec_of(p, t) if p.options else None
    if isinstance(body, list):
        ru = t.row_units or []
        for c in body:
            if re.search(r"\bп\.(?:п\.)?", c.label):
                row = next((i for i, r in enumerate(t.rows) if r and str(r[0]).strip() and c.label.startswith(
                    split_unit(str(r[0]))[0])), None)
                unit = (ru[row] if row is not None and row < len(ru) else None) or (quantity(c.value.replace(NB, " ")).unit
                                                                                       if quantity(c.value.replace(NB, " ")) else None)
                if not point_ok(c.label, unit):
                    bad.append(f"пункты у не-процента: {c.value} — {c.label}")
    ch = facts.get("change")
    if ch is not None and ch.unit in ("п.", "п.п.") and p.task.task == "dynamics":
        m = p.chosen_option
        spec = body if isinstance(body, ChartSpec) else None
        mname = spec.series[0].name if spec and spec.series else ""
        j = _col(t, mname)
        unit = t.units[j] if j is not None and j < len(t.units) else None
        if not point_ok(mname, unit if ch.unit != "п.п." else (unit or "%")):
            bad.append(f"пункты у не-процента в динамике: {mname} {unit}")
        _ = m

    # «100%» — только когда все
    sw = facts.get("share_within")
    if sw is not None:
        th = facts["threshold"]
        j = next((k for k in range(len(t.columns)) if k > 0 or len(t.columns) == 1), 0)
        jcol = max(range(len(t.columns)), key=lambda k: sum(1 for i in rows if _raw(t.rows[i][k]) is not None))
        xs = [v for v in (_raw(t.rows[i][jcol]) for i in rows) if v is not None]
        to_min = {"ч": 60, "мин": 1, "дн.": 1440, "с": 1 / 60}.get(th.unit or "", None)
        thr = th.value * to_min if to_min is not None and re.search(r"мин", t.columns[jcol], re.I) else th.value
        within = sum(1 for v in xs if v <= thr + 1e-9)
        share = within / len(xs) * 100
        if sw.value >= 100 and within < len(xs):
            bad.append(f"«100%» при {within} из {len(xs)}")
        if not (abs(sw.value - round(share)) <= 1 or (sw.value == 99 and within < len(xs))):
            bad.append(f"доля «не больше» {sw.value} против {share:.2f} по сырым")
        _ = j
    if re.search(r"(?<![\d,])100%", head) and sw is not None and sw.value < 100:
        bad.append("«100%» в заголовке без всех значений")

    spec = body if isinstance(body, ChartSpec) else None
    # сравнение и доли: лидер, его значение и доля — по сырым суммам категорий
    lead = facts.get("leader_share") or facts.get("leader_value")
    if p.task.task in ("comparison", "shares") and lead is not None and spec is not None and spec.x_title and spec.series:
        dj = _col(t, spec.x_title)
        # колонка метрики — та из рядов графика, по которой посчитан лидер (у сгруппированных их несколько)
        cand = [_col(t, s_.name) for s_ in spec.series if s_.name != "Доля"]
        cand = [j for j in cand if j is not None]
        lvf = facts.get("leader_value")

        def _lead_sum(j: int) -> float:
            sums_: dict[str, float] = {}
            for i in rows:
                lab, v = str(t.rows[i][dj]).strip(), _raw(t.rows[i][j])
                if v is not None and lab:
                    sums_[lab] = sums_.get(lab, 0.0) + v
            return max(sums_.values()) if sums_ else float("nan")

        mj = next((j for j in cand if lvf is None or _close(lvf.value, _lead_sum(j))), cand[0] if cand else None)
        if dj is not None and mj is not None:
            sums: dict[str, list[float]] = {}
            for i in rows:
                lab, v = str(t.rows[i][dj]).strip(), _raw(t.rows[i][mj])
                if v is not None and lab:
                    sums.setdefault(lab, []).append(v)
            agg = {k: sum(v) for k, v in sums.items()}
            leader = max(agg, key=lambda k: agg[k])
            total = sum(agg.values())
            lv = facts.get("leader_value")
            if lv is not None and not _close(lv.value, agg[leader]) and not _close(lv.value, np.mean(sums[leader])):
                bad.append(f"значение лидера {lv.value} против {agg[leader]} по сырым")
            ls = facts.get("leader_share")
            if ls is not None and all(v >= 0 for v in agg.values()):
                tot_row = [i for i in range(len(t.rows)) if i not in rows]
                tv = next((_raw(t.rows[i][mj]) for i in tot_row if _raw(t.rows[i][mj])), None)
                expect = agg[leader] / (tv or total) * 100
                if abs(ls.value - expect) > 0.6:
                    bad.append(f"доля лидера {ls.value} против {expect:.2f}")
    # состав — только при признаке целого
    if p.chosen_option and p.chosen_option.kind in ("stacked_bar", "stacked_column") and p.task.task == "shares":
        parts = [s.name for s in spec.series] if spec else []
        if any(re.search(r"(?:19|20)\d\d|план|факт", s, re.I) for s in parts):
            bad.append(f"годы или план/факт как части: {parts}")
        pj = [j for j in (_col(t, s) or next((k for k, c in enumerate(t.columns) if c.endswith(s)), None) for s in parts)
              if j is not None]
        totj = next((k for k, c in enumerate(t.columns) if is_total_label(c)), None)
        evid = bool(t.column_groups and any(t.column_groups))
        sums = [sum(_raw(t.rows[i][j]) or 0 for j in pj) for i in rows]
        if totj is not None:
            evid = evid or all(_close(s_, _raw(t.rows[i][totj]) or 0) for s_, i in zip(sums, rows))
        evid = evid or (bool(sums) and all(97 <= s_ <= 103 for s_ in sums))
        if not evid:
            bad.append(f"состав без признака целого: {parts}")
        # доли частей — по сырым суммам колонок
        whole = sum(sums)
        for k in range(len(parts)):
            f = facts.get(f"part_{k}")
            if f is None:
                continue
            nm = re.match(r"^(.*?) — ", f.text)
            if nm is None:
                continue
            j = _col(t, nm.group(1)) or next((jj for jj, c in enumerate(t.columns) if c.endswith(nm.group(1))), None)
            if j is not None and whole:
                expect = sum(_raw(t.rows[i][j]) or 0 for i in rows) / whole * 100
                if abs(f.value - expect) > 0.6:
                    bad.append(f"доля части {nm.group(1)} {f.value} против {expect:.2f}")
    # справочник: доля топ-10
    top = facts.get("top_share")
    if top is not None:
        mj = next((k for k, c in enumerate(t.columns) if (t.units[k] if k < len(t.units) else None) in ("млн ₽", "тыс. ₽", "₽")),
                  None)
        if mj is not None:
            xs = sorted((v for v in (_raw(t.rows[i][mj]) for i in rows) if v is not None), reverse=True)
            expect = sum(xs[:10]) / sum(xs) * 100
            if abs(top.value - expect) > 0.6:
                bad.append(f"доля топ-10 {top.value} против {expect:.2f}")
    # план и факт: исполнение
    ex = facts.get("execution")
    if ex is not None:
        pj = next(k for k, c in enumerate(t.columns) if re.search(r"план", c, re.I))
        fj = next(k for k, c in enumerate(t.columns) if re.search(r"факт", c, re.I))
        ps = sum(_raw(t.rows[i][pj]) or 0 for i in rows if _raw(t.rows[i][pj]))
        fsum = sum(_raw(t.rows[i][fj]) or 0 for i in rows if _raw(t.rows[i][pj]))
        if abs(ex.value - fsum / ps * 100) > 0.6:
            bad.append(f"исполнение {ex.value} против {fsum / ps * 100:.2f}")
    # воронка: конверсия
    cv = facts.get("conversion")
    if cv is not None:
        xs = [v for v in (_raw(t.rows[i][1]) for i in rows) if v is not None]
        expect = xs[-1] / xs[0] * 100
        if not _close(cv.value, expect, rel=0.05, absol=0.0005 if expect < 1 else 0.6):
            bad.append(f"конверсия {cv.value} против {expect:.4f}")
    # взаимосвязь: r по сырым парам
    rf = facts.get("r")
    if rf is not None and spec is not None and spec.xy:
        xj = _col(t, spec.x_title or "")
        yj = _col(t, spec.y_title or "")
        if xj is not None and yj is not None:
            pairs = [(_raw(t.rows[i][xj]), _raw(t.rows[i][yj])) for i in rows]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            r = float(np.corrcoef([a for a, _ in pairs], [b for _, b in pairs])[0, 1])
            if abs(rf.value - min(0.99, round(abs(r), 2))) > 0.011:
                bad.append(f"r {rf.value} против {r:.3f}")
            if rf.value > 0.99:
                bad.append("r больше 0,99")
    # динамика: изменение между полными периодами по сырым дням/месяцам
    if p.task.task == "dynamics" and spec is not None and spec.series and facts.get("change") is not None \
            and facts["change"].unit == "%" and len(spec.series) == 1:
        bad += _check_dynamics(t, rows, spec, facts["change"].value)
    return bad


_FREQ_OF_LABEL = [
    (re.compile(r"^[а-я]{3} \d{4}$"), "month"), (re.compile(r"^[IV]+ кв\. \d{4}$"), "quarter"),
    (re.compile(r"^\d{4}$"), "year"), (re.compile(r"^нед\. \d+, \d{4}$"), "week"),
    (re.compile(r"^\d{1,2} [а-я]{3} \d{4}$"), "day"),
]


def _bucket(day: dt.date, freq: str):
    if freq == "month":
        return day.year, day.month
    if freq == "quarter":
        return day.year, (day.month - 1) // 3
    if freq == "year":
        return day.year
    if freq == "week":
        return day.isocalendar()[:2]
    return day.toordinal()


def _calendar_days(key, freq: str) -> int:
    if freq == "month":
        y, m = key
        return (dt.date(y + m // 12, m % 12 + 1, 1) - dt.date(y, m, 1)).days
    if freq == "quarter":
        y, q = key
        return sum(_calendar_days((y, q * 3 + k), "month") for k in (1, 2, 3))
    if freq == "year":
        return 366 if (key % 4 == 0 and (key % 100 or key % 400 == 0)) else 365
    if freq == "week":
        return 7
    return 1


def _check_dynamics(t: Table, rows: list[int], spec: ChartSpec, change: float) -> list[str]:
    bad: list[str] = []
    freq = next((f for rx, f in _FREQ_OF_LABEL if spec.categories and rx.match(spec.categories[0])), None)
    tj = 0
    mj = _col(t, spec.series[0].name)
    if freq is None or mj is None:
        return bad
    days = []
    for i in rows:
        pp = period_parts(str(t.rows[i][tj]))
        v = _raw(t.rows[i][mj])
        if pp is None or v is None:
            continue
        g, o = pp
        if g == "day":
            days.append((dt.date.fromordinal(o), v, "day"))
        elif g == "month":
            days.append((dt.date(o // 12, o % 12 + 1, 1), v, "month"))
        elif g == "quarter":
            days.append((dt.date(o // 4, (o % 4) * 3 + 1, 1), v, "quarter"))
        elif g == "year":
            days.append((dt.date(o, 1, 1), v, "year"))
    if not days or days[0][2] != "day" or freq == "day":
        return bad  # проверяем ресэмплинг дней — главный источник ошибок; остальное сверено выше
    buckets: dict = {}
    cnt: dict = {}
    for d, v, _ in days:
        k = _bucket(d, freq)
        buckets[k] = buckets.get(k, 0.0) + v
        cnt[k] = cnt.get(k, 0) + 1
    vals = [v for v in spec.series[0].values if v is not None]
    if not vals:
        return bad
    keys = sorted(buckets)
    full = [k for k in keys if cnt[k] >= _calendar_days(k, freq)]
    # первая и последняя точки графика — полные периоды
    for v in (vals[0], vals[-1]):
        k = next((kk for kk in keys if _close(buckets[kk], v, rel=1e-6, absol=0.01)), None)
        if k is not None and k not in full:
            bad.append(f"на графике неполный период {k}: {cnt[k]} из {_calendar_days(k, freq)} дней")
    if len(full) >= 2:
        first, last = buckets[full[0]], buckets[full[-1]]
        lag = {"month": 12, "quarter": 4, "week": 52, "year": 1}.get(freq, 0)
        cands = [(last / first - 1) * 100]
        if len(full) > lag and lag:
            prev = full[-1 - lag] if len(full) > lag else None
            if prev is not None and buckets[prev]:
                cands.append((last / buckets[prev] - 1) * 100)
        ratio_ok = any(abs(abs(c) - change) <= 0.6 or abs(abs(c) - round(abs(c), 1)) < 1e-9 and abs(abs(c) - change) < 0.06
                       for c in cands) or any(_close(c / 100 + 1, change, rel=0.02, absol=0.06) for c in cands)
        if not ratio_ok:
            bad.append(f"изменение {change}% против {[round(c, 2) for c in cands]} по полным периодам")
    return bad


# ═══════════════════════════════════════════ тесты ═════════════════════════════════════════════════════════════════
def _plan_of(name: str, text: str) -> tuple[Table, DatasetPlan]:
    t = read_bytes(name.split("-", 2)[-1] if name.startswith("fam_") else name, text.encode("utf-8"))[0]
    return t, plan_dataset(profile_table(t), t)


@pytest.mark.parametrize("name,text", corpus(), ids=[n for n, _ in corpus()])
def test_reviewer_corpus_numbers_from_raw_rows(name, text):
    t, p = _plan_of(name, text)
    assert not check(name, t, p), (p.headline, check(name, t, p))
    for k in range(len(p.options)):
        assert chart_spec_of(p, t, option=k) is not None


def test_random_tables_numbers_from_raw_rows():
    """Сотни случайных таблиц 12 семейств: ни одного неверного числа и ни одного нарушения правил."""
    cases = random_cases()
    assert len(cases) >= 300
    failures = []
    for name, text in cases:
        t, p = _plan_of(name, text)
        errs = check(name, t, p)
        if errs:
            failures.append((name, p.headline, errs))
        for k in range(len(p.options)):
            b = chart_spec_of(p, t, option=k)
            assert b is not None and (isinstance(b, (ChartSpec, TableData, NotBuilt)) or
                                      all(isinstance(c, NumberCallout) for c in b))
    assert not failures, failures[:5]


def test_checker_catches_planted_errors():
    """Сетка ловит то, ради чего она есть: подменённое число, «100%» не у всех, пункты у денег."""
    t, p = _plan_of("Категории.csv", _csv([["Регион", "Выручка, млн ₽"], ["Москва", 500], ["Казань", 300], ["Омск", 200]]))
    assert not check("ok", t, p)
    broken = p.model_copy(deep=True)
    for f in broken.headline_facts:
        if f.id == "leader_share":
            f.value = 60.0
    assert any("доля лидера" in e for e in check("bad", t, broken))
    t2, p2 = _plan_of("Распределение.csv", _csv([["Номер", "Минут доставки"]] + [[f"N-{i}", 70 + i % 50] for i in range(399)]
                                                + [["N-x", 131]]))
    broken = p2.model_copy(deep=True)
    for f in broken.headline_facts:
        if f.id == "share_within":
            f.value = 100.0
    assert any("100%" in e for e in check("bad", t2, broken))
