"""GET /api/models/status and the plain-Russian reasons of a deck planned without the model (mocks only, no network).

The chain is Polza's (configs/models.yaml): the main model Qwen3.8-27B and the backup Qwen3.6-27B on one key. The words
a person reads never name Polza, money or keys; the owner's line does — the one place the service is named. Polza's
errors are quoted as the OpenAI SDK raises them (polza.ai/docs: «Формат ошибок», «Два вида 429»)."""

import dataclasses
import importlib
import json
import logging
import re
import sys
import time
import types
from pathlib import Path

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from verstka.api.model_status import CONTRACT_PHRASES, LINK_STATES, RETRYABLE_REASONS, ChainContext, FailedLink, advice, chain_context, classify, collect_links, failed_link, generation_planner, hostname, model_label, models_status, owner_reason, owner_reasons, planner_info, reason_code, reason_detail, reason_text, service, short_label, summarize
from verstka.providers.base import ChatMessage, ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.registry import ProviderLimits, ProviderRegistry

MAIN = "qwen/qwen3.8-27b"  # Polza's main model
BACKUP = "qwen/qwen3.6-27b"  # the backup: answers when the main one cannot
POLZA = "polza.ai"
POLZA_URL = "https://polza.ai/api/v1"
VK_MODEL = "qwen3.8-27b"  # the final's VK inference (configs/models.vk.yaml): a host the texts never name
VK_HOST = "inference.vk.example"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json"
SHORT = "Итоги пилота «Умные сводки» за второй квартал: время на чтение чатов сократилось с 47 до 29 минут в день."
PLANNER_FAILED = "outline_planner failed, deterministic outline used: "
# Polza's answers as the OpenAI SDK quotes them
NO_MONEY = "Error code: 402 - {'error': {'code': 'INSUFFICIENT_BALANCE', 'message': 'Недостаточно средств на балансе'}}"
KEY_LIMIT = "Error code: 402 - {'error': {'code': 'INSUFFICIENT_BALANCE', 'message': 'Превышен лимит расходов ключа'}}"
RESERVED = "Error code: 402 - {'error': {'code': 'INSUFFICIENT_BALANCE', 'message': 'Недостаточно средств: требуется 3.00 ₽, доступно 1.20 ₽, зарезервировано 25.00 ₽'}}"
MINUTE = "Error code: 429 - {'error': {'code': 'TOO_MANY_REQUESTS', 'message': 'Достигнут минутный лимит запросов к модели. Повторите позже.'}}"
DAY = "Error code: 429 - {'error': {'code': 'TOO_MANY_REQUESTS', 'message': 'Достигнут дневной лимит запросов к модели. Повторите позже.'}}"
HOSTS_429 = "Error code: 429 - {'error': {'code': 'TOO_MANY_REQUESTS', 'message': 'Провайдер модели ограничил частоту запросов. Повторите через несколько секунд или выберите другую модель.', 'metadata': {'provider_name': 'deepinfra', 'raw': 'Rate limit reached for requests'}}}"
NO_HOSTS = "Error code: 503 - {'error': {'code': 'SERVICE_UNAVAILABLE', 'message': 'Нет доступных провайдеров для модели'}}"
TIMED_OUT = "Error code: 408 - {'error': {'code': 'REQUEST_TIMEOUT', 'message': 'Истекло время ожидания ответа. Повторите запрос'}}"
REVOKED = "Error code: 401 - {'error': {'code': 'api_key_revoked', 'message': 'Ключ API отозван'}}"
FORBIDDEN = "Error code: 403 - {'error': {'code': 'FORBIDDEN', 'message': 'Ошибка доступа. Проверьте права доступа ключа'}}"
MODERATION = "Error code: 403 - {'error': {'code': 'FORBIDDEN', 'message': 'Запрос отклонён модерацией'}}"
NOT_FOUND = "Error code: 404 - {'error': {'code': 'NOT_FOUND', 'message': 'Модель не найдена'}}"
BAD_REQUEST = "Error code: 400 - {'error': {'code': 'BAD_REQUEST', 'message': 'Недопустимое значение параметра'}}"
TOO_LARGE = "Error code: 413 - {'error': {'code': 'PAYLOAD_TOO_LARGE', 'message': 'Размер тела запроса превышает допустимый предел'}}"
CONGESTED = [
    f"data_extractor failed, using regex facts: all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream ({HOSTS_429[:120]}",
    PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream, skipped for 120 s more (marked earlier); [Qwen3.6-27B] {BACKUP}: congested upstream (marked earlier)",
    "slide 1 (sl1): заголовок набран 36 пт (3 стр.) при 54 пт в образце",
]
# what the server's owner reads (a tooltip, the log): the one place the service is named
OWNER_MONEY = "На балансе Polza нет средств или исчерпан лимит расходов ключа: пополните баланс или поднимите лимит ключа в консоли Polza."
OWNER_KEY = "Polza отказала в доступе (401/403): проверьте ключ POLZA_API_KEY в .env — его могли отозвать."
OWNER_GONE = "Модели нет на Polza (404): проверьте её название в настройках."
AFTER_MIDNIGHT = "Соберите ещё раз после полуночи по московскому времени."  # Polza's daily caps reset at 00:00 in Moscow
# what a person must never read in the status line, its hint or the advice: the service, money, keys, config files
_BANNED = re.compile(r"polza|openrouter|groq|cloud\.ru|\$|₽|рубл|пополн|(?<![а-яё])сч[её]т|средств|баланс|(?<![а-яё])ключ|api[ _-]?key|\.env|configs/|\.ya?ml|платн", re.I)
# a link as the API shows it: a fixed set of keys, never an account or a key
LINK_FIELDS = {"model", "label", "short_label", "host", "state", "available", "last_ok", "last_error", "last_error_at", "until", "roles"}


def _plain(*texts):
    for t in texts:
        assert not t or not _BANNED.search(t), t


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


def _polza_registry(key="test-key-not-real", base_url=POLZA_URL, models=((MAIN, "Qwen3.8-27B"), (BACKUP, "Qwen3.6-27B"))):
    """The llm and vlm roles of configs/models.yaml: Polza's main model and its backup on one key."""
    llm = {"backend": "polza", "base_url": base_url, "api_key": key, "json_mode": False, "chain": [{"model": m, "label": label} for m, label in models]}
    return ProviderRegistry.from_config({"roles": {"llm": llm, "vlm": {**llm, "temperature": 0.1}}})


def _link(model, state, host=POLZA, **kw):
    """One row of verstka.providers.status.snapshot()."""
    return {"model": model, "host": host, "state": state, **kw}


POLZA_CTX = chain_context([_link(MAIN, "unknown", label="Qwen3.8-27B"), _link(BACKUP, "unknown", label="Qwen3.6-27B")], "configs/models.yaml")
VK = chain_context([_link(VK_MODEL, "unknown", host=VK_HOST, label="Qwen3.8-27B (VK)")], "configs/models.vk.yaml")
CONFIGURED = {"providers": {"llm": {"backend": "chain", "model": MAIN}}}


def _rules(warning, ctx=POLZA_CTX):
    """The planner info of a rules deck, plus `detail`: the link-specific reason the server logs (the API's `reason`
    names no service, money or key)."""
    seen = []
    handler = logging.Handler(logging.INFO)
    handler.emit = lambda record: seen.append(getattr(record, "reason_detail", None))
    logger = logging.getLogger("verstka.api.model_status")
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        info = planner_info({"planned_by": "rules"}, {**CONFIGURED, "warnings": [PLANNER_FAILED + warning]}, use_models=True, ctx=ctx)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
    _plain(info["reason"])
    return {**info, "detail": seen[-1] if seen else None}


# ---------------------------------------------------------------------------- reason mapping


@pytest.mark.parametrize(
    "warning, code",
    [
        (CONGESTED[1], "congested"),
        (PLANNER_FAILED + f"{MAIN}: daily request quota of the account is spent, skipped for 43200 s ({DAY})", "quota"),
        (PLANNER_FAILED + f"{MAIN}: time budget of the generation is spent (no answer yet)", "timeout"),
        # the budget ran out while waiting out the hosts' 429: the cause is congestion
        (PLANNER_FAILED + f"{MAIN}: time budget of the generation is spent, no room to wait out a 429 ({HOSTS_429})", "congested"),
        # a 400 that names the host is not congestion: retrying does not help
        (PLANNER_FAILED + MAIN + ": Error code: 400 - {'error': {'code': 'BAD_REQUEST', 'message': 'Превышена длина контекста', 'metadata': {'provider_name': 'deepinfra', 'raw': 'upstream: context too long'}}}", "error"),
        (PLANNER_FAILED + MAIN + ": Error code: 502 - {'error': {'code': 'BAD_GATEWAY', 'message': 'Bad gateway'}}", "congested"),
        (PLANNER_FAILED + f"{MAIN}: 503 server error (Service Unavailable)", "congested"),
        (PLANNER_FAILED + "no API key configured for model qwen at https://polza.ai/api/v1", "off"),
        ("outline_planner answer rejected (2 slides), deterministic outline used", "rejected"),
        (PLANNER_FAILED + "qwen: no valid completion after 3 attempts: Connection error.", "unreachable"),
        ("no LLM provider: deterministic outline", "off"),
        (PLANNER_FAILED + "all model links failed: every link is not configured (no API key)", "off"),
        # per-minute cap ≠ daily quota
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: per-minute request cap of the account, retry in 40 s ({MINUTE})", "rate"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.6-27B] {BACKUP}: per-minute request cap, skipped for 44 s more ({BACKUP}: per-minute request cap of the account, retry in 44 s ({MINUTE}))", "rate"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: daily request quota, skipped for 50000 s more ({MAIN}: daily request quota of the account is spent ({DAY}))", "quota"),
        # the chain's messages: each failed link named by its label
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream, skipped for 95 s more (429); [Qwen3.6-27B] {BACKUP}: no credits (402) on the balance", "no_credits"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream, skipped for 95 s more (429)", "congested"),
        (PLANNER_FAILED + "all model links failed: [Qwen3.8-27B] qwen/qwen9-27b: model not available (404): no such model or no host serves it", "missing"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: request timed out", "timeout"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: 401 request refused, check the key", "auth"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: no credits (402); [Qwen3.6-27B] {BACKUP}: congested upstream (429)", "no_credits"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: access refused (401/403)", "auth"),
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: model not available (404)", "missing"),
        # a link waiting for its key is skipped, never the reason
        (PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: not configured (no API key); [Qwen3.6-27B] {BACKUP}: congested upstream, skipped for 95 s more", "congested"),
        # not a failure of the model: a layout note, slide text quoted by the grounding, another variant's plan taken,
        # the fact check that worked
        ("slide 3 (sl3): label widened by 4% of the slide for the heading", None),
        ("grounding: slides not supported by the brief dropped: sl4 «Our model provider is congested upstream (402)»", None),
        (f"own model plan failed, the shared plan of «compact» used: {MAIN}: congested upstream", None),
        ("fact_checker found 2 issues in the model's plan", None),
    ],
)
def test_reason_code_from_warnings(warning, code):
    assert reason_code([warning]) == code


def test_the_most_telling_reason_wins():
    """Several links (or steps) failed differently: the reason someone can act on comes first — a key, the balance, the
    day's cap, a model id, then what passes by itself; a link waiting for its key is never the reason."""
    order = ["auth", "no_credits", "quota", "missing", "congested", "rate", "timeout", "unreachable", "rejected", "error"]
    parts = {
        "auth": f"{MAIN}: access refused (401/403)",
        "no_credits": f"{MAIN}: no credits (402) on the balance",
        "quota": f"{MAIN}: daily request quota of the account is spent",
        "missing": f"{MAIN}: model not available (404)",
        "congested": f"{MAIN}: congested upstream",
        "rate": f"{MAIN}: per-minute request cap of the account",
        "timeout": f"{MAIN}: request timed out",
        "unreachable": f"{MAIN}: connection error (Connection refused)",
        "rejected": f"{MAIN}: answer rejected (2 slides)",
        "error": f"{MAIN}: {BAD_REQUEST}",
    }
    for i, better in enumerate(order):
        for worse in order[i + 1:]:
            text = f"all model links failed: [Qwen3.6-27B] {parts[worse]}; [Qwen3.8-27B] {parts[better]}"
            assert reason_code([PLANNER_FAILED + text]) == better, (better, worse)
    assert reason_code([PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: not configured (no API key); [Qwen3.6-27B] {parts['error']}"]) == "error"
    assert reason_code([PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: not configured (no API key)"]) == "off"


def test_reason_prefers_the_planners_own_failure_and_says_it_in_russian():
    assert reason_code(CONGESTED) == "congested"
    timeout = f"data_extractor failed, using regex facts: {MAIN}: time budget of the generation is spent (no answer yet)"
    rejected = "outline_planner answer rejected (2 slides), deterministic outline used"
    # the planner answered but its plan was rejected: that is why the rules planned, whatever the data step did
    assert reason_code([timeout, rejected]) == "rejected"
    daily = f"data_extractor failed, using regex facts: all model links failed: [Qwen3.8-27B] {MAIN}: {DAY}"
    assert reason_code([timeout, daily]) == "quota"  # no planner warning: the other steps tell
    # the API's reason is the UI's words: no service, money or key, whatever the chain
    assert reason_text("congested") == reason_text("congested", POLZA_CTX) == reason_text("congested", VK) == "сервер модели перегружен"
    assert reason_text("no_credits") == reason_text("auth") == reason_text("missing") == "модель недоступна"
    assert reason_text("quota") == "дневной лимит запросов исчерпан"
    assert reason_text("rate") == "слишком много запросов за минуту"
    assert reason_text("unreachable") == "нет связи с сервером модели"
    assert reason_text("rejected") == "план модели не прошёл проверку"
    assert reason_text("error") == "модель вернула ошибку"
    assert reason_text("timeout") == "время на ответ вышло"
    assert reason_text("off") == "модель не подключена"
    assert reason_text(None) is None
    codes = ("congested", "rate", "quota", "no_credits", "auth", "missing", "timeout", "unreachable", "rejected", "error", "off")
    _plain(*(reason_text(code, ctx) for code in codes for ctx in (POLZA_CTX, VK)))


@pytest.mark.parametrize(
    "code, on_polza, elsewhere",
    [
        ("congested", "хосты модели на Polza сейчас перегружены", "сервер модели сейчас перегружен"),
        ("rate", "исчерпан минутный лимит запросов Polza к модели", "превышен лимит запросов к модели в минуту"),
        ("quota", "исчерпан дневной лимит запросов Polza к модели (обновится в полночь по Москве)", "исчерпан дневной лимит запросов к модели"),
        ("no_credits", "на балансе Polza нет средств или исчерпан лимит расходов ключа", "на счёте сервиса модели нет средств"),
        ("auth", "ключ доступа к Polza не подходит", "ключ доступа к модели не подходит"),
        ("missing", "этой модели сейчас нет на Polza", "эта модель сейчас недоступна на сервере"),
        ("unreachable", "не удалось связаться с сервером Polza", "не удалось связаться с сервером модели"),
        ("timeout", "время на модель вышло — она отвечала слишком долго", "время на модель вышло — она отвечала слишком долго"),
        ("rejected", "модель ответила, но её план не прошёл проверку", "модель ответила, но её план не прошёл проверку"),
        ("error", "модель вернула ошибку", "модель вернула ошибку"),
        ("off", "модель не подключена", "модель не подключена"),
    ],
)
def test_the_logged_detail_names_polza_only_for_a_polza_link(code, on_polza, elsewhere):
    # no chain known yet: the models of the config are Polza's
    assert reason_detail(code, POLZA_CTX) == reason_detail(code) == on_polza
    assert reason_detail(code, VK) == elsewhere  # the final's VK inference
    # the link that failed decides, not the first one of the chain
    assert reason_detail(code, VK, FailedLink(BACKUP, "Polza")) == on_polza
    assert reason_detail(code, POLZA_CTX, FailedLink(VK_MODEL, None)) == elsewhere
    assert reason_detail(None, POLZA_CTX) is None


def test_advice_says_when_to_build_again_never_money_or_keys():
    # whatever the active chain, the advice is about when to build again: no top-up, key, config or service
    for ctx in (POLZA_CTX, VK, ChainContext()):
        assert advice("congested", ctx) == advice("timeout", ctx) == "Соберите ещё раз через несколько минут."
        assert advice("rate", ctx) == "Соберите ещё раз через минуту."  # Polza's per-minute cap ends with the minute
        assert advice("quota", ctx) == AFTER_MIDNIGHT  # Polza's daily cap: until midnight by Moscow time
        assert advice("unreachable", ctx) == "Проверьте подключение к интернету и соберите ещё раз."
        assert advice("rejected", ctx) == "Соберите ещё раз — модель отвечает по-разному."
        # a 400: the same inputs get the same answer — say what to fix, never «соберите ещё раз»
        assert advice("error", ctx) == "Та же сборка получит ту же ошибку: сократите текст."
        # money, a key or a model id need the server's owner: the person only learns that the model is unavailable
        for code in ("no_credits", "auth", "missing"):
            assert advice(code, ctx) == "Модель недоступна."
        assert advice("off", ctx) is None and advice(None, ctx) is None
    codes = ("congested", "rate", "quota", "no_credits", "auth", "missing", "timeout", "unreachable", "rejected", "error", "off", None)
    _plain(*(advice(code, ctx) for code in codes for ctx in (POLZA_CTX, VK, ChainContext())))


def test_polzas_daily_cap_resets_at_midnight_by_moscow_time():
    """No more «после 03:00» or 00:00 UTC: Polza's daily caps reset at midnight in Moscow, whichever model hit one."""
    assert "03:00" not in AFTER_MIDNIGHT and "UTC" not in AFTER_MIDNIGHT
    both = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: daily request quota of the account is spent, skipped for 36000 s ({DAY}); [Qwen3.6-27B] {BACKUP}: daily request quota of the account is spent, skipped for 36000 s ({DAY})")
    assert both["reason_code"] == "quota" and both["advice"] == AFTER_MIDNIGHT and both["retryable"] is True
    assert both["reason"] == "дневной лимит запросов исчерпан" and both["owner"] is None
    assert both["detail"] == "исчерпан дневной лимит запросов Polza к модели (обновится в полночь по Москве)"
    # Polza's raw words of the cap, without the providers' contract wording: the same advice
    assert _rules(f"{BACKUP}: {DAY}")["advice"] == AFTER_MIDNIGHT


def test_model_labels():
    assert model_label(MAIN) == "Qwen3.8-27B" and model_label(BACKUP) == "Qwen3.6-27B"
    assert model_label("Qwen/Qwen3.8-27B") == "Qwen3.8-27B"  # the weights' name on Hugging Face
    assert model_label(VK_MODEL) == "Qwen3.8-27B"  # the final's VK inference
    assert model_label("qwen/qwen3.8-27b:nitro") == "Qwen3.8-27B"  # a routing tag is not part of the name
    assert model_label("qwen/qwen3-30b-a3b-instruct-2507") == "Qwen3-30B-A3B"
    assert model_label("qwen/qwen3-vl-32b-instruct") == "Qwen3-VL-32B"
    assert model_label(None) is None
    assert short_label("Qwen3.8-27B (VK)") == "Qwen3.8-27B" and short_label("Qwen3.6-27B") == "Qwen3.6-27B" and short_label(None) is None


def test_planner_info_for_rules_and_model_plans():
    rm = {"warnings": CONGESTED, "providers": {"llm": {"backend": "chain", "model": MAIN}}}
    info = planner_info({"planned_by": "rules"}, rm, use_models=True, ctx=POLZA_CTX)
    assert info["by_model"] is False and info["reason_code"] == "congested" and info["tried_label"] == "Qwen3.8-27B"
    assert info["reason"] == "сервер модели перегружен" and info["owner"] is None and info["retryable"] is True
    assert info["advice"] == "Соберите ещё раз через несколько минут." and info["steady"] is None
    assert planner_info({"planned_by": "rules"}, rm, use_models=True, ctx=VK)["advice"] == info["advice"]
    # the chain answered with the backup model: the recorded model wins over the configured one
    ok = planner_info({"planned_by": "model"}, {**rm, "warnings": [], "planner": {"planned_by": "model", "model": BACKUP}}, use_models=True)
    assert ok["by_model"] and ok["model"] == BACKUP and ok["model_label"] == "Qwen3.6-27B" and ok["reason"] is None
    shared = planner_info({"planned_by": "shared:structured"}, {**rm, "planner": {"planned_by": "shared:structured", "model": MAIN}})
    assert shared["by_model"] and shared["model_label"] == "Qwen3.8-27B"
    agent = planner_info({"planned_by": "agent"}, {**rm, "warnings": []}, use_models=True)
    assert agent["by_model"] and agent["model"] == MAIN  # nothing recorded: the configured model
    off = planner_info({"planned_by": "rules"}, {"warnings": ["no LLM provider: deterministic outline"], "providers": {"llm": {"backend": "none"}}}, use_models=False)
    assert off["reason_code"] == "off" and off["advice"] is None and off["owner"] is None and off["retryable"] is False
    g = generation_planner([{"planner": info}, {"planner": info}], use_models=True)
    assert g["by_model"] is False and g["reason_code"] == "congested" and g["retryable"] is True
    assert generation_planner([{"planner": info}, {"planner": ok}], use_models=True)["model_label"] == "Qwen3.6-27B"


def test_no_failure_notice_without_evidence():
    """An older deck without planned_by and without model warnings, and a deck built from a supplied outline, are not
    shown as a model failure."""
    old = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": []}, use_models=True, ctx=POLZA_CTX)
    assert old["by_model"] is None and old["reason_code"] is None and old["reason"] is None and old["advice"] is None
    g = generation_planner([{"planner": old}], use_models=True)
    assert g["by_model"] is None and g["reason"] is None
    # the same older deck with a recorded model failure: the rules planned it, and the warning says why
    failed = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": CONGESTED}, use_models=True, ctx=POLZA_CTX)
    assert failed["planned_by"] == "rules" and failed["reason_code"] == "congested"
    # an explicit rules plan without a model failure: no reason is made up
    quiet = planner_info({"planned_by": "rules"}, {**CONFIGURED, "warnings": []}, use_models=True, ctx=POLZA_CTX)
    assert quiet["by_model"] is False and quiet["reason"] is None
    assert generation_planner([{"planner": quiet}], use_models=True)["reason_code"] is None
    assert generation_planner([{"planner": quiet}], use_models=False)["reason_code"] == "off"  # the person switched it off
    # a supplied outline: no model was asked to plan
    for sup in (planner_info({"planned_by": "rules"}, {**CONFIGURED, "warnings": CONGESTED}, use_models=True, supplied=True),
                planner_info({"planned_by": "rules"}, {**CONFIGURED, "planner": {"planned_by": "rules", "supplied": True}}, use_models=True)):
        assert sup["planned_by"] == "supplied" and sup["reason_code"] is None and sup["advice"] is None
    assert generation_planner([{"planner": sup}], use_models=True)["planned_by"] == "supplied"


# ---------------------------------------------------------------------------- Polza's own words


@pytest.mark.parametrize(
    "error, code",
    [
        (NO_MONEY, "no_credits"),  # 402 INSUFFICIENT_BALANCE «Недостаточно средств»
        (KEY_LIMIT, "no_credits"),  # 402: the spending limit of the key
        (MINUTE, "rate"),  # Polza's own per-minute cap of the model
        (DAY, "quota"),  # ... and its daily cap
        # Polza's own cap names its window: never the hosts' congestion, even beside a host's name
        ("Error code: 429 - Достигнут минутный лимит запросов к модели. Повторите позже. (provider: deepinfra)", "rate"),
        (HOSTS_429, "congested"),  # the hosts' own 429, passed on by Polza
        ("Error code: 429 - Rate limit reached for requests (provider: deepinfra)", "congested"),  # metadata only
        (NO_HOSTS, "congested"),  # 503: no host serves the model now
        ("Error code: 503 - {'error': {'code': 'SERVICE_UNAVAILABLE', 'message': 'Service temporarily unavailable', 'metadata': {'reason': 'noProvidersForModel'}}}", "congested"),
        ("Error code: 500 - {'error': {'code': 'INTERNAL_ERROR', 'message': 'Ошибка сервера'}}", "congested"),
        ("Error code: 502 - {'error': {'code': 'BAD_GATEWAY', 'message': 'Провайдер вернул некорректный ответ'}}", "congested"),
        (TIMED_OUT, "timeout"),
        (REVOKED, "auth"),  # api_key_revoked
        ("Error code: 401 - {'error': {'code': 'UNAUTHORIZED', 'message': 'Ошибка авторизации. Проверьте ключ доступа'}}", "auth"),
        (FORBIDDEN, "auth"),
        (NOT_FOUND, "missing"),
        (BAD_REQUEST, "error"),  # a 400 or a 413: the same request gets the same answer
        (TOO_LARGE, "error"),
    ],
    ids=["402-balance", "402-key-limit", "429-minute", "429-day", "429-minute-with-host", "429-hosts", "429-host-name-only", "503-no-hosts",
         "503-noProvidersForModel", "500", "502", "408", "401-revoked", "401", "403", "404", "400", "413"],
)
def test_polzas_own_words_without_the_contract_wording(error, code):
    """Polza's answer quoted raw (an older warning, a message without the providers' contract wording) is read by its
    words and its code — in the planner's warning, in a chain's part named by its label, on a second pass."""
    assert reason_code([PLANNER_FAILED + f"{MAIN}: {error}"]) == code
    assert reason_code([PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: {error}"]) == code
    assert classify(f"all model links failed: again: [Qwen3.6-27B] {BACKUP}: {error}") == code


def test_polza_is_the_one_service_named():
    assert service(POLZA) == service("api.polza.ai") == service("POLZA.AI") == "Polza"
    # the hosts of the old chain are not services any more; the final's VK inference never was one
    for host in ("openrouter.ai", "api.groq.com", "foundation-models.api.cloud.ru", VK_HOST, "notpolza.ai", "polza.ai.example.org", "", None):
        assert service(host) is None, host
    assert hostname(POLZA_URL) == hostname("polza.ai/api/v1") == POLZA
    assert hostname("https://user:secret@proxy.example.org:8443/v1") == "proxy.example.org" and hostname(None) is None


def test_the_chain_context_keeps_only_what_the_words_need():
    ctx = chain_context([_link(MAIN, "congested", label="Qwen3.8-27B", until=90, available=False, last_error="x", roles=["llm"]), _link(BACKUP, "ok", label="Qwen3.6-27B")], "configs/models.yaml")
    assert ctx.primary_label == "Qwen3.8-27B" and ctx.config == "configs/models.yaml"
    assert ctx.links == [{"model": MAIN, "label": "Qwen3.8-27B", "host": POLZA, "state": "congested"}, {"model": BACKUP, "label": "Qwen3.6-27B", "host": POLZA, "state": "ok"}]
    assert ctx.primary == FailedLink(MAIN, "Polza")
    # the main model waits for its key: the chain is named by the backup, the first link it asks
    off = chain_context([_link(MAIN, "off", label="Qwen3.8-27B"), _link(BACKUP, "unknown", label="Qwen3.6-27B")])
    assert off.primary_label == "Qwen3.6-27B" and off.primary == FailedLink(BACKUP, "Polza")
    assert VK.primary_label == "Qwen3.8-27B" and VK.primary == FailedLink(VK_MODEL, None)
    # no link known yet: the words are about Polza, the service of every model of the config
    assert chain_context([], "configs/models.yaml") == ChainContext(config="configs/models.yaml")
    assert ChainContext().primary == FailedLink(service="Polza")
    # one service: no free / paid / OpenRouter / Groq fields are left
    assert {f.name for f in dataclasses.fields(ChainContext)} == {"primary_label", "config", "links"}
    assert {f.name for f in dataclasses.fields(FailedLink)} == {"model", "service", "stale"}


def test_the_failed_link_is_found_by_its_label_then_its_model():
    assert failed_link(f"[Qwen3.6-27B] {BACKUP}: access refused (401/403)", POLZA_CTX) == FailedLink(BACKUP, "Polza")
    assert failed_link(f"again: [Qwen3.8-27B] {MAIN}: congested upstream", POLZA_CTX) == FailedLink(MAIN, "Polza")
    # no label, or a label of an older config: the model id in the text, looked up in the active chain
    assert failed_link(f"{BACKUP}: no credits (402) on the balance", POLZA_CTX) == FailedLink(BACKUP, "Polza")
    assert failed_link(f"[Qwen3.6-27B (Polza)] {BACKUP}: congested upstream", POLZA_CTX) == FailedLink(BACKUP, "Polza")
    # a link of an older config (a deck built before Polza) is about no service of today: no owner's fix is asked
    assert failed_link("[Qwen3 32B (Cloud.ru)] Qwen/Qwen3-32B: congested upstream", POLZA_CTX) == FailedLink("Qwen/Qwen3-32B", None, stale=True)
    assert failed_link(f"[Qwen3.6-27B] {BACKUP}: congested upstream", VK) == FailedLink(BACKUP, None)
    # no link named («time budget of the generation is spent»): the first link the chain asks
    assert failed_link("time budget of the generation is spent", POLZA_CTX) == POLZA_CTX.primary == FailedLink(MAIN, "Polza")
    assert failed_link(None, POLZA_CTX) == failed_link("", POLZA_CTX) == FailedLink(MAIN, "Polza")
    assert failed_link(f"[Qwen3.6-27B] {BACKUP}: congested upstream") == FailedLink(BACKUP, "Polza")
    # the same model id on two hosts: the label, not the id, says which one failed
    mirror = chain_context([_link(MAIN, "unknown", label="Qwen основная"), _link(MAIN, "unknown", host="llm.example.org", label="Qwen зеркало")])
    assert failed_link(f"[Qwen зеркало] {MAIN}: access refused (401/403)", mirror) == FailedLink(MAIN, None)
    assert failed_link(f"[Qwen основная] {MAIN}: access refused (401/403)", mirror) == FailedLink(MAIN, "Polza")


def _sdk_error(text, retry_after=None):
    """What the OpenAI SDK raises for Polza's answer `text` («Error code: N - {...}»), with its status and headers."""
    code = int(re.match(r"Error code: (\d{3})", text).group(1))
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    response = httpx.Response(code, request=httpx.Request("POST", f"{POLZA_URL}/chat/completions"), headers=headers)
    return openai.APIStatusError(text, response=response, body=None)


def _failing(text, retry_after=None):
    """The client of a chain link whose every request gets Polza's error `text`."""

    def create(**kwargs):
        raise _sdk_error(text, retry_after)

    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


@pytest.mark.parametrize(
    "error, retry_after, state",
    [
        (NO_MONEY, None, "no_credits"),
        (KEY_LIMIT, None, "no_credits"),
        (RESERVED, None, "congested"),  # the balance held by the requests in flight: it frees in seconds
        (MINUTE, 40, "rate"),
        (DAY, 36000, "quota"),
        (HOSTS_429, None, "congested"),
        (NO_HOSTS, 5, "congested"),
        (TIMED_OUT, None, "congested"),
        (REVOKED, None, "auth"),
        (FORBIDDEN, None, "auth"),
        (NOT_FOUND, None, "missing"),
        (BAD_REQUEST, None, "error"),
        (TOO_LARGE, None, "error"),
        pytest.param(MODERATION, None, "error"),
    ],
    ids=["402-balance", "402-key-limit", "402-reserved", "429-minute", "429-day", "429-hosts", "503-no-hosts", "408", "401-revoked", "403", "404", "400", "413", "403-moderation"],
)
def test_the_reason_of_a_polza_error_is_the_state_the_chain_recorded(monkeypatch, error, retry_after, state):
    """Polza's answer → both links of the chain → the planner's warning: the reason read from the warning, and the
    links the API shows, are the state the providers recorded (no network: a fake client per link)."""
    from verstka.providers import openai_compat, status

    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: pytest.fail("a test tried to build a real OpenAI client"))
    monkeypatch.setattr(openai_compat.time, "sleep", lambda s: None)  # the chain's and the last link's pauses
    registry = _polza_registry(key=f"test-key-{time.time_ns()}")
    chain = registry.get("llm")
    for link in chain.links:
        link._client = _failing(error, retry_after)
    try:
        with pytest.raises(ProviderError) as ei:
            chain.complete([ChatMessage(role="user", content="Составь план презентации.")])
        assert [status.health_dict(link.health)["state"] for link in chain.links] == [state, state]
        assert str(ei.value).startswith(f"all model links failed: [Qwen3.8-27B] {MAIN}: ")
        assert reason_code([PLANNER_FAILED + str(ei.value)[:160]]) == state  # outline_planner keeps 160 characters
        assert [link["state"] for link in collect_links(registry)[0]] == [state, state]
    finally:
        for link in chain.links:
            status.record_ok(link.health)


# ---------------------------------------------------------------------------- GET /api/models/status


def test_status_without_a_configured_model(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry(key=""))
    st = c.get("/api/models/status").json()
    assert st["configured"] is False and st["state"] == "off" and st["source"] == "none"
    assert st["summary"] == "Модель не подключена" and st["hint"] is None and st["advice"] is None and st["retryable"] is False
    assert st["active_model"] == MAIN and st["active_model_label"] == "Qwen3.8-27B" and st["host"] == POLZA and st["links"] == []


def test_status_of_the_shipped_polza_chain(api, monkeypatch):
    """configs/models.yaml as it ships: the main model and the backup on Polza, one key; nothing called yet."""
    c, mod = api
    monkeypatch.setenv("POLZA_API_KEY", "test-key-shipped-chain")
    monkeypatch.setattr(mod, "_providers", None)  # built from the config on the first request, dropped after the test
    st = c.get("/api/models/status").json()
    assert st["configured"] is True and st["config"] == "configs/models.yaml" and st["source"] == "status"
    assert [(link["model"], link["label"], link["host"], link["roles"]) for link in st["links"]] == [(MAIN, "Qwen3.8-27B", POLZA, ["llm"]), (BACKUP, "Qwen3.6-27B", POLZA, ["llm"])]
    assert all(set(link) == LINK_FIELDS for link in st["links"])  # no "free", no account, no key
    assert st["active_model"] == MAIN and st["active_model_label"] == "Qwen3.8-27B" and st["host"] == POLZA
    assert st["state"] == "unknown" and st["summary"] == "Qwen3.8-27B · доступна" and st["retryable"] is True and st["owner"] is None


def test_status_uses_the_fallback_chain_snapshot(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [
        _link(MAIN, "congested", label="Qwen3.8-27B", last_error="429 upstream, key pza_0123456789abcdefSECRET, Bearer sk-0123456789abcdef", until=95, account="https://polza.ai/api/v1|k3yT41L8"),
        _link(BACKUP, "ok", label="Qwen3.6-27B", last_ok=time.time(), until=None),
    ])
    r = c.get("/api/models/status")
    assert r.status_code == 200
    st = r.json()
    assert st["source"] == "status" and st["state"] == "fallback"
    assert st["summary"] == "Qwen3.6-27B · запасная модель"
    assert st["working_label"] == "Qwen3.6-27B" and st["retry_in"] == 95 and st["retry_state"] == "congested"
    assert st["hint"] == "Презентацию соберёт запасная модель." and st["advice"] == "Сейчас отвечает запасная модель — соберите ещё раз."
    _plain(st["summary"], st["hint"], st["advice"])
    assert [link["state"] for link in st["links"]] == ["congested", "ok"] and st["owner"] is None
    assert "0123456789abcdef" not in r.text and "SECRET" not in r.text and "k3yT41L8" not in r.text  # no key, no account id
    assert all(set(link) == LINK_FIELDS for link in st["links"])
    assert st["config"] == "configs/models.yaml" and st["active_model_label"] == "Qwen3.8-27B" and st["host"] == POLZA
    assert sys.modules["verstka.providers.status"].calls[-1] == "llm"  # the llm chain, in chain order


def test_a_link_without_money_is_the_owners_business_never_the_persons(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [
        _link(MAIN, "no_credits", label="Qwen3.8-27B", until=500, available=False, last_error=f"{MAIN}: no credits (402) on the balance ({NO_MONEY})"),
        _link(BACKUP, "ok", label="Qwen3.6-27B", last_ok=time.time()),
    ])
    st = c.get("/api/models/status").json()
    assert st["state"] == "fallback" and st["summary"] == "Qwen3.6-27B · запасная модель"
    assert len(st["summary"]) <= 80 and st["working_label"] == "Qwen3.6-27B"
    assert st["advice"] == "Сейчас отвечает запасная модель — соберите ещё раз." and st["retryable"] is True
    assert st["hint"] == "Презентацию соберёт запасная модель."
    _plain(st["summary"], st["hint"], st["advice"])
    # the owner's line (a tooltip) names the service and what to fix
    assert st["owner"] == OWNER_MONEY and [link["state"] for link in st["links"]] == ["no_credits", "ok"]
    # both models draw on one balance: once it is empty both are down — the person still reads no money
    _status_module(monkeypatch, [
        _link(MAIN, "no_credits", label="Qwen3.8-27B", until=500, available=False),
        _link(BACKUP, "no_credits", label="Qwen3.6-27B", until=480, available=False),
    ])
    st = c.get("/api/models/status").json()
    assert st["state"] == "down" and st["summary"] == "Qwen3.8-27B · недоступна" and st["retryable"] is False
    assert st["hint"] == st["advice"] == "Модель недоступна." and st["owner"] == OWNER_MONEY  # once, not per link
    _plain(st["summary"], st["hint"], st["advice"])


def test_links_waiting_for_their_key_are_not_failures(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [_link(MAIN, "off", label="Qwen3.8-27B"), _link(BACKUP, "ok", label="Qwen3.6-27B", last_ok=time.time())])
    st = c.get("/api/models/status").json()
    assert st["state"] == "ok" and st["summary"] == "Qwen3.6-27B · доступна" and st["hint"] is None and st["owner"] is None
    assert st["active_model"] == BACKUP and st["links"][0]["available"] is False and st["links"][0]["until"] is None


def test_status_all_links_down(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [_link(MAIN, "congested", until=60), _link(BACKUP, "quota", until=50000)])
    st = c.get("/api/models/status").json()
    assert st["state"] == "down" and st["summary"] == "Qwen3.8-27B · недоступна" and st["working_label"] is None
    assert st["retry_in"] == 60 and st["retry_state"] == "congested" and st["retryable"] is True and st["owner"] is None
    assert st["hint"] == st["advice"] == "Соберите ещё раз через несколько минут."
    _plain(st["summary"], st["hint"], st["advice"])
    _status_module(monkeypatch, [_link(MAIN, "ok", last_ok=time.time()), _link(BACKUP, "quota", until=50000)])
    st = c.get("/api/models/status").json()
    assert st["state"] == "ok" and st["summary"] == "Qwen3.8-27B · доступна" and st["hint"] is None
    # the pause after a failure is over: the next deck tries the model again
    _status_module(monkeypatch, [_link(MAIN, "congested", available=True, until=0)])
    st = c.get("/api/models/status").json()
    assert st["state"] == "retry" and st["summary"] == "Qwen3.8-27B · доступна" and st["advice"] == "Соберите ещё раз — модель попробует снова."


def test_per_minute_cap_is_not_the_daily_quota(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [_link(MAIN, "rate", until=45, available=False, last_error=f"{MAIN}: per-minute request cap of the account, retry in 45 s ({MINUTE})")])
    st = c.get("/api/models/status").json()
    assert st["state"] == "down" and st["retry_state"] == "rate" and st["retry_in"] == 45
    assert st["summary"] == "Qwen3.8-27B · недоступна"
    assert st["hint"] == "Соберите ещё раз через минуту." and "полуноч" not in st["hint"]
    # Polza's daily cap in its last seconds before midnight stays the daily cap (no guessing from the pause's length)
    _status_module(monkeypatch, [_link(MAIN, "quota", until=40, available=False, last_error=f"{MAIN}: daily request quota of the account is spent, skipped for 40 s ({DAY})")])
    st = c.get("/api/models/status").json()
    assert st["links"][0]["state"] == "quota" and st["retry_state"] == "quota" and st["summary"] == "Qwen3.8-27B · недоступна"
    assert st["hint"] == AFTER_MIDNIGHT
    _status_module(monkeypatch, [_link(MAIN, "quota", until=50000, available=False, last_error=f"{MAIN}: daily request quota of the account is spent, skipped for 50000 s ({DAY})")])
    st = c.get("/api/models/status").json()
    assert st["retry_state"] == "quota" and st["hint"] == st["advice"] == AFTER_MIDNIGHT and st["retryable"] is True
    _plain(st["summary"], st["hint"], st["advice"])


def test_a_bad_request_is_an_error_not_congestion(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [_link(MAIN, "error", until=30, available=False, last_error=f"{MAIN}: {BAD_REQUEST}")])
    st = c.get("/api/models/status").json()
    assert st["summary"] == "Qwen3.8-27B · недоступна" and st["links"][0]["state"] == "error"
    assert "перегруж" not in st["summary"] and "перегруж" not in (st["hint"] or "")
    # a status module that records every HTTP error as «error»: Polza's own words tell which it was
    _status_module(monkeypatch, [_link(MAIN, "error", available=False, last_error=f"{MAIN}: {NO_MONEY}"), _link(BACKUP, "error", available=False, last_error=f"{BACKUP}: {REVOKED}")])
    st = c.get("/api/models/status").json()
    assert [link["state"] for link in st["links"]] == ["no_credits", "auth"] and st["retryable"] is False
    assert st["owner"] == f"{OWNER_MONEY} {OWNER_KEY}" and st["advice"] == "Модель недоступна."


def test_status_with_the_real_status_module(api, monkeypatch):
    """Links recorded by verstka.providers.status (the chain's own health) reach the UI in chain order: the main model
    waits out Polza's per-minute cap while the backup answers; then the backup's daily cap is spent too."""
    status = pytest.importorskip("verstka.providers.status")
    c, mod = api
    tag = f"test-{time.time_ns()}"
    h_main = status.link(f"{tag}|{MAIN}", MAIN, "Qwen3.8-27B", host=POLZA)
    h_backup = status.link(f"{tag}|{BACKUP}", BACKUP, "Qwen3.6-27B")  # no host recorded: the link's base_url tells

    class Link:
        name = "polza"
        api_key = "test-key-not-real"
        base_url = POLZA_URL

        def __init__(self, model, health):
            self.model, self.health = model, health

    class Chain:
        name = "chain"
        model = MAIN
        api_key = "test-key-not-real"
        links = [Link(MAIN, h_main), Link(BACKUP, h_backup)]

    monkeypatch.setattr(mod, "_providers", ProviderRegistry(roles={"llm": Chain()}, limits=ProviderLimits()))
    try:
        status.record_error(h_main, "rate", f"{MAIN}: per-minute request cap of the account, retry in 40 s ({MINUTE})", hold_s=40)
        status.record_ok(h_backup)
        st = c.get("/api/models/status").json()
        assert st["source"] == "status" and [link["model"] for link in st["links"]] == [MAIN, BACKUP]
        assert [link["host"] for link in st["links"]] == [POLZA, POLZA] and all(set(link) == LINK_FIELDS for link in st["links"])
        assert st["state"] == "fallback" and st["summary"] == "Qwen3.6-27B · запасная модель" and st["retry_state"] == "rate"
        assert 30 <= st["retry_in"] <= 40 and st["links"][0]["available"] is False and st["owner"] is None
        status.record_error(h_backup, "quota", f"{BACKUP}: daily request quota of the account is spent, skipped for 36000 s ({DAY})", hold_s=36000)
        st = c.get("/api/models/status").json()
        assert st["state"] == "down" and st["summary"] == "Qwen3.8-27B · недоступна"
        # the main model's minute ends first: the live advice waits for it, not for midnight
        assert st["retry_state"] == "rate" and st["advice"] == "Соберите ещё раз через минуту." and st["retryable"] is True
        _plain(st["summary"], st["hint"], st["advice"])
    finally:
        status.record_ok(h_main)
        status.record_ok(h_backup)


def test_a_broken_snapshot_is_logged_and_the_configured_links_shown(api, monkeypatch, caplog):
    import verstka.providers as pkg

    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    fake = types.ModuleType("verstka.providers.status")

    def snapshot(providers=None, role=None):
        raise RuntimeError("broken")

    fake.snapshot = snapshot
    monkeypatch.setitem(sys.modules, "verstka.providers.status", fake)
    monkeypatch.setattr(pkg, "status", fake, raising=False)
    with caplog.at_level(logging.WARNING, logger="verstka.api.model_status"):
        st = c.get("/api/models/status").json()
    assert "snapshot() failed" in caplog.text
    assert st["source"] == "config" and st["state"] == "unknown" and st["summary"] == "Qwen3.8-27B · доступна"
    assert [(link["model"], link["label"], link["host"], link["state"]) for link in st["links"]] == [(MAIN, "Qwen3.8-27B", POLZA, "unknown"), (BACKUP, "Qwen3.6-27B", POLZA, "unknown")]


def test_status_host_never_carries_credentials(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry(base_url="https://user:secret-token-123@proxy.example.org:8443/v1"))
    _status_module(monkeypatch, [])
    r = c.get("/api/models/status")
    st = r.json()
    assert st["host"] == "proxy.example.org" and [link["host"] for link in st["links"]] == ["proxy.example.org"] * 2
    assert "secret-token-123" not in r.text and st["source"] == "config"


def test_status_with_a_mock_model(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", ProviderRegistry.mock())
    st = c.get("/api/models/status").json()
    assert st["configured"] is True and st["state"] == "ok" and st["links"][0]["model"] == "mock-model"


def test_summarize_is_short_and_never_counts_off_links():
    links = [
        {"model": MAIN, "label": "Qwen3.8-27B", "state": "congested", "available": False, "until": 90, "host": POLZA},
        {"model": BACKUP, "label": "Qwen3.6-27B", "state": "unknown", "available": True, "until": None, "host": POLZA},
    ]
    s = summarize(links, configured=True, ctx=chain_context(links))
    assert s["summary"] == "Qwen3.6-27B · запасная модель" and s["advice"] == "Соберите ещё раз — попробую запасную модель."
    assert s["retry_in"] == 90 and s["retry_state"] == "congested" and len(s["summary"]) <= 80
    off_only = [{**link, "state": "off", "available": False} for link in links]
    assert summarize(off_only, configured=True)["state"] == "off" and summarize(off_only, configured=True)["summary"] == "Модель не подключена"
    assert summarize(links, configured=False)["state"] == "off"


def test_older_payloads_and_codes(api, monkeypatch):
    """The reason codes of the first version of this module («no_key», «gone»), and a snapshot of an older status
    module (its records as objects, «until» as a unix time, {"links": [...]}, a state it no longer has): read in
    today's words — and nothing of a record but the shown fields reaches the API."""
    from verstka.providers import status

    rm = {**CONFIGURED, "warnings": [], "planner": {"planned_by": "rules", "reason_code": "no_key"}}
    key = planner_info({"planned_by": "rules"}, rm, use_models=True, ctx=POLZA_CTX)
    assert key["reason_code"] == "auth" and key["advice"] == "Модель недоступна." and key["retryable"] is False and key["owner"] == OWNER_KEY
    gone = planner_info({"planned_by": "rules"}, {**rm, "planner": {"planned_by": "rules", "reason_code": "gone"}}, use_models=True, ctx=POLZA_CTX)
    assert gone["reason_code"] == "missing" and gone["owner"] == OWNER_GONE
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    record = status.LinkHealth(key=f"{POLZA_URL}|SECRET12|{MAIN}", model=MAIN, label="Qwen3.8-27B", host=POLZA, state="ok", last_ok=time.time())
    _status_module(monkeypatch, {"links": [
        record,
        _link(BACKUP, "gone", label="Qwen3.6-27B", until=time.time() + 60),
        _link("qwen/qwen3-32b", "no_key", label="Qwen3 32B"),
        _link("qwen/qwen2.5-7b", "weird"),
    ]})
    r = c.get("/api/models/status")
    st = r.json()
    assert [link["state"] for link in st["links"]] == ["ok", "missing", "auth", "unknown"]
    assert 55 <= st["links"][1]["until"] <= 60 and st["links"][1]["available"] is False and st["links"][2]["available"] is False
    assert "SECRET12" not in r.text and all(set(link) == LINK_FIELDS for link in st["links"])
    assert st["state"] == "ok" and st["summary"] == "Qwen3.8-27B · доступна"


# the last error a link of each state records: the providers' contract wording, then Polza's own words
_LAST_ERROR = {
    "congested": f"congested upstream, skipped for 120 s more ({HOSTS_429})",
    "rate": f"per-minute request cap of the account, retry in 40 s ({MINUTE})",
    "quota": f"daily request quota of the account is spent, skipped for 36000 s ({DAY})",
    "no_credits": f"no credits (402) on the balance ({NO_MONEY})",
    "auth": f"access refused (401/403): HTTP 401, check the key ({REVOKED})",
    "missing": f"model not available (404): no such model or no host serves it ({NOT_FOUND})",
    "error": BAD_REQUEST,
}
_HOLD = {"congested": 120, "rate": 40, "quota": 36000, "no_credits": 600, "auth": 1800, "missing": 1800}


def _row(model, label, state):
    """A link of the chain in `state`, as verstka.providers.status.snapshot() reports it."""
    err = _LAST_ERROR.get(state)
    return {"model": model, "label": label, "host": POLZA, "state": state, "available": state != "off" and state not in _HOLD, "until": _HOLD.get(state),
            "last_ok": None, "last_error": f"{model}: {err}" if err else None, "roles": ["llm"]}


def test_no_word_a_person_reads_names_the_service_money_or_keys(monkeypatch):
    """summary, hint and advice — for every state of the main model and the backup, and for every reason a deck gets
    from Polza — never name the service, money, keys or config files. The owner's line names Polza and the fix."""
    registry = _polza_registry()
    seen = set()
    for a in LINK_STATES:
        for b in LINK_STATES:
            _status_module(monkeypatch, [_row(MAIN, "Qwen3.8-27B", a), _row(BACKUP, "Qwen3.6-27B", b)])
            st = models_status(registry, configured=True, config_path=None, repo_root=Path("."))
            assert [link["state"] for link in st["links"]] == [a, b]
            assert re.fullmatch(r"Qwen3\.[86]-27B · (доступна|запасная модель|недоступна)|Модель не подключена", st["summary"]), (a, b, st["summary"])
            _plain(st["summary"], st["hint"], st["advice"])
            if st["owner"]:
                parts = re.split(r"(?<=\.) ", st["owner"])
                assert set(parts) <= {OWNER_MONEY, OWNER_KEY, OWNER_GONE} and len(parts) == len(set(parts)), (a, b, st["owner"])
                seen.update(parts)
    assert seen == {OWNER_MONEY, OWNER_KEY, OWNER_GONE}
    for error in (NO_MONEY, KEY_LIMIT, RESERVED, MINUTE, DAY, HOSTS_429, NO_HOSTS, TIMED_OUT, REVOKED, FORBIDDEN, NOT_FOUND, BAD_REQUEST, TOO_LARGE):
        info = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: {error}; [Qwen3.6-27B] {BACKUP}: {error}")
        g = generation_planner([{"planner": info}], use_models=True)
        _plain(info["reason"], info["advice"], g["reason"], g["advice"])
        assert info["owner"] is None or "Polza" in info["owner"], error


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
    chain = [{"backend": "polza", "model": MAIN, "label": "Qwen3.8-27B", "off": False}, {"backend": "polza", "model": BACKUP, "label": "Qwen3.6-27B", "off": False}]
    rm = {"strategy": "structured", "providers": {"llm": {"backend": "chain", "model": MAIN, "chain": chain}}, "warnings": warnings}
    if planner:
        rm["planner"] = planner
    (vdir / "run_manifest.json").write_text(json.dumps(rm), encoding="utf-8")
    mod.store.write_generation_meta(gid, {"id": gid, "template_id": "t", "strategies": ["structured"], "use_models": use_models, "slides": 12, "status": "done", **meta})
    return gid


def test_generation_says_why_the_model_did_not_plan(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [_link(MAIN, "unknown", label="Qwen3.8-27B"), _link(BACKUP, "unknown", label="Qwen3.6-27B")])
    g = c.get(f"/api/generations/{_fake_generation(mod)}").json()
    v = g["variants"][0]
    assert v["planner"]["planned_by"] == "rules" and v["planner"]["reason_code"] == "congested"
    assert g["planner"]["by_model"] is False and g["planner"]["reason"] == "сервер модели перегружен"
    assert g["planner"]["tried_label"] == "Qwen3.8-27B" and g["planner"]["retryable"] is True
    assert g["planner"]["advice"] == "Соберите ещё раз через несколько минут." and g["planner"]["steady"] is None and g["planner"]["owner"] is None
    # an empty Polza balance: the person reads that the model is unavailable, the owner's line names the fix
    broke = [PLANNER_FAILED + f"all model links failed: [Qwen3.8-27B] {MAIN}: no credits (402) on the balance ({NO_MONEY}); [Qwen3.6-27B] {BACKUP}: no credits (402) on the balance ({NO_MONEY})"]
    g = c.get(f"/api/generations/{_fake_generation(mod, 'rules', broke)}").json()
    assert g["planner"]["reason_code"] == "no_credits" and g["planner"]["reason"] == "модель недоступна"
    assert g["planner"]["advice"] == "Модель недоступна." and g["planner"]["retryable"] is False and g["planner"]["owner"] == OWNER_MONEY
    _plain(g["planner"]["reason"], g["planner"]["advice"])
    g = c.get(f"/api/generations/{_fake_generation(mod, 'model', [], {'planned_by': 'model', 'model': BACKUP})}").json()
    assert g["planner"]["by_model"] is True and g["planner"]["model_label"] == "Qwen3.6-27B"
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
    from verstka.providers.base import CompletionResult, Usage

    class Chain:  # a fallback chain answering with its backup model
        name = "chain"
        model = MAIN

        def complete(self, messages, **kwargs):
            return CompletionResult(text="{}", parsed=None, usage=Usage(), model=BACKUP)

    reg = ProviderRegistry(roles={"llm": Chain()}, limits=ProviderLimits())
    rec, answered = _recording(reg)
    assert rec is not reg and rec.get("llm").model == MAIN
    rec.get("llm").complete([ChatMessage(role="user", content="hi")], temperature=0.1)
    assert answered == [BACKUP]
    assert reg.get("llm").__class__ is Chain  # the shared registry stays unwrapped
    assert _recording(None) == (None, [])


class _Backup(MockProvider):
    """A chain whose main model is congested: every answer comes from the backup."""

    def complete(self, messages, **kwargs):
        res = super().complete(messages, **kwargs)
        res.model = BACKUP
        return res


# a model plan of SHORT (a plan is grounded in its own brief: verstka.planning.grounding)
SHORT_PLAN = {
    "title": "Итоги пилота «Умные сводки» за второй квартал",
    "slides": [
        {"id": "sl1", "kind": "title", "headline": "Итоги пилота «Умные сводки» за второй квартал"},
        {"id": "sl2", "kind": "big_number", "headline": "Время на чтение чатов сократилось на 18 минут в день", "content": {"numbers": [{"value": "47 → 29 минут", "label": "в день на чтение чатов"}]}},
        {"id": "sl3", "kind": "bullets", "headline": "Сводки экономят время сотрудников", "content": {"bullets": ["Время на чтение чатов сократилось с 47 до 29 минут в день", "Это на 38% меньше, чем до пилота"]}},
        {"id": "sl4", "kind": "thanks", "headline": "Спасибо за внимание"},
    ],
}


def _only_compact_plans(messages):
    text = "\n".join(m.content for m in messages)
    if "Return the JSON plan only" in text:
        if "Стратегия «Компактный»" in text:
            return SHORT_PLAN
        raise ProviderError(f"all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream, skipped for 95 s more; [Qwen3.6-27B] {BACKUP}: congested upstream")
    if "List the issues" in text:
        return {"issues": []}
    return {"facts": [], "series": [], "tables": []}


def _backup_registry() -> ProviderRegistry:
    p = _Backup(_only_compact_plans, model=MAIN)
    return ProviderRegistry(roles={"llm": p, "vlm": p}, limits=ProviderLimits(max_concurrency=1))


def test_pipeline_writes_the_planner_model_for_own_and_shared_variants(simple_deck, tmp_path):
    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import parse_brief_text
    from verstka.skills_registry.registry import SkillsRegistry

    res = generate_variants(simple_deck, brief=parse_brief_text(SHORT), strategies=["structured", "compact"], out_dir=tmp_path / "out", workspace_root=tmp_path / "ws", providers=_backup_registry(), skills=SkillsRegistry.load(), use_vlm=False, audit=False, autofix=False, exports=[], render_images=False)
    by = {v.strategy: v for v in res.variants}
    assert by["compact"].planner == {"planned_by": "model", "model": BACKUP}
    assert by["structured"].planner == {"planned_by": "shared:compact", "model": BACKUP}  # the donor's model
    for name in ("structured", "compact"):
        rm = json.loads((tmp_path / "out" / name / "run_manifest.json").read_text(encoding="utf-8"))
        assert rm["planner"]["model"] == BACKUP and rm["planner"]["planned_by"] == by[name].planner["planned_by"]


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
    assert meta["summary"]["structured"]["model"] == BACKUP and meta["summary"]["structured"]["reason"] is None
    assert meta["planner"]["by_model"] is True and meta["planner"]["model_label"] == "Qwen3.6-27B"
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


# ---------------------------------------------------------------------------- rules, links, retry, texts

# an older deck: the data step hit the hosts' 429, the fact check ran out of time — the model planned it
OLD_MODEL_PLANNED = [
    f"data_extractor failed, using regex facts: {MAIN}: no valid completion after 3 attempts: {HOSTS_429[:120]}",
    f"fact_checker skipped: {MAIN}: time budget of the generation is spent (no answer yet)",
]


def test_contract_phrases_are_the_status_modules():
    status = pytest.importorskip("verstka.providers.status")
    assert CONTRACT_PHRASES == {k: v for k, v in status.PHRASES.items() if k in CONTRACT_PHRASES}
    assert set(CONTRACT_PHRASES) == set(status.PHRASES)
    assert LINK_STATES == status.STATES
    # a snapshot row: the link's model, label, host, state, pause, last success and error, roles — no "free", no account
    registry = _polza_registry(key=f"test-key-{time.time_ns()}")
    rows = status.snapshot(registry, role="llm")
    assert [set(row) for row in rows] == [{"model", "label", "host", "state", "available", "until", "last_ok", "last_error", "roles"}] * 2
    assert [(row["model"], row["label"], row["host"], row["roles"]) for row in rows] == [(MAIN, "Qwen3.8-27B", POLZA, ["llm"]), (BACKUP, "Qwen3.6-27B", POLZA, ["llm"])]


@pytest.mark.parametrize(
    "warning, code",
    [
        # the seconds of a hold are never read as a status code
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: model not available (404), skipped for 402 s more ({MAIN}: model not available (404): no such model)", "missing"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: model not available (404), skipped for 401 s more", "missing"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: access refused (401/403), skipped for 404 s more", "auth"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream, skipped for 403 s more", "congested"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: per-minute request cap of the account, retry in 402 s ({MINUTE})", "rate"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: per-minute request cap of the account (20/min), next slot in 401 s", "rate"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: the model did not answer, skipped for 402 s more ({MAIN}: connection error (Connection refused))", "unreachable"),
        # the contract wording first, then the codes: a 402 that speaks of a limit is «no credits», never a cap
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: no credits (402): the spending limit of the key is spent ({KEY_LIMIT})", "no_credits"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: access refused (401/403): HTTP 401, check the key ({REVOKED})", "auth"),
        # the balance held by the requests in flight is a 402 that passes by itself: congestion, not an empty balance
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream: the balance is held by the requests in flight (402) ({RESERVED})", "congested"),
        # a hold quotes the error that opened it: the wording that comes first wins
        (f"all model links failed: [Qwen3.6-27B] {BACKUP}: daily request quota, skipped for 40000 s more ({BACKUP}: per-minute request cap of the account, retry in 40 s ({MINUTE}))", "quota"),
        (f"all model links failed: [Qwen3.6-27B] {BACKUP}: per-minute request cap, skipped for 40 s more ({BACKUP}: daily request quota of the account is spent ({DAY}))", "rate"),
        (f"all model links failed: [Qwen3.8-27B] {MAIN}: request timed out, congested upstream", "congested"),
    ],
)
def test_contract_wording_comes_before_status_codes(warning, code):
    assert reason_code([PLANNER_FAILED + warning]) == code


def test_an_older_deck_is_not_a_rules_deck_because_a_data_step_failed():
    """Without planned_by only the planner's own failure means the rules planned; a data_extractor 429 or a fact check
    that ran out of time says nothing against the model's plan (a fact check runs on a model plan only)."""
    planned = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": OLD_MODEL_PLANNED}, use_models=True, ctx=POLZA_CTX)
    assert planned["by_model"] is True and planned["planned_by"] == "model" and planned["reason"] is None and planned["model_label"] == "Qwen3.8-27B"
    repaired = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": [f"repair pass failed: {MAIN}: congested upstream"]}, use_models=True, ctx=POLZA_CTX)
    assert repaired["by_model"] is True  # a failed repair keeps the model's plan
    data_only = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": OLD_MODEL_PLANNED[:1]}, use_models=True, ctx=POLZA_CTX)
    assert data_only["by_model"] is None and data_only["reason_code"] is None and data_only["advice"] is None
    # the variant whose own planner failed is a rules deck, whatever the data step did
    visual = planner_info({"title": "Т"}, {**CONFIGURED, "warnings": [OLD_MODEL_PLANNED[0], PLANNER_FAILED + f"{MAIN}: time budget of the generation is spent, no room to wait out a 429 ({HOSTS_429})"]}, use_models=True, ctx=POLZA_CTX)
    assert visual["by_model"] is False and visual["planned_by"] == "rules" and visual["reason_code"] == "congested"
    # the generation as a whole: a model planned some variants — no failure notice over the deck
    g = generation_planner([{"planner": planned}, {"planner": visual}, {"planner": data_only}], use_models=True)
    assert g["by_model"] is True and g["reason"] is None
    assert generation_planner([{"planner": data_only}], use_models=True)["by_model"] is None


def test_an_older_deck_via_the_api(api, monkeypatch):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    _status_module(monkeypatch, [_link(MAIN, "unknown", label="Qwen3.8-27B"), _link(BACKUP, "unknown", label="Qwen3.6-27B")])
    g = c.get(f"/api/generations/{_fake_generation(mod, None, OLD_MODEL_PLANNED)}").json()
    assert g["planner"]["by_model"] is True and g["planner"]["reason"] is None
    g = c.get(f"/api/generations/{_fake_generation(mod, None, OLD_MODEL_PLANNED[:1])}").json()
    assert g["planner"]["by_model"] is None and g["planner"]["reason"] is None


def test_reason_words_are_about_the_link_that_failed():
    """The clause in the server log names the service of the link that failed; the API's reason and the advice never
    do."""
    busy = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: congested upstream, skipped for 120 s more ({HOSTS_429}); [Qwen3.6-27B] {BACKUP}: congested upstream ({HOSTS_429})")
    assert busy["reason_code"] == "congested" and busy["detail"] == "хосты модели на Polza сейчас перегружены"
    assert busy["reason"] == "сервер модели перегружен" and busy["advice"] == "Соберите ещё раз через несколько минут." and busy["steady"] is None and busy["owner"] is None
    minute = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: per-minute request cap of the account, retry in 40 s ({MINUTE}); [Qwen3.6-27B] {BACKUP}: per-minute request cap of the account, retry in 41 s ({MINUTE})")
    assert minute["reason_code"] == "rate" and minute["detail"] == "исчерпан минутный лимит запросов Polza к модели" and minute["advice"] == "Соберите ещё раз через минуту."
    broke = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: no credits (402) on the balance ({NO_MONEY}); [Qwen3.6-27B] {BACKUP}: congested upstream ({HOSTS_429})")
    assert broke["reason_code"] == "no_credits" and broke["detail"] == "на балансе Polza нет средств или исчерпан лимит расходов ключа"
    assert broke["advice"] == "Модель недоступна." and broke["retryable"] is False and broke["owner"] == OWNER_MONEY
    gone = _rules("all model links failed: [Qwen3.8-27B] qwen/qwen9-27b: model not available (404): no such model or no host serves it")
    assert gone["detail"] == "этой модели сейчас нет на Polza" and gone["owner"] == OWNER_GONE
    _plain(*(x["advice"] for x in (busy, minute, broke, gone)))
    # a model of an older config, not in the active chain: the chain's own service
    old = _rules("qwen/qwen3.6-35b-a3b: congested upstream (Provider returned error)")
    assert old["detail"] == "сервер модели сейчас перегружен"  # an older config's link: no service of today is named
    # the final's VK inference: no service named, the owner's fix is generic
    vk_busy = _rules(f"{VK_MODEL}: 500 server error, congested upstream", VK)
    assert vk_busy["detail"] == "сервер модели сейчас перегружен" and "Polza" not in (vk_busy["advice"] or "")
    vk_key = _rules(f"{VK_MODEL}: no valid completion after 3 attempts: {VK_MODEL}: access refused (401/403): HTTP 401, check the key", VK)
    assert vk_key["detail"] == "ключ доступа к модели не подходит" and vk_key["owner"] == "Сервис модели отказал в доступе (401/403): проверьте ключ API."


def test_the_failed_link_is_the_one_the_chain_named_by_its_label():
    """Each failed link is named by its label before its part: the reason is about that link (the main model or the
    backup), and the owner reads every link's fix once."""
    two = f"all model links failed: [Qwen3.8-27B] {MAIN}: no credits (402) on the balance ({NO_MONEY}); [Qwen3.6-27B] {BACKUP}: access refused (401/403): HTTP 401, check the key ({REVOKED})"
    info = _rules(two)
    assert info["reason_code"] == "auth" and info["detail"] == "ключ доступа к Polza не подходит" and info["advice"] == "Модель недоступна."
    assert info["owner"] == f"{OWNER_KEY} {OWNER_MONEY}"  # the reason's fix first, then the other link's
    # the second pass names the link again («again: [label]»): still that link
    again = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: per-minute request cap of the account, retry in 40 s; again: [Qwen3.6-27B] {BACKUP}: 503 server error, congested upstream ({NO_HOSTS})")
    assert again["reason_code"] == "congested" and again["detail"] == "хосты модели на Polza сейчас перегружены"
    # labels of one's own that name no service: looked up in the active chain (the same model id on two hosts)
    mirror = chain_context([_link(MAIN, "unknown", label="Qwen основная"), _link(MAIN, "unknown", host="llm.example.org", label="Qwen зеркало")], "configs/models.yaml")
    assert _rules(f"all model links failed: [Qwen основная] {MAIN}: no credits (402); [Qwen зеркало] {MAIN}: access refused (401/403)", mirror)["detail"] == "ключ доступа к модели не подходит"
    assert _rules(f"all model links failed: [Qwen основная] {MAIN}: access refused (401/403); [Qwen зеркало] {MAIN}: congested upstream", mirror)["owner"] == OWNER_KEY
    # a label is a name, never a reason: «402» or «404» in it is not a status code
    assert reason_code([PLANNER_FAILED + "all model links failed: [Qwen 402B (VK)] qwen-402b: congested upstream"]) == "congested"
    assert reason_code([PLANNER_FAILED + "all model links failed: [Model 404 (local)] m404: request timed out"]) == "timeout"


@pytest.mark.parametrize(
    "warning, retryable",
    [
        (f"{MAIN}: congested upstream ({HOSTS_429})", True),
        (f"{MAIN}: 503 server error, congested upstream ({NO_HOSTS})", True),
        (f"{MAIN}: per-minute request cap of the account, retry in 20 s ({MINUTE})", True),
        (f"{MAIN}: daily request quota of the account is spent, skipped for 50000 s ({DAY})", True),
        (f"{MAIN}: time budget of the generation is spent (no answer yet)", True),
        (f"{MAIN}: connection error (Connection refused)", True),
        (f"{MAIN}: no credits (402) on the balance ({NO_MONEY})", False),
        (f"{MAIN}: no credits (402): the spending limit of the key is spent ({KEY_LIMIT})", False),
        (f"{MAIN}: access refused (401/403): HTTP 401, check the key ({REVOKED})", False),
        (f"{MAIN}: model not available (404): no such model or no host serves it ({NOT_FOUND})", False),
        (f"{MAIN}: {BAD_REQUEST}", False),
    ],
    ids=["hosts-429", "503-no-hosts", "minute-cap", "daily-cap", "time-budget", "connection", "402-balance", "402-key-limit", "401-revoked", "404", "400"],
)
def test_a_rebuild_is_offered_only_for_reasons_it_can_get_past(warning, retryable):
    info = _rules(warning)
    assert info["retryable"] is retryable and (info["reason_code"] in RETRYABLE_REASONS) is retryable
    assert generation_planner([{"planner": info}], use_models=True)["retryable"] is retryable
    if not retryable:
        assert info["advice"] and "Соберите ещё раз" not in info["advice"]  # what to fix instead
    _plain(info["advice"])
    rejected = planner_info({"planned_by": "rules"}, {**CONFIGURED, "warnings": ["outline_planner answer rejected (2 slides), deterministic outline used"]}, use_models=True)
    assert rejected["retryable"] is True


def test_the_live_advice_follows_the_live_state():
    ok = summarize([_link(MAIN, "ok", available=True)], configured=True)
    assert ok["advice"] == "Модель снова отвечает — соберите ещё раз." and ok["retryable"] is True
    assert summarize([_link(MAIN, "unknown", available=True)], configured=True)["advice"] == "Соберите ещё раз — модель попробует снова."
    # the provider's pause is not a person's business: the words are the same as for an unknown state
    assert summarize([_link(MAIN, "congested", available=True)], configured=True)["advice"] == "Соберите ещё раз — модель попробует снова."
    fb = summarize([_link(MAIN, "congested", available=False, until=90, label="Qwen3.8-27B"), _link(BACKUP, "unknown", available=True, label="Qwen3.6-27B")], configured=True)
    assert fb["advice"] == "Соберите ещё раз — попробую запасную модель." and fb["retryable"] is True and fb["state"] == "fallback"
    # every link pauses: the advice is about the link whose pause ends first (the one the button waits for); the hint
    # under the indicator is about the main model
    down = summarize([_link(MAIN, "quota", available=False, until=50000), _link(BACKUP, "congested", available=False, until=90)], configured=True, ctx=POLZA_CTX)
    assert down["state"] == "down" and down["retry_state"] == "congested" and down["retry_in"] == 90 and down["retryable"] is True
    # the line under the indicator and the advice speak of the same link: the one whose pause ends first
    assert down["advice"] == "Соберите ещё раз через несколько минут." and down["hint"] == down["advice"]
    quota = summarize([_link(MAIN, "quota", available=False, until=50000)], configured=True)
    assert quota["advice"] == AFTER_MIDNIGHT and quota["retryable"] is True and quota["owner"] is None
    # a key that does not fit is not waited out: no rebuild, the advice says the model is unavailable
    auth = summarize([_link(MAIN, "auth", available=False, until=1800)], configured=True)
    assert auth["retryable"] is False and auth["advice"] == "Модель недоступна." and auth["summary"] == "Qwen3.8-27B · недоступна" and auth["owner"] == OWNER_KEY
    # «error» with a pause is a connection that kept dropping: worth waiting out, and it is not «the same error again»
    conn = summarize([_link(MAIN, "error", available=False, until=60, last_error=f"{MAIN}: connection error (Connection refused)")], configured=True)
    assert conn["retryable"] is True and conn["advice"].startswith("Проверьте подключение") and conn["summary"] == "Qwen3.8-27B · недоступна"
    # a 400 opens no pause: the same deck gets the same answer
    bad = summarize([_link(MAIN, "error", available=False, last_error=f"{MAIN}: {BAD_REQUEST}")], configured=True)
    assert bad["retryable"] is False and bad["advice"] == "Та же сборка получит ту же ошибку: сократите текст."
    assert summarize([], configured=False)["retryable"] is False


def _fake_status_module(monkeypatch, fn):
    import verstka.providers as pkg

    fake = types.ModuleType("verstka.providers.status")
    fake.snapshot = fn
    monkeypatch.setitem(sys.modules, "verstka.providers.status", fake)
    monkeypatch.setattr(pkg, "status", fake, raising=False)


def test_a_type_error_inside_snapshot_is_logged_not_retried_without_the_role(api, monkeypatch, caplog):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    calls = []

    def snapshot(providers=None, role=None):
        calls.append(role)
        if role is not None:
            raise TypeError("a bug inside snapshot()")
        return [_link(MAIN, "ok"), _link(BACKUP, "ok"), _link(MAIN, "ok"), _link(BACKUP, "ok")]  # llm and vlm merged: never shown

    _fake_status_module(monkeypatch, snapshot)
    with caplog.at_level(logging.WARNING, logger="verstka.api.model_status"):
        st = c.get("/api/models/status").json()
    assert calls == ["llm"] and "snapshot() failed" in caplog.text and "a bug inside snapshot()" in caplog.text
    assert st["source"] == "config" and [link["model"] for link in st["links"]] == [MAIN, BACKUP]


def test_an_older_snapshot_signature_is_called_once(api, monkeypatch, caplog):
    c, mod = api
    monkeypatch.setattr(mod, "_providers", _polza_registry())
    calls = []

    def snapshot(providers):  # no role: the registry's links
        calls.append(providers)
        return [_link(MAIN, "ok", last_ok=time.time())]

    _fake_status_module(monkeypatch, snapshot)
    st = c.get("/api/models/status").json()
    assert len(calls) == 1 and calls[0] is mod._providers and st["source"] == "status" and st["state"] == "ok"

    def odd(a, b, c):
        raise AssertionError("never called")

    _fake_status_module(monkeypatch, odd)
    with caplog.at_level(logging.WARNING, logger="verstka.api.model_status"):
        st = c.get("/api/models/status").json()
    assert "takes none of" in caplog.text and st["source"] == "config"


# ---------------------------------------------------------------------------- the owner's reason


def test_the_owner_learns_what_to_fix_and_where():
    polza, vk = FailedLink(MAIN, "Polza"), FailedLink(VK_MODEL, None)
    assert owner_reason("no_credits", polza) == OWNER_MONEY
    assert owner_reason("auth", polza) == OWNER_KEY
    assert owner_reason("missing", polza) == OWNER_GONE
    # another host (the final's VK inference): the same fixes, no service named
    assert owner_reason("no_credits", vk) == "На счёте сервиса модели нет средств: пополните баланс."
    assert owner_reason("auth", vk) == "Сервис модели отказал в доступе (401/403): проверьте ключ API."
    assert owner_reason("missing", vk) == "Модели нет на сервере (404): проверьте её название в настройках."
    # without the link, the text of its error tells the service
    assert owner_reason("no_credits", None, f"{POLZA_URL}: {NO_MONEY}") == OWNER_MONEY
    assert owner_reason("auth", None, f"{VK_MODEL}: {REVOKED}") == "Сервис модели отказал в доступе (401/403): проверьте ключ API."
    # a reason a rebuild gets past needs no owner
    for code in ("congested", "rate", "quota", "timeout", "unreachable", "rejected", "error", "off", None):
        assert owner_reason(code, polza, NO_MONEY) is None, code
    # every link's fix once: both models on one empty balance are one thing to fix, a missing model another
    pairs = [("no_credits", polza, None), ("no_credits", FailedLink(BACKUP, "Polza"), None), ("missing", FailedLink(BACKUP, "Polza"), None), ("congested", polza, None)]
    assert owner_reasons(pairs) == f"{OWNER_MONEY} {OWNER_GONE}"
    assert owner_reasons([("quota", polza, DAY)]) is None and owner_reasons([]) is None
    # the person reads none of it
    for code in ("no_credits", "auth", "missing"):
        assert reason_text(code) == "модель недоступна" and advice(code) == "Модель недоступна."


def test_the_generation_and_the_status_carry_the_owners_reason():
    """Gate 4 G4-21: the writer failed (Polza refused the key) and the topic's deck is a skeleton: the person reads
    «модель недоступна», the owner's line says what to fix."""
    revoked = f"all model links failed: [Qwen3.8-27B] {MAIN}: access refused (401/403): HTTP 401, check the key ({REVOKED}); [Qwen3.6-27B] {BACKUP}: access refused (401/403): HTTP 401, check the key ({REVOKED})"
    info = planner_info({"planned_by": "skeleton"}, {**CONFIGURED, "warnings": ["deck_writer failed: " + revoked]}, use_models=True, ctx=POLZA_CTX)
    assert info["planned_by"] == "skeleton" and info["reason_code"] == "auth" and info["reason"] == "модель недоступна"
    assert info["advice"] == "Модель недоступна." and info["retryable"] is False and info["owner"] == OWNER_KEY
    assert generation_planner([{"planner": info}], use_models=True)["owner"] == info["owner"]
    links = [_link(MAIN, "auth", label="Qwen3.8-27B", available=False, until=1800, last_error=f"{MAIN}: access refused (401/403) ({REVOKED})"),
             _link(BACKUP, "auth", label="Qwen3.6-27B", available=False, until=1700, last_error=f"{BACKUP}: access refused (401/403) ({REVOKED})")]
    s = summarize(links, configured=True, ctx=chain_context(links))
    assert s["state"] == "down" and s["owner"] == OWNER_KEY and s["retryable"] is False and s["retry_state"] == "auth"
    assert "Polza" not in s["summary"] and "Polza" not in (s["advice"] or "") and "Polza" not in (s["hint"] or "")
    _plain(s["summary"], s["hint"], s["advice"])


# ---------------------------------------------------------------------------- a refused request, a single model


def test_a_moderation_refusal_is_not_a_rejected_key(monkeypatch):
    """Polza answers 403 also when its moderation refuses one request (polza.ai/docs: «Коды ответов»): the key is fine,
    the same request gets the same answer — an «error», no owner's fix, the live link stays «error»."""
    refused = f"the request was refused by moderation (403) ({MODERATION})"
    info = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: {refused}; [Qwen3.6-27B] {BACKUP}: {refused}")
    assert info["reason_code"] == "error" and info["owner"] is None
    _status_module(monkeypatch, [_link(MAIN, "error", label="Qwen3.8-27B", available=True, last_error=f"{MAIN}: {refused}")])
    st = models_status(_polza_registry(), configured=True, config_path=None, repo_root=Path("."))
    assert st["links"][0]["state"] == "error"


@pytest.mark.parametrize("step, planned_by", [("deck_writer failed: ", "skeleton"), ("agent failed, the planner takes over: ", "rules")])
def test_the_writers_or_the_agents_failure_with_a_single_model_is_read(step, planned_by):
    """One model without a chain fails with its own message — no «all model links failed»: the step is still the
    planner's own failure, and the reason in it is what the deck's notice and the owner's line need."""
    bare = f"{VK_MODEL}: no valid completion after 3 attempts: {VK_MODEL}: access refused (401/403): HTTP 401, check the key (Error code: 401 - Invalid API key)"
    assert reason_code([step + bare]) == "auth"
    info = planner_info({"planned_by": planned_by}, {"providers": {"llm": {"backend": "openai_compat", "model": VK_MODEL}}, "warnings": [step + bare]}, use_models=True, ctx=VK)
    assert info["reason_code"] == "auth" and info["owner"] == "Сервис модели отказал в доступе (401/403): проверьте ключ API."


# ---------------------------------------------------------------------------- the web texts (modelText.ts, run by node)

_WEB = Path(__file__).resolve().parents[2] / "web"
_RUNNER = r"""
import * as m from "./modelText.mjs";
const now = Date.UTC(2026, 8, 25, 10, 0, 0); // 13:00 in Moscow
const midnight = Date.UTC(2026, 8, 25, 21, 0, 0); // 00:00 in Moscow: Polza's daily caps reset
const toMidnight = (midnight - now) / 1000;
const UNAVAILABLE = "Модель недоступна.";
const SHORTEN = "Та же сборка получит ту же ошибку: сократите текст.";
const AFTER_MIDNIGHT = "Соберите ещё раз после полуночи по московскому времени.";
const st = (over) => ({ configured: true, config: null, active_model: null, active_model_label: null, host: null, links: [], source: "status", summary: "", hint: null, working_label: null, retry_in: null, retry_state: null, advice: null, retryable: true, owner: null, ...over });
const p = (code, retryable, advice) => ({ planned_by: "rules", by_model: false, model: null, model_label: null, tried_label: "Qwen3.8-27B", reason_code: code, reason: "причина", advice, retryable, owner: null });
const down = st({ state: "down", retry_in: 90, retry_state: "congested", advice: "Соберите ещё раз через несколько минут." });
const blockedByKey = st({ state: "down", retry_in: 1800, retry_state: "auth", retryable: false, advice: UNAVAILABLE });
const unknown = st({ state: "unknown", advice: "Соберите ещё раз — модель попробует снова." });
const ok = st({ state: "ok", advice: "Модель снова отвечает — соберите ещё раз." });
const offers = {
  congestedDown: m.rebuildOffer(p("congested", true, "Соберите ещё раз через несколько минут."), { status: down, latest: false, retryIn: 80 }),
  // an older server's advice spoke of money and keys: those clauses never reach the screen
  congestedOlder: m.rebuildOffer(p("congested", true, "Соберите ещё раз через несколько минут или пополните баланс Polza."), { status: null, latest: true, retryIn: 0 }),
  authUnknownOlder: m.rebuildOffer(p("auth", false, "Проверьте ключ доступа к Polza в настройках сервера."), { status: unknown, latest: true, retryIn: 0 }),
  authUnknown: m.rebuildOffer(p("auth", false, UNAVAILABLE), { status: unknown, latest: true, retryIn: 0 }),
  authOkLatest: m.rebuildOffer(p("auth", false, UNAVAILABLE), { status: ok, latest: true, retryIn: 0 }),
  authOkOlder: m.rebuildOffer(p("auth", false, UNAVAILABLE), { status: ok, latest: false, retryIn: 0 }),
  congestedBlockedByKey: m.rebuildOffer(p("congested", true, "Соберите ещё раз через несколько минут."), { status: blockedByKey, latest: false, retryIn: 1700 }),
  error400: m.rebuildOffer(p("error", false, SHORTEN), { status: unknown, latest: true, retryIn: 0 }),
  quotaOlderOk: m.rebuildOffer(p("quota", true, AFTER_MIDNIGHT), { status: ok, latest: false, retryIn: 0 }),
  quotaDown: m.rebuildOffer(p("quota", true, AFTER_MIDNIGHT), { status: st({ state: "down", retry_in: toMidnight, retry_state: "quota", advice: AFTER_MIDNIGHT }), latest: true, retryIn: toMidnight - 5 }),
  noStatus: m.rebuildOffer(p("congested", undefined, "Соберите ещё раз через несколько минут."), { status: null, latest: true, retryIn: 0 }),
  noStatusAuth: m.rebuildOffer(p("auth", undefined, UNAVAILABLE), null),
  unknownKeepsSteady: m.rebuildOffer({ ...p("congested", true, "Соберите ещё раз через несколько минут."), steady: "Чтобы не ждать, пополните баланс Polza." }, { status: unknown, latest: true, retryIn: 0 }),
  downHasItsOwn: m.rebuildOffer({ ...p("congested", true, "x"), steady: "Чтобы не ждать, пополните баланс Polza." }, { status: down, latest: true, retryIn: 80 }),
  // every model pauses and the paused links can be retried, but the deck's own reason needs a fix
  noCreditsDown: m.rebuildOffer(p("no_credits", false, "Пополните баланс Polza: на нём нет средств."), { status: st({ state: "down", retry_in: 90, retry_state: "congested", advice: "Соберите ещё раз через несколько минут или пополните баланс Polza на 100–500 ₽." }), latest: true, retryIn: 80 }),
  noCreditsDownPlain: m.rebuildOffer(p("no_credits", false, "Пополните баланс Polza."), { status: down, latest: false, retryIn: 80 }),
  authDown: m.rebuildOffer(p("auth", false, "Проверьте ключ доступа к Polza в настройках сервера."), { status: down, latest: true, retryIn: 80 }),
  authDownBlockedByKey: m.rebuildOffer(p("auth", false, UNAVAILABLE), { status: blockedByKey, latest: true, retryIn: 1700 }),
  // a 400 is about these inputs: the model answering something else does not bring the button back (another model may)
  error400OkLatest: m.rebuildOffer(p("error", false, SHORTEN), { status: ok, latest: true, retryIn: 0 }),
  error400FallbackLatest: m.rebuildOffer(p("error", false, SHORTEN), { status: st({ state: "fallback", advice: "Сейчас отвечает запасная модель — соберите ещё раз." }), latest: true, retryIn: 0 }),
  // ... nor does the end of a pause: every model paused, the paused links retryable, for the newest deck and an older one
  error400Down: m.rebuildOffer(p("error", false, SHORTEN), { status: down, latest: true, retryIn: 80 }),
  error400DownOlder: m.rebuildOffer(p("error", false, SHORTEN), { status: down, latest: false, retryIn: 80 }),
  error400DownOldServer: m.rebuildOffer({ ...p("error", undefined, SHORTEN), retryable: undefined }, { status: st({ state: "down", retry_in: 90, retry_state: "congested", retryable: undefined, advice: "Соберите ещё раз через несколько минут." }), latest: true, retryIn: 80 }),
  error400DownBlockedByKey: m.rebuildOffer(p("error", false, SHORTEN), { status: blockedByKey, latest: true, retryIn: 1700 }),
  // an older server (no «retryable» in the live status): no button for a deck whose reason needs a fix, so no «соберите»
  authDownOldServer: m.rebuildOffer({ ...p("auth", undefined, UNAVAILABLE), retryable: undefined }, { status: st({ state: "down", retry_in: 90, retry_state: "congested", retryable: undefined, advice: "Соберите ещё раз через несколько минут." }), latest: true, retryIn: 80 }),
};
const error400DownNotice = m.deckNotice(
  { id: "g", template_id: "t", strategies: ["structured"], use_models: true, slides: 12, planner: p("error", false, SHORTEN), variants: [] },
  { strategy: "structured", outline: { planned_by: "rules" }, slides: [], files: {} },
  12,
  { status: down, latest: true, retryIn: 80 },
);
const g = { id: "g", template_id: "t", strategies: ["structured"], use_models: true, slides: 12, planner: p("quota", true, AFTER_MIDNIGHT), variants: [] };
const v = { strategy: "structured", outline: { planned_by: "rules" }, slides: [], files: {} };
const quotaDown = st({ state: "down", retry_in: toMidnight - 0.6, retry_state: "quota", advice: AFTER_MIDNIGHT });
const realNow = Date.now;
Date.now = () => now;
const notice = m.deckNotice(g, v, 11, { status: quotaDown, latest: true, retryIn: toMidnight - 0.6 });
Date.now = realNow;
// gate 4 G4-21: the writer failed (no money on the Polza balance): a topic's skeleton, never a success
const owner = "На балансе Polza нет средств или исчерпан лимит расходов ключа: пополните баланс или поднимите лимит ключа в консоли Polza.";
const skelG = { id: "g", template_id: "t", strategies: ["structured"], use_models: true, slides: 6, writer: { mode: "topic", status: "failed", text: "" }, planner: { ...p("no_credits", false, UNAVAILABLE), planned_by: "skeleton", owner }, variants: [] };
const skelV = { strategy: "structured", outline: { planned_by: "skeleton" }, slides: [], files: {} };
const skeletonNotice = m.deckNotice(skelG, skelV, 6, { status: st({ state: "down", retryable: false, advice: UNAVAILABLE, owner }), latest: true, retryIn: 0 });
const skeletonDeck = [m.skeletonDeck(skelG, skelV), m.skeletonDeck({ ...skelG, writer: { status: "written", text: "x" } }, skelV), m.skeletonDeck(skelG, v)];
console.log(JSON.stringify({ offers, notice, error400DownNotice, skeletonNotice, skeletonDeck }));
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


def test_web_rebuild_offer_and_advice_agree(tmp_path):
    o = _run_web(tmp_path)["offers"]
    assert o["congestedDown"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут."}
    # an older server's money or key clause is dropped; nothing plain left: the model is unavailable
    assert o["congestedOlder"] == {"retry": True, "wait": 0, "help": "Соберите ещё раз через несколько минут."}
    assert o["authUnknownOlder"] == {"retry": False, "wait": 0, "help": "Модель недоступна"}
    # a key, a balance or a model id need the server's owner: the person reads only that the model is unavailable
    assert o["authUnknown"] == {"retry": False, "wait": 0, "help": "Модель недоступна."}
    assert o["authOkLatest"] == {"retry": True, "wait": 0, "help": "Модель снова отвечает — соберите ещё раз."}
    assert o["authOkOlder"] == {"retry": False, "wait": 0, "help": "Модель недоступна."}
    assert o["congestedBlockedByKey"] == {"retry": False, "wait": 0, "help": "Модель недоступна."}
    assert o["error400"]["retry"] is False and "сократите текст" in o["error400"]["help"]
    assert o["quotaOlderOk"] == {"retry": True, "wait": 0, "help": "Модель снова отвечает — соберите ещё раз."}
    # Polza's daily cap: the button waits for midnight by Moscow time, the advice beside it says so
    assert o["quotaDown"]["retry"] is True and o["quotaDown"]["wait"] > 0 and o["quotaDown"]["help"] == AFTER_MIDNIGHT
    assert o["noStatus"]["retry"] is True and o["noStatusAuth"]["retry"] is False
    # an older server's word about money is dropped: the live advice alone says when to build again
    assert o["unknownKeepsSteady"]["help"] == "Соберите ещё раз — модель попробует снова."
    assert o["downHasItsOwn"]["help"] == "Соберите ещё раз через несколько минут."
    # every model pauses, the paused links can be retried, the deck's reason needs a fix: the button waits for the
    # live pause; the fix itself (money, a key) never reaches the screen, the clause «или пополните …» neither
    assert o["noCreditsDown"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут."}
    assert o["noCreditsDownPlain"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут."}
    assert o["authDown"] == {"retry": True, "wait": 80, "help": "Соберите ещё раз через несколько минут."}
    assert o["authDownBlockedByKey"] == {"retry": False, "wait": 0, "help": "Модель недоступна."}
    assert o["error400OkLatest"] == {"retry": False, "wait": 0, "help": "Та же сборка получит ту же ошибку: сократите текст."}
    assert o["error400FallbackLatest"] == {"retry": True, "wait": 0, "help": "Сейчас отвечает запасная модель — соберите ещё раз."}
    # every model pauses and the pause will end, but a 400 comes back after it: no button, only the deck's own fix
    for name in ("error400Down", "error400DownOlder", "error400DownOldServer"):
        assert o[name] == {"retry": False, "wait": 0, "help": "Та же сборка получит ту же ошибку: сократите текст."}, name
    # the paused links need a fix themselves (said plainly); the deck's own fix follows, still no button
    assert o["error400DownBlockedByKey"] == {"retry": False, "wait": 0, "help": "Модель недоступна. Та же сборка получит ту же ошибку: сократите текст."}
    assert o["authDownOldServer"] == {"retry": False, "wait": 0, "help": "Модель недоступна."}
    # the advice never promises a rebuild the notice does not offer, a shown button always has advice beside it, and
    # no advice mentions the service, money, keys or config files
    for name, offer in o.items():
        assert offer["help"], name
        _plain(offer["help"])
        if not offer["retry"]:
            assert "оберите ещё раз" not in offer["help"], name


def test_web_notice_of_a_400_while_every_model_pauses_offers_no_rebuild(tmp_path):
    n = _run_web(tmp_path)["error400DownNotice"]
    assert n["retry"] is False and n["retryWait"] == 0
    assert "сократите текст" in n["help"] and "оберите" not in n["help"]


def test_web_notice_button_waits_without_a_timer(tmp_path):
    n = _run_web(tmp_path)["notice"]
    # the button waits (disabled) without a timer in its words; the advice beside it says when: after midnight in Moscow
    assert n["retry"] is True and n["retryWait"] > 0 and n["retryLabel"] == "Собрать ещё раз"
    assert n["title"] == "Модель не ответила: дневной лимит запросов исчерпан"
    assert n["help"] == "соберите ещё раз после полуночи по московскому времени."


def test_web_a_failed_writers_skeleton_says_so_and_shows_no_score(tmp_path):
    r = _run_web(tmp_path)
    n = r["skeletonNotice"]
    assert n["title"] == "Модель недоступна — текст не написан" and "каркас" in n["basis"].lower()
    # the owner's fix (the Polza balance) is the notice's tooltip; the notice's own words stay plain
    assert n["owner"] == OWNER_MONEY
    _plain(n["title"], n["basis"], n["help"])
    assert r["skeletonDeck"] == [True, False, False]


# ---------------------------------------------------------------------------- the swarm review of the migration


def test_a_refusal_of_moderation_asks_to_rephrase_not_to_shorten():
    refused = f"the request was refused by moderation (403) ({MODERATION})"
    info = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: {refused}; [Qwen3.6-27B] {BACKUP}: {refused}")
    assert info["reason_code"] == "error" and info["advice"] == "Та же сборка получит тот же отказ: перефразируйте текст."
    assert info["retryable"] is False and info["owner"] is None
    plain = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: Error code: 400 - bad request; [Qwen3.6-27B] {BACKUP}: Error code: 400 - bad request")
    assert plain["advice"] == "Та же сборка получит ту же ошибку: сократите текст."


def test_the_advice_follows_the_failure_that_clears_first():
    """Polza's caps are per model: the main model's day is spent, the backup only had to wait — building again helps
    in a few minutes, not after midnight; the title keeps the most telling reason."""
    info = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: daily request quota of the account is spent ({DAY}); [Qwen3.6-27B] {BACKUP}: congested upstream ({HOSTS_429})")
    assert info["reason_code"] == "quota"
    assert info["advice"] == "Соберите ещё раз через несколько минут." and info["retryable"] is True
    both = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: daily request quota ({DAY}); [Qwen3.6-27B] {BACKUP}: daily request quota ({DAY})")
    assert both["advice"] == "Соберите ещё раз после полуночи по московскому времени."
    money = _rules(f"all model links failed: [Qwen3.8-27B] {MAIN}: no credits (402) on the balance ({NO_MONEY}); [Qwen3.6-27B] {BACKUP}: no credits (402) on the balance ({NO_MONEY})")
    assert money["advice"] == "Модель недоступна." and money["retryable"] is False


@pytest.mark.parametrize("label", ["Qwen3.8-27B (OpenRouter)", "Qwen3.8-27B (Groq)", "Gemma 4 31B (бесплатно)", "Qwen3 32B (Cloud.ru)"])
def test_an_older_decks_failure_asks_no_fix_of_todays_owner(label):
    """A deck built before Polza names links of an older config: its reason still reads, but the owner is never told
    to top up Polza or check its key for it."""
    info = _rules(f"all model links failed: [{label}] qwen/qwen3.8-27b: no credits (402) on the account (Insufficient credits)")
    assert info["reason_code"] == "no_credits" and info["owner"] is None


@pytest.mark.parametrize(
    "warning, code",
    [
        # OpenRouter's single-model failures, no link label (the same model id as Polza's today)
        ("model plan failed: qwen/qwen3.8-27b: no credits (402) on the account (Error code: 402 - Insufficient credits. Add more using https://openrouter.ai/settings/credits)", "no_credits"),
        ("model plan failed: qwen/qwen3.8-27b: access refused (401/403): HTTP 401 (openrouter.ai: User not found)", "auth"),
        ("model plan failed: qwen/qwen3.8-27b:free: daily request quota (free-models-per-day limit reached)", "quota"),
        ("model plan failed: qwen/qwen3.8-27b is temporarily rate-limited upstream. Please retry shortly", "congested"),
        ("model plan failed: Qwen/Qwen3-32B: access refused (401/403): HTTP 403 (foundation-models.api.cloud.ru: Project not found)", "auth"),
    ],
)
def test_an_older_decks_unlabelled_failure_reads_its_reason_and_asks_no_fix_of_todays_owner(warning, code):
    info = _rules(warning)
    assert info["reason_code"] == code and info["owner"] is None
