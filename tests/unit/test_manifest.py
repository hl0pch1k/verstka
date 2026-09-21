import time

from verstka.analysis.manifest import analyze_template
from verstka.analysis.rules import derived_rules, instruction_candidates
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import PatternKind
from verstka.schemas.template import TemplateManifest
from verstka.skills_registry.registry import SkillsRegistry


def test_analyze_simple_deck_heuristics_only(simple_deck, tmp_path):
    m = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    assert isinstance(m, TemplateManifest)
    kinds = {p.kind for p in m.patterns}
    assert kinds == {PatternKind.title, PatternKind.cards, PatternKind.image_text}
    assert any(c.text == "ACME" for c in m.tokens.chrome)
    assert m.tokens.color_for("accent.1") == "0077FF"
    assert m.tokens.typography.families[0].family
    assert m.components.card is not None and m.components.card.fill_hex == "EDF3FC"
    assert len(m.assets) == 1 and m.assets[0].kind in ("photo", "other")
    assert any(r.source == "derived" for r in m.style_rules)
    manifest_path = tmp_path / "ws" / "templates" / m.template_id / "manifest.json"
    assert manifest_path.exists()
    mtime = manifest_path.stat().st_mtime
    time.sleep(0.01)
    again = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    assert again.template_id == m.template_id and manifest_path.stat().st_mtime == mtime


def test_rules_with_mock_llm(simple_deck, tmp_path):
    skills = SkillsRegistry.load()
    providers = ProviderRegistry.mock(
        {
            "Extract the style rules": {"rules": [{"text": "Заголовки выравнивать по левому краю.", "confidence": 0.9}]},
            "Classify this slide": {"kind": "cards", "roles": {}, "confidence": 0.6, "rationale": ""},
        }
    )
    m = analyze_template(simple_deck, workspace_root=tmp_path / "ws2", providers=providers, skills=skills, use_llm=True, use_vlm=False, render=False, force=True)
    assert all(p.classification and p.classification.llm is not None for p in m.patterns)
    cands = instruction_candidates(["Шрифт для заголовков — VK Sans Display Medium, выравниваем текст по левому краю", "Пункт"])
    assert len(cands) == 1
    assert any(r.text.startswith("Шрифты шаблона") for r in derived_rules(m.tokens))
