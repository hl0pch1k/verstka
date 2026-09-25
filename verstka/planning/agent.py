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
- Critic: one call per variant, skipped when the deadline is near; the designer revises only the flagged slides.
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
AGENT_VERSION = "2.1.0"
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

_KIND_RU = {
    "title": "обложка", "section": "разделитель", "agenda": "повестка", "bullets": "список", "cards": "карточки",
    "two_column": "две колонки", "comparison": "сравнение", "process": "шаги", "timeline": "таймлайн",
    "big_number": "большая цифра", "stat_row": "ряд показателей", "table": "таблица", "chart": "диаграмма",
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


STEP_RU = {"analyst": "Аналитик", "architect": "Архитектор", "designer": "Дизайнер", "critic": "Критик", "revise": "Правка", "compile": "Сборка"}
# «Дизайнер: …», «Критик («Структурный»): …» — the step's name in front of a message
_STEP_PREFIX_RE = re.compile(r"^(?:Аналитик|Архитектор|Дизайнер|Критик|Правка|Сборка|Вёрстка)(?:\s*\([^)]*\))?\s*:\s*")
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


def _figure_item(x: str) -> bool:
    """A list item that is a figure with its label, not a statement with a figure in it: «100 покупок в день»,
    «средний чек — 300 рублей», «доля вернувшихся — 25%»; not «Добавить комбо за 390 рублей»."""
    if not figures(x):
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


def _takeaway_sentence(sentences: list[str], labels: list[str], shown: set[str]) -> Optional[str]:
    """The slide's conclusion from the brief's own words, for a slide the model did not design: the sentence of its
    source that states a result with a figure («При достижении этих показателей месячная выручка составит 1 138 500
    рублей — на 238 500 рублей больше текущей»), else a list's lead with a figure («Общий бюджет запуска — 180 000
    рублей»). Later sentences win a tie (a slide's text ends with its result); none longer than 22 words."""
    best: Optional[tuple[int, int, str]] = None
    cands = [*labels, *sentences]  # a list's lead loses a tie to a sentence
    for i, sn in enumerate(cands):
        text = H.strip_end(sn)
        if sn in shown or not figures(text) or _ASK_RE.match(text) or not 4 <= len(text.split()) <= TAKEAWAY_MAX_WORDS:
            continue
        # a result in money for the business (profit, revenue) says more than a ratio next to it
        score = 2 * bool(_RESULT_STRONG_RE.search(text)) + bool(_RESULT_WEAK_RE.search(text)) + bool(re.search(r"прибыл|выручк", text, re.I))
        if score <= 0:
            continue
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
    else:
        text_groups = [g for g in src.groups if not g.figure]
        text_groups.sort(key=lambda g: (not g.ask, -len(g.items)))  # the lists the user asked to show come first
        fig_items = [x for g in src.groups if g.figure for x in g.items]
        other_items = [x for g in text_groups[1:] for x in g.items]
        numbers = _series_figures(unit, ctx) or _kpis(fig_items) or _kpis(other_items) or _kpis(src.sentences)
        if text_groups:
            g = text_groups[0]
            pair = text_groups[1] if len(text_groups) > 1 else None
            if pair is not None and g.label and pair.label and g.ask == pair.ask and len(g.items) <= 4 and len(pair.items) <= 4:
                kind = "two_column"
                c.columns = [SlideItem(title=x.label or "", bullets=[H.short(i, 12) for i in x.items]) for x in (g, pair)]
                shown.update(i for x in (g, pair) for i in x.items)
            else:
                its = g.items[:6]
                if 2 <= len(its) <= 6 and all(len(x.split()) <= 10 for x in its):
                    kind = "cards"
                    c.items = [SlideItem(title=H.short(x, 10)) for x in its]
                else:
                    kind = "bullets"
                    c.bullets = [H.short(x, 14) for x in its]
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
        else:
            lines = [H.short(sn, 14) for sn in src.sentences if not _ASK_RE.match(sn)][:5]
            c.bullets = lines
            shown.update(src.sentences[:5])
    if spec is not None and spec.formula:
        c.formula = spec.formula
    if not (c.bullets or c.items or c.numbers or c.chart or c.table or c.columns or c.formula):
        c.bullets = [H.short(sn, 14) for sn in src.sentences[:4]] or ([H.short(unit.text, 14)] if unit.text.strip() else [])
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


def _fit_form(kind: str, c: SlideContent, changes: list[str], key: str) -> str:
    """Every field the designer filled is one the chosen form shows (a field it does not show would be lost on the
    slide — the audit calls that «content missing»): columns next to a small table become the slide (the table's
    figures are in them) or lines under the block; figures on a form without a row of figures become lines; the
    paragraphs past the lead line join the lines."""
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
        lines += [f"{H.strip_end(it.title)} — {it.text}" if it.title and it.text else (it.title or it.text) for it in c.items]
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
    """A headline when the designer's cannot stay: the source's goal sentence with its figure, when grounding keeps it
    whole and it is short («Цель — поднять средний чек с 300 до 330 рублей»), else the slide's title."""
    goal = _goal_sentence(_read_source(unit.text).sentences)
    if goal:
        g = H.strip_end(goal)
        try:
            ok = ctx.index is None or not ctx.index.clean(g).bad
        except Exception:  # noqa: BLE001
            ok = False
        if ok and len(g.split()) <= 12:
            return H.cap_first(g)
    return unit.title


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
    kind = _fit_form(kind, c, changes, unit.key)
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
            if len(c.bullets) < MAX_BULLETS:
                c.bullets.append(H.strip_end(footnote))
            changes.append(f"slide {unit.key}: footnote that is content moved to the slide's lines: {footnote[:80]}")
            footnote = None
    takeaway = H.strip_end(ans.takeaway or "") or None
    if takeaway and same_text(takeaway, headline):
        takeaway = None  # a conclusion said twice: the headline already carries it
        changes.append(f"slide {unit.key}: the takeaway repeated the headline, dropped")
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
        shown = {x for x in src.sentences if said_in(x, _visible_text_of(headline, c))}
        takeaway = _takeaway_sentence(src.sentences, [g.label for g in src.groups if g.label], shown)
        if takeaway and (same_text(takeaway, headline) or _filler_takeaway(takeaway, headline, c, unit.text)):
            takeaway = None
    s = OutlineSlide(
        id=unit.key, kind=PatternKind(kind), section=unit.section, headline=headline, subtitle=ans.subtitle, content=c,
        notes=ans.notes or "", takeaway=takeaway, footnote=footnote, rationale=ans.rationale or None,
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
    if spec.formula and (c.formula or "").strip() != spec.formula.strip():
        # the user's formula, in the user's words («Покажи формулу: 100 × 300 × 30 = 900 000 рублей»): never the model's
        if c.formula:
            d.changes.append(f"slide {d.unit.key}: the designer's formula «{c.formula[:60]}» → the brief's")
        c.formula = spec.formula
    if spec.footnote and not same_text(s.footnote, spec.footnote):
        s.footnote = spec.footnote  # the user's footnote, in the user's words
    if spec.takeaway:
        s.takeaway = spec.takeaway
        if same_text(s.takeaway, s.headline) and d.unit.title and not same_text(d.unit.title, s.takeaway):
            # the user's conclusion is the takeaway: the headline states the slide's key figure (its goal sentence),
            # else it goes back to the user's heading — not a copy of the conclusion
            s.headline = _fallback_headline(d.unit, ctx)
    _split_merged_lists(d)
    if s.kind == PatternKind.chart and c.chart is None:
        s.kind = PatternKind(kind_by_content(c.model_dump()))


def _split_merged_lists(d: _Design) -> None:
    """A column that merges two lists of the source («Меры и риски»: three measures, then three risks) is split into a
    column per list, in the source's words and order: the pairs risk → measure stay readable."""
    c = d.slide.content
    if not c.columns:
        return
    src = _read_source(d.unit.text)
    risks = next((g for g in src.groups if g.label and _RISK_RE.search(g.label)), None)
    measures = next((g for g in src.groups if g.label and _MEASURE_RE.search(g.label) and not _RISK_RE.search(g.label)), None)
    if risks is None or measures is None:
        return
    for i, col in enumerate(c.columns):
        t = col.title or ""
        if _RISK_RE.search(t) and _MEASURE_RE.search(t):
            new = [SlideItem(title=_label(risks.label or "Риски"), bullets=[H.short(x, 8) for x in risks.items]),
                   SlideItem(title=_label(measures.label or "Меры"), bullets=[H.short(x, 8) for x in measures.items])]
            c.columns = (c.columns[:i] + new + c.columns[i + 1:])[:3]
            d.changes.append(f"slide {d.unit.key}: the column «{t}» merged two lists of the brief: split into «{new[0].title}» and «{new[1].title}»")
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


def _lines_of(s: OutlineSlide) -> list[str]:
    c = s.content
    out = [*c.paragraphs, *c.bullets]
    for it in c.items:
        t = it.title.strip()
        out.append(f"{t}: {it.text.strip()}" if t and it.text.strip() else (t or it.text.strip()))
    for col in c.columns:
        out.extend(f"{col.title}: {b}" if col.title else b for b in col.bullets)
    return [x for x in out if x]


def figures_of_lines(lines: list[str]) -> Optional[tuple[list[NumberCallout], list[str]]]:
    """A list whose lines carry figures as a row of 2–4 figures with their labels and the other lines as short
    bullets under them (the visual variant's form of «Доля задач в срок выросла на 34%; экономия 2,1 часа…»); None
    when fewer than two lines give a figure with a clean label, or the lines left over would not fit under them."""
    nums: list[NumberCallout] = []
    rest: list[str] = []
    for ln in lines:
        k = _kpis([ln])
        k = [x for x in k if not re.search(r"\d", x.label) and len(x.label.split()) <= 7]
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


def reshape(s: OutlineSlide, kind: str, chart_type: Optional[str] = None) -> Optional[OutlineSlide]:
    """The slide's content in another form, without a model, or None when the content does not fit it (a chart needs
    figures of one unit, cards need short lines, …). Headline, takeaway, footnote, notes and the formula stay. A pie or
    a doughnut only of the parts of one whole (never «Сейчас / Цель», never a row of unrelated figures)."""
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
    if kind == "stat_row" and text and not (c.chart or c.table or c.numbers):
        figs = figures_of_lines(_lines_of(s))
        if figs is None:
            return None
        nums, rest = figs
        new.numbers, new.bullets = nums, rest
        return s.model_copy(update={"kind": PatternKind.stat_row, "content": new}, deep=True)
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
        lines = _lines_of(s)
        if not lines or len(lines) > MAX_BULLETS or any(len(x.split()) > 18 for x in lines):
            return None
        new.bullets = lines
        new.numbers = [n.model_copy() for n in c.numbers]
    else:
        return None
    return s.model_copy(update={"kind": PatternKind(kind), "content": new}, deep=True)


def _slide_alternatives(s: OutlineSlide, alts: list[Alternative], primary: Optional[OutlineSlide]) -> list[SlideAlternative]:
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
        r = reshape(base, kind, ctype)
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


def _variety(placed: list[_Placed], alts: dict[str, list[Alternative]], primary: Optional[dict[str, OutlineSlide]] = None) -> list[str]:
    """No two neighbours of one form when the second (or, if it is locked, the first) has an alternative that fits."""
    notes = []

    def form(p: _Placed) -> str:
        s = p.slide
        return f"chart:{s.content.chart.type}" if s.kind == PatternKind.chart and s.content.chart is not None else s.kind.value

    for i in range(1, len(placed)):
        prev, cur = placed[i - 1], placed[i]
        if form(prev) != form(cur) or cur.slide.kind.value in FRAME_KINDS:
            continue
        for j in (i, i - 1):
            p = placed[j]
            if p.locked or len(p.units) != 1:
                continue
            around = {form(placed[k]) for k in (j - 1, j + 1) if 0 <= k < len(placed) and k != j}
            done = False
            base = (primary or {}).get(p.units[0])
            options = ([Alternative(kind=base.kind.value, chart_type=base.content.chart.type if base.content.chart else None, why=base.rationale or "")] if base is not None else []) + alts.get(p.units[0], [])
            for a in options:
                src_slide = base if base is not None and a.kind == base.kind.value else p.slide
                r = reshape(src_slide, a.kind, a.chart_type)
                if r is None:
                    continue
                probe = _Placed(slide=r, units=p.units)
                if form(probe) in around or form(probe) == form(p):
                    continue
                if a.why:
                    r.rationale = a.why if a.why.endswith(".") else a.why[:1].upper() + a.why[1:] + "."
                notes.append(f"variety: slide {j + 1} {p.slide.kind.value} → {r.kind.value}")
                placed[j] = probe
                done = True
                break
            if done:
                break
    return notes


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
    for d in designs:
        d = (overrides or {}).get(d.unit.key, d)
        alts[d.unit.key] = d.alternatives
        s = d.slide.model_copy(deep=True)
        if prefer and not d.unit.locked and s.kind.value in switch_from:
            best, best_rank = s, _rank(s.kind.value, prefer)
            tries = list(d.alternatives)
            if prefer[:3].count("stat_row") and not any(a.kind == "stat_row" for a in tries):
                tries.append(Alternative(kind="stat_row", why="цифры списка крупно"))
            # the variant's own preferred forms, where the content fits them (reshape says): a plan by months as a
            # timeline, a budget as a chart, «A → B» figures as a row — not only the forms the designer listed
            for k in prefer[:5]:
                if not any(a.kind == k for a in tries) and not (k in ("timeline", "process") and not _sequential(d.slide)):
                    tries.append(Alternative(kind=k, why=_ALT_WHY.get(k, "")))
            for a in tries:
                r = reshape(d.slide, a.kind, a.chart_type)
                if r is not None and _rank(r.kind.value, prefer) < best_rank:
                    best, best_rank = r, _rank(r.kind.value, prefer)
                    best.rationale = (a.why[:1].upper() + a.why[1:] + ".") if a.why else best.rationale
            s = best
        placed.append(_Placed(slide=s, units=[d.unit.key], locked=d.unit.locked))
    fixed = bool(ctx.count or ctx.structure.specs)
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
    notes.extend(_variety(placed, alts, primary))
    return placed, notes


# ------------------------------------------------------------------ plain-Russian descriptions


def form_ru(s: OutlineSlide) -> str:
    c = s.content
    k = s.kind.value
    if k == "chart" and c.chart is not None:
        text = f"{_CHART_RU.get(c.chart.type, 'диаграмма')} ({ru_count(len(c.chart.categories), 'категория', 'категории', 'категорий')})"
        if c.chart2 is not None:
            text = f"две диаграммы: {_CHART_RU.get(c.chart.type, 'диаграмма')} и {_CHART_RU.get(c.chart2.type, 'диаграмма')}"
    elif k == "table" and c.table is not None:
        text = f"таблица {len(c.table.rows)}×{len(c.table.columns)}"
    elif k in ("stat_row",):
        text = f"ряд показателей ({ru_count(len(c.numbers), 'число', 'числа', 'чисел')})"
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


def _minimal_design(unit: _Unit) -> _Design:
    """The last resort for a slide whose design failed: its heading and the first lines of its source."""
    if unit.cover:
        return _Design(unit=unit, slide=OutlineSlide(id=unit.key, kind=PatternKind.title, headline=unit.title or "Презентация"))
    if unit.closing:
        return _closing_design(unit)
    lines = [H.short(x, 14) for x in (H.split_sentences(unit.text) or [])[:4]] or [unit.title or "…"]
    s = OutlineSlide(id=unit.key, kind=PatternKind.bullets, headline=unit.title or lines[0], content=SlideContent(bullets=lines), spec_ref=unit.spec.number if unit.spec else None, rationale=_WHY["bullets"])
    return _Design(unit=unit, slide=s)


def _safe_rules(unit: _Unit, ctx: _Ctx) -> _Design:
    try:
        return rules_design(unit, ctx)
    except Exception as e:  # noqa: BLE001 - one slide's rules never stop the deck
        log.warning("rules_design failed on slide %s", unit.key, exc_info=True)
        d = _minimal_design(unit)
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
                    results[d.unit.key] = _minimal_design(d.unit)

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
                        d = _minimal_design(u)
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
        """The slide shows this line of its source: half of its words, or its figures («65%», «27 000»)."""
        stems = self.stems_of(line)
        if not stems:
            return True
        if sum(1 for w in stems if self.stems.has(w)) * 2 >= len(stems):
            return True
        vals = figures(line)
        return bool(vals) and all(any(abs(v - x) <= 1e-6 * max(1.0, abs(v)) for x in self.figs) for v in vals)

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


def coverage_gaps(d: _Design, ctx: Optional[_Ctx] = None) -> list[str]:
    """What the designed slide misses of its source or says beyond it, as notes for the revision («problem → fix») —
    the agent's own check (a reviewer model does not reliably see what a slide left out):
    - the user's topic heading kept as the headline («Что контролировать каждую неделю»), a list announced instead
      of a conclusion («Три направления для роста прибыли», «Пять стратегий…» — and a count that is not the list's);
    - a list of the source (a lead line and its dash items, «Добавь риски: a, b, c», steps by months) that the slide
      does not show whole: every item of a list of words (actions, measures, risks, steps), half of a list of figures;
    - a column that merges two lists of the source («Меры и риски»);
    - the goal and the totals of the source («Цель — …», «Общие расходы — 780 000 рублей») missing on the slide;
    - a line with no figure that its source text does not say (about 60% of its words not the source's)."""
    u = d.unit
    if u.frame or not (u.text or "").strip():
        return []
    src = _read_source(u.text)
    shown = _Shown(_visible_text(d.slide))
    out = []
    head, own = H.strip_end(d.slide.headline or ""), H.strip_end(u.title or "")
    lists = [(g.label, g.items, not g.figure) for g in src.groups]
    if src.steps:
        lists.append(("план по шагам", [f"{t} — {x}" for t, x in src.steps], True))
    if own and head.lower() == own.lower() and not figures(head) and (_QUESTION_HEAD_RE.search(head) or len(head.split()) <= 4):
        out.append(f"Заголовок повторяет тему слайда из брифа («{head}») → Сформулируй в заголовке вывод слайда, с его ключевой цифрой из текста слайда.")
    elif not headline_states(head) and not (u.spec is not None and u.spec.takeaway and same_text(head, u.spec.takeaway)):
        m = _ANNOUNCE_RE.search(head)
        count = _COUNT_WORD.get(m.group(0).split()[0].lower()) if m else None
        sizes = {len(items) for _, items, _ in lists}
        wrong = f" (в брифе {', '.join(map(str, sorted(sizes)))}, а не {count})" if count and sizes and count not in sizes else ""
        what = "объявляет список" if m else "называет тему"
        out.append(f"Заголовок {what} («{head}»){wrong}, а не говорит вывод → Сформулируй в заголовке вывод слайда с его ключевой цифрой из текста слайда, без числа пунктов.")
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
            out.append(
                f"На слайде нет списка {what} ({ru_count(len(items), 'пункт', 'пункта', 'пунктов')}: {sample})"
                f" → Покажи этот список на слайде коротко (строками под основным блоком, карточками или второй колонкой), не убирая остальное."
            )
        else:
            sample = "; ".join(H.short(it, 6) for it in missing[:3])
            out.append(f"В списке {what} на слайде не хватает пунктов: {sample} → Покажи каждый пункт этого списка, коротко; не объединяй пункты.")
    # a column whose title joins two lists of the source («Меры и риски»): the pairs of risk and measure are lost
    labels = [g.label for g in src.groups if g.label]
    for col in d.slide.content.columns:
        hits = [lb for lb in labels if _meet(_stems(col.title), _stems(lb))]
        if len(hits) >= 2 or (_RISK_RE.search(col.title or "") and _MEASURE_RE.search(col.title or "")):
            out.append(f"Колонка «{col.title}» смешивает два списка брифа → Покажи их отдельно: риски — одной колонкой, меры — другой (или три колонки).")
            break
    # the goal and the totals the source states: on the slide, not only in the notes
    goal = _goal_sentence(src.sentences)
    keys = [goal] if goal and _GOAL_RE.match(goal) else []
    keys += [sn for sn in src.sentences if _TOTAL_RE.match(sn.strip()) and figures(sn)]
    keys += [g.label for g in src.groups if g.label and _TOTAL_RE.match(g.label) and figures(g.label)]
    for sn in keys:
        vals = [v for v in figures(sn) if v >= 10]
        if vals and not any(shown.figure(v) for v in vals):
            out.append(f"На слайде нет ключевой цифры из брифа: «{H.strip_end(sn)[:90]}» → Покажи её на слайде (в заголовке, в строке над блоком или крупной цифрой).")
            break
    # a statement of the designer's that its source does not make («Рост начался с июня», «… — минимальная доля»)
    if d.by == "model":
        for line in _content_lines(d.slide):
            if figures(line) or said_in(line, u.text, 0.4):
                continue
            out.append(f"Строка «{H.short(line, 10)}» не опирается на текст слайда в брифе → Убери её или скажи то, что написано в брифе.")
            break
    return out


def _revision_worse(old: _Design, new: _Design, ctx: Optional[_Ctx] = None) -> Optional[str]:
    """Why a revision is not taken (None: it is): it leaves out more of its source than the first version did, or it
    lost the chart, the table or the figures the first version showed."""
    a, b = old.slide.content, new.slide.content
    spec = old.unit.spec
    if a.chart is not None and b.chart is None and spec is not None and spec.charts:
        return "the requested chart is gone"
    if a.table is not None and b.table is None and b.chart is None and spec is not None and spec.table:
        return "the requested table is gone"
    if len(a.numbers) >= 2 and not (b.numbers or b.chart is not None or b.table is not None):
        return "the figures are gone"
    ga, gb = coverage_gaps(old, ctx), coverage_gaps(new, ctx)
    if len(gb) > len(ga):
        return f"more gaps ({len(gb)} > {len(ga)})"
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


SIMILAR_VARIANTS_RU = "Формы слайдов заданы в брифе — варианты отличаются подачей, а не составом слайдов."


def _similar_variants_note(outlines: dict[str, DeckOutline], strategies: list[Strategy], tracker: _Tracker, per: dict[str, list[str]]) -> None:
    """When the variants differ on fewer than 30% of their slides (the user dictated the forms: charts, a table), say
    so plainly rather than offering them as real alternatives."""
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
    for nm in names:
        line = f"Сборка: {SIMILAR_VARIANTS_RU}"
        outlines[nm].agent_log = [*outlines[nm].agent_log, line]
        per[nm].append(f"variants: differ on {int(round(max(fracs) * 100))}% of slides (forms dictated by the brief)")
        tracker.relay({"type": "agent", "step": "compile", "message": SIMILAR_VARIANTS_RU, "slide": None, "variant": nm})


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
) -> Optional[AgentResult]:
    """Brief → a designed, compiled and grounded DeckOutline per strategy (planned_by "agent" when a model designed
    at least one slide, "rules" otherwise). A variant the agent cannot plan is missing from `outlines`: every one
    when the brief has no slide specs and there is no storyline (no model, the architect failed or the budget is
    spent) — the caller plans those as before, with the result's warnings saying why.

    `facts`: the facts registry (FactsExtraction, extract_facts' (facts, warnings), or a callable returning either —
    e.g. a future, so the data_extractor runs while the analyst reads the brief). `structure`: the analyst's result
    when the caller has it. `progress` receives the agent's events (module docstring). `raw` collects the model
    answers as written (planner_raw.json). `coverage`: the agent's own check that every list the brief gives for a
    slide is on it (coverage_gaps) adds its notes to the critic's for the revision round."""
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
        structure, aw = analyse_brief(brief, skills if agent.models else None, providers if agent.models else None, a_deadline, tracker.forward)
        common.extend(aw)
    fx = _resolve_facts(facts, brief, common, structure)
    ctx = _build_ctx(brief, structure, fx, manifest)
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
                            tracker.emit("critic", f"Критик: слайд {pos} — {text[:200]}" if pos else f"Критик: {text[:200]}", slide=pos, variant=name)
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
            except Exception as e:  # noqa: BLE001
                agent.failed(e)
                return key, None, str(e) or type(e).__name__
            agent.answered(time.monotonic() - t_call)
            worse = _revision_worse(d, nd, ctx)
            if worse:
                return key, None, f"the revision was worse ({worse}): the first version stays"
            return key, nd, None

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
            shown = {x for x in src.sentences if said_in(x, _visible_text_of(s.headline, s.content))}
            new = _takeaway_sentence(src.sentences, [g.label for g in src.groups if g.label], shown)
            if new and (same_text(new, s.headline) or _filler_takeaway(new, s.headline, s.content, u.text)):
                new = None
            s.takeaway = new
            tracker.emit("revise", f"Правка: слайд {i} — вывод повторял заголовок" + (f", теперь: «{new}»." if new else ", убран."), slide=i, variant=name)

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
                s.alternatives = _slide_alternatives(s, alt_of.get(p.units[0], []), primary_of.get(p.units[0]))
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
    _similar_variants_note(outlines, strategies, tracker, per)
    return AgentResult(
        outlines=outlines, warnings={name: common + per[name] for name in per}, structure=structure, by_model=by_model,
        model_slides=model_slides, slides=len(designs), calls=agent.calls.n, critic_issues=issues_n, seconds=round(time.time() - t0, 2),
        raw=raw if raw is not None else [],
    )
