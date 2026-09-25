"""GET /api/models/status and the plain-Russian reasons of a deck planned without the model (mocks only, no network)."""

import importlib
import json
import logging
import sys
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verstka.api.model_status import CONTRACT_PHRASES, ChainContext, advice, chain_context, generation_planner, model_label, planner_info, reason_code, reason_text, summarize
from verstka.providers.base import ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry

QWEN = "qwen/qwen3.8-27b:free"
QWEN_PAID = "qwen/qwen3.8-27b"
GEMMA = "google/gemma-4-31b-it:free"
OR = "openrouter.ai"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"
SHORT = "Итоги пилота «Умные сводки» за второй квартал: время на чтение чатов сократилось с 47 до 29 минут в день."
CONGESTED = [
    "data_extractor failed, using regex facts: qwen/qwen3.8-27b:free: the model host is congested upstream, deterministic steps for now (Error code: 429 - {'error': {'message': 'Provider returned error', 'co",
    "outline_planner failed, deterministic outline used: qwen/qwen3.8-27b:free: the model host is congested upstream, deterministic steps for now (marked earlier)",
    "slide 1 (sl1): заголовок набран 36 пт (3 стр.) при 54 пт в образце",
]
FREE_ONLY = ChainContext(openrouter=True, free=True, paid_label=None, config="configs/models.free.yaml")
WITH_PAID = ChainContext(openrouter=True, free=True, paid_label="Qwen3.8-27B", config="configs/models.yaml")
PLANNER_FAILED = "outline_planner failed, deterministic outline used: "


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("VERSTKA_WORKSPACE", str(tmp_path / "ws"))
    import verstka.api.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app), app_module


def _status_module(monkeypatch, links):
    """verstka.providers.status replaced by a fake whose snapshot() returns `links`."""
    import verstka.providers as pkg

    fake = types.ModuleType("verstka.providers.status")
    calls = []

    def snapshot(providers=None, role=None):  # the signature of verstka.providers.status.snapshot
        calls.append(role)
        return links

    fake.snapshot = snapshot
    fake.calls = calls
    monkeypatch.setitem(sys.modules, "verstka.providers.status", fake)
    monkeypatch.setattr(pkg, "status", fake, raising=False)


def _openrouter_registry(model=QWEN, key="test-key-not-real", base_url="https://openrouter.ai/api/v1"):
    cfg = {"roles": {"llm": {"backend": "openai_compat", "model": model, "base_url": base_url, "api_key": key}}}
    return ProviderRegistry.from_config(cfg)


def _link(model, state, host=OR, **kw):
    return {"model": model, "host": host, "state": state, "free": model.endswith(":free"), **kw}


# ---------------------------------------------------------------------------- reason mapping


@pytest.mark.parametrize(
    "warning, code",
    [
        (CONGESTED[1], "congested"),
        (PLANNER_FAILED + "Error code: 429 - {'error': {'message': 'Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day'", "quota"),
        (PLANNER_FAILED + "qwen/qwen3.8-27b:free: daily request quota of the provider is spent", "quota"),
        (PLANNER_FAILED + "Error code: 402 - {'error': {'message': 'This request requires more credits, or fewer max_tokens.", "no_credits"),
        (PLANNER_FAILED + "Error code: 403 - {'error': {'message': 'Key limit exceeded (total limit)'", "no_credits"),
        (PLANNER_FAILED + "qwen/qwen3.8-27b: time budget of the generation is spent (no answer yet)", "timeout"),
        # the budget ran out while waiting out a 429 passed on from the host: the cause is congestion
        (PLANNER_FAILED + "qwen/qwen3.8-27b:free: time budget of the generation is spent, no room to wait out a 429 (Error code: 429 - {'error': {'message': 'Provider returned error'", "congested"),
        # a 400 wrapped by OpenRouter as «Provider returned error» is not congestion: retrying does not help
        (PLANNER_FAILED + "qwen/qwen3.8-27b:free: Error code: 400 - {'error': {'message': 'Provider returned error', 'code': 400, 'metadata': {'raw': 'upstream: context too long'", "error"),
        (PLANNER_FAILED + "qwen/qwen3.8-27b:free: Error code: 502 - {'error': {'message': 'Bad gateway'", "congested"),
        (PLANNER_FAILED + "qwen/qwen3.8-27b:free: 503 server error (Service Unavailable)", "congested"),
        (PLANNER_FAILED + "no API key configured for model qwen at https://openrouter.ai/api/v1", "off"),
        ("outline_planner answer rejected (2 slides), deterministic outline used", "rejected"),
        (PLANNER_FAILED + "qwen: no valid completion after 3 attempts: Connection error.", "unreachable"),
        ("no LLM provider: deterministic outline", "off"),
        # per-minute cap ≠ daily quota
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b:free: per-minute request cap of the account (Error code: 429 - Rate limit exceeded: free-models-per-min.)", "rate"),
        (PLANNER_FAILED + "all model links failed: google/gemma-4-31b-it:free: request quota of the account is spent, skipped for 44 s more (per-minute request cap: Error code: 429", "rate"),
        (PLANNER_FAILED + "all model links failed: google/gemma-4-31b-it:free: request quota of the account is spent, skipped for 50 s more", "rate"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b:free: request quota of the account is spent, skipped for 3600 s more", "quota"),
        (PLANNER_FAILED + "Error code: 429 - {'error': {'message': 'Rate limit exceeded: free-models-per-min. '", "rate"),
        # the chain's messages, old and new wording
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b:free: the model host is congested upstream, skipped for 95 s more (429); qwen/qwen3.8-27b: 402 no credits on the account", "no_credits"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b:free: the model host is congested upstream, skipped for 95 s more (429)", "congested"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen9-27b: 404 no such model or no endpoint serves it", "missing"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b: request timed out", "timeout"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b: 401 request refused, check the key", "auth"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b: no credits (402); qwen/qwen3.8-27b:free: congested upstream (429)", "no_credits"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b:free: daily request quota of OpenRouter is spent, skipped for 50000 s more", "quota"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b: access refused (401/403)", "auth"),
        (PLANNER_FAILED + "all model links failed: qwen/qwen3.8-27b: model not available (404)", "missing"),
        # a link waiting for its key is skipped, never the reason
        (PLANNER_FAILED + "all model links failed: qwen/qwen3-32b: not configured (no API key); qwen/qwen3.8-27b:free: congested upstream, skipped for 95 s more", "congested"),
        ("slide 3 (sl3): label widened by 4% of the slide for the heading", None),
    ],
)
def test_reason_code_from_warnings(warning, code):
    assert reason_code([warning]) == code


def test_reason_prefers_the_planners_own_failure_and_says_it_in_russian():
    assert reason_code(CONGESTED) == "congested"
    timeout = "data_extractor failed, using regex facts: qwen: time budget of the generation is spent (no answer yet)"
    rejected = "outline_planner answer rejected (2 slides), deterministic outline used"
    # the planner answered but its plan was rejected: that is why the rules planned, whatever the data step did
    assert reason_code([timeout, rejected]) == "rejected"
    daily = "data_extractor failed, using regex facts: Error code: 429 - free-models-per-day"
    assert reason_code([timeout, daily]) == "quota"  # no planner warning: the other steps tell
    assert reason_text("congested") == "бесплатные модели OpenRouter сейчас перегружены"
    assert reason_text("no_credits") == "на счёте OpenRouter нет средств для платной модели"
    assert reason_text("quota") == "исчерпан дневной лимит бесплатных запросов OpenRouter"
    assert reason_text("rate") == "превышен лимит бесплатных запросов OpenRouter в минуту"
    assert reason_text("error") == "модель вернула ошибку"
    assert "время на модель вышло" in reason_text("timeout")
    assert reason_text("congested", ChainContext(openrouter=False, free=False)) == "сервер модели сейчас перегружен"


def test_advice_depends_on_the_active_chain():
    # a paid OpenRouter link in the active config: topping up is enough
    paid = advice("congested", WITH_PAID)
    assert "пополните OpenRouter на $5–10 — платный Qwen3.8-27B отвечает стабильно" in paid
    # free models only: a top-up alone changes nothing, the paid model must be switched on
    free = advice("congested", FREE_ONLY)
    assert "платный Qwen3.8-27B отвечает стабильно" not in free
    assert "пополните OpenRouter на $5–10 и включите платную модель: configs/models.yaml" in free
    daily = advice("quota", FREE_ONLY)
    assert "после 03:00" in daily and "configs/models.yaml" in daily
    assert advice("rate", FREE_ONLY) == "Соберите ещё раз через минуту."  # the per-minute cap resets within a minute
    # a 400: the same inputs get the same answer — say what to fix, never «соберите ещё раз»
    bad = advice("error", FREE_ONLY)
    assert "сократите текст" in bad and "configs/models.free.yaml" in bad and "Соберите ещё раз" not in bad
    assert "Groq" not in (paid + free + daily)  # the optional Groq key is for the detailed hint only
    assert advice("congested", ChainContext(openrouter=False, free=False)) == "Соберите ещё раз через несколько минут."
    assert ".env" not in advice("auth", FREE_ONLY)


def test_model_labels():
    assert model_label(QWEN) == "Qwen3.8-27B"
    assert model_label("Qwen/Qwen3.8-27B") == "Qwen3.8-27B"
    assert model_label(GEMMA) == "Gemma 4 31B"
    assert model_label("google/gemma-4-26b-a4b-it:free") == "Gemma 4 26B-A4B"
    assert model_label("qwen/qwen3.6-35b-a3b") == "Qwen3.6-35B-A3B"
    assert model_label("qwen/qwen3-30b-a3b-instruct-2507") == "Qwen3-30B-A3B"
    assert model_label(None) is None


def test_planner_info_for_rules_and_model_plans():
    rm = {"warnings": CONGESTED, "providers": {"llm": {"backend": "openai_compat", "model": QWEN}}}
    info = planner_info({"planned_by": "rules"}, rm, use_models=True, ctx=FREE_ONLY)
    assert info["by_model"] is False and info["reason_code"] == "congested" and info["tried_label"] == "Qwen3.8-27B"
    assert info["reason"] == "бесплатные модели OpenRouter сейчас перегружены"
    assert "включите платную модель: configs/models.yaml" in info["advice"] and "платный Qwen3.8-27B отвечает" not in info["advice"]
    assert "платный Qwen3.8-27B отвечает стабильно" in planner_info({"planned_by": "rules"}, rm, use_models=True, ctx=WITH_PAID)["advice"]
    # the fallback chain answered with the backup model: the recorded model wins over the configured one
    ok = planner_info({"planned_by": "model"}, {**rm, "warnings": [], "planner": {"planned_by": "model", "model": GEMMA}}, use_models=True)
    assert ok["by_model"] and ok["model_label"] == "Gemma 4 31B" and ok["reason"] is None
    shared = planner_info({"planned_by": "shared:structured"}, {**rm, "planner": {"planned_by": "shared:structured", "model": QWEN}})
    assert shared["by_model"] and shared["model_label"] == "Qwen3.8-27B"
    off = planner_info({"planned_by": "rules"}, {"warnings": ["no LLM provider: deterministic outline"], "providers": {"llm": {"backend": "none"}}}, use_models=False)
    assert off["reason_code"] == "off" and off["advice"] is None
    g = generation_planner([{"planner": info}, {"planner": info}], use_models=True)
    assert g["by_model"] is False and g["reason_code"] == "congested"
    assert generation_planner([{"planner": info}, {"planner": ok}], use_models=True)["model_label"] == "Gemma 4 31B"


def test_no_failure_notice_without_evidence():
    """An older deck without planned_by and without model warnings, and a deck built from a supplied outline, are not
    shown as a model failure."""
    configured = {"providers": {"llm": {"backend": "openai_compat", "model": QWEN}}}
    old = planner_info({"title": "Т"}, {**configured, "warnings": []}, use_models=True, ctx=FREE_ONLY)
    assert old["by_model"] is None and old["reason_code"] is None and old["reason"] is None and old["advice"] is None
    g = generation_planner([{"planner": old}], use_models=True)
    assert g["by_model"] is None and g["reason"] is None
    # the same older deck with a recorded model failure: the rules planned it, and the warning says why
    failed = planner_info({"title": "Т"}, {**configured, "warnings": CONGESTED}, use_models=True, ctx=FREE_ONLY)
    assert failed["planned_by"] == "rules" and failed["reason_code"] == "congested"
    # an explicit rules plan without a model failure: no reason is made up
    quiet = planner_info({"planned_by": "rules"}, {**configured, "warnings": []}, use_models=True, ctx=FREE_ONLY)
    assert quiet["by_model"] is False and quiet["reason"] is None
    # a supplied outline: no model was asked to plan
    for sup in (planner_info({"planned_by": "rules"}, {**configured, "warnings": CONGESTED}, use_models=True, supplied=True),
                planner_info({"planned_by": "rules"}, {**configured, "planner": {"planned_by": "rules", "supplied": True}}, use_models=True)):
        assert sup["planned_by"] == "supplied" and sup["reason_code"] is None and sup["advice"] is None
    assert generation_planner([{"planner": sup}], use_models=True)["planned_by"] == "supplied"


# ---------------------------------------------------------------------------- GET /api/models/status


def test_status_without_a_configured_model(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry(key=""))
    st = c.get("/api/models/status").json()
    assert st["configured"] is False and st["state"] == "off"
    assert st["summary"] == "Модель не подключена · соберёт встроенный планировщик"
    assert st["active_model_label"] == "Qwen3.8-27B" and st["links"] == []


def test_status_uses_the_fallback_chain_snapshot(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [
        _link(QWEN, "congested", label="Qwen3.8-27B (бесплатно)", last_error="429 upstream, key sk-or-v1-0123456789abcdef", until=95, account="https://openrouter.ai/api/v1|12345678"),
        _link(GEMMA, "ok", label="Gemma 4 31B (бесплатно)", last_ok=time.time(), until=None),
    ])
    r = c.get("/api/models/status")
    assert r.status_code == 200
    st = r.json()
    assert st["source"] == "status" and st["state"] == "fallback"
    assert st["summary"] == "Модель: Qwen3.8-27B перегружена · отвечает запасная Gemma 4 31B"
    assert st["working_label"] == "Gemma 4 31B" and st["retry_in"] == 95 and st["retry_state"] == "congested"
    # the active chain has no paid link: say what to switch on, never «платный … отвечает стабильно»
    assert st["hint"].startswith("Презентацию соберёт запасная модель") and "configs/models.yaml" in st["hint"]
    assert "платный Qwen3.8-27B отвечает" not in st["hint"]
    assert [link["state"] for link in st["links"]] == ["congested", "ok"]
    body = r.text
    assert "0123456789abcdef" not in body and "account" not in st["links"][0]  # no key, no account id
    assert st["config"] and st["active_model_label"] == "Qwen3.8-27B" and st["host"] == OR
    assert sys.modules["verstka.providers.status"].calls[-1] == "llm"  # the llm chain, in chain order


def test_status_with_a_paid_link_and_the_optional_groq_key(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [
        _link(QWEN_PAID, "no_credits", label="Qwen3.8-27B (OpenRouter)", until=500, available=False),
        _link("qwen/qwen3-32b", "off", host="api.groq.com", label="Qwen3.8-27B (Groq)"),
        _link(QWEN, "ok", label="Qwen3.8-27B (бесплатно)", last_ok=time.time()),
    ])
    st = c.get("/api/models/status").json()
    assert st["state"] == "fallback"
    # two links share the short name: the backup's tag tells them apart and the line stays short
    assert st["summary"] == "Модель: Qwen3.8-27B — нет средств на счёте · отвечает бесплатная Qwen3.8-27B"
    assert len(st["summary"]) <= 80 and st["working_label"] == "бесплатная Qwen3.8-27B"
    assert st["advice"] == "Сейчас отвечает бесплатная Qwen3.8-27B — соберите ещё раз." and st["retryable"] is True
    assert "Пополните счёт OpenRouter на $5–10" in st["hint"]
    assert "бесплатный ключ Groq для той же Qwen3.8-27B — строка GROQ_API_KEY в .env" in st["hint"]
    assert "Groq" not in st["summary"]
    assert [link["state"] for link in st["links"]] == ["no_credits", "off", "ok"]
    assert st["links"][1]["available"] is False and st["links"][1]["until"] is None


def test_links_waiting_for_their_key_are_not_failures(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [_link("qwen/qwen3-32b", "off", host="api.groq.com", label="Qwen3.8-27B (Groq)"), _link(QWEN, "ok", label="Qwen3.8-27B (бесплатно)", last_ok=time.time())])
    st = c.get("/api/models/status").json()
    assert st["state"] == "ok" and st["summary"] == "Модель: Qwen3.8-27B — доступна" and st["hint"] is None
    assert st["active_model"] == QWEN


def test_status_all_links_down(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [_link(QWEN, "congested", until=60), _link(GEMMA, "quota", until=50000)])
    st = c.get("/api/models/status").json()
    assert st["state"] == "down"
    assert st["summary"] == "Модель недоступна · соберёт встроенный планировщик"
    assert st["retry_in"] == 60 and st["retry_state"] == "congested"
    assert "включите платную модель: configs/models.yaml" in st["hint"]
    _status_module(monkeypatch, [_link(QWEN, "ok", last_ok=time.time())])
    st = c.get("/api/models/status").json()
    assert st["state"] == "ok" and st["summary"] == "Модель: Qwen3.8-27B — доступна" and st["hint"] is None
    # the pause after a failure is over: the next deck tries the model again
    _status_module(monkeypatch, [_link(QWEN, "congested", available=True, until=0)])
    st = c.get("/api/models/status").json()
    assert st["state"] == "retry" and st["summary"] == "Модель: Qwen3.8-27B — недавно была перегружена, попробую снова"


def test_per_minute_cap_is_not_the_daily_quota(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [_link(QWEN, "rate", until=45, available=False, last_error="per-minute request cap: Error code: 429")])
    st = c.get("/api/models/status").json()
    assert st["state"] == "down" and st["retry_state"] == "rate" and st["retry_in"] == 45
    assert st["summary"] == "Модель: Qwen3.8-27B — лимит запросов в минуту · соберёт встроенный планировщик"
    assert st["hint"].startswith("Соберите ещё раз через минуту") and "03:00" not in st["hint"]
    # the status module records the per-minute cap as «rate»: a daily quota in its last minutes before 00:00 UTC
    # stays the daily quota (no guessing from the length of the pause)
    _status_module(monkeypatch, [_link(QWEN, "quota", until=40, available=False, last_error="daily request quota of the account is spent")])
    st = c.get("/api/models/status").json()
    assert st["links"][0]["state"] == "quota" and st["retry_state"] == "quota" and "дневной лимит исчерпан" in st["summary"]
    _status_module(monkeypatch, [_link(QWEN, "quota", until=50000, available=False, last_error="daily request quota of OpenRouter is spent")])
    st = c.get("/api/models/status").json()
    assert st["retry_state"] == "quota" and "дневной лимит исчерпан" in st["summary"] and "после 03:00" in st["hint"]


def test_a_bad_request_is_an_error_not_congestion(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [_link(QWEN, "error", until=30, available=False, last_error="Error code: 400 - Provider returned error")])
    st = c.get("/api/models/status").json()
    assert st["summary"] == "Модель: Qwen3.8-27B вернула ошибку · соберёт встроенный планировщик"
    assert "перегруж" not in st["summary"] and "перегруж" not in (st["hint"] or "")


def test_status_with_the_real_status_module(api, monkeypatch):
    """Links recorded by verstka.providers.status (the fallback chain's health) reach the UI in chain order."""
    status = pytest.importorskip("verstka.providers.status")
    c, mod = api
    tag = f"test-{time.time_ns()}"
    h_qwen = status.link(f"{tag}|qwen", QWEN, "Qwen3.8-27B (бесплатно)", f"{tag}|free")
    h_gemma = status.link(f"{tag}|gemma", GEMMA, "Gemma 4 31B (бесплатно)", f"{tag}|free")

    class Link:
        name = "openai_compat"
        api_key = "test-key-not-real"
        base_url = "https://openrouter.ai/api/v1"

        def __init__(self, model, health):
            self.model, self.health = model, health

    class Chain:
        name = "chain"
        model = QWEN
        api_key = "test-key-not-real"
        links = [Link(QWEN, h_qwen), Link(GEMMA, h_gemma)]

    monkeypatch.setattr(mod, "_providers", ProviderRegistry(roles={"llm": Chain()}, limits=ProviderLimits()))
    try:
        status.record_error(h_qwen, "congested", "Error 429: temporarily rate-limited upstream", hold_s=120)
        status.record_ok(h_gemma)
        st = c.get("/api/models/status").json()
        assert st["source"] == "status" and [link["model"] for link in st["links"]] == [QWEN, GEMMA]
        assert st["state"] == "fallback" and st["summary"] == "Модель: Qwen3.8-27B перегружена · отвечает запасная Gemma 4 31B"
        assert 100 <= st["retry_in"] <= 120 and st["links"][0]["available"] is False and st["links"][0]["host"] == OR
        status.record_error(h_gemma, "quota", "free-models-per-day", hold_s=3600)
        st = c.get("/api/models/status").json()
        assert st["state"] == "down" and "встроенный планировщик" in st["summary"]
    finally:
        status.record_ok(h_qwen)
        status.record_ok(h_gemma)


def test_a_broken_snapshot_is_logged_and_the_configured_links_shown(api, monkeypatch, caplog):
    import verstka.providers as pkg

    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    fake = types.ModuleType("verstka.providers.status")

    def snapshot(providers=None, role=None):
        raise RuntimeError("broken")

    fake.snapshot = snapshot
    monkeypatch.setitem(sys.modules, "verstka.providers.status", fake)
    monkeypatch.setattr(pkg, "status", fake, raising=False)
    with caplog.at_level(logging.WARNING, logger="verstka.api.model_status"):
        st = c.get("/api/models/status").json()
    assert "snapshot() failed" in caplog.text
    assert st["source"] == "config" and st["state"] == "unknown" and st["summary"] == "Модель: Qwen3.8-27B — подключена"


def test_status_host_never_carries_credentials(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry(base_url="https://user:secret-token-123@proxy.example.org:8443/v1"))
    _status_module(monkeypatch, [])
    r = c.get("/api/models/status")
    st = r.json()
    assert st["host"] == "proxy.example.org" and st["links"][0]["host"] == "proxy.example.org"
    assert "secret-token-123" not in r.text


def test_status_with_a_mock_model(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", ProviderRegistry.mock())
    st = c.get("/api/models/status").json()
    assert st["configured"] is True and st["state"] == "ok" and st["links"][0]["model"] == "mock-model"


def test_summarize_is_short_and_never_counts_off_links():
    links = [
        {"model": QWEN, "label": "Qwen3.8-27B (бесплатно)", "state": "congested", "available": False, "until": 90, "free": True, "host": OR},
        {"model": GEMMA, "label": "Gemma 4 31B (бесплатно)", "state": "unknown", "available": True, "until": None, "free": True, "host": OR},
    ]
    s = summarize(links, configured=True, ctx=chain_context(links))
    assert s["summary"] == "Модель: Qwen3.8-27B перегружена · попробую запасную Gemma 4 31B"
    off_only = [{**links[0], "state": "off", "available": False}]
    assert summarize(off_only, configured=True)["state"] == "off"


# ---------------------------------------------------------------------------- generation payload


def _fake_generation(mod, planned_by="rules", warnings=CONGESTED, planner=None, use_models=True, **meta):
    gid, gdir = mod.store.new_generation_dir()
    vdir = gdir / "structured"
    vdir.mkdir()
    (vdir / "deck.pptx").write_bytes(b"")
    outline = {"title": "Т", "strategy": "structured", "slides": []}
    if planned_by is not None:
        outline["planned_by"] = planned_by
    (vdir / "outline.json").write_text(json.dumps(outline), encoding="utf-8")
    rm = {"strategy": "structured", "providers": {"llm": {"backend": "openai_compat", "model": QWEN}}, "warnings": warnings}
    if planner:
        rm["planner"] = planner
    (vdir / "run_manifest.json").write_text(json.dumps(rm), encoding="utf-8")
    mod.store.write_generation_meta(gid, {"id": gid, "template_id": "t", "strategies": ["structured"], "use_models": use_models, "slides": 12, "status": "done", **meta})
    return gid


def test_generation_says_why_the_model_did_not_plan(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [_link(QWEN, "unknown", label="Qwen3.8-27B (бесплатно)"), _link(GEMMA, "unknown")])
    g = c.get(f"/api/generations/{_fake_generation(mod)}").json()
    v = g["variants"][0]
    assert v["planner"]["planned_by"] == "rules" and v["planner"]["reason_code"] == "congested"
    assert g["planner"]["by_model"] is False
    assert g["planner"]["reason"] == "бесплатные модели OpenRouter сейчас перегружены"
    assert g["planner"]["tried_label"] == "Qwen3.8-27B"
    # the advice follows the ACTIVE chain: free models only here
    assert "включите платную модель: configs/models.yaml" in g["planner"]["advice"]
    _status_module(monkeypatch, [_link(QWEN_PAID, "unknown", label="Qwen3.8-27B (OpenRouter)"), _link(QWEN, "unknown")])
    g = c.get(f"/api/generations/{_fake_generation(mod)}").json()
    assert "платный Qwen3.8-27B отвечает стабильно" in g["planner"]["advice"]
    g = c.get(f"/api/generations/{_fake_generation(mod, 'model', [], {'planned_by': 'model', 'model': GEMMA})}").json()
    assert g["planner"]["by_model"] is True and g["planner"]["model_label"] == "Gemma 4 31B"
    assert g["variants"][0]["planner"]["reason"] is None
    # an older deck: no planned_by, no model warnings — no failure to report
    g = c.get(f"/api/generations/{_fake_generation(mod, None, [])}").json()
    assert g["planner"]["by_model"] is None and g["planner"]["reason"] is None
    # a supplied outline: no model was asked
    g = c.get(f"/api/generations/{_fake_generation(mod, 'rules', CONGESTED, outline_supplied=True)}").json()
    assert g["planner"]["planned_by"] == "supplied" and g["planner"]["reason"] is None


# ---------------------------------------------------------------------------- pipeline records the answering model


def test_pipeline_records_the_model_that_answered():
    from verstka.pipeline.generate import _recording
    from verstka.providers.base import ChatMessage, CompletionResult, Usage

    class Chain:  # a fallback chain answering with its backup model
        name = "chain"
        model = QWEN

        def complete(self, messages, **kwargs):
            return CompletionResult(text="{}", parsed=None, usage=Usage(), model=GEMMA)

    reg = ProviderRegistry(roles={"llm": Chain()}, limits=ProviderLimits())
    rec, answered = _recording(reg)
    assert rec is not reg and rec.get("llm").model == QWEN
    rec.get("llm").complete([ChatMessage(role="user", content="hi")], temperature=0.1)
    assert answered == [GEMMA]
    assert reg.get("llm").__class__ is Chain  # the shared registry stays unwrapped
    assert _recording(None) == (None, [])


class _Backup(MockProvider):
    """A chain whose primary is congested: every answer comes from the backup model."""

    def complete(self, messages, **kwargs):
        res = super().complete(messages, **kwargs)
        res.model = GEMMA
        return res


def _only_compact_plans(messages):
    from verstka.schemas.outline import DeckOutline

    text = "\n".join(m.content for m in messages)
    if "Return the JSON plan only" in text:
        if "Стратегия «Компактный»" in text:
            demo = DeckOutline.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
            return {"title": demo.title, "slides": [s.model_dump(mode="json") for s in demo.slides]}
        raise ProviderError("all model links failed: qwen/qwen3.8-27b:free: congested upstream, skipped for 95 s more")
    if "List the issues" in text:
        return {"issues": []}
    return {"facts": [], "series": [], "tables": []}


def _backup_registry() -> ProviderRegistry:
    p = _Backup(_only_compact_plans, model=QWEN)
    return ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=1))


def test_pipeline_writes_the_planner_model_for_own_and_shared_variants(simple_deck, tmp_path):
    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import parse_brief_text
    from verstka.skills_registry.registry import SkillsRegistry

    res = generate_variants(simple_deck, brief=parse_brief_text(SHORT), strategies=["structured", "compact"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", providers=_backup_registry(), skills=SkillsRegistry.load(), use_vlm=False, audit=False, autofix=False, exports=[], render_images=False)
    by = {v.strategy: v for v in res.variants}
    assert by["compact"].planner == {"planned_by": "model", "model": GEMMA}
    assert by["structured"].planner == {"planned_by": "shared:compact", "model": GEMMA}  # the donor's model
    for name in ("structured", "compact"):
        rm = json.loads((tmp_path / "out" / name / "run_manifest.json").read_text(encoding="utf-8"))
        assert rm["planner"]["model"] == GEMMA and rm["planner"]["planned_by"] == by[name].planner["planned_by"]


def _wait(client, job_id, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.3)
    raise TimeoutError(job_id)


def test_post_generation_records_who_planned(api, monkeypatch, simple_deck):
    c, mod = api
    with open(simple_deck, "rb") as f:
        r = c.post("/api/templates", files={"file": ("simple.pptx", f, "application/octet-stream")}, data={"use_models": "false"})
    job = _wait(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    tid = job["result"]["template_id"]
    monkeypatch.setattr(mod, "_providers", _backup_registry())
    body = {"template_id": tid, "brief": SHORT, "strategies": ["structured", "compact"], "use_models": True, "audit_models": False, "autofix": False, "exports": []}
    r = c.post("/api/generations", json=body)
    gid = r.json()["generation_id"]
    job = _wait(c, r.json()["job_id"])
    assert job["status"] == "done", job["error"]
    meta = json.loads((mod.store.generation_dir(gid) / "generation.json").read_text(encoding="utf-8"))
    assert meta["summary"]["compact"]["planned_by"] == "model" and meta["summary"]["structured"]["planned_by"] == "shared:compact"
    assert meta["summary"]["structured"]["model"] == GEMMA and meta["summary"]["structured"]["reason"] is None
    assert meta["planner"]["by_model"] is True and meta["planner"]["model_label"] == "Gemma 4 31B"
    # the request's switches are kept: «Собрать ещё раз» repeats the deck with the same inputs
    assert meta["audit_models"] is False and meta["autofix"] is False and meta["exports"] == [] and meta["outline_supplied"] is False
    # a supplied outline: the plan is the person's own, no model failure is reported
    outline = json.loads(FIXTURE.read_text(encoding="utf-8"))
    r = c.post("/api/generations", json={"template_id": tid, "outline": outline, "strategies": ["structured"], "use_models": True, "autofix": False, "exports": []})
    gid2 = r.json()["generation_id"]
    assert _wait(c, r.json()["job_id"])["status"] == "done"
    g = c.get(f"/api/generations/{gid2}").json()
    assert g["outline_supplied"] is True and g["planner"]["planned_by"] == "supplied" and g["planner"]["reason"] is None
    assert g["variants"][0]["run_manifest"]["planner"]["supplied"] is True


# ---------------------------------------------------------------------------- fix round: rules, links, retry, texts

QWEN_GROQ_HOST = "api.groq.com"
# the links of configs/models.yaml: the same model id runs on OpenRouter (paid) and on Groq
FULL_CHAIN = [
    _link(QWEN_PAID, "unknown", label="Qwen3.8-27B (OpenRouter)"),
    _link(QWEN_PAID, "unknown", host=QWEN_GROQ_HOST, label="Qwen3.8-27B (Groq)", free=True),
    _link(QWEN, "unknown", label="Qwen3.8-27B (бесплатно)"),
    _link("Qwen/Qwen3-32B", "unknown", host="foundation-models.api.cloud.ru", label="Qwen3 32B (Cloud.ru)"),
    _link(GEMMA, "unknown", label="Gemma 4 31B (бесплатно)"),
]
FULL = chain_context(FULL_CHAIN, "configs/models.yaml")
CONFIGURED = {"providers": {"llm": {"backend": "openai_compat", "model": QWEN}}}
# 20260923-215708-5fdf55 «structured»: the data step hit a 429, the fact check ran out of time — the model planned it
OLD_MODEL_PLANNED = [
    "data_extractor failed, using regex facts: qwen/qwen3.8-27b:free: no valid completion after 3 attempts: Error code: 429 - {'error': {'message': 'Provider returned error', 'code': 429, 'metadata': {'raw':",
    "fact_checker skipped: qwen/qwen3.8-27b:free: time budget of the generation is spent (no answer yet)",
]


def _rules(warning, ctx=FULL):
    return planner_info({"planned_by": "rules"}, {**CONFIGURED, "warnings": [PLANNER_FAILED + warning]}, use_models=True, ctx=ctx)


def test_contract_phrases_are_the_status_modules():
    status = pytest.importorskip("verstka.providers.status")
    assert CONTRACT_PHRASES == {k: v for k, v in status.PHRASES.items() if k in CONTRACT_PHRASES}
    assert set(CONTRACT_PHRASES) == set(status.PHRASES)


@pytest.mark.parametrize(
    "warning, code",
    [
        # the seconds of a hold are never read as a status code
        ("all model links failed: qwen/qwen3.8-27b: model not available (404), skipped for 402 s more (qwen/qwen3.8-27b: model not available (404): no such model)", "missing"),
        ("all model links failed: qwen/qwen3.8-27b: model not available (404), skipped for 401 s more", "missing"),
        ("all model links failed: qwen/qwen3.8-27b: access refused (401/403), skipped for 404 s more", "auth"),
        ("all model links failed: qwen/qwen3.8-27b:free: congested upstream, skipped for 403 s more", "congested"),
        ("all model links failed: qwen/qwen3.8-27b:free: per-minute request cap of the account, retry in 402 s (Error code: 429 - Rate limit exceeded: free-models-per-min.)", "rate"),
        ("all model links failed: qwen/qwen3.8-27b:free: per-minute request cap of the account (20/min), next slot in 401 s", "rate"),
        ("all model links failed: qwen/qwen3.8-27b: the model did not answer, skipped for 402 s more (qwen/qwen3.8-27b: connection error (Connection refused))", "unreachable"),
        # the contract wording first, then the codes: a 403 that is a spent key limit is «no credits»
        ("all model links failed: qwen/qwen3.8-27b: no credits (402): the spending limit of the key is reached, HTTP 403 (Key limit exceeded)", "no_credits"),
        ("all model links failed: qwen/qwen3.8-27b: access refused (401/403): HTTP 401, check the key (Error code: 401 - Invalid API Key)", "auth"),
        # a hold quotes the error that opened it: the hold's own wording comes first and wins
        ("all model links failed: google/gemma-4-31b-it:free: daily request quota, skipped for 40000 s more (qwen/qwen3.8-27b:free: daily request quota of the account is spent, skipped for 43200 s (Error code: 429 - free-models-per-day))", "quota"),
        ("all model links failed: qwen/qwen3.8-27b:free: request timed out, congested upstream", "congested"),
    ],
)
def test_contract_wording_comes_before_status_codes(warning, code):
    assert reason_code([PLANNER_FAILED + warning]) == code


def test_an_older_deck_is_not_a_rules_deck_because_a_data_step_failed():
    """Without planned_by only the planner's own failure means the rules planned; a data_extractor 429 or a fact check
    that ran out of time says nothing against the model's plan (a fact check runs on a model plan only)."""
    planned = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": OLD_MODEL_PLANNED}, use_models=True, ctx=FREE_ONLY)
    assert planned["by_model"] is True and planned["planned_by"] == "model" and planned["reason"] is None and planned["model_label"] == "Qwen3.8-27B"
    repaired = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": ["repair pass failed: qwen: congested upstream"]}, use_models=True, ctx=FREE_ONLY)
    assert repaired["by_model"] is True  # a failed repair keeps the model's plan
    data_only = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": OLD_MODEL_PLANNED[:1]}, use_models=True, ctx=FREE_ONLY)
    assert data_only["by_model"] is None and data_only["reason_code"] is None and data_only["advice"] is None
    # the variant whose own planner failed is a rules deck, whatever the data step did
    visual = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": [OLD_MODEL_PLANNED[0], PLANNER_FAILED + "qwen/qwen3.8-27b:free: time budget of the generation is spent, no room to wait out a 429 (Error code: 429 - {'error': {'message': 'Provider returned error'"]}, use_models=True, ctx=FREE_ONLY)
    assert visual["by_model"] is False and visual["planned_by"] == "rules" and visual["reason_code"] == "congested"
    # the generation as a whole: a model planned some variants — no failure notice over the deck
    g = generation_planner([{"planner": planned}, {"planner": visual}, {"planner": data_only}], use_models=True)
    assert g["by_model"] is True and g["reason"] is None
    assert generation_planner([{"planner": data_only}], use_models=True)["by_model"] is None


def test_an_older_deck_via_the_api(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    _status_module(monkeypatch, [_link(QWEN, "unknown", label="Qwen3.8-27B (бесплатно)")])
    g = c.get(f"/api/generations/{_fake_generation(mod, None, OLD_MODEL_PLANNED)}").json()
    assert g["planner"]["by_model"] is True and g["planner"]["reason"] is None
    g = c.get(f"/api/generations/{_fake_generation(mod, None, OLD_MODEL_PLANNED[:1])}").json()
    assert g["planner"]["by_model"] is None and g["planner"]["reason"] is None


def test_reason_words_are_about_the_link_that_failed():
    # the paid OpenRouter model is congested: no «бесплатные модели», no top-up for that same paid model
    paid = _rules("all model links failed: qwen/qwen3.8-27b: congested upstream, skipped for 120 s more (Error code: 429 - temporarily rate-limited upstream)")
    assert paid["reason"] == "платная модель на OpenRouter сейчас перегружена"
    assert paid["advice"] == "Соберите ещё раз через несколько минут." and paid["steady"] is None
    free = _rules("all model links failed: qwen/qwen3.8-27b:free: congested upstream, skipped for 120 s more")
    assert free["reason"] == "бесплатные модели OpenRouter сейчас перегружены"
    assert "платный Qwen3.8-27B отвечает стабильно" in free["advice"]
    assert free["steady"].startswith("Чтобы не зависеть от очереди бесплатных, пополните OpenRouter") and "платный Qwen3.8-27B" in free["steady"]
    assert generation_planner([{"planner": free}], use_models=True)["steady"] == free["steady"]
    # Groq's daily limit (the same model id as the paid link: Groq's own wording tells them apart): no OpenRouter reset
    groq = _rules("all model links failed: qwen/qwen3.8-27b: daily request quota of the account is spent, skipped for 3000 s (Error code: 429 - {'error': {'message': 'Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_1` service tier `on_demand` on requests per day (RPD): Limit 1000, Used 1000'")
    assert groq["reason_code"] == "quota" and groq["reason"] == "исчерпан дневной лимит запросов Groq"
    assert groq["advice"] == "Соберите ещё раз, когда обновится дневной лимит Groq." and "03:00" not in groq["advice"] and groq["steady"] is None
    openrouter_daily = _rules("all model links failed: qwen/qwen3.8-27b:free: daily request quota of the account is spent, skipped for 50000 s (free-models-per-day)")
    assert openrouter_daily["reason"] == "исчерпан дневной лимит бесплатных запросов OpenRouter" and "после 03:00" in openrouter_daily["advice"]
    cloud = _rules("all model links failed: Qwen/Qwen3-32B: no credits (402) on the account (Error code: 402 - insufficient balance)")
    assert cloud["reason"] == "на счёте Cloud.ru нет средств" and cloud["advice"] == "Пополните счёт Cloud.ru."
    or_credits = _rules("all model links failed: qwen/qwen3.8-27b: no credits (402) on the account (Error code: 402 - This request requires more credits); qwen/qwen3.8-27b:free: congested upstream; google/gemma-4-31b-it:free: congested upstream")
    assert or_credits["reason_code"] == "no_credits" and or_credits["reason"] == "на счёте OpenRouter нет средств для платной модели"
    assert "Пополните счёт OpenRouter на $5–10" in or_credits["advice"]
    # a model of an older config, not in the active chain: what the text says, else the chain's own service
    old = _rules("qwen/qwen3.6-35b-a3b:free: congested upstream (Provider returned error)")
    assert old["reason"] == "бесплатные модели OpenRouter сейчас перегружены"
    vk = chain_context([_link("qwen3.8-27b", "unknown", host="inference.vk.example", label="Qwen3.8-27B (VK)", free=False)], "configs/models.vk.yaml")
    assert _rules("qwen3.8-27b: congested upstream (500 server error)", vk)["reason"] == "сервер модели сейчас перегружен"
    assert "OpenRouter" not in (_rules("qwen3.8-27b: congested upstream (500 server error)", vk)["advice"] or "")


def test_the_failed_link_is_the_one_the_chain_named_by_its_label():
    """Two links run qwen/qwen3.8-27b (the paid OpenRouter one and Groq): the chain's label before each part says which
    failed, whatever the wording (a Groq 401 «Invalid API Key» has no Groq word in it)."""
    two = "all model links failed: [Qwen3.8-27B (OpenRouter)] qwen/qwen3.8-27b: no credits (402) on the account (Error code: 402 - Insufficient credits); [Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: access refused (401/403): HTTP 401, check the key (Error code: 401 - Invalid API Key)"
    info = _rules(two)
    assert info["reason_code"] == "auth" and info["reason"] == "ключ доступа к Groq не подходит"
    assert info["advice"] == "Проверьте ключ доступа к Groq в настройках сервера."
    # the paid link's own part: OpenRouter, with its top-up
    paid = _rules("all model links failed: [Qwen3.8-27B (OpenRouter)] qwen/qwen3.8-27b: no credits (402) on the account (Error code: 402 - Insufficient credits)")
    assert paid["reason"] == "на счёте OpenRouter нет средств для платной модели" and "Пополните счёт OpenRouter" in paid["advice"]
    # Groq's daily limit without Groq's own wording (cut off), and a Groq 404 or 5xx: still Groq
    groq_quota = _rules("all model links failed: [Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: daily request quota of the account is spent, skipped for 3000 s (Error code: 429")
    assert groq_quota["reason"] == "исчерпан дневной лимит запросов Groq" and "03:00" not in groq_quota["advice"]
    groq_busy = _rules("all model links failed: [Qwen3.8-27B (OpenRouter)] qwen/qwen3.8-27b: no credits (402); again: [Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: 498 server error, congested upstream")
    assert groq_busy["reason_code"] == "no_credits"
    assert _rules("all model links failed: again: [Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: 498 server error, congested upstream")["reason"] == "сервер Groq сейчас перегружен"
    # the paid OpenRouter link congested, though the text has Groq-like words in it: the label wins
    paid_busy = _rules("all model links failed: [Qwen3.8-27B (OpenRouter)] qwen/qwen3.8-27b: congested upstream (Error code: 429 - service tier on_demand)")
    assert paid_busy["reason"] == "платная модель на OpenRouter сейчас перегружена"
    # labels of one's own that name no service: looked up in the active chain
    own = chain_context([_link(QWEN_PAID, "unknown", label="Qwen основная"), _link(QWEN_PAID, "unknown", host=QWEN_GROQ_HOST, label="Qwen резерв", free=True)], "configs/models.yaml")
    assert _rules("all model links failed: [Qwen основная] qwen/qwen3.8-27b: no credits (402); [Qwen резерв] qwen/qwen3.8-27b: access refused (401/403)", own)["reason"] == "ключ доступа к Groq не подходит"
    # a label of an older config, not in the active chain: the service its tag names
    old_groq = _rules("all model links failed: [Qwen3.8-30B (Groq)] qwen/qwen3.8-30b: access refused (401/403)")
    assert old_groq["reason"] == "ключ доступа к Groq не подходит"
    old_free = _rules("all model links failed: [Gemma 3 27B (бесплатно)] google/gemma-3-27b-it: congested upstream", FREE_ONLY)
    assert old_free["reason"] == "бесплатные модели OpenRouter сейчас перегружены"
    # a label is a name, never a reason: «402» or «404» in it is not a status code
    assert reason_code([PLANNER_FAILED + "all model links failed: [Qwen 402B (VK)] qwen-402b: congested upstream"]) == "congested"
    assert reason_code([PLANNER_FAILED + "all model links failed: [Model 404 (local)] m404: request timed out"]) == "timeout"


@pytest.mark.parametrize(
    "warning, retryable",
    [
        ("qwen/qwen3.8-27b:free: congested upstream", True),
        ("qwen/qwen3.8-27b:free: per-minute request cap of the account, retry in 20 s", True),
        ("qwen/qwen3.8-27b:free: daily request quota of the account is spent, skipped for 50000 s", True),
        ("qwen/qwen3.8-27b: time budget of the generation is spent (no answer yet)", True),
        ("qwen/qwen3.8-27b: connection error (Connection refused)", True),
        ("qwen/qwen3.8-27b: no credits (402) on the account", False),
        ("qwen/qwen3.8-27b: access refused (401/403): HTTP 401, check the key", False),
        ("qwen/qwen3.8-27b: model not available (404): no such model", False),
        ("qwen/qwen3.8-27b:free: Error code: 400 - {'error': {'message': 'Provider returned error', 'code': 400}}", False),
    ],
)
def test_a_rebuild_is_offered_only_for_reasons_it_can_get_past(warning, retryable):
    info = _rules(warning)
    assert info["retryable"] is retryable
    assert generation_planner([{"planner": info}], use_models=True)["retryable"] is retryable
    if not retryable:
        assert info["advice"] and "Соберите ещё раз" not in info["advice"]  # what to fix instead
    rejected = planner_info({"planned_by": "rules"}, {**CONFIGURED, "warnings": ["outline_planner answer rejected (2 slides), deterministic outline used"]}, use_models=True)
    assert rejected["retryable"] is True


def test_the_live_advice_follows_the_live_state():
    ok = summarize([_link(QWEN, "ok", available=True)], configured=True)
    assert ok["advice"] == "Модель снова отвечает — соберите ещё раз." and ok["retryable"] is True
    assert summarize([_link(QWEN, "unknown", available=True)], configured=True)["advice"] == "Соберите ещё раз — модель попробует снова."
    assert summarize([_link(QWEN, "congested", available=True)], configured=True)["advice"] == "Пауза после сбоя закончилась — соберите ещё раз."
    fb = summarize([_link(QWEN, "congested", available=False, until=90, label="Qwen3.8-27B (бесплатно)"), _link(GEMMA, "unknown", available=True, label="Gemma 4 31B (бесплатно)")], configured=True)
    assert fb["advice"] == "Соберите ещё раз — попробую запасную Gemma 4 31B." and fb["retryable"] is True
    # every link pauses: the advice is about the link whose pause ends first (the one the button waits for)
    down = summarize([_link(QWEN, "quota", available=False, until=50000), _link(GEMMA, "congested", available=False, until=90)], configured=True, ctx=chain_context([_link(QWEN, "quota"), _link(GEMMA, "congested")], "configs/models.free.yaml"))
    assert down["state"] == "down" and down["retry_state"] == "congested" and down["retryable"] is True
    assert down["advice"].startswith("Соберите ещё раз через несколько минут")
    quota = summarize([_link(QWEN, "quota", available=False, until=50000)], configured=True)
    assert "после 03:00" in quota["advice"] and quota["retryable"] is True
    # a key that does not fit is not waited out: no rebuild, the advice says what to fix
    auth = summarize([_link(QWEN_PAID, "auth", available=False, until=1800)], configured=True)
    assert auth["retryable"] is False and auth["advice"] == "Проверьте ключ доступа к OpenRouter в настройках сервера."
    # «error» with a pause is a connection that kept dropping: worth waiting out, and it is not «the same error again»
    conn = summarize([_link(QWEN, "error", available=False, until=60, last_error="qwen: connection error (Connection refused)")], configured=True)
    assert conn["retryable"] is True and conn["advice"].startswith("Проверьте подключение") and "не отвечает" in conn["summary"]
    assert summarize([], configured=False)["retryable"] is False


def _fake_status_module(monkeypatch, fn):
    import verstka.providers as pkg

    fake = types.ModuleType("verstka.providers.status")
    fake.snapshot = fn
    monkeypatch.setitem(sys.modules, "verstka.providers.status", fake)
    monkeypatch.setattr(pkg, "status", fake, raising=False)


def test_a_type_error_inside_snapshot_is_logged_not_retried_without_the_role(api, monkeypatch, caplog):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    calls = []

    def snapshot(providers=None, role=None):
        calls.append(role)
        if role is not None:
            raise TypeError("a bug inside snapshot()")
        return [_link(QWEN, "ok"), _link(QWEN, "ok")]  # the llm and vlm roles merged: must never be shown

    _fake_status_module(monkeypatch, snapshot)
    with caplog.at_level(logging.WARNING, logger="verstka.api.model_status"):
        st = c.get("/api/models/status").json()
    assert calls == ["llm"] and "snapshot() failed" in caplog.text and "a bug inside snapshot()" in caplog.text
    assert st["source"] == "config" and len(st["links"]) == 1


def test_an_older_snapshot_signature_is_called_once(api, monkeypatch, caplog):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _openrouter_registry())
    calls = []

    def snapshot(providers):  # no role: the registry's links
        calls.append(providers)
        return [_link(QWEN, "ok", last_ok=time.time())]

    _fake_status_module(monkeypatch, snapshot)
    st = c.get("/api/models/status").json()
    assert len(calls) == 1 and calls[0] is mod._providers and st["source"] == "status" and st["state"] == "ok"

    def odd(a, b, c):
        raise AssertionError("never called")

    _fake_status_module(monkeypatch, odd)
    with caplog.at_level(logging.WARNING, logger="verstka.api.model_status"):
        st = c.get("/api/models/status").json()
    assert "takes none of" in caplog.text and st["source"] == "config"


# ---------------------------------------------------------------------------- the web texts (modelText.ts, run by node)

_WEB = Path(__file__).resolve().parents[2] / "web"
_RUNNER = r"""
import * as m from "./modelText.mjs";
const now = Date.UTC(2026, 8, 25, 10, 0, 0); // 13:00 in Moscow
const midnight = Date.UTC(2026, 8, 26, 0, 0, 0); // OpenRouter's daily reset
const toMidnight = (midnight - now) / 1000;
const quota = [-0.6, -30, 0, 0.4, 40].map((d) => m.waitText(toMidnight + d, "quota", now));
const late = m.waitText((midnight - Date.UTC(2026, 8, 25, 22, 0, 0)) / 1000 - 0.5, "quota", Date.UTC(2026, 8, 25, 22, 0, 0));
const minutes = [59, 3540, 3541, 3599, 3600, 5400, 7300].map((s) => m.waitText(s, "congested", now));
const rolling = m.waitText(5000.4, "quota", now);
const st = (over) => ({ configured: true, config: null, active_model: null, active_model_label: null, host: null, links: [], source: "status", summary: "", hint: null, working_label: null, retry_in: null, retry_state: null, advice: null, retryable: true, ...over });
const p = (code, retryable, advice) => ({ planned_by: "rules", by_model: false, model: null, model_label: null, tried_label: "Qwen3.8-27B", reason_code: code, reason: "причина", advice, retryable });
const down = st({ state: "down", retry_in: 90, retry_state: "congested", advice: "Соберите ещё раз через несколько минут." });
const offers = {
  congestedDown: m.rebuildOffer(p("congested", true, "Соберите ещё раз через несколько минут или пополните OpenRouter."), { status: down, latest: false, retryIn: 80 }),
  authUnknown: m.rebuildOffer(p("auth", false, "Проверьте ключ доступа к OpenRouter в настройках сервера."), { status: st({ state: "unknown", advice: "Соберите ещё раз — модель попробует снова." }), latest: true, retryIn: 0 }),
  authOkLatest: m.rebuildOffer(p("auth", false, "Проверьте ключ."), { status: st({ state: "ok", advice: "Модель снова отвечает — соберите ещё раз." }), latest: true, retryIn: 0 }),
  authOkOlder: m.rebuildOffer(p("auth", false, "Проверьте ключ."), { status: st({ state: "ok", advice: "Модель снова отвечает — соберите ещё раз." }), latest: false, retryIn: 0 }),
  congestedBlockedByKey: m.rebuildOffer(p("congested", true, "Соберите ещё раз через несколько минут."), { status: st({ state: "down", retry_in: 1800, retry_state: "auth", retryable: false, advice: "Проверьте ключ доступа к OpenRouter в настройках сервера." }), latest: false, retryIn: 1700 }),
  error400: m.rebuildOffer(p("error", false, "Та же сборка получит ту же ошибку: сократите текст."), { status: st({ state: "unknown", advice: "Соберите ещё раз — модель попробует снова." }), latest: true, retryIn: 0 }),
  quotaOlderOk: m.rebuildOffer(p("quota", true, "Бесплатный лимит обновится завтра после 03:00."), { status: st({ state: "ok", advice: "Модель снова отвечает — соберите ещё раз." }), latest: false, retryIn: 0 }),
  noStatus: m.rebuildOffer(p("congested", undefined, "Соберите ещё раз через несколько минут."), { status: null, latest: true, retryIn: 0 }),
  noStatusAuth: m.rebuildOffer(p("auth", undefined, "Проверьте ключ."), null),
  unknownKeepsSteady: m.rebuildOffer({ ...p("congested", true, "Соберите ещё раз через несколько минут или пополните OpenRouter."), steady: "Чтобы не зависеть от очереди бесплатных, пополните OpenRouter." }, { status: st({ state: "unknown", advice: "Соберите ещё раз — модель попробует снова." }), latest: true, retryIn: 0 }),
  downHasItsOwn: m.rebuildOffer({ ...p("congested", true, "x"), steady: "Чтобы не зависеть от очереди бесплатных, пополните OpenRouter." }, { status: down, latest: true, retryIn: 80 }),
  // every model pauses and the paused links can be retried, but the deck's own reason needs a fix
  noCreditsDown: m.rebuildOffer(p("no_credits", false, "Пополните счёт OpenRouter на $5–10 — хватит на сотни презентаций."), { status: st({ state: "down", retry_in: 90, retry_state: "congested", advice: "Соберите ещё раз через несколько минут или пополните OpenRouter на $5–10 — платный Qwen3.8-27B отвечает стабильно." }), latest: true, retryIn: 80 }),
  noCreditsDownPlain: m.rebuildOffer(p("no_credits", false, "Пополните счёт OpenRouter на $5–10."), { status: down, latest: false, retryIn: 80 }),
  authDown: m.rebuildOffer(p("auth", false, "Проверьте ключ доступа к Groq в настройках сервера."), { status: down, latest: true, retryIn: 80 }),
  authDownBlockedByKey: m.rebuildOffer(p("auth", false, "Проверьте ключ доступа к Groq в настройках сервера."), { status: st({ state: "down", retry_in: 1800, retry_state: "auth", retryable: false, advice: "Проверьте ключ доступа к Groq в настройках сервера." }), latest: true, retryIn: 1700 }),
  // a 400 is about these inputs: the model answering something else does not bring the button back (another model may)
  error400OkLatest: m.rebuildOffer(p("error", false, "Та же сборка получит ту же ошибку: сократите текст."), { status: st({ state: "ok", advice: "Модель снова отвечает — соберите ещё раз." }), latest: true, retryIn: 0 }),
  error400FallbackLatest: m.rebuildOffer(p("error", false, "Та же сборка получит ту же ошибку: сократите текст."), { status: st({ state: "fallback", advice: "Сейчас отвечает запасная Gemma 4 31B — соберите ещё раз." }), latest: true, retryIn: 0 }),
  // ... nor does the end of a pause: every model paused, the paused links retryable, for the newest deck and an older one
  error400Down: m.rebuildOffer(p("error", false, "Та же сборка получит ту же ошибку: сократите текст."), { status: down, latest: true, retryIn: 80 }),
  error400DownOlder: m.rebuildOffer(p("error", false, "Та же сборка получит ту же ошибку: сократите текст."), { status: down, latest: false, retryIn: 80 }),
  error400DownOldServer: m.rebuildOffer({ ...p("error", undefined, "Та же сборка получит ту же ошибку: сократите текст."), retryable: undefined }, { status: st({ state: "down", retry_in: 90, retry_state: "congested", retryable: undefined, advice: "Соберите ещё раз через несколько минут." }), latest: true, retryIn: 80 }),
  error400DownBlockedByKey: m.rebuildOffer(p("error", false, "Та же сборка получит ту же ошибку: сократите текст."), { status: st({ state: "down", retry_in: 1800, retry_state: "auth", retryable: false, advice: "Проверьте ключ доступа к Groq в настройках сервера." }), latest: true, retryIn: 1700 }),
  // an older server (no «retryable» in the live status): no button for a deck whose reason needs a fix, so no «соберите»
  authDownOldServer: m.rebuildOffer({ ...p("auth", undefined, "Проверьте ключ."), retryable: undefined }, { status: st({ state: "down", retry_in: 90, retry_state: "congested", retryable: undefined, advice: "Соберите ещё раз через несколько минут." }), latest: true, retryIn: 80 }),
};
const error400DownNotice = m.deckNotice(
  { id: "g", template_id: "t", strategies: ["structured"], use_models: true, slides: 12, planner: p("error", false, "Та же сборка получит ту же ошибку: сократите текст."), variants: [] },
  { strategy: "structured", outline: { planned_by: "rules" }, slides: [], files: {} },
  12,
  { status: down, latest: true, retryIn: 80 },
);
const HOUR = 3600;
const resets = {
  quotaMidnight: [-30, 0, 90].map((d) => m.resetAt(toMidnight + d, now, "quota") === midnight),
  quotaOther: m.resetAt(4 * HOUR + 90, now, "quota") === Date.UTC(2026, 8, 25, 14, 2, 0), // Groq's rolling day: up
  congestedNearMidnight: m.resetAt(toMidnight + 30, now, "congested") === midnight + 60_000,
  holdNearHour: m.resetAt(6 * HOUR + 90, now, "congested") === Date.UTC(2026, 8, 25, 16, 2, 0),
  holdOnMinute: m.resetAt(6 * HOUR + 60, now, "congested") === Date.UTC(2026, 8, 25, 16, 1, 0),
};
const groqQuota = m.waitText(4 * HOUR + 90, "quota", now);
const longHold = m.waitText(6 * HOUR + 90, "congested", now);
const g = { id: "g", template_id: "t", strategies: ["structured"], use_models: true, slides: 12, planner: p("quota", true, "Бесплатный лимит обновится завтра после 03:00."), variants: [] };
const v = { strategy: "structured", outline: { planned_by: "rules" }, slides: [], files: {} };
const quotaDown = st({ state: "down", retry_in: toMidnight - 0.6, retry_state: "quota", advice: "Бесплатный лимит обновится завтра после 03:00. Чтобы не ждать, пополните OpenRouter на $5–10." });
const realNow = Date.now;
Date.now = () => now;
const notice = m.deckNotice(g, v, 11, { status: quotaDown, latest: true, retryIn: toMidnight - 0.6 });
Date.now = realNow;
console.log(JSON.stringify({ quota, late, minutes, rolling, offers, notice, resets, groqQuota, longHold, error400DownNotice }));
"""


def _run_web(tmp_path, tz="Europe/Moscow"):
    import os
    import shutil
    import subprocess

    esbuild = _WEB / "node_modules" / ".bin" / "esbuild"
    node = shutil.which("node")
    if not node or not esbuild.exists():
        pytest.skip("node or esbuild is not installed")
    out = tmp_path / "modelText.mjs"
    subprocess.run([str(esbuild), str(_WEB / "src" / "lib" / "modelText.ts"), "--bundle", "--format=esm", "--platform=node", f"--outfile={out}", "--log-level=error"], check=True, timeout=60)
    (tmp_path / "run.mjs").write_text(_RUNNER, encoding="utf-8")
    res = subprocess.run([node, str(tmp_path / "run.mjs")], capture_output=True, text=True, check=True, timeout=60, env={**os.environ, "TZ": tz})
    return json.loads(res.stdout)


@pytest.mark.parametrize("tz", ["Europe/Moscow", "America/New_York"])
def test_web_wait_texts(tmp_path, tz):
    r = _run_web(tmp_path, tz)
    # a second before or after 00:00 UTC is OpenRouter's reset: never «02:59» or «03:01»
    assert r["quota"] == ["завтра после 03:00"] * 5
    assert r["late"] == "сегодня после 03:00"  # 01:00 in Moscow: the reset is today
    assert r["minutes"] == ["через 1 мин", "через 59 мин", "через 1 ч", "через 1 ч", "через 1 ч", "через 1 ч 30 мин", "через 2 ч"]
    if tz == "Europe/Moscow":
        assert r["rolling"] == "сегодня после 14:24"  # another quota (Groq): rounded up to the whole minute
        # never snapped down to a whole hour that is already past while the button still waits
        assert r["groqQuota"] == "сегодня после 17:02" and r["longHold"] == "сегодня после 19:02"
    # only OpenRouter's reset (a quota, at 00:00 UTC) snaps; everything else is rounded up to the minute
    assert all(r["resets"]["quotaMidnight"]) and all(v is True for k, v in r["resets"].items() if k != "quotaMidnight")


def test_web_rebuild_offer_and_advice_agree(tmp_path):
    o = _run_web(tmp_path)["offers"]
    assert o["congestedDown"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут."}
    assert o["authUnknown"] == {"retry": False, "wait": 0, "help": "Проверьте ключ доступа к OpenRouter в настройках сервера."}
    assert o["authOkLatest"] == {"retry": True, "wait": 0, "help": "Модель снова отвечает — соберите ещё раз."}
    assert o["authOkOlder"]["retry"] is False and o["authOkOlder"]["help"] == "Проверьте ключ."
    assert o["congestedBlockedByKey"] == {"retry": False, "wait": 0, "help": "Проверьте ключ доступа к OpenRouter в настройках сервера."}
    assert o["error400"]["retry"] is False and "сократите текст" in o["error400"]["help"]
    assert o["quotaOlderOk"] == {"retry": True, "wait": 0, "help": "Модель снова отвечает — соберите ещё раз."}
    assert o["noStatus"]["retry"] is True and o["noStatusAuth"]["retry"] is False
    # while a model answers, the deck's word about the paid model stays after the live advice; when every model
    # pauses, the live advice (about the link the button waits for) is the whole help
    assert o["unknownKeepsSteady"]["help"] == "Соберите ещё раз — модель попробует снова. Чтобы не зависеть от очереди бесплатных, пополните OpenRouter."
    assert o["downHasItsOwn"]["help"] == "Соберите ещё раз через несколько минут."
    # every model pauses, the paused links can be retried, the deck's reason needs a fix: the button waits for the
    # live pause and the deck's fix stays after the live advice (said once when the live advice offers it already)
    assert o["noCreditsDown"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут или пополните OpenRouter на $5–10 — платный Qwen3.8-27B отвечает стабильно."}
    assert o["noCreditsDownPlain"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут. Пополните счёт OpenRouter на $5–10."}
    assert o["authDown"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут. Проверьте ключ доступа к Groq в настройках сервера."}
    assert o["authDownBlockedByKey"] == {"retry": False, "wait": 0, "help": "Проверьте ключ доступа к Groq в настройках сервера."}
    assert o["error400OkLatest"] == {"retry": False, "wait": 0, "help": "Та же сборка получит ту же ошибку: сократите текст."}
    assert o["error400FallbackLatest"] == {"retry": True, "wait": 0, "help": "Сейчас отвечает запасная Gemma 4 31B — соберите ещё раз."}
    # every model pauses and the pause will end, but a 400 comes back after it: no button, only the deck's own fix
    for name in ("error400Down", "error400DownOlder", "error400DownOldServer"):
        assert o[name] == {"retry": False, "wait": 0, "help": "Та же сборка получит ту же ошибку: сократите текст."}, name
    # the paused links need a fix themselves: that fix leads, the deck's own follows, still no button
    assert o["error400DownBlockedByKey"] == {"retry": False, "wait": 0, "help": "Проверьте ключ доступа к Groq в настройках сервера. Та же сборка получит ту же ошибку: сократите текст."}
    assert o["authDownOldServer"] == {"retry": False, "wait": 0, "help": "Проверьте ключ."}
    # the advice never promises a rebuild the notice does not offer, and a shown button always has advice beside it
    for name, offer in o.items():
        assert offer["help"], name
        if not offer["retry"]:
            assert "оберите ещё раз" not in offer["help"], name


def test_web_notice_of_a_400_while_every_model_pauses_offers_no_rebuild(tmp_path):
    n = _run_web(tmp_path)["error400DownNotice"]
    assert n["retry"] is False and n["retryWait"] == 0
    assert "сократите текст" in n["help"] and "оберите" not in n["help"]


def test_web_notice_button_and_advice_name_the_same_time(tmp_path):
    n = _run_web(tmp_path)["notice"]
    assert n["retry"] is True and n["retryWait"] > 0 and n["retryLabel"] == "Собрать завтра после 03:00"
    assert "завтра после 03:00" in n["help"] and n["help"].startswith("бесплатный лимит")
