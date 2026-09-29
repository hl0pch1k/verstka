"""The text of the agent's decks, read as an editor reads it (Agent v2 text quality).

Two live runs through the UI (2026-09-26, Qwen/Qwen3-32B on Cloud.ru, the coffee briefs) are replayed offline from
their recorded model answers (tests/fixtures/agent_v2_live_answers.json): the designer's first designs and revisions
per slide, the critic's notes per variant. The decks the agent builds from them must be faithful (every figure the
brief's, no cause it does not state) and read well: notes never broken by grounding, a takeaway that adds to its
headline, no line repeating the footnote, the headline or the chart, the key figures of a slide on it, a conclusion on
every slide when the brief asks for one, the cover's goal line, a formula that names its factors, a plan titled one
way, variants that differ where the brief leaves the form free. Unit checks of each piece follow."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

from verstka.planning import agent as A
from verstka.planning.brief import parse_brief_text
from verstka.planning.brief_structure import read_structure
from verstka.planning.compile import compile_outline, cover_goal, label_formula, same_formula
from verstka.planning.grounding import BriefIndex, _Log, _notes, ground_outline
from verstka.planning.strategies import load_strategies
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.agent import SlideDesignAnswer
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent, SlideItem
from verstka.skills_registry.registry import SkillsRegistry

FIX = Path(__file__).resolve().parents[1] / "fixtures"
SHORT = (FIX / "briefs" / "coffee_short.md").read_text(encoding="utf-8")
LONG = (FIX / "briefs" / "coffee_long.md").read_text(encoding="utf-8")
RECORDED = json.loads((FIX / "agent_v2_live_answers.json").read_text(encoding="utf-8"))
NAMES = {"Структурный": "structured", "Визуальный": "visual", "Компактный": "compact"}
FRAMES = {K.title, K.section, K.thanks, K.agenda}


# ------------------------------------------------------------------ the replay


class Replay:
    """The recorded answers given back by the slide's heading (the designer, the revision) and the variant's name (the
    critic); counts the calls and keeps the prompts."""

    def __init__(self, rec: dict, text: str) -> None:
        self.rec = rec
        self.by_title = {sp.title.strip(): f"u{sp.number}" for sp in read_structure(text).specs}
        self.calls: dict[str, int] = {}
        self.prompts: dict[str, list[str]] = {}
        self.lock = threading.Lock()

    def _count(self, what: str, text: str) -> None:
        with self.lock:
            self.calls[what] = self.calls.get(what, 0) + 1
            self.prompts.setdefault(what, []).append(text)

    def __call__(self, messages):
        system, user = messages[0].content, messages[-1].content
        if "presentation designer" in system:
            key = self.by_title.get(re.search(r"Heading of this slide: «(.+?)»", user).group(1).strip())
            if "A reviewer found problems" in user:
                self._count("revise", user)
                return self.rec["revise"].get(key) or self.rec["designer"][key]
            self._count("designer", user)
            return self.rec["designer"][key]
        if "strict reviewer" in system:
            self._count("critic", user)
            name = NAMES.get(re.search(r"The plan of the variant «(.+?)»", user).group(1))
            return self.rec["critic"].get(name) or self.rec["critic"]["structured"]
        self._count("other", user)
        return {"facts": [], "series": [], "tables": [], "charts": []}


def _replay(which: str):
    rec = RECORDED[which]
    text = SHORT if which == "short" else LONG
    script = Replay(rec, text)
    p = MockProvider(script, model="replay")
    reg = ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=6, time_budget_s=210))
    events: list = []
    res = A.run_agent(parse_brief_text(text), None, list(load_strategies().values()), skills=SkillsRegistry.load(), providers=reg, progress=events.append)
    return res, events, script


@pytest.fixture(scope="module")
def short_run():
    return _replay("short")


@pytest.fixture(scope="module")
def long_run():
    return _replay("long")


def _content(o) -> list:
    return [s for s in o.slides if s.kind not in FRAMES]


def _spec(o, n: int):
    return next(s for s in o.slides if s.spec_ref == n)


def _visible(s) -> str:
    return A._visible_text(s)


# ------------------------------------------------------------------ the replayed decks, read by an editor


def test_the_replayed_decks_keep_the_users_slides(short_run, long_run):
    for res, n in ((short_run[0], 6), (long_run[0], 10)):
        assert set(res.outlines) == {"structured", "visual", "compact"}
        for o in res.outlines.values():
            assert len(o.slides) == n and o.planned_by == "agent"
            refs = [s.spec_ref for s in o.slides if s.spec_ref is not None]
            assert refs == sorted(refs)


def test_notes_are_never_cut_into_broken_grammar(short_run, long_run):
    # the live run had «…25% — на десерты и выпечку — на чай и другие напитки» (15% taken for another item's figure)
    for o in short_run[0].outlines.values():
        notes = _spec(o, 1).notes
        assert "15% — на чай и другие напитки" in notes, notes
    for res in (short_run[0], long_run[0]):
        for o in res.outlines.values():
            for s in o.slides:
                for text in [s.notes or "", s.takeaway or "", *s.content.bullets]:
                    assert not re.search(r"\s[—–]\s(?:на|в)\s[^\d.;,]*\s[—–]\s(?:на|в)\s", text), text  # «X — на A — на B»
                    assert not re.search(r"\d%?,\s+(?:достига|объясня|связан)", text), text  # a parenthesis gone, its comma left
                    assert not re.search(r"(?:^|[.!?]\s)[а-яё]", text.strip()), text  # a sentence starting lowercase


def test_takeaways_add_to_their_headline_and_never_claim_an_unstated_cause(short_run, long_run):
    for res in (short_run[0], long_run[0]):
        for o in res.outlines.values():
            for s in _content(o):
                if not s.takeaway:
                    continue
                assert not A.adds_nothing(s.takeaway, s.headline), (s.headline, s.takeaway)
                assert A.takeaway_states(s.takeaway), s.takeaway
                assert not re.search(r"снижает|повышает|объясняется|приводит", s.takeaway), s.takeaway
    # «Рост выручки на 26,5% за 6 месяцев» under «Выручка вырастет на 26,5% за 6 месяцев» → the source's own result
    s = _spec(short_run[0].outlines["structured"], 4)
    assert s.takeaway == "На запуск изменений потребуется 180 000 рублей", s.takeaway
    # the critic's «Неравномерное распределение расходов снижает операционную прибыль до 13,3%» → the brief's sentence
    s = _spec(short_run[0].outlines["structured"], 2)
    assert s.takeaway and "120 000" in s.takeaway and "снижает" not in s.takeaway


def test_no_line_repeats_the_footnote_the_takeaway_the_headline_or_the_chart(short_run, long_run):
    for res in (short_run[0], long_run[0]):
        for o in res.outlines.values():
            for s in _content(o):
                c = s.content
                vals = [v for ch in (c.chart, c.chart2) if ch is not None for sr in ch.series for v in sr.values]
                for b in c.bullets:
                    assert not A.same_caveat(b, s.footnote), (b, s.footnote)  # «Результат не гарантирован» / «Прогноз …»
                    assert not (s.takeaway and A.adds_nothing(s.takeaway, b)), (b, s.takeaway)  # the takeaway says more than any line
                    assert not A.adds_nothing(b, s.headline), (b, s.headline)
                    figs = A._plain_figures(b)
                    assert not (vals and figs and all(any(abs(v - x) < 1e-6 for x in vals) for v in figs)), (b, vals)


def test_every_slide_of_the_long_brief_has_its_conclusion_and_its_key_figures(long_run):
    # «На каждом слайде должен быть содержательный заголовок и короткий вывод»
    for o in long_run[0].outlines.values():
        for s in _content(o):
            assert s.takeaway or s.spec_ref == 6, (s.spec_ref, s.headline)  # 6: every sentence of its source is on it
        costs = _spec(o, 3)
        shown = _visible(costs)
        for fig in ("780 000", "120 000", "13,3%"):
            assert fig in shown, (fig, shown)
        assert costs.content.chart is not None and costs.content.chart.type == "pie"


def test_the_cover_shows_the_briefs_goal_and_the_formula_names_its_factors(long_run):
    for o in long_run[0].outlines.values():
        cover = o.slides[0]
        assert cover.kind == K.title
        assert cover.content.paragraphs[:1] == ["Цель: увеличить ежемесячную операционную прибыль со 120 000 до 255 000 рублей"]
        f = _spec(o, 2).content.formula
        assert f == "100 покупок в день × 300 ₽ × 30 рабочих дней = 900 000 ₽", f


def test_a_plan_by_months_is_titled_one_way_and_keeps_every_month(long_run):
    for o in long_run[0].outlines.values():
        s = _spec(o, 8)
        lines = [f"{it.title} — {it.text}" for it in s.content.items] or [b for col in s.content.columns for b in col.bullets if "месяц" in b.lower()]
        titles = [re.match(r"^(\d)-й месяц — ", x) for x in lines]
        assert len(lines) == 6 and all(titles), lines
        assert [int(m.group(1)) for m in titles] == [1, 2, 3, 4, 5, 6]


def test_no_hedge_on_a_rounded_figure(long_run):
    for o in long_run[0].outlines.values():
        for s in o.slides:
            assert "более чем в 2,1" not in s.headline and "почти в 2,1" not in s.headline, s.headline


def test_notes_say_only_what_the_brief_says(short_run, long_run):
    for res in (short_run[0], long_run[0]):
        for o in res.outlines.values():
            for s in o.slides:
                assert "Это позволяет сосредоточиться" not in (s.notes or "")
                assert "наименьшую" not in (s.notes or "")  # «прочие расходы — наименьшую»: 20 000 of marketing is less
                assert "Риски требуют постоянного мониторинга" not in (s.notes or "")


def test_variants_differ_where_the_brief_leaves_the_form_free(long_run, short_run):
    res, events, _ = long_run
    forms = {name: [(s.kind, s.content.chart.type if s.content.chart else None) for s in o.slides] for name, o in res.outlines.items()}
    # (compact differs less since the model's own lists-in-columns stay columns in every variant)
    for name, least in (("visual", 3), ("compact", 1)):
        diff = sum(1 for a, b in zip(forms["structured"], forms[name]) if a != b)
        assert diff >= least, (name, forms[name])
    # the slides whose form the user asked for keep it everywhere: the pie, the table, the formula
    for o in res.outlines.values():
        assert _spec(o, 3).content.chart.type == "pie" and _spec(o, 9).content.table is not None and _spec(o, 2).content.formula
    # the visual variant shows figures big where the brief gives them; the compact one is denser
    assert _spec(res.outlines["visual"], 7).kind == K.stat_row
    assert _spec(res.outlines["compact"], 10).kind in (K.two_column, K.table)
    # the note on similar variants is true: in the short brief every form is dictated
    msgs = [e["message"] for e in short_run[1] if e["step"] == "compile"]
    assert any(m == A.SIMILAR_VARIANTS_RU for m in msgs)
    assert "отличаются подачей" in A.SIMILAR_VARIANTS_RU and "отличаются подачей" in A.SIMILAR_VARIANTS_SOME_RU


def test_every_figure_of_the_replayed_decks_is_the_briefs(short_run, long_run):
    for res, text in ((short_run[0], SHORT), (long_run[0], LONG)):
        idx = BriefIndex.of(parse_brief_text(text))
        idx.use_structure(read_structure(text))
        for o in res.outlines.values():
            for s in o.slides:
                for line in [s.headline, s.takeaway or "", *s.content.bullets, *s.content.paragraphs, *(f"{n.value} {n.label}" for n in s.content.numbers)]:
                    assert not idx.clean(line).bad, line


# ------------------------------------------------------------------ grounding: a strip never breaks grammar


@pytest.fixture(scope="module")
def short_idx():
    idx = BriefIndex.of(parse_brief_text(SHORT))
    return idx.use_structure(read_structure(SHORT))


@pytest.fixture(scope="module")
def long_idx():
    idx = BriefIndex.of(parse_brief_text(LONG))
    return idx.use_structure(read_structure(LONG))


def test_a_figure_named_after_its_dash_keeps_its_label(short_idx):
    s = "Из них 60% приходится на кофе, 25% — на десерты и выпечку, и 15% — на чай и другие напитки."
    assert short_idx.clean(s).text == s
    # a figure given another item's subject still goes, with its label (never a label without its value)
    assert short_idx.clean("Аренда — 25 000 рублей").text == ""
    assert short_idx.clean("25 000 рублей — на аренду").text == ""


def test_a_dash_joins_a_label_and_its_value(long_idx):
    assert long_idx.clean("Кофе — 60%, десерты и выпечка — 25%, чай и другие напитки — 17%").text == ""
    assert long_idx.clean("Аренда — 120 000 рублей, маркетинг — 20 000 рублей, реклама — 777 рублей").text == "Аренда — 120 000 рублей, маркетинг — 20 000 рублей"
    assert long_idx.clean("Операционная прибыль — 120 000 рублей, или 17% выручки").text == "Операционная прибыль — 120 000 рублей"


def test_a_parenthesis_is_kept_whole_and_a_dropped_one_leaves_no_comma(long_idx):
    s = "Рост выручки на 26,5% (900 000 → 1 138 500 рублей) достигается за счёт покупок."
    assert long_idx.clean(s).text == s  # the figure in brackets is the revenue's, not the purchases'
    out = long_idx.clean("Рост выручки на 26,5% (777 рублей) достигается за счёт покупок.").text
    assert out == "Рост выручки на 26,5% достигается за счёт покупок.", out


def test_notes_keep_a_sentence_only_when_its_beginning_stands(long_idx, short_idx):
    # a clause cut from the middle: the whole sentence goes
    out = _notes(long_idx, "Выручка — 900 000 рублей. Из них 60% приходится на кофе, 25% — на десерты и выпечку.", _Log())
    assert out == "Выручка — 900 000 рублей.", out
    # the last clause went: the beginning stands
    out = _notes(short_idx, "Рост выручки на 26,5% идёт от покупок и среднего чека, а маркетинг даст 777 заказов.", _Log())
    assert out == "Рост выручки на 26,5% идёт от покупок и среднего чека.", out


def test_a_step_title_is_not_a_figure(long_idx):
    for line in ("Месяц 1 — учет показателей и обновление меню", "месяц 3 — программа лояльности", "Квартал 2: запуск"):
        assert not long_idx.clean(line).bad, line
    assert long_idx.clean("В месяц 5 новых клиентов придут из офисов").bad  # inside a sentence it is a figure


def test_a_hedge_on_a_rounded_figure_goes(long_idx):
    assert long_idx.fix_hedges("Прибыль вырастет почти в 2,1 раза") == "Прибыль вырастет в 2,1 раза"
    assert long_idx.fix_hedges("Более чем в 2,1 раза вырастет прибыль") == "В 2,1 раза вырастет прибыль"
    assert long_idx.fix_hedges("Прибыль увеличится более чем в 2 раза") == "Прибыль увеличится более чем в 2 раза"  # 2 is not 2,12 rounded to one decimal


def test_the_cover_lines_are_grounded():
    o = DeckOutline(title="t", slides=[
        OutlineSlide(id="c", kind=K.title, headline="Больше прибыли с каждой чашки", content=SlideContent(paragraphs=["Цель: увеличить ежемесячную операционную прибыль со 120 000 до 255 000 рублей", "Цель: прибыль 999 999 рублей"])),
        OutlineSlide(id="s", kind=K.bullets, headline="Выручка — 900 000 рублей", content=SlideContent(bullets=["Средний чек — 300 рублей", "100 покупок в день"])),
    ])
    g, _ = ground_outline(o, parse_brief_text(LONG))
    assert g.slides[0].content.paragraphs == ["Цель: увеличить ежемесячную операционную прибыль со 120 000 до 255 000 рублей"]


# ------------------------------------------------------------------ compiler: the cover's goal, the formula


def test_the_cover_goal_comes_from_the_cover_the_brief_describes():
    st = read_structure(LONG)
    assert cover_goal(st, 1) == "Цель: увеличить ежемесячную операционную прибыль со 120 000 до 255 000 рублей"
    assert cover_goal(read_structure(SHORT)) is None  # no cover described: no goal line
    brief = parse_brief_text(LONG)
    o = DeckOutline(title="t", slides=[OutlineSlide(id="c", kind=K.title, headline="x", spec_ref=1)] + [
        OutlineSlide(id=f"s{n}", kind=K.bullets, headline=sp.title, spec_ref=n, content=SlideContent(bullets=["Средний чек — 300 рублей"]))
        for n, sp in ((sp.number, sp) for sp in st.specs if sp.number > 1)
    ])
    out, _ = compile_outline(o, st, brief)
    cover = out.slides[0]
    assert cover.content.paragraphs == ["Цель: увеличить ежемесячную операционную прибыль со 120 000 до 255 000 рублей"]
    assert any("цель из брифа" in m for m in out.agent_log)


def test_a_formula_names_its_factors_as_the_source_does():
    st = read_structure(LONG)
    sp = next(x for x in st.specs if x.formula)
    f = label_formula(sp.formula, sp.text)
    assert f == "100 покупок в день × 300 ₽ × 30 рабочих дней = 900 000 ₽"
    assert same_formula(f, sp.formula) and not same_formula("100 × 330 × 30 = 990 000 рублей", sp.formula)
    # a factor the source gives no words stays as the formula writes it
    assert label_formula("100 × 300 × 30 = 900 000 рублей", "Ежедневно здесь совершают 100 покупок со средним чеком 300 рублей. За 30 дней выручка составляет 900 000 рублей.") == "100 × 300 ₽ × 30 дней = 900 000 ₽"


# ------------------------------------------------------------------ the designer's answer: takeaway, lines, notes


def _ctx(text: str):
    brief = parse_brief_text(text)
    st = read_structure(text)
    return A._build_ctx(brief, st, A._resolve_facts(None, brief, [], st), None)


def _unit(ctx, n: int):
    return next(u for u in A._units_from_specs(ctx) if u.spec is not None and u.spec.number == n)


def test_a_paraphrase_of_the_headline_is_no_takeaway():
    assert A.adds_nothing("Рост выручки на 26,5% за 6 месяцев", "Выручка вырастет на 26,5% за 6 месяцев")
    assert A.adds_nothing("15 новых покупок в день дадут 148 500 рублей выручки", "Дополнительные 15 покупок в день дадут 148 500 рублей выручки")
    assert not A.adds_nothing("Рентабельность увеличится до 22,4%", "Операционная прибыль вырастет более чем в 2 раза")
    assert not A.adds_nothing("Экономия 22 770 рублей при целевой выручке 1 138 500 рублей", "Снижение доли расходов даст экономию 22 770 рублей")
    ctx = _ctx(SHORT)
    d = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["short"]["designer"]["u4"]), _unit(ctx, 4), ctx)
    assert d.slide.takeaway == "На запуск изменений потребуется 180 000 рублей"
    assert any("repeated the headline" in x for x in d.changes)


def test_a_takeaway_that_is_a_label_or_an_unstated_cause_goes():
    assert not A.takeaway_states("Три ключевых направления для роста прибыли")
    assert A.takeaway_states("Рост постепенный: это прогноз, а не гарантия")
    ctx = _ctx(SHORT)
    unit = _unit(ctx, 2)
    assert A.invented_cause("Неравномерное распределение расходов снижает операционную прибыль до 13,3%", unit.text)
    assert not A.invented_cause("Операционная прибыль составляет 120 000 рублей", unit.text)
    d = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["short"]["revise"]["u2"]), unit, ctx)
    assert d.slide.takeaway and "снижает" not in d.slide.takeaway and "120 000" in d.slide.takeaway


def test_lines_repeating_the_footnote_or_the_chart_go_once_the_form_is_final():
    ctx = _ctx(SHORT)
    unit = _unit(ctx, 4)
    d = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["short"]["designer"]["u4"]), unit, ctx)
    A.enforce_requests(d, ctx)
    A.tidy_design(d, ctx)
    assert not any("гарантир" in b for b in d.slide.content.bullets)  # «Результат не гарантирован» over the footnote
    assert not any("1 138 500" in b for b in d.slide.content.bullets)  # the line chart's own last value («на 6-й месяц»)
    assert A.same_caveat("Результат не гарантирован", "Прогноз не гарантирован")


def test_notes_the_source_does_not_say_go_and_a_copied_context_line_is_no_subtitle():
    ctx = _ctx(SHORT)
    d = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["short"]["designer"]["u2"]), _unit(ctx, 2), ctx)
    assert "наименьшую" not in d.slide.notes and "позволяет" not in d.slide.notes
    assert "780 000" in d.slide.notes  # the source's own sentences instead
    r = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["short"]["revise"]["u1"]), _unit(ctx, 1), ctx)
    assert r.slide.subtitle is None and r.slide.notes.startswith("Кофейня площадью 45 м² рассчитана на 18 посадочных мест")


def test_cards_and_columns_of_the_same_blocks_are_kept_once():
    ctx = _ctx(LONG)
    d = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["long"]["designer"]["u7"]), _unit(ctx, 7), ctx)
    assert d.slide.kind == K.two_column and d.slide.content.columns and not d.slide.content.items


def test_steps_are_titled_as_the_source_titles_them():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 8)
    s = OutlineSlide(id="u8", kind=K.timeline, headline="Разовые вложения — 180 000 рублей", spec_ref=8, content=SlideContent(items=[
        SlideItem(title="", text="Учет показателей и обновление меню"), SlideItem(title="Месяц 2", text="Запуск комбо"),
        SlideItem(title="", text="Программа лояльности"), SlideItem(title="Месяц 4", text="Дневные предложения"),
        SlideItem(title="", text="Корректировка предложений"), SlideItem(title="Месяц 6", text="Оценка результатов"),
    ]))
    d = A._Design(unit=unit, slide=s, by="model")
    A._uniform_steps(d)
    assert [it.title for it in s.content.items] == [f"{i}-й месяц" for i in range(1, 7)]
    assert s.content.items[0].text == "Учет показателей и обновление меню"


# ------------------------------------------------------------------ coverage, the revision, the safety net


def test_the_key_figures_of_a_slide_are_the_goal_the_totals_and_the_stated_measures():
    ctx = _ctx(LONG)
    assert A.key_lines(_unit(ctx, 3).text) == ["Общие расходы — 780 000 рублей", "Операционная прибыль — 120 000 рублей", "Операционная рентабельность — 13,3%"]
    assert A.key_lines(_unit(ctx, 5).text)[0].startswith("Цель — поднять средний чек с 300 до 330 рублей")
    sctx = _ctx(SHORT)
    keys = A.key_lines(_unit(sctx, 5).text)
    assert not any(k.startswith("При выручке") for k in keys)  # a calculation's detail, not a key figure


def test_coverage_lists_every_missing_key_figure_and_the_missing_conclusion():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 3)
    s = OutlineSlide(id="u3", kind=K.chart, headline="Общие расходы — 780 000 рублей в месяц", spec_ref=3, content=SlideContent(chart={
        "type": "pie", "unit": "₽", "categories": ["Продукты", "Зарплаты"], "series": [{"name": "Расходы", "values": [315000, 270000]}]}))
    gaps = A.slide_gaps(A._Design(unit=unit, slide=s, by="model"), ctx)
    kinds = [k for k, _ in gaps]
    key = next(t for k, t in gaps if k == "key")
    assert "120 000" in key and "13,3%" in key and "780 000" not in key
    assert "takeaway" in kinds  # «…и короткий вывод» on every slide


def test_a_revision_is_taken_part_by_part():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 4)
    first = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["long"]["designer"]["u4"]), unit, ctx)
    revised = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["long"]["revise"]["u4"]), unit, ctx)
    merged, why = A.merge_revision(first, revised, ctx)
    assert merged is not None
    # the revision added a missing observation (its content is better), its headline announced a list (worse)
    assert len(merged.slide.content.items) == 4 and merged.slide.headline == first.slide.headline
    assert any("headline" in w for w in why)


def test_the_safety_net_adds_the_briefs_conclusion_and_key_figures():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 3)
    s = OutlineSlide(id="u3", kind=K.chart, headline="Общие расходы — 780 000 рублей в месяц", spec_ref=3, content=SlideContent(chart={
        "type": "pie", "unit": "₽", "categories": ["Продукты", "Зарплаты"], "series": [{"name": "Расходы", "values": [315000, 270000]}]}))
    said = A.complete_slide(s, unit, ctx)
    assert s.takeaway == "Операционная прибыль — 120 000 рублей" and s.content.bullets == ["Операционная рентабельность — 13,3%"]
    assert said
    # nothing is added when the brief does not ask for a conclusion on every slide and the key figures are shown
    sctx = _ctx(SHORT)
    shown = OutlineSlide(id="u1", kind=K.bullets, headline="Выручка — 900 000 рублей", spec_ref=1, content=SlideContent(bullets=["Кофе — 60%"]))
    assert A.complete_slide(shown, _unit(sctx, 1), sctx) == [] and shown.takeaway is None
    assert A.takeaway_rule(read_structure(LONG)) and not A.takeaway_rule(read_structure(SHORT), SHORT)


# ------------------------------------------------------------------ variants: denser and more visual forms


def test_changes_become_a_table_and_cards_of_figures_a_row():
    s = OutlineSlide(id="x", kind=K.stat_row, headline="Средний чек вырастет на 10%", content=SlideContent(
        numbers=[NumberCallout(value="300 → 330 ₽", label="Средний чек"), NumberCallout(value="20% → 30%", label="Доля чеков с едой")],
        bullets=["Комбо", "Добавки к напиткам"]))
    t = A.reshape(s, "table")
    assert t.kind == K.table and t.content.table.columns == ["Показатель", "Сейчас", "Цель"]
    assert t.content.table.rows == [["Средний чек", "300 ₽", "330 ₽"], ["Доля чеков с едой", "20%", "30%"]] and t.content.bullets == ["Комбо", "Добавки к напиткам"]
    cards = OutlineSlide(id="y", kind=K.cards, headline="h", content=SlideContent(items=[
        SlideItem(title="Средний чек", text="Только 20% чеков содержат еду"), SlideItem(title="Потери", text="27 000 рублей в месяц")]))
    r = A.reshape(cards, "stat_row")
    assert r.kind == K.stat_row and [n.value for n in r.content.numbers] == ["20%", "27 000 ₽"]
    assert r.content.numbers[0].label == "чеков содержат еду" and r.content.numbers[1].label == "Потери, в месяц"


def test_the_designer_prompts_carry_the_editors_rules():
    skills = SkillsRegistry.load()
    designer = skills.get("slide_designer")
    critic = skills.get("design_critic")
    assert designer.version == "1.3.2" and critic.version == "1.3.1"
    text = (Path(__file__).resolve().parents[2] / "skills" / "slide_designer" / "prompts" / "system.md").read_text(encoding="utf-8")
    for rule in ("распределены неравномерно", "never the headline in other words", "ALL its items", "names its factors", "titled the same way", "no cause, effect or classification"):
        assert rule.lower() in text.lower(), rule
    crit = (Path(__file__).resolve().parents[2] / "skills" / "design_critic" / "prompts" / "system.md").read_text(encoding="utf-8")
    assert "never a list announced" in crit and "never a cause" in crit


# ------------------------------------------------------------------ what the first live runs of the new agent showed


def test_a_takeaway_cut_to_its_condition_is_no_conclusion():
    assert not A.takeaway_states("Дополнительные покупки при среднем чеке 330 ₽")
    assert A.takeaway_states("Экономия 22 770 рублей при целевой выручке 1 138 500 рублей")
    assert A.takeaway_states("Маркетинговый бюджет вырастет на 15 000 ₽ в месяц")


def test_figures_labelled_only_now_and_target_take_their_measures():
    ctx = _ctx(LONG)
    ans = SlideDesignAnswer.model_validate({
        "kind": "stat_row", "headline": "Средний чек вырастет на 10% — до 330 ₽", "takeaway": "Рост на 30 ₽ даст 90 000 ₽ дополнительной выручки в месяц",
        "numbers": [{"value": "300", "label": "Сейчас"}, {"value": "330", "label": "Цель"}, {"value": "20%", "label": "Сейчас"}, {"value": "30%", "label": "Цель"}],
        "bullets": ["Добавить комбо «капучино + круассан» за 390 ₽", "Разместить десерты рядом с кассой"],
    })
    d = A.design_from_answer(ans, _unit(ctx, 5), ctx)
    assert [(n.value, n.label) for n in d.slide.content.numbers] == [("300 → 330 ₽", "Средний чек"), ("20% → 30%", "Доля чеков с едой")]


def test_the_critics_harmful_fixes_are_not_acted_on():
    ctx = _ctx(LONG)
    u9, u6 = _unit(ctx, 9), _unit(ctx, 6)
    s = OutlineSlide(id="x", kind=K.table, headline="Операционная прибыль вырастет в 2,1 раза")
    assert A._harmful_fix("Заголовок не совпадает с требуемым выводом", "«Выручка увеличивается на 26,5%, а ежемесячная операционная прибыль — примерно на 112%»", s, u9)
    assert A._harmful_fix("Заголовок — это вывод, а не тема", "«Как привлечь больше гостей в свободные часы»", s, u6)
    assert A._harmful_fix("Заголовок без цифры", "«Три направления для увеличения прибыли»", s, u6)
    assert A._harmful_fix("Вывод не отражает мысль", "«Операционная прибыль вырастет в 2,1 раза»", s, u9)
    assert A._harmful_fix("Заголовок без цифры", "«Неравномерные расходы снижают прибыль до 13,3%»", s, _unit(ctx, 3))
    assert A._harmful_fix("Заголовок без цифры", "«Продукты и зарплаты — три четверти расходов»", s, _unit(ctx, 3)) is None


def test_a_revision_that_is_no_better_as_a_headline_keeps_the_first_one_unless_it_announced_a_list():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 10)
    cols = SlideContent(columns=[
        SlideItem(title="Показатели", bullets=["Количество покупок в день", "Средний чек", "Доля чеков с едой", "Доля переменных расходов в выручке", "Операционная прибыль за месяц"]),
        SlideItem(title="Основные риски", bullets=["Слабый отклик на предложения", "Рост закупочных цен", "Перегрузка сотрудников"]),
        SlideItem(title="Меры", bullets=["Тестировать акции небольшими запусками", "Сравнивать поставщиков", "Корректировать графики смен"]),
    ])
    first = A._Design(unit=unit, slide=OutlineSlide(id="u10", kind=K.two_column, headline="Три ключевых фактора для роста прибыли", spec_ref=10, content=cols), by="model")
    topic = A._Design(unit=unit, slide=OutlineSlide(id="u10", kind=K.two_column, headline="Что контролировать каждую неделю", spec_ref=10, content=cols.model_copy(deep=True)), by="model")
    merged, _ = A.merge_revision(first, topic, ctx)
    assert merged.slide.headline == "Что контролировать каждую неделю"  # a list announced is the worse of the two
    merged, _ = A.merge_revision(topic, first, ctx)
    assert merged.slide.headline == "Что контролировать каждую неделю"


def test_a_list_the_model_left_out_twice_is_put_on_the_slide():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 7)
    s = OutlineSlide(id="u7", kind=K.chart, headline="Доля расходов снизится с 35% до 33%", spec_ref=7, takeaway="Снижение на 2 п. п. даст экономию 22 770 ₽ в месяц", content=SlideContent(
        chart={"type": "column", "unit": "%", "categories": ["Текущая доля", "Цель"], "series": [{"name": "Доля расходов", "values": [35, 33]}]},
        bullets=["Целевое снижение списаний — с 27 000 до 15 000 ₽ в месяц", "Экономия от снижения доли расходов — 22 770 ₽ при выручке 1 138 500 ₽"]))
    said = A.complete_slide(s, unit, ctx)
    assert s.kind == K.stat_row and [n.value for n in s.content.numbers] == ["35% → 33%", "27 000 → 15 000 ₽"]
    assert "Ежедневный учет остатков" in s.content.bullets and "Пересмотр закупочных цен" in s.content.bullets
    assert any("22 770" in b for b in s.content.bullets) and said
    # one item left out under cards: a line under them
    u4 = _unit(ctx, 4)
    cards = OutlineSlide(id="u4", kind=K.cards, headline="Средний чек, свободные часы и списания — три барьера роста", spec_ref=4, takeaway="Утренние часы приносят 65% покупок", content=SlideContent(items=[
        SlideItem(title="Средний чек", text="Только 20% чеков содержат еду"), SlideItem(title="Свободные часы", text="После 15:00 занято 4 из 18 мест"),
        SlideItem(title="Потери", text="Списания продуктов — 27 000 ₽ в месяц")]))
    A.complete_slide(cards, u4, ctx)
    assert cards.content.bullets == ["Доля покупателей, вернувшихся в течение 30 дней, — 25%"]


def test_a_budget_slide_without_a_conclusion_gets_its_largest_item():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 8)
    s = OutlineSlide(id="u8", kind=K.two_column, headline="Разовые вложения составляют 180 000 рублей", spec_ref=8, content=SlideContent(columns=[
        SlideItem(title="Разовые вложения", bullets=["Витрина для десертов — 70 000 ₽", "Резерв — 30 000 ₽"]),
        SlideItem(title="План", bullets=[f"{i}-й месяц — шаг" for i in range(1, 7)])]))
    A.complete_slide(s, unit, ctx)
    assert s.takeaway == "Крупнейшая статья — витрина для десертов: 70 000 рублей"


def test_another_slides_figures_never_land_on_a_slide():
    # a reviewer's note sent to the wrong slide made the designer write the profit slide's figures on the slide of the
    # investments: «Операционная прибыль вырастет на 112,3% за 6 месяцев»
    ctx = _ctx(SHORT)
    unit = _unit(ctx, 4)
    assert A.foreign_figures("Операционная прибыль вырастет на 112,3% за 6 месяцев", unit, ctx) == ["112,3%"]
    assert A.foreign_figures("Выручка вырастет на 26,5% за 6 месяцев", unit, ctx) == []  # derived from its own forecast
    assert A.foreign_figures("30 000 рублей останется в резерве", _unit(ctx, 3), ctx) == ["30 000 рублей"]
    ans = SlideDesignAnswer.model_validate({
        "kind": "chart", "headline": "Операционная прибыль вырастет на 112,3% за 6 месяцев",
        "chart": {"type": "line", "unit": "₽", "categories": ["Сейчас", "1-й месяц"], "series": [{"name": "Выручка", "values": [900000, 930000]}]},
        "bullets": ["Рост выручки на 26,5% — с 900 000 до 1 138 500 рублей", "Рентабельность вырастет с 13,3% до 22,4%"],
        "takeaway": "Операционная прибыль вырастет на 112,3% — с 120 000 до 254 795 рублей",
    })
    d = A.design_from_answer(ans, unit, ctx)
    A.enforce_requests(d, ctx)
    A.tidy_design(d, ctx)
    assert "112,3" not in d.slide.headline and "112,3" not in (d.slide.takeaway or "")
    assert d.slide.content.bullets == ["Рост выручки на 26,5% — с 900 000 до 1 138 500 рублей"]


def test_a_critics_note_on_invented_or_foreign_figures_is_not_acted_on():
    ctx = _ctx(SHORT)
    s = OutlineSlide(id="x", kind=K.chart, headline="h")
    wrong = "Прогноз указан как 1 138 500 рублей, но рост на 26,5% соответствует 1 134 000 рублей от 900 000."
    assert A._harmful_fix(wrong, "Исправить процент роста", s, _unit(ctx, 4), ctx) == "the note rests on figures the brief does not give"
    assert A._harmful_fix("Нет резерва", "Добавить: «30 000 рублей останется в резерве»", s, _unit(ctx, 3), ctx) == "the fix brings another slide's figures"
    assert A._harmful_fix("Вывод повторяет диаграмму", "«Кофе составляет большую часть выручки — 60%, десерты и выпечка — 25%»", s, _unit(ctx, 1), ctx) is None


def test_a_takeaway_repeating_the_formula_or_the_cards_goes():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 2)
    s = OutlineSlide(id="u2", kind=K.big_number, headline="Месячная выручка — 900 000 рублей", spec_ref=2, takeaway="100 покупок в день × 300 ₽ × 30 дней",
                     content=SlideContent(formula="100 покупок в день × 300 ₽ × 30 рабочих дней = 900 000 ₽"))
    assert A.takeaway_ok(s.takeaway, s, unit, ctx) == "repeats the slide's block"
    s.takeaway = None
    A.complete_slide(s, unit, ctx)
    assert s.takeaway == "3 000 покупок в месяц"  # a fact of the brief the slide does not show


def test_a_slides_own_derived_figures_are_its_own():
    ctx = _ctx(LONG)
    assert A.foreign_figures("Операционная прибыль вырастет в 2,1 раза", _unit(ctx, 9), ctx) == []  # its table's row
    assert A.foreign_figures("Число покупок вырастет на 15% — до 115 в день", _unit(ctx, 6), ctx) == []
    assert A.foreign_figures("Прибыль вырастет в 2,1 раза", _unit(ctx, 6), ctx) == ["2,1 раза"]


def test_a_period_is_no_new_figure_and_the_business_result_is_a_key_figure():
    assert A.adds_nothing("Прибыль вырастет более чем в 2 раза за 6 месяцев", "Операционная прибыль вырастет более чем в 2 раза")
    assert not A.adds_nothing("Рост выручки на 26,5% за 6 месяцев при вложениях 180 000 ₽", "Выручка вырастет на 26,5% за 6 месяцев")
    ctx = _ctx(LONG)
    keys = A.key_lines(_unit(ctx, 6).text)
    assert "Дополнительные 15 покупок в день при среднем чеке 330 рублей дадут 148 500 рублей выручки за 30 дней" in keys
    assert not any("эти расходы" in k for k in A.key_lines(_unit(_ctx(SHORT), 5).text))


def test_the_last_editors_pass_of_the_live_runs():
    ctx = _ctx(LONG)
    # a card as a line: the text after the dash continues the title
    assert A._title_text(SlideItem(title="Партнёрства", text="С пятью ближайшими офисами")) == "Партнёрства — с пятью ближайшими офисами"
    # «900 000 · руб.» next to the formula that shows 900 000
    u2 = _unit(ctx, 2)
    d = A._Design(unit=u2, slide=OutlineSlide(id="u2", kind=K.big_number, headline="Месячная выручка — 900 000 рублей", spec_ref=2, content=SlideContent(
        numbers=[NumberCallout(value="900 000", label="руб.")], formula="100 покупок в день × 300 ₽ × 30 рабочих дней = 900 000 ₽")), by="model")
    A.tidy_design(d, ctx)
    assert not d.slide.content.numbers and d.slide.content.formula
    # a headline that is the user's own conclusion in other words gives way to the user's heading
    u10 = _unit(ctx, 10)
    d10 = A._Design(unit=u10, slide=OutlineSlide(id="u10", kind=K.bullets, headline="Рост прибыли зависит от покупок, среднего чека и потерь", spec_ref=10,
                                                  content=SlideContent(bullets=["Количество покупок в день", "Средний чек"])), by="model")
    A.enforce_requests(d10, ctx)
    assert d10.slide.headline == "Что контролировать каждую неделю" and d10.slide.takeaway.startswith("Рост прибыли зависит от трех")
    # notes about the making of the deck, and lines with words the brief never uses
    assert A.clean_notes("Рост прибыли зависит от покупок — вывод сделан на основе текста брифа.", u10, [], ctx, []) == ""
    sctx = _ctx(SHORT)
    assert A._unbriefed_words("Аренда и зарплаты — основные постоянные расходы", sctx) == ["постоянн"]
    assert A._unbriefed_words("Продукты и зарплаты — основные статьи расходов", sctx) == []
    # a budget left out whole goes under the plan's timeline
    u8 = _unit(ctx, 8)
    tl = OutlineSlide(id="u8", kind=K.timeline, headline="180 000 рублей на запуск", spec_ref=8, takeaway="Разовые вложения — отдельно от ежемесячных расходов",
                      content=SlideContent(items=[SlideItem(title=f"{i}-й месяц", text="Шаг") for i in range(1, 7)]))
    A.complete_slide(tl, u8, ctx)
    assert tl.content.bullets[:1] == ["Витрина для десертов — 70 000 рублей"] and len(tl.content.bullets) == 5


def test_the_final_live_run_details():
    ctx = _ctx(LONG)
    # «330 · ₽» and «30% · Цель — доля чеков с едой»: the changes of their measures
    d = A.design_from_answer(SlideDesignAnswer.model_validate({
        "kind": "stat_row", "headline": "Средний чек вырастет на 10% — до 330 ₽", "bullets": ["Добавить комбо «капучино + круассан» за 390 ₽"],
        "numbers": [{"value": "330", "label": "₽"}, {"value": "30%", "label": "Цель — доля чеков с едой"}]}), _unit(ctx, 5), ctx)
    assert [n.value for n in d.slide.content.numbers] == ["300 → 330 ₽", "20% → 30%"]
    # a line of a figure is shown by its figure, not by two of its words elsewhere on the slide
    shown = A._Shown("65% покупок приходится на утренние часы, доля еды в чеках — 20%")
    assert not shown.line("Доля покупателей, вернувшихся в течение 30 дней, — 25%")
    assert shown.line("65% покупок приходится на утренние часы с 08:00 до 11:00")
    # cards as lines: «title — text», the text continuing the title
    s = OutlineSlide(id="x", kind=K.cards, headline="h", content=SlideContent(items=[SlideItem(title="Партнёрства", text="С пятью ближайшими офисами"), SlideItem(title="Продвижение", text="В районных сообществах")]))
    assert A.reshape(s, "bullets").content.bullets == ["Партнёрства — с пятью ближайшими офисами", "Продвижение — в районных сообществах"]


# ------------------------------------------------------------------ the coordinator's review of tq_long5 / tq_short3


def test_a_callout_label_is_never_a_unit_nor_a_target_prefix_and_shows_its_change():
    # the live answer of tq_long5, slide 5: «330» · «Средний чек, ₽» and «30%» · «Цель — доля чеков с едой»; polish_plan
    # then cut the label to «₽» (label_beside took the unit after 330 in the headline for the figure's words)
    ctx = _ctx(LONG)
    ans = SlideDesignAnswer.model_validate({
        "kind": "stat_row", "headline": "Средний чек вырастет на 10% — до 330 ₽",
        "bullets": ["Добавить комбо «капучино + круассан» за 390 ₽", "Предложить добавки к напиткам за 40–60 ₽", "Разместить десерты рядом с кассой", "Обучить сотрудников предлагать еду к напитку"],
        "numbers": [{"value": "330", "label": "Средний чек, ₽"}, {"value": "30%", "label": "Цель — доля чеков с едой"}],
        "takeaway": "Дополнительная выручка — 90 000 ₽ в месяц при 3 000 покупках",
    })
    d = A.design_from_answer(ans, _unit(ctx, 5), ctx)
    assert [(n.value, n.label) for n in d.slide.content.numbers] == [("300 → 330 ₽", "Средний чек"), ("20% → 30%", "Доля чеков с едой")]
    from verstka.planning import heuristics as H

    assert H.label_beside("330", "Средний чек, ₽", "Средний чек вырастет на 10% — до 330 ₽") == "Средний чек, ₽"  # never «₽»
    # a figure with no pair in the slide's data: its unit goes to the value, the label keeps the measure
    fixed = A.fix_callouts([NumberCallout(value="180 000", label="Бюджет запуска, ₽")], _unit(ctx, 8), ctx)
    assert [(n.value, n.label) for n in fixed] == [("180 000 ₽", "Бюджет запуска")]
    # the whole agent on this answer: the outline keeps the changes (polish_plan does not cut the labels)
    rec = {"designer": dict(RECORDED["long"]["designer"]), "revise": {}, "critic": {}}
    rec["designer"]["u5"] = ans.model_dump()
    rec["designer"]["u5"]["numbers"] = [{"value": "330", "label": "Средний чек, ₽"}, {"value": "30%", "label": "Цель — доля чеков с едой"}]
    script = Replay(rec, LONG)
    p = MockProvider(script, model="replay")
    reg = ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=6, time_budget_s=210))
    res = A.run_agent(parse_brief_text(LONG), None, list(load_strategies().values()), skills=SkillsRegistry.load(), providers=reg, critic=False)
    for o in res.outlines.values():
        s5 = _spec(o, 5)
        labels = [n.label for n in s5.content.numbers]
        assert all(l and not re.fullmatch(r"₽|%|руб\.?", l) and not l.lower().startswith(("цель", "сейчас")) for l in labels), labels
        shown = _visible(s5)
        assert "300 → 330 ₽" in shown or "300 ₽" in shown, shown


def test_the_text_after_a_colon_or_under_a_cards_title_starts_in_lowercase():
    s = OutlineSlide(id="x", kind=K.bullets, headline="h", takeaway="Итог: Больше покупок", content=SlideContent(
        bullets=["Партнёрства: С пятью ближайшими офисами", "Дневные предложения: С 15:00 до 18:00", "Меры: Ежедневный учет остатков",
                 "Партнёр: VK Tech", "Метрика: NPS 64", "Кофейня: «Точка кофе»"],
        items=[SlideItem(title="Дневные предложения", text="С 15:00 до 18:00"), SlideItem(title="Средний чек", text="Только 20% чеков содержат еду")]))
    A.polish_case(s, LONG)
    assert s.content.bullets == ["Партнёрства: с пятью ближайшими офисами", "Дневные предложения: с 15:00 до 18:00", "Меры: ежедневный учет остатков",
                                 "Партнёр: VK Tech", "Метрика: NPS 64", "Кофейня: «Точка кофе»"]
    assert [it.text for it in s.content.items] == ["с 15:00 до 18:00", "Только 20% чеков содержат еду"]
    assert s.takeaway == "Итог: больше покупок"
    # the recorded card answer of tq_long5, slide 6, through the designer and the variants
    ctx = _ctx(LONG)
    ans = SlideDesignAnswer.model_validate({"kind": "cards", "headline": "15 новых покупок в день дадут 148 500 ₽ выручки", "items": [
        {"title": "Партнёрства", "text": "С пятью ближайшими офисами"}, {"title": "Программа лояльности", "text": "С понятными условиями"},
        {"title": "Продвижение", "text": "В районных сообществах"}, {"title": "Дневные предложения", "text": "С 15:00 до 18:00"}],
        "takeaway": "План увеличит число покупок до 115 в день"})
    d = A.design_from_answer(ans, _unit(ctx, 6), ctx)
    A.enforce_requests(d, ctx)
    A.tidy_design(d, ctx)
    assert [it.text for it in d.slide.content.items] == ["с пятью ближайшими офисами", "с понятными условиями", "в районных сообществах", "с 15:00 до 18:00"]
    b = A.reshape(d.slide, "bullets")
    assert b.content.bullets[0] == "Партнёрства — с пятью ближайшими офисами"


def test_a_line_beside_a_chart_says_its_own_figure_plainly():
    # tq_short3, slide 6: «Операционная прибыль вырастет до 254 795 рублей в месяц — это 112,3% роста» over the columns
    ctx = _ctx(SHORT)
    ans = SlideDesignAnswer.model_validate({
        "kind": "chart", "headline": "Операционная прибыль вырастет в 2,1 раза", "bullets": ["Рентабельность увеличится до 22,4%"],
        "chart": {"type": "column", "unit": "₽", "categories": ["Текущая", "Прогноз"], "series": [{"name": "Операционная прибыль", "values": [120000, 254795]}]},
        "takeaway": "Операционная прибыль вырастет до 254 795 рублей в месяц — это 112,3% роста",
    })
    d = A.design_from_answer(ans, _unit(ctx, 5), ctx)
    A.enforce_requests(d, ctx)
    A.tidy_design(d, ctx)
    assert d.slide.takeaway == "Рост на 112,3%", d.slide.takeaway
    assert A.plain_change("Выручка вырастет на 12% роста выручки") == "Выручка вырастет на 12% роста выручки"  # not a clause's end


def test_what_the_confirming_live_run_still_showed():
    # tq_long6 visual slide 4: cards turned into a row of figures had labels «Потери: Списания продуктов в месяц», «Покупок»
    assert A.line_figure("Потери: Списания продуктов — 27 000 ₽ в месяц") == NumberCallout(value="27 000 ₽", label="Списания продуктов в месяц")
    assert A.line_figure("Средний чек: Только 20% чеков содержат еду") == NumberCallout(value="20%", label="чеков содержат еду")
    assert A.line_figure("65% покупок приходится на утренние часы с 08:00 до 11:00") is None  # no one-word «Покупок»
    assert A.line_figure("Свободные часы: Пик нагрузки — с 08:00 до 11:00") is None  # times are no value
    assert A.line_figure("Доля покупателей, вернувшихся в течение 30 дней, — 25%").value == "25%"
    # a name keeps its capital after a colon; a common word (the brief writes it in lowercase) does not
    assert not A._lowered("Точка", LONG) and A._lowered("Больше", LONG) and A._lowered("Пик", LONG)
    assert not A._lowered("Москва", "Кофейня в Москве работает с 8 утра")
    # tq_short4 slide 5: «Прогноз роста выручки и распределение вложений показаны графически» — about the slide
    ctx = _ctx(SHORT)
    s = OutlineSlide(id="u4", kind=K.chart, headline="Выручка вырастет на 26,5% за 6 месяцев", spec_ref=4,
                     takeaway="Прогноз роста выручки и распределение вложений показаны графически", content=SlideContent(bullets=["Прогноз не гарантирует результата"]))
    assert A.takeaway_ok(s.takeaway, s, _unit(ctx, 4), ctx) == "speaks of the slide, not of the subject"
    d = A._Design(unit=_unit(ctx, 4), slide=s, by="model")
    A.tidy_design(d, ctx)
    assert d.slide.takeaway == "На запуск изменений потребуется 180 000 рублей"
    # tq_short4 slide 6: «… до 254 795 рублей в месяц (+112,3%)» beside the columns 120 000 and 254 795
    from verstka.schemas.outline import ChartSpec

    ch = ChartSpec(type="column", unit="₽", categories=["Текущая", "Прогноз"], series=[{"name": "Операционная прибыль", "values": [120000, 254795]}])
    assert A.trim_chart_restatement("Операционная прибыль вырастет до 254 795 рублей в месяц (+112,3%)", [ch]) == "Рост на 112,3%"


def test_a_takeaway_that_prescribes_or_restates_with_a_condition():
    ctx = _ctx(SHORT)
    # tq_short5, slide 3: «Низкая рентабельность (13,3%) требует оптимизации расходов» — a need the brief does not state
    assert A.invented_cause("Низкая рентабельность (13,3%) требует оптимизации расходов", _unit(ctx, 2).text)
    # tq_long7, slide 7: the headline again, with a condition — replaced when the source has a result, else kept
    lctx = _ctx(LONG)
    s = OutlineSlide(id="u7", kind=K.bullets, headline="Экономия 22 770 ₽ в месяц от снижения потерь", spec_ref=7,
                     takeaway="Экономия от снижения потерь составит 22 770 ₽ в месяц при выручке 1 138 500 ₽", content=SlideContent(bullets=["Контроль порций"]))
    assert A.takeaway_ok(s.takeaway, s, _unit(lctx, 7), lctx) == "repeats the headline with a condition"
    # a vague takeaway whose only figure is a period gives way to a fact of the brief
    u8 = _unit(lctx, 8)
    s8 = OutlineSlide(id="u8", kind=K.table, headline="Разовые вложения составляют 180 000 рублей", spec_ref=8,
                      takeaway="План внедрения охватывает 6 месяцев с поэтапными действиями", content=SlideContent(bullets=["Резерв — 30 000 ₽"]))
    A.complete_slide(s8, u8, lctx)
    assert s8.takeaway == "Крупнейшая статья — витрина для десертов: 70 000 рублей"


# ------------------------------------------------------------------ the integrated server run 20260926-021307-7b5002


def test_the_integrated_run_keeps_slide_8s_lists_and_never_repeats_slide_6s_headline():
    rec = RECORDED["long_integrated"]
    script = Replay(rec, LONG)
    p = MockProvider(script, model="replay")
    reg = ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=6, time_budget_s=210))
    res = A.run_agent(parse_brief_text(LONG), None, list(load_strategies().values()), skills=SkillsRegistry.load(), providers=reg)
    for name, o in res.outlines.items():
        s8 = _spec(o, 8)
        shown = _visible(s8)
        assert "Витрина для десертов" in shown and "6-й месяц" in shown, (name, s8.kind, shown)
        s6 = _spec(o, 6)
        assert not A.same_text(s6.takeaway, s6.headline) and not A.adds_nothing(s6.takeaway or "", s6.headline), (name, s6.headline, s6.takeaway)
        for s in _content(o):
            assert not (s.takeaway and A.adds_nothing(s.takeaway, s.headline)), (name, s.headline, s.takeaway)


def test_lists_given_under_items_become_columns():
    ctx = _ctx(LONG)
    d = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["long_integrated"]["designer"]["u8"]), _unit(ctx, 8), ctx)
    assert d.slide.kind == K.two_column and [(c.title, len(c.bullets)) for c in d.slide.content.columns] == [("Разовые вложения", 5), ("План действий", 6)]
    # a card of a list shows its lines as one line, never its title alone
    assert A._title_text(SlideItem(title="Меры", bullets=["Учёт остатков", "Контроль порций"])) == "Меры: Учёт остатков; Контроль порций"


def test_a_slide_left_with_only_its_lists_titles_gets_the_lists_back():
    ctx = _ctx(LONG)
    s = OutlineSlide(id="u8", kind=K.bullets, headline="Разовые вложения составляют 180 000 ₽", spec_ref=8, content=SlideContent(bullets=["Разовые вложения", "План действий"]))
    said = A._restore_lists(s, _unit(ctx, 8))
    assert said and s.kind == K.two_column
    assert [c.title for c in s.content.columns] == ["Разовые вложения", "План действий"]
    assert s.content.columns[0].bullets[0].startswith("Витрина для десертов") and s.content.columns[1].bullets[0].startswith("1-й месяц")
    # a slide that shows its lists is left alone
    full = OutlineSlide(id="u8", kind=K.bullets, headline="h", spec_ref=8, content=SlideContent(bullets=["Витрина для десертов — 70 000 ₽", "1-й месяц — учет показателей"]))
    assert A._restore_lists(full, _unit(ctx, 8)) == []


def test_a_revision_never_leaves_the_headline_as_the_takeaway():
    ctx = _ctx(LONG)
    unit = _unit(ctx, 6)
    first = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["long_integrated"]["designer"]["u6"]), unit, ctx)
    revised = A.design_from_answer(SlideDesignAnswer.model_validate(RECORDED["long_integrated"]["revise"]["u6"]), unit, ctx)
    merged, why = A.merge_revision(first, revised, ctx)
    assert merged.slide.headline == first.slide.headline  # the revision's «Привлечь больше гостей в день» is no better
    assert merged.slide.takeaway != merged.slide.headline and any("repeated the combined headline" in w for w in why)


def test_the_compiler_has_the_last_word_on_a_takeaway_repeating_its_headline():
    st = read_structure(LONG)
    o = DeckOutline(title="t", slides=[
        OutlineSlide(id="c", kind=K.title, headline="Больше прибыли с каждой чашки", spec_ref=1),
        OutlineSlide(id="s6", kind=K.bullets, spec_ref=6, headline="15 дополнительных покупок в день дадут 148 500 рублей выручки",
                     takeaway="15 дополнительных покупок в день дадут 148 500 рублей выручки", content=SlideContent(bullets=["Партнёрства с пятью ближайшими офисами"])),
        OutlineSlide(id="s10", kind=K.bullets, spec_ref=10, headline="Рост прибыли зависит от трех измеримых изменений: больше покупок, выше средний чек и меньше потерь",
                     takeaway="Рост прибыли зависит от трех измеримых изменений: больше покупок, выше средний чек и меньше потерь", content=SlideContent(bullets=["Средний чек"])),
    ])
    out, warns = compile_outline(o, st, parse_brief_text(LONG))
    s6, s10 = _spec(out, 6), _spec(out, 10)
    assert s6.takeaway is None
    assert s10.headline == "Что контролировать каждую неделю" and s10.takeaway.startswith("Рост прибыли зависит")
    assert any("repeated" in w for w in warns)


def test_a_list_left_out_next_to_another_comes_back():
    # tq_long8: slide 8 showed the plan by months (a timeline; a list in compact) and left out the budget — the takeaway
    # «Крупнейшая статья — витрина для десертов: 70 000 рублей» quoting one of its figures is no list shown
    ctx = _ctx(LONG)
    unit = _unit(ctx, 8)
    months = [f"{i}-й месяц" for i in range(1, 7)]
    texts = ["Учет показателей и обновление меню", "Запуск комбо и обучение сотрудников", "Программа лояльности и партнерства с офисами",
             "Продвижение дневных предложений и настройка закупок", "Корректировка предложений по результатам продаж", "Оценка результатов и закрепление удачных решений"]
    tl = OutlineSlide(id="u8", kind=K.timeline, headline="Бюджет запуска — 180 000 ₽", spec_ref=8, takeaway="Крупнейшая статья — витрина для десертов: 70 000 рублей",
                      content=SlideContent(items=[SlideItem(title=m, text=x) for m, x in zip(months, texts)]))
    A._rescue_lists(tl, unit, ctx)
    assert tl.kind == K.timeline and tl.content.bullets[0] == "Витрина для десертов — 70 000 рублей" and len(tl.content.bullets) == 5
    li = OutlineSlide(id="u8", kind=K.bullets, headline="Бюджет запуска — 180 000 ₽", spec_ref=8, takeaway="Крупнейшая статья — витрина для десертов: 70 000 рублей",
                      content=SlideContent(bullets=[f"{m} — {x[:1].lower() + x[1:]}" for m, x in zip(months, texts)]))
    A._rescue_lists(li, unit, ctx)
    assert li.kind == K.two_column and [(c.title, len(c.bullets)) for c in li.content.columns] == [("Общий бюджет запуска", 5), ("План на 6 месяцев", 6)]
