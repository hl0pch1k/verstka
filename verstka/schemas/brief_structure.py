"""What the brief says about its deck (Agent v2 contract): the slides the user asked for, the charts and tables they
requested, global rules and the data the brief holds. Produced by planning/brief_structure.py (deterministic, plus
the data_extractor skill per block); consumed by the planning agent (planning/agent.py)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from verstka.schemas.outline import Fact, Series, SlideItem, TableData

ChartKind = Literal["bar", "column", "line", "area", "pie", "doughnut"]


class ChartRequest(BaseModel):
    """A chart the user asked for on a slide: «Нужна круговая диаграмма структуры выручки», «Покажи структуру
    расходов на диаграмме», «два небольших столбчатых графика: … до и после»."""

    type: Optional[ChartKind] = None  # None when the user did not say which kind («на диаграмме»)
    what: str = ""  # what it shows, in the user's words
    series_ids: list[str] = Field(default_factory=list)  # data of the brief it shows, when found


class SlideSpec(BaseModel):
    """One slide the user described («Слайд 3. Куда уходят деньги» and the lines under it)."""

    number: int
    title: str = ""
    text: str = ""  # the lines under the heading, verbatim
    charts: list[ChartRequest] = Field(default_factory=list)
    table: bool = False  # «Сделай сравнительную таблицу …»
    formula: Optional[str] = None  # «Покажи формулу: 100 × 300 × 30 = 900 000 рублей»
    footnote: Optional[str] = None  # «Укажи, что налоги … не учитываются»
    takeaway: Optional[str] = None  # «Вывод: …», «Финальный вывод: «…»»
    series_ids: list[str] = Field(default_factory=list)  # data of this slide (registry ids)
    table_ids: list[int] = Field(default_factory=list)  # indexes into BriefStructure.tables
    # the slide's lists that are not data («1-й месяц — учет показателей и обновление меню», «— контроль порций;»):
    # a plan, steps, measures, indicators — title (and text after a dash) per line, in order
    items: list[SlideItem] = Field(default_factory=list)


class BriefStructure(BaseModel):
    title: Optional[str] = None  # «Название: «Больше прибыли с каждой чашки»»
    subtitle: Optional[str] = None
    slide_count: Optional[int] = None  # «на 10 слайдов»
    specs: list[SlideSpec] = Field(default_factory=list)  # empty when the brief does not describe slides
    rules: list[str] = Field(default_factory=list)  # global instructions, verbatim («Не перегружай слайды текстом»)
    disclaimer: Optional[str] = None  # «Все исходные данные и прогнозы условные» (to show small on the cover)
    notes_rule: bool = False  # «Подробности и пояснения расчетов вынеси в заметки докладчика»
    rounding: Optional[str] = None  # «Денежные суммы на диаграммах можно округлять до тысяч рублей»
    series: list[Series] = Field(default_factory=list)  # every data series of the brief (lists, enumerations)
    tables: list[TableData] = Field(default_factory=list)
    # figures the data_extractor skill found per block (enrich_with_model), each checked against its block; the facts
    # registry (planning/facts.py) merges them with the figures the rules read
    facts: list[Fact] = Field(default_factory=list)
