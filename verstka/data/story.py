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
from verstka.data.words import count_words, fmt_signed, fmt_value, stems_of, upper_first
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
    head = plan.headline or plan.plain_headline
    if part > 1:
        head = f"{head.rstrip('. ')} (продолжение)"
    return OutlineSlide(
        id=slide_id,
        kind=_kind_of(body),
        headline=head,
        content=_content_of(body),
        takeaway=(plan.caption or None) if part >= total else None,
        footnote=plan.source or None,
        rationale=_rationale(plan),
        alternatives=_alternatives(plan),
        notes=_notes(plan) if part == 1 else "",
        data=slide_data_of(plan, part).model_copy(update={"prepared": prepared_of(body)}),
    )


def prepared_of(body: Any) -> PreparedValues:
    """What the slide shows, as the data layer prepared it from the file (the audit's reference)."""
    if isinstance(body, ChartSpec):
        cats = [str(c) for c in body.categories]
        series = [(x.name or "", [None if v is None else float(v) for v in x.values]) for x in body.series]
        points = [(x.name or "", [(float(a), float(b)) for a, b in zip(x.x, x.y)]) for x in body.xy]
        return PreparedValues(categories=cats, series=series, points=points)
    if isinstance(body, TableData):
        return PreparedValues(columns=list(body.columns), rows=[[str(c) for c in r] for r in body.rows])
    return PreparedValues(numbers=[n.value for n in body])


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


def _summary_lines(plans: Sequence[DatasetPlan], order: Sequence[int]) -> list[tuple[str, str]]:
    """(topic, conclusion) of the first three datasets of the story: the goals' first."""
    out = []
    for k in order:
        p = plans[k]
        if p.slides <= 0 or not p.headline or p.headline == p.plain_headline:
            continue
        out.append((p.plain_headline or p.profile.file, p.headline))
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
    story = DataStory(outline=DeckOutline(title=""), plans=plans, files=files, dataset_ids=ids)

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
    lines = _summary_lines(plans, sorted(kept, key=lambda k: (0 if plans[k].task.goal else 1, order.index(k))))
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

    # the conclusions: each against its own dataset's facts (and the data's own names)
    by_id = {h.id: h.headline for h in w.headlines}
    for s in data_slides:
        new = clean(by_id.get(s.id, ""), MAX_HEADLINE)
        if not new or new == s.headline:
            continue
        labels = data_slide_labels(s)
        ok = headline_ok(new, s.data.headline_facts, labels)
        why = ""
        if not ok:
            bad = [n for n in numbers_in(new, labels) if not any(abs(n - abs(f.value)) < 1e-9 or abs(round(abs(f.value), d) - n) < 1e-9 for f in s.data.headline_facts for d in (0, 1, 2))]
            why = "число " + ", ".join(_num(n) for n in bad[:3]) + " не из фактов данных" if bad else "число не из фактов данных"
        elif new.lower() == (s.data.plain_headline or "").lower():
            ok, why = False, "это тема, а не вывод"
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
            used = True

    # the summary and the next steps: a line with numbers speaks of ONE data slide — its facts hold every number and
    # the line names that slide's own subject; true numbers recombined across slides («Выручка выросла на 41%», where
    # 41% is Moscow's share) are refused
    if summary is not None:
        lines = [clean(x, MAX_LINE) for x in w.summary][:3]
        lines = [x for x in lines if x]
        if lines:
            good: list[tuple[str, OutlineSlide]] = []
            for x in lines:
                src, why = source.of(x)
                note("summary", "summary", "", x, src is not None, why)
                if src is not None and all(src is not g[1] for g in good):
                    good.append((x, src))
            if len(good) == len(summary.content.items) or len(good) >= 2:
                summary.content.items = [SlideItem(title=src.data.plain_headline or src.data.file, text=x) for x, src in good]
                summary.headline = _COUNT_WORD.get(len(good), "Главные выводы")
                used = True
        sh = clean(w.summary_title, MAX_HEADLINE)
        if sh and sh != summary.headline:
            ok, why = source.free_or_attributed(sh)
            note("summary_title", "summary", summary.headline, sh, ok, why)
            if ok:
                summary.headline = sh
                used = True
    steps = [clean(x, MAX_LINE) for x in w.next_steps][:3]
    steps = [x for x in steps if x]
    good_steps = []
    for x in steps:
        ok, why = source.free_or_attributed(x)
        note("next_step", "next", "", x, ok, why)
        if ok:
            good_steps.append(x)
    if good_steps and (limit is None or len(o.slides) < limit):
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


class _Attribution:
    """Which data slide a sentence of the model speaks of. Each slide's subject — the words of its topic, headline,
    labels (categories, series, axes, row names) and facts that no other data slide of the deck has («месяц»,
    «сентябрь» for the revenue line; «регион», «Москва», «Казань» for the regions) — and its facts. A sentence belongs
    to the slide whose facts hold every number of it and whose own subject it names; its own headline, said again,
    belongs to it whatever it names."""

    def __init__(self, slides: Sequence[OutlineSlide]) -> None:
        self.slides = [s for s in slides if s.data is not None]
        self.labels = {s.id: data_slide_labels(s) for s in self.slides}
        vocab = {}
        for s in self.slides:
            text = " ".join([s.data.plain_headline, s.headline, *self.labels[s.id], *(f.text for f in s.data.headline_facts)])
            vocab[s.id] = {w for w in stems_of(text) if not w.isdigit()}
        self.own = {s.id: vocab[s.id] - set().union(*(vocab[o.id] for o in self.slides if o is not s)) for s in self.slides}
        self.all_labels = [x for v in self.labels.values() for x in v]

    def of(self, line: str) -> tuple[Optional[OutlineSlide], str]:
        """(the slide the line speaks of, or None with why not)."""
        low = " ".join(line.lower().split()).rstrip(".")
        for s in self.slides:
            if low == " ".join(s.headline.lower().split()).rstrip("."):
                return s, ""
        words = {w for w in stems_of(line) if not w.isdigit()}
        fits = [s for s in self.slides if headline_ok(line, s.data.headline_facts, self.labels[s.id])]
        named = [(len(words & self.own[s.id]), k, s) for k, s in enumerate(fits) if words & self.own[s.id]]
        if named:
            return max(named, key=lambda t: (t[0], -t[1]))[2], ""
        if not numbers_in(line, self.all_labels):
            return None, "не видно, о каких данных вывод"
        return None, "числа не из фактов того файла, о котором говорит вывод" if fits else "число не из фактов данных"

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
