"""DeckIR: a uniform view of any PPTX (generated or not) used by the audit and the HTML exporter."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from verstka.schemas.common import Bbox, BboxFrac, Family


class IRRun(BaseModel):
    text: str
    font: Optional[str] = None
    size_pt: Optional[float] = None
    bold: bool = False
    italic: bool = False
    color_hex: Optional[str] = None


class IRParagraph(BaseModel):
    text: str
    runs: list[IRRun] = Field(default_factory=list)
    bullet: bool = False
    level: int = 0
    align: Optional[str] = None


class IRChartSeries(BaseModel):
    name: str
    values: list[float] = Field(default_factory=list)


class IRChart(BaseModel):
    type: str  # bar, column, line, area, pie, doughnut, other
    categories: list[str] = Field(default_factory=list)
    series: list[IRChartSeries] = Field(default_factory=list)
    has_data_labels: bool = False
    has_legend: bool = False
    has_value_axis: bool = True
    colors: list[str] = Field(default_factory=list)
    number_format: Optional[str] = None


class IRTable(BaseModel):
    rows: list[list[str]] = Field(default_factory=list)
    header_fill_hex: Optional[str] = None


class IRElement(BaseModel):
    id: str
    type: Literal["text", "picture", "shape", "chart", "table", "group", "connector", "other"]
    bbox: Bbox
    bbox_frac: BboxFrac
    paragraphs: list[IRParagraph] = Field(default_factory=list)
    fill_hex: Optional[str] = None
    fill_alpha: float = 1.0  # opacity of fill_hex (0..1); consumers composite translucent fills over the slide
    line_hex: Optional[str] = None
    image_part: Optional[str] = None
    image_size: Optional[tuple[int, int]] = None
    crop: Optional[tuple[float, float, float, float]] = None
    native_kind: Optional[str] = None
    is_placeholder: bool = False
    ph_type: Optional[str] = None
    name: str = ""
    z: int = 0
    nested: bool = False
    autofit: Optional[str] = None
    insets_emu: tuple[int, int, int, int] = (91440, 45720, 91440, 45720)
    anchor: Optional[str] = None
    wrap: bool = True
    chart: Optional[IRChart] = None
    table: Optional[IRTable] = None
    geometry: Optional[str] = None
    corner_radius: Optional[float] = None
    rotation: float = 0.0

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def dominant_size(self) -> Optional[float]:
        weights: dict[float, int] = {}
        for p in self.paragraphs:
            for r in p.runs:
                if r.size_pt and r.text.strip():
                    weights[r.size_pt] = weights.get(r.size_pt, 0) + len(r.text)
        return max(weights, key=weights.get) if weights else None

    @property
    def dominant_font(self) -> Optional[str]:
        weights: dict[str, int] = {}
        for p in self.paragraphs:
            for r in p.runs:
                if r.font and r.text.strip():
                    weights[r.font] = weights.get(r.font, 0) + len(r.text)
        return max(weights, key=weights.get) if weights else None

    @property
    def dominant_color(self) -> Optional[str]:
        weights: dict[str, int] = {}
        for p in self.paragraphs:
            for r in p.runs:
                if r.color_hex and r.text.strip():
                    weights[r.color_hex] = weights.get(r.color_hex, 0) + len(r.text)
        return max(weights, key=weights.get) if weights else None

    @property
    def bold_share(self) -> float:
        total = bold = 0
        for p in self.paragraphs:
            for r in p.runs:
                n = len(r.text)
                total += n
                bold += n if r.bold else 0
        return bold / total if total else 0.0


class IRSlide(BaseModel):
    index: int  # 1-based
    layout_part: Optional[str] = None
    family: Family = Family.light
    background_hex: Optional[str] = None
    elements: list[IRElement] = Field(default_factory=list)
    notes: str = ""
    outline_id: Optional[str] = None

    @property
    def texts(self) -> list[IRElement]:
        """Text boxes only: tables and charts keep their own IR (IRTable / IRChart) and are not text checks' business."""
        return [e for e in self.elements if e.type == "text" and e.has_text]

    @property
    def all_text(self) -> list[IRElement]:
        """Every element carrying text, including table frames (one paragraph per cell): for duplicate/summary consumers."""
        return [e for e in self.elements if e.has_text]

    def by_id(self, eid: str) -> Optional[IRElement]:
        return next((e for e in self.elements if e.id == eid), None)


class DeckIR(BaseModel):
    source: str
    slide_w: int
    slide_h: int
    slides: list[IRSlide] = Field(default_factory=list)
    layout_parts: list[str] = Field(default_factory=list)
    embedded_fonts: list[str] = Field(default_factory=list)

    @property
    def n_slides(self) -> int:
        return len(self.slides)
