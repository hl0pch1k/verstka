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
