"""Provider registry: maps roles (llm, vlm, t2i) to configured backends."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from verstka.providers.base import Provider, ProviderError
from verstka.providers.chain import ChainProvider
from verstka.providers.mock import MockProvider
from verstka.providers.openai_compat import OpenAICompatProvider

log = logging.getLogger(__name__)

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
    requests_per_minute: Optional[int] = None
    # model time per generation (brief → decks): past it every step falls back to its deterministic twin, so render,
    # audit and export still fit the 5 minutes a deck may take
    time_budget_s: float = 210.0


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
            requests_per_minute=int(limits_cfg["requests_per_minute"]) if limits_cfg.get("requests_per_minute") else None,
            time_budget_s=float(limits_cfg.get("time_budget_s", 210)),
        )
        roles: dict[str, Provider] = {}
        for role, spec in (cfg.get("roles") or {}).items():
            if role == "t2i":
                continue  # pictures are not chat completions: verstka/images/providers.py builds this role
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

    def with_deadline(self, deadline: float) -> "ProviderRegistry":
        """The same providers bound to one generation's deadline (time.monotonic()); the shared registry stays
        unbound, so concurrent generations each keep their own budget."""
        return ProviderRegistry(roles={r: _Deadlined(p, deadline) for r, p in self.roles.items()}, limits=self.limits, config=self.config)

    def get(self, role: str) -> Provider:
        if role not in self.roles:
            raise ProviderError(f"no provider configured for role {role!r}; roles: {sorted(self.roles)}")
        return self.roles[role]

    def has(self, role: str) -> bool:
        return role in self.roles

    def describe(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for role, p in self.roles.items():
            d: dict[str, Any] = {"backend": p.name, "model": p.model}
            inner, seen = p, 0
            while not isinstance(inner, ChainProvider) and getattr(inner, "inner", None) is not None and seen < 5:
                inner, seen = inner.inner, seen + 1  # a deadline, the generation's recorder
            if isinstance(inner, ChainProvider):
                d["chain"] = inner.describe()
            elif getattr(inner, "label", None):
                d["label"] = inner.label  # a single model's own name («Qwen3.8-27B (VK)»)
            out[role] = d
        return out


class _Deadlined:
    """A provider whose every call carries the generation's deadline (the tighter one if the caller passes its own)."""

    def __init__(self, inner: Provider, deadline: float) -> None:
        self.inner = inner
        self.deadline = deadline
        self.name = inner.name
        self.model = inner.model

    def complete(self, messages, *, schema=None, temperature: float = 0.2, max_tokens: int = 4096, deadline: Optional[float] = None):
        d = self.deadline if deadline is None else min(deadline, self.deadline)
        return self.inner.complete(messages, schema=schema, temperature=temperature, max_tokens=max_tokens, deadline=d)

    def __getattr__(self, item: str) -> Any:
        return getattr(self.inner, item)


POLZA_BASE_URL = "https://polza.ai/api/v1"

# what a model link reads; anything else (the old hosts' pools, max_tokens_cap, min_interval_s, prices) does nothing
_LINK_OPTIONS = frozenset({
    "backend", "model", "base_url", "api_key", "timeout_s", "max_attempts", "extra_body", "json_mode", "requests_per_minute",
    "label", "system_suffix", "exclude_quantizations", "responses", "headers",
})
_WARNED: set = set()


def build_provider(spec: dict, limits: ProviderLimits) -> Provider:
    """One role's backend. `{chain: [spec, spec, ...]}` is a fallback chain (keys next to `chain` are defaults of
    every link, a link's own keys win); a single spec is one provider. A link whose `api_key` expands to an empty
    string (its variable is not set) is built "off": the chain skips it silently.

    Backends: `polza` — Polza.ai (base_url defaults to https://polza.ai/api/v1; `exclude_quantizations` leaves hosts
    with such weights out of the routing, see openai_compat.excluded_hosts); `openai_compat` — any OpenAI-compatible
    endpoint (the final's VK inference; `system_suffix` is added to the system message of every request, e.g. Qwen's
    "/no_think"); `mock` — canned answers for tests."""
    if isinstance(spec, dict) and "chain" in spec:
        shared = {k: v for k, v in spec.items() if k != "chain"}
        link_specs = spec.get("chain") or []
        if not isinstance(link_specs, list) or not link_specs:
            raise ProviderError("a model chain must be a non-empty list of provider specs")
        links: list[Provider] = []
        for ls in link_specs:
            if not isinstance(ls, dict):
                raise ProviderError(f"a chain link must be a provider spec, got {ls!r}")
            if "chain" in ls:
                raise ProviderError("model chains do not nest")
            links.append(build_provider({**shared, **ls}, limits))
        # one link is a single provider: it keeps the single-provider waits
        return links[0] if len(links) == 1 else ChainProvider(links)
    backend = (spec.get("backend") or "polza").lower()
    unused = tuple(sorted(k for k in spec if k not in _LINK_OPTIONS))
    if unused and (spec.get("model"), unused) not in _WARNED:
        _WARNED.add((spec.get("model"), unused))
        log.warning("model %s: config options %s do nothing and are ignored (left from older hosts?)", spec.get("model"), ", ".join(unused))
    if backend == "mock":
        return MockProvider(spec.get("responses") or {}, model=spec.get("model", "mock-model"))
    if backend in ("polza", "openai_compat", "vk"):
        polza = backend == "polza"
        base_url = spec.get("base_url") or (POLZA_BASE_URL if polza else "")
        # no endpoint (VK_INFERENCE_BASE_URL unset): the link is off like one without a key — never called
        api_key = (spec.get("api_key") or "") if base_url else ""
        return OpenAICompatProvider(
            model=spec["model"],
            base_url=base_url,
            api_key=api_key,
            timeout_s=float(spec.get("timeout_s", limits.timeout_s)),
            max_attempts=int(spec.get("max_attempts", limits.max_attempts)),
            extra_body=spec.get("extra_body"),
            json_mode=bool(spec.get("json_mode", True)),
            requests_per_minute=_rpm(spec, limits),
            label=spec.get("label"),
            system_suffix=spec.get("system_suffix"),
            # extra request headers (VK inference: «Project-ID»); a header whose variable is unset is left out
            headers={str(k): str(v) for k, v in (spec.get("headers") or {}).items() if v not in (None, "")} or None,
            exclude_quantizations=spec.get("exclude_quantizations") if polza else None,
            name="polza" if polza else "openai_compat",
        )
    raise ProviderError(f"unknown provider backend {backend!r} (polza, openai_compat or mock)")


def _rpm(spec: dict, limits: ProviderLimits) -> Optional[int]:
    """A link's per-minute cap: its own `requests_per_minute` (0 or null: none), else the limits'."""
    if "requests_per_minute" in spec:
        return int(spec["requests_per_minute"]) if spec["requests_per_minute"] else None
    return limits.requests_per_minute


def default_models_path() -> Path:
    """models.yaml to use: $VERSTKA_MODELS (a path relative to the repository is fine) or configs/models.yaml."""
    import os

    root = Path(__file__).resolve().parents[2]
    env = os.environ.get("VERSTKA_MODELS")
    if env:
        p = Path(env)
        return p if p.is_absolute() else (root / p)
    return root / "configs" / "models.yaml"

