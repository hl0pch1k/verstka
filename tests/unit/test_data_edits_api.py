"""Правки колоды из данных (ревью Task 10): смена вида слайда данных словами в чате идёт через «Пересобрать слайд так»,
а редизайн и «Исправить слайд» с моделью не падают на графике с пропусками (NPS) и сохраняют `OutlineSlide.data`,
диаграмму из файла и источник. Модель — заглушка дизайнера, сеть закрыта."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import DeckOutline

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
UNSEEN = ROOT / "tests" / "fixtures" / "data_story" / "lo_forestbird.pptx"
BRIEF = ("Итоги продаж VK Cloud за 9 месяцев 2026 года для правления. Покажи рост выручки, сравни регионы, что даёт "
         "выручку и где узкие места. Данные — в приложенных файлах.")
FILES = ["Итоги квартала.txt", "Выручка по месяцам.csv", "Регионы.xlsx", "Каналы продаж.json",
         "Время ответа поддержки.csv", "NPS по кварталам.csv", "Клиенты.xlsx"]

pytestmark = pytest.mark.skipif(shutil.which("soffice") is None and not Path("/Applications/LibreOffice.app").exists(),
                                reason="LibreOffice is not installed")


def _wait(jid: str, timeout: float = 240) -> A.Job:
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = A.runner.get(jid)
        if job is not None and job.events and job.events[-1].get("status") in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(jid)


@pytest.fixture(scope="module")
def deck(tmp_path_factory):
    from verstka.analysis.manifest import analyze_template

    root = tmp_path_factory.mktemp("ws")
    store = Store(root)
    mp = pytest.MonkeyPatch()
    mp.setattr(A, "store", store)
    mp.setattr(A, "models_configured", lambda: False)
    m = analyze_template(UNSEEN, workspace_root=root, use_llm=False, use_vlm=False)
    c = TestClient(A.app)
    r = c.post("/api/datasets", files=[("files", (n, (SALES / n).read_bytes())) for n in FILES])
    ids = [d["id"] for d in r.json()]
    r = c.post("/api/generations", json={"template_id": m.template_id, "brief": BRIEF, "slides": 9, "use_models": False, "exports": [],
                                         "pictures": False, "dataset_ids": ids, "strategies": ["compact"]})
    assert _wait(r.json()["job_id"]).status == "done"
    yield c, store, r.json()["generation_id"], mp
    mp.undo()


def _outline(store, gid) -> DeckOutline:
    return DeckOutline.model_validate_json((store.generation_dir(gid) / "compact" / "outline.json").read_text(encoding="utf-8"))


def _slide_of(o: DeckOutline, file: str) -> int:
    return next(k for k, s in enumerate(o.slides, 1) if s.data is not None and s.data.file == file)


def test_a_chat_form_change_of_a_data_slide_is_a_rebuild(deck):
    c, store, gid, _ = deck
    o = _outline(store, gid)
    n = _slide_of(o, "NPS по кварталам.csv")
    r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": f"на слайде {n} покажи таблицей"})
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    assert job.result["changed"] and job.result["kind"] == "rebuild" and job.result["viz"] == "table", job.result
    s = _outline(store, gid).slides[n - 1]
    assert s.content.table is not None and s.data is not None and s.data.options[s.data.chosen].kind == "table"
    assert s.data.prepared is not None and s.data.prepared.rows and s.footnote.startswith("Источник:")
    rep = json.loads((store.generation_dir(gid) / "compact" / "audit_report.json").read_text(encoding="utf-8"))
    assert not [i for i in rep["issues"] if i["check_id"] in ("chart_values_mismatch", "figure_not_in_brief")]
    # a form the data has no option for: a calm refusal, no redesign of the figures
    r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": f"на слайде {n} покажи круговой диаграммой"})
    job = _wait(r.json()["job_id"])
    assert job.status == "done" and not job.result["changed"] and "Пересобрать слайд так" in job.result["reply"]
    # back as it was
    r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": "верни как было"})
    assert _wait(r.json()["job_id"]).status == "done"
    assert _outline(store, gid).slides[n - 1].content.chart is not None


@pytest.fixture
def designer(deck, monkeypatch):
    """The model path with a stub designer: it answers a slide without `data`, its chart turned into a list and a new
    headline — what a real designer's answer looks like to the data layer."""
    from verstka.planning import agent as AG
    from verstka.providers.mock import MockProvider
    from verstka.providers.registry import ProviderRegistry
    from verstka.skills_registry.registry import SkillsRegistry

    c, store, gid, _ = deck
    reg = ProviderRegistry(roles={"llm": MockProvider({"*": {}}), "vlm": MockProvider({"*": {}})})
    monkeypatch.setattr(A, "models_configured", lambda: True)
    monkeypatch.setattr(A, "providers", lambda: reg)
    monkeypatch.setattr(A, "skills", lambda: SkillsRegistry.load())
    store.merge_generation_meta(gid, {"use_models": True})
    asked: dict = {}

    def model_design(self, unit, pos, units, ctx, deadline, issues="", previous=""):
        o = _outline(store, gid)
        old = o.slides[pos - 1]
        new = old.model_copy(deep=True, update={"data": None, "headline": asked.get("headline", "NPS вырос до 52"), "kind": PatternKind.bullets})
        new.content.chart = None
        new.content.bullets = ["Пропуски — разрывы линии"]
        return AG._Design(unit=unit, slide=new, by="model")

    monkeypatch.setattr(AG._Agent, "model_design", model_design)
    yield asked
    store.merge_generation_meta(gid, {"use_models": False})


def test_a_redesign_of_a_slide_with_gaps_keeps_its_data(deck, designer):
    c, store, gid, _ = deck
    o = _outline(store, gid)
    n = _slide_of(o, "NPS по кварталам.csv")
    old = o.slides[n - 1]
    assert None in old.content.chart.series[0].values  # the gaps the compile path used to choke on
    r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": f"на слайде {n} сделай заголовок короче"})
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    assert job.result["changed"], job.result
    s = _outline(store, gid).slides[n - 1]
    assert s.headline == "NPS вырос до 52"  # the designer's words, their number a data fact
    assert s.data is not None and s.data.dataset_id == old.data.dataset_id
    assert s.content.chart is not None and s.content.chart.series[0].values == old.content.chart.series[0].values
    assert s.footnote == old.footnote and s.kind == old.kind
    rep = json.loads((store.generation_dir(gid) / "compact" / "audit_report.json").read_text(encoding="utf-8"))
    assert not [i for i in rep["issues"] if i["check_id"] in ("chart_values_mismatch", "headline_figure_not_in_data", "figure_not_in_brief")]
    r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": "верни как было"})
    assert _wait(r.json()["job_id"]).status == "done"


def test_a_redesign_never_brings_a_number_the_data_does_not_have(deck, designer):
    c, store, gid, _ = deck
    designer["headline"] = "NPS вырос до 57"
    o = _outline(store, gid)
    n = _slide_of(o, "NPS по кварталам.csv")
    r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": f"на слайде {n} перепиши заголовок"})
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    assert _outline(store, gid).slides[n - 1].headline == o.slides[n - 1].headline  # 57 is no fact: the old one stays
    if job.result.get("changed"):
        r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": "верни как было"})
        assert _wait(r.json()["job_id"]).status == "done"


def test_fix_slide_with_the_model_on_a_gap_chart(deck, designer):
    c, store, gid, _ = deck
    o = _outline(store, gid)
    n = _slide_of(o, "NPS по кварталам.csv")
    r = c.post(f"/api/generations/{gid}/compact/slides/{n}/fix", json={"wishes": "сделай заголовок короче"})
    assert r.status_code == 200, r.text
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    assert "validation" not in json.dumps(job.result, ensure_ascii=False).lower()
    s = _outline(store, gid).slides[n - 1]
    assert s.data is not None and s.content.chart is not None and None in s.content.chart.series[0].values
    assert job.result["applied"] and job.result["how"] == "model", job.result
    assert s.headline == "NPS вырос до 52"
    r = c.post(f"/api/generations/{gid}/compact/edits", json={"message": "верни как было"})
    assert _wait(r.json()["job_id"]).status == "done"
