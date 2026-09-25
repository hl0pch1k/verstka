"""A model answer cut off at max_tokens must never validate as an empty (all-default) answer: extract_json picks an
object holding a top-level field of the schema and nothing inside an object that never closes; the provider asks
once more, shorter and with more room, and never leaves the JSON mode for it. Hermetic: fake clients only."""

from __future__ import annotations

import json
from types import SimpleNamespace

import openai
import pytest
from pydantic import BaseModel

from verstka.providers import openai_compat as oc
from verstka.providers import status
from verstka.providers.base import ChatMessage, ProviderError
from verstka.providers.openai_compat import OpenAICompatProvider, TruncatedJSON, extract_json, schema_keys
from verstka.schemas.outline import FactsExtraction, PlannedDeck

FULL = {
    "facts": [{"id": "f1", "value": "12 400", "unit": "чел.", "label": "участники пилота"}, {"id": "f2", "value": "37", "label": "компаний"}],
    "series": [{"id": "s1", "name": "Выручка", "categories": ["Май", "Июнь"], "values": [1200, 3400]}],
    "tables": [],
}
GOOD = json.dumps(FULL, ensure_ascii=False)
CUT = GOOD[: GOOD.index('"series"') - 20]  # stops inside the second fact: the first fact is a complete inner object
MSGS = [ChatMessage(role="system", content="extract"), ChatMessage(role="user", content="brief text")]


def test_cut_off_answer_never_yields_an_inner_object():
    assert json.loads(CUT[CUT.index('{"id": "f1"') : CUT.index("}") + 1])["id"] == "f1"  # the trap is really there
    with pytest.raises(TruncatedJSON):
        extract_json(CUT, schema_keys(FactsExtraction))
    with pytest.raises(TruncatedJSON):
        extract_json(CUT)  # without the schema too: nothing inside an object that never closes
    with pytest.raises(TruncatedJSON):
        extract_json("```json\n" + CUT)  # an unclosed fence is no escape


def test_inner_object_with_a_top_level_key_is_not_the_answer():
    # a cut-off plan: the slide object has «title» like the deck — it must not pass for a deck without slides
    cut = '{"title": "Больше прибыли", "slides": [{"id": "s1", "kind": "cards", "headline": "Итоги", "title": "X"}, {"id": "s2", "kind": "bul'
    with pytest.raises(TruncatedJSON):
        extract_json(cut, schema_keys(PlannedDeck))


def test_complete_answers_still_parse():
    keys = schema_keys(FactsExtraction)
    assert extract_json(GOOD, keys) == FULL
    assert extract_json("Вот ответ:\n```json\n" + GOOD + "\n```", keys) == FULL
    assert extract_json("Ответ: " + GOOD + " — готово", keys) == FULL
    assert extract_json('{"result": ' + GOOD + "}", keys) == FULL  # a wrapper: the object inside it is the answer
    assert extract_json("{}", keys) == {}  # the whole answer «nothing found» is fine
    with pytest.raises(ValueError):
        extract_json('{"id": "f1", "value": "3"}', keys)  # an object of the wrong shape is not picked
    # the old behaviour without a schema is kept
    assert extract_json('text {"a": {"b": 2}} tail')["a"]["b"] == 2
    assert extract_json('[{"x": "}"}]')[0]["x"] == "}"


# ------------------------------------------------------------------ the provider


def answer(text: str, finish: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


class FakeClient:
    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    def no_network(*a, **k):
        pytest.fail("a test tried to build a real OpenAI client")

    monkeypatch.setattr(openai, "OpenAI", no_network)
    monkeypatch.setattr(oc, "_LIMITERS", {})
    monkeypatch.setattr(oc.time, "sleep", lambda s: None)
    status.reset()
    yield
    status.reset()


def provider(script: list, **kw) -> tuple[OpenAICompatProvider, FakeClient]:
    p = OpenAICompatProvider(model="qwen3.8-27b", base_url="https://vk.example.invalid/v1", api_key="vk-test-trunc-01", **kw)
    client = FakeClient(script)
    p._client = client
    return p, client


@pytest.mark.parametrize("finish", ["length", "stop"])
def test_cut_off_answer_is_asked_again_shorter_with_more_room(finish):
    p, client = provider([answer(CUT, finish), answer(GOOD)])
    res = p.complete(MSGS, schema=FactsExtraction, max_tokens=1800)
    assert [f.id for f in res.parsed.facts] == ["f1", "f2"] and len(res.parsed.series) == 1
    assert len(client.calls) == 2 and res.attempts == 1  # the retry of a cut-off answer is not an attempt
    first, second = client.calls
    assert first["max_tokens"] == 1800 and second["max_tokens"] == 3600
    # asked again from the start: the cut-off text is not sent back, the request says to be shorter
    assert all(m.get("content") != CUT for m in second["messages"])
    assert "cut off" in second["messages"][-1]["content"] and "shorter" in second["messages"][-1]["content"]
    # the host did no wrong: the JSON mode stays on
    assert p.json_mode and second.get("response_format") == {"type": "json_object"}


def test_room_is_capped_by_the_link():
    p, client = provider([answer(CUT, "length"), answer(GOOD)], max_tokens_cap=2000)
    p.complete(MSGS, schema=FactsExtraction, max_tokens=1800)
    assert [c["max_tokens"] for c in client.calls] == [1800, 2000]


def test_always_cut_off_fails_instead_of_returning_an_empty_answer():
    p, client = provider([answer(CUT, "length")])
    with pytest.raises(ProviderError) as e:
        p.complete(MSGS, schema=FactsExtraction, max_tokens=1000)
    assert "cut off" in str(e.value)
    # one extra request with twice the room; cut again, it fails at once: the attempts left would be cut too, each at
    # the most output any request of the run asks for
    assert len(client.calls) == 2
    assert [c["max_tokens"] for c in client.calls] == [1000, 2000]
    assert p.json_mode
    assert getattr(e.value, "usage", None) is not None and e.value.usage.completion_tokens == 100  # both bills travel


def test_hidden_reasoning_is_warned_once(caplog):
    long_bill = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=GOOD), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=5000),
    )
    p, client = provider([long_bill])
    with caplog.at_level("WARNING"):
        p.complete(MSGS, schema=FactsExtraction, max_tokens=8000)
        p.complete(MSGS, schema=FactsExtraction, max_tokens=8000)
    assert p.hidden_reasoning
    assert sum("thinking on" in r.getMessage() for r in caplog.records) == 1


def test_complete_json_with_finish_length_is_accepted():
    p, client = provider([answer(GOOD + "\n\n", "length")])
    res = p.complete(MSGS, schema=FactsExtraction, max_tokens=1000)
    assert len(res.parsed.facts) == 2 and len(client.calls) == 1


def test_wrong_shape_is_repaired_as_before():
    """An answer that is complete JSON of another shape goes the old way: the error is shown to the model."""

    class Out(BaseModel):
        kind: str
        confidence: float

    p, client = provider([answer('{"id": "x"}'), answer('{"kind": "cards", "confidence": 0.9}')])
    res = p.complete(MSGS, schema=Out, max_tokens=500)
    assert res.parsed.kind == "cards" and len(client.calls) == 2
    assert client.calls[1]["messages"][-2] == {"role": "assistant", "content": '{"id": "x"}'}


def test_a_host_that_rejects_the_thinking_switch_is_asked_without_it():
    """VK's config sends extra_body chat_template_kwargs.enable_thinking=false; a host that does not know the field
    (a plain 400) gets the same request without it, and the rest of the run goes without it."""

    class Rejecting(FakeClient):
        def create(self, **kwargs):
            self.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})
            if "extra_body" in kwargs:
                e = RuntimeError("Error code: 400 - Unrecognized request argument supplied: chat_template_kwargs")
                e.status_code = 400  # type: ignore[attr-defined]
                raise e
            return answer(GOOD)

    p = OpenAICompatProvider(model="qwen3.8-27b", base_url="https://vk.example.invalid/v1", api_key="vk-test-trunc-02", extra_body={"chat_template_kwargs": {"enable_thinking": False}}, json_mode=False)
    client = Rejecting([])
    p._client = client
    res = p.complete(MSGS, schema=FactsExtraction, max_tokens=1000)
    assert len(res.parsed.facts) == 2
    assert "extra_body" in client.calls[0] and "extra_body" not in client.calls[1]
    assert p.extra_body == {}
