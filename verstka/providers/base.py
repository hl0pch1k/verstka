"""Provider protocol and message types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a (valid) completion."""


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str
    images: list[bytes] = field(default_factory=list)  # JPEG/PNG bytes attached to a user message


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Optional[float] = None

    def add(self, other: "Usage") -> "Usage":
        cost = None
        if self.cost_usd is not None or other.cost_usd is not None:
            cost = (self.cost_usd or 0.0) + (other.cost_usd or 0.0)
        return Usage(self.prompt_tokens + other.prompt_tokens, self.completion_tokens + other.completion_tokens, cost)


@dataclass
class CompletionResult:
    text: str
    parsed: Any  # BaseModel instance when schema was given, else None
    usage: Usage
    model: str
    attempts: int = 1
    raw_json: Any = None


@runtime_checkable
class Provider(Protocol):
    name: str
    model: str

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        deadline: Optional[float] = None,
    ) -> CompletionResult: ...
