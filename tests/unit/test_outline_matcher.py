import json
from pathlib import Path

from verstka.analysis.manifest import analyze_template
from verstka.matching.compat import composition_for, kind_compat, needed_chars, needed_items
from verstka.matching.matcher import match_outline
from verstka.matching.scorer import score_pattern
from verstka.planning.brief import load_brief, parse_brief_text
from verstka.planning.strategies import STRATEGY_NAMES, get_strategy, load_strategies
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"


def test_outline_fixture_roundtrip():
    outline = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert len(outline.slides) == 12 and outline.slides[0].kind == PatternKind.title and outline.slides[-1].kind == PatternKind.thanks
    assert outline.series_by_id("s1").values[-1] == 12400 and outline.fact_by_id("f5").value == "91"
    dumped = json.loads(outline.model_dump_json())
    assert DeckOutline.model_validate(dumped).slides[4].content.items[3].icon_hint == "list"


def test_strategies_and_brief():
    strategies = load_strategies()
    assert set(strategies) == set(STRATEGY_NAMES)
    assert get_strategy("compact").slide_ratio < 1.0 and get_strategy("visual").weight("chart") > 1.0 and get_strategy("visual").weight("unknown") == 1.0
    brief = parse_brief_text("---\naudience: продуктовый комитет\nslides: 8\nтип: фича\n---\n# Умные напоминания\n\nТекст брифа.")
    assert brief.audience == "продуктовый комитет" and brief.slide_count == 8 and brief.purpose == "feature" and brief.title_hint == "Умные напоминания"
    assert brief.text.startswith("# Умные напоминания")
    b2 = parse_brief_text("Сделай презентацию не более 5 слайдов про облако.")
    assert b2.slide_count == 5
    assert load_brief("just text").text == "just text"


def test_needs_and_compat():
    outline = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    cards = outline.slides[4]
    assert needed_items(cards) == 4 and needed_chars(cards)["card_title"] >= 10
    assert needed_items(outline.slides[3]) == 3 and needed_items(outline.slides[7]) == 2
    assert kind_compat(PatternKind.stat_row, PatternKind.big_number) > 0 and kind_compat(PatternKind.table, PatternKind.cards) == 0
    assert composition_for(outline.slides[5]) == "chart_text" and composition_for(outline.slides[6]) == "table"


def test_matcher_on_simple_deck(simple_deck, tmp_path):
    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    outline = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    strategy = get_strategy("structured")
    plan = match_outline(outline, manifest, strategy)
    assert len(plan.slides) == 12
    by_id = {s.outline_id: s for s in plan.slides}
    assert by_id["sl1"].mode == "clone" and manifest.patterns[0].kind == PatternKind.title
    # 3 cards on the template, 4 needed → still the best clone candidate, with a capacity reason
    cards_plan = by_id["sl5"]
    assert cards_plan.reasons and any("ячеек" in r or "ёмкость" in r for r in cards_plan.reasons)
    # three KPI numbers fit the three-card pattern (cards is a fallback for stat_row) → clone with reasons; table has no fallback → synth
    assert by_id["sl4"].mode == "clone" and by_id["sl4"].pattern_id == cards_plan.pattern_id
    assert by_id["sl7"].mode == "synth" and by_id["sl7"].composition == "table"
    assert by_id["sl6"].mode == "synth" and by_id["sl6"].composition == "chart_text"
    # score result is explainable
    cards_pattern = next(p for p in manifest.patterns if p.kind == PatternKind.cards)
    res = score_pattern(outline.slides[4], cards_pattern, manifest, strategy)
    assert 0 < res.score <= 1.2 and res.fit.get("items") and len(res.reasons) >= 3
