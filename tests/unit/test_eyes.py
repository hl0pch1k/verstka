"""«Взгляд дизайнера» (verstka/audit/eyes.py): the vision model looks at every rendered slide; a slide it sends back
is laid out again, and the new layout stays only when the deterministic audit is not worse and the model, shown both
layouts side by side, prefers it. The model is a script here and the slide images are drawn without LibreOffice."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation

from verstka.audit import eyes as E
from verstka.ingest.workspace import TemplateWorkspace
from verstka.pipeline.generate import generate_variants
from verstka.planning.brief import parse_brief_text
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry
from verstka.skills_registry.registry import SkillsRegistry

BRIEF = """# Умные напоминания

В пилоте участвовали 12 400 сотрудников. Доля завершённых в срок задач выросла на 34%. Экономия 2,1 часа в неделю.

## Что сделали
Напоминание из чата превращает сообщение в задачу одним касанием. Умный срок предлагает дату по контексту. Эскалация уходит руководителю автоматически.

## Что дальше
Запуск на всю компанию в ноябре.
"""
SKILLS = SkillsRegistry.load()


def _shots(pptx: Path, out: Path, dpi: int) -> dict[int, Path]:
    """The slide images without LibreOffice: one plain picture per slide of the deck as it is now."""
    out.mkdir(parents=True, exist_ok=True)
    n = len(Presentation(str(pptx)).slides)
    got = {}
    for i in range(1, n + 1):
        p = out / f"slide-{i:03d}.jpg"
        buf = io.BytesIO()
        Image.new("RGB", (64, 36), (10 * i % 255, 80, 120)).save(buf, "JPEG")
        p.write_bytes(buf.getvalue())
        got[i] = p
    return got


@pytest.fixture
def variant(simple_deck, tmp_path):
    res = generate_variants(simple_deck, brief=parse_brief_text(BRIEF), strategies=["structured"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws",
                            use_llm=False, use_vlm=False, exports=[], render_images=False, pictures=False)
    v = res.variants[0]
    ws = TemplateWorkspace.open(res.manifest.template_id, tmp_path / "ws")
    return v, res.manifest, ws


def _target(v) -> int:
    """A content slide the ladder can move: on a sample with an untried alternative, or composed."""
    for k, ps in enumerate(v.plan.slides, 1):
        osl = next(s for s in v.outline.slides if s.id == ps.outline_id)
        if osl.kind.value in ("title", "thanks", "agenda", "section"):
            continue
        if ps.mode == "synth" or any(score >= 0.3 for _, score in ps.alternatives):
            return k
    pytest.skip("no slide of the synthetic deck has another layout to try")


def _model(flag: int, prefer_new: bool, calls: list):
    def answer(messages):
        user = messages[-1].content
        calls.append((user, len(messages[-1].images)))
        if "Prefer the new attempt" in user:
            original = "A" if "Layout A is the current one" in user else "B"
            new = "B" if original == "A" else "A"
            return {"better": new if prefer_new else original, "reason": "без разрывов слов" if prefer_new else "прежняя аккуратнее"}
        if f"Slide {flag} of the deck" in user:
            return {"ok": False, "problems": [{"code": "word_broken", "severity": "major", "where": "карточки", "evidence": "«Температ|ура»"}], "verdict": "Разрывы слов."}
        return {"ok": True, "problems": [], "verdict": "Аккуратно."}

    p = MockProvider(answer, model="qwen/qwen3.8-27b")
    return ProviderRegistry(roles={"llm": p, "vlm": p})


def _look(v, manifest, ws, providers, **kw):
    events: list = []
    out = E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=providers, skills=SKILLS, deadline=time.monotonic() + 120,
                 emit=lambda message, slide=None, fix=None: events.append((slide, message + (f" | {fix}" if fix else ""))), images=_shots, **kw)
    return (*out, events)


def test_a_slide_the_model_sends_back_is_laid_out_again_and_kept_when_the_model_prefers_it(variant):
    v, manifest, ws = variant
    k = _target(v)
    before = v.plan.slides[k - 1].model_copy(deep=True)
    calls: list = []
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(k, True, calls))
    assert seen.looked == sum(1 for s in v.outline.slides if s.kind.value not in ("thanks", "agenda"))  # a closing slide is not looked at
    assert [f["slide"] for f in seen.flagged] == [k] and [f["slide"] for f in seen.fixed] == [k] and not seen.kept
    after = plan.slides[k - 1]
    assert (after.pattern_id, after.mode, after.fit.get("style")) != (before.pattern_id, before.mode, before.fit.get("style"))
    assert any(f.get("iteration") == "eyes" and f.get("outline_id") == after.outline_id and not f.get("rolled_back") for f in report.applied_fixes)
    assert not any(i.check_id == "design_review" for i in report.issues)  # cured: no remark left
    compare = [c for c in calls if "Prefer the new attempt" in c[0]]
    assert len(compare) == 1 and compare[0][1] == 2  # both layouts in one look
    assert any(s == k and "Взгляд дизайнера: слайд" in m and "слова разорваны посередине (карточки)." in m and "| Собрал заново" in m for s, m in events)
    assert rr is not None and Path(v.out_dir / "deck.pptx").exists()


def test_the_old_layout_stays_when_the_model_does_not_prefer_the_new_one_and_its_remark_stays(variant):
    v, manifest, ws = variant
    k = _target(v)
    before = v.plan.slides[k - 1].model_copy(deep=True)
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(k, False, []))
    assert not seen.fixed and [x["slide"] for x in seen.kept] == [k] and seen.kept[0]["why"] == "прежняя аккуратнее"
    after = plan.slides[k - 1]
    assert (after.pattern_id, after.mode, after.composition) == (before.pattern_id, before.mode, before.composition)
    remark = [i for i in report.issues if i.check_id == "design_review"]
    assert len(remark) == 1 and remark[0].slide == k and remark[0].kind == "model" and remark[0].severity == "warn"
    assert "Слова разорваны посередине (карточки)" in remark[0].message
    assert any("оставил прежнюю" in m for _, m in events)


def test_a_clean_deck_is_left_as_it_is(variant):
    v, manifest, ws = variant
    plan0 = v.plan.model_dump()
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(-1, True, []))
    assert seen.looked > 0 and not seen.flagged and not seen.fixed and rr is None
    assert plan.model_dump() == plan0 and events == [(None, f"Взгляд дизайнера: посмотрел на {E.ru_slides(seen.looked)} — замечаний нет.")]


def test_the_review_needs_time_a_vision_model_and_slide_images(variant):
    v, manifest, ws = variant
    providers = _model(1, True, [])
    short = E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=providers, skills=SKILLS, deadline=time.monotonic() + 10, images=_shots)
    assert short[4].skipped == "no time left in the generation's model budget" and short[4].calls == 0
    text_only = ProviderRegistry(roles={"llm": MockProvider({})})
    assert E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=text_only, skills=SKILLS, images=_shots)[4].skipped == "no vision model"

    def broken(pptx, out, dpi):
        raise RuntimeError("soffice not found")

    got = E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=providers, skills=SKILLS, images=broken)
    assert got[4].skipped.startswith("no slide images") and got[0] is v.audit
    off = E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=providers, skills=SKILLS, images=_shots, cfg={"enabled": False})
    assert off[4].skipped == "off in configs/eyes.yaml"


def test_the_models_answers_are_read_leniently():
    r = E.DesignReview.model_validate({"ok": "false", "problems": [
        {"code": "Word-Break", "severity": "Major", "where": "карточки", "evidence": "  «Температ|ура»  "},
        {"code": "nonsense", "severity": "major"},
        "not a problem",
        {"code": "low contrast", "severity": "minor"},
    ]})
    assert [p.code for p in r.known()] == ["word_broken", "low_contrast"] and [p.code for p in r.major()] == ["word_broken"]
    assert r.known()[0].evidence == "«Температ|ура»"
    assert E.DesignCompare.model_validate({"better": "Б"}).better == "B" and E.DesignCompare.model_validate({"better": "both"}).better == "same"
    assert E.DesignCompare.model_validate({"better": " a. "}).better == "A"


def test_the_new_layout_comes_first_on_every_other_slide(variant):
    """Shown in either order, the model favours no side: the original is «A» on even slides and «B» on odd ones."""
    v, manifest, ws = variant
    k = _target(v)
    calls: list = []
    _look(v, manifest, ws, _model(k, True, calls))
    prompt = next(c[0] for c in calls if "Prefer the new attempt" in c[0])
    assert (f"Layout {'B' if k % 2 else 'A'} is the current one") in prompt


def test_the_config_file_is_read_with_defaults_for_what_it_leaves_out(tmp_path):
    p = tmp_path / "eyes.yaml"
    p.write_text("enabled: false\nmax_fixes: 2\nunknown: 7\n", encoding="utf-8")
    cfg = E.load_config(p)
    assert cfg["enabled"] is False and cfg["max_fixes"] == 2 and "unknown" not in cfg and cfg["compare"] is True
    assert E.load_config(tmp_path / "missing.yaml") == E.DEFAULTS
