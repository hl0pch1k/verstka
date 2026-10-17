"""Цели брифа, понятые моделью (вторая ступень, раунд 10) — с проверкой кодом.

Разбор брифа правилами (`verstka/data/goals.py`) понимает «покажи рост выручки», а на естественных брифах («Хотим понять,
какие курсы бросают чаще всего», «где дольше всего ждут решения по заявлению») колода отвечает на вопрос брифа лишь
в половине случаев. Здесь модель (навык `goal_reader`) читает бриф и предлагает СТРУКТУРНЫЕ цели — только о настоящих
датасетах и колонках: цитата из брифа, датасет, задача, колонка-величина, разрез, названные категории, что спрошено
(наибольшее, наименьшее, итог, среднее, самый быстрый рост, отрыв, порог, всплеск, выполнение плана), агрегация,
период, направление «лучше», порог с единицей, с чем сравнить, вопрос «да/нет», уверенность; и предложения брифа, на
которые данные ответить не могут, — с причиной.

Код проверяет всё (`_validate`): цитата есть в брифе, датасет и колонки существуют, задача осуществима на датасете
(`task.task_scores`; сравнение периодов одного ряда — динамика, годы колонками — сравнение), агрегация подходит величине
(сумму не берут у долей, средних и уровней), единица порога — единица колонки, периоды — периоды данных (диапазон на всю
ось — «все данные»). Неверная часть отбрасывается с причиной (`UnderstoodGoal.dropped`); не осталось ни одной цели и ни
одной пометки — запасной путь: бриф разбирают правила (`goals=None`). Правила остаются и сверкой (`_merge`): цель
правил, о которой модель промолчала, сохраняется; где обе говорят об одном месте брифа и расходятся, берётся цель
модели, если её цитаты накрывают цитату правил (кроме решения или цели действия, о которых данные не спрашивают:
«…, чтобы разобрать на планёрке», «и стоит ли его менять»), иначе — цель правил.

Понятая цель становится `goals.Goal` для `plan_datasets(goals=…)` (`_to_goal`, `_fit`): фраза — цитата брифа (её и видит
человек в «Почему так»), предмет — слова названия файла (цель попадает в свой датасет), величина и главное слово —
слова колонки, вопрос — `ask`; что план возьмёт именно эту колонку и этот датасет, проверено тут же его же функциями.
Порог («какие ниже 90%») идёт первым среди целей датасета: слайд у датасета один, и порог план прикладывает к колонке,
которую показывает. Предложение без ответа в данных — цель с причиной (`unmet`): «Цель «…» здесь не подходит: …» в
«Почему так» её датасета, а без датасета — строка контекста колоды (`goal_notes`).

Числа модель не пишет: она называет колонку и вопрос, а считает и проверяет всё код (`facts`, `verify`).

Один вызов на генерацию — все датасеты вместе, короткий срок (`BUDGET_S`); второй — только если первый вернул пустой
объект «{}» (Qwen так отвечает на некоторые брифы при любой температуре). Без вопроса или просьбы в брифе вызова нет;
ответ кешируется по хешу брифа и хешам таблиц (сборка после «Целей из текста» модель снова не зовёт). Без модели —
ровно прежнее поведение: `goals=None`, бриф разбирает `goals_of`; понятые правилами цели (`understood`) — только для
показа в интерфейсе («Цели из текста»)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field, field_validator

from verstka.data.aggregate import Data
from verstka.data.goals import GOAL_VIZ, Goal, GoalPeriod, goals_of
from verstka.data.goals import stems_of as goal_stems
from verstka.data.profile import profile_table
from verstka.data.task import FEASIBLE, task_scores
from verstka.data.words import file_title, is_period_name, stem, stems_of
from verstka.schemas.data import NATURE_LABELS, TASK_TITLES, DatasetProfile, Table

log = logging.getLogger(__name__)

__all__ = [
    "SKILL", "BUDGET_S", "GoalReading", "ModelGoal", "ModelMiss", "UnderstoodGoal", "IntentNote", "GoalsRead",
    "read_goals", "rules_goals", "goal_notes", "say_goals", "dataset_cards", "looks_like_goal", "clear_cache",
]

SKILL = "goal_reader"
BUDGET_S = 30.0  # one call: past it the rules parse the brief (the deck does not wait for the model's understanding)
CACHE_SIZE = 128
MAX_VALUES = 8  # distinct values of a category column shown to the model
MAX_PERIODS = 24  # periods of a time axis listed one by one; longer — first … last

TASKS = ("dynamics", "comparison", "shares", "distribution", "relationship", "kpi", "reference")
ASKS = ("max", "min", "total", "mean", "fastest", "margin", "above", "below", "spike", "meet", "top_n", "share", "product",
        "compare_columns")
# что колода не считает (F2): ответа нет — видимая пометка, а не итог вместо ответа
UNMET = "по данным этот вопрос не посчитан"
AGGS = ("sum", "mean", "weighted_mean", "latest", "total_row")
PERIODS = ("all", "latest", "range", "compare")
TARGETS = ("plan", "target", "previous_period", "column", "category")
# the engine reads these asks of a given goal (verstka/data/plan.py, goal_data): «max» is the plan's default (the
# leader), the rest are kept on the goal for the record
_ENGINE_ASKS = ("fastest", "total", "mean", "margin", "min")
# a task the data cannot do → the nearest one that still answers the question («какая доля…» on data that is no whole)
_REMAP = {"shares": "comparison", "kpi": "comparison", "distribution": "comparison"}


# ── what the model returns (lenient: wrong parts are dropped by the code, not by the parser) ──────────────────────────
class ModelThreshold(BaseModel):
    value: float = Field(description="число порога, как в тексте брифа (15 для «больше 15 дней»)")
    unit: Optional[str] = Field(None, description="единица порога, как в брифе: «%», «дн.», «ppm», «баллов»; null — без единицы")


class ModelPeriod(BaseModel):
    kind: str = Field("all", description="all | latest | range | compare")
    start: Optional[str] = Field(None, description="range: первый период, как в данных («2025-06», «2021»)")
    end: Optional[str] = Field(None, description="range: последний период")
    base: Optional[str] = Field(None, description="compare: с чем сравнивают — период A (или его начало)")
    target: Optional[str] = Field(None, description="compare: что сравнивают — период B (или его начало)")
    base_end: Optional[str] = Field(None, description="compare: последний период A, когда A — диапазон")
    target_end: Optional[str] = Field(None, description="compare: последний период B, когда B — диапазон")


class ModelRatio(BaseModel):
    num: str = Field("", description="колонка-числитель, точное имя («Выручка» в «выручка на посетителя»)")
    den: str = Field("", description="колонка-знаменатель, точное имя («Посетители»)")


class ModelCompare(BaseModel):
    kind: str = Field(description="plan | target | previous_period | column | category")
    name: Optional[str] = Field(None, description="column / category: точное имя колонки или значения из данных")


class ModelGoal(BaseModel):
    span: str = Field("", description="точная цитата из брифа: всё предложение (или часть предложения), где цель")
    dataset: str = Field("", description="id датасета («d1»)")
    task: str = Field("", description="dynamics | comparison | shares | distribution | relationship | kpi | reference")
    metric: Optional[str] = Field(None, description="точное имя колонки-величины из данных; null — величина не названа")
    dimension: Optional[str] = Field(None, description="точное имя колонки-разреза (категории или время); null — разрез по данным")
    categories: list[str] = Field(default_factory=list, description="значения категорий, названные в брифе, точно как в данных")
    ask: Optional[str] = Field(None, description=(
        "max | min | total | mean | fastest | margin | above | below | spike | meet | top_n (доля N крупнейших, n) | "
        "share (доля названных категорий) | compare_columns (строки, где одна колонка меньше/больше другой: compare_to "
        "column) | product (ожидаемое значение, сумма × вероятность — колода его не считает); null — общий вывод"))
    aggregation: Optional[str] = Field(None, description=(
        "sum | mean | weighted_mean | latest | total_row; null — как принято для величины. Величина на единицу («на "
        "посетителя», «за сеанс», «на место») — не weighted_mean, а ratio"))
    weight: Optional[str] = Field(None, description="weighted_mean: колонка-вес, точное имя")
    period: Optional[ModelPeriod] = None
    direction: Optional[str] = Field(None, description="higher | lower — какое значение величины лучше")
    threshold: Optional[ModelThreshold] = None
    compare_to: Optional[ModelCompare] = None
    yes_no: bool = Field(False, description="вопрос «да или нет» («вырос ли», «укладываются ли»)")
    ratio: Optional[ModelRatio] = Field(None, description="величина на единицу: num / den («на посетителя», «за сеанс»)")
    n: Optional[int] = Field(None, description="top_n: сколько первых категорий («пять крупнейших» → 5)")
    confidence: float = Field(0.7, description="0…1")

    @field_validator("n", mode="before")
    @classmethod
    def _n(cls, v: Any) -> Any:
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    @field_validator("period", mode="before")
    @classmethod
    def _period(cls, v: Any) -> Any:
        return {"kind": v} if isinstance(v, str) else v

    @field_validator("threshold", mode="before")
    @classmethod
    def _threshold(cls, v: Any) -> Any:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return {"value": v}
        if isinstance(v, str):
            m = re.match(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(.*)$", v)
            return {"value": float(m.group(1).replace(",", ".")), "unit": m.group(2).strip() or None} if m else None
        return v

    @field_validator("compare_to", mode="before")
    @classmethod
    def _compare(cls, v: Any) -> Any:
        return {"kind": v} if isinstance(v, str) else v

    @field_validator("categories", mode="before")
    @classmethod
    def _cats(cls, v: Any) -> Any:
        if v is None:
            return []
        return [v] if isinstance(v, str) else v

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: Any) -> Any:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.5


class ModelMiss(BaseModel):
    span: str = Field("", description="точная цитата из брифа: предложение (или часть), на которое данные не отвечают")
    reason: str = Field("", description="почему: чего нет в данных — по-русски, со строчной буквы, без чисел")
    dataset: Optional[str] = Field(None, description="id датасета, о котором это предложение, или null")


class GoalReading(BaseModel):
    """Output of the `goal_reader` skill: the brief's goals over the real datasets and columns, and the brief's
    sentences the data cannot answer. The program checks every part and drops what is wrong."""

    goals: list[ModelGoal] = Field(default_factory=list)
    unanswerable: list[ModelMiss] = Field(default_factory=list)

    @field_validator("goals", "unanswerable", mode="before")
    @classmethod
    def _list(cls, v: Any) -> Any:
        return [] if v is None else v


# ── what the code keeps ──────────────────────────────────────────────────────────────────────────────────────────────
class UnderstoodGoal(BaseModel):
    """A goal after the checks — what the interface shows under «Цели из текста» and the run manifest keeps."""

    quote: str  # the brief's words, as written
    at: int = 0  # where in the brief
    dataset: str  # the dataset's id (the generation's dataset ids, or the tables' ids)
    file: str
    sheet: Optional[str] = None
    task: str
    metric: Optional[str] = None
    dimension: Optional[str] = None
    categories: list[str] = Field(default_factory=list)
    ask: Optional[str] = None  # max | min | total | mean | fastest | margin | above:X | below:X | spike | meet
    aggregation: Optional[str] = None
    weight: Optional[str] = None
    period: Optional[ModelPeriod] = None
    direction: Optional[str] = None
    threshold: Optional[ModelThreshold] = None
    compare_to: Optional[ModelCompare] = None
    yes_no: bool = False
    ratio: Optional[dict] = None  # {"num", "den", "name", …}: колонка-отношение (verstka/data/derive.py)
    n: Optional[int] = None
    versus: Optional[str] = None  # колонка, с которой сравнивают по строкам
    confidence: float = 1.0
    source: Literal["model", "rules"] = "model"
    label: str = ""  # «Сравнение категорий · «Срок рассмотрения» · где больше всего»
    dropped: list[str] = Field(default_factory=list)  # parts the checks dropped, with the reason
    pinned: Optional[bool] = None  # the plan shows exactly this column (checked here); None — no column named


class IntentNote(BaseModel):
    """A sentence of the brief the data cannot answer — the visible note in «Почему так» (or the deck's context)."""

    quote: str
    reason: str
    at: int = 0
    dataset: Optional[str] = None
    file: Optional[str] = None
    source: Literal["model", "rules"] = "model"
    weak: bool = False  # причина модели пустая или с чужими числами: цель правил о тех же словах — главнее (F14)


@dataclass
class GoalsRead:
    """What `read_goals` understood. `goals` go to `plan_datasets(goals=…)` / `build_data_story(goals=…)`; None — the
    rules parse the brief there exactly as before (no model, the model failed, or nothing it said held)."""

    source: str  # "model" | "rules"
    goals: Optional[list[Goal]]
    understood: list[UnderstoodGoal] = field(default_factory=list)
    notes: list[IntentNote] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)  # {"quote", "why"}: the model's goals or notes refused whole
    model: Optional[str] = None
    error: Optional[str] = None
    skipped: Optional[str] = None  # why the model was not asked
    cached: bool = False
    seconds: float = 0.0
    raw: Optional[dict] = None  # the model's answer, as parsed
    # таблицы с колонками-отношениями целей («выручка на одного посетителя»): план строится по ним; None — как есть
    tables: Optional[list] = None
    profiles: Optional[list] = None

    def payload(self) -> dict:
        """The answer of POST /api/goals («Цели из текста»): each goal with its human label, the sentences without an
        answer, who understood them."""
        goals = []
        for u in self.understood:
            viz = GOAL_VIZ.get(u.task)  # type: ignore[call-overload]
            goals.append({
                "quote": u.quote, "dataset_id": u.dataset, "file": u.file, "sheet": u.sheet, "task": u.task,
                "task_title": TASK_TITLES.get(u.task, u.task),  # type: ignore[call-overload]
                "viz": viz[0] if viz else None, "viz_title": viz[1] if viz else None, "metric": u.metric,
                "dimension": u.dimension, "categories": list(u.categories), "ask": u.ask, "aggregation": u.aggregation,
                "weight": u.weight, "period": u.period.model_dump(exclude_none=True) if u.period is not None else None,
                "direction": u.direction, "threshold": u.threshold.model_dump() if u.threshold is not None else None,
                "yes_no": u.yes_no, "confidence": round(u.confidence, 2), "label": u.label, "source": u.source,
                "dropped": list(u.dropped),
            })
        return {
            "source": self.source, "model": self.model, "cached": self.cached, "seconds": round(self.seconds, 2),
            "error": self.error, "skipped": self.skipped, "goals": goals,
            "notes": [{"quote": n.quote, "reason": n.reason, "dataset_id": n.dataset, "file": n.file, "source": n.source}
                      for n in self.notes],
        }

    def summary(self) -> dict:
        """What the run manifest keeps (data_story.json, run_manifest.json → planner.data.goals)."""
        return {
            "source": self.source,
            "model": self.model,
            "error": self.error,
            "skipped": self.skipped,
            "cached": self.cached,
            "seconds": round(self.seconds, 2),
            "goals": [u.model_dump(exclude_none=True, exclude_defaults=True) | {"quote": u.quote, "task": u.task,
                                                                               "dataset": u.dataset, "file": u.file}
                      for u in self.understood],
            "notes": [n.model_dump(exclude_none=True) for n in self.notes],
            "dropped": list(self.dropped),
        }


# ── the datasets as the code and the model see them ──────────────────────────────────────────────────────────────────
class _Ctx:
    """The generation's datasets: tables, profiles, ids («d1»… for the model), `Data`, task scores."""

    def __init__(self, tables: Sequence[Table], profiles: Optional[Sequence[DatasetProfile]] = None,
                 dataset_ids: Optional[Sequence[str]] = None) -> None:
        self.tables = list(tables)
        self.profiles = list(profiles) if profiles is not None else [profile_table(t) for t in self.tables]
        self.ids = [str(x) for x in dataset_ids] if dataset_ids else [p.table_id for p in self.profiles]
        self.keys = [f"d{k + 1}" for k in range(len(self.tables))]
        self.datas = [Data(t, p) for t, p in zip(self.tables, self.profiles)]
        self.scores = [task_scores(d) for d in self.datas]
        self._periods: dict[int, list[str]] = {}
        self.derived: dict[int, list[dict]] = {}  # колонки-отношения целей, добавленные к таблицам

    def __len__(self) -> int:
        return len(self.tables)

    def derive(self, k: int, spec: dict) -> None:
        """Колонка-отношение цели («выручка на одного посетителя») — в таблицу датасета `k`: план и проверка видят её
        как данные (`verstka/data/derive.py`)."""
        from verstka.data.derive import apply

        t = apply(self.tables[k], spec)
        if t is self.tables[k]:
            return
        self.tables[k] = t
        self.profiles[k] = profile_table(t)
        self.datas[k] = Data(t, self.profiles[k])
        self.scores[k] = task_scores(self.datas[k])
        self._periods.pop(k, None)
        self.derived[k] = [*self.derived.get(k, []), spec]

    def index(self, ref: Optional[str]) -> Optional[int]:
        """The dataset the model named: «d2», the dataset's id, or its file name."""
        if ref is None:
            return None
        r = str(ref).strip().strip("«»\"'")
        if r in self.keys:
            return self.keys.index(r)
        if r in self.ids:
            return self.ids.index(r)
        low = _norm(r)
        for k, p in enumerate(self.profiles):
            names = {_norm(p.file), _norm(file_title(p.file, p.sheet)), _norm(file_title(p.file))}
            if p.sheet:
                names |= {_norm(f"{p.file} {p.sheet}"), _norm(p.sheet)}
            if low in names:
                return k
        return None

    def column(self, k: int, name: Optional[str]) -> Optional[str]:
        """The column of dataset `k` the model named (exact, or as the file writes it with its unit)."""
        if not name:
            return None
        t, p = self.tables[k], self.profiles[k]
        want = _norm(name)
        for c in p.columns:
            if _norm(c.name) == want:
                return c.name
        for j, c in enumerate(p.columns):
            raw = t.raw_header[j] if j < len(t.raw_header) else ""
            unit = c.unit or ""
            if want in {_norm(raw), _norm(f"{c.name}, {unit}"), _norm(f"{c.name} {unit}"), _norm(f"{c.name} ({unit})")}:
                return c.name
        return None

    def role(self, k: int, name: str) -> Optional[str]:
        return next((c.role for c in self.profiles[k].columns if c.name == name), None)

    def is_measure(self, k: int, name: str) -> bool:
        d = self.datas[k]
        return any(m.name == name for m in list(d.measures) + list(getattr(d, "forecasts", []) or []))

    def measure(self, k: int, name: Optional[str]):
        if not name:
            return None
        return self.datas[k].measure(name)

    def values(self, k: int) -> dict[str, str]:
        """Category values of dataset `k` (normalized → as written)."""
        d, out = self.datas[k], {}
        cols = list(d.dims) + ([d.label] if d.label is not None else [])
        for j in cols:
            for i in d.rows_idx[:400]:
                v = d.text(i, j)
                if v:
                    out.setdefault(_norm(v), v)
        return out

    def periods(self, k: int) -> list[str]:
        """The data's periods as the model may name them: the time axis (its points, its start and end), the periods of
        period columns («Июль · Август», «I кв. 2026») with their names, and years in the names of the measures («2024
        Штат · 2025 Штат»)."""
        if k in self._periods:
            return self._periods[k]
        p, d = self.profiles[k], self.datas[k]
        out: list[str] = []
        if p.time_axis is not None:
            out += [p.time_axis.start, p.time_axis.end]
            try:
                tv = d.time
            except Exception:  # noqa: BLE001 - a view the data cannot make
                tv = None
            if tv is not None and getattr(tv, "periods", None):
                out += [str(x) for x in tv.periods]
        try:
            ct = d.columns_time
        except Exception:  # noqa: BLE001
            ct = None
        if ct is not None and getattr(ct, "periods", None):
            out += [str(x) for x in ct.periods] + [m.name for m in d.measures if is_period_name(m.name)]
        years = sorted({y for c in p.columns if c.role == "metric" for y in re.findall(r"(?:19|20)\d\d", c.name)})
        if len(years) >= 2:
            out += years
        self._periods[k] = list(dict.fromkeys(x for x in out if x))
        return self._periods[k]

    def whole(self, k: int, period: ModelPeriod) -> bool:
        """The range holds every period of the data: from the first to the last point of the axis, or from the first to
        the last period column («Июль» — «Сентябрь»), or names no bounds."""
        a, b = _norm(period.start), _norm(period.end)
        names = [_norm(m.name) for m in self.datas[k].measures if is_period_name(m.name) and not re.search(r"итог|всего", m.name, re.I)]
        if a and b and len(names) >= 2 and a == names[0] and b == names[-1]:
            return True
        return _whole(period, self.periods(k))

    def has_time(self, k: int) -> bool:
        return self.profiles[k].time_axis is not None or len(self.periods(k)) >= 2

    def known_period(self, k: int, v: Optional[str]) -> bool:
        """`v` is one of the data's periods, or lies on its time axis («2025-11-01» on a daily axis 2025-10-01…12-15)."""
        if not v:
            return True
        x = _norm(v)
        if any(x == _norm(q) or _norm(q).startswith(x) or x.startswith(_norm(q)) for q in self.periods(k)):
            return True
        ta = self.profiles[k].time_axis
        if ta is not None and re.match(r"^\d{4}", x):
            return _iso_le(_week_date(_norm(ta.start)), x) and _iso_le(x, _week_date(_norm(ta.end), last=True))
        return False


def _week_date(iso: str, last: bool = False) -> str:
    """«2026-w23» (неделя ISO) → дата её понедельника (воскресенья — `last`): с ней сравниваются месяцы и дни."""
    import datetime as _dt

    m = re.fullmatch(r"(\d{4})-w(\d{1,2})", iso or "")
    if not m:
        return iso
    try:
        return _dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 7 if last else 1).isoformat()
    except ValueError:
        return iso


def _norm(s: Optional[str]) -> str:
    s = (s or "").lower().replace("ё", "е").replace(" ", " ")
    s = re.sub(r"[«»\"'“”„]", "", s)
    return " ".join(s.split()).strip(" .,;:!?—–-")


def dataset_cards(ctx: _Ctx) -> list[dict]:
    """The datasets for the model: id, file, nature, rows, time axis and periods, columns (type, role, unit, values of a
    category, range of a number, adds up or not, weight), total rows and columns, tasks the data can do."""
    cards = []
    for k, (t, p, d) in enumerate(zip(ctx.tables, ctx.profiles, ctx.datas)):
        cols = []
        forecasts = {m.name for m in getattr(d, "forecasts", []) or []}
        for j, c in enumerate(p.columns):
            col: dict[str, Any] = {"name": c.name, "type": c.type, "role": c.role, "unit": c.unit or None,
                                   "values": [], "distinct": c.distinct, "range": None, "adds_up": None,
                                   "weight": None, "forecast": False}
            m = d.measure(c.name)
            if c.role in ("dimension", "text") or (c.role == "id" and c.distinct <= 12):
                vals = []
                for i in d.rows_idx:
                    v = d.text(i, j)
                    if v and v not in vals:
                        vals.append(v)
                    if len(vals) >= MAX_VALUES:
                        break
                col["values"] = vals
            if m is not None:
                pv = m.present
                if pv:
                    col["range"] = [_short(min(pv)), _short(max(pv))]
                col["adds_up"] = m.additive
                w = d.weight_of(m)
                if w is not None:
                    col["weight"] = w.name
            if c.name in forecasts:
                col["forecast"] = True
            cols.append(col)
        time_ = None
        if p.time_axis is not None:
            ta = p.time_axis
            per = ctx.periods(k)
            time_ = {"column": ta.column, "freq": ta.freq, "start": ta.start, "end": ta.end, "points": ta.points,
                     "missing": len(ta.missing_periods)}
            if per and len(per) <= MAX_PERIODS:
                time_["periods"] = per
        period_cols = []
        try:
            ct = d.columns_time
        except Exception:  # noqa: BLE001
            ct = None
        if ct is not None:
            period_cols = [str(x) for x in getattr(ct, "periods", []) or []]
        totals = [str(t.rows[i][0]) for i in t.totals if t.rows and i < len(t.rows) and t.rows[i]]
        tasks = sorted((x for x, s in ctx.scores[k].items() if s >= FEASIBLE), key=lambda x: -ctx.scores[k][x])
        cards.append({
            "id": ctx.keys[k], "file": p.file, "sheet": p.sheet, "title": file_title(p.file, p.sheet),
            "nature": NATURE_LABELS.get(p.nature, p.nature), "rows": d.n, "time": time_, "period_columns": period_cols,
            "columns": cols, "total_rows": totals, "total_column": p.total_column,
            "benchmarks": list(getattr(d, "benchmarks", {}).values()), "forecast_rows": len(getattr(d, "forecast_rows", ()) or ()),
            "tasks": tasks, "notes": " ".join((t.notes or "").split())[:300],
        })
    return cards


def _short(x: float) -> Any:
    if x is None:
        return None
    if abs(x) >= 100 or float(x).is_integer():
        return int(round(x))
    return round(float(x), 2)


# ── when to ask ──────────────────────────────────────────────────────────────────────────────────────────────────────
_GOALISH = re.compile(
    r"\?|\bли\b|покаж|показа|сравн|сопостав|расскаж|опиш|оцен|проанализ|разбер|выясн|найд|найти|понять|поним|хоти?м|"
    r"нужн|надо|важн|главн|интерес|вопрос|задач|цел[ьи]\b|как\w*\b|кто\b|где\b|когда\b|сколько|почему|динамик|структур|"
    r"дол[яиюе]\b|рост|сниж|паден|тренд|распредел|связ|зависи|рейтинг|лидер|сумм|средн|больше|меньше|выше|ниже|"
    r"лучше|хуже|быстрее|дольше|дороже|дешевле", re.I)


def looks_like_goal(brief: str, regex_goals: Optional[Sequence[Goal]] = None) -> bool:
    """The brief asks something: a question, a request, a goal word. Without any — no model call."""
    if not (brief or "").strip():
        return False
    if regex_goals:
        return True
    return _GOALISH.search(brief) is not None


# ── cache: brief hash + table hashes + the skill's hash → the model's answer ─────────────────────────────────────────
_CACHE: "OrderedDict[str, tuple[dict, Optional[str]]]" = OrderedDict()
_LOCK = threading.Lock()


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _table_sha(t: Table) -> str:
    body = json.dumps({"file": t.file, "sheet": t.sheet, "columns": list(t.columns),
                       "rows": [[None if c is None else str(c) for c in r] for r in t.rows]}, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _cache_key(brief: str, tables: Sequence[Table], skill_sha: str = "", who: str = "") -> str:
    """The brief (spaces aside), the tables as read, the skill's prompts and the model that answers (one registry per
    process: the interface's «Цели из текста» and the generation share the answer; another model asks anew)."""
    h = hashlib.sha256()
    h.update(" ".join((brief or "").split()).encode("utf-8"))
    for t in tables:
        h.update(b"|")
        h.update(_table_sha(t).encode())
    h.update(b"|" + (skill_sha or "").encode() + b"|" + who.encode())
    return h.hexdigest()


def _who(providers: Any) -> str:
    try:
        llm = providers.get("llm")
    except Exception:  # noqa: BLE001
        return ""
    return f"{type(llm).__name__}:{getattr(llm, 'model', '')}:{id(llm)}"


# ── the spans ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _norm_map(text: str) -> tuple[str, list[int]]:
    """The text lowered, «ё» → «е», quotes dropped and spaces collapsed, with each character's place in the original."""
    out, where = [], []
    prev_space = True
    for i, ch in enumerate(text or ""):
        c = ch.lower().replace("ё", "е")
        if c in "«»\"'“”„":
            continue
        if c.isspace() or c == " ":
            if prev_space:
                continue
            c, prev_space = " ", True
        else:
            prev_space = False
        out.append(c)
        where.append(i)
    return "".join(out), where


def _find_span(brief: str, span: str) -> Optional[tuple[int, int]]:
    """(start, end) of the model's quote in the brief: exact, then by normalized text, then the one sentence that holds
    nearly all of its words (the model shortened or reworded a little)."""
    span = (span or "").strip()
    if not span:
        return None
    i = brief.find(span)
    if i >= 0:
        return i, i + len(span)
    nb, wb = _norm_map(brief)
    ns, _ = _norm_map(span)
    ns = ns.strip(" .,;:!?—–-")
    if len(ns) >= 4:
        j = nb.find(ns)
        if j >= 0:
            return wb[j], wb[j + len(ns) - 1] + 1
    words = [w for w in stems_of(span) if len(w) >= 3]
    if len(words) < 2:
        return None
    best = None
    for m in re.finditer(r"[^.!?…\n]+[.!?…]?", brief):
        sw = stems_of(m.group(0))
        hit = sum(1 for w in words if any(w == x or (len(w) >= 4 and (x.startswith(w) or w.startswith(x))) for x in sw))
        if hit >= max(2, round(0.8 * len(words))) and (best is None or hit > best[0]):
            s = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
            best = (hit, s, m.end())
    return (best[1], best[2]) if best else None


def _quote(brief: str, a: int, b: int) -> str:
    return " ".join(brief[a:b].split()).strip(" ,;:—–-")


def _phrase(q: str) -> str:
    """The goal's phrase as the rules write it: lower first letter, one line, without the question mark."""
    q = " ".join((q or "").split()).strip(" -—–").rstrip(" ?!.…")
    return q[:1].lower() + q[1:] if q else q


# ── units ────────────────────────────────────────────────────────────────────────────────────────────────────────────
_UNITS = [
    ("%", r"^(?:%|процент\w*|проц\.?|п\.?\s*п\.?)$"),
    ("day", r"^(?:дн\.?|дн(?:ей|я|и)|день|сут\w*)$"),
    ("hour", r"^(?:ч\.?|час\w*)$"),
    ("min", r"^(?:мин\.?|минут\w*)$"),
    ("ppm", r"^ppm$"),
    ("rub", r"^(?:₽|руб\.?|рубл\w*|тыс\.?\s*₽|млн\.?\s*₽|млрд\.?\s*₽|тыс\.?\s*руб\.?|млн\.?\s*руб\.?)$"),
    ("pts", r"^(?:балл\w*|очк\w*|пункт\w*|п\.)$"),
    ("pcs", r"^(?:шт\.?|штук\w*)$"),
    ("ppl", r"^(?:чел\.?|человек\w*)$"),
]


def _unit_kind(u: Optional[str]) -> Optional[str]:
    s = _norm(u)
    if not s:
        return None
    for kind, rx in _UNITS:
        if re.match(rx, s, re.I):
            return kind
    return s


# ── the checks ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _validate(reading: GoalReading, brief: str, ctx: _Ctx) -> tuple[list[UnderstoodGoal], list[IntentNote], list[dict]]:
    """The model's answer → goals and notes that hold; what does not hold is dropped with its reason."""
    goals: list[UnderstoodGoal] = []
    notes: list[IntentNote] = []
    refused: list[dict] = []
    for mg in reading.goals:
        span = _find_span(brief, mg.span)
        if span is None:
            refused.append({"quote": mg.span, "why": "цитаты нет в тексте брифа"})
            continue
        k = ctx.index(mg.dataset)
        if k is None and len(ctx) == 1:
            k = 0
        if k is None:
            refused.append({"quote": mg.span, "why": f"нет датасета «{mg.dataset}»"})
            continue
        span = _with_categories(brief, span, mg.categories)
        quote = _quote(brief, *span)
        u, why = _check_goal(mg, quote, span[0], k, ctx)
        if u is None:
            # the task cannot be done on this dataset: the goal is not lost — its reason is the visible note
            notes.append(IntentNote(quote=quote, reason=why or "данные не отвечают на этот вопрос", at=span[0],
                                    dataset=ctx.ids[k], file=ctx.profiles[k].file))
            refused.append({"quote": quote, "why": why})
            continue
        if not any(_same(u, x) for x in goals):
            goals.append(u)
    for mm in reading.unanswerable:
        span = _find_span(brief, mm.span)
        if span is None:
            refused.append({"quote": mm.span, "why": "цитаты нет в тексте брифа"})
            continue
        quote = _quote(brief, *span)
        reason = _clean_reason(mm.reason, brief, ctx)
        weak = not reason
        if not reason:
            refused.append({"quote": quote, "why": "причина пустая или с числами, которых нет ни в брифе, ни в данных"})
            reason = "в данных нет того, о чём это предложение"
        k = ctx.index(mm.dataset) if mm.dataset else (0 if len(ctx) == 1 else None)
        if any(g.at <= span[0] < g.at + len(g.quote) or span[0] <= g.at < span[1] for g in goals):
            continue  # the same words already hold a goal: the goal wins
        notes.append(IntentNote(quote=quote, reason=reason, at=span[0], dataset=ctx.ids[k] if k is not None else None,
                                file=ctx.profiles[k].file if k is not None else None, weak=weak))
    goals.sort(key=lambda g: g.at)
    notes.sort(key=lambda n: n.at)
    return goals, notes, refused


def _with_categories(brief: str, span: tuple[int, int], cats: Sequence[str]) -> tuple[int, int]:
    """A goal whose category the brief names outside its quote («стоит ли закрывать тариф «Базовый» — правда ли он
    теряет абонентов»): its words are the whole sentence — the plan finds the category it is about by them."""
    inside = _norm(brief[span[0]:span[1]])
    if not cats or all(_norm(c) in inside for c in cats):
        return span
    for m in re.finditer(r"[^.!?…\n]+[.!?…]?", brief):
        a = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
        if a <= span[0] and span[1] <= m.end() and any(_norm(c) in _norm(m.group(0)) for c in cats):
            return a, m.end()
    return span


def _same(a: UnderstoodGoal, b: UnderstoodGoal) -> bool:
    return (a.dataset, a.task, a.metric, a.ask, a.at) == (b.dataset, b.task, b.metric, b.ask, b.at)


_PERIOD_WORD_RE = re.compile(
    r"\b(?:19|20)\d{2}\b|январ|феврал|март|апрел|\bма[йяе]\b|июн|июл|август|сентябр|октябр|ноябр|декабр|квартал|\bкв\.|"
    r"полугоди|месяц|недел|\bгод|\bлет\b|сезон|\bлет[аоеу]\b|зим|весн|осен|с\s+начала|последн|прошл|текущ|этот\s+год|"
    r"\b[IV]{1,3}\s*кв|\bQ[1-4]\b|\bH[12]\b|\b\d{1,2}\s*(?:мес|нед|дн)", re.I)


def _check_goal(mg: ModelGoal, quote: str, at: int, k: int, ctx: _Ctx) -> tuple[Optional[UnderstoodGoal], Optional[str]]:
    """One goal of the model against dataset `k`: (the goal that holds, None) or (None, why it cannot be done)."""
    dropped: list[str] = []
    d, p = ctx.datas[k], ctx.profiles[k]
    scores = ctx.scores[k]
    task = (mg.task or "").strip().lower()
    if task not in TASKS:
        return None, f"задача «{mg.task}» неизвестна"
    # the measure: a numeric column of this dataset
    metric = ctx.column(k, mg.metric)
    if mg.metric and metric is None:
        dropped.append(f"колонки «{mg.metric}» в «{p.file}» нет")
    elif metric is not None and not ctx.is_measure(k, metric):
        dropped.append(f"«{metric}» — не числа, величиной быть не может")
        metric = None
    dimension = ctx.column(k, mg.dimension)
    if mg.dimension and dimension is None:
        dropped.append(f"колонки-разреза «{mg.dimension}» нет")
    elif dimension is not None and ctx.role(k, dimension) not in ("dimension", "time", "text", "id"):
        dropped.append(f"«{dimension}» — не разрез (это числа)")
        dimension = None
    cats: list[str] = []
    if mg.categories:
        vals = ctx.values(k)
        for c in mg.categories:
            v = vals.get(_norm(c))
            if v is None:
                v = next((x for n, x in vals.items() if _norm(c) and (_norm(c) in n.split() or n.startswith(_norm(c)))), None)
            if v is None:
                dropped.append(f"категории «{c}» в данных нет")
            elif v not in cats:
                cats.append(v)
    # the task: feasible on this dataset, or the nearest one that is
    ask = (mg.ask or "").strip().lower() or None
    if ask in ("none", "null", "trend"):
        ask = None
    thresholdish = ask in ("above", "below")
    if scores.get(task, 0.0) < FEASIBLE:
        alt = _REMAP.get(task)
        if task == "comparison" and ctx.has_time(k):
            alt = "dynamics"  # periods of one series against each other («ноябрь против октября»)
        elif task == "dynamics" and (any(re.search(r"(?:19|20)\d\d", c.name) for c in p.columns if c.role == "metric")
                                     or (mg.period is not None and (mg.period.kind or "") == "compare")
                                     or mg.compare_to is not None):
            alt = "comparison"  # years as columns («2024 Штат · 2025 Штат»): the change between the columns
        if alt and scores.get(alt, 0.0) >= FEASIBLE:
            dropped.append(f"«{TASK_TITLES.get(task, task).lower()}» по этим данным не строится — "
                           f"{TASK_TITLES.get(alt, alt).lower()}")
            task = alt
        elif thresholdish:
            best = max(scores, key=lambda x: scores[x])
            if scores[best] < FEASIBLE:
                return None, _why_not(task, d)
            task = best  # «какие серверы выше 80%»: порог отвечает и тогда, когда сравнивать нечем (plan.py, th_goal)
        else:
            return None, _why_not(task, d)
    mm = ctx.measure(k, metric) if metric else None
    if task == "shares" and mm is not None and not (mm.additive or mm.stock) and scores.get("comparison", 0.0) >= FEASIBLE:
        # «покажите долю электронных выдач по филиалам» — колонка уже доля каждой строки: её не складывают в целое, а
        # сравнивают по строкам (F14: иначе план показал бы свою колонку)
        dropped.append(f"«{metric}» — не части целого: доли сравнены по строкам")
        task = "comparison"
    # what is asked
    threshold = mg.threshold
    if ask is not None and ask not in ASKS:
        dropped.append(f"вопрос «{ask}» неизвестен")
        ask = None
    versus = None
    if thresholdish and threshold is None:
        # «где платных заявлений меньше, чем платных мест» — порог не число, а другая колонка (F2): сравнение по строкам
        versus = _versus_column(mg, quote, k, ctx, metric)
        if versus is None and len(cats) >= 2:
            ask, thresholdish = None, False  # «правда ли, что на «Ледокол-2» продано больше, чем на «Северный ветер»» — строки
        elif versus is None:
            return None, f"{UNMET}: «{'меньше' if ask == 'below' else 'больше'}, чем …» — с чем сравнивать, в данных не нашлось"
    if versus is not None:
        ask = "versus_lt" if ask == "below" else "versus_gt"
        thresholdish = False
    if thresholdish:
        if threshold is None:
            dropped.append("порог без числа")
            ask = None
        else:
            col_unit = (ctx.measure(k, metric).unit if ctx.measure(k, metric) is not None else None) if metric else None
            if metric and ctx.measure(k, metric) is not None and ctx.measure(k, metric).type == "percent" and not col_unit:
                col_unit = "%"
            tu, cu = _unit_kind(threshold.unit), _unit_kind(col_unit)
            if tu and cu and tu != cu:
                dropped.append(f"порог в «{threshold.unit}», а «{metric}» — в «{col_unit}»")
                ask, threshold = None, None
            else:
                ask = f"{ask}:{_num(threshold.value)}"
    elif threshold is not None and ask is None:
        threshold = None
    pc = _period_columns_named(quote, k, ctx)
    if pc is not None and re.search(r"(?i)просел|просад|упал|паден|снизил|сниж|сократ|уменьш|меньше|вырос|рост|увелич|больше",
                                    quote or ""):
        # «сравни июль и сентябрь по маршрутам — где просело»: два периода-колонки одной таблицы — по строкам (F2)
        later, earlier = pc
        down = bool(re.search(r"(?i)просел|просад|упал|паден|снизил|сниж|сократ|уменьш|меньше", quote or ""))
        metric, versus, task = later, earlier, "comparison"
        ask = "versus_lt" if down else "versus_gt"
        thresholdish = False
        period = None
        mg = mg.model_copy(update={"period": None})
    if ask == "compare_columns":
        versus = _versus_column(mg, quote, k, ctx, metric)
        if versus is None and len(cats) >= 2:
            ask = None  # две названные строки, а не две колонки: сравнение категорий (их значения — на обложке)
        elif versus is None:
            return None, f"{UNMET}: сравнение двух колонок — вторая колонка в данных не нашлась"
        else:
            ask = "versus_lt" if re.search(r"(?i)меньше|ниже|не\s+хватает", quote) else "versus_gt"
    if ask == "product":
        return None, f"{UNMET}: ожидаемое значение (сумма × вероятность) колода не считает — на слайде сумма без учёта вероятности"
    n_top = mg.n
    if ask != "top_n" and (mg.task or "").lower() in ("shares", "comparison") and not mg.categories:
        n_top = _top_n_of(quote)  # «какую долю перевозят пять крупнейших маршрутов вместе»
        if n_top:
            ask = "top_n"
    if ask == "top_n":
        n_top = n_top or _top_n_of(quote)
        if not n_top or n_top < 1:
            return None, f"{UNMET}: сколько крупнейших — не названо числом"
        mg = mg.model_copy(update={"n": n_top})
    if ask == "share":
        ask = "share_of" if mg.categories else None
    if ask == "meet" and task == "comparison" and metric:
        # «какие станции выполнили план, а какие нет»: факт и план — две колонки одной единицы, по строкам; колонка
        # «Выполнение, %» — своя логика плана (цель 100%)
        plan_col = _plan_column(mg, k, ctx, metric)
        if plan_col is not None:
            ask, versus = "met", plan_col
    if ask in ("min", "max") and task == "dynamics" and not mg.categories and not (mg.period and (mg.period.kind or "") == "compare"):
        ask = "period_min" if ask == "min" else "period_max"  # «в каком месяце загрузка сети была самой низкой»
    if task == "comparison" and mg.yes_no and len(mg.categories) == 1 and ask in (None, "max", "min", "mean"):
        ask = "position"  # «правда ли, что «Ночная» хуже остальных»: где она среди всех
    if len(cats) == 2 and task == "comparison" and ask in (None, "total", "mean") and _own_rows(ctx, k, cats) and \
            re.search(r"(?i)конверси|из\s+тех|из\s+них|дош[её]?л|доход|доля|сколько\s+(?:из|процент)", quote or ""):
        ask = "row_ratio"  # «конверсия от отклика до оффера», «сколько дошли до выхода из откликнувшихся»: строка от строки
    elif cats and _own_rows(ctx, k, cats):
        pass  # названные строки — сами категории («СБП» среди способов оплаты): доля — обычный вывод слайда
    elif mg.categories and ask in (None, "total") and ((mg.task or "").lower() == "shares"
                                                    or re.search(r"(?i)(?<![а-яё])дол[яюие]\w*", quote or "")):
        ask = "share_of"  # «какая доля выработки приходится на астраханские станции»
    if ask in ("fastest",) and not ctx.has_time(k):
        dropped.append("«быстрее всех» — без оси времени не посчитать")
        ask = None
    if ask == "spike" and task != "dynamics":
        ask = None
    # aggregation
    agg = (mg.aggregation or "").strip().lower() or None
    weight = ctx.column(k, mg.weight) if mg.weight else None
    m = ctx.measure(k, metric)
    if agg == "ratio":
        # модель назвала отношение агрегацией: числитель — величина, знаменатель — вес (ниже это `ratio`)
        agg = "weighted_mean" if mg.weight else None
    if agg is not None and agg not in AGGS:
        dropped.append(f"агрегация «{agg}» неизвестна")
        agg = None
    if agg == "sum" and m is not None and not m.additive:
        dropped.append(f"сумма «{metric}» не имеет смысла — это не слагаемое (доля, среднее или уровень)")
        agg = None
    ratio = None
    rq = mg.ratio
    if rq is None and re.search(r"(?i)\bконкурс", quote or ""):
        rq = _contest(k, ctx, metric)  # «самый большой конкурс на бюджет» — заявлений на одно место
    wm = ctx.measure(k, weight) if weight else None
    if agg == "weighted_mean" and m is not None and m.additive and wm is not None:
        # «выручка на посетителя», «зрителей за сеанс» понятые как среднее с весом: у суммы средних с весом нет — это
        # отношение колонок; вес-доля («с учётом вероятности») — произведение, его колода не считает (F2)
        if wm.type == "percent" or (wm.unit or "") == "%" or re.search(r"(?i)вероятн|доля|процент", weight or ""):
            return None, f"{UNMET}: ожидаемое значение («{metric}» × «{weight}») колода не считает — на слайде сумма без учёта вероятности"
        rq = ModelRatio(num=metric, den=weight)
    if rq is not None and rq.num and rq.den:
        num, den = ctx.column(k, rq.num), ctx.column(k, rq.den)
        spec = None
        if num and den and ctx.is_measure(k, num) and ctx.is_measure(k, den):
            from verstka.data.derive import ratio_spec

            spec = ratio_spec(ctx.tables[k], num, den, quote)
        if spec is None:
            return None, f"{UNMET}: «{rq.num}» на «{rq.den}» — таких колонок с числами в данных нет"
        ctx.derive(k, spec)
        ratio = spec
        metric, weight, agg = spec["name"], spec["den"], "weighted_mean"
        m = ctx.measure(k, metric)
        if task not in ("comparison", "dynamics"):
            task = "comparison"
    if agg == "weighted_mean":
        if weight is not None and not ctx.is_measure(k, weight):
            dropped.append(f"вес «{weight}» — не числа")
            weight = None
        if mg.weight and weight is None and not any("вес" in x for x in dropped):
            dropped.append(f"колонки-веса «{mg.weight}» нет")
        if weight is None and m is not None and d.weight_of(m) is not None:
            weight = d.weight_of(m).name
        if weight is None:
            dropped.append("взвешивать не по чему — простое среднее")
            agg = "mean"
    elif weight is not None:
        weight = None
    if agg == "latest" and not ctx.has_time(k):
        dropped.append("«последний период» — в данных нет периодов")
        agg = None
    if agg == "total_row" and not (d.totals or p.total_column or getattr(d, "benchmarks", None)):
        dropped.append("строки или колонки итога в данных нет")
        agg = None
    # the period
    period = mg.period
    if (period is None or (period.kind or "all") == "all") and ctx.has_time(k):
        period = _season_of(quote, ctx.periods(k)) or period  # «сократилось ли ожидание за лето» — июнь–август
    if period is not None and (period.kind or "all").strip().lower() != "all" and not _PERIOD_WORD_RE.search(quote or ""):
        # the goal's own words name no period («покажи рост выручки»): the period the model took from elsewhere in the
        # brief («за 9 месяцев 2026 года» in its title) is not this goal's — the same data on every run, with or without
        # the model (qa5: 9 points on one template, 21 on another when the model's call ran out of time)
        dropped.append("период не назван в цели — данные целиком")
        period = None
    if period is not None:
        kind = (period.kind or "all").strip().lower()
        if kind not in PERIODS:
            dropped.append(f"период «{period.kind}» неизвестен")
            period = None
        elif kind != "all" and not ctx.has_time(k):
            dropped.append("в данных нет периодов — период не выбрать")
            period = None
        else:
            ends = [period.start, period.end, period.base, period.target, period.base_end, period.target_end]
            bad = [v for v in ends if v and not ctx.known_period(k, v)]
            if bad:
                dropped.append(f"периодов {', '.join('«' + b + '»' for b in bad)} в данных нет — границы сняты")
                period = ModelPeriod(kind=kind)
            else:
                period = period.model_copy(update={"kind": kind})
                if kind == "range" and ctx.whole(k, period):
                    period = None  # «с начала года», «за квартал» — the range is all the data has
            if period is not None and period.kind == "all":
                period = None
            if period is not None and period.kind == "compare" and not (period.base_end or period.target_end):
                period = _ranges_of(period, quote, ctx.periods(k))
    direction = (mg.direction or "").strip().lower() or None
    if direction not in (None, "higher", "lower"):
        direction = None
    target = mg.compare_to
    if target is not None:
        tk = (target.kind or "").strip().lower()
        if tk not in TARGETS:
            target = None
        elif tk == "column":
            name = ctx.column(k, target.name)
            target = ModelCompare(kind=tk, name=name) if name else None
        elif tk == "category":
            v = ctx.values(k).get(_norm(target.name))
            target = ModelCompare(kind=tk, name=v) if v else None
        else:
            target = ModelCompare(kind=tk, name=None)
    u = UnderstoodGoal(
        quote=quote, at=at, dataset=ctx.ids[k], file=p.file, sheet=p.sheet, task=task, metric=metric,
        dimension=dimension, categories=cats, ask=ask, aggregation=agg, weight=weight, period=period,
        direction=direction, threshold=threshold if ask and ask.startswith(("above:", "below:")) else None,
        compare_to=target, yes_no=bool(mg.yes_no), confidence=max(0.0, min(1.0, float(mg.confidence or 0.0))),
        source="model", dropped=dropped, ratio=ratio, n=mg.n if ask == "top_n" else None, versus=versus)
    u.label = label_of(u)
    return u, None


_NUM_WORDS = {"два": 2, "двух": 2, "три": 3, "трёх": 3, "трех": 3, "четыре": 4, "четырёх": 4, "четырех": 4, "пять": 5,
              "пяти": 5, "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9,
              "десять": 10, "десяти": 10}


def _top_n_of(quote: str) -> Optional[int]:
    """«пять крупнейших маршрутов», «топ-3», «три самых больших» → число; None — не о первых N."""
    q = (quote or "").lower().replace("ё", "е")
    m = re.search(r"(?:топ[-\s]?(\d+))|(\d+|" + "|".join(_NUM_WORDS) + r")\s+(?:крупнейш|самы[хе]\s+(?:больш|крупн)|первы[хе]|"
                  r"лидирующ|ведущ)", q)
    if not m:
        return None
    tok = m.group(1) or m.group(2)
    return int(tok) if tok.isdigit() else _NUM_WORDS.get(tok)


def _contest(k: int, ctx: _Ctx, metric: Optional[str]) -> Optional["ModelRatio"]:
    """«Конкурс» — заявлений на одно место: колонка заявлений (та, что назвала цель, если она о заявлениях) на колонку
    мест той же группы («Бюджет Заявлений» / «Бюджет Мест»)."""
    names = [c.name for c in ctx.profiles[k].columns if ctx.is_measure(k, c.name)]
    apps = [n for n in names if re.search(r"(?i)заявлен|заявок|заявк", n)]
    if not apps:
        return None
    num = metric if metric in apps else apps[0]
    grp = re.sub(r"(?i)\s*заявлен\w*|\s*заявок|\s*заявк\w*", "", num).strip().lower()
    seats = [n for n in names if re.search(r"(?i)мест", n)]
    den = next((n for n in seats if grp and grp in n.lower()), seats[0] if seats else None)
    return ModelRatio(num=num, den=den) if den else None


_SEASONS = {"лет": (6, 8), "зим": (12, 2), "весн": (3, 5), "осен": (9, 11)}


def _season_of(quote: str, periods: Sequence[str]) -> Optional[ModelPeriod]:
    """«За лето», «летом», «этой зимой» → диапазон месяцев сезона в году данных (F5); None — сезона в брифе нет или
    данные не по месяцам/дням."""
    m = re.search(r"(?i)(?:за|в\s+течение|этим|этой|прошл\w+)?\s*(лет(?:о|ом|а)|зим(?:а|ой|у)|весн(?:а|ой|у)|осен(?:ь|ью))\b",
                  quote or "")
    if not m:
        return None
    key = m.group(1).lower()[:4].rstrip("оаьую")
    key = next((k for k in _SEASONS if key.startswith(k)), None)
    import datetime as _dt

    isos = []
    for p in periods:
        p = str(p)
        w = re.fullmatch(r"(\d{4})-W(\d{1,2})", p)
        if w:  # неделя ISO — месяц её понедельника
            try:
                p = _dt.date.fromisocalendar(int(w.group(1)), int(w.group(2)), 1).isoformat()
            except ValueError:
                continue
        if re.match(r"^\d{4}-\d{2}", p):
            isos.append(p)
    isos.sort()
    if key is None or not isos:
        return None
    a, b = _SEASONS[key]
    year = isos[-1][:4]
    if a > b:  # зима — декабрь прошлого года по февраль
        start, end = f"{int(year) - 1:04d}-{a:02d}", f"{year}-{b:02d}"
    else:
        start, end = f"{year}-{a:02d}", f"{year}-{b:02d}"
    if not any(start <= p[:7] <= end for p in isos):
        return None
    return ModelPeriod(kind="range", start=start, end=end)


def _ranges_of(period: ModelPeriod, quote: str, periods: Sequence[str]) -> ModelPeriod:
    """Сравнение диапазонов, названных словами брифа, когда модель дала только их начала (F5): «во втором полугодии,
    чем в первом» — шесть месяцев от каждого начала, «… квартале» — три, «июль с августом–сентябрём» — B до последнего
    названного месяца."""
    q = (quote or "").lower().replace("ё", "е")
    b, t = period.base or "", period.target or ""
    if not (re.fullmatch(r"\d{4}-\d{2}", b) and re.fullmatch(r"\d{4}-\d{2}", t)):
        return period
    months = 6 if re.search(r"полугоди", q) else 3 if re.search(r"квартал", q) else 0

    def plus(iso: str, n: int) -> str:
        y, m = int(iso[:4]), int(iso[5:7]) - 1 + n
        return f"{y + m // 12:04d}-{m % 12 + 1:02d}"

    if months:
        return period.model_copy(update={"base_end": plus(b, months - 1), "target_end": plus(t, months - 1)})
    rng = re.search(r"(январ|феврал|март|апрел|ма[йяе]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*\s*[–—-]\s*"
                    r"(январ|феврал|март|апрел|ма[йяе]|июн|июл|август|сентябр|октябр|ноябр|декабр)", q)
    if rng:
        names = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"]
        end = next((i + 1 for i, x in enumerate(names) if rng.group(2).startswith(x)), None)
        if end is not None:
            te = f"{t[:4]}-{end:02d}"
            if te > t and any(str(p).startswith(te) for p in periods):
                return period.model_copy(update={"target_end": te, "base_end": b})
    return period


def _period_columns_named(quote: str, k: int, ctx: _Ctx) -> Optional[tuple[str, str]]:
    """(позднее, раннее): две колонки-периода таблицы («Июль», «Сентябрь»), которые называет бриф; None — нет."""
    from verstka.data.parse import season_name

    q = (quote or "").lower().replace("ё", "е")
    cols = [c.name for c in ctx.profiles[k].columns if ctx.is_measure(k, c.name)
            and (season_name(c.name) or re.fullmatch(r"(?:19|20)\d\d", c.name.strip()))]
    hit = []
    for c in cols:
        w = stem(c.lower().replace("ё", "е"))
        if len(w) >= 3 and re.search(r"(?<![а-яё0-9])" + re.escape(w[:max(3, len(w) - 1)]), q):
            hit.append(c)
    if len(hit) != 2:
        return None
    a, b = hit
    order = [c.name for c in ctx.profiles[k].columns]
    return (b, a) if order.index(b) > order.index(a) else (a, b)


def _own_rows(ctx: _Ctx, k: int, cats: Sequence[str]) -> bool:
    """Названные категории — значения главной колонки категорий (строки сравнения), а не группа строк другой колонки
    («Астраханская область» у станций)."""
    d = ctx.datas[k]
    try:
        j = d.cat_dim()
    except Exception:  # noqa: BLE001
        j = None
    if j is None:
        j = d.label
    if j is None:
        return False
    vals = {d.text(i, j).strip().lower() for i in d.rows_idx}
    return all(c.strip().lower() in vals for c in cats)


def _plan_column(mg: ModelGoal, k: int, ctx: _Ctx, metric: str) -> Optional[str]:
    """Колонка плана той же единицы, что факт («План янв–сен 2026, МВт·ч» к «Выработка янв–сен 2026, МВт·ч»); None —
    факт в процентах плана или плана нет."""
    m = ctx.measure(k, metric)
    if m is None or m.type == "percent" or (m.unit or "") == "%":
        return None
    names = []
    t = mg.compare_to
    if t is not None and t.name:
        names.append(ctx.column(k, t.name))
    names += [c.name for c in ctx.profiles[k].columns if re.search(r"(?i)план|норматив|цел[ьи]", c.name)]
    for n in names:
        if not n or n == metric or not ctx.is_measure(k, n):
            continue
        b = ctx.measure(k, n)
        if b is not None and (b.unit or "") == (m.unit or "") and b.type != "percent":
            return n
    return None


def _versus_column(mg: ModelGoal, quote: str, k: int, ctx: _Ctx, metric: Optional[str]) -> Optional[str]:
    """Вторая колонка сравнения по строкам: названная моделью (`compare_to` колонка) или словами брифа после «чем»
    («меньше, чем платных мест» → «Платное Мест», «больше, чем ушедших» → «Ушли за квартал»)."""
    t = mg.compare_to
    if t is not None and (t.kind or "").lower() == "column" and t.name:
        c = ctx.column(k, t.name)
        if c and c != metric and ctx.is_measure(k, c):
            return c
    m = re.search(r"(?i)\bчем\s+(?:у\s+|на\s+|в\s+)?([а-яё\s-]{3,40})", quote or "")
    if not m:
        return None
    words = [w for w in re.findall(r"[а-яё]{3,}", m.group(1).lower()) if w not in ("было", "были", "стало", "есть")][:3]
    best, score = None, 0
    for c in ctx.profiles[k].columns:
        if c.name == metric or not ctx.is_measure(k, c.name):
            continue
        cs = [stem(x) for x in stems_of(c.name)]
        hit = sum(1 for w in words if any(stem(w)[:4] == x[:4] or stem(w)[:3] == x[:3] and len(x) >= 3 for x in cs))
        if hit > score:
            best, score = c.name, hit
    return best


def _iso_le(a: str, b: str) -> bool:
    """ISO periods of any grain in order, on their common prefix: «2025-10» ≤ «2025-11-01», «2023» ≤ «2023-Q1»."""
    n = min(len(a), len(b))
    return a[:n] <= b[:n]


def _whole(period: ModelPeriod, periods: Sequence[str]) -> bool:
    """A range that holds every period of the data (or names no bounds)."""
    a, b = _norm(period.start), _norm(period.end)
    if not a and not b:
        return True
    ps = sorted(_norm(x) for x in periods if x and re.match(r"^\d{4}", _norm(x)))
    if not ps:
        return False
    return (not a or _iso_le(a, ps[0])) and (not b or _iso_le(ps[-1], b))


def _why_not(task: str, d: Data) -> str:
    from verstka.data.task import _infeasible_reason

    try:
        return _infeasible_reason(task, d)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return "данные для этой задачи не подходят"


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _clean_reason(reason: str, brief: str, ctx: _Ctx) -> str:
    """The model's reason as a note: one line, lower first letter, no period; a number in it must be the brief's or
    the data's (a column name, a value) — the model never adds a number."""
    r = " ".join((reason or "").split()).strip().rstrip(".")
    if not r:
        return ""
    r = r[:1].lower() + r[1:]
    allowed = brief + " " + " ".join(c.name + " " + (c.unit or "") for p in ctx.profiles for c in p.columns)
    allowed += " " + " ".join(p.file for p in ctx.profiles)
    for n in re.findall(r"\d+(?:[.,]\d+)?", r):
        if n not in allowed:
            return ""
    return r[:200]


# ── labels for the person ────────────────────────────────────────────────────────────────────────────────────────────
_ASK_WORDS = {"max": "кто больше всего", "min": "кто меньше всего", "total": "итог", "mean": "среднее по всем",
              "fastest": "кто растёт быстрее", "margin": "отрыв лидера", "spike": "был ли всплеск",
              "meet": "выполнен ли план или цель", "met": "кто выполнил план, кто нет",
              "top_n": "доля крупнейших", "share_of": "доля названных категорий", "versus_lt": "меньше другой колонки",
              "versus_gt": "больше другой колонки", "period_min": "самый низкий период", "period_max": "самый высокий период"}
_AGG_WORDS = {"sum": "сумма", "mean": "среднее", "weighted_mean": "средневзвешенное", "latest": "последний период",
              "total_row": "строка итога"}


def label_of(u: UnderstoodGoal) -> str:
    """«Сравнение категорий · «Срок рассмотрения» · кто больше всего · выше 15 дн.» — как цель понята."""
    parts = [TASK_TITLES.get(u.task, u.task)]  # type: ignore[arg-type]
    if u.metric:
        parts.append(f"«{u.metric}»" + (f" по «{u.dimension}»" if u.dimension else ""))
    elif u.dimension:
        parts.append(f"по «{u.dimension}»")
    if u.categories:
        parts.append(", ".join(f"«{c}»" for c in u.categories[:3]))
    if u.ask:
        if u.ask.startswith(("above:", "below:")):
            side, v = u.ask.split(":", 1)
            unit = f" {u.threshold.unit}" if u.threshold is not None and u.threshold.unit else ""
            parts.append(f"{'выше' if side == 'above' else 'ниже'} {v.replace('.', ',')}{unit}")
        else:
            parts.append(_ASK_WORDS.get(u.ask, u.ask))
    if u.aggregation and u.aggregation != "mean" or (u.aggregation == "mean" and u.ask != "mean"):
        w = _AGG_WORDS.get(u.aggregation or "", u.aggregation or "")
        if u.aggregation == "weighted_mean" and u.weight:
            w += f" по «{u.weight}»"
        if w:
            parts.append(w)
    if u.period is not None:
        pk = u.period.kind
        if pk == "latest":
            parts.append("последний период")
        elif pk == "range":
            parts.append(f"{u.period.start or '…'} — {u.period.end or '…'}")
        elif pk == "compare":
            a, b = u.period.base, u.period.target
            parts.append(f"{a} против {b}" if a and b else "сравнение периодов")
    if u.compare_to is not None:
        what = {"plan": "с планом", "target": "с целью", "previous_period": "с прошлым периодом"}.get(u.compare_to.kind)
        parts.append(what or f"с «{u.compare_to.name}»")
    return " · ".join(p for p in parts if p)


# ── the rules' goals in the same shape (no model; the cross-check) ───────────────────────────────────────────────────
def _span_of(g: Goal, brief: str) -> tuple[int, int]:
    """Where a goal of the rules stands in the brief (its phrase is lowered and one-lined)."""
    a = max(0, int(g.at))
    nb, wb = _norm_map(brief[a:])
    ph, _ = _norm_map(g.phrase)
    j = nb.find(ph.strip(" .,;:!?—–-"))
    if j >= 0 and ph:
        return a + wb[j], a + wb[min(len(wb) - 1, j + len(ph.strip(' .,;:!?—–-')) - 1)] + 1
    return a, a + len(g.phrase)


_NOT_UNDERSTOOD = "вопрос не распознан как задача"


def _rules_understood(brief: str, regex: Sequence[Goal], ctx: _Ctx) -> tuple[list[UnderstoodGoal], list[IntentNote]]:
    """The rules' goals as the plan will use them: the dataset `assign_goals` gives each, the column the plan shows for
    it, what is asked; goals that cannot be done and questions not understood — notes."""
    from verstka.data.plan import assign_goals, goal_data

    if not regex or not len(ctx):
        return [], []
    per = assign_goals(list(regex), ctx.datas)
    out: list[UnderstoodGoal] = []
    notes: list[IntentNote] = []
    seen_notes: set[str] = set()
    for k, gs in enumerate(per):
        for g in gs:
            a, _b = _span_of(g, brief)
            quote = _quote(brief, *_span_of(g, brief)) or g.phrase
            if g.unmet or g.free:
                why = g.unmet or _NOT_UNDERSTOOD
                if quote not in seen_notes:
                    seen_notes.add(quote)
                    notes.append(IntentNote(quote=quote, reason=why, at=a, dataset=ctx.ids[k],
                                            file=ctx.profiles[k].file, source="rules"))
                continue
            if ctx.scores[k].get(g.task, 0.0) < FEASIBLE:
                continue  # the plan notes it as «здесь не подходит»; another reading of the same phrase may hold
            gd = goal_data(ctx.tables[k], ctx.profiles[k], g.phrase, compare=g.task == "comparison")
            m = gd.main if g.task not in ("reference", "kpi") else None
            ask = g.ask if g.ask in ("meet", "spike") else (gd.ask or (g.ask if g.ask != "max" else None))
            agg = None
            if ask == "total":
                agg = "sum"
            elif ask == "mean":
                agg = "weighted_mean" if (m is not None and gd.weight_of(m) is not None) else "mean"
            u = UnderstoodGoal(quote=quote, at=a, dataset=ctx.ids[k], file=ctx.profiles[k].file,
                               sheet=ctx.profiles[k].sheet, task=g.task, metric=m.name if m is not None else None,
                               ask=ask, aggregation=agg,
                               weight=(gd.weight_of(m).name if agg == "weighted_mean" and m is not None else None),
                               source="rules", pinned=True if m is not None else None)
            u.label = label_of(u)
            out.append(u)
    for g in regex:
        if not any(g in gs for gs in per) and not g.free:
            quote = _quote(brief, *_span_of(g, brief)) or g.phrase
            if quote not in seen_notes:
                seen_notes.add(quote)
                notes.append(IntentNote(quote=quote, reason="ни в одном файле нет того, о чём она", at=g.at,
                                        source="rules"))
    out.sort(key=lambda u: u.at)
    return out, notes


def rules_goals(brief: str, tables: Sequence[Table], profiles: Optional[Sequence[DatasetProfile]] = None,
                dataset_ids: Optional[Sequence[str]] = None, *, skipped: Optional[str] = None,
                error: Optional[str] = None, _ctx: Optional[_Ctx] = None) -> GoalsRead:
    """The rules' understanding (no model): `goals=None` — the plan parses the brief itself, exactly as before."""
    t0 = time.monotonic()
    ctx = _ctx or _Ctx(tables, profiles, dataset_ids)
    regex = goals_of(brief or "")
    try:
        understood, notes = _rules_understood(brief or "", regex, ctx)
    except Exception as e:  # noqa: BLE001 - what the interface shows; the plan parses the brief either way
        log.warning("rules goals for the interface failed: %s", e)
        understood, notes = [], []
    return GoalsRead(source="rules", goals=None, understood=understood, notes=notes, skipped=skipped, error=error,
                     seconds=time.monotonic() - t0)


# ── the merge with the rules ─────────────────────────────────────────────────────────────────────────────────────────
def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


# what is left of a sentence outside a goal and is no goal of its own: a decision («и стоит ли его менять»), a purpose
# («, чтобы разобрать на планёрке»), an order of business («в первую очередь»)
_NOT_A_GOAL = re.compile(r"(?:\bи\s+)?\b(?:стоит|нужно|надо|следует|имеет\s+смысл)\s+ли\b[^.?!]*|\bчтобы\b[^.?!]*|"
                         r"\bв\s+первую\s+очередь\b", re.I)


def _covers(brief: str, spans: Sequence[tuple[int, int]], r: tuple[int, int]) -> bool:
    """The model's quotes (its goals and its notes) cover the rules' quote: together they hold all of it, and what they
    leave out asks nothing of its own (a decision, a purpose, punctuation)."""
    left = []
    pos = r[0]
    for a, b in sorted(spans):
        if b <= pos or a >= r[1]:
            continue
        if a > pos:
            left.append(brief[pos:a])
        pos = max(pos, b)
    if pos < r[1]:
        left.append(brief[pos:r[1]])
    rest = _NOT_A_GOAL.sub(" ", " ".join(left))
    return not re.search(r"[а-яёa-z]{3,}", rest, re.I) or _GOALISH.search(rest) is None


def _merge(brief: str, goals: list[UnderstoodGoal], notes: list[IntentNote], ctx: _Ctx,
           rules: list[UnderstoodGoal], rule_notes: list[IntentNote]) -> tuple[list[UnderstoodGoal], list[IntentNote], list[dict]]:
    """The model's goals with the rules' cross-check: a goal of the rules where the model said nothing stays; where both
    speak of the same words and disagree — the model's goal when its quotes cover the rules' one (all of it but a
    decision or a purpose that asks nothing: «…, чтобы разобрать на планёрке», «и стоит ли его менять»), otherwise the
    rules' goal. A note of the rules (a goal the data cannot answer, with its reason) stays where no goal or note of the
    model speaks of the same words; «вопрос не распознан» of the rules is no reason and does not."""
    kept_goals = list(goals)
    kept_notes = list(notes)
    log_: list[dict] = []
    spans = {id(u): (u.at, u.at + len(u.quote)) for u in kept_goals}
    nspans = [(n.at, n.at + len(n.quote)) for n in kept_notes]
    for r in rules:
        rs = (r.at, r.at + len(r.quote))
        over = [u for u in kept_goals if _overlap(spans[id(u)], rs)]
        weak = [n for n in kept_notes if n.weak and _overlap((n.at, n.at + len(n.quote)), rs)]
        if weak and not over:
            # модель сказала «нет в данных» без причины, а правила видят цель на тех же словах: цель правил (F14)
            for n in weak:
                kept_notes.remove(n)
                log_.append({"quote": n.quote, "why": "пометка модели без причины — цель правил на тех же словах"})
            nspans = [(n.at, n.at + len(n.quote)) for n in kept_notes]
        over_notes = [s for s in nspans if _overlap(s, rs)]
        if not over and not over_notes:
            kept_goals.append(r)
            spans[id(r)] = rs
            log_.append({"quote": r.quote, "why": "цель правил, модель о ней промолчала — сохранена"})
            continue
        if _covers(brief, [spans[id(u)] for u in over] + over_notes, rs):
            continue
        agree = [u for u in over if (u.dataset, u.task, u.metric) == (r.dataset, r.task, r.metric)]
        if agree:
            continue
        # the rules' quote is longer or not covered: the rules' goal, the model's disagreeing goals go
        for u in over:
            kept_goals.remove(u)
            log_.append({"quote": u.quote, "why": f"расходится с целью правил «{r.quote}», а её цитата длиннее"})
        kept_goals.append(r)
        spans[id(r)] = rs
    for n in rule_notes:
        ns = (n.at, n.at + len(n.quote))
        if n.reason == _NOT_UNDERSTOOD or any(_overlap(spans[id(u)], ns) for u in kept_goals) \
                or any(_overlap(s, ns) for s in nspans):
            continue
        kept_notes.append(n)
        nspans.append(ns)
        log_.append({"quote": n.quote, "why": "пометка правил, модель о ней промолчала — сохранена"})
    kept_goals.sort(key=lambda u: u.at)
    kept_notes.sort(key=lambda n: n.at)
    return kept_goals, kept_notes, log_


# ── to the plan ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _title_subject(ctx: _Ctx, k: int) -> list[str]:
    """Words of the dataset's title that name it among the generation's datasets (the goal lands in its dataset)."""
    own = goal_stems(file_title(ctx.profiles[k].file, ctx.profiles[k].sheet))
    if len(ctx) == 1:
        return own
    others = set()
    for j, p in enumerate(ctx.profiles):
        if j != k:
            others.update(goal_stems(file_title(p.file, p.sheet)))
    uniq = [s for s in own if s not in others]
    return uniq or own


def _pin(ctx: _Ctx, k: int, column: str, phrase: str, task: str, ask: Optional[str]) -> tuple[list[str], Optional[str], list[str], bool]:
    """(metric stems, head, negations, pinned): the words that make the plan show exactly `column` — checked on the
    plan's own `Data` (the same as `goal_data` builds for a given goal)."""
    low = column.lower().replace("ё", "е")
    words = [w for w in stems_of(column) if w not in ("без",)] or [stem(column.lower())]
    negate = [stem(w) for w in re.findall(r"\bбез\s+([а-яёa-z0-9]+)", low)]
    t, p = ctx.tables[k], ctx.profiles[k]
    subj = tuple(goal_stems(phrase))
    tried: list[Optional[str]] = list(dict.fromkeys(words))
    for h in tried:
        quals = tuple(x for x in words if x != h)
        try:
            d = Data(t, p, subject=subj, compare=task == "comparison", head=h, negate=tuple(negate), qualifiers=quals,
                     ask=ask)
            m = d.main
        except Exception:  # noqa: BLE001
            m = None
        if m is not None and m.name == column:
            return words, h, negate, True
    return words, (tried[0] if tried else None), negate, False


def _engine_ask(u: UnderstoodGoal, ctx: Optional[_Ctx] = None) -> Optional[str]:
    a = u.ask
    if a is None:
        return None
    if a == "mean" and u.aggregation == "weighted_mean" and ctx is not None and u.metric:
        k = ctx.ids.index(u.dataset)
        m = ctx.measure(k, u.metric)
        w = ctx.datas[k].weight_of(m) if m is not None else None
        if (w is None or w.name != u.weight) and not (u.weight and ctx.measure(k, u.weight) is not None):
            # без колонки-веса среднее строк было бы «в среднем» не о том («уровень брака по заводу»); вес из цели
            # план берёт сам (`Goal.weight`)
            u.dropped.append(f"среднее с весом по «{u.weight}»: такой колонки нет — общее среднее не показано")
            return None
    from verstka.data.asks import ASKS as _ANSWERED

    if a.startswith(("above:", "below:")) or a in _ENGINE_ASKS or a in ("max", "spike", "meet") or a in _ANSWERED:
        return a
    return None


def _to_goal(u: UnderstoodGoal, ctx: _Ctx) -> Goal:
    k = ctx.ids.index(u.dataset)
    phrase = _phrase(u.quote)
    task = u.task
    viz, to = GOAL_VIZ[task]  # type: ignore[index]
    subject = _title_subject(ctx, k)
    metric: list[str] = []
    head: Optional[str] = None
    negate: list[str] = []
    ask = _engine_ask(u, ctx)
    if u.metric and ctx.is_measure(k, u.metric) and ask != "meet":
        # (a plan met or not: the plan's own plan/fact and target logic picks the columns — «План»/«Факт», a norm)
        metric, head, negate, pinned = _pin(ctx, k, u.metric, phrase, task, ask if ask in _ENGINE_ASKS else None)
        u.pinned = pinned
        subject = list(dict.fromkeys(subject + [s for s in metric if s not in subject]))
    # всё, что понято, — плану явно (`Goal.given`): колонка, разрез, категории, вес, период; вопрос — как есть
    column = u.metric if u.metric and ctx.is_measure(k, u.metric) and ask != "meet" else None
    period = None
    if u.period is not None and u.period.kind in ("latest", "range", "compare"):
        period = GoalPeriod(**u.period.model_dump())
    return Goal(phrase=phrase, task=task, viz=viz, to=to, subject=subject, metric=metric, at=u.at, ask=ask, head=head,
                negate=negate, given=True, column=column, dimension=u.dimension, categories=list(u.categories),
                weight=u.weight if u.aggregation == "weighted_mean" else None, period=period, n=u.n, versus=u.versus,
                derive=u.ratio)


def _fit(g: Goal, u: UnderstoodGoal, ctx: _Ctx) -> Goal:
    """The goal as the plan will take it: it lands in its dataset (not as «здесь не подходит») and shows its column.
    The plan checks a goal's measure words against the columns' words without some of its own stop words («Выполнение»,
    «Ушло» are among them): then the measure words the plan cannot see are left out, or a word it sees that names no
    measure (the file's title, a category column) stands for them — checked here on the plan's own functions."""
    if not u.metric or not g.metric:
        return g
    try:
        from verstka.data import plan as P

        k = ctx.ids.index(u.dataset)
        t, p = ctx.tables[k], ctx.profiles[k]
        cols = [goal_stems(c.name) for c in p.columns]
        visible = [x for x in g.metric if any(x in cs for cs in cols)]
        # a word the plan sees (the title's, a category column's) that names no measure: it picks no other column
        measures = [goal_stems(m.name) for m in ctx.datas[k].measures]
        seen = goal_stems(file_title(p.file, p.sheet)) + [x for c, cs in zip(p.columns, cols) if c.role != "metric"
                                                          for x in cs] + [x for c in p.columns for x in goal_stems(c.unit or "")]
        neutral = [x for x in dict.fromkeys(seen) if len(x) >= 3 and not any(x in ms for ms in measures)]
        tries = [g]
        if visible and visible != g.metric:
            tries.append(g.model_copy(update={"metric": visible}))
        if neutral:
            tries.append(g.model_copy(update={"metric": visible + neutral[:1]}))
        for cand in tries:
            per = P.assign_goals([cand], ctx.datas)
            mine = [x for x in per[k] if x.phrase == cand.phrase]
            routed = bool(mine) and not mine[0].unmet and all(not any(x.phrase == cand.phrase for x in per[j])
                                                               for j in range(len(per)) if j != k)
            d = P.goal_data(t, p, cand.phrase, compare=cand.task == "comparison", goal=cand)
            shown = d.main is not None and d.main.name == u.metric
            if routed and (shown or cand.task in ("reference", "kpi")):
                u.pinned = True if shown else u.pinned
                return cand
        u.pinned = False
        u.dropped.append("план не берёт эту колонку по словам цели — покажет свою")
    except Exception as e:  # noqa: BLE001 - the goal as it is: the plan decides
        log.debug("goal fit failed: %s", e)
    return g


def _note_goal(n: IntentNote, ctx: _Ctx) -> Optional[Goal]:
    """A sentence the data cannot answer → a goal with its reason, routed to its dataset (its title's words): «Цель
    «…» здесь не подходит: …» in that dataset's «Почему так»."""
    if n.dataset is None or n.dataset not in ctx.ids:
        return None
    k = ctx.ids.index(n.dataset)
    sc = ctx.scores[k]
    task = max(sc, key=lambda x: sc[x])
    if sc[task] < FEASIBLE:
        return None
    viz, to = GOAL_VIZ[task]
    return Goal(phrase=_phrase(n.quote), task=task, viz=viz, to=to, subject=goal_stems(file_title(ctx.profiles[k].file, ctx.profiles[k].sheet)),
                at=n.at, unmet=n.reason)


def goal_notes(read: GoalsRead, plans: Sequence[Any]) -> list[str]:
    """Context lines of the deck for goals no dataset took (as `plan.goal_notes` does for the rules' goals): the
    model's goals that landed nowhere and its sentences without an answer that name no dataset."""
    if read.goals is None:
        return []
    used = " ".join(" ".join(p.task.reasons) + " " + (p.task.goal or "") for p in plans)
    out = []
    for g in read.goals:
        if g.phrase not in used:
            why = g.unmet or "ни в одном файле нет того, о чём она"
            out.append(f"Цель «{g.phrase}» данными не подтверждается: {why}.")
    for n in read.notes:
        if _phrase(n.quote) not in used:
            out.append(f"Цель «{_phrase(n.quote)}» данными не подтверждается: {n.reason}.")
    return list(dict.fromkeys(out))


def say_goals(read: GoalsRead, limit: int = 4) -> list[str]:
    """The data analyst's lines about the brief's goals (the build screen and the outline's log)."""
    if read.source == "model":
        lines = [f"цель «{_phrase(u.quote)}» понята: {u.label[:1].lower() + u.label[1:]}"
                 for u in read.understood[:limit]]
        if len(read.understood) > limit:
            lines.append(f"и ещё целей: {len(read.understood) - limit}")
        lines += [f"«{_phrase(n.quote)}» — данные не отвечают: {n.reason}" for n in read.notes[:2]]
        return lines or ["модель целей в тексте не нашла"]
    if read.error:
        return ["цели текста — по правилам разбора: модель не ответила"]
    return []


# ── the call ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _has_llm(providers: Any) -> bool:
    try:
        return bool(providers.has("llm"))
    except Exception:  # noqa: BLE001
        return False


def read_goals(brief: str, tables: Sequence[Table], profiles: Optional[Sequence[DatasetProfile]] = None,
               dataset_ids: Optional[Sequence[str]] = None, *, skills: Any = None, providers: Any = None,
               deadline: Optional[float] = None, stats: Optional[list] = None, budget_s: float = BUDGET_S,
               use_cache: bool = True, reading: Optional[GoalReading] = None) -> GoalsRead:
    """The brief's goals: the model's (checked) when a model is there and answers, otherwise the rules' (`goals=None`).
    `reading`: an answer of the model given (a recorded one) — no call."""
    t0 = time.monotonic()
    brief = (brief or "").strip()
    tables = list(tables)
    if not tables:
        return GoalsRead(source="rules", goals=None, skipped="нет данных")
    ctx = _Ctx(tables, profiles, dataset_ids)
    regex = goals_of(brief)
    if reading is None:
        if skills is None or providers is None or not _has_llm(providers):
            return rules_goals(brief, tables, _ctx=ctx, skipped="без модели")
        if not looks_like_goal(brief, regex):
            return rules_goals(brief, tables, _ctx=ctx, skipped="в тексте нет вопроса или просьбы")
    raw: Optional[dict] = None
    model: Optional[str] = None
    cached = False
    if reading is None:
        try:
            sha = skills.get(SKILL).sha256
        except Exception:  # noqa: BLE001
            sha = ""
        key = _cache_key(brief, tables, sha, _who(providers))
        hit = None
        if use_cache:
            with _LOCK:
                hit = _CACHE.get(key)
                if hit is not None:
                    _CACHE.move_to_end(key)
        if hit is not None:
            raw, model = hit
            cached = True
            reading = GoalReading.model_validate(raw)
        else:
            try:
                reading, model = _call(brief, ctx, skills, providers, deadline=deadline, stats=stats, budget_s=budget_s)
            except Exception as e:  # noqa: BLE001 - the rules parse the brief
                log.warning("goal_reader failed: %s", e)
                out = rules_goals(brief, tables, _ctx=ctx, error=str(e)[:200])
                out.seconds = time.monotonic() - t0
                return out
            raw = reading.model_dump()
            if use_cache:
                with _LOCK:
                    _CACHE[key] = (raw, model)
                    while len(_CACHE) > CACHE_SIZE:
                        _CACHE.popitem(last=False)
    else:
        raw = reading.model_dump()
    goals, notes, refused = _validate(reading, brief, ctx)
    if not goals and not notes:
        out = rules_goals(brief, tables, _ctx=ctx, error="в ответе модели нет ни одной верной цели")
        out.model, out.raw, out.dropped, out.cached = model, raw, refused, cached
        out.seconds = time.monotonic() - t0
        return out
    rules, rule_notes = _rules_understood(brief, regex, ctx)
    goals, notes, merged = _merge(brief, goals, notes, ctx, rules, rule_notes)
    plan_goals = [_fit(_to_goal(u, ctx), u, ctx) if u.source == "model" else _rules_goal(u, regex, brief) for u in goals]
    plan_goals = [g for g in plan_goals if g is not None]
    plan_goals += [g for g in (_note_goal(n, ctx) for n in notes) if g is not None]
    # one slide a dataset answers one goal: a threshold («какие ниже 90%») goes first — the plan applies a threshold of
    # any goal of the dataset to the column it shows, so the threshold's own column must be the one shown
    plan_goals.sort(key=lambda g: (not (g.ask or "").startswith(("above:", "below:")), g.at))
    for u in goals:
        if not u.label:
            u.label = label_of(u)
    out = GoalsRead(source="model", goals=plan_goals, understood=goals, notes=notes, dropped=refused + merged,
                    model=model, cached=cached, seconds=time.monotonic() - t0, raw=raw)
    if ctx.derived:
        out.tables, out.profiles = list(ctx.tables), list(ctx.profiles)
    return out


def _rules_goal(u: UnderstoodGoal, regex: Sequence[Goal], brief: str) -> Optional[Goal]:
    """The rules' own goal behind an understood goal the merge kept."""
    for g in regex:
        a, b = _span_of(g, brief)
        if a == u.at and g.task == u.task:
            return g
    return None


def _empty(res: Any) -> bool:
    """The answer is an empty object («{}»): nothing read at all — not an answer with other keys."""
    raw = getattr(res, "raw_json", None)
    if isinstance(raw, dict):
        return not raw
    return (getattr(res, "text", "") or "").strip() in ("", "{}")


def _parsed(res: Any) -> GoalReading:
    reading = res.parsed
    if not isinstance(reading, GoalReading):
        reading = GoalReading.model_validate(reading if isinstance(reading, dict) else json.loads(res.text))
    return reading


def _call(brief: str, ctx: _Ctx, skills: Any, providers: Any, *, deadline: Optional[float], stats: Optional[list],
          budget_s: float) -> tuple[GoalReading, Optional[str]]:
    """One call of `goal_reader` with every dataset, bound to a short deadline (a second only when the first answer is
    empty)."""
    from verstka.pipeline.generate import _recording

    end = time.monotonic() + budget_s
    if deadline is not None:
        end = min(end, deadline)
    rec, answered = _recording(providers, stats)
    if rec is None:
        rec = providers
    if hasattr(rec, "with_deadline"):
        rec = rec.with_deadline(end)
    variables = {"brief": brief, "datasets": dataset_cards(ctx), "tasks": list(TASKS), "retry": False}
    res = skills.run(SKILL, rec, variables)
    reading = _parsed(res)
    if _empty(res) and time.monotonic() < end - 3.0:
        # an empty object although the brief asks something (Qwen does this on a few briefs, at any temperature): one
        # more try that says so — the only second call
        res = skills.run(SKILL, rec, {**variables, "retry": True})
        reading = _parsed(res)
    model = (answered[0] if answered else None) or getattr(res, "label", None) or getattr(res, "model", None)
    return reading, model
