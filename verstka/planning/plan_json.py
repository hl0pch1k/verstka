"""The outline planner's answer as models really write it, normalised before validation.

Open models of 27–32B follow the plan schema loosely. Seen on live runs: every content slide typed «section» (the
structured strategy asks for section dividers, and the model put the section's bullets inside them — the plan was
then rejected as having «no content slides»), a slide without a headline (a validation error, three paid retries),
an agenda with bullets instead of items, «type» instead of «kind», content fields next to «content», figures as
numbers, items as strings, a chart type the schema does not know. None of that is a reason to lose the answer: the
shape is repaired here (`normalise_plan`), the content itself is judged later against the brief
(verstka.planning.grounding).
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from pydantic import model_validator

from verstka.schemas.common import PatternKind
from verstka.schemas.outline import OutlineSlide, PlannedDeck

KINDS = {k.value for k in PatternKind}
# the kinds the planner may use (skills/outline_planner/prompts/system.md); the others (freeform, code, mockup) and
# unknown names are typed by their content
ALLOWED_KINDS = {
    "title", "agenda", "section", "thanks", "bullets", "cards", "two_column", "comparison", "process", "timeline", "team",
    "big_number", "stat_row", "table", "chart", "quote", "image_text",
}
FRAME_KINDS = {"title", "agenda", "section", "thanks"}
_KIND_ALIASES = {
    "cover": "title", "title_slide": "title", "intro": "title", "opening": "title",
    "closing": "thanks", "end": "thanks", "final": "thanks", "questions": "thanks", "thank_you": "thanks", "contacts": "thanks",
    "divider": "section", "section_header": "section", "section_title": "section", "chapter": "section",
    "contents": "agenda", "toc": "agenda", "table_of_contents": "agenda", "plan": "agenda",
    "list": "bullets", "bullet": "bullets", "bullet_list": "bullets", "bulleted": "bullets", "text": "bullets", "content": "bullets",
    "kpi": "stat_row", "kpis": "stat_row", "stats": "stat_row", "metrics": "stat_row", "numbers": "stat_row", "kpi_row": "stat_row",
    "big_numbers": "stat_row", "number": "big_number", "stat": "big_number", "kpi_single": "big_number", "hero_number": "big_number",
    "columns": "two_column", "two_columns": "two_column", "twocolumn": "two_column", "compare": "comparison", "vs": "comparison",
    "steps": "process", "flow": "process", "roadmap": "timeline", "graph": "chart", "diagram": "chart",
    "image": "image_text", "picture": "image_text", "photo": "image_text", "people": "team",
    "card": "cards", "grid": "cards", "features": "cards", "tiles": "cards",
}
_CHART_TYPES = {"bar", "column", "line", "area", "pie", "doughnut"}
_CHART_ALIASES = {"bar_chart": "bar", "barchart": "bar", "horizontal_bar": "bar", "column_chart": "column", "histogram": "column", "line_chart": "line", "pie_chart": "pie", "donut": "doughnut"}
_CONTENT_KEYS = ("bullets", "paragraphs", "items", "numbers", "table", "chart", "quote", "quote_author", "image_hint", "columns")
_WRAPPERS = ("plan", "deck", "presentation", "outline", "result", "data", "response", "answer")


def _s(value: Any) -> str:
    """A text field as a string: a number written as a number, a dict by its text, a list joined."""
    if value is None:
        return ""
    if isinstance(value, bool):
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
    return str(value).strip()


def _opt(value: Any) -> Optional[str]:
    t = _s(value)
    return t or None


def _lines(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        t = _s(value)
        return [t] if t else []
    if isinstance(value, list):
        return [t for t in (_s(v) for v in value) if t]
    t = _s(value)
    return [t] if t else []


def _item(value: Any) -> Optional[dict]:
    if isinstance(value, str) or isinstance(value, (int, float)):
        t = _s(value)
        return {"title": t} if t else None
    if not isinstance(value, dict):
        return None
    title = _s(value.get("title") or value.get("name") or value.get("heading") or value.get("header") or value.get("label"))
    text = _s(value.get("text") or value.get("description") or value.get("desc") or value.get("body") or value.get("role") or value.get("subtitle"))
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
        return {"value": _s(value), "label": "", "fact_id": None}
    if isinstance(value, str):
        return {"value": value.strip(), "label": "", "fact_id": None} if value.strip() else None
    if not isinstance(value, dict):
        return None
    v = _s(value.get("value") if value.get("value") not in (None, "") else value.get("number") or value.get("figure") or value.get("metric"))
    label = _s(value.get("label") or value.get("title") or value.get("name") or value.get("description") or value.get("text"))
    fid = value.get("fact_id")
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
    if not cols and not out_rows:
        return None
    return {"columns": cols, "rows": out_rows, "unit": _opt(value.get("unit")), "caption": _opt(value.get("caption"))}


def _chart(value: Any) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    t = _s(value.get("type") or value.get("chart_type")).lower().replace(" ", "_").replace("-", "_")
    t = _CHART_ALIASES.get(t, t)
    ids = value.get("series_ids") or value.get("series") or value.get("ids") or []
    if isinstance(ids, (str, dict)):
        ids = [ids]
    series_ids = [x for x in ((i.get("id") if isinstance(i, dict) else i) for i in ids if i) if isinstance(x, str) and x]
    hi = value.get("highlight_index")
    return {
        "type": t if t in _CHART_TYPES else "column",
        "series_ids": series_ids,
        "title": _opt(value.get("title")),
        "unit": _opt(value.get("unit")),
        "highlight_index": hi if isinstance(hi, int) and not isinstance(hi, bool) else None,
    }


def _kind_name(value: Any) -> str:
    k = _s(value).lower().strip().replace(" ", "_").replace("-", "_")
    k = _KIND_ALIASES.get(k, k)
    return k if k in ALLOWED_KINDS else ""


def kind_by_content(content: dict, position: str = "middle") -> str:
    """The kind a slide's content asks for: a chart, a table, a quote, columns, items, one figure or a row of them,
    else a list. `content` is a normalised content dict."""
    lines = len(content.get("bullets") or []) + len(content.get("paragraphs") or [])
    nums = len(content.get("numbers") or [])
    if content.get("chart"):
        return "chart"
    if content.get("table"):
        return "table"
    if content.get("quote"):
        return "quote"
    if content.get("columns"):
        return "two_column"
    if content.get("items"):
        return "cards"
    if nums and lines <= 1:
        return "big_number" if nums == 1 else "stat_row"
    if lines:
        return "bullets"
    if nums:
        return "big_number" if nums == 1 else "stat_row"
    return {"first": "title", "last": "thanks"}.get(position, "section")


def has_body(content: dict) -> bool:
    return any(content.get(k) for k in ("bullets", "paragraphs", "items", "numbers", "table", "chart", "quote", "columns"))


def _slide(raw: Any, i: int, n: int) -> Optional[dict]:
    if isinstance(raw, str):
        raw = {"headline": raw}
    if not isinstance(raw, dict):
        return None
    c = raw.get("content")
    content: dict = dict(c) if isinstance(c, dict) else {}
    if isinstance(c, (str, list)):
        content["paragraphs" if isinstance(c, str) else "bullets"] = c
    for k in _CONTENT_KEYS + ("text", "points", "cards", "metrics", "stats", "kpis", "body"):
        if k in raw and k not in content and raw[k] not in (None, "", [], {}):
            content[k] = raw[k]
    norm = {
        "bullets": _lines(content.get("bullets") or content.get("points")),
        "paragraphs": _lines(content.get("paragraphs") or content.get("text") or content.get("body")),
        "items": _items(content.get("items") or content.get("cards")),
        "numbers": [x for x in (_number(v) for v in (content.get("numbers") or content.get("metrics") or content.get("stats") or content.get("kpis") or [])) if x],
        "table": _table(content.get("table")),
        "chart": _chart(content.get("chart")),
        "quote": _opt(content.get("quote")),
        "quote_author": _opt(content.get("quote_author")),
        "image_hint": _opt(content.get("image_hint")),
        "columns": _items(content.get("columns")),
    }
    if isinstance(content.get("numbers"), (dict, str, int, float)) and not norm["numbers"]:
        one = _number(content["numbers"])
        norm["numbers"] = [one] if one else []
    position = "first" if i == 0 else "last" if i == n - 1 else "middle"
    kind = _kind_name(raw.get("kind") or raw.get("type") or raw.get("layout") or raw.get("slide_type"))
    if kind == "agenda" and not norm["items"] and (norm["bullets"] or norm["paragraphs"]) and not (norm["numbers"] or norm["chart"] or norm["table"]):
        norm["items"] = [{"title": t, "text": "", "icon_hint": None, "number": None, "bullets": []} for t in norm["bullets"] + norm["paragraphs"]]
        norm["bullets"], norm["paragraphs"] = [], []
    retyped = False
    if not kind:
        kind, retyped = kind_by_content(norm, position), True
    elif kind == "section" and has_body(norm):
        # a «section» with bullets, figures or items is a content slide of that section, not a divider
        kind, retyped = kind_by_content(norm), True
    elif kind == "title" and position != "first" and has_body(norm):
        kind, retyped = kind_by_content(norm), True
    elif kind == "agenda" and (norm["numbers"] or norm["chart"] or norm["table"] or norm["columns"]):
        kind, retyped = kind_by_content(norm), True
    headline = _s(raw.get("headline") or raw.get("heading") or raw.get("header") or (raw.get("title") if isinstance(raw.get("title"), str) else ""))
    section = _opt(raw.get("section"))
    if not headline and kind == "section" and section:
        headline = section
    if retyped and not section and raw.get("kind") in ("section", "title") and headline:
        # the divider's name is the section this content belongs to; grounding checks it like every section label
        # (a label the brief does not say goes, whatever becomes of the headline)
        section = headline
    refs = raw.get("fact_refs") or []
    return {
        "id": _s(raw.get("id")) or f"sl{i + 1}",
        "kind": kind,
        "section": section,
        "headline": headline,
        "subtitle": _opt(raw.get("subtitle")),
        "content": norm,
        "notes": _s(raw.get("notes") or raw.get("speaker_notes")),
        "fact_refs": [r for r in (refs if isinstance(refs, list) else [refs]) if isinstance(r, str) and r],
    }


def normalise_plan(data: Any) -> Any:
    """The planner's JSON answer in the shape of PlannedDeck. Anything that is not a plan at all is returned as it is
    (and fails validation as before)."""
    if isinstance(data, list):
        data = {"title": "", "slides": data}
    if not isinstance(data, dict):
        return data
    if "slides" not in data:
        inner = next((data[k] for k in _WRAPPERS if isinstance(data.get(k), dict) and "slides" in data[k]), None)
        if inner is None:
            inner = next((v for v in data.values() if isinstance(v, dict) and isinstance(v.get("slides"), list)), None)
        if inner is None:
            return data
        data = inner
    raw_slides = data.get("slides")
    if not isinstance(raw_slides, list):
        return data
    n = len(raw_slides)
    slides = [s for s in (_slide(r, i, n) for i, r in enumerate(raw_slides)) if s is not None]
    title = _s(data.get("title") or data.get("deck_title") or data.get("name"))
    if not title and slides and slides[0]["kind"] == "title":
        title = slides[0]["headline"]
    return {"title": title, "subtitle": _opt(data.get("subtitle")), "slides": slides}


def retype_frames(slides: list[OutlineSlide]) -> list[OutlineSlide]:
    """The same repair on slides that are already validated (a plan built in code, a plan from an older schema): a
    section or a title in the middle that carries content is typed by its content."""
    n = len(slides)
    for i, s in enumerate(slides):
        c = s.content.model_dump()
        if (s.kind == PatternKind.section or (s.kind == PatternKind.title and i > 0)) and has_body(c):
            if s.kind == PatternKind.section and not s.section:
                s.section = s.headline
            s.kind = PatternKind(kind_by_content(c))
        elif s.kind.value not in ALLOWED_KINDS:
            s.kind = PatternKind(kind_by_content(c, "first" if i == 0 else "last" if i == n - 1 else "middle"))
    return slides


class PlannedDeckAnswer(PlannedDeck):
    """PlannedDeck as the outline_planner skill reads it: the answer is repaired (normalise_plan) before it is
    validated. The JSON schema the model is shown (model_json_schema) is PlannedDeck's own — its title and
    description, not this class's — with the slide kinds narrowed to ALLOWED_KINDS, the names the prompt allows."""

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, data: Any) -> Any:
        return normalise_plan(data)

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        schema = copy.deepcopy(PlannedDeck.model_json_schema(*args, **kwargs))
        kinds = schema.get("$defs", {}).get("PatternKind")
        if isinstance(kinds, dict) and isinstance(kinds.get("enum"), list):
            kinds["enum"] = [k for k in kinds["enum"] if k in ALLOWED_KINDS]
        return schema

