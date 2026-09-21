"""Skill and agent specifications (loaded from skills/<name>/skill.yaml and agents/<name>.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SkillSpec(BaseModel):
    name: str
    version: str
    role: Literal["llm", "vlm", "t2i"]
    description: str = ""
    prompt_files: dict[str, str] = Field(default_factory=dict)  # {"system": "prompts/system.md", "user": "prompts/user.md"}
    output_schema: Optional[str] = None  # dotted path to a pydantic model
    params: dict = Field(default_factory=dict)  # temperature, max_tokens, ...
    changelog: list[str] = Field(default_factory=list)
    sha256: str = ""
    root: Optional[Path] = None

    @property
    def short_hash(self) -> str:
        return self.sha256[:8]


class AgentStep(BaseModel):
    skill: str
    description: str = ""
    optional: bool = False


class AgentSpec(BaseModel):
    name: str
    version: str
    description: str = ""
    steps: list[AgentStep] = Field(default_factory=list)
    sha256: str = ""
