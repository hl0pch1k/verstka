"""Brief and DeckOutline: what the planner produces and the renderer consumes."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from verstka.schemas.common import PatternKind

# the name the free place for the user's photo carries on the slide (SlideContent.photo_slot): the audit knows it by
# it — a quiet stand-in for a photo, not a colour of the deck's own
PHOTO_PLACE_NAME = "Место для фото"

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


class InlineSeries(BaseModel):
    """One data series written into a chart by the planner (Agent v2): its values are checked against the brief."""

    name: str = ""
    values: list[float] = Field(default_factory=list)


class ChartSpec(BaseModel):
    type: Literal["bar", "column", "line", "area", "pie", "doughnut"] = "column"
    series_ids: list[str] = Field(default_factory=list)
    title: Optional[str] = None
    unit: Optional[str] = None
    highlight_index: Optional[int] = None
    # Agent v2: the data of the chart written by the slide designer (categories + one or more series). The compiler
    # (planning/compile.py) turns it into registry Series and fills series_ids; grounding checks every value.
    categories: list[str] = Field(default_factory=list)
    series: list[InlineSeries] = Field(default_factory=list)


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
    # Agent v2: a second chart on the same slide («два небольших графика: до и после»), and a formula shown large
    # («100 × 300 × 30 = 900 000 ₽»)
    chart2: Optional[ChartSpec] = None
    formula: Optional[str] = None
    # the user's own photo goes here («оставь место под фотографию помещения»): the slide keeps a free place for it —
    # the template's own picture placeholder when a sample of the template has one, else a quiet frame — and never fills
    # it with text, a chart or a picture of ours. The value names the photo («Фото помещения»).
    photo_slot: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not (self.bullets or self.paragraphs or self.items or self.numbers or self.table or self.chart or self.quote or self.columns)


class SlideAlternative(BaseModel):
    """Another form the slide designer proposed for a slide (Agent v2): the kind and what changes with it, in Russian
    («table» — «те же расходы таблицей: статья, сумма, доля»). Other variants may use it."""

    kind: str = ""
    change: str = ""
    # the alternative's own content when the designer wrote it (its fields replace the slide's); without it the
    # compiler (planning/compile.py) converts the slide's content to the kind itself when it can
    content: Optional[SlideContent] = None


class OutlineSlide(BaseModel):
    id: str
    kind: PatternKind
    section: Optional[str] = None
    headline: str
    subtitle: Optional[str] = None
    content: SlideContent = Field(default_factory=SlideContent)
    notes: str = ""
    fact_refs: list[str] = Field(default_factory=list)
    # Agent v2: the slide's short conclusion shown under its content («Вывод: …»), a small footnote (a disclaimer,
    # «налоги не учитываются»), why the designer chose this form (shown in «Почему слайд такой»), and the number of
    # the slide the user asked for in the brief («Слайд 3.») — such slides are never dropped.
    takeaway: Optional[str] = None
    footnote: Optional[str] = None
    rationale: Optional[str] = None
    spec_ref: Optional[int] = None
    # Agent v2 (UI): the other forms the designer proposed for this slide (shown in «Почему слайд такой»)
    alternatives: list[SlideAlternative] = Field(default_factory=list)


class DeckOutline(BaseModel):
    title: str
    subtitle: Optional[str] = None
    audience: Optional[str] = None
    purpose: Optional[str] = None
    strategy: str = "structured"
    language: str = "ru"
    # who wrote the plan: "rules" (deterministic planner), "model" (outline_planner skill) or "shared:<strategy>"
    # (another variant's model plan reshaped for this strategy when this variant's own model call failed)
    planned_by: str = "rules"
    slides: list[OutlineSlide] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    # Agent v2: what the agent did, in plain Russian, step by step (shown in the UI as the agent's work)
    agent_log: list[str] = Field(default_factory=list)

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
