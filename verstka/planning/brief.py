"""Brief loading: plain text, markdown with YAML front matter, or JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Union

import yaml

from verstka.schemas.outline import Brief

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_KEY_ALIASES = {
    "slides": "slide_count",
    "slide_count": "slide_count",
    "audience": "audience",
    "аудитория": "audience",
    "purpose": "purpose",
    "тип": "purpose",
    "title": "title_hint",
    "название": "title_hint",
    "language": "language",
    "язык": "language",
    "tone": "tone",
    "тон": "tone",
    "instructions": "extra_instructions",
    "инструкции": "extra_instructions",
}
_PURPOSE_ALIASES = {"фича": "feature", "feature": "feature", "продукт": "product", "product": "product", "проект": "project", "project": "project", "инициатива": "initiative", "initiative": "initiative", "отчёт": "report", "отчет": "report", "report": "report"}


def parse_brief_text(text: str) -> Brief:
    meta: dict = {}
    body = text
    m = _FRONT_MATTER_RE.match(text)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        body = text[m.end() :]
    fields: dict = {}
    for k, v in (meta or {}).items():
        key = _KEY_ALIASES.get(str(k).strip().lower())
        if key:
            fields[key] = v
    if "purpose" in fields and fields["purpose"] is not None:
        fields["purpose"] = _PURPOSE_ALIASES.get(str(fields["purpose"]).strip().lower(), "other")
    if "slide_count" in fields and fields["slide_count"] is not None:
        try:
            fields["slide_count"] = int(fields["slide_count"])
        except (TypeError, ValueError):
            fields.pop("slide_count")
    # "не более N слайдов" written inside the text also counts as an instruction
    if "slide_count" not in fields:
        m2 = re.search(r"(?:не более|максимум|до|ровно|not more than|up to|max)\s+(\d{1,2})\s+слайд", body, re.I)
        if m2:
            fields["slide_count"] = int(m2.group(1))
    if "title_hint" not in fields:
        h = re.search(r"^\s*#\s+(.+)$", body, re.M)
        if h:
            fields["title_hint"] = h.group(1).strip()
    return Brief(text=body.strip(), **fields)


def load_brief(src: Union[Path, str]) -> Brief:
    p = Path(src) if not isinstance(src, Path) else src
    if isinstance(src, (str, Path)) and p.exists() and p.is_file():
        raw = p.read_text(encoding="utf-8")
        if p.suffix.lower() == ".json":
            return Brief.model_validate(json.loads(raw))
        return parse_brief_text(raw)
    return parse_brief_text(str(src))
