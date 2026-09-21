"""Slide classification: schemas for the LLM/VLM skills and the ensemble (ensemble added in Task 9)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from verstka.schemas.common import PatternKind, SlotRole


class SlideClassification(BaseModel):
    """Output of the `slide_classifier` skill."""

    kind: PatternKind
    roles: dict[str, SlotRole] = Field(default_factory=dict)  # shape_id → role
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class SlideVisionCheck(BaseModel):
    """Output of the `slide_vision_check` skill."""

    kind: PatternKind
    purpose: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
