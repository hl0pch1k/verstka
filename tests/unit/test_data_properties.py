"""Страховочная сетка чтения и профиля — настоящий оракул (повторное ревью, раунды 3–4).

Генератор сам знает правду о каждой колонке: какое имя и какая единица должны получиться, какой тип у меры, какие
числа стоят в ячейках, где одиночный всплеск и сколько таблиц в файле. Тест сравнивает с этим напрямую — без
`_label_unit`, `split_unit`, `_names_the_unit` и других функций проверяемого модуля.

Формы: таблицы-сущности (подписи «Молоко 3,2%», «Скидка 10%» не меняются), деньги/счёт/доли/возраст/коды, «План/Факт»
одного порядка, «Бюджет» мест, счётные слова в ячейках («30 задач») рядом с номерами классов («5 класс»), единица
названия таблицы (только колонкам со словом этой единицы), таблицы показателей по строкам («Принято, чел.») и те же
подписи при колонках «Цена/Количество», две таблицы через пустую строку, «;» внутри CSV через запятую, двухэтажные
шапки «Цена: Мин | Макс», «План: Год | Месяц», «Выручка: млн ₽ | %»."""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass, field
from typing import Any, Optional

import openpyxl
import pytest

from verstka.data.profile import profile_table
from verstka.data.readers import parse_quantity, read_bytes


@dataclass
class Col:
    header: str  # как в файле
    name: str  # ожидаемое имя
    unit: Optional[str]  # ожидаемая единица
    kind: str  # ожидаемый тип: money | number | percent | id | category | text
    raw: list[str]  # ячейки как в файле
    value: list[Any]  # ожидаемые значения после чтения


@dataclass
class Expect:
    cols: list[Col]
    row_units: Optional[list[Optional[str]]] = None
    spike: Optional[tuple[int, str]] = None  # (строка, колонка) — должна быть в profile.outliers
    groups: Optional[list[Optional[str]]] = None
    outliers: Optional[list[int]] = None  # строки колонки `measure`, которые должны быть заметными выбросами
    expected: Optional[list[int]] = None  # … и естественными («лестница» крупнейших)
    measure: str = ""


@dataclass
class Case:
    name: str
    data: bytes
    tables: list[Expect] = field(default_factory=list)


def _ru(v: float, dec: int) -> str:
    return f"{v:.{dec}f}".replace(".", ",") if dec else str(int(v))


def _labels(rnd: random.Random, n: int) -> list[str]:
    tpl = rnd.choice(["Клиент {i:03d}", "Магазин {i}", "Молоко {p}%", "Скидка {p}%", "НДС {p}%", "Тариф «{i}»",
                      "ООО «Вектор {i}»", "Филиал {i}"])
    out = []
    for i in range(n):
        p = rnd.choice(["1", "2,5", "3,2", "5", "10", "20"])
        lab = tpl.format(i=i + 1, p=p)
        out.append(lab if lab not in out else f"{lab} ({i})")
    return out


def _numeric(rnd: random.Random, kind: str, n: int) -> Col:
    """Колонка известного семейства: ожидания заданы здесь, а не выведены из модуля."""
    if kind == "money_unit":
        vals = [round(rnd.uniform(10, 500), 1) for _ in range(n)]
        return Col("Выручка, млн ₽", "Выручка", "млн ₽", "money", [_ru(v, 1) for v in vals], vals)
    if kind == "money_word":
        vals = [rnd.randint(100, 900) for _ in range(n)]
        return Col("Доход", "Доход", None, "money", [str(v) for v in vals], vals)
    if kind == "count":
        vals = [rnd.randint(10, 500) for _ in range(n)]
        return Col("Клиентов", "Клиентов", None, "number", [str(v) for v in vals], vals)
    if kind == "count_unit":
        vals = [rnd.randint(1, 900) for _ in range(n)]
        return Col("Количество, шт.", "Количество", "шт.", "number", [str(v) for v in vals], vals)
    if kind == "share":
        vals = [rnd.randint(1, 40) for _ in range(n)]
        return Col("Доля, %", "Доля", "%", "percent", [str(v) for v in vals], vals)
    if kind == "age":
        vals = [rnd.randint(20, 65) for _ in range(n)]
        return Col("Возраст", "Возраст", None, "number", [str(v) for v in vals], vals)
    if kind == "code":
        vals = [rnd.choice([16, 52, 77, 78, 66]) for _ in range(n)]
        return Col("Код региона", "Код региона", None, "id", [str(v) for v in vals], vals)
    if kind == "budget_places":
        vals = [rnd.randint(50, 300) for _ in range(n)]
        return Col("Бюджет", "Бюджет", None, "number", [str(v) for v in vals], vals)
    if kind == "persons":
        vals = [rnd.randint(5, 80) for _ in range(n)]
        return Col("Численность", "Численность", None, "number", [str(v) for v in vals], vals)
    if kind == "share_cells":  # «12,5 %» в ячейках: единица из ячеек, дробь — через общий разбор
        vals = [round(rnd.uniform(0.5, 40), 1) for _ in range(n)]
        return Col("Конверсия", "Конверсия", "%", "percent", [f"{_ru(v, 1)} %" for v in vals], vals)
    if kind == "tasks":
        while True:
            vals = [rnd.randint(5, 400) for _ in range(n)]
            uniq = sorted(set(vals))
            if uniq != list(range(uniq[0], uniq[0] + len(uniq))):
                break
        return Col("Объём работ", "Объём работ", "задач", "number", [f"{v} задач" for v in vals], vals)
    raise AssertionError(kind)


def _entity(rnd: random.Random) -> Case:
    n = rnd.randint(5, 30)
    labels = _labels(rnd, n)
    kinds = rnd.sample(["money_unit", "money_word", "count", "count_unit", "share", "age", "code", "budget_places",
                        "persons", "tasks", "share_cells"], rnd.randint(1, 4))
    cols = [Col("Название", "Название", None, "category", labels, labels)]
    cols += [_numeric(rnd, k, n) for k in kinds]
    if n <= 7 and rnd.random() < 0.4:  # номера классов подряд — подписи, а не числа
        grades = [f"{5 + i} класс" for i in range(n)]
        cols.append(Col("Класс", "Класс", None, "category", grades, grades))
    if rnd.random() < 0.3:  # «План/Факт» одного порядка: деньги по величине одной из них — обе деньги
        plan = [rnd.randint(4000, 4900) for _ in range(n)]
        fact = [rnd.randint(5100, 6000) for _ in range(n)]
        cols += [Col("План", "План", None, "money", [str(v) for v in plan], plan),
                 Col("Факт", "Факт", None, "money", [str(v) for v in fact], fact)]
    spike = None
    if n >= 15 and rnd.random() < 0.5:  # одиночная опечатка ×50 — заметный выброс
        vals = [rnd.randint(100, 140) for _ in range(n)]
        k = rnd.randrange(n)
        vals[k] = 140 * 50
        cols.append(Col("Сумма заказа, ₽", "Сумма заказа", "₽", "money", [str(v) for v in vals], vals))
        spike = (k, "Сумма заказа")
    title = rnd.choice(["", "", "Доходы и прибыль, тыс. руб.", "Сотрудники по отделам, человек", "Отчёт по филиалам"])
    if title.endswith("человек"):  # слово единицы есть, но колонка — деньги или номер: единицы названия нет
        pay = [rnd.randint(60_000, 140_000) for _ in range(n)]
        cols.append(Col("Зарплата сотрудников", "Зарплата сотрудников", None, "money", [str(v) for v in pay], pay))
        ids = rnd.sample(range(1000, 9999), n)
        cols.append(Col("Номер сотрудника", "Номер сотрудника", None, "id", [str(v) for v in ids], ids))
    if title:  # единица названия — только колонкам со словом этой единицы (выручка; численность)
        for c in cols:
            if c.unit is None and title.endswith("тыс. руб.") and c.header == "Доход":
                c.unit = "тыс. ₽"
            if c.unit is None and title.endswith("человек") and c.header == "Численность":
                c.unit = "чел."
    lines = ([title, ""] if title else []) + [";".join(c.header for c in cols)]
    lines += [";".join(c.raw[i] for c in cols) for i in range(n)]
    return Case("e.csv", ("\n".join(lines) + "\n").encode(), [Expect(cols, row_units=[], spike=spike)])


KPI = [("Принято, чел.", "Принято", "чел."), ("Трудоустроено, %", "Трудоустроено", "%"),
       ("Объём НИОКР, млн ₽", "Объём НИОКР", "млн ₽"), ("Средний балл", "Средний балл", None),
       ("Отчислено, чел.", "Отчислено", "чел."), ("Выручка (млн ₽)", "Выручка", "млн ₽"),
       ("Индекс удовлетворённости", "Индекс удовлетворённости", None), ("Рост продаж 5%", "Рост продаж 5%", None),
       ("Скидка 10%, руб.", "Скидка 10%", "₽")]


def _kpi(rnd: random.Random) -> Case:
    rows = rnd.sample(KPI, rnd.randint(3, 7))
    if sum(1 for _, _, u in rows if u) < 2:
        rows = KPI[:3]
    a = [rnd.randint(50, 3000) for _ in rows]
    b = [rnd.randint(50, 3000) for _ in rows]
    if rnd.random() < 0.5:  # единицы строк: подпись без единицы, значения — числа, у колонок единиц нет
        cols = [Col("Показатель", "Показатель", None, "category", [r[0] for r in rows], [r[1] for r in rows]),
                Col("2026", "2026", None, "number", [str(v) for v in a], a),
                Col("2025", "2025", None, "number", [str(v) for v in b], b)]
        exp = Expect(cols, row_units=[r[2] for r in rows])
    else:  # те же подписи при колонках «Цена» и «Количество» — не таблица показателей: подписи как в файле
        cols = [Col("Товар", "Товар", None, "category", [r[0] for r in rows], [r[0] for r in rows]),
                Col("Цена", "Цена", None, "money", [str(v) for v in a], a),
                Col("Количество", "Количество", None, "number", [str(v) for v in b], b)]
        exp = Expect(cols, row_units=[])
    lines = [";".join(c.header for c in cols)] + [";".join(c.raw[i] for c in cols) for i in range(len(rows))]
    return Case("k.csv", ("\n".join(lines) + "\n").encode(), [exp])


def _stacked(rnd: random.Random) -> Case:
    first, second = _entity_plain(rnd, "Регион", "Выручка"), _entity_plain(rnd, "Менеджер", "Сделок")
    text = first[0] + "\n" + second[0]
    return Case("s.csv", text.encode(), [first[1], second[1]])


def _entity_plain(rnd: random.Random, label: str, measure: str) -> tuple[str, Expect]:
    n = rnd.randint(3, 8)
    labels = [f"{label} {i + 1}" for i in range(n)]
    vals = [rnd.randint(10, 900) for _ in range(n)]
    kind = "money" if measure == "Выручка" else "number"
    cols = [Col(label, label, None, "category", labels, labels), Col(measure, measure, None, kind, [str(v) for v in vals], vals)]
    lines = [f"{label};{measure}"] + [f"{a};{b}" for a, b in zip(labels, vals)]
    return "\n".join(lines) + "\n", Expect(cols, row_units=[])


def _semicolon_in_comma_file(rnd: random.Random) -> Case:
    n = rnd.randint(3, 8)
    names = [f"Статья {i + 1}" for i in range(n)]
    authors = [f"{rnd.choice(['Иванов', 'Ким', 'Ли', 'Орлова'])} А.; {rnd.choice(['Петров', 'Сидорова', 'Ан'])} Б." for _ in range(n)]
    pages = [rnd.randint(5, 40) for _ in range(n)]
    cites = [rnd.randint(0, 300) for _ in range(n)]
    cols = [Col("Название", "Название", None, "category", names, names),
            Col("Авторы", "Авторы", None, "text", authors, authors),
            Col("Страниц", "Страниц", None, "number", [str(v) for v in pages], pages),
            Col("Цитирований", "Цитирований", None, "number", [str(v) for v in cites], cites)]
    lines = [",".join(c.header for c in cols)] + [",".join(c.raw[i] for c in cols) for i in range(n)]
    return Case("a.csv", ("\n".join(lines) + "\n").encode(), [Expect(cols, row_units=[])])


def _two_floor(rnd: random.Random) -> Case:
    group, leaves, names, units, kinds = rnd.choice([
        # слово-подпись под группой — не имя само по себе: «Цена Мин» (не минуты), «План Год» (final review)
        ("Цена", ["Мин", "Макс"], ["Цена Мин", "Цена Макс"], [None, None], ["money", "money"]),
        ("План", ["Год", "Месяц"], ["План Год", "План Месяц"], [None, None], ["number", "number"]),
        # одно имя, разные единицы — имя с единицей (раунд 10, M6), а не «Выручка (2)»
        ("Выручка", ["млн ₽", "%"], ["Выручка, ₽", "Выручка, %"], ["млн ₽", "%"], ["money", "percent"]),
    ])
    n = rnd.randint(3, 6)
    labels = [f"Товар {i + 1}" for i in range(n)]
    a = [rnd.randint(100, 900) for _ in range(n)]
    b = [rnd.randint(1, 99) for _ in range(n)]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Товар", group, None])
    ws.append([None] + leaves)
    ws.merge_cells("B1:C1")
    ws.merge_cells("A1:A2")
    for row in zip(labels, a, b):
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    cols = [Col("Товар", "Товар", None, "category", labels, labels),
            Col("", names[0], units[0], kinds[0], [], a), Col("", names[1], units[1], kinds[1], [], b)]
    return Case("h.xlsx", buf.getvalue(), [Expect(cols, groups=[None, group, group])])


def _ladders(rnd: random.Random) -> Case:
    """Выбросы по форме: «лестница» крупнейших (естественна), короткая лестница, скачок ×4, вершина за 10 границами,
    длительности, три одинаковые опечатки ×50 — ожидания заданы здесь."""
    n = 30
    labels = [f"Клиент {i:03d}" for i in range(n)]
    body = [rnd.randint(100, 140) for _ in range(n)]
    shape = rnd.choice(["ladder", "short", "jump", "beyond", "duration", "typos"])
    tops = {"ladder": [200, 300, 450, 600], "short": [300, 450], "jump": [200, 250, 1100],
            "beyond": [200, 500, 1400, 4000], "duration": [200, 300, 450, 600], "typos": [7000, 7100, 7200]}[shape]
    rows = rnd.sample(range(n), len(tops))
    for r, v in zip(rows, tops):
        body[r] = v
    natural = {"ladder": rows, "beyond": rows[:3]}.get(shape, [])
    name = "Минут до ответа" if shape == "duration" else "Выручка"
    kind = "number" if shape == "duration" else "money"
    cols = [Col("Клиент", "Клиент", None, "category", labels, labels),
            Col(f"{name}, тыс. ₽" if kind == "money" else name, name, "тыс. ₽" if kind == "money" else None, kind,
                [str(v) for v in body], body)]
    lines = [";".join(c.header for c in cols)] + [";".join(c.raw[i] for c in cols) for i in range(n)]
    exp = Expect(cols, row_units=[], outliers=[r for r in rows if r not in natural], expected=natural, measure=name)
    return Case("l.csv", ("\n".join(lines) + "\n").encode(), [exp])


def _semicolon_decimals(rnd: random.Random) -> Case:
    """«;»-файл, где запятая в названии, в шапке и в дробях делит все строки поровну — разделитель всё равно «;»."""
    n = rnd.randint(3, 8)
    labels = [f"Тариф {i + 1}" for i in range(n)]
    vals = [round(rnd.uniform(100, 900), 1) for _ in range(n)]
    cols = [Col("Название", "Название", None, "category", labels, labels),
            Col("Заказов, шт.", "Заказов", "шт.", "number", [_ru(v, 1) for v in vals], vals)]
    lines = ["Сводка по тарифам, 2026", ""] + [";".join(c.header for c in cols)]
    lines += [";".join(c.raw[i] for c in cols) for i in range(n)]
    return Case("d.csv", ("\n".join(lines) + "\n").encode(), [Expect(cols, row_units=[])])


GENERATORS = [(_entity, 6), (_kpi, 2), (_stacked, 1), (_semicolon_in_comma_file, 1), (_two_floor, 1), (_ladders, 2),
              (_semicolon_decimals, 1)]


def _case(rnd: random.Random) -> Case:
    total = sum(w for _, w in GENERATORS)
    x = rnd.uniform(0, total)
    for gen, w in GENERATORS:
        if x < w:
            return gen(rnd)
        x -= w
    return GENERATORS[0][0](rnd)


def _same(got: Any, want: Any) -> bool:
    if isinstance(want, float) or isinstance(got, float):
        return isinstance(got, (int, float)) and not isinstance(got, bool) and math.isclose(got, want, rel_tol=1e-9)
    return got == want


def _check(case: Case) -> None:
    tables = read_bytes(case.name, case.data)
    assert len(tables) == len(case.tables), (case.name, [t.columns for t in tables])
    for t, exp in zip(tables, case.tables):
        assert t.columns == [c.name for c in exp.cols], (t.columns, case.data[:200])
        assert t.units == [c.unit for c in exp.cols], (t.columns, t.units, case.data[:200])
        if exp.row_units is not None:
            assert t.row_units == exp.row_units, (t.row_units, case.data[:200])
        if exp.groups is not None:
            assert t.column_groups == exp.groups, (t.column_groups,)
        n = len(exp.cols[0].value)
        assert len(t.rows) == n, (len(t.rows), n)
        for j, c in enumerate(exp.cols):
            for i in range(n):
                assert _same(t.rows[i][j], c.value[i]), (c.name, i, t.rows[i][j], c.value[i])
            # публичный разбор ячейки (им пользуется анализ) даёт то же число, что записано в файле
            if c.kind in ("money", "number", "percent") and c.raw and all(
                    not any(ch.isalpha() for ch in r) for r in c.raw):
                for r, v in zip(c.raw, c.value):
                    q = parse_quantity(r)
                    assert q is not None and _same(q[0], float(v)), (c.name, r, q, v)
        p = profile_table(t)
        for j, c in enumerate(exp.cols):
            pc = p.columns[j]
            if c.kind in ("money", "number", "percent"):
                assert (pc.role, pc.type) == ("metric", c.kind), (c.name, pc.role, pc.type, case.data[:200])
            elif c.kind == "id":
                assert pc.role == "id", (c.name, pc.role, pc.type)
            else:
                assert pc.role in ("dimension", "text") and pc.type in ("category", "text"), (c.name, pc.role, pc.type)
        if exp.outliers is not None:
            got_out = sorted(o.row for o in p.outliers if o.column == exp.measure)
            got_exp = sorted(o.row for o in p.expected_outliers if o.column == exp.measure)
            assert got_out == sorted(exp.outliers) and got_exp == sorted(exp.expected), (got_out, got_exp, exp)
        if exp.spike is not None:
            row, col = exp.spike
            assert any(o.row == row and o.column == col for o in p.outliers), (exp.spike, p.outliers)
            assert not any(o.row == row and o.column == col for o in p.expected_outliers)


@pytest.mark.parametrize("seed", range(10))
def test_random_tables_against_the_oracle(seed):
    rnd = random.Random(7000 + seed)
    for _ in range(50):
        _check(_case(rnd))


@pytest.mark.parametrize("seed", range(3))
def test_money_type_is_monotone_under_scaling(seed):
    """Деньги остаются деньгами при значениях в 10 раз больше; без «слабых» денежных слов тип от масштаба не зависит."""
    weak = ("бюджет", "расход", "затрат", "оборот", "факт", "план", "прогноз")
    rnd = random.Random(9000 + seed)
    for _ in range(40):
        name = rnd.choice(["Выручка", "Клиентов", "Бюджет", "Факт", "Расходы", "Сделок", "Оборот", "Площадь"])
        base = [rnd.randint(1, 900) * rnd.choice([1, 10, 100]) for _ in range(rnd.randint(4, 20))]
        types = []
        for scale in (1, 10):
            text = f"Отдел;{name}\n" + "\n".join(f"О{i};{v * scale}" for i, v in enumerate(base)) + "\n"
            types.append(profile_table(read_bytes("m.csv", text.encode())[0]).columns[1].type)
        if types[0] == "money":
            assert types[1] == "money", (name, types)
        if not any(w in name.lower() for w in weak):
            assert types[0] == types[1], (name, types)
