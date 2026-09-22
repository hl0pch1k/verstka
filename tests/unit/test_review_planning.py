"""Regression tests for the planning review: brief front matter through the API and hard slide limits."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_api import client  # noqa: F401  (shared fixture: workspace in tmp before importing the app)
from verstka.planning.brief import parse_brief_text
from verstka.planning.facts import basic_facts
from verstka.planning.outline import basic_outline, target_slide_count, validate_outline
from verstka.planning.strategies import load_strategies
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import ChartSpec, DeckOutline, OutlineSlide, SlideContent, TableData

BRIEF_PATH = Path(__file__).resolve().parents[2] / "examples" / "briefs" / "vk_workspace_feature.md"


def _outline(brief, strategy: str = "structured") -> DeckOutline:
    s = load_strategies()[strategy]
    return basic_outline(brief, basic_facts(brief.text), s, target_slide_count(brief, s))


def _bullets(kind_or_id: str, n: int, headline: str) -> OutlineSlide:
    return OutlineSlide(id=kind_or_id, kind=PatternKind.bullets, headline=headline, content=SlideContent(bullets=[f"{headline} {i}" for i in range(n)]))


# ---------------------------------------------------------------------------- PLAN-1 (1): front matter via the API


def test_generate_request_brief_uses_front_matter(client):
    _, mod = client
    raw = BRIEF_PATH.read_text(encoding="utf-8")
    b = mod._brief_from_request(mod.GenerateRequest(template_id="t", brief=raw))
    assert b.title_hint == "Умные напоминания в VK WorkSpace: итоги пилота и план запуска"
    assert b.audience == "продуктовый комитет VK WorkSpace" and b.purpose == "feature" and b.slide_count == 12
    assert not b.text.startswith("---") and "аудитория:" not in b.text
    # explicit request fields win, None keeps the parsed value
    b2 = mod._brief_from_request(mod.GenerateRequest(template_id="t", brief=raw, audience="совет директоров", slides=6, extra_instructions="без таблиц"))
    assert b2.audience == "совет директоров" and b2.slide_count == 6 and b2.purpose == "feature" and b2.extra_instructions == "без таблиц"
    # unknown purpose strings do not blow up the job
    assert mod._brief_from_request(mod.GenerateRequest(template_id="t", brief="текст", purpose="фича")).purpose == "feature"
    assert mod._brief_from_request(mod.GenerateRequest(template_id="t", brief="текст", purpose="whatever")).purpose == "other"
    o = _outline(b)
    assert o.title != "---" and o.title.startswith("Умные напоминания")
    assert not any(x.lower().startswith(("аудитория:", "тип:", "slides:")) for s in o.slides for x in s.content.bullets)


# ---------------------------------------------------------------------------- PLAN-1 (2): hard slide limit


@pytest.mark.parametrize("strategy", ["structured", "visual", "compact"])
def test_not_more_than_five_slides_is_respected(strategy):
    raw = BRIEF_PATH.read_text(encoding="utf-8").replace("slides: 12\n", "")
    raw = raw.replace("# Умные напоминания", "Сделай не более 5 слайдов.\n\n# Умные напоминания", 1)
    b = parse_brief_text(raw)
    assert b.slide_count == 5
    o = _outline(b, strategy)
    assert len(o.slides) <= 5, [s.kind.value for s in o.slides]
    assert o.slides[0].kind == PatternKind.title and o.slides[-1].kind == PatternKind.thanks


def test_slides_5_keeps_chart_and_table_over_bullets():
    b = parse_brief_text(BRIEF_PATH.read_text(encoding="utf-8"))
    b.slide_count = 5
    facts = basic_facts(b.text)
    assert facts.series and facts.tables
    o = _outline(b)
    kinds = [s.kind for s in o.slides]
    assert len(o.slides) <= 5, kinds
    assert PatternKind.chart in kinds and PatternKind.table in kinds, kinds
    assert kinds[0] == PatternKind.title and kinds[-1] == PatternKind.thanks


def test_validate_outline_hard_limit_drops_smallest_bullets_first():
    tbl = TableData(columns=["a", "b"], rows=[["1", "2"]])
    slides = [
        OutlineSlide(id="t", kind=PatternKind.title, headline="T"),
        _bullets("b1", 4, "Контекст"),
        _bullets("b2", 2, "Коротко"),
        _bullets("b3", 5, "План"),
        OutlineSlide(id="c", kind=PatternKind.chart, headline="Динамика", content=SlideContent(chart=ChartSpec(series_ids=["s1"]))),
        OutlineSlide(id="tb", kind=PatternKind.table, headline="Тарифы", content=SlideContent(table=tbl)),
        OutlineSlide(id="th", kind=PatternKind.thanks, headline="Спасибо"),
    ]
    out = validate_outline(DeckOutline(title="T", slides=slides), None, 5, hard_limit=True)
    ids = [s.id for s in out.slides]
    assert len(ids) == 5 and ids[0] == "t" and ids[-1] == "th"
    assert "c" in ids and "tb" in ids, ids
    # the 2-bullet slide went first (merged into the previous bullets slide), then the next smallest
    assert "b2" not in ids
    merged = next(s for s in out.slides if s.id == "b1")
    assert len(merged.content.bullets) == 6 and "Коротко 0" in merged.content.bullets


def test_validate_outline_soft_limit_keeps_tolerance():
    def deck(n_bullets: int) -> DeckOutline:
        slides = [OutlineSlide(id="t", kind=PatternKind.title, headline="T")] + [_bullets(f"b{i}", n_bullets, f"S{i}") for i in range(5)] + [OutlineSlide(id="th", kind=PatternKind.thanks, headline="Спасибо")]
        return DeckOutline(title="T", slides=slides)

    # soft target: full bullets slides are never dropped for one slide over (target + 2 tolerated, unchanged behaviour)
    out = validate_outline(deck(5), None, 5)
    assert len(out.slides) == 7 and all(len(s.content.bullets) == 5 for s in out.slides[1:-1])
    # soft target: two small slides are merged (no content lost) to reach target + 1
    out = validate_outline(deck(3), None, 5)
    assert len(out.slides) == 6 and sum(len(s.content.bullets) for s in out.slides) == 15
    # hard target: exactly the target
    out = validate_outline(deck(5), None, 5, hard_limit=True)
    assert len(out.slides) == 5 and out.slides[0].id == "t" and out.slides[-1].id == "th"
