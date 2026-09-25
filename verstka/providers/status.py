"""Health of every model link, recorded as calls happen (no probing requests).

A link is one model on one account (base_url + key). Its hold ("skip this link for N s") is its own: a congested free
Qwen does not block Gemma or the paid Qwen on the same OpenRouter key. Quotas that belong to the account rather than
to one model — the free models' daily and per-minute caps of OpenRouter — are kept per *pool* (account + free/paid),
so a spent free quota never blocks a paid model on the same key.

`snapshot()` is what the UI shows: per link its human label, host, state, last success, last error and seconds till
the next try.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

# ok          answered last time
# unknown     not tried in this server run
# congested   the host answered 429 «temporarily rate-limited upstream», a 5xx or timed out — retry later
# rate        the account's per-minute request cap (a hold under 90 s)
# quota       the free models' daily request quota of the account is spent (until the next 00:00 UTC)
# no_credits  402, or 403 «key limit exceeded» / spending limit of the key
# auth        401 / 403: the key is rejected
# missing     404: no such model, or no endpoint serves it
# error       anything else
# off         configured, but its API key variable is empty: skipped silently, never an error
STATES = ("ok", "unknown", "congested", "rate", "quota", "no_credits", "auth", "missing", "error", "off")

# the words every error message of a state carries, so the UI can classify the text of older warnings as well
PHRASES = {
    "congested": "congested upstream",
    "rate": "per-minute request cap",
    "quota": "daily request quota",
    "no_credits": "no credits (402)",
    "auth": "access refused (401/403)",
    "missing": "model not available (404)",
    "off": "not configured (no API key)",
}

_LOCK = threading.RLock()


@dataclass
class LinkHealth:
    key: str  # account|model — never shown (the account part carries the key's tail)
    model: str
    label: str
    pool: str  # account|free or account|paid: whose quota a daily / per-minute 429 spends
    host: str = ""  # hostname of the endpoint, for the UI (two hosts may serve the same model id)
    free: bool = False
    off: bool = False  # no API key: never called
    state: str = "unknown"
    last_ok: Optional[float] = None  # time.time() of the last answer
    ok_at: Optional[float] = None  # time.monotonic() of the last answer: older failures do not count "in a row"
    last_error: str = ""
    last_error_at: Optional[float] = None
    until: float = 0.0  # time.monotonic() before which the link is not tried
    strikes: int = 0  # upstream 429s in a row
    transient: int = 0  # 5xx / timeouts / dropped connections in a row


@dataclass
class _PoolBlock:
    until: float
    state: str
    error: str


_LINKS: dict[str, LinkHealth] = {}
_POOLS: dict[str, _PoolBlock] = {}


def hostname(base_url: str) -> str:
    try:
        return urlparse(base_url or "").hostname or ""
    except ValueError:
        return ""


def link(
    key: str,
    model: str,
    label: str,
    pool: str,
    *,
    explicit: bool = True,
    host: str = "",
    free: Optional[bool] = None,
    off: bool = False,
) -> LinkHealth:
    """The shared health record of (account, model): the llm and vlm roles of one config share it. A label set in
    the config replaces the one a record already has; a default label never replaces a configured one."""
    with _LOCK:
        h = _LINKS.get(key)
        if h is None:
            h = _LINKS[key] = LinkHealth(key=key, model=model, label=label, pool=pool)
            h.host = host
            h.free = model.endswith(":free") if free is None else bool(free)
        elif label and explicit:
            h.label = label
        if host:
            h.host = host
        if free is not None:
            h.free = bool(free)
        h.off = off
        if off:
            h.state = "off"
        elif h.state == "off":
            h.state = "unknown"
        return h


def blocked(h: LinkHealth, ignore: Iterable[str] = ()) -> Optional[tuple[str, str, float]]:
    """(state, reason, seconds left) when the link must not be tried now — its own hold or its pool's quota.
    States in `ignore` do not block (a single provider waits a per-minute cap out instead of skipping)."""
    ignore = tuple(ignore)
    now = time.monotonic()
    with _LOCK:
        p = _POOLS.get(h.pool)
        if p is not None and p.until > now and p.state not in ignore:
            return p.state, p.error, p.until - now
        if h.until > now and h.state not in ignore:
            return h.state, h.last_error, h.until - now
    return None


def record_ok(h: LinkHealth) -> None:
    with _LOCK:
        h.state = "ok"
        h.last_ok = time.time()
        h.ok_at = time.monotonic()
        h.until = 0.0
        h.strikes = 0
        h.transient = 0
        p = _POOLS.get(h.pool)
        if p is not None and p.until <= time.monotonic():
            _POOLS.pop(h.pool, None)


def fail(
    h: LinkHealth,
    state: str,
    error: str,
    *,
    hold_s: float = 0.0,
    counter: Optional[str] = None,
    threshold: int = 2,
    started: Optional[float] = None,
) -> tuple[int, float]:
    """Record a failure and decide its hold under one lock; returns (failures in a row, seconds the link is now on
    hold because of it: the hold it opened, or the longer one that stays — see below; 0.0 when none).

    Without `counter` the hold is `hold_s` straight away (402, 404, spent quota...). With `counter` ("strikes" for
    upstream 429s, "transient" for 5xx / timeouts) the failure is counted and the hold opens once `threshold`
    failures came in a row. A failure whose request started (`started`, time.monotonic()) before the link's last
    answer is not counted and changes neither the state nor the hold: the host answered since, so it is not "in a
    row" (parallel calls of three variants that were already in flight).

    State, reason and hold stay one piece: while a hold is active that ends later than the one this failure would
    open (none, or a shorter one), the link keeps that hold's state and reason — a 502 that was in flight never turns
    a 10-minute «no credits» hold into «congested, retry in 600 s». Otherwise the failure sets the state, the reason
    and its own hold. The returned hold is then the one that stays, and `own_hold()` names its state and reason, so
    the caller never reports «congested, skipped for 120 s» for a link that is on a 30-minute «404» hold."""
    with _LOCK:
        now = time.monotonic()
        stale = counter is not None and started is not None and h.ok_at is not None and started < h.ok_at
        n = 0
        if counter is not None:
            if not stale:
                setattr(h, counter, getattr(h, counter) + 1)
            n = getattr(h, counter)
        hold = 0.0
        if not stale and hold_s > 0 and (counter is None or n >= threshold):
            hold = hold_s
        if h.until > now and h.until > now + hold:
            return n, h.until - now  # a longer hold is active: its state, reason and end stay
        if not stale:
            h.state = state
        h.last_error = _short(error)
        h.last_error_at = time.time()
        if hold > 0:
            h.until = now + hold
        return n, hold


def own_hold(h: LinkHealth) -> Optional[tuple[str, str, float]]:
    """(state, reason, seconds left) of the link's own hold, None without one (its pool's quota is not counted)."""
    with _LOCK:
        left = h.until - time.monotonic()
        return (h.state, h.last_error, left) if left > 0 else None


def record_error(h: LinkHealth, state: str, error: str, hold_s: float = 0.0) -> None:
    """Remember a failure; `hold_s` > 0 skips the link for that long."""
    fail(h, state, error, hold_s=hold_s)


def block_pool(pool: str, state: str, error: str, hold_s: float) -> None:
    """Every link of the pool (e.g. all free models of one OpenRouter key) is skipped for `hold_s`."""
    with _LOCK:
        until = time.monotonic() + max(0.0, hold_s)
        cur = _POOLS.get(pool)
        if cur is None or cur.until < until:
            _POOLS[pool] = _PoolBlock(until=until, state=state, error=_short(error))


def reset() -> None:
    """Forget every hold and quota (tests; a restart does the same). Records keep their identity."""
    with _LOCK:
        for h in _LINKS.values():
            h.state = "off" if h.off else "unknown"
            h.last_ok, h.ok_at, h.last_error, h.last_error_at = None, None, "", None
            h.until, h.strikes, h.transient = 0.0, 0, 0
        _POOLS.clear()


def health_dict(h: LinkHealth) -> dict[str, Any]:
    """One link as the UI gets it: model, label, host, free, state, available, until, last_ok, last_error."""
    now = time.monotonic()
    with _LOCK:
        if h.off:
            state, error, left = "off", PHRASES["off"], 0.0
        else:
            state, error, left = h.state, h.last_error, max(0.0, h.until - now)
            p = _POOLS.get(h.pool)
            if p is not None and p.until > now and p.until - now >= left:
                state, error, left = p.state, p.error or error, p.until - now
        return {
            "model": h.model,
            "label": h.label,
            "host": h.host,
            "free": h.free,
            "state": state,
            "available": not h.off and left <= 0,
            "until": max(1, int(round(left))) if left > 0 else None,
            "last_ok": h.last_ok,
            "last_error": error,
        }


def _links_of(provider: Any) -> list[Any]:
    inner = getattr(provider, "inner", None)  # a registry bound to a generation's deadline
    if inner is not None and inner is not provider:
        return _links_of(inner)
    links = getattr(provider, "links", None)
    if links:
        out: list[Any] = []
        for p in links:
            out.extend(_links_of(p))
        return out
    return [provider]


def snapshot(providers: Any = None, role: Optional[str] = None) -> list[dict[str, Any]]:
    """Per link: model, label, host, free, state (see STATES), available, until (seconds till the next try, or
    None), last_ok (unix time or None), last_error (short, keys masked), roles.

    With a ProviderRegistry: its links in chain order (a link shared by llm and vlm appears once, with both roles);
    without one: every link this process has built. Mock providers have no health and are left out."""
    if providers is None:
        with _LOCK:
            records = list(_LINKS.values())
        return [{**health_dict(h), "roles": []} for h in records]
    out: dict[str, dict[str, Any]] = {}
    for r, p in (getattr(providers, "roles", None) or {}).items():
        if role is not None and r != role:
            continue
        for ln in _links_of(p):
            h = getattr(ln, "health", None)
            if h is None:
                continue
            if h.key not in out:
                out[h.key] = {**health_dict(h), "roles": []}
            if r not in out[h.key]["roles"]:
                out[h.key]["roles"].append(r)
    return list(out.values())


# API keys look like sk-or-v1-…, gsk_… (Groq), Bearer …, key=…; long random strings are masked as well
_SECRET_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:sk|gsk|key|api[-_]?key|bearer)[-_:= ]{0,3}[A-Za-z0-9_\-.]{12,}")
_LONG_RE = re.compile(r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}")


def mask(text: str, *secrets: str) -> str:
    """The text without API keys: the given secrets (a link's own key) and anything shaped like a key."""
    text = str(text)
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "[redacted]")
    text = _SECRET_RE.sub("[redacted]", text)
    return _LONG_RE.sub("[redacted]", text)


def _short(text: str, n: int = 200) -> str:
    text = mask(" ".join(str(text).split()))  # an error must never carry a key to the UI
    return text if len(text) <= n else text[: n - 1] + "…"
