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
    line_spacing: Optional[float] = None  # explicit a:lnSpc/a:spcPct of the paragraph (0.9 = 90 %); None = inherited


class IRPointLabel(BaseModel):
    """A per-point data label override (c:dLbl)."""

    deleted: bool = False
    format: Optional[str] = None
    color: Optional[str] = None
    bold: Optional[bool] = None
    size_pt: Optional[float] = None
    series_name: bool = False  # «Было: 48» — the label names its series
    position: Optional[str] = None


class IRChartSeries(BaseModel):
    name: str
    values: list[float] = Field(default_factory=list)
    color: Optional[str] = None  # fill (bars, areas, slices' default) or line colour
    outline_only: bool = False  # a hollow bar (a plan)
    dashed: bool = False
    point_colors: dict[int, str] = Field(default_factory=dict)  # c:dPt fills (a highlighted bar, pie slices)
    labels_shown: Optional[bool] = None  # the series' own c:dLbls/c:showVal
    label_format: Optional[str] = None
    label_color: Optional[str] = None
    label_bold: Optional[bool] = None
    label_size_pt: Optional[float] = None
    point_labels: dict[int, IRPointLabel] = Field(default_factory=dict)


class IRChart(BaseModel):
    type: str  # bar, column, line, area, pie, doughnut, other
    categories: list[str] = Field(default_factory=list)
    series: list[IRChartSeries] = Field(default_factory=list)
    has_data_labels: bool = False
    has_legend: bool = False
    has_value_axis: bool = True
    colors: list[str] = Field(default_factory=list)
    number_format: Optional[str] = None
    title: Optional[str] = None  # chart title or unit caption, top left
    series_labels: bool = False  # series are named on their data labels (a legend's job)
    axis_color: Optional[str] = None  # category label colour
    rule_color: Optional[str] = None  # the category axis line
    reversed_categories: bool = False


class IRTableCell(BaseModel):
    """How one table cell is set: the first run with text and the cell's own fill and side margins."""

    size_pt: Optional[float] = None
    bold: bool = False
    color_hex: Optional[str] = None  # explicit srgb only (theme colours are left unresolved)
    fill_hex: Optional[str] = None  # an opaque-enough solid cell fill
    mar_l_pt: float = 7.2
    mar_r_pt: float = 7.2


class IRTable(BaseModel):
    rows: list[list[str]] = Field(default_factory=list)
    header_fill_hex: Optional[str] = None
    col_widths_emu: list[int] = Field(default_factory=list)  # a:gridCol — the real columns, not width / n
    cells: list[list[IRTableCell]] = Field(default_factory=list)  # same shape as rows


class IRPictureCells(BaseModel):
    """A coarse grid over a template picture's box: per cell the share of opaque pixels, their mean colour and their
    luminance stdev (0–255) — what the picture really paints where (a sparse dot pattern, a photo with a flat dark
    part, a glass cube on a transparent sheet). Row-major, `w`×`h` cells."""

    w: int
    h: int
    alpha: list[float] = Field(default_factory=list)
    hex: list[str] = Field(default_factory=list)
    std: list[float] = Field(default_factory=list)
    # a photo ground (a picture covering ≥ 85 % of the slide): the luminance stdev of a grid twice as fine
    # (layers.FINE_W × FINE_H), to tell where inside a busy cell its busy part lies (round 4.1)
    fine_std: list[float] = Field(default_factory=list)


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
    # template layers (IRSlide.template_elements) only: where the shape comes from, whether a picture is a photo
    # (luminance stdev > 40) and whether its paint hides what lies under it; `fill_hex` of such a picture is its
    # median colour
    source: str = "slide"  # slide | layout | master
    busy: bool = False
    opaque: bool = True
    paint_kind: Optional[str] = None  # solid | gradient | pattern | image (template layers only)
    # what a non-rectangular template shape really paints (an ellipse, a triangle, a freeform): polygons in EMU;
    # None when the box is what it paints
    outline: Optional[list[list[tuple[int, int]]]] = None
    cells: Optional[IRPictureCells] = None  # template pictures, and a slide's own picture covering ≥ 85 % of it
    # the text shows in capitals whatever case it is typed in (cap="all"/"small" on its first run, its list style or
    # the layout/master placeholder it inherits from): widths are measured on the upper-cased text
    caps: bool = False

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
    # what the slide stands on (analysis.ground): kind of the ground (solid, gradient, pattern, image, render, None)
    # and whether its colour is only an estimate (a photo, a gradient, a render median)
    background_kind: Optional[str] = None
    background_uncertain: bool = False
    # the non-placeholder shapes and pictures the slide's layout (and its master, unless hidden) paints under the
    # slide's own shapes: bands, panels, illustrations, photo grounds. Never part of `elements` (the checks of the
    # deck's own content and the HTML exporter do not see them); grounds and template-art checks read them.
    template_elements: list[IRElement] = Field(default_factory=list)

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
    # every colour the template's layouts and masters set themselves (shape fills and lines, txStyles, list styles):
    # text in these colours is the template's own
    template_colors: list[str] = Field(default_factory=list)
    # [major, minor] theme fonts of the deck's first master (what +mj-lt / +mn-lt runs are set in)
    theme_fonts: list[str] = Field(default_factory=list)

    @property
    def n_slides(self) -> int:
        return len(self.slides)
