"""API документов и базы знаний: POST /api/documents (DOCX/PDF → текст Markdown для поля), /api/datasets с документом
(таблицы с цифрами → карточки данных), /api/knowledge (база: документы, архив, ссылки, поиск, удаление), сборка с
`knowledge_id`, «Почему так» с источниками. Без модели, сеть закрыта."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(A, "store", store)
    for var in ("VERSTKA_MAX_DOC_MB", "VERSTKA_MAX_KB_UPLOAD_MB", "VERSTKA_MAX_DATA_MB"):
        monkeypatch.delenv(var, raising=False)
    return TestClient(A.app), store


@pytest.mark.parametrize("name", ["report.docx", "report.pdf"])
def test_a_document_becomes_the_text_of_the_field_and_its_figure_tables_become_data(api, name):
    c, _ = api
    r = c.post("/api/documents", files={"file": (name, (FIX / name).read_bytes())})
    assert r.status_code == 200, r.text
    d = r.json()
    # a report of its own text: it goes into the field whole, its tables inline (the deck lays the whole report out)
    assert d["title"] == "Итоги третьего квартала 2026" and d["tables"] == 2 and d["data_tables"] == 0 and d["tables_in_text"] == 2
    assert d["markdown"].startswith("# Итоги третьего квартала 2026") and "| Q3 2026 | 412 | 1 240 |" in d["markdown"]
    # the same file sent as data: its table of figures is a data file of the second stage
    r = c.post("/api/datasets", files=[("files", (name, (FIX / name).read_bytes()))])
    assert r.status_code == 200, r.text
    cards = r.json()
    assert len(cards) == 1 and cards[0]["file"] == name
    assert cards[0]["rows"] == 3


def test_a_document_that_is_mostly_its_table_gives_a_brief_and_data(api):
    import sys

    sys.path.insert(0, str(FIX))
    from make_docs import docx_bytes, p, table

    body = [p("Продажи по месяцам", "1"), p("Выручка по месяцам, млн ₽:"),
            table([["Месяц", "Выручка"], ["Январь", "10"], ["Февраль", "12"], ["Март", "15"], ["Апрель", "14"]])]
    c, _ = api
    d = c.post("/api/documents", files={"file": ("продажи.docx", docx_bytes(body))}).json()
    assert d["data_first"] and d["data_tables"] == 1 and "| Январь |" not in d["markdown"] and d["markdown"].startswith("# Продажи по месяцам")


def test_a_document_without_figures_or_text_is_refused_in_words(api):
    c, _ = api
    md = "# Заметка\n\nТолько текст, без таблиц.\n".encode()
    r = c.post("/api/datasets", files=[("files", ("note.docx", _docx_from_md()))])
    assert r.status_code == 400 and "нет таблиц с цифрами" in r.json()["detail"]
    r = c.post("/api/documents", files={"file": ("photo.png", b"\x89PNG")})
    assert r.status_code == 400 and "не подойдёт" in r.json()["detail"]
    r = c.post("/api/documents", files={"file": ("x.pdf", b"%PDF-1.4 broken")})
    assert r.status_code == 400
    assert md  # (the markdown text is fine for the field: it never goes through this route)


def _docx_from_md() -> bytes:
    import sys

    sys.path.insert(0, str(FIX))
    from make_docs import docx_bytes, p

    return docx_bytes([p("Заметка", "1"), p("Только текст, без таблиц.")])


def test_a_knowledge_base_takes_documents_an_archive_and_answers_a_search(api):
    c, store = api
    kb = c.post("/api/knowledge", json={"name": "Квартал"}).json()
    kid = kb["id"]
    assert kb["name"] == "Квартал" and kb["docs"] == []
    files = [("files", (f.name, f.read_bytes())) for f in sorted((FIX / "kb").iterdir()) if f.suffix in (".docx", ".pdf")]
    r = c.post(f"/api/knowledge/{kid}/documents", files=files)
    assert r.status_code == 200, r.text
    assert len(r.json()["added"]) == 2 and r.json()["skipped"] == []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("docs/clients.md", (FIX / "kb" / "clients.md").read_bytes())
        z.writestr("docs/team.txt", (FIX / "kb" / "team.txt").read_bytes())
    r = c.post(f"/api/knowledge/{kid}/documents", files=[("files", ("база.zip", buf.getvalue()))])
    base = r.json()["base"]
    assert len(base["docs"]) == 4 and base["fragments"] >= 12
    hits = c.get(f"/api/knowledge/{kid}/search", params={"q": "индекс NPS"}).json()["hits"]
    assert hits[0]["title"] == "Клиенты и отзывы" and hits[0]["label"].startswith("«Клиенты и отзывы», раздел «Удовлетворённость»")
    doc = base["docs"][0]
    got = c.get(f"/api/knowledge/{kid}/documents/{doc['id']}").json()
    assert got["markdown"].startswith("# ")
    assert c.delete(f"/api/knowledge/{kid}/documents/{doc['id']}").json()["base"]["docs"].__len__() == 3
    assert c.delete(f"/api/knowledge/{kid}/documents/nope").status_code == 404
    assert any(b["id"] == kid for b in c.get("/api/knowledge").json())
    one = c.post(f"/api/knowledge/{kid}/documents", files=[("files", ("scan.png", b"\x89PNG"))])
    assert one.status_code == 400 and "формат не читаю" in one.json()["detail"]
    assert c.delete(f"/api/knowledge/{kid}").json() == {"deleted": True}
    assert c.get(f"/api/knowledge/{kid}").status_code == 404


def test_a_link_to_the_server_own_network_is_refused(api):
    c, _ = api
    kid = c.post("/api/knowledge", json={}).json()["id"]
    r = c.post(f"/api/knowledge/{kid}/links", json={"url": "http://127.0.0.1:8000/api/health"})
    assert r.status_code == 400 and ("внутренней" in r.json()["detail"] or "порты" in r.json()["detail"])
    r = c.post(f"/api/knowledge/{kid}/links", json={"url": "file:///etc/passwd"})
    assert r.status_code == 400


def test_a_generation_names_its_knowledge_base_and_a_gone_base_is_said(api):
    c, _ = api
    r = c.post("/api/generations", json={"template_id": "nope", "brief": "Итоги квартала", "knowledge_id": "20260101-000000-abcdef"})
    assert r.status_code == 404  # the template first: no such template
    assert "knowledge_id" in A.GenerateRequest.model_fields
    req = A.GenerateRequest(template_id="t", brief="x", knowledge_id="k1")
    assert A._request_options(req)["knowledge_id"] == "k1"


def test_upload_size_gate_knows_the_new_routes():
    assert A._upload_cap("/api/documents") is not None
    assert A._upload_cap("/api/knowledge/20261017-120000-abc123/documents") is not None
    assert A._upload_cap("/api/knowledge/../documents") is None
