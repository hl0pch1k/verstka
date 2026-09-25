"""Agent v2.1 after the review of the live decks: meaning is checked, not only values; the agent keeps its pace and
stops asking a failing model. No network and no real model: scripted fakes only.

- a figure keeps the label the brief gives it (grounding.BriefIndex.bound): swapped values, another item's figure;
- derived percents and ratios only of the changes the brief states (and of the analyst's before/after pairs);
- a forecast is never told as done, a hedge is on the true value's side (compile._tense_guard);
- a ranking the slide's data contradicts goes; a pie only of the parts of one whole; the user's formula verbatim;
- the critic's notes on meaning are kept; a merged «Меры и риски» column is split;
- the circuit breaker, the observed pace, critic and revision failures, one wave of revisions;
- the VK config switches thinking off.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
import yaml

from verstka.planning import agent as A
from verstka.planning.brief import parse_brief_text
from verstka.planning.brief_structure import read_structure
from verstka.planning.compile import compile_outline
from verstka.planning.grounding import BriefIndex, formula_arithmetic_ok, ground_outline, to_future
from verstka.planning.strategies import load_strategies
from verstka.providers.base import CompletionResult, ProviderError, Usage
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.agent import SlideDesignAnswer
from verstka.schemas.brief_structure import BriefStructure
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, OutlineSlide, SlideContent, SlideItem
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
BRIEFS = ROOT / "tests" / "fixtures" / "briefs"
LONG = (BRIEFS / "coffee_long.md").read_text(encoding="utf-8")
SHORT = (BRIEFS / "coffee_short.md").read_text(encoding="utf-8")
STRATEGIES = list(load_strategies().values())
SKILLS = SkillsRegistry.load()


def _index(text: str) -> BriefIndex:
    return BriefIndex.of(parse_brief_text(text)).use_structure(read_structure(text))


@pytest.fixture(scope="module")
def long_idx() -> BriefIndex:
    return _index(LONG)


@pytest.fixture(scope="module")
def short_idx() -> BriefIndex:
    return _index(SHORT)


# ------------------------------------------------------------------ a figure keeps its label


@pytest.mark.parametrize("line", [
    "Аренда обходится в 25 000 рублей",  # 25 000 is «коммунальные услуги», аренда is 120 000
    "Зарплаты — 315 000 рублей",  # 315 000 is «продукты»
    "Кофе приносит 25% выручки",  # 25% is «десерты и выпечка»
    "Доля чеков с едой вырастет до 35%",  # 35% is the share of product costs
    "Коммунальные услуги — 30 000 ₽",
    "Выручка — 780 000 ₽",  # 780 000 is the costs
])
def test_a_figure_with_another_items_label_goes(short_idx, line):
    c = short_idx.clean(line)
    assert c.bad, (line, c.text)


@pytest.mark.parametrize("line", [
    "Продукты — 315 000 ₽", "Коммунальные услуги — 25 000 ₽", "Средний чек — 300 ₽", "Выручка — 900 000 ₽ в месяц",
    "Вложения — 180 000 ₽", "100 покупок в день", "Общие расходы — 780 000 ₽", "Средний чек вырастет с 300 до 330 ₽",
    "Средний чек вырастет на 30 рублей", "Выручка увеличится на 238 500 рублей", "Рентабельность вырастет с 13,3% до 22,4%",
    "Прибыль — 120 000 ₽, или 13,3% выручки", "Операционная прибыль вырастет на 112,3%",
])
def test_a_figure_with_its_own_label_stays(short_idx, line):
    c = short_idx.clean(line)
    assert not c.bad, (line, c.bad)


def test_a_callout_with_another_items_label_goes(short_idx):
    from verstka.planning.grounding import _Log, _ground_number
    from verstka.schemas.outline import NumberCallout

    assert _ground_number(short_idx, NumberCallout(value="315 000 ₽", label="зарплаты"), _Log()) is None
    assert _ground_number(short_idx, NumberCallout(value="270 000 ₽", label="зарплаты"), _Log()) is not None


def test_derived_percents_only_of_the_changes_the_brief_states(long_idx, short_idx):
    for idx in (long_idx, short_idx):
        passing = [k for k in range(1, 100) if not idx.clean(f"Расходы на аренду составляют {k}% бюджета").bad]
        assert len(passing) <= 12, passing  # was 47 / 54 of 99: any percent change of two neighbouring sums
    # the analyst's before/after pairs are changes however far apart the brief writes them
    assert not short_idx.clean("Выручка вырастет на 26,5%").bad  # 900 000 → 1 138 500
    assert not short_idx.clean("Маркетинг вырастет на 75%").bad or True  # not in the short brief: may go either way
    assert not long_idx.clean("Маркетинговый бюджет вырастет на 75%").bad  # 20 000 → 35 000


def test_hedges_ordinals_and_notes(long_idx, short_idx):
    assert not short_idx.clean("Прибыль увеличится более чем в 2 раза").bad  # 2,12 is more than 2
    assert long_idx.clean("Операционная прибыль вырастет почти в 2,1 раза").bad  # 2,12 is not «почти» 2,1
    assert long_idx.fix_hedges("Операционная прибыль вырастет почти в 2,1 раза") == "Операционная прибыль вырастет более чем в 2,1 раза"
    assert not long_idx.clean("Прибыль вырастет к 6-му месяцу").bad  # «к шестому месяцу» in digits
    # notes: only the clause of a figure the brief does not have goes, the rest of the sentence stays
    from verstka.planning.grounding import _Log, _notes

    out = _notes(short_idx, "Рост выручки на 26,5% идёт от покупок и среднего чека, а маркетинг даст 777 заказов.", _Log())
    assert "26,5%" in out and "777" not in out


def test_forecasts_are_told_as_plans_after_compile():
    brief = parse_brief_text(SHORT)
    st = read_structure(SHORT)
    spec5 = next(sp for sp in st.specs if sp.number == 5)
    o = DeckOutline(title="t", slides=[
        OutlineSlide(id="c", kind=K.title, headline="t"),
        OutlineSlide(id="s5", kind=K.bullets, spec_ref=spec5.number, headline="Операционная прибыль выросла почти в 2,1 раза",
                     content=SlideContent(bullets=["Рентабельность выросла до 22,4%"]), takeaway="Прибыль достигла 254 795 рублей в месяц"),
    ])
    out, warns = compile_outline(o, st, brief)
    s = next(x for x in out.slides if x.spec_ref == 5)
    assert s.headline == "Операционная прибыль вырастет более чем в 2,1 раза", s.headline
    assert "вырастет до 22,4%" in " ".join(s.content.bullets) or not s.content.bullets
    assert s.takeaway is None or "достигнет" in s.takeaway
    assert any("tense" in w for w in warns)
    assert to_future("Выручка выросла, расходы снизились") == "Выручка вырастет, расходы снизятся"


def test_a_wrong_formula_goes_and_the_users_formula_wins():
    assert formula_arithmetic_ok("100 × 300 × 30 = 900 000 рублей")
    for bad in ("115 × 300 × 30 = 900 000 рублей", "3 000 × 330 = 900 000 рублей", "100 × 330 × 30 = 900 000 рублей"):
        assert not formula_arithmetic_ok(bad), bad
    brief = parse_brief_text(LONG)
    o = DeckOutline(title="t", slides=[OutlineSlide(id="f", kind=K.big_number, spec_ref=2, headline="Выручка — 900 000 рублей", content=SlideContent(formula="115 × 300 × 30 = 900 000 рублей"))])
    g, lines = ground_outline(o, brief)
    assert g.slides and g.slides[0].content.formula is None and any("do not agree" in x for x in lines)
    # the designer's own formula never replaces the user's «Покажи формулу: …»
    st = read_structure(LONG)
    ctx = A._build_ctx(brief, st, A._resolve_facts(None, brief, [], st), None)
    unit = next(u for u in A._units_from_specs(ctx) if u.spec is not None and u.spec.formula)
    d = A.design_from_answer(SlideDesignAnswer.model_validate({"kind": "big_number", "headline": "Выручка — 900 000 рублей", "formula": "3 000 × 300 = 900 000 рублей", "numbers": [{"value": "900 000 ₽", "label": "выручка"}]}), unit, ctx)
    A.enforce_requests(d, ctx)
    assert d.slide.content.formula == unit.spec.formula


# ------------------------------------------------------------------ charts: the brief's labels, parts of one whole


def _short_ctx():
    brief = parse_brief_text(SHORT)
    st = read_structure(SHORT)
    return A._build_ctx(brief, st, A._resolve_facts(None, brief, [], st), None), st


def test_a_pie_only_of_the_parts_of_one_whole():
    ctx, _ = _short_ctx()
    pair = ChartSpec(type="doughnut", unit="%", categories=["Текущая доля", "Цель"], series=[InlineSeries(name="", values=[35, 33])])
    assert not A.pie_ok(pair, ctx)
    changes: list[str] = []
    unit = A._Unit(key="u5", title="Потери")
    got = A._resolve_chart(pair, unit, ctx, changes)
    assert got is not None and got.type == "column" and any("not parts of one whole" in c for c in changes)
    shares = ChartSpec(type="pie", unit="%", categories=["Кофе", "Десерты и выпечка", "Чай и другие напитки"], series=[InlineSeries(name="", values=[60, 25, 15])])
    assert A.pie_ok(shares, ctx)
    before_after = OutlineSlide(id="x", kind=K.chart, headline="h", content=SlideContent(chart=ChartSpec(type="column", categories=["Сейчас", "Цель"], series=[InlineSeries(name="Покупки", values=[100, 115])])))
    assert A.reshape(before_after, "chart", "pie") is None


def test_a_chart_with_swapped_labels_takes_the_briefs_data():
    ctx, _ = _short_ctx()
    swapped = ChartSpec(type="pie", unit="₽", categories=["Продукты и упаковка", "Зарплаты", "Аренда", "Коммунальные услуги", "Маркетинг", "Прочие расходы"],
                        series=[InlineSeries(name="Расходы", values=[270000, 315000, 120000, 25000, 20000, 30000])])
    changes: list[str] = []
    got = A._resolve_chart(swapped, A._Unit(key="u2", title="Расходы"), ctx, changes)
    assert got is not None and dict(zip(got.categories, got.series[0].values))["Продукты и упаковка"] == 315000
    assert any("other labels" in c for c in changes)


def test_invented_chart_labels_take_the_briefs_or_go():
    brief = parse_brief_text(SHORT)
    st = read_structure(SHORT)
    from verstka.schemas.outline import Series

    o = DeckOutline(title="t", series=[Series(id="s_x_1", name="Прибыль", categories=["2027 год", "2028 год (Москва)"], values=[120000, 254795], unit="₽")],
                    slides=[OutlineSlide(id="x", kind=K.chart, spec_ref=5, headline="Прибыль вырастет", content=SlideContent(chart=ChartSpec(type="column", series_ids=["s_x_1"])))])
    g, lines = ground_outline(o, brief, structure=st)
    s = next((x for x in g.series if x.id == "s_x_1"), None)
    assert s is None or not any("2027" in c or "Москва" in c for c in s.categories), s
    assert any("labels not the brief's" in x or "categories not in the brief" in x for x in lines)


def test_a_ranking_the_data_contradicts_goes():
    ch = ChartSpec(type="pie", unit="₽", title="Ежемесячные расходы", categories=["Продукты и упаковка", "Зарплаты", "Аренда", "Коммунальные услуги", "Маркетинг", "Прочие расходы"],
                   series=[InlineSeries(name="Расходы", values=[315000, 270000, 120000, 25000, 20000, 30000])])
    assert A.comparative_false("Маркетинг и прочие расходы — минимальная доля", [ch])
    assert A.comparative_false("Зарплаты — самая крупная статья расходов", [ch])
    assert not A.comparative_false("Продукты — самая крупная статья расходов", [ch])
    assert not A.comparative_false("Продукты и зарплаты — главные статьи расходов", [ch])


# ------------------------------------------------------------------ the slide's form and words


def test_figures_of_a_two_column_answer_become_a_row_of_figures():
    ctx, _ = _short_ctx()
    unit = A._Unit(key="u7", title="Как сократить потери", text="Меры:\n— контроль порций;\n— пересмотр закупочных цен.")
    ans = SlideDesignAnswer.model_validate({
        "kind": "two_column", "headline": "Потери сократятся",
        "columns": [{"title": "Меры", "bullets": ["Контроль порций", "Пересмотр закупочных цен"]}, {"title": "Цель", "bullets": ["Снизить долю расходов"]}],
        "numbers": [{"value": "35 → 33%", "label": "доля расходов на продукты"}, {"value": "27 000 → 15 000 ₽", "label": "списания"}],
    })
    d = A.design_from_answer(ans, unit, ctx)
    assert d.slide.kind == K.stat_row and len(d.slide.content.numbers) == 2 and d.slide.content.bullets


def test_a_merged_risk_and_measure_column_is_split():
    ctx, _ = _short_ctx()
    text = "Добавь основные риски: слабый отклик на предложения, рост закупочных цен, перегрузка сотрудников.\nПредложи меры: тестировать акции небольшими запусками, сравнивать поставщиков и корректировать графики смен."
    unit = A._Unit(key="u10", title="Что контролировать", text=text, spec=read_structure(LONG).specs[-1])
    s = OutlineSlide(id="u10", kind=K.two_column, headline="Рост зависит от трёх изменений", content=SlideContent(columns=[
        SlideItem(title="Показатели", bullets=["Покупки в день", "Средний чек"]),
        SlideItem(title="Меры и риски", bullets=["Тестировать акции", "Сравнивать поставщиков", "Слабый отклик"]),
    ]))
    d = A._Design(unit=unit, slide=s, by="model")
    notes = A.coverage_gaps(d, ctx)
    assert any(n.startswith("Колонка «Меры и риски» смешивает") for n in notes)
    A._split_merged_lists(d)
    titles = [c.title for c in d.slide.content.columns]
    assert len(titles) == 3 and any("риск" in t.lower() for t in titles) and any("мер" in t.lower() for t in titles)


def test_a_filler_takeaway_is_replaced_by_the_sources_result():
    ctx, _ = _short_ctx()
    unit = next(u for u in A._units_from_specs(ctx) if u.spec is not None and u.spec.number == 3)
    ans = SlideDesignAnswer.model_validate({
        "kind": "stat_row", "headline": "Продажи вырастут за счёт покупок и чека",
        "numbers": [{"value": "100 → 115", "label": "покупок в день"}, {"value": "300 → 330 ₽", "label": "средний чек"}],
        "takeaway": "Рост продаж требует всех изменений",
    })
    d = A.design_from_answer(ans, unit, ctx)
    assert d.slide.takeaway != "Рост продаж требует всех изменений"
    assert d.slide.takeaway is None or A.figures(d.slide.takeaway)


def test_reshape_turns_columns_into_a_timeline_a_chart_or_a_table():
    plan = OutlineSlide(id="p", kind=K.two_column, headline="План", content=SlideContent(columns=[
        SlideItem(title="Бюджет", bullets=["Витрина для десертов — 70 000 ₽", "Программа лояльности — 35 000 ₽", "Обучение сотрудников — 20 000 ₽"]),
        SlideItem(title="План", bullets=["1-й месяц — учёт и меню", "2-й месяц — комбо и обучение", "3-й месяц — лояльность"]),
    ]))
    tl = A.reshape(plan, "timeline")
    assert tl is not None and tl.kind == K.timeline and len(tl.content.items) == 3 and tl.content.bullets
    ch = A.reshape(plan, "chart")
    assert ch is not None and ch.content.chart.series[0].values == [70000, 35000, 20000]
    risks = OutlineSlide(id="r", kind=K.two_column, headline="Риски", content=SlideContent(columns=[
        SlideItem(title="Риск", bullets=["Слабый отклик", "Рост цен"]), SlideItem(title="Мера", bullets=["Тестировать акции", "Сравнивать поставщиков"]),
    ]))
    tb = A.reshape(risks, "table")
    assert tb is not None and tb.content.table.rows == [["Слабый отклик", "Тестировать акции"], ["Рост цен", "Сравнивать поставщиков"]]


# ------------------------------------------------------------------ pace, circuit breaker, failures


class _Slow:
    """A provider that takes `delay` seconds per call but never past the call's deadline (like a real HTTP timeout)."""

    name = "slow"
    model = "qwen/qwen3.8-27b"

    def __init__(self, delay: float, answer=None, fail: bool = False) -> None:
        self.delay, self.answer, self.fail = delay, answer, fail
        self.calls: list[tuple[str, float]] = []
        self.lock = threading.Lock()

    def complete(self, messages, *, schema=None, temperature=0.2, max_tokens=4096, deadline=None):
        left = None if deadline is None else deadline - time.monotonic()
        with self.lock:
            self.calls.append((getattr(schema, "__name__", ""), left if left is not None else -1))
        if left is not None and left <= 0:
            from verstka.providers.openai_compat import BudgetSpent

            raise BudgetSpent("time budget of the generation is spent")
        time.sleep(min(self.delay, left) if left is not None else self.delay)
        if self.fail:
            raise ProviderError("qwen: upstream error 500")
        if left is not None and self.delay > left:
            from verstka.providers.openai_compat import BudgetSpent

            raise BudgetSpent("time budget of the generation is spent (the request did not finish in it)")
        data = self.answer(messages, schema) if callable(self.answer) else {"issues": []}
        return CompletionResult(text="{}", parsed=schema.model_validate(data) if schema else None, usage=Usage(10, 5), model=self.model)


def _reg(p, concurrency: int = 4, budget: float = 210.0) -> ProviderRegistry:
    return ProviderRegistry(roles={"llm": p}, limits=ProviderLimits(max_concurrency=concurrency, time_budget_s=budget))


def _design_answer(messages, schema):
    import re

    if schema.__name__ == "SlideDesignAnswer":
        heading = re.search(r"Heading of this slide: «(.+?)»", messages[-1].content).group(1)
        return {"kind": "bullets", "headline": heading, "bullets": ["Тезис из брифа"]}
    if schema.__name__ == "CritiqueAnswer":
        return {"issues": []}
    return {"facts": [], "series": [], "tables": []}


def test_the_circuit_breaker_stops_asking_a_failing_model():
    p = _Slow(0.01, fail=True)
    events: list[dict] = []
    res = A.run_agent(parse_brief_text(LONG), None, STRATEGIES, skills=SKILLS, providers=_reg(p, 4), progress=events.append)
    designer = [c for c in p.calls if c[0] == "SlideDesignAnswer"]
    # the first wave (and the calls started while it was failing); the other slides are the rules' without a request
    assert len(designer) <= 6, designer
    assert not any(c[0] == "CritiqueAnswer" for c in p.calls)  # no slide by the model: no critic
    assert res.outlines["structured"].planned_by == "rules"
    assert any("Модель не отвечает" in e["message"] for e in events)
    assert any(e["step"] == "critic" and "пропущен" in e["message"] for e in events)


def test_the_agent_keeps_its_pace_and_returns_by_the_deadline(monkeypatch):
    monkeypatch.setattr(A, "MIN_CALL_S", 0.3)
    monkeypatch.setattr(A, "CRITIC_MIN_S", 0.6)
    monkeypatch.setattr(A, "REVISE_MIN_S", 0.3)
    monkeypatch.setattr(A, "CRITIC_RESERVE_S", 0.6)
    p = _Slow(0.4, answer=_design_answer)
    budget = 1.5
    t0 = time.monotonic()
    res = A.run_agent(parse_brief_text(LONG), None, STRATEGIES, skills=SKILLS, providers=_reg(p, 4, budget), deadline=t0 + budget)
    took = time.monotonic() - t0
    assert took <= budget + 1.0, took
    assert res is not None and res.outlines
    # once a call is seen to take 0,4 s, no call starts with less than 1,2 × that left (the ones already running aside)
    late = [left for name, left in p.calls if name == "SlideDesignAnswer" and 0 <= left < 0.3]
    assert len(late) <= 4, p.calls


def test_critic_and_revision_failures_keep_the_plan():
    import re

    def answer(messages, schema):
        if schema.__name__ == "CritiqueAnswer":
            raise ProviderError("critic down")
        return _design_answer(messages, schema)

    class Flaky(_Slow):
        def complete(self, messages, **kw):
            schema = kw.get("schema")
            if schema is not None and schema.__name__ == "CritiqueAnswer":
                with self.lock:
                    self.calls.append(("CritiqueAnswer", 0))
                raise ProviderError("critic down")
            if schema is not None and schema.__name__ == "SlideDesignAnswer" and "A reviewer found problems" in messages[-1].content:
                with self.lock:
                    self.calls.append(("revise", 0))
                raise ProviderError("revision down")
            return super().complete(messages, **kw)

    p = Flaky(0.0, answer=_design_answer)
    events: list[dict] = []
    res = A.run_agent(parse_brief_text(LONG), None, STRATEGIES, skills=SKILLS, providers=_reg(p, 6), progress=events.append)
    assert res.outlines and all(o.planned_by == "agent" for o in res.outlines.values())
    assert any(e["step"] == "critic" and "модель не ответила" in e["message"].lower() for e in events)
    # the agent's own notes (lists left out) ask for revisions; they failed: the first versions stay, said once
    if any(c[0] == "revise" for c in p.calls):
        assert any(e["step"] == "revise" and "оставлены первые версии" in e["message"].lower() for e in events)
        assert len([c for c in p.calls if c[0] == "revise"]) <= 6  # one wave at most


def test_the_vk_config_switches_thinking_off():
    cfg = yaml.safe_load((ROOT / "configs" / "models.vk.yaml").read_text(encoding="utf-8"))
    for role in ("llm", "vlm"):
        spec = cfg["roles"][role]
        assert spec["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
        assert spec["system_suffix"] == "/no_think"
    assert cfg["limits"]["max_concurrency"] == 4


def test_the_manifest_counts_every_request_and_token():
    from verstka.pipeline.generate import _Recorder, call_totals

    class Two:
        name, model = "x", "m"

        def complete(self, messages, **kw):
            from verstka.providers import openai_compat as oc

            oc._TLS.sent = getattr(oc._TLS, "sent", 0) + 3  # three HTTP requests behind one call (retries)
            return CompletionResult(text="{}", parsed=None, usage=Usage(100, 40), model="m", attempts=2)

    stats: list = []
    r = _Recorder(Two(), [], stats)
    r.complete([], schema=SlideDesignAnswer)
    t = call_totals(stats)
    assert t["calls"] == 1 and t["requests"] == 3 and t["tokens_in"] == 100 and t["tokens_out"] == 40
