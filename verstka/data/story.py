"""Колода-история из данных (описание решения §3): файлы с данными и текст → `DeckOutline` для `generate_variants`.

`build_data_story(brief, tables, …)` строит историю детерминированно — обложка → контекст из текста (если он есть) →
карточки ключевых показателей → по слайду на датасет (2–3 у таблицы, разбитой по слайдам) → итог из трёх выводов →
приложения. Порядок датасетов: сначала те, о которых говорит цель текста (в порядке целей), затем динамика →
сравнение → структура → распределение → качество данных; справочники — в конце (большие — в приложении). Число
слайдов из параметров уважается: сначала уходят приложения, следующие шаги, контекст и продолжения таблиц.

Каждый слайд датасета — тот вид, который выбрал анализ (`verstka/data/plan.py`): `ChartSpec` / `TableData` / карточки,
заголовок-вывод, подпись-пояснение (`takeaway`), «Источник: файл» (`footnote`), почему так (`rationale`), другие
варианты (`alternatives`) и `OutlineSlide.data` для «Почему так». Шаблон на вход не влияет: колода одна на все три
варианта и любой шаблон — варианты различаются вёрсткой, а не видом графика.

С моделью навык `data_storyteller` пишет только связку — название и подзаголовок, контекст, итог и следующие шаги — и
может переформулировать заголовки-выводы. Каждая формулировка проверяется: заголовок датасета — `headline_ok` по его
фактам, итог и шаги — по фактам всей колоды, название и контекст — по числам текста. Не прошла — остаётся
детерминированная, а отказ записывается (`DataStory.rephrased`). Числа модель не придумывает."""

from __future__ import annotations

import inspect
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

from pydantic import BaseModel, Field

from verstka.data.answer import (
    card_label, plan_vocab, question_goals, route, rows_answer, step_grounded, steps_basis, summary_headline, topic_only,
    weak_card,
)
from verstka.data.goals import goals_of
from verstka.data.headline import headline_ok, numbers_in
from verstka.data.plan import NotBuilt, chart_spec_of, file_context, goal_notes, plan_datasets, slide_data_of
from verstka.data.profile import profile_table
from verstka.data.words import count_words, file_title, fmt_signed, fmt_value, stems_of, upper_first
from verstka.schemas.common import PatternKind
from verstka.schemas.data import TASK_TITLES, VIZ_TITLES, DatasetPlan, DatasetProfile, HeadlineFact, PreparedValues, Table
from verstka.schemas.outline import (
    Brief, ChartSpec, DeckOutline, NumberCallout, OutlineSlide, SlideAlternative, SlideContent, SlideItem, TableData,
)

log = logging.getLogger(__name__)

__all__ = [
    "DataStory", "StoryWriting", "build_data_story", "build_data_outline", "story_order", "slide_for",
    "data_slide_labels", "stamp_variants", "STORY_FILE",
]

STORY_FILE = "data_story.json"  # what the generation keeps of its datasets' plans («Пересобрать слайд так» reads it)
STEP = "data"  # the agent's step of the data analyst («Аналитик данных» on the build screen)
SKILL = "data_storyteller"
MODEL_BUDGET_S = 90.0  # the storyteller's share of the 5 minutes: one call, past it the deterministic wording stays
MAX_CONTEXT_SLIDES = 2
CONTEXT_LINES = 5
MAX_TITLE = 90
MAX_HEADLINE = 120
MAX_LINE = 160
# a conclusion beside a chart says its one or two main facts (the leader, the biggest change), never every category:
# a 300-character list beside a Forestbird chart ran over its source line (qa4)
MAX_CAPTION = 140

# the story's order after the goals: dynamics → comparison → shares → distribution → quality of data → reference
_TASK_RANK = {"kpi": 0, "dynamics": 1, "comparison": 2, "shares": 3, "distribution": 4, "relationship": 5, "reference": 8}
_QUALITY_RANK = 6  # a dataset with gaps (its nature says it): the quality of the data comes after the findings

# sentences of the brief that are no context: instructions about the deck and its files
_META_RE = re.compile(
    r"(?i)(данн\w*\s*[—–-]\s*в\b|приложен|в\s+файл|файл\w*\b|презентаци|слайд|\bпокажи|\bпокажите|\bсравни|\bсделай|"
    r"\bподготовь|\bсобери|\bоформи|\bдобавь|\bвизуализируй|\bотрази|\bпостро[ий])"
)
_TITLE_LEAD_RE = re.compile(
    r"(?i)^\s*(?:(?:сделай(?:те)?|подготовь(?:те)?|собери(?:те)?|нужна|нужно|создай(?:те)?)\s+)?"
    r"(?:презентаци[юяи]\s*(?:о|об|про|по|на\s+тему)?\s*[:—–-]?\s*)"
)
_SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[«\"A-ZА-ЯЁ0-9])|\n+")

ProgressFn = Callable[..., None]


# ── what the model writes ────────────────────────────────────────────────────────────────────────────────────────────
class StoryHeadline(BaseModel):
    """A dataset slide's conclusion said otherwise: the slide's id and the new headline."""

    id: str
    headline: str


class StoryWriting(BaseModel):
    """Output of the `data_storyteller` skill: the deck's connecting text. Every number must be one of the facts given
    (a dataset slide — its own facts, the summary and next steps — the facts of the deck, the title and the context —
    the numbers of the brief); the program checks it and keeps its own wording otherwise."""

    title: str = ""
    subtitle: str = ""
    context: list[str] = Field(default_factory=list)
    headlines: list[StoryHeadline] = Field(default_factory=list)
    summary_title: str = ""
    summary: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


# ── the result ───────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class DataStory:
    outline: DeckOutline
    plans: list[DatasetPlan]
    # the files the story read (id, file, sheet): the tables themselves are not kept — a big file's rows stay only as
    # long as its slides are built
    files: list[dict] = field(default_factory=list)
    dataset_ids: list[str] = field(default_factory=list)
    # the text around a table in a text file («Опрос NPS во II квартале не проводился…»): what the files explain
    notes: list[dict] = field(default_factory=list)
    brief_text: str = ""  # the brief as written (its hash goes into the run manifest)
    log: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"file", "sheet", "message"}: datasets with no slide
    dropped: list[str] = field(default_factory=list)  # slides the slide count left out (their headlines)
    model: Optional[str] = None  # the model that wrote the connecting text (None: the rules did)
    model_used: bool = False
    model_error: Optional[str] = None
    written: dict = field(default_factory=dict)  # what the model's answer was, as it wrote it
    rephrased: list[dict] = field(default_factory=list)  # {"what", "slide", "from", "to", "accepted", "why"}
    stats: list = field(default_factory=list)  # the storyteller's model calls (what they cost)
    seconds: float = 0.0
    # the brief's goals as the model understood them and the code checked them (verstka/data/intent.py); None — the
    # rules parsed the brief (no model)
    goals_read: Optional[dict] = None
    # the brief's questions and the files that answer them, in the story's order: {"question", "file"} (qa4 NEW-S2)
    questions: list[dict] = field(default_factory=list)
    # the summary's cards: the data slide each was made of and what it says (answer | weak | conclusion) — the model's
    # rewording of a card is checked against that slide (not saved)
    cards: list[dict] = field(default_factory=list)
    # вопросы брифа, которые колода не посчитала, с причиной (F2): на обложке и в итоге — пометка, а не ответ
    unmet: list[dict] = field(default_factory=list)
    cover_answer: bool = False  # обложка — проверенный вывод главной цели (не тема): модель не меняет его на тему

    @property
    def rejected(self) -> list[dict]:
        return [r for r in self.rephrased if not r.get("accepted")]

    def usage(self) -> dict:
        if not self.stats:
            return {}
        from verstka.pipeline.generate import call_totals

        return {"scope": "data_story", **call_totals(list(self.stats))}

    def summary(self) -> dict:
        """What run_manifest.json and generation.json keep of the story: who wrote it, what the model changed and
        what the checks refused."""
        return {
            "datasets": len(self.plans),
            "slides": len(self.outline.slides),
            "skipped": list(self.skipped),
            "dropped": list(self.dropped),
            "planned_by": self.outline.planned_by,
            "model": self.model,
            "model_error": self.model_error,
            "rephrased": sum(1 for r in self.rephrased if r.get("accepted")),
            "rejected": [{k: r.get(k) for k in ("what", "slide", "to", "why")} for r in self.rejected],
            "seconds": round(self.seconds, 2),
            **({"goals": self.goals_read} if self.goals_read is not None else {}),
            **({"questions": list(self.questions)} if self.questions else {}),
        }

    def save(self, path: Path) -> Path:
        """data_story.json: the plans of the generation's datasets (by dataset id) and what the model did — a slide
        rebuilt with another visualization (`verstka/data/rebuild.py`) reads its plan from here."""
        data = {
            "version": 1,
            "dataset_ids": list(self.dataset_ids),
            "files": list(self.files),
            "plans": [p.model_dump(mode="json") for p in self.plans],
            "summary": self.summary(),
            "written": self.written,
            "rephrased": self.rephrased,
            "log": self.log,
        }
        path = Path(path)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path


def read_story(path: Path) -> Optional[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def story_plan(data: dict, dataset_id: str) -> Optional[DatasetPlan]:
    """The plan of `dataset_id` kept in data_story.json (None when the generation has no such dataset)."""
    ids = list(data.get("dataset_ids") or [])
    plans = list(data.get("plans") or [])
    for i, p in zip(ids, plans):
        if i == dataset_id:
            return DatasetPlan.model_validate(p)
    for p in plans:  # a plan whose dataset id is the table's own (the CLI)
        if (p.get("profile") or {}).get("table_id") == dataset_id:
            return DatasetPlan.model_validate(p)
    return None


# ── events ───────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Voice:
    """The data analyst's lines: agent events for the build screen (step «data») and the outline's agent log."""

    def __init__(self, progress: Optional[ProgressFn]) -> None:
        self.progress = progress
        self.lines: list[str] = []
        takes = False
        if progress is not None:
            try:
                params = inspect.signature(progress).parameters
                takes = "event" in params or any(p.kind == p.VAR_KEYWORD for p in params.values())
            except (TypeError, ValueError):
                takes = False
        self.takes_event = takes

    def say(self, message: str, share: float = 0.05, slide: Optional[int] = None, step: str = STEP, log_it: bool = True) -> None:
        if log_it:
            self.lines.append(f"Аналитик данных: {message}")
        if self.progress is None:
            return
        ev = {"type": "agent", "step": step, "message": upper_first(message), "slide": slide, "variant": None}
        try:
            if self.takes_event:
                self.progress(ev["message"], share, event=ev)
            else:
                self.progress(f"data: {message}", share)
        except Exception:  # noqa: BLE001 - a listener never stops the deck
            log.debug("progress listener failed on a data event", exc_info=True)


# ── order ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _goal_at(plan: DatasetPlan, brief_text: str, goals: Sequence) -> Optional[int]:
    """Where the goal that chose the dataset's task stands in the text (None: no goal named it)."""
    g = plan.task.goal
    if not g:
        return None
    for x in goals:
        if x.phrase == g:
            return int(x.at)
    pos = (brief_text or "").lower().find(g.lower())
    return pos if pos >= 0 else 10**6


def _rank(plan: DatasetPlan) -> int:
    if plan.profile.nature == "with_gaps" and plan.task.task not in ("kpi", "reference"):
        return _QUALITY_RANK
    return _TASK_RANK.get(plan.task.task, 7)


def story_order(plans: Sequence[DatasetPlan], brief_text: str = "", goals: Optional[Sequence[Any]] = None) -> list[int]:
    """Indexes of `plans` in the story's order: the datasets the text's goals name (in the goals' order), then by task
    — dynamics, comparison, shares, distribution, relationship, the quality of the data, reference. A KPI dataset is
    the key-figures slide and stands first (it is not a goal's). `goals`: goals understood elsewhere (the model,
    `verstka/data/intent.py`) instead of parsing the text."""
    goals = list(goals) if goals is not None else goals_of(brief_text or "")
    keyed = []
    for k, p in enumerate(plans):
        at = _goal_at(p, brief_text, goals)
        if p.task.task == "kpi" and at is None:
            key = (0, 0, k)
        elif at is not None:
            key = (1, at, k)
        else:
            key = (2, _rank(p), k)
        keyed.append((key, k))
    return [k for _, k in sorted(keyed)]


# ── the slides ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _rationale(plan: DatasetPlan) -> str:
    opt = plan.chosen_option
    if opt is None:
        return ""
    parts = [f"{TASK_TITLES.get(plan.task.task, plan.task.task)} — {opt.title.lower() if opt.title else VIZ_TITLES[opt.kind].lower()}."]
    parts += [r.strip() for r in opt.reasons if r and r.strip()]
    if opt.aggregation:
        parts.append(f"Данные: {opt.aggregation}.")
    return " ".join(p if p.endswith((".", "!", "?", "…")) else p + "." for p in parts)


def _alternatives(plan: DatasetPlan) -> list[SlideAlternative]:
    out = []
    for k, o in enumerate(plan.options):
        if k == plan.chosen:
            continue
        why = o.why_not or "; ".join(o.reasons)
        out.append(SlideAlternative(kind=o.kind, change=f"{o.title}: {why}" if why else o.title))
    return out


def _notes(plan: DatasetPlan) -> str:
    """What the presenter may say about the numbers: how each fact of the headline was counted."""
    lines = [f.explain.strip() for f in plan.headline_facts if f.explain and f.explain.strip()]
    return "\n".join(dict.fromkeys(lines))[:1500]


def _kind_of(body: Any) -> PatternKind:
    if isinstance(body, ChartSpec):
        return PatternKind.chart
    if isinstance(body, TableData):
        return PatternKind.table
    if isinstance(body, list):
        return PatternKind.big_number if len(body) == 1 else PatternKind.stat_row
    raise TypeError(type(body).__name__)


def _content_of(body: Any) -> SlideContent:
    if isinstance(body, ChartSpec):
        return SlideContent(chart=body)
    if isinstance(body, TableData):
        return SlideContent(table=body)
    return SlideContent(numbers=list(body))


def slide_for(plan: DatasetPlan, table: Table, part: int = 1, *, slide_id: str, option: Optional[int] = None) -> Union[OutlineSlide, NotBuilt, None]:
    """The outline slide of one dataset (`part` of a table split over slides) with option `option` (default: the
    plan's chosen one): its content, conclusion headline, caption, source, rationale, alternatives and `data`. NotBuilt
    — the option does not suit the data (its reason); None — the dataset has nothing to show."""
    if option is not None and option != plan.chosen:
        plan = plan.model_copy(update={"chosen": option})
    body = chart_spec_of(plan, table, part=part)
    if body is None or isinstance(body, NotBuilt):
        return body
    if isinstance(body, ChartSpec):
        # the analysis chose this kind (or the person did, rebuilding the slide): the engine never turns it
        body = body.model_copy(update={"kind_locked": True})
    total = max(1, plan.slides)
    series_names = [x.name for x in body.series] if isinstance(body, ChartSpec) else []
    head = tidy_text(plan.headline or plan.plain_headline, series_names)
    if part > 1:
        head = f"{head.rstrip('. ')} (продолжение)"
    full = tidy_text(plan.caption, series_names) if plan.caption else None
    caption = short_caption(full)
    if isinstance(body, list):
        body = [n.model_copy(update={"label": tidy_text(n.label, [])}) for n in body]
    slide = OutlineSlide(
        id=slide_id,
        kind=_kind_of(body),
        headline=head,
        content=_content_of(body),
        takeaway=caption if part >= total else None,
        footnote=plan.source or None,
        rationale=_rationale(plan) + (f" Подпись на слайде — главное; полностью: {full}" if caption != full else ""),
        alternatives=_alternatives(plan),
        notes="\n".join(x for x in (_notes(plan), full if caption != full else "") if x) if part == 1 else "",
        data=slide_data_of(plan, part, table).model_copy(update={"prepared": prepared_of(body, full)}),
    )
    if not data_text_ok(slide.headline, slide):
        # the story says what the audit accepts: a headline whose number the data checks would refuse gives way to the
        # strongest fact said in its own words, else to the topic
        alt = next((f.text for f in plan.headline_facts if f.text and data_text_ok(f.text, slide)), None)
        log.warning("data story: headline «%s» fails the data check — «%s» instead", slide.headline, alt or plan.plain_headline)
        slide.headline = upper_first(alt) if alt else (plan.plain_headline or slide.headline)
    return slide


_CAPTION_SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[«\"A-ZА-ЯЁ])")  # (never after «кв.» before a year: «IV кв. 2024»)
_GAP_SAID_RE = re.compile(r"(?i)данных\s+нет|нет\s+данных|пропуск|пропущ|разрыв|не\s+проводил|не\s+собирал")
_LIST_PART_RE = re.compile(r"^\s*[^—:,;]{1,60}\s*[—:]\s*[+\-−–]?\d")


def short_caption(text: Optional[str], limit: int = MAX_CAPTION) -> Optional[str]:
    """A data slide's caption as the slide sets it: its first sentences up to about `limit` characters, a list of three
    and more «name — value» kept to its first two (the leader and the next) — never every category (qa4: a
    300-character list beside the chart). The full caption stays in the notes and «Почему так»."""
    if not text:
        return text
    t = re.sub(r"[ \t\r\n]+", " ", text).strip()  # (the no-break spaces of «III кв. 2026», «1 290 чел.» stay)
    sents: list[str] = []
    for sent in _CAPTION_SENT_RE.split(t):
        parts = [x for x in re.split(r",\s+", sent.rstrip(".")) if x.strip()]
        if len(parts) >= 3 and sum(1 for x in parts if _LIST_PART_RE.match(x.split(": ")[-1])) >= 3:
            sent = ", ".join(parts[:2])
            sent += "" if sent.endswith(".") else "."  # («840 чел.» ends it already)
        sents.append(sent)
    # the first sentence, then what the chart's gaps mean («За 2016 год данных нет»), then the rest — while it is short
    keep = {0}
    for k in sorted(range(1, len(sents)), key=lambda k: (not _GAP_SAID_RE.search(sents[k]), k)):
        if len(" ".join(sents[j] for j in sorted(keep | {k}))) <= limit:
            keep.add(k)
    res = " ".join(sents[j] for j in sorted(keep))
    if len(res) > limit + 20:
        cut = res[: limit + 1]
        k = max(cut.rfind(", "), cut.rfind(" — "), cut.rfind("; "))
        res = (cut[:k] if k >= limit // 2 else cut.rsplit(" ", 1)[0]).rstrip(",;:—– ") + "."
    return res


_PERIOD_GLUE = [
    (re.compile(r"\b([IV]{1,3})\s+(кв\.)\s*(\d{4})"), "\\1\u00a0\\2\u00a0\\3"),  # «III кв. 2026» never splits
    (re.compile(r"\b([IV]{1,3})\s+(кв\.|квартал\w*)"), "\\1\u00a0\\2"),
    (re.compile(r"\b(кв\.)\s+(\d{4})"), "\\1\u00a0\\2"),
    (re.compile(r"(\d)\s+(чел\.|шт\.|тыс\.|млн|млрд|руб\.|₽|%|п\.\s?п\.|п\.)"), "\\1\u00a0\\2"),
]


def tidy_text(text: Optional[str], names: Sequence[str] = ()) -> str:
    """The data layer's words set for a slide: a period and a figure with its unit never split across lines («III кв.
    2026», «1 290 чел.»), a series name inside a sentence in lower case («…: платное — 1 290 чел.»)."""
    t = text or ""
    for rx, rep_ in _PERIOD_GLUE:
        t = rx.sub(rep_, t)
    from verstka.data.words import lower_first, phrase

    for name in names:
        # (a common noun only — «Платное», «Бюджет»; a name, Latin or an acronym stays: «Scopus», «РИНЦ», «NPS»)
        p = phrase(name) if name else None
        low = lower_first(name) if p is not None and p.sure else name
        if low != name:
            t = re.sub(r"(?<=[,:;—–] )" + re.escape(name) + r"\b", low, t)
    return t


def prepared_of(body: Any, caption: Optional[str] = None) -> PreparedValues:
    """What the slide shows, as the data layer prepared it from the file (the audit's reference): its values and its
    own words — the caption, the cards' labels."""
    texts = [caption] if caption else []
    if isinstance(body, ChartSpec):
        cats = [str(c) for c in body.categories]
        series = [(x.name or "", [None if v is None else float(v) for v in x.values]) for x in body.series]
        points = [(x.name or "", [(float(a), float(b)) for a, b in zip(x.x, x.y)]) for x in body.xy]
        return PreparedValues(categories=cats, series=series, points=points, texts=texts)
    if isinstance(body, TableData):
        return PreparedValues(columns=list(body.columns), rows=[[str(c) for c in r] for r in body.rows], texts=texts)
    return PreparedValues(numbers=[n.value for n in body], texts=texts + [n.label for n in body if n.label])


# ── numbers on a data slide: one rule for the story, the redesign and the audit ─────────────────────────────────────
_YEAR_RE = re.compile(r"(?<![\d,.])(1[89]\d\d|20\d\d)(?!\d|,\d)")
_NUM_WORD_RE = re.compile(r"(?<![\w,.])\d+(?:[.,]\d+)?[\s\u00a0\u2060-]*[a-zа-яё]+\.?", re.I)


def data_labels(s: OutlineSlide) -> list[str]:
    """The slide's data names (`data_slide_labels`) and the number-words inside them («1 курс» of «Принято на 1 курс»,
    «2 квартал»): a headline that says «на 1 курс» names a row, it does not state a figure."""
    base = data_slide_labels(s)
    extra = [m.group(0).strip() for lab in base for m in _NUM_WORD_RE.finditer(lab)]
    return list(dict.fromkeys(base + [x for x in extra if x]))


def data_years(s: OutlineSlide) -> set[str]:
    """Years the data itself names: its time axis, its labels («Бюджет 2026», «III кв. 2026»), its periods. Such a year
    in a sentence dates it («27% бюджета 2026»), it is not a figure."""
    texts = list(data_slide_labels(s))
    d = s.data
    if d is not None and d.time_axis is not None:
        texts += [d.time_axis.start, d.time_axis.end, *d.time_axis.missing_periods]
    if d is not None and d.prepared is not None:
        texts += list(d.prepared.categories) + list(d.prepared.columns)
    return {m.group(1) for t in texts for m in _YEAR_RE.finditer(str(t))}


def _without_years(text: str, years: set[str]) -> str:
    return _YEAR_RE.sub(lambda m: " " if m.group(1) in years else m.group(0), text or "")


def slide_values(s: OutlineSlide) -> list[float]:
    """Every number the data layer put on the slide: its facts, the values of its chart, table and cards and the
    numbers of its own words (caption, card labels)."""
    d = s.data
    out = [float(f.value) for f in d.headline_facts] if d is not None else []
    p = d.prepared if d is not None else None
    if p is None:
        return out
    for _, vals in p.series:
        out += [float(v) for v in vals if v is not None]
    for _, pts in p.points:
        out += [float(v) for pair in pts for v in pair]
    for row in p.rows:
        for cell in row:
            out += numbers_in(str(cell))
    years = data_years(s)
    for t in list(p.numbers) + list(p.texts):
        out += numbers_in(_without_years(str(t), years))  # (every number of the data layer's own words counts)
    return out


def data_text_ok(text: str, s: OutlineSlide, *, values: Optional[Sequence[float]] = None, years: Sequence[str] = ()) -> bool:
    """Every number of `text` on data slide `s` is one of its facts (`values`: or one of these), not counting the digits
    of the data's names («1 курс», «Филиал 1») and the years the data names («бюджета 2026»)."""
    return not bad_numbers(text, s, values=values, years=years)


def bad_numbers(text: str, s: OutlineSlide, *, values: Optional[Sequence[float]] = None, years: Sequence[str] = ()) -> list[float]:
    """The numbers of `text` that are no fact of slide `s` (nor one of `values`); the years the data names and `years`
    (the brief's: «итоги 2026 года») date the sentence, they are not figures."""
    from verstka.data.truth import _DATE

    labels = data_labels(s)
    plain = _DATE.sub(" ", _without_years(text, data_years(s) | set(years)))  # «15 августа», «35-я неделя» — даты (F13)
    facts = list(s.data.headline_facts) if s.data is not None else []
    if values is not None:
        facts = facts + [HeadlineFact(id=f"v{k}", text="", value=float(v), kind="count") for k, v in enumerate(values)]
    if headline_ok(plain, facts, labels):
        return []
    from verstka.data.headline import _matches

    return [n for n in numbers_in(plain, labels) if not any(_matches(n, f.value) for f in facts)]


def data_slide_labels(s: OutlineSlide) -> list[str]:
    """The data's own names on a slide (categories, series, row labels, column titles): digits inside them («Филиал 1»,
    «18–24», «III кв. 2026») are part of a name, not a figure of the headline."""
    c = s.content
    out: list[str] = []
    for ch in (c.chart, c.chart2):
        if ch is None:
            continue
        out += [str(x) for x in ch.categories]
        out += [x.name for x in ch.series if x.name]
        out += [x.name for x in ch.xy if x.name]
        out += [x for x in (ch.x_title, ch.y_title) if x]
    if c.table is not None:
        out += list(c.table.columns)
        out += [str(r[0]) for r in c.table.rows if r]
    out += [n.label for n in c.numbers if n.label]
    if s.data is not None:
        ta = s.data.time_axis
        if ta is not None:
            out += [ta.start, ta.end] + list(ta.missing_periods)
    return [x for x in dict.fromkeys(out) if x]


def _brief_numbers(text: str) -> list[float]:
    return numbers_in(text or "")


def _numbers_from(text: str, allowed: Sequence[float], labels: Sequence[str] = ()) -> bool:
    """Every number of `text` is one of `allowed` (as a headline writes it: whole, or with one or two decimals)."""
    facts = [HeadlineFact(id=f"n{k}", text="", value=float(v), kind="count") for k, v in enumerate(allowed)]
    return headline_ok(text, facts, labels)


def _title(brief: Optional[Brief], plans: Sequence[DatasetPlan]) -> tuple[str, Optional[str], Optional[str]]:
    """(title, subtitle, None) — the brief's own title when the person gave one; else a neutral title of the data's
    topics («Пассажиропоток по маршрутам»), never the brief's first sentence (F11: an opinion «HR-директор считает…»,
    «Мэрия хочет закрыть один филиал», or a sentence cut mid-phrase). The answer to the brief's main goal replaces it
    once the slides are built (`_main_answer`)."""
    if brief is not None and brief.title_hint:
        return _cut(upper_first(brief.title_hint.strip()), MAX_TITLE), (f"Для {brief.audience}" if brief.audience else None), None
    names = [p.plain_headline for p in plans if p.slides > 0 and p.plain_headline]
    files = [file_title(p.profile.file, p.profile.sheet) for p in plans if p.slides > 0]
    topics = list(dict.fromkeys(x for x in (files or names) if x))
    title = _topic_title(topics)
    rest = len(names) - 3
    sub = (", ".join(names[:3]) + (f" и ещё {rest}" if rest > 0 else "")) if names else None
    if brief is not None and brief.audience:
        sub = f"Для {brief.audience}"
    else:
        # «Итоги продаж … для правления»: кому колода — подзаголовок (не утверждение о данных)
        first = next(iter(_sentences((brief.text if brief is not None else "") or "")), "")
        m = re.search(r"\s+(для\s+[^,;:.!?]{2,60})[.!?…]?$", first, re.I)
        if m and len(m.group(1).split()) <= 5 and not re.search(r"(?i)счита|думает|уверен|хочет|просит", first):
            sub = upper_first(m.group(1))
    return title, sub, None


def _topic_title(topics: Sequence[str]) -> str:
    """«Пассажиропоток по маршрутам», «Воронка B2B-продаж Q4 и подписочная выручка по месяцам» — темы файлов (до двух),
    «Данные: N файлов» — когда тем больше или их нет."""
    ts = [upper_first(" ".join(t.split())) for t in topics if t and t.strip()]
    if not ts:
        return "Данные колоды"
    if len(ts) == 1:
        return _cut(ts[0], MAX_TITLE)
    two = f"{ts[0]} и {lower_first_soft(ts[1])}"
    if len(ts) == 2 and len(two) <= MAX_TITLE:
        return two
    return _cut(f"{ts[0]} и ещё {count_words(len(ts) - 1, 'тема', 'темы', 'тем')}", MAX_TITLE)


def lower_first_soft(text: str) -> str:
    """Тема внутри фразы: первое слово строчное, если это не аббревиатура или имя («MRR», «ЕГЭ»)."""
    w = text.split(" ", 1)[0]
    if re.fullmatch(r"[A-ZА-ЯЁ0-9\-]{2,}", w) or not w[:1].isupper():
        return text
    return text[:1].lower() + text[1:]


def _main_answer(entries: Sequence["_Entry"], plans: Sequence[DatasetPlan], heads: dict) -> Optional[str]:
    """The cover of a brief that asks without a question mark («Покажи, как менялась посещаемость сети») or of a
    paragraph whose goal is buried: the verified headline of the first slide a goal of the brief chose — not a topic
    («Что показывают данные»), never cut mid-phrase."""
    for e in entries:
        k = e.plan_index
        if k is None or e.role not in ("data", "kpi") or not plans[k].task.goal:
            continue
        head = heads.get(k) or ""
        if not head or head == plans[k].plain_headline or topic_only(head):
            return None
        return _cut_clause(head, MAX_HEADLINE)
    return None


def _cut_clause(text: str, n: int) -> Optional[str]:
    """A line no longer than `n`, cut only at a clause («, », « — », «; »); None — no such cut."""
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    cut = t[: n + 1]
    for sep in ("; ", ", ", " — "):
        k = cut.rfind(sep)
        if k >= n * 0.4:
            return t[:k].strip()
    return None


def _cut(text: str, n: int) -> str:
    text = " ".join(text.split())
    if len(text) <= n:
        return text
    cut = text[: n + 1]
    for sep in (", ", " — ", " – ", ": "):
        k = cut.rfind(sep)
        if k >= n * 0.5:
            return cut[:k].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:—– ")


def _sentences(text: str) -> list[str]:
    body = re.sub(r"(?m)^\s*#+\s*", "", text or "")
    out = []
    for s in _SENT_RE.split(body):
        s = " ".join(s.split()).strip(" -—•*")
        if s:
            out.append(s)
    return out


def _context_lines(brief: Optional[Brief], title_sentence: Optional[str]) -> list[str]:
    """The brief's sentences that say something about the subject — not its title, its goals or instructions about
    the deck and its files («Данные — в приложенных файлах»)."""
    text = (brief.text if brief is not None else "") or ""
    goals = goals_of(text)
    out = []
    for s in _sentences(text):
        if title_sentence and s == title_sentence:
            continue
        low = s.lower()
        if any(g.phrase in low for g in goals) or _META_RE.search(s):
            continue
        if len(s) < 25:
            continue
        out.append(s if s.endswith((".", "!", "?", "…")) else s + ".")
    total = sum(len(s) for s in out)
    if len(out) < 2 and total < 140:
        return []  # one short line is no context slide
    return out[: CONTEXT_LINES * MAX_CONTEXT_SLIDES]


_WEAK_LABEL_WORDS = {"больше", "меньше", "всего", "более", "менее", "около", "почти", "только"}


def _meaningful(words: str) -> bool:
    return any(len(w) >= 4 and w.lower() not in _WEAK_LABEL_WORDS for w in re.findall(r"[а-яёa-z]+", words or "", re.I))


def _card_label(fact_text: str, value: str, topic: str, headline: str = "") -> str:
    lab = _card_label0(fact_text, value, topic)
    if lab != topic and not _meaningful(lab.split(" · ")[0]):
        # «80% — не больше …»: the headline's words around the figure say what it is («обращений получают ответ за 2 часа»)
        digits = re.sub(r"\D", "", value or "")
        m = re.search(r"[+\-−–]?\d[\d\u00a0\u202f ]*(?:[.,]\d+)?\s*%?", headline or "")
        if m and digits and re.sub(r"\D", "", m.group(0)) == digits:
            rest = " ".join((headline[: m.start()] + " " + headline[m.end():]).split()).strip(" ,—–:")
            if _meaningful(rest) and len(rest.split()) <= 8:
                return rest
        return topic
    return lab


def _card_label0(fact_text: str, value: str, topic: str) -> str:
    """What a key figure is, in its fact's words: «Нижний Новгород — 198 млн ₽» → «Нижний Новгород · выручка по
    регионам» — never the file's topic alone beside a figure it does not name (qa5: «198 млн ₽ — Выручка по регионам»
    for the smallest region)."""
    t = " ".join((fact_text or "").split())
    digits = re.sub(r"\D", "", value or "")
    words = re.sub(r"[+\-−–]?\d[\d\u00a0\u202f ]*(?:[.,]\d+)?\s*(?:%|млн\s?₽|млрд\s?₽|тыс\.\s?₽|₽|млн|млрд|мин|п\.\s?п\.)?", " ", t)
    words = re.sub(r"\s*[—–:]\s*$|^\s*[—–:]\s*|\(\s*\)", "", " ".join(words.split())).strip(" ,—–:")
    if not words or not digits or digits not in re.sub(r"\D", "", t):
        return topic
    low = topic[:1].lower() + topic[1:] if topic else ""
    if low and not set(re.findall(r"[а-яё]{4,}", words.lower())) & set(re.findall(r"[а-яё]{4,}", low.lower())):
        return f"{words} · {low}"
    return words


def _fact_cards(plans: Sequence[DatasetPlan], order: Sequence[int]) -> list[NumberCallout]:
    """Key figures when no dataset is a set of them: the headline's figure of each of the first datasets (up to four),
    its topic as the label."""
    out: list[NumberCallout] = []
    for k in order:
        p = plans[k]
        if p.slides <= 0 or p.task.task == "reference" or not p.headline:
            continue
        nums = numbers_in(p.headline)
        cands = [f for n in nums for f in p.headline_facts if abs(abs(f.value) - n) < 0.5 or abs(round(f.value) - n) < 1e-9]
        # the headline's strongest figure: a change, a share, the leader — the smallest only when nothing else
        rank = {"change": 0, "share": 1, "leader": 2, "max": 3, "total": 4, "last": 5, "median": 6, "count": 7, "min": 9}
        f = min(cands, key=lambda x: (rank.get(x.kind, 8), cands.index(x)), default=None)
        if f is None:
            continue
        unit = f.unit if f.unit not in ("раз",) else None
        value = fmt_signed(f.value, unit or "") if f.kind == "change" else fmt_value(f.value, unit)
        if any(c.value == value for c in out):
            continue  # one figure once (two files said the same +23%)
        out.append(NumberCallout(value=value, label=_card_label(f.text, value, p.plain_headline, p.headline), fact_id=f.id))
        if len(out) == 4:
            break
    return out


# the brief asks where it goes wrong («где узкие места», «какие риски»): the summary names a weak spot
_BOTTLENECK_RE = re.compile(r"(?i)узк\w*\s+мест|проблем|риск|слаб\w*\s+мест|отста|теря|потер")


_KEY_FIG_RE = re.compile(r"(?<![\w])([+\-−–]?\d[\d\u00a0\u202f ]*(?:[.,]\d+)?\s?(?:%|п\.\s?п\.|п\.|×|раз[а]?\b|(?:тыс\.|млн|млрд)\s?₽|₽))")
_ANY_FIG_RE = re.compile(r"(?<![\w\d.,])([+\-−–]?\d{1,3}(?:[\u00a0\u202f ]\d{3})+(?:,\d+)?|[+\-−–]\d+(?:,\d+)?|\d+,\d+|\d{2,})(?!\d|,\d)")


def key_figure(text: str) -> Optional[str]:
    """The key figure of a conclusion, as a card sets it large: its first share, change or sum («+23%», «41%», «1 433 млн
    ₽»), else its first signed figure («+1,9»); never a year. None without one."""
    t = text or ""
    for rx in (_KEY_FIG_RE, _ANY_FIG_RE):
        for m in rx.finditer(t):
            v = " ".join(m.group(1).split()).strip()
            if re.fullmatch(r"(?:19|20)\d\d", v):
                continue
            return v
    return None


def _summary_pick(plans: Sequence[DatasetPlan], kept: Sequence[int], order: Sequence[int], brief_text: str, heads: dict, answers: Sequence[int] = ()) -> list[int]:
    """The datasets whose conclusions make the summary, by weight, not by slide order (live QA, N-S1): the answers to
    the brief's questions first, one card each (qa4 NEW-S2), the key figures' slide (it says the period's result:
    «Выручка растёт быстрее числа клиентов»), the brief's goals in the brief's order, and a weak spot when the brief
    asks for one (a distribution's tail, then a concentration); a conclusion whose figures another card already says is
    left out (the revenue line's +23% beside the key figures' +23%). Three cards, four when the key figures and a weak
    spot both stand beside two goals or when the questions take them."""
    def head(k: int) -> str:
        return heads.get(k, plans[k].headline) or ""

    ok = [k for k in sorted(kept, key=lambda k: order.index(k)) if plans[k].slides > 0 and head(k) and head(k) != plans[k].plain_headline]
    kpi = [k for k in ok if plans[k].task.task == "kpi"]
    goals = sorted([k for k in ok if plans[k].task.goal], key=lambda k: ((brief_text or "").lower().find((plans[k].task.goal or "").lower()) % 10_000, order.index(k)))
    weak: list[int] = []
    if _BOTTLENECK_RE.search(brief_text or ""):
        weak = [k for k in ok if plans[k].task.task == "distribution"] + [k for k in ok if plans[k].task.task == "reference"]
    rest = [k for k in ok if k not in kpi and k not in goals and k not in weak]
    picked: list[int] = []
    said: set = set()

    def figures(k: int) -> set:
        return {round(n, 1) for n in numbers_in(_without_years(head(k), ()) ) if not (1900 <= n <= 2100 and n == int(n))}

    def take(k: int) -> None:
        f = figures(k)
        if k in picked or (f and f <= said):
            return
        picked.append(k)
        said.update(f)

    for k in answers:
        if k in ok and len(picked) < 4:
            take(k)
    for k in kpi[:1]:
        if len(picked) < 4:
            take(k)
    for k in goals:
        if len(picked) >= (2 if weak else 3) + (1 if kpi and weak else 0):
            break
        take(k)
    for k in weak[:1]:
        if len(picked) < 4:
            take(k)
    for k in goals + rest:
        if len(picked) >= 3:
            break
        take(k)
    return picked[:4]


def _answers(brief_text: str, goals: Sequence[Any], plans: Sequence[DatasetPlan], tables: Sequence[Table]) -> list[dict]:
    """The brief's questions with the datasets that answer them, one dataset a question: {"question", "plan", "goal",
    "rows"} — `rows`, the answer about the rows the question names (`answer.rows_answer`), or None."""
    out: list[dict] = []
    for g, q in question_goals(brief_text, goals):
        if any(a["question"] == q for a in out):
            continue
        k = route(g, plans, tables, [a["plan"] for a in out])
        if k is None or any(a["plan"] == k for a in out):
            continue
        main = None
        if k < len(tables):
            spec = plans[k].task.spec or {}
            main = spec.get("column")
            if not main:
                try:
                    from verstka.data.plan import data_of

                    m = data_of(plans[k], tables[k]).main
                    main = m.name if m is not None else None
                except Exception:  # noqa: BLE001 - no measure: the rows are said by their own columns
                    main = None
        out.append({"question": q, "plan": k, "goal": g,
                    "rows": rows_answer(q, tables[k] if k < len(tables) else None, main)})
    return out


def _add_facts(slide: Optional[OutlineSlide], facts: Sequence[HeadlineFact]) -> None:
    """Facts the story said of a data slide's file (a row the question names, a weak spot's tail) join the slide's own:
    every figure of the deck stays one of its data's (the audit's figure checks read them)."""
    if slide is None or slide.data is None:
        return
    have = {f.id for f in slide.data.headline_facts}
    for f in facts:
        if f.id not in have:
            slide.data.headline_facts.append(f)
            have.add(f.id)


def _proper_names(slides: Sequence[OutlineSlide]) -> list[str]:
    """One-word names of the data's categories («Москва», «Казань»): kept capitalised inside a sentence."""
    out = []
    for s in slides:
        p = s.data.prepared if s.data is not None else None
        names = (list(p.categories) + [str(r[0]) for r in p.rows if r]) if p is not None else []
        out += [x.strip() for x in names if x and len(x.split()) == 1 and x.strip()[:1].isupper()]
    return list(dict.fromkeys(out))


def _card_figure(text: str, facts: Sequence[HeadlineFact]) -> Optional[str]:
    """A card's key figure with its sign: a change the conclusion says «на 6% больше» is set «+6%» (qa4 NEW-S4)."""
    fig = key_figure(text)
    if not fig or fig[:1] in "+-−–" or not re.search(r"\bна\s+" + re.escape(fig.split()[0]), text or ""):
        return fig
    n = numbers_in(fig)
    signs = {f.value > 0 for f in facts if f.kind == "change" and n and abs(abs(f.value) - n[0]) < 0.051}
    return ("+" if signs.pop() else "−") + fig if len(signs) == 1 else fig


def _answer_cover(brief: Optional[Brief], answers: Sequence[dict], heads: dict, firsts: dict, title: str, subtitle: Optional[str]) -> tuple[str, Optional[str]]:
    """(title, subtitle) of a question brief's cover: the main question's answer — about the rows it names, or its
    dataset's conclusion — over the question as asked; a title the person gave stays, the answer under it."""
    a = answers[0]
    rows = a.get("rows")
    slide = firsts.get(a["plan"])
    if rows is not None and not _rows_true(rows, slide, rows.short):
        rows = a["rows"] = None  # the line does not hold against the slide's facts: its verified headline instead (F4)
    if rows is not None:
        _add_facts(slide, rows.facts)
    line = (rows.short if rows is not None else heads.get(a["plan"])) or ""
    line = " ".join(line.split()).rstrip(". ")
    line = _cut_clause(line, MAX_TITLE) or _cut_clause(line, MAX_HEADLINE) or line  # never cut mid-phrase (F11)
    if not line or topic_only(line):
        return title, subtitle
    if brief is not None and brief.title_hint:
        return title, line
    asked = " ".join(dict.fromkeys(x["question"] for x in answers))
    return line, (asked if len(asked) <= MAX_TITLE + 30 else answers[0]["question"])


def _goal_pos(g: Any) -> int:
    try:
        return int(getattr(g, "at", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _unmet_goals(brief_text: str, goals: Optional[Sequence[Any]]) -> list[dict]:
    """Цели брифа, которые колода не посчитала (их причина начинается с «по данным этот вопрос не посчитан»): {"quote",
    "why", "at"} по порядку брифа."""
    from verstka.data.intent import UNMET

    out = []
    for g in sorted(goals or [], key=_goal_pos):
        why = getattr(g, "unmet", None) or ""
        if not why.startswith(UNMET):
            continue
        quote = " ".join(str(getattr(g, "phrase", "") or "").split())
        if quote and not any(x["quote"] == quote for x in out):
            out.append({"quote": upper_first(quote), "why": why, "at": _goal_pos(g)})
    return out


def _rows_true(rows: Any, slide: Optional[OutlineSlide], line: str) -> bool:
    """The rows' answer line holds: each figure with the words of its own cell (column, row) — `truth.check` against
    the cells it was made of and the slide's own texts."""
    from verstka.data.headline import _matches

    if slide is None or slide.data is None or not rows.facts:
        return False
    vals = [f.value for f in rows.facts]
    labels = data_slide_labels(slide) + [f.text.split(" — ")[0] for f in rows.facts]
    return all(any(_matches(n, v) for v in vals) for n in numbers_in(line, labels))


def _summary_cards(plans: Sequence[DatasetPlan], picked: Sequence[int], heads: dict, firsts: dict, answers: Sequence[dict], *, weak_asked: bool) -> list[dict]:
    """The summary's cards: {"title", "text", "number", "conclusion", "plan"}. A question's card says its answer — the
    rows it names with their figures, or its dataset's conclusion; a weak spot the brief asks about is said as one
    (qa4 S3); the title is the card's topic, never a file's name, and the figure keeps its sign (qa4 NEW-S4)."""
    out = []
    for k in picked:
        p = plans[k]
        head = heads.get(k, p.headline)
        if p.slides <= 0 or not head or head == p.plain_headline:
            continue
        slide = firsts.get(k)
        title, text, kind = card_label(p, head), head, "conclusion"
        facts = list(slide.data.headline_facts) if slide is not None and slide.data is not None else []
        a = next((x for x in answers if x["plan"] == k), None)
        if a is not None:
            kind = "answer"
            if a.get("rows") is not None and not _rows_true(a["rows"], slide, a["rows"].text):
                a["rows"] = None
            if a.get("rows") is not None:
                title, text = a["rows"].title, a["rows"].text
                _add_facts(slide, a["rows"].facts)
                facts += a["rows"].facts
        elif weak_asked and p.task.task == "distribution":
            weak = weak_card(p)
            if weak is not None:
                title, text, extra = weak
                kind = "weak"
                _add_facts(slide, extra)
                facts += extra
        out.append({"title": title, "text": text, "number": _card_figure(text, facts), "conclusion": head, "plan": k, "kind": kind})
    return out


@dataclass
class _Entry:
    slide: OutlineSlide
    role: str  # title | context | kpi | facts | data | part | summary | next | appendix
    plan_index: Optional[int] = None
    keep: int = 0  # the order the slide count drops slides in: the lowest first


def build_data_story(
    brief: Union[Brief, str, None],
    tables: Sequence[Table],
    *,
    profiles: Optional[Sequence[DatasetProfile]] = None,
    plans: Optional[Sequence[DatasetPlan]] = None,
    dataset_ids: Optional[Sequence[str]] = None,
    manifest: Any = None,
    use_llm: bool = False,
    skills: Any = None,
    providers: Any = None,
    progress: Optional[ProgressFn] = None,
    slide_count: Optional[int] = None,
    deadline: Optional[float] = None,
    goals: Optional[Sequence[Any]] = None,
) -> DataStory:
    """The data deck (see the module's doc). `manifest` is accepted for the contract but never read: the story is the
    same on every template. `slide_count`: the person's slide count (the brief's when None). `goals`: the brief's goals
    understood elsewhere (`verstka.data.goals.Goal`, e.g. by the model in `verstka/data/intent.py`) — used instead of
    parsing the brief for the plans and the story's order."""
    t0 = time.monotonic()
    if isinstance(brief, str):
        brief = Brief(text=brief)
    brief_text = (brief.text if brief is not None else "") or ""
    tables = list(tables)
    orig_tables = tables
    # опечатки в подписях («Новосибрск» рядом с «Новосибирск») — строки частой подписи, с видимой пометкой (F7)
    from verstka.data.derive import merge_label_typos

    typo_notes: list[str] = []
    fixed = []
    for t_ in tables:
        t2, ns = merge_label_typos(t_)
        fixed.append(t2)
        typo_notes += ns
    if typo_notes:
        tables = fixed
        profiles = None  # профили — по исправленным таблицам
    voice = _Voice(progress)
    voice.say(f"Изучаю данные: {count_words(len(tables), 'таблица', 'таблицы', 'таблиц')}", 0.02, log_it=False)
    # the build screen's «Изучаю данные» runs the whole data work through: the goals, the files, the charts (screencast
    # trial 2: it flashed for a second after the branded copy)
    if brief_text.strip() and plans is None:
        voice.say("Понимаю цели из текста", 0.025, log_it=False)
    intent, intent_stats = None, []
    if goals is None and plans is None and use_llm and skills is not None and providers is not None and _has_llm(providers):
        # the brief's goals understood by the model (one call, every part checked by the code); it fails or says
        # nothing that holds — the rules parse the brief, as without the model (verstka/data/intent.py)
        from verstka.data.intent import read_goals, say_goals

        profiles = list(profiles) if profiles is not None else [profile_table(t) for t in tables]
        intent = read_goals(brief_text, tables, profiles, dataset_ids, skills=skills, providers=providers,
                            deadline=deadline, stats=intent_stats)
        goals = intent.goals
        if intent.tables is not None:
            # колонки-отношения целей («выручка на одного посетителя», F2): план, слайды и проверка — по ним
            orig_tables = tables
            tables = list(intent.tables)
            profiles = list(intent.profiles) if intent.profiles is not None else None
        for line in say_goals(intent):
            voice.say(line, 0.03)
    if plans is None:
        n_files = len({t.file for t in tables})
        voice.say(f"Читаю {count_words(n_files, 'файл', 'файла', 'файлов')}", 0.03, log_it=False)
        voice.say("Выбираю графики", 0.035, log_it=False)
    if plans is None:
        try:
            plans = plan_datasets(tables, brief_text, profiles, goals=goals)
        except Exception as e:  # noqa: BLE001 - a goal the engine cannot take never stops the deck (F9)
            if goals is None:
                raise
            log.warning("data story: planning with the model's goals failed (%s) — the rules' goals instead", e)
            voice.say("цели модели план не принял — цели по правилам разбора текста", 0.03)
            if intent is not None:
                intent.error = f"план по целям модели не построился: {str(e)[:120]}"
            goals = None
            plans = plan_datasets(tables, brief_text, profiles, goals=None)
    plans = list(plans)
    ids = list(dataset_ids) if dataset_ids is not None else [p.profile.table_id for p in plans]
    order = story_order(plans, brief_text, goals=goals)
    files = [{"id": i, "file": t.file, "sheet": t.sheet, "sha256": _table_sha(t)} for i, t in zip(ids, orig_tables)]
    notes = [{"file": t.file, "text": " ".join(t.notes.split())[:1500]} for t in tables if (t.notes or "").strip()]
    story = DataStory(outline=DeckOutline(title=""), plans=plans, files=files, dataset_ids=ids, notes=notes, brief_text=brief_text)
    if intent is not None:
        story.stats.extend(intent_stats)
        story.goals_read = intent.summary()

    # the brief's questions, each with the dataset that answers it: those slides come first, each question gets a card
    # of the summary and the main one is answered on the cover (qa4 NEW-S2)
    answers = _answers(brief_text, goals if goals is not None else goals_of(brief_text), plans, tables)
    # вопросы, которые колода не считает (F2: ожидаемое значение, сравнение без второй колонки…): ответа нет — пометка
    # на обложке и в итоге, а не сумма вместо ответа
    unmet = _unmet_goals(brief_text, goals)
    answers = [a for a in answers if not getattr(a["goal"], "unmet", None)]
    if answers:
        ks = [a["plan"] for a in answers]
        order = ks + [k for k in order if k not in ks]
        story.questions = [{"question": a["question"], "file": plans[a["plan"]].profile.file} for a in answers]
        for a in answers:
            voice.say(f"вопрос «{a['question']}» — отвечают данные «{plans[a['plan']].profile.file}»: их слайд — в начале, ответ — в итоге", 0.04)

    # what the analyst decided, dataset by dataset
    for k in order:
        p = plans[k]
        name = p.profile.file + (f", лист «{p.profile.sheet}»" if p.profile.sheet and p.profile.kind == "xlsx" else "")
        if p.slides <= 0:
            msg = p.message or "данные не складываются ни в график, ни в таблицу"
            story.skipped.append({"file": p.profile.file, "sheet": p.profile.sheet, "message": msg})
            voice.say(f"«{name}» — без слайда: {msg[:1].lower() + msg[1:]}", 0.04)
            continue
        opt = p.chosen_option
        what = (opt.title if opt else "").lower()
        why = (opt.reasons[0] if opt and opt.reasons else "").rstrip(".")
        goal = f" Цель «{p.task.goal}»." if p.task.goal else ""
        voice.say(f"«{name}» — {TASK_TITLES.get(p.task.task, p.task.task).lower()}, {what}: {why}.{goal}", 0.04)

    entries: list[_Entry] = []
    title, subtitle, title_sentence = _title(brief, plans)
    entries.append(_Entry(OutlineSlide(id="title", kind=PatternKind.title, headline=title, subtitle=subtitle), "title", keep=100))

    # цель текста, о которой нет ни одного файла, не теряется: строка в контексте колоды
    from verstka.data.intent import goal_notes as intent_notes

    ctx_lines = _context_lines(brief, title_sentence) + [x + "." for x in typo_notes] + (
        intent_notes(intent, plans) if intent is not None and intent.goals is not None else goal_notes(brief_text, plans))
    for j in range(0, min(len(ctx_lines), CONTEXT_LINES * MAX_CONTEXT_SLIDES), CONTEXT_LINES):
        chunk = ctx_lines[j : j + CONTEXT_LINES]
        head = "Контекст" if j == 0 else "Контекст (продолжение)"
        entries.append(_Entry(OutlineSlide(id=f"context-{j // CONTEXT_LINES + 1}", kind=PatternKind.bullets, headline=head, content=SlideContent(bullets=chunk), verbatim=True), "context", keep=3 - j // CONTEXT_LINES))

    data_entries: list[_Entry] = []
    kpi_done = False
    n_data = len([k for k in order if plans[k].slides > 0])
    for pos, k in enumerate(order):
        p, t = plans[k], tables[k]
        if p.slides <= 0:
            continue
        built: list[OutlineSlide] = []
        for part in range(1, max(1, p.slides) + 1):
            s = slide_for(p, t, part, slide_id=f"data-{k + 1}" + (f"-{part}" if part > 1 else ""))
            if isinstance(s, OutlineSlide):
                built.append(s)
            elif part == 1:
                reason = s.reason if isinstance(s, NotBuilt) else "нечего показать"
                story.skipped.append({"file": p.profile.file, "sheet": p.profile.sheet, "message": reason})
                voice.say(f"«{p.profile.file}» — без слайда: {reason[:1].lower() + reason[1:]}", 0.05)
                break
        if not built:
            continue
        # что о данных этого слайда говорят другие файлы колоды («Итоги квартала.txt» — о пропуске NPS)
        ctx = file_context(t, p, tables)
        built = [s.model_copy(update={"data": s.data.model_copy(update={"context": ctx})}) if s.data is not None else s
                 for s in built]
        if len(built) < p.slides:
            for s in built:
                if s.data is not None:
                    s.data.part = (s.data.part[0], len(built))
        is_kpi = p.task.task == "kpi" and not kpi_done and not p.task.goal
        # a big reference table is an appendix — when the story has other slides to tell before it
        appendix = p.task.task == "reference" and len(built) > 1 and any(
            plans[j].slides > 0 and not (plans[j].task.task == "reference" and plans[j].slides > 1) for j in order if j != k)
        for j, s in enumerate(built):
            if j == 0:
                role = "kpi" if is_kpi else ("appendix" if appendix else "data")
                # goals' datasets go last; then the story's own order from its end (reference first)
                keep = 90 if is_kpi else (60 + (n_data - pos) if p.task.goal else 30 + (n_data - pos))
                if appendix:
                    keep = 1
                if any(a["plan"] == k for a in answers):
                    keep = 92  # (a question's answer stays whatever the slide count)
            else:
                role, keep = ("appendix" if appendix else "part"), (0 if appendix else 10)
            data_entries.append(_Entry(s, role, k, keep))
        kpi_done = kpi_done or is_kpi

    # (a file of key figures — a goal's or not — already says them: no second row of figures, qa5 п. 9)
    if not kpi_done and n_data >= 3 and not any(plans[k].slides > 0 and plans[k].task.task == "kpi" for k in order):
        cards = _fact_cards(plans, order)
        if len(cards) >= 3:
            # the heading says the two first figures (never the topic «Главное в цифрах»)
            head = "; ".join(f"{c.label.split(' · ')[0]} — {c.value}" for c in cards[:2])
            entries.append(_Entry(OutlineSlide(id="key-figures", kind=PatternKind.stat_row, headline=head or "Главное в цифрах", content=SlideContent(numbers=cards), rationale="Главные числа выводов колоды — по одному из каждого файла."), "facts", keep=15))
    kpi_first = [e for e in data_entries if e.role == "kpi"]
    body = [e for e in data_entries if e.role in ("data", "part")]
    appendix = [e for e in data_entries if e.role == "appendix"]
    # a question brief is answered first: the answering slides before the key figures (qa4 NEW-S2)
    asked = [e for a in answers for e in body + kpi_first if e.plan_index == a["plan"]]
    kpi_first = [e for e in kpi_first if e not in asked]
    body = [e for e in body if e not in asked]
    entries = entries[:1] + [e for e in entries[1:] if e.role == "context"] + asked + kpi_first + [e for e in entries if e.role == "facts"] + body
    summary_at = len(entries)
    entries += appendix

    # the person's slide count: appendices go first, then the context, the continuation parts, the key figures made of
    # facts, then datasets from the end of the story (the goals' last); the cover and the summary stay
    limit = slide_count if slide_count is not None else (brief.slide_count if brief is not None else None)
    want_summary = len({e.plan_index for e in data_entries}) >= 2  # one dataset: its slide is the conclusion
    if limit is not None and limit > 0:
        while len(entries) + (1 if want_summary else 0) > limit:
            cand = [e for e in entries if e.role != "title"]
            if not cand:
                break
            if len(entries) <= 2 and want_summary:
                want_summary = False
                continue
            gone = min(cand, key=lambda e: (e.keep, -entries.index(e)))
            if gone.role == "kpi" and want_summary and len(entries) <= 3:
                want_summary = False
                continue
            if gone.plan_index is not None and gone.slide.data is not None and gone.slide.data.part[1] > 1 and gone.slide.data.part[0] > 1:
                # a table over several slides loses one of them: never silently — see `_trim_table`
                story.dropped.append(gone.slide.headline)
                _trim_table(entries, gone.plan_index, plans[gone.plan_index])
                summary_at = min(summary_at, len([e for e in entries if e.role != "appendix"]))
                continue
            entries.remove(gone)
            story.dropped.append(gone.slide.headline)
            if gone.role in ("data", "kpi", "appendix") and gone.plan_index is not None and gone.slide.data is not None and gone.slide.data.part[0] == 1:
                # a dataset without its first slide has no slide: its continuations go with it
                for e in [e for e in entries if e.plan_index == gone.plan_index]:
                    entries.remove(e)
            summary_at = min(summary_at, len([e for e in entries if e.role != "appendix"]))
        if story.dropped:
            voice.say(f"Слайдов просили {limit}: без {count_words(len(story.dropped), 'слайда', 'слайдов', 'слайдов')} — {', '.join('«' + h + '»' for h in story.dropped[:4])}{' и др.' if len(story.dropped) > 4 else ''}", 0.08)

    kept = {e.plan_index for e in entries if e.plan_index is not None}
    # the summary's conclusions: the questions' answers, the key figures, the goals (what the text asked about), a weak
    # spot when asked for
    heads = {e.plan_index: e.slide.headline for e in entries if e.plan_index is not None and e.slide.data is not None and e.slide.data.part[0] == 1}
    firsts = {e.plan_index: e.slide for e in entries if e.plan_index is not None and e.slide.data is not None and e.slide.data.part[0] == 1}
    main_unmet = unmet[0] if unmet and (not answers or unmet[0]["at"] < _goal_pos(answers[0]["goal"])) else None
    if main_unmet is not None and entries[0].role == "title" and not (brief is not None and brief.title_hint):
        # главный вопрос брифа не посчитан: обложка — тема данных, под ней — честная пометка (F2), не ответ
        subtitle = _cut(f"«{main_unmet['quote'].rstrip('?.!')}» — по данным не посчитано", MAX_TITLE + 60)
        entries[0].slide.headline, entries[0].slide.subtitle = title, subtitle
    elif answers and entries[0].role == "title":
        # the cover answers the main question (qa4 NEW-S2: «Что показывают данные» over a question brief)
        title, subtitle = _answer_cover(brief, answers, heads, firsts, title, subtitle)
        entries[0].slide.headline, entries[0].slide.subtitle = title, subtitle
    elif entries[0].role == "title" and not (brief is not None and brief.title_hint):
        # бриф без вопросительного знака: обложка — проверенный вывод главной цели, а не первая фраза брифа (F11)
        main = _main_answer(entries, plans, heads)
        if main:
            title = main
            entries[0].slide.headline = title
            story.cover_answer = True
    picked = _summary_pick(plans, sorted(kept), order, brief_text, heads, answers=[a["plan"] for a in answers if a["plan"] in kept])
    cards = _summary_cards(plans, picked, heads, firsts, answers, weak_asked=bool(_BOTTLENECK_RE.search(brief_text or "")))
    for u in unmet[:2]:
        cards.append({"title": "Без ответа в данных", "text": f"«{u['quote']}» — {u['why']}", "number": None,
                      "conclusion": "", "plan": None, "kind": "unmet"})
    want_summary = want_summary or (bool(unmet) and bool(cards) and len(cards) >= 2)
    if want_summary and cards:
        # each card leads with its conclusion's key figure, set large (qa3 N-L3: three columns of 9 pt text)
        items = [SlideItem(title=c["title"], text=c["text"], number=c["number"]) for c in cards]
        if not all(it.number for it in items):
            items = [it.model_copy(update={"number": None}) for it in items]  # all cards with a figure, or none
        # the headline says the two strongest conclusions, never «Четыре главных вывода» (qa4 NEW-S1)
        head = summary_headline([c["conclusion"] for c in cards if c["conclusion"]], _proper_names(firsts.values())) or "Главные выводы"
        summary = OutlineSlide(id="summary", kind=PatternKind.cards, headline=head, content=SlideContent(items=items), rationale="Выводы из фактов данных: ответы на вопросы брифа, ключевые цифры, то, о чём спрашивает бриф, и слабое место, когда о нём спрашивают.")
        body_n = len([e for e in entries if e.role != "appendix"])
        entries.insert(body_n, _Entry(summary, "summary", keep=95))
        story.cards = [{"slide": firsts[c["plan"]].id if c["plan"] in firsts else None, "kind": c["kind"]} for c in cards]
    story.unmet = list(unmet)

    slides = [e.slide for e in entries]
    outline = DeckOutline(title=title, subtitle=subtitle, audience=brief.audience if brief is not None else None, purpose="report", strategy="structured", language=(brief.language if brief is not None else "ru") or "ru", planned_by="rules", slides=slides)
    story.outline = outline

    # the model writes the connecting text; every figure it writes is checked
    if use_llm and skills is not None and providers is not None and _has_llm(providers):
        det_cover = (outline.slides[0].headline, outline.slides[0].subtitle) if outline.slides and outline.slides[0].kind == PatternKind.title else None
        _tell(story, brief, voice, skills, providers, deadline=deadline, limit=limit, tables=tables)
        _cover_agrees(story.outline, det_cover, voice)

    # a plan + data (the experts' «примерная структура + данные»): the slides in the order of the author's plan, its
    # items without data as the author's text, its request last (planning/plan_data.py — the data slides untouched)
    try:
        from verstka.planning.plan_data import follow_plan

        file_notes = [n.get("text") or "" for n in notes]
        said_plan = follow_plan(story.outline, brief_text, slide_count=limit, notes=file_notes)
        for line in said_plan:
            voice.say(line, 0.14)
        if not said_plan:
            # no plan: the deck still ends on what the input asks for (or says comes next), in its own words
            from verstka.planning.plan_data import close_with_ask

            for line in close_with_ask(story.outline, brief_text, file_notes):
                voice.say(line, 0.14)
        outline = story.outline
    except Exception:  # noqa: BLE001 - the story's own order stays
        log.warning("the plan's order not applied to the data story", exc_info=True)
    _say_designs(voice, outline)
    outline.agent_log = list(voice.lines) + list(outline.agent_log)
    story.log = list(voice.lines)
    story.seconds = time.monotonic() - t0
    return story


def _cover_agrees(outline: DeckOutline, det_cover: Optional[tuple], voice: "_Voice") -> None:
    """The cover's figure is one a slide shows (qa5: «Выручка выросла на 20% за 8 месяцев» on the cover, «+23%» on the
    slides): a cover the model wrote with a figure no slide says goes back to the checked one."""
    if det_cover is None or not outline.slides or outline.slides[0].kind != PatternKind.title:
        return
    cover = outline.slides[0]
    nums = [n for n in numbers_in(" ".join([cover.headline or "", cover.subtitle or ""])) if not (1900 <= n <= 2100)]
    if not nums:
        return
    shown = set()
    for s in outline.slides[1:]:
        texts = [s.headline or "", s.takeaway or "", s.subtitle or ""] + [x for it in s.content.items for x in (it.title, it.text, it.number or "")] + [n.value for n in s.content.numbers]
        for t in texts:
            shown.update(round(v, 2) for v in numbers_in(t))
    if all(round(n, 2) in shown for n in nums):
        return
    cover.headline, cover.subtitle = det_cover
    voice.say("обложка — проверенный вывод: число обложки модели не совпало ни с одним слайдом", 0.14)


def _say_designs(voice: _Voice, outline: DeckOutline) -> None:
    """One designer line per slide of the story (the build's storyboard draws the deck from them, for every variant):
    the form of each slide, as the planning agent says it."""
    try:
        from verstka.planning.agent import form_ru
    except Exception:  # noqa: BLE001 - the lines are a nicety
        return
    for pos, s in enumerate(outline.slides, 1):
        k = s.kind.value
        if k == "title":
            text = f"обложка «{s.headline}»"
        else:
            how = "по данным файла" if s.data is not None else "из выводов данных" if s.id in ("summary", "key-figures") else "из текста"
            text = f"«{s.headline}» {how} — {form_ru(s)}"
        voice.say(text, 0.15, slide=pos, step="designer", log_it=False)


def build_data_outline(brief: Union[Brief, str, None], tables: Sequence[Table], plans: Optional[Sequence[DatasetPlan]] = None, manifest: Any = None, use_llm: bool = False, **kw: Any) -> DeckOutline:
    """The contract of the design (§3): `build_data_story(…).outline`."""
    return build_data_story(brief, tables, plans=plans, manifest=manifest, use_llm=use_llm, **kw).outline


def _has_llm(providers: Any) -> bool:
    try:
        return bool(providers.has("llm"))
    except Exception:  # noqa: BLE001
        return False


# ── the storyteller ──────────────────────────────────────────────────────────────────────────────────────────────────
def _facts_payload(fs: Sequence[HeadlineFact]) -> list[dict]:
    return [{"text": f.text, "value": f.value, "unit": f.unit} for f in fs]


def _tell(story: DataStory, brief: Optional[Brief], voice: _Voice, skills: Any, providers: Any, *, deadline: Optional[float], limit: Optional[int] = None, tables: Optional[Sequence[Table]] = None) -> None:
    """One call of `data_storyteller`; what it wrote replaces the deterministic wording where the checks pass.
    `tables`: the files read — a true figure of a file a line names (its cell, the number in a fact's words) is
    accepted and joins that slide's facts (qa4 NEW-S3)."""
    from verstka.pipeline.generate import _recording

    o = story.outline
    brief_text = (brief.text if brief is not None else "") or ""
    data_slides = [s for s in o.slides if s.data is not None and s.data.part[0] == 1]
    plan_of = {s.id: _plan_of(story, s) for s in data_slides}
    all_labels = [x for s in o.slides for x in data_slide_labels(s)]
    summary = next((s for s in o.slides if s.id == "summary"), None)
    context = [s for s in o.slides if s.id.startswith("context-")]
    variables = {
        "brief": brief_text.strip() or "(текста нет — только файлы с данными)",
        "title": o.title,
        "subtitle": o.subtitle or "",
        "context": [b for s in context for b in s.content.bullets],
        "slides": [
            {"id": s.id, "file": s.data.file, "task": TASK_TITLES.get(plan_of[s.id].task.task, "") if plan_of[s.id] else "", "headline": s.headline,
             "topic": s.data.plain_headline, "caption": s.takeaway or "", "facts": _facts_payload(s.data.headline_facts)}
            for s in data_slides
        ],
        "summary_title": summary.headline if summary is not None else "",
        "summary": [it.text for it in summary.content.items] if summary is not None else [],
        "audience": (brief.audience if brief is not None else None) or "",
        "notes": list(story.notes),
        "questions": [q["question"] for q in story.questions],
    }
    voice.say("модель формулирует связку истории и проверяет заголовки-выводы", 0.1)
    rec, answered = _recording(providers, story.stats)
    if deadline is None:
        deadline = time.monotonic() + MODEL_BUDGET_S
    try:
        rec = rec.with_deadline(deadline) if hasattr(rec, "with_deadline") else rec
        # (with_deadline builds a new registry around the recorders: what the call cost is still recorded)
        res = skills.run(SKILL, rec, variables)
        w = res.parsed
        if not isinstance(w, StoryWriting):
            raise ValueError("ответ модели не по схеме")
    except Exception as e:  # noqa: BLE001 - the deterministic wording stays
        story.model_error = str(e)[:200]
        log.warning("data_storyteller failed: %s", e)
        voice.say("модель не ответила — формулировки остаются по правилам", 0.12)
        return
    story.model = (answered[0] if answered else None) or getattr(res, "model", None)
    story.written = w.model_dump()
    brief_nums = _brief_numbers(brief_text)
    brief_years = sorted({m.group(1) for m in _YEAR_RE.finditer(brief_text)})
    used = False

    def note(what: str, slide: Optional[str], before: str, after: str, ok: bool, why: str = "") -> None:
        story.rephrased.append({"what": what, "slide": slide, "from": before, "to": after, "accepted": ok, "why": why or None})

    def clean(x: str, n: int) -> str:
        return " ".join(str(x or "").split()).strip().rstrip(".") if len(" ".join(str(x or "").split())) <= n else ""

    source = _Attribution(data_slides, extra=_file_values(story, data_slides, tables))
    asked = bool(story.questions)
    noted = bool(story.unmet) and (o.subtitle or "").startswith("«")
    # смысл слов модели — по детерминированным текстам слайдов, собранным до её правок (F1): вердикт, уточнение, имя
    # величины или категории и единица числа — только из фактов того слайда, о котором фраза
    from verstka.data.truth import Pool, check as truth_check

    pools, vocab = _truth_pools(story, data_slides, source, tables)
    deck_pool = Pool()
    for sp in pools.values():
        deck_pool = deck_pool.merged(sp)
    deck_pool = deck_pool.merged(Pool([(o.title or "", False), (o.subtitle or "", False)]))

    def true_to(x: str, ids: Sequence[str], pool: Optional[Pool] = None) -> tuple[bool, str]:
        pl = pool if pool is not None else Pool()
        if pool is None:
            for i in ids:
                if i in pools:
                    pl = pl.merged(pools[i])
        return truth_check(x, pl, vocab, labels=all_labels)

    def framed(x: str) -> tuple[bool, str]:
        """The title's and the subtitle's numbers: the brief's, or one data slide's when the line names its subject;
        a year or a quarter dates the deck («Итоги III квартала 2026»), it is no figure (qa4 NEW-S2)."""
        x = _YEAR_RE.sub(" ", x)
        if _numbers_from(x, brief_nums):
            return True, ""
        ok, why = source.accept(x)
        return ok, "" if ok else f"{why} и не из текста"

    # the title and the subtitle; a question brief's cover keeps its answer unless the model's title is an answer too
    t = clean(w.title, MAX_TITLE)
    if t and t != o.title:
        ok, why = framed(t)
        if ok:
            ok, why = true_to(t, [], deck_pool)
        if ok and noted:
            ok, why = False, "главный вопрос брифа данными не посчитан — на обложке пометка, а не ответ"
        if ok and (asked or story.cover_answer) and topic_only(t):
            ok, why = False, "это тема, а не ответ на вопрос брифа"
        note("title", "title", o.title, t, ok, why)
        if ok:
            o.title = t
            o.slides[0].headline = t
            used = True
    st = clean(w.subtitle, MAX_TITLE + 30)
    if st and st != (o.subtitle or ""):
        ok, why = framed(st)
        if ok:
            ok, why = true_to(st, [], deck_pool)
        if ok and noted:
            ok, why = False, "под темой обложки — пометка о вопросе без ответа"
        if ok and asked:
            ok, why = False, "под ответом на обложке остаётся вопрос брифа"
        note("subtitle", "title", o.subtitle or "", st, ok, why)
        if ok:
            o.subtitle = st
            o.slides[0].subtitle = st
            used = True

    # which data slide each summary card was made of (its text is the slide's headline before any rewording)
    summary_slides = {s.headline: s.id for s in data_slides}
    # the conclusions: each against its own dataset's facts (and the data's own names)
    by_id = {h.id: h.headline for h in w.headlines}
    for s in data_slides:
        new = clean(by_id.get(s.id, ""), MAX_HEADLINE)
        if not new or new == s.headline:
            continue
        # (a true figure of the slide's file — «онлайн — лишь 9%» from its share column — counts, qa4 NEW-S3)
        bad = bad_numbers(new, s, values=source.values(s), years=brief_years)
        ok = not bad
        why = ""
        if not ok:
            why = "число " + ", ".join(_num(n) for n in bad[:3]) + " не из фактов данных"
        elif new.lower() == (s.data.plain_headline or "").lower() or (topic_only(new) and not topic_only(s.headline)):
            ok, why = False, "это тема, а не вывод"
        elif source.lists(new, s):
            ok, why = False, "перечень категорий, а не вывод"  # (the leader and the biggest change, not every category)
        elif is_description(new) and not is_description(s.headline):
            ok, why = False, "это описание чисел, а не вывод"
        elif source.wrong_category(new, s):
            ok, why = False, "число в данных относится к другой категории"
        if ok:
            ok, why = true_to(new, [s.id])
        note("headline", s.id, s.headline, new, ok, why)
        if ok:
            source.ground(new, s)
            old = s.headline
            s.headline = new
            for c in o.slides:
                if c.data is not None and c.data.dataset_id == s.data.dataset_id and c is not s and c.headline.startswith(old.rstrip(". ")):
                    c.headline = f"{new} (продолжение)"
            if summary is not None:
                for it in summary.content.items:
                    if it.text == old:
                        it.text = new
                summary_slides[new] = s.id
            used = True

    # the summary and the next steps: a line with numbers speaks of ONE data slide — its facts hold every number and
    # the line names that slide's own subject; true numbers recombined across slides («Выручка выросла на 41%», where
    # 41% is Moscow's share) are refused
    if summary is not None:
        by_slide = {s.id: s for s in data_slides}
        if len(story.cards) == len(summary.content.items):
            # (the card's own slide, also for a question's answer and a weak spot, whose text is no slide's headline)
            cards = [(it, by_slide.get(c.get("slide") or ""), c.get("kind")) for it, c in zip(summary.content.items, story.cards)]
        else:
            cards = [(it, _item_slide(it, data_slides, summary_slides), "conclusion") for it in summary.content.items]
        lines = [clean(x, MAX_CAPTION) for x in w.summary][:4]
        taken: set[str] = set()
        for x in [x for x in lines if x]:
            src, why = source.of(x)
            slot = next((it for it, sl, kind in cards if sl is not None and src is not None and sl.id == src.id and sl.id not in taken), None)
            kind = next((kind for it, sl, kind in cards if it is slot), None)
            if src is not None and slot is None:
                src, why = None, "о файле, которого нет среди выводов итога"
            if src is not None and is_description(x) and kind != "answer":
                src, why = None, "это описание чисел, а не вывод"
            if src is not None and kind != "answer" and source.lists(x, src):
                src, why = None, "перечень категорий, а не вывод"
            if src is not None:
                ok_t, why_t = true_to(x, [src.id])
                if not ok_t:
                    src, why = None, why_t
            if src is not None and kind == "weak" and not _BOTTLENECK_SAID_RE.search(x):
                # a weak spot the brief asks about stays a weak spot, not a success (qa4 S3)
                src, why = None, "узкое место, о котором спрашивает бриф, сказано как успех"
            note("summary", "summary", "", x, src is not None, why)
            if src is not None and slot is not None:
                source.ground(x, src)
                slot.text = x  # one for one: the conclusion of the same slide, the others stay
                if slot.number and key_figure(x):
                    slot.number = _card_figure(x, src.data.headline_facts if src.data is not None else [])
                taken.add(src.id)
                used = True
        sh = clean(w.summary_title, MAX_HEADLINE)
        if sh and sh != summary.headline:
            ok, why = source.accept(sh)
            # the summary's headline says what its cards back: a subject of no card («…опережает рост клиентской базы»
            # over cards about revenue, regions and channels) is refused
            backs = {sl.id for _, sl, _ in cards if sl is not None}
            named = source.subjects(sh)
            texts = [x for it in summary.content.items for x in (it.title or "", it.text or "")]
            if ok and topic_only(sh):
                ok, why = False, "это тема, а не вывод"  # «Ключевые итоги года», «Четыре главных вывода» (qa4 NEW-S1)
            elif ok and ((named and not named <= backs) or source.unbacked(sh, backs, texts)):
                ok, why = False, "заголовок итога говорит о том, чего нет в его карточках"
            if ok:
                ok, why = true_to(sh, sorted(backs))
            note("summary_title", "summary", summary.headline, sh, ok, why)
            if ok:
                summary.headline = sh
                used = True
    steps = [clean(x, MAX_CAPTION) for x in w.next_steps][:3]
    steps = [x for x in steps if x]
    good_steps = []
    explained = _explained(story.notes)
    # a step stands on the files' own proposal or on a weak spot of the data, never on the model's invention (qa4
    # NEW-S5)
    basis = steps_basis(story.notes)
    weak_words = set().union(*(plan_vocab(p) for p in story.plans if p.slides > 0 and p.task.task == "distribution")) if story.plans else set()
    data_words = set().union(*(plan_vocab(p) for p in story.plans if p.slides > 0)) if story.plans else set()
    for x in steps:
        ok, why = source.free_or_attributed(x)
        if ok and explained and _asks_why_missing(x):
            ok, why = False, "это объясняют сами файлы: " + explained
        if ok:
            ok, why = step_grounded(x, basis, weak_words, data_words)
        if ok:
            # шаг — действие, а не факт: из проверки смысла — вердикты и числа со своими словами
            ok, why = truth_check(x, deck_pool.merged(Pool(extra=basis)), vocab, labels=all_labels, step=True)
        note("next_step", "next", "", x, ok, why)
        if ok:
            source.accept(x)  # (its figures join the facts of the file it names)
            good_steps.append(x)
    if len(good_steps) >= 2 and (limit is None or len(o.slides) < limit):
        at = next((k + 1 for k, s in enumerate(o.slides) if s.id == "summary"), len(o.slides))
        # numbered steps at the template's sizes, not two bullets on an empty slide (qa3 N-L3)
        o.slides.insert(at, OutlineSlide(id="next-steps", kind=PatternKind.process, headline="Что дальше", content=SlideContent(items=[SlideItem(title=x) for x in good_steps]), rationale="Следующие шаги по выводам данных — сформулированы моделью, без новых чисел."))
        used = True

    # the context: the brief's numbers only
    if context:
        lines = [clean(x, MAX_LINE) for x in w.context][: CONTEXT_LINES * len(context)]
        lines = [x if x.endswith((".", "!", "?", "…")) else x + "." for x in lines if x]
        ctx_pool = Pool([(brief_text, False)] + [(b, False) for c in context for b in c.content.bullets])
        bad_ctx = next((why for x in lines for ok_, why in [truth_check(x, ctx_pool, vocab, free_numbers=True)] if not ok_), "")
        if lines and bad_ctx:
            note("context", "context", "", " ".join(lines), False, bad_ctx)
            lines = []
        if lines and all(_numbers_from(x, brief_nums) for x in lines):
            for k, s in enumerate(context):
                part = lines[k * CONTEXT_LINES : (k + 1) * CONTEXT_LINES]
                if part:
                    s.content.bullets = part
                    s.verbatim = False
            note("context", "context", "", " ".join(lines), True)
            used = True
        elif lines:
            note("context", "context", "", " ".join(lines), False, "число не из текста")

    if used:
        o.planned_by = "model"
        story.model_used = True
    took = sum(1 for r in story.rephrased if r["accepted"] and r["what"] == "headline")
    refused = [r for r in story.rephrased if not r["accepted"]]
    line = "модель написала связку истории" + (f", переформулировала {count_words(took, 'заголовок', 'заголовка', 'заголовков')}" if took else "")
    if refused:
        line += f"; не принято {count_words(len(refused), 'формулировка', 'формулировки', 'формулировок')}: " + "; ".join(f"«{r['to'][:60]}» — {r['why']}" for r in refused[:3])
    voice.say(line, 0.14)


def _truth_pools(story: DataStory, slides: Sequence[OutlineSlide], source: "_Attribution", tables: Optional[Sequence[Table]]):
    """({slide id: Pool}, Vocab): детерминированные тексты каждого слайда данных — заголовок, подпись, факты, значения
    графика и таблицы с подписями, ячейки файла — и имена всей колоды (величины, категории), до правок модели."""
    from verstka.data.answer import label_column
    from verstka.data.truth import Pool, vocab_of
    from verstka.data.words import fmt_exact

    pools: dict = {}
    measures: list[str] = []
    cats: list[str] = []
    for t in tables or []:
        measures += [c for c in t.columns]
        measures.append(file_title(t.file, t.sheet))
        if len(t.rows) <= 300:
            for j in range(len(t.columns)):
                vals = [r[j] for r in t.rows if j < len(r) and isinstance(r[j], str) and r[j].strip()]
                if vals and len(vals) >= 0.6 * max(1, len(t.rows)):
                    cats += vals
    for s in slides:
        d = s.data
        if d is None:
            continue
        sents: list[tuple[str, bool]] = [(s.headline or "", True)]
        p = d.prepared
        if p is not None:
            sents += [(x, True) for x in p.texts if x]
        sents += [(f.text or "", True) for f in d.headline_facts]
        topic = [d.plain_headline or "", file_title(d.file)]
        ch = s.content.chart if s.content is not None else None
        if ch is not None:
            topic += [x for x in (ch.y_title, ch.x_title, getattr(ch, "title", None)) if x]
            topic += [x.name for x in ch.series if x.name]
            cats += [str(c) for c in ch.categories] + [x.name for x in ch.series if x.name]
            unit = getattr(ch, "unit", None) or ""
            for x in ch.series:
                for c, v in zip(ch.categories, x.values):
                    if v is not None:
                        sents.append((f"{c} — {fmt_exact(float(v))} {unit} {x.name or ''}".strip(), True))
        tb = s.content.table if s.content is not None else None
        if tb is not None:
            topic += list(tb.columns)
            for r in tb.rows:
                for col, cell in zip(tb.columns[1:], r[1:]):
                    sents.append((f"{r[0]} — {col}: {cell}", True))
                if r:
                    cats.append(str(r[0]))
        for n in (s.content.numbers if s.content is not None else []):
            sents.append((f"{n.value} — {n.label or ''}", True))
        src = source.extra.get(s.id, ((), {}, {}))[2]
        sents += [(txt, False) for txt in src.values()]
        pools[s.id] = Pool(sents, " ".join(x for x in topic if x))
        measures += [x for x in topic if x]
    return pools, vocab_of(measures, cats)


def _trim_table(entries: list, k: int, plan: DatasetPlan) -> None:
    """A table split over slides keeps one slide less, and says so: a time series keeps its latest periods (the
    headline speaks of the last one), any other table its first rows; the footnote of every slide left tells how many
    rows of how many it shows («показаны последние 20 строк из 21»)."""
    parts = [e for e in entries if e.plan_index == k and e.slide.data is not None]
    rows = [len(e.slide.content.table.rows) if e.slide.content.table is not None else 0 for e in parts]
    total = sum(rows)
    keep = len(parts) - 1
    latest = plan.task.task == "dynamics"
    kept = parts[-keep:] if latest else parts[:keep]
    for e in parts:
        if e not in kept:
            entries.remove(e)
    first = parts[0].slide
    base = (first.headline or "").replace(" (продолжение)", "")
    shown = sum(len(e.slide.content.table.rows) for e in kept if e.slide.content.table is not None)
    what = f"показаны {'последние' if latest else 'первые'} {count_words(shown, 'строка', 'строки', 'строк')} из {total}"
    for j, e in enumerate(kept):
        s = e.slide
        s.headline = base if j == 0 else f"{base.rstrip('. ')} (продолжение)"
        s.data.part = (j + 1, len(kept))
        s.footnote = f"{plan.source} · {what}" if plan.source else what.capitalize()
        s.takeaway = (short_caption(plan.caption) or None) if j == len(kept) - 1 else None
        s.notes = first.notes if j == 0 else ""
        if j == 0 and e.role == "part":
            e.role, e.keep = parts[0].role, parts[0].keep
        elif j > 0 and e.role != "part" and e.role != "appendix":
            e.role, e.keep = "part", 10


# words that name no subject of their own: measures and parts every dataset may have («Рост, %», «Доля», «Число
# обращений», «больше 180», «Остальные 5»), roman quarters
_GENERIC = frozenset({
    "рост", "дол", "числ", "средн", "итог", "всег", "значен", "сумм", "количеств", "показател", "больш", "меньш",
    "остальн", "друг", "прочи", "процент", "измен", "i", "ii", "iii", "iv", "кв",
})


_CLAIM_RE = re.compile(
    r"(?i)(больше|меньше|быстрее|медленнее|выше|ниже|почти|половин|треть|четверт|вдвое|втрое|втрое|\bв\s+[\d,]+\s+раз|"
    r"лидир|впереди|отста|опережа|рост|рост[уа]?|раст|вырос|упал|пада|снизил|сниж|сократил|сокращ|увеличил|увелич|"
    r"дает|даёт|дают|принос|держ|составля|достиг|получа|укладыва|закрыва|каждый|чем\b|связан|влия|зависит|"
    r"крупнейш|наибольш|наименьш|главн|основн|только|лишь|уже|ещё|еще|подним|опуска|тянут|завыша|занижа)"
)
# a past-tense verb («получил», «заняла», «принесли») says something about the numbers (never «-ал», «-ел»: «канал»,
# «квартал», «отдел» are nouns)
_PAST_VERB_RE = re.compile(r"(?i)\b[а-яё]{3,}(?:ил|ила|ило|или|ала|али|ела|ели|ула|ули|ял|яла|яли)\b")
_PAIR_RE = re.compile(r"^\s*[^—:,;]{1,60}\s*[—:]\s*[+\-−–]?\d[^,;]*$")


def is_description(text: str) -> bool:
    """«Медиана стипендии — 3 590 ₽, среднее — 5 740 ₽»: the line only lists values against names — no verb, no
    comparison — a description of the numbers, not a conclusion about them."""
    t = " ".join((text or "").split())
    if not t or _CLAIM_RE.search(t) or _PAST_VERB_RE.search(t):
        return False
    parts = [p for p in re.split(r"[,;]\s+(?:а\s+|и\s+)?", t) if p.strip()]
    return bool(parts) and all(_PAIR_RE.match(p) for p in parts)


_MISSING_RE = re.compile(r"(?i)(отсутстви|нет\s+данных|не\s+хватает\s+данных|пропуск|пропущ|пробел)")
_WHY_RE = re.compile(r"(?i)(причин|выясн|разобра|провер|понять|установить)")
_EXPLAINS_RE = re.compile(r"(?i)[^.]*(не\s+проводил|не\s+собирал|не\s+измеря|переходил|не\s+вел|не\s+велся|прерв)[^.]*\.")


def _explained(notes: Sequence[dict]) -> str:
    """The sentence of the files' own text that explains missing data («Опрос NPS во II квартале … не проводился»),
    or ""."""
    for n in notes:
        m = _EXPLAINS_RE.search(n.get("text") or "")
        if m:
            return m.group(0).strip()[:160]
    return ""


def _asks_why_missing(step: str) -> bool:
    return bool(_MISSING_RE.search(step) and _WHY_RE.search(step))


def _item_slide(item: SlideItem, slides: Sequence[OutlineSlide], before: dict) -> Optional[OutlineSlide]:
    """The data slide a summary card was made of (by its conclusion as the story wrote it)."""
    sid = before.get(item.text)
    return next((s for s in slides if s.id == sid), None)


def _stem_hit(word: str, own: set[str]) -> Optional[str]:
    """`word` names one of `own` (stems): equal, or one a prefix of the other of 3 letters and more («сентябр» —
    «сен»)."""
    for o in own:
        if word == o or (min(len(word), len(o)) >= 3 and (word.startswith(o) or o.startswith(word))):
            return o
    return None


# a weak spot said as one: a tail, a wait, a loss — not «80% обращений получают ответ за 2 часа» (qa4 S3)
_BOTTLENECK_SAID_RE = re.compile(r"(?i)хвост|дольше|больше|долг|ждут|ожида|выброс|задерж|медлен|отста|теря|потер|узк|проблем|слаб|не\s+успева|превыша|сверх")


def _file_values(story: DataStory, slides: Sequence[OutlineSlide], tables: Optional[Sequence[Table]]) -> dict:
    """What a line may say of each data slide beyond its facts: {slide id: (values, {value: the rows it is in}, {value:
    where it comes from})} — the slide's own values (chart, table, caption), the numbers inside its facts' words
    («больше 10 часов» of a 600-minute bound) and the cells of its file («Онлайн — Доля: 9»), qa4 NEW-S3."""
    from verstka.data.answer import label_column
    from verstka.data.words import fmt_exact

    by_id = {}
    for i, t in zip(story.dataset_ids, tables or []):
        by_id[i] = t
        by_id.setdefault(t.id, t)
    out = {}
    for s in slides:
        if s.data is None:
            continue
        vals: list[float] = list(slide_values(s))
        rows: dict = {}
        src: dict = {}
        years = data_years(s)
        for f in s.data.headline_facts:
            for n in numbers_in(_without_years(f.text or "", years)):
                vals.append(n)
                src.setdefault(round(n, 4), f.text)
        t = by_id.get(s.data.dataset_id)
        if t is not None and len(t.rows) <= 300:
            j0 = label_column(t)
            for r in t.rows:
                lab = str(r[j0]).strip() if j0 is not None and j0 < len(r) and isinstance(r[j0], str) else ""
                for j, c in enumerate(r):
                    if j == j0 or not isinstance(c, (int, float)) or isinstance(c, bool):
                        continue
                    v = float(c)
                    vals.append(v)
                    rows.setdefault(round(v, 4), set()).add(lab.lower())
                    col = t.columns[j] if j < len(t.columns) else ""
                    un = (t.units[j] if j < len(t.units) else None) or ""
                    val = f"{fmt_exact(v)}{un}" if un == "%" else f"{fmt_exact(v)} {un}".strip()
                    src.setdefault(round(v, 4), f"{lab} — {col}: {val}" if lab else f"{col}: {val}")
        out[s.id] = (vals, rows, src)
    return out


class _Attribution:
    """Which data slide a sentence of the model speaks of. Each slide's own subject — the words of its topic, file
    name and labels (categories, series, row names, cards) that no other data slide has («месяц», «сен» for the revenue
    line; «регион», «Москва», «Казань» for the regions); verbs and the words of the facts are no subject. A sentence
    belongs to a slide when the slide's facts hold every number of it, it names that slide's own subject and no other
    slide's, and a number tied to a category («Москва — 41%») is said of that category, not of another («Казань
    выросла на 41%»). The slide's own headline, said again, belongs to it."""

    def __init__(self, slides: Sequence[OutlineSlide], extra: Optional[dict] = None) -> None:
        self.slides = [s for s in slides if s.data is not None]
        self.extra = extra or {}  # `_file_values`: the true figures of each slide's file beyond its facts
        self.labels = {s.id: data_labels(s) for s in self.slides}
        self.cats = {s.id: self._categories(s) for s in self.slides}
        vocab = {}
        for s in self.slides:
            d = s.data
            words = [d.plain_headline, file_title(d.file), *self.cats[s.id]]
            if d.prepared is not None:
                words += [name for name, _ in d.prepared.series] + [name for name, _ in d.prepared.points]
            vocab[s.id] = {w for w in stems_of(" ".join(x for x in words if x)) if not w.isdigit() and w not in _GENERIC}
        self.vocab = vocab
        self.own = {s.id: vocab[s.id] - set().union(*(vocab[o.id] for o in self.slides if o is not s)) for s in self.slides}
        self.all_labels = [x for v in self.labels.values() for x in v]

    @staticmethod
    def _categories(s: OutlineSlide) -> list[str]:
        p = s.data.prepared
        if p is None:
            return [str(c) for c in (s.content.chart.categories if s.content.chart is not None else [])]
        out = list(p.categories) + [str(r[0]) for r in p.rows if r]
        out += [t.split(",")[0] for t in p.texts[1:]] if p.numbers else []  # the cards' names («Выручка», «NPS»)
        return [x for x in out if x and not _YEAR_RE.fullmatch(x.strip())]

    def _names(self, line: str, s: OutlineSlide) -> set[str]:
        words = {w for w in stems_of(line) if not w.isdigit()}
        return {o for w in words if (o := _stem_hit(w, self.own[s.id]))}

    def of(self, line: str) -> tuple[Optional[OutlineSlide], str]:
        """(the slide the line speaks of, or None with why not)."""
        low = " ".join(line.lower().split()).rstrip(".")
        for s in self.slides:
            if low == " ".join(s.headline.lower().split()).rstrip("."):
                return s, ""
        named = {s.id: self._names(line, s) for s in self.slides}
        speaks = [s for s in self.slides if named[s.id]]
        if not speaks:
            return None, "не видно, о каких данных вывод" if not numbers_in(line, self.all_labels) else "вывод не называет, о каких данных его числа"
        if len(speaks) > 1:
            return None, "вывод смешивает данные разных файлов"
        s = speaks[0]
        if not data_text_ok(line, s, values=self.values(s)):
            return None, "числа не из фактов того файла, о котором говорит вывод"
        if self.wrong_category(line, s):
            return None, "число в данных относится к другой категории"
        # a number of a fact about one category, said of another («Казань выросла на 41%», where 41% is Moscow's)
        low_line = line.lower()
        cats = [c for c in self.cats[s.id] if c and c.lower() in low_line]
        if cats:
            from verstka.data.headline import _matches

            for n in numbers_in(_without_years(line, data_years(s)), self.labels[s.id]):
                hits = [f for f in s.data.headline_facts if _matches(n, f.value)]
                if hits and not any(c.lower() in (f.text or "").lower() for f in hits for c in cats) \
                        and not any(_label_named(f.text or "", line) for f in hits):
                    return None, f"число {_num(n)} в данных относится к другой категории"
        return s, ""

    def values(self, s: OutlineSlide) -> list[float]:
        return list(self.extra.get(s.id, ((), {}, {}))[0])

    def lists(self, line: str, s: OutlineSlide) -> bool:
        """The line names three and more of the slide's categories: a list of every category, not its one or two
        main facts (qa4: a 300-character list beside the chart)."""
        low = line.lower()
        return len({c.lower() for c in self.cats.get(s.id, []) if c and len(c) >= 3 and c.lower() in low}) >= 3

    def wrong_category(self, line: str, s: OutlineSlide) -> bool:
        """A figure of a file's cell said of another row than its own («Партнёры — 9%», where 9% is Онлайн's)."""
        rows = self.extra.get(s.id, ((), {}, {}))[1]
        if not rows:
            return False
        low = line.lower()
        named = {c.lower() for c in self.cats.get(s.id, []) if c and c.lower() in low}
        if not named:
            return False
        from verstka.data.headline import _matches

        for n in numbers_in(_without_years(line, data_years(s)), self.labels.get(s.id, [])):
            if any(_matches(n, f.value) for f in s.data.headline_facts):
                continue
            where = set().union(*(r for v, r in rows.items() if _matches(n, v))) if rows else set()
            if where and not (where & named) and not any(_label_named(w, line) for w in where if w):
                return True
        return False

    def ground(self, line: str, s: OutlineSlide) -> None:
        """The figures of an accepted line that are no fact of its slide yet (a cell of its file, a number in a fact's
        words) join the slide's facts: the deck's every figure stays one of its data's, for the audit too."""
        if s is None or s.data is None:
            return
        from verstka.data.headline import _matches

        src = self.extra.get(s.id, ((), {}, {}))[2]
        for n in numbers_in(_without_years(line, data_years(s)), self.labels.get(s.id, [])):
            if any(_matches(n, f.value) for f in s.data.headline_facts):
                continue
            where = next((t for v, t in src.items() if _matches(n, v)), None)
            if where is None:
                continue
            s.data.headline_facts.append(HeadlineFact(id=f"story_{len(s.data.headline_facts)}", text=where, value=float(n), kind="count"))

    def accept(self, line: str) -> tuple[bool, str]:
        """`free_or_attributed`, and an attributed line's new figures join its slide's facts (`ground`)."""
        if not numbers_in(line, self.all_labels):
            return True, ""
        src, why = self.of(line)
        if src is not None:
            self.ground(line, src)
        return src is not None, why

    def subjects(self, line: str) -> set[str]:
        """The data slides whose own subject the line names."""
        return {s.id for s in self.slides if self._names(line, s)}

    def unbacked(self, line: str, backs: set[str], texts: Sequence[str]) -> list[str]:
        """The words of `line` that name data — a topic, a label of some data slide — that neither the `backs` slides
        nor the `texts` carry («…рост клиентской базы» over cards about revenue, regions and channels)."""
        have = set().union(*(self.vocab[i] for i in backs if i in self.vocab)) if backs else set()
        have |= {w for w in stems_of(" ".join(texts)) if not w.isdigit()}
        anywhere = set().union(*self.vocab.values()) if self.vocab else set()
        return [w for w in stems_of(line) if not w.isdigit() and w not in _GENERIC and _stem_hit(w, anywhere) and not _stem_hit(w, have)]

    def free_or_attributed(self, line: str) -> tuple[bool, str]:
        """A line without numbers stands on its own; a line with numbers must belong to one data slide."""
        if not numbers_in(line, self.all_labels):
            return True, ""
        src, why = self.of(line)
        return src is not None, why


def _label_named(text: str, line: str) -> bool:
    """Строка своего числа названа во фразе: «Среднее по району — 66,4» — «66,4 по району» (ориентир, а не чужая
    категория); слова подписи — до « — », без общих («среднее», «итого»)."""
    lab = re.split(r"\s+—\s+|:\s", text or "", maxsplit=1)[0]
    own = [w for w in stems_of(lab) if w not in _GENERIC and not w.isdigit() and len(w) >= 4]
    if not own:
        return False
    words = set(stems_of(line))
    return all(any(w == x or (len(w) >= 4 and (x.startswith(w) or w.startswith(x))) for x in words) for w in own)


def _num(n: float) -> str:
    return (f"{n:.2f}".rstrip("0").rstrip(".") if n % 1 else str(int(n))).replace(".", ",")


def _plan_of(story: DataStory, s: OutlineSlide) -> Optional[DatasetPlan]:
    if s.data is None:
        return None
    for i, p in zip(story.dataset_ids, story.plans):
        if i == s.data.dataset_id or p.profile.table_id == s.data.dataset_id:
            return p
    return None


# ── after the generation ─────────────────────────────────────────────────────────────────────────────────────────────
def _merge_usage(a: dict, b: dict) -> dict:
    """Two call totals (call_totals dicts) added up: the storyteller's and the generation's own calls."""
    if not a:
        return dict(b or {})
    if not b:
        return dict(a)
    out = {"scope": "generation"}
    for k in ("calls", "requests", "tokens_in", "tokens_out", "failed"):
        out[k] = int(a.get(k) or 0) + int(b.get(k) or 0)
    costs = [x for x in (a.get("cost_rub"), b.get("cost_rub")) if x is not None]
    out["cost_rub"] = round(sum(costs), 4) if costs else None
    by = {k: dict(v) for k, v in (b.get("by_skill") or {}).items()}
    for k, v in (a.get("by_skill") or {}).items():
        if k in by:
            for f in ("calls", "requests", "tokens_in", "tokens_out", "failed"):
                by[k][f] = int(by[k].get(f) or 0) + int(v.get(f) or 0)
        else:
            by[k] = dict(v)
    out["by_skill"] = by
    return out


def stamp_usage(result: Any, stats: Optional[list], scope: str, usage: Optional[dict] = None) -> None:
    """Model calls made before the pipeline (the brandbook's read, the template's analysis) added to each variant's
    run manifest usage (qa3 E4: `by_skill` listed only the generation's own skills). `usage`: totals already counted
    (the API's brandbook job keeps them beside the brandbook)."""
    if not stats and not usage:
        return
    from verstka.pipeline.generate import call_totals

    usage = {**(usage or {}), "scope": scope} if usage else {"scope": scope, **call_totals(list(stats or []))}
    for v in getattr(result, "variants", []) or []:
        path = Path(v.out_dir) / "run_manifest.json"
        try:
            rm = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rm["usage"] = _merge_usage(usage, rm.get("usage") or {})
        path.write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")


def _table_sha(t: Table) -> str:
    """The table as read (its columns and rows), hashed: which data a deck was built from (run_manifest.inputs.data)."""
    import hashlib

    body = json.dumps({"columns": list(t.columns), "rows": [[None if c is None else str(c) for c in r] for r in t.rows]}, ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def stamp_steps(result: Any, seconds: dict) -> None:
    """The steps before `generate_variants` — the brandbook (read, branded copy, its analysis), the data story — in
    each variant's run manifest (`timings_s.brand`, `timings_s.data`) and in its total, so the manifest and the «N s
    total» line tell the whole run."""
    extra = {k: round(float(v), 2) for k, v in (seconds or {}).items() if v}
    if not extra:
        return
    for v in getattr(result, "variants", []) or []:
        timings = getattr(v, "timings", None)
        if isinstance(timings, dict):
            timings.update(extra)
            timings["total"] = round(float(timings.get("total", 0.0)) + sum(extra.values()), 2)
        path = Path(v.out_dir) / "run_manifest.json"
        try:
            rm = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t = rm.get("timings_s") if isinstance(rm.get("timings_s"), dict) else {}
        t.update(extra)
        t["total"] = round(float(t.get("total", 0.0)) + sum(extra.values()), 2)
        rm["timings_s"] = t
        path.write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")
    if hasattr(result, "seconds"):
        result.seconds = round(float(result.seconds or 0.0) + sum(extra.values()), 2)


def stamp_variants(result: Any, story: DataStory, out_dir: Optional[Path] = None) -> None:
    """After `generate_variants(outline=story.outline)`: each variant says who wrote its plan — the data analyst with
    the model's connecting text or the rules — not «supplied» (the plan did not come with the request), and its run
    manifest counts the storyteller's model calls too. data_story.json is written to `out_dir`."""
    usage = story.usage()
    for v in getattr(result, "variants", []) or []:
        planner = {"planned_by": story.outline.planned_by, "model": story.model, "data": story.summary()}
        v.planner = planner
        path = Path(v.out_dir) / "run_manifest.json"
        try:
            rm = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rm["planner"] = planner
        # what the deck was built from: the brief's text and every data file as read (qa3 N-U2: both were null)
        inputs = rm.get("inputs") if isinstance(rm.get("inputs"), dict) else {}
        if story.brief_text and not inputs.get("brief_sha256"):
            import hashlib

            inputs["brief_sha256"] = hashlib.sha256(story.brief_text.encode("utf-8")).hexdigest()[:16]
        inputs["data"] = [{"file": f.get("file"), "sheet": f.get("sheet"), "sha256": f.get("sha256")} for f in story.files]
        rm["inputs"] = inputs
        if usage:
            rm["usage"] = _merge_usage(usage, rm.get("usage") or {})
        extra = rm.get("extra") if isinstance(rm.get("extra"), dict) else None
        if extra is not None and isinstance(extra.get("planner"), dict):
            extra["planner"] = planner
        path.write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_dir is not None:
        story.save(Path(out_dir) / STORY_FILE)
