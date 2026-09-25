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
from verstka.planning.grounding import BriefIndex, ground_outline
from verstka.planning.plan_json import retype_frames
from verstka.planning.strategies import Strategy
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import PatternKind
from verstka.ru import ru_count
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
# a section that asks for something: said as one statement, not cut into figures. The name is the ask word alone
# («Просим», «Что нужно», «Запрос») or an ask verb with its object («Просим утвердить»); a noun with words of its own
# («Запрос пользователей», «Предложение для клиентов», «Нужна интеграция с 1С») names a topic, and asks only when its
# text asks (_asks_by_text)
_ASK_TITLE_RE = re.compile(
    r"^(?:(?P<what>что)\s+|(?:наш[аеи]?|мо[йяеи])\s+)?(?P<word>просим|прошу|предлагаем|предложение|нужн[оаы]|требуется|решение|запрос|ask|request|proposal)(?![\wё])(?P<tail>.*)$",
    re.I,
)
_ASK_VERB_WORDS = ("просим", "прошу", "предлагаем")
# «предлагаем» asks only with what it asks for («предлагаем утвердить», «предлагаем бюджет …»), not in «предлагаем бот,
# который экономит …»
_ASK_VERB_RE = re.compile(
    r"(?<![\wё])(?:(?:просим|прошу|утверди(?:ть|те)|одобри(?:ть|те)|выдели(?:ть|те)|согласовать|согласуйте)(?![\wё])"
    r"|предлагаем\s+(?:утверди|одобри|выдели|согласова|бюджет|инвестиц|финансирова))",
    re.I,
)
_MONEY_RE = re.compile(r"\d\s*(?:млн|млрд|тыс\.?)?\s*(?:₽|руб|\$|€|долл|евро)", re.I)
_ASK_NOUN_RE = re.compile(r"(?<![\wё])(бюджет\w*|инвестици\w*|финансировани\w*)", re.I)
_REACHED_RE = re.compile(r"(?<![\wё])до\s+\d", re.I)  # «снизился до 3 млн ₽»: a level reached, not an amount asked for
# «увеличить бюджет до 14,5 млн ₽»: an infinitive before «до N» asks for the level (a reflexive «увеличиться» does not)
_INFINITIVE_RE = re.compile(r"(?<![\wё])[а-яё]{3,}(?:ить|ать|ять|еть|уть|ести|асти)(?![\wё])", re.I)
_NOT_INFINITIVES = {"память", "печать", "кровать"}
# «Нужен бюджет 14,5 млн ₽ на масштабирование», «Требуется 2 млн ₽»: a need said with money asks for it
_NEED_RE = re.compile(r"^(?:нам\s+|ещё\s+|еще\s+)?(?:нуж(?:ен|на|но|ны)|требу(?:ется|ются))(?![\wё])", re.I)
# a short brief is cut into one section per labelled line and read figure by figure (_short_mode)
SHORT_BRIEF_SENTENCES = 6
ASK_STATEMENT_CHARS = 200  # two ask lines up to this long are said as one statement


def _is_ask(title: str, text: str) -> bool:
    """A request to the audience: a statement that opens with «Просим …», or a section named «Просим», «Предлагаем»,
    «Что нужно», «Запрос». «Решение» is an ask only when it asks (просим, утвердить, выделить …) or names money for a
    budget («бюджет 3 млн ₽»); in «Проблема / Решение / Результаты» it is the solution, and its figure gets a figure
    slide («бот экономит 2 млн ₽ в год»)."""
    s = text.strip()
    return bool(H._ASK_RE.match(s)) or bool(_NEED_RE.match(s) and (_MONEY_RE.search(s) or _asks_by_text(s))) or _ask_title(title, text)


def _reached(text: str) -> bool:
    """A level reached («бюджет поддержки снизился до 3 млн ₽», «расходы сократятся до 8 млн ₽»), not one asked for
    («увеличить бюджет до 14,5 млн ₽»: an infinitive before «до N»)."""
    if H._UP_RE.search(text) or H._DOWN_RE.search(text):
        return True
    m = _REACHED_RE.search(text)
    if m is None:
        return False
    return not any(w.group(0).lower() not in _NOT_INFINITIVES for w in _INFINITIVE_RE.finditer(text[: m.start()]))


def _asks_by_text(text: str) -> bool:
    """The text asks: an ask verb («выделить», «утвердить», «предлагаем утвердить»), or money for a budget («бюджет
    14,5 млн ₽», «увеличить бюджет до 14,5 млн ₽») — not a result said in money («бюджет поддержки снизился до 3 млн
    ₽»)."""
    if _ASK_VERB_RE.search(text):
        return True
    return bool(_ASK_NOUN_RE.search(text) and _MONEY_RE.search(text) and not _reached(text))


def _ask_name(title: str):
    """The ask word of a section's name («Просим», «Что нужно», «Запрос», «Решение»), or None."""
    return _ASK_TITLE_RE.match(H.strip_end(title or ""))


def _ask_title(title: str, text: str) -> bool:
    """The section's name asks: the ask word alone («Просим», «Предлагаем», «Что нужно», «Запрос»), «что …» or an ask
    verb with its object («Просим утвердить»). «Решение», and a noun with words of its own («Запрос пользователей»,
    «Нужна интеграция с 1С»), only when the text asks too (_asks_by_text)."""
    m = _ask_name(title)
    if not m:
        return False
    word, tail = m.group("word").lower(), m.group("tail").strip()
    if not word.startswith("решени") and (not tail or m.group("what") or word in _ASK_VERB_WORDS):
        return True
    return _asks_by_text(f"{tail} {text}")


def _ask_line(sentence: str, title: str = "") -> bool:
    """A sentence that asks: «Просим одобрить …», a labelled line «Предлагаем: …», «Что нужно: …», «Запрос: …»,
    «Решение: выделить …», or any sentence of a section named so (_is_ask)."""
    s = sentence.strip()
    if _is_ask(title, s):
        return True
    m = H._LABELLED_RE.match(s)
    return bool(m and len(m.group("label").split()) <= 4 and _ask_title(H.strip_end(m.group("label")), m.group("text")))


def _asking_section(title: str) -> bool:
    """A section that is all ask by its name («Просим», «Что просим», «Предлагаем»); «Решение» is not one — an ask said
    inside it is taken out into a section of its own — nor is a topic named by an ask noun («Запрос пользователей»)."""
    m = _ask_name(title)
    if not m or m.group("word").lower().startswith("решени"):
        return False
    return not m.group("tail").strip() or bool(m.group("what")) or m.group("word").lower() in _ASK_VERB_WORDS


def _ask_section(sec: H.Section) -> bool:
    """A short brief's section that is one ask as a whole: named so («Просим», «Что просим», «Запрос»), or a «Решение»
    whose lines ask («Решение:» / «- выделить бюджет 14,5 млн ₽» / «- утвердить срок 3 месяца»). Every slide of it is
    the ask, kept to the last; none of its figures is a tile or the deck's key figure."""
    return _asking_section(sec.title) or bool(sec.title and sec.sentences and _ask_title(sec.title, " ".join(sec.sentences)))


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


def _headline(sentences: list[str], fallback: str, max_words: int = 12) -> str:
    """A slide heading is a conclusion: the first statement of the section, not its topic word; a statement with a
    colon is headed by what precedes the colon («Рынку не хватает инженеров данных: …»). A long statement is cut at a
    clause boundary, never in the middle of a phrase («… в фирменный»)."""
    for s in sentences:
        if len(s.split()) < 3:
            continue
        parts = H.label_split(s)  # a colon between digits («в 10:30») is not where a statement ends
        head = parts[0] if parts and len(parts[0].split()) >= 3 else s
        words = head.split()
        if len(words) <= max_words:
            return H.strip_end(head)
        cut = " ".join(words[:max_words])
        bounds = [m.start() for m in re.finditer(r"[,;—–]\s", cut)]
        # a clause that ends on a pointer («на то, чтобы …», «так, что …») is not a statement on its own
        bounds = [b for b in bounds if len(cut[:b].split()) >= 5 and cut[:b].split()[-1].lower() not in {"то", "так", "том", "тем", "это", "там", "тогда"}]
        if bounds:
            return H.strip_end(cut[: bounds[-1]])
        return H.strip_end(head) if len(words) <= max_words + 4 else H.short(head, max_words)
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


def _table_head(title: str, tbl) -> str:
    """A table slide's heading when the brief gives none: the section's topic said as a comparison — «Результаты
    пилота: до и после», and «Сравнение вариантов» as it is (not «Сравнение вариантов: сравнение»)."""
    if not title:
        return "Сравнение"
    if "сравн" in title.lower():
        return title
    cols = " ".join(tbl.columns).lower()
    if re.search(r"\bдо\b", cols) and "после" in cols:
        return f"{title}: до и после"
    return f"{title}: сравнение"


_FIGURE_TOKEN_RE = re.compile(r"^[+\-−×]?\d[\d\s.,]*%?$")


def _only_the_figure(k: H.Kpi) -> bool:
    """«25 млн ₽» labelled «25 млн ₽», «3 мес» labelled «3 месяца»: the label says nothing but the figure itself."""
    vals = [t.lower() for t in k.value.split()]
    rest = [t for t in k.label.split() if not (_FIGURE_TOKEN_RE.match(t) or H._UNIT_WORD_RE.match(t) or any(v and t.lower().startswith(v) for v in vals))]
    return not rest


def _own_label(k: H.Kpi, text: Optional[str] = None) -> str:
    """A tile's label read against the figure's own clause, so it never repeats its own figure: «Команда выросла до 40
    человек» → «40 | человек» (basic_outline then fits every label of a short brief to its slide's heading). `text` is
    the brief: it tells a common first word from a name (H.label_beside)."""
    return H.label_beside(k.value, k.label, H.cap_first(k.clause or H.strip_end(k.sentence)), text)


def _one_sentence_block(sec: H.Section, facts: FactsExtraction, kpis_for, enum_parts: list[str], text: Optional[str] = None) -> Optional[_Block]:
    """A section of one sentence (a labelled line «Проблема: …» of a short brief) is one slide of its own: an ask
    («Просим», «Предлагаем», «Что нужно») is a statement, one figure is a big-number slide, two or more figures are a
    KPI row. None when the sentence is plain text or a list — the general rules read it then."""
    title = sec.title or ""
    s0 = sec.sentences[0]
    if _is_ask(title, s0):
        # the ask is said once, in large type (its figures in the accent colour), under the section's own name; it is
        # the last slide to give way when the deck has fewer slides than its sections (_keep_priority)
        return _Block(PatternKind.bullets, title or "Что просим", title, SlideContent(paragraphs=[H.cap_first(H.strip_end(s0))]), "ask")
    ks = _without_starts(kpis_for(s0))
    if not ks or len(s0.split()) > 30:
        return None
    if enum_parts and not all(re.search(r"\d", p) for p in enum_parts):
        return None  # «A, B и C» of which only one part has a figure is a list, not a row of figures
    bare = len(ks) == 1 and _only_the_figure(ks[0])  # «Бюджет: 25 млн ₽.»: nothing but the figure
    if title and (bare or not H.is_statement(s0)):
        # «Выручка: 120 млн ₽ за год», «Затраты: снизились до 80 млн ₽»: the label names what the figure is
        head = title
    else:
        head = _headline([s0], title) or H.strip_end(s0)
    if len(ks) >= 2:
        # a row of figures is headed by the clause of its key figure (a change first): «Время сократилось до 29
        # минут», not the whole «…, NPS 64» — the other figures speak on their tiles, under their own labels
        lead = next((k.clause for k in ks if "→" in k.value and H.is_statement(k.clause)), None) or next((k.clause for k in ks if H.is_statement(k.clause)), None)
        if lead:
            head = H.cap_first(_headline([lead], head))
    nums = []
    for k in ks[:4]:
        if _only_the_figure(k):
            # «Бюджет: 25 млн ₽»: the heading above says what the figure is, the tile does not say it again
            label = "" if not title or head == title else title
        else:
            label = _own_label(k, text)
        nums.append(NumberCallout(value=k.value, label=label, fact_id=_fact_id(facts, k.value)))
    kind = PatternKind.big_number if len(nums) == 1 else PatternKind.stat_row
    blk = _Block(kind, head, title, SlideContent(numbers=nums), "kpi", [n.fact_id for n in nums if n.fact_id], kpis=ks)
    if H.strip_end(s0) != head and not bare:
        blk.notes = H.strip_end(s0) + "."  # the heading was cut: the whole statement stays with the speaker
    return blk


def _blocks_of(sec: H.Section, facts: FactsExtraction, series_by_span: dict, closing: bool, kpis_for=H.kpis_of, short: bool = False, text: Optional[str] = None) -> list[_Block]:
    out: list[_Block] = []
    title = sec.title or ""
    sentences = list(sec.sentences)
    ask_sec = short and _ask_section(sec)  # the whole section asks: its lines are the ask's lines, never cards or tiles
    steps, rest = H.steps_of(sentences)
    labelled, rest = H.labelled_items(rest) if not steps and not ask_sec else ([], rest)
    enum_lead, enum_parts, enum_src = None, [], None
    if not steps and not labelled:
        for sn in rest:
            lead, parts = H.enumeration(sn)
            if short and parts and all(re.search(r"\d", p) for p in parts):
                continue  # «было 5 дней, стало 2 дня, NPS 64»: a short brief reads figures as figures, not as a list
            if len(parts) >= 3:
                enum_lead, enum_parts, enum_src = lead, parts, sn
                break
    if short and not steps and len(sentences) == 1 and not sec.tables:
        blk = _one_sentence_block(sec, facts, kpis_for, enum_parts, text)
        if blk is not None:
            return [blk]
    # a short brief never turns the figure of an ask («Предлагаем: бюджет 14,5 млн ₽ …») into a tile: the ask is said
    # as a statement
    kpis = [k for sn in rest if sn != enum_src and not (short and (ask_sec or _ask_line(sn, title))) for k in kpis_for(sn)]
    kpi_sentences = {k.sentence for k in kpis}
    if steps:
        statements = [r for r in rest if not H.label_split(r) and len(r.split()) >= 3]
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
        # the section's first statement heads the slide (with or without a figure of its own)
        head_sentence = next((x for x in sentences if len(x.split()) >= 3 and not H.steps_of([x, x, x])[0] and not (short and H._WAS_LEAD_RE.match(x))), kpis[0].sentence)
        tiles = [k for k in kpis if k.sentence != head_sentence]
        if len(tiles) < 3:
            tiles = kpis
        tiles = tiles[:4]
        if short:
            tiles = _without_starts(tiles)  # «47 минут» next to «47 → 29 минут» is said once, as the change
        nums = [NumberCallout(value=k.value, label=_own_label(k, text) if short else k.label, fact_id=_fact_id(facts, k.value)) for k in tiles]
        head = _headline([head_sentence], title)
        kind = PatternKind.big_number if len(nums) == 1 else PatternKind.stat_row
        blk = _Block(kind, head, title, SlideContent(numbers=nums), "kpi", [n.fact_id for n in nums if n.fact_id], kpis=kpis)
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
            out.append(_Block(PatternKind.chart, head or lead or _table_head(title, tbl), title, SlideContent(chart=spec), "chart"))
            out[-1].content.table = tbl  # kept for strategies that prefer the table
        else:
            out.append(_Block(PatternKind.table, lead or _table_head(title, tbl), title, SlideContent(table=tbl), "table"))
    # what is left is running text: a thesis slide, headed by its first statement
    rest = [r for r in rest if r.strip()]
    if rest:
        if len(rest) == 1 and out:
            first = out[0]
            if not first.content.paragraphs and len(rest[0].split()) <= 20:
                first.content.paragraphs = [H.strip_end(rest[0])]
                rest = []
        if rest and short and title and len(rest) >= 2 and (sec.listed or ask_sec):
            # a «Метка:» lead over its list, or an ask said in several lines: headed by its label, every line an item
            out.insert(0 if not closing else len(out), _Block(PatternKind.bullets, title, title, SlideContent(bullets=[H.cap_first(H.strip_end(r)) for r in rest]), "text"))
            rest = []
        if rest:
            head = _headline(rest, title) if len(rest) >= 2 else (title or H.short(rest[0], 11))
            if short and title and len(rest) >= 2 and _bare_figure(rest[0], kpis_for):
                head = title  # «Срок: 3 месяца. …»: a bare figure says what it is by its label, not under the next line
            body = []
            for r in rest:
                if H.short(r, 11) == head:
                    continue
                parts = H.label_split(r)
                if parts and H.short(parts[0], 11) == head:
                    body.append(H.cap_first(H.strip_end(parts[1].strip())))  # the heading took the part before the colon
                    continue
                body.append(H.strip_end(r))
            if not body:
                body = [H.strip_end(rest[0])]
                head = title or head
                dash = re.split(r"\s[—–]\s", body[0], maxsplit=1) if short and not title else []
                if len(dash) == 2 and len(dash[0].split()) >= 2 and len(dash[1].split()) >= 2:
                    # a line of its own, «Следующий шаг — раскатка на всю компанию»: headed by what precedes the dash,
                    # not said twice
                    head, body = dash[0].strip(), [H.cap_first(dash[1].strip())]
            kind = PatternKind.bullets
            content = SlideContent(bullets=body) if len(body) >= 2 else SlideContent(paragraphs=body)
            out.insert(0 if not closing else len(out), _Block(kind, head, title, content, "text"))
    # two figures inside running text: the text slide stays, the small KPI row is only offered to «visual»
    if ask_sec:
        for b in out:
            if b.role in ("text", "items", "steps"):
                b.role = "ask"  # the ask said in several lines (or as a list, or steps) is kept to the last as well
    return out


def _bare_figure(sentence: str, kpis_for=H.kpis_of) -> bool:
    """«3 месяца.», «25 млн ₽»: a line that is nothing but its figure."""
    ks = kpis_for(sentence)
    return len(ks) == 1 and len(sentence.split()) <= 4 and _only_the_figure(ks[0])


def _to_cards(b: _Block) -> _Block:
    """Visual strategy: two to four theses become cards with short titles instead of a bulleted list. The ask stays as
    it is: said as a statement, and kept to the last when the deck is trimmed (its role)."""
    lines = b.content.bullets or b.content.paragraphs
    if b.kind != PatternKind.bullets or b.role == "ask" or not (2 <= len(lines) <= 4):
        return b
    items = [SlideItem(title=_headline([l], H.strip_end(l), max_words=10), icon_hint=H.short(l, 2)) for l in lines]
    return _Block(PatternKind.cards, b.headline, b.section, SlideContent(items=items), "items", b.fact_refs)


def _two_column(a: _Block, b: _Block) -> _Block:
    """Compact strategy: two neighbouring text sections share one slide."""
    def col(x: _Block) -> SlideItem:
        lines = x.content.bullets or x.content.paragraphs or [i.title for i in x.content.items]
        if x.content.items and x.headline and x.headline != x.section:
            return SlideItem(title=x.headline, bullets=[H.short(l, 12) for l in lines[:4]])
        return SlideItem(title=x.section or x.headline, bullets=[H.short(l, 12) for l in lines[:4]])
    head = a.headline
    if a.section and b.section:
        first, second = a.section, b.section[:1].lower() + b.section[1:]
        # «Контекст и проблема и что сделали» doubles the «и»: a name that has its own «и» is joined by a dash
        joint = " — " if " и " in f" {first} " or " и " in f" {second} " else " и "
        head = f"{first}{joint}{second}"
    return _Block(PatternKind.two_column, head, a.section, SlideContent(columns=[col(a), col(b)]), "text")


def _read_blocks(sections: list[H.Section], facts: FactsExtraction, series_by_span: dict, short: bool = False, text: Optional[str] = None) -> tuple[list[_Block], dict]:
    """Every section's slide candidates and the figures of every sentence, each figure as the brief writes it (a
    change only when one clause tells it: «с 47 до 29 минут»; two figures of different sentences are never joined). A
    short brief gives a one-sentence section a slide of its own. `text` is the brief: a change's label keeps a name's
    capital by it (H.kpi_of)."""
    figures = {sn: H.kpis_of(sn, text) for sec in sections for sn in sec.sentences}
    kpis_for = lambda sn: figures[sn] if sn in figures else H.kpis_of(sn, text)  # noqa: E731
    blocks: list[_Block] = []
    for i, sec in enumerate(sections):
        closing = i == len(sections) - 1 and bool(_CLOSING_RE.search(sec.title or ""))
        blocks.extend(_blocks_of(sec, facts, series_by_span, closing, kpis_for, short, text if short else None))
    return blocks, figures


def _other_clause(b: "_Block", same) -> str:
    """The clause of the figure a KPI pair keeps once its hero figure opens the deck («NPS 64»)."""
    k = next((k for k in b.kpis if not same(k.value)), None)
    return k.clause if k is not None else ""


def _lead_label(sentence: str) -> Optional[str]:
    """«Результаты:», «Просим:» — a short label that ends its line, over the list that follows it; None otherwise."""
    s = sentence.strip()
    if not s.endswith(":") or H._STEP_RE.match(s):
        return None
    label = H.strip_end(s)
    return H.cap_first(label) if label and len(label.split()) <= 4 and not H._LABEL_COLON_RE.search(label) else None


def _split_labelled(sections: list[H.Section]) -> list[H.Section]:
    """Sections whose sentences are «Метка: текст» statements («Результаты: …», «Просим: …») cut into one section per
    label. The sentences are read in order: an unlabelled sentence written on a label's line belongs to that label
    («Результаты: время сократилось до 29 минут. NPS вырос до 64.» is one section), those before the first label stay
    under the section's own title; a «Метка:» lead that ends its line is the label of the list under it. The paragraph's own
    label counts as one: «Проблема: … / Результаты: …» is cut in two just as «Проблема: … / Результаты: … / Просим: …»
    is cut in three, while a paragraph that opens with a lead («Преимущества:») keeps its labelled lines together. An
    ask said among other sentences («Просим бюджет …», «Предлагаем: …», «Что нужно: …», «Запрос: …», «Решение:
    выделить …», «Нужен бюджет 14,5 млн ₽ …») always becomes a section of its own, even as the one labelled line. The
    same list when there is nothing to cut.

    An ask is never cut into figures: the lines under «## Что просим» (or «## Запрос», or a «## Решение» that asks) and
    the items of a «Просим:» lead stay the ask's lines, «- Бюджет: 14,5 млн ₽» / «- Срок: 3 месяца» included. A line
    typed on its own after «Метка: значение» lines is not the last label's («Бюджет: 25 млн ₽.» / «Срок: 3 месяца.» /
    «Команда из 8 человек начнёт работу в июле.»): it starts a section of its own — only a sentence written on the
    label's own line, or a list item under it, belongs to the label."""
    out: list[H.Section] = []
    changed = False
    for sec in sections:
        if sec.heading and _ask_section(sec):
            out.append(sec)  # «## Что просим» / «- Бюджет: 14,5 млн ₽» / «- Срок: 3 месяца»: one ask, not two figures
            continue
        steps, _ = H.steps_of(sec.sentences)
        sents = list(sec.sentences)
        # a paragraph that opens with a lead («Результаты:», «Преимущества:») is the list under it: headed by the label
        # (the section's own, or the lead's when the section has none), the lead not said again as a line of its own; the
        # labelled lines right under it are its items («Преимущества:» / «Скорость: …» / «Цена: …»)
        own_lead = bool(sents) and sents[0].rstrip().endswith(":")
        lead0 = _lead_label(sents[0]) if own_lead else None
        listed = bool(lead0) and len(sents) >= 2 and (not sec.title or lead0 == H.cap_first(sec.title))
        title = (sec.title or lead0 or "") if listed else sec.title
        if listed:
            sents = [H.cap_first(x.strip()) for x in sents[1:]]
        cut = not steps and (not own_lead or listed)  # a long lead («Результаты пилота (…):») keeps its lines together
        groups: list[H.Section] = [H.Section(title=title, listed=listed)]
        asks: list[str] = []
        labelled_run = listed  # the lines under a lead so far are all labelled («Преимущества:» / «Скорость: …»)
        by_label = False  # the current group was opened by a «Метка: значение» line of this paragraph
        for sn in sents:
            m = H._LABELLED_RE.match(sn.strip())
            labelled = cut and bool(m) and len(m.group("label").split()) <= 4 and not H._STEP_RE.match(sn.strip())
            lead = _lead_label(sn) if cut else None
            key = H.cap_first(sn.strip())
            item, same_line = key in sec.marked, key in sec.joined  # typed as a list item / on the line before it
            cur = groups[-1]
            if lead:
                groups.append(H.Section(title=lead, listed=True))
                labelled_run, by_label = True, False
            elif (
                not labelled and len(sents) >= 2 and not _asking_section(title) and not _asking_section(cur.title)
                and not (cur.listed and item and _ask_name(cur.title)) and _ask_line(sn, cur.title)
            ):
                asks.append(sn)  # (the items of a «Решение:» lead stay its own: the lead is the ask then, _ask_section)
            elif labelled and not (cur.listed and (labelled_run or item) and (_asking_section(cur.title) or not _ask_line(sn, ""))):
                # (an item of a lead stays its item — «Просим:» / «- бюджет: 14,5 млн ₽» — unless it is an ask of its own
                # under another lead: «Результаты:» / … / «Просим: бюджет …»)
                text = H.cap_first(H.strip_end(m.group("text")))
                groups.append(H.Section(title=H.cap_first(H.strip_end(m.group("label"))), sentences=H.split_sentences(text + ".") or [text + "."]))
                # only a «Метка: значение» line (a bare figure or a few words: «Бюджет: 25 млн ₽», «Срок: 3 месяца»)
                # lets the next line of its own start a section; a statement («Результаты: время сократилось до 29
                # минут.») keeps the lines that go on after it («NPS вырос с 41 до 64.»)
                labelled_run, by_label = False, len(text.split()) <= 3 or _bare_figure(text + ".")
            elif by_label and not labelled and not same_line and not item and not _asking_section(cur.title):
                groups.append(H.Section(title="", sentences=[sn]))  # a line of its own: not the last label's
                by_label = False
            else:
                cur.sentences.append(H.cap_first(sn.strip()) if cur.listed else sn)
                labelled_run = labelled_run and labelled
        for k in range(len(groups) - 1, 0, -1):
            if groups[k].listed and not groups[k].sentences:
                groups[k - 1].sentences.append(groups[k].title + ":")  # a lead with nothing under it stays a line
                del groups[k]
        own = bool(title) and any(not r.rstrip().endswith(":") for r in groups[0].sentences)  # a statement under the section's label
        if len(groups) - 1 + own < 2 and not any(g.listed for g in groups[1:]):
            # nothing to cut by labels: an ask said among the other sentences still gets a section of its own (a listed
            # section that asks as a whole — «Решение:» / «- бюджет: 14,5 млн ₽» / «- срок: 3 месяца» — stays one ask)
            rest = list(sents)
            whole_ask = listed and _ask_section(H.Section(title=title, sentences=list(sents)))
            asks = [x for x in rest if _ask_line(x, title)] if len(sents) >= 2 and not _asking_section(title) and not whole_ask else []
            rest = [x for x in rest if x not in asks]
            if not (asks and (rest or sec.tables)):
                if listed:
                    out.append(H.Section(title=title, sentences=sents, tables=list(sec.tables), table_leads=list(sec.table_leads), listed=True))
                    changed = True
                else:
                    out.append(sec)
                continue
            groups = [H.Section(title=title, sentences=rest, listed=listed)]
        changed = True
        head = groups[0]
        if head.sentences or sec.tables:
            out.append(H.Section(title=title, sentences=list(head.sentences), tables=list(sec.tables), table_leads=list(sec.table_leads), listed=head.listed))
        out.extend(groups[1:])
        for a in asks:
            # «Просим: утвердить план найма» under its own label; «Просим одобрить бюджет …» under «Что просим»
            m = H._LABELLED_RE.match(a.strip())
            if m and len(m.group("label").split()) <= 4:
                out.append(H.Section(title=H.cap_first(H.strip_end(m.group("label"))), sentences=[H.cap_first(H.strip_end(m.group("text"))) + "."]))
            elif out and out[-1].title == "Что просим":
                out[-1].sentences.append(a)
            else:
                out.append(H.Section(title="Что просим", sentences=[a]))
    return out if changed else sections


# the sections a deck of this purpose usually has: a topic without theses becomes this skeleton, not invented content
_SKELETONS: dict[str, list[str]] = {
    "feature": ["Проблема", "Решение", "Как это работает", "Результаты", "Следующие шаги"],
    "product": ["Рынок и проблема", "Продукт", "Преимущества", "Метрики", "Планы развития"],
    "project": ["Цели проекта", "Команда и сроки", "Ход работ", "Риски", "Следующие шаги"],
    "initiative": ["Контекст", "Предложение", "Эффект", "Что нужно", "Следующие шаги"],
    "report": ["Цели периода", "Что сделано", "Результаты", "Сложности", "Планы"],
}
_SKELETON_DEFAULT = ["Контекст", "Главное", "Детали", "Выводы", "Следующие шаги"]


def _title_from_first_statement(sections: list[H.Section]) -> tuple[Optional[str], bool]:
    """A brief without a heading is titled by its first statement: «Итоги пилота …: время сократилось …» → the part
    before the colon; a short statement alone → the whole of it. Returns (title, the whole statement was used)."""
    first = next((s for sec in sections for s in sec.sentences), None)
    if not first:
        return None, False
    lead, rest = H.label_split(first) or (first, "")  # «Созвон в 10:30 …» has no lead: the time is not a colon
    if rest.strip() and 2 <= len(lead.split()) <= 12:
        return H.cap_first(H.strip_end(lead.strip())), False
    if not rest.strip() and len(first.split()) <= 14:
        return H.cap_first(H.strip_end(first.strip())), True
    return None, False


def _skeleton(brief: Brief, title: str, facts: FactsExtraction, strategy: Strategy, target: int) -> DeckOutline:
    """A topic with nothing to lay out: the title, an agenda and one divider per usual section of such a deck, each
    with a speaker note on what to add. Nothing is invented; the person fills the sections in PowerPoint or adds
    theses and runs Verstka again."""
    heads = _SKELETONS.get(brief.purpose or "", _SKELETON_DEFAULT)
    slides = [
        OutlineSlide(id="sl1", kind=PatternKind.title, headline=title, subtitle=brief.audience or None),
        OutlineSlide(id="sl2", kind=PatternKind.agenda, headline="О чём поговорим", content=SlideContent(items=[SlideItem(title=h) for h in heads])),
    ]
    for h in heads:
        slides.append(OutlineSlide(id=f"sl{len(slides) + 1}", kind=PatternKind.section, headline=h, notes=f"Добавьте сюда тезисы и цифры раздела «{h}» — по ним Verstka соберёт слайды этого раздела."))
    slides.append(OutlineSlide(id=f"sl{len(slides) + 1}", kind=PatternKind.thanks, headline="Спасибо за внимание"))
    outline = DeckOutline(title=title, subtitle=brief.audience, audience=brief.audience, purpose=brief.purpose, strategy=strategy.name, language=brief.language, planned_by="skeleton", slides=slides, facts=facts.facts, series=facts.series, tables=facts.tables)
    return validate_outline(outline, None, target, hard_limit=bool(brief.slide_count))


def _short_mode(sections: list[H.Section], blocks: list[_Block], target: int) -> bool:
    """A short brief: a few statements (SHORT_BRIEF_SENTENCES at most) that the general rules turn into a thin deck
    (fewer than eight slides). Only such a brief has its labelled lines cut into sections and its one-sentence sections
    given slides of their own; a fixed small deck (four slides or more) is then trimmed with the ask kept to the last
    (_keep_priority), rather than read by rules that fold the ask into cards. A longer brief is read exactly as it
    always was (its labelled lines stay cards); so is a deck of three slides, where one slide of columns says more than
    one figure. Either way a figure is shown as it is written."""
    n = sum(1 for sec in sections for sn in sec.sentences if not sn.rstrip().endswith(":"))  # a lead «Результаты:» is not a statement
    return n <= SHORT_BRIEF_SENTENCES and target >= 4 and len([b for b in blocks if b.role != "kpi_small"]) + 2 < 8


def _short_sections(parsed: list[H.Section], popped: Optional[tuple[H.Section, str]]) -> list[H.Section]:
    """A short brief's sections: «Проблема: …», «Результаты: …», «Просим: …» written in one run are sections of their
    own (a figure slide, a KPI row, a statement), not the columns of one slide. The statement that titles the deck comes
    back when it is the one statement of a labelled section with a figure («Проблема: сотрудники тратят 47 минут …»):
    the figure keeps its slide rather than live in the title alone."""
    if popped is not None:
        popped[0].sentences.insert(0, popped[1])
    split = _split_labelled([sec for sec in parsed if sec.sentences or sec.tables])
    if popped is not None:
        sn = popped[1]
        home = next((sec for sec in split if sec.sentences and sec.sentences[0] == sn), None)
        if home is not None and not (home.title and len(home.sentences) == 1 and not home.tables and H.kpis_of(sn)):
            home.sentences.pop(0)
    return [sec for sec in split if sec.sentences or sec.tables]


def _repeats(label: str, headline: str) -> bool:
    lw, hw = H._label_words(label), set(H._label_words(headline))
    return len(label.split()) > 2 and bool(lw) and sum(w in hw for w in lw) >= 0.6 * len(lw)


def _stand_alone(b: _Block, n: NumberCallout, same, text: Optional[str] = None) -> None:
    """A row of two figures gave its key figure to the opening slide: the other one stands alone, headed by its own
    clause («Команда выросла до 40 человек») and labelled by what the heading does not say («человек»), or headed by
    the section when its clause is too short to be a heading («NPS 64»)."""
    clause = _other_clause(b, same)
    b.kind, b.content.numbers = PatternKind.big_number, [n]
    if len(clause.split()) < 3:
        b.headline = b.section or b.headline
        return
    b.headline = H.cap_first(H.short(clause, 11))
    span = H.figure_span(n.value, b.headline)
    tail = b.headline[span[1] :].strip(" ,.:;—-") if span else ""
    if tail:
        n.label = tail
        return
    label = H.label_beside(n.value, n.label, b.headline, text)
    n.label = (b.section or label) if label == n.label and _repeats(n.label, b.headline) else label


def _text_beside_row(t: _Block, row: _Block) -> None:
    """A short brief's text slide headed like the KPI row its figures went to: one line left goes onto the row, above
    its figures (the text slide is then empty and dropped); more lines are headed by their own first statement."""
    lines = t.content.bullets + t.content.paragraphs
    if len(lines) == 1 and not (row.content.paragraphs or row.content.bullets) and len(lines[0].split()) <= 20:
        row.content.paragraphs = lines
        t.content.bullets, t.content.paragraphs = [], []
    elif lines:
        _rehead(t, {row.headline})
        body = [x for x in lines if H.strip_end(x) != t.headline] or lines
        t.content.bullets, t.content.paragraphs = (body, []) if len(body) >= 2 else ([], body)


def _hero_first(blocks: list[_Block], key_kpi: H.Kpi, facts: FactsExtraction) -> list[_Block]:
    """Visual deck of a longer brief: its key figure opens it on a slide of its own; the tiles it came from keep the
    other figures (when two or more remain)."""
    summary = _Block(PatternKind.big_number, H.cap_first(H.short(key_kpi.sentence, 11)), "", SlideContent(numbers=[NumberCallout(value=key_kpi.value, label=key_kpi.label, fact_id=_fact_id(facts, key_kpi.value))]), "kpi", kpis=[key_kpi])
    blocks.insert(0, summary)
    same = lambda v: re.sub(r"\s", "", v) == re.sub(r"\s", "", key_kpi.value)  # noqa: E731
    for b in blocks[1:]:
        nums = b.content.numbers
        if any(same(n.value) for n in nums) and len([n for n in nums if not same(n.value)]) >= 2:
            b.content.numbers = [n for n in nums if not same(n.value)]
        items = b.content.items
        if any(it.number and same(it.number) for it in items) and len([it for it in items if not (it.number and same(it.number))]) >= 2:
            b.content.items = [it for it in items if not (it.number and same(it.number))]
    return blocks


def _rehead(b: _Block, taken: set[str]) -> None:
    """A slide whose heading another slide says: headed by its section, else by the first statement among its own
    figures or lines that no other slide says."""
    if b.section and b.section not in taken:
        b.headline = b.section
        return
    shown = {re.sub(r"\s", "", n.value) for n in b.content.numbers}
    clauses = [k.clause for k in b.kpis if re.sub(r"\s", "", k.value) in shown and k.clause and H.is_statement(k.clause)]
    for c in clauses + b.content.bullets + b.content.paragraphs:
        head = H.cap_first(_headline([c], H.strip_end(c)))
        if head not in taken:
            b.headline = head
            return
    for k in b.kpis:  # else the figure's own clause, however short («NPS 64»): a heading no other slide says
        head = H.cap_first(H.strip_end(k.clause or ""))
        if re.sub(r"\s", "", k.value) in shown and head and head not in taken:
            b.headline = head
            return


def _lead_with_key_figure(blocks: list[_Block], key_kpi: H.Kpi, figures: dict, facts: FactsExtraction, target: int, text: Optional[str] = None) -> list[_Block]:
    """Visual deck of a short brief: it opens with its key figure, said once.
    - The figure already has a slide of its own (or a pair whose other figure has no heading to stand under): that
      slide opens the deck.
    - Otherwise, when the deck has room for one more slide, a big-number slide opens it and the tiles it came from give
      the figure up (a pair's other figure then stands alone, _stand_alone).
    - At or over the deck's size, or when the figure would stay on its tile anyway, no slide is added: a slide that
      only repeats a figure is not worth the place of the ask or of another figure."""
    same = lambda v: re.sub(r"\s", "", v) == re.sub(r"\s", "", key_kpi.value)  # noqa: E731
    own = next((b for b in blocks if b.kind == PatternKind.big_number and len(b.content.numbers) == 1 and same(b.content.numbers[0].value)), None)
    pair = next((b for b in blocks if b.kind == PatternKind.stat_row and b.role == "kpi" and len(b.content.numbers) == 2 and any(same(n.value) for n in b.content.numbers)), None)
    if own is None and pair is not None and not (pair.section or len(_other_clause(pair, same).split()) >= 3):
        own = pair  # the other figure of the pair has no heading of its own to stand alone under: the pair leads
    if own is None and len(figures.get(key_kpi.sentence, [])) >= 2 and not H.is_statement(key_kpi.clause or ""):
        # the figure has no statement of its own to head a slide («было 5 дней, стало 2 дня, NPS 64»): the slide it is
        # on leads, rather than a heading that says the other figures again
        own = next((b for b in blocks if any(same(n.value) for n in b.content.numbers)), None)
    if own is not None:
        blocks.remove(own)
        blocks.insert(0, own)
        return blocks
    if len(blocks) + 2 >= target:
        return blocks

    def keeps(b: _Block) -> bool:  # the figure stays on this slide even when a hero slide takes it
        nums = b.content.numbers
        if any(same(n.value) for n in nums):
            others = [n for n in nums if not same(n.value)]
            if not (len(others) >= 2 or (len(others) == 1 and b.kind == PatternKind.stat_row and b.role == "kpi")):
                return True
        items = b.content.items
        return any(it.number and same(it.number) for it in items) and len([it for it in items if not (it.number and same(it.number))]) < 2

    if any(keeps(b) for b in blocks):
        return blocks
    hero_head = H.short(key_kpi.sentence, 11)
    if key_kpi.clause and len(figures.get(key_kpi.sentence, [])) >= 2 and H.is_statement(key_kpi.clause):
        hero_head = H.short(key_kpi.clause, 11)  # «Время сократилось до 29 минут», not the NPS said next to it
    hero_head = H.cap_first(hero_head)
    hero = NumberCallout(value=key_kpi.value, label=H.label_beside(key_kpi.value, key_kpi.label, hero_head, text), fact_id=_fact_id(facts, key_kpi.value))
    summary = _Block(PatternKind.big_number, hero_head, "", SlideContent(numbers=[hero]), "kpi", kpis=[key_kpi])
    blocks.insert(0, summary)
    for b in blocks[1:]:
        nums = b.content.numbers
        others = [n for n in nums if not same(n.value)]
        took = any(same(n.value) for n in nums) and len(others) >= 2
        if took:
            b.content.numbers = others
        elif any(same(n.value) for n in nums) and len(others) == 1 and b.kind == PatternKind.stat_row and b.role == "kpi":
            _stand_alone(b, others[0], same, text)
        if b.headline == hero_head or (took and H.figure_span(key_kpi.value, b.headline)):
            _rehead(b, {hero_head})  # the opening slide says this heading (and its figure) now
        items = b.content.items
        if any(it.number and same(it.number) for it in items) and len([it for it in items if not (it.number and same(it.number))]) >= 2:
            b.content.items = [it for it in items if not (it.number and same(it.number))]
    return blocks


def _norm_value(value: str) -> str:
    return re.sub(r"\s", "", value).lower()


def _change_ends(value: str) -> list[str]:
    """«47 → 29 минут» → [«47 минут», «29 минут»]: the two ends of a change (the start takes the end's unit when it is
    written without one); a single figure is its own one end."""
    if "→" not in value:
        return [value]
    a, b = (x.strip() for x in value.split("→", 1))
    unit = re.sub(r"^[+\-−]?\d[\d\s.,]*", "", b).strip()
    if unit and not re.search(r"[^\d\s.,+\-−]", a):
        a = f"{a}{unit}" if unit == "%" else f"{a} {unit}"
    return [a, b]


def _without_starts(ks: list) -> list:
    """A figure said next to the change it starts («47 минут» and «47 → 29 минут» of one section) is said once."""
    starts = {_norm_value(_change_ends(k.value)[0]) for k in ks if "→" in k.value}
    return [k for k in ks if "→" in k.value or _norm_value(k.value) not in starts] if starts else ks


def _said(s: OutlineSlide) -> str:
    c = s.content
    parts = [s.headline, s.subtitle or ""] + c.bullets + c.paragraphs + [f"{n.value} {n.label}" for n in c.numbers]
    parts += [f"{i.title} {i.text or ''} {i.number or ''} {' '.join(i.bullets)}" for i in c.items + c.columns]
    return " ".join(parts)


_BARE_VALUE_RE = re.compile(r"[+\-−]?\d[\d\s.,]*")
_NEXT_WORD_RE = re.compile(r"\s*([^\s,.;:!?)»]+)")


def _written_in(value: str, text: str) -> bool:
    """The figure is written in the text as a value: as whole words (H.figure_span), and a bare number («30») not as
    the number of some unit («30 минут», «30%»)."""
    bare = _BARE_VALUE_RE.fullmatch(value.strip()) is not None
    pos = 0
    while (span := H.figure_span(value, text[pos:])) is not None:
        nxt = _NEXT_WORD_RE.match(text[pos + span[1] :])
        if not bare or not (nxt and H._UNIT_WORD_RE.match(nxt.group(1))):
            return True
        pos += span[1]
    return False


def _stands_on(value: str, o: OutlineSlide) -> bool:
    """The figure is on slide `o` as a value — one of its figures, an end of one of its changes, or written in its text
    — not merely its digits: «30 минут» is not on a slide that says «30 команд», nor «30» on one that says «30 минут»."""
    v = _norm_value(value)
    if any(v == _norm_value(n.value) or v in {_norm_value(e) for e in _change_ends(n.value)} for n in o.content.numbers):
        return True
    return _written_in(value, _said(o))


def _keep_priority(ask_ids: set[str]):
    """Which slides of a short brief's deck give way first when the deck has fewer slides than its sections: a figure
    slide whose figures all stand on other slides goes right after the agenda; the ask («Просим бюджет …») goes last,
    after every figure — cutting the request is the worst cut a deck for a decision-maker can take."""

    def keep(slides: list[OutlineSlide], s: OutlineSlide) -> Optional[float]:
        if s.id in ask_ids:
            return 6.5
        values = [n.value for n in s.content.numbers]
        if values and s.kind in (PatternKind.big_number, PatternKind.stat_row):
            others = [o for o in slides[1:-1] if o is not s and o.kind != PatternKind.agenda]
            if all(any(_stands_on(v, o) for o in others) for v in values):
                return 2.5
        return None

    return keep


def basic_outline(brief: Brief, facts: FactsExtraction, strategy: Strategy, target: int) -> DeckOutline:
    """Deterministic planner: read the brief's sections into typed slides (steps → process, «X: …» → cards,
    figures → KPI row, tables → chart or table, the rest → theses headed by a conclusion), then assemble them the
    way the strategy asks — structured (agenda, one idea per slide), visual (key figure first, cards, charts),
    compact (paired text sections, tables). A short brief far below the deck's size is read line by line
    (_short_mode): one slide per labelled line, the ask kept to the last. A figure is always shown as the brief writes
    it: a change «A → B» only when one clause tells it («с 47 до 29 минут»), never two figures of different sentences
    joined."""
    doc_title, parsed = H.parse_sections(brief.text)
    title = brief.title_hint or doc_title
    popped: Optional[tuple[H.Section, str]] = None
    if not title:
        title, whole = _title_from_first_statement(parsed)
        if whole:  # the statement that titles the deck is not repeated as a slide of its own
            sec0 = next(sec for sec in parsed if sec.sentences)
            popped = (sec0, sec0.sentences.pop(0))
    title = title or "Презентация"
    sections = [sec for sec in parsed if sec.sentences or sec.tables]
    if not sections:
        return _skeleton(brief, title, facts, strategy, target)
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
    blocks, figures = _read_blocks(sections, facts, series_by_span, text=brief.text)
    short = _short_mode(sections, blocks, target)
    if short:
        sections = _short_sections(parsed, popped)
        blocks, figures = _read_blocks(sections, facts, series_by_span, short=True, text=brief.text)

    def asked(sec: H.Section, sn: str) -> bool:  # a short brief's ask never gives the deck its key figure
        return short and (_ask_section(sec) or _ask_line(sn, sec.title))

    # the deck's key figure: a change «с A до B» anywhere, else the first figure of the last KPI row (results come last)
    key_kpi = next((k for sec in sections for sn in sec.sentences if not asked(sec, sn) for k in figures.get(sn, []) if "→" in k.value), None)
    if key_kpi is None:
        # (a short brief's two figures of two sentences are a KPI row too, in every variant)
        kb = next((b for b in reversed(blocks) if b.role == "kpi" or (short and b.role == "kpi_small")), None)
        if kb and kb.kpis:
            key_kpi = kb.kpis[0]
    name = strategy.name
    # a short brief keeps a section's two figures as a KPI row in every variant (a longer one says them in its text
    # slide and gives the row to «visual» only)
    if name == "visual" or short:
        for b in blocks:
            if b.role == "kpi_small":
                b.role = "kpi"
                # the figures are said once: on the tiles, not again in the text slide of their section
                said = {H.strip_end(k.sentence) for k in b.kpis}
                for t in blocks:
                    if t.role == "text" and t.section == b.section:
                        t.content.bullets = [x for x in t.content.bullets if H.strip_end(x) not in said]
                        t.content.paragraphs = [x for x in t.content.paragraphs if H.strip_end(x) not in said]
                        if len(t.content.bullets) == 1:
                            t.content.paragraphs, t.content.bullets = t.content.bullets + t.content.paragraphs, []
                        if short and t.headline == b.headline:
                            _text_beside_row(t, b)
        if short:
            # a text slide headed like the KPI row of its section (its first statement heads both) is not a second
            # slide with the same heading
            for b in [x for x in blocks if x.role == "kpi"]:
                for t in blocks:
                    if t.role == "text" and t.section == b.section and t.headline == b.headline and (t.content.bullets or t.content.paragraphs):
                        _text_beside_row(t, b)
        blocks = [b for b in blocks if not (b.role == "text" and not (b.content.bullets or b.content.paragraphs or b.content.items))]
    else:
        blocks = [b for b in blocks if b.role != "kpi_small"]
    if short and name != "visual":
        for b in blocks:
            if b.role == "ask" and b.kind == PatternKind.bullets and len(b.content.bullets) == 2 and not b.content.paragraphs:
                one = ". ".join(H.strip_end(x) for x in b.content.bullets)
                if len(one) <= ASK_STATEMENT_CHARS:
                    # two short lines of an ask are said as one statement, as a one-line ask is (the composer sets it in
                    # large type, its figures in the accent colour): two thin bullets leave three quarters of the slide
                    # empty. The visual variant keeps the lines, which its composer sets as cards.
                    b.content.paragraphs, b.content.bullets = [one], []
    if name == "visual":
        blocks = [_to_cards(b) for b in blocks]
        blocks = [b for b in blocks if not (b.role == "table" and any(x.role == "chart" for x in blocks if x.section == b.section))]
        for b in blocks:
            if b.kind == PatternKind.chart:
                b.content.table = None
        if key_kpi is not None:
            blocks = _lead_with_key_figure(blocks, key_kpi, figures, facts, target, brief.text) if short else _hero_first(blocks, key_kpi, facts)
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
    for b in blocks:
        if b.headline.strip().lower() == title.strip().lower():
            # the statement that titles the deck («Итоги пилота …: время сократилось …») heads its slide by what
            # follows the lead, or by the section's name — not by the title again
            parts = H.label_split(next((k.sentence for k in b.kpis), ""))
            after = parts[1].strip() if parts else ""
            if len(after.split()) >= 3:
                b.headline = H.cap_first(_headline([after], after))
            elif b.section:
                b.headline = b.section
    slides: list[OutlineSlide] = [OutlineSlide(id="sl1", kind=PatternKind.title, headline=title, subtitle=brief.audience or None)]
    if name == "structured" and len(sections) >= 3:
        agenda_items = [SlideItem(title=sec.title) for sec in sections if sec.title][:8]  # the agenda names every section
        slides.append(OutlineSlide(id="sl2", kind=PatternKind.agenda, headline="О чём поговорим", content=SlideContent(items=agenda_items)))
    ask_ids: set[str] = set()
    for b in blocks:
        slides.append(OutlineSlide(id=f"sl{len(slides) + 1}", kind=b.kind, section=b.section or None, headline=b.headline, subtitle=b.subtitle, content=b.content, notes=b.notes, fact_refs=b.fact_refs))
        if b.role == "ask":
            ask_ids.add(slides[-1].id)
    slides.append(OutlineSlide(id=f"sl{len(slides) + 1}", kind=PatternKind.thanks, headline="Спасибо за внимание", subtitle=None))
    outline = DeckOutline(title=title, subtitle=brief.audience, audience=brief.audience, purpose=brief.purpose, strategy=strategy.name, language=brief.language, slides=slides, facts=facts.facts, series=facts.series, tables=facts.tables)
    outline = validate_outline(outline, None, target, hard_limit=bool(brief.slide_count), keep=_keep_priority(ask_ids) if short else None)
    if short:
        # a heading starts with a capital («Время сократилось до 29 минут», a list's first line); the plan says what
        # the slide shows: every label as the composer renders it under the slide's final heading (compose.distinct_label
        # is this same rule), a name in it with its capital
        for sl in outline.slides:
            sl.headline = H.cap_first(sl.headline)
            for n in sl.content.numbers:
                n.label = H.name_case(H.label_beside(n.value, n.label, sl.headline, brief.text), brief.text)
    return outline


# ------------------------------------------------------------------ validation

# Which slides go first when the deck is longer than the target: structure first, text next, data (charts, tables, KPI rows) last.
_DROP_PRIORITY = {PatternKind.section: 0, PatternKind.quote: 1, PatternKind.agenda: 2, PatternKind.bullets: 3}
_DATA_KINDS = {PatternKind.chart, PatternKind.table, PatternKind.stat_row}


def _drop_priority(s: OutlineSlide) -> int:
    return 6 if s.kind in _DATA_KINDS else _DROP_PRIORITY.get(s.kind, 5)


def _drop_key(slides: list[OutlineSlide], s: OutlineSlide, keep=None) -> tuple[float, int, int]:
    """Lower sorts first: priority, then (bullets slides only) the fewest bullets, then the later slide. `keep` may
    give a slide its own priority (the rules' deck of a short brief: the ask last, a repeated figure early)."""
    n_bullets = len(s.content.bullets) if s.kind == PatternKind.bullets else 0
    own = keep(slides, s) if keep is not None else None
    return (_drop_priority(s) if own is None else own, n_bullets, -slides.index(s))


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


def _norm_words(text: str) -> list[str]:
    return re.sub(r"[^\w%]+", " ", text.lower()).split()


def validate_outline(
    outline: DeckOutline,
    manifest: Optional[TemplateManifest],
    target: int,
    skills: Optional[SkillsRegistry] = None,
    providers: Optional[ProviderRegistry] = None,
    hard_limit: bool = False,
    keep=None,
) -> DeckOutline:
    """Normalise density and structure; trim to `target` (+1 tolerance) or, when the brief fixed the count (`hard_limit`), to exactly `target`.
    `keep(slides, slide)` → a drop priority of its own for a slide, or None for the usual one by kind.
    A deck of the slides the user asked for (Agent v2: slides with `spec_ref`, compiled by planning/compile.py) keeps
    them all in their order: no title or closing slide is added (the compiler set its frames), and only slides nobody
    asked for may go to meet the count."""
    slides = list(outline.slides)
    spec_deck = any(s.spec_ref is not None for s in slides)
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
        for ch in (c.chart, c.chart2):
            if ch is not None and len(ch.series_ids) > MAX_SERIES:
                ch.series_ids = ch.series_ids[:MAX_SERIES]
        if c.chart is None and c.chart2 is not None:
            c.chart, c.chart2 = c.chart2, None  # a second chart alone is the slide's chart
        s.headline = condense_text(s.headline, 14, skills, providers, outline.language)
        # a bullet that only repeats the heading (the closing statement of a section is often both) leaves the body
        head = _norm_words(s.headline)
        if len(head) >= 5:  # a statement, not a topic word («Контекст» may well open a bullet)
            c.bullets = [b for b in c.bullets if not (_norm_words(b)[: len(head)] == head and len(_norm_words(b)) - len(head) <= 5)]
        if s.kind in (PatternKind.stat_row, PatternKind.big_number) and not c.numbers and not c.formula:  # a formula alone is shown large
            s.kind = PatternKind.bullets
        if s.kind == PatternKind.chart and c.chart is None:
            s.kind = PatternKind.bullets
        if s.kind == PatternKind.table and c.table is None:
            s.kind = PatternKind.bullets
    # first/last slides
    if slides and slides[0].kind != PatternKind.title and not spec_deck:
        slides.insert(0, OutlineSlide(id="sl_title", kind=PatternKind.title, headline=outline.title, subtitle=outline.subtitle))
    if slides and slides[-1].kind != PatternKind.thanks and not spec_deck:
        slides.append(OutlineSlide(id="sl_thanks", kind=PatternKind.thanks, headline="Спасибо за внимание"))
    # count: drop low-priority slides beyond the limit; small bullets slides are merged into a neighbour before anything is lost
    limit = target if hard_limit else target + 1
    while len(slides) > limit:
        candidates = [s for s in slides[1:-1] if s.spec_ref is None]  # a slide the user asked for never goes
        if not candidates:
            break
        victim = min(candidates, key=lambda s: _drop_key(slides, s, keep))
        if _merge_into_previous(slides, victim):
            slides.remove(victim)
            continue
        if not hard_limit and _drop_key(slides, victim, keep)[0] >= 3 and len(slides) <= target + 2:
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

# a congested or confused model answers with an apology or an «error» deck instead of a plan
_REFUSAL_RE = re.compile(
    r"^\s*(error|ошибка)\s*$|невозможно (сформировать|создать|составить|подготовить|сделать)|не могу (сформировать|создать|составить|подготовить|помочь)"
    r"|недостаточно (данных|информации|сведений)|\bas an ai\b|\bi (cannot|can't|am unable)\b|\bunable to (create|generate)\b",
    re.I,
)
_FRAME_KINDS = {PatternKind.title, PatternKind.thanks, PatternKind.section, PatternKind.agenda}


def unusable_plan(planned: PlannedDeck) -> Optional[str]:
    """Why a model plan cannot become a deck (None when it can): no content slides, or a refusal instead of a plan. A
    «section» that carries bullets or figures is a content slide (plan_json.retype_frames types it by its content)."""
    retype_frames(planned.slides)
    if not any(s.kind not in _FRAME_KINDS for s in planned.slides):
        return "no content slides"
    if any(_REFUSAL_RE.search(t or "") for t in [planned.title] + [s.headline for s in planned.slides[:3]]):
        return "the model declined"
    return None



_COUNT_NOUNS = {"балл": ("балл", "балла", "баллов"), "пункт": ("пункт", "пункта", "пунктов")}
_COUNT_RE = re.compile(r"(?<![\w,.])(\d[\d\s\u00a0]*)(?:([,.]\d+))?(\s|\u00a0)(балл|пункт)(?:а|ов)?(?![\wё])", re.I)


def _agree(text: str) -> str:
    """«64 баллов» → «64 балла», «1 пунктов» → «1 пункт» (a decimal takes «балла»): a model's number agreement."""
    def fix(m: re.Match) -> str:
        whole, frac, sp, noun = m.group(1), m.group(2), m.group(3), m.group(4).lower()
        one, few, many = _COUNT_NOUNS[noun]
        if frac:
            form = few
        else:
            n = int(re.sub(r"\D", "", whole) or 0)
            form = ru_count(n, one, few, many).split(" ", 1)[1]
        return f"{whole}{frac or ''}{sp}{form}"
    return _COUNT_RE.sub(fix, text) if text else text


def polish_plan(o: DeckOutline) -> DeckOutline:
    """A model plan made to read like a designed deck (after grounding, before layout): a short deck (≤ 5 content
    slides) has no section dividers and no agenda — a divider per slide is noise; a slide of one bullet is set as its
    figure (a big number) when the bullet holds one, else as a statement; a figure's label is what the slide will show
    (heuristics.label_beside, the rule compose.distinct_label uses), so the audit finds the plan's text on the slide;
    «64 баллов» agrees with its number. Rules plans are left as they are. The agent's deck (planned_by "agent") is
    polished the same way, but never undoes its compiler: a deck of the slides the user asked for (`spec_ref`) keeps
    its dividers and agenda, and a slide with a chart, a table or a formula stays as it is."""
    if o.planned_by in ("rules", "skeleton"):
        return o
    o = o.model_copy(deep=True)
    content = [s for s in o.slides if s.kind not in _FRAME_KINDS]
    spec_deck = any(s.spec_ref is not None for s in o.slides)
    if 0 < len(content) <= 5 and not spec_deck:
        o.slides = [s for s in o.slides if s.kind not in (PatternKind.section, PatternKind.agenda)]
    for s in o.slides:
        c = s.content
        s.headline = _agree(s.headline)
        c.bullets = [_agree(b) for b in c.bullets]
        c.paragraphs = [_agree(t) for t in c.paragraphs]
        one_bullet = len(c.bullets) == 1 and not c.paragraphs
        short_para = len(c.paragraphs) == 1 and not c.bullets and len(c.paragraphs[0].split()) <= 8
        if s.kind == PatternKind.bullets and (one_bullet or short_para) and not (c.items or c.numbers or c.table or c.chart or c.chart2 or c.formula):
            line = (c.bullets or c.paragraphs)[0]
            ks = H.kpis_of(line)
            if len(ks) == 1 and not s.content.columns:
                k = ks[0]
                label = k.label or ""
                span = H.figure_span(k.value, label)
                if span:  # «NPS: 64 баллов» → «NPS»: the label never repeats its figure
                    label = label[: span[0]] + label[span[1]:]
                    label = re.sub(r"(?<![\wё])(?:балл|пункт)(?:а|ов)?(?![\wё])", " ", label, flags=re.I)
                    label = " ".join(label.replace(":", " ").split()).strip(" ,;—–-")
                label = H.label_beside(k.value, label, s.headline) or label
                s.kind = PatternKind.big_number
                c.numbers = [NumberCallout(value=k.value, label=_agree(label))]
                c.bullets, c.paragraphs = [], []
            else:
                c.paragraphs, c.bullets = [line], []  # one line reads as a statement, not a list of one
        for n in c.numbers:
            n.label = _agree(H.label_beside(n.value, n.label or "", s.headline) or n.label or "")
    return o

def adapt_outline(source: DeckOutline, strategy: Strategy, manifest: Optional[TemplateManifest], target: int, hard_limit: bool = False, brief: Optional[Brief] = None, warnings: Optional[list[str]] = None) -> DeckOutline:
    """Another variant's model plan reshaped for this strategy without a model: the visual and compact decks do
    without section dividers, the visual one shows figures as KPI rows, the compact one is merged down to its
    shorter target. Used when this variant's own model call failed — the deck keeps the model's content. With the
    `brief`, the reshaped plan is grounded again (grounding.ground_outline: a divider left without its slides, an
    agenda item without a slide; what it changes goes to `warnings`)."""
    o = source.model_copy(deep=True)
    o.strategy = strategy.name
    o.planned_by = f"shared:{source.strategy}"
    if strategy.name in ("visual", "compact"):
        o.slides = [s for s in o.slides if s.kind != PatternKind.section]
    if strategy.name == "visual":
        for s in o.slides:
            n = len(s.content.numbers)
            if s.kind in (PatternKind.bullets, PatternKind.two_column) and n >= 2 and not s.content.items:
                s.kind = PatternKind.stat_row
            elif s.kind == PatternKind.bullets and n == 1 and len(s.content.bullets) <= 1:
                s.kind = PatternKind.big_number
    o = validate_outline(o, manifest, target, hard_limit=hard_limit)
    if brief is not None:
        o, gw = ground_outline(o, brief)  # a divider left without its slides, an agenda item without a slide
        if warnings is not None:
            warnings.extend(gw)
    return polish_plan(o)


def _keep_raw(raw: Optional[list], step: str, res=None, error: Optional[Exception] = None) -> None:
    """The planner's answer as the model wrote it (or why there is none), for planner_raw.json of the run."""
    if raw is None:
        return
    if res is not None:
        raw.append({"step": step, "model": getattr(res, "model", None), "label": getattr(res, "label", None), "text": getattr(res, "text", None)})
    else:
        from verstka.providers.status import mask

        raw.append({"step": step, "error": mask(str(error))[:2000]})


def _has_content(outline: DeckOutline) -> bool:
    return any(s.kind not in _FRAME_KINDS for s in outline.slides)


def plan_outline(
    brief: Brief,
    manifest: TemplateManifest,
    strategy: Strategy,
    facts: FactsExtraction,
    skills: Optional[SkillsRegistry] = None,
    providers: Optional[ProviderRegistry] = None,
    target: Optional[int] = None,
    raw: Optional[list] = None,
) -> tuple[DeckOutline, list[str]]:
    """The deck's plan: the outline_planner skill's, grounded in the brief (grounding.ground_outline: no figure,
    unit, name, placeholder or slide the brief does not support) and trimmed to at most `target` slides — never padded
    to it; the rules' plan (basic_outline) when there is no model, the model fails, or nothing it planned is grounded.
    `raw` collects the planner's answers as written (planner_raw.json of the run)."""
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
        _keep_raw(raw, "plan", res)
        planned: PlannedDeck = res.parsed
    except (ProviderError, ValueError, KeyError) as e:
        _keep_raw(raw, "plan", error=e)
        warnings.append(f"outline_planner failed, deterministic outline used: {str(e)[:160]}")
        return basic_outline(brief, facts, strategy, target), warnings
    problem = unusable_plan(planned)
    if problem:
        warnings.append(f"outline_planner answer rejected ({problem}), deterministic outline used")
        return basic_outline(brief, facts, strategy, target), warnings
    hard_limit = bool(brief.slide_count)  # «не более N слайдов» / slides: N in the brief is binding
    index = BriefIndex.of(brief)
    outline = DeckOutline(title=planned.title or brief.title_hint or "Презентация", subtitle=planned.subtitle, audience=brief.audience, purpose=brief.purpose, strategy=strategy.name, language=brief.language, planned_by="model", slides=planned.slides, facts=facts.facts, series=facts.series, tables=facts.tables)
    # what the brief does not say goes before anything is laid out; the deck may come out shorter than the target
    outline, grounded = ground_outline(outline, brief, index)
    warnings.extend(grounded)
    if not _has_content(outline):
        warnings.append("outline_planner answer rejected (nothing in it is grounded in the brief), deterministic outline used")
        return basic_outline(brief, facts, strategy, target), warnings
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
                _keep_raw(raw, "repair", res2)
                planned2: PlannedDeck = res2.parsed
                if unusable_plan(planned2):
                    raise ValueError(f"repaired plan rejected ({unusable_plan(planned2)})")
                repaired = outline.model_copy(deep=True)
                repaired.slides = planned2.slides
                repaired, grounded2 = ground_outline(repaired, brief, index)
                if not _has_content(repaired):
                    raise ValueError("repaired plan rejected (nothing in it is grounded in the brief)")
                outline = validate_outline(repaired, manifest, target, skills, providers, hard_limit=hard_limit)
                warnings.append(f"fact_checker found {len(errors)} issues; outline regenerated once")
                warnings.extend(grounded2)
            except (ProviderError, ValueError, KeyError) as e:
                if not isinstance(e, ValueError) or "rejected" not in str(e):
                    _keep_raw(raw, "repair", error=e)
                warnings.append(f"repair pass failed: {str(e)[:120]}")
    except (ProviderError, ValueError, KeyError) as e:
        warnings.append(f"fact_checker skipped: {str(e)[:120]}")
    # the condenser (a model) may have rewritten a line: the final plan is checked once more
    outline, last = ground_outline(outline, brief, index)
    warnings.extend(last)
    return polish_plan(outline), warnings
