"""What a generation's model calls cost (Polza puts usage.cost_rub in every answer): the recorders sum it by skill, a
recorder inside another keeps the call's skill, the run manifest still describes the model chain behind the recorder,
and the pictures a variant shares with the others are counted once."""

from __future__ import annotations

import json

from verstka.analysis.manifest import analyze_template
from verstka.images.fill import summary
from verstka.pipeline.generate import _recording, _usage_of, call_totals, generate_variants
from verstka.planning.brief import parse_brief_text
from verstka.providers.base import ChatMessage, CompletionResult, ProviderError, Usage
from verstka.providers.chain import ChainProvider
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry
from verstka.skills_registry.registry import SkillsRegistry

MSGS = [ChatMessage(role="user", content="hi")]


class _Paid:
    name = "polza"
    off = False

    def __init__(self, model: str, cost: float) -> None:
        self.model = model
        self.label = model
        self.cost = cost

    def complete(self, messages, *, schema=None, temperature=0.2, max_tokens=4096, deadline=None):
        return CompletionResult(text="ok", parsed=None, usage=Usage(100, 20, self.cost), model=self.model)


def _registry(cost: float = 0.25) -> ProviderRegistry:
    chain = ChainProvider([_Paid("qwen/qwen3.8-27b", cost), _Paid("qwen/qwen3.6-27b", cost)])
    return ProviderRegistry(roles={"llm": chain, "vlm": chain})


def test_the_rubles_of_every_call_are_summed_by_skill():
    stats: list = []
    reg, _ = _recording(_registry(0.25), stats)
    reg.get("llm").complete(MSGS, skill="deck_writer")
    reg.get("llm").complete(MSGS, skill="deck_writer")
    reg.get("vlm").complete(MSGS, skill="slide_content_audit")
    t = call_totals(stats)
    assert t["calls"] == 3 and t["cost_rub"] == 0.75
    assert t["by_skill"]["deck_writer"]["cost_rub"] == 0.5 and t["by_skill"]["slide_content_audit"]["cost_rub"] == 0.25
    assert _usage_of(stats)["scope"] == "generation" and _usage_of([]) == {}



def test_a_cost_no_call_named_stays_unknown_not_free():
    # the final's VK inference names no cost: the manifest says «unknown», never «0 ₽»
    stats = [{"skill": "deck_writer", "ok": True, "cost_rub": None}, {"skill": "deck_writer", "ok": True}]
    t = call_totals(stats)
    assert t["cost_rub"] is None and t["by_skill"]["deck_writer"]["cost_rub"] is None
    t = call_totals(stats + [{"skill": "critic", "ok": True, "cost_rub": 0.1}])
    assert t["cost_rub"] == 0.1 and t["by_skill"]["deck_writer"]["cost_rub"] is None


def test_a_recorder_inside_another_keeps_the_calls_skill():
    outer: list = []
    inner: list = []
    reg, _ = _recording(_registry(), outer)  # the generation's
    agent, _ = _recording(reg, inner)  # the agent's, inside it
    agent.get("llm").complete(MSGS, skill="deck_writer")
    assert [r["skill"] for r in inner] == ["deck_writer"] and [r["skill"] for r in outer] == ["deck_writer"]


def test_the_manifest_describes_the_chain_behind_the_recorder():
    reg, _ = _recording(_registry(), [])
    d = reg.describe()["llm"]
    assert [x["model"] for x in d["chain"]] == ["qwen/qwen3.8-27b", "qwen/qwen3.6-27b"]


def test_a_shared_picture_is_paid_once_in_the_variants_summary():
    recs = [
        {"status": "generated", "file": "a.jpg", "cost_rub": 1.4, "model": "tongyi-mai/z-image", "palette_match": 0.5},
        {"status": "generated", "file": "a.jpg", "cost_rub": 1.4, "model": "tongyi-mai/z-image", "palette_match": 0.5},
        {"status": "generated", "file": "b.jpg", "cost_rub": 1.4, "model": "tongyi-mai/z-image", "palette_match": 0.7},
        {"status": "free", "own": True},
    ]
    s = summary(recs)
    assert s["generated"] == 3 and s["cost_rub"] == 2.8
    assert summary([{"status": "free"}])["cost_rub"] is None
    unknown = [{"status": "generated", "file": "c.jpg", "cost_rub": None, "model": "vk-t2i", "palette_match": 0.5}]
    assert summary(unknown)["generated"] == 1 and summary(unknown)["cost_rub"] is None  # not «0 ₽»


class _Billed:
    """A Polza link that bills every call, an answer that fails included (the host answered, the tokens are paid):
    `broken` — every answer of this model is unusable (invalid JSON three times over)."""

    name = "polza"
    off = False

    def __init__(self, model: str, cost: float, broken: bool = False) -> None:
        self.model = self.label = model
        self.cost, self.broken, self.calls = cost, broken, 0
        self.inner = MockProvider({"*": {"facts": [], "series": [], "tables": []}}, model=model)

    def complete(self, messages, **kwargs):
        self.calls += 1
        usage = Usage(100, 20, self.cost)
        try:
            if self.broken:
                raise ProviderError(f"{self.model}: no valid completion after 3 attempts: invalid JSON")
            res = self.inner.complete(messages, **kwargs)
        except ProviderError as e:
            e.usage = usage  # type: ignore[attr-defined]
            raise
        res.usage = usage
        return res


BRIEF = """# Умные напоминания

В пилоте участвовали 12 400 сотрудников. Доля завершённых в срок задач выросла на 34%.

## Что сделали
Напоминание из чата превращает сообщение в задачу одним касанием. Умный срок предлагает дату по контексту.
"""


def test_every_variants_manifest_carries_the_rubles_of_the_generations_model_calls(simple_deck, tmp_path):
    # the whole path: the generation's recorder over the deadline over the chain; a call the main model failed (its
    # tokens billed) and the backup answered, a call both failed — every ruble lands in run_manifest.usage
    analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    main, backup = _Billed("qwen/qwen3.8-27b", 0.05, broken=True), _Billed("qwen/qwen3.6-27b", 0.25)
    chain = ChainProvider([main, backup])
    reg = ProviderRegistry(roles={"llm": chain, "vlm": chain})
    res = generate_variants(
        simple_deck, brief=parse_brief_text(BRIEF), strategies=["structured", "compact"], out_dir=tmp_path / "out",
        workspace_root=tmp_path / "ws", providers=reg, skills=SkillsRegistry.load(), use_vlm=False, audit=False,
        autofix=False, exports=[], render_images=False, writer=False, pictures=False,
    )
    assert main.calls > 0 and backup.calls > 0
    paid = round(0.05 * main.calls + 0.25 * backup.calls, 4)
    for v in res.variants:
        m = json.loads((v.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
        u = m["usage"]
        assert u["scope"] == "generation" and u["calls"] > 0 and u["failed"] > 0  # the backup's mock fails most schemas
        assert u["cost_rub"] == paid  # the failed calls' rubles too
        assert round(sum(b["cost_rub"] for b in u["by_skill"].values()), 4) == paid
        assert [x["model"] for x in m["providers"]["llm"]["chain"]] == ["qwen/qwen3.8-27b", "qwen/qwen3.6-27b"]
