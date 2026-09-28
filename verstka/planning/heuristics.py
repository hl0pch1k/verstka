"""Deterministic reading of a brief: sections, steps, labelled items, enumerations, KPI callouts and chart-ready series.

This is what the offline planner uses instead of a model (and what the fact registry falls back to). The rules are
language-light on purpose: they rely on punctuation, numbers and a handful of Russian/English markers, never on the
wording of a particular brief.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from verstka.ru import clip_words
from verstka.schemas.outline import Series, TableData

# ------------------------------------------------------------------ text primitives

# a sentence ends at «.!?» before a capital, a quote or a digit — not after an initial («J. Fry & Sons», «А. С. Пушкин»)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])(?<!(?<![\w])[A-ZА-ЯЁ]\.)\s+(?=[A-ZА-ЯЁ«\"0-9])")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_RULE_RE = re.compile(r"^\s*\|?\s*:?-{2,}")
_NUMBER_RE = re.compile(
    r"(?<![\w.,])(?P<num>[+\-−]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|[+\-−]?\d+(?:[.,]\d+)?)"
    r"(?:\s?(?P<unit>%|млн|млрд|тыс\.?|ч(?:ас(?:ов|а)?)?\b|мин(?:ут)?\b|дн(?:ей|я)?\b|недел[ьяи]\b|мес(?:яц(?:а|ев)?)?\b|лет\b|год(?:а)?\b|раз(?:а)?\b|шт\.?|₽|руб(?:\.|лей|ля)?|\$|x|×))?"
)
_RANGE_RE = re.compile(r"(?<![\w.,])(?P<a>\d+(?:[.,]\d+)?)\s?[–—-]\s?(?P<b>\d+(?:[.,]\d+)?)(?:\s?(?P<unit>%|секунд[аы]?|сек|с\b|мин(?:ут[аы]?)?|ч(?:ас(?:ов|а)?)?\b|дн(?:ей|я)?\b|мес(?:яц(?:а|ев)?)?\b|млн|млрд|тыс\.?))?")
_OF_RE = re.compile(r"(?P<a>\d+(?:[.,]\d+)?)\s+(?:[а-яё]+\s+)?из\s+(?P<b>\d+(?:[.,]\d+)?)", re.I)
_FROM_TO_RE = re.compile(r"\bс\s+(?P<a>\d[\d\s]*(?:[.,]\d+)?\s?%?)\s+до\s+(?P<b>\d[\d\s]*(?:[.,]\d+)?\s?%?)", re.I)
_FT_UNITS = r"минут[ыа]?|мин|секунд[ыа]?|сек|час(?:ов|а)?|ч|дн(?:ей|я)|недел[ьиюя]|месяц(?:ев|а)?|мес|млн ₽|млрд ₽|тыс\. ₽|млн|млрд|тыс\.?|₽|руб(?:лей|ля|\.)?|раз(?:а)?|шт\.?"
_FT_UNIT_RE = re.compile(rf"\s?({_FT_UNITS})(?![\wё])", re.I)
# a change the brief writes itself inside one clause: «47 → 29 минут», «было 47 минут, стало 29». Nothing else is a
# change — two figures said in different sentences are never joined into one («A → B» is not made up)
_CHANGE_NUM = r"\d+(?:[\u00a0\u202f ]\d{3})*(?:[.,]\d+)?(?:\s?%)?"
_ARROW_RE = re.compile(rf"(?<![\w.,])(?P<a>{_CHANGE_NUM})\s*(?:→|->)\s*(?P<b>{_CHANGE_NUM})")
# «было 47 минут в день, стало 29», «было 120 заявок в день, стало 300»: the start may carry a few words of its own
# (what it counts, per what) before «стало», never a figure or a clause boundary
_WAS_NOW_RE = re.compile(
    rf"(?<![\wё])был[оаи]?\s+(?P<a>{_CHANGE_NUM})(?:\s?(?P<ua>{_FT_UNITS})(?![\wё]))?(?P<ta>(?:\s+[^\s\d,;:.!?—–]+){{0,4}}?)"
    rf"\s*[,;]?\s*(?:а\s+)?стал[оаи]?\s+(?P<b>{_CHANGE_NUM})",
    re.I,
)
_WAS_TAIL_RE = re.compile(r"(?<![\wё])был[оаи]?\s+\d[^,;]*$", re.I)
_NOW_HEAD_RE = re.compile(r"^(?:а\s+)?стал[оаи]?\s+\d", re.I)
_WAS_LEAD_RE = re.compile(r"^был[оаи]?\s+\d", re.I)  # «было 5 дней, стало 2 дня»: a change without its subject
_UP_RE = re.compile(r"\b(вырос\w*|увеличил\w*|рост\w*|прибав\w*|повысил\w*)\b", re.I)
_DOWN_RE = re.compile(r"\b(снизил\w*|сократил\w*|упал\w*|уменьшил\w*|сниж\w*)\b", re.I)
_PREPS = {"в", "во", "на", "до", "с", "со", "за", "по", "от", "из", "к", "ко", "у", "при", "о", "об", "для", "через", "без", "под", "над"}
_FILLERS = {"только", "всего", "около", "примерно", "почти", "более", "менее", "свыше", "лишь", "уже", "ещё", "еще", "также", "же", "—", "–", "-"}
_VERB_END_RE = re.compile(
    r"(?:ает|яет|ают|яют|ует|уют|еет|еют|ется|ются|ится|ятся|ила|ило|или|ала|ало|али|ела|ело|ели|яла|яло|яли|ыла|ыло|ыли|ула|уло|ули"
    r"|лся|лась|лось|лись|сла|сло|шла|шло|шли|рос)$"
    r"|^(стоит|ставят|ставит|тратят|тратит|дают|даёт|дает|идёт|идет|растёт|растет|требует|требуют|работает|составляет|составляют|превращает|предлагает|присылает)$",
    re.I,
)
_STEP_RE = re.compile(
    r"^(?P<marker>(?:неделя|этап|шаг|фаза|месяц|квартал|спринт|день|год|волна|week|step|stage|phase|sprint|q[1-4])\b[^:]{0,40}?"
    r"|далее|затем|потом|после этого|then|next)(?:\s*:\s*|\s+[—–-]\s+)(?P<text>.+)$",
    re.I,
)
# «Метка: текст»; a colon with digits on both sides is a time or a ratio («в 10:30», «1:1»), not a label — while
# «Вариант 2: базовый» and «Бюджет:25 млн ₽» still are labels
_LABELLED_RE = re.compile(r"^(?P<label>[^:.;]{2,40}?)\s*:(?!(?<=\d:)\d)\s*(?P<text>.{3,})$")
_LABEL_COLON_RE = re.compile(r":(?!(?<=\d:)\d)")
_CLAUSE_WORDS = {"но", "а", "из-за", "поэтому", "что", "который", "которая", "которые", "чтобы", "так", "однако", "хотя", "если", "где", "когда"}
_CURRENCY_AFTER_RE = re.compile(r"^(рублей|рубля|руб\.?|₽|долларов|\$|евро|€)\s*", re.I)
_TOTAL_RE = re.compile(r"^\s*(итого|всего|total|сумма)\b", re.I)


def split_sentences(text: str) -> list[str]:
    out = []
    for part in _SENT_SPLIT_RE.split(text.strip()):
        p = part.strip()
        if len(p) > 3:
            out.append(p)
    return out


# a line that ends with an abbreviation keeps its period: «на 10 п. п.», «315 тыс.», «2026 г.»
ABBR_END_RE = re.compile(r"(?:^|[\s(\d])(?:п\.\s?п|тыс|руб|млн|млрд|трлн|г|гг|др|пр|т\.\s?е|т\.\s?д|т\.\s?п|ед|чел|шт|мин|сек|коп|долл|кв)\.$", re.I)


def strip_end(text: str) -> str:
    t = text.strip()
    if ABBR_END_RE.search(t):
        return t
    return t.rstrip(".;:").strip()


def cap_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def label_split(text: str) -> Optional[tuple[str, str]]:
    """«Итоги пилота: время сократилось …» → («Итоги пилота», «время сократилось …»); None when the text has no label
    colon — a colon between digits («Созвон в 10:30 занимает 45 минут», «1:1») is part of a figure."""
    m = _LABEL_COLON_RE.search(text)
    return (text[: m.start()], text[m.end() :]) if m else None


def words(text: str) -> list[str]:
    return text.split()


def short(text: str, max_words: int) -> str:
    """Cut to max_words at a clause boundary when possible (no ellipsis: slides are not snippets)."""
    ws = text.split()
    if len(ws) <= max_words:
        return strip_end(text)
    cut = clip_words(text, max_words)
    m = list(re.finditer(r"[,;:—–]\s", cut))
    if m and m[-1].start() > len(cut) * 0.5:
        cut = cut[: m[-1].start()]
    return strip_end(cut.rstrip(" ,;:—–-"))


def parse_number(text: str) -> Optional[float]:
    t = text.strip().replace(" ", " ").replace(" ", " ")
    m = re.search(r"[+\-−]?\d[\d ]*(?:[.,]\d+)?", t)
    if not m:
        return None
    try:
        return float(m.group(0).replace(" ", "").replace(",", ".").replace("−", "-"))
    except ValueError:
        return None


def fmt_number(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        s = f"{int(round(v)):,}".replace(",", " ")
    else:
        s = f"{v:.1f}".replace(".", ",")
    return s


# ------------------------------------------------------------------ sections


@dataclass
class Section:
    title: str
    sentences: list[str] = field(default_factory=list)
    tables: list[TableData] = field(default_factory=list)
    table_leads: list[str] = field(default_factory=list)  # the line right before each table («Динамика …:»)
    listed: bool = False  # the lines of a «Метка:» lead over its list: headed by the label, said as its items
    heading: bool = False  # named by a markdown heading («## Что просим»): every line under it belongs to it
    # how the lines were typed (cap_first forms of the sentences): one written on the line of the sentence before it
    # («Результаты: … . NPS вырос до 64.»), one typed as a list item («- бюджет: 14,5 млн ₽;»)
    joined: set[str] = field(default_factory=set)
    marked: set[str] = field(default_factory=set)


_PARA_LABEL_RE = re.compile(r"^(?P<label>[A-ZА-ЯЁ][^:.;!?\d]{1,40}?)\s*:\s+(?P<text>\S.*)$")
_ASK_RE = re.compile(r"^(просим|прошу|предлагаем утвердить|предлагаем одобрить|нужно решение|решение, которое)", re.I)
_TITLE_LABEL_RE = re.compile(r"^(например|пример|тема|название|заголовок|title|topic|example)$", re.I)


def _plain_title(par: str) -> str:
    """The first line of a plain brief as the deck title: «Тема: уточнение» keeps the theme when both halves are real."""
    t = strip_end(par)
    head, sep, tail = t.partition(": ")
    if sep and 2 <= len(head.split()) and len(tail.split()) >= 2 and len(head) <= 90:
        return head.strip()
    return t


def _plain_sections(lines: list[str]) -> tuple[Optional[str], dict[int, str], set[int], dict[int, str]]:
    """Structure of a brief written as plain paragraphs (no markdown headings): the title line, section titles by
    line index («Проблема: …», a «Результаты пилота (…):» lead, a closing «Просим …»), lines to drop (the title) and
    lines to read without their first words (a title marker taken off).

    A paragraph is one section: labelled lines typed under its first line («Бюджет: …», «Срок: …») stay its
    sentences — the planner cuts them into sections of their own only for a short brief. A first line labelled
    «Например:», «Тема:» or «Название:» is the title, not a section."""
    starts = [i for i, ln in enumerate(lines) if ln.strip() and (i == 0 or not lines[i - 1].strip())]
    heads: dict[int, str] = {}
    for i in starts:
        s = lines[i].strip()
        if _TABLE_ROW_RE.match(lines[i]) or _STEP_RE.match(s):
            continue
        m = _PARA_LABEL_RE.match(s)
        if m and len(m.group("label").split()) <= 5:
            heads[i] = cap_first(m.group("label").strip())
        elif s.endswith(":") and len(s.split()) <= 12:
            heads[i] = cap_first(strip_end(re.sub(r"\s*\([^)]*\)", "", s)))
        elif _ASK_RE.match(s) and heads:
            heads[i] = "Что просим"
    title: Optional[str] = None
    drop: set[int] = set()
    rewrite: dict[int, str] = {}
    first = starts[0] if starts else None
    marker = _PARA_LABEL_RE.match(lines[first].strip()) if first is not None and first in heads else None
    if marker and _TITLE_LABEL_RE.match(marker.group("label").strip()):
        # «Например: итоги пилота «Умные сводки» за квартал.» — the marker is not a section, the text is the title
        text = marker.group("text").strip()
        sents = split_sentences(text) or [text]
        del heads[first]
        title = cap_first(_plain_title(sents[0]))
        if len(sents) > 1:
            rewrite[first] = " ".join(sents[1:])
        else:
            drop.add(first)
    elif first is not None and first not in heads and len(starts) >= 3 and len(lines[first].strip()) <= 200 and len(split_sentences(lines[first])) <= 1:
        title = _plain_title(lines[first].strip())
        drop.add(first)
    return title, heads, drop, rewrite


def parse_sections(text: str) -> tuple[Optional[str], list[Section]]:
    """(# title, [## sections]) — paragraphs become sentences, markdown tables are parsed with their lead line.
    A brief without markdown headings is read by paragraphs: first line → title, «Метка: …» → section."""
    title: Optional[str] = None
    sections: list[Section] = []
    cur: Optional[Section] = None
    lines = text.splitlines()
    plain_heads: dict[int, str] = {}
    drop: set[int] = set()
    rewrite: dict[int, str] = {}
    if not any(ln.lstrip().startswith("#") for ln in lines):
        title, plain_heads, drop, rewrite = _plain_sections(lines)
    i = 0
    last_text = ""
    while i < len(lines):
        raw = rewrite.get(i, lines[i])
        s = raw.strip()
        if i in drop:
            i += 1
            continue
        if i in plain_heads:
            cur = Section(title=plain_heads[i])
            sections.append(cur)
            m = _PARA_LABEL_RE.match(s)
            if m and cap_first(m.group("label").strip()) == plain_heads[i]:
                s = cap_first(m.group("text").strip())
                raw = s
        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            head = s.lstrip("#").strip()
            if level == 1 and title is None:
                title = head
            else:
                cur = Section(title=head, heading=True)
                sections.append(cur)
            i += 1
            continue
        m = _TABLE_ROW_RE.match(raw)
        if m and i + 1 < len(lines) and _TABLE_RULE_RE.match(lines[i + 1]):
            header = [c.strip() for c in m.group(1).split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and _TABLE_ROW_RE.match(lines[j]):
                rows.append([c.strip() for c in _TABLE_ROW_RE.match(lines[j]).group(1).split("|")])
                j += 1
            if cur is None:
                cur = Section(title="")
                sections.append(cur)
            lead = last_text if last_text.endswith(":") else ""
            if lead and cur.sentences and cur.sentences[-1] == strip_end(lead) + ":":
                cur.sentences.pop()
            cur.tables.append(TableData(columns=header, rows=rows, source_span=raw.strip(), caption=strip_end(lead) or None))
            cur.table_leads.append(strip_end(lead))
            i = j
            last_text = ""
            continue
        if s:
            if cur is None:
                cur = Section(title="")
                sections.append(cur)
            body = s.lstrip("-•* ").strip()
            item = body != s
            if re.match(r"^\d+[.)]\s", body):
                body = re.sub(r"^\d+[.)]\s*", "", body)
                item = True
            parts = split_sentences(body) if not body.endswith(":") else [body]
            cur.sentences.extend(parts)
            cur.joined.update(cap_first(p.strip()) for p in parts[1:])
            if item:
                cur.marked.update(cap_first(p.strip()) for p in parts)
            last_text = body
        i += 1
    return title, [s for s in sections if s.sentences or s.tables]


# ------------------------------------------------------------------ steps, labelled items, enumerations


@dataclass
class Item:
    title: str
    text: str = ""


def steps_of(sentences: list[str]) -> tuple[list[Item], list[str]]:
    """«Неделя 1: …», «Этап 2, месяц 3–4: …», «Далее: …» → ordered steps; the rest is returned untouched. A roadmap
    written in one line («Q3 — …; Q4 — …; Q1 2027 — …») counts too when every «;» part is a step."""
    steps: list[Item] = []
    rest: list[str] = []
    for s in sentences:
        parts = [p.strip() for p in s.split(";") if p.strip()]
        inline = len(parts) > 1 and all(_STEP_RE.match(p) for p in parts)
        for part in parts if inline else [s]:
            m = _STEP_RE.match(part.strip())
            if m:
                steps.append(Item(title=cap_first(strip_end(m.group("marker"))), text=cap_first(strip_end(m.group("text")))))
            else:
                rest.append(part)
    if len(steps) < 3:
        return [], sentences
    return steps, rest


def labelled_items(sentences: list[str], min_items: int = 2) -> tuple[list[Item], list[str]]:
    """«Совместимость: 2 из 140 отчётов …» → (title, text) pairs when at least `min_items` sentences share the form
    (two for cards; the short-brief planner also takes a single labelled line)."""
    items: list[Item] = []
    rest: list[str] = []
    for s in sentences:
        m = _LABELLED_RE.match(s.strip())
        if m and len(m.group("label").split()) <= 4 and not _STEP_RE.match(s.strip()):
            items.append(Item(title=cap_first(strip_end(m.group("label"))), text=cap_first(strip_end(m.group("text")))))
        else:
            rest.append(s)
    if len(items) < min_items:
        return [], sentences
    return items, rest


def enumeration(sentence: str) -> tuple[Optional[str], list[str]]:
    """«Программа из 4 модулей: SQL и Python, потоковая обработка, …» or «превращает …, предлагает …, эскалирует … и
    присылает …» → (lead, parts) when there are at least three parts of two or more words."""
    s = strip_end(sentence)
    lead = None
    body = s
    if label_split(s):
        lead, body = label_split(s)
        lead = strip_end(lead)
    parts = [p.strip() for p in re.split(r",\s+(?![^()]*\))", body) if p.strip()]
    if any(p.split()[0].lower() in _CLAUSE_WORDS for p in parts[1:] if p.split()):
        return None, []  # «…23%, но в пиковые дни 97%, из-за чего …» is one statement, not a list
    if parts and " и " in parts[-1] and len(parts) >= 2:
        head, tail = parts[-1].rsplit(" и ", 1)
        if len(tail.split()) >= 2 and _VERB_END_RE.search(tail.split()[0].lower()):
            parts = parts[:-1] + [head.strip(), tail.strip()]
    if len(parts) < 3 or any(len(p.split()) < 2 and not lead for p in parts):
        return None, []
    if not lead:
        # no colon: the subject («Функция „Умные напоминания“») stays in front of the first verb
        first = parts[0].split()
        verb_at = next((i for i, w in enumerate(first) if _VERB_END_RE.search(w.lower()) and i > 0), None)
        if verb_at:
            lead = " ".join(first[:verb_at])
            parts[0] = " ".join(first[verb_at:])
    return lead, [cap_first(strip_end(p)) for p in parts]


# ------------------------------------------------------------------ numbers


@dataclass
class Kpi:
    value: str
    label: str
    sentence: str
    number: float
    clause: str = ""  # the part of the sentence the figure was read from


def _clean_before(text: str) -> list[str]:
    ws = [w for w in text.split() if w.lower().strip(",") not in _FILLERS]
    ws = [w for w in ws if not (_VERB_END_RE.search(w.lower().strip(",")) and len(w) > 4)]
    while ws and ws[-1].lower().strip(",") in _PREPS:
        ws.pop()
    return ws


def _after_last_verb(text: str) -> list[str]:
    ws = text.split()
    idx = max((i for i, w in enumerate(ws) if _VERB_END_RE.search(w.lower().strip(",")) and len(w) > 4), default=None)
    if idx is None:
        return []
    tail = [w for w in ws[idx + 1 :] if w.lower() not in _FILLERS]
    while tail and tail[-1].lower() in _PREPS:
        tail.pop()
    return tail


def clauses(sentence: str) -> list[str]:
    """Clauses that each carry their own figure: «оценка 4,6 из 5, 91% участников …» → two clauses."""
    parts = [p.strip() for p in re.split(r"[,;:]\s+|\s[—–]\s", strip_end(sentence)) if p.strip()]
    with_numbers = [p for p in parts if re.search(r"\d", p)]
    if len(with_numbers) <= 1:
        return [strip_end(sentence)]
    out = []
    for p in parts:
        ws = p.split()
        if ws and ws[0].lower() in _CLAUSE_WORDS | {"и"}:
            p = " ".join(ws[1:])
        if re.search(r"\d", p):
            out.append(p)
    return out


def kpis_of(sentence: str, text: Optional[str] = None) -> list[Kpi]:
    """The figures of one sentence, clause by clause, each as it is written. «было 47 минут, стало 29» is one change
    («47 минут → 29»), not two figures; a figure of another sentence is never joined to one of this sentence. `text`
    (the brief) tells a change's label that starts with a common word from one that starts with a name (kpi_of)."""
    parts: list[str] = []
    for c in clauses(sentence):
        joined = f"{parts[-1]}, {c}" if parts else ""
        if parts and _NOW_HEAD_RE.match(c) and _WAS_TAIL_RE.search(parts[-1]) and _WAS_NOW_RE.search(joined):
            parts[-1] = joined  # joined only when the two read as one change: each figure is kept otherwise
        else:
            parts.append(c)
    out = []
    for c in parts:
        k = kpi_of(c, text)
        if k is not None:
            k.sentence = sentence
            k.clause = c
            out.append(k)
    return out


# a figure's unit written as a word of its own («120 млн ₽ за год» → «млн», «₽»): part of the figure, never its label
_UNIT_WORD_RE = re.compile(r"^(₽|\$|€|%|руб\w*|долл\w*|евро|млн|млрд|тыс\.?|минут\w*|мин\.?|час\w*|ч\.?|дн\w*|дней|секунд\w*|сек\.?|недел\w*|месяц\w*|мес\.?)$", re.I)


# the short units kpi_of writes for words of the brief: «3 мес» stands for «3 месяца», «8–25 с» for «8–25 секунд»
_UNIT_FORMS = {
    "мес": r"мес(?:яц(?:а|ев)?)?", "дн": r"(?:дн(?:ей|я)?|день)", "ч": r"ч(?:ас(?:ов|а)?)?", "мин": r"мин(?:ут[аы]?)?",
    "нед": r"нед(?:ел[ьиюя])?", "г": r"г(?:од(?:а|у)?)?", "с": r"с(?:ек(?:унд[аы]?)?)?",
}


def figure_span(value: str, text: str) -> Optional[tuple[int, int]]:
    """Where a figure («3 мес», «47 минут», «14,5 млн ₽») is written in a text, as whole words: the short unit of a
    plan covers the unit written in full («3 мес» → «3 месяца»), and a figure is never found inside another word or
    number («3 мес» is not in «13 месяцев», «5» is not in «15» or «0,5»). None when it is not there."""
    v = value.strip()
    if not v:
        return None
    toks = v.split()
    pat = r"\s+".join(re.escape(t) for t in toks[:-1])
    last = toks[-1]
    last_pat = _UNIT_FORMS.get(last, re.escape(last)) if len(toks) > 1 else re.escape(last)
    pat = (pat + r"\s+" if pat else "") + last_pat
    m = re.search(rf"(?<![\wё])(?<!\d[.,]){pat}(?![\wё]|[.,]\d)", text, re.I)
    return (m.start(), m.end()) if m else None


_BARE_NUMBER_RE = re.compile(r"^[+\-−]?\d[\d\s  ]*(?:[.,]\d+)?$")
_UNIT_ONLY_RE = re.compile(r"^(?:₽|\$|€|%|руб\.?|рубл(?:ей|я|ь)|тыс\.?(?:\s*₽)?|млн(?:\s*₽)?|шт\.?|п\.\s*п\.)$", re.I)  # a unit, never a label


def is_statement(text: str) -> bool:
    """«Сотрудники тратят 47 минут …» reads as a heading; «120 млн ₽ за год» (a figure first) and «Снизились до 80 млн
    ₽» (a verb first — its subject was the label cut off before the colon) do not."""
    ws = text.split()
    if len(ws) < 3 or re.match(r"^[+\-−×]?\d", ws[0]):
        return False
    if _WAS_LEAD_RE.match(text.strip()):
        return False  # «было 5 дней, стало 2 дня» says a change without its subject: the figures, not a heading
    first = ws[0].lower().strip(",«»\"")
    return not (_VERB_END_RE.search(first) and len(first) > 4)


def _label_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[\wё]+", text.lower()) if len(w) > 2]


def _written_lower(word: str, text: str) -> bool:
    """The text writes this word in lowercase somewhere: a common word («время»), not a name («Москва», «Сбер»)."""
    w = word.lower()
    return bool(w) and re.search(rf"(?<![\wё]){re.escape(w)}(?![\wё])", text) is not None


def name_case(label: str, text: str) -> str:
    """A label whose first word the brief writes only with a capital, and at least once inside a sentence, after a
    label's colon or in quotes («в Москве», «Результаты: Сбер снизил …», «пилот «Умные сводки»»), gets its capital
    back: a name is never lowercased. A common word — one the brief also writes in lowercase, or only ever at the start
    of a sentence — is left as it is."""
    ws = label.split()
    if not ws or not ws[0][:1].islower() or _written_lower(ws[0], text):
        return label
    cap = ws[0][:1].upper() + ws[0][1:]
    stem = cap[: max(4, len(cap) - 2)]  # «Москва» is written «в Москве», «Сбер» — «у Сбера»
    if re.search(rf"(?:[\wё,:][ \t\u00a0]+|[«\"„(]){re.escape(stem)}", text):  # inside a line, not at its start
        return cap + label[len(ws[0]) :]
    return label


def label_beside(value: str, label: str, headline: str, text: Optional[str] = None) -> str:
    """A figure's label that does not repeat the heading above it — the words the slide shows under the figure. When
    the label is the heading's own sentence («оператор тратит в среднем 6,5 минуты» under «Оператор тратит в среднем
    6,5 минуты на одно обращение»), the words after the figure in the heading say what it measures («минуты на одно
    обращение»), else the words before it. A short name («NPS», «время ответа») is kept as it is. The planner and the
    composer both use this one rule, so the plan says what the slide will show.

    A heading's first word starts the label in lowercase only when it is a common word: `text` (the brief, for the
    planner) or else the label itself writes it in lowercase. A name keeps its capital («Сбер сэкономил на поддержке»)."""
    lw, hw = _label_words(label), set(_label_words(headline))
    if len(label.split()) <= 2 or not lw or sum(w in hw for w in lw) < 0.6 * len(lw):
        return label
    span = figure_span(value, headline)
    if span is None:
        return label
    tail = headline[span[1] :].strip(" ,.:;—-")
    if _UNIT_ONLY_RE.match(tail):
        return label  # «… до 330 ₽»: a unit after the figure is the figure's, never its label
    if re.search(r"\d", re.sub(r"(?<!\d)(?:1\d{3}|20\d{2})(?!\d)", "", tail)):
        tail = re.split(r"[,;:]\s|\s[—–]\s", tail)[0].strip(" ,.:;—-")  # the clause of this figure, not the next one's
    if len(tail.split()) >= 2 or (len(tail.split()) == 1 and _BARE_NUMBER_RE.match(value.strip())):
        return tail  # «минуты на одно обращение»; a bare number takes the one word it counts («12» → «человек»)
    before = headline[: span[0]]
    cut = [m.end() for m in re.finditer(r"\d(?:[\d\s  ]*(?:[.,]\d+)?)\s*(?:тыс\.?|млн\.?|млрд\.?|%|₽)?[^,;:—–\w]*[,;:—–]", before)]
    if cut:
        before = before[cut[-1]:]  # «…59,6 тыс. электромобилей, продано — 17,8 тыс.»: never another figure in the label
    head = before.strip(" ,.:;—-").split()
    while head and (head[-1].lower() in _PREPS or head[-1] in ("—", "–", "-")):
        head.pop()  # «Команда выросла до» → «Команда выросла»: a label never ends on a preposition or a dash
    if len(head) < 2 or any(re.match(r"^\d", w) and not re.fullmatch(r"(?:1\d{3}|20\d{2})", w) for w in head):
        return label
    whole = len(head) <= 6  # a clause start of six words or fewer is kept whole («Отдел продаж сократил время на отчёты»)
    out = " ".join(head if whole else head[-5:])
    if whole and out[:1].isupper() and not out[:2].isupper() and _written_lower(head[0].strip(",;:«»\"()"), label if text is None else text):
        out = out[:1].lower() + out[1:]  # the capital of the heading's first common word is not the label's
    return out


def kpi_of(sentence: str, text: Optional[str] = None) -> Optional[Kpi]:
    """The headline figure of a clause with a short label, or None when the clause has no real number. A change's label
    is its subject as written: with `text` (the brief) its first word is lowercased only when the brief also writes it
    in lowercase — a name keeps its capital («Сбер снизил расходы», «Москва сократила время ответа»)."""
    s = strip_end(sentence)
    m_ft = _FROM_TO_RE.search(s) or _ARROW_RE.search(s) or _WAS_NOW_RE.search(s)
    if m_ft:
        # a change written in the clause: «с 47 до 29 минут», «47 → 29 минут», «было 47 минут, стало 29 минут»
        a, b = strip_end(m_ft.group("a")), strip_end(m_ft.group("b"))
        # what changed is said in the clause of the change, not in a lead before a colon («Итоги пилота: время …»)
        before = re.split(r"[:;]\s", s[: m_ft.start()])[-1]
        # no subject before the change: what the start counts («было 120 заявок в день» → «заявок в день»), else no
        # label at all — never the clause itself, which says the figures again
        own = [w for w in (m_ft.groupdict().get("ta") or "").split() if w.lower() not in _FILLERS]
        label = " ".join(_after_last_verb(before)) or " ".join(_clean_before(before)) or " ".join(own)
        unit_b = _FT_UNIT_RE.match(s[m_ft.end():]) if not b.endswith("%") else None
        ub, ua = (unit_b.group(1) if unit_b else ""), (m_ft.groupdict().get("ua") or "")
        if ua and ua.lower() != ub.lower():
            value = f"{a} {ua} → {b} {ub}".strip()  # each end with its own unit, as written
        else:
            value = f"{a} → {b} {ub}" if ub else f"{a} → {b}"  # «с 47 до 29 минут» → «47 → 29 минут»
        label = short(label, 7)
        first = label.split()[0].strip("«»\"„“”()") if label.split() else ""
        if label[:1].isupper() and not label[:2].isupper() and (text is None or _written_lower(first, text)):
            label = label[:1].lower() + label[1:]
        return Kpi(value=value, label=label, sentence=sentence, number=parse_number(b) or 0.0)
    m_rg = _RANGE_RE.search(s)
    if m_rg and (parse_number(m_rg.group("a")) or 0) < (parse_number(m_rg.group("b")) or 0):
        # «8–25 секунд», «88–100 из 100»: a range is one figure
        unit = {"секунд": "с", "секунды": "с", "секунда": "с", "сек": "с", "минут": "мин", "минуты": "мин", "часов": "ч", "часа": "ч", "дней": "дн", "дня": "дн", "месяцев": "мес", "месяца": "мес"}.get(m_rg.group("unit") or "", m_rg.group("unit") or "")
        value = f"{m_rg.group('a')}–{m_rg.group('b')}{('' if unit == '%' else ' ') + unit if unit else ''}"
        before = s[: m_rg.start()]
        after = re.split(r"[,;:]\s", s[m_rg.end():].strip())[0].strip()
        after = re.sub(r"^из\s+\d+\s*", "", after)
        cur = _CURRENCY_AFTER_RE.match(after)
        if cur and unit in ("млн", "млрд", "тыс", "тыс.", ""):
            # «10–20 млн ₽ на …»: the currency is part of the figure, not the first word of its label
            sign = "₽" if cur.group(1).lower().startswith(("руб", "₽")) else ("$" if cur.group(1) in ("$", "долларов") else "€")
            value = f"{value} {sign}"
            after = after[cur.end() :]
        words_b = [w for w in before.split() if w.lower() not in _FILLERS]
        while words_b and words_b[-1].lower() in _PREPS:
            words_b.pop()
        label = " ".join(words_b + after.split()[:4]) or s
        label = short(label, 8)
        return Kpi(value=value, label=label[:1].lower() + label[1:] if label[:1].isupper() and not label[:2].isupper() else label, sentence=sentence, number=parse_number(m_rg.group("b")) or 0.0)
    m_of = _OF_RE.search(s)
    if m_of and (parse_number(m_of.group("a")) or 0) > (parse_number(m_of.group("b")) or 0):
        m_of = None  # «640 студентов из 12 университетов» is not «640 of 12»
    best = None
    for m in _NUMBER_RE.finditer(s):
        num = m.group("num")
        unit = (m.group("unit") or "").strip()
        v = parse_number(num)
        if v is None:
            continue
        if not unit and len(num.replace(" ", "").replace("\u00a0", "")) <= 1 and not (m_of and m_of.start() == m.start()):
            continue  # a lone digit («2 модуля», «в 3 шага») is not a KPI
        if re.fullmatch(r"(19|20)\d\d", num.strip()) and not unit:
            continue  # a year
        score = (2 if unit else 0) + (1 if v >= 10 else 0)
        if best is None or score > best[0]:
            best = (score, m, num, unit, v)
    if m_of is not None and (best is None or not best[3]):
        best = (9, m_of, m_of.group("a"), "", parse_number(m_of.group("a")) or 0.0)  # «6 случаях из 30» → «6 из 30»
    if best is None:
        return None
    _, m, num, unit, v = best
    start, end = m.start(), m.end()
    num = re.sub(r"[\u00a0\u202f]", " ", num).strip()
    if m_of and m_of.start() == start:
        value = f"{m_of.group('a')} из {m_of.group('b')}"
        end = m_of.end()
    else:
        unit_short = {"часов": "ч", "часа": "ч", "час": "ч", "дней": "дн", "дня": "дн", "рублей": "₽", "руб": "₽", "руб.": "₽", "раза": "×", "раз": "×",
                      "месяцев": "мес", "месяца": "мес", "месяц": "мес", "недели": "нед", "неделя": "нед", "неделю": "нед", "года": "г", "год": "г", "лет": "лет"}.get(unit, unit)
        rest = s[end:]
        cur = _CURRENCY_AFTER_RE.match(rest.strip())
        if cur and unit_short in ("млн", "млрд", "тыс", "тыс.", ""):
            unit_short = (unit_short + " " if unit_short else "") + ("₽" if cur.group(1).lower().startswith(("руб", "₽")) else ("$" if cur.group(1) in ("$", "долларов") else "€"))
            end += len(rest) - len(rest.lstrip()) + cur.end()
        if unit_short == "×":
            value = f"×{num}"
        elif unit_short == "%":
            value = f"{num}%"
        else:
            value = f"{num} {unit_short}".strip()
        before_txt = s[:start]
        # a signed figure is a change «на 34%»; «снизилась до 8%» is the level reached, shown as it is (8%, not −8%)
        delta = bool(re.search(r"(?<![\wё])на\s*$", before_txt, re.I))
        if unit_short == "%" and delta and _UP_RE.search(before_txt) and not value.startswith(("+", "-", "−")):
            value = "+" + value
        elif unit_short == "%" and delta and _DOWN_RE.search(before_txt) and not value.startswith(("+", "-", "−")):
            value = "−" + value
    before = s[:start].strip()
    after = re.split(r"\s+и\s+|[,;:]\s|\s[—–]\s", s[end:].strip().lstrip(",").strip())[0].strip()
    b_words = _clean_before(before)
    a_words = after.split()
    if not a_words:
        # the figure closes the clause: what precedes it is the label («Доля завершённых в срок задач выросла на»)
        ws = [w for w in before.split() if w.lower() not in _FILLERS]
        while ws and (ws[0].lower() in _CLAUSE_WORDS or ws[0].lower() in {"чего", "и"}):
            ws = ws[1:]
        while ws and ws[-1].lower() in _PREPS:
            ws.pop()
        if len(ws) >= 4 and _VERB_END_RE.search(ws[-1].lower()) and len(ws[-1]) > 4:
            ws.pop()  # «… на следующий год стоит» → «… на следующий год»
        label = " ".join(ws[-7:])
    elif a_words[0].lower() in _PREPS and b_words:
        label = " ".join(b_words + a_words)  # «Экономия в неделю на человека»
    elif not b_words or (len(b_words) <= 3 and b_words[0].lower() in _PREPS):
        label = " ".join(a_words + [w.lower() for w in b_words])  # «сотрудников из 37 компаний в пилоте»
    else:
        label = " ".join(w for w in s.split() if w.lower() not in _FILLERS)  # the clause itself reads best
    label = short(label or s, 8)
    while label.split() and label.split()[-1].lower() in _PREPS:
        label = " ".join(label.split()[:-1])
    if label[:1].isupper() and not label[:2].isupper():
        label = label[:1].lower() + label[1:]
    return Kpi(value=value, label=label, sentence=sentence, number=v)


# ------------------------------------------------------------------ tables → series


def _numeric_cells(cells: list[str]) -> Optional[list[float]]:
    vals = []
    for c in cells:
        if not re.search(r"\d", c):
            return None
        v = parse_number(c)
        if v is None:
            return None
        vals.append(v)
    return vals


def table_series(tbl: TableData, start_id: int = 1) -> tuple[list[Series], Optional[str]]:
    """Chart-ready series of a markdown table and the chart type, or ([], None) when the table is not a chart.

    One row of numbers across ≥3 columns is a time series (column chart). Several rows with 1–3 numeric columns of
    the same unit are a comparison per category (bar chart); a total row is left out of the chart.
    """
    cols = tbl.columns
    rows = [r for r in tbl.rows if r]
    if len(cols) < 2 or not rows:
        return [], None
    unit = None
    if "," in cols[0]:
        unit = cols[0].split(",", 1)[1].strip() or None
    if len(rows) == 1 and len(cols) >= 4:
        vals = _numeric_cells(rows[0][1:])
        if vals and len(vals) == len(cols) - 1:
            name = rows[0][0]
            u = name.split(",", 1)[1].strip() if "," in name else unit
            return [Series(id=f"s{start_id}", name=name, categories=cols[1:], values=vals, unit=u, source_span=tbl.source_span)], "column"
        return [], None
    body = [r for r in rows if not _TOTAL_RE.match(r[0] or "")]
    if len(body) < 3 or len(cols) > 4:
        return [], None
    series = []
    for j in range(1, len(cols)):
        cells = [r[j] if j < len(r) else "" for r in body]
        vals = _numeric_cells(cells)
        if vals is None:
            return [], None
        if len({("%" in c) for c in cells}) > 1:
            return [], None  # mixed units in one column
        series.append(Series(id=f"s{start_id + len(series)}", name=cols[j], categories=[r[0] for r in body], values=vals, unit=unit, source_span=tbl.source_span))
    return series, "bar"


def totals_of(tbl: TableData) -> Optional[tuple[str, list[str]]]:
    for r in tbl.rows:
        if r and _TOTAL_RE.match(r[0] or ""):
            return r[0], r[1:]
    return None


def times_word(value: float) -> str:
    """«в 2 раза», «в 10 раз», «в 3,4 раза»."""
    if abs(value - round(value)) > 1e-9:
        return "раза"
    n = int(round(value)) % 100
    return "раз" if 11 <= n <= 14 or n % 10 in (0, 1, 5, 6, 7, 8, 9) else "раза"


def series_headline(s: Series) -> str:
    """«Активные пользователи: с 1 200 до 12 400, рост в 10 раз» — the change a time series shows, as a conclusion."""
    name = s.name.split(",", 1)[0].strip()
    if len(s.values) >= 2 and s.values[0] > 0:
        a, b = s.values[0], s.values[-1]
        ratio = b / a
        if ratio >= 2:
            r = round(ratio) if ratio >= 3 else round(ratio, 1)
            return f"{name}: с {fmt_number(a)} до {fmt_number(b)}, рост в {fmt_number(r)} {times_word(r)}"
        return f"{name}: с {fmt_number(a)} до {fmt_number(b)}"
    return name
