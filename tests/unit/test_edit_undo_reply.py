"""«Верни как было» with no kept version: a variant never changed and a variant whose every change was already taken
back get different, true answers; the variant payload's edit log names what each undo took back (`undo_of`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from verstka.pipeline import revise as R

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"


@pytest.fixture()
def app_module(tmp_path, monkeypatch):
    monkeypatch.setenv("VERSTKA_WORKSPACE", str(tmp_path / "ws"))
    import importlib

    import verstka.api.app as mod

    importlib.reload(mod)
    return mod


def _undo(mod, vdir: Path, monkeypatch) -> dict:
    from verstka.api.jobs import Job

    (vdir / "outline.json").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(mod, "_variant_dir", lambda gid, strategy: vdir)
    monkeypatch.setattr(mod.store, "read_generation_meta", lambda gid: {"template_id": "t"})
    monkeypatch.setattr(mod.store, "manifest", lambda tid: object())
    run = mod._edit_job("g", "structured", mod.EditRequestBody(message="Верни как было", slide=2))
    return run(Job(id="j", kind="edit"))


def test_undo_on_a_variant_never_changed(app_module, tmp_path, monkeypatch):
    vdir = tmp_path / "structured"
    vdir.mkdir()
    res = _undo(app_module, vdir, monkeypatch)
    assert res == {"reply": "Этот вариант ещё не меняли — возвращать нечего.", "changed": False}


def test_undo_after_every_change_was_taken_back(app_module, tmp_path, monkeypatch):
    vdir = tmp_path / "structured"
    vdir.mkdir()
    # fix → undo → fix → undo: the log has four entries, versions/ is empty
    for _ in range(2):
        R.log_edit(vdir, {"version": 1, "undo_of": None, "kind": "fix", "slides": [8], "request": "Исправь замечания на слайде 8", "reply": "…"})
        R.log_edit(vdir, {"version": None, "undo_of": 1, "kind": "undo", "slides": [], "request": "Верни как было", "reply": "…"})
    assert R.version_numbers(vdir) == []
    res = _undo(app_module, vdir, monkeypatch)
    assert res == {"reply": "Все правки уже отменены — возвращать нечего.", "changed": False}
    assert len(R.read_edits(vdir)) == 4  # nothing is logged for an undo that did nothing
    assert [e["undo_of"] for e in json.loads((vdir / "edits.json").read_text(encoding="utf-8"))] == [None, 1, None, 1]
    # the web replays the log to know whether «Вернуть как было» has anything to take back
    (vdir / "deck.pptx").write_bytes(b"")
    payload = app_module._variant_payload(tmp_path, "structured", use_models=False, agent_events=[])
    assert [(e["kind"], e["version"], e["undo_of"]) for e in payload["edits"]] == [("fix", 1, None), ("undo", None, 1)] * 2
