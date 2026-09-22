"""Facts registry: numbers, series and tables extracted from the brief."""

from __future__ import annotations

import re
from typing import Optional

from verstka.planning import heuristics as H
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
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


def basic_facts(text: str, max_facts: int = 16) -> FactsExtraction:
    """Numbers with their unit and a short label (heuristics.kpis_of), tables with their lead line, chart series."""
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
    return FactsExtraction(facts=facts, series=series, tables=tables)


def extract_facts(brief: Brief, skills: Optional[SkillsRegistry] = None, providers: Optional[ProviderRegistry] = None) -> tuple[FactsExtraction, list[str]]:
    warnings: list[str] = []
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
            return out, warnings
        except (ProviderError, ValueError, KeyError) as e:
            warnings.append(f"data_extractor failed, using regex facts: {str(e)[:160]}")
    return basic_facts(brief.text), warnings
