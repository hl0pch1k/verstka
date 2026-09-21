"""Kind compatibility and content demands of an outline slide."""

from __future__ import annotations

from verstka.schemas.common import PatternKind as K
from verstka.schemas.outline import OutlineSlide

# outline kind → acceptable pattern kinds with a compatibility factor
KIND_FALLBACKS: dict[K, list[tuple[K, float]]] = {
    K.title: [(K.title, 1.0)],
    K.section: [(K.section, 1.0), (K.title, 0.5)],
    K.agenda: [(K.agenda, 1.0), (K.bullets, 0.6), (K.process, 0.5), (K.cards, 0.4)],
    K.bullets: [(K.bullets, 1.0), (K.two_column, 0.5), (K.cards, 0.5), (K.image_text, 0.4), (K.freeform, 0.3)],
    K.cards: [(K.cards, 1.0), (K.process, 0.6), (K.two_column, 0.5), (K.bullets, 0.4), (K.stat_row, 0.4)],
    K.two_column: [(K.two_column, 1.0), (K.comparison, 0.9), (K.cards, 0.6), (K.bullets, 0.4)],
    K.big_number: [(K.big_number, 1.0), (K.stat_row, 0.7), (K.cards, 0.4)],
    K.stat_row: [(K.stat_row, 1.0), (K.big_number, 0.6), (K.cards, 0.6)],
    K.comparison: [(K.comparison, 1.0), (K.two_column, 0.8), (K.cards, 0.6), (K.table, 0.5)],
    K.timeline: [(K.timeline, 1.0), (K.process, 0.8), (K.cards, 0.5)],
    K.process: [(K.process, 1.0), (K.timeline, 0.8), (K.cards, 0.6), (K.agenda, 0.4)],
    K.table: [(K.table, 1.0), (K.freeform, 0.5), (K.bullets, 0.3)],
    K.chart: [(K.chart, 1.0), (K.image_text, 0.6), (K.freeform, 0.5), (K.big_number, 0.3)],
    K.image_text: [(K.image_text, 1.0), (K.mockup, 0.6), (K.bullets, 0.4), (K.two_column, 0.4)],
    K.team: [(K.team, 1.0), (K.cards, 0.5)],
    K.quote: [(K.quote, 1.0), (K.section, 0.5), (K.bullets, 0.3)],
    K.code: [(K.code, 1.0), (K.bullets, 0.4)],
    K.mockup: [(K.mockup, 1.0), (K.image_text, 0.8)],
    K.thanks: [(K.thanks, 1.0), (K.section, 0.4), (K.title, 0.3)],
    K.freeform: [(K.bullets, 0.6), (K.freeform, 0.5)],
}

_ITEM_KINDS = {K.cards, K.process, K.timeline, K.team, K.comparison, K.agenda}
_NUMBER_KINDS = {K.stat_row, K.big_number}


def kind_compat(outline_kind: K, pattern_kind: K) -> float:
    for k, f in KIND_FALLBACKS.get(outline_kind, []):
        if k == pattern_kind:
            return f
    return 0.0


def needed_items(slide: OutlineSlide) -> int:
    c = slide.content
    if slide.kind in _ITEM_KINDS:
        return len(c.items) or len(c.columns) or len(c.bullets)
    if slide.kind in _NUMBER_KINDS:
        return len(c.numbers)
    if slide.kind in (K.two_column,):
        return len(c.columns) or 2
    return max(len(c.items), len(c.numbers), len(c.columns))


def needed_chars(slide: OutlineSlide) -> dict[str, int]:
    c = slide.content
    out: dict[str, int] = {"title": len(slide.headline)}
    if slide.subtitle:
        out["subtitle"] = len(slide.subtitle)
    if c.bullets and slide.kind not in _ITEM_KINDS:
        out["bullet_list"] = sum(len(b) + 2 for b in c.bullets)
    if c.paragraphs:
        out["body"] = sum(len(p) + 1 for p in c.paragraphs)
    if c.quote:
        out["body"] = max(out.get("body", 0), len(c.quote))
    items = c.items or c.columns
    if items:
        out["card_title"] = max(len(i.title) for i in items)
        out["card_body"] = max(len(i.text) + sum(len(b) + 2 for b in i.bullets) for i in items)
    if c.numbers:
        out["number"] = max(len(n.value) for n in c.numbers)
        out["number_label"] = max(len(n.label) for n in c.numbers)
    return out


def composition_for(slide: OutlineSlide) -> str:
    c = slide.content
    k = slide.kind
    if k in (K.title, K.section, K.thanks, K.bullets, K.cards, K.stat_row, K.big_number, K.two_column, K.table, K.process, K.quote, K.agenda, K.comparison):
        name = k.value
    elif k == K.chart:
        name = "chart_text"
    elif k == K.timeline:
        name = "process"
    elif k == K.team:
        name = "cards"
    elif k in (K.image_text, K.mockup):
        name = "image_text" if c.image_hint else "bullets"
    else:
        name = "bullets"
    if name == "table" and c.table is None:
        name = "bullets"
    if name == "chart_text" and c.chart is None:
        name = "bullets"
    if name in ("cards", "process", "agenda", "comparison") and not (c.items or c.columns or c.bullets):
        name = "bullets"
    if name in ("stat_row", "big_number") and not c.numbers:
        name = "bullets"
    return name
