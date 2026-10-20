"""conv5 (2026-10-17): what the data deck states as a fact comes only from verified facts with their own meaning.

Fixtures — the conv5 tables (tests/fixtures/data/conv5); the model's answers — as the live run recorded them (no live
calls): the storyteller's rewrites that were FALSE, the goals the goal reader gave."""

from __future__ import annotations

from pathlib import Path

import pytest

from verstka.data.answer import named_rows, rows_answer
from verstka.data.derive import apply, merge_label_typos, ratio_spec
from verstka.data.facts import facts_for
from verstka.data.goals import Goal, GoalPeriod
from verstka.data.headline import compose
from verstka.data.intent import UNMET, GoalReading, read_goals
from verstka.data.parse import quantity, split_unit
from verstka.data.plan import plan_datasets
from verstka.data.readers import read_file
from verstka.data.story import _card_figure, build_data_story, key_figure
from verstka.data.units import _time_unit_of, additivity
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.data import HeadlineFact, Table
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "conv5"


def _t(prefix: str) -> list[Table]:
    path = next(DATA.glob(f"{prefix}_*"))
    return read_file(path)


def _story(prefix: str, brief: str, goals: list[dict], writing: dict, notes: list[dict] = ()):
    """The story with the model's recorded answers: the goals (GoalReading) and the connecting text (StoryWriting)."""
    reading = {"goals": goals, "unanswerable": list(notes)}
    mp = MockProvider({"turn every question or request": reading, "*": writing}, model="recorded")
    reg = ProviderRegistry(roles={"llm": mp})
    tables = []
    for p in prefix.split("+"):
        tables += _t(p)
    return build_data_story(Brief(text=brief), tables, use_llm=True, skills=SkillsRegistry.load(), providers=reg)


def _answer(st) -> str:
    """The question's answer — the heading of the slide that answers it (the first data slide). The cover is the deck's
    topic: one conclusion is never said twice (owner, 21.10; before, the answer was the cover too)."""
    from verstka.data.story import same_headline

    o = st.outline
    ans = next(s for s in o.slides if s.data is not None).headline
    assert not same_headline(o.slides[0].headline, ans)
    return ans


def _texts(st) -> str:
    o = st.outline
    out = [o.title or "", o.subtitle or ""]
    for s in o.slides:
        out += [s.headline or "", s.takeaway or ""]
        if s.content is not None:
            out += [it.text or "" for it in s.content.items] + [it.title or "" for it in s.content.items]
    return " ‖ ".join(out)


def _n(text: str) -> str:
    return (text or "").replace("\u00a0", " ")


def _refused(st, what: str, text: str) -> bool:
    return any(r["what"] == what and r["to"] == text and not r["accepted"] for r in st.rephrased)


# ── F1: the storyteller keeps the meaning of the facts ───────────────────────────────────────────────────────────────
def test_a_true_number_said_as_another_measure_is_refused_02b():
    brief = ("Нужно сравнить школы по числу не сдавших — где проблема острее всего, причём не в штуках, а относительно "
             "числа сдававших.")
    goal = {"span": brief, "dataset": "d1", "task": "comparison", "metric": "Не сдали", "dimension": "Школа", "ask": "max",
            "aggregation": "weighted_mean", "weight": "Сдавали", "direction": "lower"}
    bad = "Школа № 12 — 28% не сдавших, разрыв с другими школами в 11 раз"
    st = _story("02", brief, [goal], {"title": bad, "headlines": [{"id": "data-1", "headline": bad}]})
    # the weighted mean of a count is a ratio (F2): the fail rate, and the worst one is School 26 (6 of 51)
    assert "Школа № 26" in _answer(st) and "11,8%" in _answer(st)
    assert bad not in _texts(st)


@pytest.mark.parametrize("prefix, brief, goal, bad", [
    ("08", "У какого музея выручка на одного посетителя выше всего?",
     {"task": "comparison", "metric": "Выручка от билетов", "dimension": "Музей", "ask": "max"},
     "У Краеведческого музея выручка на посетителя выше: 35 120 тыс. ₽"),
    ("23", "Покажи, на какой фильм в среднем ходило больше всего зрителей за сеанс.",
     {"task": "comparison", "metric": "Зрители", "dimension": "Фильм", "ask": "max"},
     "Ледокол-2 собирает больше всего зрителей за сеанс"),
    ("17", "В какой категории чаще всего возвращают товар?",
     {"task": "comparison", "metric": "Доля возвратов", "dimension": "Категория", "ask": "max"},
     "Чаще всего возвращают одежду: 16,9% всех возвратов"),
    ("07", "Какой маршрут самый загруженный за квартал?",
     {"task": "comparison", "metric": "Итого за квартал", "dimension": "Маршрут", "ask": "max"},
     "Автобус 12 лидирует с 1 265 пассажиров"),
    ("22", "Какой тип машин самый прожорливый, если считать расход на 100 км по всему пробегу?",
     {"task": "comparison", "metric": "Расход на 100 км", "dimension": "Тип ТС", "ask": "max"},
     "Магистральный тягач — самый прожорливый тип: 33% расхода"),
])
def test_qualifiers_and_units_from_the_brief_are_refused(prefix, brief, goal, bad):
    st = _story(prefix, brief, [{"span": brief, "dataset": "d1", **goal}], {"title": bad})
    assert st.outline.title != bad and _refused(st, "title", bad)


def test_a_network_figure_is_never_said_of_one_region_18c():
    brief = "Я хочу понять одну вещь: стало ли время восстановления в Сибири меньше во втором полугодии, чем в первом?"
    goal = {"span": brief, "dataset": "d1", "task": "dynamics", "metric": "Среднее время восстановления",
            "dimension": "Регион", "categories": ["Сибирь"], "aggregation": "weighted_mean", "weight": "Инцидентов",
            "period": {"kind": "compare", "base": "2025-01", "target": "2025-07"}, "yes_no": True}
    st = _story("18", brief, [goal], {"title": "Время восстановления в Сибири сократилось на 13% во втором полугодии"})
    head = _answer(st)
    # F5: Siberia only, the halves as ranges (the brief's words), not the network's January against July
    assert head.startswith("Сибирь") and "июль – декабрь 2025" in head and "январь – июнь 2025" in head
    assert "−24%" in head and "13%" not in _texts(st)


@pytest.mark.parametrize("bad", [
    "Набор пациентов опережает план: рост в 3 раза против плана 2,2 раза",
    "Набор пациентов превысил план в 3 раза за 10 месяцев",
])
def test_a_verdict_the_facts_do_not_carry_is_refused_04a(bad):
    brief = "Успеваем ли мы набрать пациентов по плану к концу года?"
    goal = {"span": brief, "dataset": "d1", "task": "dynamics", "metric": "Набрано, пациентов", "ask": "meet",
            "yes_no": True, "period": {"kind": "latest"}}
    st = _story("04", brief, [goal], {"title": bad, "next_steps": ["Сохранить текущий темп набора до конца года"]})
    assert bad not in _texts(st)


def test_no_link_is_claimed_without_its_fact_10c():
    brief = "Можем посмотреть, связана ли доля доставки с выручкой ресторана?"
    tables = [Table(id="r", file="Рестораны.csv", kind="csv", columns=["Ресторан", "Доля доставки", "Чеков", "Средний чек"],
                    units=[None, "%", None, "₽"], rows=[[f"Р{i}", 10 + i * 3, 1000 + i * 400, 3000 - i * 200] for i in range(9)],
                    raw_header=["Ресторан", "Доля доставки, %", "Чеков", "Средний чек, ₽"])]
    mp = MockProvider({"turn every question or request": {"goals": []}, "*": {"title": "Доля доставки не связана с выручкой ресторана"}})
    st = build_data_story(Brief(text=brief), tables, use_llm=True, skills=SkillsRegistry.load(),
                          providers=ProviderRegistry(roles={"llm": mp}))
    assert st.outline.title != "Доля доставки не связана с выручкой ресторана"


def test_a_benchmark_row_is_no_other_category_02a():
    brief = "Какая школа лучше всех сдала ЕГЭ по среднему баллу и насколько она обгоняет среднее по району?"
    goal = {"span": brief, "dataset": "d1", "task": "comparison", "metric": "Средний балл", "dimension": "Школа", "ask": "max"}
    good = "Лицей № 1 лидирует: 74,6 против 66,4 по району"
    st = _story("02", brief, [goal], {"headlines": [{"id": "data-1", "headline": good}]})
    assert st.outline.slides[1].headline == good or any(r["to"] == good and r["accepted"] for r in st.rephrased)


def test_a_signed_change_backs_its_verdict_and_a_true_rewrite_stays():
    brief = "Покажите, где средняя задержка рейсов сократилась сильнее всего по сравнению с прошлым сентябрём."
    goal = {"span": brief, "dataset": "d1", "task": "dynamics", "metric": "Средняя задержка", "dimension": "Аэропорт",
            "period": {"kind": "compare", "base": "2025-09", "target": "2026-09"}}
    good = "Средняя задержка снизилась на 2,3% к сентябрю 2025"
    st = _story("01", brief, [goal], {"headlines": [{"id": "data-1", "headline": good}]})
    assert any(r["to"] == good and r["accepted"] for r in st.rephrased)


# ── F4: the rows a question names ────────────────────────────────────────────────────────────────────────────────────
def test_rows_are_named_by_whole_words_not_substrings_03a():
    t = _t("03")[0]
    assert named_rows("Какой город лучше по удовлетворённости клиентов?", t) == []  # «город» ≠ «Академгородок»


def test_a_percent_column_is_said_by_its_own_name_09c():
    t = _t("09")[0]
    q = "Правда ли, что группа «Ночная» хуже остальных по оценке качества?"
    ra = rows_answer(q, t, main="Оценка качества")
    assert ra is not None and _n(ra.short).startswith("Ночная — оценка качества: 79 баллов")
    assert "меньше — только у «Выходного дня» (74 балла)" in _n(ra.short)
    no_main = rows_answer(q, t)
    assert "среднего ожидания" not in no_main.short and "потерянные звонки: 5,8%" in _n(no_main.text)


def test_the_cover_answers_the_question_with_the_measure_09c():
    brief = ("Давайте ответим на один вопрос: правда ли, что группа «Ночная» хуже остальных по оценке качества?")
    goal = {"span": brief, "dataset": "d1", "task": "comparison", "metric": "Оценка качества", "dimension": "Группа",
            "categories": ["Ночная"], "yes_no": True, "direction": "higher"}
    st = _story("09", brief, [goal], {"title": "Группа «Ночная» не хуже остальных по оценке качества"})
    assert _answer(st).startswith("Ночная — ") and "79" in _answer(st) and "5,8" not in _answer(st)


# ── F2: per-unit, top-N, named shares, column against column, period extremes, what is not computed ───────────────
@pytest.mark.parametrize("prefix, num, den, quote, name, unit, top", [
    ("08", "Выручка от билетов", "Посетители", "у какого музея выручка на одного посетителя выше всего",
     "Выручка от билетов на одного посетителя", "₽", ("Дом-музей Чехова", 521)),
    ("23", "Зрители", "Сеансов", "на какой фильм ходило больше всего зрителей за сеанс", "Зрители за сеанс", None,
     ("Северный ветер", 50.7)),
    ("13", "ДМС", "Итого", "где доля ДМС в выплатах региона самая высокая", "Доля «ДМС» от «Итого»", "%",
     ("Татарстан", 27.3)),
    ("21", "Выручкa", "Активных членов", "Сравни клубы по выручке на одного активного члена",
     "Выручкa на одного активного члена", "₽", ("Атлант", 3500)),
])
def test_a_ratio_is_computed_and_verified(prefix, num, den, quote, name, unit, top):
    t = _t(prefix)[0]
    spec = ratio_spec(t, num, den, quote)
    assert spec["name"] == name and spec["unit"] == unit
    t2 = apply(t, spec)
    g = Goal(phrase=quote.lower(), task="comparison", viz="bar", to="", given=True, column=name, weight=spec["den"], ask="max",
             derive=spec)
    p = plan_datasets([t2], quote, goals=[g])[0]
    assert top[0] in p.headline and f"{top[1]:g}".replace(".", ",") in _n(p.headline).replace(" ", "")
    assert not any("не подтвердил" in r for r in p.task.reasons)


def _read(prefix: str, brief: str, goals: list[dict], notes: list[dict] = ()):
    return read_goals(brief, _t(prefix), reading=GoalReading.model_validate({"goals": goals, "unanswerable": list(notes)}))


def test_a_weighted_mean_of_a_sum_by_a_count_is_a_ratio_and_by_a_probability_is_not_computed():
    r = _read("23", "Покажи фильм с наибольшим числом зрителей за сеанс.", [{"span": "Покажи фильм с наибольшим числом зрителей за сеанс.",
              "dataset": "d1", "task": "comparison", "metric": "Зрители", "ask": "max", "aggregation": "weighted_mean",
              "weight": "Сеансов"}])
    assert r.understood[0].ratio is not None and r.understood[0].metric == "Зрители за сеанс" and r.tables is not None
    brief = "Скажи, какая ожидаемая выручка по всей воронке с учётом вероятностей?"
    r = _read("15", brief, [{"span": brief, "dataset": "d1", "task": "comparison", "metric": "Сумма сделок", "ask": "total",
                             "aggregation": "weighted_mean", "weight": "Вероятность закрытия"}])
    assert not r.understood and r.notes and r.notes[0].reason.startswith(UNMET)


def test_an_expected_value_is_said_as_not_computed_on_the_cover_15c():
    brief = "Квартал заканчивается, CFO просит прогноз. Скажи, какая ожидаемая выручка по всей воронке с учётом вероятностей?"
    goal = {"span": "Скажи, какая ожидаемая выручка по всей воронке с учётом вероятностей?", "dataset": "d1", "task": "comparison",
            "metric": "Сумма сделок", "ask": "total", "aggregation": "weighted_mean", "weight": "Вероятность закрытия"}
    st = _story("15", brief, [goal], {"title": "Ожидаемая выручка по воронке — 2 751 млн ₽",
                                      "subtitle": "Прогноз для CFO"})
    o = st.outline
    assert "не посчитано" in (o.subtitle or "") and "2 751" not in o.title and "Ожидаем" not in o.title
    summary = next(s for s in o.slides if s.id == "summary")
    assert any(it.title == "Без ответа в данных" and UNMET in it.text for it in summary.content.items)


def test_column_against_column_and_plan_met_are_lists_14c_21c_11a():
    q = "покажем, на каких программах платных заявлений меньше, чем платных мест"
    r = _read("14", q, [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Платное Заявлений", "ask": "below"}])
    u = r.understood[0]
    assert u.ask == "versus_lt" and u.versus == "Платное Мест"
    p = plan_datasets(_t("14"), q, goals=r.goals)[0]
    assert "у 3 из 9: Менеджмент, Педагогическое образование и Агрономия" in p.headline
    q = "Какие станции выполнили план по выработке, а какие нет?"
    r = _read("11", q, [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Выработка янв–сен 2026", "ask": "meet"}])
    p = plan_datasets(_t("11"), q, goals=r.goals)[0]
    assert p.headline.startswith("План выполнили 4 из 7") and "Нива" in (p.caption or "")


def test_top_n_and_named_share_07c_11c():
    q = "Нужно показать, какую долю пассажиров перевозят пять крупнейших маршрутов вместе."
    r = _read("07", q, [{"span": q, "dataset": "d1", "task": "shares", "metric": "Итого за квартал", "ask": "total"}])
    assert r.understood[0].ask == "top_n" and r.understood[0].n == 5
    p = plan_datasets(_t("07"), q, goals=r.goals)[0]
    assert p.headline.startswith("5 крупнейших") and "49%" in p.headline  # (4 772 of 9 792 = 48,7%)
    q = "Покажи хотя бы, какая доля всей выработки приходится на астраханские станции."
    r = _read("11", q, [{"span": q, "dataset": "d1", "task": "shares", "metric": "Выработка янв–сен 2026",
                         "dimension": "Регион", "categories": ["Астраханская область"]}])
    p = plan_datasets(_t("11"), q, goals=r.goals)[0]
    assert p.headline.startswith("Астраханская область — 25%") and not any("не подтвердил" in x for x in p.task.reasons)


def test_the_lowest_period_of_the_network_20c():
    q = "Нам нужно ответить, в каком месяце загрузка сети была самой низкой."
    r = _read("20", q, [{"span": q, "dataset": "d1", "task": "dynamics", "metric": "Загрузка", "ask": "min",
                         "aggregation": "weighted_mean", "weight": "Номеров"}])
    p = plan_datasets(_t("20"), q, goals=r.goals)[0]
    assert "ниже всего — ноябрь 2025" in p.headline


def test_threshold_without_a_number_and_no_second_column_is_a_visible_note():
    q = "где выручки меньше, чем у соседей"
    r = _read("21", q, [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Выручкa", "ask": "below"}])
    assert not r.understood and r.notes and r.notes[0].reason.startswith(UNMET)


# ── F3: rates and sums ───────────────────────────────────────────────────────────────────────────────────────────────
def test_per_unit_rates_never_add_up_and_a_quarter_total_does():
    assert additivity("Расход на 100 км", "л", "number")[0] is False
    assert additivity("Выручка на посетителя", "₽", "money")[0] is False
    assert additivity("Зрителей за сеанс", None, "number")[0] is False
    assert additivity("Итого за квартал", "тыс. пасс.", "number")[0] is True
    assert split_unit("Итого за квартал, тыс. пасс.") == ("Итого за квартал", "тыс. пасс.")


def test_litres_per_100_km_are_weighted_by_mileage_22a():
    q = "Какой тип машин самый прожорливый, если считать расход на 100 км по всему пробегу?"
    r = _read("22", q, [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Расход на 100 км",
                         "dimension": "Тип ТС", "ask": "max", "aggregation": "weighted_mean", "weight": "Пробег за квартал"}])
    p = plan_datasets(_t("22"), q, goals=r.goals)[0]
    assert "Рефрижератор" in p.headline and "32,4" in p.headline and "296" not in (p.caption or "")


# ── the «Мин» columns ────────────────────────────────────────────────────────────────────────────────────────────────
def test_min_is_a_minimum_not_minutes():
    assert _time_unit_of("Мин", None, ["Мин", "Макс"], [10, 20]) is None
    assert _time_unit_of("Мин цена", None, ["Мин цена", "Макс цена"], [100, 200]) is None
    assert _time_unit_of("Мин температура", None, [], [-3, 5]) is None
    assert _time_unit_of("Минут до ответа", None, [], [3, 5]) == "мин"
    assert _time_unit_of("Время ответа", "мин", ["Макс время ответа"], [3, 5]) == "мин"


# ── F9: a goal with categories and no measure never crashes the deck ────────────────────────────────────────────────
def test_categories_without_a_measure_do_not_crash_12b():
    brief = "Сравните итоговую конверсию от отклика до оффера в IT и в продажах."
    goal = {"span": brief, "dataset": "d1", "task": "comparison", "categories": ["Отклик", "Оффер"]}
    st = _story("12", brief, [goal], {})
    assert st.outline.slides and st.outline.title


def test_a_plan_that_raises_with_the_models_goals_is_rebuilt_with_the_rules(monkeypatch):
    import verstka.data.story as story_mod

    real = story_mod.plan_datasets

    def boom(tables, brief_text="", profiles=None, goals=None):
        if goals is not None:
            raise KeyError("leader")
        return real(tables, brief_text, profiles, goals=goals)

    monkeypatch.setattr(story_mod, "plan_datasets", boom)
    brief = "Какой регион даёт больше всего выплат по КАСКО?"
    st = _story("13", brief, [{"span": brief, "dataset": "d1", "task": "comparison", "metric": "КАСКО", "ask": "max"}], {})
    assert st.outline.slides and any(s.data is not None for s in st.outline.slides)


def test_compose_without_a_leader_says_the_topic():
    from verstka.data.facts import FactSet

    fs = FactSet()
    fs.ctx.update({"plain": "Кандидаты по этапам"})
    assert compose("comparison", fs)[0] == "Кандидаты по этапам"  # (no «leader» in the facts' words: no KeyError)


# ── F10: signs and decimals of the cards ─────────────────────────────────────────────────────────────────────────────
def test_a_decrease_keeps_its_sign_and_a_decimal_its_comma():
    assert key_figure("Лицей № 1 впереди: 74,6, Школа № 26 — 57,2") == "74,6"
    facts = [HeadlineFact(id="period_change", text="−17%", value=-17.0, unit="%", kind="change")]
    assert _card_figure("Простой роботов снизился на 17% после обновления", facts) == "−17%"
    q = "Стали ли роботы меньше простаивать после обновления прошивки в середине августа?"
    r = _read("06", q, [{"span": q, "dataset": "d1", "task": "dynamics", "metric": "Простой роботов",
                         "period": {"kind": "compare", "base": "2026-07", "target": "2026-08"}}])
    p = plan_datasets(_t("06"), q, goals=r.goals)[0]
    ch = next(f for f in p.headline_facts if f.id == "period_change")
    assert ch.value < 0


# ── F11: the cover ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_cover_is_never_an_opinion_from_the_brief_12c_25c():
    brief = ("HR-директор считает, что проблема в скорингах на входе. Я с этим не согласен, но спорить без цифр не хочу. "
             "Давай просто покажем, сколько людей в продажах дошли до выхода на работу из тех, кто откликнулся.")
    goal = {"span": "Давай просто покажем, сколько людей в продажах дошли до выхода на работу из тех, кто откликнулся.",
            "dataset": "d1", "task": "comparison", "metric": "Продажи Кандидатов", "dimension": "Этап",
            "categories": ["Выход на работу"]}
    st = _story("12", brief, [goal], {"title": "Из 3 988 откликов до выхода дошли 118"})
    title = st.outline.title
    assert "HR-директор" not in title and "3 988" not in title
    assert "6,4%" in _answer(st) and "118 из 1 850" in _n(_answer(st))  # the funnel (a stage it lacks is a gap, not the end)
    st = build_data_story(Brief(text="Мэрия хочет закрыть один филиал. Я против, но аргументы нужны."), _t("25"))
    assert not st.outline.title.startswith("Мэрия") and st.outline.title != "Что показывают данные"


# ── F7, F13 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_typo_label_joins_its_category_with_a_note_03a():
    t, notes = merge_label_typos(_t("03")[0])
    cities = {r[1] for r in t.rows}
    assert "Новосибрск" not in cities and "Новосибирск" in cities and "Новосибрск" in notes[0]


def test_dates_and_week_numbers_are_no_figures_of_the_data_check_06a():
    q = "Стали ли роботы меньше простаивать после обновления прошивки в середине августа?"
    goal = {"span": q, "dataset": "d1", "task": "dynamics", "metric": "Простой роботов",
            "period": {"kind": "compare", "base": "2026-07-01", "target": "2026-08-15"}}
    st = _story("06", q, [goal], {})
    head = next(s for s in st.outline.slides if s.data is not None).headline
    assert "15 августа" in head and "−28%" in head


# ── I2, I6 (final review) ────────────────────────────────────────────────────────────────────────────────────────────
def test_a_count_word_per_row_is_the_rows_unit():
    q = quantity("120 договоров")
    assert q is not None and q.value == 120 and q.unit == "договоров"
    assert quantity("1 курс") is None and quantity("11 кл.") is None
    t = Table(id="k", file="Итоги года.csv", kind="csv", columns=["Показатель", "Значение"], units=[None, None],
              rows=[["Договоры", "120 договоров"], ["Филиалы", "12 филиалов"], ["Сотрудники", "300 человек"],
                    ["Выручка", "1,2 млрд ₽"]], raw_header=["Показатель", "Значение"])
    p = plan_datasets([t], "")[0]
    assert p.slides >= 1 and not (p.message or "").startswith("Не для графика")


def test_a_huge_workbook_is_refused_and_rows_stop_at_the_cap(monkeypatch):
    import io
    import zipfile

    import verstka.data.readers as R

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", "<x/>" * 10)
    monkeypatch.setattr(R, "XLSX_MAX_XML_BYTES", 5)
    assert R._xlsx_too_big(buf.getvalue())
    with pytest.raises(R.DataReadError, match="слишком большая"):
        R._read_xlsx("big.xlsx", buf.getvalue(), "d")


# ── after the live run (the recorded answers of runs3, replayed) ─────────────────────────────────────────────────────
def test_two_named_rows_compared_are_answered_not_noted_23c():
    brief = ("Прокатчики любят хвастаться сборами, но нас интересует заполняемость. Короче: правда ли, что на «Ледокол-2» "
             "продано больше билетов, чем на «Северный ветер»?")
    q = "Короче: правда ли, что на «Ледокол-2» продано больше билетов, чем на «Северный ветер»?"
    st = _story("23", brief, [{"span": q, "dataset": "d1", "task": "comparison", "metric": "Зрители", "ask": "compare_columns",
                               "categories": ["Ледокол-2", "Северный ветер"], "yes_no": True}], {})
    # (the slide's own answer; before, the cover said it again: «Ледокол-2 — зрители: 2 710 тыс., больше, чем у …»)
    assert _n(_answer(st)) == "Ледокол-2 впереди: 2 710 тыс., Северный ветер — 2 480 тыс."
    assert "всех зрителей" not in _texts(st)  # a share of two named films is no share of all viewers


def test_where_it_dropped_between_two_period_columns_07b():
    q = "Сравни пассажиропоток июля и сентября по маршрутам — где просело?"
    r = _read("07", q, [{"span": q, "dataset": "d1", "task": "dynamics", "metric": "Сентябрь", "ask": "min",
                         "period": {"kind": "compare", "base": "Июль", "target": "Сентябрь"}}])
    p = plan_datasets(_t("07"), q, goals=r.goals)[0]
    assert p.headline.startswith("«Сентябрь» меньше, чем «Июль», — у 3 из 8") and "Автобус 88" in p.headline


def test_conversion_between_two_stages_12b():
    q = "Сравните итоговую конверсию от отклика до оффера в IT и в продажах."
    r = _read("12", q, [{"span": q, "dataset": "d1", "task": "comparison", "categories": ["Отклик", "Оффер"]}])
    p = plan_datasets(_t("12"), q, goals=r.goals)[0]
    assert "IT Кандидатов — 1,7%" in p.headline and "Продажи Кандидатов — 8,1%" in p.headline


def test_a_season_is_its_months_16c():
    q = "Вопрос в справке простой: сократилось ли ожидание в Городской больнице № 2 за лето?"
    r = _read("16", q, [{"span": q, "dataset": "d1", "task": "dynamics", "metric": "Медиана ожидания", "dimension": "Больница",
                         "categories": ["Городская больница № 2"], "yes_no": True}])
    assert r.understood[0].period.start == "2026-06" and r.understood[0].period.end == "2026-08"
    p = plan_datasets(_t("16"), q, goals=r.goals)[0]
    assert p.headline.startswith("Городская больница № 2: −14%")  # 71 → 61 мин over the summer, not −27% to September


def test_a_comparison_of_multiples_needs_its_own_fact_04a():
    brief = "Успеваем ли мы набрать пациентов по плану к концу года?"
    goal = {"span": brief, "dataset": "d1", "task": "dynamics", "metric": "Набрано, пациентов", "ask": "meet",
            "yes_no": True, "period": {"kind": "latest"}}
    bad = "Набрано пациентов в 3 раза больше, чем план вырос за 10 месяцев"
    st = _story("04", brief, [goal], {"headlines": [{"id": "data-1", "headline": bad}]})
    assert bad not in _texts(st) and _refused(st, "headline", bad)


def test_by_most_categories_is_k_of_n_19c():
    t = Table(id="y", file="Урожайность.csv", kind="csv", columns=["Культура", "Год", "Значение"], units=[None, None, "ц/га"],
              rows=[[c, str(y), v] for c, vals in {"Пшеница": (46.3, 43.8), "Ячмень": (33.1, 34.0), "Кукуруза": (61.2, 66.8),
                                                     "Свёкла": (470.0, 447.4)}.items() for y, v in zip((2025, 2026), vals)],
              raw_header=["Культура", "Год", "Значение, ц/га"])
    g = Goal(phrase="был ли 2026 год лучше 2025-го по большинству культур", task="dynamics", viz="line", to="", given=True,
             column="Значение", dimension="Культура", period=GoalPeriod(kind="compare", base="2025", target="2026"))
    p = plan_datasets([t], "x", goals=[g])[0]
    assert p.headline.startswith("В 2026 году выше, чем в 2025, — у 2 из 4") and "period_change" not in {f.id for f in p.headline_facts}
