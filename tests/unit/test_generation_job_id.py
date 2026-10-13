"""A page reloaded mid-build finds its build again: GET /api/generations/{gid} (and the list) carry the job id of the
generation's meta, so the client subscribes to the running job (runJob) and opens the build screen."""

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(A, "store", store)
    # the job this server runs (a build started before the reload): _settle_orphan keeps such a build «running»
    monkeypatch.setattr(A.runner, "get", lambda jid: object() if jid == "job0running" else None)
    return TestClient(A.app), store


def test_a_running_generation_says_its_job(client):
    c, store = client
    gid, _ = store.new_generation_dir()
    store.write_generation_meta(gid, {"id": gid, "template_id": "0123456789abcdef", "strategies": ["structured"], "status": "running", "job_id": "job0running"})
    g = c.get(f"/api/generations/{gid}").json()
    assert g["status"] == "running"
    assert g["job_id"] == "job0running"
    listed = {x["id"]: x for x in c.get("/api/generations").json()}
    assert listed[gid]["job_id"] == "job0running"


def test_a_generation_without_a_job_id_has_none(client):
    c, store = client
    gid, _ = store.new_generation_dir()
    store.write_generation_meta(gid, {"id": gid, "template_id": "0123456789abcdef", "strategies": ["structured"], "status": "done"})
    assert "job_id" not in c.get(f"/api/generations/{gid}").json()
