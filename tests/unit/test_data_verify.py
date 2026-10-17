"""Самопроверка выводов перед показом (`verstka/data/verify.py`, Task 7, раунд 7, часть B): каждое число заголовка и
подписи пересчитывается по сырым строкам таблицы по объявленному происхождению. Ошибка или непроверяемое число —
заголовок-описание вместо вывода, подпись только из подтверждённого, причина в «Почему так». Верные выводы (оба набора
примеров, все проверочные корпуса) проверка не трогает."""

from __future__ import annotations

from pathlib import Path

import pytest

import verstka.data.plan as plan_mod
from verstka.data.aggregate import Data
from verstka.data.facts import facts_for
from verstka.data.plan import data_of, plan_dataset, plan_datasets, slide_data_of
from verstka.data.profile import profile_table
from verstka.data.readers import read_bytes, read_file
from verstka.data.verify import numbers_ok, verify
from verstka.data.words import file_title
from verstka.schemas.data import HeadlineFact, Table

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = {
    "data-sales-2026": "Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, "
                       "что даёт выручку и где узкие места. Данные — в приложенных файлах.",
    "data-science-2026": "Итоги университета за 2026 год для учёного совета. Покажи, как подготовка влияет на баллы ЕГЭ, "
                         "как устроен приём по формам обучения, как растёт наука и на что ушёл бюджет НИОКР. Данные — в "
                         "приложенных файлах.",
}
DOWN = "Вывод не подтвердился проверкой"


def _csv(rows: list[list]) -> bytes:
    return ("\n".join(";".join("" if c is None else str(c) for c in r) for r in rows) + "\n").encode("utf-8")


def _t(name: str, rows: list[list]) -> Table:
    return read_bytes(name, _csv(rows))[0]


def _recheck(t: Table, p) -> object:
    """Факты плана с происхождением — заново и проверка каждого (не только тех, что в заголовке)."""
    fs = facts_for(p.task.task, data_of(p, t))
    title = file_title(p.profile.file, p.profile.sheet)
    return fs, verify(t, fs.facts, fs.prov, p.headline, p.caption, plan_mod._check_labels(fs, data_of(p, t), title),
                      title)


# ── верные выводы не понижаются ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("folder", sorted(SAMPLES))
def test_sample_sets_never_downgraded(folder):
    files = [f for f in sorted((ROOT / "examples" / folder).iterdir()) if f.suffix in (".csv", ".xlsx", ".json", ".txt")]
    tables = [read_file(f)[0] for f in files]
    for brief in ("", SAMPLES[folder]):
        for t, p in zip(tables, plan_datasets(tables, brief)):
            assert not any(DOWN in r or "Подпись не подтвердилась" in r for r in p.task.reasons), \
                (p.profile.file, p.task.reasons)
            fs, v = _recheck(t, p)
            # каждое число каждого факта подтверждено строками файла, у каждого факта есть происхождение
            assert not v.failed, (p.profile.file, v.failed)
            assert v.headline_ok and v.caption_ok, (p.profile.file, p.headline, p.caption, v.reasons)


def _corpora():
    import tests.unit.test_data_factcheck as tf

    out = [(f"rev7b/{n}", n, x.encode("utf-8"), "") for n, x in tf.corpus()]
    out += [(f"rev7c/{n}", n, x.encode("utf-8"), "") for n, x in tf.corpus_rev7c()]
    out += [(f"conv/{n}|{'b' if b else 'nb'}", n, x, b) for n, x, b in tf._conv_cases()]
    return out


def test_corpora_never_downgraded_and_every_fact_verified():
    """Все проверочные корпуса (rev7b, rev7c, 40 таблиц сходимости с целью и без): ни одного понижения и ни одного
    факта без подтверждения — проверка строже теста-оракула не ложится на верные выводы."""
    bad = []
    for key, name, data, brief in _corpora():
        t = read_bytes(name, data)[0]
        p = plan_datasets([t], brief, profiles=[profile_table(t)])[0]
        if any(DOWN in r for r in p.task.reasons):
            bad.append((key, p.task.reasons))
            continue
        fs, v = _recheck(t, p)
        if v.failed or not v.headline_ok or not v.caption_ok:
            bad.append((key, v.failed, v.reasons))
    assert not bad, bad[:5]


def test_conv2_never_downgraded_numbers_and_claims():
    """40 таблиц второй проверки сходимости (с целью и без): ни числа, ни утверждения не понижены."""
    import tests.unit.test_data_factcheck as tf

    bad = []
    for key, files, brief0 in tf.corpus_conv2():
        tables = [read_bytes(n, x)[0] for n, x in files]
        for brief in ("", brief0):
            for t, p in zip(tables, plan_datasets(tables, brief)):
                if any(DOWN in r or "Подпись не подтвердилась" in r for r in p.task.reasons):
                    bad.append((key, brief, p.task.reasons))
                fs, v = _recheck(t, p)
                if v.failed:
                    bad.append((key, brief, v.failed))
    assert not bad, bad[:5]


def test_random_families_never_downgraded():
    import tests.unit.test_data_factcheck as tf

    bad = []
    for name, text in tf.random_cases(n_per=8):
        t, p = tf._plan_of(name, text)
        fs, v = _recheck(t, p)
        if v.failed or not v.headline_ok or not v.caption_ok or any(DOWN in r for r in p.task.reasons):
            bad.append((name, v.failed, v.reasons))
    assert not bad, bad[:5]


# ── посаженные ошибки ловятся ─────────────────────────────────────────────────────────────────────────────────────
INSURANCE = [["Вид страхования", "Число выплат", "Сумма выплат, млн руб."],
             ["ОСАГО", 41250, "4620,5"], ["КАСКО", 18340, "3815,2"], ["ДМС", 96210, "2140,8"],
             ["Имущество", 5120, "912,4"], ["Жизнь", 2210, "1288,0"]]


def test_share_named_by_another_column_is_caught():
    """C1: доля ДМС посчитана по числу выплат (59%), а заголовок говорит «суммы выплат» — проверка ловит."""
    t = _t("Страховые выплаты.csv", INSURANCE)
    cnt = {r[0]: r[1] for r in INSURANCE[1:]}
    share = round(cnt["ДМС"] / sum(cnt.values()) * 100)
    f = HeadlineFact(id="leader_share", text=f"ДМС — {share}%", value=share, unit="%", kind="share")
    prov = {"leader_share": {"op": "share", "col": 1, "by": 0, "keys": ["ДМС"], "agg": "sum", "tol": 0.51,
                             "named": "суммы выплат", "col_name": "Число выплат"}}
    v = verify(t, [f], prov, f"ДМС — {share}% суммы выплат", None, ["ДМС"])
    assert not v.headline_ok and "не колонка «Число выплат»" in v.reasons[0]
    # та же доля, названная своей колонкой, — подтверждается
    prov["leader_share"]["named"] = "числа выплат"
    assert verify(t, [f], prov, f"ДМС — {share}% числа выплат", None, ["ДМС"]).headline_ok


def test_number_off_from_raw_rows_is_caught():
    """Факт расходится с сырыми строками (таблица изменилась после расчёта) — вывод понижается с причиной."""
    rows = [["Регион", "Выручка, млн ₽"], ["Москва", 420], ["Казань", 180], ["Омск", 95]]
    t = _t("Выручка по регионам.csv", rows)
    d = Data(t, profile_table(t), compare=True)
    fs = facts_for("comparison", d)
    lead = fs.get("leader_value")
    assert lead is not None and lead.value == 420
    assert verify(t, fs.facts, fs.prov, "Москва впереди: 420 млн ₽", None, ["Москва"]).headline_ok
    t2 = _t("Выручка по регионам.csv", [rows[0], ["Москва", 420], ["Казань", 510], ["Омск", 95]])
    v = verify(t2, fs.facts, fs.prov, "Москва впереди: 420 млн ₽", None, ["Москва"])
    assert not v.headline_ok and "не наибольшее" in v.reasons[0]


def test_unverifiable_number_is_caught():
    rows = [["Месяц", "Заказы"], ["2025-01", 100], ["2025-02", 130]]
    t = _t("Заказы.csv", rows)
    f = HeadlineFact(id="mystery", text="+30%", value=30, unit="%", kind="change")
    v = verify(t, [f], {}, "Заказы выросли на 30%", None)
    assert not v.headline_ok and "нечем проверить" in v.reasons[0]


def test_plan_falls_back_to_plain_headline_and_factual_caption(monkeypatch):
    """Шаблон дал число, которого нет в файле: план показывает тему, подпись — из подтверждённых фактов, причина —
    в «Почему так» (SlideData.task.reasons)."""
    rows = [["Месяц", "Выручка, млн ₽"]] + [[f"2025-{m:02d}", 100 + 10 * m] for m in range(1, 13)]
    t = _t("Выручка по месяцам.csv", rows)
    good = plan_dataset(profile_table(t), t)
    assert DOWN not in " ".join(good.task.reasons)

    real = plan_mod.compose

    def wrong(task, fs):
        head, cap = real(task, fs)
        return "Выручка выросла на 97% за год", (cap or "") + " Пик — 999 млн ₽."

    monkeypatch.setattr(plan_mod, "compose", wrong)
    p = plan_dataset(profile_table(t), t)
    assert p.headline == p.plain_headline
    assert any(r.startswith(DOWN) for r in p.task.reasons), p.task.reasons
    assert any("Подпись не подтвердилась" in r for r in p.task.reasons)
    assert "999" not in (p.caption or "") and "97" not in (p.caption or "")
    fs, v = _recheck(t, p)
    assert not numbers_ok(p.caption or "", v.pool, plan_mod._check_labels(fs, data_of(p, t), ""))
    sd = slide_data_of(p)
    assert any(r.startswith(DOWN) for r in sd.task.reasons)
    # в факты заголовка — только подтверждённые
    assert {f.id for f in p.headline_facts} <= {f.id for f in fs.facts}


# ── утверждения, не только числа (раунд 8) ────────────────────────────────────────────────────────────────────────
def _facts(name: str, rows: list[list], task: str = "comparison"):
    t = _t(name, rows)
    d = Data(t, profile_table(t), compare=task == "comparison")
    fs = facts_for(task, d)
    return t, fs


CHECKS = [["Магазин", "Средний чек, ₽", "Рост за год, %"], ["Арбат", 1540, "12,4"], ["Тверская", 1290, "5,1"],
          ["Марьино", 980, "3,2"], ["Бутово", 1050, "4,0"]]


def test_growth_clause_on_the_wrong_item_is_caught():
    """F1: «…, Марьино — 980 ₽ и растёт быстрее всех» — числа верны, утверждение — нет."""
    t, fs = _facts("Средний чек.csv", CHECKS)
    good = "Арбат впереди и растёт быстрее всех: 1 540 ₽, Марьино — 980 ₽"
    bad = "Арбат впереди: 1 540 ₽, Марьино — 980 ₽ и растёт быстрее всех"
    assert verify(t, fs.facts, fs.prov, good, None, ["Арбат", "Марьино"]).headline_ok
    v = verify(t, fs.facts, fs.prov, bad, None, ["Арбат", "Марьино"])
    assert not v.headline_ok and "быстрее всех" in v.reasons[0] and "Марьино" in v.reasons[0]


def test_wrong_leader_and_single_name_in_a_tie_are_caught():
    t, fs = _facts("Средний чек.csv", CHECKS)
    v = verify(t, fs.facts, fs.prov, "Тверская впереди: 1 540 ₽, Марьино — 980 ₽", None, ["Тверская", "Марьино"])
    assert not v.headline_ok and "впереди назван «Тверская»" in v.reasons[0]
    rows = [["Школа", "Средний балл ЕГЭ"], ["Лицей № 2", "78,4"], ["Гимназия № 1", "78,4"], ["Школа № 15", "71,9"]]
    t, fs = _facts("Рейтинг школ.csv", rows)
    labs = ["Лицей № 2", "Гимназия № 1", "Школа № 15"]
    assert verify(t, fs.facts, fs.prov, "Лицей № 2 и Гимназия № 1 впереди: 78,4, Школа № 15 — 71,9", None,
                  labs).headline_ok
    v = verify(t, fs.facts, fs.prov, "Лицей № 2 впереди: 78,4, Школа № 15 — 71,9", None, labs)
    assert not v.headline_ok and "ничья" in v.reasons[0]


def test_all_n_and_target_claims_are_counted():
    months = ["Январь", "Февраль", "Март", "Апрель"]
    rows = [["Месяц", "2024", "2025"], ["Январь", 300, 310], ["Февраль", 300, 290], ["Март", 300, 320],
            ["Апрель", 300, 330]]
    t = _t("Перевозки, тыс. чел.csv", rows)
    d = Data(t, profile_table(t))
    fs = facts_for("dynamics", d)
    assert fs.get("up") is not None and fs.get("up").value == 3
    v = verify(t, fs.facts, fs.prov, "2025 к 2024: +4% за январь–апрель, выше во всех 4 месяцах", None,
               ["2024", "2025"] + months)
    assert not v.headline_ok and "во всех 4" in v.reasons[0]
    sla = [81.4, 79.8, 83.2, 77.5, 84.0, 85.3]
    rows = [["Неделя", "SLA, %", "Цель, %"]] + [[f"{1 + 7 * k:02d}.06.2026", str(x).replace(".", ","), "80"]
                                               for k, x in enumerate(sla[:4])] + [["29.06.2026", "84", "80"]]
    t = _t("SLA.csv", rows)
    d = Data(t, profile_table(t))
    fs = facts_for("dynamics", d)
    if fs.get("below_target") is not None:
        n = int(fs.get("periods").value)
        v = verify(t, fs.facts, fs.prov, f"SLA: выше цели 80% во всех {n} неделях, в конце — 84%", None, ["SLA"])
        assert not v.headline_ok


def test_better_for_a_lower_is_better_measure_is_caught():
    rows = [["Регион", "Ошибок, шт."], ["Москва", 120], ["Казань", 40], ["Омск", 30]]
    t, fs = _facts("Ошибки по регионам.csv", rows)
    v = verify(t, fs.facts, fs.prov, "Москва впереди: 120 шт., Омск — 30 шт.", None, ["Москва", "Омск"])
    assert not v.headline_ok and "меньше — лучше" in v.reasons[0]


def test_histogram_open_bin_claim_is_checked():
    """A1: столбец «больше X» считает все значения за X — иначе подпись о выбросах неправда."""
    import random as _r

    rnd = _r.Random(5)
    vals = [round(rnd.gammavariate(2.0, 25.0)) for _ in range(300)] + [900, 1200, 1500]
    t = _t("Время ответа.csv", [["Обращение", "Минут до ответа"]] + [[f"T-{k}", x] for k, x in enumerate(vals)])
    p = plan_dataset(profile_table(t), t)
    b = plan_mod._bins_claim(data_of(p, t), p.task.task)
    assert b is not None and not any("не подтвердил" in r for r in p.task.reasons)
    inliers_only = {**b, "counts": b["counts"][:-1] + [b["counts"][-1] - 3]}  # как было: выбросов в столбце нет
    fs = facts_for("distribution", data_of(p, t))
    v = verify(t, fs.facts, fs.prov, "", p.caption, plan_mod._check_labels(fs, data_of(p, t), ""), bins=inliers_only)
    assert not v.caption_ok and "на гистограмме" in v.reasons[-1] or "столбец" in v.reasons[-1]


def test_plan_drops_a_false_claim_with_the_reason(monkeypatch):
    t = _t("Средний чек.csv", CHECKS)
    real = plan_mod.compose

    def wrong(task, fs):
        head, cap = real(task, fs)
        return "Арбат впереди: 1 540 ₽, Марьино — 980 ₽ и растёт быстрее всех", cap

    monkeypatch.setattr(plan_mod, "compose", wrong)
    p = plan_dataset(profile_table(t), t)
    assert p.headline == p.plain_headline
    assert any(r.startswith(DOWN) and "быстрее всех" in r for r in slide_data_of(p).task.reasons)
