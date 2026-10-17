"""A text edit of one slide re-lays out that slide only (qa3 N-E1: a caption edit on slide 3 turned slide 9 from three
big cards into a sparse list), and the variant keeps the generation's provenance with the edit's own calls on top
(N-E2: after an edit run_manifest said backend «none», usage null). Offline: no model, LibreOffice for the previews."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from verstka.pipeline.revise import add_usage, carry_provenance, rerender_variant, slide_fingerprints
from verstka.schemas.outline import DeckOutline

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "tests" / "fixtures" / "data_story" / "lo_forestbird.pptx"
BRIEF = (ROOT / "tests" / "fixtures" / "briefs" / "coffee_short.md").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("soffice") is None and not Path("/Applications/LibreOffice.app").exists(),
                                reason="LibreOffice is not installed")


@pytest.fixture(scope="module")
def variant(tmp_path_factory):
    from verstka.ingest.workspace import TemplateWorkspace
    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import parse_brief_text

    root = tmp_path_factory.mktemp("ws")
    ws = TemplateWorkspace.create(TEMPLATE, root)
    out = root / "runs" / "g1"
    generate_variants(ws.source, brief=parse_brief_text(BRIEF), strategies=["structured"], out_dir=out, workspace_root=root,
                      providers=None, skills=None, use_llm=False, use_vlm=False, exports=[], pictures=False, eyes=False)
    return out / "structured", ws, root


def _content_slide(o: DeckOutline) -> int:
    return next(k for k, s in enumerate(o.slides, 1) if k > 2 and s.kind.value not in ("title", "section", "thanks"))


def test_an_edit_of_one_slide_keeps_every_other_slide(variant):
    from verstka.planning.brief import parse_brief_text
    from verstka.planning.slide_edit import _EDIT_USAGE, outline_key

    vdir, ws, root = variant
    o = DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8"))
    m0 = json.loads((vdir / "run_manifest.json").read_text(encoding="utf-8"))
    fp0 = slide_fingerprints(vdir / "deck.pptx")
    n = _content_slide(o)
    o.slides[n - 1].headline = o.slides[n - 1].headline.rstrip(".") + " — коротко"
    _EDIT_USAGE[outline_key(o)] = {"calls": 1, "requests": 1, "tokens_in": 1000, "tokens_out": 100, "failed": 0, "cost_rub": None,
                                   "by_skill": {"SlideDesignAnswer": {"calls": 1, "requests": 1, "tokens_in": 1000, "tokens_out": 100, "failed": 0, "seconds": 3.0, "cost_rub": None}}}
    v = rerender_variant(vdir, "structured", o, ws.source, root, brief=parse_brief_text(BRIEF), exports=[], pictures=False)
    fp1 = slide_fingerprints(vdir / "deck.pptx")
    assert len(fp1) == len(fp0)
    assert [k for k, (a, b) in enumerate(zip(fp0, fp1), 1) if a != b] == [n]  # only the edited slide changed
    assert getattr(v, "other_slides", None) == []
    m1 = json.loads((vdir / "run_manifest.json").read_text(encoding="utf-8"))
    for key in ("planner", "providers", "skills"):
        assert m1.get(key) == m0.get(key), key
    assert m1["usage"]["edits"]["calls"] == 1 and m1["usage"]["tokens_in"] == int((m0.get("usage") or {}).get("tokens_in") or 0) + 1000
    assert m1["inputs"]["outline_sha256"] != m0["inputs"].get("outline_sha256")
    assert DeckOutline.model_validate_json((vdir / "outline.json").read_text(encoding="utf-8")).slides[n - 1].headline.endswith("— коротко")


def test_provenance_is_carried_with_the_edits_usage():
    old = {"planner": {"planned_by": "agent"}, "providers": {"llm": {"backend": "openai_compat", "model": "qwen38-27b-fp8"}},
           "usage": {"calls": 60, "requests": 61, "tokens_in": 120000, "tokens_out": 10000, "failed": 0, "cost_rub": None, "by_skill": {}},
           "skills": {"slide_designer": "1.6.0"}, "inputs": {"brief_sha256": "abc", "outline_sha256": "old"}, "timings_s": {"total": 80.0}}
    new = {"providers": {"llm": {"backend": "none"}}, "usage": None, "inputs": {"brief_sha256": "abc", "outline_sha256": "new"}, "timings_s": {"total": 9.0}}
    edit = {"calls": 2, "requests": 2, "tokens_in": 3000, "tokens_out": 300, "failed": 0, "cost_rub": None, "by_skill": {"SlideDesignAnswer": {"calls": 2, "requests": 2, "tokens_in": 3000, "tokens_out": 300, "failed": 0, "seconds": 9.0, "cost_rub": None}}}
    out = carry_provenance(old, new, edit)
    assert out["providers"]["llm"]["model"] == "qwen38-27b-fp8" and out["planner"]["planned_by"] == "agent"
    assert out["usage"]["calls"] == 62 and out["usage"]["tokens_in"] == 123000 and out["usage"]["edits"]["count"] == 1
    assert out["inputs"]["outline_sha256"] == "new" and out["timings_s"]["generation"] == {"total": 80.0}
    assert add_usage(None, {}) == {}
