"""Brief loading: plain text, markdown with YAML front matter, or JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional, Union

import yaml

from verstka.schemas.outline import Brief

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
# the deck's own size said in its text — only a phrase about the whole deck: «не более 10 слайдов», «на 8 слайдов»,
# «Сделай 12 слайдов», «at most 10 slides»; never «в 2 слайдах», «Первые 2 слайда», «3 слайда про рынок» (a part of the
# deck, not its size). The web client reads the text with the same rule (web/src/lib/textFacts.ts COUNT).
SLIDE_COUNT_RE = re.compile(
    r"(?:не\s+более|не\s+больше|максимум|до|ровно)\s+(\d{1,2})\s+слайд"
    r"|(?<![а-яё])на\s+(\d{1,2})\s+слайд(?:ов|а)?(?![а-яё])"
    r"|(?:сделай(?:те)?|подготовь(?:те)?|собери(?:те)?|нуж(?:ен|н[оаы]?)|хочу)[^.\n]{0,30}?\s(\d{1,2})\s+слайд(?:ов|а)?(?![а-яё])"
    r"|(?:not\s+more\s+than|no\s+more\s+than|up\s+to|max(?:imum)?|at\s+most|exactly)\s+(\d{1,2})\s+slides?\b"
    r"|(\d{1,2})-slide\s+(?:deck|presentation)"
    r"|(?:make|create|prepare|build)[^.\n]{0,30}?\s(\d{1,2})\s+slides?\b",
    re.I,
)

# a range of slides («6–8 слайдов», «слайдов 8–10», «8-10 slides»): the deck keeps within it — its upper bound is the
# deck's size (the jury's knowledge-base deck asked «6–8 слайдов» and got 12)
SLIDE_RANGE_RE = re.compile(
    r"(?<![\d.,])(?<!по\s)(?<!в\s)(\d{1,2})\s*(?:[–—−-]|до)\s*(\d{1,2})\s+(?:слайд(?:ов|а)?(?![а-яё])|slides?\b)"
    r"|(?<![а-яё])слайд(?:ов|а)?\s*(?:[:—–-]\s*)?(?:от\s+)?(\d{1,2})\s*(?:[–—−-]|до)\s*(\d{1,2})(?!\d|[.,]\d)",
    re.I,
)


def slide_range(text: str) -> Optional[tuple[int, int]]:
    """(at least, at most) of a range of slides the text asks for, None without one."""
    m = SLIDE_RANGE_RE.search(text or "")
    if not m:
        return None
    a, b = [int(g) for g in m.groups() if g]
    lo, hi = min(a, b), max(a, b)
    return (lo, hi) if 1 <= lo <= hi <= 60 else None


def slide_count_of(text: str) -> Optional[int]:
    """The deck's size the text asks for: the upper bound of a range («6–8 слайдов» → 8), else «не более 10 слайдов» /
    «на 8 слайдов» / «Сделай 12 слайдов»."""
    r = slide_range(text)
    if r is not None:
        return r[1]
    m = SLIDE_COUNT_RE.search(text or "")
    if m:
        return int(next(g for g in m.groups() if g))
    # «… модели обслуживания. 7 слайдов.» — the deck's size said on its own after the request
    m = re.search(r"(?:^|[.!?,;:—–]\s*)(\d{1,2})\s+слайд(?:ов|а)\s*[.!]?\s*$", (text or "").strip(), re.I | re.M)
    return int(m.group(1)) if m else None


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


def normalize_purpose(value: Optional[str]) -> Optional[str]:
    """Map a free-form purpose («фича», "feature", ...) onto the Brief.purpose literal; unknown values become "other"."""
    if value is None:
        return None
    return _PURPOSE_ALIASES.get(str(value).strip().lower(), "other")


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
        fields["purpose"] = normalize_purpose(fields["purpose"])
    if "slide_count" in fields and fields["slide_count"] is not None:
        raw = fields["slide_count"]
        try:
            fields["slide_count"] = int(raw)
        except (TypeError, ValueError):
            got = slide_count_of(f"{raw} слайдов") if isinstance(raw, str) else None  # «slides: 6–8»
            if got:
                fields["slide_count"] = got
            else:
                fields.pop("slide_count")
    # "не более N слайдов", «6–8 слайдов» written inside the text also count as an instruction
    if "slide_count" not in fields:
        got = slide_count_of(body)
        if got:
            fields["slide_count"] = got
    if "title_hint" not in fields:
        from verstka.planning.brief_structure import without_code

        # (a «# comment» of the user's code is no markdown title)
        h = re.search(r"^\s*#\s+(.+)$", "\n".join(without_code(body.splitlines())), re.M)
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
