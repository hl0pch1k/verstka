"""Подготовка данных (описание решения §2.5): из таблицы и профиля — то, что пойдёт на слайд.

- Ряд по времени (`TimeView`): периоды подряд с частотой оси, пропуски — `None` (линия с разрывами, а не ноль),
  ресэмплинг больше 36 точек (дни → недели → месяцы → кварталы → годы: сумма для потоков, среднее для уровней,
  последнее значение для остатков вроде числа клиентов), длинный формат «период × категория» — ряд на категорию.
- Категории (`CatView`): сумма или среднее по категории, ранжирование (порядковые подписи «0–30», «1 курс» — как
  в файле), топ-N и «Остальные» больше 12 категорий, доли от итога.
- Распределение (`DistView`): интервалы по Фридману–Диаконису с «круглой» шириной, 7–12 интервалов (5–12 на малых
  выборках), открытый последний «больше X»; выбросы — отдельно.
- Ключевые показатели (`KpiView`): значение, единица и изменение каждой строки («1,24 млрд ₽», «+23%», «+6 п.»).
- Справочник (`RefView`): топ-10 по главной метрике и строка «Остальные 230 …», до 5 колонок, доля посчитана;
  разбиение на слайды по 10 строк, если агрегация теряет смысл (не больше 3 слайдов).
- Взаимосвязь (`XYView`): пары значений и коэффициент корреляции.

Строки итога (`Table.totals`, если чтение их отметило, или подпись «Итого/Всего») в графики не идут — по ним
считаются доли от итога. Всё детерминировано и без модели."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import Any, Optional

import numpy as np

from verstka.data.parse import is_total_label, parse_quantity, period_iso, period_parts, quantity, split_unit
from verstka.data.words import (
    PERIOD_WORDS, count_words, fmt_exact, fmt_num, fmt_value, head_word, is_counter, join_and, lower_first,
    metric_phrase, period_label, period_text, phrase, plural, stems_match, upper_first,
)
from verstka.schemas.data import ColumnProfile, DatasetProfile, Table

__all__ = [
    "MAX_POINTS", "MAX_CATS", "TOP_N", "TABLE_ROWS", "MAX_SLIDES",
    "Measure", "SeriesV", "TimeView", "CatView", "Bins", "DistView", "KpiItem", "KpiView", "RefView", "XYView", "Data",
    "histogram_bins", "nice_width", "resample_freq", "unit_short", "NICE_MINUTES", "TO_MINUTES", "INDEX_NAME",
    "kpi_change",
]

MAX_POINTS = 36  # больше точек — ресэмплинг к более крупному периоду
MAX_CATS = 12  # больше категорий — топ и «Остальные»
TOP_N = 10  # строк справочника на слайде
TABLE_ROWS = 10
MAX_SLIDES = 3  # больше слайдов на один датасет — уже не разбиение, а агрегация
MAX_SERIES = 5

_CHANGE = re.compile(r"изменени|(?:^|[^а-яё])(?:при)?рост|динамик|разниц|отклонени|к прошл|г/г|yoy|дельта|δ", re.I)
_LEVEL = re.compile(
    r"nps|csat|индекс|средн|рейтинг|оценк|балл|конверси|курс|цен[аы]|ставк|температур|доля|коэффициент|уровень|"
    r"процент|медиан|время|срок|скорост|длительн|возраст|удовлетвор|загрузк|маржа|маржин|рентабельн|плотност|чек",
    re.I,
)
_STOCK = re.compile(r"клиент|пользовател|сотрудник|абонент|подписчик|остат|баланс|численност|штат|запас|база", re.I)
# индексы и доли: изменение — в пунктах, а не в процентах («NPS +6 п.», «конверсия +0,5 п.п.»)
# индексы и оценки по шкале — изменение в пунктах; проверяется по главному слову названия и только без единицы
# (у денег и счёта изменение — всегда в процентах: «Оценка стоимости бизнеса, млн ₽» — не индекс)
INDEX_NAME = re.compile(r"^(?:nps|enps|csat|ces|индекс\w*|рейтинг\w*|оценк\w*|балл\w*|доля|доли|конверси\w*|"
                        r"удовлетвор\w*|лояльн\w*)$", re.I)
# естественные причины для оси X рассеяния: время и усилия, цена и деньги на входе, дозы и условия опыта
_DRIVER = re.compile(r"час|подготов|занят|трениров|стаж|опыт работы|возраст|цен[аы]|стоимост|тариф|скидк|расход|"
                     r"затрат|инвестиц|реклам|бюджет|доз|концентрац|температур|давлени|площад|расстояни|время|"
                     r"длительн|частот|количество часов", re.I)
# оценочные метрики — главнее счёта размера («Средний балл» важнее «Учеников»)
_EVAL_NAME = re.compile(r"балл|оценк|рейтинг|выручк|доход|прибыл|качеств|успеваем|удовлетвор|nps|конверси|удержан|"
                        r"результат|эффективн|продаж", re.I)
_TIME_NAME = {
    "мин": "мин", "минут": "мин", "минуты": "мин", "час": "ч", "часов": "ч", "часа": "ч", "ч": "ч", "дней": "дн.",
    "день": "дн.", "дня": "дн.", "дн": "дн.", "сек": "с", "секунд": "с",
}
# длительности: единица → минут в ней; «круглые» значения в минутах (ширина интервала гистограммы, порог «за 2 часа»)
TO_MINUTES = {"мин": 1.0, "мин.": 1.0, "минут": 1.0, "ч": 60.0, "ч.": 60.0, "час": 60.0, "часов": 60.0,
              "дн.": 1440.0, "дн": 1440.0, "дней": 1440.0, "с": 1 / 60, "сек": 1 / 60, "с.": 1 / 60}
NICE_MINUTES = [1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 360, 480, 720, 1080, 1440, 2880, 4320, 10080]
_CODE = re.compile(r"^[A-Za-zА-Яа-яЁё]{0,6}[-_/#№.]?\d{1,12}[A-Za-z]?$")
_ORDINAL_LABEL = re.compile(r"^\s*(?:до|от|свыше|более|больше|менее|меньше|<|>|≤|≥)?\s*\d")


def unit_short(unit: Optional[str]) -> Optional[str]:
    return unit or None


def _common_suffix(names: list[str]) -> str:
    """Общее дополнение после запятой: «Scopus, статей», «РИНЦ, статей» → «статей»."""
    tails = {n.split(",", 1)[1].strip().lower() if "," in n else "" for n in names}
    return next(iter(tails)) if len(tails) == 1 and "" not in tails else ""


_PLAN = re.compile(r"(?:^|[^а-яёa-z])(?:план\w*|plan|цел[ьи]|target|прогноз)(?:[^а-яёa-z]|$)", re.I)
_FACT = re.compile(r"(?:^|[^а-яёa-z])(?:факт\w*|fact|actual|исполнен\w*|выполнен\w*)(?:[^а-яёa-z]|$)", re.I)


def _period_name(name: str) -> bool:
    """Колонка названа периодом («2025», «Выручка 2026», «III кв. 2026», «Январь»)."""
    return bool(re.search(r"(?:^|\D)(?:19|20)\d\d(?:\D|$)", name)) or period_parts(name.strip()) is not None


def _period_key(name: str) -> tuple[int, int]:
    """Порядок колонок-периодов: год и номер внутри года из названия («Выручка 2026» → (2026, 0))."""
    y = re.search(r"(?:19|20)\d\d", name)
    pp = period_parts(name.strip())
    if pp is not None:
        return pp[1], 0
    return (int(y.group(0)) if y else 0), 0


def _parts_ok(group: list[Measure]) -> bool:
    """Годы и периоды, план и факт — не части одного целого."""
    if any(_period_name(x.name) for x in group):
        return False
    return not (any(_PLAN.search(x.name) for x in group) and any(_FACT.search(x.name) for x in group))


def _kind(m: Measure) -> str:
    """Род величины: деньги, проценты, индекс, счётчик («Клиентов») или просто число."""
    if m.type == "money":
        return "money"
    if m.type == "percent":
        return "percent"
    if INDEX_NAME.search(head_word(m.name) or ""):
        return "index"
    if is_counter(m.name):
        return "counter"
    return "plain"


def _num(cell: Any) -> Optional[float]:
    """Число ячейки с множителем («1,24 млрд» → 1.24e9, «46 %» → 46, «(15)» → −15); None — не число или пусто."""
    if cell is None or isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if math.isfinite(cell) else None
    q = quantity(" ".join(str(cell).split()))
    return None if q is None else q.full


def is_index(name: str) -> bool:
    """Безразмерный индекс или оценка по шкале по главному слову названия: «NPS», «Индекс удовлетворённости»,
    «Средний балл»."""
    return bool(INDEX_NAME.match(head_word(split_unit(name)[0] or name) or ""))


def kpi_change(label: str, cur: float, prev: float, unit: Optional[str]) -> Optional[tuple[float, str]]:
    """Изменение показателя. Сначала единица: проценты — в п.п.; любая другая единица (деньги, люди, штуки) — в %;
    без единицы — индекс или оценка по шкале (NPS, балл) в пунктах, остальное в %."""
    u = unit or split_unit(label)[1]
    if u == "%" or (u or "").startswith("п.п"):
        return cur - prev, "п.п."
    if not u and is_index(label):
        return cur - prev, "п."
    if prev > 0:
        return (cur / prev - 1) * 100, "%"
    return None

def _time_unit_of(name: str, unit: Optional[str]) -> Optional[str]:
    """Единица длительности колонки: из единицы («мин») или из имени («Минут до ответа», «Время, ч»)."""
    if unit:
        u = unit.strip().lower()
        return u if u in TO_MINUTES else None
    first = re.split(r"[\s,()]+", name.strip().lower())[0] if name.strip() else ""
    return _TIME_NAME.get(first)


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


# ── время ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
_FREQ_ORDER = ["hour", "day", "week", "month", "quarter", "year"]


def _to_freq(gran: str, ordinal: int, freq: str) -> Optional[int]:
    """Номер периода `gran` → номер периода частоты `freq` (не мельче исходного)."""
    if gran == freq:
        return ordinal
    if gran == "hour":
        return _to_freq("day", ordinal // 24, freq) if freq != "day" else ordinal // 24
    if gran == "day":
        d = date.fromordinal(ordinal)
        if freq == "week":
            return (ordinal - 1) // 7
        if freq == "month":
            return d.year * 12 + d.month - 1
        if freq == "quarter":
            return d.year * 4 + (d.month - 1) // 3
        if freq == "year":
            return d.year
    if gran == "week":
        d = date.fromordinal(ordinal * 7 + 1)
        return _to_freq("day", d.toordinal(), freq) if freq != "week" else ordinal
    if gran == "month":
        if freq == "quarter":
            return (ordinal // 12) * 4 + (ordinal % 12) // 3
        if freq == "year":
            return ordinal // 12
    if gran == "quarter" and freq == "year":
        return ordinal // 4
    return None


def _period_days(target: str, k: int) -> list[int]:
    """Дни (порядковые номера) периода `target` с номером `k`."""
    if target == "day":
        return [k]
    if target == "week":
        return [k * 7 + 1 + d for d in range(7)]
    if target == "month":
        y, mth = divmod(k, 12)
        first = date(y, mth + 1, 1)
        nxt = date(y + (mth + 1) // 12, (mth + 1) % 12 + 1, 1)
        return list(range(first.toordinal(), nxt.toordinal()))
    if target == "quarter":
        y, q = divmod(k, 4)
        return [d for mm in range(3) for d in _period_days("month", y * 12 + q * 3 + mm)]
    if target == "year":
        return list(range(date(k, 1, 1).toordinal(), date(k + 1, 1, 1).toordinal()))
    return []


def _calendar_count(gran: str, target: str, k: int) -> int:
    """Сколько исходных точек `gran` в полном периоде `target`: 28–31 день месяца, 7 дней недели, 24 часа суток,
    понедельники недель месяца, 3 месяца квартала, 12 месяцев года, 4 квартала года. 0 — неизвестно."""
    if gran == "month":
        return {"quarter": 3, "year": 12}.get(target, 0)
    if gran == "quarter":
        return 4 if target == "year" else 0
    days = _period_days(target, k)
    if not days:
        return 0
    if gran == "day":
        return len(days)
    if gran == "hour":
        return 24 * len(days)
    if gran == "week":
        return sum(1 for d in days if date.fromordinal(d).weekday() == 0)
    return 0


def resample_freq(freq: str, points: int, span: dict[str, int]) -> str:
    """Самая мелкая частота не мельче исходной, при которой точек ≤ 36."""
    if points <= MAX_POINTS:
        return freq
    start = _FREQ_ORDER.index(freq) if freq in _FREQ_ORDER else 1
    for f in _FREQ_ORDER[start + 1:]:
        if span.get(f, 10**9) <= MAX_POINTS:
            return f
    return "year"


def _cell_time(cell: Any) -> Optional[tuple[str, int]]:
    if isinstance(cell, bool):
        return None
    if isinstance(cell, int) and 1900 <= cell <= 2100:
        return "year", cell
    if isinstance(cell, float) and cell.is_integer() and 1900 <= cell <= 2100:
        return "year", int(cell)
    if isinstance(cell, str):
        s = " ".join(cell.split())
        return period_parts(s, with_time=True) if s else None
    return None


def _iso(freq: str, o: int) -> str:
    return period_iso("day" if freq == "irregular" else freq, o)


# ── главный объект ────────────────────────────────────────────────────────────────────────────────────────────────────
class Data:
    """Датасет для анализа: таблица, профиль, метрики, подписи и подготовленные виды (лениво)."""

    def __init__(self, table: Table, profile: DatasetProfile, subject: tuple[str, ...] = ()):
        self.table = table
        self.profile = profile
        self.subject = subject
        cols = profile.columns
        self.cols: list[ColumnProfile] = cols
        self.ncols = len(cols)
        self.totals: set[int] = self._total_rows()
        self.rows_idx = [i for i in range(len(table.rows)) if i not in self.totals]
        self.n = len(self.rows_idx)
        self.measures: list[Measure] = [self._measure(j, c) for j, c in enumerate(cols) if c.role == "metric"]
        self.measures = [m for m in self.measures if m.present]
        self.codes = {j for j, c in enumerate(cols) if c.role in ("dimension", "text") and self._code_like(j)}
        self.dims = [j for j, c in enumerate(cols)
                     if c.role == "dimension" and c.type in ("category", "boolean") and j not in self.codes]
        self.label = self._label_col()
        self.id_col = next((j for j, c in enumerate(cols) if c.role == "id"), None)
        if self.id_col is None and self.codes:
            self.id_col = min(self.codes)
        self.time_col = next((j for j, c in enumerate(cols) if profile.time_axis and c.name == profile.time_axis.column),
                             None)

    # ── строки и колонки
    def _total_rows(self) -> set[int]:
        marked = getattr(self.table, "totals", None) or []
        out = {int(i) for i in marked if isinstance(i, int) and 0 <= i < len(self.table.rows)}
        if out:
            return out
        for i, r in enumerate(self.table.rows):
            if any(is_total_label(v) for v in r[:2]):
                out.add(i)
        return out if len(out) < len(self.table.rows) else set()

    def row_unit(self, i: int) -> Optional[str]:
        """Единица строки таблицы показателей по строкам (`Table.row_units`): «чел.», «%», «млн ₽»."""
        ru = getattr(self.table, "row_units", None) or []
        return ru[i] if i < len(ru) else None

    def cell(self, i: int, j: int) -> Any:
        r = self.table.rows[i]
        return r[j] if j < len(r) else None

    def column_cells(self, j: int) -> list[Any]:
        return [self.cell(i, j) for i in self.rows_idx]

    def text(self, i: int, j: int) -> str:
        v = self.cell(i, j)
        if v is None:
            return ""
        if isinstance(v, bool):
            return "да" if v else "нет"
        if isinstance(v, (int, float)):
            return fmt_num(float(v))
        return " ".join(str(v).split())

    def _measure(self, j: int, c: ColumnProfile) -> Measure:
        cells = [self.cell(i, j) for i in range(len(self.table.rows))]
        units = set()
        vals: list[Optional[float]] = []
        raw: list[Optional[float]] = []
        row_units: list[Optional[str]] = []
        for i, v in enumerate(cells):
            if i in self.totals:
                vals.append(None)
                raw.append(None)
                row_units.append(None)
                continue
            q = None
            if isinstance(v, str):
                q = parse_quantity(v)
                if q is not None and q[1]:
                    units.add(q[1])
                elif q is not None:
                    units.add("")
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                units.add("")
            vals.append(_num(v))
            raw.append(q[0] if q is not None else vals[-1])
            row_units.append(q[1] if q is not None else None)
        mixed = len(units) > 1
        name = c.name
        lname = name.lower()
        signed = sum(1 for v in cells if isinstance(v, str) and v.strip().startswith("+"))
        change = bool(_CHANGE.search(lname)) or signed >= max(1, len([v for v in cells if v is not None]) // 2)
        level = (c.type == "percent" and not change) or bool(_LEVEL.search(lname))
        unit = c.unit
        if mixed:
            unit = None
        tu = _time_unit_of(name, unit)
        # остаток (число клиентов на конец месяца) — только если остаток и есть главное слово названия («Клиентов»,
        # «Активные клиенты»); «Выручка от клиентов» — поток денег, деньги остатком не бывают
        head = name if is_counter(name) else head_word(name)
        stock = c.type != "money" and bool(_STOCK.search(head)) and not level
        return Measure(j=j, name=name, unit=unit, type=c.type, values=vals, change=change, level=level and not change,
                       stock=stock, mixed=mixed, time_unit=tu, raw=raw, row_units=row_units)

    def _code_like(self, j: int) -> bool:
        """Колонка кодов («SUP-48213», «A-12», «Z1000»): у каждой строки свой, буквы и цифры без пробелов — это
        идентификатор, а не подпись и не категория."""
        vals = [v for v in (self.cell(i, j) for i in self.rows_idx) if isinstance(v, str) and v.strip()]
        if len(vals) < 3 or len(set(vals)) < len(vals):
            return False
        ok = sum(1 for v in vals if _CODE.match(v.strip()))
        return ok >= 0.9 * len(vals)

    def _label_col(self) -> Optional[int]:
        """Подпись строки: текст или категория, у каждой строки своя (клиент, регион, показатель)."""
        best = None
        for j, c in enumerate(self.cols):
            if c.role not in ("text", "dimension") or c.type in ("boolean",) or j in self.codes:
                continue
            if c.type == "text" and c.distinct and any(isinstance(s, str) and len(s) > 60 for s in c.samples):
                continue
            vals = [self.text(i, j) for i in self.rows_idx]
            filled = [v for v in vals if v]
            if filled and len(set(filled)) == len(filled) and len(filled) >= max(1, int(0.9 * self.n)):
                best = j
                break
        return best

    # ── метрики
    def measure(self, name: str) -> Optional[Measure]:
        return next((m for m in self.measures if m.name == name), None)

    @cached_property
    def main(self) -> Optional[Measure]:
        """Главная метрика: та, что названа целью; иначе деньги; иначе первая не-изменение; иначе первая."""
        ms = self.measures
        if not ms:
            return None
        if self.subject:
            for m in ms:
                if stems_match(self.subject, m.name):
                    return m
        def latest(m: Measure) -> Measure:
            """Колонки-периоды («Выручка 2025 · Выручка 2026»): главная — последний период."""
            if not _period_name(m.name):
                return m
            sib = [x for x in ms if _period_name(x.name) and (x.unit or "") == (m.unit or "") and not x.change]
            return max(sib, key=lambda x: (_period_key(x.name), x.j)) if len(sib) >= 2 else m

        for pred in (
            lambda m: m.type == "money" and not m.change and not m.mixed,
            # оценочная метрика (балл, качество, выручка) главнее счёта размера (учеников, пользователей)
            lambda m: not m.change and not m.mixed and bool(_EVAL_NAME.search(m.name)),
            lambda m: not m.change and not m.mixed and not is_counter(m.name),
            lambda m: not m.change and not m.mixed,
            lambda m: not m.change,
        ):
            for m in ms:
                if pred(m):
                    return latest(m)
        return ms[0]

    @cached_property
    def parts_measure(self) -> Optional[Measure]:
        """Колонка долей (сумма ≈ 100) — если профиль нашёл части целого."""
        if not self.profile.parts_of_whole:
            return None
        for m in self.measures:
            if m.type == "percent" and not m.change:
                v = m.present
                s = sum(v)
                if v and all(x >= 0 for x in v) and (95 <= s <= 105 or 0.95 <= s <= 1.05):
                    return m
        return None

    @cached_property
    def total_metric(self) -> Optional[Measure]:
        """Колонка-итог: из профиля (`total_column` — «Всего», равная сумме частей), иначе по названию («Всего»,
        «Итого», «Total»): сумма серий, а не ещё одна серия."""
        name = getattr(self.profile, "total_column", None)
        if name:
            m = self.measure(name)
            if m is not None:
                return m
        return next((m for m in self.measures if is_total_label(m.name)), None)

    @cached_property
    def funnel(self) -> bool:
        """Воронка: колонка этапов («Этап/Стадия/Шаг/Воронка») и значения строго убывают по порядку файла. Одного
        убывания мало — так выглядит любая таблица, отсортированная по убыванию. Этапы — не части одного целого: их не
        складывают и не делят на сумму."""
        m, j = self.main, self.label
        if m is None or j is None or not m.additive:
            return False
        vals = [m.values[i] for i in self.rows_idx]
        if len(vals) < 3 or any(v is None for v in vals):
            return False
        dec = all(a > b for a, b in zip(vals, vals[1:]))  # type: ignore[operator]
        named = bool(re.search(r"этап|стади|шаг|воронк|funnel|stage", self.cols[j].name, re.I))
        return dec and named

    def _group_of(self, j: int) -> Optional[str]:
        groups = getattr(self.table, "column_groups", None) or []
        return groups[j] if j < len(groups) else None

    @cached_property
    def part_group(self) -> list[Measure]:
        """Части одного целого — только по признакам в данных:
        - профиль нашёл колонку-итог, равную сумме частей (`part_columns`);
        - чтение отметило группу двухэтажной шапки (`column_groups`: «Форма обучения» над «Бюджет · Платное ·
          Целевое») — берётся вся группа, а не только похожие на главную;
        - в каждой строке колонки одной единицы складываются в 100 (ответы по шкале, доли в процентах).
        Годы и периоды, план и факт — не части никогда. Без признака — пусто: тогда сравнение, а не состав."""
        ms = [m for m in self.measures if not m.change and not m.mixed and m is not self.total_metric]
        parts = [self.measure(nm) for nm in (getattr(self.profile, "part_columns", None) or [])]
        parts = [x for x in parts if x is not None and not x.change]
        if len(parts) >= 2 and _parts_ok(parts):
            return sorted(parts, key=lambda x: x.j)
        m = self.main
        if m is not None and self._group_of(m.j):
            g = self._group_of(m.j)
            grp = [x for x in ms if self._group_of(x.j) == g and (x.unit or "") == (m.unit or "")]
            if len(grp) >= 2 and _parts_ok(grp) and all(x.additive and x.nonneg for x in grp):
                return sorted(grp, key=lambda x: x.j)
        # строки по 100: все колонки одной единицы (без единицы или %) от 0 до 100, сумма в каждой строке ≈ 100
        by_unit: dict[str, list[Measure]] = {}
        for x in ms:
            if (x.unit or "%") == "%" and x.present and min(x.present) >= 0 and max(x.present) <= 100:
                by_unit.setdefault(x.unit or "", []).append(x)
        for grp in by_unit.values():
            if len(grp) < 3 or not _parts_ok(grp):
                continue
            sums = []
            for i in self.rows_idx:
                vals = [x.values[i] for x in grp]
                if all(v is not None for v in vals):
                    sums.append(sum(vals))  # type: ignore[arg-type]
            if len(sums) >= 2 and all(97 <= v <= 103 for v in sums):
                return sorted(grp, key=lambda x: x.j)
        return []

    @cached_property
    def plan_fact(self) -> Optional[tuple[Measure, Measure]]:
        """Пара «план — факт» (цель — исполнение) одной единицы; колонка «Исполнение, %» — не факт, а их отношение."""
        cands = [m for m in self.measures if not m.change and not m.mixed and m.type != "percent"]
        plans = [m for m in cands if _PLAN.search(m.name)]
        facts = [m for m in cands if _FACT.search(m.name) and m not in plans]
        for pl in plans:
            for fa in facts:
                if (pl.unit or "") == (fa.unit or ""):
                    return pl, fa
        return None

    @cached_property
    def parallel(self) -> list[Measure]:
        """Ряды одного рода с главной: части целого (`part_group`); план и факт; на оси времени — колонки одной единицы
        и одного рода (без единицы тоже: «ИТ · Продажи · Маркетинг» по месяцам); по категориям — колонки с общим
        дополнением («…, статей») или колонки-периоды («Выручка 2025 · Выручка 2026») — рядом, а не в сумме."""
        m = self.main
        if m is None or m.change or m.mixed:
            return []
        if self.part_group and m in self.part_group:
            return list(self.part_group)
        pf = self.plan_fact
        if pf is not None and m in pf:
            return list(pf)
        group = [m]
        for x in self.measures:
            if x is m or x.change or x.mixed or x is self.total_metric:
                continue
            if (x.unit or "") != (m.unit or "") or _kind(x) != _kind(m):
                continue
            if self.time_col is not None:
                group.append(x)
            elif _common_suffix([m.name, x.name]) or (_period_name(m.name) and _period_name(x.name)):
                group.append(x)
        group.sort(key=lambda x: x.j)
        return group[:MAX_SERIES] if len(group) >= 2 else []

    @cached_property
    def series_names(self) -> dict[str, str]:
        """Имена рядов для легенды: без общего дополнения-единицы («Scopus, статей» → «Scopus») и без отмеченной
        чтением группы шапки в начале; угаданный общий префикс не отрезается."""
        g = self.parallel
        if not g:
            return {}
        suf = _common_suffix([x.name for x in g])
        out = {}
        for x in g:
            nm = x.name
            grp = self._group_of(x.j)
            if grp and nm.lower().startswith(grp.lower() + " "):
                nm = nm[len(grp):].strip()
            if suf and "," in nm:
                nm = nm.rsplit(",", 1)[0].strip()
            out[x.name] = upper_first(nm) if nm else x.name
        return out

    @cached_property
    def composition(self) -> bool:
        """Ряды — части одного целого, только по признаку в данных (`part_group`)."""
        return bool(self.part_group) and self.main in self.part_group

    @cached_property
    def group_name(self) -> Optional[str]:
        """Группа рядов из двухэтажной шапки (`Table.column_groups`: «Форма обучения»); None — чтение группу не отметило."""
        g = self.parallel
        names = {self._group_of(x.j) for x in g}
        if g and len(names) == 1 and None not in names:
            return next(iter(names))
        return None

    def parent_of(self, j: int) -> Optional[int]:
        """Родитель колонки в иерархии профиля («Кафедра → Институт»), если у него 2–12 значений."""
        name = self.cols[j].name
        for child, parent in self.profile.hierarchies:
            if child == name:
                pj = next((k for k, c in enumerate(self.cols) if c.name == parent), None)
                if pj is not None and 2 <= self.cols[pj].distinct <= MAX_CATS:
                    return pj
        return None

    @cached_property
    def shares(self) -> Optional[tuple[CatView, list[float]]]:
        """Части целого: все категории (без «Остальных») и их доли в %. Колонка долей, если она есть (доли 0–1 —
        в проценты), иначе доли суммируемой неотрицательной метрики от итога. Порядок — как у `cat_view`
        (ранжированный или порядковый): лидера ищут по значению, не по месту."""
        parts = self.parts_measure
        cv = self.cat_view(parts if parts is not None else self.main, top=10**6)
        if cv is None:
            return None
        if parts is not None:
            s = sum(cv.values) or 1.0
            scale = 100.0 / s if 0.95 <= s <= 1.05 else 1.0
            return cv, [v * scale for v in cv.values]
        sh = cv.shares
        return (cv, sh) if sh else None

    @cached_property
    def mixed_units(self) -> bool:
        return any(m.mixed for m in self.measures)

    @cached_property
    def entity(self) -> Optional[str]:
        """Что за строка (подпись или id): «Клиент», «Обращение»."""
        for j in (self.label, self.id_col):
            if j is not None:
                return self.cols[j].name
        return None

    # ── виды
    @cached_property
    def time(self) -> Optional[TimeView]:
        return self.time_view(self.main)

    def time_view(self, m: Optional[Measure], max_points: int = MAX_POINTS) -> Optional[TimeView]:
        ax = self.profile.time_axis
        if ax is None or self.time_col is None:
            return None
        tj = self.time_col
        cells = [(i, _cell_time(self.cell(i, tj))) for i in self.rows_idx]
        cells = [(i, t) for i, t in cells if t is not None]
        if not cells:
            return None
        grans = {t[0] for _, t in cells}
        if "hour" in grans:
            # почасовой ряд: полночь чтение отдаёт днём («2026-01-02») — это час 00:00 того же ряда
            cells = [(i, ("hour", t[1] * 24) if t[0] == "day" else t) for i, t in cells]
            grans = {t[0] for _, t in cells}
        gran = "day" if "day" in grans else sorted(grans, key=lambda g: _FREQ_ORDER.index(g) if g in _FREQ_ORDER else 0)[0]
        if "hour" in grans:
            gran = "hour"
        cells = [(i, t) for i, t in cells if t[0] == gran]
        freq = ax.freq if ax.freq in _FREQ_ORDER else gran
        if _FREQ_ORDER.index(freq) < _FREQ_ORDER.index(gran):
            freq = gran
        irregular = ax.freq == "irregular"
        keyed = []
        for i, (g, o) in cells:
            k = o if irregular else _to_freq(g, o, freq)
            if k is not None:
                keyed.append((i, k))
        if not keyed:
            return None
        src_freq = "day" if irregular else freq
        uniq = sorted({k for _, k in keyed})
        if irregular:
            src_points = len(uniq)
        else:
            src_points = uniq[-1] - uniq[0] + 1
        partial = 0

        def how_of(mm: Optional[Measure]) -> str:
            return "sum" if mm is None else ("mean" if mm.change else mm.how)

        # ресэмплинг; почасовой ряд до недели (168 точек) остаётся часами — суточный цикл виден только так
        target = src_freq
        limit = 168 if src_freq == "hour" else max_points
        if src_points > limit:
            spans = {}
            for f in _FREQ_ORDER[_FREQ_ORDER.index(src_freq) + 1:]:
                ks = [_to_freq(gran, t[1], f) for _, t in cells]
                ks = [k for k in ks if k is not None]
                if ks:
                    spans[f] = max(ks) - min(ks) + 1
            target = resample_freq(src_freq, src_points, spans)
            keyed = [(i, _to_freq(gran, t[1], target)) for i, t in cells]
            keyed = [(i, k) for i, k in keyed if k is not None]
            uniq = sorted({k for _, k in keyed})
            irregular = False
        partial_txt: list[str] = []
        if target != src_freq and how_of(m) == "sum":
            # период полон только по календарю (все дни недели, месяца, квартала): сумма за неполный крайний период
            # занижена — такой период не показывается и не участвует в выводе
            per: dict[int, set] = {}
            for _, t in cells:
                k = _to_freq(gran, t[1], target)
                if k is not None:
                    per.setdefault(k, set()).add(t[1])
            drop = set()
            for k in {uniq[0], uniq[-1]}:
                need = _calendar_count(gran, target, k)
                have = len(per.get(k, ()))
                if need and have < need and len(uniq) > 2:
                    drop.add(k)
                    unit_w = {"day": ("день", "дня", "дней"), "hour": ("час", "часа", "часов"),
                              "week": ("неделя", "недели", "недель"), "month": ("месяц", "месяца", "месяцев"),
                              "quarter": ("квартал", "квартала", "кварталов")}.get(gran, ("точка", "точки", "точек"))
                    partial_txt.append(f"{period_text(_iso(target, k))} — {have} из {count_words(need, *unit_w)}")
            if drop:
                keyed = [(i, k) for i, k in keyed if k not in drop]
                uniq = [k for k in uniq if k not in drop]
                partial = len(drop)
        if irregular or len(uniq) == 2:
            order = uniq
        else:
            order = list(range(uniq[0], uniq[-1] + 1))
        pos = {k: p for p, k in enumerate(order)}
        out_freq = target if not (ax.freq == "irregular" and target == src_freq) else "irregular"
        iso_freq = "day" if out_freq == "irregular" else out_freq
        periods = [_iso(iso_freq, k) for k in order]
        labels = [period_label(p, out_freq) for p in periods]

        # ряды: длинный формат — по категориям, иначе метрика (и метрики в тех же единицах)
        dupes = len(keyed) > len({k for _, k in keyed})
        cat_moves: dict[str, tuple[float, float]] = {}
        series: list[SeriesV] = []
        dim_name = None
        others = 0
        measures = [m] if m is not None else []
        how = m.how if m is not None else "sum"
        if m is not None and m.change:
            how = "mean"

        def agg(vals: list[float], how_: str) -> Optional[float]:
            if not vals:
                return None
            if how_ == "sum":
                return float(sum(vals))
            if how_ == "last":
                return float(vals[-1])
            return float(sum(vals) / len(vals))

        if dupes and self.dims and m is not None:
            dj = next((j for j in self.dims if 2 <= self.cols[j].distinct <= 12), None)
            if dj is not None:
                dim_name = self.cols[dj].name
                groups: dict[str, dict[int, list[float]]] = {}
                g_units: dict[str, list[str]] = {}
                for i, k in keyed:
                    v = m.raw[i] if m.mixed else m.values[i]
                    lab = self.text(i, dj)
                    if v is None or not lab:
                        continue
                    groups.setdefault(lab, {}).setdefault(pos[k], []).append(v)
                    if m.mixed:
                        g_units.setdefault(lab, []).append(m.row_units[i] or "")
                tot = {g: sum(sum(x) for x in d.values()) for g, d in groups.items()}
                for g, dd in groups.items():
                    seq = [agg(dd[p_], how) for p_ in sorted(dd)]
                    seq = [v for v in seq if v is not None]
                    if len(seq) >= 2:
                        cat_moves[g] = (seq[0], seq[-1])
                names = sorted(groups, key=lambda g: (-tot[g], g)) if m.additive else list(groups)
                keep = names
                if len(names) > MAX_SERIES:
                    keep = names[: MAX_SERIES - 1]
                    others = len(names) - len(keep)
                for g in keep:
                    vals = [agg(groups[g].get(p, []), how) for p in range(len(order))]
                    gu = m.unit_text
                    if m.mixed and g_units.get(g):
                        gu = max(set(g_units[g]), key=g_units[g].count) or None
                    series.append(SeriesV(g, gu, vals))
                if others:
                    # «Остальные N»: сначала значение каждой категории за период (сумма, последнее, среднее),
                    # потом сумма по категориям (уровень — среднее по ним, это и сказано в подписи)
                    rest_vals = []
                    for p_ in range(len(order)):
                        per_cat = [agg(groups[g].get(p_, []), how) for g in names[len(keep):]]
                        per_cat = [v for v in per_cat if v is not None]
                        if not per_cat:
                            rest_vals.append(None)
                        elif m.additive or m.stock:
                            rest_vals.append(float(sum(per_cat)))
                        else:
                            rest_vals.append(float(sum(per_cat) / len(per_cat)))
                    label = f"Остальные {others}" if (m.additive or m.stock) else f"Остальные {others} (среднее)"
                    series.append(SeriesV(label, m.unit_text, rest_vals))
        if not series:
            if m is None:
                counts = [0] * len(order)
                for _, k in keyed:
                    counts[pos[k]] += 1
                series = [SeriesV("Число строк", None, [float(c) for c in counts])]
                how = "sum"
            else:
                # метрики одного рода (Scopus и РИНЦ, план и факт) — каждая своим рядом
                if m in self.parallel:
                    measures = list(self.parallel)
                for mm in measures:
                    buckets: dict[int, list[float]] = {}
                    for i, k in keyed:
                        v = mm.values[i]
                        if v is not None:
                            buckets.setdefault(pos[k], []).append(v)
                    h = how if mm is m else mm.how
                    nm = self.series_names.get(mm.name, mm.name) if len(measures) > 1 else mm.name
                    series.append(SeriesV(nm, mm.unit_text, [agg(buckets.get(p, []), h) for p in range(len(order))]))
        if len(series) > 1 and not dim_name:
            # главный ряд — первым (тот, что назван целью или первый по порядку)
            series.sort(key=lambda sv: sv.name != self.series_names.get(m.name, m.name))
        meas = m if m is not None else Measure(j=-1, name="Число строк", unit=None, type="number",
                                               values=[1.0] * len(self.table.rows))
        return TimeView(
            column=self.cols[tj].name, freq=out_freq, periods=periods, labels=labels, series=series, measure=meas,
            source_freq="irregular" if ax.freq == "irregular" else src_freq, source_points=src_points, how=how,
            dim=dim_name, others=others, column_type=self.cols[tj].type, partial=partial, partial_txt=partial_txt,
            cat_moves=cat_moves,
        )

    @cached_property
    def cats(self) -> Optional[CatView]:
        if self.composition and self._rows100:
            return self.cat_view(self.main, rank=False)  # строки по 100: порядок — как в файле
        return self.cat_view(self.main, rank_with=self.parallel if self.composition else None)

    @cached_property
    def _rows100(self) -> bool:
        g = self.part_group
        sums = [sum(x.values[i] for x in g) for i in self.rows_idx if all(x.values[i] is not None for x in g)]
        return bool(g) and bool(sums) and all(97 <= v <= 103 for v in sums)

    def cat_dim(self) -> Optional[int]:
        """Колонка категорий для сравнения: подпись строки (≤ 60, если есть метрика) или измерение с повторами (2–60
        значений). Без метрики сравнивают число строк — подпись, у которой каждая строка своя, для этого не годится."""
        if self.label is not None and self.n <= 60 and self.main is not None:
            parent = self.parent_of(self.label) if self._rollable else None
            return parent if parent is not None and self.n > MAX_CATS - 4 else self.label
        cands = [j for j in self.dims if 2 <= self.cols[j].distinct <= 60]
        if self.subject:
            for j in cands:
                if stems_match(self.subject, self.cols[j].name):
                    return j
        if not cands:
            return None
        # самое «крупное» деление, которое ещё различает строки: меньше всего значений, но больше одного
        best = sorted(cands, key=lambda j: (self.cols[j].distinct > 12, j))[0]
        parent = self.parent_of(best) if self._rollable else None
        return parent if parent is not None and self.cols[best].distinct > MAX_CATS - 4 else best

    @property
    def _rollable(self) -> bool:
        """К родителю иерархии сворачивается только суммируемая метрика (сумма по кафедрам); средний чек городов не
        складывается, а среднее средних — неверное число."""
        m = self.main
        return m is None or m.additive or m.stock

    def cat_view(self, m: Optional[Measure], top: int = MAX_CATS, dim: Optional[int] = None,
                 rank: bool = True, rank_with: Optional[list[Measure]] = None) -> Optional[CatView]:
        dj = dim if dim is not None else self.cat_dim()
        if dj is None:
            return None
        groups: dict[str, list[int]] = {}
        for i in self.rows_idx:
            lab = self.text(i, dj)
            if lab:
                groups.setdefault(lab, []).append(i)
        if len(groups) < 2:
            return None
        aggregated = any(len(v) > 1 for v in groups.values())

        def value_of(mm: Optional[Measure], idx: list[int]) -> Optional[float]:
            if mm is None:
                return float(len(idx))
            xs = [mm.values[i] for i in idx if mm.values[i] is not None]
            if not xs:
                return None
            if len(xs) == 1:
                return float(xs[0])
            # сумма без «хвоста» двоичной арифметики: 330.09999999999997 → 330.1
            return round(float(sum(xs)), 9) if mm.additive or mm.stock else round(float(sum(xs) / len(xs)), 9)

        labels = list(groups)
        values = [value_of(m, groups[g]) for g in labels]
        keep = [k for k, v in enumerate(values) if v is not None]
        labels = [labels[k] for k in keep]
        values = [values[k] for k in keep]  # type: ignore[misc]
        if len(labels) < 2:
            return None
        extra_ms = [mm for mm in self.measures if mm is not m and not mm.mixed]
        extra = {mm.name: [value_of(mm, groups[g]) for g in labels] for mm in extra_ms}
        ordinal = sum(1 for x in labels if _ORDINAL_LABEL.match(x)) >= 0.8 * len(labels)
        ranked = rank and not ordinal and not (dj == self.label and self.funnel)
        order = list(range(len(labels)))
        key_vals = list(values)
        if rank_with:
            # состав: порядок — по сумме всех частей категории
            key_vals = [sum((value_of(mm, groups[g]) or 0.0) for mm in rank_with) for g in labels]
        if ranked:
            order.sort(key=lambda k: (-key_vals[k], k))
        labels = [labels[k] for k in order]
        values = [values[k] for k in order]  # type: ignore[misc]
        extra = {k: [v[o] for o in order] for k, v in extra.items()}
        total = None
        total_row = False
        if m is None or m.additive:
            # итог: строка «Итого» таблицы или сумма
            for i in sorted(self.totals):
                if m is not None and m.j >= 0:
                    tv = _num(self.cell(i, m.j))
                    if tv is not None and tv > 0:
                        total, total_row = tv, True
                        break
            if total is None:
                total = float(sum(values))
        distinct = len(labels)
        others = 0
        if len(labels) > top:
            if ranked and (m is None or m.additive):
                head = top - 1
                others = len(labels) - head
                rest = float(sum(values[head:]))
                labels = labels[:head] + [f"Остальные {others}"]
                values = values[:head] + [rest]
                extra = {k: v[:head] + [None] for k, v in extra.items()}
            else:
                labels, values = labels[:top], values[:top]
                extra = {k: v[:top] for k, v in extra.items()}
        return CatView(
            dim=self.cols[dj].name, labels=labels, values=values, measure=m, extra=extra, extra_measures=extra_ms,
            others=others, ranked=ranked, total=total, total_from_row=total_row, distinct=distinct, aggregated=aggregated,
        )

    @cached_property
    def dist(self) -> Optional[DistView]:
        m = self.main
        if m is None:
            return None
        x = np.array(m.present, dtype=float)
        if x.size < 2:
            return None
        out_rows = {o.row for o in self.profile.outliers if o.column == m.name}
        outliers = sorted(float(m.values[i]) for i in out_rows if i < len(m.values) and m.values[i] is not None)
        inl = np.array([v for i, v in enumerate(m.values) if v is not None and i not in out_rows], dtype=float)
        if inl.size < 2:
            inl = x
        bins = histogram_bins(inl, m.unit_text)
        return DistView(measure=m, values=x, inliers=inl, outliers=outliers, bins=bins, entity=self.entity)

    @cached_property
    def kpi(self) -> Optional[KpiView]:
        return _kpi_view(self)

    @cached_property
    def ref(self) -> RefView:
        return _ref_view(self)

    @cached_property
    def xy(self) -> Optional[XYView]:
        # изменение («Изменение к 2025», «Δ», «прирост») — та же величина, а не вторая: не для рассеяния
        ms = [m for m in self.measures if not m.mixed and not m.change]
        if len(ms) < 2:
            return None
        # ось X — естественная причина (часы, цена, расходы, доза, концентрация), Y — результат; без причины —
        # порядок колонок, и заголовок не говорит «каждый X даёт Y»
        x = next((m for m in ms if _DRIVER.search(m.name)), None)
        y = next((m for m in ms if m is not x), None) if x is not None else None
        driver = x is not None
        if x is None or y is None:
            x, y = ms[0], ms[1]
        lab_j = self.label if self.label is not None else self.id_col
        xs, ys, labels = [], [], []
        for i in self.rows_idx:
            a, b = x.values[i], y.values[i]
            if a is None or b is None:
                continue
            xs.append(float(a))
            ys.append(float(b))
            labels.append(self.text(i, lab_j) if lab_j is not None else "")
        if len(xs) < 3:
            return None
        ax, ay = np.array(xs), np.array(ys)
        r = slope = icpt = 0.0
        if ax.std() > 0 and ay.std() > 0:
            r = float(np.corrcoef(ax, ay)[0, 1])
            slope, icpt = (float(v) for v in np.polyfit(ax, ay, 1))
        gj = next((j for j in self.dims if j != self.label and 2 <= self.cols[j].distinct <= 5), None)
        groups: list[str] = []
        if gj is not None:
            groups = [self.text(i, gj) for i in self.rows_idx if x.values[i] is not None and y.values[i] is not None]
        return XYView(x=x, y=y, xs=xs, ys=ys, labels=labels, r=r, slope=slope, intercept=icpt,
                      group=self.cols[gj].name if gj is not None else None, groups=groups, driver=driver,
                      label_name=self.cols[lab_j].name if lab_j is not None else None)

    # ── свойства для задачи
    @cached_property
    def kpi_like(self) -> bool:
        """До 6 показателей с подписью: разные единицы, подпись «Показатель» или колонка изменения."""
        if self.profile.nature == "kpi":
            return True
        kv = self.kpi
        if kv is None or not (1 <= len(kv.items) <= 6):
            return False
        if self.n == 1:
            return True
        lab = self.cols[self.label].name.lower() if self.label is not None else ""
        named = bool(re.search(r"показател|метрик|kpi|индикатор|параметр", lab))
        return kv.mixed_units or named

    @cached_property
    def label_lengths(self) -> list[int]:
        cv = self.cats
        return [len(x) for x in cv.labels] if cv else []


# ── распределение ─────────────────────────────────────────────────────────────────────────────────────────────────────
def nice_width(w: float, unit: Optional[str] = None) -> list[float]:
    """«Круглые» ширины интервала вокруг w (по возрастанию): для минут — 5, 10, 15, 20, 30, 60…; иначе 1, 2, 2,5, 5 × 10ᵏ."""
    if w <= 0 or not math.isfinite(w):
        w = 1.0
    if unit in ("мин", "мин."):
        return [float(x) for x in NICE_MINUTES]
    k = math.floor(math.log10(w))
    out = []
    for e in range(k - 2, k + 3):
        for b in (1, 2, 2.5, 5):
            out.append(round(b * 10**e, 10))
    return sorted(set(out))


def histogram_bins(x: np.ndarray, unit: Optional[str] = None, lo_bins: int = 7, hi_bins: int = 12) -> Bins:
    """Интервалы гистограммы: ширина по Фридману–Диаконису, округлённая до «круглой»; регулярные интервалы — до первой
    границы не ниже 90-го перцентиля, остальное — открытый «больше X» (если хвост длинный); 7–12 интервалов (на малой
    выборке — от 5). Правая граница включена: «100–120» — это (100; 120]."""
    x = np.sort(np.asarray(x, dtype=float))
    n = x.size
    if n < 30 or len(np.unique(x)) < 7:
        lo_bins = 5
    q1, q3 = np.percentile(x, [25, 75])
    iqr = float(q3 - q1)
    span = float(x[-1] - x[0]) or 1.0
    fd = 2 * iqr / (n ** (1 / 3)) if iqr > 0 else span / 10
    grid = nice_width(fd, unit)
    idx = int(np.argmin([abs(math.log(g / fd)) if g > 0 and fd > 0 else 1e9 for g in grid]))
    p90 = float(np.percentile(x, 90))

    def build(w: float) -> tuple[float, float, int, bool]:
        start = math.floor(x[0] / w) * w
        if x[0] >= 0 and start < 0:
            start = 0.0
        cut = max(math.ceil(p90 / w) * w, start + w)
        open_tail = float(x[-1]) > cut + w
        if not open_tail:
            cut = max(math.ceil(float(x[-1]) / w) * w, start + w)
        k = int(round((cut - start) / w)) + (1 if open_tail else 0)
        return start, cut, k, open_tail

    for _ in range(len(grid)):
        start, cut, k, open_tail = build(grid[idx])
        if k > hi_bins and idx + 1 < len(grid):
            idx += 1
            continue
        if k < lo_bins and idx > 0:
            s2, c2, k2, o2 = build(grid[idx - 1])
            if k2 <= hi_bins:
                idx -= 1
                if k2 >= lo_bins:
                    break
                continue
        break
    w = grid[idx]
    start, cut, k, open_tail = build(w)
    edges = [start + w * t for t in range(int(round((cut - start) / w)) + 1)]
    counts = []
    labels = []
    for a, b in zip(edges, edges[1:]):
        if a == edges[0]:
            c = int(((x >= a) & (x <= b)).sum())
        else:
            c = int(((x > a) & (x <= b)).sum())
        counts.append(c)
        labels.append(f"{fmt_num(a)}–{fmt_num(b)}")
    if open_tail:
        counts.append(int((x > cut).sum()))
        labels.append(f"больше {fmt_num(cut)}")
    return Bins(edges=edges, counts=counts, labels=labels, width=w, open_from=cut if open_tail else None)


# ── ключевые показатели ───────────────────────────────────────────────────────────────────────────────────────────────
def _norm_text(v: Any) -> str:
    return " ".join(str(v).replace(" ", " ").split())


def _value_text(v: Any, unit: Optional[str]) -> Optional[tuple[float, str, Optional[str]]]:
    """Ячейка → (число, текст «1,24 млрд ₽», единица)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return float(v), fmt_value(float(v), unit), unit
    q = parse_quantity(v)
    if q is None:
        return None
    num, u = q
    u = u or unit
    text = fmt_value(num, u)
    return num, text, u


def _kpi_view(d: Data) -> Optional[KpiView]:
    if d.n == 0 or not d.measures:
        return None
    # одна строка: показатели — колонки
    if d.n == 1:
        i = d.rows_idx[0]
        items = []
        for m in d.measures:
            vt = _value_text(d.cell(i, m.j), m.unit_text)
            if vt is not None:
                # счётчик-заголовок («Заказов») на карточке — «Число заказов»
                lab = metric_phrase(m.name, m.type).nom if is_counter(m.name) and metric_phrase(m.name, m.type) else m.name
                items.append(KpiItem(label=lab, value=vt[0], value_text=vt[1], unit=vt[2]))
        return KpiView(items=items, mixed_units=len({it.unit for it in items}) > 1) if items else None
    lab_j = d.label
    if lab_j is None:
        # длинный формат: «Показатель × Период → Значение» (широкую таблицу чтение разворачивает так)
        return _kpi_long(d)
    if d.n > 6:
        return None
    changes = [m for m in d.measures if m.change]
    values = [m for m in d.measures if not m.change]
    if not values:
        return None
    # колонки-периоды («III кв. 2026», «III кв. 2025»): текущая — поздняя
    timed = [(m, _cell_time(m.name)) for m in values]
    cur, prev = values[0], None
    if all(t is not None for _, t in timed) and len(timed) >= 2:
        timed.sort(key=lambda mt: (mt[1][0], mt[1][1]))  # type: ignore[index]
        cur, prev = timed[-1][0], timed[-2][0]
    elif len(values) >= 2:
        prev = None
    items: list[KpiItem] = []
    units = set()
    for i in d.rows_idx:
        label = d.text(i, lab_j)
        ru = d.row_unit(i) or cur.unit_text  # единица строки («чел.», «%», «млн ₽») — из чтения
        vt = _value_text(d.cell(i, cur.j), ru)
        if not label or vt is None:
            continue
        units.add(vt[2] or "")
        it = KpiItem(label=label, value=vt[0], value_text=vt[1], unit=vt[2])
        if prev is not None:
            pv = _value_text(d.cell(i, prev.j), d.row_unit(i) or prev.unit_text)
            if pv is not None:
                it.prev_text = pv[1]
        if changes:
            cq = d.cell(i, changes[0].j)
            q = parse_quantity(cq) if isinstance(cq, str) else (None if cq is None else (float(cq), changes[0].unit))
            if q is not None:
                it.change, it.change_unit = q[0], (q[1] or changes[0].unit)
        elif prev is not None:
            pv = _value_text(d.cell(i, prev.j), d.row_unit(i) or prev.unit_text)
            if pv is not None and (pv[2] or "") == (vt[2] or ""):
                ch = kpi_change(label, vt[0], pv[0], vt[2])
                if ch is not None:
                    it.change, it.change_unit = ch
        items.append(it)
    if not items:
        return None
    return KpiView(items=items, period=cur.name if prev is not None else None,
                   prev_period=prev.name if prev is not None else None, mixed_units=len(units) > 1)


def _kpi_long(d: Data) -> Optional[KpiView]:
    if d.time_col is None or not d.dims:
        return None
    lab_j = d.dims[0]
    m = next((x for x in d.measures if not x.change), None)
    if m is None:
        return None
    ch = next((x for x in d.measures if x.change), None)
    rows_by: dict[str, list[tuple[tuple[str, int], int]]] = {}
    for i in d.rows_idx:
        lab = d.text(i, lab_j)
        t = _cell_time(d.cell(i, d.time_col))
        if lab and t is not None:
            rows_by.setdefault(lab, []).append((t, i))
    if not rows_by or len(rows_by) > 6 or any(len(v) > 4 for v in rows_by.values()):
        return None
    items = []
    units = set()
    periods = sorted({t for v in rows_by.values() for t, _ in v})
    for lab, rs in rows_by.items():
        rs.sort()
        i_cur = rs[-1][1]
        vt = _value_text(d.cell(i_cur, m.j), d.row_unit(i_cur) or m.unit_text)
        if vt is None:
            continue
        units.add(vt[2] or "")
        it = KpiItem(label=lab, value=vt[0], value_text=vt[1], unit=vt[2])
        if len(rs) >= 2 and rs[-2][0] != rs[-1][0]:
            pv = _value_text(d.cell(rs[-2][1], m.j), d.row_unit(rs[-2][1]) or m.unit_text)
            if pv is not None:
                it.prev_text = pv[1]
                if (pv[2] or "") == (vt[2] or ""):
                    ch2 = kpi_change(lab, vt[0], pv[0], vt[2])
                    if ch2 is not None:
                        it.change, it.change_unit = ch2
        if ch is not None:
            for _, i in reversed(rs):
                cq = d.cell(i, ch.j)
                q = parse_quantity(cq) if isinstance(cq, str) else (None if cq is None else (float(cq), ch.unit))
                if q is not None:
                    it.change, it.change_unit = q[0], (q[1] or ch.unit)
                    break
        items.append(it)
    if not items:
        return None
    per = [period_text(_iso(g, o)) for g, o in periods[-2:]] if periods else []
    return KpiView(items=items, period=per[-1] if per else None, prev_period=per[0] if len(per) == 2 else None,
                   mixed_units=len(units) > 1)


# ── справочник ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _ref_view(d: Data) -> RefView:
    """Справочник: одно упорядочение строк по главной метрике (любой числовой — по убыванию, пустые в конце), из него —
    и строки таблицы, и подписи, и значения столбцов. Доля и итог «Остальные … дают X» — только у суммируемой
    неотрицательной метрики (у рейтинга или прибыли с убытками доля смысла не имеет)."""
    m = d.main
    lab = d.label if d.label is not None else d.id_col
    order = list(d.rows_idx)
    if m is not None:
        order.sort(key=lambda i: (m.values[i] is None, -(m.values[i] or 0.0), i))
    summable = m is not None and m.additive and m.nonneg
    # колонки: подпись, измерения (до 2), метрика, доля
    cols: list[int] = []
    if lab is not None:
        cols.append(lab)
    budget = 5 - len(cols) - (2 if summable else 1 if m is not None else 0)
    for j in d.dims:
        if j != lab and budget > 0 and d.cols[j].distinct < d.n:
            cols.append(j)
            budget -= 1
    if m is not None:
        cols.append(m.j)
    else:
        for j, c in enumerate(d.cols):
            if j not in cols and len(cols) < 5 and c.role != "id":
                cols.append(j)
    cols_sorted = sorted(set(cols), key=lambda j: (j != lab, j))
    total = None
    if summable:
        total = float(sum(m.present))  # type: ignore[union-attr]
        for i in sorted(d.totals):
            tv = _num(d.cell(i, m.j))  # type: ignore[union-attr]
            if tv is not None and tv > 0:
                total = tv
                break
    names = [d.cols[j].name + (f", {d.cols[j].unit}" if d.cols[j].unit else "") for j in cols_sorted]
    if summable:
        names.append("Доля, %")

    def row(i: int) -> list[str]:
        r = [_fmt_cell(d, i, j) for j in cols_sorted]
        if summable:
            v = m.values[i]  # type: ignore[union-attr]
            r.append(fmt_num(v / total * 100, 1) if v is not None and total else "")
        return r

    all_rows = [row(i) for i in order]
    top_n = min(TOP_N, d.n)
    top_sum = float(sum(m.values[i] or 0 for i in order[:top_n])) if summable else None  # type: ignore[union-attr]
    rest = None
    if d.n > top_n:
        k = d.n - top_n
        ent = phrase(d.entity) if d.entity else None
        word = plural(k, ent.low.nom, ent.low.gen, ent.low.gen_pl) if ent is not None and ent.sure else \
            plural(k, "строка", "строки", "строк")
        rest = [""] * len(names)
        rest[0] = f"Остальные {k} {word}"
        if summable and total:
            rv = total - (top_sum or 0)
            rest[cols_sorted.index(m.j)] = fmt_num(rv)  # type: ignore[union-attr]
            rest[-1] = fmt_num(rv / total * 100, 1)
    dropped = [c.name for j, c in enumerate(d.cols) if j not in cols_sorted and c.role != "id"]
    labels = [d.text(i, lab) if lab is not None else str(i + 1) for i in order]
    values = [m.values[i] for i in order] if m is not None else []
    return RefView(
        label=d.cols[lab].name if lab is not None else None, columns=names, rows=all_rows[:top_n], rest=rest, measure=m,
        n=d.n, top_n=top_n, total=total, top_sum=top_sum, dropped=dropped, share_added=summable, all_rows=all_rows,
        full_columns=names, order=order, labels=labels, values=values,
        negatives=sum(1 for v in values if v is not None and v < 0),
    )


def _fmt_cell(d: Data, i: int, j: int) -> str:
    v = d.cell(i, j)
    c = d.cols[j]
    if v is None:
        return "—"
    if c.type == "date" and isinstance(v, str):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
        if m:
            return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    if c.type == "period" and isinstance(v, str):
        return period_label(v, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return fmt_exact(float(v))  # как в файле: 212,4, а не 212
    return d.text(i, j)


def describe_dropped(names: list[str]) -> str:
    return join_and([lower_first(n) for n in names])
