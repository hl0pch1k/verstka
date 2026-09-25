"""Render-time guards: whatever the plan says, a slide reaches the deck with content it can show.

The planner checks its own output; these rules hold for any outline the renderer is given (defence in depth):

* a chart whose data does not resolve (the ids of facts rather than of series, an empty series) is never an empty
  frame under a unit caption: the slide shows the figures it has — its own numbers, else the facts the chart names —
  as KPI tiles or one big number, else the text it carries (bullets, paragraphs, items), else its headline as a
  statement;
* a comparison / two_column slide with a column that has nothing under its title, a cards slide of a model plan whose
  every card is a bare title (the rules planner sets short lines as title-only cards on purpose: those stay), a figure
  slide (stat_row / big_number) without figures, a table slide without rows and a content slide with no content at all
  take the same way (a slide's facts stand in for its missing figures);
* a kind with no composition of its own (freeform) is set as a list: its paragraphs, figures and items become lines;
* template stubs never reach the page: «[email]», «[телефон]», «[...]», «<имя>», «{контакт}», addresses at
  example.com / company.com, «+7 (XXX) XXX-XX-XX» — on covers and closing slides every bracketed text, elsewhere the
  stubs only — and the label a removed value leaves behind («Контакты:») goes with it. Comparison signs are no
  brackets: «ответ <5 минут, у конкурентов >10 минут» stays as written.

`prepare_slide` returns the slide as it will be rendered, the layout entry that renders it and notes for the run's
warnings. The renderer writes both back into the outline and the plan, so the audit, outline.json and layout_plan.json
describe the deck as it is.
"""

from __future__ import annotations

import re
from typing import Optional

from verstka.matching.compat import composition_for
from verstka.rendering.charts import chart_data_ok
from verstka.schemas.common import PatternKind as K
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import DeckOutline, Fact, NumberCallout, OutlineSlide, SlideContent, SlideItem

BOOKENDS = (K.title, K.section, K.thanks)
_COLUMN_KINDS = (K.comparison, K.two_column)
_CARD_KINDS = (K.cards, K.team)
_FIGURE_KINDS = (K.stat_row, K.big_number)
_FREE_KINDS = (K.freeform,)  # no composition of their own: set as a list
_PICTURE_KINDS = (K.image_text, K.mockup)
MAX_TILES = 4

# ---------------------------------------------------------------------------------------------- template stubs

_SENT = "\x00"
# «<email>», «<Имя Фамилия>»: an angle stub is words tight against its brackets, without digits or commas — else the
# signs are comparisons («ответ <5 минут, у конкурентов >10 минут» is a claim, not a stub around «5 минут, …»)
_ANGLE_STUB = r"<(?=[^\s<>])[^<>\n\d,;]{0,58}[^\s<>\d,;]>"
_BRACKETS_RE = re.compile(rf"\[[^\[\]\n]{{0,80}}\]|{_ANGLE_STUB}|\{{\{{?[^{{}}\n]{{0,60}}\}}\}}?")
_STUB_WORD_RE = re.compile(
    r"e-?mail|почт|телефон|\bтел\b|phone|\bимя\b|\bимени\b|фамили|\bфио\b|\bname\b|контакт|contact|ссылк|\blink\b|\burl\b|"
    r"сайт|\bsite\b|адрес|address|\bдата\b|\bdate\b|компани|company|должност|position|логотип|\blogo\b|подпись|текст|"
    r"\btext\b|названи|\btitle\b|описани|пример|example|цифр|\bчисл|сумм|значени|\bvalue\b|\bnumber\b|вставить|insert|"
    r"укажите|указать|уточн|placeholder|\btodo\b|\btbd\b|\btbc\b",
    re.I,
)
_FAKE_DOMAIN = (
    r"(?:example|company|yourcompany|your-company|mycompany|companyname|domain|yourdomain|email|test|sample|yoursite|"
    r"website|компания|пример)\.(?:com|ru|org|net|io|рф)\b"
)
_FAKE_ADDR_RE = re.compile(rf"[\w.+-]+@(?:[\w-]+\.)*{_FAKE_DOMAIN}|(?<![\w@.-])(?:https?://)?(?:www\.)?{_FAKE_DOMAIN}(?:/\S*)?", re.I)
_PHONE_MASK_RE = re.compile(r"(?:\+\d{1,3}\s?)?\(?[XХxх]{3}\)?[\s-]?[XХxх]{3}[\s-]?[XХxх]{2}[\s-]?[XХxх]{2}")
_SEP_RE = re.compile(r"(\s*[|•·;]\s*|,\s+|\s+/\s+|\s+[—–-]\s+)")
_SENTENCE_RE = re.compile(r"(?<=[.!?…])(?<![Тт]ел\.)(?<![Tt]el\.)\s+")
_TRAIL_PREP_RE = re.compile(r"(?:\s+(?:на|по|в|во|к|ко|с|со|у|для|через|at|to|via|on|by))+$", re.I)
_CONTACT_WORD = (
    r"(?:контакт\w*|e-?mail|почт\w*|телефон\w*|тел\.?|phone|сайт\w*|site|адрес\w*|address|связ\w*|для|пишите|"
    r"напишите|звоните|позвоните|свяжитесь|обращайтесь|нам|нами|с|и|или|us|contact\w*|write|call|email)"
)
_CONTACT_ONLY_RE = re.compile(rf"^[\s,.:;!?—–-]*(?:{_CONTACT_WORD}[\s,.:;!?—–-]*)*$", re.I)


def _is_stub(inner: str) -> bool:
    """«email», «телефон», «...», «Имя Фамилия», «+7 XXX»: what a template or a model writes where a value goes.
    A reference or a year in brackets («[1]», «[2024]») is not a stub."""
    s = inner.strip()
    if not s or not re.search(r"\w", s):
        return True
    if "@" in s or re.search(r"[XХxх]{3,}", s):
        return True
    if re.search(r"\d", s):
        return False
    return bool(_STUB_WORD_RE.search(s))


def _tidy_piece(piece: str) -> str:
    """A sentence that held a stub: the stub goes, and so does what it leaves behind — a label («Контакты:»), a
    preposition («пишите на»), a contact word alone."""
    if _SENT not in piece:
        return piece
    t = " ".join(piece.replace(_SENT, " ").split()).rstrip(" ,;")
    if t.endswith(":"):
        head = t[:-1].strip()
        return "" if len(head.split()) <= 4 else head
    t = _TRAIL_PREP_RE.sub("", t).rstrip(" ,;:—–-")
    return "" if _CONTACT_ONLY_RE.match(t) else t


def _scrub_line(line: str, all_brackets: bool) -> str:
    def bracket(m: re.Match) -> str:
        inner = m.group(0).strip("[]{}<>")
        return _SENT if (all_brackets or _is_stub(inner)) else m.group(0)

    t = _BRACKETS_RE.sub(bracket, line)
    t = _FAKE_ADDR_RE.sub(_SENT, t)
    t = _PHONE_MASK_RE.sub(_SENT, t)
    if _SENT not in t:
        return line
    parts = _SEP_RE.split(t)
    segs, seps = parts[0::2], parts[1::2]
    out = ""
    for i, seg in enumerate(segs):
        if _SENT in seg:
            pieces = _SENTENCE_RE.split(seg)
            seg = " ".join(p for p in (_tidy_piece(p) for p in pieces) if p.strip())
            if _CONTACT_ONLY_RE.match(seg):
                seg = ""
        seg = seg.strip()
        if not seg:
            continue
        out += (seps[i - 1] if out and i else "") + seg
    return out.strip()


def scrub_stubs(text: Optional[str], *, all_brackets: bool = False) -> Optional[str]:
    """`text` without template stubs (see the module docstring); lines left empty go. `all_brackets`: every bracketed
    text is a stub (a cover or a closing slide carries no references)."""
    if not text:
        return text
    lines = [_scrub_line(ln, all_brackets) for ln in text.split("\n")]
    if all(a == b for a, b in zip(lines, text.split("\n"))):
        return text
    return "\n".join(ln for ln in lines if ln.strip())


def _scrub_slide(o: OutlineSlide, outline: DeckOutline) -> tuple[OutlineSlide, bool]:
    allb = o.kind in BOOKENDS
    changed = False

    def f(s: Optional[str]) -> Optional[str]:
        nonlocal changed
        r = scrub_stubs(s, all_brackets=allb)
        if r != s:
            changed = True
        return r

    def items(xs: list[SlideItem]) -> list[SlideItem]:
        out = []
        for it in xs:
            new = it.model_copy(update={"title": f(it.title) or "", "text": f(it.text) or "", "bullets": [b for b in (f(b) for b in it.bullets) if b and b.strip()]})
            if new.title.strip() or new.text.strip() or new.bullets or (new.number or "").strip():
                out.append(new)
        return out

    c = o.content
    content = c.model_copy(
        update={
            "bullets": [b for b in (f(b) for b in c.bullets) if b and b.strip()],
            "paragraphs": [p for p in (f(p) for p in c.paragraphs) if p and p.strip()],
            "items": items(c.items),
            "columns": items(c.columns),
            "numbers": [n.model_copy(update={"label": f(n.label) or ""}) for n in c.numbers],
            "quote": f(c.quote) or None,
            "quote_author": f(c.quote_author) or None,
        }
    )
    headline = f(o.headline) or ""
    if not headline.strip():
        # a heading that was nothing but a stub: the cover takes the deck's title, any other slide keeps its words
        headline = outline.title if o.kind == K.title and outline.title else o.headline
    subtitle, section = f(o.subtitle) or None, f(o.section) or None
    if not changed:
        return o, False
    return o.model_copy(update={"headline": headline, "subtitle": subtitle, "section": section, "content": content}), True


# ---------------------------------------------------------------------------------------------- figures from facts

_NO_PERCENT_RE = re.compile(r"\b(?:e?NPS|CSI)\b|индекс", re.I)


def _with_unit(value: str, unit: Optional[str], label: str) -> str:
    v, u = (value or "").strip(), (unit or "").strip()
    if not u or u.lower() in v.lower():
        return v
    if u.startswith("%"):
        return v if _NO_PERCENT_RE.search(label or "") else v + u  # NPS is an index, not a share
    return f"{v} {u}"


def _norm(s: Optional[str]) -> str:
    return " ".join((s or "").lower().replace("ё", "е").split())


def fact_numbers(o: OutlineSlide, outline: DeckOutline, *, chart_only: bool = False, limit: int = MAX_TILES) -> list[NumberCallout]:
    """The figures a slide names by fact id — the chart's `series_ids` first, then its `fact_refs` (unless
    `chart_only`) — as callouts with their units. Two facts of one label and unit are one change, in the order the
    slide names them («47 → 29 минут»): a chart of the two would show the same."""
    ids = list(o.content.chart.series_ids) if o.content.chart is not None else []
    if not chart_only:
        ids += list(o.fact_refs)
    facts: list[Fact] = []
    for fid in ids:
        fact = outline.fact_by_id(fid)
        if fact is not None and fact not in facts and re.search(r"\d", fact.value or ""):
            facts.append(fact)
    groups: dict[tuple[str, str], list[Fact]] = {}
    for fact in facts:
        groups.setdefault((_norm(fact.label), _norm(fact.unit)), []).append(fact)
    out: list[NumberCallout] = []
    for group in groups.values():
        if len(group) == 2 and _norm(group[0].value) != _norm(group[1].value):
            a, b = group
            first = _with_unit(a.value, a.unit, a.label) if (b.unit or "").strip().startswith("%") else a.value.strip()
            out.append(NumberCallout(value=f"{first} → {_with_unit(b.value, b.unit, b.label)}", label=a.label, fact_id=b.id))
        else:
            seen: set[str] = set()
            for fact in group:
                if _norm(fact.value) not in seen:
                    seen.add(_norm(fact.value))
                    out.append(NumberCallout(value=_with_unit(fact.value, fact.unit, fact.label), label=fact.label, fact_id=fact.id))
    return out[:limit]


# ---------------------------------------------------------------------------------------------- substitutes


def _bare(it: SlideItem) -> bool:
    """A card or a column with nothing under a short title («NPS», «Фаза 2»): a name over an empty frame."""
    hollow = not (it.text.strip() or any(b.strip() for b in it.bullets) or (it.number or "").strip())
    return hollow and len(it.title.split()) <= 5 and len(it.title) <= 48


def _item_line(it: SlideItem) -> str:
    body = it.text.strip() or "; ".join(b.strip() for b in it.bullets if b.strip())
    head = " ".join(x for x in ((it.number or "").strip(), it.title.strip()) if x)
    return f"{head} — {body}" if head and body else (head or body)


def _number_line(n: NumberCallout, outline: DeckOutline) -> str:
    fact = outline.fact_by_id(n.fact_id) if n.fact_id else None
    label = n.label.strip()
    value = n.value.strip()
    if fact is not None and fact.unit and fact.unit.strip().lower() not in (value + " " + label).lower():
        value = _with_unit(value, fact.unit, label)
    if not label:
        return value
    unitish = bool(re.match(r"^(?:%|₽|\$|€|×|тыс|млн|млрд|руб|шт|чел|мин|час|ч\b|дн|мес|лет|год|раз)", label, re.I))
    return f"{value}{'' if label.startswith('%') else ' '}{label}" if unitish else f"{value} — {label}"


def _substitute(o: OutlineSlide, outline: DeckOutline, *, chart_facts: bool) -> tuple[OutlineSlide, str]:
    """The slide rebuilt from what it carries: its figures (its own numbers, else the facts its chart names) as tiles
    or one big number, else its text as a list, else its cards, else the facts it refers to, else the titles of its
    bare cards as a list, else its headline alone — a statement."""
    c = o.content
    bullets = [b for b in c.bullets if b.strip()]
    paragraphs = [p for p in c.paragraphs if p.strip()]
    all_items = list(c.items or c.columns)
    items = [it for it in all_items if not _bare(it)]
    numbers = list(c.numbers) or (fact_numbers(o, outline, chart_only=True) if chart_facts else [])
    if not numbers and not (bullets or paragraphs or items):
        numbers = fact_numbers(o, outline)
    if numbers:
        numbers = numbers[:MAX_TILES]
        kind = K.big_number if len(numbers) == 1 else K.stat_row
        content = SlideContent(numbers=numbers, bullets=bullets + [_item_line(it) for it in items], paragraphs=paragraphs)
        how = "one big number" if len(numbers) == 1 else f"{len(numbers)} KPI tiles"
    elif items:
        kind, content, how = K.cards, SlideContent(items=items, bullets=bullets, paragraphs=paragraphs), "cards"
    elif bullets or paragraphs:
        kind, content, how = K.bullets, SlideContent(bullets=bullets, paragraphs=paragraphs), "bullets"
    elif len(titles := [it.title.strip() for it in all_items if it.title.strip()]) >= 2:
        kind, content, how = K.bullets, SlideContent(bullets=titles), "a list of its item titles"
    else:
        kind, content, how = K.section, SlideContent(), "a statement of its headline"
    content.image_hint = c.image_hint
    return o.model_copy(update={"kind": kind, "content": content}), how


def _as_list(o: OutlineSlide, outline: DeckOutline) -> OutlineSlide:
    """A freeform slide as bullets: its figures and items become lines of the list (a lone paragraph stays one)."""
    c = o.content
    extra = [_number_line(n, outline) for n in c.numbers] + [_item_line(it) for it in list(c.items) + list(c.columns)]
    extra = [t for t in extra if t.strip()]
    if extra or c.bullets:
        content = SlideContent(bullets=[p for p in c.paragraphs if p.strip()] + [b for b in c.bullets if b.strip()] + extra)
    else:
        content = SlideContent(paragraphs=list(c.paragraphs), quote=c.quote, quote_author=c.quote_author)
    content.table, content.chart, content.image_hint = c.table, c.chart, c.image_hint
    return o.model_copy(update={"kind": K.bullets, "content": content})


def _model_plan(outline: DeckOutline) -> bool:
    """A model wrote the plan (its own or another variant's, reshaped): it was asked for cards with text under their
    titles, so cards that are titles alone lost their text. The rules planner sets a list of short lines as title-only
    cards on purpose (programme modules, parts of a whole) — those stay cards."""
    by = outline.planned_by or ""
    return by == "model" or by.startswith("shared:")


def _has_body(c: SlideContent, *, chart: bool = True) -> bool:
    return bool(c.bullets or c.paragraphs or c.items or c.columns or c.numbers or c.table is not None or c.quote or (chart and c.chart is not None))


def prepare_slide(o: OutlineSlide, ps: LayoutSlide, outline: DeckOutline) -> tuple[OutlineSlide, LayoutSlide, list[str]]:
    """The slide as the renderer will set it, the layout entry that sets it and what was changed (for the run's
    warnings). Unchanged input comes back as the same objects."""
    notes: list[str] = []
    s, scrubbed = _scrub_slide(o, outline)
    if scrubbed:
        notes.append("template stubs removed from the text ([email], [телефон], …)")
    c = s.content
    why: Optional[str] = None
    replan = False
    chart_facts = False
    if c.chart is not None and not chart_data_ok(c.chart, outline):
        ids = ", ".join(c.chart.series_ids) or "none"
        if s.kind == K.chart or not _has_body(c, chart=False):
            why, chart_facts = f"chart has no series data (ids: {ids})", True
        else:
            s = s.model_copy(update={"content": c.model_copy(update={"chart": None})})
            notes.append(f"chart dropped: no series data (ids: {ids})")
            replan = True
    elif s.kind == K.chart and c.chart is None:
        why = "chart slide without a chart"
    c = s.content
    if why is None:
        cols = list(c.items or c.columns)
        field = "items" if c.items else "columns"
        if s.kind == K.table and (c.table is None or not c.table.rows):
            why = "table slide without rows"
        elif s.kind in _COLUMN_KINDS and cols and any(_bare(it) for it in cols):
            full = [it for it in cols if not _bare(it)]
            if len(full) >= 2:
                s = s.model_copy(update={"content": c.model_copy(update={field: full})})
                notes.append(f"{len(cols) - len(full)} empty column(s) dropped")
            else:
                why = f"{s.kind.value} columns have nothing under their titles"
        elif s.kind in _CARD_KINDS and cols and all(_bare(it) for it in cols) and _model_plan(outline):
            why = "every card is a bare title"
        elif s.kind in _FIGURE_KINDS and not c.numbers:
            why = "figure slide without figures"
        elif s.kind in _FREE_KINDS:
            s = _as_list(s, outline)
            notes.append(f"kind «{o.kind.value}» has no composition of its own: set as bullets")
            replan = True
        elif s.kind not in BOOKENDS + (K.quote,) and not _has_body(c) and not (s.kind in _PICTURE_KINDS and c.image_hint):
            why = "no content"
    if why is not None:
        s, how = _substitute(s, outline, chart_facts=chart_facts)
        notes.append(f"{why}: shown as {how}")
        replan = True
    if replan:
        comp = composition_for(s)
        ps = LayoutSlide(
            outline_id=s.id,
            mode="synth",
            composition=comp,
            fit=ps.fit,
            score=ps.score,
            reasons=list(ps.reasons) + [f"при вёрстке: {notes[-1]} → композиция {comp}"],
            alternatives=list(ps.alternatives),
        )
    return s, ps, notes


def fallback_composition(o: OutlineSlide, ps: LayoutSlide) -> str:
    """The composition a slide falls back to when its planned rendering failed."""
    return ps.composition or composition_for(o)

