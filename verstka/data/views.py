"""Виды данных для слайда (описание решения §2.5): метрика, ряд по времени, категории, распределение, ключевые
показатели, справочник, взаимосвязь. Только данные и их свойства; как их собрать из таблицы — `aggregate.py`,
`timeaxis.py`, `kpi.py`, `reference.py`."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from verstka.data.words import PERIOD_WORDS, count_words, fmt_num

__all__ = [
    "MAX_POINTS", "MAX_CATS", "TOP_N", "TABLE_ROWS", "MAX_SLIDES", "MAX_SERIES", "MAX_ORDINAL",
    "Measure", "SeriesV", "TimeView", "CatView", "Bins", "DistView", "KpiItem", "KpiView", "RefView", "XYView",
]

MAX_POINTS = 36  # больше точек — ресэмплинг к более крупному периоду
MAX_CATS = 12  # больше категорий — топ и «Остальные»
TOP_N = 10  # строк справочника на слайде
TABLE_ROWS = 10
MAX_SLIDES = 3  # больше слайдов на один датасет — уже не разбиение, а агрегация
MAX_SERIES = 5
MAX_ORDINAL = 20  # порядковых групп («0–4», «5–9», …) на графике — все до 20, дальше хвост одной группой


@dataclass
class Measure:
    """Метрика — колонка с числами."""

    j: int
    name: str
    unit: Optional[str]
    type: str
    values: list[Optional[float]]  # по строкам таблицы (строки итога — None)
    change: bool = False  # изменение/рост (знак важен, не складывается)
    level: bool = False  # уровень (доля, индекс, среднее): не складывается, при ресэмплинге — среднее
    stock: bool = False  # остаток (клиентов, сотрудников): по категориям складывается, по времени — последнее
    mixed: bool = False  # в колонке разные единицы по строкам («1,24 млрд ₽», «3 480»)
    time_unit: Optional[str] = None  # «мин», «ч», «дн.» — длительность
    raw: list[Optional[float]] = field(default_factory=list)  # числа как написаны («1,24 млрд ₽» → 1.24)
    row_units: list[Optional[str]] = field(default_factory=list)  # единица каждой строки (колонка с разными единицами)
    basis: str = ""  # признак, по которому решено, складывается ли величина («единица «ц/га» — величина на единицу»)
    scale: float = 1.0  # значения поделены на это (огромные рубли — в млрд или трлн), единица — с множителем

    @property
    def additive(self) -> bool:
        return not (self.change or self.level or self.mixed)

    @property
    def nonneg(self) -> bool:
        return all(v is None or v >= 0 for v in self.values)

    @property
    def present(self) -> list[float]:
        return [v for v in self.values if v is not None]

    @property
    def how(self) -> str:
        """Как собирать значения одного периода: сумма, среднее или последнее."""
        if self.change or self.level or self.mixed:
            return "mean"
        if self.stock:
            return "last"
        return "sum"

    @property
    def unit_text(self) -> Optional[str]:
        return self.unit or self.time_unit


@dataclass
class SeriesV:
    name: str
    unit: Optional[str]
    values: list[Optional[float]]


@dataclass
class TimeView:
    column: str
    freq: str  # частота после ресэмплинга
    periods: list[str]  # ISO
    labels: list[str]
    series: list[SeriesV]
    measure: Measure
    source_freq: str
    source_points: int
    how: str  # sum | mean | last
    dim: Optional[str] = None  # ряды по категориям этой колонки (длинный формат)
    others: int = 0  # сколько категорий ушло в «Остальные»
    column_type: str = "date"
    partial: int = 0  # неполных крайних периодов не показано (сумма за них занижена)
    partial_txt: list[str] = field(default_factory=list)  # «февраль 2026 — 22 из 28 дней»
    cat_moves: dict[str, tuple[float, float]] = field(default_factory=dict)  # категория → (первое, последнее)
    per_week: bool = False  # недели в месяцы или кварталы: значение периода — в среднем за неделю
    from_columns: bool = False  # ось из колонок-периодов («I кв. · II кв. · …»), значение — по всем строкам

    @property
    def points(self) -> int:
        return len(self.periods)

    @property
    def main(self) -> SeriesV:
        return self.series[0]

    @property
    def missing(self) -> list[str]:
        """Периоды без значения главного ряда (у рядов по категориям — без значения ни в одном)."""
        if self.dim:
            return [p for i, p in enumerate(self.periods) if all(s.values[i] is None for s in self.series)]
        return [p for p, v in zip(self.periods, self.main.values) if v is None]

    @property
    def gaps(self) -> bool:
        return any(v is None for s in self.series for v in s.values)

    @property
    def resampled(self) -> bool:
        return self.freq != self.source_freq

    @property
    def split(self) -> bool:
        """Ряды в разных единицах — каждый своим графиком рядом (ChartSpec.split)."""
        return len({s.unit for s in self.series}) > 1

    @property
    def note(self) -> Optional[str]:
        """«по месяцам: 400 дней → 14 месяцев, сумма»."""
        if not self.resampled:
            return None
        src = PERIOD_WORDS.get(self.source_freq, PERIOD_WORDS["irregular"])
        dst = PERIOD_WORDS.get(self.freq, PERIOD_WORDS["irregular"])
        how = {"sum": "сумма", "mean": "среднее", "last": "значение на конец периода"}[self.how]
        if self.per_week:
            how = "в среднем за неделю"
        by = {"week": "по неделям", "month": "по месяцам", "quarter": "по кварталам", "year": "по годам",
              "day": "по дням"}.get(self.freq, "по периодам")
        s = (f"{by}: {count_words(self.source_points, src[0], src[1], src[2])} → "
             f"{count_words(self.points, dst[0], dst[1], dst[2])}, {how}")
        if self.partial:
            what = "неполный период не показан" if self.partial == 1 else "неполные периоды не показаны"
            s += f"; {what}" + (f" ({'; '.join(self.partial_txt)})" if self.partial_txt else "")
        return s

    @property
    def axis_title(self) -> str:
        """Подпись оси времени: после ресэмплинга — новый период («Неделя», «Месяц»), а не исходная «Дата»."""
        if self.resampled:
            return {"week": "Неделя", "month": "Месяц", "quarter": "Квартал", "year": "Год", "day": "День"}.get(
                self.freq, self.column)
        return self.column


@dataclass
class CatView:
    dim: str
    labels: list[str]
    values: list[float]
    measure: Optional[Measure]  # None — счёт строк
    extra: dict[str, list[Optional[float]]] = field(default_factory=dict)  # другие метрики по тем же категориям
    extra_measures: list[Measure] = field(default_factory=list)
    others: int = 0  # категорий в «Остальных»
    ranked: bool = True
    total: Optional[float] = None  # итог (строка «Итого» или сумма)
    total_from_row: bool = False
    distinct: int = 0  # категорий до топа
    aggregated: bool = False  # строки сложены по категории
    cut: int = 0  # уровень: показаны первые по значению, ещё `cut` категорий — не на графике («первые 12 из 40»)
    merged: int = 0  # порядковые группы: последние `merged` — одной группой («60–64 … 85 и старше»)
    low_label: Optional[str] = None  # при `cut`: категория с наименьшим значением из всего списка
    low_value: Optional[float] = None

    @property
    def n(self) -> int:
        return len(self.labels)

    @property
    def long_labels(self) -> bool:
        if not self.labels:
            return False
        lens = [len(x) for x in self.labels]
        return max(lens) > 12 or sum(lens) / len(lens) > 9

    @property
    def additive(self) -> bool:
        return self.measure is None or self.measure.additive

    @property
    def negatives(self) -> int:
        return sum(1 for v in self.values if v < 0)

    @property
    def shares(self) -> Optional[list[float]]:
        if not self.additive or self.negatives or not self.total or self.total <= 0:
            return None
        return [v / self.total * 100 for v in self.values]

    @property
    def note(self) -> Optional[str]:
        if self.others:
            return f"топ-{self.n - 1} и «Остальные {self.others}»"
        if self.cut:
            return f"первые {self.n} из {self.distinct}"
        if self.merged:
            return f"последние {self.merged} групп — одной: «{self.labels[-1]}»"
        return None

    @property
    def unit(self) -> Optional[str]:
        return self.measure.unit_text if self.measure else None


@dataclass
class Bins:
    edges: list[float]  # границы регулярных интервалов (правая включена)
    counts: list[int]
    labels: list[str]
    width: float
    open_from: Optional[float] = None  # последний интервал «больше X»

    @property
    def n(self) -> int:
        return len(self.counts)


@dataclass
class DistView:
    measure: Measure
    values: np.ndarray  # все значения
    inliers: np.ndarray
    outliers: list[float]
    bins: Bins
    entity: Optional[str]  # подпись строки («Обращение») — для «80% обращений»

    @property
    def n(self) -> int:
        return int(self.values.size)

    @property
    def low_outliers(self) -> list[float]:
        """Выбросы ниже обычных значений (быстрее, меньше)."""
        lo = float(self.inliers.min()) if self.inliers.size else 0.0
        return [v for v in self.outliers if v < lo]

    @property
    def high_outliers(self) -> list[float]:
        lo = float(self.inliers.min()) if self.inliers.size else 0.0
        return [v for v in self.outliers if v >= lo]

    @property
    def median(self) -> float:
        return float(np.median(self.values))

    def percentile(self, q: float) -> float:
        return float(np.percentile(self.values, q))

    @property
    def note(self) -> str:
        u = self.measure.unit_text
        w = fmt_num(self.bins.width) + (f" {u}" if u else "")
        s = f"{count_words(self.bins.n, 'интервал', 'интервала', 'интервалов')} по {w}"
        if self.bins.open_from is not None:
            s += f", последний — «больше {fmt_num(self.bins.open_from)}»"
        if self.outliers:
            s += f"; {count_words(len(self.outliers), 'выброс', 'выброса', 'выбросов')} — отдельно"
        return s


@dataclass
class KpiItem:
    label: str
    value: float
    value_text: str  # «1,24 млрд ₽»
    unit: Optional[str]
    change: Optional[float] = None  # в единицах change_unit
    change_unit: Optional[str] = None  # «%», «п.», «п.п.»
    prev_text: Optional[str] = None


@dataclass
class KpiView:
    items: list[KpiItem]
    period: Optional[str] = None  # «III кв. 2026»
    prev_period: Optional[str] = None  # «III кв. 2025»
    mixed_units: bool = False

    @property
    def with_change(self) -> list[KpiItem]:
        return [i for i in self.items if i.change is not None]


@dataclass
class RefView:
    label: Optional[str]  # колонка-подпись («Клиент»)
    columns: list[str]  # колонки на слайде
    rows: list[list[str]]  # строки слайда (топ)
    rest: Optional[list[str]]  # строка «Остальные 230 клиентов»
    measure: Optional[Measure]
    n: int  # строк данных
    top_n: int
    total: Optional[float]  # итог — только у суммируемой неотрицательной метрики
    top_sum: Optional[float]
    dropped: list[str]  # колонки, не вошедшие на слайд
    share_added: bool
    all_rows: list[list[str]] = field(default_factory=list)  # все строки (для разбиения)
    full_columns: list[str] = field(default_factory=list)
    order: list[int] = field(default_factory=list)  # номера строк таблицы по рангу (одно упорядочение для всего)
    labels: list[str] = field(default_factory=list)  # подписи строк по рангу
    values: list[Optional[float]] = field(default_factory=list)  # значения главной метрики по рангу
    negatives: int = 0

    @property
    def ranked(self) -> bool:
        return self.measure is not None

    @property
    def top_share(self) -> Optional[float]:
        if self.total and self.top_sum is not None and self.total > 0:
            return self.top_sum / self.total * 100
        return None

    @property
    def pages(self) -> int:
        return max(1, math.ceil(self.n / TABLE_ROWS))


@dataclass
class XYView:
    x: Measure
    y: Measure
    xs: list[float]
    ys: list[float]
    labels: list[str]
    r: float
    slope: float = 0.0  # наклон прямой МНК: изменение y на единицу x
    intercept: float = 0.0
    group: Optional[str] = None  # колонка-группа для цвета точек (≤ 5 значений)
    groups: list[str] = field(default_factory=list)  # группа каждой точки
    driver: bool = False  # X — естественная причина (часы, цена, расходы): можно говорить «каждый X — +Y»
    label_name: Optional[str] = None  # подпись точек (имя или код строки)

    @property
    def n(self) -> int:
        return len(self.xs)
