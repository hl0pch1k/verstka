"""A model plan keeps only what the brief says (verstka.planning.grounding), and a live answer is parsed, not lost.

Regression fixtures: the plans Qwen3-VL-30B (Cloud.ru) made on 2026-09-25 from the create screen's four-line example
brief (tests/fixtures/live_cloudru_*.json): a title copied from the prompt's example («…на 12 тысячах пользователей»),
«12 000 пользователей в пилоте», «NPS вырос до 64%», phases, benefits and recommendations nobody wrote, charts without
data, an empty comparison, a «freeform» slide, «[email@company.com]» on the closing slide — and the structured
variant's answer that was rejected as having «no content slides» (every content slide typed «section»). And plans a
careful model writes in its own words (tests/fixtures/paraphrase_plans.json: synonyms, «с 47 до 29 минут», было/стало,
roundings, dates in another format), which must come through whole.

The checks here are written independently of the grounding code: figures are read with a plain regex and compared as
values with the brief's own figures.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from verstka.planning.brief import load_brief, parse_brief_text
from verstka.planning.facts import basic_facts
from verstka.planning.grounding import BriefIndex, figures, ground_outline
from verstka.planning.outline import basic_outline, plan_outline, target_slide_count, unusable_plan
from verstka.planning.plan_json import ALLOWED_KINDS, PlannedDeckAnswer, normalise_plan
from verstka.planning.strategies import get_strategy
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, PlannedDeck, SlideContent
from verstka.skills_registry.registry import SkillsRegistry

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "fixtures"
BRIEFS = ROOT / "examples" / "briefs"
LIVE = ["structured", "visual", "compact"]

_LIVE = json.loads((FX / "live_cloudru_brief.json").read_text(encoding="utf-8"))
_NUM_RE = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)")
_PCT_RE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s?%")
_PLACEHOLDER_RE = re.compile(r"\[|\]|@|company\.com|example\.com|телефон\]|lorem|XXX|Иван Иванов", re.I)


def _live_brief():
    b = parse_brief_text(_LIVE["text"])
    b.audience = _LIVE["audience"]
    b.slide_count = _LIVE["slide_count"]
    return b


def _live(strategy: str) -> DeckOutline:
    return DeckOutline.model_validate_json((FX / f"live_cloudru_{strategy}.json").read_text(encoding="utf-8"))


def _values(text: str) -> set[float]:
    return {float(re.sub(r"[   ]", "", m).replace(",", ".")) for m in _NUM_RE.findall(text or "")}


def _texts(o: DeckOutline) -> list[str]:
    """Every text a slide shows: the section label is a kicker or a tag on the slide, the caption is under the table."""
    out = [o.title, o.subtitle or ""]
    for s in o.slides:
        c = s.content
        out += [s.headline, s.section or "", s.subtitle or "", s.notes] + c.bullets + c.paragraphs + [f"{n.value} {n.label}" for n in c.numbers]
        out += [f"{i.title} {i.text} {i.number or ''} {' '.join(i.bullets)}" for i in c.items + c.columns]
        if c.table is not None:
            out += c.table.columns + [cell for row in c.table.rows for cell in row] + [c.table.caption or ""]
        if c.chart is not None:
            out += [c.chart.title or ""]
        out += [c.quote or "", c.quote_author or ""]
    return [t for t in out if t]


# the UI brief's figures and the values a person derives from them: 47 − 29 = 18 минут, (47 − 29) / 47 = 38%
UI_VALUES = {47.0, 29.0, 64.0, 14.5}
UI_DERIVED = {18.0, 38.0, 62.0}


def _assert_grounded_live(o: DeckOutline) -> None:
    texts = _texts(o)
    for t in texts:
        assert _values(t) <= UI_VALUES | UI_DERIVED, (t, _values(t) - UI_VALUES - UI_DERIVED)
        # the brief writes no % at all: a share may only be a derived percent change
        assert all(float(v.replace(",", ".")) in UI_DERIVED for v in _PCT_RE.findall(t)), t
        assert not _PLACEHOLDER_RE.search(t), t
        assert "тысяч" not in t and "12 000" not in t, t
    for s in o.slides:
        c = s.content
        assert s.kind.value in ALLOWED_KINDS, s.kind
        assert c.chart is None or all(o.series_by_id(x) for x in c.chart.series_ids), s.id
        assert s.kind != K.chart or (c.chart is not None and c.chart.series_ids), s.id
        if s.kind in (K.two_column, K.comparison):
            assert len([col for col in c.columns if col.bullets or col.text]) >= 2, s.id
        if s.kind in (K.cards, K.process, K.timeline):
            assert len(c.items) >= 2 and all(i.title or i.text for i in c.items), s.id
        if s.kind in (K.big_number, K.stat_row):
            assert c.numbers and (s.kind == K.stat_row) == (len(c.numbers) >= 2), s.id
        assert s.headline.strip(), s.id
    # the deck's title is the brief's: «Например: итоги пилота «Умные сводки» за квартал»
    assert o.title.startswith("Итоги пилота «Умные сводки»"), o.title
    assert o.slides[0].kind == K.title and o.slides[0].headline.startswith("Итоги пилота «Умные сводки»")
    assert o.slides[-1].kind == K.thanks
    heads = " | ".join(s.headline for s in o.slides)
    for invented in ("План масштабирования", "Рекомендации по действию", "Причины запроса бюджета", "Ожидаемые показатели"):
        assert invented not in heads, heads
    # the strategy's skeleton («детали», «план или сроки») is not a label on a slide of a brief that has none of it
    labels = [s.section for s in o.slides if s.section]
    assert not any(x.startswith(("Детали", "План", "Финальный", "Оценка", "Следующие")) for x in labels), labels
    # nothing the brief says is lost: every figure of the brief is still on a slide
    shown = set().union(*[_values(t) for t in texts])
    assert UI_VALUES <= shown, UI_VALUES - shown


# ------------------------------------------------------------------------------------------ the live fixtures


@pytest.mark.parametrize("strategy", LIVE)
def test_the_live_fixtures_had_the_reported_problems(strategy):
    """The fixtures are what the live run produced (the «before» of the report)."""
    o = _live(strategy)
    texts = " | ".join(_texts(o))
    assert "Пилот подтвердил эффект на 12 тысячах пользователей" in texts
    assert re.search(r"64\s?%", texts) and "[" in texts
    assert any(s.kind == K.chart and not o.series for s in o.slides)
    assert len(o.slides) == 12


@pytest.mark.parametrize("strategy", LIVE)
def test_live_plans_come_out_grounded(strategy):
    before = _live(strategy)
    o, warnings = ground_outline(before, _live_brief())
    _assert_grounded_live(o)
    assert 5 <= len(o.slides) < len(before.slides)  # shorter than the target: what the brief supports
    assert any("12 тысячах" in w for w in warnings) and any("placeholders" in w for w in warnings)
    assert all(w.startswith("grounding:") for w in warnings)
    # NPS is points: «64%» → «64», on the slide and in the facts registry
    nps = [n for s in o.slides for n in s.content.numbers if n.value.startswith("64")]
    assert nps and all(n.value == "64" and "%" not in n.label for n in nps)
    assert next(f for f in o.facts if f.value == "64").unit is None


@pytest.mark.parametrize("strategy", LIVE)
def test_grounding_is_idempotent(strategy):
    once, _ = ground_outline(_live(strategy), _live_brief())
    twice, warnings = ground_outline(once, _live_brief())
    assert twice.model_dump() == once.model_dump() and warnings == []


def test_the_live_compact_plan_loses_its_freeform_empty_comparison_and_placeholders():
    o, warnings = ground_outline(_live("compact"), _live_brief())
    assert not any(s.kind == K.comparison for s in o.slides)
    thanks = o.slides[-1]
    assert thanks.subtitle is None  # «Контакты: [email] | [телефон]» — the brief gives no contacts
    assert any("freeform" in w for w in warnings)
    budget = [s for s in o.slides if any(n.value.startswith("14,5") for n in s.content.numbers)]
    assert len(budget) == 1  # the freeform slide repeated the ask's figure: said once


def test_the_live_charts_without_data_are_gone():
    o, warnings = ground_outline(_live("visual"), _live_brief())
    assert not any(s.kind == K.chart for s in o.slides)
    assert any("chart without data" in w for w in warnings)


# ------------------------------------------------------------------------------------------ «no content slides»


def _raw_answers() -> list[str]:
    return json.loads((FX / "live_cloudru_structured_raw.json").read_text(encoding="utf-8"))["answers"]


@pytest.mark.parametrize("i", [0, 1])
def test_a_live_structured_answer_is_parsed_not_rejected(i):
    """The model typed every content slide «section» (and left one without a headline): the answer is read, each such
    slide typed by its content, instead of failing validation or being rejected as «no content slides»."""
    from verstka.providers.openai_compat import extract_json

    raw = extract_json(_raw_answers()[i])
    assert sum(s.get("kind") == "section" for s in raw["slides"]) >= 8
    planned = PlannedDeckAnswer.model_validate(raw)
    assert unusable_plan(planned) is None
    kinds = [s.kind for s in planned.slides]
    assert kinds[0] == K.title and kinds[-1] == K.thanks and K.section not in kinds
    assert all(s.headline or s.section for s in planned.slides)
    agenda = next(s for s in planned.slides if s.kind == K.agenda)
    assert len(agenda.content.items) >= 4 and not agenda.content.bullets  # its bullets are its items
    o = DeckOutline(title=planned.title, slides=planned.slides, facts=_live("visual").facts, planned_by="model")
    grounded, _ = ground_outline(o, _live_brief())
    _assert_grounded_live(grounded)


def _manifest(simple_deck, tmp_path):
    from verstka.analysis.manifest import analyze_template

    return analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)


def test_plan_outline_keeps_the_live_answer_as_the_models_plan(simple_deck, tmp_path):
    answer = _raw_answers()[0]
    providers = ProviderRegistry.mock({"Return the JSON plan only": answer, "List the issues": {"issues": []}})
    brief = _live_brief()
    raw: list = []
    outline, warnings = plan_outline(brief, _manifest(simple_deck, tmp_path), get_strategy("structured"), basic_facts(brief.text), SkillsRegistry.load(), providers, target=12, raw=raw)
    assert outline.planned_by == "model", warnings
    assert not any("rejected" in w or "failed" in w for w in warnings), warnings
    assert any(w.startswith("grounding:") for w in warnings)
    _assert_grounded_live(outline)
    assert len(outline.slides) < 12  # not padded back to the target
    assert raw and raw[0]["step"] == "plan" and raw[0]["text"] == answer


def test_the_pipeline_keeps_the_planners_raw_answer(simple_deck, tmp_path):
    answer = _raw_answers()[1]
    providers = ProviderRegistry.mock({"Return the JSON plan only": answer, "List the issues": {"issues": []}, "*": {"facts": [], "series": [], "tables": []}})
    from verstka.pipeline.generate import generate_variants

    res = generate_variants(simple_deck, brief=_live_brief(), strategies=["structured"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", providers=providers, skills=SkillsRegistry.load(), use_vlm=False, audit=False, autofix=False, exports=[], render_images=False)
    v = res.variants[0]
    assert v.outline.planned_by == "model" and not any("rejected" in w for w in v.warnings)
    saved = json.loads((v.out_dir / "planner_raw.json").read_text(encoding="utf-8"))
    assert saved["strategy"] == "structured" and saved["answers"][0]["text"] == answer
    manifest = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert any(w.startswith("grounding:") for w in manifest["warnings"])


def test_a_plan_that_says_nothing_of_the_brief_falls_back_to_the_rules(simple_deck, tmp_path):
    """Grounding leaves no content slide (the plan is about another product): the rules plan the deck."""
    demo = json.loads((FX / "outline_demo.json").read_text(encoding="utf-8"))
    providers = ProviderRegistry.mock({"Return the JSON plan only": {"title": demo["title"], "slides": demo["slides"]}, "List the issues": {"issues": []}})
    brief = parse_brief_text("Итоги квартала по складу.\n\nПроблема: сборка заказа занимает 40 минут.\nПросим: утвердить закупку сканеров.")
    outline, warnings = plan_outline(brief, _manifest(simple_deck, tmp_path), get_strategy("visual"), basic_facts(brief.text), SkillsRegistry.load(), providers, target=8)
    assert outline.planned_by == "rules" and any("nothing in it is grounded" in w for w in warnings)


# ------------------------------------------------------------------------------------------ faithful plans stay


def _faithful(name: str) -> tuple[DeckOutline, object]:
    plan = json.loads((FX / "faithful_plans.json").read_text(encoding="utf-8"))[name]
    brief = load_brief(BRIEFS / f"{name}.md")
    facts = basic_facts(brief.text)
    planned = PlannedDeckAnswer.model_validate(plan)
    return DeckOutline(title=planned.title, subtitle=planned.subtitle, audience=brief.audience, slides=planned.slides, facts=facts.facts, series=facts.series, tables=facts.tables, planned_by="model"), brief


@pytest.mark.parametrize("name", ["cloud_initiative", "edu_program", "vk_workspace_feature", "verstka_pitch"])
def test_a_faithful_model_plan_keeps_every_slide_and_figure(name):
    """A model's plan that paraphrases the brief (conclusions for headlines, derived values such as «−43%» or «в 1,7
    раза», a chart on the brief's series, a table copied from it) comes through untouched."""
    o, brief = _faithful(name)
    g, warnings = ground_outline(o, brief)
    assert warnings == []
    assert g.model_dump() == o.model_dump()


@pytest.mark.parametrize("name", ["cloud_initiative", "edu_program", "vk_workspace_feature", "verstka_pitch"])
@pytest.mark.parametrize("strategy", LIVE)
def test_the_rules_plans_are_grounded_already(name, strategy):
    brief = load_brief(BRIEFS / f"{name}.md")
    s = get_strategy(strategy)
    o = basic_outline(brief.model_copy(deep=True), basic_facts(brief.text), s, target_slide_count(brief, s))
    g, warnings = ground_outline(o, brief)
    assert warnings == [] and g.model_dump() == o.model_dump()


def _mutated(name: str, slide_id: str, **changes) -> tuple[DeckOutline, object]:
    o, brief = _faithful(name)
    s = next(x for x in o.slides if x.id == slide_id)
    for path, value in changes.items():
        target = s
        *head, last = path.split("__")
        for part in head:
            target = getattr(target, part)
        setattr(target, last, value)
    return o, brief


def test_an_invented_figure_goes_with_its_clause_and_the_rest_stays():
    o, brief = _mutated("cloud_initiative", "sl3", content__bullets=["48 собственных серверов старше четырёх лет", "Средняя загрузка 23%, а простои обходятся в 17 млн ₽", "Ночные расчёты не успевают к утру в 6 случаях из 30"])
    g, warnings = ground_outline(o, brief)
    s = next(x for x in g.slides if x.id == "sl3")
    assert s.content.bullets == ["48 собственных серверов старше четырёх лет", "Средняя загрузка 23%", "Ночные расчёты не успевают к утру в 6 случаях из 30"]
    assert any("17 млн ₽" in w for w in warnings)


def test_a_headline_with_an_invented_figure_is_replaced_by_a_grounded_one():
    o, brief = _mutated("vk_workspace_feature", "sl4", headline="Четыре сценария закрывают 80% потребностей")
    g, _ = ground_outline(o, brief)
    s = next(x for x in g.slides if x.id == "sl4")
    assert "80" not in s.headline and s.headline  # the section's name or the slide's own first line
    assert s.headline in ("Что сделали", "Задача из сообщения")


@pytest.mark.parametrize(
    "value, label, expected",
    [
        ("12 400", "сотрудников из 37 компаний", "12 400"),
        ("12400", "сотрудников", "12400"),  # value-normalised
        ("12 400 чел.", "в пилоте", "12 400 чел."),
        ("12,4 тыс.", "сотрудников", "12,4 тыс."),
        ("91%", "готовы рекомендовать", "91%"),  # the brief's own share
        ("4,6%", "оценка удобства", "4,6"),  # a score is not a share: the % goes, the figure stays
        ("4,6", "% довольных", "4,6"),  # the % written in the label goes too
        ("13 000", "сотрудников", None),  # not the brief's
    ],
)
def test_figure_callouts_are_checked_by_value_and_unit(value, label, expected):
    from verstka.schemas.outline import NumberCallout

    o, brief = _faithful("vk_workspace_feature")
    s = next(x for x in o.slides if x.id == "sl5")
    s.content.numbers[0] = NumberCallout(value=value, label=label)
    g, _ = ground_outline(o, brief)
    s = next(x for x in g.slides if x.id == "sl5")
    first = s.content.numbers[0]
    if expected is None:
        assert [n.value for n in s.content.numbers] == ["+34%", "2,1 ч"]
    else:
        assert first.value == expected and "%" not in first.label


def test_an_invented_plan_slide_is_dropped_and_the_agenda_follows():
    from verstka.schemas.outline import SlideContent, SlideItem

    o, brief = _faithful("cloud_initiative")
    plan = OutlineSlide(id="slx", kind=K.cards, headline="План масштабирования", content=SlideContent(items=[SlideItem(title="Фаза 1", text="Внедрение в 3 департаментах"), SlideItem(title="Фаза 2", text="Интеграция с HR-системой"), SlideItem(title="Фаза 3", text="Анализ метрик и оптимизация")]))
    recs = OutlineSlide(id="sly", kind=K.bullets, headline="Рекомендации по действию", content=SlideContent(bullets=["Назначить ответственного за внедрение", "Утвердить бюджет", "Запланировать этапы реализации"]))
    o.slides[-1:-1] = [plan, recs]
    o.slides[1].content.items.append(SlideItem(title="Рекомендации по действию"))
    g, warnings = ground_outline(o, brief)
    ids = [s.id for s in g.slides]
    assert "slx" not in ids and "sly" not in ids
    assert [i.title for i in g.slides[1].content.items] == ["Проблема", "Предложение", "Экономика", "Риски", "План"]
    assert len(g.slides) == len(o.slides) - 2


@pytest.mark.parametrize(
    "subtitle, expected",
    [
        ("Вопросы? Контакты: [email@company.com]", "Вопросы?"),
        ("Контакты: [email] | [телефон]", None),
        ("Команда проекта · info@example.com · +7 (999) 123-45-67", None),
        ("Иван Иванов, руководитель проекта", None),
        (None, None),
    ],
)
def test_the_closing_slide_says_only_what_the_brief_gives(subtitle, expected):
    o, brief = _mutated("cloud_initiative", "sl10", subtitle=subtitle)
    g, _ = ground_outline(o, brief)
    assert g.slides[-1].subtitle == expected


def test_contacts_the_brief_gives_stay():
    brief = parse_brief_text("Итоги пилота.\n\nРезультаты: время ответа сократилось до 5 минут.\nКонтакты: pilot@vk.team, +7 (495) 123-45-67.")
    o = DeckOutline(title="Итоги пилота", slides=[
        OutlineSlide(id="a", kind=K.title, headline="Итоги пилота"),
        OutlineSlide(id="b", kind=K.big_number, headline="Время ответа сократилось до 5 минут", content={"numbers": [{"value": "5 минут", "label": "время ответа"}]}),
        OutlineSlide(id="c", kind=K.thanks, headline="Спасибо", subtitle="pilot@vk.team · +7 (495) 123-45-67"),
    ])
    g, warnings = ground_outline(o, brief)
    assert g.slides[-1].subtitle == "pilot@vk.team · +7 (495) 123-45-67" and warnings == []


def test_a_title_not_grounded_in_the_brief_becomes_the_briefs_own():
    o, brief = _faithful("edu_program")
    o.title = "Как мы изменим рынок труда в 3 раза"
    g, warnings = ground_outline(o, brief)
    assert g.title == "Образовательная программа VK Education «Инженер данных»"
    assert any("deck title" in w for w in warnings)


def test_a_chart_on_fact_ids_becomes_figures_or_goes():
    """«series_ids»: ["f1", "f2"] — fact ids, not series: the chart has no data. Its figures become a KPI slide when no
    other slide shows them, and the chart goes when they are all shown already."""
    from verstka.schemas.outline import ChartSpec, NumberCallout, SlideContent

    brief = _live_brief()
    facts = _live("visual").facts
    o = DeckOutline(title="Итоги пилота «Умные сводки» за квартал", facts=facts, planned_by="model", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Итоги пилота «Умные сводки» за квартал"),
        OutlineSlide(id="k", kind=K.stat_row, headline="Время на чтение чатов сократилось", content=SlideContent(numbers=[NumberCallout(value="47", label="минут до"), NumberCallout(value="29", label="минут после")])),
        OutlineSlide(id="c1", kind=K.chart, headline="Динамика времени", content=SlideContent(chart=ChartSpec(series_ids=["f1", "f2"]))),
        OutlineSlide(id="c2", kind=K.chart, headline="Бюджет на масштабирование", content=SlideContent(chart=ChartSpec(series_ids=["f4"]))),
        OutlineSlide(id="z", kind=K.thanks, headline="Спасибо за внимание"),
    ])
    g, warnings = ground_outline(o, brief)
    by = {s.id: s for s in g.slides}
    assert "c1" not in by  # 47 and 29 are on the KPI slide already
    assert by["c2"].kind == K.big_number and by["c2"].content.chart is None
    assert [n.value for n in by["c2"].content.numbers] == ["14,5 млн ₽"]
    assert any("chart without data" in w for w in warnings)


def test_unknown_kinds_and_empty_columns():
    from verstka.schemas.outline import SlideContent, SlideItem

    o, brief = _faithful("vk_workspace_feature")
    free = OutlineSlide(id="f1", kind=K.freeform, headline="Утренний дайджест по задачам команды", content=SlideContent(bullets=["Дайджест приходит утром", "В нём задачи команды"]))
    empty = OutlineSlide(id="e1", kind=K.comparison, headline="До и после", content=SlideContent(items=[SlideItem(title="До"), SlideItem(title="После")]))
    o.slides[-1:-1] = [free, empty]
    g, _ = ground_outline(o, brief)
    by = {s.id: s for s in g.slides}
    assert by["f1"].kind == K.bullets and "e1" not in by


# ------------------------------------------------------------------------------------------ figures


@pytest.mark.parametrize(
    "text, verdicts",
    [
        ("сократилось на 18 минут", ["ok"]),  # 47 − 29
        ("время сократилось на 38%", ["ok"]),  # (47 − 29) / 47
        ("время сократилось на 40%", ["bad"]),
        ("NPS 64%", ["strip"]),
        ("NPS 64", ["ok"]),
        ("NPS 64 пункта", ["ok"]),
        ("бюджет 14,5 млн ₽", ["ok"]),
        ("бюджет 14.5 млн рублей", ["ok"]),
        ("бюджет 14 500 000 ₽", ["ok"]),
        ("бюджет 15 млн ₽", ["bad"]),
        ("12 тысяч пользователей", ["bad"]),
        ("47 → 29 минут", ["ok", "ok"]),
        ("29 часов", ["bad"]),
    ],
)
def test_figure_verdicts_on_the_ui_brief(text, verdicts):
    idx = BriefIndex.of(_live_brief())
    assert [idx.verdict(f) for f in figures(text)] == verdicts


def test_a_scale_word_rounds_as_a_person_does():
    idx = BriefIndex.of(load_brief(BRIEFS / "vk_workspace_feature.md"))
    assert [idx.verdict(f) for f in figures("на 12 тысячах сотрудников")] == ["ok"]  # 12 400
    assert [idx.verdict(f) for f in figures("на 13 тысячах сотрудников")] == ["bad"]
    assert [idx.verdict(f) for f in figures("рост в 10 раз")] == ["ok"]  # 12 400 / 1 200, one row of the brief
    assert [idx.verdict(f) for f in figures("на 19 п.п.")] == ["ok"]  # 31% → 12%


def test_names_glued_to_digits_must_be_the_briefs():
    idx = BriefIndex.of(load_brief(BRIEFS / "verstka_pitch.md"))
    assert idx.clean("Qwen3.8-27B под Apache 2.0").bad == []
    assert idx.clean("Запуск в Q3 для 3-х регионов").text == ""


# ------------------------------------------------------------------------------------------ the answer's shape


def test_plan_json_repairs_the_shapes_models_write():
    data = {"presentation": {"title": "Итоги", "slides": [
        {"type": "cover", "title": "Итоги"},
        {"layout": "kpi", "heading": "Время", "numbers": [47, {"number": 29, "title": "минут"}]},
        {"kind": "cards", "headline": "Что сделали", "content": {"items": ["Сводки", {"name": "Поиск", "description": "по чатам"}]}},
        {"kind": "chart", "headline": "Динамика", "content": {"chart": {"type": "bar_chart", "series": [{"id": "s1"}]}}},
        {"kind": "section", "section": "Выводы", "content": {"bullets": ["Пилот удался"]}},
        {"kind": "closing", "headline": "Спасибо"},
    ]}}
    planned = PlannedDeckAnswer.model_validate(data)
    kinds = [s.kind for s in planned.slides]
    assert kinds == [K.title, K.stat_row, K.cards, K.chart, K.bullets, K.thanks]
    assert [n.value for n in planned.slides[1].content.numbers] == ["47", "29"]
    assert planned.slides[2].content.items[1].text == "по чатам"
    assert planned.slides[3].content.chart.type == "bar" and planned.slides[3].content.chart.series_ids == ["s1"]
    assert planned.slides[4].headline == "Выводы" or planned.slides[4].section == "Выводы"
    assert normalise_plan([{"kind": "title", "headline": "A"}])["title"] == "A"


# ------------------------------------------------------------------------------------------ the prompt


def test_the_planner_prompt_has_no_example_facts_and_a_maximum_not_a_target():
    reg = SkillsRegistry.load()
    spec = reg.get("outline_planner")
    assert spec.version == "0.2.0" and any(c.startswith("0.2.0") for c in spec.changelog)
    system = (spec.root / "prompts" / "system.md").read_text(encoding="utf-8")
    assert "12 тысячах" not in system and "34%" not in system and "(±1)" not in system and "Respect the target" not in system
    assert "never more than" in system and "freeform" not in system
    assert "NPS" in system and "has no % sign" in system  # a score is points
    prompts = reg.render("outline_planner", {"brief": "b", "title_hint": "", "audience": "a", "purpose": "p", "language": "ru", "tone": "t", "extra_instructions": "", "target": 12, "strategy_instructions": "s", "facts_json": "{}", "kinds_json": "[]", "issues": ""})
    assert "Maximum number of slides: 12" in prompts["user"] and "Return the JSON plan only" in prompts["user"]
    # the example JSON of the prompt carries no figure a model could copy
    example = system[system.index("{") : system.index("Slide kinds")]
    assert not re.search(r"\d", example.replace("sl1", ""))


def test_grounding_lines_are_not_a_model_failure():
    """The warnings quote slide text («… model …»): the model status never reads them as a failed model step."""
    from verstka.api.model_status import reason_code

    assert reason_code(["grounding: slides not supported by the brief dropped: sl4 «Our model provider»"]) is None


@pytest.mark.parametrize("strategy", LIVE)
def test_the_rules_plan_of_the_ui_brief_is_grounded_already(strategy):
    brief = _live_brief()
    s = get_strategy(strategy)
    o = basic_outline(brief.model_copy(deep=True), basic_facts(brief.text), s, target_slide_count(brief, s))
    g, warnings = ground_outline(o, brief)
    assert warnings == [] and g.model_dump() == o.model_dump()


@pytest.mark.parametrize("strategy", ["structured", "compact"])
def test_a_shared_plan_is_grounded_for_its_variant(strategy):
    """The variant whose own model call failed takes another variant's plan: adapted and grounded again."""
    from verstka.planning.outline import adapt_outline

    donor, _ = ground_outline(_live("visual"), _live_brief())
    warnings: list[str] = []
    o = adapt_outline(_live("visual"), get_strategy(strategy), None, 12, hard_limit=True, brief=_live_brief(), warnings=warnings)
    _assert_grounded_live(o)
    assert o.planned_by == "shared:visual" and len(o.slides) <= len(donor.slides) + 1
    assert any(w.startswith("grounding:") for w in warnings)


# ------------------------------------------------------------------------------------------ live check 2026-09-25 (2)
# What the second live check (Cloud.ru, Qwen3-VL-30B and Qwen3-32B, grounding and the 0.2.0 prompt in place) still
# found on the slides: a change the brief does not state — «NPS вырос до 64» (a heading of the grounded fixtures),
# «Повышение удовлетворенности сотрудников (NPS 64)» (a live bullet) — when the brief gives «NPS 64» and no earlier
# value.


@pytest.mark.parametrize(
    "text, expected",
    [
        ("NPS вырос до 64", ""),  # the brief: «NPS 64» — no earlier value, no rise
        ("Повышение удовлетворенности сотрудников (NPS 64)", ""),
        ("Рост NPS до 64 пунктов", ""),
        ("Время сократилось до 29 минут, NPS вырос до 64", "Время сократилось до 29 минут"),
        ("Время сократилось до 29 минут, NPS 64", "Время сократилось до 29 минут, NPS 64"),
        ("Время на чтение чатов сократилось с 47 до 29 минут", "Время на чтение чатов сократилось с 47 до 29 минут"),
        ("Время на чтение чатов: 47 → 29 минут, сокращение", "Время на чтение чатов: 47 → 29 минут, сокращение"),
        ("Время на чтение чатов сократилось на 18 минут", "Время на чтение чатов сократилось на 18 минут"),  # 47 − 29
        ("Снижение времени на 38%", "Снижение времени на 38%"),
        ("NPS после пилота достиг 64", "NPS после пилота достиг 64"),  # a level, not a change
        ("Бюджет на масштабирование — 14,5 млн ₽", "Бюджет на масштабирование — 14,5 млн ₽"),
    ],
)
def test_a_change_the_brief_does_not_state_goes_with_its_clause(text, expected):
    c = BriefIndex.of(_live_brief()).clean(text)
    assert c.text == expected
    assert bool(c.bad) == (expected != text) and bool(c.changes) == (expected != text)


@pytest.mark.parametrize(
    "text, kept",
    [
        ("Доля завершённых в срок задач выросла на 34%", True),  # the brief: «выросла на 34%»
        ("Срывы дедлайнов снизились с 31% до 12%", True),
        ("Активные пользователи выросли с 1 200 до 12 400", True),
        ("Активные пользователи выросли до 12 400 к сентябрю", True),  # the brief's monthly series ends there
        ("Экономия времени выросла до 2,1 часа в неделю", True),  # «Экономия составила 2,1 часа»: a saving is a change
        ("Время на контроль статусов сократилось до 5 часов в неделю", False),  # «тратят до 5 часов»: a level
        ("Оценка удобства выросла до 4,6 из 5", False),  # «Средняя оценка удобства 4,6 из 5»: a level
    ],
)
def test_changes_are_checked_against_what_the_brief_says_of_each_figure(text, kept):
    c = BriefIndex.of(load_brief(BRIEFS / "vk_workspace_feature.md")).clean(text)
    assert (c.text == text) == kept, c.text


def test_the_live_heading_nps_rose_is_replaced():
    for strategy in LIVE:
        o, warnings = ground_outline(_live(strategy), _live_brief())
        heads = [s.headline for s in o.slides]
        assert not any("вырос" in h for h in heads), heads
        nps = next(s for s in o.slides if any(n.value == "64" for n in s.content.numbers))
        assert nps.headline.strip()
        assert any(w.startswith("grounding: changes the brief does not state") and "NPS вырос до 64" in w for w in warnings)
        _assert_grounded_live(o)


def test_a_note_with_a_change_the_brief_does_not_state_goes():
    o, brief = _faithful("vk_workspace_feature")
    s = o.slides[2]
    s.notes = "Доля завершённых в срок задач выросла на 34%. Оценка удобства выросла до 4,6 из 5. Функция понравилась участникам."
    g, warnings = ground_outline(o, brief)
    gs = next(x for x in g.slides if x.id == s.id)
    assert gs.notes == "Доля завершённых в срок задач выросла на 34%. Функция понравилась участникам."
    assert any(w.startswith("grounding: speaker notes") and "4,6 из 5" in w for w in warnings)


@pytest.mark.parametrize(
    "text",
    [
        "Экономика миграции: окупаемость за 7 месяцев",  # «Экономика» is not a saving
        "Повышенная нагрузка в пиковые дни — 97%",  # a level
        "Экономия 26 млн рублей в год",
        "Расходы снижаются с 61 до 35 млн ₽ в год",  # both ends, the brief's table «Итого | 61 | 35»
    ],
)
def test_change_words_that_are_not_a_change_claim(text):
    c = BriefIndex.of(load_brief(BRIEFS / "cloud_initiative.md")).clean(text)
    assert c.text == text and not c.changes


# ------------------------------------------------------------------------------------------ review 2026-09-25 (3)
# The review of the grounding pass: it removed true paraphrases, «с 47 до 29 минут» and changes the brief gives as
# было/стало, and it let through figures it did not read («13K», «15млн», «01.04.2027», «двенадцать тысяч», «вдвое»),
# a time unit on any bare number («64 дня» for NPS 64), change words behind «:» or «—», «на 29» for «до 29», section
# labels nobody checked and derived values of any two figures of the brief.

_PARA = json.loads((FX / "paraphrase_plans.json").read_text(encoding="utf-8"))
_BRIEFS = {
    "before_after": _PARA["before_after"]["brief"],
    "years": "Итоги года.\n\nВ 2024 году выручка 120 млн ₽, в 2025 году — 150 млн ₽.",
    "formats": "Итоги пилота.\n\nВ пилоте 12k пользователей, бюджет 15млн ₽. Ответы стали быстрее в 3 раза. Автоматически закрывается 33% заявок. Сбор данных до 01.04.2027.",
    "compare": "Итоги пилота поддержки.\n\nВремя ответа <5 минут, у конкурентов >10 минут.",
}


def _brief(key: str):
    if key == "ui":
        return _live_brief()
    if key in _BRIEFS:
        return parse_brief_text(_BRIEFS[key])
    return load_brief(BRIEFS / f"{key}.md")


def _paraphrase(name: str) -> tuple[DeckOutline, object]:
    d = _PARA[name]
    brief = _live_brief() if d["brief"] == "live" else parse_brief_text(d["brief"])
    planned = PlannedDeckAnswer.model_validate(d["plan"])
    facts = basic_facts(brief.text)
    return DeckOutline(title=planned.title, subtitle=planned.subtitle, audience=brief.audience, slides=planned.slides, facts=facts.facts, series=facts.series, tables=facts.tables, planned_by="model"), brief


@pytest.mark.parametrize("name", ["ui", "before_after"])
def test_a_paraphrasing_plan_keeps_every_slide_and_figure(name):
    """A plan in the model's own words: nothing of it is lost, and nothing is reported."""
    o, brief = _paraphrase(name)
    g, warnings = ground_outline(o, brief)
    assert warnings == []
    assert g.model_dump() == o.model_dump()
    if name == "ui":
        # a paraphrase: some of its lines share almost no words with the brief and stand by their figures alone
        idx = BriefIndex.of(brief)
        lines = [x for s in o.slides for x in s.content.bullets + s.content.paragraphs]
        assert any((idx.ratio(x) or 0) < 0.25 for x in lines), lines


def test_the_paraphrase_fixture_says_nothing_the_brief_does_not():
    """Checked independently of the grounding code: every figure of the fixture is a figure of its brief or a value
    derived from two of them (18 = 47 − 29, 38 ≈ (47 − 29) / 47, 23 = 64 − 41, 3 = 12 / 4, 27 ≈ 27,4)."""
    allowed = {
        "ui": UI_VALUES | {18.0, 38.0},
        "before_after": {47.0, 29.0, 120.0, 150.0, 12.0, 4.0, 64.0, 41.0, 14.5, 18.0, 38.0, 23.0, 3.0, 27.0, 15.0, 2026.0},
    }
    for name, values in allowed.items():
        o, _ = _paraphrase(name)
        for t in _texts(o):
            assert _values(re.sub(r"(\d+)\s+октября\s+(\d{4})", r"\1; \2", t)) <= values, (name, t)


@pytest.mark.parametrize(
    "key, text, kept",
    [
        # a change with its unit written once, and one the brief gives as было/стало, до/после, or by years
        ("before_after", "Время ответа сократилось с 47 до 29 минут", True),
        ("before_after", "Время ответа сократилось до 29 минут", True),
        ("before_after", "Выручка выросла с 120 до 150 млн ₽", True),
        ("before_after", "Рост выручки до 150 млн ₽", True),
        ("before_after", "Срок обработки сократился с 12 до 4 дней", True),
        ("before_after", "NPS вырос на 23 пункта", True),  # 64 − 41: points of a score
        ("before_after", "NPS вырос до 64", True),  # «NPS 64 (было 41)»
        ("before_after", "Время ответа сократилось на 38%", True),  # (47 − 29) / 47: from the earlier value
        ("before_after", "Время ответа сократилось на 62%", False),  # (47 − 29) / 29
        ("years", "Выручка выросла до 150 млн ₽", True),
        ("years", "Выручка выросла на 30 млн ₽", True),
        ("ui", "Время сократилось с 47 до 29 минут", True),
        # a change word speaks for its sentence: no way around it with «:» or «—»
        ("ui", "Удовлетворённость выросла: NPS 64", False),
        ("ui", "NPS 64 — сотрудники довольны улучшением", False),
        # «на» is the size of the change, «до» the level it came to
        ("ui", "Время сократилось на 29 минут", False),
        ("ui", "Время сократилось до 18 минут", False),
        ("ui", "Время сократилось на 18 минут", True),
        # both ends written, but not two values of one measure of the brief
        ("ui", "NPS вырос с 29 до 64", False),
        # a comparison is not a placeholder
        ("compare", "Время ответа <5 минут, у конкурентов >10 минут", True),
        ("compare", "Ответ <5 минут против >10 минут у конкурентов", True),
    ],
)
def test_review_change_claims(key, text, kept):
    c = BriefIndex.of(_brief(key)).clean(text)
    assert (c.text == text) == kept, c.text
    assert not c.placeholders
    if not kept:
        assert c.bad


@pytest.mark.parametrize(
    "key, text, verdicts",
    [
        # figures the regex did not see: glued units, dates, words
        ("ui", "13K сотрудников", ["bad"]),
        ("ui", "экономия 15млн ₽", ["bad"]),
        ("ui", "рост в 3x", ["bad"]),
        ("ui", "старт 01.04.2027", ["bad"]),
        ("ui", "двенадцать тысяч пользователей", ["bad"]),
        ("ui", "на двенадцати тысячах пользователей", ["bad"]),
        ("ui", "время сократилось вдвое", ["bad"]),  # 47 → 29 is 1,6 times
        ("ui", "в 1,6 раза меньше", ["ok"]),
        ("ui", "половина сотрудников", ["bad"]),
        ("ui", "треть рабочего дня", ["bad"]),
        # a bare number of the brief takes no time unit
        ("ui", "пилот длился 64 дня", ["bad"]),
        ("ui", "тратят 64 часа в месяц", ["bad"]),
        # rounding half up to an integer or one decimal, never from the midpoint
        ("ui", "бюджет 14.5 млн ₽", ["ok"]),
        ("ui", "бюджет 15 млн ₽", ["bad"]),
        ("ui", "бюджет 14 млн ₽", ["bad"]),
        ("before_after", "около 27% клиентов", ["ok"]),  # 27,4%
        ("before_after", "около 28% клиентов", ["bad"]),
        ("vk_workspace_feature", "на 12 тыс. сотрудников", ["ok"]),  # 12 400
        ("vk_workspace_feature", "на 13 тыс. сотрудников", ["bad"]),
        # dates: the same day in any format
        ("before_after", "запуск 15 октября 2026 года", ["ok"]),  # «15.10.2026»
        ("before_after", "запуск 15 октября", ["ok"]),
        ("before_after", "запуск 16.10.2026", ["bad"]),
        ("before_after", "в 2026 году", ["ok"]),
        ("cloud_initiative", "старт пилота 1 ноября", ["ok"]),
        ("cloud_initiative", "старт пилота 1 декабря", ["bad"]),
        # the brief's figures in these formats are indexed the same way
        ("formats", "12 000 пользователей", ["ok"]),  # «12k»
        ("formats", "двенадцать тысяч пользователей", ["ok"]),
        ("formats", "бюджет 15 млн ₽", ["ok"]),  # «15млн ₽»
        ("formats", "ответы втрое быстрее", ["ok"]),  # «в 3 раза»
        ("formats", "треть заявок закрывается сама", ["ok"]),  # 33%
        ("formats", "до 1 апреля 2027 года", ["ok"]),  # «01.04.2027»
        ("vk_workspace_feature", "каждый третий дедлайн", ["ok"]),
        ("vk_workspace_feature", "33% дедлайнов", ["ok"]),  # «каждый третий»
        # derived values only of figures written close together
        ("cloud_initiative", "снижение расходов на 43%", ["ok"]),  # «Итого | 61 | 35», from 61
        ("cloud_initiative", "снижение расходов на 90%", ["bad"]),
        ("cloud_initiative", "экономия 17% расходов", ["bad"]),
    ],
)
def test_review_figure_formats_units_and_derived_values(key, text, verdicts):
    idx = BriefIndex.of(_brief(key))
    assert [idx.verdict(f) for f in figures(text)] == verdicts


def test_small_counts_in_words_are_not_figures():
    """«три этапа», «пять шагов», «за пять месяцев» count what the brief lists; a share, a multiple or thousands in
    words are figures."""
    assert figures("Миграция в три этапа, пять шагов, за пять месяцев") == []
    assert [f.value for f in figures("двадцать пять процентов, в два раза, полтора миллиона")] == [25, 2, 1.5]


def test_figures_come_from_the_briefs_text_not_the_instructions():
    brief = _live_brief()
    brief.extra_instructions = "не более 12 слайдов, доклад на 10 минут"
    idx = BriefIndex.of(brief)
    assert [idx.verdict(f) for f in figures("доклад на 10 минут")] == ["bad"]
    assert [idx.verdict(f) for f in figures("охват 12 регионов")] == ["bad"]
    # the title slide may still name the audience and what the user asked for
    assert idx.frame.clean("Доклад на 10 минут для генерального директора").bad == []


def test_a_placeholder_is_a_word_in_angle_brackets():
    idx = BriefIndex.of(_brief("compare"))
    c = idx.clean("Вопросы: <имя менеджера>")
    assert c.placeholders == ["<имя менеджера>"] and c.text == "Вопросы"


def _small_deck(*slides: OutlineSlide) -> DeckOutline:
    return DeckOutline(title="Итоги пилота «Умные сводки» за квартал", planned_by="model", slides=[
        OutlineSlide(id="t", kind=K.title, headline="Итоги пилота «Умные сводки» за квартал"),
        *slides,
        OutlineSlide(id="z", kind=K.thanks, headline="Спасибо за внимание"),
    ])


def _num(value: str, label: str) -> NumberCallout:
    return NumberCallout(value=value, label=label)


def test_a_problem_and_its_result_both_stay():
    o = _small_deck(
        OutlineSlide(id="p", kind=K.big_number, headline="Сотрудники тратят 47 минут в день на чтение чатов", content=SlideContent(numbers=[_num("47 минут", "в день на чтение чатов")])),
        OutlineSlide(id="r", kind=K.stat_row, headline="Время сократилось с 47 до 29 минут, NPS 64", content=SlideContent(numbers=[_num("47 минут", "до пилота"), _num("29 минут", "после пилота"), _num("64", "NPS")])),
        OutlineSlide(id="a", kind=K.big_number, headline="Просим 14,5 млн ₽ на масштабирование", content=SlideContent(numbers=[_num("14,5 млн ₽", "бюджет на масштабирование")])),
    )
    g, warnings = ground_outline(o, _live_brief())
    assert [s.id for s in g.slides] == ["t", "p", "r", "a", "z"] and warnings == []


def test_single_figures_and_their_summary_all_stay():
    o = _small_deck(
        OutlineSlide(id="s1", kind=K.big_number, headline="Время на чтение чатов сократилось до 29 минут", content=SlideContent(numbers=[_num("29 минут", "в день после пилота")])),
        OutlineSlide(id="s2", kind=K.big_number, headline="NPS после пилота — 64", content=SlideContent(numbers=[_num("64", "NPS")])),
        OutlineSlide(id="s3", kind=K.big_number, headline="Просим 14,5 млн ₽ на масштабирование", content=SlideContent(numbers=[_num("14,5 млн ₽", "бюджет")])),
        OutlineSlide(id="kpi", kind=K.stat_row, headline="Итоги пилота в цифрах", content=SlideContent(numbers=[_num("29 минут", "на чаты в день"), _num("64", "NPS"), _num("14,5 млн ₽", "бюджет")])),
    )
    g, warnings = ground_outline(o, _live_brief())
    assert [s.id for s in g.slides] == ["t", "s1", "s2", "s3", "kpi", "z"] and warnings == []


def test_a_slide_with_exactly_the_figures_of_another_goes():
    o = _small_deck(
        OutlineSlide(id="a", kind=K.big_number, headline="Просим бюджет 14,5 млн ₽ на масштабирование", content=SlideContent(numbers=[_num("14,5 млн ₽", "бюджет")])),
        OutlineSlide(id="b", kind=K.big_number, headline="Следующий шаг", content=SlideContent(numbers=[_num("14,5 млн ₽", "на следующий шаг")])),
    )
    g, warnings = ground_outline(o, _live_brief())
    assert [s.id for s in g.slides] == ["t", "a", "z"]
    assert any("repeats the figures of a" in w for w in warnings)


def test_section_labels_captions_and_authors_are_the_briefs():
    """The section label is a kicker or a tag on the slide: «Фаза 2: 50% сотрудников» went through and was printed as
    «ФАЗА 2: 50% СОТРУДНИКОВ». A divider's name copied into the label of its content is checked too."""
    from verstka.schemas.outline import TableData

    o = _small_deck(
        OutlineSlide(id="a", kind=K.big_number, section="Эффект на 12 тысячах пользователей", headline="Время на чтение чатов сократилось до 29 минут", content=SlideContent(numbers=[_num("29 минут", "в день")])),
        OutlineSlide(id="b", kind=K.big_number, section="Фаза 2: 50% сотрудников", headline="NPS после пилота — 64", content=SlideContent(numbers=[_num("64", "NPS")])),
        OutlineSlide(id="c", kind=K.big_number, section="Детали", headline="Бюджет на масштабирование — 14,5 млн ₽", content=SlideContent(numbers=[_num("14,5 млн ₽", "бюджет")])),
        OutlineSlide(id="d", kind=K.table, section="Результаты", headline="Время на чтение чатов до и после пилота", content=SlideContent(table=TableData(columns=["Показатель", "До", "После"], rows=[["Минут в день на чаты", "47", "29"]], caption="Опрос 1 200 сотрудников"))),
        OutlineSlide(id="e", kind=K.quote, headline="Проблема", content=SlideContent(quote="Сотрудники тратят 47 минут в день на чтение чатов", quote_author="Иван Петров, CTO")),
        OutlineSlide(id="f", kind=K.section, headline="Фаза 2: охват 50% сотрудников", content=SlideContent(bullets=["Время на чтение чатов сократилось до 29 минут", "Бюджет 14,5 млн ₽ на масштабирование"])),
    )
    g, warnings = ground_outline(o, _live_brief())
    by = {s.id: s for s in g.slides}
    assert by["a"].section is None and by["b"].section is None and by["c"].section is None
    assert by["d"].section == "Результаты" and by["d"].content.table.caption is None
    assert by["e"].content.quote and by["e"].content.quote_author is None
    assert by["f"].kind == K.bullets and by["f"].section is None and "50%" not in by["f"].headline
    assert any("section label «Детали» removed" in w for w in warnings)
    for t in _texts(g):
        assert "12 тысячах" not in t and "50%" not in t and "1 200" not in t, t


@pytest.mark.parametrize(
    "line, kept",
    [
        ("Работники экономят 18 минут в день", True),  # a figure of the brief with its unit, in other words
        ("Требуется 14,5 млн ₽ для расширения", True),
        ("Каждый день на переписку уходит 47 минут", True),
        ("Отделы растут, экономия 18 минут в день", False),  # a change word: the line is judged by its words as before
        ("Внедрить в 3 отделах к концу года", False),  # 3 is not the brief's
        ("Планируем охватить все департаменты компании", False),  # neither the brief's words nor its figures
    ],
)
def test_a_paraphrase_with_a_figure_of_the_brief_stays(line, kept):
    o = _small_deck(OutlineSlide(id="b", kind=K.bullets, headline="Итоги пилота", content=SlideContent(bullets=[line, "Сотрудники тратят 47 минут в день на чтение чатов", "NPS после пилота — 64"])))
    g, _ = ground_outline(o, _live_brief())
    s = next(x for x in g.slides if x.id == "b")
    assert (line in s.content.bullets) == kept, s.content.bullets


def test_the_schema_the_model_sees_is_planned_decks_with_the_allowed_kinds():
    """The model is shown PlannedDeck's own schema (no word of the answer being repaired) with only the kinds the
    prompt allows."""
    shown = PlannedDeckAnswer.model_json_schema()
    base = PlannedDeck.model_json_schema()
    assert shown["title"] == "PlannedDeck" and shown.get("description") == base.get("description")
    assert "normalis" not in json.dumps(shown)
    assert set(shown["$defs"]["PatternKind"]["enum"]) == ALLOWED_KINDS
    assert "freeform" in base["$defs"]["PatternKind"]["enum"]  # the deck itself keeps every kind


@pytest.mark.parametrize("strategy", LIVE)
def test_the_strategies_skip_what_the_brief_does_not_have(strategy):
    text = get_strategy(strategy).planner_instructions
    assert "Пропускай шаги, для которых в брифе нет содержания" in text
    assert not re.search(r"\d\s*[–-]\s*\d\s+карточ", text)  # no fixed number of cards to fill


# ------------------------------------------------------------------------------------------ review 2026-09-25 (4)
# The verification of the third round: a unit the brief writes once («было 47, стало 29 минут», «с 47 минут до 29»)
# was lost for the other value, so true lines went; «было задействовано», «теперь», «после внедрения» alone and any two
# figures without a unit counted as a stated change, so «NPS вырос до 64» came back; «2 000» was a year; «до 34%» passed
# for «на 34%»; a change word without a figure took the sentence's true figures with it; hedged fractions («больше
# половины») were checked to ±1 point; «в каждом третьем случае» was not read; a dropped clause took the sentence's end
# mark with it. The guiding rule: grounding is a net for invented figures — a true line lost is worse than a vague
# phrase let through.

_BRIEFS.update({
    "once_later": "Итоги автоматизации.\n\nВремя ответа: было 47, стало 29 минут. Выручка: было 120, стало 150 млн ₽.",
    "once_earlier": "Итоги автоматизации.\n\nВремя ответа сократилось с 47 минут до 29. Срок обработки заявки: 12 дней → 4.",
    "once_before_after": "Итоги автоматизации.\n\nСрок обработки заявки до внедрения 12 дней, после — 4.",
    "once_label": "Итоги автоматизации.\n\nСрок обработки заявки, дней: 12 → 4. Время ответа 47 минут, после внедрения 29.",
    "passive": "Итоги пилота.\n\nВ пилоте было задействовано 12 400 сотрудников из 37 компаний. За квартал было обработано 3 400 заявок. NPS 64.",
    "after_alone": "Итоги пилота.\n\nПосле внедрения время ответа 29 минут, NPS 64.",
    "now_alone": "Итоги пилота.\n\nТеперь сотрудники тратят 29 минут в день, NPS 64. Стало понятно, что чаты нужно сокращать.",
    "clients": "Итоги пилота.\n\nКлиентов было 1 500, стало 1 950. Заявок было обработано 3 400, стало 5 000.",
    "unitless": "Итоги пилота.\n\nNPS 64. В пилоте 41 команда и 2 000 сотрудников.",
    "by_size": "Итоги пилота.\n\nВыручка выросла на 30 млн ₽. Время ответа сократилось на 18 минут.",
    "years_apart": "Итоги года.\n\nВ 2024 году выручка 120 млн ₽. В 2025 году — 150 млн ₽.",
})


def _kept(key: str, text: str) -> str:
    return BriefIndex.of(_brief(key)).clean(text).text


@pytest.mark.parametrize(
    "text, expected",
    [
        ("было 47, стало 29 минут", [(47, "min"), (29, "min")]),
        ("с 47 минут до 29", [(47, "min"), (29, "min")]),
        ("с 47 до 29 минут", [(47, "min"), (29, "min")]),
        ("12 дней → 4", [(12, "d"), (4, "d")]),
        ("до внедрения 12 дней, после — 4", [(12, "d"), (4, "d")]),
        ("до внедрения 12, после — 4 дня", [(12, "d"), (4, "d")]),
        ("47 минут, после внедрения 29.", [(47, "min"), (29, "min")]),
        ("Срок обработки, дней: 12 → 4", [(12, "d"), (4, "d")]),
        ("NPS 64, теперь 29 минут", [(64, None), (29, "min")]),  # 64 is not marked as the earlier value
        ("47 минут, после внедрения 4 команды", [(47, "min"), (4, None)]),  # 4 does not stand alone
    ],
)
def test_a_unit_written_once_is_the_unit_of_both_values(text, expected):
    assert [(f.value, f.unit) for f in figures(text)] == expected


@pytest.mark.parametrize(
    "key, text, kept",
    [
        ("once_later", "Время ответа сократилось с 47 до 29 минут", True),
        ("once_later", "Время ответа сократилось до 29 минут", True),
        ("once_later", "Раньше ответ занимал 47 минут", True),
        ("once_later", "Время ответа сократилось на 18 минут", True),
        ("once_later", "Время ответа сократилось на 38%", True),
        ("once_later", "Выручка до внедрения — 120 млн ₽", True),
        ("once_later", "Выручка выросла со 120 до 150 млн ₽", True),
        ("once_later", "Время ответа — 47 часов", False),
        ("once_earlier", "Время ответа — 29 минут", True),
        ("once_earlier", "Время ответа сократилось до 29 минут", True),
        ("once_earlier", "Время ответа сократилось на 18 минут", True),
        ("once_earlier", "Время ответа сократилось на 29 минут", False),  # «до 29», not «на 29»
        ("once_earlier", "Срок обработки — 4 дня", True),
        ("once_earlier", "Срок обработки сократился с 12 до 4 дней", True),
        ("once_earlier", "Заявки обрабатываются в 3 раза быстрее", True),
        ("once_before_after", "Срок обработки — 4 дня", True),
        ("once_before_after", "Срок обработки сократился до 4 дней", True),
        ("once_label", "Срок обработки — 4 дня", True),
        ("once_label", "Время ответа сократилось до 29 минут", True),
    ],
)
def test_a_figure_whose_unit_the_brief_writes_once_stays(key, text, kept):
    assert (_kept(key, text) == text) == kept, _kept(key, text)


def test_a_result_slide_whose_unit_the_brief_writes_once_stays():
    """«время сократилось с 47 минут до 29»: the result slide and the KPI row keep «29 минут», and so does the facts
    registry."""
    from verstka.planning.grounding import grounded_facts
    from verstka.schemas.outline import Fact

    brief = parse_brief_text("Итоги пилота «Умные сводки» за квартал.\n\nПроблема: сотрудники тратили 47 минут в день на чтение чатов.\nРезультаты: время сократилось с 47 минут до 29, NPS 64.\nПросим: бюджет 14,5 млн ₽ на масштабирование.")
    o = _small_deck(
        OutlineSlide(id="p", kind=K.big_number, headline="Сотрудники тратили 47 минут в день на чтение чатов", content=SlideContent(numbers=[_num("47 минут", "в день на чаты")])),
        OutlineSlide(id="r", kind=K.big_number, headline="Время на чтение чатов сократилось до 29 минут", content=SlideContent(numbers=[_num("29 минут", "в день после пилота")])),
        OutlineSlide(id="k", kind=K.stat_row, headline="Результаты пилота", content=SlideContent(numbers=[_num("29 минут", "на чаты в день"), _num("64", "NPS")])),
    )
    g, warnings = ground_outline(o, brief)
    assert g.model_dump() == o.model_dump() and warnings == []
    facts = [Fact(id="f1", value="47", unit="минут", label="на чаты до пилота"), Fact(id="f2", value="29", unit="минут", label="на чаты после пилота")]
    kept, lines = grounded_facts(facts, brief)
    assert [(f.value, f.unit) for f in kept] == [("47", "минут"), ("29", "минут")] and lines == []


@pytest.mark.parametrize(
    "key, text, kept",
    [
        # a change stands only when one value is written as the earlier and the other as the later one
        ("passive", "NPS вырос до 64", False),  # «было обработано 3 400 заявок»: a passive, not an earlier value
        ("passive", "Число компаний выросло до 37", False),  # «было задействовано … из 37 компаний»
        ("after_alone", "NPS вырос до 64", False),  # «после внедрения» with nothing earlier
        ("after_alone", "Время ответа сократилось до 29 минут", False),
        ("now_alone", "NPS вырос до 64", False),  # «теперь», «стало понятно»
        ("clients", "Число клиентов выросло с 1 500 до 1 950", True),  # «1 950» is not a year
        ("clients", "Клиентов стало больше на 450", True),
        ("clients", "Рост клиентской базы на 30%", True),
        ("clients", "Число заявок выросло до 5 000", True),  # «было обработано 3 400, стало 5 000»
        # two figures without a unit are one measure only side by side as a change
        ("unitless", "NPS вырос с 41 до 64", False),
        ("unitless", "Число сотрудников выросло до 2 000", False),  # «2 000» is not a year either
        ("unitless", "В пилоте 2 000 сотрудников", True),
        ("years_apart", "Выручка выросла до 150 млн ₽", True),  # two years in neighbouring sentences
        ("years_apart", "Выручка выросла на 25%", True),
        ("cloud_initiative", "Расчёты ускорятся в 2 раза", False),  # «месяц 1–2» is a range, and «в 2» says nothing
        ("cloud_initiative", "Расчёты ускорятся в 3,4 раза", True),
        ("verstka_pitch", "Свободных фигур в 20 раз больше, чем плейсхолдеров", True),  # 1621 / 81, side by side
    ],
)
def test_a_change_needs_an_earlier_and_a_later_value(key, text, kept):
    assert (_kept(key, text) == text) == kept, _kept(key, text)


@pytest.mark.parametrize(
    "key, text, kept",
    [
        ("vk_workspace_feature", "Доля завершённых в срок задач выросла до 34%", False),  # the brief: «выросла на 34%»
        ("vk_workspace_feature", "Доля завершённых в срок задач выросла на 34%", True),
        ("vk_workspace_feature", "Экономия времени выросла до 2,1 часа", True),  # a level of savings
        ("by_size", "Выручка выросла до 30 млн ₽", False),
        ("by_size", "Время ответа сократилось до 18 минут", False),
        ("by_size", "Экономия времени выросла до 18 минут", True),
    ],
)
def test_to_x_is_not_a_change_the_brief_gives_by_x(key, text, kept):
    assert (_kept(key, text) == text) == kept, _kept(key, text)


@pytest.mark.parametrize(
    "key, text, expected",
    [
        # the brief states the change («время сократилось до 29 минут»): the line stands, NPS 64 is a level
        ("ui", "Время на чтение чатов сократилось, NPS 64", None),
        ("ui", "Время на чаты сократилось, а NPS составил 64", None),
        ("ui", "Сократили время на чтение чатов; NPS 64", None),
        ("ui", "Бюджет 14,5 млн ₽ и сокращение времени на чаты", None),
        # a change the brief does not state goes with its own clause, never with a figure of the brief
        ("ui", "Удовлетворённость выросла: NPS 64", "NPS 64"),
        ("ui", "Время на чтение чатов выросло, NPS 64", "NPS 64"),
        ("ui", "Снижение нагрузки на сотрудников и NPS 64", "NPS 64"),
        # … and stands when the brief states a change of the figure («NPS 64 (было 41)»)
        ("before_after", "Удовлетворённость выросла: NPS 64", None),
    ],
)
def test_a_change_word_without_a_figure_never_takes_a_true_figure(key, text, expected):
    c = BriefIndex.of(_brief(key)).clean(text)
    assert c.text == (text if expected is None else expected)
    assert bool(c.changes) == (expected is not None)


@pytest.mark.parametrize(
    "key, text, kept",
    [
        ("edu_program", "Больше половины выпускников трудоустроены за три месяца", True),  # 58%
        ("edu_program", "Меньше половины выпускников трудоустроены", False),
        ("edu_program", "До конца программы дошли почти три четверти студентов", True),  # 71%
        ("edu_program", "Около половины выпускников трудоустроены", False),
        ("ui", "Время на чтение чатов сократилось более чем на треть", True),  # (47 − 29) / 47 = 38%
        ("ui", "Время на чтение чатов сократилось более чем наполовину", False),
        ("cloud_initiative", "Серверы загружены меньше чем на четверть", True),  # 23%
        ("cloud_initiative", "Серверы загружены больше чем на четверть", False),
        # «каждом третьем»: read as a share, and checked
        ("vk_workspace_feature", "В каждом третьем случае дедлайн срывается", True),
        ("cloud_initiative", "Ночные расчёты не успевают в каждом пятом случае", True),  # «в 6 случаях из 30»
        ("cloud_initiative", "Ночные расчёты не успевают в каждом четвёртом случае", False),
    ],
)
def test_hedged_fractions_and_every_nth(key, text, kept):
    assert (_kept(key, text) == text) == kept, _kept(key, text)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Время на чаты сократилось, в пилоте 12 000 пользователей. Сотрудники тратили 47 минут", "Время на чаты сократилось. Сотрудники тратили 47 минут"),
        ("Время на чаты сократилось, охват 12 тысяч сотрудников. NPS 64", "Время на чаты сократилось. NPS 64"),
        ("Экономия времени растёт, бюджет 20 млн ₽. Бюджет на масштабирование 14,5 млн ₽", "Экономия времени растёт. Бюджет на масштабирование 14,5 млн ₽"),
        ("NPS 64. В пилоте 12 000 пользователей, время сократилось до 29 минут", "NPS 64. время сократилось до 29 минут"),
        ("Бюджет 14,5 млн ₽ (на 12 тысяч пользователей) и 29 минут в день", "Бюджет 14,5 млн ₽ и 29 минут в день"),
    ],
)
def test_a_dropped_clause_keeps_the_sentence_apart_and_a_second_pass_changes_nothing(text, expected):
    idx = BriefIndex.of(_live_brief())
    once = idx.clean(text).text
    assert once == expected
    assert idx.clean(once).text == once


def test_cleaning_is_idempotent_on_random_lines():
    import random

    rnd = random.Random(7)
    pieces = ["Время на чтение чатов сократилось", "время сократилось до 29 минут", "NPS 64", "NPS вырос до 64", "в пилоте 12 000 пользователей",
              "бюджет 14,5 млн ₽", "бюджет 20 млн ₽", "Сотрудники тратили 47 минут", "Удовлетворённость выросла", "экономия 2,1 часа",
              "доля выросла на 34%", "доля выросла до 34%", "Рост клиентов на 30%", "с 47 до 29 минут", "клиентов стало 1 950",
              "больше половины выпускников", "в каждом пятом случае", "расчёты ускорятся в 2 раза", "NPS 64%", "Снижение нагрузки", "[email]"]
    seps = [", ", "; ", " — ", ": ", ". ", " и ", " а ", "! ", "? "]
    idxs = [BriefIndex.of(_brief(k)) for k in ("ui", "vk_workspace_feature", "cloud_initiative", "before_after")]
    for _ in range(400):
        t = rnd.choice(pieces)
        for _ in range(rnd.randint(0, 4)):
            t += rnd.choice(seps) + rnd.choice(pieces)
        idx = rnd.choice(idxs)
        once = idx.clean(t).text
        assert idx.clean(once).text == once, (t, once)


@pytest.mark.parametrize("key", sorted(set(_BRIEFS) | {"ui", "cloud_initiative", "edu_program", "vk_workspace_feature", "verstka_pitch"}))
def test_every_sentence_of_a_brief_passes_unchanged(key):
    """No false removal: the brief's own sentences, each as a line of a slide, come through as they are."""
    from verstka.planning import heuristics as H

    brief = _brief(key)
    idx = BriefIndex.of(brief)
    for line in brief.text.splitlines():
        s = line.strip().lstrip("#").strip()
        if not s or s.startswith("|"):
            continue
        for sn in H.split_sentences(s) or [s]:
            c = idx.clean(sn)
            assert c.text.rstrip(".") == sn.strip().rstrip(".") and not c.bad, (sn, c.text, c.bad)


# the many ways a brief writes a before/after: the lenient reading keeps a plan's true change, the strict cases still go
_BEFORE_AFTER_CASES = [
    ("Результаты: время сократилось до 29 минут, NPS 64.", "NPS вырос до 64", False),
    ("Результаты: время сократилось до 29 минут, NPS 64.", "Время на чтение чатов сократилось до 29 минут", True),
    ("Было: 47 минут в день на чаты, NPS 41. Стало: 29 минут, NPS 64.", "NPS вырос с 41 до 64", True),
    ("Было: 47 минут в день на чаты, NPS 41. Стало: 29 минут, NPS 64.", "NPS вырос до 64", True),
    ("До миграции: 1 950 пользователей, 3,2 секунды на открытие карточки. После миграции: 2 400 пользователей, 0,8 секунды.", "Число пользователей выросло с 1 950 до 2 400", True),
    ("До миграции: 1 950 пользователей, 3,2 секунды на открытие карточки. После миграции: 2 400 пользователей, 0,8 секунды.", "Время открытия карточки сократилось до 0,8 секунды", True),
    ("Раньше: 12 операторов в смене, 47 минут на ответ, NPS 41. Теперь: 8 операторов, 29 минут, NPS 64.", "Время ответа сократилось до 29 минут", True),
    ("В мае было собрано 18 000 заказов, в августе — 31 000.", "Число заказов выросло с 18 000 до 31 000", True),
    ("В начале пилота было 1 200 активных пользователей, в конце — 12 400.", "Число пользователей выросло с 1 200 до 12 400", True),
    ("NPS в первом квартале — 41, во втором — 64.", "NPS вырос с 41 до 64", True),
    ("Ошибок комплектации 2,4% против 4,8% до пилота.", "Доля ошибок снизилась до 2,4%", True),
    ("Сейчас на чаты уходит 29 минут в день, до пилота уходило 47.", "Время на чаты сократилось до 29 минут", True),
    ("Сейчас систему поддерживают 3 инженера вместо 7.", "Число инженеров сократилось с 7 до 3", True),
    ("Время ответа: было 47 минут — стало 29.", "Время ответа сократилось с 47 до 29 минут", True),
    ("NPS 64. В пилоте 41 команда.", "NPS вырос с 41 до 64", False),
    ("После внедрения время ответа 29 минут, NPS 64.", "NPS вырос до 64", False),
    ("В пилоте было задействовано 12 400 сотрудников из 37 компаний.", "Число компаний выросло до 37", False),
    ("Проблема: сотрудники тратят 47 минут в день на чтение чатов.", "В пилоте 12 тысяч пользователей", False),
    ("Результаты: время сократилось до 29 минут, NPS 64.", "Пилот длился 64 дня", False),
]


@pytest.mark.parametrize("brief,line,keep", _BEFORE_AFTER_CASES)
def test_a_before_after_written_in_any_common_way_keeps_its_true_changes(brief, line, keep):
    out = BriefIndex(brief).clean(line).text or ""
    assert bool(re.search(r"\d", out)) is keep, out


def test_a_sentence_of_the_brief_word_for_word_keeps_its_elided_subject():
    # gate 4 (writer mode): «…составила 47,2 млн, а ежемесячная — 73,4 млн» lost its contrast clause as «a figure given
    # another subject» — the brief's own sentence as it is never misreads its figures
    from verstka.planning.grounding import ground_outline
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import Brief, DeckOutline, OutlineSlide, SlideContent

    brief = Brief(text="Слайд 5. Аудитория\nПо состоянию на 2022 год ежедневная аудитория «ВКонтакте» в России составила 47,2 млн, а ежемесячная — 73,4 млн. Всемирная месячная аудитория — 100 млн.")
    line = "По состоянию на 2022 год ежедневная аудитория «ВКонтакте» в России составила 47,2 млн, а ежемесячная — 73,4 млн."
    s = OutlineSlide(id="s5", kind=PatternKind.bullets, headline="Всемирная месячная аудитория — 100 млн.", content=SlideContent(bullets=[line]), spec_ref=5)
    o, warns = ground_outline(DeckOutline(title="x", slides=[s]), brief)
    assert "73,4 млн" in o.slides[0].content.bullets[0], (o.slides[0].content.bullets, warns)
