"""«Взгляд дизайнера» (verstka/audit/eyes.py): the vision model looks at every rendered slide; a slide it sends back
is laid out again, and the new layout stays only when the deterministic audit is not worse, the slide really changed and
the model, shown both layouts side by side in both orders, prefers it both times. The model is a script here and the
slide images are drawn without LibreOffice."""

from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pptx import Presentation

from verstka.audit import eyes as E
from verstka.ingest.workspace import TemplateWorkspace
from verstka.pipeline.generate import generate_variants
from verstka.planning.brief import parse_brief_text
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry
from verstka.rendering.renderer import render_deck
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
    """The slide images without LibreOffice: one plain picture per slide of the deck as it is now, its colour drawn
    from the slide's XML — a slide laid out again looks different, an untouched one the same."""
    from lxml import etree

    out.mkdir(parents=True, exist_ok=True)
    got = {}
    for i, slide in enumerate(Presentation(str(pptx)).slides, 1):
        h = hashlib.sha1(etree.tostring(slide._element)).digest()
        im = Image.new("RGB", (64, 36), "white")
        d = ImageDraw.Draw(im)
        for cell in range(16):  # a 4 × 4 grid of black and white cells, one bit of the hash each
            if h[cell // 8] >> (cell % 8) & 1:
                x, y = cell % 4 * 16, cell // 4 * 9
                d.rectangle([x, y, x + 15, y + 8], fill="black")
        p = out / f"slide-{i:03d}.jpg"
        buf = io.BytesIO()
        im.save(buf, "JPEG")
        p.write_bytes(buf.getvalue())
        got[i] = p
    return got


def _same_shots(pptx: Path, out: Path, dpi: int) -> dict[int, Path]:
    """Images that never change: a new layout that moved nothing visible."""
    out.mkdir(parents=True, exist_ok=True)
    got = {}
    for i in range(1, len(Presentation(str(pptx)).slides) + 1):
        p = out / f"slide-{i:03d}.jpg"
        Image.new("RGB", (64, 36), (40, 80, 120)).save(p, "JPEG")
        got[i] = p
    return got


@pytest.fixture
def variant(simple_deck, tmp_path):
    res = generate_variants(simple_deck, brief=parse_brief_text(BRIEF), strategies=["structured"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws",
                            use_llm=False, use_vlm=False, exports=[], render_images=False, pictures=False)
    v = res.variants[0]
    ws = TemplateWorkspace.open(res.manifest.template_id, tmp_path / "ws")
    return v, res.manifest, ws


def _target(v, manifest, ws, tmp_path) -> int:
    """A content slide the ladder really moves: its next layout (another sample, the composer, another variant's style)
    renders differently from the one it has."""
    for k, ps in enumerate(v.plan.slides, 1):
        osl = next(s for s in v.outline.slides if s.id == ps.outline_id)
        if osl.kind.value in ("title", "thanks", "agenda", "section"):
            continue
        if not (ps.mode == "synth" or any(score >= 0.3 for _, score in ps.alternatives)):
            continue
        plan, outline = v.plan.model_copy(deep=True), v.outline.model_copy(deep=True)
        trial = tmp_path / f"trial-{k}.pptx"
        was = E.slide_hashes(v.out_dir / "deck.pptx")
        for _ in range(3):
            if E.relayout(plan, outline, ps.outline_id, manifest, set()) == "skip":
                break
            render_deck(outline, plan, manifest, ws, trial)
            if E.slide_hashes(trial).get(k) != was.get(k):
                return k
    pytest.skip("no slide of the synthetic deck has another layout to try")


def _model(flag: int, prefer_new: bool | str, calls: list):
    """`prefer_new`: True / False — the model's choice; "first" — a model that always picks the image shown first."""

    def answer(messages):
        user = messages[-1].content
        calls.append((user, len(messages[-1].images)))
        if "Prefer the new attempt" in user:
            if prefer_new == "first":
                return {"a": "карточки", "b": "карточки", "better": "A", "reason": "новая вёрстка ровнее"}
            original = "A" if "Layout A is the current one" in user else "B"
            new = "B" if original == "A" else "A"
            return {"a": "заголовок и карточки", "b": "заголовок и карточки", "better": new if prefer_new else original, "reason": "без разрывов слов" if prefer_new else "прежняя аккуратнее"}
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


def test_a_slide_the_model_sends_back_is_laid_out_again_and_kept_when_the_model_prefers_it(variant, tmp_path):
    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
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
    assert len(compare) == 2 and all(n == 2 for _, n in compare)  # both layouts in one look, the pair asked in both orders
    assert {("Layout A is the current one" in c) for c, _ in compare} == {True, False}
    assert any(s == k and "Взгляд дизайнера: слайд" in m and "слова разорваны посередине (карточки)." in m and "| Собрал заново" in m for s, m in events)
    assert rr is not None and Path(v.out_dir / "deck.pptx").exists()


def test_the_old_layout_stays_when_the_model_does_not_prefer_the_new_one_and_its_remark_stays(variant, tmp_path):
    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
    before = v.plan.slides[k - 1].model_copy(deep=True)
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(k, False, []))
    assert not seen.fixed and [x["slide"] for x in seen.kept] == [k] and seen.kept[0]["why"] == "модель сочла её лучше — прежняя аккуратнее"
    after = plan.slides[k - 1]
    assert (after.pattern_id, after.mode, after.composition) == (before.pattern_id, before.mode, before.composition)
    remark = [i for i in report.issues if i.check_id == "design_review"]
    assert len(remark) == 1 and remark[0].slide == k and remark[0].kind == "model" and remark[0].severity == "warn"
    assert "Слова разорваны посередине (карточки)" in remark[0].message
    assert any(s == k and m.endswith("| Оставил прежнюю вёрстку: модель сочла её лучше — прежняя аккуратнее.") for s, m in events)


def test_a_clean_deck_is_left_as_it_is(variant, tmp_path):
    v, manifest, ws = variant
    plan0 = v.plan.model_dump()
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(-1, True, []))
    assert seen.looked > 0 and not seen.flagged and not seen.fixed and rr is None
    assert plan.model_dump() == plan0 and events == [(None, f"Взгляд дизайнера: посмотрел на {E.ru_slides(seen.looked)} — замечаний нет.")]


def test_the_review_needs_time_a_vision_model_and_slide_images(variant, tmp_path):
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


def test_a_review_that_does_not_start_says_so_on_the_timeline_with_a_code(variant, tmp_path):
    """The build's «Взгляд дизайнера» never hangs «now» till the end: a skip is a line of its own under the step, in the
    person's words (the reason's English stays in `skipped` for the log), and the outcome keeps the reason's code."""
    v, manifest, ws = variant
    events: list = []

    def run(**kw):
        return E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, skills=SKILLS, images=_shots,
                      emit=lambda message, slide=None, fix=None: events.append((slide, message)), **kw)[4]

    short = run(providers=_model(1, True, []), deadline=time.monotonic() + 10)
    assert short.skipped_code == "no_time" and short.summary()["skipped_code"] == "no_time"
    assert events == [(None, "Взгляд дизайнера пропущен: не хватило времени на сборку.")]
    events.clear()
    assert run(providers=ProviderRegistry(roles={"llm": MockProvider({})})).skipped_code == "no_model"
    assert events == [(None, "Взгляд дизайнера пропущен: модель недоступна.")]
    events.clear()
    assert run(providers=_model(1, True, []), cfg={"enabled": False}).skipped_code == "off"
    assert events == [(None, "Взгляд дизайнера пропущен: выключен в настройках.")]
    # a review that ran says what it saw, never «пропущен»
    events.clear()
    seen = run(providers=_model(-1, True, []), deadline=time.monotonic() + 120)
    assert seen.skipped is None and seen.skipped_code is None and not any("пропущен" in m for _, m in events)


def test_the_skip_reasons_have_a_code_and_the_interfaces_words():
    assert E.skip_code("no time left in the generation's model budget") == "no_time"
    assert E.skip_code("no slide images (soffice not found)") == "no_images"
    assert E.skip_code("the model did not answer") == "no_answer"
    assert E.skip_code("off in configs/eyes.yaml") == "off" and E.skip_code("no vision model") == "no_model"
    assert E.skip_code("failed: boom") == "failed" and E.skip_code("something new") is None and E.skip_code(None) is None
    assert E.skip_message("no_time") == "Взгляд дизайнера пропущен: не хватило времени на сборку."
    assert E.skip_message("unknown") == "Взгляд дизайнера пропущен."
    # no English reaches the screen: the words are Russian, and the web keeps the same ones for runs recorded before
    # the timeline said it (web/src/lib/designEye.ts `EYES_SKIP`)
    web = (Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "designEye.ts").read_text(encoding="utf-8")
    for code, words in E.SKIP_RU.items():
        assert not any("a" <= ch.lower() <= "z" for ch in words), words
        assert f'{code}: "{words}"' in web, code


def test_a_review_that_fails_in_the_pipeline_ends_as_skipped_on_the_timeline(simple_deck, tmp_path, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(E, "look", broken)
    events: list = []

    def progress(msg="", frac=None, event=None):
        if event is not None:
            events.append(event)

    res = generate_variants(simple_deck, brief=parse_brief_text(BRIEF), strategies=["structured"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws",
                            use_llm=False, use_vlm=True, providers=_model(1, True, []), skills=SKILLS, exports=[], render_images=False, pictures=False,
                            progress=progress)
    said = [e for e in events if e.get("step") == "eyes"]
    assert [(e["message"], e["variant"]) for e in said] == [("Взгляд дизайнера пропущен: не получилось посмотреть на слайды.", "structured")]
    import json

    m = json.loads((res.variants[0].out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert m["eyes"]["skipped_code"] == "failed" and m["eyes"]["skipped"].startswith("failed: boom")


def test_a_model_that_does_not_answer_leaves_the_slides_and_says_so(variant, tmp_path):
    v, manifest, ws = variant

    def silent(messages):
        raise TimeoutError("the model did not answer in time")

    p = MockProvider(silent, model="qwen/qwen3.8-27b")
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, ProviderRegistry(roles={"llm": p, "vlm": p}))
    assert seen.skipped == "the model did not answer" and seen.looked == 0 and not seen.flagged and rr is None
    assert events == [(None, "Взгляд дизайнера: модель не ответила — слайды остались как были.")]
    assert report is v.audit


def test_a_rejected_new_layout_leaves_the_deck_byte_for_byte(variant, tmp_path):
    """Nothing kept: the deck is the one the audit and the autofix left — its fixes made in the XML included."""
    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
    deck = v.out_dir / "deck.pptx"
    before = hashlib.sha1(deck.read_bytes()).hexdigest()
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(k, False, []))
    assert [x["slide"] for x in seen.kept] == [k] and rr is None
    assert hashlib.sha1(deck.read_bytes()).hexdigest() == before


def test_the_report_describes_the_deck_on_disk_after_a_new_layout(variant, tmp_path):
    """A slide laid out again: the report is the deck's own audit — no fix it lists is lost from the file, no issue of
    the file missing from the report."""
    from verstka.audit.runner import run_audit

    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(k, True, []))
    assert [f["slide"] for f in seen.fixed] == [k]
    fresh = run_audit(v.out_dir / "deck.pptx", manifest, outline, ws, render=False, strategy=report.strategy)
    key = lambda r: sorted((i.check_id, i.slide, i.severity) for i in r.issues if i.kind != "model")  # noqa: E731
    assert key(report) == key(fresh)


def test_a_failure_while_laying_out_again_puts_the_deck_back(variant, tmp_path):
    """LibreOffice fails on the new layout's picture: the deck, the plan and the report stay as they were, the model's
    remark stays, nothing unseen is shipped."""
    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
    deck = v.out_dir / "deck.pptx"
    before = hashlib.sha1(deck.read_bytes()).hexdigest()
    plan0 = v.plan.slides[k - 1].model_copy(deep=True)
    shots = {"n": 0}

    def flaky(pptx, out, dpi):
        shots["n"] += 1
        if shots["n"] > 1:
            raise RuntimeError("soffice crashed")
        return _shots(pptx, out, dpi)

    report, plan, outline, rr, seen = E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=_model(k, True, []), skills=SKILLS,
                                             deadline=time.monotonic() + 120, images=flaky)
    assert not seen.fixed and [x["why"] for x in seen.kept] == ["пересобрать слайд не удалось"] and rr is None
    assert hashlib.sha1(deck.read_bytes()).hexdigest() == before
    after = plan.slides[k - 1]
    assert (after.pattern_id, after.mode, after.fit.get("style")) == (plan0.pattern_id, plan0.mode, plan0.fit.get("style"))
    assert any(i.check_id == "design_review" and i.slide == k for i in report.issues)


def test_a_slide_takes_no_sample_another_variant_shows_there(variant, tmp_path):
    """The look sees the samples the OTHER variants show on the same slide at the moment it moves one — also those laid
    out while it looks — and tells the sample it takes."""
    v, manifest, ws = variant
    calls: list = []
    picks: list = []
    k = _target(v, manifest, ws, tmp_path)
    E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=_model(k, True, []), skills=SKILLS, deadline=time.monotonic() + 120,
           images=_shots, others_live=lambda: calls.append(1) or {}, on_pick=lambda osl, pid: picks.append((osl.id if osl else None, pid)))
    ps = v.plan.slides[k - 1]
    moved_by_rematch = ps.mode == "clone"
    if moved_by_rematch:
        assert calls and picks and picks[0][1] == ps.pattern_id
    else:
        assert calls  # a composed slide asks too (the ladder may go to a sample)


def test_the_review_of_an_old_deck_follows_the_config_and_skips_its_closing(tmp_path, monkeypatch):
    """«Улучшить готовую»: the original is looked at as a new deck is — not its closing or contents slide; with the
    review off in configs/eyes.yaml no model is asked; the slide pictures go to a folder of their own, removed after."""
    asked: list = []

    def answer(messages):
        asked.append(messages[-1].content)
        return {"ok": False, "problems": [{"code": "unbalanced", "severity": "major", "where": "правая половина", "evidence": "пусто"}], "verdict": ""}

    p = MockProvider(answer, model="qwen/qwen3.8-27b")
    providers = ProviderRegistry(roles={"llm": p, "vlm": p})

    def shots(pptx, out, dpi):
        out.mkdir(parents=True, exist_ok=True)
        got = {}
        for i in (1, 2, 3):
            f = out / f"slide-{i:03d}.jpg"
            Image.new("RGB", (32, 18), "white").save(f, "JPEG")
            got[i] = f
        return got

    titles = {1: "Итоги квартала", 2: "Продажи", 3: "Спасибо за внимание!"}
    seen = E.look_only(tmp_path / "old.pptx", tmp_path / "eyes", providers=providers, skills=SKILLS, titles=titles, deadline=time.monotonic() + 60, images=shots)
    assert sorted(seen) == [1, 2] and len(asked) == 2
    assert not any((tmp_path / "eyes").iterdir())  # the pictures are gone with their folder
    asked.clear()
    assert E.look_only(tmp_path / "old.pptx", tmp_path / "eyes", providers=providers, skills=SKILLS, titles=titles, cfg={"enabled": False}, images=shots) == {}
    assert not asked
    issues = E.problem_issues(seen, {1: "s1", 2: "s2"})
    from verstka.api.remarks import hint_of

    assert issues and hint_of(issues[0]) == E.FIX_HINTS["unbalanced"]


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
    assert E.DesignCompare.model_validate({"a": "  карточки\n и заголовок ", "better": "B"}).a == "карточки и заголовок"


def test_a_model_that_answers_by_the_position_of_the_image_never_changes_a_slide(variant, tmp_path):
    """Asked in both orders, a model that picks whichever image comes first chooses the new layout once and the old one
    once: the slide stays as it was, and the remark stays."""
    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
    before = v.plan.slides[k - 1].model_copy(deep=True)
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(k, "first", []))
    assert not seen.fixed and [x["why"] for x in seen.kept] == ["модель выбрала новую вёрстку только в одном порядке сравнения"]
    after = plan.slides[k - 1]
    assert (after.pattern_id, after.mode, after.composition) == (before.pattern_id, before.mode, before.composition)
    assert any(i.check_id == "design_review" and i.slide == k for i in report.issues)


def test_a_new_layout_that_changes_nothing_visible_is_not_compared(variant, tmp_path):
    """A relayout that moved a hairline (or nothing) is no new layout: the slide stays without asking the model."""
    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
    calls: list = []
    events: list = []
    out = E.look(v.out_dir, v.audit, v.outline, v.plan, manifest, ws, providers=_model(k, True, calls), skills=SKILLS, deadline=time.monotonic() + 120,
                 emit=lambda message, slide=None, fix=None: events.append(message), images=_same_shots)
    seen = out[4]
    assert not seen.fixed and [x["why"] for x in seen.kept] == ["новая вёрстка почти не отличается от прежней"]
    assert not any("Prefer the new attempt" in c for c, _ in calls)


def test_a_slide_no_rung_of_the_ladder_can_change_goes_back_without_a_look(variant, tmp_path, monkeypatch):
    """Every next layout the ladder offers renders the slide exactly as it was (a style the composer draws alike): the
    slide goes back at once, and no model is asked to compare two equal pictures."""
    v, manifest, ws = variant
    k = _target(v, manifest, ws, tmp_path)
    tries: list = []

    def same_again(plan, outline, oid, manifest, taken=None, others=None):
        tries.append(oid)
        return "restyle → compact" if len(tries) <= 3 else "skip"

    monkeypatch.setattr(E, "relayout", same_again)
    calls: list = []
    report, plan, outline, rr, seen, events = _look(v, manifest, ws, _model(k, True, calls))
    assert len(tries) == 3  # the first rung and two more
    assert not seen.fixed and [x["why"] for x in seen.kept] == ["другой вёрстки для этого слайда не нашлось"]
    assert not any("Prefer the new attempt" in c for c, _ in calls)
    assert any(i.check_id == "design_review" and i.slide == k for i in report.issues)


def test_the_share_of_the_slide_a_new_layout_changed(tmp_path):
    def draw(name: str, box=None, line=None) -> Path:
        im = Image.new("RGB", (1000, 562), "white")
        d = ImageDraw.Draw(im)
        d.rectangle([60, 60, 600, 140], fill=(20, 20, 20))  # the heading
        if box:
            d.rectangle(box, fill=(30, 90, 200))
        if line:
            d.line(line, fill=(120, 120, 120), width=1)
        p = tmp_path / name
        im.save(p, "JPEG", quality=90)
        return p

    a = draw("a.jpg", box=[60, 200, 400, 480])
    assert E.changed_share(a, a) == 0.0
    assert E.changed_share(a, draw("hairline.jpg", box=[60, 200, 400, 480], line=[700, 150, 700, 480])) < E.DEFAULTS["min_change"]
    assert E.changed_share(a, draw("moved.jpg", box=[560, 200, 900, 480])) > 0.1


def test_the_config_file_is_read_with_defaults_for_what_it_leaves_out(tmp_path):
    p = tmp_path / "eyes.yaml"
    p.write_text("enabled: false\nmax_fixes: 2\nunknown: 7\n", encoding="utf-8")
    cfg = E.load_config(p)
    assert cfg["enabled"] is False and cfg["max_fixes"] == 2 and "unknown" not in cfg and cfg["compare"] is True
    assert E.load_config(tmp_path / "missing.yaml") == E.DEFAULTS
