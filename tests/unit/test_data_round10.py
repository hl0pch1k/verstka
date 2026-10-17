"""Раунд 10 (четвёртая проверка сходимости, conv4): шапка «год, единица», прогноз по колонке статуса, устойчивый
тренд (Тейл — Сен, Манн — Кендалл, разброс по MAD) и всплеск по MAD, слова цены — только по самой величине, допуск у
целых средних, вес удельной величины — колонка её знаменателя."""

from __future__ import annotations

import csv
import io

from tests.unit.test_data_factcheck import corpus_conv4
from verstka.data.aggregate import Data, per_unit_denominator, status_column
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
    assert _sp(p.headline) == "Расход топлива вырос на 1,3% за 13 недель" and not any("не подтвердил" in r
                                                                                     for r in p.task.reasons)
