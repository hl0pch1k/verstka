from pathlib import Path

from verstka.analysis.chrome import chrome_ids, detect_chrome
from verstka.analysis.classify import classify_slide, compact_slide_json
from verstka.analysis.groups import detect_repeat_groups
from verstka.analysis.patterns import build_pattern, dedupe_patterns, estimate_capacity
from verstka.analysis.shapes import SlideContext, extract_shapes
from verstka.analysis.typography import build_type_scale
from verstka.ingest.package import PptxPackage
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import Bbox, Family, PatternKind
from verstka.skills_registry.registry import SkillsRegistry


def _prep(pptx):
    pkg = PptxPackage.open(pptx)
    per_slide = {i: extract_shapes(pkg, part, SlideContext(pkg, part)) for i, part in enumerate(pkg.slide_parts, 1)}
    chrome = detect_chrome(per_slide, *pkg.slide_size)
    ids = {i: chrome_ids(per_slide[i], chrome, *pkg.slide_size) for i in per_slide}
    typo = build_type_scale(per_slide, ids)
    groups = {i: detect_repeat_groups(per_slide[i], *pkg.slide_size, chrome_ids=ids[i]) for i in per_slide}
    return pkg, per_slide, ids, typo, groups


def test_capacity_estimate():
    box = Bbox(x=0, y=0, w=914400 * 10, h=914400 * 1)  # 10in × 1in
    cap = estimate_capacity(box, 18.0)
    assert 70 <= cap.max_chars / cap.max_lines <= 80 and cap.max_lines == 3


def test_ensemble_agreement_and_fallback(simple_deck):
    pkg, per_slide, ids, typo, groups = _prep(simple_deck)
    skills = SkillsRegistry.load()
    providers = ProviderRegistry.mock({"Classify this slide": {"kind": "cards", "roles": {}, "confidence": 0.9, "rationale": "three equal blocks"}})
    trace, roles, warnings = classify_slide(per_slide[2], groups[2], ids[2], typo, 2, 3, *pkg.slide_size, skills=skills, providers=providers, use_llm=True, use_vlm=False)
    assert trace.kind == PatternKind.cards and trace.llm is not None and trace.agreement == 1.0 and not warnings
    # LLM disagrees with low weight → heuristics win only if heavier; here llm weight 1.5×0.9 > heuristic 0.75
    providers2 = ProviderRegistry.mock({"Classify this slide": {"kind": "team", "roles": {}, "confidence": 0.9, "rationale": ""}})
    trace2, _, _ = classify_slide(per_slide[2], groups[2], ids[2], typo, 2, 3, *pkg.slide_size, skills=skills, providers=providers2, use_llm=True, use_vlm=False)
    assert trace2.kind == PatternKind.team and trace2.agreement < 1.0
    # provider failure → heuristic result with a warning
    providers3 = ProviderRegistry.mock({})
    trace3, _, warnings3 = classify_slide(per_slide[2], groups[2], ids[2], typo, 2, 3, *pkg.slide_size, skills=skills, providers=providers3, use_llm=True, use_vlm=False)
    assert trace3.kind == PatternKind.cards and trace3.llm is None and warnings3


def test_compact_json_and_pattern_build_and_dedupe(simple_deck):
    pkg, per_slide, ids, typo, groups = _prep(simple_deck)
    rows = compact_slide_json(per_slide[2], {}, groups[2], *pkg.slide_size)
    assert any(r.get("text", "").startswith("Pillar") and r.get("group") for r in rows)
    trace, roles, _ = classify_slide(per_slide[2], groups[2], ids[2], typo, 2, 3, *pkg.slide_size, use_llm=False, use_vlm=False)
    p1 = build_pattern("p2", 2, per_slide[2], roles, groups[2], trace, Family.light, *pkg.slide_size)
    assert p1.kind == PatternKind.cards
    assert len(p1.slots_by_role(p1.slots[0].role)) >= 1
    card_titles = [s for s in p1.slots if s.role.value == "card_title"]
    assert len(card_titles) == 3 and all(s.group_id for s in card_titles) and all(s.capacity.max_chars > 0 for s in card_titles)
    assert not any(s.role.value == "chrome" for s in p1.slots)
    p2 = p1.model_copy(deep=True)
    p2.id, p2.source_slide, p2.quality = "p9", 9, 0.5
    assert [p.id for p in dedupe_patterns([p1, p2])] == ["p2"]
