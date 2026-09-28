"""Writer mode end to end (WRITER_SPEC §12.1 T11, T14): a topic → the writer's text (a recorded Qwen3-32B answer) → the
agent builds the deck from it → every figure on the slides is in the written text; and the API keeps that text for the
result screen, the edits and «Исправить слайд». No network: the Wikipedia lookup is off (VERSTKA_WIKI=0)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from verstka.planning import writer as W
from verstka.providers.base import ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry

F = Path(__file__).resolve().parents[1] / "fixtures" / "writer"
REF = json.loads((F / "answers_ref.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _writer_on(monkeypatch):
    """Writer mode is off by default for the submission (configs/writer.yaml): these tests switch it on."""
    monkeypatch.setenv("VERSTKA_WRITER", "1")


class Scripted:
    """The model: the topic's kind, the recorded writer answer, an empty fact check; the designer and the critic fail
    (a slow host) — the rules build every slide from the written text."""

    def __init__(self, answer: dict, kind: str = "company") -> None:
        self.answer, self.kind = answer, kind
        self.calls: dict[str, int] = {}

    def __call__(self, messages):
        system = messages[0].content
        if "You name encyclopedia articles" in system:
            name = "reference"
            out = {"titles": ["ВКонтакте"], "kind": self.kind}
        elif "fact-checker" in system:
            name = "check"
            out = {"issues": []}
        elif "author of a presentation" in system:
            name = "writer"
            out = self.answer
        else:
            name = "other"
            self.calls[name] = self.calls.get(name, 0) + 1
            raise ProviderError("the host is slow (timeout)")
        self.calls[name] = self.calls.get(name, 0) + 1
        return out


@pytest.fixture(scope="module")
def vk_tech():
    import os

    env = os.environ.get("VERSTKA_FIXTURES_DIR")
    for c in ([Path(env)] if env else []) + [Path(__file__).resolve().parents[3] / "Датасет"]:
        if c.is_dir():
            p = next((x for x in c.glob("*.pptx") if "vk tech" in x.name.lower()), None)
            if p is not None:
                return p
    pytest.skip("VK Tech template not available")


@pytest.fixture(scope="module")
def written_run(vk_tech, tmp_path_factory):
    from verstka.pipeline.generate import generate_variants

    mp = pytest.MonkeyPatch()
    mp.setenv("VERSTKA_WIKI", "0")
    mp.setenv("VERSTKA_WRITER", "1")  # off by default for the submission
    try:
        fake = Scripted(json.loads(REF["vk"]["raw"]))
        model = MockProvider(fake, model="Qwen/Qwen3-32B")
        providers = ProviderRegistry(roles={"llm": model, "vlm": model}, limits=ProviderLimits(max_concurrency=4, time_budget_s=210))
        events: list[dict] = []

        def progress(msg, frac=None, event=None):
            if event is not None:
                events.append(event)

        out = tmp_path_factory.mktemp("out")
        t0 = time.time()
        res = generate_variants(
            vk_tech, brief=Brief(text="История VK", slide_count=8), out_dir=out, workspace_root=tmp_path_factory.mktemp("ws"), providers=providers,
            skills=SkillsRegistry.load(), use_vlm=False, audit=True, autofix=False, exports=[], render_images=False, progress=progress,
        )
        return res, events, out, fake, time.time() - t0
    finally:
        mp.undo()


def test_the_deck_is_built_from_the_written_text(written_run):
    res, events, out, fake, seconds = written_run
    w = res.writer
    assert w is not None and w.status == "written" and w.kind == "company" and fake.calls["writer"] == 1
    assert (out / "writer.md").read_text(encoding="utf-8") == w.text and json.loads((out / "writer.json").read_text(encoding="utf-8"))["status"] == "written"
    assert events and events[0]["step"] == "writer" and events[0]["message"].startswith("Пишу текст по теме «История VK»")
    for v in res.variants:
        o = v.outline
        assert len(o.slides) == w.slides + 1, v.strategy
        assert o.agent_log[0].startswith("Автор:")
        assert "Текст написан агентом Verstka по теме «История VK»" in (o.slides[0].notes or "")
        assert v.planner["writer"]["status"] == "written" and v.planner["writer"]["skills"]["deck_writer"]["version"] == "2.1.0"
        a = v.audit.summary
        assert a.score >= 97, (v.strategy, [(i.check_id, i.message) for i in v.audit.issues if i.severity != "info"])
        assert not [i for i in v.audit.issues if i.check_id == "figure_not_in_brief"], v.strategy
    # no year became a slide's key figure
    for v in res.variants:
        for s in v.outline.slides:
            for n in s.content.numbers or []:
                assert not re.fullmatch(r"(?:19|20)\d{2}(?:\s*г\.?)?", (n.value or "").strip()), (v.strategy, s.headline, n)


def test_the_run_manifest_names_the_writers_calls(written_run):
    res, _, out, _, _ = written_run
    rm = json.loads((res.variants[0].out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert rm["planner"]["writer"]["status"] == "written"
    by_skill = (rm["planner"].get("agent") or {}).get("by_skill") or {}
    assert "WriterAnswer" in by_skill and "ReferenceAnswer" in by_skill


def test_a_brief_with_material_never_starts_the_writer():
    for name in ("coffee_short.md", "coffee_long.md"):
        text = (Path(__file__).resolve().parents[1] / "fixtures" / "briefs" / name).read_text(encoding="utf-8")
        assert W.writer_mode(text).kind == "off"


# ------------------------------------------------------------------ T14: the API keeps the written text


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("VERSTKA_WORKSPACE", str(tmp_path / "ws"))
    import importlib

    import verstka.api.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app), app_module


def _written() -> W.WriterResult:
    res = W.WriterResult(mode="topic", status="written", topic="История VK", kind="company", slides=2, asked=3)
    res.text = "Слайд 1. Титульный\nНазвание: «История VK».\n\nСлайд 2. Основание\n«ВКонтакте» запущена в 2006 году.\n\nСлайд 3. Главное\nСеть работает с 2006 года.\n"
    res.brief = Brief(text=res.text, slide_count=3)
    res.source = {"title": "ВКонтакте", "url": "https://ru.wikipedia.org/wiki/ВКонтакте"}
    res.checked = "reference"
    return res


def test_the_generation_keeps_the_written_text(api, monkeypatch):
    client, mod = api
    import verstka.pipeline.generate as G
    from verstka.api.jobs import Job

    writer = _written()

    def fake_generate(template, **kw):
        writer.write_files(kw["out_dir"])
        return SimpleNamespace(variants=[], seconds=1.0, writer=writer)

    monkeypatch.setattr(G, "generate_variants", fake_generate)
    monkeypatch.setattr(mod.store, "manifest", lambda tid: SimpleNamespace(source_file="t.pptx"))
    monkeypatch.setattr(mod.store, "workspace", lambda tid: SimpleNamespace(source=Path("t.pptx")))
    gid, gdir = mod.store.new_generation_dir()
    meta = mod._run_generation(gid, gdir, mod.GenerateRequest(template_id="t", brief="История VK", slides=3, use_models=False), Job(id="j", kind="generate"))
    w = meta["writer"]
    assert w["status"] == "written" and w["text"] == writer.text and w["source"]["title"] == "ВКонтакте" and w["slides"] == 3 and w["checked"] == "reference"
    assert meta["brief"] == "История VK"  # the user's topic stays; «Собрать ещё раз» writes anew
    assert json.loads((gdir / "generation.json").read_text(encoding="utf-8"))["writer"]["status"] == "written"
    # edits, «Исправить слайд» and the remarks ground against the written text, not the topic
    b = mod._brief_of_meta(meta)
    from verstka.planning.writer import with_rules

    assert b is not None and b.text.strip() == with_rules(writer.text).strip() and b.slide_count == 3
    assert mod._brief_text_of_meta(gid, meta) == writer.text
    r = client.get(f"/api/generations/{gid}/writer.md")
    assert r.status_code == 200 and r.text == writer.text
    # a deck built from the user's own text: its brief, and no writer.md
    plain = {"id": gid, "brief": "Слайд 1. Итоги\nВыручка 900 000 рублей.", "slides": 1}
    assert mod._brief_of_meta(plain).text.startswith("Слайд 1. Итоги")
    assert client.get("/api/generations/nope/writer.md").status_code == 404
