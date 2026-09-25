"""The model's state in words: which model planned a deck, why the built-in planner took over, and whether the
model is reachable right now (GET /api/models/status). No network probing: only what the providers recorded.

The link states come from `verstka.providers.status.snapshot()` (the fallback chain's own records):
ok · unknown · congested · rate · quota · no_credits · auth · missing · error · off.
A reason is read from the contract wording of the chain's errors first (status.PHRASES), then from bare status codes;
its words are about the link that failed (a free or the paid OpenRouter model, Groq, Cloud.ru): the chain names each
failed link by its label («[Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: …»), looked up in the active chain. The advice depends
on the ACTIVE chain: a top-up is offered as «платный Qwen3.8-27B отвечает стабильно» only when the active config has
a paid OpenRouter link; with a free-only config the advice says what to switch on.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
import re
import time
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

# the contract shared with verstka/providers/status.py and the web UI
LINK_STATES = ("ok", "unknown", "congested", "rate", "quota", "no_credits", "auth", "missing", "error", "off")
_LEGACY_CODES = {"no_key": "auth", "gone": "missing"}  # reason codes of the first version of this module
PAID_CONFIG = "configs/models.yaml"  # the config with the paid Qwen3.8-27B link

# ---------------------------------------------------------------------------- model names


def model_label(model: Optional[str]) -> Optional[str]:
    """«qwen/qwen3.8-27b:free» → «Qwen3.8-27B», «google/gemma-4-31b-it:free» → «Gemma 4 31B»."""
    if not model:
        return None
    name = model.split("/")[-1].split(":")[0]
    name = re.sub(r"-(instruct|it|chat|fp8|fp4|awq|gguf|\d{4})$", "", name, flags=re.I)
    name = re.sub(r"-(instruct|it|chat)(?=-|$)", "", name, flags=re.I)
    low = name.lower()
    if low.startswith("gemma"):
        parts = [p for p in re.split(r"[-_]", name) if p]
        head = "Gemma" + (f" {parts[1]}" if len(parts) > 1 and parts[1].isdigit() else "")
        rest = parts[2:] if len(parts) > 1 and parts[1].isdigit() else parts[1:]
        size = "-".join(p.upper() for p in rest)
        return f"{head} {size}".strip()
    if low.startswith("qwen"):
        name = "Qwen" + re.sub(r"-vl(?=-|$)", "-VL", name[4:], flags=re.I)
        return re.sub(r"(?<=[-_])(a?\d+(?:\.\d+)?)b\b", lambda m: m.group(1).upper() + "B", name, flags=re.I)
    return name


def short_label(label: Optional[str]) -> Optional[str]:
    """«Qwen3.8-27B (бесплатно)» → «Qwen3.8-27B»: the indicator line stays short."""
    if not label:
        return label
    return re.sub(r"\s*\([^()]*\)\s*$", "", label).strip() or label


def is_free(model: Optional[str]) -> bool:
    return bool(model) and model.endswith(":free")


def hostname(base_url: Optional[str]) -> Optional[str]:
    """The host of a base_url, never its credentials or path («https://user:token@proxy/v1» → «proxy»)."""
    if not base_url:
        return None
    try:
        parts = urlsplit(base_url if "//" in base_url else "//" + base_url)
        return parts.hostname or None
    except ValueError:
        return None


def _is_openrouter(host: Optional[str]) -> bool:
    return service(host) == "OpenRouter"


_SERVICES = (("openrouter.ai", "OpenRouter"), ("groq.com", "Groq"), ("cloud.ru", "Cloud.ru"))


def service(host: Optional[str]) -> Optional[str]:
    """«openrouter.ai» → «OpenRouter», «api.groq.com» → «Groq»; None for another host (VK, a local server)."""
    h = (host or "").lower()
    return next((name for domain, name in _SERVICES if h == domain or h.endswith("." + domain)), None)


@dataclasses.dataclass(frozen=True)
class FailedLink:
    """The link a reason is about: the words depend on it (a free OpenRouter model, a paid one, Groq, Cloud.ru)."""

    model: Optional[str] = None
    service: Optional[str] = None  # OpenRouter | Groq | Cloud.ru | None (another or unknown host)
    free: bool = False

    @property
    def openrouter_free(self) -> bool:
        return self.service == "OpenRouter" and self.free


# ---------------------------------------------------------------------------- reasons from warnings

_CHAIN_FAILED = "all model links failed:"
# the wording every error of a link state carries (verstka.providers.status.PHRASES — the contract): checked first,
# the one that comes first in the text wins (a hold's message quotes the error that opened it after its own wording)
CONTRACT_PHRASES: dict[str, str] = {
    "no_credits": "no credits (402)",
    "auth": "access refused (401/403)",
    "missing": "model not available (404)",
    "rate": "per-minute request cap",
    "quota": "daily request quota",
    "congested": "congested upstream",
    "off": "not configured (no API key)",
}
# the seconds of a hold are never a status code: «skipped for 402 s more», «retry in 404 s», «(20/min)»
_HOLD_NUMBERS = re.compile(r"skipped for \d+(?:\.\d+)? s(?: more)?|retry in \d+(?:\.\d+)? s|next slot in \d+(?:\.\d+)? s|\(\d+/min\)", re.I)
# one link's failure (a warning or one «;»-part of a chain's «all model links failed: …») without the contract
# wording (older messages, raw provider errors), checked in this order after the hold times are cut out
_RULES: list[tuple[str, re.Pattern]] = [
    ("off", re.compile(r"not configured \(no api key\)|no api key configured", re.I)),
    ("quota", re.compile(r"daily request quota|free-models-per-day|per-day|per day|daily quota|requests per day", re.I)),
    ("rate", re.compile(r"per-minute|per minute|free-models-per-min|requests per minute", re.I)),
    ("no_credits", re.compile(r"no credits|\b402\b|insufficient credits|more credits|payment required|insufficient_quota|credit balance|key limit exceeded|spending limit", re.I)),
    ("auth", re.compile(r"access refused|\b401\b|\b403\b|check the key|invalid api key|no auth credentials|unauthori[sz]ed|forbidden", re.I)),
    ("missing", re.compile(r"model not available|no such model|model not found|not a valid model|does not exist|no endpoints? (found|serves)|\b404\b", re.I)),
    # congestion is a real upstream 429 or a 5xx: «Provider returned error» alone wraps any upstream error (a 400 too)
    ("congested", re.compile(r"congested|temporarily rate-limited|rate-limited upstream|overloaded|service unavailable|bad gateway|server error|error code:?\s*5\d\d\b|\b5\d\d\s+(internal|bad gateway|service|gateway)", re.I)),
    ("timeout", re.compile(r"time budget|timed out|timeout|deadline|\b408\b", re.I)),
    ("unreachable", re.compile(r"connection error|connecterror|connection refused|name or service|nodename|network is unreachable|ssl|could not connect", re.I)),
    ("error", re.compile(r"error code:?\s*4(?!29|08)\d\d\b|bad request", re.I)),  # a 400: retrying does not help
    ("rejected", re.compile(r"answer rejected|plan rejected|invalid json|no valid completion|not valid|does not match schema", re.I)),
]
# the most telling reason first when several links / steps failed differently
_PRIORITY = ["auth", "no_credits", "quota", "missing", "congested", "rate", "timeout", "unreachable", "rejected", "error", "off"]
# warnings that come from a model step (the rest are layout notes: «заголовок набран 36 пт»)
_MODEL_STEP = re.compile(r"^(outline_planner|data_extractor|fact_checker|repair pass|own model plan failed|no LLM provider)|provider|model", re.I)
# the planner's own step: its failure (or a rejected answer) is why a deck was planned by the rules
_PLANNER_STEP = re.compile(r"^(outline_planner (failed|answer rejected)|no LLM provider)", re.I)
# these steps run only on a plan the model wrote (a failed repair pass keeps it): an older deck with one of them and
# without a planner failure was planned by the model
_MODEL_PLANNED = re.compile(r"^(fact_checker|repair pass)", re.I)
_SKIPPED_FOR = re.compile(r"skipped for (\d+(?:\.\d+)?) s", re.I)
# the label the chain puts before each failed link's message: «[Qwen3.8-27B (Groq)] qwen/qwen3.8-27b: …» («again: »
# before it on the second pass)
_LINK_LABEL = re.compile(r"^\s*(?:again:\s*)?\[([^\[\]]{1,80})\]\s*")
# a reason the same deck built again can get past: congestion, a per-minute cap, a daily quota once it resets, the
# time budget, the connection, an answer that did not pass the check. A key, a missing model, an empty account or a
# 400 need a fix first — the notice says what to fix instead of offering a rebuild
RETRYABLE_REASONS = frozenset({"congested", "rate", "quota", "timeout", "unreachable", "rejected"})


def _segment_code(text: str) -> str:
    text = _LINK_LABEL.sub("", text, count=1)  # the link's label is a name, never a reason («Qwen 402B» would be)
    low = text.lower()
    hits = [(low.find(phrase.lower()), code) for code, phrase in CONTRACT_PHRASES.items() if phrase.lower() in low]
    if hits:
        return min(hits)[1]
    if "request quota of the account" in low and not re.search(r"per-minute|per minute|per-day|per day|daily", low):
        # an older wording of both caps: a pause under 5 minutes is the per-minute cap, a longer one the daily quota
        m = _SKIPPED_FOR.search(text)
        return "rate" if m and float(m.group(1)) < 300 else "quota"
    bare = _HOLD_NUMBERS.sub(" ", text)
    low = bare.lower()
    if re.search(r"\b429\b", bare) and re.search(r"upstream|provider returned error|temporarily", low) and not re.search(r"per-minute|per minute|per-day|per day|free-models-per", low):
        return "congested"  # a 429 passed on from the host behind OpenRouter
    for code, rx in _RULES:
        if rx.search(bare):
            return code
    if re.search(r"\b429\b|rate limit|rate-limit", low):
        return "rate"
    return "error"


def _best(codes: Iterable[Optional[str]]) -> Optional[str]:
    found = [c for c in codes if c]
    if not found:
        return None
    failures = [c for c in found if c != "off"] or found  # a link waiting for its key is skipped, never a failure
    return min(failures, key=lambda c: _PRIORITY.index(c) if c in _PRIORITY else len(_PRIORITY))


def _classified(text: str) -> list[tuple[str, str]]:
    """(reason code, the part of the text it comes from) per failed link of one warning; [] when not about the model."""
    if not isinstance(text, str) or not text or not _MODEL_STEP.search(text):
        return []
    low = text.lower()
    if low.startswith("no llm provider"):
        return [("off", text)]
    if low.startswith("own model plan failed") or low.startswith("fact_checker found"):
        return []  # the variant took another variant's model plan / the check worked: not a failure of the model
    i = low.find(_CHAIN_FAILED)
    if i >= 0:
        parts = [p.strip() for p in text[i + len(_CHAIN_FAILED):].split(";") if p.strip()]
        return [(_segment_code(p), p) for p in parts] or [("error", text)]
    return [(_segment_code(text), text)]


def _pick(found: list[tuple[str, str]]) -> tuple[Optional[str], Optional[str]]:
    code = _best(c for c, _ in found)
    return (code, next(s for c, s in found if c == code)) if code else (None, None)


def classify(text: str) -> Optional[str]:
    """Reason code of one warning / provider error, None when it is not about the model."""
    return _pick(_classified(text))[0]


def _reason(warnings: Iterable[Any], *, planner_only: bool = False) -> tuple[Optional[str], Optional[str]]:
    """(code, the failed link's text): the planner's own failure first, then (unless `planner_only`) the other steps'."""
    ws = [w for w in warnings if isinstance(w, str)]
    own = [found for w in ws if _PLANNER_STEP.match(w) for found in _classified(w)]
    if own or planner_only:
        return _pick(own)
    return _pick([found for w in ws for found in _classified(w)])


def reason_code(warnings: Iterable[str]) -> Optional[str]:
    """The most telling reason among a variant's warnings: the planner's own failure first, then the other steps'."""
    return _reason(warnings)[0]


# a model id in front of its error: «qwen/qwen3.8-27b:free: congested upstream», «qwen3.5:9b: …»
_MODEL_ID = re.compile(r"(?:^|(?<=[\s;:,(]))([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)?(?::[A-Za-z0-9_.\-]+)?):\s")
_GROQ_TEXT = re.compile(r"groq|\((?:tpd|rpd|tpm|rpm)\)|service tier|on_demand", re.I)
# the service a label's tag names: «Qwen3.8-27B (Groq)», «Qwen3 32B (Cloud.ru)», «Gemma 4 31B (бесплатно)»
_LABEL_TAGS = (("groq", "Groq"), ("cloud.ru", "Cloud.ru"), ("openrouter", "OpenRouter"), ("бесплатно", "OpenRouter"))
_OPENROUTER_TEXT = re.compile(r"openrouter|provider returned error|free-models-per", re.I)


def _model_in(text: str) -> Optional[str]:
    for m in _MODEL_ID.finditer(text):
        token = m.group(1)
        if "/" in token or re.search(r"\d", token):  # «used:», «code:», «again:» are words, a model id has a digit or a /
            return token
    return None


# ---------------------------------------------------------------------------- the active chain


@dataclasses.dataclass
class ChainContext:
    """What the active config offers — the advice depends on it."""

    openrouter: bool = True  # the chain goes through OpenRouter
    free: bool = True  # the first link the chain asks is a free model (when the failed link is not known)
    paid_label: Optional[str] = None  # a paid OpenRouter link of the active config («Qwen3.8-27B»), None if there is none
    groq_label: Optional[str] = None  # a Groq link waiting for its key (state off)
    primary_label: Optional[str] = None
    config: Optional[str] = None
    # model, label, host, free and state of every link: which of them a failure is about
    links: list = dataclasses.field(default_factory=list)

    @property
    def primary(self) -> FailedLink:
        """The first link the chain asks — what a reason is about when its text does not name the link."""
        active = [link for link in self.links if link.get("state") != "off"] or self.links
        if active:
            return link_of(active[0])
        return FailedLink(service="OpenRouter" if self.openrouter else None, free=self.free)


def link_of(link: dict) -> FailedLink:
    return FailedLink(model=link.get("model"), service=service(link.get("host")), free=bool(link.get("free")))


def chain_context(links: list[dict], config: Optional[str] = None) -> ChainContext:
    active = [link for link in links if link.get("state") != "off"]
    if not links:
        return ChainContext(config=config)
    pool = active or links
    paid = next((link for link in active if not link.get("free") and _is_openrouter(link.get("host"))), None)
    groq = next((link for link in links if link.get("state") == "off" and service(link.get("host")) == "Groq"), None)
    return ChainContext(
        openrouter=any(_is_openrouter(link.get("host")) for link in pool),
        free=bool(pool[0].get("free")),
        paid_label=short_label(paid.get("label")) if paid else None,
        groq_label=short_label(groq.get("label")) if groq else None,
        primary_label=short_label(pool[0].get("label")),
        config=config,
        links=[{k: link.get(k) for k in ("model", "label", "host", "free", "state")} for link in links],
    )


def _labelled(text: str, model: Optional[str], ctx: ChainContext) -> Optional[FailedLink]:
    """The link the chain named by its label: looked up in the active chain, else (a label of an older config) the
    service its tag names."""
    m = _LINK_LABEL.match(text)
    if not m:
        return None
    label = m.group(1).strip()
    hit = next((link for link in ctx.links if link.get("label") == label), None)
    if hit is not None:
        return link_of(hit)
    tag = re.search(r"\(([^()]*)\)\s*$", label)
    where = next((name for word, name in _LABEL_TAGS if tag and word in tag.group(1).lower()), None)
    if where is None:
        return None
    free = is_free(model) or (tag is not None and tag.group(1).strip().lower() == "бесплатно")
    return FailedLink(model=model, service=where, free=free)


def failed_link(text: Optional[str], ctx: Optional[ChainContext] = None) -> FailedLink:
    """The link a failure's text is about: the link the chain named by its label; for older texts without one, its
    model id looked up in the active chain (the same id may run on OpenRouter and on Groq: Groq's own wording tells
    them apart), else what the text itself says."""
    ctx = ctx or ChainContext()
    if not text:
        return ctx.primary
    model = _model_in(text)
    named = _labelled(text, model, ctx)
    if named is not None:
        return named
    groq = bool(_GROQ_TEXT.search(text))
    same = [link for link in ctx.links if model and link.get("model") == model]
    same = [link for link in same if link.get("state") != "off"] or same  # a link without a key never failed
    if len(same) > 1:
        same = [link for link in same if (service(link.get("host")) == "Groq") == groq] or same
    if same:
        return link_of(same[0])
    if groq:
        where: Optional[str] = "Groq"
    elif "cloud.ru" in text.lower():
        where = "Cloud.ru"
    elif is_free(model) or _OPENROUTER_TEXT.search(text):
        where = "OpenRouter"
    elif model is None:
        return ctx.primary  # «time budget of the generation is spent»: about the chain, not one link
    else:
        where = ctx.primary.service  # a model of an older config: most likely on the same service
    return FailedLink(model=model, service=where, free=is_free(model) if model else ctx.primary.free)


def _quota_reset_words(now: Optional[float] = None) -> str:
    """OpenRouter's free quota resets at 00:00 UTC = 03:00 by Moscow time."""
    utc_hour = time.gmtime(time.time() if now is None else now).tm_hour
    return "сегодня после 03:00" if utc_hour >= 21 else "завтра после 03:00"


def reason_text(code: Optional[str], ctx: Optional[ChainContext] = None, who: Optional[FailedLink] = None) -> Optional[str]:
    """One plain Russian clause: what kept the model from planning — about the link that failed (`who`)."""
    ctx = ctx or ChainContext()
    who = who or ctx.primary
    where = who.service
    if code is None:
        return None
    if code == "congested":
        if who.openrouter_free:
            return "бесплатные модели OpenRouter сейчас перегружены"
        if where == "OpenRouter":
            return "платная модель на OpenRouter сейчас перегружена"
        return f"сервер {where} сейчас перегружен" if where else "сервер модели сейчас перегружен"
    if code == "rate":
        if who.openrouter_free:
            return "превышен лимит бесплатных запросов OpenRouter в минуту"
        return f"превышен лимит запросов {where} в минуту" if where else "превышен лимит запросов к модели в минуту"
    if code == "quota":
        if who.openrouter_free:
            return "исчерпан дневной лимит бесплатных запросов OpenRouter"
        return f"исчерпан дневной лимит запросов {where}" if where else "исчерпан дневной лимит запросов к модели"
    if code == "no_credits":
        if where == "OpenRouter":
            return "на счёте OpenRouter нет средств для платной модели"
        return f"на счёте {where} нет средств" if where else "на счёте сервиса модели нет средств"
    texts = {
        "auth": f"ключ доступа к {where} не подходит" if where else "ключ доступа к модели не подходит",
        "missing": f"эта модель сейчас недоступна на {where}" if where else "эта модель сейчас недоступна на сервере",
        "timeout": "время на модель вышло — она отвечала слишком долго",
        "unreachable": f"не удалось связаться с сервером {where}" if where else "не удалось связаться с сервером модели",
        "rejected": "модель ответила, но её план не прошёл проверку",
        "off": "модель не подключена",
    }
    return texts.get(code, "модель вернула ошибку")


def _steady_way(ctx: ChainContext) -> str:
    """What makes the model answer steadily: the paid link of the active config, or switching it on."""
    if ctx.paid_label:
        return f"пополните OpenRouter на $5–10 — платный {ctx.paid_label} отвечает стабильно, ≈ 1–5 ₽ за презентацию"
    return f"пополните OpenRouter на $5–10 и включите платную модель: {PAID_CONFIG}"


def steady_tip(ctx: ChainContext) -> str:
    """The paid model, in a sentence of its own (the notice adds it to the live advice)."""
    return f"Чтобы не зависеть от очереди бесплатных, {_steady_way(ctx)}."


def advice(code: Optional[str], ctx: Optional[ChainContext] = None, who: Optional[FailedLink] = None) -> Optional[str]:
    """What helps, in one sentence (None when nothing needs doing). Used in the notice above a deck: short, no extras.
    A top-up is offered only when a free OpenRouter model failed (never for the paid model that just failed)."""
    ctx = ctx or ChainContext()
    who = who or ctx.primary
    where = who.service
    steady = who.openrouter_free and ctx.openrouter
    if code in ("congested", "timeout"):
        return f"Соберите ещё раз через несколько минут или {_steady_way(ctx)}." if steady else "Соберите ещё раз через несколько минут."
    if code == "rate":
        return "Соберите ещё раз через минуту."
    if code == "quota":
        if who.openrouter_free:
            first = f"Бесплатный лимит обновится {_quota_reset_words()}."
            return f"{first} Чтобы не ждать, {_steady_way(ctx)}." if ctx.openrouter else first
        return f"Соберите ещё раз, когда обновится дневной лимит {where or 'сервиса модели'}."
    if code == "no_credits":
        if where == "OpenRouter":
            return "Пополните счёт OpenRouter на $5–10 — хватит на сотни презентаций (≈ 1–5 ₽ за каждую)."
        return f"Пополните счёт {where or 'сервиса модели'}."
    if code == "auth":
        return f"Проверьте ключ доступа к {where or 'модели'} в настройках сервера."
    if code == "missing":
        return f"Выберите другую модель в файле настроек {ctx.config or PAID_CONFIG}."
    if code == "unreachable":
        return "Проверьте подключение к интернету и соберите ещё раз."
    if code == "rejected":
        return "Соберите ещё раз — модель отвечает по-разному."
    if code == "error":
        # a 400 (a text too long for the model, a parameter it does not take): the same inputs get the same answer
        return f"Та же сборка получит ту же ошибку: сократите текст или выберите другую модель в файле настроек {ctx.config or PAID_CONFIG}."
    return None


def groq_tip(ctx: ChainContext) -> Optional[str]:
    """The optional free Groq key — only in the detailed hint under the indicator, never in every notice."""
    if not ctx.groq_label:
        return None
    same = ctx.primary_label and short_label(ctx.groq_label) == ctx.primary_label
    return f"Ещё поможет бесплатный ключ Groq для {'той же ' if same else ''}{ctx.groq_label} — строка GROQ_API_KEY в .env."


# ---------------------------------------------------------------------------- who planned a variant


def planner_info(outline: Optional[dict], run_manifest: Optional[dict], *, use_models: Optional[bool] = None, ctx: Optional[ChainContext] = None, supplied: bool = False) -> dict:
    """Who wrote the plan of a variant and, when the built-in planner did, why — for generation.json and the UI.

    by_model: True (a model, possibly another variant's plan), False (the rules / a supplied outline), None (not
    recorded: an older deck without planned_by and without a planner failure — no notice is shown for it).
    retryable: the same deck built again can get past the reason (see RETRYABLE_REASONS). steady: the sentence about
    the paid model when a free OpenRouter model was congested or out of requests — the notice adds it to the live
    advice (which says when to build again), so it is not lost when that advice replaces the deck's own."""
    rm = run_manifest or {}
    recorded = rm.get("planner") if isinstance(rm.get("planner"), dict) else {}
    configured = ((rm.get("providers") or {}).get("llm") or {})
    tried = configured.get("model") if configured.get("backend") not in (None, "none") else None
    base = {"model": None, "model_label": None, "tried_model": tried, "tried_label": model_label(tried), "reason_code": None, "reason": None, "advice": None, "retryable": False, "steady": None}
    if supplied or recorded.get("supplied"):
        return {**base, "planned_by": "supplied", "by_model": False}  # the plan came with the request: no model was asked
    planned_by = (outline or {}).get("planned_by") or recorded.get("planned_by")
    if planned_by == "model" or (planned_by or "").startswith("shared:"):
        model = recorded.get("model") or tried
        return {**base, "planned_by": planned_by, "by_model": True, "model": model, "model_label": model_label(model)}
    warnings = rm.get("warnings") or []
    failed_text: Optional[str] = None
    if use_models is False or tried is None:
        code: Optional[str] = "off"
    elif recorded.get("reason_code"):
        code = _LEGACY_CODES.get(recorded["reason_code"], recorded["reason_code"])
    elif planned_by is None:
        # an older deck that does not say who planned it: only the planner's own failure means the rules did — a data
        # step or the fact check failing says nothing about the plan, and a fact check runs on a model's plan only
        code, failed_text = _reason(warnings, planner_only=True)
        if code is None:
            if any(isinstance(w, str) and _MODEL_PLANNED.match(w) for w in warnings):
                return {**base, "planned_by": "model", "by_model": True, "model": tried, "model_label": model_label(tried)}
            return {**base, "planned_by": None, "by_model": None}
    else:
        code, failed_text = _reason(warnings)
    ctx = ctx or ChainContext(free=is_free(tried))
    who = failed_link(failed_text, ctx) if failed_text else ctx.primary
    return {
        **base,
        "planned_by": planned_by or "rules",
        "by_model": False,
        "reason_code": code,
        "reason": reason_text(code, ctx, who),
        "advice": advice(code, ctx, who) if code not in (None, "off") else None,
        "retryable": code in RETRYABLE_REASONS,
        "steady": steady_tip(ctx) if code in ("congested", "timeout", "rate", "quota") and who.openrouter_free and ctx.openrouter else None,
    }


def generation_planner(variants: list[dict], *, use_models: Optional[bool], supplied: bool = False) -> dict:
    """The generation as a whole: did a model plan any variant, and if none did — the reason (for the notice)."""
    infos = [v.get("planner") or {} for v in variants]
    empty = {"model": None, "model_label": None, "tried_model": None, "tried_label": None, "reason_code": None, "reason": None, "advice": None, "retryable": False, "steady": None}
    if supplied or (infos and all(i.get("planned_by") == "supplied" for i in infos)):
        return {**empty, "planned_by": "supplied", "by_model": False}
    by_model = [i for i in infos if i.get("by_model")]
    if by_model:
        first = by_model[0]
        return {**empty, "planned_by": first.get("planned_by"), "by_model": True, "model": first.get("model"), "model_label": first.get("model_label")}
    failed = [i for i in infos if i.get("by_model") is False and i.get("reason_code")]
    if failed:
        code = _best(i["reason_code"] for i in failed)
        pick = next(i for i in failed if i["reason_code"] == code)
        out = {**empty, **{k: pick.get(k) for k in empty}, "planned_by": pick.get("planned_by"), "by_model": False}
        out["retryable"] = bool(pick.get("retryable", code in RETRYABLE_REASONS))
        return out
    if any(i.get("by_model") is False for i in infos):
        return {**empty, "planned_by": "rules", "by_model": False, "reason_code": "off" if use_models is False else None}
    return {**empty, "planned_by": None, "by_model": None}


# ---------------------------------------------------------------------------- models status


def _as_dict(item: Any) -> dict:
    if isinstance(item, dict):
        return dict(item)
    if dataclasses.is_dataclass(item) and not isinstance(item, type):
        return dataclasses.asdict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {k: getattr(item, k) for k in ("model", "label", "host", "state", "available", "last_ok", "last_error", "until", "roles") if hasattr(item, k)}


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{3})[A-Za-z0-9_\-*]{6,}|(Bearer\s+)\S+|(gsk_[A-Za-z0-9]{0,3})[A-Za-z0-9]{6,}")


def _redact(text: Any) -> Optional[str]:
    if not text:
        return None
    return _SECRET_RE.sub(lambda m: (m.group(1) or m.group(2) or m.group(3) or "") + "…", str(text))[:300]


def _seconds_left(until: Any) -> Optional[float]:
    """`until` as seconds from now: a remaining time, an epoch time or a time.monotonic() value."""
    try:
        u = float(until)
    except (TypeError, ValueError):
        return None
    if u > 1e9:
        u -= time.time()
    elif u > 2 * 86400:
        u -= time.monotonic()
    return u if u > 0 else None


def _norm_link(raw: dict, hosts: Optional[dict] = None) -> dict:
    """A link of the chain as the API shows it: a fixed set of keys (never an account id or a key)."""
    model = raw.get("model")
    state = _LEGACY_CODES.get(raw.get("state"), raw.get("state"))
    state = state if state in LINK_STATES else "unknown"
    until = _seconds_left(raw.get("until"))
    last_error = _redact(raw.get("last_error"))
    if state == "error" and last_error and (code := _segment_code(last_error)) in ("auth", "missing", "no_credits"):
        state = code  # a status module that records every HTTP error as «error»: the wording tells which
    available = raw.get("available")
    if state == "off":
        available = False
    elif available is None:  # older snapshots: a failed link without a pause time counts as paused
        available = state in ("ok", "unknown") or ("until" in raw and not until)
    roles = raw.get("roles")
    host = raw.get("host") or (hosts or {}).get(model)
    label = raw.get("label") or model_label(model) or "модель"
    return {
        "model": model,
        "label": label,
        "short_label": short_label(label),
        "host": hostname(host),
        "state": state,
        # False while the link's breaker (or its account's quota block) is open: the chain skips it until `until`
        "available": bool(available),
        "last_ok": raw.get("last_ok"),
        "last_error": last_error,
        "last_error_at": raw.get("last_error_at"),
        "until": round(until) if until and state != "off" else None,
        "free": bool(raw["free"]) if isinstance(raw.get("free"), bool) else is_free(model),
        "roles": [str(r) for r in roles] if isinstance(roles, (list, tuple)) else [],
    }


def _snapshot_from_module(registry: Any) -> Optional[list[dict]]:
    """The fallback chain's own view: verstka.providers.status.snapshot(registry, role="llm")."""
    try:
        from verstka.providers import status as status_mod
    except Exception:  # noqa: BLE001 - broken import: say so and show the configured links instead
        log.warning("model status: verstka.providers.status is unavailable", exc_info=True)
        return None
    fn = getattr(status_mod, "snapshot", None)
    if fn is None:
        log.warning("model status: verstka.providers.status has no snapshot()")
        return None
    # the llm chain of this registry in chain order; an older snapshot() without `role` merges the llm and vlm roles,
    # the bare call lists every link of the process. The call is picked from the signature, once: a TypeError raised
    # inside snapshot() is a bug to log, never a sign to try another signature
    args: Optional[tuple[tuple, dict]] = None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None
    if sig is None:
        args = ((registry,), {"role": "llm"})
    else:
        for a, kw in (((registry,), {"role": "llm"}), ((registry,), {}), ((), {})):
            try:
                sig.bind(*a, **kw)
            except TypeError:
                continue
            args = (a, kw)
            break
    if args is None:
        log.warning("model status: snapshot%s takes none of (registry, role=), (registry) or ()", sig)
        return None
    try:
        raw: Any = fn(*args[0], **args[1])
    except Exception:  # noqa: BLE001 - a TypeError too: the signature matched, so it came from inside
        log.warning("model status: snapshot() failed", exc_info=True)
        return None
    if isinstance(raw, dict):
        raw = raw.get("links", [])
    hosts = _member_hosts(registry)
    try:
        return [_norm_link(_as_dict(x), hosts) for x in (raw or [])]
    except Exception:  # noqa: BLE001
        log.warning("model status: unexpected snapshot() rows", exc_info=True)
        return None


def _chain_members(provider: Any) -> list[Any]:
    inner = getattr(provider, "inner", None)  # a registry bound to a deadline or a recorder
    if inner is not None and inner is not provider:
        return _chain_members(inner)
    links = getattr(provider, "links", None)
    if isinstance(links, (list, tuple)) and links:
        out: list[Any] = []
        for p in links:
            out.extend(_chain_members(p))
        return out
    return [provider]


def _llm_members(registry: Any) -> list[Any]:
    try:
        return _chain_members(registry.get("llm"))
    except Exception:  # noqa: BLE001
        return []


def _member_hosts(registry: Any) -> dict:
    return {getattr(p, "model", None): hostname(getattr(p, "base_url", None)) for p in _llm_members(registry)}


def _configured_links(registry: Any) -> list[dict]:
    """Without the providers' records (mock models, or a status module that failed): the configured links, not tried."""
    links = []
    for p in _llm_members(registry):
        model = getattr(p, "model", None)
        if getattr(p, "name", "") == "mock":
            state = "ok"
        elif not getattr(p, "api_key", "x"):
            state = "off"
        else:
            state = "unknown"
        links.append(_norm_link({"model": model, "label": getattr(p, "label", None), "host": hostname(getattr(p, "base_url", None)), "state": state}))
    return links


def collect_links(registry: Any, configured: bool = True) -> tuple[list[dict], str]:
    """The llm chain's links in chain order and where they came from ("status", "config" or "none")."""
    if registry is None or not configured:
        return [], "none"
    snap = _snapshot_from_module(registry)
    if snap:
        return snap, "status"
    return _configured_links(registry), "config"


_STATE_PHRASE = {
    "congested": "{name} перегружена",
    "rate": "{name} — лимит запросов в минуту",
    "quota": "{name} — дневной лимит исчерпан",
    "no_credits": "{name} — нет средств на счёте",
    "auth": "{name} — ключ не подходит",
    "missing": "{name} не найдена",
    "error": "{name} вернула ошибку",
    "unreachable": "{name} не отвечает",
    "timeout": "{name} не отвечает",
}
# a failed link whose pause is over: the next deck tries it again
_RECENT_WORD = {
    "congested": "недавно была перегружена, попробую снова",
    "rate": "недавно был лимит запросов, попробую снова",
    "quota": "лимит обновился, попробую снова",
    "no_credits": "недавно не было средств на счёте, попробую снова",
}


def _usable(link: dict) -> bool:
    """The chain will call this link: it answered, was never called, or its pause after a failure is over."""
    if link["state"] == "off":
        return False
    return link["state"] in ("ok", "unknown") or bool(link.get("available"))


def _label(link: dict) -> str:
    return link.get("label") or model_label(link.get("model")) or "модель"


def _short_name(link: dict) -> str:
    return link.get("short_label") or short_label(_label(link)) or _label(link)


def _backup_words(backup: dict, primary: dict) -> tuple[str, str, str]:
    """How the indicator names the backup: (after «отвечает», after «попробую», the name alone). The same model as
    the primary is told apart by its label's tag, so the line stays short: «отвечает бесплатная Qwen3.8-27B»,
    «попробую Qwen3.8-27B на Groq»; another model is «запасная Gemma 4 31B»."""
    name = _short_name(backup)
    if name != _short_name(primary):
        return f"запасная {name}", f"запасную {name}", name
    m = re.search(r"\(([^()]*)\)\s*$", _label(backup))
    tag = m.group(1).strip() if m else ""
    if tag.lower() == "бесплатно":
        return f"бесплатная {name}", f"бесплатную {name}", f"бесплатная {name}"
    if tag.lower() == "локально":
        return f"{name} локально", f"{name} локально", f"{name} локально"
    if tag:
        return f"{name} на {tag}", f"{name} на {tag}", f"{name} на {tag}"
    return f"запасная {_label(backup)}", f"запасную {_label(backup)}", _label(backup)


def _link_code(link: dict) -> str:
    """A failed link's reason code: its state, and for a bare «error» what its last error says (a dropped connection
    and a 400 are both «error» to the status module)."""
    state = link["state"]
    if state != "error":
        return state
    code = _segment_code(link.get("last_error") or "")
    return code if code in ("unreachable", "timeout", "congested") else "error"


def _retryable_link(link: dict) -> bool:
    code = _link_code(link)
    # «error» with a pause is a connection that kept dropping (a 400 opens no pause)
    return code in RETRYABLE_REASONS or (code == "error" and bool(link.get("until")))


def _hint(primary: dict, ctx: ChainContext, *, backup: bool) -> Optional[str]:
    """The detailed hint under the indicator: what helps, plus the optional free Groq key."""
    code = _link_code(primary)
    who = link_of(primary)
    if backup:
        head = "Презентацию соберёт запасная модель."
        if code in ("congested", "rate", "quota") and ctx.openrouter and who.openrouter_free:
            body: Optional[str] = steady_tip(ctx)
        elif code in ("no_credits", "auth", "missing"):
            body = advice(code, ctx, who)
        else:
            body = None
        parts = [head, body]
    else:
        parts = [advice(code, ctx, who)]
    parts.append(groq_tip(ctx))
    text = " ".join(p for p in parts if p)
    return text or None


def summarize(links: list[dict], *, configured: bool, ctx: Optional[ChainContext] = None) -> dict:
    """Overall state + one short line for the indicator («Модель: Qwen3.8-27B — доступна») + the detailed hint.

    `advice` is what the notice above a failed deck says now (the live button's words agree with it); `retryable`:
    building again can work now or once `retry_in` is over (False when a key, an account or a model id needs a fix)."""
    ctx = ctx or chain_context(links)
    none = {"hint": None, "working_label": None, "retry_in": None, "retry_state": None, "advice": None, "retryable": True}
    active = [link for link in links if link["state"] != "off"]
    if not configured or not active:
        return {**none, "state": "off", "summary": "Модель не подключена · соберёт встроенный планировщик", "hint": groq_tip(ctx) if configured else None, "retryable": False}
    primary = active[0]
    pname = _short_name(primary)
    if _usable(primary):
        if primary["state"] == "ok":
            return {**none, "state": "ok", "summary": f"Модель: {pname} — доступна", "working_label": pname, "advice": "Модель снова отвечает — соберите ещё раз."}
        if primary["state"] == "unknown":
            return {**none, "state": "unknown", "summary": f"Модель: {pname} — подключена", "working_label": pname, "advice": "Соберите ещё раз — модель попробует снова."}
        word = _RECENT_WORD.get(primary["state"], "недавно не ответила, попробую снова")
        return {**none, "state": "retry", "summary": f"Модель: {pname} — {word}", "working_label": pname, "advice": "Пауза после сбоя закончилась — соберите ещё раз."}
    phrase = _STATE_PHRASE.get(_link_code(primary), _STATE_PHRASE.get(primary["state"], "{name} недоступна")).format(name=pname)
    backup = next((link for link in active[1:] if _usable(link)), None)
    if backup is not None:
        answers, will_try, bname = _backup_words(backup, primary)
        ok = backup["state"] == "ok"
        return {
            **none,
            "state": "fallback",
            "summary": f"Модель: {phrase} · {'отвечает ' + answers if ok else 'попробую ' + will_try}",
            "hint": _hint(primary, ctx, backup=True),
            "working_label": bname,
            "retry_in": primary.get("until"),
            "retry_state": primary["state"] if primary.get("until") else None,
            "advice": f"Сейчас отвечает {answers} — соберите ещё раз." if ok else f"Соберите ещё раз — попробую {will_try}.",
        }
    waiting = [link for link in active if link.get("until")]
    soonest = min(waiting, key=lambda link: link["until"]) if waiting else None
    blocking = soonest or primary  # the link whose pause ends first: the live button waits for it
    summary = f"Модель: {phrase} · соберёт встроенный планировщик" if len(active) == 1 else "Модель недоступна · соберёт встроенный планировщик"
    return {
        **none,
        "state": "down",
        "summary": summary,
        "hint": _hint(primary, ctx, backup=False),
        "retry_in": soonest["until"] if soonest else None,
        "retry_state": soonest["state"] if soonest else None,
        "advice": advice(_link_code(blocking), ctx, link_of(blocking)),
        "retryable": _retryable_link(blocking),
    }


def config_label(path: Optional[Path], repo_root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return Path(path).name


def llm_config(registry: Any) -> dict:
    """The llm role's spec of models.yaml; for a fallback chain its first link (with the chain's shared keys)."""
    cfg = getattr(registry, "config", None) or {}
    spec = ((cfg.get("roles") or {}).get("llm") or {}) if isinstance(cfg, dict) else {}
    if isinstance(spec, dict) and isinstance(spec.get("chain"), list) and spec["chain"]:
        first = spec["chain"][0] if isinstance(spec["chain"][0], dict) else {}
        return {**{k: v for k, v in spec.items() if k != "chain"}, **first}
    return spec if isinstance(spec, dict) else {}


def active_chain_context(registry: Any, *, config: Optional[str]) -> ChainContext:
    """The ChainContext of the running server's config (for the advice in the notice above a deck)."""
    links, _ = collect_links(registry)
    if not links:
        host = hostname(llm_config(registry).get("base_url"))
        return ChainContext(openrouter=_is_openrouter(host) if host else True, config=config)
    return chain_context(links, config)


def models_status(registry: Any, *, configured: bool, config_path: Optional[Path], repo_root: Path) -> dict:
    """GET /api/models/status: the chain's links, the overall state and a line for the UI. Never calls a model."""
    config = config_label(config_path, repo_root)
    links, source = collect_links(registry, configured)
    ctx = chain_context(links, config) if links else ChainContext(config=config)
    overall = summarize(links, configured=configured, ctx=ctx)
    active = [link for link in links if link["state"] != "off"]
    primary = active[0] if active else (links[0] if links else None)
    llm_cfg = llm_config(registry)
    active_model = primary["model"] if primary else llm_cfg.get("model")
    if registry is not None and not active_model:
        try:
            active_model = registry.get("llm").model
        except Exception:  # noqa: BLE001
            active_model = None
    return {
        "configured": configured,
        "config": config,
        "active_model": active_model,
        "active_model_label": (primary.get("short_label") if primary else None) or model_label(active_model),
        "host": (primary.get("host") if primary else None) or hostname(llm_cfg.get("base_url")),
        "links": links,
        "source": source,
        **overall,
    }
