"""The API after the swarm review of 2026-10-05 (backend): «Исправить всё» is a version «верни как было» undoes, jobs on
two variants never overwrite each other's scores, a zip bomb is refused before anything reads it, an upload named
«..» is an ordinary upload, an empty list of variants builds all three."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from test_api import _wait, client  # noqa: F401  (shared fixture)

TPL = Path(__file__).resolve().parents[1] / "fixtures" / "tpl_audit" / "templates" / "lo_focus.pptx"
BRIEF = """Слайд 1. Кофейня «Точка»

План роста на год

Слайд 2. Выручка

Выручка выросла на 12% и достигла 4,8 млн ₽. Средний чек — 320 рублей. Гостей в день — 410.

Слайд 3. Спасибо!
"""


def _template(c) -> str:
    with open(TPL, "rb") as f:
        r = c.post("/api/templates", files={"file": ("lo_focus.pptx", f, "application/octet-stream")}, data={"use_models": "false"})
    return _wait(c, r.json()["job_id"])["result"]["template_id"]


def test_fix_all_is_a_version_that_can_be_undone(client):  # noqa: F811
    c, mod = client
    tid = _template(c)
    r = c.post("/api/generations", json={"template_id": tid, "brief": BRIEF, "strategies": ["structured"], "use_models": False, "autofix": False, "exports": []})
    gid = r.json()["generation_id"]
    assert _wait(c, r.json()["job_id"], timeout=240)["status"] == "done"
    vdir = mod.store.generation_dir(gid) / "structured"
    before = json.loads((vdir / "audit_report.json").read_text(encoding="utf-8"))
    job = _wait(c, c.post(f"/api/generations/{gid}/structured/fixes", json={"all_deterministic": True}).json()["job_id"], timeout=240)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["version"] == 1 and (vdir / "versions" / "v1" / "deck.pptx").exists()
    edits = json.loads((vdir / "edits.json").read_text(encoding="utf-8"))
    assert edits[-1]["kind"] == "fix_all" and edits[-1]["version"] == 1
    rm = json.loads((vdir / "run_manifest.json").read_text(encoding="utf-8"))
    after = json.loads((vdir / "audit_report.json").read_text(encoding="utf-8"))
    assert rm["audit"]["score"] == after["summary"]["score"]
    # «верни как было» brings the deck before the fixes back
    job = _wait(c, c.post(f"/api/generations/{gid}/structured/edits", json={"message": "верни как было"}).json()["job_id"])
    assert job["status"] == "done" and job["result"]["changed"], job
    assert json.loads((vdir / "audit_report.json").read_text(encoding="utf-8"))["summary"]["score"] == before["summary"]["score"]


def test_a_variants_score_is_merged_under_the_lock(client):  # noqa: F811
    c, mod = client
    gid, _ = mod.store.new_generation_dir()
    mod.store.write_generation_meta(gid, {"id": gid, "summary": {"structured": {"score": 62}, "visual": {"score": 62}}})
    stale = mod.store.read_generation_meta(gid)  # what a job read at its start
    mod.store.merge_variant_summary(gid, "visual", {"score": 80})
    mod.store.merge_variant_summary(gid, "structured", {"score": 87})
    assert mod.store.read_generation_meta(gid)["summary"] == {"structured": {"score": 87}, "visual": {"score": 80}}
    assert stale["summary"]["visual"]["score"] == 62


def _bomb(tmp: Path) -> Path:
    path = tmp / "bomb.pptx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ppt/presentation.xml", "<p/>")
        z.writestr("ppt/media/zero.bin", b"\0" * (64 << 20))  # 64 MB of zeros in a few KB
    return path


def test_a_zip_bomb_is_refused_by_its_sizes(tmp_path, monkeypatch):
    from verstka.ingest import convert as C

    monkeypatch.setattr(C, "MAX_MEMBER", 32 << 20)
    p = _bomb(tmp_path)
    assert C.sniff(p) == "bomb"
    with pytest.raises(C.ConvertError, match="распаковывается"):
        C.check_upload(p)
    assert C.sniff(TPL) == "pptx"


def test_an_upload_named_dots_is_an_ordinary_upload(client):  # noqa: F811
    c, mod = client
    for name in ("..", ".", "...pptx"):
        p = mod.store.upload_path(name)
        assert p.name not in ("..", ".") and p.parent.parent == mod.store.uploads


def test_an_empty_list_of_variants_builds_all_three(client, monkeypatch):  # noqa: F811
    c, mod = client
    tid = _template(c)
    seen = {}

    def fake_submit(kind, fn):
        seen["kind"] = kind
        return mod.Job(id="j0", kind=kind)

    monkeypatch.setattr(mod.runner, "submit", fake_submit)
    r = c.post("/api/generations", json={"template_id": tid, "brief": BRIEF, "strategies": [], "use_models": False, "exports": []})
    assert r.status_code == 200
    meta = mod.store.read_generation_meta(r.json()["generation_id"])
    assert meta["strategies"] == ["structured", "visual", "compact"]


def test_the_upload_goes_once_the_template_is_analysed(client):  # noqa: F811
    c, mod = client
    _template(c)
    assert not [p for p in mod.store.uploads.rglob("*") if p.is_file()]


def test_a_background_coloured_shape_is_no_card_a_text_runs_out_of(tmp_path):
    """Marketing Report: an ellipse filled with the ground's own colour (a soft glow of the template) under a pie's
    legend made every legend row «выходит за свою карточку» — twelve false errors, the variant scored 0."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    from verstka.audit.checks.layout import text_outside_card
    from verstka.audit.ir import build_deck_ir
    from verstka.audit.registry import AuditContext

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor(0xFE, 0xFC, 0xFF)
    glow = s.shapes.add_shape(9, Inches(7.9), Inches(1.0), Inches(3.5), Inches(3.5))  # an ellipse
    glow.fill.solid()
    glow.fill.fore_color.rgb = RGBColor(0xFD, 0xFB, 0xFF)
    glow.line.fill.background()
    tb = s.shapes.add_textbox(Inches(9.5), Inches(2.0), Inches(3.2), Inches(1.0))
    tb.text_frame.text = "Продукты, упаковка и списания"
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    deck = tmp_path / "d.pptx"
    prs.save(str(deck))
    ctx = AuditContext(ir=build_deck_ir(deck, with_images=False), manifest=None)
    assert text_outside_card(ctx) == []


def test_a_sentence_goes_only_from_the_block_that_overflows():
    from verstka.planning.faithful import drop_one_sentence
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import OutlineSlide, SlideContent, SlideItem

    def slide():
        return OutlineSlide(id="s", kind=PatternKind.cards, headline="Этапы", verbatim=True, content=SlideContent(items=[
            SlideItem(title="Первый этап развития", text="Повышение надежности. Резервное питание."),
            SlideItem(title="Второй этап", text="Анализ истории. Система сможет сравнивать зоны и выявлять быстрое высыхание."),
        ]))

    s = slide()
    assert drop_one_sentence(s, target="Первый этап развития") == "skip"  # a one-line title over its card: no text goes
    assert s.content.items[1].text.startswith("Анализ истории. Система")
    s = slide()
    assert drop_one_sentence(s, target="Повышение надежности. Резервное питание.").startswith("one sentence less")
    assert s.content.items[0].text == "Повышение надежности." and "Система сможет" in s.content.items[1].text
