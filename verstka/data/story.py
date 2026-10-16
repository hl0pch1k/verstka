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

from verstka.data.goals import goals_of
from verstka.data.headline import headline_ok, numbers_in
from verstka.data.plan import NotBuilt, chart_spec_of, plan_datasets, slide_data_of
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


def story_order(plans: Sequence[DatasetPlan], brief_text: str = "") -> list[int]:
    """Indexes of `plans` in the story's order: the datasets the text's goals name (in the goals' order), then by task
    — dynamics, comparison, shares, distribution, relationship, the quality of the data, reference. A KPI dataset is
    the key-figures slide and stands first (it is not a goal's)."""
    goals = goals_of(brief_text or "")
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
    caption = tidy_text(plan.caption, series_names) if plan.caption else None
    if isinstance(body, list):
        body = [n.model_copy(update={"label": tidy_text(n.label, [])}) for n in body]
    slide = OutlineSlide(
        id=slide_id,
        kind=_kind_of(body),
        headline=head,
        content=_content_of(body),
        takeaway=caption if part >= total else None,
        footnote=plan.source or None,
        rationale=_rationale(plan),
        alternatives=_alternatives(plan),
        notes=_notes(plan) if part == 1 else "",
        data=slide_data_of(plan, part).model_copy(update={"prepared": prepared_of(body, caption)}),
    )
    if not data_text_ok(slide.headline, slide):
        # the story says what the audit accepts: a headline whose number the data checks would refuse gives way to the
        # strongest fact said in its own words, else to the topic
        alt = next((f.text for f in plan.headline_facts if f.text and data_text_ok(f.text, slide)), None)
        log.warning("data story: headline «%s» fails the data check — «%s» instead", slide.headline, alt or plan.plain_headline)
        slide.headline = upper_first(alt) if alt else (plan.plain_headline or slide.headline)
    return slide


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
    for name in names:
        if name and len(name) > 1 and name[0].isupper() and not name[1].isupper():
            t = re.sub(r"(?<=[,:;—–] )" + re.escape(name) + r"\b", name[0].lower() + name[1:], t)
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
_YEAR_RE = re.compile(r"(?<![\d,.])(1[89]\d\d|20\d\d)(?![\d,])")
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
    labels = data_labels(s)
    plain = _without_years(text, data_years(s) | set(years))
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
    """(title, subtitle, the brief's sentence it came from) — the brief's title, or its first sentence when that names
    the deck (its tail «для правления» becomes the subtitle); else a title of the data."""
    if brief is not None and brief.title_hint:
        return _cut(upper_first(brief.title_hint.strip()), MAX_TITLE), (f"Для {brief.audience}" if brief.audience else None), None
    text = (brief.text if brief is not None else "") or ""
    first = next((s for s in _sentences(text)), "")
    goals = goals_of(text)
    if first and not any(g.phrase in first.lower() for g in goals):
        head = _TITLE_LEAD_RE.sub("", first).strip().rstrip(".!…").strip()
        sub = None
        m = re.search(r"\s+(для\s+[^,;:]{2,60})$", head, re.I)
        if m and len(m.group(1).split()) <= 5 and len(head[: m.start()].split()) >= 2:
            sub = upper_first(m.group(1))
            head = head[: m.start()].strip()
        if head and not _META_RE.search(head) and len(head.split()) >= 2:
            return _cut(upper_first(head), MAX_TITLE), sub or (f"Для {brief.audience}" if brief is not None and brief.audience else None), first
    names = [p.plain_headline for p in plans if p.slides > 0 and p.plain_headline][:3]
    rest = sum(1 for p in plans if p.slides > 0) - len(names)
    sub = ", ".join(names) + (f" и ещё {rest}" if rest > 0 else "") if names else None
    return "Что показывают данные", sub, None


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


def _fact_cards(plans: Sequence[DatasetPlan], order: Sequence[int]) -> list[NumberCallout]:
    """Key figures when no dataset is a set of them: the headline's figure of each of the first datasets (up to four),
    its topic as the label."""
    out: list[NumberCallout] = []
    for k in order:
        p = plans[k]
        if p.slides <= 0 or p.task.task == "reference" or not p.headline:
            continue
        nums = numbers_in(p.headline)
        f = next((f for n in nums for f in p.headline_facts if abs(abs(f.value) - n) < 0.5 or abs(round(f.value) - n) < 1e-9), None)
        if f is None:
            continue
        unit = f.unit if f.unit not in ("раз",) else None
        value = fmt_signed(f.value, unit or "") if f.kind == "change" else fmt_value(f.value, unit)
        out.append(NumberCallout(value=value, label=p.plain_headline, fact_id=f.id))
        if len(out) == 4:
            break
    return out


def _summary_lines(plans: Sequence[DatasetPlan], order: Sequence[int], heads: Optional[dict] = None) -> list[tuple[str, str]]:
    """(topic, conclusion) of the first three datasets of the story: the goals' first; `heads` — the headlines their
    slides carry (the story's self-check may have replaced the plan's)."""
    out = []
    for k in order:
        p = plans[k]
        head = (heads or {}).get(k, p.headline)
        if p.slides <= 0 or not head or head == p.plain_headline:
            continue
        out.append((p.plain_headline or p.profile.file, head))
        if len(out) == 3:
            break
    return out


_COUNT_WORD = {1: "Главный вывод", 2: "Два главных вывода", 3: "Три главных вывода"}


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
) -> DataStory:
    """The data deck (see the module's doc). `manifest` is accepted for the contract but never read: the story is the
    same on every template. `slide_count`: the person's slide count (the brief's when None)."""
    t0 = time.monotonic()
    if isinstance(brief, str):
        brief = Brief(text=brief)
    brief_text = (brief.text if brief is not None else "") or ""
    tables = list(tables)
    voice = _Voice(progress)
    voice.say(f"Изучаю данные: {count_words(len(tables), 'таблица', 'таблицы', 'таблиц')}", 0.02, log_it=False)
    plans = list(plans) if plans is not None else plan_datasets(tables, brief_text, profiles)
    ids = list(dataset_ids) if dataset_ids is not None else [p.profile.table_id for p in plans]
    order = story_order(plans, brief_text)
    files = [{"id": i, "file": t.file, "sheet": t.sheet} for i, t in zip(ids, tables)]
    notes = [{"file": t.file, "text": " ".join(t.notes.split())[:1500]} for t in tables if (t.notes or "").strip()]
    story = DataStory(outline=DeckOutline(title=""), plans=plans, files=files, dataset_ids=ids, notes=notes)

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

    ctx_lines = _context_lines(brief, title_sentence)
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
            else:
                role, keep = ("appendix" if appendix else "part"), (0 if appendix else 10)
            data_entries.append(_Entry(s, role, k, keep))
        kpi_done = kpi_done or is_kpi

    if not kpi_done and n_data >= 3:
        cards = _fact_cards(plans, order)
        if len(cards) >= 3:
            entries.append(_Entry(OutlineSlide(id="key-figures", kind=PatternKind.stat_row, headline="Главное в цифрах", content=SlideContent(numbers=cards), rationale="Главные числа выводов колоды — по одному из каждого файла."), "facts", keep=15))
    kpi_first = [e for e in data_entries if e.role == "kpi"]
    body = [e for e in data_entries if e.role in ("data", "part")]
    appendix = [e for e in data_entries if e.role == "appendix"]
    entries = entries[:1] + [e for e in entries[1:] if e.role == "context"] + kpi_first + [e for e in entries if e.role == "facts"] + body
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
    # the summary's conclusions: the goals' datasets first (what the text asked about), then the story's order
    heads = {e.plan_index: e.slide.headline for e in entries if e.plan_index is not None and e.slide.data is not None and e.slide.data.part[0] == 1}
    lines = _summary_lines(plans, sorted(kept, key=lambda k: (0 if plans[k].task.goal else 1, order.index(k))), heads)
    if want_summary and lines:
        items = [SlideItem(title=topic, text=concl) for topic, concl in lines]
        summary = OutlineSlide(id="summary", kind=PatternKind.cards, headline=_COUNT_WORD.get(len(items), "Главные выводы"), content=SlideContent(items=items), rationale="Три вывода из фактов данных: по одному из главных файлов истории.")
        body_n = len([e for e in entries if e.role != "appendix"])
        entries.insert(body_n, _Entry(summary, "summary", keep=95))

    slides = [e.slide for e in entries]
    outline = DeckOutline(title=title, subtitle=subtitle, audience=brief.audience if brief is not None else None, purpose="report", strategy="structured", language=(brief.language if brief is not None else "ru") or "ru", planned_by="rules", slides=slides)
    story.outline = outline

    # the model writes the connecting text; every figure it writes is checked
    if use_llm and skills is not None and providers is not None and _has_llm(providers):
        _tell(story, brief, voice, skills, providers, deadline=deadline, limit=limit)

    _say_designs(voice, outline)
    outline.agent_log = list(voice.lines) + list(outline.agent_log)
    story.log = list(voice.lines)
    story.seconds = time.monotonic() - t0
    return story


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


def _tell(story: DataStory, brief: Optional[Brief], voice: _Voice, skills: Any, providers: Any, *, deadline: Optional[float], limit: Optional[int] = None) -> None:
    """One call of `data_storyteller`; what it wrote replaces the deterministic wording where the checks pass."""
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

    source = _Attribution(data_slides)

    def framed(x: str) -> tuple[bool, str]:
        """The title's and the subtitle's numbers: the brief's, or one data slide's when the line names its subject."""
        if _numbers_from(x, brief_nums):
            return True, ""
        ok, why = source.free_or_attributed(x)
        return ok, "" if ok else f"{why} и не из текста"

    # the title and the subtitle
    t = clean(w.title, MAX_TITLE)
    if t and t != o.title:
        ok, why = framed(t)
        note("title", "title", o.title, t, ok, why)
        if ok:
            o.title = t
            o.slides[0].headline = t
            used = True
    st = clean(w.subtitle, MAX_TITLE + 30)
    if st and st != (o.subtitle or ""):
        ok, why = framed(st)
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
        bad = bad_numbers(new, s, years=brief_years)
        ok = not bad
        why = ""
        if not ok:
            why = "число " + ", ".join(_num(n) for n in bad[:3]) + " не из фактов данных"
        elif new.lower() == (s.data.plain_headline or "").lower():
            ok, why = False, "это тема, а не вывод"
        elif is_description(new) and not is_description(s.headline):
            ok, why = False, "это описание чисел, а не вывод"
        note("headline", s.id, s.headline, new, ok, why)
        if ok:
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
        cards = [(it, _item_slide(it, data_slides, summary_slides)) for it in summary.content.items]
        lines = [clean(x, MAX_LINE) for x in w.summary][:3]
        taken: set[str] = set()
        for x in [x for x in lines if x]:
            src, why = source.of(x)
            slot = next((it for it, sl in cards if sl is not None and src is not None and sl.id == src.id and sl.id not in taken), None)
            if src is not None and slot is None:
                src, why = None, "о файле, которого нет среди выводов итога"
            if src is not None and is_description(x):
                src, why = None, "это описание чисел, а не вывод"
            note("summary", "summary", "", x, src is not None, why)
            if src is not None and slot is not None:
                slot.text = x  # one for one: the conclusion of the same slide, the others stay
                taken.add(src.id)
                used = True
        sh = clean(w.summary_title, MAX_HEADLINE)
        if sh and sh != summary.headline:
            ok, why = source.free_or_attributed(sh)
            # the summary's headline says what its cards back: a subject of no card («…опережает рост клиентской базы»
            # over cards about revenue, regions and channels) is refused
            backs = {sl.id for _, sl in cards if sl is not None}
            named = source.subjects(sh)
            texts = [x for it in summary.content.items for x in (it.title or "", it.text or "")]
            if ok and ((named and not named <= backs) or source.unbacked(sh, backs, texts)):
                ok, why = False, "заголовок итога говорит о том, чего нет в его карточках"
            note("summary_title", "summary", summary.headline, sh, ok, why)
            if ok:
                summary.headline = sh
                used = True
    steps = [clean(x, MAX_LINE) for x in w.next_steps][:3]
    steps = [x for x in steps if x]
    good_steps = []
    explained = _explained(story.notes)
    for x in steps:
        ok, why = source.free_or_attributed(x)
        if ok and explained and _asks_why_missing(x):
            ok, why = False, "это объясняют сами файлы: " + explained
        note("next_step", "next", "", x, ok, why)
        if ok:
            good_steps.append(x)
    if len(good_steps) >= 2 and (limit is None or len(o.slides) < limit):
        at = next((k + 1 for k, s in enumerate(o.slides) if s.id == "summary"), len(o.slides))
        o.slides.insert(at, OutlineSlide(id="next-steps", kind=PatternKind.bullets, headline="Что дальше", content=SlideContent(bullets=good_steps), rationale="Следующие шаги по выводам данных — сформулированы моделью, без новых чисел."))
        used = True

    # the context: the brief's numbers only
    if context:
        lines = [clean(x, MAX_LINE) for x in w.context][: CONTEXT_LINES * len(context)]
        lines = [x if x.endswith((".", "!", "?", "…")) else x + "." for x in lines if x]
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
        s.takeaway = (plan.caption or None) if j == len(kept) - 1 else None
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
_PAIR_RE = re.compile(r"^\s*[^—:,;]{1,60}\s*[—:]\s*[+\-−–]?\d[^,;]*$")


def is_description(text: str) -> bool:
    """«Медиана стипендии — 3 590 ₽, среднее — 5 740 ₽»: the line only lists values against names — no verb, no
    comparison — a description of the numbers, not a conclusion about them."""
    t = " ".join((text or "").split())
    if not t or _CLAIM_RE.search(t):
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


class _Attribution:
    """Which data slide a sentence of the model speaks of. Each slide's own subject — the words of its topic, file
    name and labels (categories, series, row names, cards) that no other data slide has («месяц», «сен» for the revenue
    line; «регион», «Москва», «Казань» for the regions); verbs and the words of the facts are no subject. A sentence
    belongs to a slide when the slide's facts hold every number of it, it names that slide's own subject and no other
    slide's, and a number tied to a category («Москва — 41%») is said of that category, not of another («Казань
    выросла на 41%»). The slide's own headline, said again, belongs to it."""

    def __init__(self, slides: Sequence[OutlineSlide]) -> None:
        self.slides = [s for s in slides if s.data is not None]
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
        if not data_text_ok(line, s):
            return None, "числа не из фактов того файла, о котором говорит вывод"
        # a number of a fact about one category, said of another («Казань выросла на 41%», where 41% is Moscow's)
        low_line = line.lower()
        cats = [c for c in self.cats[s.id] if c and c.lower() in low_line]
        if cats:
            from verstka.data.headline import _matches

            for n in numbers_in(_without_years(line, data_years(s)), self.labels[s.id]):
                hits = [f for f in s.data.headline_facts if _matches(n, f.value)]
                if hits and not any(c.lower() in (f.text or "").lower() for f in hits for c in cats):
                    return None, f"число {_num(n)} в данных относится к другой категории"
        return s, ""

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
        if usage:
            rm["usage"] = _merge_usage(usage, rm.get("usage") or {})
        extra = rm.get("extra") if isinstance(rm.get("extra"), dict) else None
        if extra is not None and isinstance(extra.get("planner"), dict):
            extra["planner"] = planner
        path.write_text(json.dumps(rm, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_dir is not None:
        story.save(Path(out_dir) / STORY_FILE)
