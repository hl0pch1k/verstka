"""TemplateManifest: everything the analyzer learns about a PPTX template."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from verstka.schemas.common import BboxFrac, Family, PatternKind, SlotRole


class ColorToken(BaseModel):
    hex: str
    role: Optional[str] = None  # primary role for display: background.light, background.dark, surface, text.primary, text.secondary, accent.N, neutral.N
    roles: list[str] = Field(default_factory=list)  # all roles (black may be background.dark AND text.primary)
    semantic: Optional[str] = None  # positive | negative (hint for charts and status colours)
    is_brand: bool = False
    weight: float = 0.0
    contexts: dict[str, int] = Field(default_factory=dict)  # fill/text/line/background → count
    context_weight: dict[str, float] = Field(default_factory=dict)  # fill/text/line/background → summed weight

    def has_role(self, role: str) -> bool:
        return role in self.roles or self.role == role


class FontUsage(BaseModel):
    family: str
    weight: float = 0.0  # share of characters
    bold_share: float = 0.0


class TypeStep(BaseModel):
    role: str  # display, h1, h2, body, small, caption
    size_pt: float
    weight_bold_share: float = 0.0
    count: int = 0


class Typography(BaseModel):
    families: list[FontUsage] = Field(default_factory=list)
    scale: list[TypeStep] = Field(default_factory=list)
    sizes_used: list[float] = Field(default_factory=list)  # every size the template uses (audit tolerance ±0.75 pt)
    left_align_share: float = 1.0
    line_spacing: float = 1.2

    def size_for(self, role: str, default: float = 18.0) -> float:
        for step in self.scale:
            if step.role == role:
                return step.size_pt
        return default

    @property
    def primary_family(self) -> Optional[str]:
        return self.families[0].family if self.families else None


class Spacing(BaseModel):
    safe_area: BboxFrac = Field(default_factory=lambda: BboxFrac(x=0.05, y=0.08, w=0.90, h=0.84))
    columns: list[float] = Field(default_factory=list)  # left edges as fractions
    gutter: Optional[float] = None  # fraction of slide width


class ShapeStyleStats(BaseModel):
    corner_radius_share: float = 0.0  # share of rects with rounded corners
    typical_radius: Optional[float] = None  # adj value 0..0.5
    line_share: float = 0.0
    typical_line_w_pt: Optional[float] = None
    shadow_share: float = 0.0
    card_fill_hex: Optional[str] = None


class ChromeElement(BaseModel):
    signature: str
    bbox: BboxFrac
    share: float
    kind: str  # sp/pic/text
    sample_slide: int
    text: Optional[str] = None
    image_part: Optional[str] = None
    source: str = "slide"  # slide | layout:<part> | master:<part> (layout/master chrome is inherited automatically)


class BackgroundFamily(BaseModel):
    family: Family
    fill_kind: str  # solid, gradient, image
    hex: Optional[str] = None
    asset_id: Optional[str] = None
    slides: list[int] = Field(default_factory=list)


class Tokens(BaseModel):
    colors: list[ColorToken] = Field(default_factory=list)
    typography: Typography = Field(default_factory=Typography)
    spacing: Spacing = Field(default_factory=Spacing)
    shapes: ShapeStyleStats = Field(default_factory=ShapeStyleStats)
    chrome: list[ChromeElement] = Field(default_factory=list)
    backgrounds: list[BackgroundFamily] = Field(default_factory=list)

    def color_for(self, role: str) -> Optional[str]:
        for c in self.colors:
            if c.has_role(role):
                return c.hex
        return None

    def accents(self) -> list[str]:
        acc = []
        for c in self.colors:
            for r in c.roles or ([c.role] if c.role else []):
                if r and r.startswith("accent."):
                    acc.append((int(r.split(".")[1]), c.hex))
        acc.sort()
        return [h for _, h in acc]

    def semantic_color(self, kind: str) -> Optional[str]:
        for c in self.colors:
            if c.semantic == kind:
                return c.hex
        return None

    def palette(self) -> list[str]:
        return [c.hex for c in self.colors]


class SlotStyle(BaseModel):
    font_family: Optional[str] = None
    size_pt: Optional[float] = None
    bold: bool = False
    color_hex: Optional[str] = None
    align: Optional[str] = None


class Capacity(BaseModel):
    max_chars: int
    max_lines: int


class Slot(BaseModel):
    id: str
    role: SlotRole
    shape_id: str
    bbox: BboxFrac
    style: SlotStyle = Field(default_factory=SlotStyle)
    capacity: Capacity = Field(default_factory=lambda: Capacity(max_chars=0, max_lines=0))
    group_id: Optional[str] = None
    sample_text: Optional[str] = None


class RepeatGroup(BaseModel):
    id: str
    member_shape_ids: list[list[str]]  # one inner list per cell
    min_n: int = 1
    max_n: int
    axis: str  # row, column, grid
    gap: float = 0.0  # fraction of slide width (row) or height (column)
    cell_bbox: BboxFrac
    rows: int = 1
    cols: int = 1


class SignalVote(BaseModel):
    kind: PatternKind
    confidence: float
    rationale: Optional[str] = None


class ClassificationTrace(BaseModel):
    kind: PatternKind
    heuristic: SignalVote
    llm: Optional[SignalVote] = None
    vlm: Optional[SignalVote] = None
    agreement: float = 1.0
    purpose: Optional[str] = None


class Pattern(BaseModel):
    id: str
    source_slide: int  # 1-based
    kind: PatternKind
    family: Family
    slots: list[Slot] = Field(default_factory=list)
    repeat_groups: list[RepeatGroup] = Field(default_factory=list)
    decor_assets: list[str] = Field(default_factory=list)
    quality: float = 1.0
    thumbnail: Optional[str] = None
    classification: Optional[ClassificationTrace] = None
    layout_part: Optional[str] = None

    def slots_by_role(self, role: SlotRole) -> list[Slot]:
        return [s for s in self.slots if s.role == role]


class CardSpec(BaseModel):
    fill_hex: Optional[str] = None
    line_hex: Optional[str] = None
    radius: Optional[float] = None
    title_size_pt: Optional[float] = None
    body_size_pt: Optional[float] = None
    inset_frac: float = 0.06
    width_frac: Optional[float] = None
    height_frac: Optional[float] = None


class BulletSpec(BaseModel):
    marker: Optional[str] = None
    size_pt: Optional[float] = None
    indent_emu: Optional[int] = None
    space_after_pt: Optional[float] = None


class NumberSpec(BaseModel):
    size_pt: Optional[float] = None
    color_hex: Optional[str] = None
    label_size_pt: Optional[float] = None


class IconChipSpec(BaseModel):
    bg_hex: Optional[str] = None
    size_frac: Optional[float] = None
    icon_color_hex: Optional[str] = None
    shape: str = "ellipse"


class TableStyleSpec(BaseModel):
    header_fill_hex: Optional[str] = None
    header_text_hex: Optional[str] = None
    body_text_hex: Optional[str] = None
    band_fill_hex: Optional[str] = None
    border_hex: Optional[str] = None
    font_size_pt: float = 12.0
    numbers_align: str = "right"


class ChartStyleSpec(BaseModel):
    series_colors: list[str] = Field(default_factory=list)
    gridlines: bool = False
    data_labels: bool = True
    font_family: Optional[str] = None
    font_size_pt: float = 12.0
    legend_position: str = "bottom"


class Components(BaseModel):
    card: Optional[CardSpec] = None
    bullet_item: Optional[BulletSpec] = None
    number_callout: Optional[NumberSpec] = None
    icon_chip: Optional[IconChipSpec] = None
    table_style: TableStyleSpec = Field(default_factory=TableStyleSpec)
    chart_style: ChartStyleSpec = Field(default_factory=ChartStyleSpec)


class Asset(BaseModel):
    id: str
    path: str
    kind: str  # icon, logo, mockup, illustration, photo, pattern, other
    width: int
    height: int
    has_alpha: bool = False
    tags: list[str] = Field(default_factory=list)
    used_on_slides: list[int] = Field(default_factory=list)
    media_part: Optional[str] = None


class StyleRule(BaseModel):
    text: str
    source: str  # derived | template_text | llm
    confidence: float = 1.0


class SlideSize(BaseModel):
    w: int
    h: int


class TemplateManifest(BaseModel):
    template_id: str
    source_file: str
    slide_size: SlideSize
    tokens: Tokens
    patterns: list[Pattern] = Field(default_factory=list)
    components: Components = Field(default_factory=Components)
    assets: list[Asset] = Field(default_factory=list)
    style_rules: list[StyleRule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    n_slides: int = 0
    analysis_version: str = "8"
    embedded_fonts: list[str] = Field(default_factory=list)

    def patterns_of_kind(self, kind: PatternKind) -> list[Pattern]:
        return [p for p in self.patterns if p.kind == kind]
