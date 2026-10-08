"""OpenAI-compatible chat provider: Polza.ai (https://polza.ai — the models of the qualifying stage, paid in rubles)
and VK inference (the final's Qwen3.8-27B, configs/models.vk.yaml).

Polza's answers that matter here (docs: polza.ai/docs/api-reference/introduction):
* 402 INSUFFICIENT_BALANCE — no money on the balance, or the key's / member's spending limit is spent (the text says
  «лимит»), or — under parallel load — the balance is reserved by the requests in flight (the text names the reserved
  sum): a short pause and one more try;
* 429 of two kinds — Polza's own per-model cap of the organisation (with Retry-After: seconds to the next minute or to
  midnight by Moscow time) and the model host's own rate limit (no Retry-After; metadata.provider_name);
* 408 / 502 / 503 — worth another try (503 not before its Retry-After); 400 / 401 / 403 / 404 / 413 — not: a 403 may
  also be the moderation refusing one request, which says nothing about the key;
* every answer's usage carries cost_rub — what the call cost; a failed request costs nothing.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from collections import deque
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from verstka.providers import status
from verstka.providers.base import ChatMessage, CompletionResult, ProviderError, Usage

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_CODE_RE = re.compile(r"error code:\s*(\d{3})", re.I)
_THINK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.S | re.I)
# Polza's 402 when the spending limit of the key or of the member is spent: the text speaks of exceeding a limit
_SPEND_LIMIT_RE = re.compile(r"лимит|limit", re.I)
# Polza's 402 under parallel load: the text names the sum the requests in flight hold («зарезервировано 25.00 ₽»,
# «25.00 ₽ зарезервировано», «reserved: 3.5», «3.5 RUB reserved»)
_RESERVED_RE = re.compile(
    r"(?:зарезервирован\w*|reserved)\D{0,24}?(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:₽|руб\w*\.?|rub)?\s*(?:уже\s+)?(?:зарезервирован\w*|reserved)",
    re.I,
)
# a 403 that refuses one request (Polza's moderation, a host's content filter), not the key
_MODERATION_RE = re.compile(r"модерац|moderat|content (?:policy|filter)|flagged", re.I)
# Polza's own 429 names the window («Достигнут минутный (дневной) лимит запросов к модели»)
_DAILY_RE = re.compile(r"дневн|суточн|per[- ]day|daily", re.I)
_MINUTE_RE = re.compile(r"минутн|per[- ]minute", re.I)
# the host's own 429 passed on by Polza («Провайдер модели ограничил частоту запросов…»; the host is named in
# metadata.provider_name — Polza's own caps name none)
_HOST_LIMIT_RE = re.compile(r"провайдер\w* модели ограничил|upstream|provider returned|temporarily rate-limited|provider_name|\(provider: ", re.I)
# the sums a 402 names: what the request needs, what is available, what the requests in flight hold
_NEEDED_RE = re.compile(r"(?:требуется|необходимо|нужно|required|needed)\D{0,16}?(\d+(?:[.,]\d+)?)", re.I)
_AVAILABLE_RE = re.compile(r"(?:доступно|available|на балансе)\D{0,16}?(\d+(?:[.,]\d+)?)", re.I)


class RateLimited(ProviderError):
    """429 from the provider: `daily` when the day's quota is spent (retrying today is pointless); `upstream` when it
    is the model host's own rate limit rather than a cap of our account."""

    def __init__(self, message: str, retry_after: Optional[float] = None, daily: bool = False, upstream: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.daily = daily
        self.upstream = upstream or bool(_HOST_LIMIT_RE.search(message))


class LinkUnavailable(ProviderError):
    """This model cannot answer for a while (no credits, no such model, rejected key, congested host, spent quota,
    no API key): a fallback chain moves on to its next link. `state` is one of status.STATES; `hold_s` is how long a
    chain skips the link."""

    def __init__(self, message: str, state: str = "error", hold_s: float = 0.0) -> None:
        super().__init__(message)
        self.state = state
        self.hold_s = hold_s


class TransientError(ProviderError):
    """5xx, timeout, dropped connection: worth another try a little later."""

    def __init__(self, message: str, timeout: bool = False, state: str = "congested") -> None:
        super().__init__(message)
        self.timeout = timeout
        self.state = state


class BudgetSpent(ProviderError):
    """The generation's time budget does not leave room for this request."""


class _BodyError(RuntimeError):
    """An error the host returned inside an HTTP 200 body (a stream that failed mid-way: finish_reason "error")."""

    def __init__(self, message: str, status_code: Optional[int]) -> None:
        super().__init__(message)
        self.status_code = status_code


class _MinuteLimiter:
    """At most `rpm` requests in any 60 s window, shared by every provider on the same account and model (the llm and
    vlm roles both count against the cap of one model) — only when a config sets requests_per_minute."""

    def __init__(self, rpm: int) -> None:
        self.rpm = max(1, rpm)
        self.lock = threading.Lock()
        self.stamps: deque = deque()

    def try_acquire(self) -> float:
        """Take a slot now and return 0, or take nothing and return the seconds until the next slot frees."""
        with self.lock:
            now = time.monotonic()
            while self.stamps and now - self.stamps[0] >= 60.0:
                self.stamps.popleft()
            if len(self.stamps) < self.rpm:
                self.stamps.append(now)
                return 0.0
            return max(0.05, 60.0 - (now - self.stamps[0]) + 0.05)

    def wait(self, deadline: Optional[float] = None) -> None:
        while True:
            delay = self.try_acquire()
            if delay <= 0:
                return
            # never sleep past the generation's budget: the caller takes its deterministic path instead
            if deadline is not None and time.monotonic() + delay > deadline - _MIN_REQUEST_S:
                raise BudgetSpent("time budget of the generation is spent while waiting for a rate-limit slot")
            time.sleep(delay)


_MIN_REQUEST_S = 5.0  # less time than this left in the generation's budget: do not start a request
_TLS = threading.local()


def requests_sent() -> int:
    """HTTP requests this thread has sent so far (every attempt, retry and repair): a caller that wraps one
    complete() reads it before and after to know what the call really cost."""
    return getattr(_TLS, "sent", 0)


_LIMITERS: dict[str, _MinuteLimiter] = {}
_GUARD = threading.Lock()
# how long a link is skipped (status.py keeps the holds per account + model)
_CONGESTION_S = 120.0  # two 429s of the model's hosts in a row — a single provider as well as a chain link
# inside a fallback chain only:
_NO_CREDITS_S = 600.0  # 402: retried after 10 minutes, so a top-up of the balance (or a higher key limit) is picked up soon
_GONE_S = 1800.0  # 404 / 401 / 403: no such model, a rejected or revoked key
_TRANSIENT_S = 60.0  # two 5xx / timeouts / connection errors in a row, or a timeout of a link that is not the last
# a single provider (the final's VK inference): a 402 / 401 / 403 / 404 is reported after its attempts, then at most
# this short hold, so a hiccup of the only model never costs more than a minute
_SINGLE_HOLD_S = 60.0
# a JSON answer cut off at max_tokens is asked again once with twice the room, up to this many tokens
_CUT_MAX_TOKENS = 8192
_CUT_RETRY = (
    "Your previous answer was cut off at the length limit and is lost. Answer again from the start with a much shorter "
    "JSON object: fewer items, short strings, no quotes from the source text. Close every bracket."
)


def _status_of(e: Exception) -> Optional[int]:
    code = getattr(e, "status_code", None)
    if isinstance(code, int):
        return code
    m = _CODE_RE.search(str(e))
    return int(m.group(1)) if m else None


def _retry_after(e: Exception) -> Optional[float]:
    """The answer's Retry-After header, in seconds (Polza sends it with its own 429 and with a 503)."""
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    try:
        value = headers.get("retry-after") if hasattr(headers, "get") else None
        if value in (None, ""):
            value = headers.get("Retry-After") if hasattr(headers, "get") else None
        return max(0.0, float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _rate_limit_info(e: Exception, text: Optional[str] = None, polza: bool = True) -> Optional[RateLimited]:
    """A 429 → RateLimited. On Polza its own cap of the organisation on the model comes with Retry-After — the seconds
    to the next minute or to midnight by Moscow time, the one signal that tells the two windows apart (the documented
    wording «Достигнут минутный (дневной) лимит…» may name both) —, the model hosts' own limit without it. Another
    endpoint (the final's VK inference) reads a bare 429 as a per-minute cap, as before the migration."""
    status_code = getattr(e, "status_code", None)
    text = str(e) if text is None else text
    low = text.lower()
    if status_code != 429 and "429" not in text and "too_many_requests" not in low and "rate limit" not in low:
        return None
    retry_after = _retry_after(e)
    host = bool(_HOST_LIMIT_RE.search(text))
    if polza:
        own = not host and (retry_after is not None or bool(_MINUTE_RE.search(text) or _DAILY_RE.search(text)))
    else:
        own = not host
    if retry_after is not None:
        # the per-minute window ends within a minute (a few seconds more for the clocks); anything longer is the day's
        # cap, minutes before midnight by Moscow time included
        daily = own and retry_after > 90
    else:
        daily = own and bool(_DAILY_RE.search(text)) and not _MINUTE_RE.search(text)
    return RateLimited(text[:300], retry_after=retry_after, daily=daily, upstream=not own)


def _amount(s: str) -> float:
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return 0.0


def classify_error(e: Exception, model: str, secret: str = "", polza: bool = True) -> ProviderError:
    """An SDK / HTTP error → the ProviderError subclass that tells the caller (and a fallback chain) what to do.
    The message carries the state's wording (status.PHRASES); `secret` (the link's key) never appears in it.
    `polza`: Polza's rules for a 429 (see _rate_limit_info); False for another endpoint."""
    if isinstance(e, ProviderError):
        return e
    code = _status_of(e)
    text = status.mask(" ".join(str(e).split())[:400], secret)
    low = text.lower()
    if code is None or code == 429:
        rl = _rate_limit_info(e, text, polza=polza)
        if rl is not None:
            return rl
    if code == 402 or "insufficient_balance" in low or "payment required" in low:
        held = _RESERVED_RE.search(text)
        reserved = _amount(held.group(1) or held.group(2) or "0") if held else 0.0
        needed, available = _NEEDED_RE.search(text), _AVAILABLE_RE.search(text)
        # the reserve is the cause when its return would cover the request (or the text does not say what it needs);
        # a spent limit or balance that the reserve would not cover is no passing trouble
        covered = needed is None or available is None or _amount(available.group(1)) + reserved >= _amount(needed.group(1))
        if reserved > 0 and covered:
            # the requests in flight hold the balance: one of them ends in seconds and frees its reserve
            err = TransientError(f"{model}: {status.PHRASES['congested']}: the balance is held by the requests in flight (402) ({text})")
            err.reserve = True  # type: ignore[attr-defined]
            return err
        if _SPEND_LIMIT_RE.search(text):
            return LinkUnavailable(f"{model}: no credits (402): the spending limit of the key is spent ({text})", state="no_credits", hold_s=_NO_CREDITS_S)
        return LinkUnavailable(f"{model}: no credits (402) on the balance ({text})", state="no_credits", hold_s=_NO_CREDITS_S)
    if code == 401 or "api_key_revoked" in low:
        return LinkUnavailable(f"{model}: access refused (401/403): HTTP {code or 401}, check the key ({text})", state="auth", hold_s=_GONE_S)
    if code == 403:
        if _MODERATION_RE.search(text):
            # moderation refused this request: another request (or the other model) may pass, the key is fine
            return _plain(f"{model}: the request was refused by moderation (403) ({text})", 403)
        return LinkUnavailable(f"{model}: access refused (401/403): HTTP 403, check the key ({text})", state="auth", hold_s=_GONE_S)
    if code == 404 or (code in (None, 400) and any(s in low for s in ("model not found", "not a valid model", "no such model", "does not exist"))):
        return LinkUnavailable(f"{model}: model not available (404): no such model or no host serves it ({text})", state="missing", hold_s=_GONE_S)
    if code == 413:
        return _plain(f"{model}: the request is too large for the model (413) ({text})", 413)
    kind = type(e).__name__.lower()
    if "timeout" in kind or "timed out" in low or code == 408:
        return TransientError(f"{model}: request timed out ({code or 'no answer in time'}), congested upstream", timeout=True)
    if code is not None and code >= 500:
        err = TransientError(f"{model}: {code} server error, congested upstream ({text})")
        err.retry_after = _retry_after(e)  # type: ignore[attr-defined]  # a 503 «no hosts for the model»: not before it
        return err
    if "connection" in kind or "connection error" in low or isinstance(e, ConnectionError):
        return TransientError(f"{model}: connection error ({text})", state="error")
    return _plain(f"{model}: {text}" if code is None or str(code) in text else f"{model}: {code} {text}", code)


def _plain(message: str, code: Optional[int]) -> ProviderError:
    """An error the same request would get again (a 400, a 413, a refusal of moderation): `no_retry` — the attempts
    stop at once (a chain asks its next link); `status_code` lets the caller drop an option the host rejects (a 400)."""
    err = ProviderError(message)
    err.status_code = code  # type: ignore[attr-defined]
    err.no_retry = code is not None and 400 <= code < 500  # type: ignore[attr-defined]
    return err


_MSK_MIDNIGHT_UTC_H = 21  # 00:00 in Moscow (UTC+3 all year)


def _quota_hold(e: RateLimited) -> float:
    """How long Polza's spent daily cap of a model blocks it: its Retry-After, else until midnight by Moscow time."""
    if e.retry_after is not None and e.retry_after > 60:
        return min(e.retry_after, 86400.0)
    now = time.time()
    since = (now - _MSK_MIDNIGHT_UTC_H * 3600.0) % 86400.0
    return 86400.0 - since + 5.0


def _unavailable(model: str, state: str, reason: str, left: float) -> LinkUnavailable:
    """The link is on hold: skipped without a request."""
    what = status.PHRASES.get(state, "the model did not answer")
    err = LinkUnavailable(f"{model}: {what}, skipped for {left:.0f} s more ({reason})", state=state)
    err.skipped = True  # type: ignore[attr-defined]
    return err


_KNOWN_LABELS = {"qwen3.8-27b": "Qwen3.8-27B", "qwen3.6-27b": "Qwen3.6-27B"}


def default_label(model: str, base_url: str = "") -> str:
    """A human name for the UI: «qwen/qwen3.8-27b» → «Qwen3.8-27B» (a config may set its own `label`)."""
    base = model.split("/")[-1]
    name = _KNOWN_LABELS.get(base.lower())
    if name is None:
        tokens = [t for t in re.split(r"[-_: ]+", base) if t and t.lower() not in ("it", "instruct", "chat", "latest")]
        tokens = [t.upper() if re.fullmatch(r"a?\d+(\.\d+)?b", t, re.I) else t for t in tokens]
        if tokens:
            tokens[0] = tokens[0][:1].upper() + tokens[0][1:]
        name = " ".join(tokens) or model
    return name


# Polza's public catalog of a model's hosts (no key needed): hosts whose weights are quantized below the floor are
# left out of the routing (Qwen garbled JSON on 4-bit hosts). Read per model and process, again after `_CATALOG_TTL_S`;
# a failed or empty read retries after `_CATALOG_RETRY_S` and meanwhile Polza routes freely.
_CATALOG_URL = "https://api.polza.ai/v1/models/{model}"
_CATALOG_RETRY_S = 600.0
_CATALOG_TTL_S = 6 * 3600.0  # hosts come and go: the list is read again after this long
_EXCLUDED: dict[tuple[str, tuple[str, ...]], tuple[float, list[str]]] = {}
_READING: dict[tuple[str, tuple[str, ...]], threading.Lock] = {}  # one read per model at a time
_CATALOG_TIMEOUT_S = 8.0


def _fetch_hosts(model: str, timeout: float = 8.0) -> list[str]:
    """The names of a model's hosts in Polza's catalog («deepinfra/bf16», «morph/fp4», «phala»...)."""
    import httpx

    r = httpx.get(_CATALOG_URL.format(model=model), timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    data = data.get("data", data) if isinstance(data, dict) else {}
    return [str(p.get("name")) for p in (data.get("providers") or []) if isinstance(p, dict) and p.get("name")]


def excluded_hosts(model: str, quantizations: tuple[str, ...], deadline: Optional[float] = None) -> list[str]:
    """Hosts of `model` whose name ends in one of `quantizations` («/fp4»): the `provider.ignore` list of its requests.
    VERSTKA_NO_CATALOG=1 (tests, an offline run) skips the catalog: nothing is left out. The calls side by side wait
    for one read instead of reading too; none waits or reads past the time its request needs (`deadline`) — it goes
    unfiltered then, and the read is left to a later call."""
    if not quantizations or os.environ.get("VERSTKA_NO_CATALOG", "").strip().lower() not in ("", "0", "false", "no"):
        return []
    key = (model, tuple(sorted(q.lower() for q in quantizations)))
    with _GUARD:
        hit = _EXCLUDED.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return list(hit[1])
        reading = _READING.setdefault(key, threading.Lock())
    spare = _CATALOG_TIMEOUT_S if deadline is None else min(_CATALOG_TIMEOUT_S, deadline - time.monotonic() - _MIN_REQUEST_S)
    if spare < 1.0 or not reading.acquire(timeout=spare):
        return []
    try:
        with _GUARD:
            hit = _EXCLUDED.get(key)
            if hit is not None and hit[0] > time.monotonic():
                return list(hit[1])  # read by the call this one waited for
        return _read_catalog(model, quantizations, key, spare)
    finally:
        reading.release()


def _read_catalog(model: str, quantizations: tuple[str, ...], key: tuple, timeout: float) -> list[str]:
    now = time.monotonic()
    try:
        hosts = _fetch_hosts(model, timeout=timeout)
        names = [n for n in hosts if any(n.lower().endswith("/" + q.lower()) for q in quantizations)]
        until = now + _CATALOG_TTL_S
        if not hosts:
            log.warning("%s: Polza's catalog lists no hosts for the model; hosts are not filtered for %.0f s", model, _CATALOG_RETRY_S)
            until = now + _CATALOG_RETRY_S
    except Exception as e:  # noqa: BLE001 - the catalog is a nicety: Polza still routes the request
        log.warning("%s: Polza's catalog of hosts is unavailable (%s); hosts are not filtered for %.0f s", model, str(e)[:160], _CATALOG_RETRY_S)
        names, until = [], now + _CATALOG_RETRY_S
    with _GUARD:
        _EXCLUDED[key] = (until, names)
    if names:
        log.info("%s: hosts left out of the routing (%s weights): %s", model, "/".join(quantizations), ", ".join(names))
    return list(names)


class TruncatedJSON(ValueError):
    """The model's JSON was cut off (the answer hit max_tokens, or the host stopped it): no object of it may stand in
    for the answer — an inner object of a cut-off answer validates as an empty (all-default) answer."""


_PAIRS = {"{": "}", "[": "]"}


def _balanced(text: str, start: int) -> Optional[int]:
    """End (exclusive) of the bracket structure opened at text[start], or None when it never closes (cut off)."""
    stack: list[str] = []
    in_str = esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in _PAIRS:
            stack.append(_PAIRS[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                return i + 1
    return None


def _fits(data: Any, keys: Optional[set[str]], whole: bool) -> bool:
    """A candidate stands for the answer: with `keys` (the schema's top-level fields) it is an object holding at least
    one of them — an inner object of the answer («{"id": "f1", …}») never does. An empty object counts only as the
    whole answer («{}»: nothing found), never as a piece of it."""
    if keys is None:
        return True
    if not isinstance(data, dict):
        return False
    if not data:
        return whole
    return any(k in keys for k in data)


def schema_keys(schema: type[BaseModel]) -> set[str]:
    """Top-level field names (and aliases) of a schema: what extract_json requires of the object it picks."""
    keys: set[str] = set()
    for name, f in schema.model_fields.items():
        keys.add(name)
        if f.alias:
            keys.add(f.alias)
    return keys


_BAD_ESCAPE_RE = re.compile(r'\\(?!["\\/bfnrtu])|\\u(?![0-9a-fA-F]{4})')


def _loads(text: str) -> Any:
    """json.loads, and on an invalid escape once more with that backslash taken literally: a formula's LaTeX written
    with single backslashes («\\int», «\\sqrt», «\\,») is an answer, not broken JSON."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        if "escape" not in str(e).lower():
            raise
        return json.loads(_BAD_ESCAPE_RE.sub(lambda m: "\\\\" + m.group(0)[1:], text))


def extract_json(text: str, keys: Optional[set[str]] = None) -> Any:
    """Pull the JSON answer out of model output (fenced or inline).

    `keys`: the schema's top-level fields — the object picked must hold at least one of them (see _fits). An object
    that opens and never closes means the answer was cut off: nothing inside it is picked (TruncatedJSON), since an
    inner object of a cut-off answer would validate silently as an empty answer."""
    text = text.strip()
    for m in _FENCE_RE.finditer(text):
        candidate = m.group(1).strip()
        try:
            data = _loads(candidate)
        except ValueError:
            continue
        if _fits(data, keys, whole=True):
            return data
    try:
        data = _loads(text)
    except ValueError:
        pass
    else:
        if _fits(data, keys, whole=True):
            return data
        # a wrapper around the answer ({"result": {...}}): an object inside it may still be the answer
    # the top-level structures in order: one that never closes is the cut-off answer, and everything after its opening
    # bracket is inside it
    cut_at: Optional[int] = None
    pos = 0
    while True:
        opener = min((i for i in (text.find("{", pos), text.find("[", pos)) if i != -1), default=-1)
        if opener == -1:
            break
        end = _balanced(text, opener)
        if end is None:
            cut_at = opener
            break
        pos = end
    # scan for balanced {...} or [...] before the cut
    limit = len(text) if cut_at is None else cut_at
    found_any = False
    for opener in ("{", "["):
        start = text.find(opener, 0, limit)
        while start != -1:
            end = _balanced(text, start)
            if end is not None:
                try:
                    data = _loads(text[start:end])
                except ValueError:
                    data = None
                else:
                    found_any = True
                    if _fits(data, keys, whole=False):
                        return data
            start = text.find(opener, start + 1, limit)
    if cut_at is not None:
        raise TruncatedJSON("the JSON answer is cut off (it opens and never closes)")
    if found_any and keys is not None:
        raise ValueError(f"the JSON answer has none of the expected fields ({', '.join(sorted(keys))})")
    raise ValueError("no JSON found in model output")


def _image_part(data: bytes) -> dict:
    mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def to_openai_messages(messages: list[ChatMessage]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        if m.images:
            parts: list[dict] = [{"type": "text", "text": m.content}]
            parts.extend(_image_part(img) for img in m.images)
            out.append({"role": m.role, "content": parts})
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _with_system_suffix(messages: list[dict], suffix: str) -> list[dict]:
    """`suffix` appended to the last system message (the schema instruction, when there is one); without a system
    message, one is put first."""
    for m in reversed(messages):
        if m.get("role") != "system":
            continue
        content = m.get("content")
        if isinstance(content, list):
            m["content"] = [*content, {"type": "text", "text": suffix}]
        else:
            m["content"] = f"{content or ''}\n{suffix}".lstrip("\n")
        return messages
    return [{"role": "system", "content": suffix}, *messages]


def _body_error(obj: Any) -> Optional[_BodyError]:
    err = getattr(obj, "error", None)
    if err is None:
        err = (getattr(obj, "model_extra", None) or {}).get("error")
    if not err:
        return None
    if isinstance(err, dict):
        code = err.get("code")
        message = str(err.get("message") or err)
        meta = err.get("metadata")
    else:
        code = getattr(err, "code", None)
        message = str(getattr(err, "message", None) or err)
        meta = getattr(err, "metadata", None)
    if isinstance(meta, dict):
        # Polza says why (metadata.reason: a refusal of moderation among them), names the host that failed
        # (metadata.provider_name) and quotes the host's own words (metadata.raw)
        if meta.get("reason"):
            message = f"{message} (reason: {' '.join(str(meta['reason']).split())[:160]})"
        raw = meta.get("raw")
        if raw:
            raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            message = f"{message}: {' '.join(raw_text.split())[:240]}"
        if meta.get("provider_name"):
            message = f"{message} (provider: {meta['provider_name']})"
    if isinstance(code, str) and not code.isdigit():
        message = f"{code}: {message}"
        code = _POLZA_CODES.get(code.upper())
    code = code if isinstance(code, int) else (int(code) if isinstance(code, str) and code.isdigit() else None)
    return _BodyError(f"Error code: {code} - {message}" if code else message, code)


# Polza's machine error codes (error.code) → the HTTP status they stand for
_POLZA_CODES = {
    "BAD_REQUEST": 400, "UNAUTHORIZED": 401, "API_KEY_REVOKED": 401, "INSUFFICIENT_BALANCE": 402, "FORBIDDEN": 403,
    "NOT_FOUND": 404, "REQUEST_TIMEOUT": 408, "CONFLICT": 409, "PAYLOAD_TOO_LARGE": 413, "TOO_MANY_REQUESTS": 429,
    "INTERNAL_ERROR": 500, "BAD_GATEWAY": 502, "SERVICE_UNAVAILABLE": 503,
}


def _kept_hold(h: status.LinkHealth, model: str, state: str) -> Optional[LinkUnavailable]:
    """The link stays on a longer hold of another kind than this failure (a parallel call found a 404 or a 402 while
    this request was in flight): the error names that hold, so the warning and the status agree."""
    hit = status.own_hold(h)
    if hit is None or hit[0] == state:
        return None
    return _unavailable(model, *hit)


def _fail(err: ProviderError, usage: Usage) -> ProviderError:
    """Tokens a failed call still spent (answers with invalid JSON) travel with its error, so a chain can bill them."""
    err.usage = usage  # type: ignore[attr-defined]
    return err


def _cost_rub(u: Any, polza: bool = True) -> Optional[float]:
    """What the call cost in rubles: Polza's usage.cost_rub (or its alias usage.cost); None when the host does not say.
    Another endpoint's usage.cost is in its own money (OpenRouter's: dollars), so only cost_rub counts there."""
    if u is None:
        return None
    extra = getattr(u, "model_extra", None) or {}
    for name in ("cost_rub", "cost") if polza else ("cost_rub",):
        value = getattr(u, name, None)
        if value is None and isinstance(extra, dict):
            value = extra.get(name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 120.0,
        max_attempts: int = 3,
        extra_body: Optional[dict] = None,
        json_mode: bool = True,
        headers: Optional[dict] = None,
        requests_per_minute: Optional[int] = None,
        label: Optional[str] = None,
        system_suffix: Optional[str] = None,
        exclude_quantizations: Optional[list] = None,
        name: Optional[str] = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key or ""
        if name:
            self.name = name
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.extra_body = dict(extra_body or {})
        self.json_mode = json_mode
        self.headers = headers or {}
        self.label = label or default_label(model, base_url)
        # text added to the system message of every request of this link: Qwen3's documented soft switch
        # "/no_think" turns thinking off on a host that has no parameter for it (the final's VK inference, if needed)
        self.system_suffix = (system_suffix or "").strip() or None
        # hosts whose weights are quantized this low are left out of Polza's routing («fp4»: see excluded_hosts)
        self.exclude_quantizations = tuple(str(q).strip().lstrip("/") for q in (exclude_quantizations or []) if str(q).strip())
        # no key (its variable is empty): the link is off — a chain skips it silently, it is never an error
        self.off = not self.api_key
        self._client = None
        self._account = f"{base_url}|{self.api_key[-8:]}"
        # holds are per (account, model): Polza's caps are per model, so a capped main model leaves the backup free
        self.health = status.link(f"{self._account}|{model}", model, self.label, explicit=label is not None, host=status.hostname(base_url), off=self.off)
        self._limiter: Optional[_MinuteLimiter] = None
        if requests_per_minute:
            with _GUARD:
                self._limiter = _LIMITERS.setdefault(f"{self._account}|{model}|{requests_per_minute}", _MinuteLimiter(requests_per_minute))

    # lazy client so tests can construct the provider without the SDK doing network setup
    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LinkUnavailable(f"{self.model}: {status.PHRASES['off']}", state="off")
            from openai import OpenAI

            # retries are ours (complete(): attempts, per-minute waits, daily fail-fast); the SDK's own sub-second
            # retries of a 429 would only hit the same cap again
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout_s, default_headers=self.headers or None, max_retries=0)
        return self._client

    hidden_reasoning = False  # set once an answer's completion tokens far exceed its text (thinking left on)

    def _check_hidden_reasoning(self, text: str, usage: Usage) -> None:
        """A host that serves a Qwen model with its thinking on bills the reasoning as completion tokens and returns
        only the answer (or nothing): warn once, so the config gets its switch (Polza: extra_body reasoning.effort
        none; VK: chat_template_kwargs enable_thinking false or system_suffix "/no_think"). About 3 characters of
        Russian or JSON per token."""
        out = int(getattr(usage, "completion_tokens", 0) or 0)
        est = max(1.0, len(text or "") / 3.0)
        if out >= 300 and out > 3 * est and not self.hidden_reasoning:
            self.hidden_reasoning = True
            log.warning(
                "%s: %d completion tokens for an answer of about %d — the host seems to run the model with thinking on; "
                "turn it off in the model config (extra_body.reasoning.effort: none on Polza)",
                self.model, out, int(est),
            )

    def _body(self, deadline: Optional[float] = None) -> dict:
        """The link's extra_body with the hosts to leave out of Polza's routing (provider.ignore)."""
        body = dict(self.extra_body)
        hosts = excluded_hosts(self.model, self.exclude_quantizations, deadline) if self.exclude_quantizations else []
        if hosts:
            routing = dict(body.get("provider") or {})
            ignore = list(routing.get("ignore") or [])
            routing["ignore"] = ignore + [h for h in hosts if h not in ignore]
            body["provider"] = routing
        return body

    def _create(self, client: Any, kwargs: dict, capped: bool) -> Any:
        _TLS.sent = getattr(_TLS, "sent", 0) + 1  # every request sent, answered or not (requests_sent)
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            err = classify_error(e, self.model, self.api_key, polza=self.name == "polza")
            if capped and isinstance(err, TransientError) and err.timeout and _status_of(e) is None:
                # our own client timeout, cut to the generation's budget: the request ran out of the budget, not of its
                # own timeout — not the host's fault (a 408 the host sent is the host's, and is retried)
                raise BudgetSpent(f"{self.model}: time budget of the generation is spent (the request did not finish in it)") from e
            raise err from e

    def _call(
        self, messages: list[dict], temperature: float, max_tokens: int, want_json: bool, deadline: Optional[float] = None, nonblocking: bool = False
    ) -> tuple[str, Usage, Optional[str]]:
        """(answer text, usage, finish_reason): "length" means the answer hit max_tokens and is cut off."""
        client = self._get_client()
        kwargs: dict[str, Any] = dict(model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        body = self._body(deadline)
        if body:
            kwargs["extra_body"] = body
        if want_json and self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._limiter is not None:
            if nonblocking:
                # inside a chain nobody waits for a slot: the next link answers now
                wait = self._limiter.try_acquire()
                if wait > 0:
                    raise LinkUnavailable(
                        f"{self.model}: {status.PHRASES['rate']} of the account ({self._limiter.rpm}/min), next slot in {wait:.0f} s", state="rate", hold_s=wait
                    )
            else:
                self._limiter.wait(deadline)
        capped = False
        if deadline is not None:
            # a request never outlives the generation's budget (the limiter may have waited)
            left = deadline - time.monotonic()
            if left < _MIN_REQUEST_S:
                raise BudgetSpent(f"{self.model}: time budget of the generation is spent")
            capped = left < self.timeout_s
            kwargs["timeout"] = min(self.timeout_s, left)
        try:
            resp = self._create(client, kwargs, capped)
        except BudgetSpent:
            raise
        except ProviderError as err:
            # a host may reject response_format: one more try without it (only for a 400, not for a 402/429/5xx or a
            # moderation 403); then the same for the link's extra_body (a switch the host does not know), for the run
            if type(err) is not ProviderError or getattr(err, "status_code", None) != 400:
                raise
            resp = None
            if want_json and self.json_mode and "response_format" in kwargs:
                log.warning("json_mode rejected by provider (%s); retrying without it", err)
                kwargs.pop("response_format")
                try:
                    resp = self._create(client, kwargs, capped)
                except ProviderError as err2:
                    if type(err2) is not ProviderError or getattr(err2, "status_code", None) != 400 or "extra_body" not in kwargs:
                        raise
                    err = err2
            if resp is None:
                # Polza documents `reasoning` and `provider` (a host that lacks a parameter drops it without an error):
                # its 400 is about the request itself — dropping them would only turn the model's thinking back on
                if "extra_body" not in kwargs or self.name == "polza":
                    raise
                kept = {k: v for k, v in kwargs["extra_body"].items() if k == "provider"}
                log.warning("%s: the host rejected the link's extra_body %s (%s); retrying without it", self.model, sorted(set(kwargs["extra_body"]) - set(kept)), str(err)[:200])
                if kept:
                    kwargs["extra_body"] = kept
                else:
                    kwargs.pop("extra_body")
                resp = self._create(client, kwargs, capped)
                # the retry without them worked: they stay off for the rest of the run
                self.extra_body = {k: v for k, v in self.extra_body.items() if k == "provider"}
        choices = getattr(resp, "choices", None)
        if not choices:
            raise classify_error(_body_error(resp) or _BodyError("empty answer: no choices", None), self.model, self.api_key, polza=self.name == "polza")
        choice = choices[0]
        if getattr(choice, "finish_reason", None) == "error":
            raise classify_error(_body_error(choice) or _BodyError("the host reported an error mid-answer", None), self.model, self.api_key, polza=self.name == "polza")
        text = (getattr(choice, "message", None) and choice.message.content) or ""
        # a host that cannot switch a Qwen3 model's thinking off returns it inline: the answer is what follows
        text = _THINK_RE.sub("", text, count=1)
        u = getattr(resp, "usage", None)
        usage = Usage(getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0, _cost_rub(u, polza=self.name == "polza"))
        return text, usage, getattr(choice, "finish_reason", None)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        deadline: Optional[float] = None,
        fail_fast: bool = False,
        in_chain: bool = False,
    ) -> CompletionResult:
        """Alone (`in_chain` False — e.g. the final's VK inference) the provider behaves as before the fallback
        chain: up to `max_attempts` tries with backoff; a 429 of the model's hosts gets one short pause and one more
        try, two in a row skip the model for 2 minutes; per-minute caps are waited out; a 402 / 401 / 403 / 404 is
        reported after the attempts, then skipped for at most a minute; a 400 / 413 / refusal of moderation is
        reported at once (the same request would get the same answer).

        `in_chain`: a link of a fallback chain. A link on hold is skipped without a request, a 402 / 401 / 403 / 404
        / spent quota fails at once with its hold, and nobody waits for a per-minute slot. `fail_fast` (every link but
        the last): a 429 of the hosts, a 5xx or any other error also fails at once, so the next link answers; the last
        link keeps the short pause and the backoff."""
        in_chain = in_chain or fail_fast
        h = self.health
        if self.off:
            raise LinkUnavailable(f"{self.model}: {status.PHRASES['off']}", state="off")
        oai_messages = to_openai_messages(messages)
        if schema is not None:
            schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            oai_messages.append(
                {"role": "system", "content": "Respond with a single JSON object only, no prose, matching this JSON schema:\n" + schema_json}
            )
        if self.system_suffix:
            oai_messages = _with_system_suffix(oai_messages, self.system_suffix)
        call_kw = {"nonblocking": True} if in_chain else {}  # a chain link never waits for a per-minute slot
        keys = schema_keys(schema) if schema is not None else None
        base_messages = list(oai_messages)
        cut_retried = False  # a cut-off answer gets one more request, asked shorter with more room (not an attempt)
        total = Usage()
        last_err: Optional[Exception] = None
        attempt = 0
        rate_waits = 0
        while attempt < self.max_attempts:
            attempt += 1
            if deadline is not None and deadline - time.monotonic() < _MIN_REQUEST_S:
                raise _fail(BudgetSpent(f"{self.model}: time budget of the generation is spent ({last_err or 'no answer yet'})"), total)
            # alone, a per-minute cap is waited out below, never skipped
            hit = status.blocked(h) if in_chain else status.blocked(h, ignore=("rate",))
            if hit is not None:
                raise _fail(_unavailable(self.model, *hit), total)
            started = time.monotonic()
            try:
                got = self._call(oai_messages, temperature, max_tokens, want_json=schema is not None, deadline=deadline, **call_kw)
                # (text, usage, finish_reason); a stand-in without the finish reason (tests) is read as before
                text, usage, finish = got[0], got[1], (got[2] if len(got) > 2 else None)
            except BudgetSpent as e:
                raise _fail(e, total)  # the budget ran out, the link did nothing wrong: nothing is recorded
            except RateLimited as e:
                last_err = e
                if e.daily:
                    # Polza's daily cap of this model is spent: no request to it until midnight by Moscow time (the
                    # other model of the chain has a cap of its own)
                    hold = _quota_hold(e)
                    msg = f"{self.model}: {status.PHRASES['quota']} of the account is spent, skipped for {hold:.0f} s ({e})"
                    status.fail(h, "quota", msg, hold_s=hold)
                    log.warning("%s: daily request quota spent, skipped until it resets (%s)", self.model, e)
                    raise _fail(LinkUnavailable(msg, "quota", hold), total) from e
                if e.upstream:
                    congested = f"{self.model}: {status.PHRASES['congested']} ({e})"
                    # a short pause and one more try — waiting it out spent two minutes of every deck and got nothing
                    wait = min(max(e.retry_after or 5.0, 1.0), 8.0)
                    no_room = deadline is not None and deadline - time.monotonic() < wait + _MIN_REQUEST_S
                    if no_room and not in_chain:
                        # alone, as before the chain: the budget is checked before the 429 is counted, so a 429 that
                        # arrives when the generation's time is up does not count towards the next generation's hold
                        status.fail(h, "congested", congested)
                        raise _fail(BudgetSpent(f"{self.model}: time budget of the generation is spent, no room to wait out a 429 ({e})"), total) from e
                    _, hold = status.fail(h, "congested", congested, counter="strikes", threshold=2, hold_s=_CONGESTION_S, started=started)
                    if hold or fail_fast:
                        kept = _kept_hold(h, self.model, "congested")
                        if kept is not None:
                            raise _fail(kept, total) from e
                        # two in a row: congested for a while. A chain link that is not the last hands over at once
                        if hold:
                            log.warning("%s: host congested upstream, skipped for %.0f s", self.model, hold)
                        what = f"{status.PHRASES['congested']}, skipped for {hold:.0f} s" if hold else status.PHRASES["congested"]
                        raise _fail(LinkUnavailable(f"{self.model}: {what} ({e})", "congested", hold), total) from e
                    if no_room:
                        raise _fail(BudgetSpent(f"{self.model}: time budget of the generation is spent, no room to wait out a 429 ({e})"), total) from e
                    log.info("host busy upstream, one more try in %.0f s: %s", wait, str(e)[:160])
                    time.sleep(wait)
                    continue
                # a per-minute cap of the account
                wait = min(max(e.retry_after or 20.0, 1.0), 65.0)
                msg = f"{self.model}: {status.PHRASES['rate']} of the account, retry in {wait:.0f} s ({e})"
                if in_chain:
                    # the model is skipped till its minute window ends; the other model of the chain answers meanwhile
                    status.fail(h, "rate", msg, hold_s=wait)
                    raise _fail(LinkUnavailable(msg, "rate", wait), total) from e
                status.fail(h, "rate", msg)
                if deadline is not None and deadline - time.monotonic() < wait + _MIN_REQUEST_S:
                    spent = BudgetSpent(f"{self.model}: time budget of the generation is spent, no room to wait out a 429 ({e})")
                    spent.retry_in = wait  # type: ignore[attr-defined]  # a caller with a longer budget may ask again then
                    raise _fail(spent, total) from e
                if rate_waits < 6:
                    # wait the window out, the attempt does not count
                    rate_waits += 1
                    attempt -= 1
                    log.info("rate limited, waiting %.0f s: %s", wait, str(e)[:160])
                    time.sleep(wait)
                continue
            except LinkUnavailable as e:
                last_err = e
                if in_chain:
                    # 402 / 404 / 401 / 403 / no free slot: retrying now is pointless, the next link answers
                    status.fail(h, e.state, str(e), hold_s=e.hold_s)
                    log.warning("%s unavailable: %s", self.model, str(e)[:200])
                    raise _fail(_kept_hold(h, self.model, e.state) or e, total)
                # alone: the short hold comes after the last attempt. Polza says a 402 (not its reserve), 401, 403 and
                # 404 are not asked again — the same request gets the same answer; another endpoint (the final's VK
                # inference) is tried again with backoff as before the chain
                status.fail(h, e.state, str(e))
                if attempt >= self.max_attempts or self.name == "polza":
                    break
                log.warning("provider call failed (attempt %d/%d): %s", attempt, self.max_attempts, e)
                time.sleep(min(2**attempt, 8))
                continue
            except TransientError as e:
                last_err = e
                reserve = bool(getattr(e, "reserve", False))
                retry_after = float(getattr(e, "retry_after", None) or 0.0)
                if in_chain:
                    if reserve:
                        # the balance is held by the requests in flight — the whole account's, not this model's
                        # trouble: no hold; the other link or the second pass asks again in a few seconds
                        status.fail(h, e.state, str(e))
                        if fail_fast:
                            raise _fail(e, total)
                    else:
                        # a timed-out link would eat the next call's budget too: a link that is not the last is
                        # skipped after one timeout, otherwise after two failures in a row; a 503 with a long
                        # Retry-After is held for exactly that long
                        threshold = 1 if (e.timeout and fail_fast) or retry_after > 15 else 2
                        hold_s = max(_TRANSIENT_S, retry_after) if retry_after > 15 else _TRANSIENT_S
                        _, hold = status.fail(h, e.state, str(e), counter="transient", threshold=threshold, hold_s=hold_s, started=started)
                        if fail_fast or hold:
                            raise _fail(_kept_hold(h, self.model, e.state) or e, total)
                else:
                    status.fail(h, e.state, str(e))  # alone: no hold, the next call tries again
                if attempt >= self.max_attempts:
                    break
                # a 503 «no hosts for the model» is asked again not before its Retry-After; no pause runs past the
                # generation's budget (the step takes its deterministic path instead)
                wait = max(2.0**attempt, retry_after)
                if wait > 15.0 or (deadline is not None and deadline - time.monotonic() < wait + _MIN_REQUEST_S):
                    break
                log.warning("provider call failed (attempt %d/%d): %s", attempt, self.max_attempts, e)
                time.sleep(wait)
                continue
            except ProviderError as e:
                last_err = e
                status.fail(h, "error", str(e))
                if fail_fast or getattr(e, "no_retry", False):
                    # a 400 / 413 / refusal of moderation: the same request gets the same answer — a chain asks its
                    # next link, a single provider reports it at once
                    raise _fail(e, total)
                if attempt >= self.max_attempts:
                    break
                log.warning("provider call failed (attempt %d/%d): %s", attempt, self.max_attempts, e)
                time.sleep(min(2**attempt, 8))
                continue
            total = total.add(usage)
            status.record_ok(h)  # the host answered: not congested, not out of credits
            self._check_hidden_reasoning(text, usage)
            if schema is None:
                return CompletionResult(text=text, parsed=None, usage=total, model=self.model, attempts=attempt, label=self.label)
            try:
                data = extract_json(text, keys)
                parsed = schema.model_validate(data)
                return CompletionResult(text=text, parsed=parsed, usage=total, model=self.model, attempts=attempt, raw_json=data, label=self.label)
            except (ValueError, ValidationError) as e:
                last_err = e
                if finish == "length" or isinstance(e, TruncatedJSON):
                    # the answer ran out of max_tokens: asked again from the start, shorter, with more room — never
                    # repaired from its cut-off text, and not a reason to leave the JSON mode (the host did no wrong)
                    last_err = TruncatedJSON(f"the answer was cut off at {max_tokens} tokens (finish_reason={finish}): {str(e)[:200]}")
                    log.warning("%s: JSON answer cut off at %d tokens (attempt %d/%d)", self.model, max_tokens, attempt, self.max_attempts)
                    if cut_retried:
                        # cut again with twice the room: the next attempts at that room are cut too (a model thinking
                        # aloud, a host that ignores the length) — each would cost the most output of any request
                        raise _fail(ProviderError(f"{self.model}: no valid completion, the answer was cut off twice: {last_err}"), total)
                    cut_retried = True
                    attempt -= 1
                    max_tokens = max(max_tokens, min(max_tokens * 2, _CUT_MAX_TOKENS))
                    oai_messages = base_messages + [{"role": "user", "content": _CUT_RETRY}]
                    continue
                log.warning("invalid JSON from model (attempt %d/%d): %s", attempt, self.max_attempts, str(e)[:300])
                if self.json_mode:
                    # some hosts garble guided JSON (': ' glued to values, empty keys) yet answer clean JSON without
                    # it; the schema is in the prompt, so plain mode for the rest of the run
                    self.json_mode = False
                    log.warning("%s: response_format=json_object gave invalid JSON, plain mode from now on", self.model)
                oai_messages.append({"role": "assistant", "content": text[:4000]})
                oai_messages.append(
                    {"role": "user", "content": f"Your previous answer was not valid. Error: {str(e)[:800]}. Return only the corrected JSON object."}
                )
        if isinstance(last_err, LinkUnavailable) and not in_chain and last_err.hold_s and last_err.state != "rate":
            # alone: a 402 / 401 / 403 / 404 on every attempt — the next calls of this minute skip the model. A
            # per-minute state opens no hold: alone, those are waited out (the pre-call check ignores them), so a hold
            # would only show a pause that does not happen
            status.fail(h, last_err.state, str(last_err), hold_s=min(last_err.hold_s, _SINGLE_HOLD_S))
        if in_chain and isinstance(last_err, (TransientError, RateLimited)) and not getattr(last_err, "daily", False):
            # the last link ran out of attempts on a passing trouble (congestion, a 5xx, the balance held by the
            # requests in flight): said as such, so the chain may make its second pass
            raise _fail(last_err, total)
        raise _fail(ProviderError(f"{self.model}: no valid completion after {attempt} attempt{'' if attempt == 1 else 's'}: {last_err}"), total)
