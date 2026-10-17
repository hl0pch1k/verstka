"""Сервер на Linux и в работе: LibreOffice из официального пакета (/opt/libreofficeX.Y) и $VERSTKA_SOFFICE, логотип SVG
без rsvg-convert, имена файлов в NFC, русская ошибка 500, наборы данных, которыми собрана презентация, не удаляются, и
уборка старых наборов при запуске. Без ключей и без сети."""

from __future__ import annotations

import io
import json
import os
import shutil
import time
import unicodedata
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "examples" / "brandbook-vk-cloud"
REVENUE = ("Месяц;Выручка, млн ₽\n" + "\n".join(f"2025-{m:02d};{100 + m * 7}" for m in range(1, 13)) + "\n").encode("utf-8")


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(A, "store", store)
    return TestClient(A.app, raise_server_exceptions=False), store, tmp_path


def _wait(jid: str, timeout: float = 60) -> A.Job:
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = A.runner.get(jid)
        if job is not None and job.events and job.events[-1].get("status") in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(jid)


# ---------------------------------------------------------------------------------------------- LibreOffice на Linux


def _fake_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_soffice_from_the_environment_first(tmp_path, monkeypatch):
    import verstka.ingest.render as R

    exe = _fake_exe(tmp_path / "lo" / "program" / "soffice")
    monkeypatch.setenv("VERSTKA_SOFFICE", str(exe))
    assert R.find_soffice() == str(exe)
    monkeypatch.setenv("VERSTKA_SOFFICE", str(tmp_path / "nope"))  # not runnable: looked for elsewhere
    assert R.find_soffice() != str(tmp_path / "nope")


def test_soffice_of_the_official_linux_package(monkeypatch):
    """The .deb/.rpm from libreoffice.org: /opt/libreofficeX.Y/program/soffice, nothing on PATH — the newest first."""
    import glob

    import verstka.ingest.render as R

    monkeypatch.delenv("VERSTKA_SOFFICE", raising=False)
    monkeypatch.setattr(R.shutil, "which", lambda name: None)
    builds = ["/opt/libreoffice7.6/program/soffice", "/opt/libreoffice24.8/program/soffice", "/opt/libreoffice24.2/program/soffice"]
    monkeypatch.setattr(glob, "glob", lambda pattern: list(builds) if pattern == "/opt/libreoffice*/program/soffice" else [])
    monkeypatch.setattr(R, "_runnable", lambda p: p in builds)
    assert R.find_soffice() == "/opt/libreoffice24.8/program/soffice"
    monkeypatch.setattr(R, "_runnable", lambda p: p == "/usr/lib/libreoffice/program/soffice")
    assert R.find_soffice() == "/usr/lib/libreoffice/program/soffice"
    monkeypatch.setattr(R, "_runnable", lambda p: False)
    assert R.find_soffice() is None


def test_libreoffice_fonts_beside_its_soffice(tmp_path, monkeypatch):
    import verstka.ingest.render as R
    import verstka.rendering.fonts as F

    exe = _fake_exe(tmp_path / "libreoffice24.8" / "program" / "soffice")
    monkeypatch.setattr(R, "find_soffice", lambda: str(exe))
    assert tmp_path.resolve() / "libreoffice24.8" / "share" / "fonts" / "truetype" in F._lo_font_dirs()
    assert set(F._LO_FONT_DIRS) <= set(F._lo_font_dirs())


def test_an_svg_logo_is_drawn_without_rsvg_convert(tmp_path, monkeypatch):
    import verstka.brand.logos as L

    monkeypatch.setattr(L.shutil, "which", lambda name: None)
    svg = tmp_path / "mark.svg"  # no PNG twin beside it
    shutil.copyfile(BRAND / "logos" / "mark.svg", svg)
    data, ext = L._raster(svg)
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    assert ext == "png" and im.size[1] == 512 and im.convert("RGBA").getchannel("A").getbbox() is not None


# ---------------------------------------------------------------------------------------------- имена в NFC


def test_data_file_names_are_nfc(api):
    c, _, _ = api
    nfd = unicodedata.normalize("NFD", "Выручка за май и июнь.csv")
    assert nfd != unicodedata.normalize("NFC", nfd)
    (card,) = c.post("/api/datasets", files=[("files", (nfd, REVENUE, "text/csv"))]).json()
    assert card["file"] == "Выручка за май и июнь.csv"
    assert A.safe_file_name(unicodedata.normalize("NFD", "Мой брендбук.pdf"), "x") == "Мой брендбук.pdf"


def test_zip_entries_are_nfc(api):
    c, _, root = api
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Бренд/tokens.json", (BRAND / "tokens.json").read_bytes())
        z.writestr(unicodedata.normalize("NFD", "Бренд/logos/мой знак.png"), (BRAND / "logos" / "mark.png").read_bytes())
    r = c.post("/api/brandbooks", files={"file": ("Бренд.zip", buf.getvalue(), "application/zip")})
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.error
    files = [lg["file"] for lg in job.result["brand"]["logos"]]
    assert files and all(f == unicodedata.normalize("NFC", f) for f in files)
    assert any("мой знак" in f for f in files)


# ---------------------------------------------------------------------------------------------- ошибки


def test_an_unexpected_error_is_a_calm_russian_500(api, monkeypatch):
    c, store, _ = api
    monkeypatch.setattr(store, "list_templates", lambda: 1 / 0)
    r = c.get("/api/templates")
    assert r.status_code == 500 and r.json() == {"detail": A._SERVER_ERROR}


def test_unknown_strategies_are_listed_readably(api, monkeypatch):
    c, store, _ = api
    monkeypatch.setattr(store, "manifest", lambda tid: object())
    r = c.post("/api/generations", json={"template_id": "0123456789abcdef", "brief": "Итоги", "strategies": ["x", "y"]})
    assert r.status_code == 400 and r.json()["detail"] == "Неизвестные варианты: «x», «y» — бывают «structured», «visual», «compact»"


def test_the_goals_brief_has_a_limit(api):
    c, _, _ = api
    r = c.post("/api/goals", json={"brief": "а" * (A._MAX_GOALS_BRIEF + 1), "use_models": False})
    assert r.status_code == 413 and r.json()["detail"].startswith("Текст длиннее 20 000 символов")


# ---------------------------------------------------------------------------------------------- наборы данных в работе


def _deck(store: Store, dids: list[str], title: str = "Итоги продаж") -> str:
    gid, _ = store.new_generation_dir()
    store.write_generation_meta(gid, {"id": gid, "template_id": "0123456789abcdef", "title": title, "status": "done", "dataset_ids": dids})
    return gid


def test_a_dataset_a_deck_uses_is_not_deleted(api):
    c, store, root = api
    did = c.post("/api/datasets", files=[("files", ("Выручка.csv", REVENUE, "text/csv"))]).json()[0]["id"]
    gid = _deck(store, [did])
    r = c.delete(f"/api/datasets/{did}")
    assert r.status_code == 409 and r.json()["detail"] == "Этот файл с данными использует презентация «Итоги продаж» — он остаётся на сервере, пока она есть"
    assert (root / "datasets" / did).is_dir()
    gid2 = _deck(store, [did], "Второй")
    assert "используют 2 презентации" in c.delete(f"/api/datasets/{did}").json()["detail"]
    store.delete_generation(gid)
    store.delete_generation(gid2)
    assert c.delete(f"/api/datasets/{did}").json() == {"deleted": True}


def test_old_datasets_no_deck_uses_go_at_start(api, monkeypatch):
    c, store, root = api
    ids = [c.post("/api/datasets", files=[("files", (f"{n}.csv", REVENUE, "text/csv"))]).json()[0]["id"] for n in ("old", "used", "fresh")]
    old, used, fresh = (root / "datasets" / i for i in ids)
    _deck(store, [ids[1]])
    past = time.time() - (A.dataset_keep_days() + 1) * 86400
    for d in (old, used):
        for p in [*d.iterdir(), d]:
            os.utime(p, (past, past))
    with TestClient(A.app):  # the lifespan
        pass
    assert not old.exists() and used.is_dir() and fresh.is_dir()
