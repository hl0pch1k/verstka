"""The slide previews a variant has so far (GET /api/generations/{gid}/{strategy}/slides): the build screen asks for
these while the export renders them, so it never requests an image that is not there yet."""

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(A, "store", store)
    gid, gdir = store.new_generation_dir()
    store.write_generation_meta(gid, {"id": gid, "template_id": "0123456789abcdef", "status": "running"})
    return TestClient(A.app), gid, gdir


def test_none_before_the_export_then_the_rendered_ones(client):
    c, gid, gdir = client
    assert c.get(f"/api/generations/{gid}/structured/slides").json() == {"slides": []}
    d = gdir / "structured" / "slides"
    d.mkdir(parents=True)
    for n in (2, 1):
        (d / f"slide-{n:03d}.jpg").write_bytes(b"\xff\xd8")
    (d / "notes.txt").write_text("x")
    assert c.get(f"/api/generations/{gid}/structured/slides").json() == {"slides": ["slide-001.jpg", "slide-002.jpg"]}


def test_unknown_variant_or_generation(client):
    c, gid, _ = client
    assert c.get(f"/api/generations/{gid}/nope/slides").status_code == 404
    assert c.get("/api/generations/20990101-000000-000000/structured/slides").status_code == 404
