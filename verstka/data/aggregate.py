"""Подготовка данных (описание решения §2.5): из таблицы и профиля — то, что пойдёт на слайд.

- Ряд по времени (`TimeView`): периоды подряд с частотой оси, пропуски — `None` (линия с разрывами, а не ноль),
  ресэмплинг больше 36 точек (дни → недели → месяцы → кварталы → годы: сумма для потоков, среднее для уровней,
  последнее значение для остатков вроде числа клиентов), длинный формат «период × категория» — ряд на категорию.
- Категории (`CatView`): сумма или среднее по категории, ранжирование (порядковые подписи «0–30», «1 курс» — как
  в файле), топ-N и «Остальные» больше 12 категорий, доли от итога.
- Распределение (`DistView`): интервалы по Фридману–Диаконису с «круглой» шириной, 7–12 интервалов (5–12 на малых
  выборках), открытый последний «больше X» — все значения за X, выбросы тоже.
- Ключевые показатели (`KpiView`): значение, единица и изменение каждой строки («1,24 млрд ₽», «+23%», «+6 п.»).
- Справочник (`RefView`): топ-10 по главной метрике и строка «Остальные 230 …», до 5 колонок, доля посчитана;
  разбиение на слайды по 10 строк, если агрегация теряет смысл (не больше 3 слайдов).
- Взаимосвязь (`XYView`): пары значений и коэффициент корреляции.

Строки итога (`Table.totals`, если чтение их отметило, или подпись «Итого/Всего») в графики не идут — по ним
считаются доли от итога. Всё детерминировано и без модели."""

from __future__ import annotations

import math
import re
from functools import cached_property
from typing import Any, Optional

import numpy as np

from verstka.data.kpi import _kpi_view
from verstka.data.parse import forecast_period, is_total_label, iso_ord, period_str, season_name, split_unit
from verstka.data.reference import _ref_view, describe_dropped
from verstka.data.timeaxis import columns_time_view, resample_freq, time_view
from verstka.data.units import (
    _CODE, _DRIVER, _EVAL_NAME, _FACT, _ORDINAL_LABEL, _PLAN, INDEX_NAME, NICE_MINUTES, TO_MINUTES, _common_suffix,
    _kind, _num, _parts_ok, _period_key, _period_name, build_measure, is_index, kpi_change, unit_short,
)
from verstka.data.views import (
    MAX_CATS, MAX_ORDINAL, MAX_POINTS, MAX_SERIES, MAX_SLIDES, TABLE_ROWS, TOP_N, Bins, CatView, DistView, KpiItem,
    KpiView, Measure, RefView, SeriesV, TimeView, XYView,
)
from verstka.data.words import (
    file_title, fmt_num, head_word, is_counter, same_stem, stem, stem_in, stems_match, stems_of, upper_first,
)
from verstka.schemas.data import ColumnProfile, DatasetProfile, Table

__all__ = [
    "MAX_POINTS", "MAX_CATS", "TOP_N", "TABLE_ROWS", "MAX_SLIDES",
    "Measure", "SeriesV", "TimeView", "CatView", "Bins", "DistView", "KpiItem", "KpiView", "RefView", "XYView", "Data",
    "histogram_bins", "nice_width", "resample_freq", "unit_short", "NICE_MINUTES", "TO_MINUTES", "INDEX_NAME",
    "kpi_change", "is_index", "describe_dropped",
]


_BENCHMARK = re.compile(r"^(?:среднее|в\s+среднем|средн\w*\s+(?:по|значение)|по\s+(?:стране|россии|рф|миру|отрасли|"
                        r"региону|округу|выборке|компании)|норматив\w*|норма|целевое\s+значение|бенчмарк|benchmark|"
                        r"average|медиана\s+по)(?:\s|$|,)", re.I)
_CENTRAL = re.compile(r"(?:^|[^а-яёa-z])(?:медиан\w*|средн\w*|смешанн\w*|комбинированн\w*|median|mean|average)",
                      re.I)
_CLOCK = re.compile(r"^\s*\d{1,2}:\d{2}(?:\s*[–—-]\s*\d{1,2}:\d{2})?\s*$")
_STAT_ANY = re.compile(r"(?:^|[^а-яёa-z])(?:минимум\w*|максимум\w*|мин\.|макс\.|минимальн\w*|максимальн\w*|min|max)",
                       re.I)
_WEEKDAY = re.compile(r"^(?:пн|вт|ср|чт|пт|сб|вс|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье|"
                      r"mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\.?$", re.I)
_METRIC_WORD = re.compile(r"выручк|расход|доход|прибыл|продаж|сумм|цен[аы]|стоимост|колич|числ|дол[яи]|средн|процент|"
                          r"итог|всего|план|факт|(?:^|\s)рост|изменени|балл|рейтинг|индекс|ставк|курс|тариф|вес(?:\s|$)|"
                          r"объ[её]м|площад|длительн|время|минимум|максимум|медиан|мин\.|макс\.|затрат|бюджет|"
                          r"конверси|охват|населени|штук|ед\.", re.I)
MAX_DISCRETE_BINS = 15  # значений не больше — гистограмма по значениям, а не по интервалам
_COUNT_NAME = re.compile(r"^(?:число|количество|кол-во|частота|сколько|человек|учеников|студентов|семей|случаев)", re.I)
_TARGET_NAME = re.compile(r"(?:^|[^а-яё])(?:цел[ьи]|целев|норматив|норма|target|таргет|kpi|ориентир)", re.I)
# счёт, которым взвешивают средние: чеки, заказы, ответы, анкеты, визиты, сессии, звонки, обращения, клиенты
_WEIGHT_NAME = re.compile(r"чек(?:ов|и)\b|заказ|ответ(?:ов|ы|ивших)|анкет|респондент|опрошен|визит|сессий|сессии|звонк|"
                          r"обращени|покупател|транзакц|поездок|посещени|отзыв", re.I)
_PER_UNIT = re.compile(r"/\s*(?:\d+[\s\u00a0]*)?([a-zа-яё][a-zа-яё.·²³]*)", re.I)


def per_unit_denominator(unit: str) -> Optional[str]:
    """Знаменатель удельной величины: «л/100 км» → «км», «₽/кВт·ч» → «квт·ч», «руб./чел.» → «чел»; нет «/» — None."""
    m = _PER_UNIT.search(unit or "")
    return m.group(1).lower().rstrip(".") if m else None


def den_matches(den: str, unit: str, name: str) -> bool:
    """Колонка несёт знаменатель удельной величины: единица («км») или имя («Пробег, км», «Потреблено, кВт·ч»)."""
    u = (unit or "").lower().rstrip(".")
    return u == den or u.endswith(" " + den) or bool(re.search(rf"(?:^|[\s,(]){re.escape(den)}(?:$|[\s,).])",
                                                                  (name or "").lower()))


def _no_n(name: str) -> str:
    """«Продажи (n=120)» → «Продажи»: размер выборки — не часть имени."""
    return re.sub(r"\s*\(\s*n\s*=\s*[\d\s]+\)\s*$", "", name or "").strip()


_OVERALL = re.compile(r"^(?:все\s+[а-яё]+|в\s+целом|по\s+компании|по\s+всем\s+[а-яё]+|в\s+среднем\s+по\s+[а-яё]+|"
                      r"overall|all\s+[a-z]+)$", re.I)


# колонка статуса строки: «Факт» / «Прогноз» / «План» / «Оценка» — не факт всё, кроме факта
_STATUS = {"факт": "fact", "фактически": "fact", "fact": "fact", "actual": "fact", "actuals": "fact",
           "прогноз": "forecast", "прогн.": "forecast", "forecast": "forecast", "план": "plan", "plan": "plan",
           "оценка": "estimate", "оценочно": "estimate", "estimate": "estimate", "ожидание": "estimate",
           "ожид.": "estimate", "ожидаемое": "estimate", "предварительно": "estimate", "предв.": "estimate"}


def _status_of(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    return _STATUS.get(" ".join(v.lower().split()))


def status_column(table: Table) -> Optional[int]:
    """Колонка статуса строк: все значения — «факт», «прогноз», «план», «оценка» (и их английские пары), есть и факт, и
    не факт. Её строки «не факт» — прогноз: в рост, «за N месяцев» и итоги не входят."""
    for j in range(len(table.columns)):
        vals = [r[j] for r in table.rows if j < len(r) and r[j] not in (None, "")]
        if len(vals) < 2 or not all(_status_of(v) is not None for v in vals):
            continue
        kinds = {_status_of(v) for v in vals}
        if "fact" in kinds and len(kinds) >= 2:
            return j
    return None


# «Оценка» одна — это балл («Оценка удовлетворённости»), прогноз — только с периодом («Оценка 2026», «2026 (оценка)»)
_FORECAST_NAME = re.compile(r"^(?:прогноз|ожид(?:ание|аемое|\.)?|forecast|fc)(?:[^а-яёa-z]|$)", re.I)
_CUMUL = re.compile(r"нараста|накоплен|с начала года|с начала периода|ytd|cumulative|running total", re.I)
# «Прочее», «Другие», «Остальное» — строка-остаток: в конце списка и никогда не лидер
# «Прочее», «Прочие партнёры (214)», «Другое (12)», «Остальные клиенты» — остаток, а не категория
_OTHER = re.compile(r"^(?:прочее|прочие|прочая|прочий|другое|другие|остальное|остальные|иное|иные|others?|other)\b.*$",
                    re.I)


def is_other_label(label: str) -> bool:
    return bool(_OTHER.match(" ".join(str(label).split())))


def stem_hits(subject: tuple[str, ...] | list[str], text: str) -> int:
    """Сколько основ предмета цели есть в тексте («доле брошенных корзин» и «Доля брошенных корзин» — 3); части
    сложных слов тоже («потреблению» — в «Водопотребление»)."""
    words = stems_of(text)
    return sum(1 for s in subject if any(stem_in(s, w) for w in words))


# слова величин-уровней в цели: «по конверсии», «по доле», «по среднему» — из равных колонок берётся уровень (процент)
_LEVEL_GOAL = re.compile(r"^(?:конверс|дол[ьиея]?$|процент|средн|оценк|балл|рейтинг|скорост|цен|тариф|медиан|уров|"
                         r"удельн|частот|плотн|открываем|посещаем|загрузк|заполняем|обеспеченн|охват)", re.I)
# цель о величине на душу («обеспеченность врачами», «уровень преступности»): колонка «на 1 000 жителей», «на 100 тыс.»
RATE_GOAL = re.compile(r"^(?:обеспеченн|уров|частот|плотн|интенсивн|распространенн|заболеваем|смертн|рождаем)", re.I)
RATE_COLUMN = re.compile(r"(?:^|[\s(/])на\s+(?:1\s*000|1000|10\s*000|100\s*000|100\s*тыс|10\s*тыс|тыс\.?\s*(?:жител|человек|"
                         r"населени)|душу|человека|жителя|\d[\d\s]*(?:жител|человек|населени)|одн(?:ого|у|о)\b|"
                         r"врача|сотрудника|работника|ученика|студента|пациента)|per\s+capita|‰", re.I)


# ── главный объект ────────────────────────────────────────────────────────────────────────────────────────────────────
class Data:
    """Датасет для анализа: таблица, профиль, метрики, подписи и подготовленные виды (лениво)."""

    def __init__(self, table: Table, profile: DatasetProfile, subject: tuple[str, ...] = (), compare: bool = False,
                 head: Optional[str] = None, negate: tuple[str, ...] = (), qualifiers: tuple[str, ...] = (),
                 ask: Optional[str] = None):
        self.table = table
        self.profile = profile
        self.subject = subject
        # величина цели: главное слово («мест»), уточнения («свободн»), отрицания («без НДС» → «ндс»)
        self.head = head
        self.negate = negate
        self.qualifiers = qualifiers
        self.ask = ask  # «кто растёт быстрее всех» → "fastest": темп каждой категории, а не рост целого
        # сравнение категорий: главная метрика — колонка-итог («Итого за год»), если она есть, а не первая часть
        self.compare = compare
        cols = profile.columns
        self.cols: list[ColumnProfile] = cols
        self.ncols = len(cols)
        self.totals: set[int] = self._total_rows()
        # строки-ориентиры («Среднее по стране», «Норматив»): не категория — не лидер, не последний, не доля
        self.benchmarks: dict[int, str] = self._benchmark_rows()
        # строки-прогнозы («2026П», «2026 (прогноз)»): не факт — в вывод и рост не входят, на графике — отдельным рядом
        self.forecast_rows: set[int] = self._forecast_rows()
        self.rows_idx = [i for i in range(len(table.rows))
                         if i not in self.totals and i not in self.benchmarks and i not in self.forecast_rows]
        self.n = len(self.rows_idx)
        self.measures: list[Measure] = [build_measure(self, j, c) for j, c in enumerate(cols) if c.role == "metric"]
        self.measures = [m for m in self.measures if m.present]
        # колонки-прогнозы («Прогноз», «Прогноз 2026», «2026 (прогноз)», «Оценка»): не факт — ни в рядах, ни в выводе
        self.forecasts: list[Measure] = [m for m in self.measures if _FORECAST_NAME.match(m.name.strip())
                                         or forecast_period(m.name.strip()) is not None]
        self.measures = [m for m in self.measures if m not in self.forecasts]
        # нарастающий итог («Нарастающим итогом», «С начала года») — не второй ряд и не слагаемое: последнее значение
        # равно сумме за период; в рядах и долях его нет, итог — в подписи
        self.cumulative: list[tuple[Measure, Measure]] = []
        for b_ in list(self.measures):
            a_ = next((x for x in self.measures if x is not b_ and self._running_sum(x, b_)), None)
            if a_ is not None:
                self.cumulative.append((b_, a_))
                self.measures.remove(b_)
        # номера, а не величины (аудитории в расписании): единственное «число» без единицы и признака суммы, с
        # повторами, среди трёх и больше текстовых колонок — таблицей, «не для графика»
        self.not_numbers: list[str] = []
        texts = [j for j, c in enumerate(cols) if c.role in ("dimension", "text") and c.type in ("category", "text")]
        if len(self.measures) == 1 and len(texts) >= 3:
            m0 = self.measures[0]
            pv = m0.present
            # длительность или счёт по названию («Дней открыт», «Заказов») — величина, а не номер
            if not m0.unit and not m0.additive and m0.time_unit is None and not is_counter(m0.name) and pv \
                    and all(float(v).is_integer() for v in pv) and len(set(pv)) <= 0.7 * len(pv):
                self.not_numbers = [m0.name]
                self.measures = []
        self.codes = {j for j, c in enumerate(cols) if c.role in ("dimension", "text") and self._code_like(j)}
        self.dims = [j for j, c in enumerate(cols)
                     if c.role == "dimension" and c.type in ("category", "boolean") and j not in self.codes
                     and j != self.status_col]  # «Тип: Факт/Прогноз» — пометка строк, а не признак для сравнения
        # коды ответа HTTP («Код ответа»: 404, 500) — категории, а не номера строк
        self.status_cols = {j for j, c in enumerate(cols) if c.role == "id" and self._status_like(j)}
        self.label = self._label_col()
        self.id_col = next((j for j, c in enumerate(cols) if c.role == "id" and j not in self.status_cols), None)
        if self.id_col is None and self.codes:
            self.id_col = min(self.codes)
        self.time_col = next((j for j, c in enumerate(cols) if profile.time_axis and c.name == profile.time_axis.column),
                             None)

    # ── строки и колонки
    def _forecast_rows(self) -> set[int]:
        """Строки-прогнозы: период-прогноз в колонке времени («2026П», «2026 (прогноз)») или колонка статуса
        («Тип», «Статус»: Факт / Прогноз / План / Оценка) — всё, что не «факт», не факт."""
        self.status_col: Optional[int] = status_column(self.table)
        out: set[int] = set()
        if self.status_col is not None:
            out = {i for i, r in enumerate(self.table.rows)
                   if self.status_col < len(r) and _status_of(r[self.status_col]) not in (None, "fact")}
        ax = self.profile.time_axis
        tj = next((j for j, c in enumerate(self.profile.columns) if ax is not None and c.name == ax.column), None)
        if tj is not None:
            out |= {i for i, r in enumerate(self.table.rows) if tj < len(r) and forecast_period(r[tj]) is not None}
        return out if len(out) < len(self.table.rows) else set()

    def _running_sum(self, a: Measure, b: Measure) -> bool:
        """b — нарастающий итог a: по строкам подряд b = a₁ + … + aₖ (с точностью до округления записи), строк ≥ 3."""
        if (a.unit or "") != (b.unit or "") or a.change or b.change:
            return False
        rows = [i for i in self.rows_idx if a.values[i] is not None and b.values[i] is not None]
        if len(rows) < 3 or len(rows) < 0.8 * self.n:
            return False
        run = 0.0
        for i in rows:
            run += float(a.values[i])  # type: ignore[arg-type]
            if abs(run - float(b.values[i])) > 0.051 + 1e-6 * abs(run):  # type: ignore[arg-type]
                return False
        return bool(_CUMUL.search(b.name)) or len(rows) >= 4

    def _total_rows(self) -> set[int]:
        marked = getattr(self.table, "totals", None) or []
        out = {int(i) for i in marked if isinstance(i, int) and 0 <= i < len(self.table.rows)}
        if out:
            return out
        for i, r in enumerate(self.table.rows):
            if any(is_total_label(v) for v in r[:2]):
                out.add(i)
        return out if len(out) < len(self.table.rows) else set()

    def _benchmark_rows(self) -> dict[int, str]:
        """Строки-ориентиры по подписи в первых двух колонках: «Среднее по стране», «В среднем», «По России»,
        «Норматив». Только если остаются хотя бы две обычные строки."""
        out: dict[int, str] = {}
        for i, r in enumerate(self.table.rows):
            if i in self.totals:
                continue
            for v in r[:2]:
                if isinstance(v, str) and _BENCHMARK.match(" ".join(v.split())):
                    out[i] = " ".join(v.split())
                    break
        rest = len(self.table.rows) - len(self.totals) - len(out)
        return out if rest >= 2 else {}

    def sums_check(self, j: int, vals: list[Optional[float]]) -> bool:
        """Признак, что колонка складывается: она — часть или итог по профилю (итог равен сумме частей) или строка
        «Итого» таблицы равна сумме её значений."""
        name = self.cols[j].name
        if name in (getattr(self.profile, "part_columns", None) or []) or name == getattr(self.profile, "total_column", None):
            return True
        s = sum(v for v in vals if v is not None)
        for i in self.totals:
            tv = _num(self.cell(i, j))
            if tv is not None and s and abs(tv - s) <= max(0.51, 0.005 * abs(s)):
                return True
        return False

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

    def _code_like(self, j: int) -> bool:
        """Колонка кодов («SUP-48213», «A-12», «Z1000»): у каждой строки свой, буквы и цифры без пробелов — это
        идентификатор, а не подпись и не категория."""
        vals = [v for v in (self.cell(i, j) for i in self.rows_idx) if isinstance(v, str) and v.strip()]
        if len(vals) < 3 or len(set(vals)) < len(vals):
            return False
        ok = sum(1 for v in vals if _CODE.match(v.strip()))
        return ok >= 0.9 * len(vals)

    def _status_like(self, j: int) -> bool:
        """Колонка кодов состояния: целые 100–599 (ответы HTTP) под названием «код/статус» — подпись категории."""
        if not re.search(r"код|статус|status|code|http", self.cols[j].name, re.I):
            return False
        vals = [self.cell(i, j) for i in self.rows_idx]
        nums = [_num(v) for v in vals if v is not None]
        return len(nums) >= 2 and all(x is not None and float(x).is_integer() and 100 <= x <= 599 for x in nums)

    def _label_col(self) -> Optional[int]:
        """Подпись строки: текст или категория, у каждой строки своя (клиент, регион, показатель)."""
        best = None
        for j, c in enumerate(self.cols):
            if (c.role not in ("text", "dimension") and j not in self.status_cols) or c.type in ("boolean",) \
                    or j in self.codes:
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
        """Главная метрика: названная целью (больше всего совпавших основ слов); для сравнения — колонка-итог; иначе
        поток денег (выручка, а не цена или минимум); оценка (балл); центральная статистика (медиана, среднее); деньги-
        уровень; не счётчик; первая не-изменение."""
        ms = self.measures
        if not ms:
            return None
        if self.subject and any(RATE_GOAL.match(s_) for s_ in self.subject) and self.rate_measure is not None:
            # «по обеспеченности врачами», «по уровню преступности» — величина на душу, а не абсолютный счёт
            return self.rate_measure
        twin = self._unit_twin
        if twin is not None:
            return twin  # «по объёму» — тонны, «в деньгах» — доллары, когда у колонок одно имя и разные единицы
        if self.head:
            # главное слово величины цели решает: «по свободным местам» — «Свободно мест», а не «Куплено мест»;
            # «по цене с НДС» — не «Цена без НДС»; главного слова нет ни в одной колонке — цель колонку не выбирает
            picked = self.head_measure
            if picked is not None:
                return self._not_target(self._rate_over_count(picked, broad=False))
            if not self.head_in_columns:
                ms_sub = ()
            else:
                ms_sub = self.subject
        else:
            ms_sub = self.subject
        if ms_sub:
            hits = [stem_hits(ms_sub, m.name) for m in ms]
            top = max(hits)
            if top > 0:
                tied = [m for m, h in zip(ms, hits) if h == top]
                if len(tied) > 1:
                    # равные по словам цели: слово уровня («по конверсии») — процент и уровень; иначе («структура
                    # выплат») — поток денег, потом то, что складывается
                    if any(_LEVEL_GOAL.match(s_) for s_ in self.subject):
                        tied.sort(key=lambda m: (m.type != "percent", m.additive, m.j))
                    else:
                        tied.sort(key=lambda m: (not (m.type == "money" and m.additive), not m.additive, m.j))
                return self._not_target(self._rate_over_count(tied[0], broad=False))
        if self.compare and self.total_metric is not None:
            return self.total_metric
        tm = self.total_metric
        if tm is not None and all(x is tm or _period_name(x.name) or season_name((split_unit(x.name)[0] or x.name).strip())
                                  for x in ms if (x.unit or "") == (tm.unit or "")):
            return tm  # «Июль · Август · Сентябрь · Итого за квартал»: величина таблицы — итог за квартал, а не июль

        def latest(m: Measure) -> Measure:
            """Колонки-периоды («Выручка 2025 · Выручка 2026»): главная — последний период."""
            if not _period_name(m.name):
                return m
            sib = [x for x in ms if _period_name(x.name) and (x.unit or "") == (m.unit or "") and not x.change]
            return max(sib, key=lambda x: (_period_key(x.name), x.j)) if len(sib) >= 2 else m

        # колонка по всем («Все сотрудники», «В целом», «По компании») рядом с подгруппами («Продажи (n=120)»): она и есть
        # величина таблицы, а не первая подгруппа
        ov = [m for m in ms if _OVERALL.match(_no_n(m.name)) and not m.change]
        if ov and sum(1 for x in ms if x is not ov[0] and (x.unit or "") == (ov[0].unit or "")) >= 2:
            return ov[0]
        # колонка с одним значением у всех строк («И» — 22 игры у каждой команды) — не главная, если есть другие
        varied = [m for m in ms if len(set(m.present)) > 1]
        if varied and len(varied) < len(ms):
            ms = varied
        th = self._title_head
        for pred in (
            lambda m: m.type == "money" and not m.change and not m.mixed and m.additive,
            # колонка, названная как файл («Пробег автопарка октябрь» — «Пробег за месяц», а не одометр; «Загрузка
            # отеля» — загрузка, а не тариф), — если это не статистика вроде «Средняя выплата»
            lambda m: bool(th) and not m.change and not m.mixed and not _STAT_ANY.search(m.name)
            and not _CENTRAL.search(m.name) and stem_in(th, stem(head_word(split_unit(m.name)[0] or m.name))),
            # оценочная метрика (балл, качество, выручка) главнее счёта размера (учеников, пользователей)
            lambda m: not m.change and not m.mixed and bool(_EVAL_NAME.search(m.name)),
            # центральная статистика: медиана и среднее — главнее минимума и максимума
            lambda m: not m.change and not m.mixed and bool(_CENTRAL.search(m.name)),
            lambda m: m.type == "money" and not m.change and not m.mixed,
            lambda m: not m.change and not m.mixed and not is_counter(m.name),
            lambda m: not m.change and not m.mixed,
            lambda m: not m.change,
        ):
            for m in ms:
                if pred(m):
                    return self._rate_over_count(latest(m))
        return ms[0]

    @cached_property
    def target_pair(self) -> Optional[tuple[Measure, Measure]]:
        """(величина, цель): колонка цели («Цель, %», «Норматив», «План») с одним значением на весь ряд рядом с
        величиной той же единицы — ориентир, а не второй ряд («ниже цели в 5 из 12 недель»)."""
        for t_ in self.measures:
            if not _TARGET_NAME.search(t_.name) or len(set(t_.present)) > 2 or len(t_.present) < 2:
                continue
            m = next((x for x in self.measures if x is not t_ and (x.unit or "") == (t_.unit or "") and not x.change),
                     None)
            if m is not None:
                return m, t_
        return None

    @cached_property
    def row_target(self) -> Optional[tuple[Measure, Measure]]:
        """(величина, цель строки): у каждой строки своя цель той же единицы («Доступность» и «Цель SLA», «Время ответа»
        и «Норматив, мин») — порог строки, а не вторая величина: «ниже цели — 2 из 7: CDN и Почта для бизнеса».
        Без оси времени (там — `target_pair`) и без пары «план — факт» (там — исполнение плана)."""
        if self.time_col is not None or self.plan_fact is not None:
            return None
        for t_ in self.measures:
            if not _TARGET_NAME.search(t_.name) or t_.change:
                continue
            cands = [x for x in self.measures if x is not t_ and not x.change and not _TARGET_NAME.search(x.name)
                     and (x.unit or "") == (t_.unit or "") and x.type == t_.type]
            if cands:
                return cands[0], t_
        return None

    def _not_target(self, m: Measure) -> Measure:
        """Цель «не уложились в SLA» называет колонку цели («Цель SLA»), а спрашивает о величине рядом с ней."""
        rt = self.row_target
        return rt[0] if rt is not None and rt[1] is m else m

    @cached_property
    def typo_rows(self) -> dict[str, list[int]]:
        """Выбросы-опечатки: значение, отмеченное профилем, в сто и больше раз больше (или меньше) медианы остальных
        («4 520 000» среди «4 210 … 5 240»). В ряду по времени их нет — линию не сплющивает; подпись говорит о них."""
        out: dict[str, list[int]] = {}
        for m in self.measures:
            rows = sorted({o.row for o in self.profile.outliers if o.column == m.name})
            if not rows:
                continue
            others = [abs(m.values[i]) for i in self.rows_idx if m.values[i] is not None and i not in rows]
            if len(others) < 4:
                continue
            med = float(np.median(others))
            if med <= 0:
                continue
            bad = [i for i in rows if m.values[i] is not None and (abs(m.values[i]) >= 100 * med
                                                                  or abs(m.values[i]) * 100 <= med)]
            if bad:
                out[m.name] = bad
        return out

    def dominant_typos(self, m: Optional[Measure]) -> list[int]:
        """Опечатки, которые делают итог сами (больше половины суммы и в сто раз больше медианы: 1 500 000 ₽ среди
        пожертвований по 975 ₽): в топе и долях их нет. Крупнейший клиент — не опечатка, даже если в сто раз больше."""
        if m is None:
            return []
        rows = self.typo_rows.get(m.name, [])
        tot = sum(float(m.values[i]) for i in self.rows_idx if m.values[i] is not None and m.values[i] > 0)  # type: ignore
        return [i for i in rows if m.values[i] is not None and tot > 0 and float(m.values[i]) > 0.5 * tot]  # type: ignore

    @cached_property
    def parallel_time_only(self) -> bool:
        """Колонки на оси времени — ряды одного рода («ИТ · Продажи · Маркетинг» по месяцам, «2024 · 2025»): их не
        сопоставляют друг с другом как причину и следствие."""
        xy = self.xy
        if xy is None:
            return True
        same = (xy.x.unit or "") == (xy.y.unit or "") and xy.x.type == xy.y.type
        years = all(re.fullmatch(r"\s*(?:19|20)\d\d\s*", m.name) for m in (xy.x, xy.y))
        return bool(years or (same and self._siblings(xy.x, xy.y)))

    def weight_of(self, m: Measure) -> Optional[Measure]:
        """Вес уровня: счёт того, из чего он средний («Средний чек» — «Чеков», NPS — «Ответов», конверсия — «Визиты»,
        оценка — «Анкет»). Колонка-счётчик целыми; из нескольких — с общим словом в имени, потом слово ответов."""
        if m.additive or m.stock or m.change:
            return None
        return self._weights.get(m.name)

    @cached_property
    def _weights(self) -> dict[str, Measure]:
        out: dict[str, Measure] = {}
        counters = [x for x in self.measures if x.additive and not x.change and x.present
                    and all(float(v).is_integer() and v >= 0 for v in x.present)
                    and (_WEIGHT_NAME.search(x.name) or is_counter(x.name))]
        for m in self.measures:
            if m.additive or m.stock or m.change:
                continue
            den = per_unit_denominator(m.unit_text or "")
            if den is not None:
                # расход «л/100 км» — на километр: вес — колонка километров («Пробег, км»), а не рейсы; нет её — без веса
                w = next((x for x in self.measures if x is not m and x.additive and not x.change
                          and den_matches(den, x.unit_text or "", x.name)), None)
                if w is not None:
                    out[m.name] = w
                continue
            if not counters:
                continue
            hm = {stem(w) for w in stems_of(m.name)}
            same = [c for c in counters if hm & {stem(w) for w in stems_of(c.name)}]
            resp = [c for c in counters if _WEIGHT_NAME.search(c.name)]
            pick = same[0] if same else resp[0] if len(resp) == 1 else counters[0] if len(counters) == 1 else None
            if pick is not None:
                out[m.name] = pick
        return out

    @cached_property
    def head_in_columns(self) -> bool:
        """Главное слово величины цели есть в названии какой-нибудь колонки."""
        quals = [x for x in self.qualifiers if len(x) >= 3]
        return bool(self.head) and any(any(stem_in(self.head, w) or any(stem_in(x, w) for x in quals)
                                           for w in stems_of(m.name)) for m in self.measures)

    @cached_property
    def head_measure(self) -> Optional[Measure]:
        """Колонка, названная главным словом цели; из нескольких — по уточнениям («свободн»), без противоречия
        отрицанию («без НДС» только у цели «без НДС»), потом по словам цели и названию файла; не по порядку колонок."""
        if not self.head:
            return None
        # уточнение цели («свободн», «ндс», «средн») конкретнее главного слова: «свободным местам» — «Свободно», хотя
        # слово «мест» — только в «Куплено мест»
        quals = [x for x in self.qualifiers if len(x) >= 3]
        cands = [m for m in self.measures if any(stem_in(self.head, w) for w in stems_of(m.name))
                 or any(stem_in(x, w) for x in quals for w in stems_of(m.name))]
        if not cands:
            return None
        title = stems_of(file_title(self.profile.file, self.profile.sheet))

        def neg_bad(m: Measure) -> int:
            low = m.name.lower().replace("ё", "е")
            has = {stem(w) for w in re.findall(r"\bбез\s+([а-яёa-z0-9]+)", low)}
            return len(has - set(self.negate)) + len(set(self.negate) - has)

        def score(m: Measure) -> tuple:
            words = stems_of(m.name)
            q = sum(1 for x in quals if any(stem_in(x, w) for w in words))
            h = int(any(stem_in(self.head, w) for w in words))  # type: ignore[arg-type]
            sub = sum(1 for x in self.subject if any(stem_in(x, w) for w in words))
            tit = sum(1 for x in title if any(stem_in(x, w) for w in words))
            return (-neg_bad(m), q, h, sub, tit, not m.change)

        best = max(score(m) for m in cands)
        top = [m for m in cands if score(m) == best]
        return top[0] if len(top) == 1 else None  # ничья и по словам цели, и по файлу — не порядок колонок

    @cached_property
    def rate_measure(self) -> Optional[Measure]:
        """Колонка «на душу»: «Врачей на 1 000 жителей», «На 100 тыс. населения», единица «на 1 000 чел.»."""
        return next((m for m in self.measures if not m.change and RATE_COLUMN.search(f"{m.name} {m.unit or ''}")), None)

    @cached_property
    def _title_head(self) -> str:
        """Основа главного слова названия файла («Пробег автопарка октябрь» → «пробег»), без кодов и чисел в начале."""
        title = re.sub(r"^(?:[\w-]*\d[\w-]*\s+)+", "", file_title(self.profile.file, self.profile.sheet))
        h = head_word(title)
        return stem(h) if h and h not in ("данные", "итоги", "итог", "отчёт", "отчет", "таблица", "список") else ""

    @cached_property
    def _unit_twin(self) -> Optional[Measure]:
        """Колонки с одним именем и разными единицами («Экспорт, т» и «Экспорт, $»): цель «по объёму / в тоннах» —
        натуральная, «в деньгах / выручки / стоимость» — денежная. Нет такой пары или цель о другом — None."""
        if not self.subject:
            return None
        base = {}
        for m in self.measures:
            base.setdefault((split_unit(m.name)[0] or m.name).strip().lower(), []).append(m)
        pairs = [ms for ms in base.values() if len(ms) >= 2 and len({x.unit_text for x in ms}) == len(ms)]
        if not pairs:
            return None
        words = " ".join(self.subject)
        money = re.search(r"выручк|деньг|денеж|стоимост|доход|доллар|рубл|валют|сумм", words)
        volume = re.search(r"объ[её]м|объем|тонн|натур|физическ|вес|штук|литр|количеств", words)
        for ms in pairs:
            if money and not volume:
                hit = next((x for x in ms if x.type == "money"), None)
            elif volume and not money:
                hit = next((x for x in ms if x.type != "money"), None)
            else:
                hit = None
            if hit is not None:
                return hit
        return None

    def _rate_over_count(self, m: Measure, broad: bool = True) -> Measure:
        """Счёт и его доля рядом («Конверсии» и «Конверсия, %», A/B-тест): сравнивают долю — она не зависит от размера
        группы."""
        if m.type == "percent" or m.type == "money":
            return m
        hm = stem(head_word(split_unit(m.name)[0] or m.name))
        for x in self.measures:
            if x is not m and x.type == "percent" and not x.change \
                    and same_stem(hm, stem(head_word(split_unit(x.name)[0] or x.name))):
                return x
        # «Брак, шт.» и «Брак, ppm», «Возвратов» и «Доля возвратов, %», «Завершили» и «Доля завершивших»: уровень (ppm,
        # %, на 1000) не зависит от объёма — сравнивают его, а не долю счёта («34% брака» читается как уровень брака)
        mw = {w[:5] for w in stems_of(split_unit(m.name)[0] or m.name) if len(w) >= 4} if broad else set()
        for x in self.measures:
            if x is m or x.change or not mw:
                continue
            u = (x.unit_text or "").strip().lower()
            rate = x.type == "percent" or u in ("ppm", "‰", "%", "п.п.") or bool(RATE_COLUMN.search(f"{x.name} {u}"))
            xw = {w[:5] for w in stems_of(split_unit(x.name)[0] or x.name) if len(w) >= 4} - {"доля", "уровен", "проце"}
            if rate and mw & xw:
                return x
        return m

    @cached_property
    def constant_main(self) -> bool:
        """У главной метрики все значения одинаковые (все нули): лидера и графика нет."""
        m = self.main
        vals = m.present if m is not None else []
        return len(vals) >= 2 and max(vals) == min(vals)

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
        if m is None or m.change or m.mixed or m is self.total_metric:
            return []
        if self.matrix and self.matrix_axis is not None:
            return []  # перекрёстная таблица: сравниваются итоги строк или колонок, а не колонки рядом
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
            if self.time_col is not None and not self.compare:
                group.append(x)  # на оси времени — ряды рядом; сравнение категорий (смены по браку) — по одной величине
            elif _common_suffix([m.name, x.name]) or (_period_name(m.name) and _period_name(x.name)) \
                    or self._siblings(m, x):
                group.append(x)
        group.sort(key=lambda x: x.j)
        return group[:MAX_SERIES] if len(group) >= 2 else []

    def _siblings(self, m: Measure, x: Measure) -> bool:
        """Две колонки одной величины по категориям — рядом, а не одна из них: статистики одной величины («Минимум ·
        Медиана · Максимум»), колонки с общим главным словом («Продажи онлайн · Продажи офлайн») или счёт одного рода
        по порядковым группам («Мужчины · Женщины» по возрасту). Расходы и выручка, выручка и прибыль — разные
        величины: на графике одна, другая названа в причинах."""
        if _CENTRAL.search(m.name) or _STAT_ANY.search(m.name):
            return bool(_STAT_ANY.search(x.name) or _CENTRAL.search(x.name))
        hm, hx = head_word(split_unit(m.name)[0] or m.name), head_word(split_unit(x.name)[0] or x.name)
        if hm and hm == hx and m.additive == x.additive:
            return True
        if not (m.additive and x.additive and m.nonneg and x.nonneg) or m.stock != x.stock:
            return False
        return self._ordinal_dim

    @cached_property
    def _ordinal_dim(self) -> bool:
        """Категории — порядковые группы («0–4», «5–9», «70 и старше»)."""
        dj = self.cat_dim()
        if dj is None:
            return False
        labs = {self.text(i, dj) for i in self.rows_idx} - {""}
        return bool(labs) and sum(1 for x in labs if _ORDINAL_LABEL.match(x)) >= 0.8 * len(labs)

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
    def composition_constant(self) -> bool:
        """Части одного целого в одной и той же пропорции в каждой строке (налог — один процент цены)."""
        g = self.part_group
        if not g or len(g) < 2:
            return False
        shares = []
        for i in self.rows_idx:
            vals = [x.values[i] for x in g]
            if all(v is not None for v in vals) and sum(vals) > 0:  # type: ignore[arg-type]
                shares.append(vals[0] / sum(vals) * 100)  # type: ignore[arg-type, operator]
        return len(shares) >= 2 and max(shares) - min(shares) < 0.5

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
        tv = self.time_view(self.main)
        if tv is None and self.profile.time_axis is None:
            return self.columns_time  # колонки-периоды — ось, если её просит цель (балл задачи — в task_scores)
        return tv

    @cached_property
    def columns_time(self) -> Optional[TimeView]:
        return columns_time_view(self)

    def time_view(self, m: Optional[Measure], max_points: int = MAX_POINTS) -> Optional[TimeView]:
        return time_view(self, m, max_points)

    # ── перекрёстная таблица: строки × колонки одной величины ────────────────────────────────────────────────────
    @cached_property
    def matrix(self) -> list[Measure]:
        """Колонки одной величины по второму признаку (часы × дни недели, ученики × предметы, регионы × каналы): одна
        колонка не представляет всю таблицу — сравнивают итоги (сумма) или средние строк или колонок. Признак: от трёх
        колонок одной единицы, рода и сложения; имена — значения признака (дни, месяцы, годы, названия), а не разные
        величины («Выручка · Расходы · Прибыль»)."""
        if self.time_col is not None or self.part_group or self.plan_fact is not None:
            return []
        # подгруппы с размером выборки («Продажи (n=120)») — значения признака; колонка по всем — не подгруппа
        ms = [m for m in self.measures if not is_total_label(m.name) and not _OVERALL.match(_no_n(m.name))]
        if len(ms) < 3 or any(m.change or m.mixed for m in ms):
            return []
        if len({m.unit_text or "" for m in ms}) != 1 or len({m.type for m in ms}) != 1 \
                or len({m.additive for m in ms}) != 1:
            return []
        names = [_no_n((split_unit(m.name)[0] or m.name).strip()) for m in ms]
        if all(re.fullmatch(r"(?:19|20)\d\d", n) for n in names):
            return []  # колонки-годы — ось времени, а не второй признак: годы не складывают как категории
        calendar = all(_WEEKDAY.match(n) or season_name(n) or re.fullmatch(r"(?:19|20)\d\d", n) for n in names)
        # колонки с размером выборки («Продажи (n=120)», «ИТ (n=85)») — подгруппы, даже если имя похоже на величину
        subgroups = sum(1 for m in ms if re.search(r"\(\s*n\s*=", m.name)) >= 2
        if not calendar and not subgroups and any(_METRIC_WORD.search(n) or len(n.split()) > 3 or re.search(r"\d", n)
                                                  for n in names):
            return []
        if not calendar:
            # варианты одной величины («Город · Трасса · Смешанный», «Пиковая зона · Ночная зона») — не значения
            # второго признака: общее слово в именах или сводная колонка («смешанный», «средний»)
            words = [set(re.findall(r"[а-яёa-z]{3,}", n.lower())) for n in names]
            if set.intersection(*words) or any(_CENTRAL.search(n) or _STAT_ANY.search(n) for n in names):
                return []
        means = [sum(m.present) / len(m.present) for m in ms if m.present]
        if len(means) != len(ms) or min(means) <= 0 or max(means) > 5 * min(means):
            return []
        dj = self._matrix_rows()
        return ms if dj is not None else []

    def _matrix_rows(self) -> Optional[int]:
        """Подпись строк перекрёстной таблицы: каждая строка — своя (часы, ученики, регионы)."""
        for j in ([self.label] if self.label is not None else []) + list(self.dims):
            labs = [self.text(i, j) for i in self.rows_idx]
            if labs and all(labs) and len(set(labs)) == len(labs):
                return j
        return None

    @cached_property
    def matrix_axis(self) -> Optional[str]:
        """Что сравнивать в перекрёстной таблице: строки («row» — итог или среднее строки по всем колонкам) или колонки
        («col» — дни недели, предметы). Цель решает: названы строки — строки; названы колонки как род («дни недели»,
        «месяцы», «годы») или цель говорит о другом, чем строки и отдельные колонки, — колонки; названа одна колонка
        («по алгебре») — она и сравнивается (тогда она названа в заголовке). Без цели — строки."""
        ms = self.matrix
        if not ms:
            return None
        # колонка по всем или итог строк уже есть («Все сотрудники», «Итого за квартал»): строки сравнивают по ней
        overall = any(_OVERALL.match(_no_n(m.name)) for m in self.measures) or self.total_metric is not None
        rj0 = self._matrix_rows()
        if self.subject_word and rj0 is not None and not stems_match(self.subject, self.cols[rj0].name) \
                and not any(stem_in(s, m.name) for s in self.subject for m in ms):
            return "col"  # «в каком отделе хуже всего» — колонки-отделы, а не строки-утверждения
        if not self.subject:
            return None if overall else "row"  # есть колонка по всем — строки сравнивают по ней
        rj = self._matrix_rows()
        if rj is not None and stems_match(self.subject, self.cols[rj].name):
            return None if overall else "row"  # «сравни регионы» при «Итого за год» — по итогу, а не сумме колонок
        names = " ".join(m.name for m in ms)
        if any(stem_in(s, m.name) for s in self.subject for m in ms):
            return None
        # колонки сравнивают, только когда цель называет их род («по дням недели», «по месяцам»); цель о другом
        # («сколько всего отгрузили за полугодие») — итоги строк, а не «июнь — 19%»
        if re.search(r"(?:^|\s)(?:дн|недел|месяц|квартал|предмет|колонк|столбц)", " ".join(self.subject)):
            return "col"
        return None if overall else "row"

    @cached_property
    def matrix_note(self) -> Optional[str]:
        """Как собраны значения перекрёстной таблицы — для заголовка: «сумма Пн–Вс», «в среднем по 6 строкам»."""
        ms, ax = self.matrix, self.matrix_axis
        if not ms or ax is None:
            return None
        add = ms[0].additive
        if ax == "row":
            first, last = ms[0].name, ms[-1].name
            return (f"сумма {first}–{last}" if add else f"среднее {first}–{last}") if len(first) <= 12 and \
                len(last) <= 12 else (f"сумма по {len(ms)} колонкам" if add else f"в среднем по {len(ms)} колонкам")
        if self.matrix_focus_rows:
            rj = self._matrix_rows()
            return f"«{self.text(self.matrix_focus_rows[0], rj)}»" if rj is not None else None
        n = len(self.rows_idx)
        return f"сумма по {n} строкам" if add else f"в среднем по {n} строкам"

    def _matrix_view(self) -> Optional[CatView]:
        ms, ax = self.matrix, self.matrix_axis
        rj = self._matrix_rows()
        if not ms or ax is None or rj is None:
            return None
        add = ms[0].additive
        unit = ms[0].unit
        if ax == "row":
            vals: list[Optional[float]] = []
            for i in range(len(self.table.rows)):
                xs = [m.values[i] for m in ms if m.values[i] is not None] if i in set(self.rows_idx) else []
                vals.append(None if not xs else float(sum(xs)) if add else float(sum(xs) / len(xs)))
            vm = Measure(j=-3, name=upper_first(self.matrix_note or ""), unit=unit, type=ms[0].type, values=vals,
                         level=not add, time_unit=ms[0].time_unit, basis=ms[0].basis, scale=ms[0].scale)
            return self.cat_view(vm)
        aggs = []
        rows = self.matrix_focus_rows or self.rows_idx
        for m in ms:
            xs = [m.values[i] for i in rows if m.values[i] is not None]
            aggs.append((float(sum(xs)) if add else float(sum(xs) / len(xs))) if xs else 0.0)
        order = sorted(range(len(ms)), key=lambda k: (-aggs[k], k))
        vm = Measure(j=-4, name=upper_first(self.matrix_note or ""), unit=unit, type=ms[0].type, values=[],
                     level=not add, time_unit=ms[0].time_unit, basis=ms[0].basis, scale=ms[0].scale)
        dim = "День недели" if all(_WEEKDAY.match(m.name.strip()) for m in ms) else \
            upper_first(self.subject_word or "Колонка")
        return CatView(dim=dim, labels=[ms[k].name for k in order], values=[aggs[k] for k in order], measure=vm,
                       ranked=True, total=float(sum(aggs)) if add else None, distinct=len(ms), aggregated=True)

    @cached_property
    def matrix_focus_rows(self) -> list[int]:
        """Строка, которую называет цель при сравнении колонок («сравните отделы по удовлетворённости зарплатой» →
        «Моя зарплата справедлива»): колонки сравнивают по ней, а не по среднему всех строк."""
        rj = self._matrix_rows()
        if rj is None or not self.subject:
            return []
        dimw = (self.subject_word or "").lower()[:5]
        # слово-род колонок («отдел») — не о строке: «Я понимаю цели своего отдела» не названа целью «в каком отделе»
        subj = [x for x in self.subject if len(x) >= 5 and not (dimw and x.startswith(dimw[:4]))]
        hits = [i for i in self.rows_idx if any(stem_in(x, w) for x in subj for w in stems_of(self.text(i, rj)))]
        return hits if len(hits) == 1 else []

    @cached_property
    def subject_word(self) -> Optional[str]:
        """Предмет цели как подпись оси колонок («Предмет», «Канал»), если цель его называет."""
        words = {"предмет": "Предмет", "дисциплин": "Дисциплина", "канал": "Канал", "месяц": "Месяц", "год": "Год",
                 "квартал": "Квартал", "магазин": "Магазин", "регион": "Регион", "город": "Город", "отдел": "Отдел",
                 "филиал": "Филиал", "продукт": "Продукт", "товар": "Товар", "направлен": "Направление"}
        for s_ in self.subject:
            for k, v in words.items():
                if s_.startswith(k):
                    return v
        return None

    @cached_property
    def cats(self) -> Optional[CatView]:
        if self.matrix and self.matrix_axis is not None:
            mv = self._matrix_view()
            if mv is not None:
                return mv
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
        if self.main is None:
            # без метрики считают строки по группам — нужна колонка с повторами, а не подпись каждой строки
            cands = [j for j in cands if self.cols[j].distinct < self.n] or cands
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

    @cached_property
    def panel_latest(self) -> Optional[tuple[set[int], str, str]]:
        """Таблица «период × категория» (тарифы регионов по годам, OEE линий по месяцам): строки последнего периода и
        его подпись. Уровень, цену и остаток сравнивают по последнему периоду («в 2025»), а не средним за все годы."""
        if self.time_col is None:
            return None
        keys: dict[int, tuple] = {}
        for i in self.rows_idx:
            v = self.cell(i, self.time_col)
            iso = period_str(str(v), True, years=True) if v is not None else None
            r = iso_ord(iso) if iso else None
            if r is not None:
                keys[i] = (r[1], iso)
        if len(keys) < 2 or len({k for k, _ in keys.values()}) < 2:
            return None
        last = max(k for k, _ in keys.values())
        first = min(k for k, _ in keys.values())
        rows = {i for i, (k, _) in keys.items() if k == last}
        iso = next(x for k, x in keys.values() if k == last)
        iso0 = next(x for k, x in keys.values() if k == first)
        return rows, iso, iso0

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

        latest = self.panel_latest if dj != self.time_col else None

        def value_of(mm: Optional[Measure], idx: list[int]) -> Optional[float]:
            if mm is None:
                return float(len(idx))
            if latest is not None and mm is not None and (mm.stock or (not mm.additive and self.weight_of(mm) is None)):
                # уровень и остаток по периодам: последний период, а не среднее (или сумма) всех лет; уровень с весом
                # (средний чек и число чеков) — среднее взвешенное за весь период, оно и есть «средний чек за квартал»
                idx = [i for i in idx if i in latest[0]] or idx
            xs = [mm.values[i] for i in idx if mm.values[i] is not None]
            if not xs:
                return None
            if len(xs) == 1:
                return float(xs[0])
            if mm.additive or mm.stock:
                # сумма без «хвоста» двоичной арифметики: 330.09999999999997 → 330.1
                return round(float(sum(xs)), 9)
            w = self.weight_of(mm)
            if w is not None:
                # уровень с весом («Средний чек» и «Чеков», NPS и «Ответов»): среднее взвешенное, не среднее средних
                pairs = [(mm.values[i], w.values[i]) for i in idx if mm.values[i] is not None and w.values[i]]
                tw = sum(float(b_) for _, b_ in pairs)  # type: ignore[arg-type]
                if pairs and tw > 0:
                    return round(sum(float(a_) * float(b_) for a_, b_ in pairs) / tw, 9)  # type: ignore[arg-type]
            return round(float(sum(xs) / len(xs)), 9)

        labels = list(groups)
        values = [value_of(m, groups[g]) for g in labels]
        keep = [k for k, v in enumerate(values) if v is not None]
        labels = [labels[k] for k in keep]
        values = [values[k] for k in keep]  # type: ignore[misc]
        if len(labels) < 2:
            return None
        extra_ms = [mm for mm in self.measures if mm is not m and not mm.mixed]
        extra = {mm.name: [value_of(mm, groups[g]) for g in labels] for mm in extra_ms}
        ordinal = sum(1 for x in labels if _ORDINAL_LABEL.match(x)) >= 0.8 * len(labels) and dj not in self.status_cols
        ranked = rank and not ordinal and not (dj == self.label and self.funnel)
        order = list(range(len(labels)))
        key_vals = list(values)
        if rank_with:
            # состав: порядок — по сумме всех частей категории
            key_vals = [sum((value_of(mm, groups[g]) or 0.0) for mm in rank_with) for g in labels]
        if ranked:
            # «Прочее», «Другие» — в конце списка, по какому бы значению они ни шли
            order.sort(key=lambda k: (is_other_label(labels[k]), -key_vals[k], k))
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
        others = cut = merged = 0
        low: tuple[Optional[str], Optional[float]] = (None, None)
        summable = m is None or m.additive or m.stock
        clock = sum(1 for x in labels if _CLOCK.match(x)) >= 0.8 * len(labels)
        if not ranked and len(labels) > max(top, MAX_ORDINAL) and not (clock and len(labels) <= 48):
            # порядковые группы («0–4», «5–9», …) не обрезаются молча: хвост — одной подписанной группой (у уровня —
            # «в среднем»); часы суток («00:00 … 23:00») — ось, их не сворачивают
            head = max(top, MAX_ORDINAL) - 1
            merged = len(labels) - head
            tail_lab = f"{labels[head]} … {labels[-1]}" + ("" if summable else " (в среднем)")
            tail_v = float(sum(values[head:])) if summable else float(sum(values[head:]) / merged)
            labels, values = labels[:head] + [tail_lab], values[:head] + [tail_v]
            extra = {k: v[:head] + [None] for k, v in extra.items()}
        elif ranked and len(labels) > top:
            if m is None or m.additive:
                head = top - 1
                others = len(labels) - head
                rest = float(sum(values[head:]))
                labels = labels[:head] + [f"Остальные {others}"]
                values = values[:head] + [rest]
                extra = {k: v[:head] + [None] for k, v in extra.items()}
            else:
                # уровень (средний чек, балл) не складывается в «Остальные»: первые по значению и честное «из N»
                cut = len(labels) - top
                real = [k for k in range(len(labels)) if not is_other_label(labels[k])] or list(range(len(labels)))
                lk = min(real, key=lambda k: (values[k], k))
                low = (labels[lk], values[lk])
                labels, values = labels[:top], values[:top]
                extra = {k: v[:top] for k, v in extra.items()}
        return CatView(
            dim=self.cols[dj].name, labels=labels, values=values, measure=m, extra=extra, extra_measures=extra_ms,
            others=others, ranked=ranked, total=total, total_from_row=total_row, distinct=distinct, aggregated=aggregated,
            cut=cut, merged=merged, low_label=low[0], low_value=low[1],
        )

    @cached_property
    def freq_table(self) -> Optional[tuple[Measure, Measure]]:
        """Готовая частотная таблица: значение (оценка, число детей, размер) и сколько раз оно встретилось («Оценка |
        Число учеников»). Это распределение значения, взвешенное счётом, а не две величины и не список."""
        ms = [m for m in self.measures if not m.change and not m.mixed]
        if len(ms) != 2 or len(self.measures) != 2 or self.label is not None or self.time_col is not None:
            return None
        v, c = sorted(ms, key=lambda x: x.j)
        vals = [v.values[i] for i in self.rows_idx]
        cnt = [c.values[i] for i in self.rows_idx]
        if any(x is None for x in vals + cnt) or not 3 <= len(vals) <= 20 or len(set(vals)) != len(vals):
            return None
        if any(not float(2 * x).is_integer() for x in vals):  # type: ignore[operator]
            return None
        if not (vals == sorted(vals) or vals == sorted(vals, reverse=True)):  # type: ignore[type-var]
            return None
        if any(not float(x).is_integer() or x < 0 for x in cnt):  # type: ignore[operator, union-attr]
            return None
        if not (_COUNT_NAME.search(c.name) or is_counter(c.name) or (c.unit or "").rstrip(".") in ("чел", "шт", "ед")):
            return None
        return v, c

    @cached_property
    def dist(self) -> Optional[DistView]:
        ft = self.freq_table
        if ft is not None:
            # частотная таблица: значения, повторённые столько раз, сколько их было; интервалы — сами значения
            v, c = ft
            vals = [float(v.values[i]) for i in self.rows_idx]  # type: ignore[arg-type]
            cnt = [int(c.values[i]) for i in self.rows_idx]  # type: ignore[arg-type]
            order = sorted(range(len(vals)), key=lambda k: vals[k])
            x = np.repeat(np.array([vals[k] for k in order]), [cnt[k] for k in order]).astype(float)
            step = min(b - a for a, b in zip(sorted(vals), sorted(vals)[1:])) if len(vals) > 1 else 1.0
            bins = Bins(edges=[vals[k] for k in order], counts=[cnt[k] for k in order],
                        labels=[fmt_num(vals[k]) for k in order], width=step)
            return DistView(measure=v, values=x, inliers=x, outliers=[], bins=bins, entity=None)
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
        uniq = np.unique(inl)
        if 3 <= uniq.size <= MAX_DISCRETE_BINS:
            # значений мало (размеры стипендий, оценки, размеры одежды): столбец на каждое значение — без пустых
            # интервалов между ними
            bins = Bins(edges=[float(v) for v in uniq], counts=[int((inl == v).sum()) for v in uniq],
                        labels=[fmt_num(float(v)) for v in uniq],
                        width=float(np.diff(uniq).min()) if uniq.size > 1 else 1.0, discrete=True)
        else:
            bins = histogram_bins(inl, m.unit_text)
        if outliers and inl.size and bins.discrete:
            hi = [v for v in outliers if v > float(inl.max())]
            lo = [v for v in outliers if v < float(inl.min())]
            if hi:  # выбросы — одним крайним столбцом «от X» (все значения больше обычных)
                bins.counts.append(len(hi))
                bins.labels.append(f"от {fmt_num(min(hi))}")
                bins.open_from = float(inl.max())
            if lo:
                bins.counts.insert(0, len(lo))
                bins.labels.insert(0, f"до {fmt_num(max(lo))}")
                bins.open_to = float(inl.min())
        elif outliers and inl.size:
            # выбросы — на графике, в крайних столбцах: «больше 180» считает все значения больше 180, а не только обычные
            hi = [v for v in outliers if v > float(inl.max())]
            lo = [v for v in outliers if v < float(inl.min())]
            if hi:
                if bins.open_from is not None:
                    bins.counts[-1] += sum(1 for v in hi if v > bins.open_from)
                else:
                    bins.counts.append(len(hi))
                    bins.labels.append(f"больше {fmt_num(bins.edges[-1])}")
                    bins.open_from = bins.edges[-1]
            if lo:
                bins.counts.insert(0, len(lo))
                bins.labels.insert(0, f"меньше {fmt_num(bins.edges[0])}")
                bins.open_to = bins.edges[0]
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

