"""plan_outline: brief → DeckOutline (LLM skills with a deterministic fallback) + validation."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from typing import Optional

from verstka.planning.condense import condense_text
from verstka.planning.strategies import Strategy
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import Brief, DeckOutline, FactCheck, FactsExtraction, NumberCallout, OutlineSlide, PlannedDeck, SlideContent, SlideItem
from verstka.schemas.template import TemplateManifest
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)

MAX_BULLETS = 6
MAX_WORDS_PER_BULLET = 15
MAX_ITEMS = 8
MAX_NUMBERS = 5
MAX_TABLE_ROWS = 7
MAX_TABLE_COLS = 5
MAX_SERIES = 5


def target_slide_count(brief: Brief, strategy: Strategy) -> int:
    base = brief.slide_count or 12
    if brief.slide_count:
        return max(3, base)
    return max(5, int(round(base * strategy.slide_ratio)))


def available_kinds(manifest: TemplateManifest) -> list[dict]:
    kinds: dict[str, dict] = {}
    for p in manifest.patterns:
        k = p.kind.value
        entry = kinds.setdefault(k, {"kind": k, "samples": 0, "max_items": 0})
        entry["samples"] += 1
        for g in p.repeat_groups:
            entry["max_items"] = max(entry["max_items"], g.max_n)
    return sorted(kinds.values(), key=lambda e: -e["samples"])


# ------------------------------------------------------------------ deterministic fallback


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) > 3]


def basic_outline(brief: Brief, facts: FactsExtraction, strategy: Strategy, target: int) -> DeckOutline:
    """Split the brief by headings/paragraphs into bullets slides; add title, KPI, chart, table and closing slides."""
    text = brief.text
    title = brief.title_hint or next((l.lstrip("# ").strip() for l in text.splitlines() if l.strip()), "Презентация")
    sections: list[tuple[str, list[str]]] = []
    current_title = None
    buf: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if buf:
                sections.append((current_title or "", buf))
                buf = []
            continue
        if s.startswith("#"):
            if buf:
                sections.append((current_title or "", buf))
                buf = []
            current_title = s.lstrip("# ").strip()
            continue
        if s.startswith("|"):
            continue
        buf.append(s.lstrip("-•* ").strip())
    if buf:
        sections.append((current_title or "", buf))
    slides: list[OutlineSlide] = [OutlineSlide(id="sl1", kind=PatternKind.title, headline=title, subtitle=brief.audience or None)]
    k = 2
    for sec_title, lines in sections:
        bullets: list[str] = []
        for l in lines:
            bullets.extend(_split_sentences(l) if len(l) > 160 else [l])
        bullets = [condense_text(b, MAX_WORDS_PER_BULLET) for b in bullets if b]
        for chunk_start in range(0, len(bullets), 5):
            chunk = bullets[chunk_start : chunk_start + 5]
            if not chunk:
                continue
            headline = sec_title or chunk[0]
            if len(chunk) >= 3 and len(headline) > 60:
                headline = condense_text(headline, 8)
            slides.append(OutlineSlide(id=f"sl{k}", kind=PatternKind.bullets, section=sec_title or None, headline=headline, content=SlideContent(bullets=chunk if len(chunk) > 1 or chunk[0] != headline else [])))
            k += 1
    if len(facts.facts) >= 3:
        nums = [NumberCallout(value=f"{f.value}{(' ' + f.unit) if f.unit and f.unit != '%' else (f.unit or '')}", label=condense_text(f.label, 8), fact_id=f.id) for f in facts.facts[:4]]
        slides.insert(min(2, len(slides)), OutlineSlide(id=f"sl{k}", kind=PatternKind.stat_row, headline="Ключевые цифры", content=SlideContent(numbers=nums), fact_refs=[n.fact_id for n in nums if n.fact_id]))
        k += 1
    for s in facts.series[:1]:
        from verstka.schemas.outline import ChartSpec

        slides.append(OutlineSlide(id=f"sl{k}", kind=PatternKind.chart, headline=s.name, content=SlideContent(chart=ChartSpec(type="column", series_ids=[s.id], unit=s.unit))))
        k += 1
    for t in facts.tables[:1]:
        slides.append(OutlineSlide(id=f"sl{k}", kind=PatternKind.table, headline=t.caption or "Данные", content=SlideContent(table=t)))
        k += 1
    slides.append(OutlineSlide(id=f"sl{k}", kind=PatternKind.thanks, headline="Спасибо за внимание", subtitle=None))
    outline = DeckOutline(title=title, subtitle=brief.audience, audience=brief.audience, purpose=brief.purpose, strategy=strategy.name, language=brief.language, slides=slides, facts=facts.facts, series=facts.series, tables=facts.tables)
    return validate_outline(outline, None, target)


# ------------------------------------------------------------------ validation


def validate_outline(outline: DeckOutline, manifest: Optional[TemplateManifest], target: int, skills: Optional[SkillsRegistry] = None, providers: Optional[ProviderRegistry] = None) -> DeckOutline:
    slides = list(outline.slides)
    # density limits
    for s in slides:
        c = s.content
        c.bullets = [condense_text(b, MAX_WORDS_PER_BULLET, skills, providers, outline.language) for b in c.bullets if b.strip()]
        if len(c.bullets) > MAX_BULLETS:
            extra = c.bullets[MAX_BULLETS:]
            c.bullets = c.bullets[:MAX_BULLETS]
            s.notes = (s.notes + "\n" if s.notes else "") + "Не вошло: " + "; ".join(extra)
        for it in c.items + c.columns:
            it.title = condense_text(it.title, 8, skills, providers, outline.language)
            it.text = condense_text(it.text, 24, skills, providers, outline.language) if it.text else it.text
            it.bullets = [condense_text(b, MAX_WORDS_PER_BULLET, skills, providers, outline.language) for b in it.bullets][:MAX_BULLETS]
        if len(c.items) > MAX_ITEMS:
            c.items = c.items[:MAX_ITEMS]
        if len(c.numbers) > MAX_NUMBERS:
            c.numbers = c.numbers[:MAX_NUMBERS]
        if c.table is not None:
            c.table.columns = c.table.columns[:MAX_TABLE_COLS]
            c.table.rows = [r[:MAX_TABLE_COLS] for r in c.table.rows[:MAX_TABLE_ROWS]]
        if c.chart is not None and len(c.chart.series_ids) > MAX_SERIES:
            c.chart.series_ids = c.chart.series_ids[:MAX_SERIES]
        s.headline = condense_text(s.headline, 14, skills, providers, outline.language)
        if s.kind in (PatternKind.stat_row, PatternKind.big_number) and not c.numbers:
            s.kind = PatternKind.bullets
        if s.kind == PatternKind.chart and c.chart is None:
            s.kind = PatternKind.bullets
        if s.kind == PatternKind.table and c.table is None:
            s.kind = PatternKind.bullets
    # first/last slides
    if slides and slides[0].kind != PatternKind.title:
        slides.insert(0, OutlineSlide(id="sl_title", kind=PatternKind.title, headline=outline.title, subtitle=outline.subtitle))
    if slides and slides[-1].kind != PatternKind.thanks:
        slides.append(OutlineSlide(id="sl_thanks", kind=PatternKind.thanks, headline="Спасибо за внимание"))
    # count: drop low-priority slides beyond target (+1 tolerance)
    def priority(s: OutlineSlide) -> int:
        return {PatternKind.section: 0, PatternKind.quote: 1, PatternKind.agenda: 2}.get(s.kind, 5)

    while len(slides) > target + 1:
        candidates = [s for s in slides[1:-1]]
        victim = min(candidates, key=lambda s: (priority(s), -slides.index(s)))
        if priority(victim) >= 5 and len(slides) <= target + 2:
            break
        slides.remove(victim)
    # unique headlines
    seen: Counter = Counter()
    for s in slides:
        seen[s.headline] += 1
        if seen[s.headline] > 1 and s.section:
            s.headline = f"{s.headline}: {s.section}"
    # unique ids
    ids: set[str] = set()
    for i, s in enumerate(slides, 1):
        if not s.id or s.id in ids:
            s.id = f"sl{i}"
        ids.add(s.id)
    outline.slides = slides
    return outline


# ------------------------------------------------------------------ LLM planning


def plan_outline(
    brief: Brief,
    manifest: TemplateManifest,
    strategy: Strategy,
    facts: FactsExtraction,
    skills: Optional[SkillsRegistry] = None,
    providers: Optional[ProviderRegistry] = None,
    target: Optional[int] = None,
) -> tuple[DeckOutline, list[str]]:
    warnings: list[str] = []
    target = target or target_slide_count(brief, strategy)
    if skills is None or providers is None or not providers.has("llm"):
        warnings.append("no LLM provider: deterministic outline")
        return basic_outline(brief, facts, strategy, target), warnings
    variables = {
        "brief": brief.text,
        "title_hint": brief.title_hint or "",
        "audience": brief.audience or "не указана",
        "purpose": brief.purpose or "не указан",
        "language": brief.language,
        "tone": brief.tone or "деловой",
        "extra_instructions": brief.extra_instructions or "",
        "target": target,
        "strategy_instructions": strategy.planner_instructions,
        "facts_json": json.dumps(facts.model_dump(), ensure_ascii=False),
        "kinds_json": json.dumps(available_kinds(manifest), ensure_ascii=False),
        "issues": "",
    }
    try:
        res = skills.run("outline_planner", providers, variables)
        planned: PlannedDeck = res.parsed
    except (ProviderError, ValueError, KeyError) as e:
        warnings.append(f"outline_planner failed, deterministic outline used: {str(e)[:160]}")
        return basic_outline(brief, facts, strategy, target), warnings
    outline = DeckOutline(title=planned.title or brief.title_hint or "Презентация", subtitle=planned.subtitle, audience=brief.audience, purpose=brief.purpose, strategy=strategy.name, language=brief.language, slides=planned.slides, facts=facts.facts, series=facts.series, tables=facts.tables)
    outline = validate_outline(outline, manifest, target, skills, providers)
    # fact check + one repair pass
    try:
        chk = skills.run("fact_checker", providers, {"outline_json": outline.model_dump_json(), "brief": brief.text, "facts_json": variables["facts_json"]})
        issues: FactCheck = chk.parsed
        errors = [i for i in issues.issues if i.severity == "error"]
        if errors:
            variables["issues"] = "\n".join(f"- слайд {i.slide_id}: {i.text}" for i in errors)
            try:
                res2 = skills.run("outline_planner", providers, variables)
                planned2: PlannedDeck = res2.parsed
                outline.slides = planned2.slides
                outline = validate_outline(outline, manifest, target, skills, providers)
                warnings.append(f"fact_checker found {len(errors)} issues; outline regenerated once")
            except (ProviderError, ValueError, KeyError) as e:
                warnings.append(f"repair pass failed: {str(e)[:120]}")
    except (ProviderError, ValueError, KeyError) as e:
        warnings.append(f"fact_checker skipped: {str(e)[:120]}")
    return outline, warnings
