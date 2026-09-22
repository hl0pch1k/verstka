"""plan_outline: brief → DeckOutline (LLM skills with a deterministic fallback) + validation."""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from verstka.planning import heuristics as H
from verstka.planning.condense import condense_text
from verstka.planning.strategies import Strategy
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import Brief, ChartSpec, DeckOutline, FactCheck, FactsExtraction, NumberCallout, OutlineSlide, PlannedDeck, SlideContent, SlideItem
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


_STEP_TITLES_RE = re.compile(r"шаг|этап|план|дорожн|roadmap|запуск|timeline|сроки|следующ", re.I)
_CLOSING_RE = re.compile(r"вывод|итог|решени|просим|предлагаем утвердить|summary|conclusion|next steps", re.I)


@dataclass
class _Block:
    """One slide candidate cut from a brief section."""
    kind: PatternKind
    headline: str
    section: str
    content: SlideContent
    role: str  # text, items, steps, kpi, chart, table
    fact_refs: list[str] = field(default_factory=list)
    subtitle: Optional[str] = None
    notes: str = ""
    kpis: list = field(default_factory=list)


def _fact_id(facts: FactsExtraction, value: str) -> Optional[str]:
    digits = re.sub(r"\D", "", value)
    for f in facts.facts:
        if digits and re.sub(r"\D", "", f.value) and re.sub(r"\D", "", f.value) in digits:
            return f.id
    return None


def _headline(sentences: list[str], fallback: str, max_words: int = 11) -> str:
    """A slide heading is a conclusion: the first statement of the section, not its topic word; a statement with a
    colon is headed by what precedes the colon («Рынку не хватает инженеров данных: …»)."""
    for s in sentences:
        if len(s.split()) < 3:
            continue
        head = s.split(":", 1)[0] if ":" in s and len(s.split(":", 1)[0].split()) >= 3 else s
        return H.short(head, max_words)
    return fallback


def _attach(block: "_Block", extra: list[str]) -> None:
    """Sentences left over next to cards or steps: the first short one is the slide's subtitle, the rest go to the
    speaker notes — nothing from the brief is silently dropped, and no slide is made of one stray bullet."""
    extra = [H.strip_end(x) for x in extra if x.strip()]
    if not extra:
        return
    if block.subtitle is None and len(extra[0].split()) <= 20:
        block.subtitle = extra.pop(0)
    if extra:
        block.notes = (block.notes + "\n" if block.notes else "") + " ".join(e + "." for e in extra)


def _blocks_of(sec: H.Section, facts: FactsExtraction, series_by_span: dict, closing: bool) -> list[_Block]:
    out: list[_Block] = []
    title = sec.title or ""
    sentences = list(sec.sentences)
    steps, rest = H.steps_of(sentences)
    labelled, rest = H.labelled_items(rest) if not steps else ([], rest)
    enum_lead, enum_parts, enum_src = None, [], None
    if not steps and not labelled:
        for sn in rest:
            lead, parts = H.enumeration(sn)
            if len(parts) >= 3:
                enum_lead, enum_parts, enum_src = lead, parts, sn
                break
    kpis = [k for sn in rest if sn != enum_src for k in H.kpis_of(sn)]
    kpi_sentences = {k.sentence for k in kpis}
    if steps:
        statements = [r for r in rest if ":" not in r and len(r.split()) >= 3]
        head = H.short(statements[0], 11) if statements else title
        blk = _Block(PatternKind.process, head, title, SlideContent(items=[SlideItem(title=i.title, text=i.text) for i in steps[:6]]), "steps")
        out.append(blk)
        _attach(blk, [r for r in rest if not statements or r != statements[0]])
        rest = []
    elif labelled:
        kind = PatternKind.two_column if len(labelled) == 2 else PatternKind.cards
        items = [SlideItem(title=i.title, text=i.text) for i in labelled[:6]]
        content = SlideContent(columns=items) if kind == PatternKind.two_column else SlideContent(items=items)
        out.append(_Block(kind, _headline(rest, title), title, content, "items"))
        rest = []
    elif enum_parts:
        as_steps = bool(_STEP_TITLES_RE.search(title)) and not enum_lead
        kind = PatternKind.process if as_steps else PatternKind.cards
        head = H.short(enum_lead, 11) if enum_lead and len(enum_lead.split()) >= 2 else (title or _headline(rest, title))
        others = [r for r in rest if r != enum_src and r not in kpi_sentences]
        content = SlideContent(items=[SlideItem(title=H.short(p, 9)) for p in enum_parts[:6]])
        blk = _Block(kind, head, title, content, "steps" if as_steps else "items")
        out.append(blk)
        if len(others) <= 2:
            _attach(blk, others)
            rest = []
        else:
            rest = others
    # figures: three or more in a section make a KPI row; fewer stay in the text
    if len(kpis) >= 2 and len(kpi_sentences) >= 2 or len(kpis) >= 3:
        head_sentence = kpis[0].sentence
        tiles = [k for k in kpis if k.sentence != head_sentence]
        if len(tiles) < 3:
            tiles = kpis
        tiles = tiles[:4]
        nums = [NumberCallout(value=k.value, label=k.label, fact_id=_fact_id(facts, k.value)) for k in tiles]
        head = _headline([head_sentence], title)
        blk = _Block(PatternKind.stat_row, head, title, SlideContent(numbers=nums), "kpi", [n.fact_id for n in nums if n.fact_id], kpis=kpis)
        if len(kpis) < 3:
            blk.role = "kpi_small"  # two figures: a KPI row for the visual strategy, running text for the others
        out.append(blk)
        rest = [r for r in rest if r not in kpi_sentences] if blk.role == "kpi" else rest
    for tbl, lead in zip(sec.tables, sec.table_leads):
        series, chart_type = series_by_span.get(tbl.source_span, ([], None))
        if series:
            head = H.series_headline(series[0]) if chart_type == "column" else None
            tot = H.totals_of(tbl)
            if head is None and tot and len(tot[1]) >= 2:
                unit = tbl.columns[0].split(",", 1)[1].strip() if "," in tbl.columns[0] else ""
                head = f"{title or tot[0]}: {tot[1][0]} → {tot[1][1]} {unit}".strip()
            spec = ChartSpec(type=chart_type or "column", series_ids=[x.id for x in series], unit=series[0].unit, highlight_index=len(series[0].values) - 1 if chart_type == "column" else None)
            out.append(_Block(PatternKind.chart, head or lead or title, title, SlideContent(chart=spec), "chart"))
            out[-1].content.table = tbl  # kept for strategies that prefer the table
        else:
            out.append(_Block(PatternKind.table, lead or (f"{title}: сравнение" if title else "Сравнение"), title, SlideContent(table=tbl), "table"))
    # what is left is running text: a thesis slide, headed by its first statement
    rest = [r for r in rest if r.strip()]
    if rest:
        if len(rest) == 1 and out:
            first = out[0]
            if not first.content.paragraphs and len(rest[0].split()) <= 20:
                first.content.paragraphs = [H.strip_end(rest[0])]
                rest = []
        if rest:
            head = _headline(rest, title) if len(rest) >= 2 else (title or H.short(rest[0], 11))
            body = []
            for r in rest:
                if H.short(r, 11) == head:
                    continue
                if ":" in r and H.short(r.split(":", 1)[0], 11) == head:
                    body.append(H.cap_first(H.strip_end(r.split(":", 1)[1].strip())))  # the heading took the part before the colon
                    continue
                body.append(H.strip_end(r))
            if not body:
                body = [H.strip_end(rest[0])]
                head = title or head
            kind = PatternKind.bullets
            content = SlideContent(bullets=body) if len(body) >= 2 else SlideContent(paragraphs=body)
            out.insert(0 if not closing else len(out), _Block(kind, head, title, content, "text"))
    # two figures inside running text: the text slide stays, the small KPI row is only offered to «visual»
    return out


def _to_cards(b: _Block) -> _Block:
    """Visual strategy: two to four theses become cards with short titles instead of a bulleted list."""
    lines = b.content.bullets or b.content.paragraphs
    if b.kind != PatternKind.bullets or not (2 <= len(lines) <= 4):
        return b
    items = [SlideItem(title=H.short(l, 9), icon_hint=H.short(l, 2)) for l in lines]
    return _Block(PatternKind.cards, b.headline, b.section, SlideContent(items=items), "items", b.fact_refs)


def _two_column(a: _Block, b: _Block) -> _Block:
    """Compact strategy: two neighbouring text sections share one slide."""
    def col(x: _Block) -> SlideItem:
        lines = x.content.bullets or x.content.paragraphs or [i.title for i in x.content.items]
        if x.content.items and x.headline and x.headline != x.section:
            return SlideItem(title=x.headline, bullets=[H.short(l, 12) for l in lines[:4]])
        return SlideItem(title=x.section or x.headline, bullets=[H.short(l, 12) for l in lines[:4]])
    head = f"{a.section or a.headline} и {b.section[:1].lower() + b.section[1:] if b.section else b.headline}" if a.section and b.section else a.headline
    return _Block(PatternKind.two_column, head, a.section, SlideContent(columns=[col(a), col(b)]), "text")


def basic_outline(brief: Brief, facts: FactsExtraction, strategy: Strategy, target: int) -> DeckOutline:
    """Deterministic planner: read the brief's sections into typed slides (steps → process, «X: …» → cards,
    figures → KPI row, tables → chart or table, the rest → theses headed by a conclusion), then assemble them the
    way the strategy asks — structured (agenda, one idea per slide), visual (key figure first, cards, charts),
    compact (paired text sections, tables)."""
    doc_title, sections = H.parse_sections(brief.text)
    title = brief.title_hint or doc_title or "Презентация"
    series_by_span: dict = {}
    k = len(facts.series)
    for sec in sections:
        for tbl in sec.tables:
            existing = [x for x in facts.series if x.source_span == tbl.source_span]
            if existing:
                ctype = "column" if len(existing) == 1 and len(existing[0].values) >= 3 and len(tbl.rows) == 1 else "bar"
                series_by_span[tbl.source_span] = (existing, ctype)
                continue
            ss, ctype = H.table_series(tbl, start_id=k + 1)
            if ss:
                facts.series.extend(ss)
                k += len(ss)
                series_by_span[tbl.source_span] = (ss, ctype)
            if not any(t.source_span == tbl.source_span for t in facts.tables):
                facts.tables.append(tbl)
    blocks: list[_Block] = []
    for i, sec in enumerate(sections):
        closing = i == len(sections) - 1 and bool(_CLOSING_RE.search(sec.title or ""))
        blocks.extend(_blocks_of(sec, facts, series_by_span, closing))
    # the deck's key figure: a change «с A до B» anywhere, else the first figure of the last KPI row (results come last)
    key_kpi = next((k for sec in sections for sn in sec.sentences for k in H.kpis_of(sn) if "→" in k.value), None)
    if key_kpi is None:
        kb = next((b for b in reversed(blocks) if b.role == "kpi"), None)
        if kb and kb.kpis:
            key_kpi = kb.kpis[0]
    name = strategy.name
    if name == "visual":
        for b in blocks:
            if b.role == "kpi_small":
                b.role = "kpi"
    else:
        blocks = [b for b in blocks if b.role != "kpi_small"]
    if name == "visual":
        blocks = [_to_cards(b) for b in blocks]
        blocks = [b for b in blocks if not (b.role == "table" and any(x.role == "chart" for x in blocks if x.section == b.section))]
        for b in blocks:
            if b.kind == PatternKind.chart:
                b.content.table = None
        if key_kpi is not None:
            summary = _Block(PatternKind.big_number, H.short(key_kpi.sentence, 11), "", SlideContent(numbers=[NumberCallout(value=key_kpi.value, label=key_kpi.label, fact_id=_fact_id(facts, key_kpi.value))]), "kpi")
            blocks.insert(0, summary)
    elif name == "compact":
        merged: list[_Block] = []
        floor = 8 - 2  # title and thanks come on top: a compact deck still has at least eight slides
        for idx, b in enumerate(blocks):
            if b.kind == PatternKind.chart and b.content.table is not None and b.content.chart and b.content.chart.type == "bar":
                b = _Block(PatternKind.table, b.headline, b.section, SlideContent(table=b.content.table), "table")  # a comparison reads denser as a table
            elif b.kind == PatternKind.chart:
                b.content.table = None
            prev = merged[-1] if merged else None
            remaining = len(blocks) - idx - 1
            if prev is not None and len(merged) + remaining >= floor and b.role in ("text", "items") and prev.role in ("text", "items") and prev.kind in (PatternKind.bullets, PatternKind.cards) and b.kind in (PatternKind.bullets, PatternKind.cards) and b.section != prev.section and not getattr(prev, "merged", False):
                merged[-1] = _two_column(prev, b)
                merged[-1].merged = True  # type: ignore[attr-defined]
                continue
            merged.append(b)
        blocks = merged
    else:
        for b in blocks:
            if b.kind == PatternKind.chart and b.content.chart and b.content.chart.type == "bar" and b.content.table is not None:
                b.kind, b.content = PatternKind.table, SlideContent(table=b.content.table)  # structured: exact figures
            elif b.kind == PatternKind.chart:
                b.content.table = None
    slides: list[OutlineSlide] = [OutlineSlide(id="sl1", kind=PatternKind.title, headline=title, subtitle=brief.audience or None)]
    if name == "structured" and len(sections) >= 3:
        agenda_items = [SlideItem(title=sec.title) for sec in sections if sec.title][:6]
        slides.append(OutlineSlide(id="sl2", kind=PatternKind.agenda, headline="О чём поговорим", content=SlideContent(items=agenda_items)))
    for b in blocks:
        slides.append(OutlineSlide(id=f"sl{len(slides) + 1}", kind=b.kind, section=b.section or None, headline=b.headline, subtitle=b.subtitle, content=b.content, notes=b.notes, fact_refs=b.fact_refs))
    slides.append(OutlineSlide(id=f"sl{len(slides) + 1}", kind=PatternKind.thanks, headline="Спасибо за внимание", subtitle=None))
    outline = DeckOutline(title=title, subtitle=brief.audience, audience=brief.audience, purpose=brief.purpose, strategy=strategy.name, language=brief.language, slides=slides, facts=facts.facts, series=facts.series, tables=facts.tables)
    return validate_outline(outline, None, target, hard_limit=bool(brief.slide_count))


# ------------------------------------------------------------------ validation

# Which slides go first when the deck is longer than the target: structure first, text next, data (charts, tables, KPI rows) last.
_DROP_PRIORITY = {PatternKind.section: 0, PatternKind.quote: 1, PatternKind.agenda: 2, PatternKind.bullets: 3}
_DATA_KINDS = {PatternKind.chart, PatternKind.table, PatternKind.stat_row}


def _drop_priority(s: OutlineSlide) -> int:
    return 6 if s.kind in _DATA_KINDS else _DROP_PRIORITY.get(s.kind, 5)


def _drop_key(slides: list[OutlineSlide], s: OutlineSlide) -> tuple[int, int, int]:
    """Lower sorts first: priority, then (bullets slides only) the fewest bullets, then the later slide."""
    n_bullets = len(s.content.bullets) if s.kind == PatternKind.bullets else 0
    return (_drop_priority(s), n_bullets, -slides.index(s))


def _merge_into_previous(slides: list[OutlineSlide], victim: OutlineSlide) -> bool:
    """Move a bullets slide's bullets into the nearest earlier bullets slide that has room (keeps the content, loses the slide)."""
    if victim.kind != PatternKind.bullets or not victim.content.bullets:
        return False
    idx = slides.index(victim)
    for prev in reversed(slides[1:idx]):
        if prev.kind == PatternKind.bullets and len(prev.content.bullets) + len(victim.content.bullets) <= MAX_BULLETS:
            prev.content.bullets.extend(victim.content.bullets)
            prev.notes = (prev.notes + "\n" if prev.notes else "") + f"Объединено со слайдом «{victim.headline}»"
            return True
    return False


def validate_outline(
    outline: DeckOutline,
    manifest: Optional[TemplateManifest],
    target: int,
    skills: Optional[SkillsRegistry] = None,
    providers: Optional[ProviderRegistry] = None,
    hard_limit: bool = False,
) -> DeckOutline:
    """Normalise density and structure; trim to `target` (+1 tolerance) or, when the brief fixed the count (`hard_limit`), to exactly `target`."""
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
    # count: drop low-priority slides beyond the limit; small bullets slides are merged into a neighbour before anything is lost
    limit = target if hard_limit else target + 1
    while len(slides) > limit:
        candidates = slides[1:-1]
        if not candidates:
            break
        victim = min(candidates, key=lambda s: _drop_key(slides, s))
        if _merge_into_previous(slides, victim):
            slides.remove(victim)
            continue
        if not hard_limit and _drop_priority(victim) >= 3 and len(slides) <= target + 2:
            break  # soft target: keep real content rather than lose it for one slide
        slides.remove(victim)
    # unique headlines
    seen: Counter = Counter()
    for s in slides:
        seen[s.headline] += 1
        if seen[s.headline] > 1 and s.section and s.section not in seen:
            s.headline = s.section  # a repeated statement gives way to the topic of its section
            seen[s.headline] += 1
        elif seen[s.headline] > 1 and s.section:
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
    hard_limit = bool(brief.slide_count)  # «не более N слайдов» / slides: N in the brief is binding
    outline = DeckOutline(title=planned.title or brief.title_hint or "Презентация", subtitle=planned.subtitle, audience=brief.audience, purpose=brief.purpose, strategy=strategy.name, language=brief.language, slides=planned.slides, facts=facts.facts, series=facts.series, tables=facts.tables)
    outline = validate_outline(outline, manifest, target, skills, providers, hard_limit=hard_limit)
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
                outline = validate_outline(outline, manifest, target, skills, providers, hard_limit=hard_limit)
                warnings.append(f"fact_checker found {len(errors)} issues; outline regenerated once")
            except (ProviderError, ValueError, KeyError) as e:
                warnings.append(f"repair pass failed: {str(e)[:120]}")
    except (ProviderError, ValueError, KeyError) as e:
        warnings.append(f"fact_checker skipped: {str(e)[:120]}")
    return outline, warnings
