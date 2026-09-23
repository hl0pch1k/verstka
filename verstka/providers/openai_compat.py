"""OpenAI-compatible chat provider (OpenRouter, VK inference, vLLM, Ollama...)."""

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

from verstka.providers.base import ChatMessage, CompletionResult, ProviderError, Usage

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class RateLimited(ProviderError):
    """429 from the provider: `daily` when the day's quota is spent (retrying today is pointless)."""

    def __init__(self, message: str, retry_after: Optional[float] = None, daily: bool = False) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.daily = daily


class _MinuteLimiter:
    """At most `rpm` requests in any 60 s window, shared by every provider on the same account (llm and vlm roles
    both count against e.g. OpenRouter's 20 requests/min for free models)."""

    def __init__(self, rpm: int) -> None:
        self.rpm = max(1, rpm)
        self.lock = threading.Lock()
        self.stamps: deque = deque()

    def wait(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.stamps and now - self.stamps[0] >= 60.0:
                    self.stamps.popleft()
                if len(self.stamps) < self.rpm:
                    self.stamps.append(now)
                    return
                delay = 60.0 - (now - self.stamps[0]) + 0.05
            time.sleep(delay)


_LIMITERS: dict[str, _MinuteLimiter] = {}
_EXHAUSTED: set[str] = set()  # accounts whose daily quota is spent: every later call fails fast → deterministic fallbacks
_GUARD = threading.Lock()


def _rate_limit_info(e: Exception) -> Optional[RateLimited]:
    status = getattr(e, "status_code", None)
    text = str(e)
    low = text.lower()
    if status != 429 and "429" not in text and "rate limit" not in low and "rate-limit" not in low:
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
    daily = "per-day" in low or "per day" in low or "free-models-per-day" in low or (retry_after is not None and retry_after > 300)
    return RateLimited(text[:300], retry_after=retry_after, daily=daily)


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
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.price_in = price_in_per_m
        self.price_out = price_out_per_m
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.extra_body = extra_body or {}
        self.json_mode = json_mode
        self.headers = headers or {}
        self._client = None
        self._account = f"{base_url}|{api_key[-8:]}"
        self._limiter: Optional[_MinuteLimiter] = None
        if requests_per_minute:
            with _GUARD:
                self._limiter = _LIMITERS.setdefault(f"{self._account}|{requests_per_minute}", _MinuteLimiter(requests_per_minute))

    # lazy client so tests can construct the provider without the SDK doing network setup
    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise ProviderError(f"no API key configured for model {self.model} at {self.base_url}")
            from openai import OpenAI

            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout_s, default_headers=self.headers or None)
        return self._client

    def _cost(self, usage: Usage) -> Optional[float]:
        if self.price_in is None or self.price_out is None:
            return None
        return usage.prompt_tokens / 1e6 * self.price_in + usage.completion_tokens / 1e6 * self.price_out

    def _call(self, messages: list[dict], temperature: float, max_tokens: int, want_json: bool) -> tuple[str, Usage]:
        client = self._get_client()
        kwargs: dict[str, Any] = dict(model=self.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        if want_json and self.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self._account in _EXHAUSTED:
            raise RateLimited(f"{self.model}: daily request quota of the provider is spent", daily=True)
        if self._limiter is not None:
            self._limiter.wait()
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:  # provider may reject response_format; retry without it once
            rl = _rate_limit_info(e)
            if rl is not None:
                raise rl from e
            if want_json and self.json_mode and "response_format" in kwargs:
                log.warning("json_mode rejected by provider (%s); retrying without it", e)
                kwargs.pop("response_format")
                try:
                    resp = client.chat.completions.create(**kwargs)
                except Exception as e2:
                    raise ProviderError(str(e2)) from e2
            else:
                raise ProviderError(str(e)) from e
        choice = resp.choices[0]
        text = choice.message.content or ""
        u = resp.usage
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
    ) -> CompletionResult:
        oai_messages = to_openai_messages(messages)
        if schema is not None:
            schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            oai_messages.append(
                {"role": "system", "content": "Respond with a single JSON object only, no prose, matching this JSON schema:\n" + schema_json}
            )
        total = Usage()
        last_err: Optional[Exception] = None
        attempt = 0
        rate_waits = 0
        while attempt < self.max_attempts:
            attempt += 1
            try:
                text, usage = self._call(oai_messages, temperature, max_tokens, want_json=schema is not None)
            except RateLimited as e:
                if e.daily:
                    _EXHAUSTED.add(self._account)
                    log.warning("provider daily quota spent: deterministic fallbacks from now on (%s)", e)
                    raise
                last_err = e
                if rate_waits < 6:
                    # a per-minute cap: wait the window out, the attempt does not count
                    rate_waits += 1
                    attempt -= 1
                    wait = min(max(e.retry_after or 20.0, 1.0), 65.0)
                    log.info("rate limited, waiting %.0f s", wait)
                    time.sleep(wait)
                continue
            except ProviderError as e:
                last_err = e
                log.warning("provider call failed (attempt %d/%d): %s", attempt, self.max_attempts, e)
                time.sleep(min(2**attempt, 8))
                continue
            total = total.add(usage)
            if schema is None:
                return CompletionResult(text=text, parsed=None, usage=total, model=self.model, attempts=attempt)
            try:
                data = extract_json(text)
                parsed = schema.model_validate(data)
                return CompletionResult(text=text, parsed=parsed, usage=total, model=self.model, attempts=attempt, raw_json=data)
            except (ValueError, ValidationError) as e:
                last_err = e
                log.warning("invalid JSON from model (attempt %d/%d): %s", attempt, self.max_attempts, str(e)[:300])
                oai_messages.append({"role": "assistant", "content": text[:4000]})
                oai_messages.append(
                    {"role": "user", "content": f"Your previous answer was not valid. Error: {str(e)[:800]}. Return only the corrected JSON object."}
                )
        raise ProviderError(f"{self.model}: no valid completion after {self.max_attempts} attempts: {last_err}")
