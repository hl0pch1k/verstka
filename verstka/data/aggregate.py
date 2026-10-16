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
from functools import cached_property
from typing import Any, Optional

import numpy as np

from verstka.data.kpi import _kpi_view
from verstka.data.parse import is_total_label, split_unit
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
from verstka.data.words import fmt_num, head_word, is_counter, same_stem, stems_match, stems_of, upper_first
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
_CENTRAL = re.compile(r"(?:^|[^а-яёa-z])(?:медиан\w*|средн\w*|median|mean|average)", re.I)
_STAT_ANY = re.compile(r"(?:^|[^а-яёa-z])(?:минимум\w*|максимум\w*|мин\.|макс\.|минимальн\w*|максимальн\w*|min|max)",
                       re.I)
# «Прочее», «Другие», «Остальное» — строка-остаток: в конце списка и никогда не лидер
_OTHER = re.compile(r"^(?:прочее|прочие|другое|другие|остальное|остальные|иное|иные|прочее\s+\S+|другие\s+\S+)$", re.I)


def is_other_label(label: str) -> bool:
    return bool(_OTHER.match(" ".join(str(label).split())))


def stem_hits(subject: tuple[str, ...] | list[str], text: str) -> int:
    """Сколько основ предмета цели есть в тексте («доле брошенных корзин» и «Доля брошенных корзин» — 3)."""
    words = stems_of(text)
    return sum(1 for s in subject if any(same_stem(s, w) for w in words))


# ── главный объект ────────────────────────────────────────────────────────────────────────────────────────────────────
class Data:
    """Датасет для анализа: таблица, профиль, метрики, подписи и подготовленные виды (лениво)."""

    def __init__(self, table: Table, profile: DatasetProfile, subject: tuple[str, ...] = (), compare: bool = False):
        self.table = table
        self.profile = profile
        self.subject = subject
        # сравнение категорий: главная метрика — колонка-итог («Итого за год»), если она есть, а не первая часть
        self.compare = compare
        cols = profile.columns
        self.cols: list[ColumnProfile] = cols
        self.ncols = len(cols)
        self.totals: set[int] = self._total_rows()
        # строки-ориентиры («Среднее по стране», «Норматив»): не категория — не лидер, не последний, не доля
        self.benchmarks: dict[int, str] = self._benchmark_rows()
        self.rows_idx = [i for i in range(len(table.rows)) if i not in self.totals and i not in self.benchmarks]
        self.n = len(self.rows_idx)
        self.measures: list[Measure] = [build_measure(self, j, c) for j, c in enumerate(cols) if c.role == "metric"]
        self.measures = [m for m in self.measures if m.present]
        # номера, а не величины (аудитории в расписании): единственное «число» без единицы и признака суммы, с
        # повторами, среди трёх и больше текстовых колонок — таблицей, «не для графика»
        self.not_numbers: list[str] = []
        texts = [j for j, c in enumerate(cols) if c.role in ("dimension", "text") and c.type in ("category", "text")]
        if len(self.measures) == 1 and len(texts) >= 3:
            m0 = self.measures[0]
            pv = m0.present
            if not m0.unit and not m0.additive and pv and all(float(v).is_integer() for v in pv) \
                    and len(set(pv)) <= 0.7 * len(pv):
                self.not_numbers = [m0.name]
                self.measures = []
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
        """Главная метрика: названная целью (больше всего совпавших основ слов); для сравнения — колонка-итог; иначе
        поток денег (выручка, а не цена или минимум); оценка (балл); центральная статистика (медиана, среднее); деньги-
        уровень; не счётчик; первая не-изменение."""
        ms = self.measures
        if not ms:
            return None
        if self.subject:
            hits = [(stem_hits(self.subject, m.name), -k) for k, m in enumerate(ms)]
            best = max(range(len(ms)), key=lambda k: hits[k])
            if hits[best][0] > 0:
                return ms[best]
        if self.compare and self.total_metric is not None:
            return self.total_metric

        def latest(m: Measure) -> Measure:
            """Колонки-периоды («Выручка 2025 · Выручка 2026»): главная — последний период."""
            if not _period_name(m.name):
                return m
            sib = [x for x in ms if _period_name(x.name) and (x.unit or "") == (m.unit or "") and not x.change]
            return max(sib, key=lambda x: (_period_key(x.name), x.j)) if len(sib) >= 2 else m

        for pred in (
            lambda m: m.type == "money" and not m.change and not m.mixed and m.additive,
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
        if m is None or m.change or m.mixed or m is self.total_metric:
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
        if not ranked and len(labels) > max(top, MAX_ORDINAL):
            # порядковые группы («0–4», «5–9», …) не обрезаются молча: хвост — одной подписанной группой
            head = max(top, MAX_ORDINAL) - 1
            merged = len(labels) - head
            tail_lab = f"{labels[head]} … {labels[-1]}"
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

