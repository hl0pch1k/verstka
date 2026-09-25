import pytest
from pydantic import BaseModel

from verstka.providers.base import ChatMessage, ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.openai_compat import extract_json, to_openai_messages
from verstka.providers.registry import ProviderRegistry, expand_env


class Out(BaseModel):
    kind: str
    confidence: float


def test_mock_provider_parses_schema():
    p = MockProvider(responses={"classify": '{"kind": "cards", "confidence": 0.9}'})
    r = p.complete([ChatMessage(role="user", content="please classify this")], schema=Out)
    assert r.parsed.kind == "cards" and r.attempts == 1
    assert p.calls[0]["schema"] == "Out"


def test_mock_provider_default_and_missing():
    p = MockProvider(responses={"*": {"kind": "title", "confidence": 1.0}})
    assert p.complete([ChatMessage(role="user", content="anything")], schema=Out).parsed.kind == "title"
    with pytest.raises(ProviderError):
        MockProvider(responses={"x": "y"}).complete([ChatMessage(role="user", content="z")])


def test_extract_json_from_fences_and_prose():
    assert extract_json('Sure:\n```json\n{"a": 1}\n```')["a"] == 1
    assert extract_json('text {"a": {"b": 2}} tail')["a"]["b"] == 2
    assert extract_json('[{"x": "}"}]')[0]["x"] == "}"
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_images_become_image_url_parts():
    msgs = to_openai_messages([ChatMessage(role="user", content="look", images=[b"\x89PNG\r\n\x1a\n...."])])
    parts = msgs[0]["content"]
    assert parts[0]["type"] == "text" and parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_registry_loads_mock_backend(tmp_path):
    y = tmp_path / "models.yaml"
    y.write_text("roles:\n  llm: {backend: mock}\n  vlm: {backend: mock}\nlimits: {max_concurrency: 2}\n")
    reg = ProviderRegistry.from_yaml(y)
    assert reg.get("llm").name == "mock" and reg.limits.max_concurrency == 2
    with pytest.raises(ProviderError):
        reg.get("t2i")


def test_registry_builds_openai_compat_without_network(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "sk-test")
    cfg = {"roles": {"llm": {"backend": "openai_compat", "model": "qwen/qwen3.8-27b", "api_key": "${TEST_KEY}"}}}
    assert expand_env(cfg)["roles"]["llm"]["api_key"] == "sk-test"
    reg = ProviderRegistry.from_config(cfg)
    p = reg.get("llm")
    assert p.name == "openai_compat" and p.model == "qwen/qwen3.8-27b" and p.api_key == "sk-test"


def test_rate_limits_wait_per_minute_and_fail_fast_when_the_day_is_spent(monkeypatch):
    """Free model tiers (OpenRouter: 20 req/min, 50 req/day): a per-minute 429 is waited out without spending an
    attempt; a spent daily quota fails fast for every later call so the pipeline drops to its deterministic steps."""
    from verstka.providers import openai_compat as oc
    from verstka.providers.base import ChatMessage, ProviderError

    sleeps: list[float] = []
    monkeypatch.setattr(oc.time, "sleep", lambda s: sleeps.append(s))
    p = oc.OpenAICompatProvider(model="qwen/qwen3.8-27b:free", base_url="https://example.invalid/v1", api_key="sk-test-123456789", max_attempts=2)
    calls = {"n": 0}

    def minute_then_ok(messages, temperature, max_tokens, want_json, deadline=None):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise oc.RateLimited("429 rate limit exceeded: free-models-per-min", retry_after=30)
        return "ok", oc.Usage(1, 1)

    monkeypatch.setattr(p, "_call", minute_then_ok)
    assert p.complete([ChatMessage(role="user", content="hi")]).text == "ok"
    assert sleeps == [30, 30, 30] and calls["n"] == 4  # three waits, the two real attempts untouched

    def daily(messages, temperature, max_tokens, want_json, deadline=None):
        raise oc.RateLimited("429 Rate limit exceeded: free-models-per-day", daily=True)

    monkeypatch.setattr(p, "_call", daily)
    import pytest

    with pytest.raises(ProviderError):
        p.complete([ChatMessage(role="user", content="hi")])
    # the quota of the account's free models is spent (per pool since the fallback chain, not per account)
    assert oc.status.blocked(p.health)[0] == "quota"
    oc.status.reset()
    assert oc._rate_limit_info(RuntimeError("Error code: 429 - free-models-per-day")).daily
    assert not oc._rate_limit_info(RuntimeError("Error code: 429 - too many requests per minute")).daily
    assert oc._rate_limit_info(RuntimeError("Error code: 500")) is None


def test_json_mode_is_dropped_when_the_backend_garbles_it(monkeypatch):
    """Some hosts break structured output under response_format=json_object (OpenRouter free Qwen: values start with
    ': ', keys come back empty) while the same model answers clean JSON without it. The first invalid answer in JSON
    mode switches the provider to plain mode for the rest of the run; the schema is in the prompt anyway."""
    from verstka.providers import openai_compat as oc

    p = oc.OpenAICompatProvider(model="qwen/qwen3.8-27b:free", base_url="https://example.invalid/v1", api_key="sk-test-json")
    seen: list[bool] = []

    def garbled_in_json_mode(messages, temperature, max_tokens, want_json, deadline=None):
        json_mode = want_json and p.json_mode
        seen.append(json_mode)
        if json_mode:
            return '{"": "tip", "confidence": ": 0.9"}', oc.Usage(1, 1)
        return '{"kind": "tip", "confidence": 0.9}', oc.Usage(1, 1)

    monkeypatch.setattr(p, "_call", garbled_in_json_mode)
    res = p.complete([ChatMessage(role="user", content="classify")], schema=Out)
    assert res.parsed == Out(kind="tip", confidence=0.9) and res.attempts == 2
    assert p.complete([ChatMessage(role="user", content="again")], schema=Out).attempts == 1
    assert seen == [True, False, False]  # one wasted call per run, not per request
    assert ProviderRegistry.from_config({"roles": {"llm": {"model": "m", "api_key": "k", "json_mode": False}}}).get("llm").json_mode is False


def test_a_generation_deadline_bounds_waits_and_requests(monkeypatch):
    """≤5 minutes per deck whatever the backend: a registry bound to a deadline never waits out a 429 or starts a
    request past it; the planner then falls back to its deterministic steps."""
    import time as _time

    from verstka.providers import openai_compat as oc

    sleeps: list[float] = []
    monkeypatch.setattr(oc.time, "sleep", lambda s: sleeps.append(s))
    reg = ProviderRegistry.from_config({"roles": {"llm": {"model": "m", "base_url": "https://example.invalid/v1", "api_key": "sk-deadline"}}, "limits": {"time_budget_s": 90}})
    assert reg.limits.time_budget_s == 90
    inner = reg.get("llm")
    got: dict = {}

    def congested(messages, temperature, max_tokens, want_json, deadline=None):
        got["deadline"] = deadline
        raise oc.RateLimited("429 temporarily rate-limited upstream", retry_after=30)

    monkeypatch.setattr(inner, "_call", congested)
    bound = reg.with_deadline(_time.monotonic() + 10)
    assert bound.get("llm").model == "m" and reg.get("llm") is inner  # the shared registry stays unbound
    with pytest.raises(ProviderError, match="time budget"):
        bound.get("llm").complete([ChatMessage(role="user", content="hi")])
    assert sleeps == [] and got["deadline"] is not None  # no 30 s wait with 10 s left

    calls = {"n": 0}
    monkeypatch.setattr(inner, "_call", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    with pytest.raises(ProviderError, match="time budget"):
        reg.with_deadline(_time.monotonic() - 1).get("llm").complete([ChatMessage(role="user", content="hi")])
    assert calls["n"] == 0  # nothing is sent once the budget is spent
    with pytest.raises(ProviderError, match="time budget"):
        ProviderRegistry.mock({}).with_deadline(_time.monotonic() - 1).get("llm").complete([ChatMessage(role="user", content="hi")])


def test_upstream_congestion_fails_fast_instead_of_waiting_out_the_budget(monkeypatch):
    """OpenRouter's free Qwen «temporarily rate-limited upstream» is congestion on the host, not our per-minute cap:
    waiting 20 s six times per call spent two minutes of every deck and still got nothing. Two such answers in a
    row mark the endpoint congested for a while — every call fails at once and the deterministic steps take over."""
    from verstka.providers import openai_compat as oc
    from verstka.providers.base import ChatMessage, ProviderError

    sleeps: list[float] = []
    monkeypatch.setattr(oc.time, "sleep", lambda s: sleeps.append(s))
    p = oc.OpenAICompatProvider(model="qwen/qwen3.8-27b:free", base_url="https://example.invalid/v1", api_key="sk-congested-1", max_attempts=3)
    calls = {"n": 0}

    def congested(messages, temperature, max_tokens, want_json, deadline=None):
        calls["n"] += 1
        raise oc.RateLimited("Error code: 429 - qwen/qwen3.8-27b:free is temporarily rate-limited upstream", retry_after=None)

    monkeypatch.setattr(p, "_call", congested)
    with pytest.raises(ProviderError, match="congested"):
        p.complete([ChatMessage(role="user", content="hi")])
    assert calls["n"] == 2 and sum(sleeps) <= 10  # two tries and a short pause, not a minute of waiting
    with pytest.raises(ProviderError, match="congested"):
        p.complete([ChatMessage(role="user", content="again")])
    assert calls["n"] == 2  # the next call does not even knock
    assert oc._rate_limit_info(RuntimeError("Error code: 429 - temporarily rate-limited upstream")).upstream
    assert not oc._rate_limit_info(RuntimeError("Error code: 429 - rate limit exceeded: free-models-per-min")).upstream
    assert oc.status.blocked(p.health)[0] == "congested"  # the breaker is per (account, model) now
    oc.status.reset()
