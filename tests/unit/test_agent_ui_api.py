"""Agent v2 in the API: the agent's progress events become job events (live timeline), agent.json keeps them for the
result, variant payloads expose the agent's log, critic notes and the per-slide rationale/alternatives, the chat
helper answers «почему слайд N такой» from the rationale — and runs made before Agent v2 still render. No models."""

import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from verstka.api.agent_view import job_progress, normalize_alternatives, normalize_event, read_agent_events, slide_design, write_agent_file
from verstka.api.jobs import Job

TID = "t0agentui000001"


def _slide(sid, kind, headline, **extra):
    return {"id": sid, "kind": kind, "headline": headline, "content": {}, **extra}


def _outline(strategy, slides, agent_log=None):
    o = {"title": "Больше прибыли с каждой чашки", "strategy": strategy, "slides": slides, "planned_by": "model"}
    if agent_log is not None:
        o["agent_log"] = agent_log
    return o


def _plan(strategy, outline):
    return {"strategy": strategy, "template_id": TID, "slides": [{"outline_id": s["id"], "mode": "synth", "composition": "grid", "score": 0.7} for s in outline["slides"]]}


STRUCTURED = _outline("structured", [
    _slide("s1", "title", "Больше прибыли с каждой чашки", spec_ref=1),
    _slide("s2", "chart", "Аренда и зарплаты — две трети расходов", spec_ref=3, rationale="Доли расходов складываются в целое, поэтому круговая диаграмма",
           takeaway="Главные статьи — аренда и зарплаты", alternatives=[{"kind": "table", "change": "те же расходы таблицей: статья, сумма, доля"}, {"kind": "cards", "change": "карточки по статьям"}],
           content={"chart": {"type": "pie", "categories": ["Аренда", "Зарплаты"], "series": [{"name": "Расходы", "values": [120000, 180000]}]}}),
], agent_log=["Аналитик: нашёл 2 слайда, 1 ряд данных, 1 заказанную диаграмму", "Критик: 1 замечание — слайд 2", "Правка: слайд 2 переделан"])
VISUAL = _outline("visual", [
    _slide("v1", "title", "Больше прибыли с каждой чашки", spec_ref=1),
    _slide("v2", "table", "Аренда и зарплаты — две трети расходов", spec_ref=3, rationale="Таблица показывает и суммы, и доли"),
], agent_log=["Аналитик: нашёл 2 слайда"])


def _agent(step, message, slide=None, variant=None):
    return {"type": "agent", "step": step, "message": message, "slide": slide, "variant": variant}


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


def _write_variant(gdir: Path, strategy: str, outline: dict) -> None:
    vdir = gdir / strategy
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "deck.pptx").write_bytes(b"PK")
    (vdir / "outline.json").write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
    (vdir / "layout_plan.json").write_text(json.dumps(_plan(strategy, outline)), encoding="utf-8")


def _fake_generate(outlines: dict):
    """generate_variants as the Agent v2 pipeline calls back: plain messages, agent events (as the first argument and
    as `event=`), then the variant folders."""

    def fake(template, *, brief=None, outline=None, strategies=None, out_dir=None, progress=None, **kw):
        from verstka.schemas.outline import DeckOutline

        progress("analyze: loaded cached manifest", 0.1)
        progress(_agent("analyst", "Нашёл 2 слайда, 1 ряд данных, 1 заказанную диаграмму"), 0.2)
        progress(_agent("designer", "Слайд 2 — круговая диаграмма расходов, 2 категории", slide=2))
        progress("", None, event=_agent("critic", "Слайд 2: подпись длиннее 12 слов", slide=2, variant="structured"))
        progress(_agent("revise", "Слайд 2 переделан", slide=2, variant="structured"), 0.5)
        progress(_agent("critic", "Замечаний нет", variant="visual"))
        progress({"type": "agent", "step": "", "message": "без шага"})  # not an event of the contract: dropped
        variants = []
        for name in strategies:
            _write_variant(Path(out_dir), name, outlines[name])
            progress(f"{name}: done in 1.0s", 0.9)
            o = DeckOutline.model_validate(outlines[name])
            variants.append(SimpleNamespace(strategy=name, outline=o, audit=None, seconds=1.0, warnings=[], planner={"planned_by": "model", "model": None}))
        return SimpleNamespace(variants=variants, seconds=2.0)

    return fake


def _wait(c, job_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise TimeoutError(job_id)


def test_agent_events_reach_the_job_and_the_generation(api, monkeypatch):
    c, mod = api
    import verstka.pipeline.generate as gen

    monkeypatch.setattr(gen, "generate_variants", _fake_generate({"structured": STRUCTURED, "visual": VISUAL}))
    r = c.post("/api/generations", json={"template_id": TID, "brief": "Слайд 1. Титул\nСлайд 3. Расходы", "strategies": ["structured", "visual"], "use_models": False, "exports": []})
    assert r.status_code == 200, r.text
    job = _wait(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    # the polled job record carries the agent's timeline in order, with step / slide / variant
    steps = [(e["step"], e["slide"], e["variant"]) for e in job["agent"]]
    assert steps == [("analyst", None, None), ("designer", 2, None), ("critic", 2, "structured"), ("revise", 2, "structured"), ("critic", None, "visual")]
    assert job["agent"][1]["message"] == "Слайд 2 — круговая диаграмма расходов, 2 категории"
    assert all(e["type"] == "agent" and isinstance(e["seq"], int) for e in job["agent"])

    gid = r.json()["generation_id"]
    g = c.get(f"/api/generations/{gid}").json()
    v = {x["strategy"]: x for x in g["variants"]}
    s = v["structured"]
    # the log of the outline, the structured timeline of agent.json (shared steps + its own), the critic's notes
    assert s["agent"]["log"][0].startswith("Аналитик")
    assert [e["step"] for e in s["agent"]["events"]] == ["analyst", "designer", "critic", "revise"]
    assert [e["message"] for e in s["agent"]["critic"]] == ["Слайд 2: подпись длиннее 12 слов", "Слайд 2 переделан"]
    assert [e["variant"] for e in v["visual"]["agent"]["events"]] == [None, None, "visual"]
    # per slide: rationale, takeaway, alternatives in words, and «used in» the other variant
    d2 = s["design"][1]
    assert d2["rationale"].startswith("Доли расходов") and d2["takeaway"] == "Главные статьи — аренда и зарплаты" and d2["spec_ref"] == 3
    assert d2["alternatives"][0] == {"kind": "table", "label": "таблица", "text": "те же расходы таблицей: статья, сумма, доля", "used_in": ["visual"]}
    assert d2["alternatives"][1] == {"kind": "cards", "label": "карточки", "text": "карточки по статьям", "used_in": []}
    assert s["outline"]["slides"][1]["content"]["chart"]["type"] == "pie"
    assert s["design"][0]["rationale"] is None and s["design"][0]["alternatives"] == []

    # the chat helper: «почему слайд 2 такой» about the variant on screen, from the designer's reason
    r = c.post("/api/chat", json={"session_id": "a1", "message": "почему слайд 2 такой?", "template_id": TID, "generation_id": gid, "strategy": "structured"}).json()
    assert r["intent"] == "explain_slide" and {"type": "open_tab", "tab": "why", "slide": 2} in r["actions"]
    assert "Почему так: Доли расходов складываются в целое" in r["reply"] and "таблица — те же расходы таблицей" in r["reply"]
    assert "Критик: подпись длиннее 12 слов. Правка: слайд 2 переделан." in r["reply"] and "Вёрстка: по дизайн-системе шаблона" in r["reply"]
    r = c.post("/api/chat", json={"session_id": "a1", "message": "почему слайд 2 такой?", "strategy": "visual"}).json()
    assert "Таблица показывает и суммы, и доли" in r["reply"] and "«Визуальный»" in r["reply"]
    # «как работал агент» → the timeline by steps and the panel
    r = c.post("/api/chat", json={"session_id": "a1", "message": "Как работал агент?", "strategy": "structured"}).json()
    assert r["intent"] == "agent" and {"type": "open_tab", "tab": "agent"} in r["actions"]
    assert "• Аналитик: нашёл 2 слайда" in r["reply"] and "• Критик: слайд 2: подпись длиннее 12 слов." in r["reply"] and "• Правка: слайд 2 переделан." in r["reply"]
    assert "• Дизайнер: продумал форму 1 слайда, например: слайд 2: круговая диаграмма расходов, 2 категории." in r["reply"]
    # the explain endpoint says the same
    ex = c.get(f"/api/generations/{gid}/structured/explain/2").json()
    assert "Почему так:" in ex["text"]


def test_old_runs_without_agent_data_still_render(api):
    c, mod = api
    gid, gdir = mod.store.new_generation_dir()
    old = {"title": "Старый запуск", "strategy": "structured", "slides": [{"id": "a", "kind": "bullets", "headline": "Тезисы", "content": {"bullets": ["раз", "два"]}}]}
    _write_variant(gdir, "structured", old)
    mod.store.write_generation_meta(gid, {"id": gid, "template_id": TID, "strategies": ["structured"], "status": "done"})
    g = c.get(f"/api/generations/{gid}").json()
    v = g["variants"][0]
    assert v["agent"] == {"log": [], "events": [], "critic": []}
    assert v["design"] == [{"index": 1, "kind": "bullets", "rationale": None, "alternatives": [], "takeaway": None, "footnote": None, "spec_ref": None}]
    r = c.post("/api/chat", json={"session_id": "o1", "message": "почему слайд 1 такой", "template_id": TID, "generation_id": gid}).json()
    assert r["reply"].startswith("Слайд 1 — список: «Тезисы».") and "Почему так" not in r["reply"]
    r = c.post("/api/chat", json={"session_id": "o1", "message": "что делал агент"}).json()
    assert r["intent"] == "agent" and "журнал агента не записан" in r["reply"]
    # a broken agent.json is ignored
    (gdir / "agent.json").write_text("{not json", encoding="utf-8")
    assert c.get(f"/api/generations/{gid}").json()["variants"][0]["agent"]["events"] == []


def test_job_replays_the_whole_agent_timeline_to_a_late_subscriber():
    job = Job(id="j1", kind="generate", status="running")
    cb = job_progress(job)
    cb(_agent("analyst", "Нашёл 10 слайдов"), 0.1)
    for i in range(80):
        cb(f"visual: rendered slide {i % 10 + 1}/10", 0.5)
    cb(_agent("critic", "2 замечания", variant="visual"))
    q = job.subscribe()
    replay = [q.get_nowait() for _ in range(q.qsize())]
    agent = [e for e in replay if e.get("type") == "agent"]
    assert [e["message"] for e in agent] == ["Нашёл 10 слайдов", "2 замечания"]  # the first one is older than the last 50
    assert len(replay) == 51 and [e["seq"] for e in replay] == sorted(e["seq"] for e in replay)
    assert job.progress == 0.5 and job.message == "2 замечания"  # an event without a share keeps the progress
    assert [e["step"] for e in job.to_dict()["agent"]] == ["analyst", "critic"]
    assert "agent" not in Job(id="j2", kind="analyze").to_dict()


def test_event_normalisation_and_agent_file(tmp_path):
    assert normalize_event({"type": "agent", "step": "Designer", "message": "  Слайд 3 —\n круговая  ", "slide": "3", "variant": ""}) == {
        "type": "agent", "step": "designer", "message": "Слайд 3 — круговая", "slide": 3, "variant": None}
    assert normalize_event({"type": "log", "message": "x", "step": "analyst"}) is None
    assert normalize_event({"type": "agent", "step": "critic", "message": " "}) is None
    assert normalize_event("analyze: done") is None
    events = [{"type": "agent", "step": "analyst", "message": "Нашёл", "slide": None, "variant": None, "t": 1.5, "seq": 3}, {"message": "plain"}]
    assert write_agent_file(tmp_path, events) == tmp_path / "agent.json"
    assert read_agent_events(tmp_path) == [{"step": "analyst", "message": "Нашёл", "slide": None, "variant": None, "t": 1.5}]
    assert write_agent_file(tmp_path / "none", [{"message": "plain"}]) is None
    assert normalize_alternatives([{"form": "line", "note": "динамика по месяцам"}, 5, {}, "карточки"]) == [
        {"kind": "line", "label": "линейный график", "text": "динамика по месяцам"}, {"kind": None, "label": None, "text": "карточки"}]
    assert slide_design(None) == [] and slide_design({"slides": ["bad"]}) == []
