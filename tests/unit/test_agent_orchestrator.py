"""The planning agent (planning/agent.py) with scripted fake models: no network, no real model.

The fake answers each skill by its system prompt (designer / critic / architect; anything else — the analyst's
data_extractor — gets an empty registry) and each designer call by the heading of the slide in its prompt."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from verstka.planning import agent as A
from verstka.planning.brief import parse_brief_text
from verstka.planning.strategies import load_strategies
from verstka.providers.base import ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.agent import CritiqueAnswer, SlideDesignAnswer, StorylineAnswer
from verstka.schemas.brief_structure import BriefStructure, ChartRequest, SlideSpec
from verstka.schemas.common import PatternKind as K
from verstka.skills_registry.registry import SkillsRegistry

BRIEFS = Path(__file__).resolve().parents[1] / "fixtures" / "briefs"
LONG = (BRIEFS / "coffee_long.md").read_text(encoding="utf-8")
SHORT = (BRIEFS / "coffee_short.md").read_text(encoding="utf-8")
STRATEGIES = list(load_strategies().values())
EVENT_KEYS = {"type", "step", "message", "slide", "variant"}

SKILLS = SkillsRegistry.load()


# ------------------------------------------------------------------ the fake model


class Script:
    """Answers per skill; counts the calls; `delay` makes every call take that long (for the concurrency test)."""

    def __init__(self, designs: dict | None = None, critic: dict | None = None, architect=None, revisions: dict | None = None, delay: float = 0.0) -> None:
        self.designs = designs or {}
        self.critic = critic or {}
        self.architect = architect
        self.revisions = revisions or {}
        self.delay = delay
        self.calls: dict[str, int] = {}
        self.prompts: dict[str, list[str]] = {}
        self.lock = threading.Lock()
        self.live = 0
        self.peak = 0

    def _count(self, skill: str, text: str) -> None:
        with self.lock:
            self.calls[skill] = self.calls.get(skill, 0) + 1
            self.prompts.setdefault(skill, []).append(text)

    def __call__(self, messages):
        system, user = messages[0].content, messages[-1].content
        with self.lock:
            self.live += 1
            self.peak = max(self.peak, self.live)
        try:
            if self.delay:
                time.sleep(self.delay)
            if "presentation designer" in system:
                heading = re.search(r"Heading of this slide: «(.+?)»", user).group(1)
                if "A reviewer found problems" in user:
                    self._count("revise", user)
                    return self.revisions.get(heading) or {"kind": "bullets", "headline": heading, "bullets": ["Исправлено"]}
                self._count("designer", user)
                ans = self.designs.get(heading)
                if isinstance(ans, Exception):
                    raise ans
                return ans if ans is not None else {"kind": "bullets", "headline": heading, "bullets": ["Тезис из брифа"]}
            if "strict reviewer" in system:
                self._count("critic", user)
                variant = re.search(r"The plan of the variant «(.+?)»", user).group(1)
                return self.critic.get(variant, {"issues": []})
            if "presentation architect" in system:
                self._count("architect", user)
                if isinstance(self.architect, Exception):
                    raise self.architect
                return self.architect
            self._count("other", user)
            return {"facts": [], "series": [], "tables": []}
        finally:
            with self.lock:
                self.live -= 1


def _registry(script: Script, concurrency: int = 6) -> ProviderRegistry:
    p = MockProvider(script, model="qwen/qwen3.8-27b")
    return ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=concurrency, time_budget_s=210))


def _run(brief_text: str, script: Script | None = None, **kw):
    brief = parse_brief_text(brief_text)
    events: list[dict] = []
    raw: list = []
    if script is None:
        res = A.run_agent(brief, None, STRATEGIES, progress=events.append, raw=raw, **kw)
    else:
        res = A.run_agent(brief, None, STRATEGIES, skills=SKILLS, providers=_registry(script, kw.pop("concurrency", 6)), progress=events.append, raw=raw, **kw)
    return res, events, raw


def _by_spec(o) -> dict:
    return {s.spec_ref: s for s in o.slides if s.spec_ref is not None}


# ------------------------------------------------------------------ answers read leniently, never an empty answer


def test_the_designers_answer_is_read_leniently():
    ans = SlideDesignAnswer.model_validate({
        "kind": "pie", "headline": "Две трети расходов — продукты и зарплаты",
        "content": {"chart": {"data": [{"label": "Продукты", "value": "315 000"}, {"label": "Зарплаты", "value": 270000}], "unit": "₽"}},
        "alternatives": ["table", {"form": "stat_row", "change": "крупно"}],
    })
    assert ans.kind == "chart" and ans.chart.type == "pie"
    assert ans.chart.categories == ["Продукты", "Зарплаты"] and ans.chart.series[0].values == [315000.0, 270000.0]
    assert [a.kind for a in ans.alternatives] == ["table", "stat_row"] and ans.alternatives[1].why == "крупно"
    # a chart given by the ids of the data list is kept as ids (the agent copies the data in)
    by_ids = SlideDesignAnswer.model_validate({"kind": "chart", "headline": "Выручка", "chart": {"type": "line", "series": ["s7"]}})
    assert by_ids.chart.series_ids == ["s7"] and by_ids.chart.series == []


def test_an_answer_that_is_not_one_fails_instead_of_passing_empty():
    """The inner object of an answer cut at max_tokens (what extract_json picks) must not validate as an empty
    slide, storyline or critique — the root cause of the silent empty FactsExtraction."""
    with pytest.raises(ValidationError):
        SlideDesignAnswer.model_validate({"name": "Расходы", "values": [1, 2]})
    with pytest.raises(ValidationError):
        StorylineAnswer.model_validate({"facts": [], "series": [], "tables": []})
    with pytest.raises(ValidationError):
        CritiqueAnswer.model_validate({"facts": []})
    story = StorylineAnswer.model_validate({"deck": {"title": "T", "slides": [{"headline": "A", "sentences": ["2-4", "#7"], "data": "s1"}]}})
    assert story.slides[0].sentences == [2, 3, 4, 7] and story.slides[0].data == ["s1"]
    crit = CritiqueAnswer.model_validate([{"slide_id": "s3", "issue": "Тема вместо вывода", "fix": "Сформулировать вывод"}])
    assert crit.issues[0].slide == 3 and crit.issues[0].problem == "Тема вместо вывода"


def test_the_json_schema_shown_to_the_model_is_compact():
    for cls in (SlideDesignAnswer, StorylineAnswer, CritiqueAnswer):
        assert len(json.dumps(cls.model_json_schema(), ensure_ascii=False)) < 2500


# ------------------------------------------------------------------ no model: the deterministic designer


def test_without_a_model_the_short_coffee_brief_gets_every_requested_chart():
    """The user's five-slide brief asked for 7 charts: a pie, a pie, two columns, a line and a pie, a column. The
    rules build every one from the brief's data — none is dropped as «chart without data»."""
    res, events, _ = _run(SHORT)
    assert set(res.outlines) == {"structured", "visual", "compact"}
    for name, o in res.outlines.items():
        assert o.planned_by == "rules", name
        spec = _by_spec(o)
        assert sorted(spec) == [1, 2, 3, 4, 5], name
        types = {n: [ch.type for ch in (s.content.chart, s.content.chart2) if ch is not None] for n, s in spec.items()}
        assert types == {1: ["pie"], 2: ["pie"], 3: ["column", "column"], 4: ["line", "pie"], 5: ["column"]}, (name, types)
        for s in spec.values():
            for ch in (s.content.chart, s.content.chart2):
                if ch is not None:
                    assert ch.series_ids and all(o.series_by_id(i) is not None for i in ch.series_ids), (name, s.headline)
        assert spec[2].footnote and "не включены" in spec[2].footnote
        assert o.slides[0].kind == K.title and o.slides[0].footnote  # «Все цифры условные» small on the cover
    assert all(EVENT_KEYS <= set(e) and e["type"] == "agent" for e in events)
    assert sum(e["step"] == "designer" for e in events) == 6  # the cover and the five slides


def test_without_a_model_the_long_coffee_brief_keeps_the_users_slides_and_requests():
    res, _, _ = _run(LONG)
    o = res.outlines["structured"]
    spec = _by_spec(o)
    assert sorted(spec) == list(range(1, 11)) and len(o.slides) == 10
    assert o.title == "Больше прибыли с каждой чашки" and spec[1].kind == K.title
    assert spec[2].content.formula and "900 000" in spec[2].content.formula
    assert spec[3].content.chart is not None and spec[3].content.chart.type == "pie" and len(spec[3].content.chart.categories) == 6
    assert spec[9].kind == K.table and spec[9].content.table is not None and spec[9].takeaway.startswith("Выручка увеличивается")
    assert spec[8].kind == K.timeline and len(spec[8].content.items) == 6
    assert spec[10].takeaway.startswith("Рост прибыли зависит")
    # the three directions the user asked to single out are on slide 4, not buried in the notes
    assert [it.title for it in spec[4].content.items] == ["Увеличение среднего чека", "Привлечение гостей в свободные часы", "Снижение потерь"]
    # a time («с 15:00») is never a figure
    assert not any(n.value.startswith("15") and ":" in (n.label or "") for s in o.slides for n in s.content.numbers)


# ------------------------------------------------------------------ with a model: design, enforce, critic, revise


def _long_script() -> Script:
    return Script(
        designs={
            "Как работает кофейня сейчас": {
                "kind": "stat_row", "headline": "Сейчас кофейня зарабатывает 900 000 рублей в месяц",
                "numbers": [{"value": "100", "label": "покупок в день"}, {"value": "300 ₽", "label": "средний чек"}, {"value": "900 000 ₽", "label": "выручка в месяц"}],
                "takeaway": "Выручка держится на 100 покупках в день", "notes": "100 покупок по 300 рублей 30 дней дают 900 000 рублей.",
                "rationale": "Три ключевых числа крупно.", "alternatives": [{"kind": "table", "why": "те же числа таблицей"}, {"kind": "bullets", "why": "короче"}],
            },
            # the user asked for a pie: the model's column chart becomes one
            "Куда уходят деньги": {
                "kind": "chart", "headline": "Продукты и зарплаты — главные статьи расходов",
                "chart": {"type": "column", "unit": "₽", "categories": ["Продукты, упаковка и списания", "Зарплаты и связанные начисления", "Аренда", "Коммунальные услуги", "Маркетинг", "Другие операционные расходы"],
                          "series": [{"name": "Расходы", "values": [315000, 270000, 120000, 25000, 20000, 30000]}]},
                "takeaway": "Две статьи — три четверти расходов", "rationale": "Структура расходов.",
                "alternatives": [{"kind": "table", "why": "точные суммы"}, {"kind": "bullets", "why": "короче"}],
            },
            # a figure the brief does not have (345) on a chart nobody asked for: the chart goes
            "Как увеличить средний чек": {
                "kind": "chart", "headline": "Допродажи поднимут средний чек",
                "chart": {"type": "column", "categories": ["Сейчас", "Цель"], "series": [{"name": "Средний чек", "values": [300, 345]}]},
                "bullets": ["Комбо «капучино + круассан»", "Добавки к напиткам", "Десерты у кассы"],
                "alternatives": [{"kind": "cards"}, {"kind": "bullets"}],
            },
            "Как привлечь больше гостей": {"kind": "cards", "headline": "Новые гости придут днём и из офисов", "items": [{"title": "Партнёрства с офисами"}, {"title": "Программа лояльности"}, {"title": "Дневные предложения"}], "alternatives": [{"kind": "bullets"}, {"kind": "process"}]},
            "Как сократить потери": {"kind": "cards", "headline": "Учёт и закупки сократят потери", "items": [{"title": "Учёт остатков"}, {"title": "Закупки по спросу"}, {"title": "Контроль порций"}], "alternatives": [{"kind": "bullets", "why": "короче"}, {"kind": "process"}]},
            # the model forgot the table the user asked for: it is added from the brief
            "Финансовый результат к шестому месяцу": {"kind": "bullets", "headline": "Прибыль вырастет вдвое", "bullets": ["Выручка растёт", "Прибыль растёт"]},
        },
        critic={"Визуальный": {"issues": [{"slide": 5, "problem": "На слайде список вместо цифр", "fix": "Показать средний чек крупно"}]}},
        revisions={"Как увеличить средний чек": {"kind": "big_number", "headline": "Средний чек вырастет на 10%", "numbers": [{"value": "300 → 330 ₽", "label": "средний чек"}], "takeaway": "Комбо и добавки дают рост чека"}},
    )


def test_the_agent_designs_every_slide_and_honours_the_users_requests():
    script = _long_script()
    res, events, raw = _run(LONG, script, coverage=False)
    assert res is not None and res.by_model and res.model_slides == 9  # the cover needs no model
    assert script.calls["designer"] == 9 and script.calls["critic"] == 3 and script.calls["revise"] == 1
    o = res.outlines["structured"]
    assert o.planned_by == "agent"
    spec = _by_spec(o)
    assert sorted(spec) == list(range(1, 11))
    assert spec[2].content.formula and spec[2].takeaway == "Выручка держится на 100 покупках в день"
    pie = spec[3].content.chart
    assert spec[3].kind == K.chart and pie.type == "pie" and pie.series_ids and o.series_by_id(pie.series_ids[0]).values[0] == 315000
    assert spec[3].footnote and "не учитываются" in spec[3].footnote
    assert spec[5].content.chart is None  # 345 is not in the brief
    assert any("values not in the brief" in w for w in res.warnings["structured"])
    assert spec[9].kind == K.table and spec[9].content.table is not None
    assert spec[9].takeaway.startswith("Выручка увеличивается")  # the user's own conclusion wins
    assert spec[2].rationale == "Три ключевых числа крупно."
    assert any(a.kind == "table" for a in spec[2].alternatives)
    # the model answers are kept as written, per step
    assert {e["step"] for e in raw} >= {"designer", "critic", "revise"}


def test_the_critic_flags_one_variant_and_only_its_slide_is_revised_once():
    script = _long_script()
    res, events, _ = _run(LONG, script, coverage=False)
    visual, structured = _by_spec(res.outlines["visual"]), _by_spec(res.outlines["structured"])
    assert visual[5].headline == "Средний чек вырастет на 10%"
    assert structured[5].headline != visual[5].headline
    assert res.critic_issues == {"structured": 0, "visual": 1, "compact": 0}
    revise_prompt = script.prompts["revise"][0]
    assert "Показать средний чек крупно" in revise_prompt and '"headline"' in revise_prompt
    crit = [e for e in events if e["step"] == "critic"]
    assert {e["variant"] for e in crit} == {"structured", "visual", "compact"}
    # the notes and the revision carry the slide's number in the variant (the result screen's «Почему слайд N»)
    assert any(e["step"] == "critic" and e["slide"] == 5 and e["variant"] == "visual" for e in events)
    assert any(e["step"] == "revise" and e["slide"] == 5 and e["variant"] == "visual" for e in events)
    assert not any(e["step"] == "revise" and e["variant"] != "visual" for e in events)
    assert not any(e["message"].startswith(("Критик", "Правка", "Дизайнер", "Аналитик")) for e in events)  # the UI names the step
    log_v, log_s = res.outlines["visual"].agent_log, res.outlines["structured"].agent_log
    assert any(m.startswith("Критик: 1 замечание") for m in log_v) and "Критик: замечаний нет." in log_s
    assert any(m.startswith("Аналитик:") for m in log_s) and any(m.startswith("Дизайнер: слайд 3") for m in log_s)


def test_events_follow_the_contract_in_plain_russian():
    res, events, _ = _run(LONG, _long_script())
    assert events and all(set(e) == EVENT_KEYS and e["type"] == "agent" for e in events)
    steps = [e["step"] for e in events]
    assert steps.index("analyst") < steps.index("designer") < steps.index("critic") < steps.index("revise") < steps.index("compile")
    designer = [e for e in events if e["step"] == "designer"]
    assert sorted(e["slide"] for e in designer) == list(range(1, 11))
    assert all(re.search(r"[а-яё]", e["message"], re.I) for e in events)
    assert not any(re.search(r"\b(?:series|spec|json|kind|stat_row|big_number)\b", e["message"]) for e in events)


def test_a_designer_failure_falls_back_to_the_rules_for_that_slide_only():
    script = _long_script()
    script.designs["Куда уходят деньги"] = ProviderError("qwen/qwen3.8-27b: congested upstream")
    res, events, _ = _run(LONG, script)
    spec = _by_spec(res.outlines["structured"])
    assert spec[3].content.chart is not None and spec[3].content.chart.type == "pie"  # the rules drew the requested pie
    assert res.outlines["structured"].planned_by == "agent" and res.model_slides == 8
    assert any("собран по правилам (модель не ответила)" in e["message"] for e in events if e["slide"] == 3)
    assert any("slide_designer failed on slide u3" in w for w in res.warnings["structured"])


def test_near_the_deadline_no_model_is_asked_and_the_critic_is_skipped():
    script = _long_script()
    res, events, _ = _run(LONG, script, deadline=time.monotonic() + 5)
    assert "designer" not in script.calls and "critic" not in script.calls
    assert res.outlines["structured"].planned_by == "rules"
    assert any(e["step"] == "critic" and "пропущен" in e["message"] for e in events)
    spec = _by_spec(res.outlines["visual"])
    assert spec[3].content.chart is not None and spec[9].content.table is not None


def test_designer_calls_run_in_parallel_within_the_providers_concurrency():
    script = _long_script()
    script.delay = 0.15
    res, _, _ = _run(LONG, script, concurrency=3, critic=False)
    # side by side, within the providers' concurrency (the peak, not the wall clock: a busy machine stretches time)
    assert 2 <= script.peak <= 3
    assert "critic" not in script.calls


# ------------------------------------------------------------------ a brief without slide specs: the architect


PLAIN = """Итоги пилота «Умные сводки» за квартал.

Сотрудники тратили 47 минут в день на чтение рабочих чатов. Сводки сократили это время до 29 минут.
В пилоте участвовали 1200 сотрудников из 12 команд.
Просим утвердить запуск на всю компанию в ноябре."""


def test_a_brief_without_slide_specs_gets_a_storyline_from_the_architect():
    script = Script(
        architect={"title": "Итоги пилота «Умные сводки»", "slides": [
            {"title": "Время на чаты сократилось", "section": "Результаты", "sentences": [2, 3], "form": "big_number"},
            {"title": "Кто участвовал", "section": "Результаты", "sentences": [4]},
            {"title": "Просим утвердить запуск", "section": "Решение", "sentences": [5]},
        ]},
        designs={"Время на чаты сократилось": {"kind": "big_number", "headline": "Сводки экономят сотрудникам 18 минут в день", "numbers": [{"value": "47 → 29 минут", "label": "чтение чатов в день"}]}},
    )
    res, events, _ = _run(PLAIN, script)
    o = res.outlines["structured"]
    assert o.planned_by == "agent" and script.calls["architect"] == 1 and script.calls["designer"] == 3
    assert o.slides[0].kind == K.title and o.slides[-1].kind == K.thanks
    assert [s.kind for s in o.slides[1:-1]][0] == K.big_number
    prompt = script.prompts["architect"][0]
    assert "[2] Сотрудники тратили 47 минут" in prompt
    assert any(e["step"] == "architect" and "сюжет из 3 слайдов" in e["message"].lower() for e in events)


def test_without_a_storyline_the_agent_hands_the_deck_to_the_planner():
    res, events, _ = _run(PLAIN, Script(architect=ProviderError("all model links failed: congested")))
    assert res.outlines == {} and any(e["step"] == "architect" for e in events)
    assert all(any(w.startswith("deck_architect failed") for w in ws) for ws in res.warnings.values())
    res2, _, _ = _run(PLAIN)  # no model at all
    assert res2.outlines == {} and any("deck_architect skipped: no model" in w for w in res2.warnings["structured"])


# ------------------------------------------------------------------ variants from the shared designs


def _unit(key: str, **kw) -> A._Unit:
    return A._Unit(key=key, title=kw.pop("title", key), **kw)


def _design(key: str, kind: str, alts=(), section=None, spec=None, **content) -> A._Design:
    from verstka.schemas.outline import OutlineSlide, SlideContent

    s = OutlineSlide(id=key, kind=K(kind), headline=f"Вывод {key}", section=section, content=SlideContent(**content))
    return A._Design(unit=_unit(key, section=section, spec=spec), slide=s, alternatives=[A.Alternative(kind=k) for k in alts], by="model")


def _ctx(**kw) -> A._Ctx:
    from verstka.planning.facts import basic_facts

    return A._build_ctx(parse_brief_text("Бриф"), BriefStructure(**kw), basic_facts(""), None)


def test_variants_take_the_forms_they_prefer_and_keep_the_requested_ones():
    from verstka.schemas.outline import ChartSpec, InlineSeries, NumberCallout

    chart = ChartSpec(type="pie", categories=["А", "Б"], series=[InlineSeries(name="x", values=[1, 2])])
    spec = SlideSpec(number=2, title="Структура", charts=[ChartRequest(type="pie", what="структура")])
    designs = [
        _design("u1", "bullets", alts=("cards", "table"), bullets=["Первый: пояснение", "Второй: пояснение", "Третий: пояснение"]),
        _design("u2", "chart", alts=("table", "stat_row"), spec=spec, chart=chart),
        _design("u3", "stat_row", alts=("chart", "table"), numbers=[NumberCallout(value="10 ₽", label="цена"), NumberCallout(value="20 ₽", label="доход")]),
    ]
    ctx = _ctx()
    prefs = A.designer_prefs()
    st = {s.name: s for s in STRATEGIES}
    visual, _ = A.assemble(designs, st["visual"], prefs, ctx)
    structured, _ = A.assemble(designs, st["structured"], prefs, ctx)
    compact, _ = A.assemble(designs, st["compact"], prefs, ctx)
    assert [p.slide.kind for p in structured] == [K.bullets, K.chart, K.stat_row]
    assert visual[0].slide.kind == K.cards and visual[0].slide.content.items[0].title == "Первый"
    assert all(v[1].slide.kind == K.chart and v[1].slide.content.chart.type == "pie" for v in (visual, compact))  # asked for: kept


def test_compact_merges_thin_neighbours_when_the_count_is_free_and_variety_breaks_runs():
    from verstka.schemas.outline import NumberCallout

    designs = [
        _design("u1", "bullets", section="Итоги", bullets=["Один тезис"]),
        _design("u2", "bullets", section="Итоги", bullets=["Другой тезис"]),
        _design("u3", "big_number", section="Итоги", numbers=[NumberCallout(value="5", label="команд")]),
        _design("u4", "big_number", section="Итоги", numbers=[NumberCallout(value="7", label="недель")]),
        _design("u5", "cards", alts=("bullets",), section="План", items=[{"title": "Шаг А"}, {"title": "Шаг Б"}]),
        _design("u6", "cards", alts=("bullets",), section="План", items=[{"title": "Шаг В"}, {"title": "Шаг Г"}]),
    ]
    st = {s.name: s for s in STRATEGIES}
    compact, notes = A.assemble(designs, st["compact"], A.designer_prefs(), _ctx())
    kinds = [p.slide.kind for p in compact]
    # merged down to the compact share of the deck (slide_ratio 0.7 of 6 → 5), not below it
    assert kinds[0] == K.two_column and compact[0].units == ["u1", "u2"] and len(compact) == 5
    assert [b.title for b in compact[0].slide.content.columns] == ["Вывод u1", "Вывод u2"]
    structured, notes = A.assemble(designs, st["structured"], A.designer_prefs(), _ctx())
    kinds = [p.slide.kind for p in structured]
    assert kinds[4] == K.cards and kinds[5] == K.bullets  # two card slides in a row: the second takes its alternative
    assert any(n.startswith("variety:") for n in notes)
    # with a slide count fixed by the user nothing is merged
    fixed, _ = A.assemble(designs, st["compact"], A.designer_prefs(), _ctx(slide_count=8))
    assert len(fixed) == len(designs)


def test_reshape_never_loses_the_slides_text_for_a_figure_form():
    from verstka.schemas.outline import NumberCallout, OutlineSlide, SlideContent

    s = OutlineSlide(id="x", kind=K.cards, headline="h", content=SlideContent(items=[{"title": "А"}, {"title": "Б"}], numbers=[NumberCallout(value="1", label="a"), NumberCallout(value="2", label="b")]))
    assert A.reshape(s, "stat_row") is None and A.reshape(s, "chart") is None
    b = A.reshape(s, "bullets")
    # a list shows the figures as its lines, never a row of figures under another kind's name
    assert b is not None and b.content.bullets == ["a: 1", "b: 2", "А", "Б"] and not b.content.numbers
    figs = OutlineSlide(id="y", kind=K.stat_row, headline="h", content=SlideContent(numbers=[NumberCallout(value="315 000 ₽", label="продукты"), NumberCallout(value="270 000 ₽", label="зарплаты")]))
    # a row of figures is not the parts of one whole: never a pie (its «shares» would be made up), columns
    assert A.reshape(figs, "chart", "pie") is None
    ch = A.reshape(figs, "chart")
    assert ch is not None and ch.content.chart.type == "column" and ch.content.chart.series[0].values == [315000.0, 270000.0] and ch.content.chart.unit == "₽"
    assert A.reshape(figs, "table").content.table.rows == [["продукты", "315 000 ₽"], ["зарплаты", "270 000 ₽"]]


def test_chart_values_must_be_the_briefs_rounded_or_scaled():
    allowed = [254795.0, 13.3, 1138500.0]
    assert A.value_ok(255000, allowed) and A.value_ok(254.795, allowed) and A.value_ok(1138.5, allowed) and A.value_ok(13.3, allowed)
    assert not A.value_ok(345, allowed) and not A.value_ok(260000, allowed)


# ------------------------------------------------------------------ the pipeline


def test_generate_variants_plans_with_the_agent_and_records_it(simple_deck, tmp_path):
    from verstka.pipeline.generate import generate_variants

    script = Script(designs={"Как работает кофейня сейчас": {"kind": "chart", "headline": "Кофе даёт 60% выручки", "chart": {"type": "pie", "categories": ["Кофе", "Десерты и выпечка", "Чай и другие напитки"], "series": [{"name": "Выручка", "values": [540000, 225000, 135000]}]}}})
    got: list[dict] = []

    def progress(msg, frac=None, event=None):
        if event is not None:
            assert event["message"] == msg and isinstance(frac, float)
            got.append(event)

    res = generate_variants(
        simple_deck, brief=parse_brief_text(SHORT), out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", providers=_registry(script), skills=SKILLS,
        use_vlm=False, audit=False, autofix=False, exports=[], render_images=False, progress=progress,
    )
    assert [v.strategy for v in res.variants] == ["structured", "visual", "compact"]
    for v in res.variants:
        assert v.outline.planned_by == "agent" and v.planner["planned_by"] == "agent" and v.planner["model"] == "qwen/qwen3.8-27b"
        assert v.planner["agent"]["slides_by_model"] == 5 and v.planner["agent"]["version"] == A.AGENT_VERSION
        rm = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
        assert rm["planner"]["planned_by"] == "agent"
        raw = json.loads((v.out_dir / "planner_raw.json").read_text(encoding="utf-8"))
        assert any(a["step"] == "designer" for a in raw["answers"])
        saved = json.loads((v.out_dir / "outline.json").read_text(encoding="utf-8"))
        assert saved["agent_log"] and saved["agent_log"][0].startswith("Аналитик")
        charts = [ch for s in v.outline.slides for ch in (s.content.chart, s.content.chart2) if ch is not None]
        assert len(charts) >= 7
    assert "other" not in script.calls or script.calls["other"] <= 5  # no whole-brief data_extractor next to the analyst's
    assert got and {e["step"] for e in got} >= {"analyst", "designer", "critic", "compile"}
    assert all(set(e) >= EVENT_KEYS and e["type"] == "agent" for e in got)


def test_the_api_job_gets_the_agents_events():
    """The API's progress adapter (api.agent_view.job_progress) takes the agent's events as `event=`: the job's
    events carry the step, slide and variant the build screen draws its timeline from."""
    from verstka.pipeline.generate import _event_sink

    try:
        from verstka.api.agent_view import job_progress
    except ImportError:  # the UI area is not there: nothing to connect
        pytest.skip("api.agent_view not available")

    class Job:
        def __init__(self):
            self.events = []

        def emit(self, message, progress=None, **extra):
            self.events.append({"message": message, "progress": progress, **extra})

        def agent_events(self):
            return [e for e in self.events if e.get("type") == "agent"]

    job = Job()
    sink = _event_sink(job_progress(job))
    sink({"type": "agent", "step": "designer", "message": "Дизайнер: слайд 3 — круговая диаграмма.", "slide": 3, "variant": None})
    assert job.events and job.events[-1]["step"] == "designer" and job.events[-1]["slide"] == 3 and job.events[-1]["type"] == "agent"
    plain = []
    _event_sink(lambda msg, frac: plain.append((msg, frac)))({"type": "agent", "step": "critic", "message": "Критик: замечаний нет.", "slide": None, "variant": "visual"})
    assert plain == [("Критик: замечаний нет.", 0.33)]


def test_generate_variants_falls_back_to_the_planner_when_the_agent_cannot_plan(simple_deck, tmp_path):
    """A brief without slide specs whose storyline the model does not give: the planner plans the deck as before."""
    from verstka.pipeline.generate import generate_variants

    res = generate_variants(
        simple_deck, brief=parse_brief_text(PLAIN), strategies=["structured"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws",
        providers=_registry(Script(architect=ProviderError("congested"))), skills=SKILLS, use_vlm=False, audit=False, autofix=False, exports=[], render_images=False,
    )
    v = res.variants[0]
    assert v.outline.planned_by in ("rules", "model") and "agent" not in v.planner
    assert len(v.outline.slides) >= 3
    assert any(w.startswith("deck_architect failed") for w in v.warnings)


# ------------------------------------------------------------------ live-run findings (Cloud.ru Qwen3-32B, 2026-09-25)


def _placed(*slides) -> list:
    return [A._Placed(slide=s, units=[s.id]) for s in slides]


def _slide(key: str, kind: str, headline: str, takeaway=None, **content):
    from verstka.schemas.outline import OutlineSlide, SlideContent

    return OutlineSlide(id=key, kind=K(kind), headline=headline, takeaway=takeaway, content=SlideContent(**content))


def test_the_agent_checks_the_critics_claims_before_a_slide_is_redone():
    from verstka.planning.facts import basic_facts
    from verstka.schemas.outline import SlideItem, TableData

    brief = parse_brief_text("Средний чек вырастет с 300 до 330 рублей. Списания — 27 000 рублей в месяц.")
    ctx = A._build_ctx(brief, BriefStructure(), basic_facts(brief.text), None)
    table = TableData(columns=["Показатель", "Сейчас", "Цель"], rows=[["Средний чек", "300", "330"]])
    placed = _placed(
        _slide("u1", "table", "Средний чек вырастет до 330 рублей", takeaway="Комбо и допродажи поднимут чек", table=table),
        _slide("u2", "cards", "Как сократить потери", items=[SlideItem(title="Учёт", text="ежедневно"), SlideItem(title="Закупки", text="по дням")]),
        _slide("u3", "bullets", "Три меры снизят списания", bullets=["Учёт остатков", "Закупки по дням"]),
    )
    titles = {"u1": "Как увеличить средний чек", "u2": "Как сократить потери", "u3": "Как сократить потери"}
    fa = lambda text, pos: A._false_alarm(text, pos, placed, ctx, titles)  # noqa: E731
    # the reviewer misread the brief: 300 and 27 000 are the brief's figures
    assert fa("Таблица содержит число 300, которого нет в брифе.", 1)
    assert fa("Слайд содержит число 27 000, которое не указано в брифе.", 2)
    assert fa("Слайд содержит число 45 000, которого нет в брифе.", 1) is None
    # «two neighbours of one form»: slides 2 and 3 are cards and a list
    assert fa("Два соседних слайда в одном формате (слайды 2 и 3).", 3)
    # a takeaway «repeating» the headline: the note stands (the agent acts on it itself, without a model); a light
    # slide «overloaded»
    assert fa("Вывод повторяет заголовок.", 1) is None and A.takeaway_note("Вывод повторяет заголовок.")
    assert fa("Слайд перегружен текстом.", 3)
    assert fa("Слайд содержит 4 пункта, что превышает рекомендуемое количество (до 3). → Сократить до 3 ключевых действий.", 2)
    # a «topic» headline: the conclusion stands, the user's heading copied is a real topic
    assert fa("Заголовок не формулирует вывод, а называет тему.", 1)
    assert fa("Заголовок не формулирует вывод, а называет тему.", 2) is None
    # what the agent cannot check stays
    assert fa("На слайде нет списка мер из брифа.", 2) is None
    # notes on meaning are never dropped: a figure with a meaning its source does not give, a claim with no figure
    assert fa("Утверждение, что 31% срывов связано с упущенными напоминаниями, не указано в брифе.", 1) is None
    assert fa("Вывод «Функция повышает прозрачность задач» отсутствует в брифе.", 1) is None
    assert fa("Строка «Рост начался с июня» придумана.", 1) is None
    # a vague headline is a «topic» note, not a «repeat» one: it stands on a list announced as the headline
    vague = _placed(_slide("u9", "two_column", "Три ключевых фактора роста прибыли", takeaway="Рост прибыли зависит от трех изменений"))
    assert A._false_alarm("Заголовок не отражает ключевой вывод слайда, а повторяет общий контекст", 1, vague, ctx, {"u9": "Что контролировать"}) is None
    assert not A.takeaway_note("Заголовок не отражает ключевой вывод слайда, а повторяет общий контекст")
    assert A._false_alarm("Заголовок слишком общий, не содержит вывода", 1, vague, ctx, {"u9": "Что контролировать"}) is None


def test_a_takeaway_repeating_the_headline_and_an_unasked_footnote_are_dropped():
    from verstka.planning.facts import basic_facts

    unit = _unit("u5", title="Как увеличить средний чек", text="Цель — поднять средний чек с 300 до 330 рублей, выручка вырастет на 90 000 рублей. Налоги в расчёт не включены.")
    brief = parse_brief_text(unit.text)
    ctx = A._build_ctx(brief, BriefStructure(), basic_facts(brief.text), None)
    ans = SlideDesignAnswer.model_validate({
        "kind": "bullets", "headline": "Средний чек вырастет с 300 до 330 рублей", "bullets": ["Комбо", "Добавки"],
        "takeaway": "Средний чек вырастет с 300 до 330 рублей", "footnote": "Результаты зависят от выполнения действий",
    })
    d = A.design_from_answer(ans, unit, ctx)
    assert d.slide.takeaway is None and d.slide.footnote is None
    ans2 = ans.model_copy(update={"takeaway": "Выручка вырастет на 90 000 рублей", "footnote": "Налоги в расчёт не включены"})
    d2 = A.design_from_answer(ans2, unit, ctx)
    assert d2.slide.takeaway == "Выручка вырастет на 90 000 рублей" and d2.slide.footnote == "Налоги в расчёт не включены"


def test_a_requested_chart_never_takes_a_chart_that_mixes_in_another_measure():
    from verstka.schemas.outline import ChartSpec, InlineSeries, Series

    spec = SlideSpec(number=3, title="Как увеличить продажи", text="…", charts=[
        ChartRequest(type="column", what="количество покупок в день до и после", series_ids=["s4"]),
        ChartRequest(type="column", what="средний чек до и после", series_ids=["s5"]),
    ])
    st = BriefStructure(specs=[spec], series=[
        Series(id="s4", name="Покупок в день", categories=["Сейчас", "Цель"], values=[100, 115]),
        Series(id="s5", name="Средний чек", categories=["Сейчас", "Цель"], values=[300, 330], unit="₽"),
    ])
    ctx = A._build_ctx(parse_brief_text("Бриф"), st, __import__("verstka.planning.facts", fromlist=["basic_facts"]).basic_facts(""), None)
    mixed = ChartSpec(type="column", categories=["Покупки", "Средний чек"], series=[InlineSeries(name="Сейчас", values=[100, 300]), InlineSeries(name="Цель", values=[115, 330])])
    check = ChartSpec(type="column", categories=["Сейчас", "Цель"], series=[InlineSeries(name="Средний чек", values=[300, 330])])
    d = _design("u3", "chart", spec=spec, chart=mixed, chart2=check)
    d.unit.series_ids = ["s4", "s5"]
    A.enforce_requests(d, ctx)
    c = d.slide.content
    assert [s.values for s in c.chart.series] == [[100, 115]] and [s.values for s in c.chart2.series] == [[300, 330]]


def test_a_pie_of_the_amounts_answers_a_pie_of_the_percentages():
    from verstka.schemas.outline import ChartSpec, InlineSeries, Series

    spec = SlideSpec(number=1, title="Выручка", text="…", charts=[ChartRequest(type="pie", what="структура выручки", series_ids=["s2"])])
    st = BriefStructure(specs=[spec], series=[Series(id="s2", name="Структура выручки", categories=["Кофе", "Десерты", "Чай"], values=[60, 25, 15], unit="%")])
    ctx = A._build_ctx(parse_brief_text("Бриф"), st, __import__("verstka.planning.facts", fromlist=["basic_facts"]).basic_facts(""), None)
    pie = ChartSpec(type="pie", unit="₽", categories=["Кофе", "Десерты", "Чай"], series=[InlineSeries(name="Выручка", values=[540000, 225000, 135000])])
    d = _design("u1", "chart", spec=spec, chart=pie)
    d.unit.series_ids = ["s2"]
    A.enforce_requests(d, ctx)
    assert d.slide.content.chart is pie and d.slide.content.chart2 is None


def test_the_visual_variant_shows_a_list_of_figures_as_a_row_of_figures():
    pilot = ["Доля завершённых в срок задач выросла на 34%", "Экономия — 2,1 часа в неделю на человека", "Средняя оценка удобства: 4,6 из 5", "91% участников готовы рекомендовать функцию"]
    r = A.reshape(_slide("u4", "bullets", "Пилот удался", bullets=pilot), "stat_row")
    assert r is not None and r.kind == K.stat_row and [n.value for n in r.content.numbers] == ["+34%", "2,1 ч", "4,6 из 5", "91%"] and not r.content.bullets
    # a list of actions with one figure keeps its form: its lines would not fit under the figures
    actions = ["Партнёрства с пятью офисами", "Программа лояльности", "Продвижение в районе", "Дневные предложения", "Бюджет вырастет до 35 000 ₽"]
    assert A.reshape(_slide("u6", "bullets", "Больше гостей", bullets=actions), "stat_row") is None
    d = _design("u4", "bullets", alts=("chart",), bullets=pilot)
    placed, _ = A.assemble([d], next(s for s in STRATEGIES if s.name == "visual"), A.designer_prefs(), _ctx())
    assert placed[0].slide.kind == K.stat_row
    placed, _ = A.assemble([d], next(s for s in STRATEGIES if s.name == "structured"), A.designer_prefs(), _ctx())
    assert placed[0].slide.kind == K.bullets


def test_a_headline_loses_only_the_figure_the_brief_does_not_give():
    from verstka.planning.facts import basic_facts

    text = (BRIEFS.parent.parent.parent / "examples" / "briefs" / "vk_workspace_feature.md").read_text(encoding="utf-8")
    brief = parse_brief_text(text)
    ctx = A._build_ctx(brief, BriefStructure(), basic_facts(brief.text), None)
    unit = _unit("u5", title="Динамика активных пользователей")
    changes: list[str] = []
    assert A._headline_checked("Активные пользователи выросли в 10 раз за 5 месяцев", unit, ctx, changes) == "Активные пользователи выросли в 10 раз"
    assert changes
    assert A._headline_checked("Пилот охватил 12 400 сотрудников", unit, ctx, []) == "Пилот охватил 12 400 сотрудников"
    assert A._headline_checked("Выручка 7 млн", unit, ctx, []) == "Динамика активных пользователей"


def test_a_list_the_slide_left_out_is_sent_back_to_the_designer_for_every_variant():
    """The fake designer shows «Как привлечь больше гостей» as three cards of actions and «Что контролировать…»
    without its risks: the agent's own check (no model) flags both lists and the designer redoes those slides once."""
    script = _long_script()
    res, events, raw = _run(LONG, script)
    gaps = [e for e in events if e["step"] == "critic" and e["variant"] is None and e["slide"]]  # the agent's own notes
    assert gaps and all(e["variant"] is None and e["slide"] for e in gaps)
    assert any("«Основные риски»" in e["message"] for e in gaps)
    assert all(not e["message"].startswith("Критик") for e in gaps)
    flagged = {e["slide"] for e in gaps}
    # the critic's slide 5 (visual) and the lists, one call each — one wave of revisions at most (the concurrency, 6)
    assert script.calls["revise"] == min(len(flagged | {5}), 6)
    revise_prompts = "\n".join(script.prompts["revise"])
    assert "Покажи этот список на слайде" in revise_prompts
    # every variant takes the revised slides of the lists
    for name in ("structured", "visual", "compact"):
        assert any(m.startswith("Правка: слайд") for m in res.outlines[name].agent_log)
    assert any(m.startswith("Критик: слайд") and "нет списка" in m for m in res.outlines["structured"].agent_log)


def test_coverage_counts_a_list_shown_in_other_words_or_by_its_figures():
    from verstka.schemas.outline import OutlineSlide, SlideContent, SlideItem

    text = "Меры:\n— ежедневный учет остатков;\n— закупки по дням недели с учетом спроса;\n— контроль порций.\nДобавь основные риски: слабый отклик на предложения, рост закупочных цен, перегрузка сотрудников."
    unit = _unit("u7", title="Как сократить потери", text=text)
    shown = OutlineSlide(id="u7", kind=K.two_column, headline="Учёт и закупки сократят потери", content=SlideContent(columns=[
        SlideItem(title="Меры", bullets=["Учёт остатков каждый день", "Закупки по спросу", "Контроль порций"]),
        SlideItem(title="Риски", bullets=["Слабый отклик", "Рост цен закупки", "Перегрузка сотрудников"]),
    ]))
    assert A.coverage_gaps(A._Design(unit=unit, slide=shown, by="model")) == []
    half = shown.model_copy(update={"content": SlideContent(columns=[shown.content.columns[0]])}, deep=True)
    gaps = A.coverage_gaps(A._Design(unit=unit, slide=half, by="model"))
    assert len(gaps) == 1 and "«Основные риски»" in gaps[0] and " → " in gaps[0]


def test_a_topic_heading_kept_as_the_headline_is_sent_back():
    from verstka.schemas.outline import OutlineSlide, SlideContent

    unit = _unit("u10", title="Что контролировать каждую неделю", text="Покажи пять основных показателей:\n— количество покупок в день;\n— средний чек.")
    topic = OutlineSlide(id="u10", kind=K.bullets, headline="Что контролировать каждую неделю", content=SlideContent(bullets=["Покупки в день", "Средний чек"]))
    gaps = A.coverage_gaps(A._Design(unit=unit, slide=topic, by="model"))
    assert gaps and gaps[0].startswith("Заголовок повторяет тему")
    stated = topic.model_copy(update={"headline": "Пять показателей покажут рост каждую неделю"})
    assert A.coverage_gaps(A._Design(unit=unit, slide=stated, by="model")) == []
    # a list announced instead of a conclusion, with a count the brief's list does not have
    announced = topic.model_copy(update={"headline": "Три ключевых показателя роста"})
    gaps = A.coverage_gaps(A._Design(unit=unit, slide=announced, by="model"))
    assert len(gaps) == 1 and gaps[0].startswith("Заголовок объявляет список") and "в брифе 2, а не 3" in gaps[0]


def test_every_field_the_designer_filled_is_one_its_form_shows():
    """A revision answered «table» with a one-row table and two columns of lists (the columns hold the table's
    figures): the slide is the two columns. Figures on a card slide become lines, not a field the form drops."""
    unit = _unit("u5", title="Как увеличить средний чек", text="Цель — поднять средний чек с 300 до 330 рублей.")
    ans = SlideDesignAnswer.model_validate({
        "kind": "table", "headline": "Средний чек вырастет с 300 до 330 рублей",
        "table": {"columns": ["Показатель", "Сейчас", "Цель"], "rows": [["Доля чеков с едой", "20%", "30%"]]},
        "columns": [{"title": "Цель", "bullets": ["Средний чек: 300 → 330 ₽", "Доля чеков с едой: 20% → 30%"]}, {"title": "Действия", "bullets": ["Комбо", "Добавки", "Десерты у кассы"]}],
    })
    d = A.design_from_answer(ans, unit, _ctx())
    assert d.slide.kind == K.two_column and d.slide.content.table is None and len(d.slide.content.columns) == 2
    cards = SlideDesignAnswer.model_validate({
        "kind": "cards", "headline": "Три шага к росту", "items": [{"title": "Комбо", "text": "за 390 рублей"}, {"title": "Добавки", "text": "к напиткам"}],
        "numbers": [{"value": "90 000 ₽", "label": "выручки в месяц"}],
    })
    d2 = A.design_from_answer(cards, unit, _ctx())
    assert d2.slide.kind == K.cards and not d2.slide.content.numbers
    assert [b.lower() for b in d2.slide.content.bullets] == ["выручки в месяц — 90 000 ₽"]


def test_a_footnote_that_is_content_becomes_a_line_and_chart_lines_do_not_repeat_its_values():
    text = "Маркетинговый бюджет вырастет с 20 000 до 35 000 рублей в месяц. Это выручка, а не прибыль. Зарплаты — 270 000 рублей, аренда — 120 000 рублей."
    unit = _unit("u6", title="Как привлечь больше гостей", text=text)
    ans = SlideDesignAnswer.model_validate({
        "kind": "cards", "headline": "Партнёрства и лояльность приведут новых гостей", "items": [{"title": "Партнёрства"}, {"title": "Лояльность"}],
        "footnote": "Маркетинговый бюджет вырастет с 20 000 до 35 000 рублей в месяц",
    })
    d = A.design_from_answer(ans, unit, _ctx())
    assert d.slide.footnote is None and d.slide.content.bullets == ["Маркетинговый бюджет вырастет с 20 000 до 35 000 рублей в месяц"]
    caveat = ans.model_copy(update={"footnote": "Это выручка, а не прибыль"})
    assert A.design_from_answer(caveat, unit, _ctx()).slide.footnote == "Это выручка, а не прибыль"
    pie = SlideDesignAnswer.model_validate({
        "kind": "chart", "headline": "Зарплаты и аренда — главные расходы",
        "chart": {"type": "pie", "categories": ["Зарплаты", "Аренда"], "series": [{"name": "Расходы", "values": [270000, 120000]}]},
        "bullets": ["Зарплаты — 270 000 ₽", "Аренда — 120 000 ₽", "Это выручка, а не прибыль"],
    })
    from verstka.planning.facts import basic_facts

    brief = parse_brief_text(text)
    ctx = A._build_ctx(brief, BriefStructure(), basic_facts(brief.text), None)
    d3 = A.design_from_answer(pie, unit, ctx)
    assert d3.slide.kind == K.chart and d3.slide.content.bullets == ["Это выручка, а не прибыль"]


def test_lines_that_repeat_the_formulas_figures_are_dropped():
    unit = _unit("u2", title="Как работает кофейня сейчас", text="100 покупок в день, средний чек — 300 рублей, 30 дней. Покажи формулу: 100 × 300 × 30 = 900 000 рублей.")
    from verstka.planning.facts import basic_facts

    brief = parse_brief_text(unit.text)
    ctx = A._build_ctx(brief, BriefStructure(), basic_facts(brief.text), None)
    ans = SlideDesignAnswer.model_validate({
        "kind": "stat_row", "headline": "Выручка — 900 000 рублей в месяц", "formula": "100 × 300 × 30 = 900 000 рублей",
        "numbers": [{"value": "100", "label": "покупок в день"}, {"value": "300 ₽", "label": "средний чек"}],
        "bullets": ["100 покупок в день", "300 рублей — средний чек", "Кофейня работает ежедневно"],
    })
    assert A.design_from_answer(ans, unit, ctx).slide.content.bullets == ["Кофейня работает ежедневно"]


def test_a_bare_figure_is_not_cut_out_of_a_headline():
    from verstka.planning.facts import basic_facts

    brief = parse_brief_text("Расходы: зарплаты — 270 000 рублей, продукты — 315 000 рублей, всего 780 000 рублей.")
    ctx = A._build_ctx(brief, BriefStructure(), basic_facts(brief.text), None)
    unit = _unit("u2", title="Расходы и прибыль")
    # «73%» is not the brief's: cutting it would leave «составляют бюджета» — the slide's heading instead
    assert A._headline_checked("Расходы на зарплаты и продукты составляют 73% бюджета", unit, ctx, []) == "Расходы и прибыль"
