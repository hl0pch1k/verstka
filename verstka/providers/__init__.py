"""Model providers: OpenAI-compatible endpoints (OpenRouter, VK inference, vLLM, Ollama), fallback chains of them and
a mock for tests. `verstka.providers.status.snapshot()` tells the UI which model answers right now."""

from verstka.providers.base import ChatMessage, CompletionResult, Provider, ProviderError, Usage
from verstka.providers.chain import ChainProvider
from verstka.providers.registry import ProviderRegistry

__all__ = ["ChatMessage", "ChainProvider", "CompletionResult", "Provider", "ProviderError", "Usage", "ProviderRegistry"]
