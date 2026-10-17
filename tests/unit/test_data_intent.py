"""Цели брифа, понятые моделью (раунд 10, `verstka/data/intent.py`): модель предлагает структурные цели над настоящими
датасетами и колонками, код проверяет каждую часть и отбрасывает неверное; правила (`goals_of`) — запасной путь и
сверка. Без модели — ровно прежнее поведение."""

from __future__ import annotations

import csv
import io
import json

import pytest

from verstka.data import intent
from verstka.data.intent import GoalReading, read_goals, rules_goals
from verstka.data.plan import chart_spec_of, plan_datasets
from verstka.data.readers import read_bytes
from verstka.data.story import build_data_story
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.data import Table
from verstka.skills_registry import SkillsRegistry


def _t(name: str, rows: list[list]) -> Table:
    buf = io.StringIO(newline="")
    csv.writer(buf, delimiter=";").writerows(rows)
    return read_bytes(name, buf.getvalue().encode("utf-8"))[0]


REGIONS = [["Регион", "Заявлений, тыс.", "Доля онлайн, %", "Срок рассмотрения, дн.", "Жалоб на 1000 заявлений"],
           ["Северный", 210, 64, 11.5, 2.1], ["Южный", 410, 71, 9.0, 1.4], ["Восточный", 180, 52, 14.0, 3.3],
           ["Западный", 150, 48, 16.5, 4.0], ["Центральный", 390, 83, 7.5, 1.9], ["Горный", 38, 31, 21.5, 7.2]]
MONTHS = [["Месяц", "Выручка, млн ₽", "Заказов"]] + [[f"2025-{m:02d}", 100 + 9 * m, 900 + 20 * m] for m in range(1, 13)]
BRIEF = "Где дольше всего ждут решения по заявлению?"


def _reading(goals=None, miss=None) -> dict:
    return {"goals": goals or [], "unanswerable": miss or []}


def _mock(answer, calls: list | None = None) -> ProviderRegistry:
    def respond(messages):
        if calls is not None:
            calls.append(messages)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return ProviderRegistry.mock({"*": respond})


@pytest.fixture(autouse=True)
def _fresh():
    intent.clear_cache()
    import verstka.data.plan as plan

    getattr(plan, "_GIVEN", {}).clear()
    yield
    intent.clear_cache()


@pytest.fixture(scope="module")
def skills():
    return SkillsRegistry.load()


# ── without a model: exactly as before ───────────────────────────────────────────────────────────────────────────────
def test_without_a_model_the_rules_parse_the_brief(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    r = read_goals(BRIEF, [t])
    assert r.source == "rules" and r.goals is None and r.skipped == "без модели"
    # what the rules understood — only for the interface
    assert r.understood and r.understood[0].source == "rules" and r.understood[0].task == "comparison"


def test_story_without_a_model_is_the_deterministic_one(monkeypatch, skills):
    """VERSTKA_NO_DOTENV=1, no keys: the story never asks for goals and its plans are the rules' plans."""
    t = _t("Госуслуги регионы.csv", REGIONS)
    called = []
    monkeypatch.setattr(intent, "read_goals", lambda *a, **k: called.append(1))
    before = plan_datasets([t], BRIEF)
    st = build_data_story(BRIEF, [t])  # use_llm=False
    st2 = build_data_story(BRIEF, [t], use_llm=True, skills=skills, providers=None)  # a model is not configured
    assert not called and st.goals_read is None and st2.goals_read is None
    for s in (st, st2):
        assert [p.model_dump() for p in s.plans] == [p.model_dump() for p in before]


# ── the model's goals, checked ───────────────────────────────────────────────────────────────────────────────────────
def test_model_goal_chooses_the_column_the_rules_miss(skills):
    """«Где дольше всего ждут решения по заявлению»: правила видели «заявлен» и показывали колонку заявлений (conv4, 07A);
    модель называет колонку срока — и план показывает её (фраза — слова брифа)."""
    t = _t("Госуслуги регионы.csv", REGIONS)
    ans = _reading([{"span": BRIEF, "dataset": "d1", "task": "comparison", "metric": "Срок рассмотрения",
                     "dimension": "Регион", "ask": "max", "direction": "lower", "confidence": 0.9}])
    calls: list = []
    r = read_goals(BRIEF, [t], skills=skills, providers=_mock(ans, calls))
    assert len(calls) == 1 and r.source == "model" and r.goals is not None
    u = r.understood[0]
    assert (u.task, u.metric, u.ask, u.pinned) == ("comparison", "Срок рассмотрения", "max", True)
    assert "Срок рассмотрения" in u.label
    p = plan_datasets([t], BRIEF, goals=r.goals)[0]
    assert p.task.goal == "где дольше всего ждут решения по заявлению"
    assert chart_spec_of(p, t).series[0].name == "Срок рассмотрения"


def test_wrong_parts_are_dropped_with_a_reason(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    ans = _reading([
        {"span": "Где дольше всего ждут", "dataset": "d1", "task": "comparison", "metric": "Время ожидания",
         "aggregation": "sum", "confidence": 0.5},  # no such column
        {"span": "решения по заявлению", "dataset": "d1", "task": "comparison", "metric": "Доля онлайн",
         "aggregation": "sum"},  # a share does not add up
        {"span": "Этого нет в брифе", "dataset": "d1", "task": "comparison"},  # the quote is not in the brief
        {"span": BRIEF, "dataset": "d1", "task": "dynamics", "metric": "Срок рассмотрения"},  # no time axis
    ])
    r = read_goals(BRIEF, [t], skills=skills, providers=_mock(ans))
    by = {u.quote: u for u in r.understood}
    a = by["Где дольше всего ждут"]
    assert a.metric is None and any("Время ожидания" in x for x in a.dropped)
    b = by["решения по заявлению"]
    assert b.metric == "Доля онлайн" and b.aggregation is None and any("не слагаемое" in x for x in b.dropped)
    whys = " ".join(d["why"] for d in r.dropped)
    assert "цитаты нет" in whys
    # dynamics without a time axis: not lost — a visible note with the reason
    assert any(n.reason == "в данных нет оси времени" for n in r.notes)


def test_threshold_unit_must_be_the_columns(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    brief = "В каких регионах рассмотрение занимает больше 15 дней?"
    ok = _reading([{"span": brief, "dataset": "d1", "task": "comparison", "metric": "Срок рассмотрения",
                    "ask": "above", "threshold": {"value": 15, "unit": "дней"}}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(ok))
    assert r.understood[0].ask == "above:15" and "выше 15 дней" in r.understood[0].label
    intent.clear_cache()
    bad = _reading([{"span": brief, "dataset": "d1", "task": "comparison", "metric": "Срок рассмотрения",
                     "ask": "above", "threshold": {"value": 15, "unit": "%"}}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(bad))
    assert r.understood[0].ask is None and any("порог" in x for x in r.understood[0].dropped)


def test_weighted_mean_takes_the_datas_weight(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    brief = "Какой средний срок рассмотрения по всем регионам?"
    ans = _reading([{"span": brief, "dataset": "d1", "task": "comparison", "metric": "Срок рассмотрения",
                     "ask": "mean", "aggregation": "weighted_mean"}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(ans))
    u = r.understood[0]
    assert (u.ask, u.aggregation, u.weight) == ("mean", "weighted_mean", "Заявлений")


def test_unanswerable_sentence_is_a_visible_note(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    brief = "Где дольше всего ждут решения? Сколько платят сотрудникам?"
    ans = _reading([{"span": "Где дольше всего ждут решения?", "dataset": "d1", "task": "comparison",
                     "metric": "Срок рассмотрения", "ask": "max"}],
                   [{"span": "Сколько платят сотрудникам?", "reason": "в данных нет зарплат сотрудников",
                     "dataset": "d1"}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(ans))
    assert [n.reason for n in r.notes] == ["в данных нет зарплат сотрудников"]
    p = plan_datasets([t], brief, goals=r.goals)[0]
    assert any("сколько платят сотрудникам" in x and "в данных нет зарплат сотрудников" in x
               for x in p.task.reasons), p.task.reasons
    # a reason with a number the brief and the data do not have is not shown
    intent.clear_cache()
    bad = _reading([], [{"span": "Сколько платят сотрудникам?", "reason": "зарплата 120 тыс.", "dataset": "d1"}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(bad))
    assert all("120" not in n.reason for n in r.notes)


def test_story_with_the_model_records_the_goals_and_notes(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    brief = "Где дольше всего ждут решения? Сколько платят сотрудникам?"
    goals_ans = _reading([{"span": "Где дольше всего ждут решения?", "dataset": "d1", "task": "comparison",
                           "metric": "Срок рассмотрения", "ask": "max"}],
                         [{"span": "Сколько платят сотрудникам?", "reason": "в данных нет зарплат сотрудников"}])
    prov = ProviderRegistry.mock({"Return the brief's goals": goals_ans, "*": {"title": ""}})
    st = build_data_story(brief, [t], use_llm=True, skills=skills, providers=prov)
    assert st.goals_read is not None and st.goals_read["source"] == "model"
    assert st.plans[0].task.goal == "где дольше всего ждут решения"
    assert any(r.get("skill") == "GoalReading" for r in st.stats)
    assert any("цель «где дольше всего ждут решения» понята" in x for x in st.log)
    assert "goals" in st.summary()


# ── the cross-check with the rules ───────────────────────────────────────────────────────────────────────────────────
def test_rules_goal_the_model_did_not_cover_stays(skills):
    t = _t("Выручка по месяцам.csv", MONTHS)
    brief = "Итоги года. Покажи рост выручки. Сравни месяцы по заказам."
    ans = _reading([{"span": "Сравни месяцы по заказам.", "dataset": "d1", "task": "dynamics", "metric": "Заказов"}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(ans))
    tasks = [(u.source, u.task, u.quote) for u in r.understood]
    assert ("rules", "dynamics", "Покажи рост выручки") in tasks and ("model", "dynamics", "Сравни месяцы по заказам.") in tasks


def test_model_goal_covering_the_rules_wins_and_a_longer_rules_goal_wins_back(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    # the model quotes the whole sentence: its goal replaces the rules' one (column «Заявлений»)
    ans = _reading([{"span": BRIEF, "dataset": "d1", "task": "comparison", "metric": "Срок рассмотрения"}])
    r = read_goals(BRIEF, [t], skills=skills, providers=_mock(ans))
    assert [(u.source, u.metric) for u in r.understood] == [("model", "Срок рассмотрения")]
    # the model quotes a part and disagrees: the rules' longer quote wins
    intent.clear_cache()
    ans = _reading([{"span": "ждут решения", "dataset": "d1", "task": "comparison", "metric": "Доля онлайн"}])
    r = read_goals(BRIEF, [t], skills=skills, providers=_mock(ans))
    assert [(u.source, u.metric) for u in r.understood] == [("rules", rules_goals(BRIEF, [t]).understood[0].metric)]


def test_model_goal_wins_over_a_tail_that_asks_nothing(skills):
    """«Нужно показать, у кого хуже всего …, чтобы разобрать на планёрке»: правила берут всё предложение, модель — без
    цели действия; её цель накрывает цель правил (хвост ни о чём не спрашивает данные)."""
    t = _t("Госуслуги регионы.csv", REGIONS)
    brief = "Итоги года. Нужно показать, где дольше всего ждут решения, чтобы разобрать на планёрке."
    ans = _reading([{"span": "Нужно показать, где дольше всего ждут решения", "dataset": "d1", "task": "comparison",
                     "metric": "Срок рассмотрения", "ask": "max"}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(ans))
    assert [(u.source, u.metric) for u in r.understood] == [("model", "Срок рассмотрения")]


def test_a_rules_note_the_model_did_not_cover_stays(skills):
    """Модель ответила о первом предложении и промолчала о втором; правила видят, что на второе данные не отвечают, —
    эта пометка не теряется («Почему так»)."""
    t = _t("Госуслуги регионы.csv", REGIONS)
    brief = "Где дольше всего ждут решения? Покажите, как менялся срок рассмотрения по месяцам."
    ans = _reading([{"span": "Где дольше всего ждут решения?", "dataset": "d1", "task": "comparison",
                     "metric": "Срок рассмотрения", "ask": "max"}])
    r = read_goals(brief, [t], skills=skills, providers=_mock(ans))
    kept = [n for n in r.notes if n.source == "rules"]
    assert kept and "срок рассмотрения по месяцам" in kept[0].quote and kept[0].reason == "в данных нет оси времени"
    p = plan_datasets([t], brief, goals=r.goals)[0]
    assert any("в данных нет оси времени" in x for x in p.task.reasons), p.task.reasons


# ── when the model fails, says nothing that holds, or is not needed ─────────────────────────────────────────────────
def test_an_empty_object_is_asked_once_more(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    good = _reading([{"span": BRIEF, "dataset": "d1", "task": "comparison", "metric": "Срок рассмотрения"}])
    calls: list = []

    def answer(messages):
        calls.append(messages)
        return {} if len(calls) == 1 else good

    r = read_goals(BRIEF, [t], skills=skills, providers=ProviderRegistry.mock({"*": answer}))
    assert len(calls) == 2 and "previous answer was empty" in calls[1][-1].content
    assert r.source == "model" and r.understood[0].metric == "Срок рассмотрения"
    # an answer with other keys is no empty object: no second call (the rules then)
    intent.clear_cache()
    calls.clear()
    r = read_goals(BRIEF, [t], skills=skills, providers=_mock({"title": "x"}, calls))
    assert len(calls) == 1 and r.source == "rules"

def test_model_failure_falls_back_to_the_rules(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    r = read_goals(BRIEF, [t], skills=skills, providers=_mock(ProviderError("timeout")))
    assert r.source == "rules" and r.goals is None and "timeout" in (r.error or "")
    intent.clear_cache()
    junk = _reading([{"span": "чего нет в тексте", "dataset": "d1", "task": "comparison"}])
    r = read_goals(BRIEF, [t], skills=skills, providers=_mock(junk))
    assert r.source == "rules" and r.goals is None and r.error


def test_no_goal_in_the_brief_no_call(skills):
    t = _t("Выручка по месяцам.csv", MONTHS)
    calls: list = []
    r = read_goals("Итоги 2025 года для совета директоров.", [t], skills=skills, providers=_mock(_reading(), calls))
    assert not calls and r.source == "rules" and r.skipped


def test_one_call_cached_by_brief_and_tables(skills):
    t = _t("Госуслуги регионы.csv", REGIONS)
    ans = _reading([{"span": BRIEF, "dataset": "d1", "task": "comparison", "metric": "Срок рассмотрения"}])
    calls: list = []
    prov = _mock(ans, calls)
    a = read_goals(BRIEF, [t], skills=skills, providers=prov)
    b = read_goals("  " + BRIEF + " ", [t], skills=skills, providers=prov)
    assert len(calls) == 1 and not a.cached and b.cached and b.understood[0].metric == "Срок рассмотрения"
    t2 = _t("Госуслуги регионы.csv", REGIONS[:-1])  # other rows — another answer
    read_goals(BRIEF, [t2], skills=skills, providers=prov)
    assert len(calls) == 2


def test_one_call_with_every_dataset(skills):
    a = _t("Госуслуги регионы.csv", REGIONS)
    b = _t("Выручка по месяцам.csv", MONTHS)
    brief = "Покажи, как росла выручка, и где дольше всего ждут решения."
    ans = _reading([{"span": "Покажи, как росла выручка", "dataset": "d2", "task": "dynamics", "metric": "Выручка"},
                    {"span": "где дольше всего ждут решения", "dataset": "d1", "task": "comparison",
                     "metric": "Срок рассмотрения", "ask": "max"}])
    ans["goals"].append({"span": brief, "dataset": "d9", "task": "comparison"})  # no such dataset
    calls: list = []
    r = read_goals(brief, [a, b], skills=skills, providers=_mock(ans, calls))
    assert len(calls) == 1 and any("нет датасета" in d["why"] for d in r.dropped)
    user = calls[0][-1].content
    assert "[d1] «Госуслуги регионы.csv»" in user and "[d2] «Выручка по месяцам.csv»" in user
    plans = plan_datasets([a, b], brief, goals=r.goals)
    assert plans[0].task.goal == "где дольше всего ждут решения" and plans[1].task.task == "dynamics"
    assert chart_spec_of(plans[0], a).series[0].name == "Срок рассмотрения"


def test_reading_schema_is_lenient():
    r = GoalReading.model_validate({"goals": [{"span": "x", "dataset": "d1", "task": "comparison", "period": "latest",
                                               "threshold": "15 дней", "compare_to": "plan", "categories": "СБП",
                                               "confidence": "high"}], "unanswerable": None})
    g = r.goals[0]
    assert g.period.kind == "latest" and g.threshold.value == 15 and g.threshold.unit == "дней"
    assert g.compare_to.kind == "plan" and g.categories == ["СБП"] and r.unanswerable == []
    json.dumps(GoalReading.model_json_schema())
