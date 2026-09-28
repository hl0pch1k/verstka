"""Answers of the writer-mode skills (planning/writer.py): topic_reference (the encyclopedia articles of a topic and its
kind), deck_writer (the source text of a whole deck written from a topic) and writer_check (the fact check,
deletion-only).

The writer's answer is parsed by writer.py (extract_json, then salvage slide by slide when the answer is cut), not by
the provider: with a schema the provider asks a cut answer again «much shorter», which halved the text in the probes.
Open models follow the shape loosely — a data row as «СССР — 27», a value as «27 млн», a timeline entry as «1939 — …»,
the slides nested under «deck» — so every shape is repaired here before validation (model_validator mode="before");
what cannot be repaired is dropped, never a reason to lose the answer.

The compact JSON schemas (model_json_schema) are the contract the prompts show; the tests validate recorded answers
against these classes."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from verstka.schemas.agent import number_of

CHARTS = ("column", "bar", "line", "pie")
_SPACED_DASH_RE = re.compile(r"\s+[—–-]\s+")
_DASH_RE = re.compile(r"\s*[—–:]\s*")
# a citation of the numbered reference («[41]», «[41, 42]», «[41–43]»): writer.py anchors the statement to it
_MARK_RE = re.compile(r"\s*\[\s*(?:№\s*)?(\d{1,4}(?:\s*(?:[,;]|[-–—])\s*\d{1,4})*)\s*\]")


def _ids(body: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"\s*[,;]\s*", body or ""):
        part = part.strip()
        m = re.fullmatch(r"(\d{1,4})\s*[-–—]\s*(\d{1,4})", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out += list(range(a, b + 1)) if 0 <= b - a <= 4 else [a, b]
        elif part.isdigit():
            out.append(int(part))
    return out


def _marks(text: str, into: list[int]) -> str:
    """The text without its citation marks, their numbers added to `into`."""
    if "[" not in (text or ""):
        return text
    for m in _MARK_RE.finditer(text):
        into.extend(_ids(m.group(1)))
    out = _MARK_RE.sub("", text)
    return re.sub(r"\s+([,.;:!?…])", r"\1", " ".join(out.split())).strip()


def _src(value: Any) -> list[int]:
    """The «src» a model wrote on an entry, a row or a chart: [41, 42], "41, 42", «[41]»."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [int(value)]
    if isinstance(value, str):
        return _ids(value.strip("[] "))
    if isinstance(value, list):
        return [int(v) for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)] + [
            i for v in value if isinstance(v, str) for i in _ids(v.strip("[] "))]
    return []


def _s(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, (int, str)):
        return " ".join(str(value).split())
    if isinstance(value, dict):
        for k in ("text", "title", "name", "label", "value"):
            if value.get(k):
                return _s(value[k])
        return ""
    if isinstance(value, list):
        return " ".join(t for t in (_s(v) for v in value) if t)
    return ""


def _event(value: Any) -> Optional[dict]:
    """{"when", "what"} of a timeline entry written as an object, a pair or «1939 — Германия нападает на Польшу»."""
    ids: list[int] = []
    out: Optional[dict] = None
    if isinstance(value, dict):
        ids += _src(value.get("src") or value.get("source") or value.get("sources"))
        when = _marks(_s(value.get("when") or value.get("date") or value.get("year") or value.get("time")), ids)
        what = _marks(_s(value.get("what") or value.get("event") or value.get("text") or value.get("title")), ids)
        out = {"when": when, "what": what} if when and what else None
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        when, what = _marks(_s(value[0]), ids), _marks(_s(value[1]), ids)
        out = {"when": when, "what": what} if when and what else None
    elif isinstance(value, str):
        v = _marks(value.strip(), ids)
        parts = _SPACED_DASH_RE.split(v, maxsplit=1)
        if len(parts) != 2:
            parts = _DASH_RE.split(v, maxsplit=1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            out = {"when": parts[0].strip(), "what": parts[1].strip()}
    if out is not None and ids:
        out["src"] = list(dict.fromkeys(ids))
    return out


def _row(value: Any) -> Optional[dict]:
    """{"label", "value"} of a data row written as an object, a pair or «СССР — 27»; None without a label or a number."""
    label: str = ""
    raw: Any = None
    ids: list[int] = []
    if isinstance(value, dict):
        ids += _src(value.get("src") or value.get("source") or value.get("sources"))
        label = _marks(_s(value.get("label") or value.get("name") or value.get("category") or value.get("country") or value.get("year")), ids)
        raw = value.get("value") if value.get("value") is not None else value.get("number", value.get("amount"))
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        label, raw = _s(value[0]), value[1]
    elif isinstance(value, str):
        m = re.match(r"^\s*(?P<label>.+?)\s*(?:[—–:]|\s-\s)\s*(?P<value>[+\-−]?\d.*)$", value)
        if m:
            label, raw = m.group("label").strip(), m.group("value")
    if isinstance(raw, str):
        raw = _marks(raw, ids)
    v = number_of(raw)
    if not label or v is None:
        return None
    return {"label": label, "value": v, **({"src": list(dict.fromkeys(ids))} if ids else {})}


def _data(value: Any) -> Optional[dict]:
    if not isinstance(value, dict):
        if isinstance(value, list):
            value = {"rows": value}
        else:
            return None
    rows = [r for r in (_row(x) for x in (value.get("rows") or value.get("values") or value.get("data") or [])) if r]
    chart = _s(value.get("chart") or value.get("type")).lower()
    chart = {"bar_chart": "bar", "column_chart": "column", "line_chart": "line", "pie_chart": "pie", "круговая": "pie",
             "линейная": "line", "столбчатая": "column", "doughnut": "pie"}.get(chart, chart)
    ids = _src(value.get("src") or value.get("source") or value.get("sources"))
    out = {
        "caption": _marks(_s(value.get("caption") or value.get("title") or value.get("name")), ids),
        "unit": _s(value.get("unit")),
        "chart": chart if chart in CHARTS else "column",
        "rows": rows,
    }
    if ids:
        out["src"] = list(dict.fromkeys(ids))
    return out


def normalise_writer(data: Any) -> Any:
    if isinstance(data, list):
        data = {"slides": data}
    if not isinstance(data, dict):
        return data
    if not isinstance(data.get("slides"), list):
        for key in ("deck", "presentation", "result"):
            inner = data.get(key)
            if isinstance(inner, dict) and isinstance(inner.get("slides"), list):
                data = {**inner, **{k: v for k, v in data.items() if k != key and k not in inner}}
                break
    status = _s(data.get("status")).lower() or "ok"
    out: dict[str, Any] = {
        "status": status if status in ("ok", "private", "refuse") else "ok",
        "kind": _s(data.get("kind")).lower() or "other",
        "title": _s(data.get("title")),
        "subtitle": _s(data.get("subtitle")),
        "slides": [],
    }
    for s in data.get("slides") or []:
        if isinstance(s, str):
            s = {"text": s}
        if not isinstance(s, dict):
            continue
        tl = s.get("timeline")
        text = s.get("text")
        if isinstance(tl, dict):
            # {"text": "…", "entries": [...]}: the timeline wrapped with its context sentences (live «История VK»: the
            # chronology slide was lost)
            inner = next((tl.get(k) for k in ("entries", "events", "items", "timeline", "list") if isinstance(tl.get(k), list)), None)
            if not _s(text if not isinstance(text, list) else " ".join(map(_s, text))) and _s(tl.get("text") or tl.get("context")):
                text = tl.get("text") or tl.get("context")
            tl = inner
        events = [e for e in (_event(x) for x in tl) if e] if isinstance(tl, list) else []
        if isinstance(text, list):
            text = " ".join(_s(x) for x in text if _s(x))
        out["slides"].append({
            "title": _s(s.get("title") or s.get("headline")),
            "text": _s(text),
            "timeline": events or None,
            "data": _data(s.get("data")),
        })
    return out


class WriterEvent(BaseModel):
    when: str
    what: str
    src: list[int] = Field(default_factory=list)  # the numbered reference sentences it comes from


class WriterRow(BaseModel):
    label: str
    value: float
    src: list[int] = Field(default_factory=list)


class WriterData(BaseModel):
    caption: str = ""
    unit: str = ""
    chart: Literal["column", "bar", "line", "pie"] = "column"
    rows: list[WriterRow] = Field(default_factory=list)
    src: list[int] = Field(default_factory=list)


class WriterSlide(BaseModel):
    title: str = ""
    text: str = ""
    timeline: Optional[list[WriterEvent]] = None
    data: Optional[WriterData] = None


class WriterAnswer(BaseModel):
    """Output of the `deck_writer` skill: the deck's title, subtitle and content slides (the cover is not written)."""

    status: Literal["ok", "private", "refuse"] = "ok"
    kind: str = "other"
    title: str = ""
    subtitle: str = ""
    slides: list[WriterSlide] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        return normalise_writer(data)

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return WRITER_SCHEMA


class ReferenceAnswer(BaseModel):
    """Output of the `topic_reference` skill: 1–3 encyclopedia article titles (the main one first) and the topic's kind."""

    titles: list[str] = Field(default_factory=list)
    kind: str = "other"

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw = data.get("titles") or data.get("articles") or data.get("title") or []
        if isinstance(raw, str):
            raw = [raw]
        titles = [t for t in (_s(x).replace("_", " ").strip() for x in raw if isinstance(x, (str, dict))) if t]
        return {"titles": list(dict.fromkeys(titles))[:3], "kind": _s(data.get("kind")).lower() or "other"}

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return REFERENCE_SCHEMA


class WriterCheckIssue(BaseModel):
    id: str
    verdict: str = ""
    problem: str = ""
    evidence: str = ""  # the reference's own words that say otherwise (writer.apply_check puts them in, when fit)


class WriterCheckAnswer(BaseModel):
    """Output of the `writer_check` skill: the ids of the sentences, timeline entries and data rows that must go."""

    issues: list[WriterCheckIssue] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        if isinstance(data, list):
            data = {"issues": data}
        if not isinstance(data, dict):
            return data
        out = []
        for it in data.get("issues") or data.get("problems") or []:
            if not isinstance(it, dict):
                continue
            ident = _s(it.get("id") or it.get("sentence") or it.get("ref")).strip("[] ")
            if ident:
                out.append({"id": ident, "verdict": _s(it.get("verdict")).lower(), "problem": _s(it.get("problem") or it.get("reason")),
                            "evidence": _s(it.get("evidence") or it.get("reference") or it.get("quote"))})
        return {"issues": out}

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return CHECK_SCHEMA


_STR = {"type": "string"}
WRITER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status", "slides"],
    "properties": {
        "status": {"enum": ["ok", "private", "refuse"]}, "kind": _STR, "title": _STR, "subtitle": _STR,
        "slides": {"type": "array", "items": {"type": "object", "properties": {
            "title": _STR, "text": _STR,
            "timeline": {"type": ["array", "null"], "items": {"type": "object", "properties": {"when": _STR, "what": _STR}}},
            "data": {"type": ["object", "null"], "properties": {
                "caption": _STR, "unit": _STR, "chart": {"enum": list(CHARTS)}, "src": {"type": "array", "items": {"type": "integer"}},
                "rows": {"type": "array", "items": {"type": "object", "properties": {"label": _STR, "value": {"type": "number"}}}}}},
        }}},
    },
}
REFERENCE_SCHEMA: dict[str, Any] = {"type": "object", "required": ["titles", "kind"], "properties": {"titles": {"type": "array", "items": _STR}, "kind": _STR}}
CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["issues"],
    "properties": {"issues": {"type": "array", "items": {"type": "object", "properties": {"id": _STR, "verdict": _STR, "problem": _STR, "evidence": _STR}}}},
}

__all__ = [
    "CHECK_SCHEMA", "REFERENCE_SCHEMA", "ReferenceAnswer", "WRITER_SCHEMA", "WriterAnswer", "WriterCheckAnswer",
    "WriterCheckIssue", "WriterData", "WriterEvent", "WriterRow", "WriterSlide", "normalise_writer",
]
