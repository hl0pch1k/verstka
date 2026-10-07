import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VERSTKA_WORKSPACE", str(tmp_path / "ws"))
    import importlib

    import verstka.api.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app), app_module


def _wait(client, job_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.3)
    raise TimeoutError(job_id)


def test_api_flow(client, simple_deck):
    c, mod = client
    assert c.get("/api/health").json()["ok"]
    assert {s["name"] for s in c.get("/api/strategies").json()} == {"structured", "visual", "compact"}
    assert any(ch["id"] == "text_overflow" for ch in c.get("/api/checks").json())
    # upload + analyze
    with open(simple_deck, "rb") as f:
        r = c.post("/api/templates", files={"file": ("simple.pptx", f, "application/octet-stream")}, data={"use_models": "false"})
    assert r.status_code == 200
    job = _wait(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    tid = job["result"]["template_id"]
    t = c.get(f"/api/templates/{tid}").json()
    assert t["template_id"] == tid and t["patterns"] and "narration" in t
    assert c.get("/api/templates").json()[0]["template_id"] == tid
    # generate from an outline (offline), single strategy, no exports beyond pptx
    outline = json.loads(FIXTURE.read_text(encoding="utf-8"))
    r = c.post("/api/generations", json={"template_id": tid, "outline": outline, "strategies": ["structured"], "use_models": False, "exports": []})
    assert r.status_code == 200
    gid = r.json()["generation_id"]
    job = _wait(c, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    g = c.get(f"/api/generations/{gid}").json()
    assert g["status"] == "done" and g["job_id"] == job["id"]
    assert c.get("/api/generations").json()[0]["status"] == "done"
    v = g["variants"][0]
    assert v["strategy"] == "structured" and len(v["outline"]["slides"]) == 12 and v["audit"] is not None and v["run_manifest"]["strategy"] == "structured"
    assert "deck.pptx" in v["files"]
    assert c.get(v["files"]["deck.pptx"]).status_code == 200
    ex = c.get(f"/api/generations/{gid}/structured/explain/5").json()
    assert "Слайд 5" in ex["text"]
    # chat agent answers about the plan and the audit
    r = c.post("/api/chat", json={"session_id": "s1", "message": "покажи план", "template_id": tid, "generation_id": gid}).json()
    assert r["intent"] == "plan" and "Вариант" in r["reply"] and {"type": "open_tab", "tab": "plan"} in r["actions"]
    r = c.post("/api/chat", json={"session_id": "s1", "message": "почему слайд 4 такой?"}).json()
    assert r["intent"] == "explain_slide" and "Слайд 4" in r["reply"]
    r = c.post("/api/chat", json={"session_id": "s1", "message": "покажи аудит"}).json()
    assert r["intent"] == "audit" and "Проверка качества" in r["reply"] and {"type": "open_tab", "tab": "audit"} in r["actions"]
    assert "«Структурный»" in r["reply"] and "structured" not in r["reply"]  # strategy titles, not ids
    # fixes endpoint accepts a request
    r = c.post(f"/api/generations/{gid}/structured/fixes", json={"all_deterministic": True})
    assert r.status_code == 200
    job = _wait(c, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    # the per-variant fix lock is released once the job is over
    r = c.post(f"/api/generations/{gid}/structured/fixes", json={"all_deterministic": True})
    assert r.status_code == 200
    job = _wait(c, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    # the chat agent can start autofix for every variant
    r = c.post("/api/chat", json={"session_id": "s1", "message": "исправь все ошибки"}).json()
    assert r["intent"] == "fix_all" and r["actions"] and r["actions"][0]["type"] == "jobs"
    for j in r["actions"][0]["jobs"]:
        assert _wait(c, j["job_id"], timeout=300)["status"] == "done"


def test_a_build_interrupted_by_a_restart_ends_as_failed(client):
    """A build whose job this server does not run (started before a restart) is no longer «running»: the list and the
    deck page say it failed and why, and its template can be deleted; a build a few ms old (no job id yet) is kept."""
    c, mod = client
    gid, _ = mod.store.new_generation_dir()
    mod.store.write_generation_meta(gid, {"id": gid, "template_id": "t", "strategies": ["structured"], "status": "running", "job_id": "gone0000", "created_at": time.time() - 600})
    fresh, _ = mod.store.new_generation_dir()
    mod.store.write_generation_meta(fresh, {"id": fresh, "template_id": "t", "strategies": ["structured"], "status": "running", "created_at": time.time()})
    listed = {g["id"]: g for g in c.get("/api/generations").json()}
    assert listed[gid]["status"] == "failed" and "перезапускался" in listed[gid]["error"]
    assert listed[fresh]["status"] == "running"
    assert mod.store.read_generation_meta(gid)["status"] == "failed"  # kept, not only shown
    assert c.get(f"/api/generations/{gid}").json()["status"] == "failed"


def test_an_old_deck_uploaded_to_improve_comes_back_as_its_text_and_its_audit(client, simple_deck):
    """«Улучшить готовую презентацию»: the deck is analysed as the template, read back as the author's «Слайд N» text,
    and audited as it is (the «было» of «было → стало»); a generation keeps where it came from."""
    c, mod = client
    with open(simple_deck, "rb") as f:
        r = c.post("/api/templates", files={"file": ("old.pptx", f, "application/octet-stream")}, data={"use_models": "false", "improve": "true"})
    assert r.status_code == 200
    job = _wait(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    src = job["result"]["improve"]
    assert src["name"] == "old.pptx" and src["slides"] >= 3 and src["brief"].startswith("Слайд 1.")
    assert set(src["audit"]) == {"score", "errors", "warnings"} and src["problems"] == []  # no vision model in the tests
    tid = job["result"]["template_id"]
    assert src["template_id"] == tid  # its pictures follow the deck into any template
    r = c.post("/api/generations", json={"template_id": tid, "brief": src["brief"], "strategies": ["structured"], "use_models": False, "exports": [],
                                         "eyes": True, "improved_from": {"name": src["name"], "slides": src["slides"], "audit": src["audit"]}})
    assert r.status_code == 200
    job = _wait(c, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    g = c.get(f"/api/generations/{r.json()['generation_id']}").json()
    assert g["improved_from"]["name"] == "old.pptx" and g["eyes"] is True


def test_an_old_deck_whose_text_cannot_be_read_says_so_in_russian_and_the_titles_of_its_text(client, monkeypatch, tmp_path):
    """«Улучшить готовую»: a deck whose text cannot be read stays a template, and the interface says why in Russian
    (never an English exception); the titles of a read-back text end with their line («Слайд 3.» over a paragraph)."""
    import types

    import verstka.ingest.deck_text as D

    c, mod = client

    def broken(path):
        raise KeyError("no relationship with key 'rId777'")

    monkeypatch.setattr(D, "deck_text", broken)
    monkeypatch.setattr(mod.store, "workspace", lambda tid: types.SimpleNamespace(source=tmp_path / "source.pptx", dir=tmp_path))
    with pytest.raises(ValueError) as e:
        mod._improve_source(types.SimpleNamespace(template_id="t1"), "old.pptx")
    assert str(e.value) == "Не удалось прочитать текст презентации — она добавлена как шаблон"
    brief = "Слайд 1. Титульный\nНазвание: «Итоги квартала».\n\nСлайд 2.\n\nВыручка выросла на 34%.\n\nСлайд 3. Планы\n\nТекст.\n"
    assert mod._slide_titles(brief) == {1: "Итоги квартала", 2: "", 3: "Планы"}
