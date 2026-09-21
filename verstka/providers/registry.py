"""Provider registry: maps roles (llm, vlm, t2i) to configured backends."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from verstka.providers.base import Provider, ProviderError
from verstka.providers.mock import MockProvider
from verstka.providers.openai_compat import OpenAICompatProvider

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


@dataclass
class ProviderLimits:
    max_concurrency: int = 6
    timeout_s: float = 120.0
    max_attempts: int = 3


@dataclass
class ProviderRegistry:
    roles: dict[str, Provider] = field(default_factory=dict)
    limits: ProviderLimits = field(default_factory=ProviderLimits)
    config: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict) -> "ProviderRegistry":
        cfg = expand_env(cfg)
        limits_cfg = cfg.get("limits", {}) or {}
        limits = ProviderLimits(
            max_concurrency=int(limits_cfg.get("max_concurrency", 6)),
            timeout_s=float(limits_cfg.get("timeout_s", 120)),
            max_attempts=int(limits_cfg.get("max_attempts", 3)),
        )
        roles: dict[str, Provider] = {}
        for role, spec in (cfg.get("roles") or {}).items():
            roles[role] = build_provider(spec, limits)
        return cls(roles=roles, limits=limits, config=cfg)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "ProviderRegistry":
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cls.from_config(cfg)

    @classmethod
    def mock(cls, responses: Optional[dict] = None) -> "ProviderRegistry":
        p = MockProvider(responses or {})
        return cls(roles={"llm": p, "vlm": p, "t2i": p})

    def get(self, role: str) -> Provider:
        if role not in self.roles:
            raise ProviderError(f"no provider configured for role {role!r}; roles: {sorted(self.roles)}")
        return self.roles[role]

    def has(self, role: str) -> bool:
        return role in self.roles

    def describe(self) -> dict[str, dict]:
        return {role: {"backend": p.name, "model": p.model} for role, p in self.roles.items()}


def build_provider(spec: dict, limits: ProviderLimits) -> Provider:
    backend = (spec.get("backend") or "openai_compat").lower()
    if backend == "mock":
        return MockProvider(spec.get("responses") or {}, model=spec.get("model", "mock-model"))
    if backend in ("openai_compat", "openrouter", "vk", "vllm", "ollama"):
        base_url = spec.get("base_url") or "https://openrouter.ai/api/v1"
        headers = {}
        if "openrouter.ai" in base_url:
            headers = {"HTTP-Referer": "https://github.com/verstka", "X-Title": "Verstka"}
        return OpenAICompatProvider(
            model=spec["model"],
            base_url=base_url,
            api_key=spec.get("api_key") or "",
            price_in_per_m=spec.get("price_in_per_m"),
            price_out_per_m=spec.get("price_out_per_m"),
            timeout_s=float(spec.get("timeout_s", limits.timeout_s)),
            max_attempts=int(spec.get("max_attempts", limits.max_attempts)),
            extra_body=spec.get("extra_body"),
            json_mode=bool(spec.get("json_mode", True)),
            headers=headers,
        )
    raise ProviderError(f"unknown provider backend {backend!r}")
