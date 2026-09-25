"""Model providers: the single provider of the final (VK inference) keeps its pre-chain behaviour; a fallback chain of
models hands over from a link that cannot answer to the next one, with holds of its own per (account, model), a
last link that keeps a short pause, and one more pass when every link was only busy.
Hermetic: every link talks to a fake client; building a real OpenAI client fails the test."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from verstka.providers import openai_compat as oc
from verstka.providers import status
from verstka.providers.base import ChatMessage, ProviderError
from verstka.providers.chain import ChainProvider
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderRegistry

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://router.example.invalid/api/v1"
GROQ = "https://api.groq.com/openai/v1"
CLOUDRU = "https://foundation-models.api.cloud.ru/v1"
KEY = "sk-test-chain-00000001"
PAID, FREE = "qwen/qwen3.8-27b", "qwen/qwen3.8-27b:free"
GEMMA, GEMMA_MOE = "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free"
QWEN_VL = "qwen/qwen3-vl-30b-a3b-instruct"
QWEN32 = "Qwen/Qwen3-32B"
_REQ = httpx.Request("POST", "https://router.example.invalid/api/v1/chat/completions")
MSGS = [ChatMessage(role="user", content="classify this slide")]
GOOD = '{"kind": "cards", "confidence": 0.9}'
SNAPSHOT_FIELDS = {"model", "label", "host", "free", "state", "available", "until", "last_ok", "last_error", "roles"}


class Out(BaseModel):
    kind: str
    confidence: float


def http_error(code: int, message: str, headers: dict | None = None) -> openai.APIStatusError:
    return openai.APIStatusError(f"Error code: {code} - {message}", response=httpx.Response(code, request=_REQ, headers=headers or {}), body=None)


UPSTREAM = http_error(429, f"{FREE} is temporarily rate-limited upstream. Please retry shortly.")
NO_CREDITS = http_error(402, "Insufficient credits. This account never purchased credits.")
PER_MINUTE = http_error(429, "Rate limit exceeded: free-models-per-min.", headers={"retry-after": "30"})
PER_DAY = http_error(429, "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day")

# OpenRouter passes a host's 429 on inside an HTTP 200 body: «Provider returned error», the reason in metadata.raw
BODY_429 = SimpleNamespace(
    choices=None,
    usage=None,
    error={
        "code": 429,
        "message": "Provider returned error",
        "metadata": {"raw": f"{FREE} is temporarily rate-limited upstream. Please retry shortly.", "provider_name": "ModelRun"},
    },
)
TOO_LARGE = http_error(
    413,
    "Request too large for model `qwen/qwen3.8-27b` in organization `org_test` service tier `on_demand` on tokens per minute (TPM): "
    "Limit 8000, Requested 9120, please reduce your message size and try again.",
)


def answer(text: str = GOOD, prompt: int = 100, completion: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


class FakeClient:
    """Plays its script: each call takes the next item (the last one repeats); exceptions are raised, callables are
    called first (to act "while the request is in flight"). Without a script, any call fails the test — pytest.fail
    is a BaseException, so no `except Exception` of the provider or the chain can swallow it."""

    def __init__(self, script: list | None, name: str) -> None:
        self.script = list(script) if script is not None else None
        self.name = name
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if self.script is None:
            pytest.fail(f"{self.name} must not be called")
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages") or [])})  # as sent, before later repairs
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if callable(item):
            item = item()
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """No real sleeping, no real client, no limiter stamps from other tests, clean holds before and after."""

    def no_network(*a, **k):
        pytest.fail("a test tried to build a real OpenAI client")

    monkeypatch.setattr(openai, "OpenAI", no_network)
    monkeypatch.setattr(oc, "_LIMITERS", {})
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDRU_API_KEY", raising=False)
    slept: list[float] = []
    monkeypatch.setattr(oc.time, "sleep", lambda s: slept.append(s))  # the time module: the chain's pause as well
    status.reset()
    yield slept
    status.reset()


def registry(links: list, key: str = KEY, roles: tuple[str, ...] = ("llm",), **limits) -> ProviderRegistry:
    role = {"backend": "openai_compat", "base_url": BASE, "api_key": key, "json_mode": False, "chain": [x if isinstance(x, dict) else {"model": x} for x in links]}
    return ProviderRegistry.from_config({"roles": {r: dict(role) for r in roles}, "limits": limits})


def single(model: str = "qwen3.8-27b", base_url: str = "https://vk.example.invalid/v1", key: str = "vk-test-000001", **spec):
    return ProviderRegistry.from_config({"roles": {"llm": {"model": model, "base_url": base_url, "api_key": key, **spec}}}).get("llm")


def wire(provider, *by_index, **by_model) -> dict:
    """Give every link a fake client: scripts by position, or by model keyword (see s()); a link without a script
    must not be called. Returns the clients by model and by position."""
    clients: dict = {}
    for i, link in enumerate(getattr(provider, "links", [provider])):
        script = by_index[i] if i < len(by_index) else by_model.get(s(link.model))
        link._client = FakeClient(script, f"{link.label} [{i}]")
        clients[i] = link._client
        clients.setdefault(link.model, link._client)
    return clients


def s(model: str) -> str:
    """The keyword under which wire() finds a model's script."""
    return model.replace("/", "_").replace(":", "_").replace("-", "_").replace(".", "_")


# ---------------------------------------------------------------------------------------------- configuration


def test_a_single_spec_config_is_unchanged(sleeps):
    reg = ProviderRegistry.from_config({"roles": {"llm": {"model": PAID, "base_url": BASE, "api_key": KEY}}})
    p = reg.get("llm")
    assert isinstance(p, oc.OpenAICompatProvider) and p.json_mode is True
    assert reg.describe() == {"llm": {"backend": "openai_compat", "model": PAID}}
    # alone, a provider keeps its patience: one short pause on an upstream 429, then the answer
    c = wire(p, **{s(PAID): [UPSTREAM, answer("ok")]})
    assert p.complete(MSGS).text == "ok"
    assert len(c[PAID].calls) == 2 and sleeps == [5.0]
    # a one-link chain is a single provider as well
    assert isinstance(registry([FREE]).get("llm"), oc.OpenAICompatProvider)


def test_a_chain_config_builds_links_with_shared_defaults():
    reg = registry(
        [
            {"model": PAID, "label": "Qwen3.8-27B (OpenRouter)", "extra_body": {"reasoning": {"enabled": False}}},
            FREE,
            {"model": "qwen3.5:9b", "base_url": "http://localhost:11434/v1", "api_key": "ollama", "requests_per_minute": 0},
        ],
        requests_per_minute=18,
    )
    ch = reg.get("llm")
    assert isinstance(ch, ChainProvider) and ch.name == "chain" and ch.model == PAID
    assert [p.model for p in ch.links] == [PAID, FREE, "qwen3.5:9b"]
    assert ch.links[1].api_key == KEY and ch.links[1].base_url == BASE and ch.links[1].json_mode is False  # inherited
    assert ch.links[2].base_url.startswith("http://localhost") and ch.links[2]._limiter is None  # its own, no cap
    assert ch.links[0]._limiter.rpm == 18 and ch.links[1].extra_body == {}
    assert ch.api_key == KEY and not any(p.off for p in ch.links)
    d = reg.describe()["llm"]
    assert d["backend"] == "chain" and d["model"] == PAID
    assert [x["label"] for x in d["chain"]] == ["Qwen3.8-27B (OpenRouter)", "Qwen3.8-27B (бесплатно)", "Qwen3.5 9B (локально)"]
    bound = reg.with_deadline(time.monotonic() + 100)
    assert bound.get("llm").model == PAID and bound.describe()["llm"]["chain"] == d["chain"]
    with pytest.raises(ProviderError):
        registry([])
    with pytest.raises(ProviderError):
        registry([{"chain": [{"model": FREE}]}, FREE])


def test_a_call_to_a_link_without_a_script_fails_the_test():
    """The guard is a BaseException: neither the provider's nor the chain's `except` can turn it into a fallback."""
    ch = registry([FREE, GEMMA]).get("llm")
    wire(ch, **{s(GEMMA): [answer()]})  # the free Qwen has no script
    with pytest.raises(pytest.fail.Exception, match="must not be called"):
        ch.complete(MSGS)


# ---------------------------------------------------------------------------------------------- a single provider (the final)


@pytest.mark.parametrize(
    "error, state, phrase",
    [
        (NO_CREDITS, "no_credits", "no credits (402)"),
        (http_error(403, "Key limit exceeded"), "no_credits", "no credits (402)"),
        (http_error(401, "User not found."), "auth", "access refused (401/403)"),
        (http_error(403, "Forbidden"), "auth", "access refused (401/403)"),
        (http_error(404, "The model `qwen3.8-27b` does not exist"), "missing", "model not available (404)"),
    ],
)
def test_alone_a_402_401_403_404_is_reported_after_three_attempts_with_at_most_a_short_hold(sleeps, error, state, phrase):
    p = single()
    c = wire(p, [error])
    with pytest.raises(ProviderError, match="after 3 attempts") as ei:
        p.complete(MSGS)
    assert phrase in str(ei.value) and len(c[0].calls) == 3 and sleeps == [2, 4]  # backoff as before the chain
    hit = status.blocked(p.health)
    assert hit is not None and hit[0] == state and 50 < hit[2] <= 60  # never 10 or 30 minutes for the only model
    with pytest.raises(ProviderError, match="skipped for"):
        p.complete(MSGS)  # within that minute the model is not asked
    assert len(c[0].calls) == 3
    p.health.until = time.monotonic() - 1  # a minute later
    c[0].script = [answer("ok")]
    assert p.complete(MSGS).text == "ok" and p.health.state == "ok"


@pytest.mark.parametrize(
    "error",
    [http_error(502, "Bad gateway"), http_error(503, "Service unavailable"), openai.APITimeoutError(request=_REQ), openai.APIConnectionError(request=_REQ)],
)
def test_alone_5xx_timeouts_and_dropped_connections_get_three_attempts_and_no_hold(sleeps, error):
    p = single()
    c = wire(p, [error, error, answer("third")])
    assert p.complete(MSGS).text == "third" and len(c[0].calls) == 3 and sleeps == [2, 4]
    c[0].script = [error]
    for _ in range(2):  # two calls failing in a row (as two parallel variants would): still no hold
        with pytest.raises(ProviderError, match="after 3 attempts"):
            p.complete(MSGS)
        assert status.blocked(p.health) is None
    assert len(c[0].calls) == 9


def test_alone_congestion_gets_a_short_pause_and_two_in_a_row_skip_the_model_for_two_minutes(sleeps):
    p = single()
    c = wire(p, [UPSTREAM])
    with pytest.raises(ProviderError, match="congested upstream"):
        p.complete(MSGS)
    assert len(c[0].calls) == 2 and sleeps == [5.0]
    state, _, left = status.blocked(p.health)
    assert state == "congested" and 110 < left <= 120
    with pytest.raises(ProviderError, match="congested upstream"):
        p.complete(MSGS)
    assert len(c[0].calls) == 2  # the next call does not knock


def test_alone_the_budget_is_checked_before_an_upstream_429_is_counted(sleeps):
    """As before the chain: a 429 that finds no room to wait in the generation's budget is not a strike, so the next
    generation's first 429 still gets its short pause and one more try (not the 2-minute hold at once)."""
    p = single()
    c = wire(p, [UPSTREAM])
    with pytest.raises(ProviderError, match="time budget"):
        p.complete(MSGS, deadline=time.monotonic() + 8)  # a 5 s pause would leave less than one request's worth
    assert len(c[0].calls) == 1 and sleeps == [] and p.health.strikes == 0 and status.blocked(p.health) is None
    assert p.health.state == "congested"  # recorded for the UI, without a hold
    c[0].script = [UPSTREAM, answer("ok")]
    assert p.complete(MSGS, deadline=time.monotonic() + 200).text == "ok"
    assert len(c[0].calls) == 3 and sleeps == [5.0] and status.blocked(p.health) is None and p.health.strikes == 0


def test_alone_an_upstream_429_inside_a_200_answer_is_congestion_not_the_per_minute_cap(sleeps):
    p = single()
    c = wire(p, [BODY_429, answer("ok")])
    assert p.complete(MSGS).text == "ok" and len(c[0].calls) == 2 and sleeps == [5.0]  # not six 20 s waits
    c[0].script = [BODY_429]
    with pytest.raises(ProviderError, match="congested upstream"):
        p.complete(MSGS)
    assert status.blocked(p.health)[0] == "congested"


def test_alone_a_per_minute_cap_is_waited_out(sleeps):
    p = single(requests_per_minute=0)
    c = wire(p, [PER_MINUTE, answer("ok")])
    assert p.complete(MSGS).text == "ok" and sleeps == [30.0] and len(c[0].calls) == 2
    assert p.health.state == "ok"


def test_alone_a_413_too_large_per_minute_gets_its_attempts_on_every_call_and_no_hold(sleeps):
    """Alone, a per-minute state is never skipped (the pre-call check ignores it): a 413 must not show a pause that
    does not happen."""
    p = single(model=PAID, base_url=GROQ, key="gsk_test_000000000001")
    c = wire(p, [TOO_LARGE])
    with pytest.raises(ProviderError, match="after 3 attempts") as ei:
        p.complete(MSGS)
    assert len(c[0].calls) == 3 and sleeps == [2, 4]
    snap = status.health_dict(p.health)
    assert snap["state"] == "rate" and snap["available"] is True and snap["until"] is None
    # neither the error nor the status names a pause that does not happen
    assert "per-minute request cap" in str(ei.value) and "skipped" not in str(ei.value)
    assert "per-minute request cap" in snap["last_error"] and "skipped" not in snap["last_error"]
    assert status.blocked(p.health) is None and status.own_hold(p.health) is None
    with pytest.raises(ProviderError, match="after 3 attempts"):
        p.complete(MSGS)
    assert len(c[0].calls) == 6 and sleeps == [2, 4, 2, 4]  # the next call makes its own attempts, as the UI says


def test_the_vk_config_of_the_final_is_one_model_without_long_holds(sleeps, monkeypatch):
    monkeypatch.setenv("VK_INFERENCE_BASE_URL", "https://vk.example.invalid/v1")
    monkeypatch.setenv("VK_INFERENCE_API_KEY", "vk-test-000001")
    reg = ProviderRegistry.from_yaml(ROOT / "configs" / "models.vk.yaml")
    for role in ("llm", "vlm"):
        p = reg.get(role)
        assert isinstance(p, oc.OpenAICompatProvider) and p.model == "qwen3.8-27b" and p.max_attempts == 3
    p = reg.get("llm")
    c = wire(p, [http_error(401, "invalid api key")])
    with pytest.raises(ProviderError, match=r"access refused \(401/403\)"):
        p.complete(MSGS)
    assert len(c[0].calls) == 3 and status.blocked(p.health)[2] <= 60
    assert status.blocked(reg.get("vlm").health)[2] <= 60  # vlm shares the model's record: the same short hold


# ---------------------------------------------------------------------------------------------- fallbacks


def test_an_upstream_429_hands_over_at_once_and_two_in_a_row_open_the_hold(sleeps):
    ch = registry([FREE, GEMMA]).get("llm")
    c = wire(ch, **{s(FREE): [UPSTREAM], s(GEMMA): [answer()]})
    r = ch.complete(MSGS, schema=Out)
    assert r.model == GEMMA and r.parsed == Out(kind="cards", confidence=0.9) and r.label == "Gemma 4 31B (бесплатно)"
    assert sleeps == [] and len(c[FREE].calls) == 1  # no 5-8 s pause for a link that is not the last
    assert status.blocked(ch.links[0].health) is None  # one 429: the next call knocks again
    ch.complete(MSGS, schema=Out)
    assert len(c[FREE].calls) == 2
    state, reason, left = status.blocked(ch.links[0].health)
    assert state == "congested" and 110 < left <= 120 and "congested upstream" in reason
    ch.complete(MSGS, schema=Out)
    assert len(c[FREE].calls) == 2 and len(c[GEMMA].calls) == 3  # skipped without a request
    assert sleeps == []


def test_the_last_link_keeps_a_short_pause_and_one_more_try_on_congestion(sleeps):
    ch = registry([PAID, FREE]).get("llm")
    c = wire(ch, **{s(PAID): [NO_CREDITS], s(FREE): [UPSTREAM, answer("free")]})
    r = ch.complete(MSGS)
    assert r.model == FREE and r.text == "free" and len(c[FREE].calls) == 2 and sleeps == [5.0]


def test_402_moves_on_and_the_paid_link_is_retried_after_ten_minutes():
    ch = registry([PAID, FREE]).get("llm")
    c = wire(ch, **{s(PAID): [NO_CREDITS, answer("paid")], s(FREE): [answer("free")]})
    assert ch.complete(MSGS).model == FREE
    state, reason, left = status.blocked(ch.links[0].health)
    assert state == "no_credits" and 590 < left <= 600 and "no credits (402)" in reason
    assert ch.complete(MSGS).text == "free" and len(c[PAID].calls) == 1  # skipped instantly
    ch.links[0].health.until = time.monotonic() - 1  # ten minutes later — the account was topped up meanwhile
    r = ch.complete(MSGS)
    assert r.model == PAID and r.text == "paid" and ch.links[0].health.state == "ok"


@pytest.mark.parametrize(
    "error, state, phrase, hold",
    [
        (http_error(404, "No endpoints found for google/gemma-4-31b-it:free."), "missing", "model not available (404)", 1800),
        (http_error(400, "google/gemma-9-99b is not a valid model ID"), "missing", "model not available (404)", 1800),
        (http_error(401, "User not found."), "auth", "access refused (401/403)", 1800),
        (http_error(403, "Forbidden"), "auth", "access refused (401/403)", 1800),
        (http_error(403, "Key limit exceeded (spending limit of this key)"), "no_credits", "no credits (402)", 600),
        (http_error(403, "Key limit exceeded (total limit)"), "no_credits", "no credits (402)", 600),
        (http_error(403, "Rate limit exceeded"), "auth", "access refused (401/403)", 1800),
        (http_error(502, "Bad gateway"), "congested", "congested upstream", 0),
        (http_error(503, "Service unavailable"), "congested", "congested upstream", 0),
        (openai.APITimeoutError(request=_REQ), "congested", "congested upstream", 60),
        (openai.APIConnectionError(request=_REQ), "error", "connection error", 0),
    ],
)
def test_an_unavailable_link_hands_over_to_the_next_one(sleeps, error, state, phrase, hold):
    reg = registry([GEMMA, GEMMA_MOE])
    ch = reg.get("llm")
    c = wire(ch, **{s(GEMMA): [error], s(GEMMA_MOE): [answer()]})
    r = ch.complete(MSGS, schema=Out)
    assert r.model == GEMMA_MOE and len(c[GEMMA].calls) == 1 and sleeps == []
    snap = {x["model"]: x for x in status.snapshot(reg)}
    assert snap[GEMMA]["state"] == state and phrase in snap[GEMMA]["last_error"] and snap[GEMMA_MOE]["state"] == "ok"
    hit = status.blocked(ch.links[0].health)
    if hold:
        assert hit is not None and hold - 10 < hit[2] <= hold
    else:
        assert hit is None  # one 5xx / dropped connection: tried again next call; two in a row open the hold
        ch.complete(MSGS, schema=Out)
        assert status.blocked(ch.links[0].health)[2] > 50


def test_an_error_inside_a_200_answer_moves_on():
    ch = registry([FREE, GEMMA]).get("llm")
    wire(ch, **{s(FREE): [SimpleNamespace(choices=None, error={"code": 502, "message": "Upstream error from ModelRun"}, usage=None)], s(GEMMA): [answer("ok")]})
    assert ch.complete(MSGS).model == GEMMA
    assert "502" in ch.links[0].health.last_error and ch.links[0].health.state == "congested"


def test_an_upstream_429_inside_a_200_answer_keeps_its_upstream_marker(sleeps):
    reg = registry([FREE, GEMMA])
    ch = reg.get("llm")
    c = wire(ch, **{s(FREE): [BODY_429], s(GEMMA): [answer("gemma")]})
    assert ch.complete(MSGS).model == GEMMA and len(c[GEMMA].calls) == 1 and sleeps == []
    snap = {x["model"]: x for x in status.snapshot(reg)}
    assert snap[FREE]["state"] == "congested" and snap[GEMMA]["state"] == "ok" and snap[GEMMA]["available"]
    assert "temporarily rate-limited upstream" in snap[FREE]["last_error"] and "ModelRun" in snap[FREE]["last_error"]
    assert "per-minute" not in snap[FREE]["last_error"]  # the free pool is not blocked as the account's cap
    # the same body as the SDK builds it (the error is an extra field of ChatCompletion)
    sdk = openai.types.chat.ChatCompletion.model_validate(
        {"id": "gen-1", "choices": [], "created": 0, "model": FREE, "object": "chat.completion", "error": BODY_429.error}
    )
    err = oc.classify_error(oc._body_error(sdk), FREE)
    assert isinstance(err, oc.RateLimited) and err.upstream and not err.daily
    # «Provider returned error» on a 429 is the host's limit even without the word «upstream»; the account's caps are not
    assert oc._rate_limit_info(http_error(429, "Provider returned error: Resource has been exhausted")).upstream
    assert not oc._rate_limit_info(http_error(429, "Provider returned error: Rate limit exceeded: free-models-per-min.")).upstream


@pytest.mark.parametrize(
    "text, state",
    [
        ("Key limit exceeded", "no_credits"),
        ("Key limit exceeded (total limit)", "no_credits"),
        ("This key's spending limit is reached", "no_credits"),
        ("Credit limit reached for this key", "no_credits"),
        ("Insufficient balance", "no_credits"),
        # a rate limit on a 403 is no empty account: it stays the 403 it is, never «top up the account»
        ("Rate limit exceeded", "auth"),
        ("quota limit exceeded for requests per minute", "auth"),
        ("Request limit exceeded", "auth"),
    ],
)
def test_only_key_spending_or_credit_wording_makes_a_403_no_credits(text, state):
    err = oc.classify_error(http_error(403, text), PAID)
    assert isinstance(err, oc.LinkUnavailable) and err.state == state
    assert ("no credits" in str(err)) is (state == "no_credits")


def test_groq_413_request_too_large_per_minute_is_a_short_rate_hold(sleeps):
    err = oc.classify_error(TOO_LARGE, PAID)
    assert isinstance(err, oc.LinkUnavailable) and err.state == "rate" and 0 < err.hold_s < 90
    assert "per-minute request cap" in str(err) and "skipped" not in str(err)  # the hold is named where it opens
    plain = oc.classify_error(http_error(413, "Payload too large"), PAID)
    assert type(plain) is ProviderError  # a 413 without the per-minute limit is a plain error
    reg = registry([{"model": PAID, "base_url": GROQ, "api_key": "gsk_test_000000000001"}, GEMMA])
    ch = reg.get("llm")
    c = wire(ch, [TOO_LARGE], [answer("gemma")])
    assert ch.complete(MSGS).model == GEMMA and len(c[0].calls) == 1 and sleeps == []
    groq = status.snapshot(reg)[0]
    assert groq["state"] == "rate" and not groq["available"] and 20 < groq["until"] <= 30
    assert "per-minute request cap" in groq["last_error"] and "(413), skipped for 30 s (" in groq["last_error"]
    ch.complete(MSGS)
    assert len(c[0].calls) == 1  # skipped during the short hold, Gemma answers


def test_invalid_json_after_the_links_own_attempts_moves_on():
    ch = registry([FREE, GEMMA]).get("llm")
    c = wire(ch, **{s(FREE): [answer("Sorry, I cannot help with that.")], s(GEMMA): [answer()]})
    r = ch.complete(MSGS, schema=Out)
    assert r.model == GEMMA and r.parsed.kind == "cards"
    assert len(c[FREE].calls) == 3  # its own repair attempts first
    assert len(c[GEMMA].calls[0]["messages"]) == len(c[FREE].calls[0]["messages"])  # the next link starts clean
    assert r.usage.prompt_tokens == 400 and r.usage.completion_tokens == 80  # the wasted answers are billed too
    assert ch.links[0].health.state == "ok"  # the model answered: reachable, just wrong


def test_every_link_failed_raises_one_error_that_names_each_of_them(sleeps):
    reg = registry([PAID, FREE, GEMMA])
    ch = reg.get("llm")
    wire(ch, **{s(PAID): [NO_CREDITS], s(FREE): [UPSTREAM], s(GEMMA): [http_error(404, "No endpoints found")]})
    with pytest.raises(ProviderError, match="all model links failed") as ei:
        ch.complete(MSGS, schema=Out)
    msg = str(ei.value)
    assert PAID in msg and FREE in msg and GEMMA in msg
    assert "no credits (402)" in msg and "congested upstream" in msg and "model not available (404)" in msg
    # the 402 and the 404 are on hold, the free Qwen was only busy: one more pass, which skips the held links
    assert len(sleeps) == 1 and 3.0 <= sleeps[0] <= 5.0 and "again: " in msg
    # every failed link is named by its label (the one the status shows), in brackets before its own message
    labels = [x["label"] for x in status.snapshot(reg)]
    assert labels[1:] == ["Qwen3.8-27B (бесплатно)", "Gemma 4 31B (бесплатно)"]
    parts = msg[len("all model links failed: "):].split("; ")
    assert parts[0].startswith(f"[{labels[0]}] {PAID}: no credits (402)")
    assert parts[1].startswith(f"[{labels[1]}] {FREE}: congested upstream")
    assert parts[2].startswith(f"[{labels[2]}] {GEMMA}: model not available (404)")
    assert any(x.startswith(f"again: [{labels[1]}] ") for x in parts[3:])
    assert [(f["label"], f["state"], f["pass"]) for f in ei.value.failed][:3] == [(labels[0], "no_credits", 1), (labels[1], "congested", 1), (labels[2], "missing", 1)]
    assert [len(c.calls) for c in (ch.links[0]._client, ch.links[1]._client, ch.links[2]._client)] == [1, 2, 1]


def test_mock_links_work_in_a_chain():
    ch = ChainProvider([MockProvider({"nothing": "x"}, model="m1"), MockProvider({"*": GOOD}, model="m2")])
    assert ch.complete(MSGS, schema=Out).model == "m2"


# ---------------------------------------------------------------------------------------------- second pass


def test_a_second_pass_after_a_short_pause_when_every_link_was_only_busy(sleeps):
    ch = registry([FREE, GEMMA]).get("llm")
    c = wire(ch, **{s(FREE): [UPSTREAM, answer("second pass")], s(GEMMA): [http_error(502, "Bad gateway")]})
    r = ch.complete(MSGS)
    assert r.model == FREE and r.text == "second pass"
    # the last link: 502, backoff 2 s, 502 again (two in a row: held 60 s); then one jittered 3-5 s pause
    assert len(c[GEMMA].calls) == 2 and sleeps[0] == 2 and len(sleeps) == 2 and 3.0 <= sleeps[1] <= 5.0
    assert len(c[FREE].calls) == 2 and len(c[GEMMA].calls) == 2  # Gemma is on hold: not asked in the second pass


def test_a_per_minute_cap_counts_as_busy_for_the_second_pass(sleeps):
    ch = registry([{"model": FREE, "requests_per_minute": 0}, {"model": PAID, "requests_per_minute": 0}]).get("llm")
    c = wire(ch, **{s(FREE): [UPSTREAM, answer("free")], s(PAID): [PER_MINUTE]})
    assert ch.complete(MSGS).text == "free" and len(sleeps) == 1 and 3.0 <= sleeps[0] <= 5.0
    assert len(c[PAID].calls) == 1  # the paid pool's minute window is still open: skipped in the second pass


def test_a_second_pass_also_runs_while_the_402_and_404_links_are_on_hold(sleeps):
    ch = registry([PAID, FREE, GEMMA, GEMMA_MOE]).get("llm")
    c = wire(
        ch,
        **{
            s(PAID): [NO_CREDITS],
            s(FREE): [UPSTREAM, answer("second pass")],
            s(GEMMA): [http_error(404, "No endpoints found for google/gemma-4-31b-it:free.")],
            s(GEMMA_MOE): [http_error(503, "Service unavailable")],
        },
    )
    r = ch.complete(MSGS)
    assert r.model == FREE and r.text == "second pass"
    # the last link's backoff, then the jittered pause; the paid and the Gemma 31B links are skipped in pass 2
    assert sleeps[0] == 2 and len(sleeps) == 2 and 3.0 <= sleeps[1] <= 5.0
    assert [len(c[m].calls) for m in (PAID, FREE, GEMMA, GEMMA_MOE)] == [1, 2, 1, 2]


def test_the_default_config_makes_its_second_pass_without_credits(config_env, sleeps):
    """The user's current state: the paid Qwen answers 402, Groq and Cloud.ru have no key, the free links are busy."""
    ch = ProviderRegistry.from_yaml(ROOT / "configs" / "models.yaml").get("llm")
    c = wire(ch, [NO_CREDITS], None, [UPSTREAM, answer("free qwen")], None, None, [UPSTREAM], [http_error(502, "Bad gateway")])
    r = ch.complete(MSGS)
    assert r.model == FREE and r.text == "free qwen" and len(sleeps) == 2 and 3.0 <= sleeps[1] <= 5.0
    assert [len(c[i].calls) for i in range(7)] == [1, 0, 2, 0, 0, 1, 2]


def test_no_second_pass_after_a_real_failure_short_budget_or_when_every_link_is_on_hold(sleeps):
    # a 402 on hold, and the last link held after its second upstream 429: nothing is free after the pause
    ch = registry([PAID, FREE]).get("llm")
    c = wire(ch, **{s(PAID): [NO_CREDITS], s(FREE): [UPSTREAM]})
    with pytest.raises(ProviderError, match="all model links failed"):
        ch.complete(MSGS)
    assert sleeps == [5.0] and len(c[PAID].calls) == 1 and len(c[FREE].calls) == 2
    status.reset()
    sleeps.clear()
    # a failure that opens no hold (invalid JSON after the link's own attempts) would only repeat: no second pass
    ch = registry([FREE, GEMMA]).get("llm")
    c = wire(ch, **{s(FREE): [UPSTREAM], s(GEMMA): [answer("Sorry, I cannot help with that.")]})
    with pytest.raises(ProviderError, match="all model links failed"):
        ch.complete(MSGS, schema=Out)
    assert sleeps == [] and len(c[FREE].calls) == 1 and len(c[GEMMA].calls) == 3
    status.reset()
    sleeps.clear()
    # a plain 4xx of a link that is not the last (no hold) rules it out as well
    ch = registry([GEMMA, FREE]).get("llm")
    c = wire(ch, **{s(GEMMA): [http_error(400, "Bad request: unsupported parameter")], s(FREE): [http_error(502, "Bad gateway")]})
    with pytest.raises(ProviderError, match="all model links failed"):
        ch.complete(MSGS)
    assert sleeps == [2] and len(c[GEMMA].calls) == 1 and len(c[FREE].calls) == 2
    status.reset()
    sleeps.clear()
    # less than 30 s of the budget left
    reg = registry([GEMMA, GEMMA_MOE])
    c = wire(reg.get("llm"), **{s(GEMMA): [UPSTREAM], s(GEMMA_MOE): [http_error(503, "Service unavailable")]})
    with pytest.raises(ProviderError, match="all model links failed"):
        reg.with_deadline(time.monotonic() + 25).get("llm").complete(MSGS)
    assert sleeps == [2] and len(c[GEMMA].calls) == 1
    status.reset()
    sleeps.clear()
    # both links are on hold after the first pass: a pause would only lead to skipping them
    ch = registry([FREE, GEMMA]).get("llm")
    c = wire(ch, **{s(FREE): [UPSTREAM], s(GEMMA): [UPSTREAM]})
    ch.links[0].health.strikes = 1  # the free Qwen was congested on the previous call already
    with pytest.raises(ProviderError, match="congested upstream"):
        ch.complete(MSGS)
    assert sleeps == [5.0]  # only the last link's short pause
    assert status.blocked(ch.links[0].health)[0] == "congested" and status.blocked(ch.links[1].health)[0] == "congested"


# ---------------------------------------------------------------------------------------------- holds and pools


def test_congestion_of_one_model_does_not_block_another_model_on_the_same_account():
    ch = registry([FREE, GEMMA]).get("llm")
    wire(ch, **{s(FREE): [UPSTREAM], s(GEMMA): [answer("gemma")]})
    ch.complete(MSGS)
    ch.complete(MSGS)
    assert status.blocked(ch.links[0].health)[0] == "congested"
    assert status.blocked(ch.links[1].health) is None
    # a separate provider of Gemma on the very same key is not blocked either (the old mark was per account)
    alone = ProviderRegistry.from_config({"roles": {"llm": {"model": GEMMA, "base_url": BASE, "api_key": KEY}}}).get("llm")
    c = wire(alone, **{s(GEMMA): [answer("alone")]})
    assert alone.complete(MSGS).text == "alone" and len(c[GEMMA].calls) == 1


def test_an_upstream_429_with_a_long_retry_after_is_congestion_not_the_daily_quota(sleeps):
    reg = registry([FREE, GEMMA])
    ch = reg.get("llm")
    long_wait = http_error(429, f"{FREE} is temporarily rate-limited upstream.", headers={"retry-after": "600"})
    c = wire(ch, **{s(FREE): [long_wait], s(GEMMA): [answer("gemma")]})
    assert ch.complete(MSGS).model == GEMMA and len(c[GEMMA].calls) == 1  # Gemma (same free pool) is still asked
    assert {x["model"]: x["state"] for x in status.snapshot(reg)} == {FREE: "congested", GEMMA: "ok"}
    assert not oc._rate_limit_info(long_wait).daily
    assert oc._rate_limit_info(http_error(429, "Rate limit exceeded", headers={"retry-after": "600"})).daily  # no upstream marker
    assert oc._rate_limit_info(http_error(429, "Rate limit reached on tokens per day (TPD): Limit 200000")).daily  # Groq


def test_the_free_daily_quota_blocks_the_free_models_of_the_key_but_not_the_paid_one():
    reg = registry([FREE, GEMMA, PAID])
    ch = reg.get("llm")
    c = wire(ch, **{s(FREE): [PER_DAY], s(PAID): [answer("paid")]})
    r = ch.complete(MSGS)
    assert r.model == PAID and len(c[FREE].calls) == 1 and len(c[GEMMA].calls) == 0  # Gemma is free too: not asked
    snap = {x["model"]: x for x in status.snapshot(reg)}
    assert snap[FREE]["state"] == "quota" and snap[GEMMA]["state"] == "quota" and snap[PAID]["state"] == "ok"
    assert snap[FREE]["until"] > 60 and not snap[GEMMA]["available"] and snap[PAID]["available"]
    assert "daily request quota" in snap[FREE]["last_error"] and "daily request quota" in snap[GEMMA]["last_error"]
    ch.complete(MSGS)
    assert len(c[FREE].calls) == 1 and len(c[PAID].calls) == 2
    # another key is another account: its free models are not blocked
    other = registry([GEMMA], key="sk-test-chain-00000002").get("llm")
    assert status.blocked(other.health) is None


def test_a_per_minute_cap_inside_a_chain_skips_the_free_links_of_the_key_without_waiting(sleeps):
    reg = registry([FREE, GEMMA, PAID])
    ch = reg.get("llm")
    c = wire(ch, **{s(FREE): [PER_MINUTE], s(PAID): [answer("paid")]})
    assert ch.complete(MSGS).model == PAID and sleeps == [] and len(c[GEMMA].calls) == 0
    state, reason, left = status.blocked(ch.links[0].health)
    assert state == "rate" and 20 < left <= 30 and "per-minute request cap" in reason
    snap = {x["model"]: x for x in status.snapshot(reg)}
    assert snap[GEMMA]["state"] == "rate" and 20 < snap[GEMMA]["until"] <= 30 and snap[PAID]["state"] == "ok"
    assert "daily" not in snap[FREE]["last_error"]  # never shown as the daily quota


def test_the_minute_limiter_inside_a_chain_skips_the_link_instead_of_waiting(sleeps):
    reg = registry([{"model": FREE, "requests_per_minute": 1}, {"model": GEMMA, "requests_per_minute": 0}])
    ch = reg.get("llm")
    c = wire(ch, **{s(FREE): [answer("free")], s(GEMMA): [answer("gemma")]})
    assert ch.complete(MSGS).text == "free"
    assert ch.complete(MSGS).text == "gemma" and sleeps == [] and len(c[FREE].calls) == 1  # no slot: skipped, no request
    free = status.snapshot(reg)[0]
    assert free["state"] == "rate" and not free["available"] and 50 < free["until"] <= 61
    assert "per-minute request cap" in free["last_error"]


# ---------------------------------------------------------------------------------------------- links without a key


def test_a_link_without_a_key_is_off_and_skipped_silently(sleeps):
    reg = registry([{"model": PAID, "api_key": ""}, GEMMA, GEMMA_MOE])
    ch = reg.get("llm")
    assert ch.links[0].off and not ch.links[1].off
    c = wire(ch, **{s(GEMMA): [answer("gemma")]})  # the paid link has no script: a request would fail the test
    assert ch.complete(MSGS).text == "gemma" and sleeps == []
    snap = status.snapshot(reg)
    assert snap[0]["state"] == "off" and snap[0]["available"] is False and snap[0]["until"] is None
    assert snap[0]["last_error"] == "not configured (no API key)"
    status.reset()
    assert status.snapshot(reg)[0]["state"] == "off"  # a reset forgets holds, not the missing key
    c[GEMMA].script = [http_error(404, "No endpoints found")]
    c[1].script = [http_error(404, "No endpoints found")]
    c[2].script = [http_error(404, "No endpoints found")]
    with pytest.raises(ProviderError, match="all model links failed") as ei:
        ch.complete(MSGS)
    assert "not configured" not in str(ei.value) and "qwen" not in str(ei.value)  # the off link is not an error
    # every link off: one clear error, no request
    off = registry([{"model": PAID, "api_key": ""}, {"model": GEMMA, "api_key": ""}]).get("llm")
    wire(off)
    with pytest.raises(ProviderError, match=r"not configured \(no API key\)"):
        off.complete(MSGS)
    assert off.api_key == ""


def test_the_chain_is_named_after_its_first_link_with_a_key(config_env):
    reg = registry([{"model": PAID, "base_url": GROQ, "api_key": "", "label": "Qwen3.8-27B (Groq)"}, GEMMA, GEMMA_MOE])
    ch = reg.get("llm")
    assert ch.model == GEMMA and ch.label == "Gemma 4 31B (бесплатно)"
    assert reg.describe()["llm"]["model"] == GEMMA and reg.with_deadline(time.monotonic() + 60).get("llm").model == GEMMA
    free = ProviderRegistry.from_yaml(ROOT / "configs" / "models.free.yaml").get("llm")  # no GROQ_API_KEY
    assert free.model == FREE and free.label == "Qwen3.8-27B (бесплатно)"
    off = registry([{"model": PAID, "api_key": ""}, {"model": GEMMA, "api_key": ""}]).get("llm")
    assert off.model == PAID  # every link off: the first one names the chain


def test_a_chain_with_one_live_link_behaves_as_a_single_provider(sleeps):
    vk = {"model": "qwen3.8-27b", "base_url": "https://vk.example.invalid/v1", "api_key": "vk-test-000001"}
    reg = registry([vk, {"model": PAID, "base_url": GROQ, "api_key": ""}])  # a key-gated backup without its key
    ch = reg.get("llm")
    assert isinstance(ch, ChainProvider) and ch.model == "qwen3.8-27b"
    c = wire(ch, [http_error(401, "invalid api key")])
    with pytest.raises(ProviderError, match="after 3 attempts"):
        ch.complete(MSGS)
    assert len(c[0].calls) == 3 and sleeps == [2, 4]  # its own attempts and backoff
    assert status.blocked(ch.links[0].health)[2] <= 60  # at most the short hold, never 30 minutes
    status.reset()
    sleeps.clear()
    c[0].script = [UPSTREAM, answer("ok")]
    assert ch.complete(MSGS).text == "ok" and sleeps == [5.0]  # the short pause, not a hand-over
    c[0].script = [PER_MINUTE, answer("waited")]
    ch.links[0]._limiter = None
    assert ch.complete(MSGS).text == "waited" and sleeps == [5.0, 30.0]  # a per-minute cap is waited out


def test_a_key_from_an_unset_variable_makes_the_link_off(monkeypatch):
    spec = {"model": PAID, "base_url": GROQ, "api_key": "${GROQ_API_KEY}"}
    reg = registry([spec, GEMMA])
    assert reg.get("llm").links[0].off
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_000000000001")
    assert not registry([spec, GEMMA]).get("llm").links[0].off


def test_a_single_provider_without_a_key_says_so_at_once(sleeps):
    p = single(key="")
    wire(p)
    with pytest.raises(ProviderError, match=r"not configured \(no API key\)"):
        p.complete(MSGS)
    assert sleeps == [] and status.snapshot(ProviderRegistry(roles={"llm": p}))[0]["state"] == "off"


# ---------------------------------------------------------------------------------------------- per-link options


def test_max_tokens_cap_limits_every_request_of_the_link():
    ch = registry([{"model": PAID, "base_url": GROQ, "api_key": "gsk_test_000000000001", "max_tokens_cap": 3000, "extra_body": {"reasoning_effort": "none"}}, GEMMA]).get("llm")
    c = wire(ch, [answer("groq")])
    assert ch.complete(MSGS, max_tokens=4096).text == "groq"
    assert ch.complete(MSGS, max_tokens=1000).text == "groq"
    assert [x["max_tokens"] for x in c[0].calls] == [3000, 1000]
    assert c[0].calls[0]["extra_body"] == {"reasoning_effort": "none"}
    assert ch.links[1].max_tokens_cap is None


def test_an_inline_think_block_is_dropped_before_parsing():
    p = single(model=QWEN32, base_url=CLOUDRU, key="cloudru-test-0001")
    wire(p, [answer("<think>\nThe user wants {a plan}...\n</think>\n\n" + GOOD)])
    assert p.complete(MSGS, schema=Out).parsed == Out(kind="cards", confidence=0.9)


def test_the_system_suffix_is_sent_only_by_its_own_link():
    cloudru = {"model": QWEN32, "base_url": CLOUDRU, "api_key": "cloudru-test-0001", "system_suffix": "/no_think"}
    ch = registry([cloudru, GEMMA]).get("llm")
    assert ch.links[0].system_suffix == "/no_think" and ch.links[1].system_suffix is None
    c = wire(ch, [http_error(502, "Bad gateway"), answer("<think>\n\n</think>\n\n" + GOOD)], [answer()])
    assert ch.complete(MSGS, schema=Out).model == GEMMA
    sent = c[0].calls[0]["messages"]
    assert sent[-1]["role"] == "system" and sent[-1]["content"].endswith("\n/no_think") and "JSON schema" in sent[-1]["content"]
    assert sum("/no_think" in str(m["content"]) for m in sent) == 1
    assert not any("/no_think" in str(m["content"]) for m in c[1].calls[0]["messages"])  # not Gemma's
    # without a system message of its own, the switch comes first; the empty think block is dropped from the answer
    r = ch.complete(MSGS, schema=Out)
    assert r.model == QWEN32 and r.parsed == Out(kind="cards", confidence=0.9)
    plain = registry([cloudru, GEMMA]).get("llm")
    c = wire(plain, [answer("<think>\n\n</think>\n\nready")])
    assert plain.complete(MSGS).text == "ready"
    assert c[0].calls[0]["messages"][0] == {"role": "system", "content": "/no_think"} and c[0].calls[0]["messages"][1]["role"] == "user"
    assert MSGS[0].content == "classify this slide"  # the caller's messages are not changed


# ---------------------------------------------------------------------------------------------- deadline


def test_the_generation_deadline_is_respected():
    reg = registry([PAID, FREE])
    ch = reg.get("llm")
    c = wire(ch, **{s(PAID): [NO_CREDITS], s(FREE): [answer("free")]})
    with pytest.raises(ProviderError, match="time budget"):
        reg.with_deadline(time.monotonic() + 3).get("llm").complete(MSGS)  # less than one request's worth left
    assert len(c[PAID].calls) == 0 and len(c[FREE].calls) == 0
    r = reg.with_deadline(time.monotonic() + 40).get("llm").complete(MSGS)
    assert r.model == FREE and c[FREE].calls[0]["timeout"] <= 40  # the next link gets what is left, not 120 s
    assert reg.get("llm") is ch  # the shared registry stays unbound


def test_a_timeout_cut_short_by_the_generations_deadline_is_not_the_links_fault(sleeps):
    reg = registry([FREE, GEMMA])
    c = wire(reg.get("llm"), **{s(FREE): [openai.APITimeoutError(request=_REQ)], s(GEMMA): [answer("gemma")]})
    r = reg.with_deadline(time.monotonic() + 20).get("llm").complete(MSGS)
    assert r.model == GEMMA and c[FREE].calls[0]["timeout"] <= 20
    h = reg.get("llm").links[0].health
    assert status.blocked(h) is None and h.state == "unknown" and h.last_error == ""  # nothing recorded
    # the link's own timeout (not cut by the budget) is the host's: a link that is not the last is held 60 s
    reg.get("llm").complete(MSGS)
    assert status.blocked(h)[0] == "congested" and 50 < status.blocked(h)[2] <= 60


# ---------------------------------------------------------------------------------------------- "in a row"


def test_failures_that_started_before_the_last_answer_do_not_count_in_a_row():
    h = status.link("test-acc|m-in-a-row", "m", "M", "test-acc|paid")
    started = time.monotonic() - 0.001
    status.record_ok(h)  # another call answered while this request was in flight
    n, hold = status.fail(h, "congested", "429 upstream", counter="strikes", threshold=2, hold_s=120, started=started)
    assert (n, hold, h.state, h.strikes) == (0, 0.0, "ok", 0)
    after = time.monotonic()
    assert status.fail(h, "congested", "429 upstream", counter="strikes", hold_s=120, started=after) == (1, 0.0)
    n, hold = status.fail(h, "congested", "429 upstream", counter="strikes", hold_s=120, started=after)
    assert (n, hold, h.state) == (2, 120, "congested")


def test_parallel_failures_are_counted_and_decided_under_one_lock():
    h = status.link("test-acc|m-parallel", "m", "M", "test-acc|paid")
    started = time.monotonic()
    holds: list[float] = []
    barrier = threading.Barrier(8)

    def fail_once():
        barrier.wait()
        holds.append(status.fail(h, "congested", "503", counter="transient", threshold=2, hold_s=60, started=started)[1])

    threads = [threading.Thread(target=fail_once) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert h.transient == 8 and sorted(holds).count(0.0) == 1  # the first failure alone opens no hold


def test_a_longer_hold_keeps_its_own_state_and_reason():
    h = status.link("test-acc|m-consistent", "m", "M", "test-acc|paid")
    status.fail(h, "no_credits", "m: no credits (402) on the account", hold_s=600)
    # a 502 that was in flight (no answer since), then the minute limiter's short "rate" hold
    _, hold = status.fail(h, "congested", "m: 502 server error, congested upstream", counter="transient", threshold=1, hold_s=60, started=time.monotonic())
    assert 590 < hold <= 600  # the hold that stays, not the 60 s this failure asked for
    _, hold = status.fail(h, "rate", "m: per-minute request cap of the account", hold_s=20)
    assert 590 < hold <= 600
    d = status.health_dict(h)
    assert d["state"] == "no_credits" and 590 < d["until"] <= 600 and "no credits (402)" in d["last_error"]
    state, reason, left = status.own_hold(h)
    assert state == "no_credits" and "no credits (402)" in reason and 590 < left <= 600
    # a longer hold replaces a shorter one, with its own state and reason
    h2 = status.link("test-acc|m-consistent-2", "m2", "M2", "test-acc|paid")
    status.fail(h2, "rate", "m2: per-minute request cap of the account", hold_s=20)
    status.fail(h2, "missing", "m2: model not available (404)", hold_s=1800)
    d2 = status.health_dict(h2)
    assert d2["state"] == "missing" and d2["until"] > 1700 and "404" in d2["last_error"]
    # without an active hold a failure sets the state as before
    h3 = status.link("test-acc|m-consistent-3", "m3", "M3", "test-acc|paid")
    status.fail(h3, "congested", "m3: 502 server error, congested upstream")
    assert status.health_dict(h3)["state"] == "congested" and status.health_dict(h3)["until"] is None


def test_a_longer_hold_found_while_a_429_was_in_flight_is_the_one_the_error_names(sleeps):
    """A parallel call finds a 404 (a 30-minute hold) while this request, the link's second upstream 429, is in flight:
    the link stays «missing», and the error says so too — never «congested, skipped for 120 s»."""
    from verstka.api.model_status import classify

    def missing_meanwhile(h, model):
        def act():
            status.fail(h, "missing", f"{model}: model not available (404): no such model", hold_s=1800)
            return UPSTREAM

        return act

    # alone (the final): no pause, no second request
    p = single()
    p.health.strikes = 1
    c = wire(p, [missing_meanwhile(p.health, p.model)])
    with pytest.raises(ProviderError) as ei:
        p.complete(MSGS)
    msg = str(ei.value)
    assert "model not available (404), skipped for" in msg and "congested upstream, skipped" not in msg
    assert len(c[0].calls) == 1 and sleeps == [] and classify(msg) == "missing"
    assert status.health_dict(p.health)["state"] == "missing" and status.health_dict(p.health)["until"] > 1700
    # in a chain: the part of the free Qwen names its 404 hold; Gemma, the last link, is congested twice
    status.reset()
    reg = registry([FREE, GEMMA])
    ch = reg.get("llm")
    h = ch.links[0].health
    wire(ch, **{s(FREE): [missing_meanwhile(h, FREE)], s(GEMMA): [UPSTREAM]})
    with pytest.raises(ProviderError) as ei:
        ch.complete(MSGS)
    first = str(ei.value).split("; ")[0]
    assert first.startswith(f"all model links failed: [{h.label}] {FREE}: model not available (404), skipped for")
    assert "congested upstream, skipped" not in first and classify(first) == "missing"
    snap = status.snapshot(reg)[0]
    assert snap["state"] == "missing" and snap["until"] > 1700
    # a 5xx, or a 402 with its shorter hold, in flight while a longer hold was opened: the error names that hold too
    for kept, meanwhile, got, phrase in (
        ("no_credits", 600, http_error(502, "Bad gateway"), "no credits (402), skipped for"),
        ("missing", 1800, NO_CREDITS, "model not available (404), skipped for"),
    ):
        status.reset()
        ch = registry([FREE, GEMMA]).get("llm")
        h = ch.links[0].health

        def opened_meanwhile(h=h, kept=kept, meanwhile=meanwhile, got=got):
            status.fail(h, kept, f"{FREE}: {status.PHRASES[kept]} on the account", hold_s=meanwhile)
            return got

        wire(ch, **{s(FREE): [opened_meanwhile], s(GEMMA): [http_error(401, "User not found.")]})
        with pytest.raises(ProviderError) as ei:
            ch.complete(MSGS)
        first = str(ei.value).split("; ")[0]
        assert phrase in first and "502" not in first and "Insufficient credits" not in first and classify(first) == kept
        assert status.health_dict(h)["state"] == kept


def test_a_chain_link_whose_429s_were_in_flight_during_a_success_is_not_held(sleeps):
    ch = registry([FREE, GEMMA]).get("llm")
    h = ch.links[0].health

    def answered_meanwhile():
        status.record_ok(h)  # a parallel variant got an answer from the same model meanwhile
        return UPSTREAM

    c = wire(ch, **{s(FREE): [answered_meanwhile], s(GEMMA): [answer()]})
    for _ in range(3):
        ch.complete(MSGS)
    assert len(c[FREE].calls) == 3 and status.blocked(h) is None and h.strikes == 0


# ---------------------------------------------------------------------------------------------- status for the UI


def test_status_snapshot_reports_every_link_in_chain_order():
    reg = registry([PAID, FREE, GEMMA, GEMMA_MOE], roles=("llm", "vlm"))
    llm, vlm = reg.get("llm"), reg.get("vlm")
    assert [x["state"] for x in status.snapshot(reg)] == ["unknown"] * 4
    wire(llm, **{s(PAID): [NO_CREDITS], s(FREE): [UPSTREAM], s(GEMMA): [answer()]})
    cv = wire(vlm, **{s(GEMMA): [answer()]})
    llm.complete(MSGS)
    llm.complete(MSGS)  # the second upstream 429 of the free Qwen opens its hold
    vlm.complete(MSGS)  # the vlm role shares the holds: straight to Gemma
    assert len(cv[PAID].calls) == 0 and len(cv[FREE].calls) == 0 and len(cv[GEMMA].calls) == 1
    snap = status.snapshot(reg)
    assert all(set(x) == SNAPSHOT_FIELDS for x in snap)
    assert [x["model"] for x in snap] == [PAID, FREE, GEMMA, GEMMA_MOE]
    assert [x["state"] for x in snap] == ["no_credits", "congested", "ok", "unknown"]
    assert all(x["roles"] == ["llm", "vlm"] for x in snap)
    assert all(x["host"] == "router.example.invalid" for x in snap)
    assert [x["free"] for x in snap] == [False, True, True, True]
    paid, free, gemma, moe = snap
    assert not paid["available"] and 590 < paid["until"] <= 600 and "no credits (402)" in paid["last_error"]
    assert not free["available"] and 110 < free["until"] <= 120 and paid["last_ok"] is None
    assert gemma["available"] and gemma["until"] is None and gemma["last_ok"] and gemma["label"] == "Gemma 4 31B (бесплатно)"
    assert moe["label"] == "Gemma 4 26B A4B (бесплатно)" and moe["last_error"] == "" and moe["until"] is None
    bound = status.snapshot(reg.with_deadline(time.monotonic() + 60), role="vlm")
    assert [(x["model"], x["state"], x["roles"]) for x in bound] == [(x["model"], x["state"], ["vlm"]) for x in snap]
    assert "sk-" not in repr(snap) and "chain-0000" not in repr(snap)  # the key never reaches the UI
    assert status.snapshot(ProviderRegistry.mock({})) == []


def test_keys_are_masked_in_errors_and_in_the_chain_summary():
    key = "sk-or-v1-0123456789abcdef0123456789abcdef"
    ch = registry([FREE, GEMMA], key=key).get("llm")
    leak = http_error(400, f"bad request for key {key} and gsk_ABCDEFGHIJKLMNOPQRSTUVWX0123 (Bearer abcdefghijklmnop1234)")
    wire(ch, **{s(FREE): [leak], s(GEMMA): [leak]})
    with pytest.raises(ProviderError) as ei:
        ch.complete(MSGS)
    text = str(ei.value) + repr(status.snapshot())
    assert key not in text and "0123456789abcdef" not in text and "gsk_ABCD" not in text and "abcdefghijklmnop1234" not in text
    assert "[redacted]" in text


def test_every_state_has_its_wording():
    assert set(status.PHRASES) == {"congested", "rate", "quota", "no_credits", "auth", "missing", "off"}
    assert set(status.STATES) == {"ok", "unknown", "congested", "rate", "quota", "no_credits", "auth", "missing", "error", "off"}
    for state, phrase in status.PHRASES.items():
        assert phrase in str(oc._unavailable("m", state, "reason", 30))
    assert "congested upstream" in str(oc.classify_error(http_error(498, "flex tier capacity exceeded"), "m"))


def test_the_default_labels_are_human():
    assert oc.default_label(PAID, "https://openrouter.ai/api/v1") == "Qwen3.8-27B (OpenRouter)"
    assert oc.default_label(GEMMA, "https://openrouter.ai/api/v1") == "Gemma 4 31B (бесплатно)"
    assert oc.default_label("qwen3.5:9b", "http://localhost:11434/v1") == "Qwen3.5 9B (локально)"
    assert oc.default_label("qwen3.8-27b", "https://vk.example.invalid/v1") == "Qwen3.8-27B"
    assert oc.default_label(PAID, GROQ) == "Qwen3.8-27B (Groq)"
    assert oc.default_label(QWEN32, CLOUDRU) == "Qwen3 32B (Cloud.ru)"


# ---------------------------------------------------------------------------------------------- shipped configs


@pytest.fixture
def config_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-config-000001")
    monkeypatch.setenv("VK_INFERENCE_BASE_URL", "https://vk.example.invalid/v1")
    monkeypatch.setenv("VK_INFERENCE_API_KEY", "vk-test-000001")


def test_the_default_config_paid_qwen_groq_free_qwen_cloudru_then_gemma(config_env, monkeypatch):
    reg = ProviderRegistry.from_yaml(ROOT / "configs" / "models.yaml")
    assert reg.limits.requests_per_minute == 18 and reg.limits.time_budget_s == 210 and reg.limits.timeout_s == 120
    llm, vlm = reg.get("llm"), reg.get("vlm")
    assert isinstance(llm, ChainProvider) and isinstance(vlm, ChainProvider)
    assert [(p.model, status.hostname(p.base_url)) for p in llm.links] == [
        (PAID, "openrouter.ai"),
        (PAID, "api.groq.com"),
        (FREE, "openrouter.ai"),
        (QWEN_VL, "foundation-models.api.cloud.ru"),
        (QWEN32, "foundation-models.api.cloud.ru"),
        (GEMMA, "openrouter.ai"),
        (GEMMA_MOE, "openrouter.ai"),
    ]
    assert [p.model for p in vlm.links] == [PAID, PAID, FREE, QWEN_VL, GEMMA, GEMMA_MOE]  # Qwen3-32B reads no images
    assert vlm.links[0].health is llm.links[0].health  # llm and vlm share the records
    paid, groq, free, cloudru_vl, cloudru, gemma, moe = llm.links
    assert paid.extra_body == {"reasoning": {"enabled": False}, "provider": {"allow_fallbacks": True, "quantizations": ["bf16", "fp8"]}}
    assert (paid.price_in, paid.price_out) == (0.42, 3.00) and paid._limiter.rpm == 60
    assert groq.off and cloudru.off and cloudru_vl.off  # GROQ_API_KEY / CLOUDRU_API_KEY are not set: skipped silently
    assert cloudru_vl.label == "Qwen3-VL 30B (Cloud.ru)" and cloudru_vl.extra_body == {} and cloudru_vl.system_suffix is None
    assert groq.label == "Qwen3.8-27B (Groq)" and groq._limiter.rpm == 20 and groq.max_tokens_cap == 3000
    assert groq.extra_body == {"reasoning_effort": "none"} and groq.json_mode is False and groq.price_in == 0.0
    assert cloudru.label == "Qwen3 32B (Cloud.ru)" and cloudru.extra_body == {} and cloudru._limiter.rpm == 60
    assert cloudru.system_suffix == "/no_think" and all(p.system_suffix is None for p in (paid, groq, free, gemma, moe))
    assert free.extra_body == {"reasoning": {"enabled": False}} and free._limiter.rpm == 18
    assert gemma.extra_body == {} and moe.extra_body == {}  # Gemma gets no reasoning parameters
    assert free._limiter is gemma._limiter is moe._limiter  # the free models share the account's 20/min
    assert all(p.json_mode is False for p in llm.links)
    assert all(p.api_key == "sk-test-config-000001" for p in (paid, free, gemma, moe))
    assert llm.label == "Qwen3.8-27B (OpenRouter)"
    assert [x["state"] for x in status.snapshot(reg, role="llm")] == ["unknown", "off", "unknown", "off", "off", "unknown", "unknown"]
    # with the keys set, both links take part
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_config_000001")
    monkeypatch.setenv("CLOUDRU_API_KEY", "cloudru-test-config-01")
    llm = ProviderRegistry.from_yaml(ROOT / "configs" / "models.yaml").get("llm")
    assert not llm.links[1].off and llm.links[1].api_key == "gsk_test_config_000001" and not llm.links[3].off and not llm.links[4].off


def test_the_default_config_end_to_end_with_fake_hosts(config_env, monkeypatch, sleeps):
    """Paid Qwen without credits, Groq off, free Qwen congested, Cloud.ru off: Gemma answers, nothing waits."""
    ch = ProviderRegistry.from_yaml(ROOT / "configs" / "models.yaml").get("llm")
    c = wire(ch, [NO_CREDITS], None, [UPSTREAM], None, None, [answer("gemma")], None)
    r = ch.complete(MSGS)
    assert r.model == GEMMA and r.label == "Gemma 4 31B (бесплатно)" and sleeps == []
    assert [len(c[i].calls) for i in range(7)] == [1, 0, 1, 0, 0, 1, 0]


def test_the_ui_names_the_failed_link_by_its_label_not_by_the_wording(config_env, monkeypatch, sleeps):
    """The paid OpenRouter link and Groq run the same model id, and Groq's 401 carries no Groq wording: the label the
    chain puts before each failed link tells the notice which of them it is about."""
    from verstka.api.model_status import chain_context, collect_links, planner_info

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_config_000001")
    reg = ProviderRegistry.from_yaml(ROOT / "configs" / "models.yaml")
    ch = reg.get("llm")
    wire(ch, [NO_CREDITS], [http_error(401, "Invalid API Key")], [UPSTREAM], None, None, [UPSTREAM], [UPSTREAM])
    with pytest.raises(ProviderError) as ei:
        ch.complete(MSGS)
    text = str(ei.value)
    assert "[Qwen3.8-27B (OpenRouter)] qwen/qwen3.8-27b: no credits (402)" in text
    assert "[Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: access refused (401/403)" in text
    links, source = collect_links(reg)
    assert source == "status" and [x["label"] for x in links][:2] == ["Qwen3.8-27B (OpenRouter)", "Qwen3.8-27B (Groq)"]
    ctx = chain_context(links, "configs/models.yaml")
    manifest = {"providers": {"llm": {"backend": "chain", "model": PAID}}}
    info = planner_info({"planned_by": "rules"}, {**manifest, "warnings": ["outline_planner failed, deterministic outline used: " + text]}, use_models=True, ctx=ctx)
    assert info["reason_code"] == "auth" and info["reason"] == "ключ доступа к Groq не подходит"
    assert info["advice"] == "Проверьте ключ доступа к Groq в настройках сервера."
    # the planner's warning keeps the first 160 characters: the paid link's own part, about OpenRouter
    cut = planner_info({"planned_by": "rules"}, {**manifest, "warnings": ["outline_planner failed, deterministic outline used: " + text[:160]]}, use_models=True, ctx=ctx)
    assert cut["reason_code"] == "no_credits" and cut["reason"] == "на счёте OpenRouter нет средств для платной модели"


def test_the_free_local_and_vk_configs(config_env):
    free = ProviderRegistry.from_yaml(ROOT / "configs" / "models.free.yaml").get("llm")
    assert [p.model for p in free.links] == [PAID, FREE, GEMMA, GEMMA_MOE] and all(p.price_in == 0.0 for p in free.links)
    groq = free.links[0]
    assert groq.off and "groq.com" in groq.base_url and groq.max_tokens_cap == 3000 and groq.extra_body == {"reasoning_effort": "none"}
    assert free.links[1].extra_body == {"reasoning": {"enabled": False}} and free.links[2].extra_body == {}
    vk = ProviderRegistry.from_yaml(ROOT / "configs" / "models.vk.yaml")
    for role in ("llm", "vlm"):
        p = vk.get(role)
        assert isinstance(p, oc.OpenAICompatProvider) and p.model == "qwen3.8-27b"  # the final: one model, no chain
        assert p.base_url == "https://vk.example.invalid/v1" and p.label == "Qwen3.8-27B (VK)"
    local = ProviderRegistry.from_yaml(ROOT / "configs" / "models.local.yaml").get("llm")
    assert isinstance(local, oc.OpenAICompatProvider) and local.base_url == "http://localhost:11434/v1"
    assert local._limiter is None and local.api_key == "ollama"
