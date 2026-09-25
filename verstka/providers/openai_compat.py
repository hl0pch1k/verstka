"""OpenAI-compatible chat provider (OpenRouter, Groq, Cloud.ru, VK inference, vLLM, Ollama...)."""

from __future__ import annotations

import base64
import json
import logging
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
# OpenRouter answers 403 «Key limit exceeded» when the key's own spending limit is reached: that is money, not a bad
# key. Only the key / spending / credit wording counts: a 403 «Rate limit exceeded» is not an empty account
_KEY_LIMIT_RE = re.compile(r"\bkey limit|spending limit|credits? limit|insufficient (?:credits|balance|funds)", re.I)
# Groq answers 413 «Request too large for model … on tokens per minute (TPM)» when one request is bigger than the
# plan's per-minute token budget: a per-minute cap of the host, not a broken request
_TPM_RE = re.compile(r"per[- ]minute|\btpm\b", re.I)
# the account's own caps, named in the text (OpenRouter «free-models-per-min» / «-per-day», Groq «per minute (RPM)»)
_ACCOUNT_CAP_RE = re.compile(r"per[- ]minute|per[- ]day|free-models-per", re.I)


class RateLimited(ProviderError):
    """429 from the provider: `daily` when the day's quota is spent (retrying today is pointless)."""

    def __init__(self, message: str, retry_after: Optional[float] = None, daily: bool = False, upstream: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.daily = daily
        # congestion on the model host («temporarily rate-limited upstream»), not a cap of our account
        low = message.lower()
        self.upstream = upstream or "upstream" in low or "temporarily rate-limited" in low


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
    """An error the host returned inside an HTTP 200 body (OpenRouter does so when the upstream fails mid-way)."""

    def __init__(self, message: str, status_code: Optional[int]) -> None:
        super().__init__(message)
        self.status_code = status_code


class _MinuteLimiter:
    """At most `rpm` requests in any 60 s window, shared by every provider on the same account (llm and vlm roles
    both count against e.g. OpenRouter's 20 requests/min for free models)."""

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
_LIMITERS: dict[str, _MinuteLimiter] = {}
_GUARD = threading.Lock()
# how long a link is skipped (status.py keeps the holds per account + model)
_CONGESTION_S = 120.0  # two upstream 429s in a row — a single provider as before the chain, and a chain link
# inside a fallback chain only:
_NO_CREDITS_S = 600.0  # 402: retried after 10 minutes, so a top-up of the account is picked up soon
_GONE_S = 1800.0  # 404 / 401 / 403: no such model, no endpoint, rejected key
_TRANSIENT_S = 60.0  # two 5xx / timeouts / connection errors in a row, or a timeout of a link that is not the last
_TOO_LARGE_S = 30.0  # 413 «request too large … tokens per minute»: a short "rate" hold (the next steps are smaller)
# a single provider (the final's VK inference): a 402 / 401 / 403 / 404 is reported after its attempts, then at most
# this short hold, so a hiccup of the only model never costs more than a minute
_SINGLE_HOLD_S = 60.0


def _status_of(e: Exception) -> Optional[int]:
    code = getattr(e, "status_code", None)
    if isinstance(code, int):
        return code
    m = _CODE_RE.search(str(e))
    return int(m.group(1)) if m else None


def _rate_limit_info(e: Exception, text: Optional[str] = None) -> Optional[RateLimited]:
    status_code = getattr(e, "status_code", None)
    text = str(e) if text is None else text
    low = text.lower()
    if status_code != 429 and "429" not in text and "rate limit" not in low and "rate-limit" not in low:
        return None
    retry_after: Optional[float] = None
    headers = getattr(getattr(e, "response", None), "headers", None) or {}
    try:
        if headers.get("retry-after"):
            retry_after = float(headers.get("retry-after"))
        elif headers.get("x-ratelimit-reset"):
            retry_after = max(0.0, float(headers.get("x-ratelimit-reset")) / 1000.0 - time.time())
    except (TypeError, ValueError):
        retry_after = None
    # congestion of the model's host: OpenRouter's «temporarily rate-limited upstream», or any 429 it passes on as
    # «Provider returned error» (the host's own limit) — unless the text names a cap of our account
    upstream = "upstream" in low or "temporarily rate-limited" in low or ("provider returned error" in low and not _ACCOUNT_CAP_RE.search(low))
    # the daily quota is named in the text (OpenRouter «free-models-per-day», Groq «tokens per day (TPD)»); a long
    # reset alone means it only when the host is not congested — a congested host may ask for 10 minutes too
    daily = "per-day" in low or "per day" in low or (not upstream and retry_after is not None and retry_after > 300)
    return RateLimited(text[:300], retry_after=retry_after, daily=daily, upstream=upstream)


def classify_error(e: Exception, model: str, secret: str = "") -> ProviderError:
    """An SDK / HTTP error → the ProviderError subclass that tells the caller (and a fallback chain) what to do.
    The message carries the state's wording (status.PHRASES); `secret` (the link's key) never appears in it."""
    if isinstance(e, ProviderError):
        return e
    code = _status_of(e)
    text = status.mask(" ".join(str(e).split())[:300], secret)
    low = text.lower()
    if code is None or code == 429:
        rl = _rate_limit_info(e, text)
        if rl is not None:
            return rl
    if code == 402 or "insufficient credits" in low or "payment required" in low or "requires more credits" in low:
        return LinkUnavailable(f"{model}: no credits (402) on the account ({text})", state="no_credits", hold_s=_NO_CREDITS_S)
    if code == 403 and _KEY_LIMIT_RE.search(low):
        return LinkUnavailable(f"{model}: no credits (402): the spending limit of the key is reached, HTTP 403 ({text})", state="no_credits", hold_s=_NO_CREDITS_S)
    if code in (401, 403):
        return LinkUnavailable(f"{model}: access refused (401/403): HTTP {code}, check the key ({text})", state="auth", hold_s=_GONE_S)
    if code == 404 or (code in (None, 400) and any(s in low for s in ("no endpoints found", "model not found", "not a valid model", "does not exist"))):
        return LinkUnavailable(f"{model}: model not available (404): no such model or no endpoint serves it ({text})", state="missing", hold_s=_GONE_S)
    if code == 413 and _TPM_RE.search(low):
        return _too_large(model, text)
    kind = type(e).__name__.lower()
    if "timeout" in kind or "timed out" in low or code == 408:
        return TransientError(f"{model}: request timed out, congested upstream", timeout=True)
    if code is not None and (code >= 500 or code == 498):  # 498: Groq's «capacity exceeded, try again later»
        return TransientError(f"{model}: {code} server error, congested upstream ({text})")
    if "connection" in kind or "connection error" in low or isinstance(e, ConnectionError):
        return TransientError(f"{model}: connection error ({text})", state="error")
    return ProviderError(f"{model}: {text}" if code is None or str(code) in text else f"{model}: {code} {text}")


def _too_large(model: str, text: str, held: bool = False) -> LinkUnavailable:
    """Groq's 413 «request too large … tokens per minute». Its short hold opens only inside a chain (alone a per-minute
    state opens none), so only a chain link's error (`held`) says «skipped for 30 s»."""
    hold = f", skipped for {_TOO_LARGE_S:.0f} s" if held else ""
    err = LinkUnavailable(
        f"{model}: {status.PHRASES['rate']} of the host: the request is larger than its tokens-per-minute limit (413){hold} ({text})",
        state="rate",
        hold_s=_TOO_LARGE_S,
    )
    err.too_large = text  # type: ignore[attr-defined]
    return err


def _quota_hold(e: RateLimited) -> float:
    """How long a spent daily quota blocks its pool: the provider's reset time, else the next 00:00 UTC."""
    if e.retry_after is not None and e.retry_after > 60:
        return min(e.retry_after, 86400.0)
    return 86400.0 - (time.time() % 86400.0) + 5.0


def _unavailable(model: str, state: str, reason: str, left: float) -> LinkUnavailable:
    """The link is on hold: skipped without a request."""
    what = status.PHRASES.get(state, "the model did not answer")
    err = LinkUnavailable(f"{model}: {what}, skipped for {left:.0f} s more ({reason})", state=state)
    err.skipped = True  # type: ignore[attr-defined]
    return err


_KNOWN_LABELS = {"qwen3.8-27b": "Qwen3.8-27B", "gemma-4-31b-it": "Gemma 4 31B", "gemma-4-26b-a4b-it": "Gemma 4 26B A4B"}
_HOST_LABELS = (("openrouter.ai", "OpenRouter"), ("groq.com", "Groq"), ("cloud.ru", "Cloud.ru"), ("localhost", "локально"), ("127.0.0.1", "локально"))


def default_label(model: str, base_url: str) -> str:
    """A human name for the UI: «Qwen3.8-27B (OpenRouter)», «Gemma 4 31B (бесплатно)», «Qwen3.5 9B (локально)»."""
    base = model.split("/")[-1]
    free = base.endswith(":free")
    if free:
        base = base[: -len(":free")]
    name = _KNOWN_LABELS.get(base.lower())
    if name is None:
        tokens = [t for t in re.split(r"[-_: ]+", base) if t and t.lower() not in ("it", "instruct", "chat", "latest")]
        tokens = [t.upper() if re.fullmatch(r"a?\d+(\.\d+)?b", t, re.I) else t for t in tokens]
        if tokens:
            tokens[0] = tokens[0][:1].upper() + tokens[0][1:]
        name = " ".join(tokens) or model
    host = (base_url or "").lower()
    suffix = "бесплатно" if free else next((v for k, v in _HOST_LABELS if k in host), "")
    return f"{name} ({suffix})" if suffix else name


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of model output (fenced or inline)."""
    text = text.strip()
    for m in _FENCE_RE.finditer(text):
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # scan for first balanced {...} or [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            in_str = False
            esc = False
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
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(opener, start + 1)
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
        # OpenRouter wraps the host's own error as «Provider returned error»; what it was is in metadata.raw
        # («… is temporarily rate-limited upstream …») and metadata.provider_name
        raw = meta.get("raw")
        if raw:
            raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            message = f"{message}: {' '.join(raw_text.split())[:240]}"
        if meta.get("provider_name"):
            message = f"{message} (provider: {meta['provider_name']})"
    code = code if isinstance(code, int) else (int(code) if isinstance(code, str) and code.isdigit() else None)
    return _BodyError(f"Error code: {code} - {message}" if code else message, code)


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


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        *,
        price_in_per_m: Optional[float] = None,
        price_out_per_m: Optional[float] = None,
        timeout_s: float = 120.0,
        max_attempts: int = 3,
        extra_body: Optional[dict] = None,
        json_mode: bool = True,
        headers: Optional[dict] = None,
        requests_per_minute: Optional[int] = None,
        label: Optional[str] = None,
        max_tokens_cap: Optional[int] = None,
        system_suffix: Optional[str] = None,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key or ""
        self.price_in = price_in_per_m
        self.price_out = price_out_per_m
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.extra_body = extra_body or {}
        self.json_mode = json_mode
        self.headers = headers or {}
        self.label = label or default_label(model, base_url)
        # a host with a small tokens-per-minute budget (Groq's free plan: 8K) rejects a request whose max_tokens
        # alone would spend it: every request of this link asks for at most this many
        self.max_tokens_cap = int(max_tokens_cap) if max_tokens_cap else None
        # text added to the system message of every request of this link: Qwen3's documented soft switch
        # "/no_think" turns thinking off on a host that has no parameter for it (Cloud.ru)
        self.system_suffix = (system_suffix or "").strip() or None
        # no key (its variable is empty): the link is off — a chain skips it silently, it is never an error
        self.off = not self.api_key
        self._client = None
        self._account = f"{base_url}|{self.api_key[-8:]}"
        # holds are per (account, model); the free models' quotas of the account are a pool of their own, so a
        # spent free quota does not block a paid model on the same key
        pool = f"{self._account}|{'free' if model.endswith(':free') else 'paid'}"
        free = model.endswith(":free") or (price_in_per_m == 0 and price_out_per_m == 0)
        self.health = status.link(
            f"{self._account}|{model}", model, self.label, pool, explicit=label is not None, host=status.hostname(base_url), free=free, off=self.off
        )
        self._limiter: Optional[_MinuteLimiter] = None
        if requests_per_minute:
            with _GUARD:
                self._limiter = _LIMITERS.setdefault(f"{self._account}|{requests_per_minute}", _MinuteLimiter(requests_per_minute))

    # lazy client so tests can construct the provider without the SDK doing network setup
    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LinkUnavailable(f"{self.model}: {status.PHRASES['off']}", state="off")
            from openai import OpenAI

            # retries are ours (complete(): attempts, per-minute waits, daily fail-fast); the SDK's own sub-second
            # retries of a 429 only spend the free quota
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout_s, default_headers=self.headers or None, max_retries=0)
        return self._client

    def _cost(self, usage: Usage) -> Optional[float]:
        if self.price_in is None or self.price_out is None:
            return None
        return usage.prompt_tokens / 1e6 * self.price_in + usage.completion_tokens / 1e6 * self.price_out

    def _create(self, client: Any, kwargs: dict, capped: bool) -> Any:
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            err = classify_error(e, self.model, self.api_key)
            if capped and isinstance(err, TransientError) and err.timeout:
                # the request ran out of the generation's budget, not of its own timeout: not the host's fault
                raise BudgetSpent(f"{self.model}: time budget of the generation is spent (the request did not finish in it)") from e
            raise err from e

    def _call(
        self, messages: list[dict], temperature: float, max_tokens: int, want_json: bool, deadline: Optional[float] = None, nonblocking: bool = False
    ) -> tuple[str, Usage]:
        client = self._get_client()
        kwargs: dict[str, Any] = dict(model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
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
            # a host may reject response_format: one more try without it (only for a plain 4xx, not for a 402/429/5xx)
            if type(err) is ProviderError and want_json and self.json_mode and "response_format" in kwargs:
                log.warning("json_mode rejected by provider (%s); retrying without it", err)
                kwargs.pop("response_format")
                resp = self._create(client, kwargs, capped)
            else:
                raise
        choices = getattr(resp, "choices", None)
        if not choices:
            raise classify_error(_body_error(resp) or _BodyError("empty answer: no choices", None), self.model, self.api_key)
        choice = choices[0]
        if getattr(choice, "finish_reason", None) == "error":
            raise classify_error(_body_error(choice) or _BodyError("the host reported an error mid-answer", None), self.model, self.api_key)
        text = (getattr(choice, "message", None) and choice.message.content) or ""
        # a host that cannot switch a Qwen3 model's thinking off returns it inline: the answer is what follows
        text = _THINK_RE.sub("", text, count=1)
        u = getattr(resp, "usage", None)
        usage = Usage(getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)
        usage.cost_usd = self._cost(usage)
        return text, usage

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
        chain: up to `max_attempts` tries with backoff; an upstream 429 gets one short pause and one more try, two in
        a row skip the model for 2 minutes; per-minute caps are waited out; a 402 / 401 / 403 / 404 is reported after
        the attempts, then skipped for at most a minute (a 413 «too large for the tokens per minute» gets its attempts
        on every call, never a hold).

        `in_chain`: a link of a fallback chain. A link on hold is skipped without a request, a 402 / 401 / 403 / 404
        / spent quota fails at once with its hold, and nobody waits for a per-minute slot. `fail_fast` (every link but
        the last): an upstream 429, a 5xx or any other error also fails at once, so the next link answers; the last
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
        if self.max_tokens_cap:
            max_tokens = min(max_tokens, self.max_tokens_cap)
        call_kw = {"nonblocking": True} if in_chain else {}  # a chain link never waits for a per-minute slot
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
                text, usage = self._call(oai_messages, temperature, max_tokens, want_json=schema is not None, deadline=deadline, **call_kw)
            except BudgetSpent as e:
                raise _fail(e, total)  # the budget ran out, the link did nothing wrong: nothing is recorded
            except RateLimited as e:
                last_err = e
                if e.daily:
                    # the day's quota of the pool (e.g. every free model of the key) is spent: no request until it resets
                    hold = _quota_hold(e)
                    msg = f"{self.model}: {status.PHRASES['quota']} of the account is spent, skipped for {hold:.0f} s ({e})"
                    status.block_pool(h.pool, "quota", msg, hold)
                    status.fail(h, "quota", msg)
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
                    # every link of the pool (all free models of the key) is skipped till the window ends; not the paid one
                    status.block_pool(h.pool, "rate", msg, wait)
                    status.fail(h, "rate", msg)
                    raise _fail(LinkUnavailable(msg, "rate", wait), total) from e
                status.fail(h, "rate", msg)
                if deadline is not None and deadline - time.monotonic() < wait + _MIN_REQUEST_S:
                    raise _fail(BudgetSpent(f"{self.model}: time budget of the generation is spent, no room to wait out a 429 ({e})"), total) from e
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
                    if getattr(e, "too_large", None) is not None:
                        e = last_err = _too_large(self.model, e.too_large, held=True)  # the hold opens here: say so
                    status.fail(h, e.state, str(e), hold_s=e.hold_s)
                    log.warning("%s unavailable: %s", self.model, str(e)[:200])
                    raise _fail(_kept_hold(h, self.model, e.state) or e, total)
                # alone: tried again with backoff as before the chain; the short hold comes after the last attempt
                status.fail(h, e.state, str(e))
                if attempt >= self.max_attempts:
                    break
                log.warning("provider call failed (attempt %d/%d): %s", attempt, self.max_attempts, e)
                time.sleep(min(2**attempt, 8))
                continue
            except TransientError as e:
                last_err = e
                if in_chain:
                    # a timed-out link would eat the next call's budget too: a link that is not the last is skipped
                    # after one timeout, otherwise after two failures in a row
                    threshold = 1 if (e.timeout and fail_fast) else 2
                    _, hold = status.fail(h, e.state, str(e), counter="transient", threshold=threshold, hold_s=_TRANSIENT_S, started=started)
                    if fail_fast or hold:
                        raise _fail(_kept_hold(h, self.model, e.state) or e, total)
                else:
                    status.fail(h, e.state, str(e))  # alone: no hold, the next call tries again
                if attempt >= self.max_attempts:
                    break
                log.warning("provider call failed (attempt %d/%d): %s", attempt, self.max_attempts, e)
                time.sleep(min(2**attempt, 8))
                continue
            except ProviderError as e:
                last_err = e
                status.fail(h, "error", str(e))
                if fail_fast:
                    raise _fail(e, total)
                if attempt >= self.max_attempts:
                    break
                log.warning("provider call failed (attempt %d/%d): %s", attempt, self.max_attempts, e)
                time.sleep(min(2**attempt, 8))
                continue
            total = total.add(usage)
            status.record_ok(h)  # the host answered: not congested, not out of credits
            if schema is None:
                return CompletionResult(text=text, parsed=None, usage=total, model=self.model, attempts=attempt, label=self.label)
            try:
                data = extract_json(text)
                parsed = schema.model_validate(data)
                return CompletionResult(text=text, parsed=parsed, usage=total, model=self.model, attempts=attempt, raw_json=data, label=self.label)
            except (ValueError, ValidationError) as e:
                last_err = e
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
            # per-minute state (Groq's 413 «request too large … tokens per minute») opens no hold: alone, those are
            # never skipped (the pre-call check ignores them), so a hold would only show a pause that does not happen
            status.fail(h, last_err.state, str(last_err), hold_s=min(last_err.hold_s, _SINGLE_HOLD_S))
        raise _fail(ProviderError(f"{self.model}: no valid completion after {self.max_attempts} attempts: {last_err}"), total)
