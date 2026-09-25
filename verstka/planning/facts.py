"""Facts registry: numbers, series and tables extracted from the brief.

The series and tables of the brief's structure (planning/brief_structure.py: lists, enumerations, «с X до Y», «Сейчас
/ Цель» tables, markdown tables) come first and keep their ids — the slide specs name them; series found otherwise
that are not the same data follow with ids of their own."""

from __future__ import annotations

import re
from typing import Optional

from verstka.planning import heuristics as H
from verstka.planning.brief_structure import read_structure
from verstka.planning.grounding import grounded_facts
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.brief_structure import BriefStructure
from verstka.schemas.outline import Brief, Fact, FactsExtraction, Series, TableData
from verstka.skills_registry.registry import SkillsRegistry

_NUM_RE = re.compile(r"(?<![\w.])([+\-−]?\d[\d\s]{0,8}(?:[.,]\d+)?)\s?(%|млн|млрд|тыс\.?|ч(?:ас(?:ов|а)?)?|дн(?:ей|я)?|раз|шт\.?|₽|руб\.?|\$|USD|RUB|k|K|M|x|×)?(?![\w])")
_SENT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


def _markdown_tables(text: str) -> list[TableData]:
    tables: list[TableData] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _TABLE_ROW_RE.match(lines[i])
        if m and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            header = [c.strip() for c in m.group(1).split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and _TABLE_ROW_RE.match(lines[j]):
                rows.append([c.strip() for c in _TABLE_ROW_RE.match(lines[j]).group(1).split("|")])
                j += 1
            if header and rows:
                tables.append(TableData(columns=header, rows=rows, source_span=lines[i]))
            i = j
        else:
            i += 1
    return tables


def _series_from_table(tbl: TableData, idx: int) -> Optional[Series]:
    """A markdown table whose columns after the first are numeric becomes one series per row (first row only)."""
    if len(tbl.columns) < 3 or not tbl.rows:
        return None
    cats = tbl.columns[1:]
    row = tbl.rows[0]
    try:
        vals = [float(re.sub(r"[^\d.,\-]", "", v).replace(",", ".").replace(" ", "")) for v in row[1:]]
    except ValueError:
        return None
    if len(vals) != len(cats):
        return None
    return Series(id=f"s{idx}", name=row[0], categories=cats, values=vals, source_span=tbl.source_span)


def _data_key(s: Series) -> tuple:
    return (tuple(round(v, 6) for v in s.values), tuple(c.lower() for c in s.categories))


def merge_data(primary: FactsExtraction, series: list[Series], tables: list[TableData]) -> FactsExtraction:
    """`primary` keeps its series ids; the other series that are not the same data (values and categories) are added
    with an id no series of `primary` has, the other tables when not the same cells."""
    out_series = list(primary.series)
    keys = {_data_key(s) for s in out_series}
    ids = {s.id for s in out_series}
    for s in series:
        if _data_key(s) in keys:
            continue
        s = s.model_copy()
        if not s.id or s.id in ids:
            n = len(out_series) + 1
            while f"s{n}" in ids:
                n += 1
            s.id = f"s{n}"
        ids.add(s.id)
        keys.add(_data_key(s))
        out_series.append(s)
    out_tables = list(primary.tables)
    for t in tables:
        if not any(t.columns == u.columns and t.rows == u.rows for u in out_tables):
            out_tables.append(t)
    return FactsExtraction(facts=list(primary.facts), series=out_series, tables=out_tables)


def basic_facts(text: str, max_facts: int = 16, structure: Optional[BriefStructure] = None) -> FactsExtraction:
    """Numbers with their unit and a short label (heuristics.kpis_of), the structure's series and tables (read here
    when not given), then the tables' own chart series."""
    facts: list[Fact] = []
    seen: set[str] = set()
    _, sections = H.parse_sections(text)
    sentences = [sn for sec in sections for sn in sec.sentences] or [x.strip() for x in _SENT_RE.split(text) if x.strip()]
    for s in sentences:
        kpis = H.kpis_of(s)
        for m in _NUM_RE.finditer(s):
            value = re.sub(r"\s+", " ", m.group(1)).strip()
            unit = (m.group(2) or "").strip() or None
            if not any(ch.isdigit() for ch in value):
                continue
            key = f"{value}{unit or ''}"
            if key in seen or (unit is None and len(value.replace(" ", "")) <= 1):
                continue
            seen.add(key)
            digits = re.sub(r"\D", "", value)
            k = next((k for k in kpis if digits and digits in re.sub(r"\D", "", k.value)), None)
            label = k.label if k is not None else s[:120]
            facts.append(Fact(id=f"f{len(facts) + 1}", value=value, unit=unit, label=label, source_span=s[:200]))
            if len(facts) >= max_facts:
                break
        if len(facts) >= max_facts:
            break
    tables = [t for sec in sections for t in sec.tables] or _markdown_tables(text)
    series: list[Series] = []
    for t in tables:
        ss, _ = H.table_series(t, start_id=len(series) + 1)
        series.extend(ss)
    st = structure if structure is not None else read_structure(text)
    return merge_data(FactsExtraction(facts=facts, series=[s.model_copy() for s in st.series], tables=list(st.tables)), series, tables)


def _with_model_facts(out: FactsExtraction, extra: list[Fact]) -> FactsExtraction:
    """The model's facts of the structure (per block) after the rules' ones, one per figure, ids renumbered."""
    seen = {(re.sub(r"\D", "", f.value), f.unit or "") for f in out.facts}
    facts = list(out.facts)
    for f in extra:
        key = (re.sub(r"\D", "", f.value), f.unit or "")
        if key in seen:
            continue
        seen.add(key)
        facts.append(f.model_copy())
    for i, f in enumerate(facts, 1):
        f.id = f"f{i}"
    return FactsExtraction(facts=facts, series=out.series, tables=out.tables)


def extract_facts(
    brief: Brief, skills: Optional[SkillsRegistry] = None, providers: Optional[ProviderRegistry] = None, structure: Optional[BriefStructure] = None
) -> tuple[FactsExtraction, list[str]]:
    """The registry of the brief. With `structure` (Agent v2: read_structure + enrich_with_model already ran, the model
    per block) no model is called here: the rules' figures, the structure's model facts, series and tables. Without it
    the data_extractor reads the whole brief as before, and the structure's series and tables are added."""
    warnings: list[str] = []
    if structure is not None:
        out = _with_model_facts(basic_facts(brief.text, max_facts=40, structure=structure), structure.facts)
        out.facts, changed = grounded_facts(out.facts, brief)
        warnings.extend(changed)
        return out, warnings
    # facts are figures: a brief without a single digit has none, and asking a model for them only spends its budget
    if not any(ch.isdigit() for ch in brief.text):
        return basic_facts(brief.text), warnings
    if skills is not None and providers is not None and providers.has("llm"):
        try:
            res = skills.run("data_extractor", providers, {"brief": brief.text, "language": brief.language})
            out: FactsExtraction = res.parsed
            # normalise ids
            for i, f in enumerate(out.facts, 1):
                f.id = f.id or f"f{i}"
            for i, s in enumerate(out.series, 1):
                s.id = s.id or f"s{i}"
            if not out.tables:
                out.tables = _markdown_tables(brief.text)
            st = read_structure(brief.text)
            out = merge_data(FactsExtraction(facts=out.facts, series=out.series, tables=out.tables), st.series, st.tables)
            # the registry is the planner's only source of figures: a figure the brief does not have, or a unit the
            # brief does not give it («NPS 64» registered as «64 %»), must not reach the plan
            out.facts, changed = grounded_facts(out.facts, brief)
            warnings.extend(changed)
            return out, warnings
        except (ProviderError, ValueError, KeyError) as e:
            warnings.append(f"data_extractor failed, using regex facts: {str(e)[:160]}")
    return basic_facts(brief.text), warnings
