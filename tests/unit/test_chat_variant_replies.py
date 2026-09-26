"""The helper's answers to «план», «качество» and «файлы» speak about the variant on screen (like the drawer tab they
open beside the chat), in the interface's words: «PowerPoint», not «PPTX». No models."""

import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

TID = "t0chatreply0001"


def _outline(strategy: str) -> dict:
    return {
        "title": "Больше прибыли с каждой чашки",
        "strategy": strategy,
        "planned_by": "model",
        "slides": [
            {"id": "s1", "kind": "title", "headline": "Больше прибыли с каждой чашки", "content": {}},
            {"id": "s2", "kind": "table", "headline": "Аренда и зарплаты — две трети расходов", "content": {}},
        ],
    }


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("VERSTKA_WORKSPACE", str(tmp_path / "ws"))
    import verstka.api.app as mod

    importlib.reload(mod)
    manifest = SimpleNamespace(template_id=TID, source_file="Шаблон.pptx", patterns=[])
    monkeypatch.setattr(mod.store, "manifest", lambda tid: manifest if tid == TID else None)
    monkeypatch.setattr(mod.store, "workspace", lambda tid: SimpleNamespace(source=tmp_path / "t.pptx"))
    monkeypatch.setattr(mod, "models_configured", lambda: False)
    return TestClient(mod.app), mod


def _fake_generate(template, *, brief=None, outline=None, strategies=None, out_dir=None, progress=None, **kw):
    from verstka.schemas.outline import DeckOutline

    variants = []
    for name in strategies:
        o = _outline(name)
        vdir = Path(out_dir) / name
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "deck.pptx").write_bytes(b"PK")
        if name == "visual":
            (vdir / "deck.pdf").write_bytes(b"%PDF")
        (vdir / "outline.json").write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
        plan = {"strategy": name, "template_id": TID, "slides": [{"outline_id": s["id"], "mode": "synth", "composition": "grid", "score": 0.7} for s in o["slides"]]}
        (vdir / "layout_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        progress(f"{name}: done in 1.0s", 0.9)
        variants.append(SimpleNamespace(strategy=name, outline=DeckOutline.model_validate(o), audit=None, seconds=1.0, warnings=[], planner={"planned_by": "model", "model": None}))
    return SimpleNamespace(variants=variants, seconds=2.0)


def _wait(c, job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise TimeoutError(job_id)


def test_chat_plan_quality_and_files_answer_for_the_variant_on_screen(api, monkeypatch):
    c, mod = api
    import verstka.pipeline.generate as gen

    monkeypatch.setattr(gen, "generate_variants", _fake_generate)
    r = c.post("/api/generations", json={"template_id": TID, "brief": "Слайд 1. Титул\nСлайд 2. Расходы", "strategies": ["structured", "visual"], "use_models": False, "exports": []})
    assert r.status_code == 200, r.text
    assert _wait(c, r.json()["job_id"])["status"] == "done"
    gid = r.json()["generation_id"]

    # the plan: one variant, not every variant joined into one bubble
    r = c.post("/api/chat", json={"session_id": "p1", "message": "покажи план", "template_id": TID, "generation_id": gid, "strategy": "visual"}).json()
    assert r["intent"] == "plan" and {"type": "open_tab", "tab": "plan"} in r["actions"]
    assert r["reply"].startswith("Вариант «Визуальный»: 2 слайда") and "Структурный" not in r["reply"]

    # the quality check: the variant on screen only (this one was never checked)
    r = c.post("/api/chat", json={"session_id": "p1", "message": "покажи аудит", "strategy": "structured"}).json()
    assert r["intent"] == "audit" and {"type": "open_tab", "tab": "audit"} in r["actions"]
    assert r["reply"] == "Вариант «Структурный». Проверка качества для него не запускалась."

    # the files: Russian names, the variant on screen, one line
    r = c.post("/api/chat", json={"session_id": "p1", "message": "скачать pdf", "strategy": "visual"}).json()
    assert r["intent"] == "export" and {"type": "open_tab", "tab": "export"} in r["actions"]
    assert r["reply"] == "Вариант «Визуальный»: PowerPoint и PDF — открыл «Файлы»."
    assert "PPTX" not in r["reply"] and "HTML" not in r["reply"]
    r = c.post("/api/chat", json={"session_id": "p1", "message": "скачать pdf", "strategy": "structured"}).json()
    assert r["reply"] == "Вариант «Структурный»: PowerPoint — открыл «Файлы»."
