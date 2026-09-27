"""Deleting a template from the library (DELETE /api/templates/{id}): the trash button on a template tile."""

import json

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store

TID = "0123456789abcdef"


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    d = tmp_path / "templates" / TID
    d.mkdir(parents=True)
    (d / "source.pptx").write_bytes(b"x")
    (d / "manifest.json").write_text(json.dumps({"template_id": TID, "source_file": "Brand.pptx", "patterns": []}), encoding="utf-8")
    monkeypatch.setattr(A, "store", store)
    return TestClient(A.app), store, tmp_path


def test_delete_removes_the_template(client):
    c, store, root = client
    assert c.delete(f"/api/templates/{TID}").json() == {"deleted": True}
    assert not (root / "templates" / TID).exists()
    assert c.delete(f"/api/templates/{TID}").status_code == 404


def test_unknown_and_malformed_ids(client):
    c, _, _ = client
    assert c.delete("/api/templates/ffffffffffffffff").status_code == 404
    assert c.delete("/api/templates/..%2F..%2Fetc").status_code in (404, 405)


def test_not_while_a_deck_is_built_on_it(client):
    c, store, root = client
    gid, gdir = store.new_generation_dir()
    store.write_generation_meta(gid, {"id": gid, "template_id": TID, "status": "running"})
    r = c.delete(f"/api/templates/{TID}")
    assert r.status_code == 409 and "собирается" in r.json()["detail"]
    assert (root / "templates" / TID).exists()
