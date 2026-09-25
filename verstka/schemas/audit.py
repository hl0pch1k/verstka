"""Audit report schemas."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from verstka.schemas.common import BboxFrac

Severity = Literal["error", "warn", "info"]
IssueKind = Literal["deterministic", "model"]
FixKind = Literal["rematch", "synth", "shrink_text", "condense_text", "recolor", "refont", "move_inside", "drop_element", "none"]


class FixAction(BaseModel):
    action: FixKind
    params: dict = Field(default_factory=dict)
    description: str = ""


class Issue(BaseModel):
    id: str
    slide: int  # 1-based, 0 = deck level
    check_id: str
    severity: Severity
    kind: IssueKind
    message: str
    bboxes: list[BboxFrac] = Field(default_factory=list)
    element_ids: list[str] = Field(default_factory=list)
    suggestion: Optional[str] = None
    autofix: Optional[FixAction] = None
    details: dict = Field(default_factory=dict)
    outline_id: Optional[str] = None


class AuditSummary(BaseModel):
    errors: int = 0
    warnings: int = 0
    infos: int = 0
    model_flags: int = 0
    score: int = 100
    checks_run: list[str] = Field(default_factory=list)
    # the figures on the slides compared with the source text: {"checked", "derived", "unverified"} (checks/facts.py)
    figures: Optional[dict] = None


class AuditReport(BaseModel):
    deck: str
    template_id: str
    strategy: Optional[str] = None
    issues: list[Issue] = Field(default_factory=list)
    summary: AuditSummary = Field(default_factory=AuditSummary)
    per_slide: dict[int, list[str]] = Field(default_factory=dict)  # slide → issue ids
    iterations: int = 0
    applied_fixes: list[dict] = Field(default_factory=list)
    slide_images: dict[int, str] = Field(default_factory=dict)
    seconds: float = 0.0

    def issues_for(self, slide: int) -> list[Issue]:
        return [i for i in self.issues if i.slide == slide]

    def recompute(self) -> "AuditReport":
        s = AuditSummary(checks_run=self.summary.checks_run, figures=self.summary.figures)
        for i in self.issues:
            if i.kind == "model":
                s.model_flags += 1
            if i.severity == "error":
                s.errors += 1
            elif i.severity == "warn":
                s.warnings += 1
            else:
                s.infos += 1
        s.score = max(0, 100 - 10 * s.errors - 3 * s.warnings - 2 * s.model_flags)
        self.summary = s
        per: dict[int, list[str]] = {}
        for i in self.issues:
            per.setdefault(i.slide, []).append(i.id)
        self.per_slide = per
        return self


class CheckSpec(BaseModel):
    id: str
    title: str
    severity: Severity
    kind: IssueKind = "deterministic"
    category: str  # layout | template | density | integrity | content
    description: str = ""
