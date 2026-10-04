"""Renaming a template for people (PATCH /api/templates/{id}): the pencil next to its name. The file and its analysis
stay as they are; the cards, the build and the deck show the new name."""

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
    (d / "manifest.json").write_text(json.dumps({"template_id": TID, "source_file": "source.pptx", "patterns": []}), encoding="utf-8")
    monkeypatch.setattr(A, "store", store)
    return TestClient(A.app), tmp_path


def _listed(c):
    return next(t for t in c.get("/api/templates").json() if t["template_id"] == TID)


def test_a_template_without_a_name_of_its_own(client):
    c, _ = client
    assert _listed(c)["title"] is None


def test_rename_and_back(client):
    c, root = client
    manifest_before = (root / "templates" / TID / "manifest.json").read_text(encoding="utf-8")
    r = c.patch(f"/api/templates/{TID}", json={"title": "  VK   Education  "})
    assert r.status_code == 200 and r.json()["title"] == "VK Education"
    assert _listed(c)["title"] == "VK Education"
    # the analysis is not touched: the list's order (by the manifest's time) and the file name stay
    assert (root / "templates" / TID / "manifest.json").read_text(encoding="utf-8") == manifest_before
    assert _listed(c)["source_file"] == "source.pptx"
    # an empty name brings back the file's
    assert c.patch(f"/api/templates/{TID}", json={"title": "   "}).json()["title"] is None
    assert _listed(c)["title"] is None


def test_a_long_name_is_cut(client):
    c, _ = client
    assert len(c.patch(f"/api/templates/{TID}", json={"title": "Ш" * 300}).json()["title"]) == 80


def test_unknown_and_malformed_ids(client):
    c, _ = client
    assert c.patch("/api/templates/ffffffffffffffff", json={"title": "x"}).status_code == 404
    assert c.patch("/api/templates/..%2F..%2Fetc", json={"title": "x"}).status_code in (404, 405)
