"""Данные (вторая ступень): таблица из файла, её профиль, аналитическая задача, варианты визуализации и факты для
заголовка-вывода — общие контракты слоя `verstka/data/`, API и интерфейса.

Путь датасета: файл → `Table` (readers) → `DatasetProfile` (profile) → `TaskDecision`, `VizOption` × 2–3,
`HeadlineFact` (task, viz, facts) → `DatasetPlan` (plan) → слайд колоды с `SlideData` в `OutlineSlide.data`
(«Почему так») и `DatasetSummary` — карточка файла в панели «Данные».

Интерпретация — детерминированный код: всё, что здесь лежит, посчитано, а не написано моделью. Тексты для человека
(причины, «почему не он», пояснения) — по-русски, спокойно, без англицизмов."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

# формат файла, из которого прочитана таблица (.txt и .md — «text»: таблица внутри текста)
SourceKind = Literal["csv", "tsv", "xlsx", "json", "text"]
# тип значений колонки
ColumnType = Literal["number", "percent", "money", "date", "period", "category", "text", "boolean", "id"]
# роль колонки в датасете: ось времени, измерение (категории), метрика (числа), идентификатор, подпись (текст строки),
# атрибут (описывает строку, но не ось и не мера: дата договора в списке клиентов)
ColumnRole = Literal["time", "dimension", "metric", "id", "text", "attribute"]
# частота оси времени; «hour» — время внутри дня («2025-03-01T10:00»); «irregular» — даты без постоянного шага
TimeFreq = Literal["hour", "day", "week", "month", "quarter", "year", "irregular"]
# аналитическая задача датасета (ТЗ, п. 2)
TaskKind = Literal["dynamics", "comparison", "shares", "distribution", "relationship", "reference", "kpi"]
# вид визуализации — от задачи и профиля, не от шаблона и не от формата файла
VizKind = Literal[
    "line", "column", "bar", "histogram", "pie", "doughnut", "scatter", "grouped_column", "grouped_bar",
    "stacked_column", "stacked_bar", "kpi_cards", "table", "area",
]
# природа датасета — строка его карточки («Временной ряд · 21 строка · 3 колонки»)
Nature = Literal[
    "time_series", "comparison", "shares", "distribution", "reference", "with_gaps", "text_table", "relationship",
    "kpi", "untypable",
]
# размер: small ≤ 12 строк, medium ≤ 60, large — больше
DatasetSize = Literal["small", "medium", "large"]
# вид факта для заголовка-вывода
FactKind = Literal["change", "share", "leader", "max", "min", "median", "percentile", "count", "total", "gap", "outliers"]

# ячейка таблицы: число, логическое значение, строка или пусто; даты и периоды — ISO-строки («2025-01», «2025-Q1»)
Cell = Union[bool, int, float, str, None]

NATURE_LABELS: dict[Nature, str] = {
    "time_series": "Временной ряд",
    "comparison": "Сравнение",
    "shares": "Доли",
    "distribution": "Распределение",
    "reference": "Справочник",
    "with_gaps": "С пропусками",
    "text_table": "Таблица в тексте",
    "relationship": "Взаимосвязь",
    "kpi": "Ключевые показатели",
    "untypable": "Не для графика",
}

VIZ_TITLES: dict[VizKind, str] = {
    "line": "Линейный график",
    "column": "Столбцы",
    "bar": "Полосы",
    "histogram": "Гистограмма",
    "pie": "Круговая",
    "doughnut": "Кольцевая",
    "scatter": "Рассеяние",
    "grouped_column": "Сгруппированные столбцы",
    "grouped_bar": "Сгруппированные полосы",
    "stacked_column": "Накопительные столбцы",
    "stacked_bar": "Накопительные полосы",
    "kpi_cards": "Карточки показателей",
    "table": "Таблица",
    "area": "Область",
}

# названия задач — как в «Почему так» (раздел «Задача»)
TASK_TITLES: dict[TaskKind, str] = {
    "dynamics": "Динамика",
    "comparison": "Сравнение категорий",
    "shares": "Структура долей",
    "distribution": "Распределение",
    "relationship": "Взаимосвязь",
    "reference": "Справочные значения",
    "kpi": "Ключевые значения",
}


class Table(BaseModel):
    """Таблица, прочитанная из файла: лист XLSX, ключ JSON и таблица внутри текста — каждая своя."""

    id: str
    # имя файла, как его загрузили («Выручка по месяцам.csv»)
    file: str
    kind: SourceKind
    # лист XLSX, ключ JSON-объекта или номер таблицы в тексте; None — в файле одна таблица
    sheet: Optional[str] = None
    # имена колонок без единиц («Выручка»)
    columns: list[str] = Field(default_factory=list)
    # единица каждой колонки — по порядку колонок («млн ₽», «%»); None — без единицы
    units: list[Optional[str]] = Field(default_factory=list)
    rows: list[list[Cell]] = Field(default_factory=list)
    # заголовки, как в файле («Выручка, млн ₽»)
    raw_header: list[str] = Field(default_factory=list)
    # текст вокруг таблицы (файл .txt/.md): контекст, единицы, период
    notes: str = ""
    # номера строк (Table.rows) с итогом по строгому правилу («Итого», «Всего:», «Итого по России»): строка остаётся
    # в таблице, но не данные — в графики и статистику не идёт, по ней проверяются «доли от итога»
    totals: list[int] = Field(default_factory=list)
    # таблица показателей по строкам («Показатель | 2026 | 2025 | Изменение»): единица каждой строки
    # («чел.», «%», «млн ₽»; None — без единицы), по порядку Table.rows. Пусто — единицы у колонок (Table.units)
    row_units: list[Optional[str]] = Field(default_factory=list)
    # группа над колонкой из двухэтажной шапки («Форма обучения» над «Бюджет · Платное · Целевое»), по порядку
    # колонок; None — без группы. Пусто — групп нет
    column_groups: list[Optional[str]] = Field(default_factory=list)

    def column_values(self, column: Union[int, str]) -> list[Cell]:
        """Значения колонки по номеру или имени (короткая строка — пусто)."""
        j = column if isinstance(column, int) else self.columns.index(column)
        return [r[j] if j < len(r) else None for r in self.rows]

    def unit_of(self, column: Union[int, str]) -> Optional[str]:
        j = column if isinstance(column, int) else self.columns.index(column)
        return self.units[j] if j < len(self.units) else None


class ColumnProfile(BaseModel):
    name: str
    unit: Optional[str] = None
    type: ColumnType
    role: ColumnRole
    missing: int = 0
    distinct: int = 0
    # для чисел — числа, для дат и периодов — ISO-строки
    min: Optional[Union[float, str]] = None
    max: Optional[Union[float, str]] = None
    median: Optional[Union[float, str]] = None
    # первое и последнее непустое значение (по порядку строк)
    first: Cell = None
    last: Cell = None
    # номера строк (Table.rows) с выбросами
    outliers: list[int] = Field(default_factory=list)
    # несколько значений, как в файле
    samples: list[Cell] = Field(default_factory=list)


class TimeAxis(BaseModel):
    column: str
    freq: TimeFreq
    # начало и конец — ISO («2025-01», «2026-Q3», «2025-01-31»)
    start: str
    end: str
    points: int
    # периоды без строки или без значения метрики — разрывы линии, а не ноль
    missing_periods: list[str] = Field(default_factory=list)


class Outlier(BaseModel):
    column: str
    row: int  # номер строки в Table.rows
    value: float
    # «больше 1,5 межквартильного размаха над третьим квартилем»
    reason: str = ""


class DatasetProfile(BaseModel):
    table_id: str
    file: str
    kind: SourceKind
    sheet: Optional[str] = None
    rows: int
    cols: int
    columns: list[ColumnProfile] = Field(default_factory=list)
    time_axis: Optional[TimeAxis] = None
    # имена колонок-метрик и колонок-измерений
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    # иерархии: (дочерняя, родительская) — («город», «регион»)
    hierarchies: list[tuple[str, str]] = Field(default_factory=list)
    missing_total: int = 0
    # выбросы, похожие на ошибку или событие (время ответа 1 430 мин в распределении) — их показывает карточка файла
    outliers: list[Outlier] = Field(default_factory=list)
    # значения далеко от остальных, но естественные для сущностей строк: крупнейшие клиенты справочника, Москва среди
    # регионов. Не проблема данных — карточка их не называет; для анализа остаются здесь (и в ColumnProfile.outliers)
    expected_outliers: list[Outlier] = Field(default_factory=list)
    # части одного целого: доли с суммой ≈ 100 или доли от итога
    parts_of_whole: bool = False
    # колонка-итог по строкам («Всего» = «Бюджет» + «Платное» + «Целевое») и её части; None / пусто — такой нет
    total_column: Optional[str] = None
    part_columns: list[str] = Field(default_factory=list)
    size: DatasetSize = "small"
    nature: Nature
    # пригодность для графика: False — с причиной («одни текстовые колонки», «одна строка»)
    typable: bool = True
    untypable_reason: Optional[str] = None
    # «Временной ряд · 21 строка · 3 колонки»
    summary: str = ""


class TaskDecision(BaseModel):
    task: TaskKind
    # короткие причины — идут в «Почему так»
    reasons: list[str] = Field(default_factory=list)
    # фраза из текста, которая подняла задачу («покажи рост выручки»); None — цели в тексте нет
    goal: Optional[str] = None
    # баллы всех рассмотренных задач
    scores: dict[TaskKind, float] = Field(default_factory=dict)
    # цель, понятая снаружи (модель): её поля (`goals.Goal` без фразы — колонка, разрез, категории, вес, период, вопрос)
    # — чтобы данные слайда и пересборка после перезапуска видели ту же величину, что и план, без разбора фразы
    spec: Optional[dict[str, Any]] = None


class VizOption(BaseModel):
    kind: VizKind
    score: float = 0.0
    # название варианта; пусто — по виду (VIZ_TITLES): «Ранжированные горизонтальные столбцы» точнее, чем «Полосы»
    title: str = ""
    # почему этот вариант подходит («Дата и одна метрика, 21 точка — тренд виден сразу»)
    reasons: list[str] = Field(default_factory=list)
    # для невыбранного — почему не он («Названия регионов не помещаются под столбцами»)
    why_not: Optional[str] = None
    # как подготовлены данные для варианта («топ-10 и строка «Остальные 230»», «по месяцам», «9 интервалов»)
    aggregation: Optional[str] = None

    @model_validator(mode="after")
    def _title_by_kind(self) -> "VizOption":
        if not self.title:
            self.title = VIZ_TITLES[self.kind]
        return self


class HeadlineFact(BaseModel):
    """Число для заголовка-вывода, посчитанное из подготовленных данных: каждое число заголовка есть среди фактов."""

    id: str
    # «Выручка выросла на 23% к сентябрю 2026»
    text: str
    value: float
    # «%», «п.п.», «млн ₽»
    unit: Optional[str] = None
    kind: FactKind
    # откуда число («Сентябрь 2026 к сентябрю 2025: 423 млн ₽ — на 23% больше. Посчитано по колонке «Выручка».»)
    explain: str = ""


class DatasetPlan(BaseModel):
    """Решение по датасету: задача, ранжированные варианты, выбранный, заголовок-вывод и его факты."""

    profile: DatasetProfile
    task: TaskDecision
    # 2–3 варианта, лучший по данным — первым
    options: list[VizOption] = Field(default_factory=list)
    # номер выбранного варианта в options (обычно 0; «Пересобрать слайд так» выбирает другой)
    chosen: int = 0
    headline: str = ""
    headline_facts: list[HeadlineFact] = Field(default_factory=list)
    # заголовок-описание, которым слайд мог бы назваться («Выручка по месяцам»): тема, а не вывод
    plain_headline: str = ""
    # подпись-пояснение под графиком (1–2 строки)
    caption: Optional[str] = None
    # «Источник: Выручка по месяцам.csv»
    source: str = ""
    # сколько слайдов занимает датасет (1–3; 0 — датасет пропущен, причина в message)
    slides: int = 1
    # сообщение для карточки файла, ленты агента и «Почему так» («Не для графика: одни текстовые колонки»)
    message: Optional[str] = None

    @property
    def chosen_option(self) -> Optional[VizOption]:
        return self.options[self.chosen] if 0 <= self.chosen < len(self.options) else None


class PreparedValues(BaseModel):
    """Значения слайда, как их подготовил из файла слой данных (до вёрстки и правок): аудит сверяет колоду с ними, а не
    с планом слайда, который могли поменять. Диаграмма — категории и ряды (None — пропуск), рассеяние — точки рядов,
    таблица — шапка и строки, карточки — значения как написаны."""

    categories: list[str] = Field(default_factory=list)
    series: list[tuple[str, list[Optional[float]]]] = Field(default_factory=list)
    points: list[tuple[str, list[tuple[float, float]]]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)
    # слова слоя данных на слайде (подпись-пояснение, подписи карточек): их числа — тоже из файла
    texts: list[str] = Field(default_factory=list)


class SlideData(BaseModel):
    """Данные слайда для «Почему так» (OutlineSlide.data): профиль кратко, задача, варианты и факты заголовка."""

    dataset_id: str
    file: str
    # «CSV · 21 строка × 3 колонки · временной ряд»
    profile_line: str = ""
    nature: Optional[Nature] = None
    # подпись природы; пусто — по NATURE_LABELS
    nature_label: str = ""
    columns: list[ColumnProfile] = Field(default_factory=list)
    time_axis: Optional[TimeAxis] = None
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    missing_total: int = 0
    outliers: list[Outlier] = Field(default_factory=list)
    task: Optional[TaskDecision] = None
    options: list[VizOption] = Field(default_factory=list)
    # номер выбранного варианта в options
    chosen: int = 0
    headline_facts: list[HeadlineFact] = Field(default_factory=list)
    # заголовок-описание, которым слайд мог бы назваться (тема, а не вывод)
    plain_headline: str = ""
    # как подготовлены данные этого слайда («топ-10 и строка «Остальные 230»»)
    aggregation: Optional[str] = None
    # часть k из n: датасет, разбитый на несколько слайдов
    part: tuple[int, int] = (1, 1)
    # значения слайда из файла (для аудита данных); None — колоды, собранные до этого поля
    prepared: Optional[PreparedValues] = None
    # что сам файл говорит о своих данных: текст вокруг таблицы (до ~600 знаков, без строки-заголовка и сносок вроде
    # «Источник:») — «Опрос NPS во II квартале не проводился…»; None — файл без такого текста. Числа из него в подписи
    # проходят то же правило, что и остальные
    context: Optional[str] = None

    @model_validator(mode="after")
    def _label_by_nature(self) -> "SlideData":
        if not self.nature_label and self.nature is not None:
            self.nature_label = NATURE_LABELS[self.nature]
        return self


class DatasetSummary(BaseModel):
    """Карточка файла в панели «Данные» (ответ POST /api/datasets)."""

    id: str
    file: str
    kind: SourceKind
    rows: int = 0
    cols: int = 0
    nature: Nature
    # подпись природы; пусто — по NATURE_LABELS
    nature_label: str = ""
    # строка профиля: «Временной ряд · 21 строка · 3 колонки»
    line: str = ""
    # что заметно в данных: «2 пропуска», «3 выброса», «Не для графика: одни тексты»
    issues: list[str] = Field(default_factory=list)
    sheet: Optional[str] = None

    @model_validator(mode="after")
    def _label_by_nature(self) -> "DatasetSummary":
        if not self.nature_label:
            self.nature_label = NATURE_LABELS[self.nature]
        return self
