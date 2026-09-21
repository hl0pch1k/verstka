"""Load, hash, render and run skills."""

from __future__ import annotations

import hashlib
import importlib
import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel

from verstka.providers.base import ChatMessage, CompletionResult
from verstka.providers.registry import ProviderRegistry
from verstka.skills_registry.models import AgentSpec, SkillSpec

log = logging.getLogger(__name__)


def default_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "skills"


def default_agents_root() -> Path:
    return Path(__file__).resolve().parents[2] / "agents"


def _resolve_schema(dotted: str) -> type[BaseModel]:
    module_name, _, attr = dotted.rpartition(".")
    module = importlib.import_module(module_name)
    schema = getattr(module, attr)
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        raise TypeError(f"{dotted} is not a pydantic model")
    return schema


class SkillsRegistry:
    def __init__(self, skills: dict[str, SkillSpec], agents: Optional[dict[str, AgentSpec]] = None, root: Optional[Path] = None) -> None:
        self.skills = skills
        self.agents = agents or {}
        self.root = root
        self._env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)

    @classmethod
    def load(cls, root: Optional[Path] = None, agents_root: Optional[Path] = None) -> "SkillsRegistry":
        root = Path(root) if root else default_skills_root()
        skills: dict[str, SkillSpec] = {}
        for spec_file in sorted(root.glob("*/skill.yaml")):
            with open(spec_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            spec = SkillSpec(**data, root=spec_file.parent)
            spec.sha256 = cls._hash_skill(spec)
            skills[spec.name] = spec
        agents: dict[str, AgentSpec] = {}
        agents_root = Path(agents_root) if agents_root else default_agents_root()
        if agents_root.is_dir():
            for agent_file in sorted(agents_root.glob("*.yaml")):
                with open(agent_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                agent = AgentSpec(**data)
                agent.sha256 = hashlib.sha256(agent_file.read_bytes()).hexdigest()
                agents[agent.name] = agent
        return cls(skills, agents, root)

    @staticmethod
    def _hash_skill(spec: SkillSpec) -> str:
        h = hashlib.sha256()
        assert spec.root is not None
        h.update((spec.root / "skill.yaml").read_bytes())
        for key in sorted(spec.prompt_files):
            h.update(key.encode())
            h.update((spec.root / spec.prompt_files[key]).read_bytes())
        return h.hexdigest()

    def get(self, name: str) -> SkillSpec:
        if name not in self.skills:
            raise KeyError(f"unknown skill {name!r}; available: {sorted(self.skills)}")
        return self.skills[name]

    def versions(self) -> dict[str, dict[str, str]]:
        out = {name: {"version": s.version, "sha256": s.sha256} for name, s in sorted(self.skills.items())}
        for name, a in sorted(self.agents.items()):
            out[f"agent:{name}"] = {"version": a.version, "sha256": a.sha256}
        return out

    def render(self, name: str, variables: dict[str, Any]) -> dict[str, str]:
        spec = self.get(name)
        assert spec.root is not None
        rendered: dict[str, str] = {}
        for key, rel in spec.prompt_files.items():
            template = self._env.from_string((spec.root / rel).read_text(encoding="utf-8"))
            rendered[key] = template.render(**variables)
        return rendered

    def build_messages(self, name: str, variables: dict[str, Any], images: Optional[list[bytes]] = None) -> list[ChatMessage]:
        prompts = self.render(name, variables)
        messages: list[ChatMessage] = []
        if "system" in prompts:
            messages.append(ChatMessage(role="system", content=prompts["system"]))
        user = prompts.get("user", "")
        messages.append(ChatMessage(role="user", content=user, images=list(images or [])))
        return messages

    def run(
        self,
        name: str,
        providers: ProviderRegistry,
        variables: dict[str, Any],
        images: Optional[list[bytes]] = None,
        **overrides: Any,
    ) -> CompletionResult:
        spec = self.get(name)
        schema = _resolve_schema(spec.output_schema) if spec.output_schema else None
        params = {**spec.params, **overrides}
        provider = providers.get(spec.role)
        messages = self.build_messages(name, variables, images)
        log.debug("running skill %s v%s (%s) with %s", spec.name, spec.version, spec.short_hash, provider.name)
        return provider.complete(
            messages,
            schema=schema,
            temperature=float(params.get("temperature", 0.2)),
            max_tokens=int(params.get("max_tokens", 4096)),
        )
