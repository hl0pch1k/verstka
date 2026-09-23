"""Deterministic mock provider for tests and offline runs."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional, Union

from pydantic import BaseModel, ValidationError

from verstka.providers.base import ChatMessage, CompletionResult, ProviderError, Usage
from verstka.providers.openai_compat import extract_json

ResponseSpec = Union[str, dict, list, Callable[[list[ChatMessage]], Union[str, dict, list]]]


class MockProvider:
    """Returns canned responses.

    `responses` maps a substring (searched in messages, last user message first) to a response.
    The special key "*" is the default. A callable receives the messages and returns the response.
    """

    name = "mock"

    def __init__(self, responses: Optional[Union[dict[str, ResponseSpec], Callable]] = None, model: str = "mock-model") -> None:
        self.responses = responses or {}
        self.model = model
        self.calls: list[dict[str, Any]] = []

    def _pick(self, messages: list[ChatMessage]) -> Union[str, dict, list]:
        if callable(self.responses):
            return self.responses(messages)
        texts = [m.content for m in reversed(messages)]
        for key, value in self.responses.items():
            if key == "*":
                continue
            if any(key in t for t in texts):
                return value(messages) if callable(value) else value
        if "*" in self.responses:
            value = self.responses["*"]
            return value(messages) if callable(value) else value
        raise ProviderError("mock provider: no response matched the request")

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        deadline: Optional[float] = None,
    ) -> CompletionResult:
        if deadline is not None and time.monotonic() >= deadline:
            raise ProviderError("mock provider: time budget of the generation is spent")
        self.calls.append({"messages": messages, "schema": schema.__name__ if schema else None, "n_images": sum(len(m.images) for m in messages)})
        value = self._pick(messages)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        parsed = None
        data = None
        if schema is not None:
            try:
                data = extract_json(text)
                parsed = schema.model_validate(data)
            except (ValueError, ValidationError) as e:
                raise ProviderError(f"mock response does not match schema {schema.__name__}: {e}") from e
        return CompletionResult(text=text, parsed=parsed, usage=Usage(0, 0, 0.0), model=self.model, attempts=1, raw_json=data)
