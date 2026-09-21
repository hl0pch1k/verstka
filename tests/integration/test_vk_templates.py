"""Integration tests on the three VK templates (skipped when the dataset is absent)."""

import time
from collections import Counter

import pytest

from verstka.analysis.manifest import analyze_template
from verstka.schemas.common import Family

pytestmark = pytest.mark.integration


def _find(fixtures_dir, needle):
    if fixtures_dir is None:
        pytest.skip("VK templates not available")
    for p in fixtures_dir.glob("*.pptx"):
        if needle.lower() in p.name.lower():
            return p
    pytest.skip(f"template {needle} not found")


@pytest.mark.parametrize("needle,expect_family,min_patterns", [("VK Tech", Family.light, 15), ("WorkSpace", Family.dark, 10), ("Education", Family.light, 15)])
def test_templates_analyze_without_models(fixtures_dir, tmp_path, needle, expect_family, min_patterns):
    pptx = _find(fixtures_dir, needle)
    t0 = time.time()
    m = analyze_template(pptx, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    assert time.time() - t0 < 120
    assert len(m.patterns) >= min_patterns
    fams = Counter(p.family for p in m.patterns)
    assert fams.most_common(1)[0][0] == expect_family
    assert m.tokens.typography.families[0].family == "Play"
    assert "0077FF" in {c.hex for c in m.tokens.colors if c.role and (c.role.startswith("accent") or c.role.startswith("background") or c.role.startswith("text"))}
    assert not any("extraction failed" in w for w in m.warnings)
