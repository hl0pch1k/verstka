"""Brief and DeckOutline: what the planner produces and the renderer consumes."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from verstka.schemas.common import PatternKind

Purpose = Literal["feature", "product", "project", "initiative", "report", "other"]


class Brief(BaseModel):
    text: str
    title_hint: Optional[str] = None
    audience: Optional[str] = None
    purpose: Optional[Purpose] = None
    slide_count: Optional[int] = None
    language: str = "ru"
    tone: Optional[str] = None
    extra_instructions: Optional[str] = None


class Fact(BaseModel):
    id: str
    value: str
    unit: Optional[str] = None
    label: str
    source_span: Optional[str] = None


class Series(BaseModel):
    id: str
    name: str
    categories: list[str]
    values: list[float]
    unit: Optional[str] = None
    source_span: Optional[str] = None


class TableData(BaseModel):
    columns: list[str]
    rows: list[list[str]]
    unit: Optional[str] = None
    caption: Optional[str] = None
    source_span: Optional[str] = None


class ChartSpec(BaseModel):
    type: Literal["bar", "column", "line", "area", "pie", "doughnut"] = "column"
    series_ids: list[str] = Field(default_factory=list)
    title: Optional[str] = None
    unit: Optional[str] = None
    highlight_index: Optional[int] = None


class SlideItem(BaseModel):
    title: str
    text: str = ""
    icon_hint: Optional[str] = None
    number: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class NumberCallout(BaseModel):
    value: str
    label: str
    fact_id: Optional[str] = None


class SlideContent(BaseModel):
    bullets: list[str] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    items: list[SlideItem] = Field(default_factory=list)
    numbers: list[NumberCallout] = Field(default_factory=list)
    table: Optional[TableData] = None
    chart: Optional[ChartSpec] = None
    quote: Optional[str] = None
    quote_author: Optional[str] = None
    image_hint: Optional[str] = None
    columns: list[SlideItem] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.bullets or self.paragraphs or self.items or self.numbers or self.table or self.chart or self.quote or self.columns)


class OutlineSlide(BaseModel):
    id: str
    kind: PatternKind
    section: Optional[str] = None
    headline: str
    subtitle: Optional[str] = None
    content: SlideContent = Field(default_factory=SlideContent)
    notes: str = ""
    fact_refs: list[str] = Field(default_factory=list)


class DeckOutline(BaseModel):
    title: str
    subtitle: Optional[str] = None
    audience: Optional[str] = None
    purpose: Optional[str] = None
    strategy: str = "structured"
    language: str = "ru"
    slides: list[OutlineSlide] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)

    def series_by_id(self, sid: str) -> Optional[Series]:
        return next((s for s in self.series if s.id == sid), None)

    def fact_by_id(self, fid: str) -> Optional[Fact]:
        return next((f for f in self.facts if f.id == fid), None)


class FactsExtraction(BaseModel):
    """Output of the `data_extractor` skill."""

    facts: list[Fact] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)


class PlannedDeck(BaseModel):
    """Output of the `outline_planner` skill (facts/series come from the extractor)."""

    title: str
    subtitle: Optional[str] = None
    slides: list[OutlineSlide] = Field(default_factory=list)


class CondensedText(BaseModel):
    """Output of the `text_condenser` skill."""

    text: str


class FactIssue(BaseModel):
    slide_id: str
    text: str
    severity: Literal["error", "warn"] = "warn"


class FactCheck(BaseModel):
    """Output of the `fact_checker` skill."""

    issues: list[FactIssue] = Field(default_factory=list)
