"""A congested or confused model must never shape the deck: empty plans and refusals are rejected, one variant's good
plan rescues the variants whose own plan failed, and waiting for a rate-limit slot respects the generation's budget."""

import time
from pathlib import Path

import pytest

from verstka.analysis.manifest import analyze_template
from verstka.pipeline.generate import generate_variants
from verstka.planning.brief import parse_brief_text
from verstka.planning.facts import basic_facts
from verstka.planning.outline import plan_outline
from verstka.planning.strategies import get_strategy
from verstka.providers.base import ProviderError
from verstka.providers.openai_compat import _MinuteLimiter
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline
from verstka.skills_registry.registry import SkillsRegistry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"
SHORT = "Итоги пилота «Умные сводки» за второй квартал: время на чтение чатов сократилось с 47 до 29 минут в день."


def _plan(title: str, headlines: list[tuple[str, str]]) -> dict:
    return {"title": title, "slides": [{"id": f"s{i}", "kind": k, "headline": h} for i, (k, h) in enumerate(headlines, 1)]}


@pytest.fixture
def manifest(simple_deck, tmp_path):
    return analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)


@pytest.mark.parametrize(
    "answer",
    [
        _plan("Стратегическая презентация", []),  # an empty plan: the model said nothing
        _plan("error", [("title", "Невозможно сформировать план презентации"), ("thanks", "Обратная связь")]),  # a refusal
        _plan("Итоги пилота", [("title", "Итоги пилота"), ("thanks", "Спасибо")]),  # no content slides at all
    ],
)
def test_an_unusable_model_plan_falls_back_to_the_rules(manifest, answer):
    providers = ProviderRegistry.mock({"Return the JSON plan only": answer, "List the issues": {"issues": []}})
    brief = parse_brief_text(SHORT)
    outline, warnings = plan_outline(brief, manifest, get_strategy("structured"), basic_facts(brief.text), SkillsRegistry.load(), providers, target=8)
    assert outline.planned_by == "rules"
    assert any("rejected" in w for w in warnings), warnings
    assert len(outline.slides) >= 3 and outline.title != "error"
    assert not any("Невозможно" in s.headline for s in outline.slides)


def test_a_good_model_plan_is_marked(manifest):
    demo = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    planned = {"title": demo.title, "slides": [s.model_dump() for s in demo.slides]}
    providers = ProviderRegistry.mock({"Return the JSON plan only": planned, "List the issues": {"issues": []}})
    brief = parse_brief_text(SHORT)
    outline, _ = plan_outline(brief, manifest, get_strategy("visual"), basic_facts(brief.text), SkillsRegistry.load(), providers, target=12)
    assert outline.planned_by == "model" and len(outline.slides) >= 10


def test_one_good_model_plan_serves_every_variant(simple_deck, manifest, tmp_path):
    """Congested free endpoint: only the compact plan got through. The other variants take its content (adapted to
    their strategy) instead of a three-slide deck made by the rules from a one-line brief."""
    demo = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    good = {"title": demo.title, "slides": [s.model_dump() for s in demo.slides]}

    def answer(messages):
        text = "\n".join(m.content for m in messages)
        if "Return the JSON plan only" in text:
            if "Стратегия «Компактный»" in text:
                return good
            raise ProviderError("429 temporarily rate-limited upstream")
        if "List the issues" in text:
            return {"issues": []}
        return {"facts": [], "series": [], "tables": []}

    providers = ProviderRegistry.mock(answer)
    res = generate_variants(simple_deck, brief=parse_brief_text(SHORT), out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", providers=providers, skills=SkillsRegistry.load(), use_vlm=False, audit=False, autofix=False, exports=[], render_images=False)
    by = {v.strategy: v.outline for v in res.variants}
    assert by["compact"].planned_by == "model"
    assert by["structured"].planned_by == "shared:compact" and by["visual"].planned_by == "shared:compact"
    content = {s.headline for s in demo.slides}
    for name in ("structured", "visual"):
        assert len(by[name].slides) >= 8, name
        assert sum(s.headline in content for s in by[name].slides) >= 6, name
        assert any("adapted" in w for w in next(v for v in res.variants if v.strategy == name).warnings)
    assert not any(s.kind == PatternKind.section for s in by["visual"].slides)


def test_waiting_for_a_rate_limit_slot_respects_the_deadline():
    limiter = _MinuteLimiter(rpm=1)
    limiter.wait()  # the one request of this minute
    t = time.monotonic()
    with pytest.raises(ProviderError, match="budget"):
        limiter.wait(deadline=time.monotonic() + 3)
    assert time.monotonic() - t < 1.0  # it did not sleep out the minute


def test_a_topic_without_content_becomes_a_skeleton_not_three_slides():
    """«итоги пилота умные сводки за второй квартал» — a topic, no theses: the rules do not invent content, they lay
    out the sections of such a deck (dividers with notes on what to add) under a real title."""
    from verstka.planning.brief import parse_brief_text
    from verstka.planning.outline import basic_outline

    brief = parse_brief_text("итоги пилота умные сводки за второй квартал")
    brief.purpose = "report"
    o = basic_outline(brief, basic_facts(brief.text), get_strategy("structured"), 11)
    assert o.planned_by == "skeleton"
    assert o.title == "Итоги пилота умные сводки за второй квартал"
    kinds = [s.kind for s in o.slides]
    assert kinds[0] == PatternKind.title and kinds[-1] == PatternKind.thanks and PatternKind.agenda in kinds
    dividers = [s for s in o.slides if s.kind == PatternKind.section]
    assert len(dividers) >= 4 and all(s.notes.startswith("Добавьте") for s in dividers)
    assert [s.headline for s in dividers][:3] == ["Цели периода", "Что сделано", "Результаты"]
    assert sum(s.headline.lower() == o.title.lower() for s in o.slides) == 1  # the topic is the title, not a slide too


def test_a_headingless_brief_is_titled_by_its_first_statement():
    from verstka.planning.brief import parse_brief_text
    from verstka.planning.outline import basic_outline

    brief = parse_brief_text(SHORT + " NPS 64. Просим бюджет 14,5 млн ₽ на масштабирование.")
    o = basic_outline(brief, basic_facts(brief.text), get_strategy("structured"), 8)
    assert o.planned_by == "rules" and o.title == "Итоги пилота «Умные сводки» за второй квартал"
    assert any(s.kind in (PatternKind.stat_row, PatternKind.big_number) for s in o.slides)
