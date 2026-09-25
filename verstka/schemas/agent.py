"""Answers of the Agent v2 skills: slide_designer (one slide), deck_architect (the storyline of a brief that does
not describe its slides) and design_critic (issues of one variant's plan).

Open models of 27–35B follow a JSON shape loosely: content nested under «content» or written next to the headline,
a chart's data as {"label", "value"} pairs, figures as strings with spaces («315 000»), a slide number as «s3».
Every answer is repaired here before it is validated (model_validator mode="before"), so the shape of an answer is
never a reason to lose it. What is NOT repaired is an answer that is not one at all: a JSON object without a
headline or a kind (for a slide), without slides (for a storyline), without issues (for a critique) — e.g. the
inner object of an answer cut at max_tokens, which extract_json would otherwise hand over as an empty, «valid» answer.
Such an answer fails validation, the provider asks once more, and the agent takes its deterministic step.

The JSON schema the provider appends to the prompt (model_json_schema) is a compact one written here: the full
pydantic schema of these classes would cost a few thousand tokens per call and say nothing the prompt does not."""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from verstka.schemas.outline import ChartSpec, InlineSeries, NumberCallout, SlideItem, TableData

# the kinds a designer may choose (the composer sets every one of them in any template's design system)
DESIGN_KINDS = (
    "bullets", "cards", "two_column", "comparison", "process", "timeline", "big_number", "stat_row", "table", "chart",
    "quote", "title", "section", "agenda", "thanks", "image_text", "team",
)
CHART_TYPES = ("bar", "column", "line", "area", "pie", "doughnut")

_KIND_ALIASES = {
    "list": "bullets", "bullet": "bullets", "bullet_list": "bullets", "text": "bullets", "список": "bullets",
    "card": "cards", "grid": "cards", "tiles": "cards", "карточки": "cards",
    "columns": "two_column", "two_columns": "two_column", "twocolumn": "two_column", "compare": "comparison", "vs": "comparison",
    "steps": "process", "flow": "process", "шаги": "process", "roadmap": "timeline", "таймлайн": "timeline",
    "kpi": "stat_row", "kpis": "stat_row", "stats": "stat_row", "metrics": "stat_row", "numbers": "stat_row", "kpi_row": "stat_row",
    "number": "big_number", "stat": "big_number", "hero_number": "big_number",
    "graph": "chart", "diagram": "chart", "диаграмма": "chart", "график": "chart", "таблица": "table",
    "cover": "title", "closing": "thanks", "final": "thanks", "divider": "section", "contents": "agenda",
}
# a chart type named as a kind («pie») is a chart of that type
_CHART_KINDS = {"pie": "pie", "doughnut": "doughnut", "donut": "doughnut", "bar": "bar", "column": "column", "line": "line", "area": "area",
                "pie_chart": "pie", "bar_chart": "bar", "column_chart": "column", "line_chart": "line", "histogram": "column"}
_CHART_ALIASES = {
    **_CHART_KINDS,
    "круговая": "pie", "кольцевая": "doughnut", "столбчатая": "column", "гистограмма": "column", "линейная": "line",
    "линейный": "line", "горизонтальная": "bar", "barchart": "bar", "columns": "column", "horizontal_bar": "bar",
}
_NUM_RE = re.compile(r"[+\-−]?\d[\d\s  ]*(?:[.,]\d+)?")


def _s(value: Any) -> str:
    """A text field as a string: a number as written, a dict by its text, a list joined."""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, dict):
        for k in ("text", "title", "value", "name", "label", "content"):
            if value.get(k):
                return _s(value[k])
        return ""
    if isinstance(value, list):
        return "; ".join(t for t in (_s(v) for v in value) if t)
    return " ".join(str(value).split())


def _opt(value: Any) -> Optional[str]:
    t = _s(value)
    return t or None


def _lines(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (str, dict, int, float)):
        t = _s(value)
        return [t] if t else []
    if isinstance(value, list):
        return [t for t in (_s(v) for v in value) if t]
    return []


def number_of(value: Any) -> Optional[float]:
    """«315 000» → 315000.0, «13,3%» → 13.3, 42 → 42.0; None when there is no number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM_RE.search(str(value))
    if not m:
        return None
    raw = re.sub(r"[\s  ]", "", m.group(0)).replace(",", ".").replace("−", "-")
    try:
        return float(raw)
    except ValueError:
        return None


def kind_name(value: Any) -> str:
    """A kind as the designer may name it («list», «kpi», «pie») → a design kind, or "" when unknown."""
    k = _s(value).lower().strip().replace(" ", "_").replace("-", "_")
    if k in _CHART_KINDS:
        return "chart"
    k = _KIND_ALIASES.get(k, k)
    return k if k in DESIGN_KINDS else ""


def chart_type_name(value: Any) -> Optional[str]:
    t = _s(value).lower().strip().replace(" ", "_").replace("-", "_")
    t = _CHART_ALIASES.get(t, t)
    return t if t in CHART_TYPES else None


def _item(value: Any) -> Optional[dict]:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        t = _s(value)
        return {"title": t} if t else None
    if not isinstance(value, dict):
        return None
    title = _s(value.get("title") or value.get("name") or value.get("heading") or value.get("label") or value.get("step"))
    text = _s(value.get("text") or value.get("description") or value.get("desc") or value.get("body"))
    number = _opt(value.get("number") if value.get("number") not in (None, "") else value.get("value"))
    bullets = _lines(value.get("bullets") or value.get("points") or value.get("items"))
    if not (title or text or number or bullets):
        return None
    return {"title": title, "text": text, "icon_hint": _opt(value.get("icon_hint") or value.get("icon")), "number": number, "bullets": bullets}


def _items(value: Any) -> list[dict]:
    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        return []
    return [it for it in (_item(v) for v in value) if it is not None]


def _number(value: Any) -> Optional[dict]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"value": _s(value), "label": ""}
    if isinstance(value, str):
        return {"value": value.strip(), "label": ""} if value.strip() else None
    if not isinstance(value, dict):
        return None
    v = _s(value.get("value") if value.get("value") not in (None, "") else value.get("number") or value.get("figure"))
    label = _s(value.get("label") or value.get("title") or value.get("name") or value.get("description") or value.get("text"))
    fid = value.get("fact_id") or value.get("id")
    return {"value": v, "label": label, "fact_id": fid if isinstance(fid, str) and fid else None} if v else None


def _table(value: Any) -> Optional[dict]:
    if isinstance(value, list) and value and all(isinstance(r, list) for r in value):
        value = {"columns": value[0], "rows": value[1:]}
    if not isinstance(value, dict):
        return None
    cols = value.get("columns") or value.get("headers") or value.get("header") or []
    rows = value.get("rows") or value.get("data") or []
    if not isinstance(cols, list) or not isinstance(rows, list):
        return None
    cols = [_s(c) for c in cols]
    out_rows = []
    for r in rows:
        if isinstance(r, dict):
            r = [r.get(c, "") for c in cols] if cols else list(r.values())
        if isinstance(r, list):
            out_rows.append([_s(c) for c in r])
    if not cols or not out_rows:
        return None
    return {"columns": cols, "rows": out_rows, "unit": _opt(value.get("unit")), "caption": _opt(value.get("caption") or value.get("title"))}


def _values(raw: Any) -> Optional[list[float]]:
    if not isinstance(raw, list):
        return None
    out = []
    for v in raw:
        if isinstance(v, dict):
            v = v.get("value", v.get("y"))
        n = number_of(v)
        if n is None:
            return None
        out.append(n)
    return out


def _chart(value: Any, kind_hint: Optional[str] = None) -> Optional[dict]:
    """A chart with its data inline (categories + series), or with series ids of the data list; None when it has
    neither or its data do not line up (a value per category)."""
    if not isinstance(value, dict):
        return None
    ctype = chart_type_name(value.get("type") or value.get("chart_type") or value.get("kind")) or kind_hint or "column"
    cats = value.get("categories") or value.get("labels") or value.get("x") or []
    series_raw = value.get("series")
    ids: list[str] = []
    for key in ("series_ids", "ids", "data_ids"):
        v = value.get(key)
        if isinstance(v, str):
            ids.append(v)
        elif isinstance(v, list):
            ids.extend(x for x in v if isinstance(x, str) and x)
    series: list[dict] = []
    data = value.get("data")
    if isinstance(data, list) and data and all(isinstance(d, dict) for d in data) and not cats:
        # [{"label": "кофе", "value": 60}, …]
        cats = [_s(d.get("label") or d.get("category") or d.get("name") or d.get("x")) for d in data]
        vals = _values([d.get("value", d.get("y")) for d in data])
        if vals is not None:
            series = [{"name": _s(value.get("title")), "values": vals}]
    if isinstance(series_raw, list):
        for i, sr in enumerate(series_raw):
            if isinstance(sr, str):
                ids.append(sr)  # a series id where the data should be
                continue
            if isinstance(sr, (int, float)) and not isinstance(sr, bool):
                series = [{"name": _s(value.get("title")), "values": _values(series_raw) or []}]
                break
            if not isinstance(sr, dict):
                continue
            if sr.get("id") and not sr.get("values") and not sr.get("data"):
                ids.append(_s(sr["id"]))
                continue
            vals = _values(sr.get("values") if sr.get("values") is not None else sr.get("data"))
            if vals is None:
                continue
            series.append({"name": _s(sr.get("name") or sr.get("label") or sr.get("title")), "values": vals})
    elif isinstance(value.get("values"), list):
        vals = _values(value["values"])
        if vals is not None:
            series = [{"name": _s(value.get("title") or value.get("name")), "values": vals}]
    cats = [_s(c) for c in cats] if isinstance(cats, list) else []
    series = [s for s in series if cats and len(s["values"]) == len(cats)]
    if not series:
        cats = []
    if not series and not ids:
        return None
    hi = value.get("highlight_index")
    return {
        "type": ctype,
        "series_ids": list(dict.fromkeys(ids)) if not series else [],
        "title": _opt(value.get("title")),
        "unit": _opt(value.get("unit")),
        "highlight_index": hi if isinstance(hi, int) and not isinstance(hi, bool) else None,
        "categories": cats,
        "series": series,
    }


def _alternative(value: Any) -> Optional[dict]:
    if isinstance(value, str):
        value = {"kind": value}
    if not isinstance(value, dict):
        return None
    raw_kind = value.get("kind") or value.get("form") or value.get("type")
    kind = kind_name(raw_kind)
    ctype = chart_type_name(value.get("chart_type") or (raw_kind if kind == "chart" else None))
    if not kind:
        return None
    return {"kind": kind, "chart_type": ctype, "why": _s(value.get("why") or value.get("change") or value.get("rationale") or value.get("reason"))}


_CONTENT_KEYS = ("bullets", "paragraphs", "items", "numbers", "table", "chart", "chart2", "columns", "formula", "quote", "quote_author", "cards", "points", "metrics", "stats", "kpis", "text")
_WRAPPERS = ("slide", "design", "result", "answer", "data", "output")


def normalise_design(data: Any) -> Any:
    """The slide_designer's answer in the shape of SlideDesignAnswer (flat: the content fields next to the headline)."""
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        return data
    if not (data.get("headline") or data.get("kind")):
        inner = next((data[k] for k in _WRAPPERS if isinstance(data.get(k), dict)), None)
        if inner is not None:
            data = inner
    if not (_s(data.get("headline") or data.get("title") or data.get("heading")) or data.get("kind") or data.get("type")):
        raise ValueError("not a slide design: no headline and no kind")
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    merged: dict = dict(content)
    for k in _CONTENT_KEYS:
        if k in data and data[k] not in (None, "", [], {}) and k not in merged:
            merged[k] = data[k]
    raw_kind = data.get("kind") or data.get("type") or data.get("layout")
    kind = kind_name(raw_kind)
    chart_hint = _CHART_KINDS.get(_s(raw_kind).lower().replace(" ", "_").replace("-", "_"))
    numbers = merged.get("numbers") or merged.get("metrics") or merged.get("stats") or merged.get("kpis") or []
    if isinstance(numbers, (dict, str, int, float)):
        numbers = [numbers]
    alts = data.get("alternatives") or data.get("alternative") or []
    if isinstance(alts, (dict, str)):
        alts = [alts]
    notes = data.get("notes") if data.get("notes") is not None else data.get("speaker_notes")
    return {
        "kind": kind,
        "headline": _s(data.get("headline") or data.get("heading") or (data.get("title") if isinstance(data.get("title"), str) else "")),
        "subtitle": _opt(data.get("subtitle")),
        "bullets": _lines(merged.get("bullets") or merged.get("points")),
        "paragraphs": _lines(merged.get("paragraphs") or (merged.get("text") if isinstance(merged.get("text"), (str, list)) else None)),
        "items": _items(merged.get("items") or merged.get("cards")),
        "numbers": [x for x in (_number(v) for v in numbers if v is not None) if x] if isinstance(numbers, list) else [],
        "chart": _chart(merged.get("chart"), chart_hint),
        "chart2": _chart(merged.get("chart2")),
        "table": _table(merged.get("table")),
        "columns": _items(merged.get("columns")),
        "formula": _opt(merged.get("formula")),
        "quote": _opt(merged.get("quote")),
        "quote_author": _opt(merged.get("quote_author")),
        "takeaway": _opt(data.get("takeaway") or data.get("conclusion") or data.get("вывод")),
        "footnote": _opt(data.get("footnote")),
        "notes": _s(notes),
        "rationale": _s(data.get("rationale") or data.get("why")),
        "alternatives": [a for a in (_alternative(v) for v in (alts if isinstance(alts, list) else [])) if a][:3],
    }


class Alternative(BaseModel):
    """Another form of the same slide (used by the other variants): the kind, the chart type for a chart, and why."""

    kind: str
    chart_type: Optional[str] = None
    why: str = ""


class SlideDesignAnswer(BaseModel):
    """Output of the `slide_designer` skill: one slide — its form, text, inline chart data, notes, why this form, and
    two other forms of it."""

    kind: str = ""
    headline: str = ""
    subtitle: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    items: list[SlideItem] = Field(default_factory=list)
    numbers: list[NumberCallout] = Field(default_factory=list)
    chart: Optional[ChartSpec] = None
    chart2: Optional[ChartSpec] = None
    table: Optional[TableData] = None
    columns: list[SlideItem] = Field(default_factory=list)
    formula: Optional[str] = None
    quote: Optional[str] = None
    quote_author: Optional[str] = None
    takeaway: Optional[str] = None
    footnote: Optional[str] = None
    notes: str = ""
    rationale: str = ""
    alternatives: list[Alternative] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        return normalise_design(data)

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return DESIGN_SCHEMA


class StorySlide(BaseModel):
    """One slide of the storyline: a working title, its section, the brief's sentences (by number) and data ids."""

    title: str = ""
    section: Optional[str] = None
    sentences: list[int] = Field(default_factory=list)
    data: list[str] = Field(default_factory=list)
    form: Optional[str] = None


def _ints(value: Any) -> list[int]:
    """[1, "2", "3-5", "#6"] → [1, 2, 3, 4, 5, 6]."""
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        value = [value]
    out: list[int] = []
    if not isinstance(value, list):
        return out
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
            continue
        if isinstance(v, float) and v.is_integer():
            out.append(int(v))
            continue
        m = re.match(r"^\D*(\d+)\s*(?:[-–—]|\.\.)\s*(\d+)\s*$", str(v))
        if m and int(m.group(2)) >= int(m.group(1)) and int(m.group(2)) - int(m.group(1)) < 40:
            out.extend(range(int(m.group(1)), int(m.group(2)) + 1))
            continue
        m = re.search(r"\d+", str(v))
        if m:
            out.append(int(m.group(0)))
    return list(dict.fromkeys(out))


def normalise_storyline(data: Any) -> Any:
    if isinstance(data, list):
        data = {"slides": data}
    if not isinstance(data, dict):
        return data
    if not isinstance(data.get("slides"), list):
        inner = next((v for v in data.values() if isinstance(v, dict) and isinstance(v.get("slides"), list)), None)
        if inner is None:
            raise ValueError("not a storyline: no slides")
        data = inner
    slides = []
    for raw in data["slides"]:
        if isinstance(raw, str):
            raw = {"title": raw}
        if not isinstance(raw, dict):
            continue
        ids = raw.get("data") or raw.get("data_ids") or raw.get("ids") or []
        slides.append({
            "title": _s(raw.get("title") or raw.get("headline") or raw.get("name")),
            "section": _opt(raw.get("section")),
            "sentences": _ints(raw.get("sentences") or raw.get("source") or raw.get("sentence_ids") or []),
            "data": [x for x in ([ids] if isinstance(ids, str) else ids if isinstance(ids, list) else []) if isinstance(x, str) and x],
            "form": kind_name(raw.get("form") or raw.get("kind")) or None,
        })
    return {"title": _s(data.get("title") or data.get("deck_title")), "subtitle": _opt(data.get("subtitle")), "slides": slides}


class StorylineAnswer(BaseModel):
    """Output of the `deck_architect` skill: the deck's title and its content slides in order."""

    title: str = ""
    subtitle: Optional[str] = None
    slides: list[StorySlide] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        return normalise_storyline(data)

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return STORYLINE_SCHEMA


class CriticIssue(BaseModel):
    slide: int = 0  # the slide's number in the plan shown to the critic (1-based)
    problem: str = ""
    fix: str = ""


def normalise_critique(data: Any) -> Any:
    if isinstance(data, list):
        data = {"issues": data}
    if not isinstance(data, dict):
        return data
    raw = next((data[k] for k in ("issues", "problems", "remarks", "comments", "findings") if isinstance(data.get(k), list)), None)
    if raw is None:
        raise ValueError("not a critique: no issues list")
    out = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        n = _ints(it.get("slide") if it.get("slide") is not None else it.get("slide_id") or it.get("id") or it.get("number"))
        problem = _s(it.get("problem") or it.get("issue") or it.get("text"))
        if not n or not problem:
            continue
        out.append({"slide": n[0], "problem": problem, "fix": _s(it.get("fix") or it.get("suggestion") or it.get("how"))})
    return {"issues": out}


class CritiqueAnswer(BaseModel):
    """Output of the `design_critic` skill: the problems of one variant's plan, per slide."""

    issues: list[CriticIssue] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        return normalise_critique(data)

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return CRITIQUE_SCHEMA


_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}
_ITEM = {"type": "object", "properties": {"title": _STR, "text": _STR, "number": _STR, "bullets": _STRS}}
_CHART = {
    "type": ["object", "null"],
    "properties": {
        "type": {"enum": list(CHART_TYPES)}, "title": _STR, "unit": _STR,
        "categories": _STRS,
        "series": {"type": "array", "items": {"type": "object", "properties": {"name": _STR, "values": {"type": "array", "items": {"type": "number"}}}}},
        "highlight_index": {"type": ["integer", "null"]},
    },
}
DESIGN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["kind", "headline"],
    "properties": {
        "kind": {"enum": [k for k in DESIGN_KINDS if k not in ("title", "section", "agenda", "thanks")]},
        "headline": _STR, "subtitle": {"type": ["string", "null"]},
        "bullets": _STRS, "items": {"type": "array", "items": _ITEM},
        "numbers": {"type": "array", "items": {"type": "object", "properties": {"value": _STR, "label": _STR}}},
        "chart": _CHART, "chart2": _CHART,
        "table": {"type": ["object", "null"], "properties": {"columns": _STRS, "rows": {"type": "array", "items": _STRS}}},
        "columns": {"type": "array", "items": _ITEM},
        "formula": {"type": ["string", "null"]}, "takeaway": _STR, "footnote": {"type": ["string", "null"]},
        "notes": _STR, "rationale": _STR,
        "alternatives": {"type": "array", "items": {"type": "object", "properties": {"kind": _STR, "chart_type": {"type": ["string", "null"]}, "why": _STR}}},
    },
}
STORYLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["slides"],
    "properties": {
        "title": _STR, "subtitle": {"type": ["string", "null"]},
        "slides": {"type": "array", "items": {"type": "object", "properties": {
            "title": _STR, "section": _STR, "sentences": {"type": "array", "items": {"type": "integer"}}, "data": _STRS, "form": _STR}}},
    },
}
CRITIQUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["issues"],
    "properties": {"issues": {"type": "array", "items": {"type": "object", "properties": {"slide": {"type": "integer"}, "problem": _STR, "fix": _STR}}}},
}

__all__ = [
    "Alternative", "CHART_TYPES", "CriticIssue", "CritiqueAnswer", "DESIGN_KINDS", "InlineSeries", "SlideDesignAnswer",
    "StorySlide", "StorylineAnswer", "chart_type_name", "kind_name", "number_of",
]
