"""The planning agent (Agent v2): brief → one designed DeckOutline per variant.

    analyst ──► [deck_architect, when the brief does not describe its slides] ──► slide_designer × slide (parallel)
            ──► variants (structured / visual / compact from the designs and their alternatives)
            ──► design_critic × variant ──► slide_designer again on the flagged slides (one round)
            ──► compiler (planning/compile.py) ──► grounding ──► a DeckOutline per variant

- Analyst: planning/brief_structure.py (the slides the user dictated, their requests, rules and data).
- Architect: one call that turns a brief without slide specs into a storyline — the brief's sentences (by number)
  and data ids per slide. No model or a failed call: the agent gives up (run_agent → None) and the caller plans the
  deck as before (plan_outline / basic_outline).
- Designer: one call per slide, in parallel, bounded by the providers' concurrency. It writes the slide (headline as
  a conclusion, takeaway, notes, short bullets), chooses its form, puts chart data inline, and returns why and two
  alternative forms the other variants use. The user's explicit requests for the slide (chart type, table, formula,
  footnote, «Вывод») are enforced after the answer. A slide the model did not design (no model, an error, the
  deadline) is built deterministically from its SlideSpec: requested charts from its series, the table, the
  formula, figures as stat_row / big_number, lists as cards / timeline / bullets.
- Variants share the designs: structured takes the primary forms, visual the alternatives that show more (charts,
  figures), compact the denser ones and merges thin neighbours when the user did not fix the slide count. A slide
  whose form the user asked for keeps it in every variant. No two neighbours of one kind when an alternative fits.
- Critic: one call per variant, skipped when the deadline is near; next to it the agent's own check (slide_gaps: the
  lists, the key figures, the takeaway the brief asks for, a headline without its figure); the designer revises only
  the flagged slides, and a revision is taken part by part (merge_revision).
- Editor's pass, deterministic: a line repeating the chart, the takeaway, the headline or the footnote goes, a takeaway
  that restates the headline or claims a cause the brief does not state goes, notes say only what the source says,
  steps are titled one way (tidy_design, clean_notes); after the revisions every slide the user described shows its
  key figures and, when the brief asks for it, a takeaway from the brief's own sentences (complete_slide).
- Compiler: planning/compile.py `compile_outline(outline, structure, brief) -> (DeckOutline, warnings)` (inline
  chart data → registry series, spec slides kept, the user's slide count); a minimal built-in step when it is not
  there. Then grounding.ground_outline (every figure from the brief) and outline.polish_plan.

Every step reports to `progress` as {"type": "agent", "step": "analyst" | "architect" | "designer" | "critic" |
"revise" | "compile", "message": "<plain Russian>", "slide": int | None, "variant": str | None}; the same messages
go to DeckOutline.agent_log (the common ones and the variant's own).

The whole agent spends the generation's model budget (the providers' deadline, limits.time_budget_s): the designer
phase leaves room for the critic when there is enough of it, the critic is skipped when there is not, and a model
step that cannot start any more is taken deterministically. Prompts are model-agnostic and each answer is small
(one slide, one storyline, one list of issues)."""

from __future__ import annotations

import inspect
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union

import yaml

from verstka.planning import heuristics as H
from verstka.planning.plan_json import kind_by_content
from verstka.planning.strategies import Strategy, default_strategies_path
from verstka.ru import ru_count
from verstka.schemas.agent import Alternative, CritiqueAnswer, SlideDesignAnswer, StorylineAnswer, number_of
from verstka.schemas.brief_structure import BriefStructure, SlideSpec
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import (
    Brief, ChartSpec, DeckOutline, Fact, FactsExtraction, InlineSeries, NumberCallout, OutlineSlide, Series, SlideAlternative, SlideContent,
    SlideItem, TableData,
)
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)

AGENT_NAME = "deck_designer"
AGENT_VERSION = "2.2.0"
EventFn = Callable[[dict], None]
FactsSource = Union[FactsExtraction, tuple, Callable[[], Any], None]

FRAME_KINDS = {"title", "section", "agenda", "thanks"}
MAX_BULLETS = 6
MAX_ITEMS = 8
MAX_NUMBERS = 5
MAX_TABLE_ROWS = 8
MAX_TABLE_COLS = 5
MAX_CONTENT_SLIDES = 12  # a brief without a slide count: at most this many content slides
MIN_CALL_S = 12.0  # less model time than this left: the step is taken deterministically
CRITIC_MIN_S = 45.0  # the critic and one revision need at least this much of the budget
REVISE_MIN_S = 15.0
CRITIC_RESERVE_S = 60.0  # the designer phase leaves this much for the critic when the budget allows it
ARCHITECT_MAX_S = 75.0
ANALYST_MAX_S = 30.0
CALL_MARGIN = 1.2  # a model step starts only with this many times the calls' observed time (median) left
CRITIC_BRIEF_CHARS = 6000  # the brief the critic reads is cut here (the plan and the requests carry the rest)
TAKEAWAY_FIX = "\x00takeaway:"  # a critic's note the agent acts on itself (the takeaway repeats the headline)
BREAKER_STREAK = 3  # this many model failures in a row (or a whole first wave): the model is not answering
SKILLS = ("slide_designer", "deck_architect", "design_critic")

# the forms in the timeline's words, as the interface's tabs name them («Ряд чисел», «Хронология», «Большое число»)
_KIND_RU = {
    "title": "обложка", "section": "разделитель", "agenda": "повестка", "bullets": "список", "cards": "карточки",
    "two_column": "две колонки", "comparison": "сравнение", "process": "процесс", "timeline": "хронология",
    "big_number": "большое число", "stat_row": "ряд чисел", "table": "таблица", "chart": "диаграмма",
    "quote": "цитата", "thanks": "финальный слайд", "image_text": "картинка и текст", "team": "команда",
}
_CHART_RU = {
    "pie": "круговая диаграмма", "doughnut": "кольцевая диаграмма", "column": "столбчатая диаграмма",
    "bar": "горизонтальная диаграмма", "line": "линейный график", "area": "диаграмма с областями",
}
_WHY = {
    "pie": "Доли одного целого лучше всего видны на круговой диаграмме.",
    "doughnut": "Доли одного целого лучше всего видны на кольцевой диаграмме.",
    "line": "Изменение по периодам читается по линии графика.",
    "column": "Сравнение значений нагляднее столбцами.",
    "bar": "Сравнение значений с длинными подписями нагляднее горизонтальными столбцами.",
    "area": "Изменение по периодам читается по линии графика.",
    "stat_row": "Несколько ключевых чисел — крупно в один ряд.",
    "big_number": "Одна главная цифра — крупно.",
    "table": "Сравнение по нескольким показателям — в таблице.",
    "cards": "Параллельные идеи — отдельными карточками.",
    "timeline": "План по шагам — на шкале времени.",
    "process": "Шаги по порядку — схемой процесса.",
    "two_column": "Две стороны вопроса — в две колонки.",
    "comparison": "Варианты рядом — в сравнении.",
    "bullets": "Текст, который не выразить числами, — коротким списком.",
    "quote": "Слова из брифа — цитатой.",
    "title": "Обложка: название и подзаголовок из брифа.",
    "thanks": "Финальный слайд.",
    "section": "Разделитель раздела.",
}
_ALT_WHY = {
    "chart": "данные нагляднее на диаграмме", "stat_row": "ключевые числа крупно", "big_number": "одна главная цифра крупно",
    "cards": "тезисы карточками", "timeline": "шаги на шкале времени", "process": "шаги по порядку", "table": "плотнее: всё в одной таблице",
    "two_column": "две колонки рядом", "comparison": "варианты рядом", "bullets": "короткий список",
}
_VISUAL_ORDER = ("chart", "stat_row", "big_number", "timeline", "process", "cards")
_COMPACT_ORDER = ("table", "two_column", "bullets", "stat_row", "comparison")


# ------------------------------------------------------------------ budget, events


class _Clock:
    """The generation's model deadline (time.monotonic()): the providers' own (ProviderRegistry.with_deadline), else
    now + limits.time_budget_s; no deadline without providers."""

    def __init__(self, providers: Any = None, deadline: Optional[float] = None) -> None:
        self.deadline = deadline
        if self.deadline is None and providers is not None:
            d = None
            try:
                d = getattr(providers.get("llm"), "deadline", None)
            except Exception:  # noqa: BLE001 - no llm role: no model steps anyway
                d = None
            if isinstance(d, (int, float)) and not isinstance(d, bool):
                self.deadline = float(d)
            else:
                self.deadline = time.monotonic() + float(getattr(getattr(providers, "limits", None), "time_budget_s", 210.0))

    def left(self) -> float:
        return math.inf if self.deadline is None else self.deadline - time.monotonic()

    def at(self, seconds_before_end: float) -> Optional[float]:
        return None if self.deadline is None else self.deadline - seconds_before_end


STEP_RU = {"writer": "Автор", "analyst": "Аналитик", "architect": "Архитектор", "designer": "Дизайнер", "critic": "Критик", "revise": "Правка", "compile": "Сборка"}
# «Дизайнер: …», «Критик («Структурный»): …» — the step's name in front of a message
_STEP_PREFIX_RE = re.compile(r"^(?:Автор|Аналитик|Архитектор|Дизайнер|Критик|Правка|Сборка|Вёрстка)(?:\s*\([^)]*\))?\s*:\s*")
# «слайд 3 «…» — …», «Слайд 3: …» — the slide's number in front of an event that carries it as `slide`
_SLIDE_LEAD_RE = re.compile(r"^слайд\s*\d+\s*(?:[—–:.\-]\s*)?", re.I)


def log_line(step: str, message: str) -> str:
    """A line of DeckOutline.agent_log: «Аналитик: …» (the step's name in front, once)."""
    message = str(message).strip()
    return message if _STEP_PREFIX_RE.match(message) else f"{STEP_RU.get(step, step.capitalize())}: {message}"


def event_message(message: str, slide: Optional[int]) -> str:
    """The event's text as the timeline shows it under its step (and the slide as a badge): no step name in front,
    no «слайд N» in front when the event carries the slide."""
    text = _STEP_PREFIX_RE.sub("", str(message).strip(), count=1)
    if slide is not None:
        text = _SLIDE_LEAD_RE.sub("", text, count=1)
    text = text.strip()
    return (text[:1].upper() + text[1:]) if text and text[0].islower() else (text or str(message))


class _Tracker:
    """Progress events of the agent (the contract above) and the log each variant's DeckOutline.agent_log gets. The
    log line names the step («Критик: …»); the event does not — the timeline shows it under its step."""

    def __init__(self, progress: Optional[EventFn]) -> None:
        self.progress = progress
        self.entries: list[tuple[Optional[str], str]] = []
        self.lock = threading.Lock()

    def emit(self, step: str, message: str, slide: Optional[int] = None, variant: Optional[str] = None) -> None:
        self.forward({"type": "agent", "step": step, "message": message, "slide": slide, "variant": variant})

    def forward(self, ev: dict) -> None:
        if not isinstance(ev, dict) or not ev.get("message"):
            return
        step = ev.get("step") or "analyst"
        slide = ev.get("slide") if isinstance(ev.get("slide"), int) and not isinstance(ev.get("slide"), bool) else None
        with self.lock:
            self.entries.append((ev.get("variant"), log_line(step, ev["message"])))
        self.relay({**ev, "step": step, "slide": slide})

    def relay(self, ev: dict) -> None:
        """An event to the listener only (the compiler keeps its own log lines)."""
        if not isinstance(ev, dict) or not ev.get("message"):
            return
        step = ev.get("step") or "compile"
        slide = ev.get("slide") if isinstance(ev.get("slide"), int) and not isinstance(ev.get("slide"), bool) else None
        out = {"type": "agent", "step": step, "message": event_message(ev["message"], slide), "slide": slide, "variant": ev.get("variant")}
        log.info("agent %s: %s", step, out["message"])
        if self.progress is None:
            return
        try:
            self.progress(out)
        except Exception:  # noqa: BLE001 - a broken listener must not stop the plan
            log.debug("agent progress listener failed", exc_info=True)

    def log_for(self, variant: str) -> list[str]:
        with self.lock:
            return [m for v, m in self.entries if v is None or v == variant]


def _keep_raw(raw: Optional[list], step: str, key: Optional[str], res: Any = None, error: Optional[BaseException] = None, variant: Optional[str] = None) -> None:
    """A model answer as written (or why there is none), for planner_raw.json of the run."""
    if raw is None:
        return
    entry: dict[str, Any] = {"step": step}
    if key:
        entry["slide"] = key
    if variant:
        entry["variant"] = variant
    if res is not None:
        entry.update({"model": getattr(res, "model", None), "label": getattr(res, "label", None), "text": getattr(res, "text", None)})
    else:
        from verstka.providers.status import mask

        entry["error"] = mask(str(error))[:2000]
    raw.append(entry)


# ------------------------------------------------------------------ strategies' preferences (configs/strategies.yaml)


def designer_prefs(path: Optional[Path | str] = None) -> dict[str, dict]:
    """Each strategy's `designer` block of configs/strategies.yaml: which forms the variant prefers (`prefer`, best
    first), which primary forms it may leave for an alternative (`switch_from`), whether it merges thin neighbours
    (`merge_thin`) and may use section dividers (`sections`), and a hint for the designer (`hint`)."""
    p = Path(path) if path else default_strategies_path()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {name: dict((cfg or {}).get("designer") or {}) for name, cfg in data.items() if isinstance(cfg, dict)}


# ------------------------------------------------------------------ analyst, compiler (other modules, guarded)


def analyse_brief(
    brief: Brief,
    skills: Any = None,
    providers: Any = None,
    deadline: Optional[float] = None,
    progress: Optional[EventFn] = None,
) -> tuple[BriefStructure, list[str]]:
    """The analyst: planning/brief_structure.py — read_structure (rules) and enrich_with_model (data_extractor per
    block). Never raises: without the module, or when it fails, the structure is empty (no slide specs) and the
    warning says why."""
    warnings: list[str] = []
    try:
        from verstka.planning import brief_structure as bs
    except Exception as e:  # noqa: BLE001 - the analyst is another module: the agent still plans without it
        return BriefStructure(), [f"analyst unavailable, the brief is read as a whole: {str(e)[:160]}"]
    read = getattr(bs, "read_structure", None)
    if not callable(read):
        return BriefStructure(), ["analyst unavailable (no read_structure), the brief is read as a whole"]
    try:
        st = read(brief.text)
    except Exception as e:  # noqa: BLE001
        log.warning("analyst failed on the brief", exc_info=True)
        return BriefStructure(), [f"analyst failed, the brief is read as a whole: {str(e)[:160]}"]
    enrich = getattr(bs, "enrich_with_model", None)
    if callable(enrich) and skills is not None and providers is not None:
        try:
            kwargs: dict[str, Any] = {}
            params = inspect.signature(enrich).parameters
            if "deadline" in params:
                kwargs["deadline"] = deadline
            if "progress" in params:
                kwargs["progress"] = progress
            if "warnings" in params:
                kwargs["warnings"] = warnings
            st = enrich(st, brief.text, skills, providers, **kwargs) or st
        except Exception as e:  # noqa: BLE001 - the rules' structure stands
            warnings.append(f"analyst: data_extractor per block failed, the rules' reading is used: {str(e)[:160]}")
    return st, warnings


def describe_structure(st: BriefStructure) -> str:
    try:
        from verstka.planning.brief_structure import describe

        return describe(st)
    except Exception:  # noqa: BLE001
        parts = [ru_count(len(st.specs), "слайд", "слайда", "слайдов")] if st.specs else []
        parts.append(ru_count(len(st.series), "ряд данных", "ряда данных", "рядов данных"))
        return "Нашёл в брифе " + ", ".join(parts)


def _compiler() -> Optional[Callable]:
    try:
        from verstka.planning.compile import compile_outline
    except Exception:  # noqa: BLE001 - not written yet, or broken: the built-in step
        return None
    return compile_outline


def _call_compiler(fn: Callable, o: DeckOutline, structure: BriefStructure, brief: Brief, progress: Optional[EventFn]) -> tuple[DeckOutline, list[str]]:
    try:
        takes_progress = "progress" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        takes_progress = False
    return fn(o, structure, brief, progress=progress) if takes_progress else fn(o, structure, brief)


def basic_compile(outline: DeckOutline, structure: BriefStructure, brief: Brief) -> tuple[DeckOutline, list[str]]:
    """The minimal compile step (used when planning/compile.py is not there or fails): inline chart data → registry
    series `s_<slide>_<n>` with the chart's series_ids, the title and subtitle from the brief's structure, the
    disclaimer as the cover's footnote."""
    o = outline.model_copy(deep=True)
    taken = {s.id for s in o.series}
    for s in o.slides:
        n = 0
        for ch in (s.content.chart, s.content.chart2):
            if ch is None or not ch.series or ch.series_ids:
                continue
            ids = []
            for sr in ch.series:
                n += 1
                sid = f"s_{s.id}_{n}"
                while sid in taken:
                    n += 1
                    sid = f"s_{s.id}_{n}"
                taken.add(sid)
                o.series.append(Series(id=sid, name=sr.name or ch.title or s.headline, categories=list(ch.categories), values=list(sr.values), unit=ch.unit))
                ids.append(sid)
            ch.series_ids = ids
    if structure.title:
        o.title = structure.title
    if structure.subtitle:
        o.subtitle = structure.subtitle
    cover = o.slides[0] if o.slides and o.slides[0].kind == PatternKind.title else None
    if cover is not None:
        cover.headline = o.title or cover.headline
        if o.subtitle:
            cover.subtitle = o.subtitle
        if structure.disclaimer and not cover.footnote:
            cover.footnote = structure.disclaimer
    return o, []


# ------------------------------------------------------------------ data of the deck


_FIG_RE = re.compile(r"(?<![\w.,])\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?!\d)|(?<![\w.,])\d+(?:[.,]\d+)?")


def figures(text: str) -> list[float]:
    out = []
    for m in _FIG_RE.finditer(text or ""):
        v = number_of(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _fmt(v: float) -> str:
    """A value for the prompt and for JSON: 315000, 13.3 — plain, so the model copies it as a number."""
    return str(int(v)) if abs(v - round(v)) < 1e-9 else f"{v:g}"


def _fmt_ru(v: float, unit: Optional[str] = None) -> str:
    n = H.fmt_number(v) if abs(v - round(v)) < 1e-9 else f"{v:g}".replace(".", ",")
    if not unit:
        return n
    return f"{n}%" if unit.strip() == "%" else f"{n} {unit.strip()}"


@dataclass
class _Ctx:
    brief: Brief
    structure: BriefStructure
    series: dict[str, Series]
    tables: dict[str, TableData]
    table_index: dict[int, str]  # BriefStructure.tables index → table id in prompts ("t1")
    facts: dict[str, Fact]
    allowed: list[float]
    title: str
    kinds: str
    rules: str
    count: Optional[int]
    index: Any = None  # grounding's BriefIndex of the brief, built on first use (_headline_checked)
    takeaway_rule: bool = False  # the brief asks for a conclusion on every slide («…содержательный заголовок и короткий вывод»)
    unit_index: dict = field(default_factory=dict)  # unit key → grounding's index of that slide's own source (and the brief's frame)
    lock: Any = field(default_factory=threading.Lock)
    written: bool = False  # the brief is the writer's text (planning/writer.py): a year is never a slide's key figure


def _dupe_series(a: Series, b: Series) -> bool:
    return a.values == b.values and [c.lower() for c in a.categories] == [c.lower() for c in b.categories]


def _dupe_table(a: TableData, b: TableData) -> bool:
    return a.columns == b.columns and a.rows == b.rows


def _build_ctx(brief: Brief, structure: BriefStructure, facts: FactsExtraction, manifest: Optional[TemplateManifest]) -> _Ctx:
    series: dict[str, Series] = {}
    for s in structure.series:
        series[s.id] = s
    for s in facts.series:
        if any(_dupe_series(s, x) for x in series.values()):
            continue
        sid = s.id if s.id and s.id not in series else f"x{s.id or len(series) + 1}"
        series[sid] = s.model_copy(update={"id": sid})
    tables: dict[str, TableData] = {}
    index: dict[int, str] = {}
    for i, t in enumerate(structure.tables):
        tid = f"t{i + 1}"
        tables[tid] = t
        index[i] = tid
    for t in facts.tables:
        if not any(_dupe_table(t, x) for x in tables.values()):
            tables[f"t{len(tables) + 1}"] = t
    fdict = {f.id: f for f in facts.facts if f.id}
    for f in getattr(structure, "facts", None) or []:
        if isinstance(f, Fact) and f.id and f.id not in fdict:
            fdict[f.id] = f
    allowed = figures(brief.text)
    for s in series.values():
        allowed.extend(s.values)
    for t in tables.values():
        for row in t.rows:
            for cell in row:
                allowed.extend(figures(cell))
    for f in fdict.values():
        v = number_of(f.value)
        if v is not None:
            allowed.append(v)
    title = structure.title or brief.title_hint or ""
    if not title:
        first = next((ln.strip() for ln in brief.text.splitlines() if ln.strip()), "")
        title = H.strip_end((H.split_sentences(first) or [first])[0]) if first else "Презентация"
    rules = list(structure.rules)
    if structure.notes_rule and not any("заметк" in r.lower() for r in rules):
        rules.append("Подробности и пояснения расчётов — в заметки докладчика.")
    if structure.rounding and H.strip_end(structure.rounding) not in {H.strip_end(r) for r in rules}:
        rules.append(structure.rounding)
    ctx = _Ctx(
        brief=brief, structure=structure, series=series, tables=tables, table_index=index, facts=fdict,
        allowed=sorted(set(allowed)), title=title, kinds=_kinds_text(manifest), rules="\n".join(f"- {r}" for r in rules),
        count=structure.slide_count or brief.slide_count,
        takeaway_rule=takeaway_rule(structure, brief.text),
    )
    try:
        # grounding's index of the brief, built once here (not lazily from the designer's worker threads)
        from verstka.planning.grounding import BriefIndex

        ctx.index = BriefIndex.of(brief)
        use = getattr(ctx.index, "use_structure", None)
        if callable(use):
            use(structure)
    except Exception:  # noqa: BLE001 - the checks that need it are skipped; grounding checks the deck anyway
        ctx.index = None
    return ctx


# «На каждом слайде должен быть … короткий вывод», «Каждый слайд заканчивай выводом», «вывод на всех слайдах»
_TAKEAWAY_RULE_RE = re.compile(
    r"(?:кажд\w*|вс[еёи]\w*|любо\w*)\s+(?:\S+\s+){0,2}?слайд\w*[^.\n]{0,80}?(?:вывод|итог|takeaway)|"
    r"(?:вывод|итог)\w*[^.\n]{0,60}?(?:на|для|в)\s+(?:кажд\w*|вс[еёи]\w*)\s+(?:\S+\s+){0,1}?слайд|"
    r"every\s+slide[^.\n]{0,60}?(?:takeaway|conclusion)",
    re.I,
)


def takeaway_rule(structure: BriefStructure, text: str = "") -> bool:
    """The brief asks for a conclusion (a takeaway) on every slide."""
    return any(_TAKEAWAY_RULE_RE.search(r) for r in [*structure.rules, text or ""])


def _kinds_text(manifest: Optional[TemplateManifest]) -> str:
    most: dict[str, int] = {}
    if manifest is not None:
        for p in manifest.patterns:
            for g in p.repeat_groups:
                most[p.kind.value] = max(most.get(p.kind.value, 0), g.max_n)
    cards = min(6, most.get("cards") or 6)
    steps = min(6, most.get("process") or most.get("timeline") or 6)
    lines = [
        ("chart", "a chart: column, bar, line, pie or doughnut (data inline)"),
        ("stat_row", "2–4 key figures with short labels"),
        ("big_number", "one key figure with its label"),
        ("table", f"at most {MAX_TABLE_ROWS - 1} rows × {MAX_TABLE_COLS} columns"),
        ("cards", f"2–{cards} cards: a title of up to 5 words and a short text"),
        ("timeline", f"3–{steps} dated steps (months, weeks, stages)"),
        ("process", f"3–{steps} steps in order"),
        ("two_column", "2 columns, each a title and short bullets"),
        ("comparison", "2–3 options side by side"),
        ("bullets", f"a short list, at most {MAX_BULLETS} lines"),
    ]
    return "\n".join(f"- {k}: {d}" for k, d in lines)


def value_ok(v: float, allowed: list[float]) -> bool:
    """A chart value the brief supports: one of its figures, or one rounded (to thousands, to a decimal) or scaled
    (in thousands / millions). The strict check is grounding's; this one only keeps invented chart data out."""
    for a in allowed:
        if abs(v - a) <= 1e-6 * max(1.0, abs(a)):
            return True
        if abs(a) >= 1000 and (abs(v - a) <= 500 or abs(v * 1000 - a) <= 500):
            return True
        if abs(a) >= 1_000_000 and abs(v * 1_000_000 - a) <= 500_000:
            return True
        if abs(a) < 1000 and abs(v - a) <= 0.05 + 1e-9 and v != 0:
            return True
    return False


def _data_lines(ctx: _Ctx, series_ids: list[str], table_ids: list[str], fact_ids: list[str]) -> str:
    lines = []
    for sid in series_ids:
        s = ctx.series.get(sid)
        if s is None:
            continue
        pts = "; ".join(f"{c} = {_fmt(v)}" for c, v in zip(s.categories, s.values))
        lines.append(f"- {sid} «{s.name}»{f' ({s.unit})' if s.unit else ''}: {pts}")
    for tid in table_ids:
        t = ctx.tables.get(tid)
        if t is None:
            continue
        rows = " / ".join(" | ".join(r) for r in t.rows[:MAX_TABLE_ROWS])
        cap = f" «{t.caption}»" if t.caption else ""
        lines.append(f"- {tid} table{cap}: columns {' | '.join(t.columns)}; rows: {rows}")
    for fid in fact_ids:
        f = ctx.facts.get(fid)
        if f is None:
            continue
        lines.append(f"- {fid} {f.label}: {f.value}{(' ' + f.unit) if f.unit and f.unit not in f.value else ''}")
    return "\n".join(lines) or "(no separate data: only the figures written in the source text)"


# ------------------------------------------------------------------ storyline units


@dataclass
class _Unit:
    """One slide of the storyline: a slide the user described, or one the architect made from the brief."""

    key: str
    title: str
    text: str = ""
    section: Optional[str] = None
    spec: Optional[SlideSpec] = None
    cover: bool = False
    closing: bool = False
    form: Optional[str] = None
    series_ids: list[str] = field(default_factory=list)
    table_ids: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)

    @property
    def frame(self) -> bool:
        return self.cover or self.closing

    @property
    def locked(self) -> bool:
        """The user asked for this slide's form (a chart, a table): every variant keeps it."""
        return self.frame or bool(self.spec is not None and (self.spec.charts or self.spec.table))


_COVER_RE = re.compile(r"титул|обложк|заглавн|\bcover\b|title slide", re.I)
_TITLE_LINE_RE = re.compile(r"^\s*(?:[—–\-•*]\s*)?(?:название|подзаголовок|заголовок|title|subtitle)\s*[:—–]", re.I | re.M)


def _is_cover(spec: SlideSpec, first: bool) -> bool:
    if not first:
        return False
    if _COVER_RE.search(spec.title or ""):
        return True
    return bool(_TITLE_LINE_RE.search(spec.text or "")) and not spec.charts and not spec.table


def _clean_fact(f: Fact) -> bool:
    """A figure worth listing: not a piece of a time («08:00» → 08, 00) or a lone digit."""
    digits = re.sub(r"\D", "", f.value or "")
    if not digits:
        return False
    if len(digits) <= 2 and re.search(rf"(?<!\d){re.escape(f.value.strip())}\s*:\s*\d\d|\d\d\s*:\s*{re.escape(f.value.strip())}(?!\d)", f.source_span or f.label or ""):
        return False
    return len(digits) > 1 or bool(f.unit)


def _facts_in(ctx: _Ctx, text: str, limit: int = 10) -> list[str]:
    vals = figures(text)
    out = []
    for fid, f in ctx.facts.items():
        if not _clean_fact(f):
            continue
        v = number_of(f.value)
        if v is not None and any(abs(v - x) <= 1e-6 * max(1.0, abs(x)) for x in vals):
            out.append(fid)
        if len(out) >= limit:
            break
    return out


def _units_from_specs(ctx: _Ctx) -> list[_Unit]:
    specs = sorted(ctx.structure.specs, key=lambda s: s.number)
    units: list[_Unit] = []
    for i, sp in enumerate(specs):
        sids = list(dict.fromkeys([*sp.series_ids, *(x for r in sp.charts for x in r.series_ids)]))
        tids = [ctx.table_index[j] for j in sp.table_ids if j in ctx.table_index]
        cover = _is_cover(sp, i == 0)
        # the slide's own text holds its figures: the facts registry (regex figures, times and all) would only add noise
        u = _Unit(
            key=f"u{sp.number}", title=ctx.title if cover else H.strip_end(sp.title or ""), text=sp.text or "", spec=sp, cover=cover,
            series_ids=[x for x in sids if x in ctx.series], table_ids=tids,
        )
        if not u.title:
            u.title = H.short((H.split_sentences(u.text) or [u.text or f"Слайд {sp.number}"])[0], 8)
        units.append(u)
    if not any(u.cover for u in units):
        units.insert(0, _Unit(key="u0", title=ctx.title, cover=True))
    return units


def numbered_sentences(text: str) -> list[str]:
    """The brief's sentences in order (a list line is a sentence of its own), for the architect's numbers."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or re.match(r"^\|?\s*:?-{2,}", line):
            continue
        out.extend(H.split_sentences(line) or [line])
    return out


# ------------------------------------------------------------------ designs


@dataclass
class _Design:
    unit: _Unit
    slide: OutlineSlide
    alternatives: list[Alternative] = field(default_factory=list)
    by: str = "rules"  # model | rules
    model: Optional[str] = None
    changes: list[str] = field(default_factory=list)  # what the agent changed in the answer (for the warnings)
    failure: Optional[str] = None  # why the model did not design it


_MARK_RE = re.compile(r"^\s*(?:[—–\-•*·]|\d{1,2}[.)])\s+")
_MONTH_RE = re.compile(r"^(?P<t>\d{1,2}\s*-?\s*(?:й|ый|ой|ий)?\s*(?:месяц|недел[яи]|квартал|этап|шаг|день)|(?:месяц|неделя|квартал|этап|шаг)\s+\d{1,2})\s*[—–:\-]\s*(?P<x>.+)$", re.I)
_ASK_RE = re.compile(
    r"^(?:покажи|нужн[аоы]|нужен|сделай|укажи|добавь|предложи|выдели|используй|отметь|подчеркни|не\s+(?:складывай|рассчитывай|представляй|перегружай|прибавляй)|"
    r"(?:финальный\s+|главный\s+|итоговый\s+)?вывод\s*:|разовые вложения показывай)",
    re.I,
)
_ASK_LEAD_RE = re.compile(r"^(?:добавь|предложи|выдели|покажи|укажи|используй|перечисли|сделай)\s+", re.I)
_SHOW_RE = re.compile(r"^(?:добавь|предложи|выдели|покажи|перечисли)\s", re.I)  # «show this list» (not «используй …»)
_FILLER_LABELS = {"то есть", "или", "из них", "а", "и", "это"}


@dataclass
class _Group:
    """A list of the source: its lead line («Меры:», «Добавь основные риски: …») and its items; `ask` when the user
    asked for it to be shown («Выдели …», «Покажи …», «Добавь …»)."""

    label: Optional[str]
    items: list[str]
    ask: bool = False

    @property
    def figure(self) -> bool:
        """Most items are figures with their labels («средний чек — 300 рублей», «100 покупок в день»)."""
        return sum(_figure_item(x) for x in self.items) * 2 > len(self.items)


@dataclass
class _Source:
    """A slide's source text read by lines: plain sentences, list groups (a lead line and its dash items), steps."""

    sentences: list[str] = field(default_factory=list)
    groups: list[_Group] = field(default_factory=list)
    steps: list[tuple[str, str]] = field(default_factory=list)
    asks: list[str] = field(default_factory=list)
    steps_label: Optional[str] = None  # the lead line of the steps («План на 6 месяцев:»)


_MONTHS_GEN = r"(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*"
# a date in front of an event («1 сентября 1939 года — …», «май 1945 — …», «1941–1945 гг. — …», «1991 год»)
_DATE_LEAD_RE = re.compile(
    rf"^(?:\d{{1,2}}\s+{_MONTHS_GEN}\s+\d{{4}}|{_MONTHS_GEN}\s+\d{{4}}|\d{{4}}(?:\s*[–—-]\s*\d{{4}})?)(?:\s*(?:год\w*|гг?\.?))?"
    r"(?=\s*(?:[—–:]|-\s|$))",
    re.I,
)


def _dated_event(x: str) -> Optional[tuple[str, str]]:
    """(date, event) of a list item that is a dated event with no figure of its own («1 сентября 1939 года — Германия
    нападает на Польшу»); None for anything else — a year with its value («2023 — 900 000 рублей») is a figure."""
    m = _DATE_LEAD_RE.match((x or "").strip())
    if not m:
        return None
    when = m.group(0).strip()
    what = re.sub(r"^\s*[—–:-]\s*", "", x.strip()[m.end():]).strip()
    if not what or figures(what):
        return None
    return H.strip_end(when), H.cap_first(H.strip_end(what))


def _dated_items(unit: "_Unit", src: "_Source") -> Optional[list[SlideItem]]:
    """A slide's dated list as timeline items (date → title, event → text): the analyst's items of the slide's spec
    when every one is dated, else a source list whose every item is a dated event; None when there is none (≥ 3)."""
    spec = unit.spec
    if spec is not None and len(spec.items) >= 3 and all(_DATE_LEAD_RE.match((it.title or "").strip()) and not figures(it.text or "") for it in spec.items):
        return [SlideItem(title=H.strip_end(it.title), text=H.cap_first(H.strip_end(it.text or ""))) for it in spec.items[:6]]
    for g in src.groups:
        ev = [_dated_event(x) for x in g.items]
        if len(ev) >= 3 and all(ev):
            return [SlideItem(title=w, text=t) for w, t in ev[:6]]  # type: ignore[misc]
    return None


def _date_callout(n: NumberCallout, any_year: bool = True, source: Optional[str] = None) -> bool:
    """A «key figure» that is a date: a day of a month («17» · «сентября СССР начал…»; «6 июня 1944»), a year read
    with its «году» («1939» · «году Германия…») and — `any_year` (the writer's text) — any year («1939 г»,
    «1941–1945»); with the `source`, a bare four-digit number is a year only when the source writes it as one («1213
    кораблей» is a count)."""
    v = " ".join((n.value or "").split())
    label = (n.label or "").strip()
    if re.match(r"^\d{1,2}$", v) and re.match(_MONTHS_GEN, label, re.I):
        return True
    if source is not None and re.match(rf"^\d{{1,2}}\s+{_MONTHS_GEN}\w*\s+\d{{4}}", v, re.I):
        return True
    m = re.match(r"^(\d{4})(?:\s*[–—-]\s*(\d{4}))?\s*(г\.?|гг\.?|год\w*)?$", v, re.I)
    if not (m and 1000 <= int(m.group(1)) <= 2100):
        return False
    if source is not None and not m.group(2) and not m.group(3) and not re.match(r"^(?:год\w*|гг?\.)(?![\wё])", label, re.I):
        y = m.group(1)
        return bool(re.search(rf"(?:(?<![\wё])(?:в|с|до|по|к|на)\s+(?:\d{{1,2}}\s+\w+\s+)?{y}|{y}\s*(?:год|г\.|гг))", source, re.I))
    return any_year or bool(m.group(3)) or bool(re.match(r"^(?:год\w*|гг?\.)(?![\wё])", label, re.I))


def _figure_item(x: str) -> bool:
    """A list item that is a figure with its label, not a statement with a figure in it: «100 покупок в день»,
    «средний чек — 300 рублей», «доля вернувшихся — 25%»; not «Добавить комбо за 390 рублей», not a dated event
    («1 сентября 1939 года — Германия нападает на Польшу»)."""
    if not figures(x):
        return False
    if _dated_event(x) is not None:
        return False
    if re.match(r"^[+\-−]?\d", x):
        return True
    return bool(re.search(r"(?:[—–]|:(?!\d))\s*(?:около\s+|примерно\s+|до\s+)?\d", x))


def _label(text: str) -> str:
    return H.cap_first(_ASK_LEAD_RE.sub("", H.strip_end(text)))


def _read_source(text: str) -> _Source:
    src = _Source()
    label: Optional[str] = None
    ask = False
    items: list[str] = []

    def close() -> None:
        nonlocal label, items, ask
        if items:
            src.groups.append(_Group(label=_label(label) if label else None, items=items, ask=ask))
        label, items, ask = None, [], False

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            close()
            continue
        if _MARK_RE.match(line):
            body = H.strip_end(_MARK_RE.sub("", line, count=1))
            m = _MONTH_RE.match(body)
            if m:
                src.steps.append((H.strip_end(m.group("t")), H.cap_first(H.strip_end(m.group("x")))))
            elif body:
                items.append(H.cap_first(body))
            continue
        m = _MONTH_RE.match(line)
        if m:
            if label and not items and not src.steps:
                src.steps_label = _label(label)
            close()
            src.steps.append((H.strip_end(m.group("t")), H.cap_first(H.strip_end(m.group("x")))))
            continue
        close()
        if line.endswith(":"):
            label = line
            ask = bool(_SHOW_RE.match(line))
            continue
        if _ASK_RE.match(line):
            src.asks.append(line)
            parts = H.label_split(line)
            if parts and not re.match(r"^(?:покажи\s+формул|нужн|сделай|укажи|отметь|подчеркни|не\s|(?:финальный\s+|главный\s+|итоговый\s+)?вывод)", line, re.I):
                enum = _enum_parts(parts[1])
                if len(enum) >= 2:
                    src.groups.append(_Group(label=_label(parts[0]), items=enum, ask=bool(_SHOW_RE.match(line))))
            continue
        for sn in H.split_sentences(line) or [line]:
            src.sentences.append(sn)
    close()
    return src


def _enum_parts(body: str) -> list[str]:
    """«слабый отклик, рост цен и перегрузка сотрудников» → three parts (the last «и» splits too, when both sides
    have two words or more); fewer than two parts: []."""
    body = H.strip_end(body)
    parts = [p.strip() for p in re.split(r",\s+(?![^()]*\))", body) if p.strip()]
    if parts and " и " in parts[-1]:
        head, tail = parts[-1].rsplit(" и ", 1)
        if len(head.split()) >= 2 and len(tail.split()) >= 2:
            parts = parts[:-1] + [head.strip(), tail.strip()]
    if len(parts) < 2 or any(len(p.split()) > 12 for p in parts):
        return []
    return [H.cap_first(p) for p in parts]


_BEFORE_AFTER_RE = re.compile(r"^(?:сейчас|было|до\b|текущ|исходн|факт|now|before)|^(?:цель|стало|после|прогноз|план|целев|after|target)", re.I)


_GOAL_RE = re.compile(r"^(?:главная\s+|основная\s+)?(?:цель|задача|целевой показатель)\b", re.I)


def _goal_sentence(sentences: list[str]) -> Optional[str]:
    """The sentence that states the slide's target with its figures («Цель — …»), else the first short sentence
    with a figure; None when there is none of at most 20 words."""
    cands = [sn for sn in sentences if figures(sn) and len(sn.split()) <= 20 and not _ASK_RE.match(sn)]
    return next((sn for sn in cands if _GOAL_RE.match(sn)), cands[0] if cands else None)


# a sentence that states a result: «выручка составит …», «дадут 148 500 рублей», «прибыль достигнет …»
_RESULT_STRONG_RE = re.compile(
    r"(?:состав(?:ит|ят|ляет|ляют)|\bдаст\b|\bдадут\b|достигнет|достигнут|вырастет|вырастут|увеличится|увеличатся|снизится|сократится"
    r"|сэконом|окупится|потребуется|потребуют|принесёт|принесет|приносит|приносят|обходятся|обойдётся|обойдется)",
    re.I,
)
_RESULT_WEAK_RE = re.compile(r"(?:прибыл|выручк|итог|рентабельност|бюджет|экономи|снижени|рост\b|больше|меньше)", re.I)
TAKEAWAY_MAX_WORDS = 22
_BACKREF_RE = re.compile(r"(?<![\wё])(?:эт(?:и|их|им|ими|от|ого|ому|ом|а|ой|у|о)|данн(?:ые|ых|ым|ыми|ая|ой|ую|ое)|таки[ехм]|из\s+них|из\s+этой)\s", re.I)


def _takeaway_sentence(sentences: list[str], labels: list[str], shown: set[str]) -> Optional[str]:
    """The slide's conclusion from the brief's own words, for a slide the model did not design: the sentence of its
    source that states a result with a figure («При достижении этих показателей месячная выручка составит 1 138 500
    рублей — на 238 500 рублей больше текущей»), else a list's lead with a figure («Общий бюджет запуска — 180 000
    рублей»). Later sentences win a tie (a slide's text ends with its result); none longer than 22 words."""
    best: Optional[tuple[int, int, str]] = None
    cands = [*labels, *sentences]  # a list's lead loses a tie to a sentence
    for i, sn in enumerate(cands):
        text = H.strip_end(sn)
        if sn in shown or text in shown or not figures(text) or _ASK_RE.match(text) or not 4 <= len(text.split()) <= TAKEAWAY_MAX_WORDS:
            continue
        # a result in money for the business (profit, revenue) says more than a ratio next to it
        score = 2 * bool(_RESULT_STRONG_RE.search(text)) + bool(_RESULT_WEAK_RE.search(text)) + bool(re.search(r"прибыл|выручк", text, re.I))
        if score <= 0:
            continue
        if _BACKREF_RE.search(text):
            score -= 2  # «При выручке … эти расходы составят …» leans on the sentence before it: another result first
        if best is None or (score, i) >= best[:2]:
            best = (score, i, text)
    return best[2] if best else None


def _series_figures(unit: _Unit, ctx: _Ctx) -> list[NumberCallout]:
    """The slide's two-point series («Сейчас / Цель») as change figures: «300 → 330 ₽» — средний чек."""
    out = []
    for sid in unit.series_ids:
        s = ctx.series.get(sid)
        if s is None or len(s.values) != 2 or len(s.categories) != 2 or not all(_BEFORE_AFTER_RE.match(c.strip()) for c in s.categories):
            continue
        u = (s.unit or "").strip()
        if u == "%":
            value = f"{_fmt_ru(s.values[0], '%')} → {_fmt_ru(s.values[1], '%')}"
        else:
            value = f"{_fmt_ru(s.values[0])} → {_fmt_ru(s.values[1], u or None)}"
        out.append(NumberCallout(value=value, label=s.name))
    return out


def _kpis(lines: list[str]) -> list[NumberCallout]:
    out: list[NumberCallout] = []
    seen: set[str] = set()
    for ln in lines:
        for k in H.kpis_of(ln):
            label = H.strip_end(k.label or "")
            if label.lower() in _FILLER_LABELS or len(label) < 3 or re.match(r"^\d", label):
                label = ""
            key = re.sub(r"\s", "", k.value)
            if key in seen or not label or re.search(rf"(?<!\d){re.escape(k.value.split()[0])}:\d\d", ln):
                continue
            seen.add(key)
            out.append(NumberCallout(value=k.value, label=H.cap_first(label)))
    return out


def _guess_type(s: Series, what: str = "") -> str:
    n = len(s.values)
    text = f"{what} {s.name}".lower()
    periods = sum(bool(re.search(r"месяц|квартал|год|недел|янв|фев|мар|апр|май|мая|июн|июл|авг|сен|окт|ноя|дек|q\d|\b\d{4}\b|перв|втор|трет|четв|пят|шест|сейчас|текущ", c.lower())) for c in s.categories)
    if 2 <= n <= 7 and all(v > 0 for v in s.values) and (re.search(r"структур|дол[яи]|распределен|состав|из чего", text) or ((s.unit or "").strip() == "%" and 95 <= sum(s.values) <= 105)):
        return "pie"
    if n >= 5 and periods >= n - 1:
        return "line"
    if n >= 4 and max((len(c) for c in s.categories), default=0) > 22:
        return "bar"
    return "column"


def chart_of(series: list[Series], ctype: Optional[str] = None, what: str = "") -> Optional[ChartSpec]:
    """A chart with its data inline from registry series: series of the same categories side by side, one-value
    series side by side as one, else the first series."""
    series = [s for s in series if s.values and len(s.values) == len(s.categories)]
    if not series:
        return None
    base = series[0]
    same = [s for s in series if [c.lower() for c in s.categories] == [c.lower() for c in base.categories]]
    if len(series) >= 2 and all(len(s.values) == 1 for s in series):
        cats, rows = [s.name for s in series], [InlineSeries(name=what or "", values=[s.values[0] for s in series])]
        unit = base.unit
    elif len(same) >= 2:
        cats, rows = list(base.categories), [InlineSeries(name=s.name, values=list(s.values)) for s in same[:4]]
        unit = base.unit
    else:
        cats, rows = list(base.categories), [InlineSeries(name=base.name, values=list(base.values))]
        unit = base.unit
    t = ctype or _guess_type(base, what)
    if t in ("pie", "doughnut") and (len(rows) != 1 or not all(v > 0 for v in rows[0].values)):
        t = "column"
    # the series' name is a noun phrase in the nominative («Структура выручки»); the request's words are not
    # («структуры выручки», «выручки по месяцам, начиная с …»)
    title = base.name if len(series) == 1 or len(same) >= 2 else (H.cap_first(what) if what else base.name)
    return ChartSpec(type=t, title=title or None, unit=unit, categories=cats, series=rows)


def _request_charts(unit: _Unit, ctx: _Ctx) -> list[Optional[ChartSpec]]:
    """The charts the user asked for on this slide, from its data (None for a request without data)."""
    spec = unit.spec
    if spec is None:
        return []
    out: list[Optional[ChartSpec]] = []
    used: set[str] = set()
    free = [sid for sid in unit.series_ids if not any(sid in r.series_ids for r in spec.charts)]
    for req in spec.charts[:2]:
        ids = [sid for sid in req.series_ids if sid in ctx.series]
        if not ids:
            nxt = next((sid for sid in free if sid not in used), None)
            ids = [nxt] if nxt else []
        used.update(ids)
        out.append(chart_of([ctx.series[i] for i in ids], req.type, req.what) if ids else None)
    return out


def _same_family(a: str, b: str) -> bool:
    fam = {"pie": "pie", "doughnut": "pie", "column": "col", "bar": "col", "line": "line", "area": "line"}
    return fam.get(a) == fam.get(b)


def _same_data(a: ChartSpec, b: ChartSpec) -> bool:
    return [c.lower() for c in a.categories] == [c.lower() for c in b.categories] and [s.values for s in a.series] == [s.values for s in b.series]


def _similar_data(a: ChartSpec, b: ChartSpec) -> bool:
    """The same figures, whatever the labels, the order or the scale (thousands): the designer drew this data."""
    if _same_data(a, b):
        return True
    va = sorted(v for s in a.series[:1] for v in s.values)
    vb = sorted(v for s in b.series[:1] for v in s.values)
    if not va or len(va) != len(vb):
        return False
    return any(all(abs(x - y * k) <= 1e-6 * max(1.0, abs(x)) for x, y in zip(va, vb)) for k in (1.0, 1000.0, 0.001))


def _covers(want: ChartSpec, got: ChartSpec) -> bool:
    """`got` shows the data of `want` (the brief's): every value of it (as is or in thousands), at most one more."""
    wv = [v for sr in want.series for v in sr.values]
    gv = [v for sr in got.series for v in sr.values]
    if not wv or not gv:
        return False

    def near(a: float, b: float) -> bool:
        return any(abs(a - b * k) <= 1e-6 * max(1.0, abs(a)) for k in (1.0, 1000.0, 0.001))

    if _same_shares(want, got):
        return True  # a pie of the amounts for a pie of the percentages: the same parts of the whole
    if not all(any(near(w, g) for g in gv) for w in wv):
        return False
    return sum(1 for g in gv if not any(near(w, g) for w in wv)) <= 1


def _same_shares(a: ChartSpec, b: ChartSpec) -> bool:
    """One series each, of the same length, with the same shares of the whole (540 000 / 225 000 / 135 000 and
    60 / 25 / 15)."""
    if len(a.series) != 1 or len(b.series) != 1:
        return False
    va, vb = a.series[0].values, b.series[0].values
    if len(va) != len(vb) or len(va) < 2 or any(v <= 0 for v in [*va, *vb]):
        return False
    sa, sb = sum(va), sum(vb)
    return all(abs(x / sa - y / sb) <= 0.005 for x, y in zip(va, vb))


_STATE_CAT_RE = re.compile(
    r"^(?:сейчас|было|стало|до|после|текущ|нынешн|исходн|факт|цель|целев|прогноз|план|итог|now|before|after|target|plan|forecast)"
    r"|(?:месяц|квартал|недел|год|янв|фев|мар|апр|май|мая|июн|июл|авг|сен|окт|ноя|дек|q\d|\b\d{4}\b)",
    re.I,
)


def _stems(text: str) -> frozenset:
    try:
        from verstka.planning.grounding import content_stems

        return frozenset(content_stems(text or "", neutral=True))
    except Exception:  # noqa: BLE001
        return frozenset(w[:5] for w in _words(text) if len(w) > 3)


def _meet(a: frozenset, b: frozenset) -> bool:
    try:
        from verstka.planning.grounding import _stems_meet

        return _stems_meet(a, b)
    except Exception:  # noqa: BLE001
        return bool(a & b)


def pie_ok(ch: Optional[ChartSpec], ctx: Optional["_Ctx"] = None) -> bool:
    """A pie or a doughnut shows the parts of one whole: one series of 2–8 positive values whose categories are
    parts, not states or periods (never «Сейчас / Цель», «Текущая доля / Цель», months); in percent they add up to
    about 100 (95–105); in amounts they are an enumeration the brief gives (the analyst's series of these categories)
    or add up to a total the brief states. [35, 33] labelled «Текущая доля / Цель» would be drawn as 52% / 48%: false."""
    if ch is None or len(ch.series) != 1 or not 2 <= len(ch.categories) <= 8:
        return False
    vals = ch.series[0].values
    if len(vals) != len(ch.categories) or not all(v is not None and v > 0 for v in vals):
        return False
    if sum(1 for c in ch.categories if _STATE_CAT_RE.search(c.strip())) >= max(1, len(ch.categories) - 1):
        return False
    if (ch.unit or "").strip() in ("%", "п. п.", "п.п."):
        return 95 <= sum(vals) <= 105
    if ctx is None:
        return len(vals) >= 3
    mine = [_stems(c) for c in ch.categories]
    for s in ctx.series.values():
        if len(s.categories) < 2 or len(s.categories) != len(vals):
            continue
        theirs = [_stems(c) for c in s.categories]
        if all(any(_meet(m, x) for x in theirs) for m in mine if m):
            return True  # the brief's own enumeration of parts
    total = sum(vals)
    for scale in (1.0, 1000.0, 1_000_000.0):
        if any(abs(total * scale - a) <= 0.005 * max(1.0, abs(a)) for a in ctx.allowed):
            return True  # the parts add up to a total the brief gives
    return False


def label_conflicts(want: ChartSpec, got: ChartSpec) -> list[str]:
    """The categories of `got` that the brief's data (`want`) gives another value: «Продукты» drawn at 270 000 when the
    brief's «Продукты» is 315 000 (and 270 000 its «Зарплаты»). A category is matched to the brief's by its words;
    values compare as they are, in thousands or in millions."""
    if not want.series or not got.series:
        return []
    wv, gv = want.series[0].values, got.series[0].values
    sw, sg = sum(wv), sum(gv)
    theirs = [_stems(c) for c in want.categories]
    distinct = [x - frozenset().union(*[y for j, y in enumerate(theirs) if j != i]) for i, x in enumerate(theirs)]
    out = []
    for cat, v in zip(got.categories, gv):
        mine = _stems(cat)
        hits = [i for i, x in enumerate(distinct) if x and _meet(mine, x)]
        if len(hits) != 1 or hits[0] >= len(wv):
            continue
        w = wv[hits[0]]
        if any(abs(v * k - w) <= 0.005 * max(1.0, abs(w)) or abs(v * k - w) <= 500 * (k == 1000.0) for k in (1.0, 1000.0, 0.001, 1_000_000.0)):
            continue
        if sw > 0 and sg > 0 and abs(v / sg - w / sw) <= 0.005:
            continue  # the same part of the whole: amounts for the brief's percentages (540 000 of 900 000 = 60%)
        out.append(cat)
    return out


def _table_for(unit: _Unit, ctx: _Ctx) -> Optional[TableData]:
    for tid in unit.table_ids:
        t = ctx.tables.get(tid)
        if t is not None:
            return _clip_table(t)
    return None


def _clip_table(t: Optional[TableData]) -> Optional[TableData]:
    if t is None:
        return None
    t = t.model_copy(deep=True)
    t.columns = t.columns[:MAX_TABLE_COLS]
    t.rows = [r[:MAX_TABLE_COLS] for r in t.rows[:MAX_TABLE_ROWS]]
    return t if t.columns and t.rows else None


def _cover_design(unit: _Unit, ctx: _Ctx) -> _Design:
    st = ctx.structure
    title = st.title or ctx.title or unit.title
    notes = ""
    if unit.spec is not None:
        rest = [ln.strip() for ln in (unit.spec.text or "").splitlines() if ln.strip() and not _TITLE_LINE_RE.match(ln)]
        notes = " ".join(rest)
    s = OutlineSlide(
        id=unit.key, kind=PatternKind.title, headline=title, subtitle=st.subtitle, footnote=st.disclaimer, notes=notes,
        rationale=_WHY["title"], spec_ref=unit.spec.number if unit.spec else None,
    )
    return _Design(unit=unit, slide=s)


def _closing_design(unit: _Unit) -> _Design:
    return _Design(unit=unit, slide=OutlineSlide(id=unit.key, kind=PatternKind.thanks, headline=unit.title or "Спасибо за внимание", rationale=_WHY["thanks"]))


def _why(slide: OutlineSlide, requested: bool = False) -> str:
    k = slide.kind.value
    key = slide.content.chart.type if k == "chart" and slide.content.chart is not None else k
    base = _WHY.get(key, "")
    if requested:
        return f"Так просили в брифе. {base}".strip()
    return base


def rules_design(unit: _Unit, ctx: _Ctx) -> _Design:
    """The slide without a model: requested charts from its series, the table, the formula, figures as a row of
    numbers, lists as cards / a timeline / bullets; the user's heading, «Вывод» and footnote; the rest of the source
    text (explanations, calculations) in the notes."""
    if unit.cover:
        return _cover_design(unit, ctx)
    if unit.closing:
        return _closing_design(unit)
    spec = unit.spec
    src = _read_source(unit.text)
    c = SlideContent()
    kind = "bullets"
    # a writer's sentence is shortened only where a clause ends, else shown whole (gate 4 G4-1); a user's brief keeps
    # the old word cut
    lim = 30 if len(src.sentences) <= 3 else 20  # a slide of few sentences has room for them whole
    cut = (lambda x, n: _clause_cut(x, n, lim)) if ctx.written else H.short
    subtitle: Optional[str] = None
    shown: set[str] = set()
    charts = [ch for ch in _request_charts(unit, ctx) if ch is not None][:2]
    if not charts and spec is None and unit.series_ids:
        ch = chart_of([ctx.series[unit.series_ids[0]]])
        charts = [ch] if ch else []
    table = _table_for(unit, ctx) if (spec is not None and (spec.table or spec.table_ids)) or (spec is None and not charts) else None
    if charts:
        kind = "chart"
        c.chart = charts[0]
        c.chart2 = charts[1] if len(charts) > 1 else None
    elif table is not None:
        kind, c.table = "table", table
    elif len(src.steps) >= 3:
        kind = "timeline"
        c.items = [SlideItem(title=t, text=x) for t, x in src.steps[:6]]
    elif (dated := _dated_items(unit, src)) is not None:
        # a dated list («— 1 сентября 1939 года — Германия нападает на Польшу;»): a timeline, never years as figures
        kind, c.items = "timeline", dated
        shown.update(x for g in src.groups if all(_dated_event(i) for i in g.items) for x in g.items)
    else:
        text_groups = [g for g in src.groups if not g.figure]
        text_groups.sort(key=lambda g: (not g.ask, -len(g.items)))  # the lists the user asked to show come first
        fig_items = [x for g in src.groups if g.figure for x in g.items]
        other_items = [x for g in text_groups[1:] for x in g.items]
        def kpis(lines: list[str]) -> list[NumberCallout]:
            out = _kpis(lines)
            # the writer's text (a topic): a year or a day of a month is a date, never a slide's key figure; nor a time
            # of day, a project number or a bound of a requirement (gate 4 G4-3)
            return [n for n in out if not _date_callout(n) and not _not_key_figure(n, lines)] if ctx.written else out

        numbers = _series_figures(unit, ctx) or kpis(fig_items) or kpis(other_items) or kpis(src.sentences)
        if text_groups:
            g = text_groups[0]
            pair = text_groups[1] if len(text_groups) > 1 else None
            if pair is not None and g.label and pair.label and g.ask == pair.ask and len(g.items) <= 4 and len(pair.items) <= 4:
                kind = "two_column"
                c.columns = [SlideItem(title=x.label or "", bullets=[cut(i, 12) for i in x.items]) for x in (g, pair)]
                shown.update(i for x in (g, pair) for i in x.items)
            else:
                its = g.items[:6]
                if 2 <= len(its) <= 6 and all(len(x.split()) <= 10 for x in its):
                    kind = "cards"
                    c.items = [SlideItem(title=cut(x, 10)) for x in its]
                else:
                    kind = "bullets"
                    c.bullets = [cut(x, 14) for x in its]
                shown.update(its)
            # a list is the slide's one block (the composer shows items or figures, not both): its key figure goes
            # into the subtitle as the sentence that states it («Цель — поднять средний чек с 300 до 330 рублей»)
            goal = _goal_sentence(src.sentences)
            if goal is not None:
                subtitle = H.strip_end(goal)
                shown.add(goal)
        elif numbers:
            nums = numbers if len(numbers) <= 4 else numbers[:3] + numbers[-1:]
            kind = "stat_row" if len(nums) >= 2 else "big_number"
            c.numbers = nums
            shown.update(fig_items)
            if ctx.written:
                # a writer's slide shows its other sentences under its figures (they went to the notes: gate 4 G4-2)
                from verstka.planning.grounding import figures as g_figs

                mags = [f.mag for n in nums for f in g_figs(n.value or "") if f.date is None]
                own = [sn for sn in src.sentences if not _ASK_RE.match(sn) and any(abs(f.mag - m) <= 1e-6 * max(1.0, abs(m)) for f in g_figs(sn) for m in mags)]
                rest = [sn for sn in src.sentences if sn not in own and not _ASK_RE.match(sn)][:3]
                c.bullets = [cut(sn, 14) for sn in rest]
                shown.update(own + rest)
        else:
            lines = [cut(sn, 14) for sn in src.sentences if not _ASK_RE.match(sn)][:5]
            c.bullets = lines
            shown.update(src.sentences[:5])
    if spec is not None and spec.formula:
        c.formula = spec.formula
    if not (c.bullets or c.items or c.numbers or c.chart or c.table or c.columns or c.formula):
        c.bullets = [cut(sn, 14) for sn in src.sentences[:4]] or ([cut(unit.text, 14)] if unit.text.strip() else [])
        kind = "bullets"
        shown.update(src.sentences[:4])
    if kind == "bullets" and not c.bullets and c.formula:
        kind = "big_number" if c.numbers else "bullets"
    takeaway = spec.takeaway if spec else None
    if takeaway is None:
        labels = [g.label for g in src.groups if g.label]
        takeaway = _takeaway_sentence(src.sentences, labels, shown | ({subtitle} if subtitle else set()))
        if takeaway is not None:
            shown.update(sn for sn in src.sentences if H.strip_end(sn) == takeaway)
    notes = [sn for sn in src.sentences if sn not in shown and not _ASK_RE.match(sn)]
    for g in src.groups:
        rest = [x for x in g.items if x not in shown]
        if rest and not ((c.chart is not None or c.table is not None) and g.figure) and not (c.table is not None and g.label and re.search(r"таблиц", g.label, re.I)):
            notes.append((f"{g.label}: " if g.label else "") + "; ".join(rest) + ".")
    if src.steps and kind != "timeline":
        notes.append("; ".join(f"{t} — {x}" for t, x in src.steps) + ".")
    headline = unit.title or H.short(unit.text, 10)
    section = unit.section
    if spec is not None and not headline_states(headline):
        # the user's heading names a topic («Как увеличить средний чек»): the headline states the slide's goal with its
        # figure when the source gives one short enough, the heading stays as the slide's kicker
        stated = _fallback_headline(unit, ctx)
        if stated and stated != headline:
            if subtitle and same_text(stated, subtitle):
                subtitle = None  # the goal line moves up into the headline
            headline, section = stated, section or unit.title
            if takeaway and same_text(takeaway, headline):
                takeaway = None
    s = OutlineSlide(
        id=unit.key, kind=PatternKind(kind), section=section, headline=headline, subtitle=subtitle, content=c,
        notes=" ".join(notes[:5]), takeaway=takeaway, footnote=spec.footnote if spec else None,
        spec_ref=spec.number if spec else None,
    )
    s.rationale = _why(s, requested=bool(spec and (spec.charts or spec.table)))
    d = _Design(unit=unit, slide=s)
    d.alternatives = auto_alternatives(s)
    return d


def _clause_cut(text: str, max_words: int, floor: int = 20) -> str:
    """A writer's sentence on a line: whole up to `floor` words (20; 30 on a slide of three sentences or fewer), else
    shortened where a clause ends (clauses.fit), never a fragment — «6 июня 1944 года союзные силы США» was the old
    word cut (gate 4 G4-1)."""
    from verstka.planning.clauses import fit

    return fit(text, max(max_words, floor))


def _not_key_figure(n: NumberCallout, lines: list[str]) -> bool:
    """A writer's figure that is not a key figure: a time of day («10 ч» of «в 10 часов 53 минуты»), a project or
    model number («22220» of «ледоколы проекта 22220»), a bound or a figure of a requirements list («не более 170 см»,
    «возраст около 30 лет, … вес до 68—70 кг») — gate 4 G4-3."""
    from verstka.planning.clauses import figure_kind
    from verstka.planning.grounding import figures as g_figs

    want = g_figs(n.value or "")
    if not want:
        return False
    for ln in lines:
        for f in g_figs(ln):
            if f.date is None and abs(f.mag - want[0].mag) <= 1e-6 * max(1.0, abs(f.mag)) and figure_kind(ln, f.start, f.end):
                return True
    return False


_STEP_TITLE_RE = re.compile(r"^(?:\d{1,2}\s*[-.)]|\d{1,2}\s*-?\s*(?:й|ый|ой|ий)\b|(?:шаг|этап|неделя|месяц|квартал|фаза|step|stage|phase|week)\b|(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр))", re.I)


def _sequential(s: OutlineSlide) -> bool:
    """The slide's items read as steps in order («1-й месяц», «Этап 2», «Неделя 3», «Март»), or one of its columns
    does («1-й месяц — учёт показателей», …)."""
    titles = [it.title for it in s.content.items] or list(s.content.bullets)
    if len(titles) >= 3 and all(_STEP_TITLE_RE.match(t.strip()) for t in titles):
        return True
    return any(len(col.bullets) >= 3 and all(_step_item(b) is not None for b in col.bullets) for col in s.content.columns)


def auto_alternatives(s: OutlineSlide) -> list[Alternative]:
    """Two other forms the slide's content can take (a more visual one, then a denser one) — for a design the model
    did not make, and to complete a model's answer that gave none. A timeline or a process only for items that read
    as steps: the rules cannot tell a sequence from a list otherwise."""
    out: list[Alternative] = []
    for order in (_VISUAL_ORDER, _COMPACT_ORDER):
        for k in order:
            if k == s.kind.value or any(a.kind == k for a in out):
                continue
            if k in ("timeline", "process") and not _sequential(s):
                continue
            if reshape(s, k) is not None:
                out.append(Alternative(kind=k, why=_ALT_WHY.get(k, "")))
                break
    return out


# ------------------------------------------------------------------ the model's design → a slide




_UNIT_TAIL_RE = re.compile(r"^(?P<label>.*?)[\s,;(]*(?P<unit>₽|руб\.?|рубл(?:ей|я|ь)|%|процент\w*|шт\.?|штук)\)?$", re.I)
_STATE_PREFIX_RE = re.compile(r"^(?:сейчас|было|стало|текущ\w*|нынешн\w*|исходн\w*|цель|целев\w*|план\w*|прогноз\w*|до|после)\s*(?:[—–:-]\s*|$)", re.I)
_UNIT_SIGN = {"₽": "₽", "руб": "₽", "руб.": "₽", "рублей": "₽", "рубля": "₽", "рубль": "₽", "%": "%", "шт": "шт.", "шт.": "шт.", "штук": "шт."}


def fix_callouts(numbers: list[NumberCallout], unit: _Unit, ctx: Optional[_Ctx]) -> list[NumberCallout]:
    """A row of figures as the audience reads it: a label is never only a unit nor a «Цель — / Сейчас —» prefix — the
    unit goes to the value («330» · «Средний чек, ₽» → «330 ₽» · «Средний чек»), the prefix goes; and a figure that is
    one end of a before/after pair the slide's data gives (the analyst's «Сейчас / Цель» series, the brief's «с 300 до
    330») is shown as the change of its measure with the measure's name: «300 → 330 ₽» · «Средний чек», «20% → 30%» ·
    «Доля чеков с едой». Two figures of one pair become one callout."""
    pairs = _series_figures(unit, ctx) if ctx is not None else []
    out: list[NumberCallout] = []
    for n in numbers:
        value, label = " ".join((n.value or "").split()), H.strip_end(" ".join((n.label or "").split()))
        m = _UNIT_TAIL_RE.match(label)
        if m and not figures(label):
            sign = _UNIT_SIGN.get(m.group("unit").lower(), m.group("unit"))
            label = H.strip_end(m.group("label"))
            if figures(value) and not re.search(r"[^\d\s  .,+\-−→]", value):
                value = f"{value}%" if sign == "%" else f"{value} {sign}"
        label = _STATE_PREFIX_RE.sub("", label).strip(" —–:-")
        label = H.cap_first(label) if label else ""
        vals = figures(value)
        if "→" not in value and len(vals) == 1:
            for p in pairs:
                ends = figures(p.value)
                if len(ends) == 2 and any(abs(vals[0] - e) <= 1e-6 * max(1.0, abs(e)) for e in ends) and (not label or _meet(_stems(label), _stems(p.label))):
                    value, label = p.value, label or p.label  # the designer's name of the measure, else the data's
                    break
        if any(x.value == value for x in out):
            continue  # the other end of a pair already shown as its change
        out.append(n.model_copy(update={"value": value, "label": label}))
    return out


def _resolve_chart(ch: Optional[ChartSpec], unit: _Unit, ctx: _Ctx, changes: list[str]) -> Optional[ChartSpec]:
    """A chart of the designer's answer with its data inline and supported by the brief: series ids of the data list
    are copied in; a chart whose values are not in the brief is dropped (the request is then served by the rules)."""
    if ch is None:
        return None
    ch = ch.model_copy(deep=True)
    if not ch.series and ch.series_ids:
        found = [ctx.series[i] for i in ch.series_ids if i in ctx.series]
        built = chart_of(found, ch.type, ch.title or "")
        if built is None:
            changes.append(f"slide {unit.key}: chart without data dropped (ids {', '.join(ch.series_ids)})")
            return None
        built.title = ch.title or built.title
        built.unit = ch.unit or built.unit
        built.highlight_index = ch.highlight_index
        ch = built
    ch.series_ids = []
    ch.series = [s for s in ch.series if s.values and len(s.values) == len(ch.categories)]
    if not ch.series or not ch.categories:
        changes.append(f"slide {unit.key}: chart without data dropped")
        return None
    bad = [v for s in ch.series for v in s.values if not value_ok(v, ctx.allowed)]
    if bad:
        changes.append(f"slide {unit.key}: chart dropped, values not in the brief: {', '.join(_fmt(v) for v in bad[:4])}")
        return None
    if ch.type in ("pie", "doughnut") and not pie_ok(ch, ctx):
        changes.append(f"slide {unit.key}: a {ch.type} of values that are not parts of one whole ({', '.join(ch.categories[:3])}) drawn as columns")
        ch.type = "column"
    # the brief's values under the brief's labels: a chart that swaps them («Продукты» at 270 000) takes the brief's
    for s in ctx.series.values():
        want = chart_of([s])
        if want is not None and _similar_data(want, ch) and label_conflicts(want, ch):
            bad = label_conflicts(want, ch)
            changes.append(f"slide {unit.key}: chart values under other labels than the brief's ({', '.join(bad[:3])}): the brief's data used")
            fixed = chart_of([s], ch.type, ch.title or "")
            if fixed is None:
                return None
            fixed.title, fixed.highlight_index = ch.title or fixed.title, None
            if fixed.type in ("pie", "doughnut") and not pie_ok(fixed, ctx):
                fixed.type = "column"
            return fixed
    if ch.highlight_index is not None and not 0 <= ch.highlight_index < len(ch.categories):
        ch.highlight_index = None
    return ch


def _quote_ok(q: Optional[str], ctx: _Ctx) -> bool:
    if not q:
        return False
    norm = lambda t: re.sub(r"\W+", " ", t.lower()).strip()  # noqa: E731
    return norm(q) in norm(ctx.brief.text)


def _words(text: str) -> list[str]:
    return re.findall(r"[0-9a-zа-яё]+", (text or "").lower().replace("ё", "е"))


# a footnote's business: what the figures leave out or assume («не учитываются», «условные», «это выручка, а не прибыль»)
_CAVEAT_RE = re.compile(
    r"не\s+учитыва|не\s+учт[её]н|не\s+включ|без\s+уч[её]та|без\s+налог|до\s+вычета|условн|не\s+гарантир|упрощ[её]нн|"
    r"прогноз|оценк|предполож|допущени|\bа\s+не\b|excluded|not\s+included|hypothetical|estimate|assum",
    re.I,
)


def _title_text(it: SlideItem, text: str = "") -> str:
    """A card as one line: «Партнёрства — с пятью ближайшими офисами» (the text after the dash continues the title) —
    a name keeps its capital («1937 год — Япония начала войну»: `text`, the source the card comes from, writes it so)."""
    t, x = H.strip_end(it.title or ""), H.strip_end(it.text or "")
    if not x and it.bullets:
        x = "; ".join(H.strip_end(b) for b in it.bullets)  # a card of a list keeps its lines
        return f"{t}: {x}" if t else x
    if t and x and re.search(r"\s[—–]\s", x):
        return f"{t}: {x}"  # the text has its own dash: «Свободные часы: 65% покупок — утром»
    if t and x:
        return f"{t} — {_low_first(x, text, date_title=bool(_DATE_TITLE_RE.search(t)))}"
    return t or x


def _fit_form(kind: str, c: SlideContent, changes: list[str], key: str, text: str = "") -> str:
    """Every field the designer filled is one the chosen form shows (a field it does not show would be lost on the
    slide — the audit calls that «content missing»): columns next to a small table become the slide (the table's
    figures are in them) or lines under the block; figures on a form without a row of figures become lines; the
    paragraphs past the lead line join the lines."""
    if c.columns and c.items:
        # the same blocks given twice (as cards and as columns): the form's own field keeps them
        ct = [" ".join(H.strip_end(x.title).lower().split()) for x in c.columns]
        it = [" ".join(H.strip_end(x.title).lower().split()) for x in c.items]
        if ct == it or set(it) <= set(ct) or set(ct) <= set(it):
            if kind in ("two_column", "comparison"):
                c.items = []
            else:
                c.columns = []
            changes.append(f"slide {key}: the same blocks as cards and as columns: kept once")
    if c.columns and kind not in ("two_column", "comparison"):
        col_text = " ".join(b for col in c.columns for b in [col.title, *col.bullets, col.text])
        col_figs = figures(col_text)
        tab_figs = [v for row in (c.table.rows if c.table is not None else []) for cell in row for v in figures(cell)]
        in_cols = all(any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) for x in col_figs) for v in tab_figs)
        if c.chart is None and not c.items and not c.numbers and in_cols and len(c.columns) >= 2:
            changes.append(f"slide {key}: {kind} with columns → two_column (the table's figures are in the columns)")
            kind, c.table = "two_column", None
        else:
            lines = [f"{col.title}: {b}" if col.title else b for col in c.columns for b in (col.bullets or [col.text]) if b]
            c.bullets = (list(c.bullets) + lines)[:MAX_BULLETS]
            c.columns = []
            changes.append(f"slide {key}: columns on a {kind} slide shown as lines under it")
    if c.bullets and (c.chart is not None or c.formula or (c.numbers and kind in ("stat_row", "big_number"))):
        # lines that only repeat the figures the slide already shows big (the chart's values, the row of figures, the
        # formula's terms): «100 покупок в день» under «100 × 300 × 30 = 900 000»
        vals = [v for ch in (c.chart, c.chart2) if ch is not None for sr in ch.series for v in sr.values]
        vals += [v for n in c.numbers for v in figures(n.value)] + figures(c.formula or "")
        keep = [b for b in c.bullets if not (figures(b) and all(any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) for x in vals) for v in figures(b)))]
        if len(keep) < len(c.bullets):
            changes.append(f"slide {key}: {len(c.bullets) - len(keep)} lines repeated the figures the slide shows, dropped")
            c.bullets = keep
    if c.numbers and kind in ("two_column", "comparison", "cards") and 2 <= len(c.numbers) <= 4 and c.chart is None and c.table is None and not c.formula:
        # the figures are the slide's substance: a row of big figures, the list under it as short lines — never the
        # figures demoted to small lines under the cards («35 → 33%», «27 000 → 15 000 ₽» of a two-column answer)
        # the longest list keeps its lines as they are; each other column folds into one line «Цель: …»
        cols = sorted(c.columns, key=lambda col: -len(col.bullets))
        lines = [b for b in (cols[0].bullets or [cols[0].text]) if b] if cols else []
        for col in cols[1:]:
            body = "; ".join(x for x in [*(col.bullets or [col.text])] if x)
            if body:
                lines.append(f"{col.title}: {body}" if col.title else body)
        lines += [_title_text(it, text) for it in c.items]
        lines = [x for x in list(c.bullets) + lines if x]
        if len(lines) <= MAX_BULLETS and all(len(x.split()) <= 14 for x in lines):
            changes.append(f"slide {key}: {kind} with {len(c.numbers)} figures → a row of figures with the list under it")
            c.bullets, c.columns, c.items = lines, [], []
            return "stat_row"
    if c.numbers and kind not in ("stat_row", "big_number") and not c.formula:
        lines = [f"{H.strip_end(n.label)} — {n.value}" if n.label else n.value for n in c.numbers]
        c.bullets = (list(c.bullets) + lines)[:MAX_BULLETS]
        c.numbers = []
        changes.append(f"slide {key}: figures on a {kind} slide shown as lines")
    if len(c.paragraphs) > 1 or (c.paragraphs and c.bullets and kind not in ("bullets", "chart", "stat_row", "big_number")):
        lead = [] if c.bullets else c.paragraphs[:1]
        c.bullets = (list(c.bullets) + [p for p in c.paragraphs if p not in lead])[:MAX_BULLETS]
        c.paragraphs = lead
    return kind


def _headline_checked(headline: str, unit: _Unit, ctx: _Ctx, changes: list[str]) -> str:
    """The designer's headline without a figure the brief does not give («за 5 месяцев» counted from the months of a
    table): the rest of it when the figure goes with its preposition and three words or more are left, else the
    slide's title (the user's heading, the architect's working title) — never a bare section name, which is what
    grounding falls back to on a slide the brief did not describe."""
    try:
        if ctx.index is None:
            return headline
        c = ctx.index.clean(headline)
    except Exception:  # noqa: BLE001 - grounding checks the deck again anyway
        return headline
    if not c.bad:
        return headline
    # the figure with its preposition out («… выросли в 10 раз за 5 месяцев» → «… выросли в 10 раз»), when that leaves
    # a clean line; else what grounding keeps of it; else the working title
    cut, whole = headline, True
    for b in c.bad:
        # only a figure with its preposition goes («за 5 месяцев», «до 1,14 млн ₽»): a bare figure is a word the
        # sentence needs («составляют 75% бюджета» would read «составляют бюджета»)
        m = re.search(rf"\s*(?:(?:почти|около|примерно|приблизительно|более\s+чем|больше\s+чем|менее\s+чем|меньше\s+чем|свыше)\s+)?(?:за|через|в\s+течение|на|до|с|со|по|около|более|почти|в)\s+{re.escape(b)}(?=\s*(?:$|[,.;:—–]|за\b|через\b|в\s+течение\b|к\b))", cut, flags=re.I)
        if m is None:
            whole = False
            break
        cut = cut[: m.start()] + cut[m.end():]
    cut = H.strip_end(re.sub(r"\s{2,}", " ", cut).strip(" ,—–-"))
    try:
        cut_ok = whole and bool(cut) and not ctx.index.clean(cut).bad
    except Exception:  # noqa: BLE001
        cut_ok = False
    # else the slide's own title (the user's heading, the architect's working title): a clause grounding keeps of the
    # sentence («Расходы на зарплаты» of «… и продукты составляют 73% бюджета») says less than either
    new = H.cap_first(cut) if cut_ok and len(cut.split()) >= 3 and cut.lower() != headline.lower() else _fallback_headline(unit, ctx)
    changes.append(f"slide {unit.key}: headline «{headline[:80]}» had figures not in the brief ({', '.join(c.bad)[:60]}) → «{new[:80]}»")
    return new or headline


def said_in(line: str, source: str, share: float = 0.6) -> bool:
    """The line says what the source text says: most of its words (by stem, `share` of them) are the source's."""
    try:
        from verstka.planning.grounding import _Stems, content_stems

        have = _Stems(content_stems(source, neutral=True))
        mine = content_stems(line, neutral=True)
        return bool(mine) and sum(1 for w in mine if have.has(w)) / len(mine) >= share
    except Exception:  # noqa: BLE001
        stems = {w[:5] for w in _words(source) if len(w) > 3}
        mine2 = [w[:5] for w in _words(line) if len(w) > 3]
        return bool(mine2) and sum(1 for w in mine2 if w in stems) / len(mine2) >= share


def same_text(a: Optional[str], b: Optional[str]) -> bool:
    """Two lines that say the same thing (a takeaway that repeats the headline): the same words, or one line's words
    nearly all in the other."""
    wa, wb = _words(a or ""), _words(b or "")
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    sa, sb = set(wa), set(wb)
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return len(small) >= 3 and len(small & big) / len(small) >= 0.85


def _subject_stems(text: str) -> frozenset:
    """The stems of what a line is about: its content words without the words of measure, change, period and plan
    («рост», «вырастет», «месяц», «цель» …), which any two lines about one figure share."""
    try:
        from verstka.planning.grounding import _GENERIC_STEMS
    except Exception:  # noqa: BLE001
        _GENERIC_STEMS = ()  # noqa: N806
    return frozenset(s for s in _stems(text) if not s.startswith(tuple(_GENERIC_STEMS)))


# «за 6 месяцев», «в течение 30 дней»: the deck's horizon, not a figure a line adds
_PERIOD_RE = re.compile(r"(?<![\d.,])\d{1,3}\s*(?:-?\s*(?:й|го|м)\s+)?(?:месяц\w*|мес\.|дн(?:я|ей)|день|недел\w*|год(?:а|у)?|лет|квартал\w*)(?![\wё])", re.I)


def _figure_set(text: str) -> frozenset:
    return frozenset(round(v, 6) for v in figures(_PERIOD_RE.sub(" ", text or "")))


def adds_nothing(line: Optional[str], ref: Optional[str]) -> bool:
    """`line` says nothing `ref` does not: the same words (same_text), or its figures are all ref's and what it speaks
    of is ref's subject in other words — «Рост выручки на 26,5% за 6 месяцев» under «Выручка вырастет на 26,5% за 6
    месяцев». A line that adds a figure or a subject of its own adds something («Рентабельность вырастет до 22,4%»
    under «Прибыль вырастет вдвое»)."""
    if not line or not ref:
        return False
    wl, wr = set(_words(line)), set(_words(ref))
    if wl and len(wl & wr) / len(wl) >= 0.85:
        return True  # its words are ref's (a line that holds ref's words and more of its own adds them)
    fl, fr = _figure_set(line), _figure_set(ref)
    if not fl <= fr:
        return False
    if len(fl) >= 2:
        return True  # the same two figures: the same statement («Экономия 22 770 ₽ при выручке 1 138 500 ₽» twice)
    mine, theirs = _subject_stems(line), _subject_stems(ref)
    if not mine:
        return bool(fl)  # only figures and measure words, all of them ref's
    hit = sum(1 for x in mine if _meet(frozenset([x]), theirs))
    return hit / len(mine) >= (0.75 if fl else 0.85) and (bool(fl) or len(mine) >= 2)


# a footnote's kinds of caveat: a line under the block with the same one repeats it («Результат не гарантирован» over
# the footnote «Прогноз не гарантирован»)
_CAVEAT_KINDS = (
    re.compile(r"не\s+гарантир|гаранти\w*\s+нет|без\s+гаранти", re.I),
    re.compile(r"не\s+учитыва|не\s+учт[её]н|не\s+включ|без\s+уч[её]та|в\s+расч[её]т\s+не", re.I),
    re.compile(r"условн|вымышлен|учебн\w*\s+кейс", re.I),
    re.compile(r"учитыва\w*\s+отдельно|отдельно\s+от", re.I),
)


def same_caveat(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    return any(rx.search(a) and rx.search(b) for rx in _CAVEAT_KINDS)


_SAM = r"сам(?:ый|ая|ое|ые|ого|ой|ую|ых|ым|ыми)"
_MIN_CLAIM_RE = re.compile(rf"минимальн|наименьш|{_SAM}\s+(?:маленьк|низк|мал|скромн)|меньше\s+всего|незначительн", re.I)
_MAX_CLAIM_RE = re.compile(rf"максимальн|наибольш|{_SAM}\s+(?:крупн|больш|высок|значим|дорог)|больше\s+всего|львин", re.I)


def comparative_false(line: Optional[str], charts: list[ChartSpec], ctx: Optional[_Ctx] = None) -> bool:
    """A line that ranks parts («Маркетинг и прочие расходы — минимальная доля», «Зарплаты — самая крупная статья»)
    against the data of its slide (or of the brief): the parts it names by their own words must be the smallest (or
    the largest) as many of them as it names. «Прочие расходы» at 30 000 are not among the two smallest of 20 000,
    25 000, 30 000 … — the line is false."""
    if not line:
        return False
    lo, hi = bool(_MIN_CLAIM_RE.search(line)), bool(_MAX_CLAIM_RE.search(line))
    if not (lo or hi):
        return False
    pool = list(charts)
    if ctx is not None:
        pool += [x for x in (chart_of([s]) for s in ctx.series.values()) if x is not None]
    mine = _stems(line)
    for ch in pool:
        if len(ch.series) != 1 or len(ch.categories) < 3 or len(ch.series[0].values) != len(ch.categories):
            continue
        cats = [_stems(c) for c in ch.categories]
        common = _stems(f"{ch.title or ''} {ch.series[0].name or ''}")
        distinct = [x - common - frozenset().union(*[y for j, y in enumerate(cats) if j != i]) for i, x in enumerate(cats)]
        named = [i for i, x in enumerate(distinct) if x and _meet(mine, x)]
        if not named:
            continue
        vals = ch.series[0].values
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        k = len(named)
        if lo and not set(named) <= set(order[:k]):
            return True
        if hi and not set(named) <= set(order[-k:]):
            return True
    return False


def _visible_text_of(headline: str, c: SlideContent) -> str:
    parts = [headline, c.formula or "", *c.bullets, *c.paragraphs]
    parts += [f"{it.title} {it.text} {' '.join(it.bullets)} {it.number or ''}" for it in [*c.items, *c.columns]]
    parts += [f"{n.value} {n.label}" for n in c.numbers]
    if c.table is not None:
        parts += [*c.table.columns, *(x for r in c.table.rows for x in r)]
    return " ".join(p for p in parts if p)


def _shown_sentences(src: "_Source", headline: str, c: SlideContent) -> set[str]:
    """The source's sentences and list leads the slide already says: in its words, or every figure of them written on
    it (the headline, the lines, the figures — a chart's values are not counted: a coincidence of amounts is not the
    same statement)."""
    text = _visible_text_of(headline, c)
    figs = figures(text)
    out = set()
    for x in [*src.sentences, *(g.label for g in src.groups if g.label)]:
        vals = figures(x)
        if said_in(x, text) or (vals and all(any(abs(v - y) <= 1e-6 * max(1.0, abs(v)) for y in figs) for v in vals)):
            out.add(x)
    return out


def _filler_takeaway(takeaway: str, headline: str, c: SlideContent, source: str = "") -> bool:
    """A takeaway that adds nothing: it repeats a line, a figure's label or the formula of the slide; or it has no
    figure and at most one content word the headline does not have; or, without a figure, it does not say what the
    slide's source says (half of its words not the source's: «Увеличение дохода требует оптимизации всех трёх
    направлений», «Рост продаж требует всех изменений»)."""
    lines = [*c.bullets, *c.paragraphs, *(f"{n.label} {n.value}" for n in c.numbers), c.formula or ""]
    lines += [f"{it.title} {it.text}" for it in [*c.items, *c.columns]] + [b for col in c.columns for b in col.bullets]
    if any(x and same_text(takeaway, x) for x in lines):
        return True
    if c.formula and re.search(r"(?i)формул", takeaway):
        return True  # «Формула выручки: покупки × средний чек × рабочие дни» under the formula itself
    if figures(takeaway):
        return False
    new = [w for w in _stems(takeaway) if not _meet(frozenset([w]), _stems(headline))]
    if len(new) <= 1:
        return True
    return bool(source.strip()) and not said_in(takeaway, source, 0.5)


def _tidy_lines(c: SlideContent) -> None:
    """Every line, card and column starts with a capital letter; no trailing period on a short line."""
    c.bullets = [H.cap_first(H.strip_end(b)) for b in c.bullets]
    for it in [*c.items, *c.columns]:
        it.title = H.cap_first(it.title)
        it.bullets = [H.cap_first(H.strip_end(b)) for b in it.bullets]


def _fallback_headline(unit: _Unit, ctx: _Ctx) -> str:
    """A headline when the designer's cannot stay: the source's goal sentence with its figure («Цель — поднять
    средний чек с 300 до 330 рублей»), else its first key figure («Операционная прибыль — 120 000 рублей»), else its
    sentence of a result («На запуск изменений потребуется 180 000 рублей»), when grounding keeps it whole and it is
    short; else the slide's title — never a sentence of context («Кофейня площадью 45 м² рассчитана на 18 посадочных
    мест»)."""
    src = _read_source(unit.text)
    goal = _goal_sentence(src.sentences)
    result = _takeaway_sentence(src.sentences, [], set())
    cands = ([goal] if goal and _GOAL_RE.match(goal) else []) + key_lines(unit.text) + ([result] if result else [])
    for g in (H.strip_end(x) for x in cands):
        try:
            ok = ctx.index is None or not ctx.index.clean(g).bad
        except Exception:  # noqa: BLE001
            ok = False
        if ok and len(g.split()) <= 12:
            return H.cap_first(g)
    return unit.title


def _invented_figures(text: Optional[str], ctx: Optional[_Ctx]) -> bool:
    """The line has a figure the brief does not give (grounding's check; False when it cannot be run)."""
    if not text or ctx is None or ctx.index is None:
        return False
    try:
        return bool(ctx.index.clean(text).bad)
    except Exception:  # noqa: BLE001 - grounding checks the deck again anyway
        return False


# a cause or an effect claimed: «… снижает операционную прибыль до 13,3%», «объясняется ростом выручки и контролем
# расходов», «позволяет сосредоточиться на…»
_CAUSE_RE = re.compile(
    r"(?<![\wё])(?:снижа\w*|понижа\w*|повыша\w*|увеличива\w*|уменьша\w*|привод\w*|привед[её]т|позволя\w*|обеспечива\w*|"
    r"влия\w*|объясня\w*|вызыва\w*|требу\w*|из-за|благодаря|вследствие|поэтому|следовательно|потому\s+что|за\s+сч[её]т|в\s+результате)(?![\wё])",
    re.I,
)


def invented_cause(line: Optional[str], source: str) -> bool:
    """The line claims a cause or an effect («Неравномерное распределение расходов снижает прибыль до 13,3%») with a
    word of cause the slide's source does not use: a claim the brief does not make."""
    if not line:
        return False
    src = (source or "").lower()
    for m in _CAUSE_RE.finditer(line):
        w = m.group(0).lower()
        stem = w[:5] if len(w) > 5 and " " not in w and "-" not in w else w
        if stem not in src:
            return True
    return False


# «Дополнительные покупки при среднем чеке 330 ₽»: a noun and a condition, the result cut off
_CONDITION_TAIL_RE = re.compile(r"\s+(?:при|с\s+учетом|с\s+учётом)\s+[^—–:;]*$", re.I)
_CONDITION_ONLY_RE = re.compile(r"^[^\d]*?(?<![\wё])(?:при|с\s+учетом|с\s+учётом|для|за\s+сч[её]т|в\s+случае)\s[^—–:]*\d", re.I)


def takeaway_states(text: Optional[str]) -> bool:
    """A takeaway that states something (a figure, a verb, a dash or a colon for the verb: «Рост постепенный: это
    прогноз, а не гарантия»), not a label or a list announced («Три ключевых направления для роста прибыли»), nor a
    phrase whose only figures are a condition's («Дополнительные покупки при среднем чеке 330 ₽» — its result is cut
    off)."""
    t = (text or "").strip()
    if not t:
        return False
    has_verb = any(m.group(0).lower() not in _NOT_VERBS for m in _VERB_RE.finditer(t))
    if not has_verb and not re.search(r"\s[—–]\s|:\s", t) and _CONDITION_ONLY_RE.match(t):
        return False
    return headline_states(t) or (bool(re.search(r":\s", t)) and not _QUESTION_HEAD_RE.search(t))


def _copied_context(subtitle: str, headline: str, unit: _Unit) -> bool:
    """A subtitle that is a sentence of the slide's source copied as it is, and neither the slide's goal or key figure
    nor about the headline's subject: context, not a subtitle."""
    if unit.spec is None or not (unit.text or "").strip():
        return False
    src = _read_source(unit.text)
    copy = next((sn for sn in src.sentences if same_text(subtitle, sn)), None)
    if copy is None:
        return False
    if _GOAL_RE.match(copy) or any(same_text(copy, k) for k in key_lines(unit.text)):
        return False
    mine, theirs = _subject_stems(subtitle), _subject_stems(headline)
    shared = sum(1 for x in mine if _meet(frozenset([x]), theirs))
    return shared * 2 < max(1, len(mine))


# «… показаны графически», «на диаграмме видно»: a line about the slide, not about its subject
_SHOWN_RE = re.compile(r"(?<![\wё])(?:показан\w*\s+(?:графически|на\s+(?:графике|диаграмме|слайде))|на\s+(?:графике|диаграмме|слайде)\s+(?:видн|показан|представлен)\w*|представлен\w*\s+(?:графически|наглядно))", re.I)
# a sentence about the deck's making, not its subject: «вывод сделан на основе текста брифа», «как указано в брифе»
_META_RE = re.compile(r"(?<![\wё])(?:бриф\w*|brief|промпт\w*|пользовател\w*\s+(?:просил|указал))", re.I)


def clean_notes(notes: str, unit: _Unit, charts: list, ctx: Optional[_Ctx], changes: Optional[list[str]] = None) -> str:
    """The designer's speaker notes without what the slide's source does not say: a sentence with no figure whose words
    are mostly not the source's («Это позволяет сосредоточиться на оптимизации закупок», «Риски требуют постоянного
    мониторинга»), a ranking the data contradicts («… а прочие расходы — наименьшую»). Notes left empty take the
    source's sentences the slide does not show (the explanations and calculations of the brief)."""
    text = " ".join((notes or "").split())
    if unit.spec is None or not (unit.text or "").strip():
        return text
    keep, gone = [], []
    for sn in H.split_sentences(text) or ([text] if text else []):
        if not sn.strip():
            continue
        if _META_RE.search(sn) or comparative_false(sn, charts, ctx) or invented_cause(sn, unit.text) or (not figures(sn) and not said_in(sn, unit.text, 0.6)):
            gone.append(sn)
            continue
        keep.append(sn)
    if gone and changes is not None:
        changes.append(f"slide {unit.key}: notes the source does not say dropped: {' '.join(gone)[:120]}")
    if not keep and gone:
        src = _read_source(unit.text)
        keep = [H.strip_end(sn) + "." for sn in src.sentences if not _ASK_RE.match(sn)][:4]
    return " ".join(keep)


def design_from_answer(ans: SlideDesignAnswer, unit: _Unit, ctx: _Ctx) -> Optional[_Design]:
    """The designer's answer as a slide (density limits, charts resolved and checked); None when nothing of it is
    usable (the rules design the slide then)."""
    changes: list[str] = []
    c = SlideContent(
        bullets=[b for b in ans.bullets if b.strip()][:MAX_BULLETS],
        paragraphs=[p for p in ans.paragraphs if p.strip()][:2],
        items=ans.items[:MAX_ITEMS],
        numbers=[n for n in ans.numbers if n.value.strip()][:MAX_NUMBERS],
        table=_clip_table(ans.table),
        chart=_resolve_chart(ans.chart, unit, ctx, changes),
        chart2=_resolve_chart(ans.chart2, unit, ctx, changes),
        columns=ans.columns[:3],
        formula=ans.formula,
        quote=ans.quote if _quote_ok(ans.quote, ctx) else None,
        quote_author=ans.quote_author if _quote_ok(ans.quote, ctx) else None,
    )
    if c.chart is None and c.chart2 is not None:
        c.chart, c.chart2 = c.chart2, None
    # a «key figure» that is words («Высокая стоимость», «Низкие эксплуатационные расходы») is a statement, not a figure:
    # it cannot stand large in a row of figures (it overflows the frame) — it becomes a line of the slide
    wordy = [n for n in c.numbers if not re.search(r"\d", n.value) and (len(n.value.split()) >= 2 or len(n.value.strip()) > 12)]
    if ctx.written:
        # the writer's text (a topic): a year or a day of a month is a date, never a slide's key figure («1999 г»
        # in large type over «занимает должности главы правительства»)
        dated = [n for n in c.numbers if _date_callout(n, source=unit.text)]
        if dated:
            c.numbers = [n for n in c.numbers if n not in dated]
            lines = [f"{H.strip_end(n.value)} — {H.strip_end(n.label)}" if n.label.strip() else H.strip_end(n.value) for n in dated]
            c.bullets = (c.bullets + [x for x in lines if x not in c.bullets and len(x.split()) >= 3])[:MAX_BULLETS]
            changes.append(f"slide {unit.key}: dates given as key figures → lines: {'; '.join(lines)[:120]}")
    if wordy:
        c.numbers = [n for n in c.numbers if n not in wordy]
        case_text = ctx.brief.text if ctx is not None else unit.text
        lines = [f"{H.cap_first(H.strip_end(n.label))}: {_low_first(H.strip_end(n.value), case_text)}" if n.label.strip() else H.cap_first(H.strip_end(n.value)) for n in wordy]
        c.bullets = (c.bullets + [x for x in lines if x not in c.bullets])[:MAX_BULLETS]
        changes.append(f"slide {unit.key}: words given as key figures → lines: {'; '.join(lines)[:120]}")
    spec_items = unit.spec.items if unit.spec is not None else []
    if ans.kind in ("timeline", "process", "cards") and not c.items and len(spec_items) >= 2:
        empty = not (c.bullets or c.paragraphs or c.numbers or c.table or c.chart or c.columns or c.quote or c.formula)
        if empty or (ctx.written and ans.kind == "timeline"):
            # «timeline» answered without its entries (a slow host cuts the answer): the slide's own list, which the
            # analyst read from the source (date → title, event → text), is the form the designer chose
            c.items = [SlideItem(title=H.strip_end(it.title), text=H.strip_end(it.text or "")) for it in spec_items[:MAX_ITEMS]]
            changes.append(f"slide {unit.key}: {ans.kind} without items: the slide's list of the source used ({len(c.items)} items)")
    listed = [it for it in c.items if len(it.bullets) >= 2]
    if listed and not c.columns:
        if 2 <= len(c.items) <= 3 and len(listed) == len(c.items):
            # «two_column» answered with its lists under «items»: the lists are columns (a card shows no list)
            c.columns, c.items = [SlideItem(title=it.title, text=it.text, number=it.number, bullets=list(it.bullets)) for it in c.items], []
            changes.append(f"slide {unit.key}: blocks with lists given as cards → columns")
        else:
            for it in listed:  # a card of a list: its lines as its text, never lost
                if not it.text:
                    it.text = "; ".join(H.strip_end(b) for b in it.bullets[:4])
                    it.bullets = []
    body = c.model_dump()
    if not (c.bullets or c.paragraphs or c.items or c.numbers or c.table or c.chart or c.columns or c.quote or c.formula):
        return None
    kind = ans.kind if ans.kind and ans.kind not in FRAME_KINDS else ""
    needs = {"chart": c.chart is not None, "table": c.table is not None, "stat_row": len(c.numbers) >= 2, "big_number": bool(c.numbers),
             "cards": bool(c.items), "process": bool(c.items), "timeline": bool(c.items), "two_column": bool(c.columns),
             "comparison": bool(c.columns or c.items), "quote": bool(c.quote), "team": bool(c.items), "image_text": True,
             "bullets": bool(c.bullets or c.paragraphs)}
    if not kind or not needs.get(kind, False):
        kind = kind_by_content(body)
        if kind in FRAME_KINDS:
            kind = "big_number" if c.formula else "bullets"
    if kind == "stat_row" and len(c.numbers) == 1:
        kind = "big_number"
    if c.numbers:
        fixed = fix_callouts(c.numbers, unit, ctx)
        if [(n.value, n.label) for n in fixed] != [(n.value, n.label) for n in c.numbers]:
            changes.append(f"slide {unit.key}: figures «{'; '.join(f'{n.value} · {n.label}' for n in c.numbers)[:120]}» → «{'; '.join(f'{n.value} · {n.label}' for n in fixed)[:120]}»")
            c.numbers = fixed
        if kind == "stat_row" and len(c.numbers) == 1:
            kind = "big_number"
    kind = _fit_form(kind, c, changes, unit.key, ctx.brief.text if ctx is not None else unit.text)
    _tidy_lines(c)
    charts = [x for x in (c.chart, c.chart2) if x is not None]
    # a line comparing parts («Маркетинг и прочие расходы — минимальная доля») that the slide's own data contradicts
    for field_ in ("bullets", "paragraphs"):
        lines = getattr(c, field_)
        keep = [b for b in lines if not comparative_false(b, charts, ctx)]
        if len(keep) < len(lines):
            changes.append(f"slide {unit.key}: a comparison the slide's data contradicts dropped: {[b for b in lines if b not in keep][0][:80]}")
            setattr(c, field_, keep)
    # a pie of amounts shows shares of its own whole: a line with a share of another base for one of its parts
    # («Продукты — 35% от выручки» next to a pie that draws them at 40% of the costs) contradicts the legend
    pie = next((x for x in charts if x.type in ("pie", "doughnut") and (x.unit or "").strip() != "%"), None)
    if pie is not None and c.bullets:
        cats = [_stems(x) for x in pie.categories]
        keep = [b for b in c.bullets if not (re.search(r"\d\s?%", b) and any(_meet(_stems(b), s) for s in cats if s))]
        if len(keep) < len(c.bullets):
            changes.append(f"slide {unit.key}: a share of another base for a part the pie shows dropped: {[b for b in c.bullets if b not in keep][0][:80]}")
            c.bullets = keep
    raw_head = H.strip_end(ans.headline or "") or unit.title
    if ctx.index is not None:
        try:
            from verstka.planning.grounding import PAST_CHANGE_RE, to_future

            # a hedge on the wrong side of the true value is turned, a forecast told as done is told as a plan —
            # before the check, which would otherwise cut the figure and leave «… выросла почти»
            fixed = ctx.index.fix_hedges(raw_head)
            if PAST_CHANGE_RE.search(fixed) and ctx.index.forecast_line(fixed):
                fixed = to_future(fixed)
            if fixed != raw_head:
                changes.append(f"slide {unit.key}: headline «{raw_head[:80]}» → «{fixed[:80]}» (a plan is not a result; the hedge's side)")
                raw_head = fixed
        except Exception:  # noqa: BLE001 - the compiler's guard runs again anyway
            pass
    headline = _headline_checked(raw_head, unit, ctx, changes)
    if _ANNOUNCE_RE.search(headline) and not headline_states(headline):
        # «Пять стратегий для роста числа покупок»: a list announced (and counted wrong, as often as not) — the source's
        # goal with its figure is a conclusion; no model call for it
        stated = _fallback_headline(unit, ctx)
        if stated and stated != unit.title and headline_states(stated):
            changes.append(f"slide {unit.key}: headline «{headline[:80]}» announced a list → «{stated[:80]}»")
            headline = stated
    if comparative_false(headline, charts, ctx):
        changes.append(f"slide {unit.key}: headline «{headline[:80]}» contradicts the slide's data")
        headline = _fallback_headline(unit, ctx)
    footnote = ans.footnote
    if footnote and not (unit.spec is not None and unit.spec.footnote):
        if not said_in(footnote, unit.text):
            # a footnote the slide's source does not state («Результаты зависят от…»): a disclaimer nobody asked for
            changes.append(f"slide {unit.key}: footnote not in the slide's source dropped: {footnote[:80]}")
            footnote = None
        elif not _CAVEAT_RE.search(footnote):
            # a statement of the source set in small print («Маркетинговый бюджет вырастет до 35 000 ₽»): content, a line
            for sn in H.split_sentences(footnote) or [footnote]:
                if len(c.bullets) < MAX_BULLETS and H.strip_end(sn):
                    c.bullets.append(H.strip_end(sn))  # a line per sentence
            changes.append(f"slide {unit.key}: footnote that is content moved to the slide's lines: {footnote[:80]}")
            footnote = None
    takeaway = H.strip_end(ans.takeaway or "") or None
    if takeaway and adds_nothing(takeaway, headline):
        takeaway = None  # a conclusion said twice (in other words: «Рост выручки на 26,5%» under «Выручка вырастет на 26,5%»)
        changes.append(f"slide {unit.key}: the takeaway repeated the headline, dropped")
    if takeaway and not takeaway_states(takeaway):
        # «Три ключевых направления для роста прибыли»: a label, not a conclusion
        changes.append(f"slide {unit.key}: the takeaway «{takeaway[:80]}» states nothing, dropped")
        takeaway = None
    if takeaway and not (unit.spec is not None and unit.spec.takeaway) and invented_cause(takeaway, unit.text):
        changes.append(f"slide {unit.key}: the takeaway «{takeaway[:80]}» claims a cause the brief does not state, dropped")
        takeaway = None
    if takeaway and _invented_figures(takeaway, ctx):
        # «На зарплаты и продукты уходит 65% всех расходов» (they are 75%): grounding would cut the figure out and leave
        # a broken line — the source's own result takes its place
        changes.append(f"slide {unit.key}: the takeaway «{takeaway[:80]}» has figures not in the brief, dropped")
        takeaway = None
    if takeaway and figures(takeaway) and any(same_text(takeaway, b) for b in c.bullets):
        # a result with its figure said twice: the conclusion strip keeps it, the line under the block goes
        c.bullets = [b for b in c.bullets if not same_text(takeaway, b)]
        changes.append(f"slide {unit.key}: a line repeating the takeaway dropped")
    if takeaway and (comparative_false(takeaway, charts, ctx) or _filler_takeaway(takeaway, headline, c, unit.text)):
        changes.append(f"slide {unit.key}: the takeaway «{takeaway[:80]}» repeated a line or added nothing, replaced by the source's result")
        takeaway = None
    if takeaway is None and unit.spec is not None and not unit.spec.takeaway:
        # the source's own sentence with its result and figure («+90 000 ₽ выручки в месяц — это выручка, а не прибыль»)
        src = _read_source(unit.text)
        shown = _shown_sentences(src, headline, c)
        takeaway = _takeaway_sentence(src.sentences, [g.label for g in src.groups if g.label], shown)
        if takeaway and (adds_nothing(takeaway, headline) or _filler_takeaway(takeaway, headline, c, unit.text)):
            takeaway = None
    subtitle = H.strip_end(ans.subtitle or "") or None
    notes = ans.notes or ""
    if subtitle and _copied_context(subtitle, headline, unit):
        # a sentence of the source copied under the headline («Кофейня площадью 45 м² рассчитана на 18 посадочных
        # мест» under «Кофе — 60% выручки»): context for the speaker, not the slide's subtitle
        changes.append(f"slide {unit.key}: the subtitle «{subtitle[:80]}» copies the source's context: moved to the notes")
        if not said_in(subtitle, notes, 0.8):
            notes = f"{subtitle}. {notes}".strip()
        subtitle = None
    notes = clean_notes(notes, unit, charts, ctx, changes)
    s = OutlineSlide(
        id=unit.key, kind=PatternKind(kind), section=unit.section, headline=headline, subtitle=subtitle, content=c,
        notes=notes, takeaway=takeaway, footnote=footnote, rationale=ans.rationale or None,
        spec_ref=unit.spec.number if unit.spec else None,
    )
    if not s.rationale:
        s.rationale = _why(s)
    d = _Design(unit=unit, slide=s, by="model", changes=changes)
    d.alternatives = [a for a in ans.alternatives if a.kind != kind or (a.kind == "chart" and a.chart_type and c.chart is not None and a.chart_type != c.chart.type)][:2]
    if len(d.alternatives) < 2:
        for a in auto_alternatives(s):
            if len(d.alternatives) < 2 and all(a.kind != b.kind for b in d.alternatives):
                d.alternatives.append(a)
    return d


def enforce_requests(d: _Design, ctx: _Ctx) -> None:
    """The user's requests for the slide win over the design: the requested charts (with the requested type), the
    table, the formula, the footnote and the user's own conclusion."""
    spec = d.unit.spec
    if spec is None or d.unit.frame:
        return
    s, c = d.slide, d.slide.content
    s.spec_ref = spec.number
    wanted = spec.charts[:2]
    if wanted:
        det = _request_charts(d.unit, ctx)
        det += [None] * (len(wanted) - len(det))
        free = [x for x in (c.chart, c.chart2) if x is not None]
        got: list[Optional[ChartSpec]] = [None] * len(wanted)

        def take(i: int, pick: Callable[[ChartSpec], bool]) -> None:
            m = next((x for x in free if pick(x)), None)
            if m is not None:
                got[i] = m
                free.remove(m)

        # the designer's charts go to the requests they answer: the request's own data first, then the requested kind,
        # then (a request whose data the brief does not give) in order — never a pie of one request retyped as the
        # line of another
        # (the same figures under the brief's labels: a chart with the values swapped between its categories matches
        # nothing — the brief's data answers the request then)
        for i in range(len(wanted)):
            if det[i] is not None:
                take(i, lambda x, i=i: _similar_data(det[i], x) and not label_conflicts(det[i], x))
        for i, req in enumerate(wanted):
            if got[i] is None and req.type:
                # a chart of the requested kind answers a request whose data the brief gives only when it shows that
                # data (one extra point at most, «начиная с текущих …»): never one that mixes in another measure
                take(i, lambda x, i=i, req=req: _same_family(req.type, x.type) and (det[i] is None or (_covers(det[i], x) and not label_conflicts(det[i], x))))
        for i in range(len(wanted)):
            if got[i] is None and det[i] is None:
                take(i, lambda x: True)
        for i, req in enumerate(wanted):
            if got[i] is None and det[i] is not None:
                got[i] = det[i]
                d.changes.append(f"slide {d.unit.key}: the requested chart «{req.what[:60]}» added from the brief's data")
            elif got[i] is not None and req.type and not _same_family(req.type, got[i].type):
                d.changes.append(f"slide {d.unit.key}: chart type {got[i].type} → {req.type} (asked in the brief)")
                got[i].type = req.type
        placed_ = [x for x in got if x is not None]
        # a chart of the designer's that no request took stays, unless it draws what a requested one already shows (or
        # the brief's figures under other labels)
        charts = placed_ + [x for x in free if not any(_similar_data(p, x) or _same_shares(p, x) or _covers(p, x) for p in placed_) and not any(d_ is not None and label_conflicts(d_, x) for d_ in det)]
        c.chart = charts[0] if charts else None
        c.chart2 = charts[1] if len(charts) > 1 else None
        if c.chart is not None and s.kind != PatternKind.chart:
            s.kind = PatternKind.chart
            s.rationale = _why(s, requested=True)
    if spec.table:  # the user asked for a table («Сделай сравнительную таблицу»); a table the brief only contains is data
        if c.table is None:
            c.table = _table_for(d.unit, ctx)
            if c.table is not None:
                d.changes.append(f"slide {d.unit.key}: the requested table added from the brief")
        if c.table is not None and not wanted and s.kind != PatternKind.table:
            s.kind = PatternKind.table
            c.chart, c.chart2 = None, None
            s.rationale = _why(s, requested=True)
    if spec.formula:
        # the user's calculation («Покажи формулу: 100 × 300 × 30 = 900 000 рублей»): the designer's words may name its
        # factors («100 покупок в день × 300 ₽ × 30 дней = 900 000 ₽»), its figures and operators are the user's; a
        # bare formula gets its factors named from the slide's text
        from verstka.planning.compile import label_formula, same_formula

        if not same_formula(c.formula, spec.formula):
            if c.formula:
                d.changes.append(f"slide {d.unit.key}: the designer's formula «{c.formula[:60]}» → the brief's")
            c.formula = spec.formula
        if not re.search(r"[а-яё]{3,}.*[×x*·÷/+]", (c.formula or "").split("=")[0], re.I):
            c.formula = label_formula(c.formula, d.unit.text) or c.formula
    if spec.footnote and not same_text(s.footnote, spec.footnote):
        s.footnote = spec.footnote  # the user's footnote, in the user's words
    if spec.takeaway:
        s.takeaway = spec.takeaway
        if (same_text(s.takeaway, s.headline) or adds_nothing(s.headline, s.takeaway)) and d.unit.title and not same_text(d.unit.title, s.takeaway):
            # the user's conclusion is the takeaway: the headline states the slide's key figure (its goal sentence),
            # else it goes back to the user's heading — not a copy of the conclusion
            s.headline = _fallback_headline(d.unit, ctx)
    _split_merged_lists(d)
    if s.kind == PatternKind.chart and c.chart is None:
        s.kind = PatternKind(kind_by_content(c.model_dump()))


_ORD_TOKEN_RE = re.compile(r"(?<![\d.,])\d{1,2}\s*-\s*(?:й|ый|ой|ий|го|ого|его|му|ому|м|ом|я|е)(?![\wё])|(?<![\wё])(?:месяц|квартал|неделя|этап|шаг)\s+\d{1,2}(?!\d)", re.I)


def _plain_figures(text: str) -> list[float]:
    """The figures of a line that are values — not a step's number («6-й месяц», «Месяц 2»)."""
    return figures(_ORD_TOKEN_RE.sub(" ", text or ""))


def _content_text(s: OutlineSlide) -> str:
    """What the slide's block says (not its headline, takeaway or notes): lines, cards, columns, figures, formula."""
    c = s.content
    parts = [c.formula or "", *c.bullets, *c.paragraphs]
    parts += [f"{it.title} {it.text} {' '.join(it.bullets)}" for it in [*c.items, *c.columns]]
    parts += [f"{n.value} {n.label}" for n in c.numbers]
    return " ".join(p for p in parts if p)


def takeaway_ok(t: Optional[str], s: OutlineSlide, unit: _Unit, ctx: Optional[_Ctx]) -> Optional[str]:
    """Why a takeaway cannot stay on the slide (None: it can): it states nothing, repeats the headline or what the
    slide's block already says (its cards, its formula: «100 покупок в день × 300 ₽ × 30 дней» under the formula),
    claims a cause the brief does not state, or has a figure the brief does not give. The user's own conclusion
    always stays."""
    if not t:
        return None
    if unit.spec is not None and unit.spec.takeaway and same_text(t, unit.spec.takeaway):
        return None
    if not takeaway_states(t):
        return "states nothing"
    if adds_nothing(t, s.headline):
        return "repeats the headline"
    if _CONDITION_TAIL_RE.search(t) and adds_nothing(_CONDITION_TAIL_RE.sub("", t), s.headline):
        return "repeats the headline with a condition"  # «… 22 770 ₽ в месяц при выручке 1 138 500 ₽»
    body = _content_text(s)
    if body and adds_nothing(t, body):
        return "repeats the slide's block"
    if (unit.text or "").strip() and invented_cause(t, unit.text):
        return "claims a cause the brief does not state"
    if _META_RE.search(t) or _SHOWN_RE.search(t):
        return "speaks of the slide, not of the subject"
    if _invented_figures(t, ctx):
        return "has figures not in the brief"
    return None


_SPEC_HEAD_LINE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:слайд|slide)\s*\d{1,2}\b.*$", re.I | re.M)


def _frame_text(ctx: _Ctx) -> str:
    """The brief without the slides it describes: its title line, its context and its rules — what every slide may say
    («за 6 месяцев» of «Кофейня «Точка кофе»: план увеличения прибыли за 6 месяцев»)."""
    rest = ctx.brief.text or ""
    for sp in ctx.structure.specs:
        if sp.text:
            rest = rest.replace(sp.text, " ")
    return _SPEC_HEAD_LINE_RE.sub(" ", rest)


def unit_index(unit: _Unit, ctx: Optional[_Ctx]) -> Any:
    """Grounding's index of one slide's own source (its text, its data, the brief's frame): a figure it does not give
    or derive comes from another slide («Операционная прибыль вырастет на 112,3%» on the slide of the investments)."""
    if ctx is None or not (unit.text or "").strip():
        return None
    with ctx.lock:
        if unit.key in ctx.unit_index:
            return ctx.unit_index[unit.key]
    try:
        from verstka.planning.grounding import BriefIndex

        extra = [f"{s.name}: " + "; ".join(f"{c} — {_fmt_ru(v, s.unit)}" for c, v in zip(s.categories, s.values)) for s in (ctx.series.get(x) for x in unit.series_ids) if s is not None]
        extra += [" ".join([*t.columns, *(c for r in t.rows for c in r)]) for t in (ctx.tables.get(x) for x in unit.table_ids) if t is not None]
        idx = BriefIndex("\n".join([unit.text, *extra, _frame_text(ctx)]))
        idx.use_structure(BriefStructure(series=[ctx.series[x] for x in unit.series_ids if x in ctx.series], tables=[ctx.tables[x] for x in unit.table_ids if x in ctx.tables]))
    except Exception:  # noqa: BLE001 - the deck-wide grounding still checks every figure
        idx = None
    with ctx.lock:
        ctx.unit_index[unit.key] = idx
    return idx


def foreign_figures(text: Optional[str], unit: _Unit, ctx: Optional[_Ctx]) -> list[str]:
    """The figures of a line that the slide's own source neither gives nor derives (they are another slide's, or
    nobody's)."""
    idx = unit_index(unit, ctx)
    if idx is None or not text:
        return []
    try:
        from verstka.planning.grounding import figures as gfigs
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in gfigs(text):
        if f.date is not None or f.approx:
            continue
        if idx.verdict(f) == "bad" and not re.fullmatch(r"\d{1,2}", text[f.start : f.uend].strip()):
            out.append(text[f.start : f.uend].strip())
    return out


# the words of a deck about any business («статья расходов», «направление», «этап», «мера»): never a claim of their own
_DECK_WORDS = ("стат", "направлен", "фактор", "этап", "шаг", "мер", "задач", "итог", "результат", "эффект", "действ", "пункт")


def _unbriefed_words(line: str, ctx: Optional[_Ctx]) -> list[str]:
    """The content words of a line without figures that the brief nowhere uses (a classification or a claim of the
    model's: «Аренда и зарплаты — основные постоянные расходы» when the brief never calls anything «постоянные»). A
    line with a figure is grounding's to judge."""
    if ctx is None or ctx.index is None or figures(line):
        return []
    try:
        from verstka.planning.grounding import _GENERIC_STEMS, content_stems

        return [x for x in content_stems(line, neutral=True) if not x.startswith(_GENERIC_STEMS) and not x.startswith(_DECK_WORDS) and not ctx.index.stems.has(x)]
    except Exception:  # noqa: BLE001
        return []


_FUNCTION_WORDS = frozenset(
    """с со в во на для по до от из к ко за при без через про об о у и а или но либо как чтобы если когда где
    между перед после над под""".split()
)
_COLON_LINE_RE = re.compile(r"^(?P<head>[^:\d]{2,60}?):\s+(?P<first>[A-ZА-ЯЁ][^\s,;:]*)")
_DASH_LOW_RE = re.compile(r"(?<=\S)[ \u00a0][—–][ \u00a0](?P<first>[а-яё][а-яё-]*)")


def _lowered(word: str, text: str) -> bool:
    """The word may start in lowercase: not an abbreviation («NPS», «ВКС»), not a Latin name, not a quotation, and not a
    name — a word the brief writes with its capital in the middle of a sentence («… в Москве»)."""
    core = word.strip("«»\"'()")
    if core.lower() in _FUNCTION_WORDS:
        return True
    if not core or core[:1] in "«\"" or re.match(r"[A-Za-z]", core) or (len(core) >= 2 and core.isupper()) or any(ch.isupper() for ch in core[1:]):
        return False
    stem = core if len(core) <= 5 else core[: len(core) - 2]
    if re.search(rf"(?<![\wё]){re.escape(stem.lower())}", text or ""):
        return True  # the brief writes it in lowercase: a common word
    return not re.search(rf"(?:[a-zа-яё0-9,;:)»]\s+|«){re.escape(stem)}", text or "")


def _keeps_capital(word: str, text: str) -> bool:
    """A word that keeps its capital at the start of a line's second half («1937 год — Япония начала войну», «Итог —
    Германия капитулировала»): an abbreviation, a Latin name, or a name the text writes with its capital inside a
    sentence or after a dash inside a line («войну Германии», «года — Германия») and never in lowercase as the word
    itself («германские войска» is another word). Function words never («С пятью офисами» → «с пятью»)."""
    core = word.strip("«»\"'()")
    if not core or not core[:1].isupper() or core.lower() in _FUNCTION_WORDS:
        return False
    if not _lowered(core, text):
        return True
    if len(core) < 4:
        return False
    own = core.lower()[: len(core) - 1]  # «германи» of «Германия»/«Германии», not «германские»
    if re.search(rf"(?<![\wё]){re.escape(own)}", text or ""):
        return False
    stem = core if len(core) <= 5 else core[: len(core) - 2]
    return bool(re.search(rf"(?:[a-zа-яё0-9,;:)»][ \t ]+|«|\S[ \t ]+[—–][ \t ]+){re.escape(stem)}", text or ""))


_DATE_TITLE_RE = re.compile(rf"(?<!\d)(?:1[5-9]|20)\d{{2}}(?!\d)|{_MONTHS_GEN}|(?:^|\s)(?:январ|феврал|март|апрел|май|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", re.I)


def _low_first(x: str, text: str = "", only_if_next_lower: bool = False, date_title: bool = False) -> str:
    """The line with its first letter in lowercase where Russian needs it after a dash or a colon — not a name, an
    abbreviation or a Latin word (_keeps_capital with the text the line comes from: the brief or the slide's source).
    `only_if_next_lower`: lowercase only a word whose second letter is lowercase («ВКС» stays). `date_title` (the line
    continues a date: «Июнь 1940 — Италия присоединилась…»): with the text, a word starts in lowercase only when the
    text writes it so somewhere (a country named only at a sentence's start is still a name)."""
    words = (x or "").split()
    if not words:
        return x
    if only_if_next_lower and not x[1:2].islower():
        return x
    first = words[0]
    if _keeps_capital(first, text):
        return x
    core = first.strip("«»\"'()")
    if date_title and text and core[:1].isupper() and core.lower() not in _FUNCTION_WORDS:
        own = core.lower()[: max(3, len(core) - 1)]
        if not re.search(rf"(?<![\wё]){re.escape(own)}", text):
            return x
    if not text:
        keep = len(first) >= 2 and first.isupper() or bool(re.match(r"[A-Za-z]", first))  # «NPS», «VK Tech»
        if keep:
            return x
    return x[:1].lower() + x[1:]


_GROWTH_NOUN = {"роста": "рост", "прироста": "прирост", "снижения": "снижение", "сокращения": "сокращение", "падения": "падение"}
# «— это 112,3% роста» → «— рост на 112,3%»: a change said the way a person says it (only a clause's own end: «12% роста
# выручки» is left alone)
_PCT_GROWTH_RE = re.compile(
    r"(?P<lead>^|[—–,:]\s*)(?:это\s+)?(?P<v>[+\-−]?\d[\d\s  ]*(?:[.,]\d+)?\s?%)\s+(?P<w>роста|прироста|снижения|сокращения|падения)(?=\s*(?:$|[.,;!?)]))",
    re.I,
)


def plain_change(line: Optional[str]) -> Optional[str]:
    if not line:
        return line
    out = _PCT_GROWTH_RE.sub(lambda m: f"{m.group('lead')}{_GROWTH_NOUN[m.group('w').lower()]} на {m.group('v')}", line)
    return H.cap_first(out) if out != line else line


def trim_chart_restatement(line: Optional[str], charts: list) -> Optional[str]:
    """A line beside a chart that first says again what the chart draws and then adds a figure of its own
    («Операционная прибыль вырастет до 254 795 рублей в месяц — рост на 112,3%» over the columns 120 000 and
    254 795): the part that adds, on its own («Рост на 112,3%»). The line as it is when nothing of it repeats the
    chart, or when what is left would not stand."""
    if not line or not charts:
        return line
    vals = [v for ch in charts for sr in ch.series for v in sr.values]
    m = re.match(r"^(?P<head>.*\d.*?)\s*\((?P<sign>[+\-−])\s?(?P<v>\d+(?:[.,]\d+)?)\s?%\)\s*$", line)
    if m:  # «… до 254 795 рублей в месяц (+112,3%)»
        head, rest = m.group("head"), ("Рост на " if m.group("sign") == "+" else "Снижение на ") + m.group("v") + "%"
    else:
        parts = re.split(r"\s+[—–]\s+(?=[^\d]*\d)", line, maxsplit=1)
        if len(parts) != 2:
            return line
        head, rest = parts
    hv, rv = _plain_figures(head), _plain_figures(rest)
    on_chart = lambda v: any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) or (abs(v) >= 1000 and abs(v - x) <= 500) for x in vals)  # noqa: E731
    if hv and all(on_chart(v) for v in hv) and rv and not all(on_chart(v) for v in rv) and len(rest.split()) >= 2:
        return H.cap_first(H.strip_end(rest))
    return line


def polish_case(s: OutlineSlide, text: str) -> None:
    """Capitals where Russian has them: the text after a label's colon starts in lowercase («Партнёрства: с пятью
    ближайшими офисами», «Меры: учёт остатков»), and so does a card's text that continues its title with a preposition or
    a conjunction («Дневные предложения» · «с 15:00 до 18:00») — never a name or an abbreviation («Партнёр: VK Tech»,
    «Город: Москва» when the brief writes «Москва» with its capital)."""
    def colon(line: str) -> str:
        m = _COLON_LINE_RE.match(line or "")
        if m and _lowered(m.group("first"), text):
            i = m.start("first")
            return line[:i] + line[i].lower() + line[i + 1:]
        return line

    def name(line: str) -> str:
        # a name lowercased after a dash by a form that joined a card's title and text («1937 год — япония начала
        # войну», «Апрель — июнь 1940 — германия завоевала…») gets its capital back when the brief writes it so
        # («В Азии Япония вела войну»)
        out = line or ""
        for m in list(_DASH_LOW_RE.finditer(out)):
            w = m.group("first")
            if _keeps_capital(w[:1].upper() + w[1:], text):
                i = m.start("first")
                out = out[:i] + out[i].upper() + out[i + 1:]
        return out

    c = s.content
    c.bullets = [name(colon(b)) for b in c.bullets]
    c.paragraphs = [name(colon(b)) for b in c.paragraphs]
    for n in c.numbers:
        n.label = colon(n.label or "")
    for it in [*c.items, *c.columns]:
        it.bullets = [name(colon(b)) for b in it.bullets]
        t = (it.text or "").strip()
        first = t.split()[0] if t.split() else ""
        if it.title and first and first[:1].isupper() and first.lower() in _FUNCTION_WORDS:
            it.text = t[:1].lower() + t[1:]
        elif it.text:
            it.text = colon(it.text)
            if it.title and first[:1].islower() and _keeps_capital(first[:1].upper() + first[1:], text):
                it.text = it.text[:1].upper() + it.text[1:]
    if s.takeaway:
        s.takeaway = colon(s.takeaway)


_YEAR_VALUE_RE = re.compile(r"^(?:1[5-9]|20)\d{2}\s*(?:г\.?|год\w*)?$", re.I)


def _years_only(nums: list[NumberCallout]) -> bool:
    """Every «key figure» is a year («1998 г», «2021 год», «2023»): dates, never a row of figures."""
    return bool(nums) and all(_YEAR_VALUE_RE.match(" ".join((n.value or "").split())) for n in nums)


def _years_as_timeline(d: _Design) -> None:
    """A row of years («1998 г» · «— основана как почтовый сервис Mail.ru», «2021 г» · …) is a timeline: each year the
    title of a step, its label (without the leading dash) the step's text; one or two years become lines."""
    s, c = d.slide, d.slide.content
    if s.kind not in (PatternKind.stat_row, PatternKind.big_number) or not _years_only(c.numbers) or c.chart is not None or c.table is not None:
        return
    items = []
    for n in c.numbers:
        year = re.match(r"\d{4}", " ".join(n.value.split())).group(0)
        label = H.strip_end(re.sub(r"^\s*[—–-]\s*", "", n.label or ""))
        items.append(SlideItem(title=year, text=H.cap_first(label) if label else ""))
    was = s.kind.value
    if len(items) >= 3 and not c.items:
        s.kind, c.items = PatternKind.timeline, items[:MAX_ITEMS]
    else:
        lines = [f"{it.title} — {_low_first(it.text, d.unit.text)}" if it.text else it.title for it in items]
        c.bullets = (lines + [b for b in c.bullets if b not in lines])[:MAX_BULLETS]
        if not (c.items or c.columns):
            s.kind = PatternKind.bullets
    c.numbers = []
    d.changes.append(f"slide {d.unit.key}: a {was} of years only → {s.kind.value} ({', '.join(it.title for it in items)})")


_COUNT_NEXT_SKIP = re.compile(
    r"^(?:трет|четверт|половин|раз|процент|тысяч|миллион|миллиард|млн|млрд|тыс|час|минут|секунд|дн|недел|месяц|лет|год|век|пункт)", re.I,
)


def _count_words(text: str) -> set[int]:
    """The counts 2–10 a text gives: as digits («3 сервиса») or in words («трём», «пятью»)."""
    from verstka.planning.grounding import _CARDINALS

    out = {int(v) for v in figures(text or "") if float(v).is_integer() and 2 <= v <= 10}
    for w in re.findall(r"[а-яё]+", (text or "").lower()):
        v = _CARDINALS.get(w)
        if v and 2 <= v[0] <= 10:
            out.add(v[0])
    return out


def _list_sizes(s: OutlineSlide, source: str = "") -> set[int]:
    """How many things the slide and its source list: lines, cards, columns, figures, a chart's categories, a table's
    rows, and the names or parts one line enumerates («"ВКонтакте", "Одноклассники", "Мой мир"» — 3)."""
    c = s.content
    sizes = {len(c.bullets), len(c.items), len(c.columns), len(c.numbers)}
    sizes |= {len(x.bullets) for x in [*c.items, *c.columns]}
    for ch in (c.chart, c.chart2):
        if ch is not None:
            sizes.add(len(ch.categories))
    if c.table is not None:
        sizes.add(len(c.table.rows))
    lines = [*c.bullets, *c.paragraphs] + [f"{x.title}: {x.text} {' '.join(x.bullets)}" for x in [*c.items, *c.columns]]
    lines += H.split_sentences(source or "") or []
    for ln in lines:
        sizes.add(len(re.findall(r"«[^«»]+»", ln)))
        body = ln.split(":", 1)[-1]
        sizes.add(len([p for p in re.split(r",\s*|\s+и\s+", body) if p.strip()]))
    return {n for n in sizes if n >= 2}


def invented_counts(headline: str, source: str, s: OutlineSlide) -> list[str]:
    """The counts in words a headline gives («шестью социальными сетями и пятью мессенджерами») that neither its source
    text states (in digits or words) nor the slide shows (a list of that many): the designer's invention."""
    from verstka.planning.grounding import _CARDINALS

    toks = list(re.finditer(r"[А-Яа-яЁё]+", headline or ""))
    have: Optional[set[int]] = None
    bad = []
    for i, m in enumerate(toks):
        v = _CARDINALS.get(m.group(0).lower())
        if not v or not 2 <= v[0] <= 10 or i + 1 >= len(toks):
            continue
        nxt = toks[i + 1]
        if headline[m.end():nxt.start()].strip() or _COUNT_NEXT_SKIP.match(nxt.group(0)) or nxt.group(0).lower() in _CARDINALS:
            continue
        if have is None:
            have = _count_words(source) | _list_sizes(s, source)
        if v[0] not in have:
            bad.append(f"{m.group(0)} {nxt.group(0)}")
    return bad


_LABEL_DROP_RE = re.compile(
    r"^(?:что|и|а|но|это|так|около|более|менее|почти|примерно|свыше|порядка|до|лишь|только|уже|было|будет|был[аио]?|были|"
    r"составит|составляет|составил[аио]?|составили|достиг\w*|насчитыва\w*|прогнозиру\w*|ожида\w*|оценива\w*)$",
    re.I,
)


def _values(text: str) -> list[float]:
    """The magnitudes of a text's figures that are not dates or years («240 млн» → 240 000 000; «1 854» stays, «в 2025
    году» goes)."""
    from verstka.planning.grounding import _is_year, figures as g_figures

    return [f.mag for f in g_figures(text or "") if f.date is None and not _is_year(f)]


def _same_value(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(a))


def _figure_sentence(value: str, source: str) -> Optional[str]:
    """The source's sentence that states the figure (every figure of `value` that is not a year in it)."""
    want = _values(value)
    if not want:
        return None
    for sn in H.split_sentences(source or "") or []:
        have = _values(sn)
        if all(any(_same_value(v, x) for x in have) for v in want):
            return H.strip_end(sn)
    return None


# what a figure measures: a label that names one of these must find it in the figure's sentence
_KPI_MEASURE_RE = re.compile(
    r"(?<![\wё])(прод|выручк|доход|прибыл|убыт|пользоват|аудитор|абонент|подписчик|сотрудник|работник|клиент|покупател|"
    r"экспорт|импорт|производ|выпуск|регистр|инвестиц|расход|затрат|стоимост|цен[аыуе]|населен|жител|потер|погиб|жертв|"
    r"участник|зрител|посетител|студент|учащ|парк)",
    re.I,
)


def _label_words_ok(label: str, sentence: str) -> bool:
    """The measure a figure's label names is the one its sentence states: «Прогноз продаж» over «…в мире будет около 240
    млн электромобилей» is not («продаж» is another measure); a paraphrase of the same measure is («Доля на рынке» for
    «менее 1 % от общего числа проданных»)."""
    low = (sentence or "").lower()
    return all(re.search(rf"(?<![\wё]){re.escape(m.group(1).lower()[:4])}", low) for m in _KPI_MEASURE_RE.finditer(label or ""))


def _label_from_sentence(sentence: str, value: str) -> Optional[str]:
    """A figure's label in the words of its sentence: what the figure counts (the words after it, up to the clause's
    end) and where and when (the clause before it, without hedges, «что», auxiliaries): «…что к 2030 году в мире будет
    около 240 млн электромобилей» → «электромобилей к 2030 году в мире»."""
    want = figures(value)
    if not want:
        return None
    m = next((m for m in _FIG_RE.finditer(sentence) if number_of(m.group(0)) is not None and abs(number_of(m.group(0)) - want[0]) <= 1e-6 * max(1.0, abs(want[0]))), None)
    if m is None:
        return None
    after = re.split(r"[,;:(]|\s[—–]\s", sentence[m.end():])[0].split()
    while after and re.match(r"^(?:тыс\.?|млн\.?|млрд\.?|трлн\.?|%|₽|руб\w*|долл\w*|\$|€|шт\.?)$", after[0], re.I):
        after = after[1:]
    before = re.split(r"[,;:(]|\s[—–]\s", sentence[: m.start()])[-1].split()
    before = [w for w in before if not _LABEL_DROP_RE.match(w)]
    label = " ".join(after[:6] + before[-5:]).strip(" ,.;:")
    if not label:
        return None
    return label[:1].lower() + label[1:] if _lowered(label.split()[0], sentence) else label


def misdated(headline: str, source: str) -> list[str]:
    """The names a headline puts at a date that the source's lines of that date never name: «Германия капитулировала 2
    сентября 1945 года» where the source says «2 сентября 1945 года — Япония капитулирует» (and «8 мая 1945 года —
    Германия капитулирует»). Only full dates (day, month, year); a line without a year takes the years of its text."""
    from verstka.planning.grounding import figures as g_figures

    want = {f.date for f in g_figures(headline or "") if f.date is not None and f.date[2]}
    if not want:
        return []
    names = []
    for m in re.finditer(r"[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z-]{2,}", headline):
        w = m.group(0)
        if _keeps_capital(w, source) and not re.match(_MONTHS_GEN, w, re.I):
            names.append(w)
    if not names:
        return []
    years = {int(y) for y in re.findall(r"(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)", source or "")}
    lines = [x for ln in (source or "").splitlines() for x in (H.split_sentences(ln) or [ln])]
    dated = []
    for ln in lines:
        for f in g_figures(ln):
            if f.date is None:
                continue
            day, mo, y = f.date
            if (day, mo, y) in want or (y is None and any((day, mo, yy) in want for yy in years)):
                dated.append(ln.lower())
                break
    if not dated:
        return []
    stem = lambda w: w.lower()[: max(4, len(w) - 2)]  # noqa: E731 - «Германия» · «Германии»
    return [w for w in names if not any(stem(w) in ln for ln in dated)]


def _dated_in(headline: str, source: str) -> bool:
    """The source writes a full date of the headline (with its year, or a day of a month of a year it writes)."""
    from verstka.planning.grounding import figures as g_figures

    want = {f.date for f in g_figures(headline or "") if f.date is not None and f.date[2]}
    years = {int(y) for y in re.findall(r"(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)", source or "")}
    for f in g_figures(source or ""):
        if f.date is not None and (f.date in want or (f.date[2] is None and any((f.date[0], f.date[1], y) in want for y in years))):
            return True
    return False


def _true_labels(d: _Design) -> None:
    """A written deck (the writer's text): a key figure's label says what its sentence says it counts, and a big
    number's headline states that figure — «240 млн · Прогноз продаж к 2030 году» under «Продажи электромобилей в
    России: 1854 шт.» said a world fleet was a sales forecast."""
    s, c = d.slide, d.slide.content
    src = d.unit.text or ""
    if not c.numbers or not src.strip():
        return
    for n in c.numbers:
        sn = _figure_sentence(n.value, src)
        if sn is None or not (n.label or "").strip() or _label_words_ok(n.label, sn):
            continue
        new = _label_from_sentence(sn, n.value)
        if new and new != n.label:
            d.changes.append(f"slide {d.unit.key}: the label «{n.label[:60]}» of {n.value} is not what its sentence counts → «{new}»")
            n.label = new
    if s.kind == PatternKind.big_number and len(c.numbers) == 1:
        kv = _values(c.numbers[0].value)
        hv = _values(_ORD_TOKEN_RE.sub(" ", s.headline or ""))
        if kv and hv and not any(_same_value(a, b) for a in kv for b in hv):
            sn = _figure_sentence(c.numbers[0].value, src)
            if sn and len(sn.split()) <= 14:
                d.changes.append(f"slide {d.unit.key}: the headline «{(s.headline or '')[:60]}» states another figure than the big number {c.numbers[0].value} → its sentence")
                s.headline = H.cap_first(sn)


_LEADING_DATE_RE = re.compile(r"^([^—–:]{0,32}?(?<![\d.,])(?:1\d{3}|20\d{2})(?![\d.,])[^—–:]{0,14}?)\s*[—–:]\s")


def _chrono_order(d: _Design) -> None:
    """A written deck: a timeline, dated cards and a dated list («1998 — …», «Июль 1937 — …») in time order — the
    narrative's order left «22 июня 1941 → 1931–1937 → Июль 1937 → 7 декабря 1941» (gate 2 W3). Stable; only when at
    least 80 % of the entries parse as dates (writer.date_start)."""
    from verstka.planning.writer import chrono_sort

    s, c = d.slide, d.slide.content
    if c.items and s.kind in (PatternKind.timeline, PatternKind.cards, PatternKind.process):
        new = chrono_sort(list(c.items), lambda it: it.title or "")
        if [id(x) for x in new] != [id(x) for x in c.items]:
            d.changes.append(f"slide {d.unit.key}: the {s.kind.value} in time order ({', '.join(it.title for it in new)[:120]})")
            c.items = new
    if len(c.bullets) >= 2:
        def lead(b: str) -> str:
            m = _LEADING_DATE_RE.match(b or "")
            return m.group(1) if m else ""

        new_b = chrono_sort(list(c.bullets), lead)
        if new_b != c.bullets and sum(1 for b in c.bullets if lead(b)) >= 0.8 * len(c.bullets):
            d.changes.append(f"slide {d.unit.key}: the dated list in time order")
            c.bullets = new_b


def _hero_supports_headline(d: _Design) -> None:
    """A written deck: a big number stands under a headline that names it; «2800 · студентов в вузах ежегодно» under
    «VK охватывает миллионы пользователей по всему миру» (gate 2 W7) becomes a line of the slide."""
    s, c = d.slide, d.slide.content
    if s.kind != PatternKind.big_number or len(c.numbers) != 1 or c.chart is not None or c.table is not None:
        return
    n = c.numbers[0]
    kv = _values(n.value)
    hv = _values(_ORD_TOKEN_RE.sub(" ", s.headline or ""))
    if not kv or any(_same_value(a, b) for a in kv for b in hv):
        return
    sn = _figure_sentence(n.value, d.unit.text or "")
    line = H.strip_end(sn) if sn and len(sn.split()) <= 24 else H.strip_end(f"{n.value} — {_low_first(n.label or '', d.unit.text)}" if (n.label or "").strip() else n.value)
    rest = [b for b in c.bullets if not same_text(b, line)]
    c.bullets = ([line] + rest)[:MAX_BULLETS]
    c.numbers = []
    s.kind = PatternKind.bullets
    d.changes.append(f"slide {d.unit.key}: the big number {n.value} is not what the headline «{(s.headline or '')[:60]}» says → a line")


def _sentence_headline(d: _Design) -> None:
    """A written deck: a headline is a statement, not a section label («Инфраструктура» over production facts, gate 2
    W7) — a headline of one or two words becomes the slide's first short fact (≤ 14 words)."""
    from verstka.planning.writer import anaphoric, sentences_of

    s = d.slide
    h = H.strip_end(s.headline or "")
    if not h or len(h.split()) > 2 or re.search(r"\d", h):
        return
    first = next((x for x in sentences_of(d.unit.text or "") if 4 <= len(x.split()) <= 14 and not anaphoric(x) and not re.match(r"^\s*[—–-]", x)), None)
    if first:
        d.changes.append(f"slide {d.unit.key}: the headline «{h}» is a label → «{H.strip_end(first)[:80]}»")
        s.headline = H.strip_end(first)


def _plain_takeaway(d: _Design) -> None:
    """A written deck: a takeaway with an evaluative word its source never uses («Прогнозируется значительный рост…»,
    gate 2 W7) goes — the critic's note on it is honoured without a model call."""
    from verstka.planning.writer import opinion_word

    s = d.slide
    if s.takeaway and opinion_word(s.takeaway, d.unit.text or ""):
        d.changes.append(f"slide {d.unit.key}: the takeaway «{s.takeaway[:80]}» is an evaluation, dropped")
        s.takeaway = None


def _written_kpis(d: _Design) -> None:
    """A written deck: a key figure is a figure — a date («2021 г» · «— ребрендинг») or a word («Москвич» · «Основной
    производитель») in a row of key figures becomes a line of the slide (gate 2: the visual variants' last slides)."""
    s, c = d.slide, d.slide.content
    out = [n for n in c.numbers if _date_callout(n, source=d.unit.text) or not re.search(r"\d", n.value or "")]
    if not out:
        return
    c.numbers = [n for n in c.numbers if n not in out]
    lines = []
    for n in out:
        label = H.strip_end(re.sub(r"^\s*[—–-]\s*", "", n.label or ""))
        lines.append(f"{H.strip_end(n.value)} — {_low_first(label, d.unit.text)}" if label else H.strip_end(n.value))
    c.bullets = (c.bullets + [x for x in lines if not any(same_text(x, b) for b in c.bullets)])[:MAX_BULLETS]
    if not c.numbers and s.kind in (PatternKind.stat_row, PatternKind.big_number) and c.chart is None and c.table is None:
        s.kind = PatternKind.bullets
    d.changes.append(f"slide {d.unit.key}: key figures that are dates or words → lines ({', '.join(n.value for n in out)[:80]})")


_FIG_LINE_RE = re.compile(r"^\s*([\d][\d\s,.]*(?:\s*(?:млн|млрд|тыс\.?|%|₽))?)\s+[—–-]\s+(.+)$")


def _true_bullet_labels(d: _Design) -> None:
    """A written deck: a «figure — label» line says what its sentence says the figure counts; «1213 — Кораблей США»
    over «Для операции было выделено 1213 кораблей и 4126 десантных судов» (the ships were the allies') becomes that
    sentence (or goes when it is too long for a line)."""
    from verstka.planning.grounding import content_stems

    src = d.unit.text or ""
    c = d.slide.content
    out: list[str] = []
    changed = False
    for b in c.bullets:
        m = _FIG_LINE_RE.match(b or "")
        if not m or _date_callout(NumberCallout(value=m.group(1).strip(), label=m.group(2)), source=src):
            out.append(b)
            continue
        sn = _figure_sentence(m.group(1).strip(), src)
        if sn is None:
            out.append(b)
            continue
        low = sn.lower()
        words = {x[:5] for x in content_stems(m.group(2), neutral=True) if not re.match(r"^\d", x)}
        names = re.findall(r"(?<![\wё])[A-ZА-ЯЁ][\w-]{1,}", m.group(2))[1:]  # a name inside the label (its first word is capitalised anyway)
        if all(w in low for w in words) and all(x.lower()[:5] in low for x in names):
            out.append(b)
            continue
        changed = True
        if len(sn.split()) <= 16 and not any(same_text(sn, o) for o in out):
            out.append(H.strip_end(sn))
    if changed:
        d.changes.append(f"slide {d.unit.key}: «figure — label» lines whose label is not what their sentence counts → the sentences")
        c.bullets = out


def _undated_timeline(d: _Design) -> None:
    """A written deck: a timeline's steps are dates; one titled «Нью-Йорк», «Петербург» or nothing makes it a list of
    lines («date — event»), not a time axis that is not one."""
    from verstka.planning.writer import date_start

    s, c = d.slide, d.slide.content
    if s.kind != PatternKind.timeline or not c.items or all(date_start(it.title or "") for it in c.items):
        return
    lines = [f"{H.strip_end(it.title)} — {_low_first(H.strip_end(it.text), d.unit.text)}" if (it.title or "").strip() and (it.text or "").strip()
             else H.strip_end(it.title or it.text or "") for it in c.items]
    c.bullets = [x for x in lines if x][:MAX_BULLETS]
    c.items = []
    s.kind = PatternKind.bullets
    d.changes.append(f"slide {d.unit.key}: a timeline with undated steps → lines")


_FUTURE_WORD_RE = re.compile(r"(?<![\wё])(станет|станут|будет|будут|окажется|получит|войдёт)(?![\wё])", re.I)


def _no_new_future(d: _Design) -> None:
    """A written deck: the designer never turns a past event into a future one («Гагарин станет самым известным
    человеком планеты» over «стал»): such a takeaway goes, such a headline takes the slide's title, such a line its
    source sentence (or goes)."""
    from verstka.planning.writer import sentences_of

    s, c = d.slide, d.slide.content
    src = (d.unit.text or "").lower()

    def new_future(x: Optional[str]) -> bool:
        return bool(x) and any(m.group(1).lower() not in src for m in _FUTURE_WORD_RE.finditer(x or ""))

    if new_future(s.takeaway):
        d.changes.append(f"slide {d.unit.key}: the takeaway «{(s.takeaway or '')[:60]}» tells a past event as future, dropped")
        s.takeaway = None
    if new_future(s.headline) and d.unit.title:
        d.changes.append(f"slide {d.unit.key}: the headline «{s.headline[:60]}» tells a past event as future → «{d.unit.title}»")
        s.headline = H.strip_end(d.unit.title)
    if any(new_future(b) for b in c.bullets):
        sents = sentences_of(d.unit.text or "")
        out = []
        for b in c.bullets:
            if not new_future(b):
                out.append(b)
                continue
            best = next((H.strip_end(x) for x in sents if said_in(b.replace("станет", "стал").replace("будет", "был"), x, 0.6) and len(x.split()) <= 16), None)
            if best and not any(same_text(best, o) for o in out):
                out.append(best)
        d.changes.append(f"slide {d.unit.key}: lines telling a past event as future → the source's sentences")
        c.bullets = out


def _written_ru(changes: list[str]) -> str:
    """What the written check changed on a slide, in a few Russian words for the agent's log."""
    what = []
    joined = " ".join(changes)
    if "entries checked" in joined or "lines checked" in joined:
        what.append("даты и события по тексту")
    if "headline" in joined:
        what.append("заголовок")
    if "takeaway" in joined:
        what.append("вывод — фраза из текста")
    if "label" in joined or "key figure" in joined:
        what.append("подписи чисел")
    if "timeline" in joined:
        what.append("шкала без дат заменена")
    if "short slide" in joined or "one line" in joined:
        what.append("короткий слайд заполнен")
    if "enumerates" in joined:
        what.append("список полностью")
    return ", ".join(what) or "исправления"


def _written_notes(text: str) -> str:
    """The speaker notes of a written deck's slide: its checked text as written (sentences and dated entries; not the
    chart's rows or the chart request) — the designer's own notes added claims the check never saw («США сыграли
    решающую роль…», «ознаменовал начало эпохи…»)."""
    out: list[str] = []
    data = False
    for line in (text or "").splitlines():
        t = line.strip()
        if not t:
            continue
        if re.match(r"^(?:Нужна\s.*диаграмма|Укажи,\s+что\s+данные|Диаграмма\s*\([^)]*\)\s*:|Данные\s+приблизительные\.?$|Название:|Подзаголовок:)", t):
            continue
        if t.endswith(":"):
            data = not re.match(r"^Хронология:$", t)
            continue
        if re.match(r"^[—–-]\s", t):
            if data:
                continue
            t = re.sub(r"^[—–-]\s*", "", t).rstrip(";.")
        else:
            data = False
        out.append(t if t.endswith((".", "!", "?", "…")) else t + ".")
    return " ".join(out)


def tidy_design(d: _Design, ctx: Optional[_Ctx] = None) -> None:
    """The slide once its form is final (after the user's requests are enforced — a requested chart may have been
    added, a headline replaced): no line says again what the slide says elsewhere — the chart's own values, the
    takeaway, the headline, the footnote's caveat («Результат не гарантирован» over «Прогноз не гарантирован»); no
    takeaway that repeats the headline in other words; the steps of a plan titled one way («1-й месяц», not «Месяц 2»
    next to untitled ones)."""
    s, c = d.slide, d.slide.content
    if d.unit.frame or s.kind.value in FRAME_KINDS:
        return
    users = d.unit.spec.takeaway if d.unit.spec is not None else None
    _years_as_timeline(d)  # years are never a row of key figures
    written = ctx is not None and ctx.written
    if d.by == "model" and s.headline and not (users and same_text(s.headline, users)):
        # a count in words the source does not give («шестью социальными сетями и пятью мессенджерами» over 3 and 3)
        source = d.unit.text if written or ctx is None else f"{d.unit.text}\n{ctx.brief.text}"
        bad = invented_counts(s.headline, source, s)
        if bad:
            new = H.strip_end(d.unit.title or "") if written or ctx is None else _fallback_headline(d.unit, ctx)
            if new and not invented_counts(new, source, s):
                d.changes.append(f"slide {d.unit.key}: the headline «{s.headline[:80]}» gives a count the source does not ({', '.join(bad)}) → «{new[:80]}»")
                s.headline = new
    if written:
        _written_kpis(d)
        _true_labels(d)
        _true_bullet_labels(d)
        _undated_timeline(d)
        _chrono_order(d)
        _no_new_future(d)
        notes = _written_notes(d.unit.text)
        if notes:
            s.notes = notes
        _hero_supports_headline(d)
        _plain_takeaway(d)
        if not users and not written:
            _sentence_headline(d)  # a written deck: the written check states a label's slide from its own sentences
        if d.by == "model" and s.headline:
            # a date given to another actor («Германия капитулировала 2 сентября 1945 года»: Japan did)
            wrong = misdated(s.headline, d.unit.text) or (misdated(s.headline, ctx.brief.text) if not _dated_in(s.headline, d.unit.text) else [])
            if wrong:
                new = H.strip_end(d.unit.title or "")
                d.changes.append(f"slide {d.unit.key}: the headline «{s.headline[:80]}» puts {', '.join(wrong)} at a date the text gives to another → «{new}»")
                s.headline = new
    if d.by == "model" and d.unit.spec is not None:
        # what another slide's source says (a reviewer's note sent to the wrong slide, the model's memory of the deck):
        # never on this one
        foreign = foreign_figures(s.headline, d.unit, ctx)
        if foreign:
            new = _fallback_headline(d.unit, ctx)
            d.changes.append(f"slide {d.unit.key}: the headline «{s.headline[:80]}» has figures of another slide ({', '.join(foreign[:3])}) → «{new[:80]}»")
            s.headline = new
        if s.takeaway and not users and foreign_figures(s.takeaway, d.unit, ctx):
            d.changes.append(f"slide {d.unit.key}: the takeaway «{s.takeaway[:80]}» has figures of another slide, dropped")
            s.takeaway = None
        for field_ in ("bullets", "paragraphs"):
            lines = getattr(c, field_)
            keep = [b for b in lines if not foreign_figures(b, d.unit, ctx) and not _unbriefed_words(b, ctx)]
            if len(keep) < len(lines):
                d.changes.append(f"slide {d.unit.key}: lines with figures of another slide or words the brief does not use dropped: {'; '.join(b for b in lines if b not in keep)[:120]}")
                setattr(c, field_, keep)
    why = takeaway_ok(s.takeaway, s, d.unit, ctx)
    if why:
        old_tk = s.takeaway
        s.takeaway = None
        if d.unit.spec is not None and (d.unit.text or "").strip():
            # the source's own sentence of a result the slide does not show yet, if there is one
            src = _read_source(d.unit.text)
            cand = _takeaway_sentence(src.sentences, [g.label for g in src.groups if g.label], _shown_sentences(src, s.headline, s.content))
            if cand and takeaway_ok(cand, s, d.unit, ctx) is None and not _filler_takeaway(cand, s.headline, s.content, d.unit.text):
                s.takeaway = cand
        if s.takeaway is None and why == "repeats the headline with a condition":
            s.takeaway = old_tk  # its condition is still something the headline does not say: better than none
        else:
            d.changes.append(f"slide {d.unit.key}: the takeaway «{(old_tk or '')[:80]}» {why}, " + (f"replaced by the source's «{s.takeaway[:60]}»" if s.takeaway else "dropped"))
    if c.formula and c.numbers and all(set(figures(n.value)) <= set(figures(c.formula)) for n in c.numbers):
        # «900 000 · руб.» next to «100 × 300 × 30 = 900 000 ₽»: the formula shows its result large already
        d.changes.append(f"slide {d.unit.key}: figures that repeat the formula's dropped")
        c.numbers = []
        if s.kind == PatternKind.stat_row:
            s.kind = PatternKind.big_number
    vals = [v for ch in (c.chart, c.chart2) if ch is not None for sr in ch.series for v in sr.values]
    vals += [v for n in c.numbers for v in figures(n.value)] + figures(c.formula or "")

    def repeats(b: str) -> Optional[str]:
        if d.by == "model" and (d.unit.text or "").strip() and invented_cause(b, d.unit.text):
            return "nothing: a cause the brief does not state"
        if vals and _plain_figures(b) and all(any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) or (abs(v) >= 1000 and abs(v - x * 1000) <= 500) for x in vals) for v in _plain_figures(b)) and (c.chart is not None or c.numbers or c.formula):
            return "the figures the slide shows"
        if s.takeaway and (adds_nothing(b, s.takeaway) or same_caveat(b, s.takeaway)):
            return "the takeaway"
        if adds_nothing(b, s.headline):
            return "the headline"
        if s.footnote and (same_caveat(b, s.footnote) or adds_nothing(b, s.footnote)):
            return "the footnote"
        return None

    for field_ in ("bullets", "paragraphs"):
        lines = getattr(c, field_)
        keep = []
        for b in lines:
            why = repeats(b)
            if why is None:
                keep.append(b)
            else:
                d.changes.append(f"slide {d.unit.key}: the line «{b[:60]}» repeated {why}, dropped")
        if len(keep) < len(lines) and (keep or c.chart is not None or c.table is not None or c.items or c.columns or c.numbers or c.formula or field_ == "paragraphs" or c.paragraphs):
            setattr(c, field_, keep)
    _uniform_steps(d, ctx.brief.text if ctx is not None else d.unit.text)
    s.takeaway = plain_change(s.takeaway)
    c.bullets = [plain_change(b) or b for b in c.bullets]
    charts = [x for x in (c.chart, c.chart2) if x is not None]
    if charts and s.takeaway and not users:
        t2 = trim_chart_restatement(s.takeaway, charts)
        if t2 != s.takeaway and takeaway_ok(t2, s, d.unit, ctx) is None:
            d.changes.append(f"slide {d.unit.key}: the takeaway «{s.takeaway[:80]}» said the chart's figures again → «{t2}»")
            s.takeaway = t2
    c.bullets = [trim_chart_restatement(b, charts) or b for b in c.bullets]
    polish_case(s, ctx.brief.text if ctx is not None else d.unit.text)
    # «2 п. п.» never breaks between its dots at a line's end
    s.headline = _PP_RE.sub("\\1\u00a0п.\u00a0п.", s.headline or "")
    if s.takeaway:
        s.takeaway = _PP_RE.sub("\\1\u00a0п.\u00a0п.", s.takeaway)
    c.bullets = [_PP_RE.sub("\\1\u00a0п.\u00a0п.", b) for b in c.bullets]
    if written:
        _written_check(d.slide, d.unit, ctx, d.changes)


def _written_check(s: OutlineSlide, unit: _Unit, ctx: Optional[_Ctx], changes: list[str]) -> list[str]:
    """A written deck (writer mode): the slide against its writer text — no date, figure, name or rank the text does
    not give together with its event, dated steps only on a time axis, labels that are their sentences, takeaways that
    are sentences, headlines in the text's gender (planning/written_check.py). Never raises."""
    if unit.frame or not (unit.text or "").strip():
        return []
    try:
        from verstka.planning.written_check import check_slide

        done = check_slide(s, unit.text, deck=ctx.brief.text if ctx is not None else unit.text, title=unit.title, topic=ctx.title if ctx is not None else "", key=unit.key)
    except Exception:  # noqa: BLE001 - the check never stops the deck
        log.warning("written check failed on %s", unit.key, exc_info=True)
        return []
    changes.extend(done)
    return done


_PP_RE = re.compile(r"(\d)\s+п\.\s*п\.")
_STEP_ORD_RE = re.compile(r"^(?:(?P<n1>\d{1,2})\s*-?\s*(?:й|ый|ой|ий)?\s*(?P<w1>месяц|недел[яи]|квартал|этап|шаг|день)|(?P<w2>месяц|неделя|квартал|этап|шаг)\s+(?P<n2>\d{1,2}))$", re.I)


def _uniform_steps(d: _Design, text: str = "") -> None:
    """The steps of a timeline or a process (or a column of steps) titled one way: the source's own step titles
    («1-й месяц», …) when the slide shows as many steps as the source gives, in order; else an untitled step between
    titled ones gets its number's title in the form of the others («Месяц 2» … → «Месяц 3»)."""
    src = _read_source(d.unit.text) if (d.unit.text or "").strip() else _Source()
    c = d.slide.content

    case_text = text or d.unit.text or ""

    def low(x: str) -> str:
        return _low_first(x, case_text, only_if_next_lower=True)

    if d.slide.kind.value in ("timeline", "process") and len(c.items) >= 3:
        items = c.items
        titled = [bool(_STEP_ORD_RE.match(H.strip_end(it.title or ""))) for it in items]
        if src.steps and len(src.steps) == len(items) and [H.strip_end(it.title or "") for it in items] != [t for t, _ in src.steps]:
            for it, ok, (t, _) in zip(items, titled, src.steps):
                if not ok and it.title and not it.text:
                    it.text = it.title
                it.title = t
            d.changes.append(f"slide {d.unit.key}: steps titled as the source titles them")
        elif any(titled) and not all(titled):
            m = next(_STEP_ORD_RE.match(H.strip_end(it.title)) for it, ok in zip(items, titled) if ok)
            word = (m.group("w1") or m.group("w2") or "").lower()
            ordinal = m.group("n1") is not None
            for i, (it, ok) in enumerate(zip(items, titled), 1):
                if not ok:
                    if it.title and not it.text:
                        it.text = it.title
                    it.title = f"{i}-й {word}" if ordinal else f"{word.capitalize()} {i}"
            d.changes.append(f"slide {d.unit.key}: untitled steps titled like the others")
    for col in c.columns:
        bl = col.bullets
        if len(bl) >= 3 and src.steps and len(src.steps) == len(bl) and any(_step_item(b) for b in bl) != all(_step_item(b) for b in bl) or (
            len(bl) >= 3 and src.steps and len(src.steps) == len(bl) and all(_step_item(b) for b in bl) and [_step_item(b).title for b in bl] != [t for t, _ in src.steps]
        ):
            new = []
            for b, (t, _) in zip(bl, src.steps):
                it = _step_item(b)
                new.append(f"{t} — {low(it.text if it is not None else H.strip_end(b))}")
            col.bullets = new
            d.changes.append(f"slide {d.unit.key}: the plan's lines titled as the source titles them")


def _split_merged_lists(d: _Design) -> None:
    """A column (or a card of lines) that merges two lists of the source («Меры и риски»: three measures, then three
    risks) is split into one per list, in the source's words and order: the pairs risk → measure stay readable."""
    c = d.slide.content
    if not (c.columns or any(it.bullets for it in c.items)):
        return
    src = _read_source(d.unit.text)
    risks = next((g for g in src.groups if g.label and _RISK_RE.search(g.label)), None)
    measures = next((g for g in src.groups if g.label and _MEASURE_RE.search(g.label) and not _RISK_RE.search(g.label)), None)
    if risks is None or measures is None:
        return
    for field_ in ("columns", "items"):
        blocks = getattr(c, field_)
        for i, col in enumerate(blocks):
            t = col.title or ""
            if _RISK_RE.search(t) and _MEASURE_RE.search(t):
                new = [SlideItem(title=_label(risks.label or "Риски"), bullets=[H.short(x, 8) for x in risks.items]),
                       SlideItem(title=_label(measures.label or "Меры"), bullets=[H.short(x, 8) for x in measures.items])]
                setattr(c, field_, (blocks[:i] + new + blocks[i + 1:])[: 3 if field_ == "columns" else MAX_ITEMS])
                d.changes.append(f"slide {d.unit.key}: the block «{t}» merged two lists of the brief: split into «{new[0].title}» and «{new[1].title}»")
                return


# ------------------------------------------------------------------ one slide's content in another form


def _pairs(s: OutlineSlide) -> list[tuple[str, str, Optional[float]]]:
    """(label, value as shown, number) of the slide's figures: its callouts, else a one-series chart's points."""
    c = s.content
    if c.numbers:
        return [(n.label, n.value, None if "→" in n.value else number_of(n.value)) for n in c.numbers]
    if c.chart is not None and len(c.chart.series) == 1:
        return [(cat, _fmt_ru(v, c.chart.unit), v) for cat, v in zip(c.chart.categories, c.chart.series[0].values)]
    return []


def _unit_of_value(value: str) -> str:
    return re.sub(r"[\d\s  .,+\-−]+", " ", value).strip()


def _chart_from_pairs(pairs: list[tuple[str, str, Optional[float]]]) -> Optional[ChartSpec]:
    ok = [(lb, v, n) for lb, v, n in pairs if n is not None and lb]
    if len(ok) < 2 or len(ok) != len(pairs) or len(ok) > 8:
        return None
    units = {_unit_of_value(v) for _, v, _ in ok}
    if len(units) != 1:
        return None
    unit = units.pop() or None
    return ChartSpec(type="column", unit=unit, categories=[lb for lb, _, _ in ok], series=[InlineSeries(name="", values=[n for _, _, n in ok])])


def _chart_from_table(t: Optional[TableData]) -> Optional[ChartSpec]:
    if t is None or len(t.columns) < 2 or not 2 <= len(t.rows) <= 8:
        return None
    rows = [r for r in t.rows if len(r) == len(t.columns)]
    if len(rows) != len(t.rows):
        return None
    series = []
    units = set()
    for j in range(1, min(len(t.columns), 4)):
        cells = [r[j] for r in rows]
        vals = [None if "→" in x else number_of(x) for x in cells]
        if any(v is None for v in vals):
            return None
        units.update(_unit_of_value(x) for x in cells)
        series.append(InlineSeries(name=t.columns[j], values=[float(v) for v in vals]))  # type: ignore[arg-type]
    if not series or len(units) > 1:
        return None
    return ChartSpec(type="column", title=t.caption, unit=(units.pop() or None) if units else t.unit, categories=[r[0] for r in rows], series=series)


def _table_from_chart(ch: Optional[ChartSpec]) -> Optional[TableData]:
    if ch is None or not ch.series or len(ch.categories) > MAX_TABLE_ROWS:
        return None
    cols = [ch.title or "", *[(s.name or ch.unit or "") for s in ch.series[:MAX_TABLE_COLS - 1]]]
    rows = [[cat, *[_fmt_ru(s.values[i], ch.unit) for s in ch.series[:MAX_TABLE_COLS - 1]]] for i, cat in enumerate(ch.categories)]
    return TableData(columns=cols, rows=rows, unit=ch.unit, caption=ch.title)


def _table_from_pairs(pairs: list[tuple[str, str, Optional[float]]]) -> Optional[TableData]:
    rows = [[lb, v] for lb, v, _ in pairs if lb and v]
    if len(rows) < 2 or len(rows) != len(pairs):
        return None
    return TableData(columns=["Показатель", "Значение"], rows=rows[:MAX_TABLE_ROWS])


def _lines_of(s: OutlineSlide, text: str = "") -> list[str]:
    c = s.content
    out = [*c.paragraphs, *c.bullets]
    for it in c.items:
        out.append(_title_text(it, text))
    for col in c.columns:
        out.extend(f"{col.title}: {b}" if col.title else b for b in col.bullets)
    return [x for x in out if x]


_ONLY_RE = re.compile(r"^(?:только|лишь|всего|уже|около|примерно|почти)\s+", re.I)


def figures_of_items(items: list[SlideItem]) -> Optional[list[NumberCallout]]:
    """2–4 cards of one figure each as a row of figures: the figure with its unit, under it the card's words without
    it («Только 20% чеков содержат еду» → «20%» · «чеков содержат еду»), or the card's title when its text says no
    more than the figure («Потери от списаний» · «27 000 рублей в месяц» → «27 000 ₽» · «Потери от списаний, в
    месяц»). None when a card has no figure or more than one."""
    if not 2 <= len(items) <= 4:
        return None
    out: list[NumberCallout] = []
    for it in items:
        body = H.strip_end(it.text or "") or H.strip_end(it.title or "")
        ks = H.kpis_of(body)
        vals = figures(body)
        if len(ks) != 1 or len(vals) != 1 or it.bullets:
            return None
        k = ks[0]
        m = re.search(r"[+\-−]?\d[\d\s\u00a0]*(?:[.,]\d+)?\s*(?:%|₽|руб\w*|млн|тыс\.?|минут\w*|час\w*|дн\w*|мест\w*|чел\w*)?", body)
        rest = (body[: m.start()] + " " + body[m.end():]) if m else body
        rest = _ONLY_RE.sub("", " ".join(rest.split()).strip(" ,;:—–"))
        title = H.strip_end(it.title or "")
        if len(_subject_stems(rest)) < 2:
            label = f"{title}, {rest}" if title and rest and title.lower() not in rest.lower() else (title or rest)
        else:
            label = rest
        if not label or len(label.split()) > 8:
            return None
        out.append(NumberCallout(value=k.value, label=label))
    return out


def _table_of_changes(numbers: list[NumberCallout]) -> Optional[TableData]:
    """2–5 figures of changes («300 → 330 ₽» · «Средний чек») as a table «Показатель | Сейчас | Цель» (the unit on
    both sides); None when one of them is not a change or has no label."""
    if not 2 <= len(numbers) <= 5:
        return None
    rows = []
    for n in numbers:
        parts = [p.strip() for p in re.split(r"\s*→\s*", n.value or "")]
        if len(parts) != 2 or not all(figures(p) for p in parts) or not (n.label or "").strip():
            return None
        a, b = parts
        unit = _unit_of_value(b)
        if unit and not _unit_of_value(a):
            a = f"{a}{unit}" if unit == "%" else f"{a} {unit}"
        rows.append([H.cap_first(H.strip_end(n.label)), a, b])
    return TableData(columns=["Показатель", "Сейчас", "Цель"], rows=rows)


_VAL = r"[+\-−]?\d{1,3}(?:[\s  ]\d{3})*(?:[.,]\d+)?(?:\s?(?:%|₽|руб\.?|рубл(?:ей|я|ь)|тыс\.?\s?₽|млн\s?₽|час(?:а|ов)?|минут[аы]?|дн(?:я|ей)|день))?"
_FIG_FIRST_RE = re.compile(rf"^(?:только\s+|лишь\s+|всего\s+)?(?P<v>{_VAL})\s+(?P<rest>[а-яёa-z«].*)$", re.I)
_FIG_AFTER_DASH_RE = re.compile(rf"^(?P<label>[^\d—–]*?(?:\d+\s+(?:дн\w*|дня|месяц\w*|недел\w*|час\w*|минут\w*)[^\d—–]*?)?)[\s,]*[—–]\s+(?:только\s+|около\s+)?(?P<v>{_VAL})(?P<tail>(?:\s+[а-яё]+){{0,3}})$", re.I)
_PERIOD_LABEL_RE = re.compile(r"\d+\s+(?:дн\w*|дня|месяц\w*|недел\w*|час\w*|минут\w*)|\d{1,2}:\d{2}", re.I)


def _money(v: str) -> str:
    return re.sub(r"\s?(?:руб\.?|рубл(?:ей|я|ь))$", " ₽", v.strip())


def _kpi_figure(line: str) -> Optional[NumberCallout]:
    """The figure of a line as the plan's rules read it («Доля задач в срок выросла на 34%» → «+34%» · «Доля задач в
    срок», «Средняя оценка удобства: 4,6 из 5»): one figure, a label without figures of at most 7 words — one word only
    for a short line (never «Покупок» of «65% покупок приходится на утренние часы …»), not cut on a preposition."""
    k = [x for x in _kpis([line]) if not re.search(r"\d", x.label) and len(x.label.split()) <= 7]
    if len(k) != 1 or (len(k[0].label.split()) == 1 and len(line.split()) > 4):
        return None
    return None if re.search(r"(?<![\wё])(?:с|до|на|в|по|за|из|от|к|и)$", k[0].label, re.I) else k[0]


def line_figure(line: str) -> Optional[NumberCallout]:
    """A line of a list as one figure with its words, the way a row of figures shows it: a figure first («Только 20%
    чеков содержат еду» → «20%» · «чеков содержат еду»), or a label, a dash and the figure («Списания продуктов —
    27 000 ₽ в месяц» → «27 000 ₽» · «Списания продуктов в месяц»); a title before a colon is the card's, not the
    figure's. None for a line of words, of times only, or with a label of more than 8 words."""
    head, sep, tail = line.partition(": ")
    body = H.strip_end(tail if sep and not figures(head) and figures(tail) else line)
    if not figures(_PERIOD_LABEL_RE.sub(" ", body)):
        return None  # «Пик нагрузки — с 08:00 до 11:00»: times, no value
    m = _FIG_FIRST_RE.match(body)
    if m:
        value, label = _money(m.group("v")), m.group("rest").strip(" ,")
    else:
        m = _FIG_AFTER_DASH_RE.match(body)
        if m is None:
            return _kpi_figure(line)
        value = _money(m.group("v"))
        label = " ".join(f"{m.group('label')} {m.group('tail') or ''}".split()).strip(" ,")
        label = H.cap_first(label)
    if not label or len(label.split()) > 8 or not re.search(r"[а-яёa-z]{3,}", label, re.I) or re.search(r"\d", _PERIOD_LABEL_RE.sub(" ", label)):
        return _kpi_figure(line)
    if re.search(r"(?<![\wё])(?:с|со|до|на|в|во|по|за|из|от|к|при|и)$", label, re.I):
        return None  # a label cut on a preposition
    n = NumberCallout(value=value, label=label)
    if _date_callout(n, any_year=False):
        return None  # «3 сентября Великобритания…», «1939 году …»: a date, not a figure with its words
    return n


def figures_of_lines(lines: list[str]) -> Optional[tuple[list[NumberCallout], list[str]]]:
    """A list whose lines carry figures as a row of 2–4 figures with their labels and the other lines as short
    bullets under them (the visual variant's form of «Доля задач в срок выросла на 34%; экономия 2,1 часа…»); None
    when fewer than two lines give a figure with a clean label, or the lines left over would not fit under them."""
    nums: list[NumberCallout] = []
    rest: list[str] = []
    for ln in lines:
        k = [line_figure(ln)] if line_figure(ln) is not None else []
        if len(k) == 1 and len(nums) < 4:
            nums.append(k[0])
        else:
            rest.append(ln)
    if len(nums) < 2 or len(rest) > 4 or any(len(x.split()) > 12 for x in rest):
        return None
    return nums, rest


def _items_from_lines(lines: list[str]) -> Optional[list[SlideItem]]:
    if not 2 <= len(lines) <= 6:
        return None
    items = []
    for ln in lines:
        parts = H.label_split(ln)
        if parts is None and " — " in ln:
            a, b = ln.split(" — ", 1)
            parts = (a, b)
        if parts and len(parts[0].split()) <= 6 and parts[1].strip():
            items.append(SlideItem(title=H.strip_end(parts[0]), text=H.strip_end(parts[1])))
        elif len(ln.split()) <= 10:
            items.append(SlideItem(title=H.strip_end(ln)))
        else:
            return None
    return items


_AMOUNT_LINE_RE = re.compile(r"^(?P<label>[^\d:—–]{2,60}?)\s*(?::|\s[—–]\s)\s*(?P<value>[+\-−]?\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*(?P<unit>[^\d\s][^\d]{0,14})?$")


def _amount_lines(lines: list[str]) -> Optional[tuple[list[str], list[float], str]]:
    """3–8 lines «label — amount unit» of one unit («Витрина для десертов — 70 000 ₽»): (labels, values, unit)."""
    if not 3 <= len(lines) <= 8:
        return None
    labels, values, units = [], [], set()
    for ln in lines:
        m = _AMOUNT_LINE_RE.match(H.strip_end(ln))
        if m is None or "→" in ln:
            return None
        v = number_of(m.group("value"))
        if v is None or v <= 0:
            return None
        labels.append(H.cap_first(H.strip_end(m.group("label"))))
        values.append(v)
        units.add(H.strip_end((m.group("unit") or "").strip()))
    return (labels, values, units.pop()) if len(units) == 1 else None


def _reshape_columns(s: OutlineSlide, kind: str, chart_type: Optional[str]) -> Optional[SlideContent]:
    """A two-column slide in another form, each column where it fits: a column of «N-й месяц — …» lines becomes a
    timeline and the other column lines under it; a column of «label — amount» lines becomes a bar chart (a doughnut
    when asked) with the other column beside it; 2–4 «A → B» figures of the columns a row of figures with the rest as
    lines; two lists of equal length (risks and measures) a two-column table, paired in order."""
    c = s.content
    cols = [col for col in c.columns if col.bullets or col.text]
    if len(cols) < 2:
        return None
    lines = [[b for b in (col.bullets or [col.text]) if b] for col in cols]
    new = SlideContent(formula=c.formula)
    if kind in ("timeline", "process"):
        for i, ls in enumerate(lines):
            items = [_step_item(x) for x in ls]
            if len(items) >= 3 and all(items):
                new.items = [it for it in items if it]
                new.bullets = [b for j, ls2 in enumerate(lines) if j != i for b in ls2][:5] + list(c.bullets)[: max(0, 5 - sum(len(x) for j, x in enumerate(lines) if j != i))]
                return new
        return None
    if kind == "chart":
        for i, ls in enumerate(lines):
            got = _amount_lines(ls)
            if got is None:
                continue
            labels, values, unit = got
            rest = [b for j, ls2 in enumerate(lines) if j != i for b in ls2]
            if len(rest) > 3:
                return None  # the other column would not fit beside the chart whole (a plan by months): another form
            t = chart_type if chart_type in ("bar", "column", "pie", "doughnut") else ("bar" if max(len(x) for x in labels) > 14 else "column")
            new.chart = ChartSpec(type=t, title=cols[i].title or None, unit=unit or None, categories=labels, series=[InlineSeries(name=cols[i].title or "", values=values)])
            if t in ("pie", "doughnut") and not pie_ok(new.chart):
                new.chart.type = "bar"
            new.bullets = [b for j, ls2 in enumerate(lines) if j != i for b in ls2][:3]
            return new
        return None
    if kind == "stat_row":
        figs = figures_of_lines([b for ls in lines for b in ls] + list(c.bullets))
        if figs is None:
            return None
        new.numbers, new.bullets = figs
        return new
    if kind == "table" and len(cols) == 2 and len(lines[0]) == len(lines[1]) and 2 <= len(lines[0]) <= MAX_TABLE_ROWS - 1:
        if all(len(x.split()) <= 10 for ls in lines for x in ls):
            new.table = TableData(columns=[cols[0].title or "", cols[1].title or ""], rows=[[a, b] for a, b in zip(lines[0], lines[1])])
            new.bullets = list(c.bullets)[:3]
            return new
    return None


def _step_item(line: str) -> Optional[SlideItem]:
    m = _MONTH_RE.match(H.strip_end(line))
    if m is None:
        return None
    return SlideItem(title=H.strip_end(m.group("t")), text=H.cap_first(H.strip_end(m.group("x"))))


def reshape(s: OutlineSlide, kind: str, chart_type: Optional[str] = None, case_text: str = "") -> Optional[OutlineSlide]:
    """The slide's content in another form, without a model, or None when the content does not fit it (a chart needs
    figures of one unit, cards need short lines, …). Headline, takeaway, footnote, notes and the formula stay. A pie or
    a doughnut only of the parts of one whole (never «Сейчас / Цель», never a row of unrelated figures). Never a row of
    years as key figures («1998 г», «2021 г», «2023 г» — a timeline's dates). `case_text`: the brief (a name keeps its
    capital in a card joined into one line)."""
    if kind == "chart" and s.content.chart is None and s.content.numbers and case_text:
        from verstka.planning.writer import is_written_text

        if is_written_text(case_text) and not _one_measure(s.content.numbers):
            return None  # a written deck: only the writer's data rows are a chart, never unrelated figures (G4-4)
    r = _reshape(s, kind, chart_type, case_text)
    if r is not None and r.kind.value in ("stat_row", "big_number") and _years_only(r.content.numbers):
        return None
    if r is not None and r.kind == PatternKind.timeline and case_text:
        from verstka.planning.writer import date_start, is_written_text

        if is_written_text(case_text) and not all(date_start(it.title or "") for it in r.content.items):
            return None  # a written deck's time axis has dates on it («Нью-Йорк», a sentence as a step: not one)
    return r


def _one_measure(numbers: list[NumberCallout]) -> bool:
    """Key figures of one measure: one unit and one subject (the same counted word first in every label) — «36
    энергоблоков» and «54 страны» are two measures, never one chart's columns (gate 4 G4-4)."""
    if len(numbers) < 2:
        return False
    units = set()
    heads = set()
    from verstka.planning.grounding import figures as g_figs

    for n in numbers:
        fs = [f for f in g_figs(n.value or "") if f.date is None]
        if len(fs) != 1:
            return False
        units.add((fs[0].unit, fs[0].scale))
        w = re.findall(r"[а-яёa-z]{3,}", (n.label or "").lower())
        if not w:
            return False
        heads.add(w[0][:5])
    return len(units) == 1 and len(heads) == 1


def _reshape(s: OutlineSlide, kind: str, chart_type: Optional[str] = None, case_text: str = "") -> Optional[OutlineSlide]:
    c = s.content
    if kind == s.kind.value and (kind != "chart" or not chart_type or (c.chart is not None and c.chart.type == chart_type)):
        return s.model_copy(deep=True)
    if c.columns and kind in ("timeline", "process", "chart", "stat_row", "table") and not (c.chart or c.table or c.items):
        cols_new = _reshape_columns(s, kind, chart_type)
        if cols_new is None:
            return None
        k = "timeline" if kind == "process" and cols_new.items and _sequential(s.model_copy(update={"content": cols_new})) else kind
        return s.model_copy(update={"kind": PatternKind(k), "content": cols_new}, deep=True)
    new = SlideContent(formula=c.formula)
    pairs = _pairs(s)
    text = bool(c.bullets or c.paragraphs or c.items or c.columns)
    if kind == "stat_row" and c.items and not (c.chart or c.table or c.numbers or c.columns) and len(c.bullets) <= 4:
        # cards of one figure each («Только 20% чеков содержат еду», «Потери от списаний — 27 000 рублей в месяц»): the
        # figures big, each with its card's words
        nums = figures_of_items(c.items)
        if nums is not None:
            new.numbers, new.bullets = nums, list(c.bullets)
            return s.model_copy(update={"kind": PatternKind.stat_row, "content": new}, deep=True)
    if kind == "stat_row" and text and not (c.chart or c.table or c.numbers):
        figs = figures_of_lines(_lines_of(s, case_text))
        if figs is None:
            return None
        nums, rest = figs
        new.numbers, new.bullets = nums, rest
        return s.model_copy(update={"kind": PatternKind.stat_row, "content": new}, deep=True)
    if kind == "table" and c.numbers and not (c.chart or c.table or c.items or c.columns or c.paragraphs) and len(c.bullets) <= 5:
        # changes «300 → 330 ₽» as a table «Показатель | Сейчас | Цель», the list under it: the denser form
        t = _table_of_changes(c.numbers)
        if t is not None:
            new.table, new.bullets = t, list(c.bullets)
            return s.model_copy(update={"kind": PatternKind.table, "content": new}, deep=True)
    if kind != s.kind.value and kind in ("chart", "stat_row", "big_number", "table") and text:
        return None  # a figure form cannot carry the slide's lines: the variant keeps its form
    if kind in ("bullets", "cards", "process", "timeline", "two_column", "comparison") and (c.chart is not None or c.table is not None):
        return None
    if kind == "chart":
        ch = c.chart.model_copy(deep=True) if c.chart is not None else (_chart_from_pairs(pairs) if c.numbers else None) or _chart_from_table(c.table)
        if ch is None:
            return None
        if chart_type:
            if chart_type in ("pie", "doughnut"):
                probe = ch.model_copy(update={"type": chart_type})
                # a pie of the parts of one whole only: never a before/after pair, never a row of figures turned into
                # a chart (their «shares» would be made up)
                if c.numbers or not pie_ok(probe) or not 2 <= len(ch.categories) <= 7:
                    return None
            ch.type = chart_type  # type: ignore[assignment]
        new.chart = ch
        new.chart2 = c.chart2.model_copy(deep=True) if c.chart2 is not None else None
    elif kind in ("stat_row", "big_number"):
        if c.numbers:
            nums = [n.model_copy() for n in c.numbers]
        elif pairs and c.chart2 is None:
            nums = [NumberCallout(value=v, label=lb) for lb, v, _ in pairs]
        else:
            nums = []
        if kind == "stat_row" and not 2 <= len(nums) <= 4:
            return None
        if kind == "big_number":
            if len(nums) == 2 and c.chart is not None and len(c.chart.categories) == 2 and not c.numbers:
                nums = [NumberCallout(value=f"{nums[0].value} → {nums[1].value}", label=c.chart.title or s.headline)]
            if len(nums) != 1:
                return None
        new.numbers = nums
    elif kind == "table":
        t = c.table.model_copy(deep=True) if c.table is not None else _table_from_chart(c.chart) if c.chart is not None and c.chart2 is None else _table_from_pairs(pairs) if c.numbers else None
        if t is None:
            return None
        new.table = t
    elif kind in ("cards", "process", "timeline"):
        if c.items and (kind != "cards" or len(c.items) <= 6):
            items = [it.model_copy() for it in c.items]
        elif kind == "cards" and c.numbers and 2 <= len(c.numbers) <= 4 and not (c.bullets or c.paragraphs):
            items = [SlideItem(title=n.label, number=n.value) for n in c.numbers]
        elif c.bullets and not (c.chart or c.table or c.numbers):
            items = _items_from_lines(c.bullets) or []
        else:
            items = []
        if len(items) < (3 if kind != "cards" else 2):
            return None
        new.items = items
        if c.items or c.bullets:
            new.numbers = [n.model_copy() for n in c.numbers]
    elif kind in ("two_column", "comparison"):
        if c.columns:
            cols = [it.model_copy() for it in c.columns]
        elif 2 <= len(c.items) <= 3 and all(it.bullets or it.text for it in c.items):
            cols = [SlideItem(title=it.title, bullets=it.bullets or [it.text]) for it in c.items]
        else:
            return None
        new.columns = cols
        new.numbers = [n.model_copy() for n in c.numbers]
    elif kind == "bullets":
        # a list shows its figures as lines («Покупок в день: 100 → 115»), never as a row of figures under another name
        lines = [f"{H.strip_end(n.label)}: {n.value}" if n.label else n.value for n in c.numbers] + _lines_of(s, case_text)
        if not lines or len(lines) > MAX_BULLETS or any(len(x.split()) > 18 for x in lines):
            return None
        new.bullets = lines
    else:
        return None
    return s.model_copy(update={"kind": PatternKind(kind), "content": new}, deep=True)


def _slide_alternatives(s: OutlineSlide, alts: list[Alternative], primary: Optional[OutlineSlide], text: str = "") -> list[SlideAlternative]:
    """The other forms of the slide for the outline (the compiler's variety pass and «Почему слайд такой»): the
    designer's alternatives and its primary form when the variant shows another one, each with its content when this
    module can reshape the slide into it."""
    out: list[SlideAlternative] = []
    cands: list[tuple[str, Optional[str], str, OutlineSlide]] = []
    if primary is not None and primary.kind != s.kind:
        cands.append((primary.kind.value, primary.content.chart.type if primary.content.chart else None, primary.rationale or "", primary))
    cands.extend((a.kind, a.chart_type, a.why, primary or s) for a in alts)
    for kind, ctype, why, base in cands:
        if kind == s.kind.value and not (kind == "chart" and ctype and s.content.chart is not None and ctype != s.content.chart.type):
            continue
        if any(x.kind == kind for x in out):
            continue
        r = reshape(base, kind, ctype, text)
        change = why or _ALT_WHY.get(kind, "")
        if kind == "chart" and ctype:
            change = f"{_CHART_RU.get(ctype, ctype)}: {change}" if change else _CHART_RU.get(ctype, ctype)
        out.append(SlideAlternative(kind=kind, change=change, content=r.content if r is not None else None))
    return out[:3]


# ------------------------------------------------------------------ variants


@dataclass
class _Placed:
    """A slide of a variant and the storyline unit(s) it presents."""

    slide: OutlineSlide
    units: list[str]
    locked: bool = False


def _rank(kind: str, prefer: list[str]) -> int:
    return prefer.index(kind) if kind in prefer else len(prefer)


def _thin(p: _Placed) -> bool:
    s = p.slide
    c = s.content
    if p.locked or s.kind.value in FRAME_KINDS or c.chart or c.table or c.formula or c.items or c.columns:
        return False
    if s.kind == PatternKind.big_number:
        return True
    return s.kind == PatternKind.bullets and len(c.bullets) + len(c.paragraphs) <= 3 and not c.numbers


def _merge(a: _Placed, b: _Placed) -> Optional[_Placed]:
    sa, sb = a.slide, b.slide
    if sa.kind == PatternKind.big_number and sb.kind == PatternKind.big_number:
        content = SlideContent(numbers=[*sa.content.numbers, *sb.content.numbers][:4])
        kind = PatternKind.stat_row
    elif sa.kind == PatternKind.bullets and sb.kind == PatternKind.bullets:
        content = SlideContent(columns=[SlideItem(title=sa.headline, bullets=[*sa.content.paragraphs, *sa.content.bullets]), SlideItem(title=sb.headline, bullets=[*sb.content.paragraphs, *sb.content.bullets])])
        kind = PatternKind.two_column
    else:
        return None
    merged = sa.model_copy(update={"kind": kind, "content": content, "notes": " ".join(x for x in (sa.notes, sb.notes) if x), "takeaway": sb.takeaway or sa.takeaway, "rationale": "Два коротких слайда объединены: вариант плотнее."}, deep=True)
    return _Placed(slide=merged, units=[*a.units, *b.units])


def _variety(placed: list[_Placed], alts: dict[str, list[Alternative]], primary: Optional[dict[str, OutlineSlide]] = None, prefer: Optional[list[str]] = None, case_text: str = "") -> list[str]:
    """No two neighbours of one form when one of them has an alternative that fits: of the two, the switch whose new
    form the variant prefers most (`prefer`, best first; the second slide on a tie). Two neighbours of one of the
    variant's three favourite forms stay (the visual variant's figures, the compact one's tables): its style, not a
    monotony — three in a row the compiler still breaks."""
    notes = []
    prefer = list(prefer or [])

    def form(p: _Placed) -> str:
        s = p.slide
        return f"chart:{s.content.chart.type}" if s.kind == PatternKind.chart and s.content.chart is not None else s.kind.value

    for i in range(1, len(placed)):
        prev, cur = placed[i - 1], placed[i]
        if form(prev) != form(cur) or cur.slide.kind.value in FRAME_KINDS:
            continue
        if prefer and cur.slide.kind.value in prefer[:3]:
            continue
        best: Optional[tuple[int, int, _Placed, str, str]] = None  # (rank, order, the new placed slide, old kind, note)
        for order, j in enumerate((i, i - 1)):
            p = placed[j]
            if p.locked or len(p.units) != 1:
                continue
            around = {form(placed[k]) for k in (j - 1, j + 1) if 0 <= k < len(placed) and k != j}
            base = (primary or {}).get(p.units[0])
            options = ([Alternative(kind=base.kind.value, chart_type=base.content.chart.type if base.content.chart else None, why=base.rationale or "")] if base is not None else []) + alts.get(p.units[0], [])
            for a in options:
                src_slide = base if base is not None and a.kind == base.kind.value else p.slide
                r = reshape(src_slide, a.kind, a.chart_type, case_text)
                if r is None:
                    continue
                probe = _Placed(slide=r, units=p.units)
                if form(probe) in around or form(probe) == form(p):
                    continue
                if a.why:
                    r.rationale = a.why if a.why.endswith(".") else a.why[:1].upper() + a.why[1:] + "."
                key = (_rank(r.kind.value, prefer) if prefer else 0, order)
                if best is None or key < best[:2]:
                    best = (key[0], key[1], probe, p.slide.kind.value, f"variety: slide {j + 1} {p.slide.kind.value} → {r.kind.value}")
                break
        if best is not None:
            j = i if best[1] == 0 else i - 1
            placed[j] = best[2]
            notes.append(best[4])
    return notes


def series_form(d: _Design, ctx: _Ctx) -> Optional[OutlineSlide]:
    """The slide as a row of its before/after figures («35% → 33%» · доля расходов на продукты, «27 000 → 15 000 ₽» ·
    списания) with its list of words under them (the measures): the visual form of a slide that states its changes in
    words. None when the slide has fewer than two such series, a chart, a table or a formula, a figure the row would
    lose, or more lines than fit under it."""
    s, c = d.slide, d.slide.content
    if c.chart is not None or c.table is not None or c.formula:
        return None
    nums = _series_figures(d.unit, ctx)
    if not 2 <= len(nums) <= 4:
        return None
    big = [v for n in nums for v in figures(n.value)]
    lines = [*c.paragraphs, *c.bullets]
    lines += [_title_text(it, ctx.brief.text) for it in c.items]
    lines += [b for col in c.columns for b in (col.bullets or ([col.text] if col.text else []))]
    lines += [f"{n.value} {n.label}" for n in c.numbers]
    keep = []
    for ln in (x for x in lines if x and x.strip()):
        vs = figures(ln)
        if vs:
            if all(any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) for x in big) for v in vs):
                continue  # the row shows it big
            return None
        keep.append(H.strip_end(ln))
    if len(keep) > 5 or any(len(x.split()) > 14 for x in keep):
        return None
    return s.model_copy(update={"kind": PatternKind.stat_row, "content": SlideContent(numbers=nums, bullets=keep)}, deep=True)


def assemble(designs: list[_Design], strategy: Strategy, prefs: dict, ctx: _Ctx, overrides: Optional[dict[str, _Design]] = None) -> tuple[list[_Placed], list[str]]:
    """One variant's slides from the shared designs: the variant's preferred forms among each design's primary form
    and its alternatives (the user's requested forms stay), thin neighbours merged (compact, no fixed count), section
    dividers (structured, long decks without a fixed count), then the variety pass."""
    pref = prefs.get(strategy.name, {}) or {}
    prefer = [str(k) for k in pref.get("prefer") or []]
    switch_from = set(pref.get("switch_from") or [])
    notes: list[str] = []
    placed: list[_Placed] = []
    alts: dict[str, list[Alternative]] = {}
    fixed = bool(ctx.count or ctx.structure.specs)
    if pref.get("merge_thin") and fixed:
        # the user fixed the slides (their number, their order): the compact variant cannot merge them — it takes the
        # denser form of a slide instead (changes as a table, figures as lines)
        switch_from = switch_from | {"stat_row", "big_number"}
    for d in designs:
        d = (overrides or {}).get(d.unit.key, d)
        alts[d.unit.key] = d.alternatives
        s = d.slide.model_copy(deep=True)
        if prefer and not d.unit.locked and s.kind.value in switch_from:
            best, best_rank = s, _rank(s.kind.value, prefer)
            if "stat_row" in prefer[:3]:
                # the slide's own before/after data as big figures, its list of words under them
                r = series_form(d, ctx)
                if r is not None and _rank("stat_row", prefer) < best_rank:
                    best, best_rank = r, _rank("stat_row", prefer)
                    best.rationale = "Изменения показателей — крупными цифрами, список действий под ними."
            tries = list(d.alternatives)
            if prefer[:3].count("stat_row") and not any(a.kind == "stat_row" for a in tries):
                tries.append(Alternative(kind="stat_row", why="цифры списка крупно"))
            # the variant's own preferred forms, where the content fits them (reshape says): a plan by months as a
            # timeline, a budget as a chart, «A → B» figures as a row — not only the forms the designer listed
            for k in prefer[:5]:
                if not any(a.kind == k for a in tries) and not (k in ("timeline", "process") and not _sequential(d.slide)):
                    tries.append(Alternative(kind=k, why=_ALT_WHY.get(k, "")))
            for a in tries:
                r = reshape(d.slide, a.kind, a.chart_type, ctx.brief.text)
                if r is not None and _rank(r.kind.value, prefer) < best_rank:
                    best, best_rank = r, _rank(r.kind.value, prefer)
                    best.rationale = (a.why[:1].upper() + a.why[1:] + ".") if a.why else best.rationale
            s = best
        placed.append(_Placed(slide=s, units=[d.unit.key], locked=d.unit.locked))
    if pref.get("merge_thin") and not fixed:
        content = [p for p in placed if p.slide.kind.value not in FRAME_KINDS]
        floor = max(3, math.ceil(len(content) * float(strategy.slide_ratio or 0.7)))
        i = 1
        while i < len(placed) and sum(1 for p in placed if p.slide.kind.value not in FRAME_KINDS) > floor:
            a, b = placed[i - 1], placed[i]
            if _thin(a) and _thin(b) and a.slide.section == b.slide.section:
                m = _merge(a, b)
                if m is not None:
                    placed[i - 1: i + 1] = [m]
                    notes.append(f"compact: slides {a.units[0]} and {b.units[0]} merged")
                    continue
            i += 1
    if pref.get("sections") and not fixed:
        sections = [p.slide.section for p in placed if p.slide.section and p.slide.kind.value not in FRAME_KINDS]
        counts = {sec: sections.count(sec) for sec in set(sections)}
        if len([p for p in placed if p.slide.kind.value not in FRAME_KINDS]) >= 7 and sum(1 for n in counts.values() if n >= 2) >= 2:
            out: list[_Placed] = []
            last = None
            for p in placed:
                sec = p.slide.section
                if sec and sec != last and counts.get(sec, 0) >= 2 and p.slide.kind.value not in FRAME_KINDS:
                    out.append(_Placed(slide=OutlineSlide(id=f"sec_{len(out)}", kind=PatternKind.section, headline=sec, section=sec, rationale=_WHY["section"]), units=[], locked=True))
                if p.slide.kind.value not in FRAME_KINDS:
                    last = sec
                out.append(p)
            placed = out
    primary = {d.unit.key: (overrides or {}).get(d.unit.key, d).slide for d in designs}
    notes.extend(_variety(placed, alts, primary, prefer, ctx.brief.text))
    return placed, notes


# ------------------------------------------------------------------ plain-Russian descriptions


def form_ru(s: OutlineSlide) -> str:
    c = s.content
    k = s.kind.value
    if k == "chart" and c.chart is not None:
        text = f"{_CHART_RU.get(c.chart.type, 'диаграмма')} ({ru_count(len(c.chart.categories), 'категория', 'категории', 'категорий')})"
        if c.chart2 is not None:
            a, b = _CHART_RU.get(c.chart.type, "диаграмма"), _CHART_RU.get(c.chart2.type, "диаграмма")
            # «две столбчатые диаграммы», «два линейных графика»; two different charts are named one by one
            two = {"линейный график": "два линейных графика", "диаграмма с областями": "две диаграммы с областями", "диаграмма": "две диаграммы"}
            text = (two.get(a) or "две " + a.replace("ая диаграмма", "ые диаграммы")) if a == b else f"{a} и {b}"
    elif k == "table" and c.table is not None:
        text = f"таблица {len(c.table.rows)}×{len(c.table.columns)}"
    elif k in ("stat_row",):
        text = f"ряд чисел ({ru_count(len(c.numbers), 'число', 'числа', 'чисел')})"
    elif k in ("cards", "process", "timeline"):
        text = f"{_KIND_RU[k]} ({len(c.items)})"
    elif k == "bullets":
        text = f"список ({ru_count(len(c.bullets) + len(c.paragraphs), 'пункт', 'пункта', 'пунктов')})"
    else:
        text = _KIND_RU.get(k, k)
    if c.formula:
        text += ", формула"
    return text


def _plan_line(pos: int, s: OutlineSlide) -> str:
    c = s.content
    what = []
    for ch in (c.chart, c.chart2):
        if ch is not None:
            vals = ", ".join(f"{cat} {_fmt(v)}" for cat, v in zip(ch.categories[:7], ch.series[0].values[:7])) if ch.series else ""
            what.append(f"{ch.type} chart{f' «{ch.title}»' if ch.title else ''}: {vals}")
    if c.table is not None:
        what.append(f"table {len(c.table.rows)}×{len(c.table.columns)}: {' | '.join(c.table.columns)}")
    if c.numbers:
        what.append("figures: " + "; ".join(f"{n.value} {n.label}".strip() for n in c.numbers))
    if c.items:
        what.append(f"{len(c.items)} items: " + "; ".join((it.title or it.text)[:50] for it in c.items))
    if c.columns:
        what.append("columns: " + " | ".join(f"{col.title} ({len(col.bullets)})" for col in c.columns))
    lines = [*c.paragraphs, *c.bullets]
    if lines:
        words = sum(len(x.split()) for x in lines)
        what.append(f"{len(lines)} bullets, {words} words: " + " / ".join(x[:70] for x in lines))
    if c.formula:
        what.append(f"formula: {c.formula}")
    if s.takeaway:
        what.append(f"takeaway: {s.takeaway}")
    if s.footnote:
        what.append(f"footnote: {s.footnote}")
    return f"{pos}. [{s.kind.value}] «{s.headline}»" + (" — " + "; ".join(what) if what else "")


def _requests_of(spec: SlideSpec, ctx: _Ctx) -> list[str]:
    out = []
    for r in spec.charts:
        ids = [x for x in r.series_ids if x in ctx.series]
        kind = f"a {r.type} chart" if r.type else "a chart of a fitting type"
        out.append(f"{kind}: {r.what or 'the slide data'}" + (f" (data: {', '.join(ids)})" if ids else ""))
    if spec.table:
        tids = [ctx.table_index[j] for j in spec.table_ids if j in ctx.table_index]
        out.append("a table" + (f" (data: {', '.join(tids)})" if tids else ""))
    if spec.formula:
        out.append(f"show the formula: {spec.formula}")
    if spec.footnote:
        out.append(f"a small footnote: {spec.footnote}")
    if spec.takeaway:
        out.append(f"the takeaway, in the user's words: {spec.takeaway} (the headline then states something else: the slide's key figure or subject)")
    return out


# ------------------------------------------------------------------ result


@dataclass
class AgentResult:
    outlines: dict[str, DeckOutline]
    warnings: dict[str, list[str]]
    structure: BriefStructure
    by_model: bool = False
    model_slides: int = 0
    slides: int = 0
    calls: int = 0
    critic_issues: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    raw: list = field(default_factory=list)

    def summary(self, strategy: str) -> dict:
        """What the agent did for one variant (run_manifest.planner.agent)."""
        return {
            "name": AGENT_NAME, "version": AGENT_VERSION, "model_calls": self.calls, "slides_by_model": self.model_slides,
            "slides": self.slides, "critic_issues": self.critic_issues.get(strategy), "seconds": self.seconds,
        }


class _Calls:
    def __init__(self) -> None:
        self.n = 0
        self.lock = threading.Lock()

    def add(self) -> None:
        with self.lock:
            self.n += 1


def _complete(skills: Any, providers: Any, name: str, schema: type, variables: dict, deadline: Optional[float], calls: _Calls) -> Any:
    spec = skills.get(name)
    params = spec.params or {}
    messages = skills.build_messages(name, variables)
    provider = providers.get(spec.role)
    calls.add()
    return provider.complete(messages, schema=schema, temperature=float(params.get("temperature", 0.2)), max_tokens=int(params.get("max_tokens", 1500)), deadline=deadline)


def _resolve_facts(facts: FactsSource, brief: Brief, warnings: list[str], structure: Optional[BriefStructure] = None) -> FactsExtraction:
    """The facts registry: the one given, else the brief's figures with the analyst's series, tables and the facts
    its model read per block (extract_facts with the structure: no model call of its own)."""
    if facts is None and structure is not None:
        try:
            from verstka.planning.facts import extract_facts

            fx, fw = extract_facts(brief, None, None, structure=structure)
            warnings.extend(fw)
            return fx
        except Exception as e:  # noqa: BLE001 - the plain figures below
            warnings.append(f"facts registry unavailable: {str(e)[:160]}")
    try:
        if callable(facts):
            facts = facts()
        if isinstance(facts, tuple):
            if len(facts) > 1 and isinstance(facts[1], list):
                warnings.extend(str(w) for w in facts[1])
            facts = facts[0]
    except Exception as e:  # noqa: BLE001 - the registry is a help, not a must
        warnings.append(f"facts registry unavailable: {str(e)[:160]}")
        facts = None
    if isinstance(facts, FactsExtraction):
        return facts
    from verstka.planning.facts import basic_facts

    return basic_facts(brief.text, structure=structure)


def _budget_error(e: BaseException) -> bool:
    """The generation's time ran out (not the model's failure)."""
    try:
        from verstka.providers.openai_compat import BudgetSpent

        if isinstance(e, BudgetSpent):
            return True
    except Exception:  # noqa: BLE001
        pass
    return "time budget" in str(e)


def _deadline_for(clock: _Clock, seconds: float, before_end: float = 2.0) -> Optional[float]:
    if clock.deadline is None:
        return None
    return min(clock.deadline - before_end, time.monotonic() + seconds)


def _minimal_design(unit: _Unit, written: bool = False) -> _Design:
    """The last resort for a slide whose design failed: its heading and the first lines of its source."""
    if unit.cover:
        return _Design(unit=unit, slide=OutlineSlide(id=unit.key, kind=PatternKind.title, headline=unit.title or "Презентация"))
    if unit.closing:
        return _closing_design(unit)
    cut = _clause_cut if written else H.short
    lines = [cut(x, 14) for x in (H.split_sentences(unit.text) or [])[:4]] or [unit.title or "…"]
    s = OutlineSlide(id=unit.key, kind=PatternKind.bullets, headline=unit.title or lines[0], content=SlideContent(bullets=lines), spec_ref=unit.spec.number if unit.spec else None, rationale=_WHY["bullets"])
    return _Design(unit=unit, slide=s)


def _safe_rules(unit: _Unit, ctx: _Ctx) -> _Design:
    try:
        return rules_design(unit, ctx)
    except Exception as e:  # noqa: BLE001 - one slide's rules never stop the deck
        log.warning("rules_design failed on slide %s", unit.key, exc_info=True)
        d = _minimal_design(unit, ctx.written)
        d.failure = f"rules failed: {str(e)[:160]}"
        return d


class _Agent:
    def __init__(self, brief: Brief, manifest: Optional[TemplateManifest], strategies: list[Strategy], skills: Any, providers: Any, tracker: _Tracker, clock: _Clock, raw: Optional[list]) -> None:
        self.brief = brief
        self.manifest = manifest
        self.strategies = strategies
        self.skills = skills
        self.providers = providers
        self.tracker = tracker
        self.clock = clock
        self.raw = raw
        self.calls = _Calls()
        self.models = bool(skills is not None and providers is not None and providers.has("llm") and all(n in getattr(skills, "skills", {}) for n in SKILLS))
        self.workers = max(1, int(getattr(getattr(providers, "limits", None), "max_concurrency", 4) or 4))
        self.last_error: Optional[str] = None
        self.lock = threading.Lock()
        self.durations: list[float] = []  # seconds of the model calls that answered (the designer's, the critic's)
        self.fail_streak = 0
        self.first_wave = 0  # the number of designer calls started at once (min(workers, slides))
        self.broken = False  # the model failed call after call: the rest is taken deterministically

    # ---------------------------------------------------------------- the model's pace and health
    def need_s(self, calls: float = 1.0, floor: float = MIN_CALL_S) -> float:
        """The time a model step needs left before it starts: `calls` × CALL_MARGIN × the median of the calls that
        answered so far (a slow host: 45 s a call needs 54 s, not the fixed 12), never less than `floor`."""
        with self.lock:
            d = sorted(self.durations)
        if not d:
            return floor
        return max(floor, calls * CALL_MARGIN * d[len(d) // 2])

    def answered(self, seconds: float) -> None:
        with self.lock:
            self.durations.append(seconds)
            self.fail_streak = 0

    def failed(self, e: BaseException) -> None:
        """A model call failed. Not the budget's end (that is not the model's fault): after BREAKER_STREAK failures in
        a row — or a whole first wave when it is smaller — the agent stops asking (the circuit breaker): the slides
        left are designed by the rules and the critic and the revisions are skipped."""
        if _budget_error(e):
            return
        with self.lock:
            self.fail_streak += 1
            limit = max(1, min(BREAKER_STREAK, self.first_wave or BREAKER_STREAK))
            trip = not self.broken and self.fail_streak >= limit
            if trip:
                self.broken = True
        if trip:
            self.tracker.emit("designer", "Модель не отвечает — остальные слайды собраны по правилам, без неё.")

    # ---------------------------------------------------------------- architect
    def architect(self, ctx: _Ctx, warnings: list[str]) -> Optional[list[_Unit]]:
        sentences = numbered_sentences(self.brief.text)
        if not sentences:
            return None
        left = self.clock.left()
        if not self.models or left < MIN_CALL_S + 30:
            why = "модель недоступна" if not self.models else "не хватает времени"
            self.tracker.emit("architect", f"Архитектор: бриф не разбит на слайды, а {why} — план составит встроенный планировщик.")
            warnings.append("deck_architect skipped: " + ("no model" if not self.models else "time budget of the generation is spent"))
            return None
        count = ctx.count
        closing = not count or count >= 5
        if count:
            n_content = max(1, count - (2 if closing else 1))
            rule = f"exactly {n_content} content slides (the deck has {count} slides with the cover{' and the closing slide' if closing else ''})."
        else:
            n_content = MAX_CONTENT_SLIDES
            rule = f"as many content slides as the brief's content supports, at most {MAX_CONTENT_SLIDES}; fewer strong slides are better than padded ones."
        variables = {
            "audience": self.brief.audience or "не указана", "purpose": self.brief.purpose or "не указана", "language": self.brief.language,
            "title_hint": ctx.structure.title or self.brief.title_hint or "", "rules": ctx.rules, "count_rule": rule,
            "sentences": "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences, 1)),
            "data": _data_lines(ctx, list(ctx.series), list(ctx.tables), [fid for fid, f in ctx.facts.items() if _clean_fact(f)][:30]),
        }
        try:
            res = _complete(self.skills, self.providers, "deck_architect", StorylineAnswer, variables, _deadline_for(self.clock, min(ARCHITECT_MAX_S, max(10.0, left - 60)), 2.0), self.calls)
            _keep_raw(self.raw, "architect", None, res=res)
            ans: StorylineAnswer = res.parsed
        except Exception as e:  # noqa: BLE001 - a failed storyline hands the deck to the planner
            _keep_raw(self.raw, "architect", None, error=e)
            self.last_error = str(e)
            warnings.append(f"deck_architect failed, the planner takes over: {str(e)[:160]}")
            self.tracker.emit("architect", "Архитектор: модель не составила сюжет — план составит встроенный планировщик.")
            return None
        units: list[_Unit] = []
        used: set[int] = set()
        for i, ss in enumerate(ans.slides, 1):
            idx = [n for n in ss.sentences if 1 <= n <= len(sentences) and n not in used]
            used.update(idx)
            text = "\n".join(sentences[n - 1] for n in idx)
            sids = [x for x in ss.data if x in ctx.series]
            tids = [x for x in ss.data if x in ctx.tables]
            fids = [x for x in ss.data if x in ctx.facts] or _facts_in(ctx, text)
            if not text and not sids and not tids:
                continue
            units.append(_Unit(key=f"u{i}", title=H.strip_end(ss.title) or H.short(text, 8), text=text, section=ss.section, form=ss.form, series_ids=sids, table_ids=tids, fact_ids=fids))
        if not units:
            warnings.append("deck_architect answer rejected (no slide refers to the brief), the planner takes over")
            self.tracker.emit("architect", "Архитектор: сюжет модели не опирается на бриф — план составит встроенный планировщик.")
            return None
        units = units[:n_content]
        taken = {x for u in units for x in u.series_ids}
        for sid, s in ctx.series.items():
            if sid in taken or not s.source_span:
                continue
            host = next((u for u in units if s.source_span[:40] and s.source_span[:40] in u.text), None)
            if host is not None:
                host.series_ids.append(sid)
        title = ctx.structure.title or ans.title or ctx.title
        ctx.title = title
        out = [_Unit(key="u0", title=title, cover=True), *units]
        if closing:
            out.append(_Unit(key="u_end", title="Спасибо за внимание", closing=True))
        names = ", ".join(f"«{u.title}»" for u in units[:6]) + ("…" if len(units) > 6 else "")
        self.tracker.emit("architect", f"Архитектор: сюжет из {ru_count(len(units), 'слайда', 'слайдов', 'слайдов')} — {names}.")
        return out

    # ---------------------------------------------------------------- designer
    def _variables(self, unit: _Unit, pos: int, units: list[_Unit], ctx: _Ctx, issues: str = "", previous: str = "") -> dict:
        prev = units[pos - 2].title if pos >= 2 else ""
        nxt = units[pos].title if pos < len(units) else ""
        return {
            "deck_title": ctx.title, "audience": self.brief.audience or "не указана", "purpose": self.brief.purpose or "не указана",
            "language": self.brief.language, "position": pos, "total": len(units), "prev_title": prev, "next_title": nxt,
            "rules": ctx.rules, "slide_title": unit.title, "slide_text": unit.text.strip() or unit.title,
            "requests": "\n".join(f"- {r}" for r in (_requests_of(unit.spec, ctx) if unit.spec else [])) or ("" if not unit.form else f"- suggested form: {unit.form}"),
            "data": _data_lines(ctx, unit.series_ids, unit.table_ids, unit.fact_ids), "kinds": ctx.kinds,
            "issues": issues, "previous": previous,
        }

    def model_design(self, unit: _Unit, pos: int, units: list[_Unit], ctx: _Ctx, deadline: Optional[float], issues: str = "", previous: str = "") -> _Design:
        step = "revise" if issues else "designer"
        try:
            res = _complete(self.skills, self.providers, "slide_designer", SlideDesignAnswer, self._variables(unit, pos, units, ctx, issues, previous), deadline, self.calls)
            _keep_raw(self.raw, step, unit.key, res=res)
        except Exception as e:  # noqa: BLE001
            _keep_raw(self.raw, step, unit.key, error=e)
            raise
        d = design_from_answer(res.parsed, unit, ctx)
        if d is None:
            raise ValueError("the designer's answer has no content for the slide")
        d.model = getattr(res, "label", None) or getattr(res, "model", None)
        return d

    def design_all(self, units: list[_Unit], ctx: _Ctx, phase_end: Optional[float]) -> list[_Design]:
        pos_of = {u.key: i for i, u in enumerate(units, 1)}
        results: dict[str, _Design] = {}

        def finish(d: _Design) -> None:
            enforce_requests(d, ctx)
            tidy_design(d, ctx)
            results[d.unit.key] = d
            pos = pos_of[d.unit.key]
            s = d.slide
            if d.unit.cover:
                msg = f"Дизайнер: слайд {pos} — обложка «{s.headline}»" + (", мелким текстом — условность данных" if s.footnote else "") + "."
            elif d.unit.closing:
                msg = f"Дизайнер: слайд {pos} — финальный слайд."
            elif d.by == "model":
                msg = f"Дизайнер: слайд {pos} «{s.headline}» — {form_ru(s)}."
            else:
                why = " (модель не ответила)" if d.failure else ""
                msg = f"Дизайнер: слайд {pos} «{s.headline}» собран по правилам{why} — {form_ru(s)}."
            self.tracker.emit("designer", msg, slide=pos)

        def work(u: _Unit) -> _Design:
            if not self.models or u.frame:
                return _safe_rules(u, ctx)
            if self.broken:
                d = _safe_rules(u, ctx)
                d.failure = "the model is not answering (it failed call after call), the rules designed the rest"
                return d
            need = self.need_s()
            if self.clock.left() < need or (phase_end is not None and phase_end - time.monotonic() < need):
                d = _safe_rules(u, ctx)
                d.failure = "time budget of the generation is spent"
                return d
            t = time.monotonic()
            try:
                d = self.model_design(u, pos_of[u.key], units, ctx, phase_end)
            except Exception as e:  # noqa: BLE001 - the slide is designed by the rules instead
                self.failed(e)
                d = _safe_rules(u, ctx)
                d.failure = str(e)
                self.last_error = str(e)
                return d
            self.answered(time.monotonic() - t)
            return d

        def done(d: _Design) -> None:
            try:
                finish(d)
            except Exception as e:  # noqa: BLE001 - one slide's error never stops the deck: the rules' slide, else a minimal one
                log.warning("finishing slide %s failed", d.unit.key, exc_info=True)
                d2 = _safe_rules(d.unit, ctx)
                d2.failure = d.failure or f"the slide could not be finished: {str(e)[:160]}"
                try:
                    finish(d2)
                except Exception:  # noqa: BLE001
                    results[d.unit.key] = _minimal_design(d.unit, ctx.written)

        for u in units:
            if u.frame or not self.models:
                done(work(u))
        todo = [u for u in units if u.key not in results]
        if todo:
            self.first_wave = min(self.workers, len(todo))
            with ThreadPoolExecutor(max_workers=min(self.workers, len(todo))) as ex:
                futs = {ex.submit(work, u): u for u in todo}
                for f in as_completed(futs):
                    try:
                        d = f.result()
                    except Exception as e:  # noqa: BLE001
                        u = futs[f]
                        log.warning("designing slide %s failed", u.key, exc_info=True)
                        d = _minimal_design(u, ctx.written)
                        d.failure = str(e)
                    done(d)
        return [results[u.key] for u in units]

    # ---------------------------------------------------------------- critic
    def critique(self, name: str, title: str, hint: str, placed: list[_Placed], units: list[_Unit], ctx: _Ctx, deadline: Optional[float]) -> list[tuple[str, str]]:
        """(unit key, «problem → fix») of one variant's plan."""
        pos_of_spec = {p.slide.spec_ref: i for i, p in enumerate(placed, 1) if p.slide.spec_ref is not None}
        requests = []
        for u in units:
            if u.spec is not None and not u.frame:
                reqs = _requests_of(u.spec, ctx)
                if reqs and u.spec.number in pos_of_spec:
                    requests.append(f"- slide {pos_of_spec[u.spec.number]}: " + "; ".join(reqs))
        brief_text = self.brief.text.strip()
        if len(brief_text) > CRITIC_BRIEF_CHARS:
            brief_text = brief_text[:CRITIC_BRIEF_CHARS].rsplit("\n", 1)[0] + "\n…"
        variables = {
            "brief": brief_text, "rules": ctx.rules, "requests": "\n".join(requests), "variant": title, "variant_hint": hint,
            "plan": "\n".join(_plan_line(i, p.slide) for i, p in enumerate(placed, 1)), "language": self.brief.language,
        }
        try:
            res = _complete(self.skills, self.providers, "design_critic", CritiqueAnswer, variables, deadline, self.calls)
            _keep_raw(self.raw, "critic", None, res=res, variant=name)
        except Exception as e:  # noqa: BLE001
            _keep_raw(self.raw, "critic", None, error=e, variant=name)
            raise
        out: list[tuple[str, str]] = []
        titles = {u.key: u.title for u in units}
        units_by_key = {u.key: u for u in units}
        for it in res.parsed.issues[:6]:
            it.slide = _quoted_slide(it.problem, it.slide, placed)
            if not 1 <= it.slide <= len(placed):
                continue
            p = placed[it.slide - 1]
            if not p.units or p.slide.kind.value in FRAME_KINDS:
                continue
            why = _false_alarm(it.problem, it.slide, placed, ctx, titles)
            if why is not None:
                _keep_raw(self.raw, "critic_dropped", p.units[0], variant=name, error=ValueError(f"{why}: {it.problem[:160]}"))
                continue
            harm = _harmful_fix(it.problem, it.fix or "", p.slide, units_by_key.get(p.units[0]), ctx)
            if harm is not None:
                # the reviewer's own fix would make the slide worse: a note about the headline goes whole (its problem is
                # the fix's premise — «the headline must be the user's conclusion»), so does a note resting on figures
                # the brief does not give or bringing another slide's; a note about the takeaway keeps its problem
                # without the fix
                if _HEAD_NOTE_RE.search(it.problem) or harm in ("the note rests on figures the brief does not give", "the fix brings another slide's figures"):
                    _keep_raw(self.raw, "critic_dropped", p.units[0], variant=name, error=ValueError(f"{harm}: {it.problem[:120]} → {it.fix[:80]}"))
                    continue
                it.fix = ""
            if takeaway_note(it.problem):
                # acted on without a model: the takeaway goes, the source's own result takes its place
                out.append((p.units[0], TAKEAWAY_FIX + it.problem))
                continue
            out.append((p.units[0], f"{it.problem}" + (f" → {it.fix}" if it.fix else "")))
        return out


_NOT_IN_BRIEF_RE = re.compile(
    r"нет\s+в\s+брифе|не\s+(?:указан\w*|упомина\w*|привед[её]н\w*|встреча\w*)\s+в\s+брифе|отсутству\w*\s+в\s+брифе|"
    r"не\s+из\s+брифа|выдуман|придуман|not\s+in\s+the\s+brief|invented|made[- ]up",
    re.I,
)
_SAME_FORM_RE = re.compile(r"соседн|подряд|одного\s+(?:формата|вида|типа)|одинаков\w*\s+(?:формат|вид|тип)|same\s+(?:form|kind|format)|neighbou?r", re.I)
_SLIDE_NUM_RE = re.compile(r"(?:слайд\w*|slides?)\s*(\d{1,2})(?:\s*(?:и|and|,|–|-)\s*(\d{1,2}))?", re.I)


# «Вывод повторяет заголовок»: the takeaway (the subject) repeats the headline (the object)
_REPEAT_RE = re.compile(
    r"(?:вывод|takeaway|итог)\w*\s+(?:\S+\s+){0,3}(?:повторя|дублир)\w*\s+(?:\S+\s+){0,2}заголов|"
    r"(?:вывод|takeaway)\w*\s+(?:\S+\s+){0,2}(?:повторя|дублир)\w*\s*[.!]?$|repeats?\s+the\s+headline",
    re.I,
)
_OVERLOAD_RE = re.compile(
    r"перегруж|много\s+текста|(?:более|больше)\s+(?:\d|шести|пяти|четыр)|слишком\s+(?:много|длинн)|превыша\w*\s+рекомендуем|"
    r"сократ\w*\s+(?:количество\s+)?(?:пункт\w*\s+)?до\s+\d|text[- ]heavy|overload|too\s+much\s+text|text\s+wall|too\s+many",
    re.I,
)
_TOPIC_RE = re.compile(
    r"заголов\w*\s+(?:\S+\s+){0,2}(?:не\s+(?:отража|формулир|содерж|явля|выража|да[её]т|сообща)|называ\w*\s+тем|описыва\w*\s+(?:тем|содерж)|"
    r"повторя\w*\s+(?:назван|тем|заголов|общ|контекст)|—\s*тема|является\s+темой|слишком\s+общ|общ\w*|абстрактн|размыт|расплывчат)|"
    r"(?:names?|states?)\s+(?:a|the)\s+topic|topic\s+instead|vague\s+headline",
    re.I,
)
_QUESTION_HEAD_RE = re.compile(r"^(?:как|что|куда|почему|зачем|какие|какой|где|когда|сколько|how|what|why|where)\b", re.I)
# «Три направления для роста прибыли», «Пять стратегий…», «4 ключевых действия»: a list announced, not a conclusion
# (a count and a noun: «Три барьера для роста прибыли» — a list announced when the headline has no verb nor figure)
_ANNOUNCE_RE = re.compile(r"^(?:два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|\d{1,2})\s+(?:[а-яё]+\s+){0,2}?[а-яё]{3,}", re.I)
_COUNT_WORD = {"два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8}
# a finite verb, a short participle or a dash as the verb: «вырастет», «держится», «сосредоточены», «Кофе — 60% выручки»
_VERB_RE = re.compile(
    r"(?<![\wё])[а-яё]{2,}(?:ет|ит|ут|ют|ат|ят|ется|ится|утся|ются|атся|ятся|ал|ала|ало|али|ил|ила|ило|или|ел|ела|ело|ели|ся|сь|ен|ена|ено|ены|ан|ана|ано|аны|ят|ет)(?![\wё])",
    re.I,
)
_NOT_VERBS = frozenset(
    """бюджет совет предмет ответ отчет отчёт расчет расчёт счет счёт кабинет пакет билет момент клиент процент эффект
    проект аспект результат продукт пункт контракт формат вариант стандарт факт кредит лимит визит аудит депозит
    объект элемент документ сегмент компонент инструмент рецепт приоритет авторитет интернет маркет предел план
    сайт ассортимент потенциал персонал канал капитал сигнал материал интервал""".split()
)
# a note about what a figure or a line means, not whether it is in the brief («31% срывов связано с…»): the agent
# cannot check it and never drops it
_MEANING_RE = re.compile(
    r"связа[нв]|означа|значени|смысл|относит|трактов|интерпрет|приписыва|перепута|путает|вместо|\bа\s+не\b|не\s+соответств|"
    r"искаж|гарант|как\s+факт|как\s+(?:уже\s+)?достигнут|уже\s+(?:достигн|произош|случил)|прошедш\w*\s+врем|будущ|прогноз|"
    r"не\s+подтвержд|нет\s+основан|не\s+следует|не\s+утвержда|утвержден\w*,?\s+(?:что|котор)|до\s+запуск|доля\s+до",
    re.I,
)


def _form_key(s: OutlineSlide) -> str:
    return f"chart:{s.content.chart.type}" if s.kind == PatternKind.chart and s.content.chart is not None else s.kind.value


def headline_states(head: str) -> bool:
    """A headline that states something: a figure of the slide, or a verb (a finite one, a short participle, a dash
    for the verb) — and not a list announced («Три направления для роста прибыли») nor a question."""
    h = (head or "").strip()
    if not h or _QUESTION_HEAD_RE.search(h):
        return False
    if figures(h) or re.search(r"\s[—–]\s", h):
        return True
    verb = any(m.group(0).lower() not in _NOT_VERBS for m in _VERB_RE.finditer(h))
    return verb  # «Три направления для роста прибыли» has none; «Пять показателей покажут рост» has one


def _slide_words(s: OutlineSlide) -> tuple[int, int]:
    """(lines, words) of the text a slide shows."""
    c = s.content
    lines = [*c.bullets, *c.paragraphs, *(f"{it.title} {it.text}" for it in c.items), *(b for col in c.columns for b in [col.title, *col.bullets])]
    return len(c.bullets) + len(c.paragraphs), sum(len(x.split()) for x in lines)


def _literal_figures(text: str, ctx: _Ctx) -> Optional[bool]:
    """Whether every figure quoted in a critic's note is written in the brief as it is (None: the note quotes none)."""
    try:
        from verstka.planning.grounding import figures as gfigs
    except Exception:  # noqa: BLE001
        gfigs = None
    if gfigs is None or ctx.index is None:
        vals = figures(text)
        return None if not vals else all(any(abs(v - a) <= 1e-6 * max(1.0, abs(a)) for a in ctx.allowed) for v in vals)
    figs = [f for f in gfigs(text) if f.date is None]
    if not figs:
        return None
    return all(any(p.fig.unit is None or f.unit is None or p.fig.unit == f.unit for p in ctx.index._same(f)) for f in figs)


def _false_alarm(text: str, pos: int, placed: list["_Placed"], ctx: _Ctx, titles: Optional[dict[str, str]] = None) -> Optional[str]:
    """Why a critic's note is not acted on (None: it is) — the agent checks a reviewer's claim before a slide is
    redone, only where the plan itself answers it: a figure «not in the brief» that the brief writes as it is (and the
    note says nothing about what the figure means), two neighbours «of the same form» the plan shows in different
    forms, a takeaway «repeating» a headline when it carries a figure the headline does not, a slide «overloaded» with
    at most 6 lines and 70 words, a «topic» headline that states something (a figure or a verb, not a list announced,
    not the user's heading). A note on meaning (a figure used for something its source does not say, a claim the
    source does not make, a forecast told as done) is never dropped: no program checks meaning."""
    s = placed[pos - 1].slide
    if _TOPIC_RE.search(text):
        head = s.headline or ""
        own = (titles or {}).get(placed[pos - 1].units[0], "") if placed[pos - 1].units else ""
        if headline_states(head) and not (same_text(head, own) or H.strip_end(head).lower() == H.strip_end(own).lower()):
            return "the headline states a conclusion"
        return None
    if _REPEAT_RE.search(text):
        if s.takeaway and figures(s.takeaway) and not same_text(s.takeaway, s.headline) and not set(figures(s.takeaway)) <= set(figures(s.headline or "")):
            return "the takeaway does not repeat the headline"
        return None
    if _OVERLOAD_RE.search(text):
        lines, words = _slide_words(s)
        if lines <= MAX_BULLETS and words <= 70:
            return "the slide is not overloaded"
    if _NOT_IN_BRIEF_RE.search(text):
        if _MEANING_RE.search(text):
            return None
        if _literal_figures(text, ctx):
            return "a number the brief has"
        return None
    if _SAME_FORM_RE.search(text):
        nums = {int(x) for m in _SLIDE_NUM_RE.finditer(text) for x in m.groups() if x}
        pair = sorted(n for n in nums if 1 <= n <= len(placed))
        if len(pair) >= 2:
            forms = {_form_key(placed[n - 1].slide) for n in pair}
            if len(forms) > 1:
                return "the plan shows these slides in different forms"
        else:
            me = _form_key(placed[pos - 1].slide)
            around = [_form_key(placed[k].slide) for k in (pos - 2, pos) if 0 <= k < len(placed)]
            if me not in around:
                return "no neighbour of the same form"
    return None


_HEAD_NOTE_RE = re.compile(r"заголов|headline", re.I)
_TAKEAWAY_NOTE_RE = re.compile(r"вывод|takeaway|conclusion", re.I)


def _harmful_fix(problem: str, fix: str, s: OutlineSlide, unit: Optional[_Unit], ctx: Optional[_Ctx] = None) -> Optional[str]:
    """Why a reviewer's note would make the slide worse (None: it would not): it rests on a figure the brief does not
    give («… соответствует 1 134 000 рублей»), or its proposed wording brings another slide's figures (a note sent to
    the wrong slide), makes the user's own conclusion the headline (the takeaway's place), is a topic question, a list
    announced, a cause the brief does not state, or a takeaway that is the headline in other words."""
    if ctx is not None and ctx.index is not None:
        try:
            from verstka.planning.grounding import figures as gfigs

            note = f"{problem} {fix}"
            bad = [f for f in gfigs(note) if f.date is None and not f.approx and ctx.index.verdict(f) == "bad" and not re.fullmatch(r"\d{1,2}", note[f.start : f.uend].strip())]
            if bad:
                return "the note rests on figures the brief does not give"
        except Exception:  # noqa: BLE001
            pass
    quotes = [q.strip() for q in re.findall(r"«([^«»]{6,200})»", fix or "")]
    if not quotes:
        return None
    if unit is not None and unit.spec is not None and any(foreign_figures(q, unit, ctx) for q in quotes):
        return "the fix brings another slide's figures"
    about_head = bool(_HEAD_NOTE_RE.search(problem or ""))
    users = unit.spec.takeaway if unit is not None and unit.spec is not None else None
    for q in quotes:
        if about_head and users and (same_text(q, users) or adds_nothing(q, users)):
            return "the fix makes the user's conclusion the headline"
        if about_head and (_QUESTION_HEAD_RE.search(q) or _announces(q)):
            return "the fix proposes a topic or a list announced as the headline"
        if unit is not None and invented_cause(q, unit.text):
            return "the fix states a cause the brief does not"
        if not about_head and _TAKEAWAY_NOTE_RE.search(problem or "") and adds_nothing(q, s.headline):
            return "the fix proposes the headline as the takeaway"
    return None


def _quoted_slide(text: str, pos: int, placed: list["_Placed"]) -> int:
    """The slide a critic's note is about: the number it gives, unless the note quotes («…») the headline or a line of
    exactly one other slide and nothing of that one — a reviewer model counts slides off by one now and then (the
    cover left out), and a note acted on at the wrong slide is a wasted revision."""
    quotes = [q.strip() for q in re.findall(r"«([^«»]{6,160})»", text or "")]
    if not quotes:
        return pos

    def says(p: "_Placed", q: str) -> bool:
        s = p.slide
        texts = [s.headline, s.takeaway or "", *s.content.bullets, *s.content.paragraphs, *(f"{i.title} {i.text}" for i in s.content.items)]
        low = q.lower()
        return any(x and (low in x.lower() or same_text(q, x)) for x in texts)

    if 1 <= pos <= len(placed) and any(says(placed[pos - 1], q) for q in quotes):
        return pos
    hits = {i for i, p in enumerate(placed, 1) for q in quotes if says(p, q)}
    return hits.pop() if len(hits) == 1 else pos


def takeaway_note(text: str) -> bool:
    """A critic's note that the slide's takeaway repeats its headline: acted on without a model (the takeaway goes, the
    source's own result takes its place)."""
    return bool(_REPEAT_RE.search(text)) and not _TOPIC_RE.search(text)


def _stems_of(text: str) -> list[str]:
    return [w[:5] for w in _words(text) if len(w) >= 4]


def _visible_text(s: OutlineSlide) -> str:
    """What a slide shows (not its notes): headline, lines, cards, columns, figures, table, chart labels, conclusion."""
    c = s.content
    parts = [s.headline, s.subtitle or "", s.takeaway or "", c.formula or "", *c.bullets, *c.paragraphs]
    parts += [f"{it.title} {it.text} {' '.join(it.bullets)} {it.number or ''}" for it in [*c.items, *c.columns]]
    parts += [f"{n.value} {n.label}" for n in c.numbers]
    if c.table is not None:
        parts += [*c.table.columns, *(cell for row in c.table.rows for cell in row)]
    for ch in (c.chart, c.chart2):
        if ch is not None:
            parts += [ch.title or "", *ch.categories, *(sr.name for sr in ch.series)]
    return " ".join(p for p in parts if p)


_TIME_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")


class _Shown:
    """The words a slide shows, by stem (grounding's stems: «кассой» and «кассы» are one word), and its figures."""

    def __init__(self, text: str) -> None:
        self.text = text
        try:
            from verstka.planning.grounding import _Stems, content_stems

            self.stems = _Stems(content_stems(text, neutral=True))
            self.stems_of = lambda x: content_stems(x, neutral=True)  # noqa: E731
        except Exception:  # noqa: BLE001
            words = set(_stems_of(text))
            self.stems = type("S", (), {"has": lambda _self, s: s[:5] in words})()
            self.stems_of = _stems_of  # noqa: E731
        self.figs = figures(text)

    def line(self, line: str) -> bool:
        """The slide shows this line of its source: its figures («65%», «27 000» — a line of a figure is shown by its
        figure, not by its words: «Доля покупателей, вернувшихся в течение 30 дней, — 25%» is not shown by «доля» and
        «покупок» elsewhere), or, for a line of words, half of them."""
        vals = [v for v in figures(_PERIOD_RE.sub(" ", _TIME_RE.sub(" ", line or ""))) if v]
        if vals:
            if any(any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) for x in self.figs) for v in vals):
                return True
            if any(v >= 10 or not float(v).is_integer() for v in vals):
                return False
        stems = self.stems_of(line)
        if not stems:
            return True
        return sum(1 for w in stems if self.stems.has(w)) * 2 >= len(stems)

    def figure(self, v: float) -> bool:
        return any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) or (abs(v) >= 1000 and abs(v - x * 1000) <= 500) for x in self.figs)


def _line_shown(line: str, shown: set[str], text: str) -> bool:
    return _Shown(text).line(line)


_TOTAL_RE = re.compile(r"^(?:общ(?:ие|ий|ая|ее)|итого|всего|суммарн\w*)\b", re.I)
_RISK_RE = re.compile(r"риск", re.I)
_MEASURE_RE = re.compile(r"мер[ыау]?\b|меры|действи|предлож|что\s+делать|решени", re.I)


def _content_lines(s: OutlineSlide) -> list[str]:
    """The slide's own statements the designer wrote (not its headline, takeaway or notes): lines, card texts, column
    lines."""
    c = s.content
    out = [*c.bullets, *c.paragraphs]
    out += [x for it in c.items for x in (it.text, *it.bullets) if x]
    out += [b for col in c.columns for b in col.bullets]
    return [x for x in out if x and x.strip()]


# a short statement of a business measure with its figure, the measure first («Операционная прибыль — 120 000
# рублей», «Ежемесячные расходы кофейни составляют 780 000 рублей»): a key figure of its slide
_KEY_MEASURE_RE = re.compile(
    r"^(?!(?:при|если|в\s+случае)\s)(?:[а-яё0-9]+\s+){0,3}?(?:прибыл\w*|выручк\w*|расход\w*|затрат\w*|рентабельност\w*|бюджет\w*|вложени\w*|экономи\w*|"
    r"окупаемост\w*|доход\w*|марж\w*)(?![\wё])",
    re.I,
)
_KEY_VERB_RE = re.compile(
    r"\s[—–]\s|составля|состав(?:ит|ят)\b|достигн|обход(?:ится|ятся)|потребует|вырастет|вырастут|увеличится|снизится|\bдаст\b|\bдадут\b",
    re.I,
)
KEY_MAX_WORDS = 16
_BUSINESS_RESULT_RE = re.compile(r"(?:руб\w*|₽)\s+(?:дополнительно\s+)?(?:выручк|прибыл|экономи)|(?:выручк|прибыл|экономи)\w*\s+(?:\S+\s+){0,3}?(?:на|в|до|—)\s+\d", re.I)
KEY_LINE_MAX_WORDS = 14  # a key line longer than this is asked of the designer, never pasted under the block


def _has_figure(text: str) -> bool:
    """A figure in digits or in words («три четверти», «вдвое»)."""
    if figures(text):
        return True
    try:
        from verstka.planning.grounding import figures as gfigs

        return bool(gfigs(text or ""))
    except Exception:  # noqa: BLE001
        return False


def key_lines(text: str) -> list[str]:
    """The key figures of a slide, as its source states them: the goal («Цель — поднять средний чек с 300 до 330
    рублей»), the totals («Общие расходы — 780 000 рублей»), short statements of a business measure with its figure
    («Операционная прибыль — 120 000 рублей», «Ежемесячные расходы кофейни составляют 780 000 рублей»). Not a list's
    items (a list is checked whole) nor a calculation's details («При выручке 1 138 500 рублей эти расходы составят
    …»): they belong in the notes."""
    src = _read_source(text)
    out: list[str] = []
    goal = _goal_sentence(src.sentences)
    if goal and _GOAL_RE.match(goal):
        out.append(H.strip_end(goal))
    for sn in src.sentences:
        t = H.strip_end(sn)
        if not figures(t) or _ASK_RE.match(t) or t in out:
            continue
        n = len(t.split())
        if n <= KEY_MAX_WORDS and (_TOTAL_RE.match(t) or (_KEY_MEASURE_RE.match(t) and _KEY_VERB_RE.search(t))):
            out.append(t)
        elif n <= TAKEAWAY_MAX_WORDS and _RESULT_STRONG_RE.search(t) and _BUSINESS_RESULT_RE.search(t) and not _BACKREF_RE.search(t):
            # the slide's business result in money, whatever its subject: «Дополнительные 15 покупок в день при среднем
            # чеке 330 рублей дадут 148 500 рублей выручки за 30 дней»
            out.append(t)
    out += [H.strip_end(g.label) for g in src.groups if g.label and _TOTAL_RE.match(g.label) and figures(g.label) and H.strip_end(g.label) not in out]
    return out


def missing_key_lines(s: OutlineSlide, text: str) -> list[str]:
    """The key lines of the source (key_lines) none of whose figures the slide shows — in its text, or on a chart of
    the same measure (a coincidence of amounts on a chart of another measure is not the figure shown: «Операционная
    прибыль — 120 000» is not on a pie of costs where «Аренда» is 120 000)."""
    shown = _Shown(_visible_text(s))
    charts = [ch for ch in (s.content.chart, s.content.chart2) if ch is not None]
    out = []
    for sn in key_lines(text):
        vals = [v for v in figures(sn) if v >= 10 or not float(v).is_integer()]
        if not vals or any(shown.figure(v) for v in vals):
            continue
        subj = _subject_stems(sn)
        on_chart = any(
            all(any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) for sr in ch.series for x in sr.values) for v in vals)
            and _meet(subj, _subject_stems(" ".join([ch.title or "", *(sr.name or "" for sr in ch.series)])))
            for ch in charts
        )
        if not on_chart:
            out.append(sn)
    return out


def slide_gaps(d: _Design, ctx: Optional[_Ctx] = None) -> list[tuple[str, str]]:
    """What the designed slide misses of its source or says beyond it, as (kind, «problem → fix») notes for the
    revision — the agent's own check (a reviewer model does not reliably see what a slide left out). Kinds:
    - "headline": the user's topic heading kept as the headline («Что контролировать каждую неделю»), a list announced
      instead of a conclusion («Три направления для роста прибыли» — and a count that is not the list's), a headline
      without a figure on a slide whose source states its key figures;
    - "list": a list of the source (a lead line and its dash items, «Добавь риски: a, b, c», steps by months) that the
      slide does not show whole: every item of a list of words (actions, measures, risks, steps), half of a list of
      figures;
    - "column": a column that merges two lists of the source («Меры и риски»);
    - "key": the key figures of the source (key_lines: the goal, the totals, the measures it states) missing on the
      slide — every one of them in one note;
    - "takeaway": no takeaway on a slide of a brief that asks for a conclusion on every slide, or one that says
      nothing the headline does not;
    - "line": a line with no figure that its source text does not say (about 60% of its words not the source's)."""
    u = d.unit
    if u.frame or not (u.text or "").strip():
        return []
    src = _read_source(u.text)
    shown = _Shown(_visible_text(d.slide))
    out: list[tuple[str, str]] = []
    head, own = H.strip_end(d.slide.headline or ""), H.strip_end(u.title or "")
    lists = [(g.label, g.items, not g.figure) for g in src.groups]
    if src.steps:
        lists.append(("план по шагам", [f"{t} — {x}" for t, x in src.steps], True))
    keys = key_lines(u.text)
    users_takeaway = bool(u.spec is not None and u.spec.takeaway and same_text(head, u.spec.takeaway))
    if own and head.lower() == own.lower() and not figures(head) and (_QUESTION_HEAD_RE.search(head) or len(head.split()) <= 4):
        out.append(("headline", f"Заголовок повторяет тему слайда из брифа («{head}») → Сформулируй в заголовке вывод слайда, с его ключевой цифрой из текста слайда."))
    elif not headline_states(head) and not users_takeaway:
        m = _ANNOUNCE_RE.search(head)
        count = _COUNT_WORD.get(m.group(0).split()[0].lower()) if m else None
        sizes = {len(items) for _, items, _ in lists}
        wrong = f" (в брифе {', '.join(map(str, sorted(sizes)))}, а не {count})" if count and sizes and count not in sizes else ""
        what = "объявляет список" if m else "называет тему"
        out.append(("headline", f"Заголовок {what} («{head}»){wrong}, а не говорит вывод → Сформулируй в заголовке вывод слайда с его ключевой цифрой из текста слайда, без числа пунктов."))
    elif not _has_figure(head) and not users_takeaway and any(figures(k) for k in keys):
        sample = H.strip_end(keys[0])[:90]
        out.append(("headline", f"Заголовок без цифры («{head}»), хотя у слайда есть ключевая цифра («{sample}») → Сформулируй вывод слайда с этой цифрой (не более 10 слов), только то, что сказано в брифе."))
    for label, items, whole in lists:
        if len(items) < 2:
            continue
        missing = [it for it in items if not shown.line(it)]
        hit = len(items) - len(missing)
        if not missing or (not whole and hit * 2 >= len(items)):
            continue
        what = f"«{H.strip_end(label)}»" if label else "из брифа"
        if hit * 2 < len(items):
            sample = "; ".join(H.short(it, 6) for it in items[:3]) + ("…" if len(items) > 3 else "")
            out.append((
                "list",
                f"На слайде нет списка {what} ({ru_count(len(items), 'пункт', 'пункта', 'пунктов')}: {sample})"
                f" → Покажи этот список на слайде коротко (строками под основным блоком, карточками или второй колонкой), не убирая остальное.",
            ))
        else:
            sample = "; ".join(H.short(it, 6) for it in missing[:3])
            out.append(("list", f"В списке {what} на слайде не хватает пунктов: {sample} → Покажи каждый пункт этого списка, коротко; не объединяй пункты."))
    # a column whose title joins two lists of the source («Меры и риски»): the pairs of risk and measure are lost
    labels = [g.label for g in src.groups if g.label]
    for col in d.slide.content.columns:
        hits = [lb for lb in labels if _meet(_stems(col.title), _stems(lb))]
        if len(hits) >= 2 or (_RISK_RE.search(col.title or "") and _MEASURE_RE.search(col.title or "")):
            out.append(("column", f"Колонка «{col.title}» смешивает два списка брифа → Покажи их отдельно: риски — одной колонкой, меры — другой (или три колонки)."))
            break
    # the goal, the totals and the measures the source states: on the slide, not only in the notes
    missing_keys = missing_key_lines(d.slide, u.text)
    if missing_keys:
        quoted = "; ".join(f"«{x[:90]}»" for x in missing_keys[:3])
        one = len(missing_keys) == 1
        out.append((
            "key",
            f"На слайде нет {'ключевой цифры' if one else 'ключевых цифр'} из брифа: {quoted} → Покажи {'её' if one else 'их'} на слайде "
            f"(в заголовке, в выводе или короткой строкой рядом с основным блоком), не убирая остального.",
        ))
    # a conclusion on every slide, when the brief asks for it; never a copy of the headline
    tk = d.slide.takeaway
    tk_why = takeaway_ok(tk, d.slide, u, ctx) if tk else None
    if tk and tk_why in ("repeats the headline", "repeats the slide's block", "states nothing"):
        what = {"repeats the headline": "повторяет заголовок другими словами", "repeats the slide's block": "повторяет то, что уже есть на слайде", "states nothing": "ничего не утверждает"}[tk_why]
        out.append(("takeaway", f"Вывод «{H.strip_end(tk)}» {what} → Напиши вывод, который добавляет смысл: итог, условие или следствие из текста слайда."))
    elif not tk and ctx is not None and ctx.takeaway_rule:
        out.append(("takeaway", "На слайде нет короткого вывода, а бриф просит вывод на каждом слайде → Добавь вывод до 12 слов: итог, условие или следствие из текста слайда, не повторяя заголовок."))
    # a statement of the designer's that its source does not make («Рост начался с июня», «… — минимальная доля»)
    if d.by == "model":
        for line in _content_lines(d.slide):
            if figures(line) or said_in(line, u.text, 0.4):
                continue
            out.append(("line", f"Строка «{H.short(line, 10)}» не опирается на текст слайда в брифе → Убери её или скажи то, что написано в брифе."))
            break
    return out


def coverage_gaps(d: _Design, ctx: Optional[_Ctx] = None) -> list[str]:
    """slide_gaps' notes, as the revision reads them («problem → fix»)."""
    return [text for _, text in slide_gaps(d, ctx)]


_CONTENT_GAPS = ("list", "column", "key", "line")


def _revision_worse(old: _Design, new: _Design, ctx: Optional[_Ctx] = None) -> Optional[str]:
    """Why a revision is not taken (None: it is): it leaves out more of its source than the first version did, or it
    lost the chart, the table or the figures the first version showed. (merge_revision takes the parts of a revision
    that are better and keeps the first version's where the revision is worse.)"""
    a, b = old.slide.content, new.slide.content
    spec = old.unit.spec
    if a.chart is not None and b.chart is None and spec is not None and spec.charts:
        return "the requested chart is gone"
    if a.table is not None and b.table is None and b.chart is None and spec is not None and spec.table:
        return "the requested table is gone"
    if len(a.numbers) >= 2 and not (b.numbers or b.chart is not None or b.table is not None):
        return "the figures are gone"
    ga = [k for k, _ in slide_gaps(old, ctx) if k in _CONTENT_GAPS]
    gb = [k for k, _ in slide_gaps(new, ctx) if k in _CONTENT_GAPS]
    if len(gb) > len(ga):
        return f"more gaps ({len(gb)} > {len(ga)})"
    return None


def _announces(head: Optional[str]) -> bool:
    """«Три ключевых фактора для роста прибыли»: a list announced, no statement."""
    h = (head or "").strip()
    return bool(_ANNOUNCE_RE.search(h)) and not headline_states(h)


HEAD_MAX_WORDS = 14


def _long_head(head: Optional[str]) -> bool:
    return len((head or "").split()) > HEAD_MAX_WORDS


def merge_revision(old: _Design, new: _Design, ctx: Optional[_Ctx] = None) -> tuple[Optional[_Design], list[str]]:
    """The revision as it is taken, part by part (a reviewer's note fixes one thing, and the revised answer may break
    another — the critic's own suggestion for a headline announces a list more often than not): the revised content
    when it leaves out no more of its source than the first version (else the first version's content); the revised
    headline when it is no worse as a headline (else the first one); the revised takeaway when it says something the
    headline does not (else the first one's, if that one does). None when nothing of the revision is better."""
    why: list[str] = []
    ga, gb = slide_gaps(old, ctx), slide_gaps(new, ctx)
    kinds_a, kinds_b = [k for k, _ in ga], [k for k, _ in gb]
    content_worse = _revision_worse(old, new, ctx)
    base = old if content_worse else new
    out = _Design(unit=base.unit, slide=base.slide.model_copy(deep=True), alternatives=list(base.alternatives), by=base.by, model=new.model or old.model, changes=list(new.changes))
    s = out.slide
    if content_worse:
        why.append(f"the revised content is worse ({content_worse}): the first version's content kept")
        # the revision's headline and takeaway may still be better
        if kinds_b.count("headline") < kinds_a.count("headline") and not (_long_head(new.slide.headline) and not _long_head(old.slide.headline)):
            s.headline = new.slide.headline
            why.append("the revised headline taken")
        if kinds_b.count("takeaway") < kinds_a.count("takeaway") and new.slide.takeaway and takeaway_ok(new.slide.takeaway, s, out.unit, ctx) is None:
            s.takeaway = new.slide.takeaway
            why.append("the revised takeaway taken")
    else:
        ha, hb = kinds_a.count("headline"), kinds_b.count("headline")
        # a revised headline that is no better as a headline does not replace the designer's first one — unless that one
        # announces a list («Три ключевых фактора…» over a slide of indicators, risks and measures): the user's own
        # heading is then the lesser evil
        if hb > ha or (hb and hb == ha and not _announces(old.slide.headline)):
            s.headline = old.slide.headline
            why.append(f"the revised headline «{new.slide.headline[:60]}» is no better: the first one kept")
        elif _long_head(new.slide.headline) and not _long_head(old.slide.headline):
            # a critic's «neutral» headline is often two of the source's sentences joined (22 words over a row of figures)
            s.headline = old.slide.headline
            why.append(f"the revised headline «{new.slide.headline[:60]}…» is too long ({len(new.slide.headline.split())} words): the first one kept")
        worse_tk = kinds_b.count("takeaway") > kinds_a.count("takeaway") or (not s.takeaway and bool(old.slide.takeaway))
        if worse_tk and old.slide.takeaway and takeaway_ok(old.slide.takeaway, s, out.unit, ctx) is None:
            s.takeaway = old.slide.takeaway
            why.append("the revised takeaway is worse (or gone): the first one kept")
    if s.takeaway and takeaway_ok(s.takeaway, s, out.unit, ctx) is not None:
        # the parts of two versions: the revision's takeaway may be the first version's headline («15 дополнительных
        # покупок…» moved down when the critic asked for a topic headline) — never both on one slide
        other = old.slide.takeaway if s.takeaway != old.slide.takeaway else new.slide.takeaway
        s.takeaway = other if other and takeaway_ok(other, s, out.unit, ctx) is None else None
        why.append("the combined takeaway repeated the combined headline: " + ("the other version's taken" if s.takeaway else "dropped"))
    if content_worse and s.headline == old.slide.headline and s.takeaway == old.slide.takeaway:
        return None, why
    return out, why


_LINE_ROOM = {"chart": 3, "stat_row": 4, "big_number": 4, "cards": 5, "timeline": 5, "process": 5, "table": 5, "bullets": MAX_BULLETS}


def complete_slide(s: OutlineSlide, unit: _Unit, ctx: _Ctx) -> list[str]:
    """The agent's safety net for a slide the user described, once the model is done with it (what changed, in English,
    for the warnings): when the brief asks for a conclusion on every slide and the slide has none, the source's own
    sentence that states its result (not one the slide already shows, not a copy of the headline), else its first key
    figure the slide leaves out; then the key figures still missing (key_lines: the goal, the totals, the measures the
    source states) as short lines next to the slide's block, as many as its form shows."""
    if unit.frame or unit.spec is None or s.kind.value in FRAME_KINDS or not (unit.text or "").strip():
        return []
    said: list[str] = []
    missing = missing_key_lines(s, unit.text)
    users = unit.spec.takeaway
    # a takeaway without a figure whose words are mostly not its source's («Разовые вложения покрывают запуск, план
    # распределен по месяцам») gives way to a result of the source with its figure, when there is one
    weak = bool(s.takeaway) and not users and not _figure_set(s.takeaway) and not said_in(s.takeaway, unit.text, 0.6)
    if (not s.takeaway or weak) and ctx.takeaway_rule:
        src = _read_source(unit.text)
        shown = _shown_sentences(src, s.headline, s.content)
        cand = _takeaway_sentence(src.sentences, [g.label for g in src.groups if g.label], shown)
        if cand and (takeaway_ok(cand, s, unit, ctx) or _filler_takeaway(cand, s.headline, s.content, unit.text)):
            cand = None
        if cand is None:
            cand = next((k for k in missing if len(k.split()) <= TAKEAWAY_MAX_WORDS and takeaway_ok(k, s, unit, ctx) is None), None)
        if cand is None:
            cand = _largest_item(src, s, ctx.brief.text)
        if cand is None and not weak:
            cand = _unshown_figure_item(src, s)
        if cand is None:
            cand = _asked_list(src, s, ctx.brief.text)
        if cand:
            old_tk = s.takeaway
            s.takeaway = H.strip_end(cand)
            said.append((f"a vague takeaway «{old_tk[:60]}» replaced" if weak else "no takeaway (the brief asks for one on every slide)") + f": «{s.takeaway[:80]}» from the brief")
            missing = missing_key_lines(s, unit.text)
    c = s.content
    room = _LINE_ROOM.get(s.kind.value, 0) - len(c.bullets)
    added = []
    for line in missing:
        if room <= 0:
            break
        if len(line.split()) > KEY_LINE_MAX_WORDS:
            continue
        c.bullets.append(H.strip_end(line))
        added.append(H.strip_end(line))
        room -= 1
    if added:
        said.append("key figures of the brief added as lines: " + "; ".join(f"«{x[:60]}»" for x in added))
    said.extend(_restore_lists(s, unit))
    said.extend(_rescue_lists(s, unit, ctx))
    return said


def _restore_lists(s: OutlineSlide, unit: _Unit) -> list[str]:
    """A slide whose content is only the titles of its lists («Разовые вложения», «План действий» — the lines were
    lost on the way: a model's lists under a key the form does not show) gets the lists back from its source, in the
    source's words: one column per list the slide leaves out whole (up to three), titled with the slide's own titles
    when they are as many, else the source's leads; a single list as the slide's lines."""
    c = s.content
    if c.chart is not None or c.table is not None or any(col.bullets for col in c.columns) or any(it.bullets or it.text for it in c.items):
        return []
    titles = [H.strip_end(b) for b in c.bullets] + [H.strip_end(it.title) for it in [*c.items, *c.columns] if it.title]
    if not titles or any(len(t.split()) > 5 or figures(t) for t in titles):
        return []
    src = _read_source(unit.text)
    lists = [(g.label, list(g.items)) for g in src.groups if len(g.items) >= 2]
    if len(src.steps) >= 2:
        lists.append((None, [f"{t} — {_low_first(x, unit.text)}" for t, x in src.steps]))
    shown = _Shown(_visible_text(s))
    if any(sum(shown.line(it) for it in items) * 2 >= len(items) for _, items in lists):
        return []  # the titles are a list's items themselves («Увеличение среднего чека», …): content, not lost lists
    lost = [(lb, items) for lb, items in lists if not any(shown.line(it) for it in items)]
    if not lost:
        return []
    lost = lost[:3]
    names = titles if len(titles) == len(lost) else [H.strip_end(re.split(r"\s+[—–]\s+", lb or "")[0]) or t for (lb, _), t in zip(lost, titles + [""] * len(lost))]
    cols = [SlideItem(title=H.cap_first(n or ""), bullets=[H.short(H.strip_end(x), 9) for x in items[:6]]) for n, (_, items) in zip(names, lost)]
    if len(cols) >= 2:
        s.kind, s.content = PatternKind.two_column, SlideContent(columns=cols, numbers=list(c.numbers), formula=c.formula)
    else:
        s.kind, s.content = PatternKind.bullets, SlideContent(bullets=cols[0].bullets, numbers=list(c.numbers), formula=c.formula)
    s.rationale = "Списки из брифа — в колонки рядом."
    return [f"the slide showed only the titles of its lists: {len(cols)} list(s) restored from the brief"]


def _largest_item(src: "_Source", s: OutlineSlide, text: str = "") -> Optional[str]:
    """«Крупнейшая статья — витрина для десертов: 70 000 рублей»: the largest amount of a budget the source lists (3–8
    amounts of one unit, one of them the largest) — a conclusion its figures state."""
    for g in src.groups:
        got = _amount_lines(g.items) if g.figure else None
        if got is None:
            continue
        labels, values, unit = got
        i = max(range(len(values)), key=lambda k: values[k])
        if sorted(values)[-1] == sorted(values)[-2]:
            continue  # two largest: no «the largest»
        return f"Крупнейшая статья — {_low_first(labels[i], text)}: {_fmt_ru(values[i])} {unit}".strip()
    return None


def _asked_list(src: "_Source", s: OutlineSlide, text: str = "") -> Optional[str]:
    """The list the user asked the slide to single out («Выдели три направления роста: увеличение среднего чека,
    привлечение гостей в свободные часы и снижение потерь») as its conclusion, in the user's words: «Три направления
    роста: увеличение среднего чека, привлечение гостей в свободные часы и снижение потерь»."""
    for g in src.groups:
        if not g.ask or not g.label or not 2 <= len(g.items) <= 4:
            continue
        items = [_low_first(x, text, only_if_next_lower=True) for x in (H.strip_end(i) for i in g.items)]
        line = f"{H.strip_end(g.label)}: {', '.join(items[:-1])} и {items[-1]}"
        if len(line.split()) <= TAKEAWAY_MAX_WORDS and not adds_nothing(line, s.headline):
            return line
    return None


def _unshown_figure_item(src: "_Source", s: OutlineSlide) -> Optional[str]:
    """The first figure of the source's lists that the slide does not show («3 000 покупок в месяц»): the last resort
    for a conclusion the brief asks for — a fact of the brief, not a made-up one."""
    shown = _Shown(_visible_text(s))
    for g in src.groups:
        if not g.figure:
            continue
        for it in g.items:
            vals = figures(it)
            if vals and not any(shown.figure(v) for v in vals) and 2 <= len(it.split()) <= 10:
                return H.cap_first(H.strip_end(it))
    return None


def _rescue_lists(s: OutlineSlide, unit: _Unit, ctx: _Ctx) -> list[str]:
    """The lists of words the source gives for the slide (actions, measures, observations) that the slide still leaves
    out after the revision: their missing items as short lines under the slide's block when its form has room for
    them; a list left out whole on a slide whose form the user did not ask for, with no room for it, as the lines under
    a row of the slide's before/after figures (its series) — the form that carries both."""
    said: list[str] = []
    src = _read_source(unit.text)
    for g in src.groups:
        if len(g.items) < 2:
            continue
        # a list of figures is shown by the slide's block (one of its figures quoted in the headline or the takeaway —
        # «Крупнейшая статья — витрина: 70 000 рублей» — shows no budget); a list of words by anything the slide says
        shown = _Shown(_visible_text(s.model_copy(update={"headline": "", "takeaway": None, "subtitle": None}) if g.figure else s))
        missing = [it for it in g.items if not shown.line(it)]
        if not missing or any(len(x.split()) > 12 for x in missing) or (g.figure and len(missing) < len(g.items)):
            continue  # a list of figures counts when it is left out whole (its figures may be on a chart)
        c = s.content
        room = _LINE_ROOM.get(s.kind.value, 0) - len(c.bullets)
        lines = [H.strip_end(x) for x in missing]
        if len(lines) <= room:
            c.bullets.extend(lines)
            said.append(f"items of the list «{(g.label or '')[:40]}» the slide left out added as lines: " + "; ".join(f"«{x[:40]}»" for x in lines))
            continue
        other = _one_other_list(s, src, g, unit.text)
        if len(missing) == len(g.items) and other is not None and not unit.locked and not c.table and not c.chart and not c.formula:
            # the slide shows one list of its source and leaves out the other (the plan by months, not the budget): the
            # two lists side by side, in the source's order
            first, second = (g, other) if _source_pos(unit.text, g.items[0]) <= _source_pos(unit.text, other.items[0]) else (other, g)
            cols = [SlideItem(title=H.strip_end(re.split(r"\s+[—–]\s+", x.label or "")[0]), bullets=[H.short(H.strip_end(i), 9) for i in x.items[:6]]) for x in (first, second)]
            s.kind, s.content = PatternKind.two_column, SlideContent(columns=cols, numbers=list(c.numbers))
            s.rationale = "Два списка из брифа — рядом, в две колонки."
            said.append(f"the list «{(g.label or '')[:40]}» the slide left out shown next to the one it shows")
            continue
        if len(missing) == len(g.items) and not unit.locked and not c.table and not c.formula and not c.items and not c.columns:
            nums = _series_figures(unit, ctx) if not c.numbers else list(c.numbers)
            if not 2 <= len(nums) <= 4:
                continue
            big = [v for n in nums for v in figures(n.value)]
            keep = [b for b in [*c.paragraphs, *c.bullets] if not (figures(b) and all(any(abs(v - x) < 1e-6 for x in big) for v in figures(b)))]
            new_lines = keep + lines
            if len(new_lines) > MAX_BULLETS:
                continue
            s.kind = PatternKind.stat_row
            s.content = SlideContent(numbers=nums, bullets=new_lines)
            s.rationale = "Изменения показателей — крупными цифрами, список мер под ними."
            said.append(f"the list «{(g.label or '')[:40]}» the slide left out shown under a row of its figures")
    return said


def _source_pos(text: str, item: str) -> int:
    i = (text or "").lower().find(item[:20].lower())
    return i if i >= 0 else 10**6


def _one_other_list(s: OutlineSlide, src: "_Source", g: "_Group", text: str = "") -> Optional["_Group"]:
    """The one other list of the source the slide shows whole as its only content (its lines, or its steps as a
    timeline), as a group; None otherwise."""
    c = s.content
    if c.columns or c.numbers or c.chart is not None or c.table is not None:
        return None
    lines = [*c.bullets] + [f"{it.title} — {it.text}" if it.title and it.text else (it.title or it.text) for it in c.items]
    if not lines:
        return None
    cands = [x for x in src.groups if x is not g and len(x.items) >= 2]
    if len(src.steps) >= 2:
        cands.append(_Group(label=src.steps_label or "План", items=[f"{t} — {_low_first(x, text)}" for t, x in src.steps]))
    shown = _Shown(" ".join(lines))
    for x in cands:
        if len(lines) <= len(x.items) + 1 and sum(shown.line(i) for i in x.items) == len(x.items):
            return x
    return None


def _previous_json(s: OutlineSlide) -> str:
    c = s.content
    d: dict[str, Any] = {"kind": s.kind.value, "headline": s.headline}
    for k in ("bullets", "paragraphs"):
        if getattr(c, k):
            d[k] = getattr(c, k)
    if c.items:
        d["items"] = [{"title": it.title, "text": it.text} for it in c.items]
    if c.numbers:
        d["numbers"] = [{"value": n.value, "label": n.label} for n in c.numbers]
    for k in ("chart", "chart2"):
        ch = getattr(c, k)
        if ch is not None:
            d[k] = {"type": ch.type, "categories": ch.categories, "series": [{"name": sr.name, "values": sr.values} for sr in ch.series], "unit": ch.unit}
    if c.table is not None:
        d["table"] = {"columns": c.table.columns, "rows": c.table.rows}
    if c.columns:
        d["columns"] = [{"title": col.title, "bullets": col.bullets} for col in c.columns]
    if c.formula:
        d["formula"] = c.formula
    for k in ("takeaway", "footnote", "notes"):
        if getattr(s, k):
            d[k] = getattr(s, k)
    return json.dumps(d, ensure_ascii=False)


SIMILAR_VARIANTS_RU = "Формы всех слайдов заданы в брифе — варианты отличаются подачей: раскладкой текста и крупных цифр рядом с диаграммами."
SIMILAR_VARIANTS_SOME_RU = "Формы большинства слайдов заданы в брифе — варианты отличаются подачей этих слайдов и формой остальных."


def _similar_variants_note(outlines: dict[str, DeckOutline], strategies: list[Strategy], tracker: _Tracker, per: dict[str, list[str]], structure: Optional[BriefStructure] = None) -> None:
    """When the variants differ on fewer than 30% of their slides (the user dictated the forms: charts, a table), say
    so plainly rather than offering them as real alternatives — and say it truly: every slide's form dictated (the
    variants differ only in how the renderer lays a chart's slide out), or most of them (the others take another
    form)."""
    names = [st.name for st in strategies if st.name in outlines]
    if len(names) < 2:
        return

    def forms(o: DeckOutline) -> list[str]:
        return [f"{s.kind.value}:{s.content.chart.type if s.content.chart else ''}" for s in o.slides]

    base = forms(outlines[names[0]])
    fracs = []
    for nm in names[1:]:
        other = forms(outlines[nm])
        n = max(len(base), len(other), 1)
        diff = sum(1 for i in range(n) if i >= len(base) or i >= len(other) or base[i] != other[i])
        fracs.append(diff / n)
    if max(fracs) >= 0.3:
        return
    specs = {sp.number: sp for sp in (structure.specs if structure is not None else [])}
    content = [s for s in outlines[names[0]].slides if s.kind.value not in FRAME_KINDS]
    pinned = [s for s in content if s.spec_ref in specs and (specs[s.spec_ref].charts or specs[s.spec_ref].table)]
    text = SIMILAR_VARIANTS_RU if content and len(pinned) == len(content) else SIMILAR_VARIANTS_SOME_RU
    for nm in names:
        line = f"Сборка: {text}"
        outlines[nm].agent_log = [*outlines[nm].agent_log, line]
        per[nm].append(f"variants: differ on {int(round(max(fracs) * 100))}% of slides (forms dictated by the brief)")
        tracker.relay({"type": "agent", "step": "compile", "message": text, "slide": None, "variant": nm})


def run_agent(
    brief: Brief,
    manifest: Optional[TemplateManifest],
    strategies: list[Strategy],
    *,
    facts: FactsSource = None,
    skills: Any = None,
    providers: Any = None,
    structure: Optional[BriefStructure] = None,
    progress: Optional[EventFn] = None,
    raw: Optional[list] = None,
    deadline: Optional[float] = None,
    critic: bool = True,
    coverage: bool = True,
    written: bool = False,
) -> Optional[AgentResult]:
    """Brief → a designed, compiled and grounded DeckOutline per strategy (planned_by "agent" when a model designed
    at least one slide, "rules" otherwise). A variant the agent cannot plan is missing from `outlines`: every one
    when the brief has no slide specs and there is no storyline (no model, the architect failed or the budget is
    spent) — the caller plans those as before, with the result's warnings saying why.

    `facts`: the facts registry (FactsExtraction, extract_facts' (facts, warnings), or a callable returning either —
    e.g. a future, so the data_extractor runs while the analyst reads the brief). `structure`: the analyst's result
    when the caller has it. `progress` receives the agent's events (module docstring). `raw` collects the model
    answers as written (planner_raw.json). `coverage`: the agent's own check that every list the brief gives for a
    slide is on it (coverage_gaps) adds its notes to the critic's for the revision round. `written`: the brief is the
    text the writer wrote from a topic (planning/writer.py): the analyst reads it by its rules only (its lists and data
    are in the writer's own format; the data_extractor would read every dated block), and the rules path never makes
    a year a slide's key figure."""
    t0 = time.time()
    tracker = _Tracker(progress)
    clock = _Clock(providers if skills is not None else None, deadline)
    agent = _Agent(brief, manifest, strategies, skills, providers, tracker, clock, raw)
    common: list[str] = []
    per: dict[str, list[str]] = {st.name: [] for st in strategies}

    # 1. analyst
    if structure is None:
        # the analyst's model calls (data_extractor per block) get a share of the budget, never all of it
        a_deadline = None if clock.deadline is None else min(clock.deadline, time.monotonic() + ANALYST_MAX_S)
        by_model = agent.models and not written
        structure, aw = analyse_brief(brief, skills if by_model else None, providers if by_model else None, a_deadline, tracker.forward)
        common.extend(aw)
    fx = _resolve_facts(facts, brief, common, structure)
    ctx = _build_ctx(brief, structure, fx, manifest)
    ctx.written = written
    tracker.emit("analyst", f"Аналитик: {describe_structure(structure)}.")

    # 2. storyline
    if structure.specs:
        units = _units_from_specs(ctx)
    else:
        found = agent.architect(ctx, common)
        if found is None:
            # no storyline: the caller plans the deck as before; the warnings say why
            return AgentResult(outlines={}, warnings={st.name: list(common) for st in strategies}, structure=structure, calls=agent.calls.n, seconds=round(time.time() - t0, 2), raw=raw if raw is not None else [])
        units = found

    # 3. designer: one call per slide, in parallel; the phase leaves room for the critic when the budget allows it
    left = clock.left()
    phase_end = None if clock.deadline is None else (clock.deadline - CRITIC_RESERVE_S if critic and left >= CRITIC_RESERVE_S + 90 else clock.deadline - 3)
    designs = agent.design_all(units, ctx, phase_end)
    for d in designs:
        common.extend(d.changes)
        if d.failure and not d.unit.frame and agent.models:
            common.append(f"slide_designer failed on slide {d.unit.key}, deterministic slide used: {d.failure[:200]}")

    # 4. variants
    prefs = designer_prefs()
    placed: dict[str, list[_Placed]] = {}
    shaped: dict[str, list[str]] = {}  # what the assembly changed per variant (the last assembly's)
    for st in strategies:
        placed[st.name], shaped[st.name] = assemble(designs, st, prefs, ctx)

    # 5. critic per variant (parallel), then one revision round of the flagged slides
    issues_n: dict[str, int] = {}
    revised_all: dict[str, _Design] = {}
    overrides: dict[str, dict[str, _Design]] = {}  # variant → the revised designs of the slides its critic flagged
    flagged: dict[str, dict[str, list[str]]] = {}  # unit → variant → issues
    takeaway_fix: dict[str, set[str]] = {}  # variant → the units whose takeaway repeats the headline (no model needed)
    model_made = sum(1 for d in designs if d.by == "model")
    healthy = agent.models and not agent.broken and model_made > 0
    if healthy and coverage:
        # the agent's own check first: a list the brief gives for a slide (actions, risks, steps) that the slide does not
        # show is a note for every variant (the design is shared), whatever the critic says
        for d in designs:
            gaps = coverage_gaps(d, ctx) if d.by == "model" else []
            pos = next((i for i, u in enumerate(units, 1) if u.key == d.unit.key), None)
            for text in gaps:
                for st in strategies:
                    flagged.setdefault(d.unit.key, {}).setdefault(st.name, []).append(text)
                tracker.emit("critic", f"Критик: слайд {pos} — {text.split(' → ')[0]}" if pos else f"Критик: {text.split(' → ')[0]}", slide=pos)
    if critic and healthy and clock.left() >= max(CRITIC_MIN_S, agent.need_s(2.0)):
        c_deadline = _deadline_for(clock, 60.0, 20.0)
        # variants whose plans are the same (the forms the user dictated leave no choice) get one critic call
        groups: dict[str, list[Strategy]] = {}
        for st in strategies:
            key = "\n".join(_plan_line(i, p.slide) for i, p in enumerate(placed[st.name], 1))
            groups.setdefault(key, []).append(st)

        def crit(group: list[Strategy]) -> tuple[list[Strategy], list[tuple[str, str]], Optional[str]]:
            st = group[0]
            hint = (prefs.get(st.name, {}) or {}).get("hint") or st.description
            t_call = time.monotonic()
            try:
                found = agent.critique(st.name, st.title or st.name, hint, placed[st.name], units, ctx, c_deadline)
                return group, found, None
            except Exception as e:  # noqa: BLE001
                agent.failed(e)
                return group, [], str(e) or type(e).__name__
            finally:
                _ = t_call

        with ThreadPoolExecutor(max_workers=max(1, min(len(groups), agent.workers))) as ex:
            for group, found_issues, err in ex.map(crit, list(groups.values())):
                for st in group:
                    name = st.name
                    if err is not None:
                        per[name].append(f"design_critic failed: {err[:160]}")
                        tracker.emit("critic", "Критик: модель не ответила, план оставлен как есть.", variant=name)
                        continue
                    if len(group) > 1:
                        per[name].append(f"design_critic: one call for the same plans of {', '.join(x.name for x in group)}")
                    issues_n[name] = len(found_issues)
                    for key, text in found_issues:
                        if text.startswith(TAKEAWAY_FIX):
                            takeaway_fix.setdefault(name, set()).add(key)
                        else:
                            flagged.setdefault(key, {}).setdefault(name, []).append(text)
                    found_issues = [(k, x[len(TAKEAWAY_FIX):] + " → вывод заменён результатом из брифа" if x.startswith(TAKEAWAY_FIX) else x) for k, x in found_issues]
                    if found_issues:
                        # a summary line, then one event per note with the slide's number in this variant (the result
                        # screen's «Почему слайд N» shows the notes on slide N)
                        pos_of = {p.units[0]: i for i, p in enumerate(placed[name], 1) if p.units}
                        nums = sorted({pos_of[k] for k, _ in found_issues if k in pos_of})
                        where = f"слайд {nums[0]}" if len(nums) == 1 else f"слайды {', '.join(map(str, nums))}"
                        tracker.emit("critic", f"Критик: {ru_count(len(found_issues), 'замечание', 'замечания', 'замечаний')} — {where}.", variant=name)
                        for key, text in found_issues:
                            pos = pos_of.get(key)
                            # «problem → fix», each part cut at a word near its limit (the timeline shows them apart);
                            # the fix gets room for a whole proposed headline and takeaway (a cut one says nothing)
                            problem, _, fix = text.partition(" → ")
                            said = " → ".join(
                                part if len(part) <= limit else part[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—–-") + "…"
                                for part, limit in ((problem, 280), (fix, 400)) if part
                            )
                            tracker.emit("critic", f"Критик: слайд {pos} — {said}" if pos else f"Критик: {said}", slide=pos, variant=name)
                    else:
                        tracker.emit("critic", "Критик: замечаний нет.", variant=name)
    elif critic and agent.models and (agent.broken or model_made == 0):
        tracker.emit("critic", "Критик пропущен: слайды собраны по правилам, без модели.")
    elif agent.models and critic:
        tracker.emit("critic", "Критик пропущен: не хватает времени на проверку.")
    if flagged and healthy and not agent.broken and clock.left() >= max(REVISE_MIN_S, agent.need_s()):
        by_key = {d.unit.key: d for d in designs}
        order = [u.key for u in units]
        keys = [k for k in order if k in flagged and k in by_key and not by_key[k].unit.frame]
        # one wave of revisions at most (the provider's concurrency): the slides with the most notes first
        if len(keys) > agent.workers:
            weight = {k: sum(len(v) for v in flagged[k].values()) for k in keys}
            keep = set(sorted(keys, key=lambda k: (-weight[k], order.index(k)))[: agent.workers])
            skipped = [k for k in keys if k not in keep]
            keys = [k for k in keys if k in keep]
            common.append(f"revisions capped at {agent.workers}: slides {', '.join(skipped)} keep their first version")
        pos_of_unit = {u.key: i for i, u in enumerate(units, 1)}
        r_deadline = clock.at(2.0)

        def revise(key: str) -> tuple[str, Optional[_Design], Optional[str]]:
            d = by_key[key]
            if agent.broken or clock.left() < max(REVISE_MIN_S, agent.need_s()):
                return key, None, "no time left for the revision (or the model is not answering): the first version stays"
            texts = list(dict.fromkeys(t for v in flagged[key].values() for t in v))
            t_call = time.monotonic()
            try:
                nd = agent.model_design(d.unit, pos_of_unit[key], units, ctx, r_deadline, issues="\n".join(f"- {t}" for t in texts), previous=_previous_json(d.slide))
                enforce_requests(nd, ctx)
                tidy_design(nd, ctx)
            except Exception as e:  # noqa: BLE001
                agent.failed(e)
                return key, None, str(e) or type(e).__name__
            agent.answered(time.monotonic() - t_call)
            merged, why = merge_revision(d, nd, ctx)
            if merged is None:
                return key, None, f"the revision was worse ({'; '.join(why)}): the first version stays"
            merged.changes.extend(f"slide {key}: revision: {w}" for w in why)
            return key, merged, None

        revised = revised_all
        with ThreadPoolExecutor(max_workers=max(1, min(len(keys), agent.workers))) as ex:
            for key, nd, err in ex.map(revise, keys):
                if nd is not None:
                    revised[key] = nd
                    common.extend(nd.changes)
                else:
                    common.append(f"revision of slide {key} failed: {(err or '')[:160]}")
        if revised:
            for st in strategies:
                over = {k: nd for k, nd in revised.items() if st.name in flagged.get(k, {})}
                if over:
                    overrides[st.name] = over
                    placed[st.name], shaped[st.name] = assemble(designs, st, prefs, ctx, over)
                    # the slide's number in this variant, as the critic's notes have it
                    pos_in = {k: i for i, p in enumerate(placed[st.name], 1) for k in p.units}
                    for k in order:
                        if k in over:
                            pos = pos_in.get(k)
                            tracker.emit("revise", f"Правка: слайд {pos} переделан по замечаниям критика — {form_ru(over[k].slide)}." if pos else "Правка: слайд переделан по замечаниям критика.", slide=pos, variant=st.name)
        elif keys:
            tracker.emit("revise", "Правка: модель не успела переделать слайды — оставлены первые версии.")
    elif flagged and healthy:
        tracker.emit("revise", "Правка пропущена: не хватает времени.")

    # a takeaway the critic found repeating its headline: the source's own result, or none (no model call)
    by_unit = {u.key: u for u in units}
    for name, keys in takeaway_fix.items():
        for i, p in enumerate(placed.get(name, []), 1):
            if len(p.units) != 1 or p.units[0] not in keys:
                continue
            u = by_unit.get(p.units[0])
            if u is None or (u.spec is not None and u.spec.takeaway):
                continue  # the user's own conclusion stays
            s = p.slide
            src = _read_source(u.text)
            shown = _shown_sentences(src, s.headline, s.content)
            new = _takeaway_sentence(src.sentences, [g.label for g in src.groups if g.label], shown)
            if new and (same_text(new, s.headline) or _filler_takeaway(new, s.headline, s.content, u.text)):
                new = None
            s.takeaway = new
            tracker.emit("revise", f"Правка: слайд {i} — вывод повторял заголовок" + (f", теперь: «{new}»." if new else ", убран."), slide=i, variant=name)

    # the safety net once the model is done: the key figures of every slide the user described are on it, and every
    # content slide has its conclusion when the brief asks for one — from the source's own sentences, no model call
    for st in strategies:
        done_msgs: list[tuple[int, str]] = []
        for i, p in enumerate(placed.get(st.name, []), 1):
            if len(p.units) != 1:
                continue
            u = by_unit.get(p.units[0])
            if u is None:
                continue
            said = complete_slide(p.slide, u, ctx) if coverage else []
            polish_case(p.slide, ctx.brief.text)  # the lines a variant's form made («title: text») too
            if said:
                per[st.name].extend(f"slide {u.key}: {x}" for x in said)
                done_msgs.append((i, said[0]))
        for i, _ in done_msgs:
            tracker.emit("revise", f"Правка: слайд {i} — добавил из брифа ключевые цифры или вывод, которых на слайде не было.", slide=i, variant=st.name)

    # 6. compile, ground, polish — per variant
    by_model = any(d.by == "model" for d in designs)
    model_slides = sum(1 for d in designs if d.by == "model")
    if agent.models and not by_model:
        common.append("agent: no slide was designed by a model, deterministic designer used" + (f": {agent.last_error[:200]}" if agent.last_error else ""))
    compile_fn = _compiler()
    outlines: dict[str, DeckOutline] = {}
    from verstka.planning.grounding import ground_outline
    from verstka.planning.outline import polish_plan

    cover = next((d.slide for d in designs if d.unit.cover), None)
    for st in strategies:
        own = {d.unit.key: overrides.get(st.name, {}).get(d.unit.key, d) for d in designs}
        alt_of = {k: d.alternatives for k, d in own.items()}
        primary_of = {k: d.slide for k, d in own.items()}
        slides = []
        for i, p in enumerate(placed[st.name], 1):
            s = p.slide.model_copy(deep=True)
            s.id = f"sl{i}"
            if p.units and len(p.units) == 1 and s.kind.value not in FRAME_KINDS:
                s.alternatives = _slide_alternatives(s, alt_of.get(p.units[0], []), primary_of.get(p.units[0]), ctx.brief.text)
            slides.append(s)
        o = DeckOutline(
            title=(cover.headline if cover else ctx.title) or ctx.title, subtitle=cover.subtitle if cover else ctx.structure.subtitle,
            audience=brief.audience, purpose=brief.purpose, strategy=st.name, language=brief.language,
            planned_by="agent" if by_model else "rules", slides=slides, facts=list(ctx.facts.values()),
            series=[s.model_copy() for s in ctx.series.values()], tables=[t.model_copy(deep=True) for t in ctx.tables.values()],
            agent_log=tracker.log_for(st.name),
        )
        warns = per[st.name]
        warns.extend(shaped[st.name])
        grounded = False
        try:
            if compile_fn is not None:
                # the compiler grounds the deck itself (with the structure: the rounding the brief allows, the user's
                # slides kept) and writes its steps to agent_log and to progress
                o, cw = _call_compiler(compile_fn, o, structure, brief, tracker.relay)
                grounded = True
            else:
                o, cw = basic_compile(o, structure, brief)
            warns.extend(cw or [])
        except Exception as e:  # noqa: BLE001 - the built-in step keeps the charts drawable
            log.warning("compile_outline failed on %s", st.name, exc_info=True)
            warns.append(f"compile failed, built-in compile used: {str(e)[:160]}")
            o, cw = basic_compile(o, structure, brief)
            warns.extend(cw)
        if not grounded:
            try:
                log_kept = list(o.agent_log)
                o, gw = ground_outline(o, brief)
                o.agent_log = log_kept
                warns.extend(gw)
            except Exception as e:  # noqa: BLE001 - an ungrounded model plan never reaches the slides
                log.warning("grounding failed on the agent's %s plan", st.name, exc_info=True)
                warns.append(f"agent plan rejected: grounding failed ({str(e)[:160]})")
                continue
        o = polish_plan(o)
        if ctx.written:
            # the variant's final slides (the compiler's variety pass may have given one another form): each against its
            # writer text once more
            unit_of = {u.spec.number: u for u in units if u.spec is not None}
            fixed_at: list[int] = []
            all_done: list[str] = []
            for i, sl in enumerate(o.slides, 1):
                u = unit_of.get(sl.spec_ref) if sl.spec_ref is not None else None
                if u is not None and sl.kind.value not in FRAME_KINDS:
                    done = _written_check(sl, u, ctx, warns)
                    if done:
                        fixed_at.append(i)
                        all_done.extend(done)
            # no two slides under one headline (gate 4 G4-5: «VK была основана в 1998 году» on s2 and s8)
            try:
                from verstka.planning.written_check import unique_headlines

                runs = [(sl, unit_of[sl.spec_ref].text, unit_of[sl.spec_ref].title) for sl in o.slides if sl.spec_ref in unit_of and sl.kind.value not in FRAME_KINDS]
                done = unique_headlines(runs, deck=ctx.brief.text, topic=ctx.title)
            except Exception:  # noqa: BLE001 - the check never stops the deck
                log.warning("unique headlines failed on %s", st.name, exc_info=True)
                done = []
            if done:
                warns.extend(done)
                all_done.extend(done)
                fixed_at.extend(i for i, sl in enumerate(o.slides, 1) if any(f"slide {sl.id}:" in x for x in done) and i not in fixed_at)
            if fixed_at:
                tracker.emit("compile", f"Сборка: сверил слайды {', '.join(map(str, fixed_at))} с текстом — {_written_ru(all_done)}.", variant=st.name)
        n_content = sum(1 for s in o.slides if s.kind.value not in FRAME_KINDS)
        if n_content == 0:
            warns.append("agent plan rejected: no content slide left after grounding")
            continue
        charts = sum(1 for s in o.slides for ch in (s.content.chart, s.content.chart2) if ch is not None)
        tables = sum(1 for s in o.slides if s.content.table is not None)
        extras = [x for x in (charts and ru_count(charts, "диаграмма", "диаграммы", "диаграмм"), tables and ru_count(tables, "таблица", "таблицы", "таблиц")) if x]
        done = f"Сборка: план готов — {ru_count(len(o.slides), 'слайд', 'слайда', 'слайдов')}" + (f", {', '.join(extras)}" if extras else "") + "."
        tracker.emit("compile", done, variant=st.name)
        o.agent_log = [*o.agent_log, done]
        outlines[st.name] = o
    _similar_variants_note(outlines, strategies, tracker, per, structure)
    return AgentResult(
        outlines=outlines, warnings={name: common + per[name] for name in per}, structure=structure, by_model=by_model,
        model_slides=model_slides, slides=len(designs), calls=agent.calls.n, critic_issues=issues_n, seconds=round(time.time() - t0, 2),
        raw=raw if raw is not None else [],
    )
