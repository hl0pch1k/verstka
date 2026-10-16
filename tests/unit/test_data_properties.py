"""Страховочная сетка чтения и профиля: свойства на сотнях случайных правдоподобных таблиц (повторное ревью, раунд 3).

Принцип: правило срабатывает только по прямому однородному признаку; без него данные остаются как написаны.
- Текст ячейки не меняется, кроме описанной нормализации (пробелы; подпись строки-показателя без единицы после запятой
  или в скобках: «Принято, чел.» → «Принято»). «Молоко 3,2%», «Скидка 10%» не трогаются.
- Единица колонки — только с признаком: единица в шапке, единица в ячейках, единица названия таблицы при однородных
  колонках или слово единицы в имени колонки. Единица строки — из подписи после запятой/в скобках или из её ячеек.
- Одиночный всплеск ×10 и больше никогда не «естественный» выброс (`expected_outliers`).
- Деньги/число устойчивы к масштабу: если колонка — деньги, то и в 10 раз большие значения — деньги; без «слабых»
  денежных слов («бюджет», «расходы», «затраты», «оборот», «факт») тип от масштаба не зависит."""

from __future__ import annotations

import random

import pytest

from verstka.data.parse import split_unit
from verstka.data.profile import profile_table
from verstka.data.readers import _label_unit, _names_the_unit, read_bytes

ENTITY_LABELS = [
    "Клиент {i:03d}", "Магазин {i}", "Филиал {i}", "Товар {i}", "Молоко {p}%", "Скидка {p}%", "НДС {p}%",
    "Тариф {i}", "Проект «{i}»", "ООО «Вектор {i}»",
]
NUMERIC_HEADERS = [
    ("Выручка", ["", ", млн ₽", ", тыс. руб.", " (₽)"]), ("Клиентов", ["", ", чел."]), ("Заказов", ["", ", шт."]),
    ("Доля", ["", ", %"]), ("Бюджет", ["", ", руб."]), ("Расходы", ["", ", млн ₽"]), ("Численность", ["", ", человек"]),
    ("Площадь", ["", ", м²"]), ("Минут до ответа", ["", ", мин"]), ("Оценка", [""]), ("Факт", [""]), ("Сумма", ["", ", ₽"]),
]
TITLES = ["", "Сотрудники по отделам, человек", "Продажи за квартал, тыс. руб.", "Выручка по регионам, млн ₽",
          "Отчёт по филиалам", "Структура, %"]
KPI_LABELS = ["Принято, чел.", "Трудоустроено, %", "Объём НИОКР, млн ₽", "Средний балл", "Отчислено, чел.",
              "Индекс удовлетворённости", "Выручка (млн ₽)", "Доля онлайна, %"]


def _fmt(v: float, comma: bool) -> str:
    s = f"{v:.1f}" if isinstance(v, float) else str(v)
    return s.replace(".", ",") if comma else s


def _entity_table(rnd: random.Random, scale: float = 1.0) -> tuple[str, dict]:
    n = rnd.randint(4, 40)
    label_tpl = rnd.choice(ENTITY_LABELS)
    labels = []
    for i in range(n):
        lab = label_tpl.format(i=i + 1, p=rnd.choice([1, 2.5, 3.2, 5, 10, 20, 25]) if "{p}" in label_tpl else 0)
        lab = lab.replace(".", ",") if "%" in lab else lab
        labels.append(lab if lab not in labels else f"{lab} ({i})")
    heads = rnd.sample(NUMERIC_HEADERS, rnd.randint(1, 3))
    cols, names = [], []
    for base, units in heads:
        names.append(base + rnd.choice(units))
        size = rnd.choice([1, 10, 100, 1000, 50_000, 2_000_000])
        decimal = rnd.random() < 0.3
        col = []
        for _ in range(n):
            v = size * rnd.uniform(0.2, 1.5) * scale
            col.append(round(v, 1) if decimal else int(v))
        cols.append(col)
    spike = None
    if n >= 15 and rnd.random() < 0.5:  # одиночный всплеск ×50 — опечатка, а не крупный клиент
        k = rnd.randrange(len(cols))
        spike = (rnd.randrange(n), k)
        cols[k][spike[0]] = max(cols[k]) * 50
    title = rnd.choice(TITLES)
    lines = ([title, ""] if title else []) + [";".join(["Название"] + names)]
    raw_rows = []
    for i in range(n):
        cells = [labels[i]] + [_fmt(c[i], True) for c in cols]
        if rnd.random() < 0.05:
            cells[rnd.randrange(1, len(cells))] = rnd.choice(["—", "н/д", ""])
        raw_rows.append(cells)
        lines.append(";".join(cells))
    if rnd.random() < 0.3:
        lines.append(";".join(["Итого"] + [_fmt(sum(c), True) for c in cols]))
    return "\n".join(lines) + "\n", {"labels": labels, "names": names, "spike": spike, "title": title, "raw": raw_rows}


def _kpi_table(rnd: random.Random) -> tuple[str, dict]:
    labels = rnd.sample(KPI_LABELS, rnd.randint(2, 6))
    lines = [rnd.choice(["Показатель", "Статья", "Метрика"]) + ";2026;2025"]
    raw_rows = []
    for lab in labels:
        unit = _label_unit(lab)[1]
        a, b = rnd.randint(50, 3000), rnd.randint(50, 3000)
        if unit == "%" and rnd.random() < 0.5:
            cells = [lab, f"{a % 100}%", f"{b % 100}%"]
        else:
            cells = [lab, str(a), str(b)]
        raw_rows.append(cells)
        lines.append(";".join(cells))
    return "\n".join(lines) + "\n", {"labels": labels, "raw": raw_rows, "title": "", "spike": None}


def _norm(s: str) -> str:
    return " ".join(str(s).split())


def _check_cells(t, meta) -> None:
    allowed = {_norm(c) for r in meta["raw"] for c in r if c} | {"Итого"}
    allowed |= {_label_unit(c)[0] for r in meta["raw"] for c in r[:1] if c and _label_unit(c)[1]}
    for r in t.rows:
        for v in r:
            if isinstance(v, str):
                assert _norm(v) in allowed, (v, t.file)
    for lab in meta["labels"]:  # подпись без единицы после запятой/в скобках — как в файле
        if _label_unit(lab)[1] is None and any(_norm(lab) == _norm(r[0]) for r in meta["raw"]):
            assert any(r and r[0] == lab for r in t.rows), lab


def _check_units(t, meta) -> None:
    title_unit = split_unit(meta["title"])[1] if meta["title"] else None
    numeric = [j for j, c in enumerate(t.columns) if any(isinstance(r[j], (int, float)) and not isinstance(r[j], bool)
                                                         for r in t.rows)]
    titled = [j for j in numeric if t.units[j] == title_unit and split_unit(t.raw_header[j])[1] is None]
    for j, u in enumerate(t.units):
        if u is None:
            continue
        head = split_unit(t.raw_header[j])[1]
        cells = [r[j + 0] for r in meta["raw"] if j < len(r)]
        from_cells = any(isinstance(c, str) and c.strip().endswith(u.split()[-1]) for c in cells)
        if head == u or from_cells:
            continue
        assert title_unit == u, (t.columns[j], u)
        # единица названия: всем однородным колонкам без своей единицы — или колонке со словом этой единицы
        bare = [k for k in numeric if split_unit(t.raw_header[k])[1] is None]
        assert set(titled) == set(bare) or _names_the_unit(t.columns[j], u), (t.columns, t.units, meta["title"])
    for i, ru in enumerate(t.row_units):
        if ru is None:
            continue
        raw = meta["raw"][i]
        assert _label_unit(raw[0])[1] == ru or any(isinstance(c, str) and c.strip().endswith(ru[-1]) for c in raw[1:]), \
            (raw, ru)


@pytest.mark.parametrize("seed", range(8))
def test_random_tables_keep_text_units_and_spikes_honest(seed):
    rnd = random.Random(1000 + seed)
    for _ in range(60):
        text, meta = (_kpi_table if rnd.random() < 0.25 else _entity_table)(rnd)
        t = read_bytes("t.csv", text.encode())[0]
        _check_cells(t, meta)
        _check_units(t, meta)
        p = profile_table(t)
        if meta["spike"] is not None:
            row, k = meta["spike"]
            name = t.columns[k + 1]
            assert not any(o.row == row and o.column == name for o in p.expected_outliers), (name, text[:200])


@pytest.mark.parametrize("seed", range(4))
def test_money_type_is_stable_under_scaling(seed):
    weak = ("бюджет", "расход", "затрат", "оборот", "факт")
    for k in range(50):
        seed_k = 2000 + seed * 100 + k
        small = _entity_table(random.Random(seed_k), 1.0)
        big = _entity_table(random.Random(seed_k), 10.0)
        ps = profile_table(read_bytes("s.csv", small[0].encode())[0])
        pb = profile_table(read_bytes("b.csv", big[0].encode())[0])
        for cs, cb in zip(ps.columns, pb.columns):
            if cs.role != "metric" or cb.role != "metric":
                continue
            if cs.type == "money":
                assert cb.type == "money", (cs.name, cs.type, cb.type)
            if not any(w in cs.name.lower() for w in weak):
                assert (cs.type == "money") == (cb.type == "money"), (cs.name, cs.type, cb.type)
