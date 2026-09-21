"""LayoutPlan: which pattern (or synthesized composition) renders each outline slide, and why."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LayoutSlide(BaseModel):
    outline_id: str
    mode: Literal["clone", "synth"]
    pattern_id: Optional[str] = None
    composition: Optional[str] = None  # synth composition name
    fit: dict = Field(default_factory=dict)  # {"items": "3/4", "text_ratio": 0.8, ...}
    score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    alternatives: list[tuple[str, float]] = Field(default_factory=list)  # (pattern_id, score) runners-up


class LayoutPlan(BaseModel):
    strategy: str
    template_id: str
    slides: list[LayoutSlide] = Field(default_factory=list)

    def for_outline(self, outline_id: str) -> Optional[LayoutSlide]:
        return next((s for s in self.slides if s.outline_id == outline_id), None)
