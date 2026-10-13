"""«Взгляд дизайнера» on the result screen (api/app.py `_eyes_of`, GET …/eyes/{stage}/{name}): what the review saw, by
the slides' current numbers; the slide before and after for the slides it laid out again; nothing for a run without
the review (no model here: the review's outcome is written into the run as the pipeline writes it)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from test_api import _wait, client  # noqa: F401  (shared fixture)
from test_images import GREENHOUSE

TPL = Path(__file__).resolve().parents[1] / "fixtures" / "tpl_audit" / "templates" / "lo_focus.pptx"


@pytest.fixture
def built(client):  # noqa: F811
    c, mod = client
    with open(TPL, "rb") as f:
        r = c.post("/api/templates", files={"file": ("lo_focus.pptx", f, "application/octet-stream")}, data={"use_models": "false"})
    tid = _wait(c, r.json()["job_id"])["result"]["template_id"]
    r = c.post("/api/generations", json={"template_id": tid, "brief": GREENHOUSE, "strategies": ["structured"], "use_models": False, "exports": [], "pictures": False})
    assert r.status_code == 200, r.text
    gid = r.json()["generation_id"]
    job = _wait(c, r.json()["job_id"], timeout=240)
    assert job["status"] == "done", job.get("error")
    return c, mod, gid


def test_a_run_without_the_review_has_no_eyes(built):
    c, mod, gid = built
    assert c.get(f"/api/generations/{gid}").json()["variants"][0]["eyes"] is None


def test_the_review_by_the_slides_current_numbers_with_the_slide_before_and_after(built):
    c, mod, gid = built
    vdir = mod.store.generation_dir(gid) / "structured"
    ids = [s["id"] for s in json.loads((vdir / "outline.json").read_text(encoding="utf-8"))["slides"]]
    seen_id, fixed_id, kept_id = ids[0], ids[1], ids[2]  # a deck of three slides
    m = json.loads((vdir / "run_manifest.json").read_text(encoding="utf-8"))
    m["eyes"] = {
        "looked": 5, "calls": 9, "seconds": 12.5, "skipped": None,
        "flagged": [
            {"slide": 2, "outline_id": fixed_id, "problems": [{"code": "word_broken", "severity": "major", "where": "карточки", "evidence": "«Температ|ура»"}]},
            {"slide": 3, "outline_id": kept_id, "problems": [{"code": "unbalanced", "severity": "major", "where": "правая половина", "evidence": ""}]},
            {"slide": 1, "outline_id": seen_id, "problems": [{"code": "cramped", "severity": "minor", "where": "", "evidence": ""}]},
            {"slide": 9, "outline_id": "gone-since", "problems": [{"code": "leftover", "severity": "major", "where": "", "evidence": ""}]},
        ],
        "fixed": [{"slide": 2, "outline_id": fixed_id, "result": "rematch → p3", "reason": "Новая вёрстка без разрывов слов."}],
        "kept": [{"slide": 3, "outline_id": kept_id, "why": "новая вёрстка почти не отличается от прежней"}],
    }
    (vdir / "run_manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    for stage in ("before", "after"):
        (vdir / "eyes" / stage).mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 18), "white").save(vdir / "eyes" / stage / "slide-002.jpg", "JPEG")

    eye = c.get(f"/api/generations/{gid}").json()["variants"][0]["eyes"]
    assert eye["looked"] == 5 and [s["slide"] for s in eye["slides"]] == [1, 2, 3]  # a slide gone since is left out
    s, f, k = eye["slides"]
    assert f["status"] == "fixed" and f["problems"][0]["label"] == "слова разорваны посередине" and f["reason"].startswith("Новая вёрстка")
    assert f["before"] == f"/api/generations/{gid}/structured/eyes/before/slide-002.jpg" and f["after"].endswith("/eyes/after/slide-002.jpg")
    assert k["status"] == "kept" and k["reason"] == "новая вёрстка почти не отличается от прежней" and k["before"] is None
    assert s["status"] == "seen" and s["problems"][0]["severity"] == "minor"
    r = c.get(f["before"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert c.get(f"/api/generations/{gid}/structured/eyes/elsewhere/slide-002.jpg").status_code == 404
    assert c.get(f"/api/generations/{gid}/structured/eyes/before/slide-2.jpg").status_code == 404
    assert c.get(f"/api/generations/{gid}/structured/eyes/after/slide-003.jpg").status_code == 404


def test_a_skipped_review_has_its_code_also_for_runs_recorded_before_the_code(built):
    """The interface says why the review did not look by its code (web/src/lib/designEye.ts); the English reason stays
    for the log. A run recorded before the code was kept gets it from its reason."""
    c, mod, gid = built
    vdir = mod.store.generation_dir(gid) / "structured"
    m = json.loads((vdir / "run_manifest.json").read_text(encoding="utf-8"))
    m["eyes"] = {"looked": 0, "calls": 0, "seconds": 0.0, "skipped": "no time left in the generation's model budget", "flagged": [], "fixed": [], "kept": []}
    (vdir / "run_manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    eye = c.get(f"/api/generations/{gid}").json()["variants"][0]["eyes"]
    assert eye["skipped_code"] == "no_time" and eye["looked"] == 0 and eye["slides"] == []
    m["eyes"] |= {"skipped": "failed: boom", "skipped_code": "failed"}
    (vdir / "run_manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    assert c.get(f"/api/generations/{gid}").json()["variants"][0]["eyes"]["skipped_code"] == "failed"
    # it looked: no code
    m["eyes"] |= {"looked": 3, "skipped": None, "skipped_code": None}
    (vdir / "run_manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    assert c.get(f"/api/generations/{gid}").json()["variants"][0]["eyes"]["skipped_code"] is None
