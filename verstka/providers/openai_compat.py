"""OpenAI-compatible chat provider (OpenRouter, VK inference, vLLM, Ollama...)."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from verstka.providers.base import ChatMessage, CompletionResult, ProviderError, Usage

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


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
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:  # provider may reject response_format; retry without it once
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
        for attempt in range(1, self.max_attempts + 1):
            try:
                text, usage = self._call(oai_messages, temperature, max_tokens, want_json=schema is not None)
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
