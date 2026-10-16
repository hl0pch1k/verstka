"""Колода из данных через API (описание решения §3, §5, §6): POST /api/generations с `dataset_ids` строит
колоду-историю, брендбук ведёт на брендированную копию шаблона (логотипы — в папке сборки), «Пересобрать слайд так»
(POST …/slides/{n}/rebuild) пересобирает один слайд другим вариантом визуализации, а неподходящий вариант получает
спокойный отказ с причиной.

Без ключей и без модели, шаблон — LibreOffice «Forestbird» (не использовался при разработке), сеть закрыта."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import verstka.api.app as A
from verstka.api.store import Store
from verstka.pipeline.revise import slide_fingerprints

ROOT = Path(__file__).resolve().parents[2]
SALES = ROOT / "examples" / "data-sales-2026"
BRAND = ROOT / "examples" / "brandbook-vk-cloud"
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
def api(tmp_path_factory):
    from verstka.analysis.manifest import analyze_template

    root = tmp_path_factory.mktemp("ws")
    store = Store(root)
    mp = pytest.MonkeyPatch()
    mp.setattr(A, "store", store)
    mp.setattr(A, "models_configured", lambda: False)
    m = analyze_template(UNSEEN, workspace_root=root, use_llm=False, use_vlm=False)
    yield TestClient(A.app), store, root, m.template_id
    mp.undo()


def _upload(c) -> list[str]:
    files = [("files", (name, (SALES / name).read_bytes())) for name in FILES]
    r = c.post("/api/datasets", files=files)
    assert r.status_code == 200, r.text
    return [d["id"] for d in r.json()]


def _generate(c, tid: str, ids: list[str], **kw) -> tuple[str, dict]:
    body = {"template_id": tid, "brief": BRIEF, "slides": 9, "use_models": False, "exports": [], "pictures": False,
            "dataset_ids": ids, **kw}
    r = c.post("/api/generations", json=body)
    assert r.status_code == 200, r.text
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    gid = r.json()["generation_id"]
    return gid, c.get(f"/api/generations/{gid}").json()


@pytest.fixture(scope="module")
def deck(api):
    c, store, root, tid = api
    ids = _upload(c)
    gid, gen = _generate(c, tid, ids, strategies=["structured", "visual"])
    return gid, gen, ids


def _slide_of(outline: dict, file: str) -> int:
    return next(k for k, s in enumerate(outline["slides"], 1) if (s.get("data") or {}).get("file") == file)


def test_datasets_become_a_story_deck(api, deck):
    c, store, root, tid = api
    gid, gen, ids = deck
    assert gen["status"] == "done" and gen["template_id"] == tid
    assert [d["id"] for d in gen["datasets"]] == ids
    assert gen["data_story"]["datasets"] == 7 and gen["data_story"]["planned_by"] == "rules"
    gdir = store.generation_dir(gid)
    saved = json.loads((gdir / "data_story.json").read_text(encoding="utf-8"))
    assert saved["dataset_ids"] == ids and len(saved["plans"]) == 7
    types = {}
    for v in gen["variants"]:
        o = v["outline"]
        assert len(o["slides"]) == 9
        data = [s for s in o["slides"] if s.get("data")]
        assert len(data) == 7 and all(s["data"]["dataset_id"] in ids for s in data)
        for s in data:
            ch = (s["content"].get("chart") or {}).get("type")
            types.setdefault(s["data"]["file"], set()).add(ch)
        # the plan was the data analyst's, not «supplied»; its run manifest says so
        assert v["planner"]["planned_by"] == "rules"
        rm = json.loads((gdir / v["strategy"] / "run_manifest.json").read_text(encoding="utf-8"))
        assert rm["planner"]["data"]["datasets"] == 7
        codes = {i["check_id"] for i in v["audit"]["issues"] if i["severity"] in ("error", "warn")}
        assert not codes & {"headline_figure_not_in_data", "chart_values_mismatch", "chart_no_source", "chart_no_units",
                            "chart_from_untypable", "data_split_inconsistent", "headline_no_conclusion"}, codes
    assert all(len(t) == 1 for t in types.values()), types  # one chart type per dataset in every variant
    events = json.loads((gdir / "agent.json").read_text(encoding="utf-8"))["events"]
    assert any(e["step"] == "data" for e in events)


def test_a_slide_is_rebuilt_with_another_option(api, deck):
    from verstka.audit.ir import build_deck_ir

    c, store, root, tid = api
    gid, gen, ids = deck
    vdir = store.generation_dir(gid) / "structured"
    o = json.loads((vdir / "outline.json").read_text(encoding="utf-8"))
    n = _slide_of(o, "Каналы продаж.json")
    d = o["slides"][n - 1]["data"]
    assert [x["kind"] for x in d["options"]][:2] == ["doughnut", "stacked_column"] and d["chosen"] == 0
    fp0 = slide_fingerprints(vdir / "deck.pptx")
    r = c.post(f"/api/generations/{gid}/structured/slides/{n}/rebuild", json={"option": 1})
    assert r.status_code == 200, r.text
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    res = job.result
    assert res["kind"] == "rebuild" and res["applied"] and res["viz"] == "stacked_column" and res["slides"] == [n]
    assert "Пересобрал слайд" in res["reply"] and res["version"] == 1
    o2 = json.loads((vdir / "outline.json").read_text(encoding="utf-8"))
    s2 = o2["slides"][n - 1]
    assert s2["content"]["chart"]["type"] == "stacked_column" and s2["data"]["chosen"] == 1
    assert s2["headline"] == o["slides"][n - 1]["headline"]
    ir = build_deck_ir(vdir / "deck.pptx")
    assert [e.chart.grouping for e in ir.slides[n - 1].elements if e.chart] == ["stacked"]
    fp1 = slide_fingerprints(vdir / "deck.pptx")
    assert fp1[n - 1] != fp0[n - 1]
    assert [a for k, a in enumerate(fp0) if k != n - 1] == [b for k, b in enumerate(fp1) if k != n - 1]  # the rest stays
    edits = json.loads((vdir / "edits.json").read_text(encoding="utf-8"))
    assert edits[-1]["kind"] == "rebuild" and edits[-1]["slides"] == [n]
    rep = json.loads((vdir / "audit_report.json").read_text(encoding="utf-8"))
    assert not [i for i in rep["issues"] if i["check_id"] in ("chart_values_mismatch", "headline_figure_not_in_data")]
    # the other variant keeps its own choice
    ov = json.loads((store.generation_dir(gid) / "visual" / "outline.json").read_text(encoding="utf-8"))
    assert ov["slides"][_slide_of(ov, "Каналы продаж.json") - 1]["content"]["chart"]["type"] == "doughnut"
    # «верни как было» brings the variant back exactly
    r = c.post(f"/api/generations/{gid}/structured/edits", json={"message": "верни как было"})
    assert _wait(r.json()["job_id"]).status == "done"
    assert slide_fingerprints(vdir / "deck.pptx") == fp0


def test_an_option_the_data_does_not_suit_is_refused_calmly(api, deck):
    c, store, root, tid = api
    gid, gen, ids = deck
    o = json.loads((store.generation_dir(gid) / "structured" / "outline.json").read_text(encoding="utf-8"))
    n = _slide_of(o, "Регионы.xlsx")
    r = c.post(f"/api/generations/{gid}/structured/slides/{n}/rebuild", json={"option": 2})
    assert r.status_code == 422 and "8 долей" in r.json()["detail"]  # the pie: its reason, not a stack trace
    r = c.post(f"/api/generations/{gid}/structured/slides/{n}/rebuild", json={"option": 0})
    assert r.status_code == 422 and "уже показан так" in r.json()["detail"]
    r = c.post(f"/api/generations/{gid}/structured/slides/1/rebuild", json={"option": 1})
    assert r.status_code == 422 and "не из файла" in r.json()["detail"]
    r = c.post(f"/api/generations/{gid}/structured/slides/99/rebuild", json={"option": 1})
    assert r.status_code == 422
    r = c.post(f"/api/generations/{gid}/structured/slides/{n}/rebuild", json={"option": 9})
    assert r.status_code == 422 and "варианта 10 нет" in r.json()["detail"]
    r = c.post(f"/api/generations/{gid}/nope/slides/{n}/rebuild", json={"option": 1})
    assert r.status_code == 404


def test_a_rebuild_into_more_slides_lays_the_variant_out_again(api, deck):
    c, store, root, tid = api
    gid, gen, ids = deck
    vdir = store.generation_dir(gid) / "visual"
    o = json.loads((vdir / "outline.json").read_text(encoding="utf-8"))
    n = _slide_of(o, "Выручка по месяцам.csv")
    table = next(k for k, x in enumerate(o["slides"][n - 1]["data"]["options"]) if x["kind"] == "table")
    r = c.post(f"/api/generations/{gid}/visual/slides/{n}/rebuild", json={"option": table})
    assert r.status_code == 200, r.text
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    o2 = json.loads((vdir / "outline.json").read_text(encoding="utf-8"))
    parts = [s for s in o2["slides"] if (s.get("data") or {}).get("file") == "Выручка по месяцам.csv"]
    assert len(parts) == 3 and [tuple(s["data"]["part"]) for s in parts] == [(1, 3), (2, 3), (3, 3)]
    assert len(o2["slides"]) == len(o["slides"]) + 2 and job.result["slides"] == [n, n + 1, n + 2]
    rep = json.loads((vdir / "audit_report.json").read_text(encoding="utf-8"))
    assert not [i for i in rep["issues"] if i["check_id"] in ("data_split_inconsistent", "chart_values_mismatch")]


def test_a_rebuild_without_its_file_is_refused(api, deck):
    c, store, root, tid = api
    gid, gen, ids = deck
    o = json.loads((store.generation_dir(gid) / "structured" / "outline.json").read_text(encoding="utf-8"))
    n = _slide_of(o, "Клиенты.xlsx")
    did = o["slides"][n - 1]["data"]["dataset_id"]
    saved = store.dataset_dir(did)
    keep = root / "kept-dataset"
    shutil.copytree(saved, keep)
    try:
        assert c.delete(f"/api/datasets/{did}").status_code == 200
        r = c.post(f"/api/generations/{gid}/structured/slides/{n}/rebuild", json={"option": 1})
        assert r.status_code == 409 and "Клиенты.xlsx" in r.json()["detail"]
    finally:
        shutil.copytree(keep, saved, dirs_exist_ok=True)


def _brandbook(c) -> str:
    parts = [("files", (f"Брендбук/logos/{p.name}", p.read_bytes())) for p in sorted((BRAND / "logos").glob("*.png"))]
    parts.append(("files", ("Брендбук/tokens.json", (BRAND / "tokens.json").read_bytes())))
    r = c.post("/api/brandbooks", files=parts, data={"use_models": "false"})
    assert r.status_code == 200, r.text
    job = _wait(r.json()["job_id"])
    assert job.status == "done", job.events[-1]
    return r.json()["brandbook_id"]


def test_a_brandbook_lays_the_deck_out_on_the_branded_copy(api):
    from verstka.brand.apply import branded_info

    c, store, root, tid = api
    bid = _brandbook(c)
    ids = _upload(c)
    gid, gen = _generate(c, tid, ids, strategies=["structured"], brandbook_id=bid)
    info = branded_info(gen["template_id"], root)
    assert gen["template_id"] != tid and info is not None and info["base_template_id"] == tid
    assert gen["base_template_id"] == tid and gen["brandbook"]["id"] == bid
    v = gen["variants"][0]
    assert len(v["outline"]["slides"]) == 9
    rm = json.loads((store.generation_dir(gid) / "structured" / "run_manifest.json").read_text(encoding="utf-8"))
    assert rm["template"]["id"] == gen["template_id"]
    # the logos were copied into the build's folder: a brandbook deleted later takes nothing away from it
    copied = sorted(p.name for p in (store.generation_dir(gid) / "brand").rglob("*.png"))
    assert copied and set(copied) <= {p.name for p in (BRAND / "logos").glob("*.png")}
    # «Собрать ещё раз» on the branded copy brands the base template again (the same cached copy), never the copy
    gid2, gen2 = _generate(c, gen["template_id"], ids, strategies=["structured"], brandbook_id=bid)
    assert gen2["template_id"] == gen["template_id"]


def test_the_logos_are_copied_before_the_brandbook_can_go(api, tmp_path):
    c, store, root, tid = api
    bid = _brandbook(c)
    data = A._generation_data(A.GenerateRequest(template_id=tid, brief="x", brandbook_id=bid))
    gdir = tmp_path / "gen"
    gdir.mkdir()
    copy = A._brand_files(data, gdir)
    assert c.delete(f"/api/brandbooks/{bid}").status_code == 200
    assert not (root / "brandbooks" / bid).exists()
    logos = [l.file for l in data.brand.logos]
    assert logos and all((copy / f).is_file() for f in logos)
    from verstka.brand.apply import branded_info, branded_template

    copy_id = branded_template(tid, data.brand, "brand", workspace_root=root, brand_dir=copy, render=False)
    assert (branded_info(copy_id, root) or {}).get("base_template_id") == tid
