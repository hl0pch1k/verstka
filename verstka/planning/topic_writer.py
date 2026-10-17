"""Writer mode v2: a deck from a short request («Сделай презентацию про вторую мировую войну», «сделай презентацию
про интегралы»). Verstka writes the deck's whole text — rich, complete and correct — and then lays it out exactly as
it lays out a person's own «Слайд N» text.

The v1 writer (planning/writer.py) wrote the deck in one call over a cut of a Wikipedia article and pinned every
sentence to a sentence of it: it left out what the cut missed (the war's end in Europe) and every formula (articles on
mathematics lose them to the cut). v2 plans before it writes, writes each slide on its own, and checks:

1. the topic (`topic_reference`: the encyclopedia titles and the topic's kind; an ongoing armed conflict is refused),
   the reference (Wikipedia, `planning/reference.py`) when the topic is public;
2. the plan (`topic_planner`): the cover, the must-know facts a teacher or an expert would never leave out, and the
   content slides covering all of them in a logical order, each with the form that shows it best (dated events, key
   figures, a formula, a table, steps, a chart…);
3. the slides (`topic_slide_writer`, side by side): each one sees the whole plan and its own facts and reference
   paragraphs;
4. coverage: a must-know fact a slide left out goes back onto it, as the plan wrote it;
5. the fact check (`topic_fact_check`): a subject expert reads every statement and corrects the errors it is sure of
   (a wrong date, name, figure, formula); an answer that flags most of the deck is not applied;
6. the text in the «Слайд N» form the analyst reads best (planning/writer.render conventions): the cover's fields,
   the lead, the points, «Хронология:», key figures, «Формула:», a markdown table, numbered steps, a chart's data with
   its request, «Вывод:», a picture's place.

The result is planning/writer.WriterResult: the pipeline writes writer.md / writer.json, the UI shows «Показать
текст», the cover's notes name the source. Never raises."""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from verstka.planning import heuristics as H
from verstka.planning.writer import KINDS, WriterMode, WriterResult, event_topic, with_rules
from verstka.rendering.equation import has_latex, is_math, to_latex, typesettable
from verstka.ru import ru_count
from verstka.schemas.outline import Brief

log = logging.getLogger(__name__)

SKILLS = ("topic_reference", "topic_planner", "topic_slide_writer", "topic_fact_check")
FORMS = ("timeline", "numbers", "formula", "formulas", "example", "table", "steps", "list", "chart", "text")
MATH_FORMS = ("formula", "formulas", "example")
_FORM_SYNONYMS = {
    "dates": "timeline", "chronology": "timeline", "events": "timeline", "хронология": "timeline",
    "figures": "numbers", "kpi": "numbers", "stats": "numbers", "statistics": "numbers", "цифры": "numbers",
    "equation": "formula", "формула": "formula", "comparison": "table", "таблица": "table",
    "formula_list": "formulas", "equations": "formulas", "properties": "formulas", "rules": "formulas", "формулы": "formulas",
    "worked_example": "example", "problem": "example", "solution": "example", "пример": "example", "задача": "example",
    "process": "steps", "method": "steps", "шаги": "steps", "bullets": "list", "points": "list", "список": "list",
    "diagram": "chart", "graph": "chart", "диаграмма": "chart", "paragraph": "text", "текст": "text",
}
DEFAULT_SLIDES = 12  # a topic deck: the cover and eleven content slides, unless the person asked for another count
MIN_CONTENT, MAX_CONTENT = 4, 20
PLAN_MAX_S = 70.0
SLIDE_MAX_S = 60.0
CHECK_MAX_S = 45.0
CHECK_BATCH = 30  # statements per fact-check call, the calls side by side (a call over the whole deck — 75 statements —
#                  did not fit the writer's 100 s after the plan and the slides); a batch is a run of neighbouring slides
CHECK_DEGENERATE = 0.35  # an answer flagging more than this share of the statements is not applied
REF_PLAN_CHARS = 7000
REF_SLIDE_CHARS = 2600
REF_CHECK_CHARS = 6000
MAX_PICTURES = 2
PICTURE_FORMS = ("list", "text", "numbers")  # a picture beside a timeline, steps, formulas, a table or a chart squeezes them

EventFn = Callable[[dict], None]


# ------------------------------------------------------------------ the skills' answers (read leniently)


def _text(v: Any, limit: int = 600) -> str:
    return " ".join(str(v if v is not None else "").split())[:limit]


class PlannedSlide(BaseModel):
    title: str = ""
    goal: str = ""
    form: str = "text"
    must: list[int] = Field(default_factory=list)
    picture: bool = False

    @field_validator("title", "goal", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _text(v, 300)

    @field_validator("form", mode="before")
    @classmethod
    def _form(cls, v: Any) -> str:
        f = _text(v, 40).lower()
        f = _FORM_SYNONYMS.get(f, f)
        return f if f in FORMS else "text"

    @field_validator("must", mode="before")
    @classmethod
    def _must(cls, v: Any) -> list[int]:
        out = []
        for x in v if isinstance(v, list) else []:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
        return out

    @field_validator("picture", mode="before")
    @classmethod
    def _pic(cls, v: Any) -> bool:
        return v is True or str(v).strip().lower() in ("true", "yes", "1", "да")


class TopicPlan(BaseModel):
    """Output of `topic_planner`."""

    title: str = ""
    subtitle: str = ""
    kind: str = "other"
    facts: list[str] = Field(default_factory=list)
    slides: list[PlannedSlide] = Field(default_factory=list)

    @field_validator("title", "subtitle", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _text(v, 200)

    @field_validator("kind", mode="before")
    @classmethod
    def _k(cls, v: Any) -> str:
        return _text(v, 30).lower() or "other"

    @field_validator("facts", mode="before")
    @classmethod
    def _facts(cls, v: Any) -> list[str]:
        out = []
        for x in v if isinstance(v, list) else []:
            t = _text(x.get("text") or x.get("fact") if isinstance(x, dict) else x, 500)
            if t:
                out.append(t)
        return out

    @field_validator("slides", mode="before")
    @classmethod
    def _slides(cls, v: Any) -> list:
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


class TimelineEvent(BaseModel):
    when: str = ""
    what: str = ""

    @field_validator("when", "what", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _text(v, 300)


class KeyNumber(BaseModel):
    value: str = ""
    label: str = ""

    @field_validator("value", "label", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _text(v, 120)


class TableSpec(BaseModel):
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)

    @field_validator("header", mode="before")
    @classmethod
    def _h(cls, v: Any) -> list[str]:
        return [_text(x, 80) for x in v] if isinstance(v, list) else []

    @field_validator("rows", mode="before")
    @classmethod
    def _r(cls, v: Any) -> list[list[str]]:
        return [[_text(c, 160) for c in row] for row in v if isinstance(row, list)] if isinstance(v, list) else []


class ChartRow(BaseModel):
    label: str = ""
    value: float = 0.0

    @field_validator("value", mode="before")
    @classmethod
    def _v(cls, v: Any) -> float:
        try:
            return float(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
        except (TypeError, ValueError):
            return float("nan")


class ChartData(BaseModel):
    type: str = "column"
    caption: str = ""
    unit: str = ""
    rows: list[ChartRow] = Field(default_factory=list)

    @field_validator("rows", mode="before")
    @classmethod
    def _rows(cls, v: Any) -> list:
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


_CTRL = {"\x0c": "\\f", "\x08": "\\b", "\n": "\\n", "\t": "\\t", "\r": "\\r", "\x07": "\\a", "\x0b": "\\v"}


def _latex(v: Any) -> str:
    """A formula's LaTeX as the model meant it: a JSON escape it wrote single («\\frac» read as a form feed and «rac»,
    «\\neq» as a new line, «\\times» as a tab) back to its command, the dollars and a doubled backslash taken off."""
    t = str(v if v is not None else "")
    for c, r in _CTRL.items():
        t = t.replace(c, r)
    t = t.strip()
    if t.startswith("$") and t.endswith("$"):
        t = t.strip("$").strip()
    t = re.sub(r"\\\\(?=[A-Za-z])", r"\\", t)
    return " ".join(t.split())[:400]


class NamedFormula(BaseModel):
    """One formula of a slide: its name or the step it makes («Линейность», «Первообразная», «Ответ»), its LaTeX and
    what it says in words (`note`: a formula alone does not explain the topic)."""

    name: str = ""
    latex: str = ""
    note: str = ""

    @model_validator(mode="before")
    @classmethod
    def _shape(cls, data: Any) -> Any:
        if isinstance(data, str):
            name, sep, rest = data.partition(":")
            return {"name": name.strip(), "latex": _latex(rest)} if sep and "\\" in rest and "\\" not in name else {"name": "", "latex": _latex(data)}
        if isinstance(data, dict):
            return {"name": _text(data.get("name") or data.get("label") or data.get("title"), 80), "latex": _latex(data.get("latex") or data.get("formula") or data.get("tex")),
                    "note": _text(data.get("note") or data.get("explanation") or data.get("meaning"), 260).replace(";", ",")}
        return data


class TopicSlide(BaseModel):
    """Output of `topic_slide_writer`."""

    title: str = ""
    lead: str = ""
    points: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    numbers: list[KeyNumber] = Field(default_factory=list)
    formula: str = ""
    formula_note: str = ""
    formulas: list[NamedFormula] = Field(default_factory=list)
    table: Optional[TableSpec] = None
    steps: list[str] = Field(default_factory=list)
    chart: Optional[ChartData] = None
    takeaway: str = ""
    picture: str = ""

    @model_validator(mode="before")
    @classmethod
    def _shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        d["formula"] = _latex(d.get("formula"))
        for k in ("title", "lead", "formula_note", "takeaway", "picture"):
            d[k] = _text(d.get(k), 700)
        v = d.get("formulas")
        d["formulas"] = [x for x in v if isinstance(x, (dict, str))][:8] if isinstance(v, list) else []
        for k in ("points", "steps"):
            v = d.get(k)
            d[k] = [_text(x, 400) for x in v if _text(x)] if isinstance(v, list) else []
        for k in ("timeline", "numbers"):
            v = d.get(k)
            d[k] = [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
        for k in ("table", "chart"):
            if not isinstance(d.get(k), dict):
                d[k] = None
        return d


class FactIssue(BaseModel):
    id: str = ""
    problem: str = ""
    fix: str = ""

    @field_validator("id", "problem", "fix", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _text(v, 600)


class FactIssues(BaseModel):
    """Output of `topic_fact_check`."""

    issues: list[FactIssue] = Field(default_factory=list)

    @field_validator("issues", mode="before")
    @classmethod
    def _i(cls, v: Any) -> list:
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


# ------------------------------------------------------------------ the request's subject

_ASK_RE = re.compile(
    r"^\s*(?:пожалуйста[,\s]+)?(?:(?:с|по)?дела(?:й|йте)|созда(?:й|йте)|подготов(?:ь|ьте)|сгенерир\w*|напиш(?:и|ите)|сформир\w*|"
    r"постро(?:й|йте)|собер(?:и|ите)|нуж(?:на|ен|но)|хочу|please\s+make|make|create|prepare|generate|build|write)\s+"
    r"(?:мне\s+|me\s+|нам\s+)?(?:a\s+|an\s+)?(?:\S*\s+)?",
    re.I,
)
_DECK_WORD_RE = re.compile(r"^(?:\S*презент\S*|\S*слайд\S*|доклад\w*|deck|presentation|slides?)\s*", re.I)
_ABOUT_RE = re.compile(r"^(?:про|о|об|обо|на\s+тему|по\s+теме|по|about|on)\s+", re.I)
_TAIL_RE = re.compile(r"\s*(?:,?\s*(?:на|из)\s+\d+\s+слайд\w*|,?\s*\d+\s+слайд\w*)\s*$", re.I)


def topic_subject(topic: str) -> str:
    """«Сделай презентацию про вторую мировую войну» → «вторую мировую войну»; «сделай презентаицю про интегралы» →
    «интегралы»; a bare topic stays as it is."""
    t = " ".join((topic or "").split()).strip()
    first = t.split(". ")[0] if ". " in t else t
    s = first
    m = _ASK_RE.match(s)
    if m:
        rest = s[m.end():]
        # the matched optional word may have been the deck word itself, or the first word of the subject
        cand = s[: m.end()].split()
        tail_word = cand[-1] if len(cand) > 1 else ""
        if tail_word and not _DECK_WORD_RE.match(tail_word + " ") and not _ABOUT_RE.match(tail_word + " "):
            rest = tail_word + " " + rest
        s = rest
    s = _DECK_WORD_RE.sub("", s, count=1)
    s = _ABOUT_RE.sub("", s, count=1)
    s = _TAIL_RE.sub("", s)
    s = s.strip(" .!?:;«»\"'")
    return s or t.strip(" .!?")


# ------------------------------------------------------------------ the reference's paragraphs

_HEAD_RE = re.compile(r"^\s*=+\s*(.+?)\s*=+\s*$", re.M)


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", text or "")}


def _years(text: str) -> set[str]:
    return set(re.findall(r"\b(1\d{3}|20\d{2})\b", text or ""))


def paragraphs(texts: list[str]) -> list[str]:
    """The reference's paragraphs worth reading (60+ characters, headings out)."""
    out: list[str] = []
    for t in texts:
        for para in re.split(r"\n\s*\n|\n", _HEAD_RE.sub("\n", t or "")):
            p = " ".join(para.split())
            if len(p) >= 60:
                out.append(p)
    return out


def relevant(paras: list[str], query: str, limit: int) -> str:
    """The paragraphs that share the most words and years with `query`, in the article's order, up to `limit`
    characters."""
    if not paras or limit <= 0:
        return ""
    q, qy = _stems(query), _years(query)
    scored = []
    for i, p in enumerate(paras):
        st = _stems(p)
        score = len(q & st) / (1.0 + 0.02 * len(st)) + 1.5 * len(qy & _years(p))
        if score > 0:
            scored.append((score, i))
    picked: list[int] = []
    room = limit
    for score, i in sorted(scored, reverse=True):
        if len(paras[i]) + 1 > room:
            continue
        picked.append(i)
        room -= len(paras[i]) + 1
        if room < 200:
            break
    return "\n".join(paras[i] for i in sorted(picked))


# ------------------------------------------------------------------ coverage and statements


def _covered(fact: str, text: str) -> bool:
    """A must-know fact the slide's text states: its years all there and most of its content words."""
    fy = _years(fact)
    if fy and not fy <= _years(text):
        return False
    fs = {s for s in _stems(fact) if len(s) >= 5}
    if not fs:
        return True
    return len(fs & _stems(text)) / len(fs) >= 0.55


def slide_text(s: TopicSlide) -> str:
    parts = [s.title, s.lead, *s.points, *(f"{e.when} {e.what}" for e in s.timeline), *(f"{n.value} {n.label}" for n in s.numbers),
             s.formula, s.formula_note, *s.steps, s.takeaway, *(f"{f.name} {f.latex} {f.note}" for f in s.formulas)]
    if s.table:
        parts += [" ".join(s.table.header)] + [" ".join(r) for r in s.table.rows]
    if s.chart:
        parts += [s.chart.caption] + [f"{r.label} {r.value}" for r in s.chart.rows]
    return " ".join(p for p in parts if p)


def _overlap(a: str, b: str) -> float:
    """The share of `a`'s content words (stems of 4 letters and more) that `b` says too."""
    fs = {x for x in _stems(a) if len(x) >= 4}
    return len(fs & _stems(b)) / len(fs) if fs else 0.0


POINTS_CAP = {"formulas": 2, "example": 1}


def _first_year(when: str) -> Optional[int]:
    m = re.search(r"(?<!\d)(\d{3,4})(?!\d)", when or "")
    if not m:
        return None
    y = int(m.group(1))
    return -y if re.search(r"до\s+н\.?\s*э|до\s+нашей", when or "", re.I) else y


def order_timelines(slides: list[TopicSlide]) -> None:
    """A timeline reads in time order («1687» never before «1680-е»): its events sorted by their first year, the same
    year kept in the writer's order. A timeline with an event without a year stays as written."""
    for s in slides:
        years = [_first_year(e.when) for e in s.timeline]
        if len(years) >= 2 and all(y is not None for y in years) and years != sorted(years):
            s.timeline = [e for _, e in sorted(zip(years, s.timeline), key=lambda t: t[0])]


def dedupe_points(slides: list[TopicSlide], forms: Optional[list[str]] = None) -> int:
    """Points that say once more what the slide already shows — an event of its timeline (the same year, the same
    words), a figure, a formula's explanation, a step, its lead, another point — leave the slide; a slide of formulas
    keeps at most two points, a worked example one. Returns how many left."""
    gone = 0
    for k, s in enumerate(slides):
        shown = [f"{e.when} {e.what}" for e in s.timeline] + [f"{x.value} {x.label}" for x in s.numbers] + list(s.steps)
        notes = [f.note for f in s.formulas if f.note] + ([s.formula_note] if s.formula_note else [])
        keep: list[str] = []
        for pt in s.points:
            dup = False
            for t in shown + notes + [s.lead] + keep:
                if not t:
                    continue
                ys, yt = _years(pt), _years(t)
                if (ys and yt and ys & yt and _overlap(pt, t) >= 0.4) or _overlap(pt, t) >= (0.5 if t in notes else 0.6):
                    dup = True
                    break
            if dup:
                gone += 1
            else:
                keep.append(pt)
        cap = POINTS_CAP.get(forms[k]) if forms and k < len(forms) else None
        if cap is not None and len(keep) > cap:
            gone += len(keep) - cap
            keep = keep[:cap]
        s.points = keep
    return gone


def cover_facts(plan: TopicPlan, slides: list[TopicSlide]) -> list[dict]:
    """Every must-know fact on a slide: a fact its slide left out goes back as a point of that slide (a fact no slide
    was given goes to the slide closest to it). Returns what was put back."""
    put: list[dict] = []
    owner: dict[int, int] = {}
    for k, ps in enumerate(plan.slides):
        for m in ps.must:
            owner.setdefault(m, k)
    texts = [slide_text(s) for s in slides]
    for m, fact in enumerate(plan.facts, 1):
        if any(_covered(fact, t) for t in texts):
            continue
        k = owner.get(m)
        if k is not None and k < len(slides) and is_math(fact) and (slides[k].formula or slides[k].formulas):
            continue  # a formula the plan gave to a slide of formulas: the slide sets it as a formula, never as a line
        if k is None or k >= len(slides):
            fs = _stems(fact)
            k = max(range(len(slides)), key=lambda j: len(fs & _stems(texts[j]))) if slides else None
        if k is None:
            continue
        slides[k].points.append(H.strip_end(fact) + ".")
        texts[k] = slide_text(slides[k])
        put.append({"slide": k + 2, "fact": fact})
    return put


def statements(slides: list[TopicSlide]) -> list[dict]:
    """Every statement of the written deck with its id (s<slide>.<field><n>) and text, for the fact check."""
    out: list[dict] = []
    for k, s in enumerate(slides, 2):
        if s.lead:
            out.append({"id": f"s{k}.lead", "text": s.lead})
        out += [{"id": f"s{k}.p{i}", "text": p} for i, p in enumerate(s.points, 1)]
        out += [{"id": f"s{k}.t{i}", "text": f"{e.when} — {e.what}"} for i, e in enumerate(s.timeline, 1)]
        out += [{"id": f"s{k}.n{i}", "text": f"{n.value} — {n.label}"} for i, n in enumerate(s.numbers, 1)]
        if s.formula:
            out.append({"id": f"s{k}.f", "text": s.formula + (f" — {s.formula_note}" if s.formula_note else "")})
        out += [{"id": f"s{k}.m{i}", "text": (f"{f.name}: " if f.name else "") + f.latex + (f" — {f.note}" if f.note else "")} for i, f in enumerate(s.formulas, 1)]
        if s.table:
            out += [{"id": f"s{k}.r{i}", "text": " | ".join(f"{h}: {c}" for h, c in zip(s.table.header, row)) or " | ".join(row)} for i, row in enumerate(s.table.rows, 1)]
        out += [{"id": f"s{k}.st{i}", "text": st} for i, st in enumerate(s.steps, 1)]
        if s.chart:
            unit = f" {s.chart.unit}" if s.chart.unit else ""
            out += [{"id": f"s{k}.c{i}", "text": f"{s.chart.caption}: {r.label} — {_num(r.value)}{unit}"} for i, r in enumerate(s.chart.rows, 1)]
        if s.takeaway:
            out.append({"id": f"s{k}.w", "text": s.takeaway})
    return out


def _num(v: float) -> str:
    if v != v:  # NaN
        return ""
    s = f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")
    return s


_ID_RE = re.compile(r"^s(\d+)\.(lead|p\d+|t\d+|n\d+|f|m\d+|r\d+|st\d+|c\d+|w)$")


def same_claim(before: str, fix: str) -> bool:
    """A correction speaks of what it corrects: most of the statement's words (or its formula's characters) stay —
    a date, a figure, a name changes. A «fix» about something else (a checker that mixed up the statements' numbers
    put «9 декабря 1941 — Китай объявил войну Японии» in place of a line on Pearl Harbor) is no correction."""
    import difflib

    a, b = " ".join((before or "").lower().split()), " ".join((fix or "").lower().split())
    if not a or not b:
        return False
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.5:
        return True
    fa = {x for x in _stems(a) if len(x) >= 4}
    fb = {x for x in _stems(b) if len(x) >= 4}
    return bool(fa and fb) and len(fa & fb) / min(len(fa), len(fb)) >= 0.5


def apply_fixes(slides: list[TopicSlide], issues: list[FactIssue], skipped: Optional[list] = None) -> list[dict]:
    """The fact check's corrections on the deck: the corrected statement in place of the wrong one, a statement with
    no correction dropped; a correction about another statement (`same_claim`) is not applied (`skipped`). Returns
    what was changed."""
    done: list[dict] = []
    drop: dict[int, set[tuple[str, int]]] = {}
    said = {x["id"]: x["text"] for x in statements(slides)}
    for it in issues:
        m = _ID_RE.match(it.id.strip())
        if not m:
            continue
        if it.fix.strip() and it.id.strip() in said and not same_claim(said[it.id.strip()], it.fix):
            if skipped is not None:
                skipped.append({"id": it.id, "statement": said[it.id.strip()], "fix": it.fix})
            continue
        k, field_ = int(m.group(1)) - 2, m.group(2)
        if not 0 <= k < len(slides):
            continue
        s = slides[k]
        fix = it.fix.strip()
        kind = re.match(r"[a-z]+", field_).group(0)
        idx = int(field_[len(kind):]) - 1 if field_[len(kind):].isdigit() else -1
        before = None
        try:
            if kind == "lead":
                before, s.lead = s.lead, fix
            elif kind == "w":
                before, s.takeaway = s.takeaway, fix
            elif kind == "f":
                before = s.formula
                if fix:
                    f, _, note = fix.partition(" — ")
                    s.formula = _latex(f)
                    if note:
                        s.formula_note = note.strip()
                else:
                    s.formula, s.formula_note = "", ""
            elif kind == "m" and 0 <= idx < len(s.formulas):
                f = s.formulas[idx]
                before = (f"{f.name}: " if f.name else "") + f.latex + (f" — {f.note}" if f.note else "")
                if fix:
                    name, sep, latex = fix.partition(": ") if f.name and fix.startswith(f.name) else ("", "", fix)
                    body = latex if sep else fix
                    tex, dash, note = body.partition(" — ")
                    s.formulas[idx] = NamedFormula(name=f.name, latex=_latex(tex if dash else body), note=(note.strip() if dash else f.note))
                else:
                    drop.setdefault(k, set()).add(("m", idx))
            elif kind == "p" and 0 <= idx < len(s.points):
                before = s.points[idx]
                if fix:
                    s.points[idx] = fix
                else:
                    drop.setdefault(k, set()).add(("p", idx))
            elif kind == "st" and 0 <= idx < len(s.steps):
                before = s.steps[idx]
                if fix:
                    s.steps[idx] = fix
                else:
                    drop.setdefault(k, set()).add(("st", idx))
            elif kind == "t" and 0 <= idx < len(s.timeline):
                e = s.timeline[idx]
                before = f"{e.when} — {e.what}"
                when, sep, what = fix.partition(" — ")
                if fix and sep:
                    s.timeline[idx] = TimelineEvent(when=when.strip(), what=what.strip())
                else:
                    drop.setdefault(k, set()).add(("t", idx))
            elif kind == "n" and 0 <= idx < len(s.numbers):
                n = s.numbers[idx]
                before = f"{n.value} — {n.label}"
                value, sep, label = fix.partition(" — ")
                if fix and sep:
                    s.numbers[idx] = KeyNumber(value=value.strip(), label=label.strip())
                else:
                    drop.setdefault(k, set()).add(("n", idx))
            elif kind == "r" and s.table and 0 <= idx < len(s.table.rows):
                before = " | ".join(s.table.rows[idx])
                cells = [re.sub(r"^[^:|]{1,60}:\s*", "", c).strip() for c in fix.split("|")] if fix else []
                if cells and len(cells) == len(s.table.rows[idx]):
                    s.table.rows[idx] = cells
                else:
                    drop.setdefault(k, set()).add(("r", idx))
            elif kind == "c" and s.chart and 0 <= idx < len(s.chart.rows):
                before = f"{s.chart.rows[idx].label} — {_num(s.chart.rows[idx].value)}"
                s.chart = None  # a chart with a wrong figure is no chart: its slide keeps the rest
            else:
                continue
        except Exception:  # noqa: BLE001 - a malformed correction is not applied
            continue
        done.append({"slide": k + 2, "id": it.id, "problem": it.problem, "before": before, "after": fix or None})
    for k, items in drop.items():
        s = slides[k]
        for kind, idx in sorted(items, key=lambda x: -x[1]):
            seq = {"p": s.points, "st": s.steps, "t": s.timeline, "n": s.numbers, "m": s.formulas}.get(kind)
            if seq is not None and 0 <= idx < len(seq):
                seq.pop(idx)
            elif kind == "r" and s.table and 0 <= idx < len(s.table.rows):
                s.table.rows.pop(idx)
    return done


# ------------------------------------------------------------------ the text the analyst reads

CHART_RU = {"column": "столбчатая", "bar": "столбчатая", "line": "линейная", "pie": "круговая"}


def _sentence(t: str) -> str:
    t = " ".join((t or "").split())
    if not t:
        return ""
    if not re.match(r"[A-Za-z]{1,2}(?![A-Za-z])|[A-Za-z][(_^′'₀-₉⁰-⁹]", t):  # a symbol keeps its case («dx показывает…», «f(x) — …»)
        t = t[0].upper() + t[1:]
    return t if t.endswith((".", "!", "?", "…")) else t + "."


def _clause(t: str) -> str:
    """A line after a dash: as the writer wrote it (a country, a name keeps its capital), without its final stop."""
    return H.strip_end(" ".join((t or "").split()))


def _dollar(latex: str) -> str:
    """A formula in the text as «$…$» (the analyst reads it as a formula, the composer typesets it)."""
    t = latex.strip()
    return t if t.startswith("$") else f"${t}$"


def check_formulas(slides: list[TopicSlide]) -> list[dict]:
    """Every formula of the deck typesets: LaTeX the typesetters cannot read is read again as Unicode
    («∫ f(x) dx = F(x) + C»), else the formula leaves the slide (its name and LaTeX in the record)."""
    dropped: list[dict] = []
    for k, s in enumerate(slides, 2):
        if s.formula:
            got = s.formula if has_latex(s.formula) else to_latex(s.formula)
            if got and typesettable(got):
                s.formula = got
            else:
                dropped.append({"slide": k, "formula": s.formula})
                s.formula = ""
        keep = []
        for f in s.formulas:
            got = (f.latex if has_latex(f.latex) else to_latex(f.latex)) if f.latex else None
            if got and typesettable(got):
                keep.append(NamedFormula(name=f.name, latex=got, note=f.note))
            elif f.latex:
                dropped.append({"slide": k, "formula": (f"{f.name}: " if f.name else "") + f.latex})
        s.formulas = keep
    return dropped


def render_slide(n: int, s: TopicSlide, title: str) -> list[str]:
    out = ["", f"Слайд {n}. {H.strip_end(s.title or title)}"]
    if s.lead:
        out.append(_sentence(s.lead))
    pts = [p for p in s.points if p.strip()]
    if pts:
        out += [f"- {_sentence(p)}" for p in pts]
    if s.timeline:
        out.append("Хронология:")
        out += [f"— {H.strip_end(e.when)} — {_clause(e.what)}{';' if i < len(s.timeline) - 1 else '.'}" for i, e in enumerate(s.timeline) if e.when and e.what]
    if s.numbers:
        out.append("Ключевые цифры:")
        out += [f"— {n_.value} — {_clause(n_.label)}{';' if i < len(s.numbers) - 1 else '.'}" for i, n_ in enumerate(s.numbers) if n_.value and n_.label]
    forms = [f for f in s.formulas if f.latex]
    if s.formula and not forms:
        out.append(f"Формула: {_dollar(s.formula)}" + (f" — {H.strip_end(s.formula_note).replace(';', ',')}" if s.formula_note else ""))
    elif forms:
        lines = [(f"{H.strip_end(f.name)}: " if f.name else "") + _dollar(f.latex) + (f" — {H.strip_end(f.note)}" if f.note else "") for f in forms]
        out.append(("Формулы: " if len(lines) > 1 else "Формула: ") + "; ".join(lines))
        if s.formula_note:
            out.append(_sentence(s.formula_note))
    if s.table and s.table.rows:
        width = max(len(s.table.header), max(len(r) for r in s.table.rows))
        head = (s.table.header + [""] * width)[:width]
        out.append("| " + " | ".join(h or " " for h in head) + " |")
        out.append("|" + "---|" * width)
        out += ["| " + " | ".join((r + [""] * width)[:width]) + " |" for r in s.table.rows]
    if s.steps:
        out += [f"{i}. {_sentence(st)}" for i, st in enumerate(s.steps, 1)]
    c = s.chart
    if c and len([r for r in c.rows if r.value == r.value]) >= 2:
        cap = H.strip_end(c.caption) or "Данные"
        unit = H.strip_end(c.unit)
        out.append(f"{cap}, {unit}:" if unit else f"{cap}:")
        rows = [r for r in c.rows if r.value == r.value and r.label]
        out += [f"— {r.label} — {_num(r.value)}{';' if i < len(rows) - 1 else '.'}" for i, r in enumerate(rows)]
        out.append(f"Диаграмма ({CHART_RU.get(c.type, 'столбчатая')}): {cap[:1].lower() + cap[1:]}.")
    if s.takeaway:
        out.append(f"Вывод: {_sentence(s.takeaway)}")
    if s.picture:
        # a bracket inside the note («на отрезке [a; b]») would end it early: the note would read as the author's photo
        pic = H.strip_end(s.picture).replace("[", "(").replace("]", ")")
        out.append(f"[Место под изображение: {pic}]")
    return out


def render_text(plan: TopicPlan, slides: list[TopicSlide]) -> str:
    """The written text as the person reads and edits it («Показать текст»): the cover's fields and the content
    slides in the «Слайд N» form."""
    out = ["Слайд 1. Титульный", f"Название: «{H.strip_end(plan.title)}»."]
    if plan.subtitle:
        out.append(f"Подзаголовок: «{H.strip_end(plan.subtitle)}».")
    for k, (ps, s) in enumerate(zip(plan.slides, slides), 2):
        out += render_slide(k, s, ps.title)
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ the phase


def _subject_title(subject: str) -> str:
    return H.cap_first(subject)


# ------------------------------------------------------------------ the knowledge base as the source

KB_MIN_RELEVANCE = 1.0  # the base's best fragment scores at least this for the request: it knows the topic
KB_PLAN_CHARS = 11000
KB_SLIDE_CHARS = 3200
_NO_FIGURE_CHECK = ("f", "m")  # formulas: their digits are not facts of a document


_PLAN_ITEM_RE = re.compile(r"^\s*(?:(?:слайд|slide)\s*№?\s*\d{1,2}\s*[.:)—–-]?|\d{1,2}\s*[.)]|[-–—•*·])\s*(?P<t>\S.*)$", re.I)
PLAN_MAX_FIGURES = 4  # a plan with more figures than this brings material of its own: it is laid out as written


def plan_items(text: str) -> tuple[str, list[str]]:
    """(the deck's topic, the plan's items) of a plan the person wrote — a numbered or bulleted list, «Слайд N: …»,
    the lines of a letter (planning/plan_form.py when it reads the text). An item keeps its own words (the author's
    asks included: the planner takes them as the slide's form, never as text)."""
    from verstka.planning.brief_structure import _front_matter

    _, body = _front_matter(text or "")
    try:
        from verstka.planning.plan_form import as_slides

        pf = as_slides(body)
    except Exception:  # noqa: BLE001 - the simple reading below
        pf = None
    if pf is not None and pf.items:
        items = [" — ".join(x for x in [it.title, " ".join(ln.strip() for ln in it.lines if ln.strip() and not ln.strip().startswith("|"))] if x)
                 for it in pf.items]
        return (pf.title or ""), [i for i in items if i]
    head = ""
    items: list[str] = []
    for ln in body.splitlines():
        if not ln.strip():
            continue
        m = _PLAN_ITEM_RE.match(ln)
        if m:
            items.append(" ".join(m.group("t").split()).strip(" .;"))
        elif not items and not head:
            head = H.strip_end(ln.strip().lstrip("#").strip())
        elif items:
            items[-1] = f"{items[-1]} — {ln.strip()}"
    return head, items


def kb_plan_mode(brief: Brief, mode: WriterMode) -> WriterMode:
    """With a knowledge base, a plan without material of its own («1. Итоги квартала 2. Клиенты 3. Планы» — at most
    PLAN_MAX_FIGURES figures, no table) is written from the base: one slide per item, in order. A text with material
    stays as it is (faithful mode)."""
    if mode.kind != "off" or mode.reason not in ("list", "specs", "sentences") and not mode.reason.startswith(("sentences", "words")):
        return mode
    from verstka.knowledge.text import figures

    text = brief.text or ""
    if sum(1 for ln in text.splitlines() if ln.strip().startswith("|")) >= 2:
        return mode
    head, items = plan_items(text)
    if len(items) < 2:
        return mode
    body_figs = figures(re.sub(r"слайд\s*\d+|^\s*\d{1,2}[.)]", " ", text, flags=re.I | re.M))
    if len(body_figs) > PLAN_MAX_FIGURES:
        return mode
    topic = head or (brief.title_hint or "") or items[0]
    return WriterMode("topic", topic=topic, theses=[], private_hint=mode.private_hint, language=mode.language, reason="kb_plan", plan=items[:MAX_CONTENT])


def kb_figure_check(slides: list[TopicSlide], kb: Any, given: str = "") -> list[dict]:
    """The statements with a figure no document of the base states (nor the person's request): out of the deck.
    Returns what went ({"slide", "id", "text", "why"})."""
    issues: list[FactIssue] = []
    gone: list[dict] = []
    for st in statements(slides):
        field_ = st["id"].split(".", 1)[1]
        if re.match(r"[a-z]+", field_).group(0) in _NO_FIGURE_CHECK:
            continue
        bad = kb.unsupported(st["text"], given)
        if bad:
            issues.append(FactIssue(id=st["id"], problem="figure not in the knowledge base", fix=""))
            gone.append({"slide": int(st["id"][1:].split(".")[0]), "id": st["id"], "text": st["text"],
                         "why": "в базе знаний нет " + ", ".join(sorted(bad))})
    if issues:
        apply_fixes(slides, issues)
    return gone


def kb_sources(slides: list[TopicSlide], kb: Any) -> list[dict]:
    """Every statement's source in the base: {"slide", "text", "page" (the document), "url", "sentence" (the place and
    the fragment), "doc", "place", "fragment"}; a statement no fragment supports has none."""
    out: list[dict] = []
    for st in statements(slides):
        src = kb.source_of(st["text"])
        if src is None:
            continue
        out.append({"slide": int(st["id"][1:].split(".")[0]), "id": st["id"], "text": st["text"], "page": src.title, "url": src.url or "",
                    "sentence": (f"{src.place}: " if src.place else "") + " ".join(src.text.split())[:400],
                    "doc": src.doc, "place": src.place, "fragment": src.fragment})
    return out


def write_topic_deck(
    brief: Brief,
    mode: WriterMode,
    skills: Any,
    providers: Any,
    *,
    budget_end: Optional[float] = None,
    progress: Optional[EventFn] = None,
    raw: Optional[list] = None,
    cache_dir: Any = None,
    config: Optional[dict] = None,
    transport: Any = None,
    knowledge: Any = None,
) -> WriterResult:
    """The writer phase v2 (see the module's docstring). Never raises: a failure is a result with status «failed»
    (the caller builds the person's text as it is).

    `knowledge`: the person's knowledge base (verstka/knowledge/reference.KbReference). When it knows the topic it is
    the deck's source of facts in place of Wikipedia: the plan and every slide are written from its fragments, every
    figure is checked against its documents (a statement with a figure none of them states goes), the fact check
    reads the fragments, and every statement keeps the fragment it comes from (`sources`: the slide's notes and
    «Почему так» name the document and the place)."""
    t0 = time.monotonic()
    cfg = config or {}
    res = WriterResult(mode=mode.kind, topic=mode.topic, theses=list(mode.theses), lang=mode.language)
    lines: list[str] = []

    def emit(message: str) -> None:
        lines.append(f"Автор: {message}")
        if progress is not None:
            try:
                progress({"type": "agent", "step": "writer", "message": H.cap_first(message), "slide": None, "variant": None})
            except Exception:  # noqa: BLE001 - a listener never stops the deck
                log.debug("writer progress listener failed", exc_info=True)

    def finish(status: str, reason: str = "") -> WriterResult:
        res.status, res.reason = status, reason or res.reason
        res.log_lines = lines
        res.seconds["total"] = round(time.monotonic() - t0, 2)
        return res

    def usage(r: Any) -> None:
        u = getattr(r, "usage", None)
        res.tokens["in"] += int(getattr(u, "prompt_tokens", 0) or 0)
        res.tokens["out"] += int(getattr(u, "completion_tokens", 0) or 0)
        res.model = res.model or getattr(r, "model", None)
        res.model_label = res.model_label or getattr(r, "label", None) or getattr(r, "model", None)

    def keep_raw(skill: str, r: Any = None, error: Optional[BaseException] = None) -> None:
        if raw is None:
            return
        e: dict[str, Any] = {"step": "writer", "skill": skill}
        if r is not None:
            e.update({"model": getattr(r, "model", None), "label": getattr(r, "label", None), "text": getattr(r, "text", None)})
        else:
            from verstka.providers.status import mask

            e["error"] = mask(str(error))[:2000]
        raw.append(e)

    if skills is None or providers is None or not getattr(providers, "has", lambda r: False)("llm"):
        res.warnings.append("topic writer skipped: no LLM provider")
        return finish("skipped", "no_model")
    try:
        res.skills = {n: {"version": skills.get(n).version, "sha256": skills.get(n).sha256[:16]} for n in SKILLS}
    except Exception:  # noqa: BLE001
        res.warnings.append("topic writer failed: its skills are not installed")
        return finish("failed", "writer skills are not installed")
    limits = cfg.get("limits") or {}
    reserve = float(limits.get("agent_reserve_s", 110.0))
    max_s = float(limits.get("writer_max_s", 100.0))
    budget_end = budget_end if budget_end is not None else t0 + 240.0
    deadline = min(budget_end - reserve, t0 + max_s)
    if deadline - t0 < 30:
        res.warnings.append("topic writer skipped: the model time budget is spent")
        emit("не хватает времени написать текст — соберу каркас по теме.")
        return finish("skipped", "no_time")
    bound = providers.with_deadline(deadline) if hasattr(providers, "with_deadline") else providers

    subject = topic_subject(mode.topic)
    plan_items = list(getattr(mode, "plan", None) or [])
    asked = int(brief.slide_count or DEFAULT_SLIDES)
    if plan_items and not brief.slide_count:
        asked = len(plan_items) + 1  # the person's plan: one slide per item
    content_n = max(MIN_CONTENT, min(MAX_CONTENT, asked - 1))
    res.asked = content_n + 1
    rcfg = cfg.get("reference") or {}
    # the knowledge base: the deck's source when it knows the topic (its documents are the person's own: a topic about
    # «наш проект» is no longer private to the writer)
    kb = knowledge if knowledge is not None and not getattr(knowledge, "empty", True) else None
    kb_query = " ".join([subject, *mode.theses, *plan_items])
    if kb is not None:
        score = kb.relevance(kb_query)
        if score < KB_MIN_RELEVANCE:
            res.warnings.append(f"knowledge: the base does not know the topic (best score {score:.2f})")
            emit(f"в базе знаний «{kb.name}» нет ничего о теме — пишу по открытым источникам.")
            kb = None
    ref_on = bool(rcfg.get("enabled", True)) and not mode.private_hint and kb is None
    if kb is not None:
        res.basis = "kb"
        res.kb = {"id": kb.kb.id, "name": kb.name, "docs": [{"id": k, "title": kb.title_of(k), "url": d.get("url")} for k, d in kb.docs.items()]}
        emit(f"беру факты из базы знаний «{kb.name}»: {ru_count(len(kb.docs), 'документ', 'документа', 'документов')}, "
             f"{ru_count(len(kb.frags), 'фрагмент', 'фрагмента', 'фрагментов')}.")
    else:
        emit(f"ищу материалы по теме «{H.strip_end(subject)[:80]}»." if ref_on else f"пишу текст по теме «{H.strip_end(subject)[:80]}».")

    # 1. the topic's kind, its articles, the reference
    kind: Optional[str] = None
    reference = None
    tr = time.monotonic()
    if not mode.private_hint and kb is None:
        try:
            r = skills.run("topic_reference", bound, {"topic": subject, "lang": mode.language})
            usage(r)
            keep_raw("topic_reference", r)
            res.answers["reference"] = getattr(r, "text", None)
            ra = r.parsed
            kind = ra.kind if ra.kind in KINDS else None
            if kind in ("person", "other", None) and event_topic(subject):
                kind = "history"
            if kind == "conflict":
                res.kind = "conflict"
                res.warnings.append("topic writer: refused (an ongoing armed conflict)")
                emit("на эту тему текст не пишу.")
                return finish("refused", "conflict")
            if kind == "private":
                res.kind = "private"
            elif ra.titles and ref_on:
                from verstka.planning.reference import fetch_reference

                reference = fetch_reference(
                    ra.titles, subject, lang=mode.language, contact=str(rcfg.get("contact") or ""), kind=kind,
                    limit=int(rcfg.get("max_chars_history", 18000) if kind in ("history", "conflict") else rcfg.get("max_chars", 12000)),
                    timeout_s=float(rcfg.get("timeout_s", 6)), cache_dir=cache_dir, cache_days=float(rcfg.get("cache_days", 7)),
                    deadline=min(deadline, tr + 14.0), transport=transport,
                )
                res.warnings.extend(reference.warnings)
        except Exception as e:  # noqa: BLE001 - no reference: the deck is written from knowledge
            keep_raw("topic_reference", error=e)
            res.warnings.append(f"reference: {type(e).__name__} ({str(e)[:120]})")
    res.kind = kind or res.kind or "other"
    if kb is not None and res.kind in ("private", "other"):
        from verstka.planning.writer import guess_kind

        res.kind = guess_kind(subject)
    res.seconds["reference"] = round(time.monotonic() - tr, 2)
    texts = reference.full_texts if reference is not None else []
    paras = paragraphs(texts)
    main = reference.main if reference is not None else None
    if main is not None:
        res.source = {"title": main.title, "url": main.url}
        res.pages = [p.meta() for p in reference.pages]
        res.pages_used = [{"title": p.title, "url": p.url} for p in reference.pages]
        res.reference_chars = len(reference.cut or "")
        emit(f"нашёл статью «{main.title}» в Википедии — сверю с ней даты, имена и цифры.")

    # 2. the plan: the cover, the must-know facts, the slides
    tp = time.monotonic()
    ref_plan = (reference.cut if reference is not None else "")[:REF_PLAN_CHARS]
    if kb is not None:
        ref_plan = kb.cut(kb_query, KB_PLAN_CHARS)
    source = "kb" if kb is not None else "wiki"
    plan: Optional[TopicPlan] = None
    for attempt in range(2):
        try:
            r = skills.run("topic_planner", bound, {
                "request": mode.topic, "subject": subject, "language": "русский" if mode.language == "ru" else "English",
                "slides": content_n, "theses": mode.theses, "reference": ref_plan,
                "reference_title": kb.name if kb is not None else (main.title if main else ""), "source": source, "plan_items": plan_items,
            })
            usage(r)
            keep_raw("topic_planner", r)
            res.answers["plan"] = getattr(r, "text", None)
            got: TopicPlan = r.parsed
            got.slides = [s for s in got.slides if s.title][: content_n + 2]
            if got.facts and len(got.slides) >= max(MIN_CONTENT, content_n - 3):
                plan = got
                break
        except Exception as e:  # noqa: BLE001 - asked once more, then the deck is not written
            keep_raw("topic_planner", error=e)
            res.warnings.append(f"topic_planner: {type(e).__name__} ({str(e)[:160]})")
        if time.monotonic() > deadline - 40:
            break
    res.seconds["plan"] = round(time.monotonic() - tp, 2)
    if plan is None:
        emit("не получилось составить план — соберу каркас по теме.")
        return finish("failed", "plan")
    plan.title = plan.title or _subject_title(subject)
    pics = [i for i, s in enumerate(plan.slides) if s.picture and s.form in PICTURE_FORMS][:MAX_PICTURES]
    for i, s in enumerate(plan.slides):
        s.picture = i in pics
    res.title = plan.title
    forms = [s.form for s in plan.slides]
    emit(f"составил план: {ru_count(len(plan.slides), 'слайд', 'слайда', 'слайдов')}, {ru_count(len(plan.facts), 'ключевой факт', 'ключевых факта', 'ключевых фактов')}, формы — {_forms_ru(forms)}.")

    # 3. the slides, side by side
    tw = time.monotonic()
    plan_rows = [{"n": k, "title": s.title, "goal": s.goal} for k, s in enumerate(plan.slides, 2)]

    def write_one(k_ps: tuple[int, PlannedSlide]) -> TopicSlide:
        k, ps = k_ps
        facts = [plan.facts[m - 1] for m in ps.must if 1 <= m <= len(plan.facts)]
        query = " ".join([ps.title, ps.goal, *facts])
        for attempt in range(2):
            try:
                r = skills.run("topic_slide_writer", bound, {
                    "deck_title": plan.title, "subject": subject, "language": "русский" if mode.language == "ru" else "English",
                    "plan": plan_rows, "n": k, "title": ps.title, "goal": ps.goal, "form": ps.form, "picture": ps.picture,
                    "facts": facts, "source": source,
                    "reference": kb.relevant(query, KB_SLIDE_CHARS) if kb is not None else relevant(paras, query, REF_SLIDE_CHARS),
                })
                usage(r)
                keep_raw("topic_slide_writer", r)
                s: TopicSlide = r.parsed
                if s.lead or s.points or s.timeline or s.numbers or s.formula or s.formulas or s.table or s.steps:
                    s.title = s.title or ps.title
                    if not ps.picture:
                        s.picture = ""
                    return s
            except Exception as e:  # noqa: BLE001 - asked once more, then the plan's facts stand for the slide
                keep_raw("topic_slide_writer", error=e)
                res.warnings.append(f"topic_slide_writer s{k}: {type(e).__name__} ({str(e)[:120]})")
            if time.monotonic() > deadline - 20:
                break
        # the slide the model did not write: its must-know facts, as the plan wrote them
        return TopicSlide(title=ps.title, lead=ps.goal, points=[H.strip_end(f) + "." for f in facts])

    limit = getattr(getattr(providers, "limits", None), "max_concurrency", 4) or 4
    with ThreadPoolExecutor(max_workers=max(1, min(int(limit), 6, len(plan.slides)))) as ex:
        slides = list(ex.map(write_one, list(enumerate(plan.slides, 2))))
    res.seconds["write"] = round(time.monotonic() - tw, 2)

    dedupe_points(slides, [ps.form for ps in plan.slides])
    order_timelines(slides)
    bad = check_formulas(slides)
    if bad:
        res.warnings.append(f"writer: {len(bad)} formula(s) could not be typeset and left the slides: " + "; ".join(b["formula"][:60] for b in bad[:4]))

    # 4. coverage: every must-know fact on its slide
    put = cover_facts(plan, slides)
    res.refill = {"facts": len(plan.facts), "put_back": len(put)} if put else {}
    if put:
        res.edits.extend({"slide": p["slide"], "kind": "must_fact", "text": p["fact"]} for p in put)

    # 4b. the knowledge base: every figure of the deck must be in its documents (or in the person's request)
    if kb is not None:
        gone = kb_figure_check(slides, kb, given=" ".join([mode.topic, *mode.theses, *plan_items]))
        res.removed.extend(gone)
        if gone:
            emit(f"сверил цифры с базой знаний — убрал {ru_count(len(gone), 'утверждение', 'утверждения', 'утверждений')}, "
                 "цифр которых в документах нет.")
        else:
            emit("сверил цифры с базой знаний — все они есть в документах.")

    # 5. the fact check, in batches side by side, when there is time
    tc = time.monotonic()
    stmts = statements(slides)
    if (cfg.get("check") or {}).get("enabled", True) and deadline - tc >= 25 and stmts:
        n_b = max(1, -(-len(stmts) // CHECK_BATCH))
        size = -(-len(stmts) // n_b)  # even batches: 75 statements → 25 + 25 + 25, never 30 + 30 + 15
        batches = [stmts[i:i + size] for i in range(0, len(stmts), size)]
        failed: list[int] = []

        def check_one(batch: list[dict]) -> list[FactIssue]:
            q = " ".join(s["text"] for s in batch)
            try:
                r = skills.run("topic_fact_check", bound, {
                    "deck_title": plan.title, "subject": subject, "statements": batch, "source": source,
                    "reference": kb.relevant(q, REF_CHECK_CHARS, k=16) if kb is not None else relevant(paras, q, REF_CHECK_CHARS),
                })
                usage(r)
                keep_raw("topic_fact_check", r)
                got: FactIssues = r.parsed
                ids = {s["id"] for s in batch}
                found = [it for it in got.issues if it.id in ids]
                res.check_stats.append({"statements": len(batch), "flagged": len(found)})
                if len(found) > CHECK_DEGENERATE * len(batch):
                    res.check_stats[-1]["degenerate"] = True
                    return []
                return found
            except Exception as e:  # noqa: BLE001 - an unchecked batch stays as written
                keep_raw("topic_fact_check", error=e)
                res.warnings.append(f"topic_fact_check: {type(e).__name__} ({str(e)[:120]})")
                failed.append(len(batch))
                return []

        with ThreadPoolExecutor(max_workers=max(1, min(int(limit), len(batches)))) as ex:
            issues = [it for found in ex.map(check_one, batches) for it in found]
        skipped: list[dict] = []
        changed = apply_fixes(slides, issues, skipped)
        if skipped:
            res.warnings.append(f"topic_fact_check: {len(skipped)} correction(s) about another statement not applied: " + "; ".join(x["id"] for x in skipped[:6]))
        check_formulas(slides)
        dedupe_points(slides)
        order_timelines(slides)
        if kb is not None:
            # a correction must not bring a figure the base does not state
            res.removed.extend(kb_figure_check(slides, kb, given=" ".join([mode.topic, *mode.theses, *plan_items])))
        res.removed.extend(c for c in changed if c["after"] is None)
        res.overruled.extend(c for c in changed if c["after"] is not None)
        res.checked = "knowledge" if kb is not None else "reference" if paras else "model"
        if len(failed) == len(batches):
            # the check did not answer: the text is as written — never «no errors found»
            res.check_state = "failed"
            res.checked = None
            emit("не успел проверить факты — текст оставлен как написан.")
        else:
            res.check_state = "applied" if changed else "clean"
            part = f" (без {ru_count(sum(failed), 'утверждения', 'утверждений', 'утверждений')} — проверка не ответила)" if failed else ""
            emit(f"проверил факты: {_fixes_ru(len(changed))}{part}." if changed else f"проверил факты: ошибок не нашёл{part}.")
    else:
        res.check_skipped = "no_time" if stmts else "empty"
    res.seconds["check"] = round(time.monotonic() - tc, 2)

    # 6. the text; with the knowledge base every statement keeps the fragment it comes from
    text = render_text(plan, slides)
    res.text = text
    res.slides = len(slides)
    res.sources = kb_sources(slides, kb) if kb is not None else []
    if kb is not None:
        used = list(dict.fromkeys(x["doc"] for x in res.sources))
        res.pages_used = [{"title": kb.title_of(d), "url": (kb.docs.get(d) or {}).get("url") or ""} for d in used]
        res.source = {"title": kb.name, "url": ""}
        n_src = len(res.sources)
        n_all = len(statements(slides))
        emit(f"у {n_src} из {n_all} утверждений указан источник в базе знаний — документ и место; они в заметках слайдов.")
    # a topic deck informs: never a pitch of a product (the person's purpose stays for a company or a market)
    purpose = brief.purpose if res.kind in ("company", "market") else "other"
    res.brief = Brief(
        text=with_rules(text), slide_count=len(slides) + 1, audience=brief.audience, purpose=purpose, language=brief.language,
        title_hint=None, tone=brief.tone, extra_instructions=brief.extra_instructions,
    )
    emit(f"написал текст: {ru_count(len(slides) + 1, 'слайд', 'слайда', 'слайдов')}, в нём {ru_count(len(plan.facts), 'ключевой факт', 'ключевых факта', 'ключевых фактов')} темы.")
    return finish("written")


def _forms_ru(forms: list[str]) -> str:
    names = {"timeline": "хронология", "numbers": "ключевые цифры", "formula": "формулы", "formulas": "формулы", "example": "разборы примеров", "table": "таблицы", "steps": "шаги",
             "list": "списки", "chart": "диаграммы", "text": "пояснения"}
    seen = list(dict.fromkeys(names.get(f, f) for f in forms))
    return ", ".join(seen[:6])


def _fixes_ru(n: int) -> str:
    tail = n % 100
    word = "исправлений" if 11 <= tail <= 14 else {1: "исправление", 2: "исправления", 3: "исправления", 4: "исправления"}.get(n % 10, "исправлений")
    return f"{n} {word}"
