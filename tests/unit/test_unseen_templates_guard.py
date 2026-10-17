"""A guard for ordinary decks on templates the analysis has never seen (final review C1/I9): a typographic floor taken
from a LibreOffice template's 24–32 pt placeholder size cut lo_focus's fitness deck from 100/97/100 to 58/67/91 —
text past its frame, words broken, lines only in the speaker notes — and no test looked. Offline, the example brief on
three unseen templates must score at least as well as the base (2e381cb) did, with no more errors, overflows, broken
words or missing texts."""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# (template, variant) → the base's (score, errors, text_overflow, word_break, content_missing) on fitness_studio.md
BASE = {
    ("lo_focus", "structured"): (100, 0, 0, 0, 0), ("lo_focus", "visual"): (97, 0, 1, 0, 0), ("lo_focus", "compact"): (100, 0, 0, 0, 0),
    ("synth_sidebar43", "structured"): (100, 0, 0, 0, 0), ("synth_sidebar43", "visual"): (100, 0, 0, 0, 0), ("synth_sidebar43", "compact"): (100, 0, 0, 0, 0),
    ("lo_forestbird", "structured"): (100, 0, 0, 0, 0), ("lo_forestbird", "visual"): (97, 0, 1, 0, 0), ("lo_forestbird", "compact"): (100, 0, 0, 0, 0),
}
TEMPLATES = {
    "lo_focus": ROOT / "tests/fixtures/tpl_audit/templates/lo_focus.pptx",
    "synth_sidebar43": ROOT / "tests/fixtures/tpl_audit/templates/synth_sidebar43.pptx",
    "lo_forestbird": ROOT / "tests/fixtures/data_story/lo_forestbird.pptx",
}


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_an_unseen_template_is_no_worse_than_the_base(name, tmp_path, monkeypatch):
    for v in ("POLZA_API_KEY", "VERSTKA_MODELS", "VK_INFERENCE_BASE_URL", "VK_INFERENCE_API_KEY", "VK_T2I_MODEL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("VERSTKA_NO_DOTENV", "1")
    monkeypatch.setenv("VERSTKA_NO_CATALOG", "1")
    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import parse_brief_text

    brief = parse_brief_text((ROOT / "examples/briefs/fitness_studio.md").read_text(encoding="utf-8"))
    res = generate_variants(TEMPLATES[name], brief=brief, out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", use_llm=False,
                            use_vlm=False, audit=True, autofix=True, exports=[])
    assert len(res.variants) == 3
    for v in res.variants:
        score, errors, overflow, broken, missing = BASE[(name, v.strategy)]
        c = collections.Counter(i.check_id for i in v.audit.issues if i.severity != "info")
        got = (v.audit.summary.score, v.audit.summary.errors, c["text_overflow"], c["word_break"], c["content_missing"])
        assert got[0] >= score and got[1] <= errors and got[2] <= overflow and got[3] <= broken and got[4] <= missing, (
            name, v.strategy, got, [(i.slide, i.check_id, i.message[:80]) for i in v.audit.issues if i.severity != "info"])
