"""Gate 4 G4-21: a topic whose writer failed (the model is down) is built as a skeleton — and the audit is told so
(pipeline/generate.py passes the writer's record to run_audit / autofix_loop), so the deck never scores as a success."""

from __future__ import annotations

from pathlib import Path

import pytest

from verstka.providers.base import ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry
from verstka.schemas.outline import Brief
from verstka.skills_registry.registry import SkillsRegistry


def _down(messages):
    raise ProviderError("Qwen3 32B (Cloud.ru): access refused (401/403): HTTP 403 (Project not found. Please contact support)")


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


def test_a_topic_the_model_could_not_write_is_audited_as_unwritten(vk_tech, tmp_path, monkeypatch):
    from verstka.pipeline.generate import generate_variants

    monkeypatch.setenv("VERSTKA_WIKI", "0")
    monkeypatch.setenv("VERSTKA_WRITER", "1")  # writer mode is off by default for the submission
    model = MockProvider(_down, model="Qwen/Qwen3-32B")
    providers = ProviderRegistry(roles={"llm": model, "vlm": model}, limits=ProviderLimits(max_concurrency=2, time_budget_s=60))
    res = generate_variants(
        vk_tech, brief=Brief(text="Полёт Гагарина", slide_count=6), out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", providers=providers,
        skills=SkillsRegistry.load(), use_vlm=False, audit=True, autofix=False, exports=[], render_images=False, strategies=["structured"],
    )
    assert res.writer is not None and res.writer.status in ("failed", "skipped")
    v = res.variants[0]
    ids = [i.check_id for i in v.audit.issues]
    assert "writer_failed" in ids, ids
    assert v.audit.summary.score < 97
