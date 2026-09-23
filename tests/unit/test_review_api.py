"""Regression tests for the API review: path traversal, chat intents, job status, SSE, uploads, locks, eviction."""

from __future__ import annotations

import importlib
import io
import json
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_api import _wait, client  # noqa: F401  (shared fixture)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"
BRIEFS = sorted((Path(__file__).resolve().parents[2] / "examples" / "briefs").glob("*.md"))


def _analyze(c, simple_deck) -> str:
    with open(simple_deck, "rb") as f:
        r = c.post("/api/templates", files={"file": ("simple.pptx", f, "application/octet-stream")}, data={"use_models": "false"})
    assert r.status_code == 200, r.text
    job = _wait(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    return job["result"]["template_id"]


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in entries.items():
            z.writestr(name, text)
    return buf.getvalue()


# ---------------------------------------------------------------------------- API-1: path traversal


def test_traversal_is_rejected_and_workspace_intact(client):
    c, mod = client
    root = mod.store.root
    (root / "secret.txt").write_text("top secret", encoding="utf-8")
    (root / "deck.pptx").write_bytes(b"PK-root")
    (root / "templates" / "tpl1" / "thumbs").mkdir(parents=True)
    (root / "templates" / "tpl1" / "thumbs" / "p1.png").write_bytes(b"\x89PNG")
    (root / "templates" / "tpl1-evil").mkdir(parents=True)
    (root / "templates" / "tpl1-evil" / "private.txt").write_text("private", encoding="utf-8")
    (root / "runs" / "g1" / "structured").mkdir(parents=True)
    (root / "runs" / "g1" / "structured" / "deck.pptx").write_bytes(b"PK-g1")
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    # legitimate files are still served
    assert c.get("/api/templates/tpl1/files/thumbs/p1.png").status_code == 200
    assert c.get("/api/generations/g1/structured/files/deck.pptx").content == b"PK-g1"
    for url in (
        "/api/templates/%2e%2e/files/secret.txt",
        "/api/templates/tpl1/files/%2e%2e/tpl1-evil/private.txt",
        "/api/templates/tpl1/files/%2e%2e/%2e%2e/secret.txt",
        "/api/generations/%2e%2e/%2e/files/deck.pptx",
        "/api/generations/%2e%2e/%2e/slides/slide-001.jpg",
        "/api/templates/nope/files/x.txt",
        "/api/templates/%2e%2e",
        "/api/generations/%2e%2e",
        "/api/generations/g1/nostrategy/files/deck.pptx",
        "/api/generations/g1/nostrategy/slides/slide-001.jpg",
        "/api/generations/g1/nostrategy/explain/1",
        "/api/generations/g1/nostrategy/diff/g1/structured",
        "/api/generations/g1/structured/diff/g1/nostrategy",
    ):
        r = c.get(url)
        assert r.status_code == 404, (url, r.status_code, r.text[:120])
    assert c.delete("/api/generations/%2e%2e").status_code == 404
    assert c.delete("/api/generations/%2e%2e%2f%2e%2e").status_code in (404, 405)  # decodes to ../.. and matches no DELETE route
    assert c.post("/api/generations/g1/nostrategy/fixes", json={"all_deterministic": True}).status_code == 404
    # a valid but unknown id keeps the old response shape
    assert c.delete("/api/generations/20990101-000000-abcdef").json() == {"deleted": False}
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before


def test_store_rejects_unsafe_ids(client):
    _, mod = client
    st = mod.store
    for bad in ("..", "../x", "a/b", ".hidden", "", "x" * 65, "g1\x00", "g1 ", "../../etc"):
        assert st.generation_dir(bad) is None, bad
        assert st.delete_generation(bad) is False, bad
        assert st.read_generation_meta(bad) is None, bad
        assert st.write_generation_meta(bad, {"id": bad}) is False, bad
        assert st.manifest(bad) is None, bad
        with pytest.raises(FileNotFoundError):
            st.workspace(bad)
    assert not (st.root / "generation.json").exists() and not (st.runs / "generation.json").exists()
    gid, gdir = st.new_generation_dir()
    assert st.generation_dir(gid) == gdir and st.write_generation_meta(gid, {"id": gid}) is True
    assert st.read_generation_meta(gid) == {"id": gid}


def test_cors_is_restricted_to_dev_origins(client):
    c, _ = client
    r = c.options("/api/generations/x", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "DELETE"})
    assert "access-control-allow-origin" not in r.headers
    r = c.options("/api/generations/x", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_origins_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VERSTKA_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("VERSTKA_CORS_ORIGINS", "https://verstka.example, http://localhost:5173")
    import verstka.api.app as mod

    importlib.reload(mod)
    c = TestClient(mod.app)
    r = c.options("/api/health", headers={"Origin": "https://verstka.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://verstka.example"
    r = c.options("/api/health", headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


# ---------------------------------------------------------------------------- API-2: chat intent router


@pytest.mark.parametrize(
    "message, expected",
    [
        ("исправь все ошибки", "fix_all"),
        ("Исправь всё", "fix_all"),
        ("почини все замечания", "fix_all"),
        ("Сгенерируй презентацию: пилот умных напоминаний, аудитория — комитет", "generate"),
        ("сделай презентацию про облако", "generate"),
        ("Собери слайды для совета директоров", "generate"),
        ("покажи аудит", "audit"),
        ("какие ошибки нашёл аудит?", "audit"),
        ("почему слайд 4 такой", "explain_slide"),
        ("покажи план", "plan"),
        ("экспорт в pdf", "export"),
        ("расскажи о шаблоне", "template"),
        ("привет", "help"),
    ],
)
def test_intent_router(client, message, expected):
    _, mod = client
    assert mod._intent(message)[0] == expected


def test_intent_explain_slide_index(client):
    _, mod = client
    assert mod._intent("почему слайд 4 такой") == ("explain_slide", {"index": 4})


@pytest.mark.parametrize("brief", BRIEFS, ids=[b.name for b in BRIEFS])
def test_example_briefs_route_to_generate(client, brief):
    _, mod = client
    assert mod._intent(brief.read_text(encoding="utf-8"))[0] == "generate"


def test_chat_brief_starts_generation(client, monkeypatch):
    c, mod = client
    seen: list = []

    def fake_create(req):
        seen.append(req)
        return {"job_id": "job1", "generation_id": "gen1"}

    monkeypatch.setattr(mod, "create_generation", fake_create)
    text = BRIEFS[0].read_text(encoding="utf-8")
    r = c.post("/api/chat", json={"session_id": "chat-brief", "message": text, "template_id": "tpl"}).json()
    assert r["intent"] == "generate" and r["generation_id"] == "gen1"
    assert r["actions"] == [{"type": "generation_started", "job_id": "job1", "generation_id": "gen1"}]
    assert seen and seen[0].brief == text and seen[0].template_id == "tpl"


# ---------------------------------------------------------------------------- F7: generation status


def test_invalid_outline_is_rejected_with_422(client, simple_deck):
    c, mod = client
    tid = _analyze(c, simple_deck)
    r = c.post("/api/generations", json={"template_id": tid, "outline": {"title": "x", "slides": [{"kind": "nope"}]}, "strategies": ["structured"], "use_models": False, "exports": []})
    assert r.status_code == 422
    assert "slides" in r.json()["detail"] and "kind" in r.json()["detail"]
    assert c.get("/api/generations").json() == []
    assert not any(mod.store.runs.iterdir())


def test_blank_brief_is_rejected_with_422(client, simple_deck):
    c, _ = client
    tid = _analyze(c, simple_deck)
    for brief in ("   \n\t", "---\nslides: 5\n---\n"):
        r = c.post("/api/generations", json={"template_id": tid, "brief": brief, "strategies": ["structured"], "use_models": False, "exports": []})
        assert r.status_code == 422, (brief, r.text)
    assert c.get("/api/generations").json() == []


def test_failed_generation_is_marked_failed(client, simple_deck, monkeypatch):
    c, mod = client
    tid = _analyze(c, simple_deck)

    def boom(*args, **kwargs):
        raise RuntimeError("boom in the pipeline")

    monkeypatch.setattr(mod, "_run_generation", boom)
    outline = json.loads(FIXTURE.read_text(encoding="utf-8"))
    r = c.post("/api/generations", json={"template_id": tid, "outline": outline, "strategies": ["structured"], "use_models": False, "exports": []})
    assert r.status_code == 200
    gid, job_id = r.json()["generation_id"], r.json()["job_id"]
    meta = mod.store.read_generation_meta(gid)
    assert meta["status"] in ("running", "failed") and meta["job_id"] == job_id and meta.get("created_at")
    job = _wait(c, job_id)
    assert job["status"] == "failed"
    meta = mod.store.read_generation_meta(gid)
    assert meta["status"] == "failed" and "boom in the pipeline" in meta["error"] and meta["job_id"] == job_id
    listed = c.get("/api/generations").json()
    assert [g["id"] for g in listed] == [gid] and listed[0]["status"] == "failed"
    g = c.get(f"/api/generations/{gid}").json()
    assert g["status"] == "failed" and g["variants"] == []


# ---------------------------------------------------------------------------- F8: SSE termination and subscribe race


def _collect_events(c, job_id, on_event=None, timeout=30):
    events = []
    t0 = time.time()
    with c.stream("GET", f"/api/jobs/{job_id}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data:"):
                ev = json.loads(line[5:])
                events.append(ev)
                if on_event:
                    on_event(ev)
            assert time.time() - t0 < timeout, "stream did not terminate"
    return events


def test_sse_stream_survives_progress_message_starting_with_failed(client):
    c, mod = client
    gate = threading.Event()

    def fn(job):
        job.emit("failed to reach model, retrying", 0.3)
        gate.wait(20)
        job.emit("almost", 0.9)
        return {"ok": True}

    job = mod.runner.submit("test", fn)
    time.sleep(0.2)
    events = _collect_events(c, job.id, on_event=lambda ev: gate.set() if ev["message"].startswith("failed to reach") else None)
    msgs = [e["message"] for e in events]
    assert "failed to reach model, retrying" in msgs and "almost" in msgs
    assert events[-1]["status"] == "done" and events[-1]["message"] == "done"


def test_sse_stream_ends_on_failed_job(client):
    c, mod = client

    def fn(job):
        raise RuntimeError("kaput")

    job = mod.runner.submit("test", fn)
    _wait(c, job.id)
    events = _collect_events(c, job.id)
    assert events[-1]["status"] == "failed" and events[-1]["message"].startswith("failed: kaput")


def test_subscribe_does_not_lose_a_concurrent_final_event():
    from verstka.api.jobs import Job

    class SlowList(list):
        # widen the race window: the replay slice is taken, then the emitter gets a chance to run
        def __getitem__(self, item):
            out = super().__getitem__(item)
            if isinstance(item, slice):
                time.sleep(0.1)
            return out

    job = Job(id="x", kind="t")
    job.events = SlowList()
    job.status = "running"

    def finish():
        time.sleep(0.02)
        job.status = "done"
        job.emit("done", 1.0)

    t = threading.Thread(target=finish)
    t.start()
    q = job.subscribe()
    t.join()
    got = []
    while not q.empty():
        got.append(q.get_nowait())
    assert any(e["message"] == "done" and e["status"] == "done" for e in got), got


# ---------------------------------------------------------------------------- UPLOAD


def test_upload_rejects_payloads_that_are_not_pptx(client):
    c, mod = client
    uploads = mod.store.uploads
    r = c.post("/api/templates", files={"file": ("junk.pptx", io.BytesIO(b"x" * 4096), "application/octet-stream")}, data={"use_models": "false"})
    assert r.status_code == 400, r.text
    r = c.post("/api/templates", files={"file": ("nopres.pptx", io.BytesIO(_zip_bytes({"hello.txt": "x"})), "application/octet-stream")}, data={"use_models": "false"})
    assert r.status_code == 400, r.text
    assert not any(uploads.iterdir())
    assert not any((mod.store.root / "templates").iterdir())


def test_upload_size_cap(client, monkeypatch):
    c, mod = client
    monkeypatch.setenv("VERSTKA_MAX_UPLOAD_MB", "1")
    big = _zip_bytes({"ppt/presentation.xml": "x" * (2 << 20)})
    r = c.post("/api/templates", files={"file": ("big.pptx", io.BytesIO(big), "application/octet-stream")}, data={"use_models": "false"})
    assert r.status_code == 413, r.text
    assert not any(mod.store.uploads.iterdir())


def test_failed_analysis_removes_upload_and_template_dir(client):
    c, mod = client
    payload = _zip_bytes({"ppt/presentation.xml": "<broken", "[Content_Types].xml": "<Types/>"})
    r = c.post("/api/templates", files={"file": ("broken.pptx", io.BytesIO(payload), "application/octet-stream")}, data={"use_models": "false"})
    assert r.status_code == 200, r.text
    job = _wait(c, r.json()["job_id"])
    assert job["status"] == "failed"
    assert not any(mod.store.uploads.iterdir())
    assert not any((mod.store.root / "templates").iterdir())
    assert c.get("/api/templates").json() == []


# ---------------------------------------------------------------------------- LOCKS / EVICTION


def test_concurrent_fixes_for_same_variant_get_409(client, simple_deck, monkeypatch):
    c, mod = client
    tid = _analyze(c, simple_deck)
    outline = json.loads(FIXTURE.read_text(encoding="utf-8"))
    r = c.post("/api/generations", json={"template_id": tid, "outline": outline, "strategies": ["structured"], "use_models": False, "exports": [], "autofix": False})
    assert r.status_code == 200
    gid = r.json()["generation_id"]
    job = _wait(c, r.json()["job_id"], timeout=300)
    assert job["status"] == "done", job["error"]
    import verstka.audit.autofix as af

    real = af.autofix_loop
    started, gate = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        started.set()
        gate.wait(30)
        return real(*args, **kwargs)

    monkeypatch.setattr(af, "autofix_loop", slow)
    r1 = c.post(f"/api/generations/{gid}/structured/fixes", json={"all_deterministic": True})
    assert r1.status_code == 200
    assert started.wait(10)
    r2 = c.post(f"/api/generations/{gid}/structured/fixes", json={"all_deterministic": True})
    assert r2.status_code == 409
    gate.set()
    assert _wait(c, r1.json()["job_id"], timeout=300)["status"] == "done"
    monkeypatch.setattr(af, "autofix_loop", real)
    r3 = c.post(f"/api/generations/{gid}/structured/fixes", json={"all_deterministic": True})
    assert r3.status_code == 200
    assert _wait(c, r3.json()["job_id"], timeout=300)["status"] == "done"


def test_job_runner_evicts_oldest_finished_jobs():
    from verstka.api.jobs import JobRunner

    runner = JobRunner(max_jobs=20)
    gate = threading.Event()
    running = runner.submit("t", lambda job: gate.wait(20))
    ids = [runner.submit("t", lambda job: 1).id for _ in range(30)]
    for jid in ids:
        while runner.get(jid) is not None and runner.get(jid).status not in ("done", "failed"):
            time.sleep(0.01)
    last = runner.submit("t", lambda job: 1)
    assert len(runner.jobs) <= 20
    assert runner.get(running.id) is not None and runner.get(last.id) is not None and runner.get(ids[0]) is None
    gate.set()


def test_chat_sessions_are_capped(client):
    c, mod = client
    for i in range(505):
        assert c.post("/api/chat", json={"session_id": f"s{i}", "message": "привет"}).status_code == 200
    assert len(mod._chat_sessions) <= 500
    assert "s504" in mod._chat_sessions and "s0" not in mod._chat_sessions


def test_generation_meta_is_never_read_half_written(tmp_path):
    """The job thread rewrites generation.json while the UI polls it: a reader must always see a whole file."""
    import threading

    from verstka.api.store import Store

    s = Store(tmp_path)
    gid, _ = s.new_generation_dir()
    s.write_generation_meta(gid, {"id": gid, "status": "running", "brief": "x" * 20000})
    stop, errors = [False], []

    def writer():
        i = 0
        while not stop[0]:
            s.merge_generation_meta(gid, {"status": "running" if i % 2 else "failed", "n": i})
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(3000):
            try:
                assert s.read_generation_meta(gid)["id"] == gid
            except Exception as e:  # noqa: BLE001
                errors.append(type(e).__name__)
    finally:
        stop[0] = True
        t.join()
    assert errors == [] and not list(s.generation_dir(gid).glob("*.tmp"))


def test_audit_is_told_in_words_not_check_ids():
    from verstka.api.narrator import describe_audit
    from verstka.schemas.audit import AuditReport

    report = AuditReport.model_validate({
        "deck": "deck.pptx", "template_id": "t1",
        "summary": {"score": 94, "errors": 0, "warnings": 2, "infos": 0, "model_flags": 0, "checks_run": []},
        "issues": [
            {"id": "i1", "check_id": "size_not_in_scale", "severity": "warn", "kind": "deterministic", "slide": 3, "message": "кегль 48"},
            {"id": "i2", "check_id": "size_not_in_scale", "severity": "warn", "kind": "deterministic", "slide": 4, "message": "кегль 44"},
        ],
        "applied_fixes": [{"iteration": 1, "action": "rematch"}, {"iteration": 2, "action": "xml"}],
        "iterations": 2,
    })
    text = describe_audit(report)
    assert text.startswith("Аудит: оценка 94 из 100, ошибок нет, предупреждений 2.")
    assert "Кегль не из типографической шкалы шаблона ×2" in text and "size_not_in_scale" not in text
    assert "Автофикс (2 прохода): подбор другого макета, правка разметки." in text
