"""Model providers: OpenAI-compatible endpoints (OpenRouter, VK inference, vLLM) and a mock for tests."""

from verstka.providers.base import ChatMessage, CompletionResult, Provider, ProviderError, Usage
from verstka.providers.registry import ProviderRegistry

__all__ = ["ChatMessage", "CompletionResult", "Provider", "ProviderError", "Usage", "ProviderRegistry"]
