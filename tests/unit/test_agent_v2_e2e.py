"""Agent v2 end to end on the VK Tech template: brief → analyst → designer per slide → critic → revision → compiler →
grounding → render, through generate_variants, with a scripted fake model (no network) and without any model.

The fake designer answers like a real one does on a bad day: a requested pie sent as bullets, a line chart with an
invented month, a footnote and takeaways in its own words. The deck must still carry every chart the user asked for,
with the brief's own data, and tell the user what the agent did (events, agent_log, run manifest).
Skipped when the VK templates (Датасет/) are not on this machine."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pytest

from verstka.planning import agent as A
from verstka.planning.brief import parse_brief_text
from verstka.planning.compile import same_formula
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.common import PatternKind as K
from verstka.skills_registry.registry import SkillsRegistry

BRIEFS = Path(__file__).resolve().parents[1] / "fixtures" / "briefs"
SHORT = (BRIEFS / "coffee_short.md").read_text(encoding="utf-8")
LONG = (BRIEFS / "coffee_long.md").read_text(encoding="utf-8")
STEPS = ("Аналитик", "Архитектор", "Дизайнер", "Критик", "Правка", "Сборка")


def _pie(categories, values, unit="₽"):
    return {"type": "pie", "unit": unit, "categories": categories, "series": [{"name": "Доля", "values": values}]}


def _column(categories, values, name, unit=""):
    return {"type": "column", "unit": unit, "categories": categories, "series": [{"name": name, "values": values}]}


# what the fake designer answers per slide heading (the headings of the short brief's «Слайд 1…5»)
DESIGNS = {
    "Как работает кофейня сейчас": {
        "kind": "chart", "headline": "Кофе приносит 60% выручки кофейни",
        "chart": _pie(["Кофе", "Десерты и выпечка", "Чай и другие напитки"], [540000, 225000, 135000]),
        "takeaway": "Кофе — основа выручки: 540 000 из 900 000 рублей",
        "notes": "100 покупок в день по 300 рублей за 30 дней дают 900 000 рублей.",
        "rationale": "Доли одного целого лучше всего видны на круговой диаграмме.",
        "alternatives": [{"kind": "stat_row", "why": "три суммы крупно"}, {"kind": "table", "why": "плотнее"}],
    },
    # the user asked for a pie of the expenses: the designer sent a list (the compiler must draw the pie from the brief)
    "Расходы и прибыль": {
        "kind": "bullets", "headline": "Продукты и зарплаты — три четверти расходов",
        "bullets": ["Продукты и упаковка — 315 000 рублей", "Зарплаты — 270 000 рублей", "Аренда — 120 000 рублей"],
        "takeaway": "Операционная прибыль — 120 000 рублей, 13,3% выручки",
        "footnote": "Налоги, проценты по кредитам и амортизация в расчет не включены",
        "rationale": "Список расходов.", "alternatives": [{"kind": "chart", "chart_type": "pie", "why": "доли расходов"}, {"kind": "table", "why": "плотнее"}],
    },
    "Как увеличить продажи": {
        "kind": "chart", "headline": "Больше покупок и выше чек дают +238 500 рублей",
        "chart": _column(["Сейчас", "Цель"], [100, 115], "Покупок в день"),
        "chart2": _column(["Сейчас", "Цель"], [300, 330], "Средний чек", "₽"),
        "takeaway": "Выручка вырастет до 1 138 500 рублей в месяц",
        "rationale": "До и после одного показателя — два столбца.",
        "alternatives": [{"kind": "stat_row", "why": "два изменения крупно"}, {"kind": "table", "why": "плотнее"}],
    },
    # an invented month in the forecast (950 000): the chart must come back with the brief's own figures
    "Вложения и прогноз роста": {
        "kind": "chart", "headline": "180 000 рублей вложений ведут выручку к 1 138 500",
        "chart": {"type": "line", "unit": "₽", "categories": ["Сейчас", "1-й месяц", "2-й месяц", "3-й месяц"], "series": [{"name": "Выручка", "values": [900000, 950000, 970000, 1015000]}]},
        "chart2": _pie(["Витрина для десертов", "Программа лояльности и учет", "Меню и фотографии", "Обучение сотрудников", "Резерв"], [70000, 35000, 25000, 20000, 30000]),
        "takeaway": "Рост постепенный: это прогноз, а не гарантия",
        "rationale": "Изменение по месяцам читается по линии графика.",
        "alternatives": [{"kind": "table", "why": "все месяцы в таблице"}, {"kind": "bullets", "why": "коротко"}],
    },
    "Ожидаемый финансовый результат": {
        "kind": "chart", "headline": "Прибыль вырастет на 112,3%",
        "chart": _column(["Сейчас", "Прогноз"], [120000, 254795], "Операционная прибыль", "₽"),
        "takeaway": "Рентабельность вырастет с 13,3% до 22,4%",
        "rationale": "Сравнение двух значений нагляднее столбцами.",
        "alternatives": [{"kind": "big_number", "why": "одна цифра крупно"}, {"kind": "table", "why": "плотнее"}],
    },
}
REVISED = {
    "Ожидаемый финансовый результат": {
        "kind": "chart", "headline": "Операционная прибыль вырастет до 254 795 рублей",
        "chart": _column(["Сейчас", "Прогноз"], [120000, 254795], "Операционная прибыль", "₽"),
        "takeaway": "Прибыль вырастет со 120 000 до 254 795 рублей в месяц",
        "rationale": "Сравнение двух значений нагляднее столбцами.",
        "alternatives": [{"kind": "big_number", "why": "одна цифра крупно"}, {"kind": "table", "why": "плотнее"}],
    },
}


class FakeModel:
    """The scripted model: answers each skill by its system prompt and each slide by its heading; counts the calls."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.lock = threading.Lock()

    def _count(self, what: str) -> None:
        with self.lock:
            self.calls[what] = self.calls.get(what, 0) + 1

    def __call__(self, messages):
        system, user = messages[0].content, messages[-1].content
        if "presentation designer" in system:
            heading = re.search(r"Heading of this slide: «(.+?)»", user).group(1)
            if "A reviewer found problems" in user:
                self._count("revise")
                return REVISED.get(heading) or DESIGNS[heading]
            self._count("designer")
            return DESIGNS.get(heading) or {"kind": "bullets", "headline": heading, "bullets": ["Тезис из брифа"]}
        if "strict reviewer" in system:
            self._count("critic")
            # the variants whose plans are the same share one critic call (named after the first of them): the note
            # is on every plan's last slide, the designer redoes that slide once and every variant takes it
            if re.search(r"The plan of the variant «(.+?)»", user):
                last = len(re.findall(r"(?m)^\s*\d+\.", user.split("The plan", 1)[1])) or 6
                return {"issues": [{"slide": last, "problem": "Заголовок повторяет подпись оси", "fix": "Сказать, во сколько раз вырастет прибыль"}]}
            return {"issues": []}
        if "presentation architect" in system:
            self._count("architect")
            raise AssertionError("the short brief describes its slides: no storyline call")
        self._count("other")
        return {"facts": [], "series": [], "tables": [], "charts": []}


@pytest.fixture(scope="module")
def vk_tech(fixtures_dir_module) -> Path:
    if fixtures_dir_module is None:
        pytest.skip("VK templates not available")
    pptx = next((p for p in fixtures_dir_module.glob("*.pptx") if "vk tech" in p.name.lower()), None)
    if pptx is None:
        pytest.skip("VK Tech template not available")
    return pptx


@pytest.fixture(scope="module")
def fixtures_dir_module():
    import os

    env = os.environ.get("VERSTKA_FIXTURES_DIR")
    for c in ([Path(env)] if env else []) + [Path(__file__).resolve().parents[3] / "Датасет"]:
        if c.is_dir() and any(c.glob("*.pptx")):
            return c
    return None


@pytest.fixture(scope="module")
def workspace(vk_tech, tmp_path_factory) -> Path:
    """The template analysed once for the module, without models (the fake answers only the agent's skills)."""
    from verstka.analysis.manifest import analyze_template

    ws = tmp_path_factory.mktemp("ws")
    analyze_template(vk_tech, workspace_root=ws, use_llm=False, use_vlm=False)
    return ws


def _allowed(text: str) -> list[float]:
    return A.figures(text)


def _charts(o):
    return [(s, ch) for s in o.slides for ch in (s.content.chart, s.content.chart2) if ch is not None]


def _by_spec(o) -> dict:
    return {s.spec_ref: s for s in o.slides if s.spec_ref is not None}


def _assert_chart_grounded(o, ch, text: str) -> None:
    """Inline data (categories + series) that the renderer draws, every value one of the brief's figures (or the
    same figure in thousands), and registry series behind the chart's ids."""
    assert ch.categories and ch.series and all(len(sr.values) == len(ch.categories) for sr in ch.series), ch
    allowed = _allowed(text)
    for sr in ch.series:
        for v in sr.values:
            assert A.value_ok(v, allowed), f"{v} is not a figure of the brief ({ch.type} «{ch.title}»)"
    reg = {s.id: s for s in o.series}
    assert ch.series_ids and all(i in reg for i in ch.series_ids), ch.series_ids


@pytest.fixture(scope="module")
def short_run(vk_tech, workspace, tmp_path_factory):
    from verstka.pipeline.generate import generate_variants

    fake = FakeModel()
    model = MockProvider(fake, model="qwen/qwen3.8-27b")
    providers = ProviderRegistry(roles={"llm": model, "vlm": model}, limits=ProviderLimits(max_concurrency=6, time_budget_s=210))
    brief = parse_brief_text(SHORT)
    brief.slide_count = 5  # what the user set in the form: the five slides the brief describes
    events: list[dict] = []
    plain: list[str] = []

    def progress(msg, frac=None, event=None):
        if event is not None:
            events.append(event)
        else:
            plain.append(msg)

    t0 = time.time()
    res = generate_variants(
        vk_tech, brief=brief, out_dir=tmp_path_factory.mktemp("out"), workspace_root=workspace, providers=providers, skills=SkillsRegistry.load(),
        use_vlm=False, audit=False, autofix=False, exports=[], render_images=False, progress=progress,
    )
    return res, events, plain, fake, time.time() - t0


def test_three_variants_planned_by_the_agent(short_run):
    res, _, _, fake, _ = short_run
    assert [v.strategy for v in res.variants] == ["structured", "visual", "compact"]
    # one critic call per distinct plan (the variants of one plan share it), one revision per flagged slide: the
    # critic's (slide 6) and the agent's own check's (slide 3 leaves out the brief's total «780 000 рублей»)
    assert fake.calls["designer"] == 5 and 1 <= fake.calls["critic"] <= 3 and fake.calls["revise"] == 2
    assert "architect" not in fake.calls and fake.calls.get("other", 0) <= 2  # no whole-brief extraction next to the analyst's
    for v in res.variants:
        assert v.outline.planned_by == "agent" and v.planner["planned_by"] == "agent" and v.planner["model"] == "qwen/qwen3.8-27b"
        assert v.planner["agent"]["slides_by_model"] == 5 and v.planner["agent"]["version"] == A.AGENT_VERSION
        rm = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
        assert rm["planner"]["planned_by"] == "agent"
        assert (v.out_dir / "deck.pptx").is_file()


def test_every_requested_chart_is_there_with_the_briefs_data(short_run):
    res, *_ = short_run
    for v in res.variants:
        o = v.outline
        sp = _by_spec(o)
        assert sorted(sp) == [1, 2, 3, 4, 5], [s.spec_ref for s in o.slides]
        assert sp[1].content.chart.type in ("pie", "doughnut")
        # the designer sent a list for «Нужна круговая диаграмма распределения расходов»: the pie comes from the brief
        assert sp[2].content.chart is not None and sp[2].content.chart.type in ("pie", "doughnut")
        assert sorted(sp[2].content.chart.series[0].values) == sorted([315000, 270000, 120000, 25000, 20000, 30000])
        # «два небольших столбчатых графика»
        assert sp[3].content.chart.type == "column" and sp[3].content.chart2 is not None and sp[3].content.chart2.type == "column"
        assert {tuple(sp[3].content.chart.series[0].values), tuple(sp[3].content.chart2.series[0].values)} == {(100, 115), (300, 330)}
        # the line with an invented month (950 000) is the brief's forecast instead; the investments' pie next to it
        line = sp[4].content.chart
        assert line.type == "line" and 950000 not in line.series[0].values and 950 not in line.series[0].values
        assert len(line.series[0].values) >= 6
        assert sp[4].content.chart2 is not None and sp[4].content.chart2.type in ("pie", "doughnut")
        assert sp[5].content.chart.type == "column" and sp[5].content.chart.series[0].values == [120000, 254795]
        charts = _charts(o)
        assert len(charts) == 7
        for _, ch in charts:
            _assert_chart_grounded(o, ch, SHORT)


def test_forms_takeaways_and_footnotes(short_run):
    res, *_ = short_run
    for v in res.variants:
        o = v.outline
        kinds = [s.kind for s in o.slides]
        assert kinds.count(K.bullets) <= 1 and len(set(kinds)) >= 2, kinds  # designed, not the brief pasted as lists
        assert o.slides[0].kind == K.title and o.slides[0].footnote and "условн" in o.slides[0].footnote  # the disclaimer
        sp = _by_spec(o)
        assert sp[2].footnote and "Налоги" in sp[2].footnote
        assert sum(1 for s in o.slides if s.takeaway) >= 4
        assert all(s.rationale for s in o.slides if s.spec_ref is not None)
        assert any(s.alternatives for s in o.slides if s.spec_ref is not None)
        comps = [s.composition for s in v.render.slides]
        assert comps.count("chart_pair") == 2, comps  # two charts side by side on slides 3 and 4
    # the critic flagged the visual variant's last slide: the variants of that plan got the revision
    visual = _by_spec(res.variants[1].outline)[5]
    assert visual.headline == "Операционная прибыль вырастет до 254 795 рублей"
    for v in res.variants:
        s5 = _by_spec(v.outline)[5]
        assert s5.headline in ("Операционная прибыль вырастет до 254 795 рублей", "Прибыль вырастет на 112,3%")


def test_the_agent_reports_its_work(short_run):
    res, events, plain, _, seconds = short_run
    assert events and all(e["type"] == "agent" and set(e) >= {"step", "message", "slide", "variant"} for e in events)
    steps = {e["step"] for e in events}
    assert steps >= {"analyst", "designer", "critic", "revise", "compile"}, steps
    designer = [e for e in events if e["step"] == "designer"]
    assert len(designer) == 6 and {e["slide"] for e in designer} == {1, 2, 3, 4, 5, 6}
    # the timeline names the step itself: the message does not start with it, nor with «слайд N» when it has the slide
    assert not any(e["message"].startswith(STEPS) for e in events)
    assert not any(re.match(r"(?i)слайд\s*\d", e["message"]) for e in events if e["slide"] is not None)
    assert any(e["step"] == "critic" and e["variant"] == "visual" and e["slide"] == 6 for e in events)
    assert any(e["step"] == "revise" and e["variant"] == "visual" and e["slide"] == 6 for e in events)
    assert any(m.startswith("plan: agent") for m in plain)
    for v in res.variants:
        log = v.outline.agent_log
        assert log and log[0].startswith("Аналитик:") and all(line.split(":", 1)[0].split(" (")[0] in STEPS for line in log), log
        assert any(line.startswith("Дизайнер:") for line in log) and any(line.startswith("Сборка:") for line in log)
    assert any(line.startswith("Критик: 1 замечание") for line in res.variants[1].outline.agent_log)
    assert seconds < 90, f"{seconds:.0f} s"  # the template's analysis included; a model-less generation is seconds


# ------------------------------------------------------------------ without a model: the deterministic designer


@pytest.fixture(scope="module")
def offline_runs(vk_tech, workspace, tmp_path_factory):
    from verstka.pipeline.generate import generate_variants

    out = {}
    for name, text, count in (("short", SHORT, 5), ("long", LONG, 10)):
        brief = parse_brief_text(text)
        brief.slide_count = count
        events: list[dict] = []
        t0 = time.time()
        res = generate_variants(
            vk_tech, brief=brief, out_dir=tmp_path_factory.mktemp(f"off_{name}"), workspace_root=workspace, use_llm=False, use_vlm=False,
            audit=False, autofix=False, exports=[], render_images=False, progress=lambda m, f=None, event=None: event and events.append(event),
        )
        out[name] = (res, events, time.time() - t0)
    return out


def test_without_a_model_the_short_brief_keeps_every_chart(offline_runs):
    res, events, seconds = offline_runs["short"]
    assert len(res.variants) == 3 and seconds < 60
    for v in res.variants:
        o = v.outline
        assert o.planned_by == "rules" and o.slides[0].kind == K.title
        sp = _by_spec(o)
        assert sorted(sp) == [1, 2, 3, 4, 5]
        assert [sp[n].content.chart.type for n in range(1, 6)] == ["pie", "pie", "column", "line", "column"]
        assert sp[3].content.chart2 is not None and sp[4].content.chart2 is not None
        for _, ch in _charts(o):
            _assert_chart_grounded(o, ch, SHORT)
        assert sum(1 for s in o.slides if s.takeaway) >= 3  # the brief's own result sentences
        assert o.agent_log and o.agent_log[0].startswith("Аналитик:")
    assert {e["step"] for e in events} >= {"analyst", "designer", "compile"}


def test_without_a_model_the_long_brief_has_its_formula_table_charts_and_takeaways(offline_runs):
    res, _, seconds = offline_runs["long"]
    assert seconds < 60
    for v in res.variants:
        o = v.outline
        assert len(o.slides) == 10 and o.planned_by == "rules"
        sp = _by_spec(o)
        cover = sp[1]
        assert cover.kind == K.title and cover.headline == "Больше прибыли с каждой чашки" and "условн" in (cover.footnote or "")
        # the user's calculation, its factors named from the slide's text
        assert same_formula(sp[2].content.formula, "100 × 300 × 30 = 900 000 рублей") and "покупок в день" in sp[2].content.formula
        assert sp[3].content.chart is not None and sp[3].content.chart.type in ("pie", "doughnut") and "налог" in (sp[3].footnote or "").lower()
        assert sp[9].content.table is not None and len(sp[9].content.table.rows) == 7 and sp[9].takeaway
        assert sp[10].takeaway and sp[10].takeaway.startswith("Рост прибыли зависит")
        # the 6-month plan: steps on a timeline (the compact variant sets it next to the budget, in two columns)
        assert sp[8].kind in (K.timeline, K.process) or (v.strategy == "compact" and sp[8].kind in (K.bullets, K.two_column))
        assert "Витрина для десертов" in " ".join([*sp[8].content.bullets, *(b for c in sp[8].content.columns for b in c.bullets)])
        assert sum(1 for s in o.slides if s.takeaway) >= 5
        assert [s.kind for s in o.slides].count(K.bullets) <= 4
        for _, ch in _charts(o):
            _assert_chart_grounded(o, ch, LONG)
