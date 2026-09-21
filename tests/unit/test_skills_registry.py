from pathlib import Path

from verstka.analysis.classify import SlideClassification
from verstka.providers.registry import ProviderRegistry
from verstka.skills_registry.registry import SkillsRegistry, default_skills_root


def test_registry_loads_slide_classifier():
    reg = SkillsRegistry.load()
    spec = reg.get("slide_classifier")
    assert spec.version == "0.1.0" and spec.role == "llm"
    assert len(spec.sha256) == 64
    assert "slide_classifier" in reg.versions()


def test_hash_changes_when_prompt_changes(tmp_path: Path):
    src = default_skills_root() / "slide_classifier"
    dst = tmp_path / "skills" / "slide_classifier"
    dst.mkdir(parents=True)
    (dst / "prompts").mkdir()
    (dst / "skill.yaml").write_text((src / "skill.yaml").read_text())
    (dst / "prompts" / "system.md").write_text((src / "prompts" / "system.md").read_text())
    (dst / "prompts" / "user.md").write_text((src / "prompts" / "user.md").read_text())
    h1 = SkillsRegistry.load(tmp_path / "skills").get("slide_classifier").sha256
    (dst / "prompts" / "user.md").write_text("changed {{ slide_json }} {{ template_summary }} {{ slide_index }} {{ n_slides }}")
    h2 = SkillsRegistry.load(tmp_path / "skills").get("slide_classifier").sha256
    assert h1 != h2


def test_run_skill_with_mock_provider():
    reg = SkillsRegistry.load()
    providers = ProviderRegistry.mock({"Classify this slide": {"kind": "cards", "roles": {"s1": "title", "s2": "card_title"}, "confidence": 0.8, "rationale": "repeated blocks"}})
    result = reg.run(
        "slide_classifier",
        providers,
        {"template_summary": "light template", "slide_index": 2, "n_slides": 10, "slide_json": '[{"id": "s1"}]'},
    )
    assert isinstance(result.parsed, SlideClassification)
    assert result.parsed.kind.value == "cards" and result.parsed.roles["s2"].value == "card_title"
    call = providers.get("llm").calls[0]
    assert call["messages"][0].role == "system" and "Template summary: light template" in call["messages"][1].content
