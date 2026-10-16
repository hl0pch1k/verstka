"""Model providers on Polza: the fallback chain of the qualifying stage (Qwen3.8-27B, then Qwen3.6-27B) hands over from a
model that cannot answer to the next one, with holds of its own per (account, model), a last link that keeps a short
pause, and one more pass when every link was only busy. Polza's own answers are read the way the chain needs them: a
402 (balance held by parallel requests / the key's spending limit / no money), its per-minute and daily caps on a model
against the hosts' own 429, a refusal of moderation, the ruble cost of every call, hosts with 4-bit weights left out.
The single provider of the final (Qwen3.8-27B on VK inference) keeps its single-provider behaviour.
Hermetic: every link talks to a fake client; building a real OpenAI client or reading Polza's catalog fails the test."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest
import yaml
from pydantic import BaseModel

from verstka.providers import openai_compat as oc
from verstka.providers import status
from verstka.providers.base import ChatMessage, ProviderError, Usage
from verstka.providers.chain import ChainProvider
from verstka.providers.mock import MockProvider
from verstka.providers.registry import POLZA_BASE_URL, ProviderRegistry

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "configs" / "models.yaml"
VK_CONFIG = ROOT / "configs" / "models.vk.yaml"
BASE = "https://polza.example.invalid/api/v1"  # a stand-in for Polza's endpoint
VK = "https://ai-demo.platformpreview.ru/api/inference-providers-router/00000000-0000-0000-0000-000000000001/v1"  # the final's endpoint (organisers' quickstart 16.10)
KEY = "pza_test_chain_000001"
VK_KEY = "vk-test-000001"
MAIN, BACKUP = "qwen/qwen3.8-27b", "qwen/qwen3.6-27b"
VK_MODEL = "qwen3.8-27b"  # a generic OpenAI-compatible link in the chain tests
VK_FINAL_MODEL = "qwen38-27b-fp8"  # the final's model id on VK inference (configs/models.vk.yaml)
VK_PROJECT = "PRJ-test-000001"
THIRD, FOURTH = "test/third-model", "test/fourth-model"  # more links for the chain's generic logic (not in any config)
_REQ = httpx.Request("POST", BASE + "/chat/completions")
MSGS = [ChatMessage(role="user", content="classify this slide")]
GOOD = '{"kind": "cards", "confidence": 0.9}'
SNAPSHOT_FIELDS = {"model", "label", "host", "state", "available", "until", "last_ok", "last_error", "roles"}
_REAL_FETCH_HOSTS = oc._fetch_hosts  # the autouse fixture replaces it with a guard


class Out(BaseModel):
    kind: str
    confidence: float


# Polza's error.code for each status (the docs' «Формат ошибок»)
_CODE_OF = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 402: "INSUFFICIENT_BALANCE", 403: "FORBIDDEN", 404: "NOT_FOUND",
    408: "REQUEST_TIMEOUT", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 429: "TOO_MANY_REQUESTS", 500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY", 503: "SERVICE_UNAVAILABLE",
}
_SDK_ERRORS = {400: openai.BadRequestError, 401: openai.AuthenticationError, 403: openai.PermissionDeniedError, 404: openai.NotFoundError, 429: openai.RateLimitError}


def http_error(code: int, message: str, headers: dict | None = None, *, error: str | None = None, host: str | None = None) -> openai.APIStatusError:
    """Polza's error answer as the openai SDK raises it: the class of its status, «Error code: 402 - {'error': {...}}»
    and the response's headers (Retry-After). `error` is Polza's error code (by default the one its status stands
    for: Polza's codes are strings), `host` its metadata.provider_name."""
    inner: dict = {"code": error or _CODE_OF.get(code, code), "message": message}
    if host:
        inner["metadata"] = {"provider_name": host}
    body = {"error": inner}
    cls = _SDK_ERRORS.get(code) or (openai.InternalServerError if code >= 500 else openai.APIStatusError)
    return cls(f"Error code: {code} - {body}", response=httpx.Response(code, request=_REQ, headers=headers or {}), body=inner)


# Polza's 402 INSUFFICIENT_BALANCE: no money, the key's spending limit, or the balance held by the requests in flight
NO_MONEY = http_error(402, "Недостаточно средств на балансе. Пополните баланс", error="INSUFFICIENT_BALANCE")
KEY_LIMIT = http_error(402, "Превышен лимит расходов API-ключа", error="INSUFFICIENT_BALANCE")
RESERVED = http_error(402, "Недостаточно средств: на балансе 12.40 ₽, зарезервировано 25.00 ₽ выполняющимися запросами", error="INSUFFICIENT_BALANCE")
# Polza's own caps on a model come with Retry-After: to the next minute, or to midnight by Moscow time
PER_MINUTE = http_error(429, f"Достигнут минутный лимит запросов к модели {MAIN}", {"retry-after": "30"})
MINUTE_CAP = http_error(429, f"Достигнут минутный лимит запросов к модели {MAIN}", {"retry-after": "20"})
PER_DAY = http_error(429, f"Достигнут дневной лимит запросов к модели {MAIN}", {"retry-after": "9000"})
# the model hosts' own limit, passed on by Polza: no Retry-After, the host in metadata.provider_name
HOSTS_429 = http_error(429, "Провайдер модели ограничил частоту запросов. Повторите попытку позже", host="deepinfra")
# a refusal of one request, not of the key
MODERATION = http_error(403, "Запрос отклонён модерацией: нарушение правил использования")
TOO_LARGE = http_error(413, "Запрос слишком большой для модели")
# the hosts' 429 inside an HTTP 200 body: the reason in metadata.raw, the host in metadata.provider_name
BODY_429 = SimpleNamespace(
    choices=None,
    usage=None,
    error={"code": "TOO_MANY_REQUESTS", "message": "Провайдер модели ограничил частоту запросов", "metadata": {"raw": "Too many requests", "provider_name": "deepinfra"}},
)


def answer(text: str = GOOD, prompt: int = 100, completion: int = 20, *, cost: float | None = None, cost_field: str = "cost_rub", finish: str = "stop") -> SimpleNamespace:
    """A chat completion; `cost` is what Polza says the call cost (usage.cost_rub, or its alias usage.cost)."""
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    if cost is not None:
        setattr(usage, cost_field, cost)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)], usage=usage)


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
    """No real sleeping, no real client, no catalog of hosts, no limiter stamps from other tests, clean holds before
    and after."""

    def no_network(*a, **k):
        pytest.fail("a test tried to build a real OpenAI client")

    def no_catalog(model, timeout=8.0):
        pytest.fail(f"a test tried to read Polza's catalog of hosts for {model}")

    monkeypatch.setattr(openai, "OpenAI", no_network)
    monkeypatch.setattr(oc, "_fetch_hosts", no_catalog)
    monkeypatch.setattr(oc, "_EXCLUDED", {})
    monkeypatch.setattr(oc, "_READING", {})
    monkeypatch.setattr(oc, "_LIMITERS", {})
    monkeypatch.setenv("VERSTKA_NO_CATALOG", "1")
    for var in ("POLZA_API_KEY", "VK_INFERENCE_BASE_URL", "VK_INFERENCE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    slept: list[float] = []
    monkeypatch.setattr(oc.time, "sleep", lambda s: slept.append(s))  # the time module: the chain's pause as well
    status.reset()
    yield slept
    status.reset()


def registry(links: list, key: str = KEY, roles: tuple[str, ...] = ("llm",), **limits) -> ProviderRegistry:
    """A chain on the Polza backend (a fake endpoint): `links` are model ids or link specs."""
    role = {"backend": "polza", "base_url": BASE, "api_key": key, "json_mode": False, "chain": [x if isinstance(x, dict) else {"model": x} for x in links]}
    return ProviderRegistry.from_config({"roles": {r: dict(role) for r in roles}, "limits": limits})


def polza(model: str = MAIN, key: str = KEY, **spec):
    """One Polza model alone (a config without a chain)."""
    return ProviderRegistry.from_config({"roles": {"llm": {"backend": "polza", "model": model, "base_url": BASE, "api_key": key, **spec}}}).get("llm")


def single(model: str = VK_MODEL, base_url: str = VK, key: str = VK_KEY, **spec):
    """The final's single provider: one model on VK inference."""
    return ProviderRegistry.from_config({"roles": {"llm": {"backend": "openai_compat", "model": model, "base_url": base_url, "api_key": key, **spec}}}).get("llm")


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


@pytest.fixture
def clock(monkeypatch, sleeps):
    """A fake monotonic clock that the (recorded) sleeps advance, so holds really end while the chain waits."""
    now = [10_000.0]
    monkeypatch.setattr(oc.time, "monotonic", lambda: now[0])

    def sleep(t: float) -> None:
        sleeps.append(t)
        now[0] += t

    monkeypatch.setattr(oc.time, "sleep", sleep)
    status.reset()
    return now


@pytest.fixture
def catalog(monkeypatch, sleeps):
    """Polza's public catalog of hosts, faked: the host names it lists per model (or the error it fails with) and the
    reads made."""
    monkeypatch.delenv("VERSTKA_NO_CATALOG", raising=False)
    hosts: dict = {MAIN: ["deepinfra/bf16", "morph/fp4", "phala", "Novita/FP4"], BACKUP: ["chutes/fp8", "nebius/fp4"], THIRD: ["deepinfra/bf16"]}
    reads: list[str] = []

    def fetch(model: str, timeout: float = 8.0) -> list[str]:
        reads.append(model)
        got = hosts[model]
        if isinstance(got, BaseException):
            raise got
        return list(got)

    monkeypatch.setattr(oc, "_fetch_hosts", fetch)
    return SimpleNamespace(hosts=hosts, reads=reads)


@pytest.fixture
def config_env(monkeypatch):
    monkeypatch.setenv("POLZA_API_KEY", "pza_test_config_000001")


@pytest.fixture
def vk_env(monkeypatch):
    monkeypatch.setenv("VK_INFERENCE_API_KEY", VK_KEY)
    monkeypatch.setenv("VK_PROJECT_ID", VK_PROJECT)


# ---------------------------------------------------------------------------------------------- configuration


def test_a_single_spec_is_one_polza_provider_and_so_is_a_one_link_chain(sleeps):
    reg = ProviderRegistry.from_config({"roles": {"llm": {"model": MAIN, "base_url": BASE, "api_key": KEY}}})
    p = reg.get("llm")
    assert isinstance(p, oc.OpenAICompatProvider) and p.name == "polza" and p.json_mode is True and p.label == "Qwen3.8-27B"
    assert reg.describe() == {"llm": {"backend": "polza", "model": MAIN, "label": "Qwen3.8-27B"}}  # polza is the default backend
    # alone, a provider keeps its patience: one short pause on the hosts' 429, then the answer
    c = wire(p, [HOSTS_429, answer("ok")])
    assert p.complete(MSGS).text == "ok"
    assert len(c[0].calls) == 2 and sleeps == [5.0]
    # a one-link chain is a single provider as well
    assert isinstance(registry([BACKUP]).get("llm"), oc.OpenAICompatProvider)


def test_the_backends_are_polza_openai_compat_and_mock(caplog):
    # polza: Polza's endpoint unless the config names another; hosts with the listed weights are left out of its routing
    p = ProviderRegistry.from_config({"roles": {"llm": {"model": MAIN, "api_key": KEY, "exclude_quantizations": ["fp4", " /fp8 ", ""]}}}).get("llm")
    assert p.name == "polza" and p.base_url == POLZA_BASE_URL == "https://polza.ai/api/v1" and not p.off
    assert p.exclude_quantizations == ("fp4", "fp8") and p.health.host == "polza.ai"
    # openai_compat (or its alias vk): any OpenAI-compatible endpoint — the final's VK inference, no host filtering
    for backend in ("openai_compat", "vk", "OpenAI_Compat"):
        spec = {"backend": backend, "model": VK_MODEL, "base_url": VK, "api_key": VK_KEY, "exclude_quantizations": ["fp4"]}
        q = ProviderRegistry.from_config({"roles": {"llm": spec}}).get("llm")
        assert q.name == "openai_compat" and q.base_url == VK and q.exclude_quantizations == () and not q.off
    # without its endpoint (VK_INFERENCE_BASE_URL unset) it is off even with a key: never called, never an error
    gone = ProviderRegistry.from_config({"roles": {"llm": {"backend": "openai_compat", "model": VK_MODEL, "base_url": "", "api_key": VK_KEY}}}).get("llm")
    assert gone.off and gone.api_key == ""
    assert ProviderRegistry.from_config({"roles": {"llm": {"backend": "mock", "model": "m"}}}).get("llm").name == "mock"
    # an old link spec with the options of the old hosts still builds — with a warning that they do nothing; a
    # request carries the caller's max_tokens
    with caplog.at_level("WARNING", logger="verstka.providers.registry"):
        old = polza(max_tokens_cap=3000, min_interval_s=0.5, price_in_per_m=0.42, price_out_per_m=3.0)
    assert "max_tokens_cap, min_interval_s, price_in_per_m, price_out_per_m do nothing" in caplog.text
    c = wire(old, [answer("ok")])
    assert old.complete(MSGS, max_tokens=4096).text == "ok" and c[0].calls[0]["max_tokens"] == 4096
    # the backends of the old chain are gone
    for backend in ("openrouter", "ollama", "vllm"):
        with pytest.raises(ProviderError, match="unknown provider backend"):
            ProviderRegistry.from_config({"roles": {"llm": {"backend": backend, "model": MAIN, "api_key": KEY}}})


def test_a_chain_config_builds_links_with_shared_defaults():
    key = "pza_test_shared_000002"  # the label set here stays with the records of this key only
    vk = {"backend": "openai_compat", "model": VK_MODEL, "base_url": VK, "api_key": VK_KEY, "requests_per_minute": 0, "system_suffix": "/no_think"}
    reg = registry([{"model": MAIN, "label": "Qwen3.8-27B (основная)", "extra_body": {"reasoning": {"effort": "none"}}}, BACKUP, vk], key=key, requests_per_minute=18)
    ch = reg.get("llm")
    assert isinstance(ch, ChainProvider) and ch.name == "chain" and ch.model == MAIN and ch.label == "Qwen3.8-27B (основная)"
    main, backup, last = ch.links
    assert [(p.model, p.name) for p in ch.links] == [(MAIN, "polza"), (BACKUP, "polza"), (VK_MODEL, "openai_compat")]
    assert backup.api_key == key and backup.base_url == BASE and backup.json_mode is False  # inherited
    assert main.extra_body == {"reasoning": {"effort": "none"}} and backup.extra_body == {}  # a link's own keys stay its own
    assert last.base_url == VK and last.api_key == VK_KEY and last._limiter is None and last.system_suffix == "/no_think"
    assert main._limiter.rpm == 18 and backup._limiter.rpm == 18 and main._limiter is not backup._limiter  # per model
    assert ch.api_key == key and not any(p.off for p in ch.links)
    d = reg.describe()["llm"]
    assert d["backend"] == "chain" and d["model"] == MAIN
    assert d["chain"] == [
        {"backend": "polza", "model": MAIN, "label": "Qwen3.8-27B (основная)", "off": False},
        {"backend": "polza", "model": BACKUP, "label": "Qwen3.6-27B", "off": False},
        {"backend": "openai_compat", "model": VK_MODEL, "label": "Qwen3.8-27B", "off": False},
    ]
    bound = reg.with_deadline(time.monotonic() + 100)
    assert bound.get("llm").model == MAIN and bound.describe()["llm"]["chain"] == d["chain"]
    with pytest.raises(ProviderError):
        registry([])
    with pytest.raises(ProviderError, match="do not nest"):
        registry([{"chain": [{"model": BACKUP}]}, BACKUP])


def test_a_call_to_a_link_without_a_script_fails_the_test():
    """The guard is a BaseException: neither the provider's nor the chain's `except` can turn it into a fallback."""
    ch = registry([MAIN, BACKUP]).get("llm")
    wire(ch, **{s(BACKUP): [answer()]})  # the main model has no script
    with pytest.raises(pytest.fail.Exception, match="must not be called"):
        ch.complete(MSGS)


# ---------------------------------------------------------------------------------------------- a single provider (the final, or one model alone)


@pytest.mark.parametrize(
    "error, state, phrase",
    [
        (NO_MONEY, "no_credits", "no credits (402)"),
        (KEY_LIMIT, "no_credits", "no credits (402)"),
        (http_error(401, "Неверный API-ключ"), "auth", "access refused (401/403)"),
        (http_error(403, "Доступ к модели запрещён"), "auth", "access refused (401/403)"),
        (http_error(404, f"Модель {MAIN} не найдена"), "missing", "model not available (404)"),
    ],
)
def test_alone_a_402_401_403_404_of_polza_is_reported_at_once_with_at_most_a_short_hold(sleeps, error, state, phrase):
    # Polza: a 402 (but its reserve), 401, 403 or 404 is not asked again — the same request gets the same answer
    p = polza()
    c = wire(p, [error])
    with pytest.raises(ProviderError, match="after 1 attempt:") as ei:
        p.complete(MSGS)
    assert phrase in str(ei.value) and len(c[0].calls) == 1 and sleeps == []
    hit = status.blocked(p.health)
    assert hit is not None and hit[0] == state and 50 < hit[2] <= 60  # never 10 or 30 minutes for the only model
    with pytest.raises(ProviderError, match="skipped for"):
        p.complete(MSGS)  # within that minute the model is not asked
    assert len(c[0].calls) == 1
    p.health.until = time.monotonic() - 1  # a minute later
    c[0].script = [answer("ok")]
    assert p.complete(MSGS).text == "ok" and p.health.state == "ok"


@pytest.mark.parametrize("code, state", [(402, "no_credits"), (401, "auth"), (404, "missing")])
def test_alone_the_finals_endpoint_is_asked_three_times_as_before_the_chain(sleeps, code, state):
    vk = single()
    c = wire(vk, [http_error(code, "Payment required" if code == 402 else "Unauthorized" if code == 401 else "Model not found")])
    with pytest.raises(ProviderError, match="after 3 attempts"):
        vk.complete(MSGS)
    assert len(c[0].calls) == 3 and sleeps == [2, 4] and status.blocked(vk.health)[0] == state


@pytest.mark.parametrize(
    "error",
    [
        http_error(502, "Bad gateway"),
        http_error(503, "Service unavailable"),
        http_error(408, "Request Timeout"),
        openai.APITimeoutError(request=_REQ),
        openai.APIConnectionError(request=_REQ),
    ],
)
def test_alone_5xx_408_timeouts_and_dropped_connections_get_three_attempts_and_no_hold(sleeps, error):
    assert isinstance(oc.classify_error(error, VK_MODEL), oc.TransientError)
    p = single()
    c = wire(p, [error, error, answer("third")])
    assert p.complete(MSGS).text == "third" and len(c[0].calls) == 3 and sleeps == [2, 4]
    c[0].script = [error]
    for _ in range(2):  # two calls failing in a row (as two parallel variants would): still no hold
        with pytest.raises(ProviderError, match="after 3 attempts"):
            p.complete(MSGS)
        assert status.blocked(p.health) is None
    assert len(c[0].calls) == 9


def test_alone_the_hosts_429_gets_a_short_pause_and_two_in_a_row_skip_the_model_for_two_minutes(sleeps):
    p = polza()
    c = wire(p, [HOSTS_429])
    with pytest.raises(ProviderError, match="congested upstream"):
        p.complete(MSGS)
    assert len(c[0].calls) == 2 and sleeps == [5.0]
    state, _, left = status.blocked(p.health)
    assert state == "congested" and 110 < left <= 120
    with pytest.raises(ProviderError, match="congested upstream"):
        p.complete(MSGS)
    assert len(c[0].calls) == 2  # the next call does not knock


def test_alone_the_budget_is_checked_before_a_hosts_429_is_counted(sleeps):
    """A 429 that finds no room to wait in the generation's budget is not a strike, so the next generation's first 429
    still gets its short pause and one more try (not the 2-minute hold at once)."""
    p = polza()
    c = wire(p, [HOSTS_429])
    with pytest.raises(ProviderError, match="time budget"):
        p.complete(MSGS, deadline=time.monotonic() + 8)  # a 5 s pause would leave less than one request's worth
    assert len(c[0].calls) == 1 and sleeps == [] and p.health.strikes == 0 and status.blocked(p.health) is None
    assert p.health.state == "congested"  # recorded for the UI, without a hold
    c[0].script = [HOSTS_429, answer("ok")]
    assert p.complete(MSGS, deadline=time.monotonic() + 200).text == "ok"
    assert len(c[0].calls) == 3 and sleeps == [5.0] and status.blocked(p.health) is None and p.health.strikes == 0


def test_alone_a_hosts_429_inside_a_200_answer_is_congestion_not_the_per_minute_cap(sleeps):
    p = polza()
    c = wire(p, [BODY_429, answer("ok")])
    assert p.complete(MSGS).text == "ok" and len(c[0].calls) == 2 and sleeps == [5.0]  # not six 20 s waits
    c[0].script = [BODY_429]
    with pytest.raises(ProviderError, match="congested upstream"):
        p.complete(MSGS)
    assert status.blocked(p.health)[0] == "congested"


def test_alone_polzas_per_minute_cap_is_waited_out(sleeps):
    p = polza(requests_per_minute=0)
    c = wire(p, [PER_MINUTE, answer("ok")])
    assert p.complete(MSGS).text == "ok" and sleeps == [30.0] and len(c[0].calls) == 2  # its Retry-After
    assert p.health.state == "ok"


def test_alone_polzas_daily_cap_fails_at_once_and_holds_the_model_until_its_retry_after(sleeps):
    p = polza()
    c = wire(p, [PER_DAY])
    with pytest.raises(ProviderError, match="daily request quota"):
        p.complete(MSGS)
    assert len(c[0].calls) == 1 and sleeps == []  # no attempts against a spent day
    state, _, left = status.blocked(p.health)
    assert state == "quota" and 8990 < left <= 9000
    with pytest.raises(ProviderError, match="daily request quota"):
        p.complete(MSGS)
    assert len(c[0].calls) == 1


@pytest.mark.parametrize(
    "error, code, phrase",
    [
        (http_error(400, "Некорректный запрос: unsupported parameter"), 400, "Error code: 400"),
        (TOO_LARGE, 413, "the request is too large for the model (413)"),
        (MODERATION, 403, "the request was refused by moderation (403)"),
    ],
)
def test_alone_a_400_413_or_refusal_of_moderation_is_reported_at_once_without_a_hold(sleeps, error, code, phrase):
    p = polza()
    c = wire(p, [error, answer("next request")])
    with pytest.raises(ProviderError) as ei:
        p.complete(MSGS)
    err = ei.value
    assert type(err) is ProviderError and err.no_retry and err.status_code == code and phrase in str(err)
    assert len(c[0].calls) == 1 and sleeps == [] and "after 3 attempts" not in str(err)  # the same request, the same answer
    assert status.blocked(p.health) is None and p.health.state == "error"  # the key and the model are fine: no hold
    assert p.complete(MSGS).text == "next request" and p.health.state == "ok"


def test_only_a_400_drops_json_mode_or_the_links_extra_body_for_one_more_try(sleeps):
    # a host that rejects response_format (a 400): the same request once more without it
    p = single()  # json_mode on
    c = wire(p, [http_error(400, "response_format is not supported"), answer()])
    sent = oc.requests_sent()
    assert p.complete(MSGS, schema=Out).parsed == Out(kind="cards", confidence=0.9) and oc.requests_sent() - sent == 2
    assert c[0].calls[0]["response_format"] == {"type": "json_object"} and "response_format" not in c[0].calls[1]
    # a switch of the link's extra_body the host does not know (a 400): once more without it, and so for the run
    thinking = {"chat_template_kwargs": {"enable_thinking": False}}
    p = single(json_mode=False, extra_body=thinking)
    c = wire(p, [http_error(400, "Unrecognized request argument supplied: chat_template_kwargs"), answer("ok")])
    assert p.complete(MSGS).text == "ok" and p.extra_body == {}
    assert c[0].calls[0]["extra_body"] == thinking and "extra_body" not in c[0].calls[1]
    # a 413, a refusal of moderation or a 402 is no reason to drop either: nothing is sent without them
    for error in (TOO_LARGE, MODERATION, NO_MONEY):
        status.reset()
        p = single(extra_body=thinking)
        c = wire(p, [error])
        with pytest.raises(ProviderError):
            p.complete(MSGS, schema=Out)
        assert c[0].calls and all(x["response_format"] == {"type": "json_object"} and x["extra_body"] == thinking for x in c[0].calls)
        assert p.extra_body == thinking and p.json_mode


def test_a_503_is_retried_not_before_its_retry_after_and_never_later_than_fifteen_seconds(sleeps):
    no_hosts = http_error(503, "Нет доступных провайдеров для модели", {"retry-after": "10"})
    assert oc.classify_error(no_hosts, MAIN).retry_after == 10.0 and oc.classify_error(http_error(502, "Bad gateway"), MAIN).retry_after is None
    p = polza()
    c = wire(p, [no_hosts, no_hosts, answer("ok")])
    assert p.complete(MSGS).text == "ok" and len(c[0].calls) == 3 and sleeps == [10.0, 10.0]
    sleeps.clear()
    # a Retry-After longer than a pause may be is never cut short (Polza: «не раньше указанного числа секунд»): the
    # model reports it instead of asking again early
    c[0].script = [http_error(503, "Нет доступных провайдеров для модели", {"retry-after": "60"}), answer("ok")]
    with pytest.raises(ProviderError):
        p.complete(MSGS)
    assert sleeps == [] and len(c[0].calls) == 4  # 3 + 1: one request of this call
    # in a chain the main model is held for exactly that long and the backup answers
    status.reset()
    sleeps.clear()
    ch0 = registry([MAIN, BACKUP]).get("llm")
    c0 = wire(ch0, **{s(MAIN): [http_error(503, "Нет доступных провайдеров для модели", {"retry-after": "60"})], s(BACKUP): [answer("backup")]})
    assert ch0.complete(MSGS).text == "backup" and len(c0[MAIN].calls) == 1
    assert 50 < status.blocked(ch0.links[0].health)[2] <= 60
    status.reset()
    sleeps.clear()
    sleeps.clear()
    c[0].script = [http_error(503, "Service unavailable"), http_error(503, "Service unavailable", {"retry-after": "1"}), answer("ok")]
    assert p.complete(MSGS).text == "ok" and sleeps == [2, 4]  # never sooner than the backoff
    # the last link of a chain waits the same way; the main model hands over at once
    status.reset()
    sleeps.clear()
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [no_hosts], s(BACKUP): [no_hosts, answer("backup")]})
    assert ch.complete(MSGS).text == "backup" and sleeps == [10.0] and len(c[MAIN].calls) == 1


def test_the_vk_config_of_the_final_is_one_model_without_long_holds(sleeps, vk_env):
    reg = ProviderRegistry.from_yaml(VK_CONFIG)
    for role in ("llm", "vlm"):
        p = reg.get(role)
        assert isinstance(p, oc.OpenAICompatProvider) and p.name == "openai_compat" and p.model == VK_FINAL_MODEL and p.max_attempts == 3
    p = reg.get("llm")
    c = wire(p, [http_error(401, "invalid api key")])
    with pytest.raises(ProviderError, match=r"access refused \(401/403\)"):
        p.complete(MSGS)
    assert len(c[0].calls) == 3 and status.blocked(p.health)[2] <= 60
    assert status.blocked(reg.get("vlm").health)[2] <= 60  # vlm shares the model's record: the same short hold


# ---------------------------------------------------------------------------------------------- Polza's errors


@pytest.mark.parametrize(
    "error, kind, state, phrase",
    [
        # the balance is held by the requests in flight: one of them ends in seconds — retried, never «top up»
        (RESERVED, oc.TransientError, "congested", "held by the requests in flight"),
        (http_error(402, "Insufficient balance: reserved 3.5 RUB by requests in flight", error="INSUFFICIENT_BALANCE"), oc.TransientError, "congested", "held by the requests in flight"),
        # nothing held: a reserve of zero is no money
        (http_error(402, "Недостаточно средств: зарезервировано 0.00 ₽", error="INSUFFICIENT_BALANCE"), oc.LinkUnavailable, "no_credits", "on the balance"),
        # the spending limit of the key (or of the member) is spent
        (KEY_LIMIT, oc.LinkUnavailable, "no_credits", "the spending limit of the key is spent"),
        (http_error(402, "Spending limit of this API key exceeded", error="INSUFFICIENT_BALANCE"), oc.LinkUnavailable, "no_credits", "the spending limit of the key is spent"),
        # no money on the balance; the wording alone is enough when no status code comes with it
        (NO_MONEY, oc.LinkUnavailable, "no_credits", "on the balance"),
        (RuntimeError("INSUFFICIENT_BALANCE: payment required"), oc.LinkUnavailable, "no_credits", "on the balance"),
    ],
)
def test_polzas_402_is_a_reserve_of_parallel_requests_a_spent_key_limit_or_no_money(error, kind, state, phrase):
    err = oc.classify_error(error, MAIN, KEY)
    assert type(err) is kind and err.state == state and phrase in str(err)
    if kind is oc.LinkUnavailable:
        assert err.hold_s == 600 and "no credits (402)" in str(err)
    else:
        assert not err.timeout and "congested upstream" in str(err) and "no credits" not in str(err)


@pytest.mark.parametrize(
    "text, refused",
    [
        ("Запрос отклонён модерацией: нарушение правил использования", True),
        ("Request blocked by moderation", True),
        ("The response was filtered by the content filter", True),
        ("Your prompt was flagged as violating the usage policy", True),
        ("Доступ к модели запрещён", False),
        ("Forbidden", False),
        ("api_key_revoked", False),
    ],
)
def test_a_403_is_a_refusal_of_moderation_or_a_refused_key(text, refused):
    err = oc.classify_error(http_error(403, text), MAIN, KEY)
    if refused:
        # one request was refused: not retried (the same request gets the same answer), no hold — the key is fine
        assert type(err) is ProviderError and err.no_retry and err.status_code == 403 and "refused by moderation (403)" in str(err)
    else:
        assert isinstance(err, oc.LinkUnavailable) and err.state == "auth" and err.hold_s == 1800 and "access refused (401/403)" in str(err)


@pytest.mark.parametrize(
    "error, daily, upstream, retry_after",
    [
        # Polza's own caps on the model: with Retry-After (to the next minute / to midnight by Moscow time) or its words
        (PER_MINUTE, False, False, 30.0),
        (http_error(429, "Too Many Requests", {"retry-after": "45"}), False, False, 45.0),
        (http_error(429, "Достигнут минутный лимит запросов к модели"), False, False, None),
        (PER_DAY, True, False, 9000.0),
        (http_error(429, "Too Many Requests", {"retry-after": "600"}), True, False, 600.0),  # past 5 minutes: the day
        (http_error(429, "Достигнут дневной лимит запросов к модели"), True, False, None),
        # the hosts' own limit: no Retry-After, or the host's wording even with one
        (HOSTS_429, False, True, None),
        (http_error(429, "Too Many Requests"), False, True, None),
        (http_error(429, "Провайдер модели ограничил частоту запросов", {"retry-after": "600"}, host="deepinfra"), False, True, 600.0),
        (http_error(429, "Provider returned error: Resource has been exhausted"), False, True, None),
    ],
)
def test_polzas_own_429_names_its_window_and_the_hosts_429_comes_without_retry_after(error, daily, upstream, retry_after):
    err = oc.classify_error(error, MAIN, KEY)
    assert isinstance(err, oc.RateLimited)
    assert (err.daily, err.upstream, err.retry_after) == (daily, upstream, retry_after)


# ---------------------------------------------------------------------------------------------- fallbacks


def test_the_hosts_429_hands_over_at_once_and_two_in_a_row_open_the_hold(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [HOSTS_429], s(BACKUP): [answer()]})
    r = ch.complete(MSGS, schema=Out)
    assert r.model == BACKUP and r.parsed == Out(kind="cards", confidence=0.9) and r.label == "Qwen3.6-27B"
    assert sleeps == [] and len(c[MAIN].calls) == 1  # no 5-8 s pause for a link that is not the last
    assert status.blocked(ch.links[0].health) is None  # one 429: the next call knocks again
    ch.complete(MSGS, schema=Out)
    assert len(c[MAIN].calls) == 2
    state, reason, left = status.blocked(ch.links[0].health)
    assert state == "congested" and 110 < left <= 120 and "congested upstream" in reason
    ch.complete(MSGS, schema=Out)
    assert len(c[MAIN].calls) == 2 and len(c[BACKUP].calls) == 3  # skipped without a request
    assert sleeps == []


def test_the_last_link_keeps_a_short_pause_and_one_more_try_on_congestion(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [NO_MONEY], s(BACKUP): [HOSTS_429, answer("backup")]})
    r = ch.complete(MSGS)
    assert r.model == BACKUP and r.text == "backup" and len(c[BACKUP].calls) == 2 and sleeps == [5.0]


@pytest.mark.parametrize("error, phrase", [(NO_MONEY, "on the balance"), (KEY_LIMIT, "the spending limit of the key is spent")])
def test_a_402_without_money_or_over_the_keys_limit_moves_on_and_the_model_is_asked_again_after_ten_minutes(error, phrase):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [error, answer("main")], s(BACKUP): [answer("backup")]})
    assert ch.complete(MSGS).model == BACKUP
    state, reason, left = status.blocked(ch.links[0].health)
    assert state == "no_credits" and 590 < left <= 600 and "no credits (402)" in reason and phrase in reason
    assert ch.complete(MSGS).text == "backup" and len(c[MAIN].calls) == 1  # skipped instantly
    ch.links[0].health.until = time.monotonic() - 1  # ten minutes later — the balance was topped up meanwhile
    r = ch.complete(MSGS)
    assert r.model == MAIN and r.text == "main" and ch.links[0].health.state == "ok"


def test_a_402_while_the_balance_is_held_by_parallel_requests_is_retried_not_held(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [RESERVED, answer("main")], s(BACKUP): [answer("backup")]})
    assert ch.complete(MSGS).model == BACKUP and sleeps == []  # handed over at once
    h = ch.links[0].health
    assert status.blocked(h) is None and h.state == "congested" and "held by the requests in flight" in h.last_error
    assert "no credits" not in h.last_error  # never «top up the balance»
    assert ch.complete(MSGS).text == "main" and h.state == "ok" and len(c[MAIN].calls) == 2  # asked on the next call
    # alone: a short pause and one more try, no hold
    p = polza()
    c = wire(p, [RESERVED, answer("ok")])
    assert p.complete(MSGS).text == "ok" and sleeps == [2] and len(c[0].calls) == 2 and status.blocked(p.health) is None


def test_when_both_models_find_the_balance_held_the_chain_makes_one_more_pass(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [RESERVED, answer("main")], s(BACKUP): [RESERVED]})
    r = ch.complete(MSGS)
    assert r.model == MAIN and r.text == "main"
    # the backup (the last link) keeps its attempts (2 s, 4 s: the reserve frees in seconds, it is never a hold);
    # then the jittered pause before the second pass, where the main model answers
    assert sleeps[:2] == [2, 4] and len(sleeps) == 3 and 3.0 <= sleeps[2] <= 5.0
    assert [len(c[MAIN].calls), len(c[BACKUP].calls)] == [2, 3]


@pytest.mark.parametrize("error", [http_error(400, "Некорректный запрос: unsupported parameter"), TOO_LARGE, MODERATION])
def test_a_400_413_or_refusal_of_moderation_hands_over_and_never_holds_the_model(sleeps, error):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [error], s(BACKUP): [answer("backup")]})
    for _ in range(3):
        assert ch.complete(MSGS).text == "backup"
    assert len(c[MAIN].calls) == 3 and sleeps == []  # one request per call, and asked again on every call
    h = ch.links[0].health
    assert status.blocked(h) is None and h.state == "error" and str(error.status_code) in h.last_error


def test_a_request_both_models_refuse_gets_no_second_pass(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [MODERATION], s(BACKUP): [MODERATION]})
    with pytest.raises(ProviderError, match="all model links failed") as ei:
        ch.complete(MSGS)
    # the same request would be refused again: neither the backup's backoff nor a second pass
    assert sleeps == [] and [len(c[MAIN].calls), len(c[BACKUP].calls)] == [1, 1]
    assert str(ei.value).count("refused by moderation (403)") == 2 and ei.value.retry_in is None
    assert [f["state"] for f in ei.value.failed] == ["error", "error"]
    assert status.blocked(ch.links[0].health) is None and status.blocked(ch.links[1].health) is None


@pytest.mark.parametrize(
    "error, state, phrase, hold",
    [
        (http_error(404, f"Модель {MAIN} не найдена"), "missing", "model not available (404)", 1800),
        (http_error(400, "qwen/qwen9-99b is not a valid model ID"), "missing", "model not available (404)", 1800),
        (http_error(401, "Неверный API-ключ"), "auth", "access refused (401/403)", 1800),
        (http_error(401, "api_key_revoked"), "auth", "access refused (401/403)", 1800),
        (http_error(403, "Доступ к модели запрещён"), "auth", "access refused (401/403)", 1800),
        (NO_MONEY, "no_credits", "no credits (402)", 600),
        (KEY_LIMIT, "no_credits", "no credits (402)", 600),
        (PER_MINUTE, "rate", "per-minute request cap", 30),
        (PER_DAY, "quota", "daily request quota", 9000),
        (http_error(502, "Bad gateway"), "congested", "congested upstream", 0),
        (http_error(503, "Service unavailable"), "congested", "congested upstream", 0),
        (RESERVED, "congested", "held by the requests in flight", 0),
        (http_error(408, "Request Timeout"), "congested", "timed out", 60),
        (openai.APITimeoutError(request=_REQ), "congested", "timed out", 60),
        (openai.APIConnectionError(request=_REQ), "error", "connection error", 0),
    ],
)
def test_an_unavailable_link_hands_over_to_the_next_one(sleeps, error, state, phrase, hold):
    reg = registry([MAIN, BACKUP])
    ch = reg.get("llm")
    c = wire(ch, **{s(MAIN): [error], s(BACKUP): [answer()]})
    r = ch.complete(MSGS, schema=Out)
    assert r.model == BACKUP and len(c[MAIN].calls) == 1 and sleeps == []
    snap = {x["model"]: x for x in status.snapshot(reg)}
    assert snap[MAIN]["state"] == state and phrase in snap[MAIN]["last_error"] and snap[BACKUP]["state"] == "ok"
    hit = status.blocked(ch.links[0].health)
    if hold:
        assert hit is not None and hold - 10 < hit[2] <= hold
    else:
        assert hit is None  # one 5xx / held balance / dropped connection: tried again next call
        ch.complete(MSGS, schema=Out)
        if "held by the requests in flight" in phrase:
            # the balance held by the requests in flight is the account's, not the model's: never a hold
            assert status.blocked(ch.links[0].health) is None
        else:
            assert status.blocked(ch.links[0].health)[2] > 50  # two in a row hold it


def test_an_error_inside_a_200_answer_moves_on():
    ch = registry([MAIN, BACKUP]).get("llm")
    body_502 = SimpleNamespace(choices=None, usage=None, error={"code": "BAD_GATEWAY", "message": "Upstream error", "metadata": {"provider_name": "deepinfra"}})
    wire(ch, **{s(MAIN): [body_502], s(BACKUP): [answer("ok")]})
    assert ch.complete(MSGS).model == BACKUP
    h = ch.links[0].health
    assert "502" in h.last_error and "deepinfra" in h.last_error and h.state == "congested"


def test_a_hosts_429_inside_a_200_answer_keeps_its_host_marker(sleeps):
    reg = registry([MAIN, BACKUP])
    ch = reg.get("llm")
    c = wire(ch, **{s(MAIN): [BODY_429], s(BACKUP): [answer("backup")]})
    assert ch.complete(MSGS).model == BACKUP and len(c[BACKUP].calls) == 1 and sleeps == []
    snap = {x["model"]: x for x in status.snapshot(reg)}
    assert snap[MAIN]["state"] == "congested" and snap[BACKUP]["state"] == "ok" and snap[BACKUP]["available"]
    assert "Провайдер модели ограничил частоту запросов" in snap[MAIN]["last_error"] and "deepinfra" in snap[MAIN]["last_error"]
    assert "per-minute" not in snap[MAIN]["last_error"]  # never shown as Polza's cap on the model
    # the same body as the SDK builds it (the error is an extra field of ChatCompletion)
    sdk = openai.types.chat.ChatCompletion.model_validate({"id": "gen-1", "choices": [], "created": 0, "model": MAIN, "object": "chat.completion", "error": BODY_429.error})
    err = oc.classify_error(oc._body_error(sdk), MAIN)
    assert isinstance(err, oc.RateLimited) and err.upstream and not err.daily


def test_invalid_json_after_the_links_own_attempts_moves_on_and_every_answer_is_billed():
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [answer("Извините, я не могу помочь с этим.", cost=0.05)], s(BACKUP): [answer(cost=0.12)]})
    r = ch.complete(MSGS, schema=Out)
    assert r.model == BACKUP and r.parsed.kind == "cards"
    assert len(c[MAIN].calls) == 3  # its own repair attempts first
    assert len(c[BACKUP].calls[0]["messages"]) == len(c[MAIN].calls[0]["messages"])  # the next link starts clean
    # the wasted answers are billed too: tokens and rubles of three invalid answers and the valid one
    assert r.usage.prompt_tokens == 400 and r.usage.completion_tokens == 80 and r.usage.cost_rub == pytest.approx(0.27)
    assert ch.links[0].health.state == "ok"  # the model answered: reachable, just wrong


def test_a_model_cut_off_twice_hands_over_and_both_cut_answers_are_billed(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    cut = answer('{"kind": "cards", "confid', completion=200, cost=0.3, finish="length")
    c = wire(ch, **{s(MAIN): [cut], s(BACKUP): [answer(cost=0.02)]})
    r = ch.complete(MSGS, schema=Out, max_tokens=1000)
    assert r.model == BACKUP and r.parsed == Out(kind="cards", confidence=0.9) and sleeps == []
    # asked once more from the start, shorter, with twice the room; cut again, the backup answers with the caller's room
    assert [x["max_tokens"] for x in c[MAIN].calls] == [1000, 2000] and "cut off" in c[MAIN].calls[1]["messages"][-1]["content"]
    assert c[BACKUP].calls[0]["max_tokens"] == 1000 and len(c[BACKUP].calls[0]["messages"]) == len(c[MAIN].calls[0]["messages"])
    assert r.usage.cost_rub == pytest.approx(0.62) and r.usage.completion_tokens == 420
    assert status.blocked(ch.links[0].health) is None and ch.links[0].health.state == "ok"  # it answered: no hold


def test_every_link_failed_raises_one_error_that_names_each_of_them(sleeps):
    reg = registry([MAIN, BACKUP, THIRD])
    ch = reg.get("llm")
    wire(ch, **{s(MAIN): [NO_MONEY], s(BACKUP): [HOSTS_429], s(THIRD): [http_error(404, f"Модель {THIRD} не найдена")]})
    with pytest.raises(ProviderError, match="all model links failed") as ei:
        ch.complete(MSGS, schema=Out)
    msg = str(ei.value)
    assert MAIN in msg and BACKUP in msg and THIRD in msg
    assert "no credits (402)" in msg and "congested upstream" in msg and "model not available (404)" in msg
    # the 402 and the 404 are on hold, the backup was only busy: one more pass, which skips the held links
    assert len(sleeps) == 1 and 3.0 <= sleeps[0] <= 5.0 and "again: " in msg
    # every failed link is named by its label (the one the status shows), in brackets before its own message
    labels = [x["label"] for x in status.snapshot(reg)]
    assert labels == ["Qwen3.8-27B", "Qwen3.6-27B", "Third model"]
    parts = msg[len("all model links failed: "):].split("; ")
    assert parts[0].startswith(f"[Qwen3.8-27B] {MAIN}: no credits (402)")
    assert parts[1].startswith(f"[Qwen3.6-27B] {BACKUP}: congested upstream")
    assert parts[2].startswith(f"[Third model] {THIRD}: model not available (404)")
    assert any(x.startswith("again: [Qwen3.6-27B] ") for x in parts[3:])
    assert [(f["label"], f["state"], f["pass"]) for f in ei.value.failed][:3] == [("Qwen3.8-27B", "no_credits", 1), ("Qwen3.6-27B", "congested", 1), ("Third model", "missing", 1)]
    assert [len(c.calls) for c in (ch.links[0]._client, ch.links[1]._client, ch.links[2]._client)] == [1, 2, 1]


def test_mock_links_work_in_a_chain():
    ch = ChainProvider([MockProvider({"nothing": "x"}, model="m1"), MockProvider({"*": GOOD}, model="m2")])
    assert ch.complete(MSGS, schema=Out).model == "m2"


# ---------------------------------------------------------------------------------------------- second pass


def test_a_second_pass_after_a_short_pause_when_every_link_was_only_busy(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [HOSTS_429, answer("second pass")], s(BACKUP): [http_error(502, "Bad gateway")]})
    r = ch.complete(MSGS)
    assert r.model == MAIN and r.text == "second pass"
    # the last link: 502, backoff 2 s, 502 again (two in a row: held 60 s); then one jittered 3-5 s pause
    assert len(c[BACKUP].calls) == 2 and sleeps[0] == 2 and len(sleeps) == 2 and 3.0 <= sleeps[1] <= 5.0
    assert len(c[MAIN].calls) == 2  # the backup is on hold: not asked in the second pass


def test_a_second_pass_also_follows_5xx_answers_inside_200_bodies(sleeps):
    # Polza's string codes in the body of an HTTP 200 (BAD_GATEWAY, SERVICE_UNAVAILABLE) are passing trouble too
    body = lambda code: SimpleNamespace(choices=None, usage=None, error={"code": code, "message": "Upstream error", "metadata": {"provider_name": "phala"}})  # noqa: E731
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [body("BAD_GATEWAY"), answer("second pass")], s(BACKUP): [body("SERVICE_UNAVAILABLE")]})
    r = ch.complete(MSGS)
    assert r.model == MAIN and r.text == "second pass" and len(c[MAIN].calls) == 2
    assert ch.links[1].health.state == "congested" and "503" in ch.links[1].health.last_error


def test_a_per_minute_cap_counts_as_busy_for_the_second_pass(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [HOSTS_429, answer("main")], s(BACKUP): [PER_MINUTE]})
    assert ch.complete(MSGS).text == "main" and len(sleeps) == 1 and 3.0 <= sleeps[0] <= 5.0
    assert len(c[BACKUP].calls) == 1  # its minute window is still open: skipped in the second pass


def test_a_second_pass_also_runs_while_the_402_and_404_links_are_on_hold(sleeps):
    ch = registry([MAIN, BACKUP, THIRD, FOURTH]).get("llm")
    c = wire(
        ch,
        **{
            s(MAIN): [NO_MONEY],
            s(BACKUP): [HOSTS_429, answer("second pass")],
            s(THIRD): [http_error(404, f"Модель {THIRD} не найдена")],
            s(FOURTH): [http_error(503, "Service unavailable")],
        },
    )
    r = ch.complete(MSGS)
    assert r.model == BACKUP and r.text == "second pass"
    # the last link's backoff, then the jittered pause; the 402 and the 404 links are skipped in pass 2
    assert sleeps[0] == 2 and len(sleeps) == 2 and 3.0 <= sleeps[1] <= 5.0
    assert [len(c[m].calls) for m in (MAIN, BACKUP, THIRD, FOURTH)] == [1, 2, 1, 2]


def test_the_default_config_makes_one_more_pass_when_both_models_were_only_busy(config_env, sleeps):
    ch = ProviderRegistry.from_yaml(DEFAULT).get("llm")
    c = wire(ch, [HOSTS_429, answer("main")], [http_error(503, "Нет доступных провайдеров для модели")])
    r = ch.complete(MSGS)
    assert r.model == MAIN and r.label == "Qwen3.8-27B" and r.text == "main"
    assert sleeps[0] == 2 and len(sleeps) == 2 and 3.0 <= sleeps[1] <= 5.0
    assert [len(c[i].calls) for i in range(2)] == [2, 2]


def test_no_second_pass_after_a_real_failure_short_budget_or_when_every_link_is_on_hold(sleeps):
    # a 402 on hold, and the last link held after its second hosts' 429: nothing is free after the pause
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [NO_MONEY], s(BACKUP): [HOSTS_429]})
    with pytest.raises(ProviderError, match="all model links failed"):
        ch.complete(MSGS)
    assert sleeps == [5.0] and len(c[MAIN].calls) == 1 and len(c[BACKUP].calls) == 2
    status.reset()
    sleeps.clear()
    # a failure that opens no hold (invalid JSON after the link's own attempts) would only repeat: no second pass
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [HOSTS_429], s(BACKUP): [answer("Извините, я не могу помочь с этим.")]})
    with pytest.raises(ProviderError, match="all model links failed"):
        ch.complete(MSGS, schema=Out)
    assert sleeps == [] and len(c[MAIN].calls) == 1 and len(c[BACKUP].calls) == 3
    status.reset()
    sleeps.clear()
    # a plain 4xx of a link that is not the last (no hold) rules it out as well
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [http_error(400, "Некорректный запрос: unsupported parameter")], s(BACKUP): [http_error(502, "Bad gateway")]})
    with pytest.raises(ProviderError, match="all model links failed"):
        ch.complete(MSGS)
    assert sleeps == [2] and len(c[MAIN].calls) == 1 and len(c[BACKUP].calls) == 2
    status.reset()
    sleeps.clear()
    # less than 30 s of the budget left
    reg = registry([MAIN, BACKUP])
    c = wire(reg.get("llm"), **{s(MAIN): [HOSTS_429], s(BACKUP): [http_error(503, "Service unavailable")]})
    with pytest.raises(ProviderError, match="all model links failed"):
        reg.with_deadline(time.monotonic() + 25).get("llm").complete(MSGS)
    assert sleeps == [2] and len(c[MAIN].calls) == 1
    status.reset()
    sleeps.clear()
    # both links are on hold after the first pass: a pause would only lead to skipping them
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [HOSTS_429], s(BACKUP): [HOSTS_429]})
    ch.links[0].health.strikes = 1  # the main model was congested on the previous call already
    with pytest.raises(ProviderError, match="congested upstream"):
        ch.complete(MSGS)
    assert sleeps == [5.0]  # only the last link's short pause
    assert status.blocked(ch.links[0].health)[0] == "congested" and status.blocked(ch.links[1].health)[0] == "congested"


# ---------------------------------------------------------------------------------------------- waiting out a short hold


def test_a_short_per_minute_hold_on_the_only_working_model_is_waited_out(clock, sleeps):
    """The main model hit Polza's per-minute cap (Retry-After 20), the backup has no money: the chain waits the 20-s
    window out and asks the main model again, instead of failing the writer into a skeleton."""
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [MINUTE_CAP, answer("main")], s(BACKUP): [NO_MONEY]})
    r = ch.complete(MSGS, deadline=clock[0] + 120)
    assert r.model == MAIN and r.text == "main"
    assert len(c[MAIN].calls) == 2 and len(c[BACKUP].calls) == 1
    waits = [x for x in sleeps if x >= 20]
    assert len(waits) == 1 and 20.5 <= waits[0] <= 22.0  # the window (20 s) and a jitter, once


def test_a_hold_is_waited_out_only_when_the_budget_leaves_room_and_the_error_says_when_it_ends(clock, sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [MINUTE_CAP, answer("late")], s(BACKUP): [NO_MONEY]})
    # 40 s left: the 20-s window plus 30 s for the answer do not fit — no wait, the caller learns when it could ask
    with pytest.raises(ProviderError, match="all model links failed") as ei:
        ch.complete(MSGS, deadline=clock[0] + 40)
    assert len(c[MAIN].calls) == 1 and not [x for x in sleeps if x >= 20]
    assert ei.value.retry_in is not None and 15.0 <= ei.value.retry_in <= 20.0
    # a hold longer than 30 s is never waited out (every link on a long hold: nothing to wait for)
    status.reset()
    sleeps.clear()
    ch = registry([MAIN, BACKUP]).get("llm")
    wire(ch, **{s(MAIN): [NO_MONEY], s(BACKUP): [HOSTS_429]})
    with pytest.raises(ProviderError) as ei:
        ch.complete(MSGS, deadline=clock[0] + 200)
    assert ei.value.retry_in is None and max(sleeps, default=0) <= 5.0


def test_at_most_three_passes_while_the_cap_keeps_coming_back(clock, sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    c = wire(ch, **{s(MAIN): [MINUTE_CAP], s(BACKUP): [NO_MONEY]})
    with pytest.raises(ProviderError, match="again: "):
        ch.complete(MSGS, deadline=clock[0] + 200)
    assert len(c[MAIN].calls) == 3 and len(c[BACKUP].calls) == 1 and len([x for x in sleeps if x >= 20]) == 2


def test_a_single_provider_without_room_to_wait_a_cap_says_when_to_ask_again(clock, sleeps):
    one = polza(requests_per_minute=0)
    wire(one, [MINUTE_CAP])
    with pytest.raises(ProviderError) as ei:
        one.complete(MSGS, deadline=clock[0] + 8)
    assert getattr(ei.value, "retry_in", None) == 20.0


# ---------------------------------------------------------------------------------------------- holds per model (no pools)


def test_polzas_per_minute_cap_holds_only_the_capped_model_and_the_backup_answers_at_once(sleeps):
    reg = registry([MAIN, BACKUP])
    ch = reg.get("llm")
    c = wire(ch, **{s(MAIN): [PER_MINUTE, answer("main")], s(BACKUP): [answer("backup")]})
    r = ch.complete(MSGS)
    assert r.model == BACKUP and r.label == "Qwen3.6-27B" and sleeps == []  # nobody waits for the minute
    state, reason, left = status.blocked(ch.links[0].health)
    assert state == "rate" and 25 < left <= 30 and "per-minute request cap" in reason and "daily" not in reason
    snap = {x["model"]: x for x in status.snapshot(reg)}
    assert snap[MAIN]["state"] == "rate" and not snap[MAIN]["available"] and 25 < snap[MAIN]["until"] <= 30
    assert snap[BACKUP]["state"] == "ok" and snap[BACKUP]["available"]  # the backup on the same key is not held
    assert ch.complete(MSGS).text == "backup" and len(c[MAIN].calls) == 1  # skipped till its minute ends
    ch.links[0].health.until = time.monotonic() - 1  # the minute is over
    assert ch.complete(MSGS).text == "main" and len(c[MAIN].calls) == 2


def test_polzas_daily_cap_holds_only_the_capped_model_until_its_retry_after(sleeps):
    reg = registry([MAIN, BACKUP], roles=("llm", "vlm"))
    ch = reg.get("llm")
    c = wire(ch, **{s(MAIN): [PER_DAY], s(BACKUP): [answer("backup")]})
    assert ch.complete(MSGS).model == BACKUP and sleeps == []
    state, reason, left = status.blocked(ch.links[0].health)
    assert state == "quota" and 8990 < left <= 9000 and "daily request quota" in reason
    assert status.blocked(ch.links[1].health) is None  # the backup has a cap of its own
    ch.complete(MSGS)
    assert len(c[MAIN].calls) == 1 and len(c[BACKUP].calls) == 2
    # the vlm role shares the model's record: straight to the backup as well
    cv = wire(reg.get("vlm"), **{s(BACKUP): [answer("vlm")]})
    assert reg.get("vlm").complete(MSGS).text == "vlm" and len(cv[MAIN].calls) == 0


@pytest.mark.parametrize("utc, hold", [((20, 0), 3605.0), ((3, 30), 63005.0)])
def test_a_daily_cap_without_retry_after_holds_the_model_until_midnight_in_moscow(monkeypatch, sleeps, utc, hold):
    """23:00 in Moscow: an hour (and 5 s); 06:30: seventeen and a half hours — midnight by Moscow time, not by UTC."""
    now = datetime(2026, 10, 6, *utc, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(oc.time, "time", lambda: now)
    ch = registry([MAIN, BACKUP]).get("llm")
    wire(ch, **{s(MAIN): [http_error(429, f"Достигнут дневной лимит запросов к модели {MAIN}")], s(BACKUP): [answer("backup")]})
    assert ch.complete(MSGS).model == BACKUP
    state, _, left = status.blocked(ch.links[0].health)
    assert state == "quota" and hold - 5 < left <= hold


def test_congestion_of_one_model_does_not_block_another_model_on_the_same_key():
    ch = registry([MAIN, BACKUP]).get("llm")
    wire(ch, **{s(MAIN): [HOSTS_429], s(BACKUP): [answer("backup")]})
    ch.complete(MSGS)
    ch.complete(MSGS)
    assert status.blocked(ch.links[0].health)[0] == "congested"
    assert status.blocked(ch.links[1].health) is None
    # a provider of the backup alone on the very same key shares its record, and is not held either
    alone = polza(BACKUP)
    c = wire(alone, [answer("alone")])
    assert alone.health is ch.links[1].health and alone.complete(MSGS).text == "alone" and len(c[0].calls) == 1


def test_a_hosts_429_with_a_long_retry_after_is_congestion_not_polzas_daily_cap(sleeps):
    reg = registry([MAIN, BACKUP])
    ch = reg.get("llm")
    hosts = http_error(429, "Провайдер модели ограничил частоту запросов", {"retry-after": "600"}, host="deepinfra")
    c = wire(ch, **{s(MAIN): [hosts], s(BACKUP): [answer("backup")]})
    assert ch.complete(MSGS).model == BACKUP and len(c[BACKUP].calls) == 1
    assert {x["model"]: x["state"] for x in status.snapshot(reg)} == {MAIN: "congested", BACKUP: "ok"}
    assert status.blocked(ch.links[0].health) is None  # a strike, not the ten minutes it names
    # alone, the short pause stays short whatever the host's Retry-After says
    status.reset()
    p = polza()
    c = wire(p, [hosts, answer("ok")])
    assert p.complete(MSGS).text == "ok" and sleeps == [8.0]


def test_the_minute_limiter_inside_a_chain_skips_the_link_instead_of_waiting(sleeps):
    reg = registry([{"model": MAIN, "requests_per_minute": 1}, {"model": BACKUP, "requests_per_minute": 0}])
    ch = reg.get("llm")
    c = wire(ch, **{s(MAIN): [answer("main")], s(BACKUP): [answer("backup")]})
    assert ch.complete(MSGS).text == "main"
    assert ch.complete(MSGS).text == "backup" and sleeps == [] and len(c[MAIN].calls) == 1  # no slot: skipped, no request
    main = status.snapshot(reg)[0]
    assert main["state"] == "rate" and not main["available"] and 50 < main["until"] <= 61
    assert "per-minute request cap" in main["last_error"]


# ---------------------------------------------------------------------------------------------- links without a key


def test_a_link_without_a_key_is_off_and_skipped_silently(sleeps):
    reg = registry([{"model": MAIN, "api_key": ""}, BACKUP, THIRD])
    ch = reg.get("llm")
    assert ch.links[0].off and not ch.links[1].off
    c = wire(ch, **{s(BACKUP): [answer("backup")]})  # the main model has no script: a request would fail the test
    assert ch.complete(MSGS).text == "backup" and sleeps == []
    snap = status.snapshot(reg)
    assert snap[0]["state"] == "off" and snap[0]["available"] is False and snap[0]["until"] is None
    assert snap[0]["last_error"] == "not configured (no API key)"
    status.reset()
    assert status.snapshot(reg)[0]["state"] == "off"  # a reset forgets holds, not the missing key
    c[1].script = [http_error(404, "Модель не найдена")]
    c[2].script = [http_error(404, "Модель не найдена")]
    with pytest.raises(ProviderError, match="all model links failed") as ei:
        ch.complete(MSGS)
    assert "not configured" not in str(ei.value) and MAIN not in str(ei.value)  # the off link is not an error
    # every link off: one clear error, no request
    off = registry([{"model": MAIN, "api_key": ""}, {"model": BACKUP, "api_key": ""}]).get("llm")
    wire(off)
    with pytest.raises(ProviderError, match=r"not configured \(no API key\)"):
        off.complete(MSGS)
    assert off.api_key == ""


def test_the_chain_is_named_after_its_first_link_with_a_key():
    reg = registry([{"model": MAIN, "api_key": ""}, BACKUP, THIRD])
    ch = reg.get("llm")
    assert ch.model == BACKUP and ch.label == "Qwen3.6-27B"
    assert reg.describe()["llm"]["model"] == BACKUP and reg.with_deadline(time.monotonic() + 60).get("llm").model == BACKUP
    off = registry([{"model": MAIN, "api_key": ""}, {"model": BACKUP, "api_key": ""}]).get("llm")
    assert off.model == MAIN and off.label == "Qwen3.8-27B"  # every link off: the first one names the chain


def test_a_chain_with_one_live_link_behaves_as_a_single_provider(sleeps):
    vk = {"backend": "openai_compat", "model": VK_MODEL, "base_url": VK, "api_key": VK_KEY}
    reg = registry([vk, {"model": BACKUP, "api_key": ""}])  # a key-gated backup on Polza without its key
    ch = reg.get("llm")
    assert isinstance(ch, ChainProvider) and ch.model == VK_MODEL and ch.links[1].off
    c = wire(ch, [http_error(401, "invalid api key")])
    with pytest.raises(ProviderError, match="after 3 attempts"):
        ch.complete(MSGS)
    assert len(c[0].calls) == 3 and sleeps == [2, 4]  # its own attempts and backoff
    assert status.blocked(ch.links[0].health)[2] <= 60  # at most the short hold, never 30 minutes
    status.reset()
    sleeps.clear()
    # another endpoint than Polza reads a bare 429 as its per-minute cap, as before the migration: waited out, never
    # the hosts' congestion that would hold the only model for 2 minutes
    c[0].script = [http_error(429, "Too Many Requests"), answer("ok")]
    assert ch.complete(MSGS).text == "ok" and sleeps == [20.0]
    c[0].script = [http_error(429, "Too Many Requests", {"retry-after": "30"}), answer("waited")]
    assert ch.complete(MSGS).text == "waited" and sleeps == [20.0, 30.0]  # a per-minute cap is waited out


def test_a_key_or_an_endpoint_from_an_unset_variable_makes_the_link_off(monkeypatch):
    assert all(p.off for p in registry([MAIN, BACKUP], key="${POLZA_API_KEY}").get("llm").links)
    monkeypatch.setenv("POLZA_API_KEY", "pza_test_env_000001")
    links = registry([MAIN, BACKUP], key="${POLZA_API_KEY}").get("llm").links
    assert not any(p.off for p in links) and links[1].api_key == "pza_test_env_000001"
    # the final's endpoint from an unset VK_INFERENCE_BASE_URL: off even with its key
    vk = {"backend": "openai_compat", "model": VK_MODEL, "base_url": "${VK_INFERENCE_BASE_URL}", "api_key": "${VK_INFERENCE_API_KEY}"}
    monkeypatch.setenv("VK_INFERENCE_API_KEY", VK_KEY)
    assert registry([vk, BACKUP]).get("llm").links[0].off
    monkeypatch.setenv("VK_INFERENCE_BASE_URL", VK)
    assert not registry([vk, BACKUP]).get("llm").links[0].off


def test_a_single_provider_without_a_key_says_so_at_once(sleeps):
    p = single(key="")
    wire(p)
    with pytest.raises(ProviderError, match=r"not configured \(no API key\)"):
        p.complete(MSGS)
    assert sleeps == [] and status.snapshot(ProviderRegistry(roles={"llm": p}))[0]["state"] == "off"


# ---------------------------------------------------------------------------------------------- per-link options


def test_an_inline_think_block_is_dropped_before_parsing():
    p = single()
    wire(p, [answer("<think>\nThe user wants {a plan}...\n</think>\n\n" + GOOD)])
    assert p.complete(MSGS, schema=Out).parsed == Out(kind="cards", confidence=0.9)


def test_the_system_suffix_is_sent_only_by_its_own_link():
    vk = {"backend": "openai_compat", "model": VK_MODEL, "base_url": VK, "api_key": VK_KEY, "system_suffix": "/no_think"}
    ch = registry([vk, BACKUP]).get("llm")
    assert ch.links[0].system_suffix == "/no_think" and ch.links[1].system_suffix is None
    c = wire(ch, [http_error(502, "Bad gateway"), answer("<think>\n\n</think>\n\n" + GOOD)], [answer()])
    assert ch.complete(MSGS, schema=Out).model == BACKUP
    sent = c[0].calls[0]["messages"]
    # one system message, first (Qwen's template refuses any other place): the schema instruction, then the switch
    assert sent[0]["role"] == "system" and sent[0]["content"].endswith("\n/no_think") and "JSON schema" in sent[0]["content"]
    assert [m["role"] for m in sent].count("system") == 1
    assert sum("/no_think" in str(m["content"]) for m in sent) == 1
    assert not any("/no_think" in str(m["content"]) for m in c[1].calls[0]["messages"])  # not the backup's
    # without a system message of its own, the switch comes first; the empty think block is dropped from the answer
    r = ch.complete(MSGS, schema=Out)
    assert r.model == VK_MODEL and r.parsed == Out(kind="cards", confidence=0.9)
    plain = registry([vk, BACKUP]).get("llm")
    c = wire(plain, [answer("<think>\n\n</think>\n\nready")])
    assert plain.complete(MSGS).text == "ready"
    assert c[0].calls[0]["messages"][0] == {"role": "system", "content": "/no_think"} and c[0].calls[0]["messages"][1]["role"] == "user"
    assert MSGS[0].content == "classify this slide"  # the caller's messages are not changed


def test_every_system_text_goes_into_one_first_message():
    """VK inference serves Qwen's own chat template: a system message after the user's is refused with a 400
    («System message must be at the beginning») — the skill's system text, the schema instruction and the thinking
    switch are sent as one system message, first; the rest keeps its order."""
    vk = {"backend": "openai_compat", "model": VK_MODEL, "base_url": VK, "api_key": VK_KEY, "system_suffix": "/no_think"}
    p = registry([vk]).get("llm")
    c = wire(p, [answer(GOOD)])
    msgs = [ChatMessage(role="system", content="Ты — дизайнер презентаций."), ChatMessage(role="user", content="первый"),
            ChatMessage(role="assistant", content="ответ"), ChatMessage(role="system", content="Помни про шаблон."),
            ChatMessage(role="user", content="второй")]
    assert p.complete(msgs, schema=Out).parsed == Out(kind="cards", confidence=0.9)
    sent = c[0].calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    first = sent[0]["content"]
    assert first.index("Ты — дизайнер") < first.index("Помни про шаблон") < first.index("JSON schema") < first.index("/no_think")
    assert [m["content"] for m in sent[1:]] == ["первый", "ответ", "второй"]
    assert oc._system_first([{"role": "system", "content": "a"}, {"role": "user", "content": "b"}])[0] == {"role": "system", "content": "a"}
    assert oc._system_first([{"role": "user", "content": "b"}]) == [{"role": "user", "content": "b"}]


def test_hosts_with_4_bit_weights_are_read_once_per_model_from_polzas_catalog(catalog):
    assert oc.excluded_hosts(MAIN, ("fp4",)) == ["morph/fp4", "Novita/FP4"]  # by the name's ending, in any case
    assert oc.excluded_hosts(MAIN, ("fp4",)) == ["morph/fp4", "Novita/FP4"] and catalog.reads == [MAIN]  # cached
    assert oc.excluded_hosts(BACKUP, ("fp4", "fp8")) == ["chutes/fp8", "nebius/fp4"] and catalog.reads == [MAIN, BACKUP]
    assert oc.excluded_hosts(THIRD, ("fp4",)) == [] and catalog.reads == [MAIN, BACKUP, THIRD]  # nothing to leave out
    assert oc.excluded_hosts(FOURTH, ()) == [] and catalog.reads == [MAIN, BACKUP, THIRD]  # no quantization: no read


def test_offline_runs_and_tests_skip_the_catalog(monkeypatch, catalog):
    monkeypatch.setenv("VERSTKA_NO_CATALOG", "1")
    assert oc.excluded_hosts(MAIN, ("fp4",)) == [] and catalog.reads == []


def test_a_catalog_that_cannot_be_read_filters_nothing_and_is_read_again_ten_minutes_later(catalog, clock, caplog):
    catalog.hosts[MAIN] = httpx.ConnectError("catalog unreachable")
    with caplog.at_level(logging.WARNING, logger="verstka.providers.openai_compat"):
        assert oc.excluded_hosts(MAIN, ("fp4",)) == []  # Polza routes freely meanwhile
    assert "catalog of hosts is unavailable" in caplog.text
    clock[0] += 590
    assert oc.excluded_hosts(MAIN, ("fp4",)) == [] and catalog.reads == [MAIN]  # not asked again within ten minutes
    catalog.hosts[MAIN] = ["morph/fp4", "deepinfra/bf16"]
    clock[0] += 11
    assert oc.excluded_hosts(MAIN, ("fp4",)) == ["morph/fp4"] and catalog.reads == [MAIN, MAIN]


def test_the_catalog_is_read_without_a_key(monkeypatch):
    seen: dict = {"urls": []}
    replies = [
        {"data": {"id": MAIN, "providers": [{"name": "deepinfra/bf16"}, {"name": "morph/fp4"}, {"name": ""}, {"slug": "x"}, "junk"]}},
        {"providers": [{"name": "phala"}]},  # without the data envelope
        {"data": {"id": THIRD}},  # no hosts listed
    ]

    class Reply:
        def __init__(self, data: dict) -> None:
            self.data = data

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self.data

    def get(url, **kw):
        seen["urls"].append(url)
        seen["kw"] = kw
        return Reply(replies.pop(0))

    monkeypatch.setattr(httpx, "get", get)
    assert _REAL_FETCH_HOSTS(MAIN) == ["deepinfra/bf16", "morph/fp4"]
    assert seen["urls"] == ["https://api.polza.ai/v1/models/qwen/qwen3.8-27b"]
    assert "headers" not in seen["kw"] and "auth" not in seen["kw"] and seen["kw"]["timeout"] == 8.0  # public: no key
    assert _REAL_FETCH_HOSTS(BACKUP) == ["phala"] and _REAL_FETCH_HOSTS(THIRD) == []


def test_the_request_leaves_the_4_bit_hosts_out_and_keeps_the_links_own_routing_and_reasoning(catalog):
    own = {"reasoning": {"effort": "none"}, "provider": {"ignore": ["morph/fp4", "slowhost"], "sort": "latency"}}
    reg = registry([{"model": MAIN, "exclude_quantizations": ["fp4"], "extra_body": own}, {"model": THIRD, "exclude_quantizations": ["fp4"]}, BACKUP])
    main, third, backup = reg.get("llm").links
    body = {"reasoning": {"effort": "none"}, "provider": {"ignore": ["morph/fp4", "slowhost", "Novita/FP4"], "sort": "latency"}}
    assert main._body() == body  # the catalog's hosts join the configured ones, each once
    assert main.extra_body == own  # the link's own options are not changed by the merge
    assert third._body() == {}  # no 4-bit host listed: no routing block at all
    assert backup._body() == {} and catalog.reads == [MAIN, THIRD]  # a link without the option reads nothing
    c = wire(reg.get("llm"), **{s(MAIN): [answer("main")]})
    assert reg.get("llm").complete(MSGS).text == "main"
    assert c[MAIN].calls[0]["extra_body"] == body and catalog.reads == [MAIN, THIRD]
    # the final's endpoint is not Polza: the option is ignored and the catalog is not read
    vk = single(exclude_quantizations=["fp4"], extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    assert vk.exclude_quantizations == () and vk._body() == {"chat_template_kwargs": {"enable_thinking": False}}
    assert catalog.reads == [MAIN, THIRD]


# ---------------------------------------------------------------------------------------------- costs in rubles


def test_the_cost_in_rubles_is_read_from_polzas_usage():
    # usage.cost_rub, or its alias usage.cost; None when the host does not say (VK inference)
    assert oc._cost_rub(SimpleNamespace(prompt_tokens=1, completion_tokens=1, cost_rub=0.042)) == 0.042
    assert oc._cost_rub(SimpleNamespace(prompt_tokens=1, completion_tokens=1, cost="0.30")) == 0.3
    assert oc._cost_rub(SimpleNamespace(cost_rub="n/a", cost=0.5)) == 0.5  # an unreadable value is skipped
    assert oc._cost_rub(SimpleNamespace(prompt_tokens=1, completion_tokens=1)) is None and oc._cost_rub(None) is None
    # another endpoint's usage.cost is in its own money (OpenRouter's: dollars): only cost_rub counts there
    assert oc._cost_rub(SimpleNamespace(cost=0.5), polza=False) is None and oc._cost_rub(SimpleNamespace(cost_rub=0.5, cost=9), polza=False) == 0.5
    sdk = openai.types.chat.ChatCompletion.model_validate(
        {
            "id": "gen-1",
            "created": 0,
            "model": MAIN,
            "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": GOOD}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150, "cost_rub": 0.0421},
        }
    )
    assert oc._cost_rub(sdk.usage) == 0.0421  # an extra field of the SDK's usage
    p = polza()
    wire(p, [sdk])
    r = p.complete(MSGS, schema=Out)
    assert r.usage == Usage(120, 30, 0.0421) and not hasattr(r.usage, "cost_usd")
    # sums: an unknown cost stays unknown until some call names its own
    assert Usage(1, 2).add(Usage(3, 4)) == Usage(4, 6, None)
    assert Usage(1, 2, 0.5).add(Usage(3, 4)) == Usage(4, 6, 0.5) and Usage(0, 0, 0.25).add(Usage(0, 0, 0.5)).cost_rub == 0.75


def test_a_chain_bills_the_rubles_of_its_failed_and_successful_calls(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    # the main model's invalid answers (usage.cost), the backup's valid one (usage.cost_rub)
    wire(ch, **{s(MAIN): [answer("Извините.", cost=0.05, cost_field="cost")], s(BACKUP): [answer(cost=0.12)]})
    assert ch.complete(MSGS, schema=Out).usage == Usage(400, 80, pytest.approx(0.27))
    # a request that failed costs nothing: a 402 of the main model adds no rubles
    status.reset()
    wire(ch, **{s(MAIN): [NO_MONEY], s(BACKUP): [answer(cost=0.12)]})
    assert ch.complete(MSGS, schema=Out).usage == Usage(100, 20, 0.12)


# ---------------------------------------------------------------------------------------------- deadline


def test_the_generation_deadline_is_respected():
    reg = registry([MAIN, BACKUP])
    ch = reg.get("llm")
    c = wire(ch, **{s(MAIN): [NO_MONEY], s(BACKUP): [answer("backup")]})
    with pytest.raises(ProviderError, match="time budget"):
        reg.with_deadline(time.monotonic() + 3).get("llm").complete(MSGS)  # less than one request's worth left
    assert len(c[MAIN].calls) == 0 and len(c[BACKUP].calls) == 0
    r = reg.with_deadline(time.monotonic() + 40).get("llm").complete(MSGS)
    assert r.model == BACKUP and c[BACKUP].calls[0]["timeout"] <= 40  # the next link gets what is left, not 120 s
    assert reg.get("llm") is ch  # the shared registry stays unbound


def test_a_timeout_cut_short_by_the_generations_deadline_is_not_the_links_fault(sleeps):
    reg = registry([MAIN, BACKUP])
    c = wire(reg.get("llm"), **{s(MAIN): [openai.APITimeoutError(request=_REQ)], s(BACKUP): [answer("backup")]})
    r = reg.with_deadline(time.monotonic() + 20).get("llm").complete(MSGS)
    assert r.model == BACKUP and c[MAIN].calls[0]["timeout"] <= 20
    h = reg.get("llm").links[0].health
    assert status.blocked(h) is None and h.state == "unknown" and h.last_error == ""  # nothing recorded
    # the link's own timeout (not cut by the budget) is the host's: a link that is not the last is held 60 s
    reg.get("llm").complete(MSGS)
    assert status.blocked(h)[0] == "congested" and 50 < status.blocked(h)[2] <= 60


def test_a_408_from_the_host_is_retried_even_when_the_budget_caps_the_request(sleeps):
    """A 408 is the host's answer (Polza's upstream timed out), not our own timeout cut short by the budget: with 100 s of
    the generation left (less than the 120 s request timeout, so the request is capped) it is retried like any 408."""
    p = polza()
    c = wire(p, [http_error(408, "Request Timeout"), answer("ok")])
    assert p.complete(MSGS, deadline=time.monotonic() + 100).text == "ok"
    assert len(c[0].calls) == 2 and sleeps == [2]


# ---------------------------------------------------------------------------------------------- "in a row"


def test_failures_that_started_before_the_last_answer_do_not_count_in_a_row():
    h = status.link("test-acc|m-in-a-row", "m", "M")
    started = time.monotonic() - 0.001
    status.record_ok(h)  # another call answered while this request was in flight
    n, hold = status.fail(h, "congested", "429 upstream", counter="strikes", threshold=2, hold_s=120, started=started)
    assert (n, hold, h.state, h.strikes) == (0, 0.0, "ok", 0)
    after = time.monotonic()
    assert status.fail(h, "congested", "429 upstream", counter="strikes", hold_s=120, started=after) == (1, 0.0)
    n, hold = status.fail(h, "congested", "429 upstream", counter="strikes", hold_s=120, started=after)
    assert (n, hold, h.state) == (2, 120, "congested")


def test_parallel_failures_are_counted_and_decided_under_one_lock():
    h = status.link("test-acc|m-parallel", "m", "M")
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
    h = status.link("test-acc|m-consistent", "m", "M")
    status.fail(h, "no_credits", "m: no credits (402) on the balance", hold_s=600)
    # a 502 that was in flight (no answer since), then Polza's short per-minute hold
    _, hold = status.fail(h, "congested", "m: 502 server error, congested upstream", counter="transient", threshold=1, hold_s=60, started=time.monotonic())
    assert 590 < hold <= 600  # the hold that stays, not the 60 s this failure asked for
    _, hold = status.fail(h, "rate", "m: per-minute request cap of the account", hold_s=20)
    assert 590 < hold <= 600
    d = status.health_dict(h)
    assert d["state"] == "no_credits" and 590 < d["until"] <= 600 and "no credits (402)" in d["last_error"]
    state, reason, left = status.own_hold(h)
    assert state == "no_credits" and "no credits (402)" in reason and 590 < left <= 600
    # a longer hold replaces a shorter one, with its own state and reason
    h2 = status.link("test-acc|m-consistent-2", "m2", "M2")
    status.fail(h2, "rate", "m2: per-minute request cap of the account", hold_s=20)
    status.fail(h2, "missing", "m2: model not available (404)", hold_s=1800)
    d2 = status.health_dict(h2)
    assert d2["state"] == "missing" and d2["until"] > 1700 and "404" in d2["last_error"]
    # without an active hold a failure sets the state as before
    h3 = status.link("test-acc|m-consistent-3", "m3", "M3")
    status.fail(h3, "congested", "m3: 502 server error, congested upstream")
    assert status.health_dict(h3)["state"] == "congested" and status.health_dict(h3)["until"] is None


def test_a_longer_hold_found_while_a_429_was_in_flight_is_the_one_the_error_names(sleeps):
    """A parallel call finds a 404 (a 30-minute hold) while this request, the model's second hosts' 429, is in flight:
    the link stays «missing», and the error says so too — never «congested, skipped for 120 s»."""
    from verstka.api.model_status import classify

    def missing_meanwhile(h, model):
        def act():
            status.fail(h, "missing", f"{model}: model not available (404): no such model", hold_s=1800)
            return HOSTS_429

        return act

    # alone: no pause, no second request
    p = polza()
    p.health.strikes = 1
    c = wire(p, [missing_meanwhile(p.health, p.model)])
    with pytest.raises(ProviderError) as ei:
        p.complete(MSGS)
    msg = str(ei.value)
    assert "model not available (404), skipped for" in msg and "congested upstream, skipped" not in msg
    assert len(c[0].calls) == 1 and sleeps == [] and classify(msg) == "missing"
    assert status.health_dict(p.health)["state"] == "missing" and status.health_dict(p.health)["until"] > 1700
    # in a chain: the main model's part names its 404 hold; the backup, the last link, is congested twice
    status.reset()
    reg = registry([MAIN, BACKUP])
    ch = reg.get("llm")
    h = ch.links[0].health
    wire(ch, **{s(MAIN): [missing_meanwhile(h, MAIN)], s(BACKUP): [HOSTS_429]})
    with pytest.raises(ProviderError) as ei:
        ch.complete(MSGS)
    first = str(ei.value).split("; ")[0]
    assert first.startswith(f"all model links failed: [Qwen3.8-27B] {MAIN}: model not available (404), skipped for")
    assert "congested upstream, skipped" not in first and classify(first) == "missing"
    snap = status.snapshot(reg)[0]
    assert snap["state"] == "missing" and snap["until"] > 1700
    # a 5xx, or a 402 with its shorter hold, in flight while a longer hold was opened: the error names that hold too
    for kept, meanwhile, got, phrase in (
        ("no_credits", 600, http_error(502, "Bad gateway"), "no credits (402), skipped for"),
        ("missing", 1800, NO_MONEY, "model not available (404), skipped for"),
    ):
        status.reset()
        ch = registry([MAIN, BACKUP]).get("llm")
        h = ch.links[0].health

        def opened_meanwhile(h=h, kept=kept, meanwhile=meanwhile, got=got):
            status.fail(h, kept, f"{MAIN}: {status.PHRASES[kept]} on the balance", hold_s=meanwhile)
            return got

        wire(ch, **{s(MAIN): [opened_meanwhile], s(BACKUP): [http_error(401, "Неверный API-ключ")]})
        with pytest.raises(ProviderError) as ei:
            ch.complete(MSGS)
        first = str(ei.value).split("; ")[0]
        assert phrase in first and "502" not in first and "Недостаточно средств" not in first and classify(first) == kept
        assert status.health_dict(h)["state"] == kept


def test_a_chain_link_whose_429s_were_in_flight_during_a_success_is_not_held(sleeps):
    ch = registry([MAIN, BACKUP]).get("llm")
    h = ch.links[0].health

    def answered_meanwhile():
        status.record_ok(h)  # a parallel variant got an answer from the same model meanwhile
        return HOSTS_429

    c = wire(ch, **{s(MAIN): [answered_meanwhile], s(BACKUP): [answer()]})
    for _ in range(3):
        ch.complete(MSGS)
    assert len(c[MAIN].calls) == 3 and status.blocked(h) is None and h.strikes == 0


# ---------------------------------------------------------------------------------------------- status for the UI


def test_status_snapshot_reports_every_link_in_chain_order():
    reg = registry([MAIN, BACKUP, THIRD, FOURTH], roles=("llm", "vlm"))
    llm, vlm = reg.get("llm"), reg.get("vlm")
    assert [x["state"] for x in status.snapshot(reg)] == ["unknown"] * 4
    wire(llm, **{s(MAIN): [NO_MONEY], s(BACKUP): [HOSTS_429], s(THIRD): [answer()]})
    cv = wire(vlm, **{s(THIRD): [answer()]})
    llm.complete(MSGS)
    llm.complete(MSGS)  # the second hosts' 429 of the backup opens its hold
    vlm.complete(MSGS)  # the vlm role shares the holds: straight to the third model
    assert len(cv[MAIN].calls) == 0 and len(cv[BACKUP].calls) == 0 and len(cv[THIRD].calls) == 1
    snap = status.snapshot(reg)
    assert all(set(x) == SNAPSHOT_FIELDS for x in snap)  # no pools: no «free» flag
    assert [x["model"] for x in snap] == [MAIN, BACKUP, THIRD, FOURTH]
    assert [x["state"] for x in snap] == ["no_credits", "congested", "ok", "unknown"]
    assert all(x["roles"] == ["llm", "vlm"] for x in snap)
    assert all(x["host"] == "polza.example.invalid" for x in snap)
    main, backup, third, moe = snap
    assert not main["available"] and 590 < main["until"] <= 600 and "no credits (402)" in main["last_error"]
    assert not backup["available"] and 110 < backup["until"] <= 120 and main["last_ok"] is None
    assert third["available"] and third["until"] is None and third["last_ok"] and third["label"] == "Third model"
    assert [main["label"], backup["label"], moe["label"]] == ["Qwen3.8-27B", "Qwen3.6-27B", "Fourth model"]
    assert moe["last_error"] == "" and moe["until"] is None
    bound = status.snapshot(reg.with_deadline(time.monotonic() + 60), role="vlm")
    assert [(x["model"], x["state"], x["roles"]) for x in bound] == [(x["model"], x["state"], ["vlm"]) for x in snap]
    assert "pza_" not in repr(snap) and "chain_0000" not in repr(snap)  # the key never reaches the UI
    assert status.snapshot(ProviderRegistry.mock({})) == []
    assert not hasattr(status, "block_pool")


def test_keys_are_masked_in_errors_and_in_the_chain_summary():
    key = "pza_0123456789abcdef0123456789abcdef"
    ch = registry([MAIN, BACKUP], key=key).get("llm")
    leak = http_error(400, f"bad request for key {key} and sk-or-v1-ABCDEFGHIJKLMNOPQRSTUVWX0123 (Bearer abcdefghijklmnop1234) tok_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
    wire(ch, **{s(MAIN): [leak], s(BACKUP): [leak]})
    with pytest.raises(ProviderError) as ei:
        ch.complete(MSGS)
    text = str(ei.value) + repr(status.snapshot())
    assert key not in text and "0123456789abcdef" not in text and "ABCDEFGHIJKLMNOP" not in text and "abcdefghijklmnop1234" not in text
    assert "[redacted]" in text


def test_every_state_has_its_wording():
    assert set(status.PHRASES) == {"congested", "rate", "quota", "no_credits", "auth", "missing", "off"}
    assert set(status.STATES) == {"ok", "unknown", "congested", "rate", "quota", "no_credits", "auth", "missing", "error", "off"}
    for state, phrase in status.PHRASES.items():
        assert phrase in str(oc._unavailable("m", state, "reason", 30))


def test_the_default_labels_are_human():
    assert oc.default_label(MAIN) == "Qwen3.8-27B" and oc.default_label(BACKUP) == "Qwen3.6-27B"
    assert oc.default_label(MAIN, POLZA_BASE_URL) == "Qwen3.8-27B"  # no host in the name: every model is on Polza
    assert oc.default_label(VK_MODEL, VK) == "Qwen3.8-27B" and oc.default_label("Qwen/Qwen3.8-27B") == "Qwen3.8-27B"
    assert oc.default_label(THIRD, POLZA_BASE_URL) == "Third model" and oc.default_label(FOURTH) == "Fourth model"
    # a configured label wins, and a default one never replaces it on the model's record
    key = "pza_test_label_000004"
    p = polza(BACKUP, key=key, label="Запасная Qwen")
    assert p.label == "Запасная Qwen" and p.health.label == "Запасная Qwen"
    assert polza(BACKUP, key=key).health.label == "Запасная Qwen"


# ---------------------------------------------------------------------------------------------- shipped configs


def test_the_default_config_is_qwen38_then_qwen36_on_polza(config_env):
    reg = ProviderRegistry.from_yaml(DEFAULT)
    assert reg.limits.requests_per_minute is None and reg.limits.time_budget_s == 210 and reg.limits.timeout_s == 120
    assert reg.limits.max_attempts == 3 and reg.limits.max_concurrency == 4
    assert sorted(reg.roles) == ["llm", "vlm"]  # pictures (t2i) are built by verstka/images
    llm, vlm = reg.get("llm"), reg.get("vlm")
    assert isinstance(llm, ChainProvider) and isinstance(vlm, ChainProvider)
    for ch in (llm, vlm):
        assert [(p.model, p.label, p.name) for p in ch.links] == [(MAIN, "Qwen3.8-27B", "polza"), (BACKUP, "Qwen3.6-27B", "polza")]
        for p in ch.links:
            assert p.base_url == POLZA_BASE_URL and p.api_key == "pza_test_config_000001" and not p.off
            assert p.json_mode is False and p.exclude_quantizations == ("fp4",) and p.extra_body == {"reasoning": {"effort": "none"}}
            assert p.system_suffix is None and p._limiter is None and p.max_attempts == 3 and p.timeout_s == 120
    assert all(v.health is m.health for v, m in zip(vlm.links, llm.links))  # llm and vlm share the records
    assert llm.model == MAIN and llm.label == "Qwen3.8-27B" and llm.api_key == "pza_test_config_000001"
    assert reg.describe()["llm"] == {
        "backend": "chain",
        "model": MAIN,
        "chain": [{"backend": "polza", "model": MAIN, "label": "Qwen3.8-27B", "off": False}, {"backend": "polza", "model": BACKUP, "label": "Qwen3.6-27B", "off": False}],
    }
    snap = status.snapshot(reg)
    assert [(x["label"], x["host"], x["state"], x["roles"]) for x in snap] == [
        ("Qwen3.8-27B", "polza.ai", "unknown", ["llm", "vlm"]),
        ("Qwen3.6-27B", "polza.ai", "unknown", ["llm", "vlm"]),
    ]


def test_the_default_config_without_polzas_key_is_off(sleeps):
    reg = ProviderRegistry.from_yaml(DEFAULT)  # POLZA_API_KEY is not set
    ch = reg.get("llm")
    assert all(p.off for p in ch.links) and ch.api_key == "" and ch.model == MAIN and ch.label == "Qwen3.8-27B"
    wire(ch)  # a request would fail the test
    with pytest.raises(ProviderError, match=r"not configured \(no API key\)"):
        ch.complete(MSGS)
    assert [x["state"] for x in status.snapshot(reg, role="llm")] == ["off", "off"] and sleeps == []


def test_the_default_config_end_to_end_with_fake_hosts(config_env, sleeps):
    """The main model has no money on the balance: the backup answers at once, nothing waits."""
    ch = ProviderRegistry.from_yaml(DEFAULT).get("llm")
    c = wire(ch, [NO_MONEY], [answer("backup", cost=0.04)])
    r = ch.complete(MSGS)
    assert r.model == BACKUP and r.label == "Qwen3.6-27B" and r.text == "backup" and r.usage.cost_rub == 0.04 and sleeps == []
    sent = c[0].calls[0]
    assert sent["model"] == MAIN and sent["extra_body"] == {"reasoning": {"effort": "none"}} and "response_format" not in sent
    # the main model's 402 holds it for ten minutes: the next call goes straight to the backup
    ch.complete(MSGS)
    assert [len(c[i].calls) for i in range(2)] == [1, 2]


def test_the_default_config_sends_reasoning_off_and_leaves_the_4_bit_hosts_out(config_env, catalog, sleeps):
    ch = ProviderRegistry.from_yaml(DEFAULT).get("llm")
    c = wire(ch, [NO_MONEY], [answer("backup")])
    assert ch.complete(MSGS).text == "backup" and sleeps == []
    assert c[0].calls[0]["extra_body"] == {"reasoning": {"effort": "none"}, "provider": {"ignore": ["morph/fp4", "Novita/FP4"]}}
    assert c[1].calls[0]["extra_body"] == {"reasoning": {"effort": "none"}, "provider": {"ignore": ["nebius/fp4"]}}
    assert catalog.reads == [MAIN, BACKUP]
    assert [p.extra_body for p in ch.links] == [{"reasoning": {"effort": "none"}}] * 2  # the config is not changed


def test_the_ui_names_each_failed_link_by_its_label(config_env, sleeps, caplog):
    """Both models run on Polza: the label the chain puts before each failed link tells the notice which model failed
    and why — the main model's spent key limit and the backup's refused key are two different fixes for the owner."""
    from verstka.api.model_status import chain_context, collect_links, planner_info

    reg = ProviderRegistry.from_yaml(DEFAULT)
    ch = reg.get("llm")
    wire(ch, [KEY_LIMIT], [http_error(401, "Неверный API-ключ")])
    with pytest.raises(ProviderError) as ei:
        ch.complete(MSGS)
    text = str(ei.value)
    assert f"[Qwen3.8-27B] {MAIN}: no credits (402)" in text and f"[Qwen3.6-27B] {BACKUP}: access refused (401/403)" in text
    assert sleeps == []  # both are on hold: no second pass
    links, source = collect_links(reg)
    assert source == "status"
    assert [(x["label"], x["host"], x["state"]) for x in links] == [("Qwen3.8-27B", "polza.ai", "no_credits"), ("Qwen3.6-27B", "polza.ai", "auth")]
    ctx = chain_context(links, "configs/models.yaml")
    manifest = {"providers": {"llm": {"backend": "chain", "model": MAIN}}}

    def detail():
        return getattr(caplog.records[-1], "reason_detail", None)

    caplog.set_level(logging.INFO, logger="verstka.api.model_status")
    info = planner_info({"planned_by": "rules"}, {**manifest, "warnings": ["outline_planner failed, deterministic outline used: " + text]}, use_models=True, ctx=ctx)
    # the API's reason names no provider or key; the server log says which link failed and why
    assert info["reason_code"] == "auth" and info["reason"] == "модель недоступна" and detail() == "ключ доступа к Polza не подходит"
    assert info["advice"] == "Модель недоступна." and info["retryable"] is False
    assert "лимит ключа" in info["owner"] and "проверьте ключ POLZA_API_KEY" in info["owner"]  # both fixes, for the owner
    # the planner's warning keeps the first 160 characters: the main model's own part
    cut = planner_info({"planned_by": "rules"}, {**manifest, "warnings": ["outline_planner failed, deterministic outline used: " + text[:160]]}, use_models=True, ctx=ctx)
    assert cut["reason_code"] == "no_credits" and cut["reason"] == "модель недоступна"
    assert detail() == "на балансе Polza нет средств или исчерпан лимит расходов ключа"


def test_the_vk_config_is_one_model_on_vk_inference(vk_env):
    vk = ProviderRegistry.from_yaml(VK_CONFIG)
    assert sorted(vk.roles) == ["llm", "vlm"] and vk.limits.timeout_s == 180
    # every limit the Polza profile sets is set here too (the VK profile may only differ in its values)
    assert vk.limits.time_budget_s == ProviderRegistry.from_yaml(DEFAULT).limits.time_budget_s == 210 and vk.limits.max_concurrency == 8
    assert set(yaml.safe_load(DEFAULT.read_text(encoding="utf-8"))["limits"]) <= set(yaml.safe_load(VK_CONFIG.read_text(encoding="utf-8"))["limits"])
    for role in ("llm", "vlm"):
        p = vk.get(role)
        assert isinstance(p, oc.OpenAICompatProvider) and p.name == "openai_compat" and p.model == VK_FINAL_MODEL  # one model, no chain
        assert p.base_url == VK and p.api_key == VK_KEY and p.label == "Qwen3.8-27B (VK)" and not p.off
        assert p.headers == {"Project-ID": VK_PROJECT}  # the project header of the organisers' inference
        assert p.extra_body == {"chat_template_kwargs": {"enable_thinking": False}} and p.system_suffix == "/no_think"
        assert p.exclude_quantizations == () and p.timeout_s == 180 and p.max_attempts == 3
    assert vk.get("vlm").health is vk.get("llm").health


@pytest.mark.parametrize("env", [{}, {"VK_PROJECT_ID": VK_PROJECT}])
def test_the_vk_config_without_its_key_is_off(monkeypatch, sleeps, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    reg = ProviderRegistry.from_yaml(VK_CONFIG)
    for role in ("llm", "vlm"):
        p = reg.get(role)
        assert isinstance(p, oc.OpenAICompatProvider) and p.off and p.api_key == ""
    p = reg.get("llm")
    wire(p)  # a request would fail the test
    with pytest.raises(ProviderError, match=r"not configured \(no API key\)"):
        p.complete(MSGS)
    assert status.snapshot(reg, role="llm")[0]["state"] == "off" and sleeps == []


@pytest.mark.parametrize(
    "text, held",
    [
        ("Недостаточно средств: требуется 3.50 ₽, доступно 1.20 ₽, зарезервировано 25.00 ₽", True),
        ("Insufficient balance: required 3.5 RUB, available 1.2 RUB, 3.5 RUB reserved", True),
        ("Недостаточно средств: 25,00 ₽ уже зарезервировано выполняющимися запросами", True),
        ("Недостаточно средств: зарезервировано 0.00 ₽", False),
        # the key's limit: the reserve's return would cover the request — a short wait; it would not — the limit is spent
        ("Превышен лимит расходов ключа: требуется 3.50 ₽, доступно 0.00 ₽, зарезервировано 25.00 ₽", True),
        ("Превышен лимит расходов ключа: требуется 3.50 ₽, доступно 0.00 ₽, зарезервировано 1.00 ₽", False),
        ("Недостаточно средств: требуется 3.50 ₽, доступно 0.40 ₽, зарезервировано 2.00 ₽", False),
        ("Недостаточно средств на балансе", False),
        ("Превышен лимит расходов API-ключа", False),
    ],
)
def test_a_402_reserve_is_read_in_either_word_order(text, held):
    """The sum the requests in flight hold may come before or after its word: either way the 402 is a short wait, not
    an empty balance held for 10 minutes; a reserve of zero is an empty balance."""
    from verstka.providers.openai_compat import LinkUnavailable, TransientError, classify_error

    err = classify_error(http_error(402, text, error="INSUFFICIENT_BALANCE"), MAIN)
    if held:
        assert isinstance(err, TransientError) and "held by the requests in flight" in str(err)
    else:
        assert isinstance(err, LinkUnavailable) and err.state == "no_credits"


# ---------------------------------------------------------------------------- the swarm review of the migration


def test_a_400_on_polza_never_turns_the_models_thinking_back_on(sleeps):
    """Polza documents `reasoning` and `provider` (a host without a parameter drops it silently): its 400 is about the
    request — the link's extra_body stays, so the next request still asks for no thinking and no fp4 host."""
    p = polza(extra_body={"reasoning": {"effort": "none"}, "provider": {"ignore": ["morph/fp4"]}})
    c = wire(p, [http_error(400, "Invalid image in messages[0]"), answer("ok")])
    with pytest.raises(ProviderError):
        p.complete(MSGS)
    assert len(c[0].calls) == 1  # no retry without the body
    assert p.extra_body == {"reasoning": {"effort": "none"}, "provider": {"ignore": ["morph/fp4"]}}
    assert p.complete(MSGS).text == "ok"
    assert c[0].calls[-1]["extra_body"]["reasoning"] == {"effort": "none"}


def test_another_endpoint_drops_a_rejected_switch_only_once_the_retry_works_and_keeps_the_routing(sleeps):
    vk = single(extra_body={"chat_template_kwargs": {"enable_thinking": False}, "provider": {"only": ["x"]}})
    c = wire(vk, [http_error(400, "unknown field chat_template_kwargs"), http_error(400, "still bad")])
    with pytest.raises(ProviderError):
        vk.complete(MSGS)
    assert vk.extra_body["chat_template_kwargs"] == {"enable_thinking": False}  # the retry failed: nothing is dropped
    assert c[0].calls[1]["extra_body"] == {"provider": {"only": ["x"]}}  # retried without the switch, routing kept
    c[0].script = [http_error(400, "unknown field chat_template_kwargs"), answer("ok")]
    assert vk.complete(MSGS).text == "ok"
    assert vk.extra_body == {"provider": {"only": ["x"]}}  # it worked: the switch stays off for the run


@pytest.mark.parametrize(
    "retry_after, daily",
    # a minute's window ends within a minute (a few seconds more for the clocks); a longer one is the day's — minutes
    # before midnight by Moscow time included
    [("30", False), ("59", False), ("90", False), ("120", True), ("240", True), ("9000", True), ("43200", True)],
)
def test_the_window_of_polzas_own_429_is_its_retry_after_whatever_the_words(retry_after, daily):
    """Polza documents one wording for both caps («Достигнут минутный (дневной) лимит запросов к модели»): the seconds
    of Retry-After — to the next minute or to midnight by Moscow time — tell the windows apart."""
    e = oc.classify_error(http_error(429, "Достигнут минутный (дневной) лимит запросов к модели. Повторите позже.", {"retry-after": retry_after}), MAIN)
    assert isinstance(e, oc.RateLimited) and e.daily is daily and not e.upstream


@pytest.mark.parametrize(
    "code, kind, state",
    [
        ("BAD_REQUEST", "plain", None),
        ("UNAUTHORIZED", "unavailable", "auth"),
        ("api_key_revoked", "unavailable", "auth"),
        ("INSUFFICIENT_BALANCE", "unavailable", "no_credits"),
        ("FORBIDDEN", "unavailable", "auth"),
        ("NOT_FOUND", "unavailable", "missing"),
        ("REQUEST_TIMEOUT", "transient", "congested"),
        ("CONFLICT", "plain", None),
        ("PAYLOAD_TOO_LARGE", "plain", None),
        ("TOO_MANY_REQUESTS", "rate", None),
        ("INTERNAL_ERROR", "transient", "congested"),
        ("BAD_GATEWAY", "transient", "congested"),
        ("SERVICE_UNAVAILABLE", "transient", "congested"),
    ],
)
def test_every_polza_error_code_inside_a_200_body_reads_as_its_status(code, kind, state):
    # a neutral message: the code alone decides (no wording to fall back on)
    body = SimpleNamespace(choices=None, usage=None, error={"code": code, "message": "Error", "metadata": {"provider_name": "phala"}})
    err = oc.classify_error(oc._body_error(body), MAIN)
    if kind == "plain":
        assert type(err) is ProviderError and err.no_retry and err.status_code == oc._POLZA_CODES[code]
    elif kind == "unavailable":
        assert isinstance(err, oc.LinkUnavailable) and err.state == state
    elif kind == "transient":
        assert isinstance(err, oc.TransientError) and err.state == state
    else:
        assert isinstance(err, oc.RateLimited) and err.upstream and not err.daily  # no Retry-After: the host's limit


def test_a_polza_error_code_inside_a_200_body_is_read_as_its_status():
    body = SimpleNamespace(choices=None, usage=None, error={"code": "TOO_MANY_REQUESTS", "message": "Провайдер модели ограничил частоту запросов", "metadata": {"provider_name": "phala"}})
    err = oc.classify_error(oc._body_error(body), MAIN)
    assert isinstance(err, oc.RateLimited) and err.upstream and "TOO_MANY_REQUESTS" in str(err)
    body = SimpleNamespace(choices=None, usage=None, error={"code": "INSUFFICIENT_BALANCE", "message": "Недостаточно средств"})
    assert oc.classify_error(oc._body_error(body), MAIN).state == "no_credits"
    # a 403 whose reason is moderation (metadata.reason) refuses this request, not the key
    body = SimpleNamespace(choices=None, usage=None, error={"code": "FORBIDDEN", "message": "Forbidden", "metadata": {"reason": "content moderation"}})
    err = oc.classify_error(oc._body_error(body), MAIN)
    assert type(err) is ProviderError and err.no_retry and "refused by moderation (403)" in str(err)
    body = SimpleNamespace(choices=None, usage=None, error={"code": "FORBIDDEN", "message": "Forbidden"})
    assert oc.classify_error(oc._body_error(body), MAIN).state == "auth"


def test_the_catalog_is_read_again_after_its_ttl_and_an_empty_answer_is_retried_soon(catalog, monkeypatch, caplog):
    now = [1000.0]
    monkeypatch.setattr(oc.time, "monotonic", lambda: now[0])
    assert oc.excluded_hosts(MAIN, ("fp4",)) == ["morph/fp4", "Novita/FP4"]
    now[0] += oc._CATALOG_TTL_S - 1
    oc.excluded_hosts(MAIN, ("fp4",))
    assert catalog.reads == [MAIN]  # still fresh
    now[0] += 2
    oc.excluded_hosts(MAIN, ("fp4",))
    assert catalog.reads == [MAIN, MAIN]  # hosts come and go: read again
    oc.excluded_hosts(MAIN, ("fp4", "int4"))
    assert catalog.reads == [MAIN, MAIN, MAIN]  # another floor, another entry
    catalog.hosts[BACKUP] = []
    with caplog.at_level(logging.WARNING):
        assert oc.excluded_hosts(BACKUP, ("fp4",)) == []
    assert "lists no hosts" in caplog.text
    now[0] += oc._CATALOG_RETRY_S + 1
    oc.excluded_hosts(BACKUP, ("fp4",))
    assert catalog.reads.count(BACKUP) == 2  # an empty answer is not trusted for hours


@pytest.mark.parametrize("value, on", [("1", False), ("true", False), ("0", True), ("false", True), ("", True)])
def test_the_no_catalog_switch_reads_its_value(catalog, monkeypatch, value, on):
    monkeypatch.setenv("VERSTKA_NO_CATALOG", value)
    assert bool(oc.excluded_hosts(MAIN, ("fp4",))) is on


def test_a_429_that_names_its_host_is_the_hosts_limit_even_with_a_retry_after():
    # Polza's own caps name no host; one that names it (metadata.provider_name) is the host's limit
    e = oc.classify_error(http_error(429, "Too many requests", {"retry-after": "30"}, host="deepinfra"), MAIN)
    assert isinstance(e, oc.RateLimited) and e.upstream and not e.daily
    body = SimpleNamespace(choices=None, usage=None, error={"code": "TOO_MANY_REQUESTS", "message": "Too many requests", "metadata": {"provider_name": "phala"}})
    e = oc.classify_error(oc._body_error(body), MAIN)
    assert isinstance(e, oc.RateLimited) and e.upstream


def test_a_402_over_the_keys_limit_that_the_reserve_would_not_cover_says_the_limit_is_spent():
    text = "Превышен лимит расходов ключа: требуется 3.50 ₽, доступно 0.00 ₽, зарезервировано 1.00 ₽"
    err = oc.classify_error(http_error(402, text), MAIN)
    assert isinstance(err, oc.LinkUnavailable) and err.state == "no_credits" and "spending limit of the key is spent" in str(err)


def test_calls_side_by_side_wait_for_one_catalog_read(catalog, monkeypatch):
    import threading

    fake, gate, started = oc._fetch_hosts, threading.Event(), threading.Event()

    def slow(model, timeout=8.0):
        started.set()
        gate.wait(5)
        return fake(model, timeout)

    monkeypatch.setattr(oc, "_fetch_hosts", slow)
    got: list = []
    threads = [threading.Thread(target=lambda: got.append(oc.excluded_hosts(MAIN, ("fp4",)))) for _ in range(4)]
    for th in threads:
        th.start()
    assert started.wait(5)
    threading.Event().wait(0.2)  # the other three reach the catalog while the first one reads it
    gate.set()
    for th in threads:
        th.join(5)
    assert catalog.reads == [MAIN] and got == [["morph/fp4", "Novita/FP4"]] * 4


def test_no_catalog_read_runs_past_the_time_its_request_needs(catalog):
    soon = time.monotonic() + oc._MIN_REQUEST_S + 0.5
    assert oc.excluded_hosts(MAIN, ("fp4",), deadline=soon) == [] and catalog.reads == []  # unfiltered this time
    assert oc.excluded_hosts(MAIN, ("fp4",)) == ["morph/fp4", "Novita/FP4"] and catalog.reads == [MAIN]  # read later
