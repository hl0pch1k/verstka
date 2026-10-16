"""Брендбук (вторая ступень): цвета с ролями, шрифты, логотипы, поля и правила — общий контракт чтения
(`verstka/brand/` — токены, PDF, папка, Figma), применения к шаблону (брендированная копия) и слоя «Брендбук».

`BrandConflict` — расхождение брендбука с выбранным шаблоном и то, что в итоге попало в презентацию: при
`brand_priority = "brand"` (по умолчанию) важнее брендбук, при "template" бренд только дополняет то, чего нет в шаблоне."""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

BrandColorRole = Literal[
    "primary", "secondary", "accent", "text", "background", "surface", "chart", "neutral", "success", "warning", "danger",
]
BrandFontRole = Literal["heading", "body"]
# основной, белый (для тёмного фона), знак, монохромный
LogoVariant = Literal["primary", "white", "mark", "mono"]
# на каком фоне логотип стоит: светлом, тёмном, любом
LogoGround = Literal["light", "dark", "any"]
BrandRuleKind = Literal["logo", "color", "type", "grid", "other"]
BrandSource = Literal["tokens", "pdf", "folder", "figma"]
# место логотипа на слайде («логотип — в правом нижнем углу»)
LogoPlace = Literal["top_left", "top_right", "bottom_left", "bottom_right"]
# что важнее при расхождении брендбука с шаблоном
BrandPriority = Literal["brand", "template"]
ConflictKind = Literal["color", "font", "logo", "margins", "other"]

_HEX_RE = re.compile(r"#?([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})")


def normalize_hex(value: str) -> str:
    """«0077ff», «#07F» → «#0077FF»; иначе ValueError."""
    m = _HEX_RE.fullmatch(str(value).strip())
    if not m:
        raise ValueError(f"не цвет HEX: {value!r}")
    h = m.group(1).upper()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


class BrandColor(BaseModel):
    # «#0077FF» — всегда шесть цифр в верхнем регистре
    hex: str
    # роль не названа — цвет идёт в палитру диаграмм
    role: BrandColorRole = "chart"
    # имя цвета в брендбуке («VK Blue»)
    name: Optional[str] = None

    @field_validator("hex", mode="before")
    @classmethod
    def _hex(cls, v: object) -> str:
        return normalize_hex(str(v))


class BrandFont(BaseModel):
    role: BrandFontRole
    family: str
    # замена, когда шрифта нет на машине («Play»)
    fallback: Optional[str] = None
    weight: int = 400


class BrandLogo(BaseModel):
    # «Основной», «Белый», «Знак», «Монохром»
    name: str
    # файл логотипа в папке брендбука (svg/png)
    file: str
    variant: LogoVariant = "primary"
    ground: LogoGround = "any"


class BrandRule(BaseModel):
    # «Логотип — в правом нижнем углу», «Поля — 48 px», «Акцент — только для главного числа»
    text: str
    kind: BrandRuleKind = "other"


class BrandSpec(BaseModel):
    id: str = ""
    # «VK Cloud»
    name: str = ""
    source: BrandSource
    # имя файла или ссылка Figma
    file: Optional[str] = None
    # страниц PDF-гайдлайна (0 — не PDF)
    pages: int = 0
    colors: list[BrandColor] = Field(default_factory=list)
    fonts: list[BrandFont] = Field(default_factory=list)
    logos: list[BrandLogo] = Field(default_factory=list)
    # поля слайда, px
    margins_px: Optional[float] = None
    # сетка словами («12 колонок, промежуток 24 px»)
    grid: Optional[str] = None
    rules: list[BrandRule] = Field(default_factory=list)
    logo_place: Optional[LogoPlace] = None
    # что прочитать не удалось или прочитано неуверенно — по-русски
    warnings: list[str] = Field(default_factory=list)

    def color(self, role: BrandColorRole) -> Optional[BrandColor]:
        return next((c for c in self.colors if c.role == role), None)

    def font(self, role: BrandFontRole) -> Optional[BrandFont]:
        return next((f for f in self.fonts if f.role == role), None)


class BrandConflict(BaseModel):
    """Расхождение брендбука с шаблоном: «Шрифт заголовков: шаблон — Play · брендбук — VK Sans Display»."""

    # что расходится («Шрифт заголовков», «Второй акцент»)
    what: str
    # значение в шаблоне и в брендбуке («Play», «#FF3885»)
    template: str
    brand: str
    # что в итоге в презентации («VK Sans Display»)
    result: str
    kind: ConflictKind = "other"
