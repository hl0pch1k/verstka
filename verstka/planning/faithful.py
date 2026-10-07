"""The author's own text, laid out as it is (Agent v2, the verbatim mode).

When the text is the user's own — the switch «Модель пишет тексты слайдов» is off, or no model is configured — a slide
shows the author's sentences whole, in the form its content asks for: a fenced code block as code, a note «[Место под
изображение: …]» as the place for that picture, «[… диаграмма: …]» as that chart with the note's data, «a → b → c» as
steps, «Первый этап … Второй этап …» as stages, paragraphs as blocks of text. No sentence is cut, no figure is taken
out of its sentence; what does not fit the slide stays in the speaker notes, which keep the slide's whole text.

This module reads a slide's text into its parts (`read_parts`, `read_slide`). The rules rely on punctuation, brackets,
arrows, code fences and a handful of Russian/English markers — never on one brief or one template.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import Optional

from verstka.planning import heuristics as H

# ------------------------------------------------------------------ sentences


_ABBR_BEFORE_RE = re.compile(
    r"(?:^|[\s(«\"])(?:т\.\s?е|т\.\s?д|т\.\s?п|т\.\s?к|и\.\s?о|см|ср|напр|рис|табл|стр|илл|гл|п|пп|г|гг|ул|д|кв|тыс|млн|млрд|руб|коп|долл|"
    r"мин|сек|ч|ок|прим|e\.\s?g|i\.\s?e|vs|etc|mr|mrs|dr|no|fig)\.$",
    re.I,
)
_INITIAL_RE = re.compile(r"(?:^|[\s(«\"])[A-ZА-ЯЁ]\.$")
# abbreviations that stand before a name or a figure and never end a sentence («ул. Тверская», «д. 7», «проф. Иванов»,
# «т. е. Москву», «Dr. Smith», «e.g. Walmart»): no split after them, whatever letter comes next
_NO_END_RE = re.compile(
    r"(?:^|[\s(«\"])(?:ул|пр|просп|пер|наб|пл|б-р|ш|д|корп|стр|оф|им|проф|акад|доц|т\.\s?е|т\.\s?к|т\.\s?н|напр|"
    r"dr|mr|mrs|ms|prof|st|e\.\s?g|i\.\s?e|vs|cf)\.$",
    re.I,
)
# «г.» with no figure before it is a city («в г. Москва»); after a year («в 2024 г.») it may end the sentence
_CITY_RE = re.compile(r"(?:^|[\s(«\"])г\.$")
_YEAR_ABBR_RE = re.compile(r"\d\s?гг?\.$")
# «и т. д.», «и т. п.», «и др.», «etc.» end a sentence like any other word
_ETC_RE = re.compile(r"т\.\s?[дп]\.$|(?:^|\s)др\.$|(?:^|\s)etc\.$", re.I)
# a dotted acronym («U.S.», «С.Ш.А.»)
_ACRONYM_RE = re.compile(r"(?:^|[\s(«\"])(?:[A-Za-zА-Яа-яЁё]\.){2,}$")
_OPEN = {"«": "»", "(": ")", "“": "”", "„": "“"}


def sentences(text: str) -> list[str]:
    """The text's sentences, each whole: a sentence ends at «.», «!», «?» or «…» before a capital, a digit or an opening
    quote — never inside «quotes» or (brackets), after an initial («А. С. Пушкин») or a short abbreviation («т. е.»)."""
    t = " ".join((text or "").split())
    out: list[str] = []
    depth: list[str] = []
    start = 0
    i = 0
    n = len(t)
    while i < n:
        ch = t[i]
        if ch in _OPEN:
            depth.append(_OPEN[ch])
        elif depth and ch == depth[-1]:
            depth.pop()
        elif ch == '"':
            if depth and depth[-1] == '"':
                depth.pop()
            elif i == 0 or not t[i - 1].isalnum():
                depth.append('"')
        if ch in ".!?…" and not depth:
            j = i + 1
            while j < n and t[j] in ".!?…»\")”":
                j += 1
            if j < n and t[j] == " ":
                k = j + 1
                nxt = t[k] if k < n else ""
                # (an initial or an abbreviation is the sentence's last few characters: a paragraph without a split point
                # never makes the check read the whole sentence again at every period)
                head = t[max(start, i - 11) : i + 1]
                kept = ch == "." and (
                    (not _ETC_RE.search(head) and (_NO_END_RE.search(head) or _ACRONYM_RE.search(head) or (_CITY_RE.search(head) and not _YEAR_ABBR_RE.search(head))))
                    or (_ABBR_BEFORE_RE.search(head) and not nxt.isupper())
                )
                if nxt and (nxt.isupper() or nxt.isdigit() or nxt in "«\"(“[") and not _INITIAL_RE.search(head) and not kept:
                    out.append(t[start:j].strip())
                    start = k
                    i = k
                    continue
            i = j
            continue
        i += 1
    tail = t[start:].strip()
    if tail:
        out.append(tail)
    return [s for s in out if s]


def words(text: str) -> int:
    return len((text or "").split())


# ------------------------------------------------------------------ parts of a slide's text


@dataclass
class Part:
    """One part of a slide's text, in the author's order.

    kind: "para" — a paragraph; "code" — a fenced code block (`text` the code as written, `lang` the fence's language,
    `label` the line that introduces it, «Пример записи, которую контроллер отправляет в журнал:»); "image" — a picture
    the author will add («[Место под изображение: вид теплицы сверху …]», `text` what it shows); "chart" / "table" —
    a note asking for one, with its data in `text`; "note" — any other bracketed note for the designer; "flow" — a
    sequence «датчики → проверка → решение» (`items`, `label` the words before the colon); "list" — lines with
    markers (`items`, `label` the lead line)."""

    kind: str
    text: str = ""
    label: str = ""
    lang: str = ""
    items: list[str] = field(default_factory=list)

    @cached_property
    def sentences(self) -> list[str]:
        return sentences(self.text) if self.kind == "para" else []


_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([\w+#.\-]*)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[—–\-•*·▪◦]|\d{1,2}[.)])\s+(?P<x>\S.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_ARROW_SPLIT_RE = re.compile(r"\s*(?:→|->|⟶|⇒|➔|➜|➝|—>|–>)\s*")
_NOTE_RE = re.compile(r"^\[(?P<body>[^\[\]]{3,})\]\s*[.;]?$", re.S)
_INLINE_NOTE_RE = re.compile(r"\[(?P<body>[^\[\]]{3,}?)\]")

# what a note asks for, by the words of its label («Место под изображение», «Сравнительные столбчатые графики»)
_IMAGE_WORDS_RE = re.compile(
    r"изображени|фото|картинк|иллюстрац|скриншот|снимок|снимк|рисун|схем[аыуе]|визуализац|макет|мокап|инфографик|"
    r"\bimage|\bphoto|\bpicture|screenshot|illustration|\bmock-?up",
    re.I,
)
_CHART_WORDS_RE = re.compile(r"диаграмм|график|гистограмм|\bchart|\bgraph|\bplot\b", re.I)
_TABLE_WORDS_RE = re.compile(r"таблиц|\btable\b", re.I)


def _note_kind(label: str, body: str) -> str:
    head = label or body[:80]
    if _CHART_WORDS_RE.search(head):
        return "chart"
    if _TABLE_WORDS_RE.search(head):
        return "table"
    if _IMAGE_WORDS_RE.search(head):
        return "image"
    return "note"


def _note_part(body: str) -> Part:
    body = " ".join(body.split())
    label, sep, rest = body.partition(":")
    if not sep or len(label.split()) > 8:
        label, rest = "", body
    kind = _note_kind(label.strip(), rest.strip())
    return Part(kind=kind, text=rest.strip(), label=label.strip())


def _flow_part(text: str) -> Optional[Part]:
    """«Последовательность работы: датчики → проверка показаний → … → запись результата в журнал.» → its steps."""
    if len(_ARROW_SPLIT_RE.findall(text)) < 2:
        return None
    label = ""
    body = text.strip()
    first = _ARROW_SPLIT_RE.search(body)
    colon = body.rfind(":", 0, first.start()) if first else -1
    if colon > 0:
        label, body = body[:colon].strip(), body[colon + 1 :].strip()
    steps = [H.strip_end(x.strip()) for x in _ARROW_SPLIT_RE.split(body)]
    steps = [H.cap_first(x) for x in steps if x]
    if len(steps) < 3 or any(words(x) > 12 for x in steps):
        return None
    return Part(kind="flow", items=steps, label=H.strip_end(label))


def _flow_split(text: str) -> list[Part]:
    """A paragraph whose sentence lays out a sequence «а → б → в»: the sentences before it, the sequence, the sentences
    after it — each a part of its own (the sentence's words before the colon are the sequence's label). Any other
    paragraph is one part."""
    if len(_ARROW_SPLIT_RE.findall(text)) >= 2:
        ss = sentences(text)
        for k, s in enumerate(ss):
            flow = _flow_part(s)
            if flow is None:
                continue
            out = [Part(kind="para", text=" ".join(ss[:k]))] if ss[:k] else []
            out.append(flow)
            if ss[k + 1 :]:
                out.append(Part(kind="para", text=" ".join(ss[k + 1 :])))
            return out
    return [Part(kind="para", text=text)]


def _ends_statement(line: str) -> bool:
    return line.rstrip().endswith((".", "!", "?", "…", ";", ":", "»", "\""))


# a line that breaks inside a sentence ends on a word that cannot end one («… офис в» / «Москве в 2024 году»)
_OPEN_END_RE = re.compile(
    r"(?:^|\s)(?:в|во|на|с|со|к|ко|по|о|об|обо|у|за|из|от|до|для|при|про|без|под|над|и|а|но|или|либо|что|как|чтобы|если|"
    r"когда|где|не|ни|же|the|a|an|of|to|and|or|in|on|at|for|with|by|from)$",
    re.I,
)


def _short_unit(line: str, nxt: Optional[str]) -> bool:
    """A short line without a final mark before a line that starts anew (a capital, a figure, a quote): a unit of its
    own — the label of the paragraph under it («Подготовка» / «Мы описали процессы…») or an item of a list written
    without markers («Прозрачность» / «Скорость») — not the first half of a sentence the line broke."""
    t = line.strip()
    if _ends_statement(t) or words(t) > 8 or t.endswith((",", "—", "–", "-", "(")) or _OPEN_END_RE.search(t):
        return False
    if nxt is None:
        return True
    n = nxt.strip()
    return bool(n) and (n[0].isupper() or n[0].isdigit() or n[0] in "«\"(“")


def _block_parts(lines: list[str]) -> list[Part]:
    """The parts of one block of lines (between blank lines)."""
    raw = [ln.rstrip() for ln in lines if ln.strip()]
    if not raw:
        return []
    joined = " ".join(ln.strip() for ln in raw)
    m = _NOTE_RE.match(joined)
    if m:
        return [_note_part(m.group("body"))]
    if len(raw) >= 2 and all(_TABLE_ROW_RE.match(ln) for ln in raw):
        return [Part(kind="table", text="\n".join(raw), label="")]
    marked = [_LIST_RE.match(ln) for ln in raw]
    if sum(1 for x in marked if x) >= 2:
        # the line right over the list introduces it (its label: «Исходные показатели:»); the lines before that one are
        # a paragraph of their own — never the label (the shop's area, seats and hours read as the list's heading, and
        # «Исходные показатели:» went into the next instruction)
        first = next(i for i, x in enumerate(marked) if x)
        before = [ln.strip() for ln in raw[:first]]
        lead = before[-1] if before else ""
        found: list[str] = []
        rest: list[str] = []
        for ln, x in zip(raw[first:], marked[first:]):
            if x:
                found.append(x.group("x").strip())
                continue
            t = ln.strip()
            # a wrapped item goes on: an indented line, or one after an item its line broke inside a sentence
            if found and not rest and (ln[:1] in (" ", "\t") or not _ends_statement(found[-1]) or t[:1].islower()):
                found[-1] = f"{found[-1]} {t}"
            else:
                rest.append(t)
        out = _block_parts(before[:-1]) if len(before) > 1 else []
        out.append(Part(kind="list", items=[H.strip_end(x) for x in found], label=H.strip_end(lead)))
        if rest:
            out.append(Part(kind="para", text=" ".join(rest)))
        return out
    # lines that each end a statement are paragraphs of their own («Цель: …» / «Метрика: …»); a line broken inside a
    # sentence joins the next one; a short line without a final mark before a line that starts anew is a unit of its
    # own (_short_unit): two or more in a row are a list written without markers, one over a paragraph is its label
    units: list[tuple[str, bool]] = []
    cur = ""
    for k, ln in enumerate(raw):
        t = ln.strip()
        nxt = raw[k + 1] if k + 1 < len(raw) else None
        if not cur and len(raw) >= 2 and _short_unit(t, nxt):
            units.append((t, True))
            continue
        cur = f"{cur} {t}".strip() if cur else t
        if _ends_statement(t):
            units.append((cur, False))
            cur = ""
    if cur:
        units.append((cur, False))
    paras: list[tuple[str, str]] = []  # (the paragraph, its label)
    k = 0
    while k < len(units):
        text, short = units[k]
        if short:
            run = [text]
            while k + 1 < len(units) and units[k + 1][1]:
                k += 1
                run.append(units[k][0])
            if len(run) >= 2:
                paras.append(("\x00list", "\x00".join(run)))
            elif k + 1 < len(units):
                k += 1
                paras.append((units[k][0], H.strip_end(run[0])))
            else:
                paras.append((run[0], ""))
        else:
            paras.append((text, ""))
        k += 1
    out: list[Part] = []
    for p, label in paras:
        if p == "\x00list":
            out.append(Part(kind="list", items=[H.strip_end(x) for x in label.split("\x00")]))
            continue
        notes = list(_INLINE_NOTE_RE.finditer(p))
        text = p
        for nm in notes:
            np_ = _note_part(nm.group("body"))
            if np_.kind != "note" or nm.group(0) == p:
                out.append(np_)
                text = text.replace(nm.group(0), " ")
        text = " ".join(text.split())
        if not text:
            continue
        got = _flow_split(text)
        if label and got and got[0].kind == "para":
            got[0].label = label
        out.extend(got)
    return out


# markdown the author pasted with the text: read, never shown («**жирный**», «[текст](адрес)», «> цитата», «### Подзаголовок»)
_MD_EMPH_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__|(?<![\w*])\*(?=[^\s*])([^*\n]+?)(?<=[^\s*])\*(?![\w*])")
_MD_LINK_RE = re.compile(r"\[([^\[\]\n]{1,200})\]\(\s*(\S+?)\s*\)")
_MD_SUBHEAD_RE = re.compile(r"^\s*#{1,6}\s+(?P<t>.+?)\s*#*\s*$")
_MD_QUOTE_RE = re.compile(r"^\s*(?:>\s?)+(?P<x>.*)$")
_MD_RULE_ROW_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _md_inline(line: str) -> str:
    """A line without markdown's inline marks: emphasis dropped, a link written as «текст (адрес)»."""

    def link(m: re.Match) -> str:
        label, url = m.group(1).strip(), m.group(2).strip()
        bare = re.sub(r"^https?://(?:www\.)?", "", url).rstrip("/")
        return label if label in (url, bare) else f"{label} ({url})"

    line = _MD_LINK_RE.sub(link, line)
    return _MD_EMPH_RE.sub(lambda m: m.group(1) or m.group(2) or m.group(3), line)


def _md_quotes(lines: list[str]) -> list[str]:
    """«> …» lines as one quoted line, the «— Имя» line after them as its attribution."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _MD_QUOTE_RE.match(lines[i])
        if not m or not lines[i].lstrip().startswith(">"):
            out.append(lines[i])
            i += 1
            continue
        said: list[str] = []
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            said.append(_MD_QUOTE_RE.match(lines[i]).group("x").strip())
            i += 1
        said = [x for x in said if x]
        by = None
        if said and re.match(r"^[—–-]\s*\S", said[-1]):
            by = re.sub(r"^[—–-]\s*", "", said.pop())
        if said:
            q = " ".join(said).strip().strip("«»\"“”")
            out.append(f"«{q}»" + (f" — {by}" if by else ""))
    return out


def _md_table_rows(lines: list[str]) -> list[str]:
    """A GFM table without its outer pipes («Курс | Цена» / «--- | ---» / …) written with them."""
    if len(lines) >= 2 and sum(1 for ln in lines if _MD_RULE_ROW_RE.match(ln)) == 1 and all("|" in ln for ln in lines if ln.strip()):
        return ["| " + ln.strip().strip("|").strip() + " |" for ln in lines if ln.strip()]
    return lines


def read_parts(text: str) -> list[Part]:
    """A slide's text as its parts, in order: code fences first (their lines are code, never sentences), then blocks
    between blank lines — notes in brackets, tables, lists, sequences with arrows, paragraphs. Markdown is read: a
    «### Подзаголовок» heads the paragraph or list under it (its `label`), «> цитата» is a quote, emphasis and link
    marks are dropped."""
    lines = (text or "").splitlines()
    parts: list[Part] = []
    block: list[str] = []
    pending: list[str] = []  # a subheading waiting for the paragraph or list it heads

    def flush() -> None:
        if block:
            rows = _md_table_rows(_md_quotes([_md_inline(x) for x in block]))
            got = _block_parts(rows)
            if pending and got and got[0].kind in ("para", "list") and not got[0].label:
                got[0].label = pending.pop()
            parts.extend(got)
            block.clear()

    i = 0
    while i < len(lines):
        sub = _MD_SUBHEAD_RE.match(lines[i])
        if sub and not _FENCE_RE.match(lines[i]):
            flush()
            if pending:  # two subheadings in a row: the first one stands alone
                parts.append(Part(kind="para", text=H.strip_end(pending.pop())))
            pending.append(_md_inline(sub.group("t")).strip(" *"))
            i += 1
            continue
        m = _FENCE_RE.match(lines[i])
        if m:
            flush()
            fence, lang = m.group(1), m.group(2)
            j = i + 1
            code: list[str] = []
            while j < len(lines) and not lines[j].strip().startswith(fence[:3]):
                code.append(lines[j].rstrip())
                j += 1
            while code and not code[0].strip():
                code.pop(0)
            while code and not code[-1].strip():
                code.pop()
            label = ""
            if parts and parts[-1].kind == "para" and parts[-1].text.rstrip().endswith(":"):
                label = parts.pop().text.rstrip().rstrip(":").strip()
            if code:
                parts.append(Part(kind="code", text=_dedent("\n".join(code)), lang=(lang or "").lower(), label=label))
            i = j + 1
            continue
        if not lines[i].strip():
            flush()
        else:
            block.append(lines[i])
        i += 1
    flush()
    if pending:
        parts.append(Part(kind="para", text=H.strip_end(pending.pop())))
    return parts


def _dedent(code: str) -> str:
    ls = code.splitlines()
    pad = min((len(x) - len(x.lstrip(" "))) for x in ls if x.strip()) if any(x.strip() for x in ls) else 0
    return "\n".join(x[pad:] if len(x) >= pad else x.lstrip(" ") for x in ls).replace("\t", "    ")


# ------------------------------------------------------------------ the data of a chart note


_NUM_SRC = r"[+\-−]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|[+\-−]?\d+(?:[.,]\d+)?"
_VALUE_RE = re.compile(rf"(?<![\w.,])(?P<num>{_NUM_SRC})(?![\d])")
_ITEM_SEP_RE = re.compile(r"\s*;\s*|\n+")
# «контроллер — 8 000 рублей, датчики — 14 000 рублей»: a comma before the next «label — figure» parts two items
_COMMA_ITEM_RE = re.compile(
    r",\s+(?=[^,;:—–\d]{2,60}?\s[—–-]\s+[+\-−]?\d)"
    # «2021 — 10%, 2022 — 15%»: a comma before the next period's figure parts two items too
    r"|,\s+(?=(?:(?:19|20)\d{2}|q[1-4]|[1-4]\s*кв\.?)\S*\s*(?:[—–-]|:)\s*[+\-−]?\d)",
    re.I,
)
# «доля каналов — онлайн 60%, офлайн 40%»: an item written as its label and its figure, no separator between them
_BARE_ITEM_RE = re.compile(r"^(?P<label>[^\d,;:—–]{2,40}?)\s+(?P<rest>[+\-−]?\d.*)$")
# «выручка, млн ₽ — 2022: 1,2; 2023: 2,5», «fuel per day before and after — Driver A: 42 and 29 litres; …»: the words
# before the note's first dash name what it measures (and its unit after a comma); its items follow
_SUBJECT_RE = re.compile(r"^(?P<subj>[^—–:;\d]{2,90}?)\s+[—–]\s+(?P<rest>\S.*)$")
_LABEL_SEP_RE = re.compile(r"\s+[—–-]\s+|\s*:\s+")
_CHART_TYPES = (
    (re.compile(r"кругов|секторн|\bpie\b", re.I), "pie"),
    (re.compile(r"кольцев|бублик|doughnut|donut", re.I), "doughnut"),
    (re.compile(r"горизонтальн|линейчат|\bbar\b", re.I), "bar"),
    (re.compile(r"с\s+областями|площадн|\barea\b", re.I), "area"),
    (re.compile(r"линейн|динамик|тренд|\bline\b", re.I), "line"),
    (re.compile(r"столбчат|столбик|гистограмм|сравнительн|\bcolumn", re.I), "column"),
)
_EACH_RE = re.compile(r"для\s+каждого|отдельн\w*\s+(?:график|диаграмм)|каждый\s+показатель|separate", re.I)
# the unit after a figure as the chart writes it: «рублей» → «₽», «литров» → «л»; the words after it («в день») stay
_UNIT_NAMES = (
    (re.compile(r"^(?:тыс\.?|тысяч\w*)\s*(?:руб\w*|₽)", re.I), "тыс. ₽"),
    (re.compile(r"^(?:млн|миллион\w*)\s*(?:руб\w*|₽)", re.I), "млн ₽"),
    (re.compile(r"^(?:млрд|миллиард\w*)\s*(?:руб\w*|₽)", re.I), "млрд ₽"),
    (re.compile(r"^(?:тыс\.?|тысяч\w*)(?![а-яё])", re.I), "тыс."),
    (re.compile(r"^(?:млн\.?|миллион\w*)(?![а-яё])", re.I), "млн"),
    (re.compile(r"^(?:млрд\.?|миллиард\w*)(?![а-яё])", re.I), "млрд"),
    (re.compile(r"^(?:руб\w*\.?|₽)", re.I), "₽"),
    (re.compile(r"^(?:долл\w*\.?|\$)", re.I), "$"),
    (re.compile(r"^(?:евро|€)", re.I), "€"),
    (re.compile(r"^(?:%|процент\w*)", re.I), "%"),
    (re.compile(r"^(?:литр\w*|л\.?)(?![а-яё])", re.I), "л"),
    (re.compile(r"^(?:минут\w*|мин\.?)(?![а-яё])", re.I), "мин"),
    (re.compile(r"^(?:час\w*|ч\.?)(?![а-яё])", re.I), "ч"),
    (re.compile(r"^(?:секунд\w*|сек\.?|с\.?)(?![а-яё])", re.I), "с"),
    (re.compile(r"^(?:дн\w*|дней|день)(?![а-яё])", re.I), "дн."),
    (re.compile(r"^(?:месяц\w*|мес\.?)(?![а-яё])", re.I), "мес."),
    (re.compile(r"^(?:человек|чел\.?)(?![а-яё])", re.I), "чел."),
    (re.compile(r"^(?:штук\w*|шт\.?)(?![а-яё])", re.I), "шт."),
    (re.compile(r"^(?:килограмм\w*|кг)(?![а-яё])", re.I), "кг"),
    (re.compile(r"^(?:тонн\w*|т\.?)(?![а-яё])", re.I), "т"),
    (re.compile(r"^(?:м²|м2|кв\.?\s?м\w*)", re.I), "м²"),
    (re.compile(r"^(?:м³|м3|куб\w*\s?м\w*)", re.I), "м³"),
    (re.compile(r"^(?:кВт·?ч|квт\s?ч)", re.I), "кВт·ч"),
    # an English note's units, as an English slide writes them
    (re.compile(r"^(?:litres?|liters?|l)\b", re.I), "l"),
    (re.compile(r"^(?:minutes?|mins?)\b", re.I), "min"),
    (re.compile(r"^(?:hours?|hrs?|h)\b", re.I), "h"),
    (re.compile(r"^days?\b", re.I), "days"),
    (re.compile(r"^(?:people|persons?|users?|customers?)\b", re.I), "people"),
    (re.compile(r"^(?:kg|kilograms?)\b", re.I), "kg"),
    (re.compile(r"^(?:usd|dollars?)\b", re.I), "$"),
    (re.compile(r"^(?:eur|euros?)\b", re.I), "€"),
    (re.compile(r"^(?:rub|roubles?|rubles?)\b", re.I), "₽"),
    (re.compile(r"^(?:percent|per\s+cent)\b", re.I), "%"),
)
# a pair of figures said of two states of one thing: what the bars are called
_PAIR_WORDS = (
    (re.compile(r"вручную|ручн\w+|\bmanual\w*", re.I), re.compile(r"автоматическ\w*|автоматич\w*|автоматизац\w*|\bautomat\w*", re.I), ("Вручную", "Автоматически")),
    (re.compile(r"\bплан\w*|\bplan(?:ned)?\b", re.I), re.compile(r"\bфакт\w*|\bactual\b", re.I), ("План", "Факт")),
    (re.compile(r"\bсейчас\b|\bтекущ\w+", re.I), re.compile(r"\bцел[ьи]\b|\bцелев\w+", re.I), ("Сейчас", "Цель")),
    # «до и после», «до/после», «до внедрения … после внедрения» — never «выросла до 150» (a preposition)
    (re.compile(r"\bдо\s*(?:и|/)\s*после\b|\bдо\s+(?:внедрени|запуск|автоматизац|начал|ремонт|реформ|открыти|переход|изменени|установк|обучени|оптимизац)", re.I), re.compile(r"\bпосле\b", re.I), ("До", "После")),
    (re.compile(r"\bbefore\b", re.I), re.compile(r"\bafter\b", re.I), ("Before", "After")),
)
# a slide that says its figures changed («сократился», «снизился», «стало», «с … до …»): two figures of one thing are
# what it was and what it became
_CHANGE_RE = re.compile(
    r"сократил\w*|снизил\w*|уменьшил\w*|вырос\w*|выросл\w*|увеличил\w*|стал[аио]?\b|был[аио]?\b|раньше|теперь|"
    r"\bс\s+\d[\d\s,.]*\s*(?:\S+\s+){0,2}?до\s+\d|\bdropped|\bfell\b|\brose\b|\bgrew\b|\bfrom\s+\d[\d,.]*\s+to\s+\d",
    re.I,
)
# the label of a figure that is a period, not a thing: «2023», «2024 г.», «Q1 2025», «2-й квартал», «март»
_PERIOD_LABEL_RE = re.compile(
    r"^(?:(?:19|20)\d{2}(?:\s*(?:г\.?|год\w*))?|(?:19|20)\d{2}\s*[-–/]\s*(?:19|20)?\d{2}|"
    r"(?:q|кв\.?\s*)[1-4](?:\s*(?:19|20)\d{2})?|[1-4][-‑]?й?\s+квартал\w*(?:\s+(?:19|20)\d{2})?|"
    r"(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*(?:\s+(?:19|20)\d{2})?)$",
    re.I,
)


def number_value(raw: str) -> float:
    return float(re.sub(r"[\s  ]", "", raw).replace(",", ".").replace("−", "-"))


def thousands(text: str) -> str:
    """«4,800» read as four thousand eight hundred where commas group thousands: in an English note, and wherever a
    figure has two groups («1,250,000»); a Russian «1,25» stays one and a quarter."""
    t = re.sub(r"(?<![\d,.])\d{1,3}(?:,\d{3}){2,}(?![\d,])", lambda m: m.group(0).replace(",", " "), text or "")
    if latin(t):
        t = re.sub(r"(?<![\d,.])\d{1,3},\d{3}(?![\d,])", lambda m: m.group(0).replace(",", " "), t)
    return t


def unit_of(tail: str) -> tuple[Optional[str], str]:
    """(the unit written right after a figure, the words after the unit): «литров воды» → («л», «воды»)."""
    t = (tail or "").strip()
    for rx, name in _UNIT_NAMES:
        m = rx.match(t)
        if m:
            return name, t[m.end() :].strip(" ,.")
    return None, t.strip(" ,.")


@dataclass
class ChartItem:
    label: str
    values: list[float]
    unit: Optional[str] = None
    unit_words: str = ""  # «в день» of «45 и 20 минут в день»
    raw: list = field(default_factory=list)  # the figures as written («4 800», «1,2»)
    span: bool = False  # «40–60 рублей»: a range — no bar draws it, a table cell shows it as written
    text: str = ""  # what the note says of it after its label, as written («4 800 и 3 300 литров»)


def chart_type_of(label: str, items: list[ChartItem]) -> str:
    for rx, kind in _CHART_TYPES:
        if rx.search(label or ""):
            return kind
    if items and len(items) >= 3 and all(_PERIOD_LABEL_RE.match(it.label or "") for it in items):
        return "line"
    return "column"


# what stands between two figures of one item: «4 800 и 3 300», «100 / 115», «с 45 до 20», «4,800 and 3,300»
_PAIR_SEPS = ("и", ",", "и,", "/", "vs", "vs.", "versus", "против", "→", "->", "до", "and", "to", "against")
_SPAN_SEP_RE = re.compile(r"^\s*[—–\-−]\s*$")


def chart_items(body: str) -> list[ChartItem]:
    """«расход воды — 4 800 и 3 300 литров; ручная работа — 45 и 20 минут в день» → items with their figures and units;
    an item without a unit takes the first one written («контроллер — 8 000 рублей; датчики — 14 000»). A label may be a
    period («2023 — 1,2 млн рублей»); «40–60 рублей» is a range (`span`), never two figures."""
    data = _note_data(body)
    head_unit: Optional[tuple] = None
    sm = _SUBJECT_RE.match(data)
    if sm is not None and _items_follow(sm.group("rest")):
        subj = sm.group("subj").strip()
        if "," in subj:
            unit, unit_words = unit_of(subj.rsplit(",", 1)[1].strip())
            if unit:
                head_unit = (unit, unit_words)
        data = sm.group("rest")
    out: list[ChartItem] = []
    chunks = [c for part in _ITEM_SEP_RE.split(H.strip_end(data)) for c in _COMMA_ITEM_RE.split(part)]
    if len(chunks) == 1 and "," in chunks[0] and all(_BARE_ITEM_RE.match(c.strip(" .")) for c in chunks[0].split(",")):
        chunks = chunks[0].split(",")
    for chunk in chunks:
        chunk = chunk.strip(" .")
        if not chunk:
            continue
        m = _LABEL_SEP_RE.search(chunk)
        if m is None:
            bare = _BARE_ITEM_RE.match(chunk)
            if bare is None:
                continue
            chunk = f"{bare.group('label').strip()} — {bare.group('rest').strip()}"
            m = _LABEL_SEP_RE.search(chunk)
        label, rest = chunk[: m.start()].strip(), chunk[m.end() :].strip()
        if not label or words(label) > 8 or (_VALUE_RE.search(label) and not _PERIOD_LABEL_RE.match(label)):
            continue
        nums = list(_VALUE_RE.finditer(rest))
        lead = rest[: nums[0].start()].strip(" (~≈") if nums else ""
        if not nums or len(lead.split()) > 2 or any(len(w) > 9 or not w.isalpha() for w in lead.split()):
            continue  # «около 45 минут», «в среднем 45 минут» — never a figure inside a sentence
        # the figures are the start of the rest: «4 800 и 3 300 литров», «8 000 рублей», never a figure inside words after them
        values: list[float] = []
        raw: list[str] = []
        span = False
        last_end = 0
        for k, n in enumerate(nums):
            if k:
                gap = rest[last_end : n.start()]
                if _SPAN_SEP_RE.match(gap):
                    span = True
                elif gap.strip().lower() not in _PAIR_SEPS:
                    break
            values.append(number_value(n.group("num")))
            raw.append(n.group("num").strip())
            last_end = n.end()
        unit, unit_words = unit_of(rest[last_end:])
        out.append(ChartItem(label=H.cap_first(label), values=values, unit=unit, unit_words=unit_words if unit else "", raw=raw, span=span, text=rest))
    first_unit = next((it.unit for it in out if it.unit), None) or (head_unit[0] if head_unit else None)
    for it in out:
        if it.unit is None and first_unit and len({len(x.values) for x in out}) == 1:
            it.unit = first_unit
            if head_unit and not it.unit_words and first_unit == head_unit[0]:
                it.unit_words = head_unit[1] or ""
    return out


def _note_data(body: str) -> str:
    """The figures' part of a note: the sentences after the data are its instructions («Для каждого показателя —
    отдельный график …»)."""
    data = thousands(body)
    sents = sentences(data)
    if len(sents) > 1:
        keep = [s for s in sents if _VALUE_RE.search(s)]
        data = " ".join(keep) if keep else data
    return data


def _items_follow(rest: str) -> bool:
    """The words after a note's first dash are its items: two or more «label: figure» / «label — figure» / «label
    figure» parts."""
    chunks = [c.strip(" .") for part in _ITEM_SEP_RE.split(rest) for c in _COMMA_ITEM_RE.split(part)]
    if len(chunks) == 1 and "," in chunks[0]:
        chunks = [c.strip(" .") for c in chunks[0].split(",")]
    def item(c: str) -> bool:
        if not c or not _VALUE_RE.search(c):
            return False
        m = _LABEL_SEP_RE.search(c)
        if m is not None:
            label = c[: m.start()].strip()
            return bool(label) and (not re.match(r"^[+\-−]?\d", label) or bool(_PERIOD_LABEL_RE.match(label)))
        return bool(_BARE_ITEM_RE.match(c))

    # (the first part after the dash is an item with its own label: «расход воды — 4 800 и 3 300 литров; …» is an item
    # whose dash parts its label from its figures, not a subject over the items)
    return bool(chunks) and item(chunks[0]) and sum(1 for c in chunks if item(c)) >= 2


def note_covered(body: str, items: list) -> bool:
    """Every figure of the note is in its items (as a value or a period label): a chart drawn from them shows the note
    whole. «Пекарня на Ленина: 420 и 380 кг» read as no item would leave a chart without it — the note is then shown as
    written instead."""
    data = _note_data(body)
    sm = _SUBJECT_RE.match(data)
    if sm is not None and _items_follow(sm.group("rest")):
        data = sm.group("rest")
    have = [number_value(m.group("num")) for m in _VALUE_RE.finditer(data)]
    used = [v for it in items for v in it.values] + [number_value(x) for it in items for x in re.findall(r"(?:19|20)\d{2}", it.label or "")]
    for v in have:
        if v is None:
            continue
        hit = next((k for k, u in enumerate(used) if u is not None and abs(u - v) <= 1e-9 * max(1.0, abs(v))), None)
        if hit is None:
            return False
        used.pop(hit)
    return True


def pair_names(text: str, n: int, whole: Optional[str] = None) -> list[str]:
    """The names of the figures of each item, from the words of the note and the sentences that state its figures
    (`text`): a contrast («вручную» … «автоматически», «план» … «факт», «сейчас» … «цель», «до и после»), else the
    periods the slide names (`whole`: «Данные за 2024 и 2025 годы» — as many years as figures), else «Было» / «Стало»
    where the note's words say the figures changed; else their order («1», «2» — unnamed: no chart draws them, the note
    is shown as written)."""
    if n == 2:
        for a, b, names in _PAIR_WORDS:
            if a.search(text or "") and b.search(text or ""):
                return list(names)
    years = list(dict.fromkeys(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", whole if whole is not None else text or "")))
    if len(years) == n:
        return years
    if n == 2 and _CHANGE_RE.search(text or ""):
        return ["Before", "After"] if latin(text) else ["Было", "Стало"]
    return [str(i + 1) for i in range(n)]


def unnamed(names: list[str]) -> bool:
    """The names are only the figures' order («1», «2»): nothing in the text names them."""
    return names == [str(i + 1) for i in range(len(names))]


def _pair_context(r: "Reading", note: "Part", items: list) -> str:
    """The words that may name a note's figures: the note itself and the slide's sentences about them — a sentence that
    states one of its figures or names one of its items («Water use dropped» over «water — 4,800 and 3,300 litres»);
    never a sentence about something else («Цены были пересмотрены в марте» over the prices of two tariffs)."""
    vals = {v for it in items for v in it.values}
    stems = {w.lower()[:5] for it in items for w in re.findall(r"[a-zа-яё]{4,}", it.label or "", re.I)}

    def about(sent: str) -> bool:
        if any(number_value(m.group("num")) in vals for m in _VALUE_RE.finditer(thousands(sent))):
            return True
        return any(w.lower()[:5] in stems for w in re.findall(r"[a-zа-яё]{4,}", sent, re.I))

    own = [x for p in r.of("para") for x in p.sentences if about(x)]
    return " ".join([note.label or "", note.text or "", *own])


def latin(text: str) -> bool:
    """The text is written in Latin letters more than in Cyrillic (an English brief)."""
    return len(re.findall(r"[a-z]", text or "", re.I)) > len(re.findall(r"[а-яё]", text or "", re.I))


def unit_label(unit: Optional[str], unit_words: str = "") -> Optional[str]:
    if not unit:
        return None
    return f"{unit} {unit_words}".strip() if unit_words and words(unit_words) <= 3 and not _VALUE_RE.search(unit_words) else unit


# ------------------------------------------------------------------ a slide read for its layout


_CAVEAT_RE = re.compile(
    r"допущени|\bусловн\w*|иллюстрир\w*|не\s+составля\w*|не\s+учитыва\w*|не\s+учтен\w*|не\s+входят|не\s+включ\w*|"
    r"приблизительн\w*|ориентировочн\w*|не\s+являются|не\s+является\s+(?:офертой|рекомендац)|носят\s+\w+\s+характер|"
    r"\bhypothetical\b|\billustrative\b|for\s+illustration",
    re.I,
)
_RESULT_RE = re.compile(
    r"^(?:вывод|итог|главн\w+\s+(?:результат|вывод|итог)\w*|таким\s+образом|в\s+итоге|итак|в\s+результате|резюмируя|"
    r"in\s+short|in\s+summary|overall|the\s+key\s+result)\b",
    re.I,
)
_STAGE_RE = re.compile(
    r"^(?P<t>(?:перв|втор|трет|четв[её]рт|пят|шест|седьм|восьм|девят|десят|заключительн|финальн|начальн|последн)\w*\s+"
    r"(?:этап|шаг|уровень|фаз\w*|период|год|месяц|квартал|день|недел\w*|волн\w*|спринт|стади\w*)(?:\s+[а-яё]+){0,2}?|"
    r"(?:этап|шаг|фаза|уровень|волна|спринт|стадия|stage|step|phase)\s+\d{1,2})\s*(?:[—–:]|\s-)\s*(?P<x>\S.+)$",
    re.I,
)
_QUOTE_RE = re.compile(r"«(?P<q>[^«»]{24,400})»|“(?P<q2>[^“”]{24,400})”|\"(?P<q3>[^\"]{24,400})\"")
# the quote's author after it: «…» — Ольга Смирнова, директор по логистике
_QUOTE_BY_RE = re.compile(r"^\s*[—–-]\s*(?P<by>[^!?\n]{3,160}?)[.!]?\s*$")
_COVER_WORDS_RE = re.compile(r"титул|обложк|заглавн|\bcover\b|title\s+slide", re.I)
# the usual headings of a deck's parts: a first slide named so is the deck's first content slide, not its cover, even
# when a short line opens it («Слайд 1. Проблема / Клиенты ждут ответа два дня»)
SECTION_WORDS_RE = re.compile(
    r"^(?:проблем\w*|введени\w*|актуальност\w*|цел[ьи]\w*|задач\w*|решени\w*|рын\w*|контекст\w*|обзор\w*|о\s+(?:компании|проекте|нас|продукте)|"
    r"предпосылк\w*|план\w*|содержани\w*|повестк\w*|итог\w*|вывод\w*|результат\w*|команд\w*|продукт\w*|конкурент\w*|бизнес-модел\w*|"
    r"финанс\w*|риск\w*|этап\w*|ситуаци\w*|аудитори\w*|история|предложени\w*|problem\w*|introduction|solution|market|overview|agenda|"
    r"team|product|goals?|results?|conclusions?|background|context)\b",
    re.I,
)
_TITLE_LINE_RE = re.compile(r"^\s*(?:[—–\-•*]\s*)?(?:название|подзаголовок|заголовок|title|subtitle)\s*[:—–]\s*(?P<v>.+)$", re.I)
# a closing slide's heading, piece by piece («Спасибо за внимание! Вопросы?»): thanks, questions, contacts, goodbye —
# never a heading that merely starts so («Вопросы безопасности», «Контактный центр после внедрения»)
_CLOSING_PIECE_RE = re.compile(
    r"^(?:спасибо(?:\s+за\s+(?:внимание|просмотр|интерес|ваше\s+время))?|благодар(?:ю|им)(?:\s+за\s+внимание)?|"
    r"(?:ваши\s+|есть\s+|остались\s+)?вопросы(?:\s+и\s+(?:ответы|обсуждение))?|обсуждение|(?:наши\s+|мои\s+)?контакты|"
    r"свяжитесь\s+с\s+нами|до\s+встречи|thank\s+you(?:\s+for\s+(?:your\s+)?attention)?|thanks|(?:any\s+)?questions|"
    r"q\s*&\s*a|contacts?|get\s+in\s+touch|the\s+end)$",
    re.I,
)
_CONTACT_RE = re.compile(r"@|https?://|www\.|t\.me/|vk\.com/|\+?\d[\d\s()\-]{8,}\d|e-?mail|почт[аы]|телефон|тел\.", re.I)
_AGENDA_RE = re.compile(r"^(?:план(?:\s+(?:презентации|доклада|выступления))?|содержание|повестка(?:\s+дня)?|оглавление|agenda|contents|о\s+ч[её]м\s+(?:расскажу|поговорим))[.!]?$", re.I)
_SCREEN_RE = re.compile(
    r"экран|интерфейс|приложени|сайт|страниц\w+\s+сайта|панел\w*\s+(?:управления|наблюдения|мониторинга|администратора)|"
    r"дашборд|dashboard|скриншот|screen|\bapp\b|личн\w+\s+кабинет|мобильн|окн\w+\s+программ",
    re.I,
)


@dataclass
class Reading:
    """One slide the user dictated, read for its layout: its parts and what the text itself marks — the subtitle
    under the heading, a caveat, the stated result — and its role in the deck."""

    number: int
    title: str
    parts: list[Part]
    text: str
    role: str = "content"  # cover | closing | agenda | section | content
    lead: Optional[str] = None
    footnote: Optional[str] = None
    takeaway: Optional[str] = None
    used: set = field(default_factory=set)
    # the sentences that ask the designer for something («Нужна круговая диаграмма …», «Покажи формулу: …»): the
    # analyst reads them as the slide's requests, the slide never shows them as text
    asks: dict = field(default_factory=dict)
    # the slide's data blocks its form does not show (code with a chart under it, a chart and a table, a third chart):
    # each a reading of its own, shown on a continuation slide (expand_slides) — never dropped
    extra: list = field(default_factory=list)
    # the speaker notes the brief gives the slide («[Заметки докладчика: …]», a deck read back by ingest/deck_text.py):
    # the slide's notes keep them, its text never shows them
    speaker: str = ""

    def of(self, kind: str) -> list[Part]:
        return [p for p in self.parts if p.kind == kind]

    def paras(self) -> list[list[str]]:
        """The paragraphs' sentences, without those the lead, the caveat and the result took."""
        out = []
        for p in self.of("para"):
            ss = [s for s in p.sentences if s not in self.used]
            if ss:
                out.append(ss)
        return out

    def para_labels(self) -> list[str]:
        """The subheading over each of paras()' paragraphs («### Практика» in the author's markdown), "" where there is
        none — in the same order as paras()."""
        out = []
        for p in self.of("para"):
            if any(s not in self.used for s in p.sentences):
                out.append(p.label or "")
        return out

    def stages(self) -> list[tuple[str, list[str]]]:
        """«Первый этап развития — повышение надежности: …» paragraphs: (the stage's name, its sentences with the
        first one's rest leading), when there are two or more of them."""
        out = []
        for ss in self.paras():
            m = _STAGE_RE.match(ss[0])
            if m:
                rest = H.cap_first(m.group("x").strip())
                out.append((H.cap_first(m.group("t").strip()), [rest] + ss[1:]))
        return out if len(out) >= 2 else []

    def quote(self) -> Optional[tuple[str, str]]:
        """A message or a saying quoted in the text («Зона 2: данные датчика не обновлялись 8 минут. …»): (the quote,
        the sentence that introduces it)."""
        got = self.quote_by()
        return (got[0], got[1]) if got else None

    def quote_by(self) -> Optional[tuple[str, str, Optional[str]]]:
        """The quote, the sentence that introduces it, and who said it («…» — Ольга Смирнова, директор), when the text
        names them right after the quote (in its sentence or the next one)."""
        for ss in self.paras():
            for k, s in enumerate(ss):
                m = _QUOTE_RE.search(s)
                q = (m.group("q") or m.group("q2") or m.group("q3")) if m else None
                if q and words(q) >= 5:
                    intro = H.strip_end(s[: m.start()].strip().rstrip(":").strip())
                    tail = s[m.end() :]
                    by = _QUOTE_BY_RE.match(tail) or (_QUOTE_BY_RE.match(ss[k + 1]) if not tail.strip() and k + 1 < len(ss) else None)
                    return q.strip(), intro, (H.strip_end(by.group("by").strip()) if by else None)
        return None


def clean_title(title: str) -> str:
    return H.strip_end(" ".join((title or "").split()).strip(" *#"))


def closing_title(title: str) -> bool:
    """The heading opens with thanks, a call for questions or the contacts («Спасибо! Вопросы?», «Спасибо за внимание!
    Контакты команды»): a closing — never a heading that merely starts so in one piece («Вопросы безопасности»)."""
    pieces = [x.strip() for x in re.split(r"[!?.…;,]+", title or "") if x.strip()]
    return bool(pieces) and bool(_CLOSING_PIECE_RE.match(pieces[0]))


def _norm_title(t: str) -> str:
    return " ".join(re.sub(r"[«»\"“”„.,!?…:;—–-]", " ", (t or "").lower().replace("ё", "е")).split())


def end_sentence(text: str) -> str:
    """A sentence with its own end: «!», «?», «…» stay, a period where it had none."""
    t = H.strip_end(text)
    return t if not t or t.endswith(("!", "?", "…", ".")) else t + "."


def designer_ask(sentence: str) -> Optional[str]:
    """What a dictated sentence asks of the designer (brief_structure.instruction_kind) — a rule only when it is said to
    the designer: «Линии подачи воды должны быть доступны для проверки», «Цвета листьев меняются», «Обязательно
    проверяйте датчики», «Используй разные пароли», «Сохрани подозрительное письмо» are the author's own text and stay
    on the slide (brief_structure.speaks_of_the_deck)."""
    from verstka.planning.brief_structure import instruction_kind, speaks_of_the_deck

    kind = instruction_kind(sentence)
    if kind == "rule" and not speaks_of_the_deck(sentence):
        return None
    return kind


def _has_figure(sentence: str) -> bool:
    """The sentence states a figure with its unit («85 000 рублей», «30%»): what it says is the slide's content."""
    for m in _VALUE_RE.finditer(sentence or ""):
        tail = sentence[m.end() :]
        if tail.startswith("%") or unit_of(tail)[0] is not None:
            return True
    return False


def _heading_of(r: "Reading") -> str:
    """A heading for a slide the user gave none («Слайд 3.» and its text): its first sentence when it is short (the
    text then goes on from the next one), else that sentence's first clause, the label of its list or its picture."""
    for p in r.parts:
        if p.kind == "para":
            ss = [x for x in p.sentences if x not in r.used]
            if not ss:
                continue
            s0 = ss[0]
            if words(s0) <= 10 and (len(ss) > 1 or len(r.parts) > 1):
                r.used.add(s0)
                return H.strip_end(s0)
            clause = re.split(r"[,:;]\s|\s[—–]\s", s0, maxsplit=1)[0]
            if 2 <= words(clause) <= 10:
                return H.strip_end(clause)
            return " ".join(s0.split()[:7]).rstrip(",;:—–") + "…"
        if p.kind in ("list", "flow") and p.label:
            return H.strip_end(p.label)
        if p.kind in ("image", "chart", "table", "note") and (p.label or p.text):
            got = chart_title(p.label) if p.label else None
            return got or H.cap_first(H.strip_end(" ".join((p.text or p.label).split()[:7])))
        if p.kind == "code" and p.label:
            return H.strip_end(p.label)
    return ""


def _field_value(raw: str) -> str:
    """The value of a «Название: «…».» line: its wrapping quotes off, nested quotes kept («Задача «Цифровой дизайнер»»)."""
    from verstka.planning.brief_structure import _unquote

    return H.strip_end(_unquote(raw.strip())).strip()


# a note of a slide that carries its speaker notes («[Заметки докладчика: …]»)
_SPEAKER_RE = re.compile(r"^(?:заметки\s+(?:для\s+)?докладчика|speaker\s+notes)$", re.I)


def read_slide(number: int, title: str, text: str, *, first: bool = False, last: bool = False, deck: Optional[str] = None, notes: str = "") -> Reading:
    """`deck`: the deck's own title when the text gives one («Тема презентации: …»): a first slide named the same that
    says one or two short lines is the cover — a cover of its own before it would show the same title twice. `notes`:
    the speaker notes the brief gives the slide (brief_structure takes «[Заметки докладчика: …]» out of its text) —
    the slide's notes keep them, never its text."""
    parts = read_parts(text)
    said = [p.text for p in parts if p.kind == "note" and _SPEAKER_RE.match(p.label or "")]
    parts = [p for p in parts if not (p.kind == "note" and _SPEAKER_RE.match(p.label or ""))]
    r = Reading(number=number, title=clean_title(title), parts=parts, text=text or "", speaker="\n\n".join(x for x in [(notes or "").strip(), *said] if x))
    for p in r.of("para"):
        for sent in p.sentences:
            kind = designer_ask(sent)
            if kind:
                r.asks.setdefault(kind, []).append(sent)
                r.used.add(sent)
    # a paragraph made of requests only is no text of the slide
    parts = [p for p in parts if not (p.kind == "para" and p.sentences and all(x in r.used for x in p.sentences))]
    # «Название: …» / «Подзаголовок: …» lines (a cover the user described by its fields), plain or as a list
    fields: dict = {}
    for p in parts:
        if p.kind == "para":
            m = _TITLE_LINE_RE.match(p.text)
            if m:
                key = "sub" if re.match(r"\s*(?:[—–\-•*]\s*)?(?:подзаголовок|subtitle)", p.text, re.I) else "title"
                fields.setdefault(key, _field_value(m.group("v")))
                r.used.update(p.sentences)
        elif p.kind == "list":
            keep = []
            for it in p.items:
                m = _TITLE_LINE_RE.match(it)
                if m:
                    key = "sub" if re.match(r"\s*(?:подзаголовок|subtitle)", it, re.I) else "title"
                    fields.setdefault(key, _field_value(m.group("v")))
                else:
                    keep.append(it)
            p.items = keep
    parts = [p for p in parts if not (p.kind == "list" and not p.items) and not (p.kind == "para" and p.sentences and all(x in r.used for x in p.sentences))]
    r.parts = parts
    derived = False
    if not r.title and not fields.get("title"):
        r.title = _heading_of(r)
        derived = bool(r.title)  # the heading is the text's own first words: the slide is a slide of text, never a divider
    paras = r.of("para")
    rich = any(p.kind in ("code", "chart", "table", "flow", "image") for p in parts) or any(k in r.asks for k in ("chart", "table", "formula"))
    # the lead: a short first line of one sentence over more text («Автоматизация полива и контроль микроклимата»)
    tagline = False
    if paras and parts and parts[0] is paras[0]:
        ss = [x for x in paras[0].sentences if x not in r.used]
        tagline = len(ss) == 1 and not paras[0].text.rstrip().endswith((".", "!", "?", "…")) and words(ss[0]) <= 14
        if len(ss) == 1 and words(ss[0]) <= 14 and (len(parts) > 1 or first or last) and (tagline or last):
            r.lead = H.strip_end(ss[0])
            r.used.add(ss[0])
    if fields.get("sub"):
        r.lead = fields["sub"]
    rest = [x for p in paras for x in p.sentences if x not in r.used]
    # a first slide of one or two short lines, nothing else (no data, code, picture or list): what a cover says
    short = (not rich and not r.of("list") and len(rest) <= 2 and sum(words(x) for x in rest) <= 24
             and all(not _VALUE_RE.search(x) or _YEAR_ONLY_RE.fullmatch(H.strip_end(x)) for x in rest))
    named = deck is None or _norm_title(deck) == _norm_title(r.title)
    # the role: the first slide is the cover when it says so, names its fields, opens on a tagline (a line without a
    # final period under the heading) and carries no code, data or picture of its own — or says one or two short lines
    # under a heading that is the deck's title (or names no part of a deck: «Проблема» over a line is the first content)
    if first and (_COVER_WORDS_RE.search(r.title) or fields or not parts or (tagline and r.lead and not rich and len(paras) <= 5 and not SECTION_WORDS_RE.match(r.title))
                  or (short and rest and not derived and ((deck is not None and named) or not _part_name(r.title)))):
        r.role = "cover"
        if fields.get("title"):
            r.title = fields["title"]
        if r.lead is None and rest:
            r.lead = H.strip_end(" ".join(rest))
            r.used.update(rest)
    elif last and closing_title(r.title) and not rich and sum(words(x) for x in rest if not _CONTACT_RE.search(x)) <= 30 and not any(
            p.kind == "list" and len(p.items) > 4 and not all(_CONTACT_RE.search(x) for x in p.items) for p in parts):
        r.role = "closing"
        # under the heading: its first short line and the contacts (a list, a line with an address or a phone); the
        # other lines are the speaker's
        if r.lead is None and rest and words(rest[0]) <= 14:
            r.lead = H.strip_end(rest[0])
            r.used.add(rest[0])
        contacts = [x for x in rest if x not in r.used and _CONTACT_RE.search(x)] + [x for p in r.of("list") for x in p.items]
        if contacts:
            r.lead = " · ".join(([r.lead] if r.lead else []) + [H.strip_end(x) for x in contacts])
            r.used.update(contacts)
    elif _AGENDA_RE.match(r.title) and (r.of("list") or len(paras) >= 2) and not rich:
        r.role = "agenda"
    elif not first and not derived and (not parts or (len(parts) == 1 and paras and len(rest) == 1 and words(rest[0]) <= 14 and not _VALUE_RE.search(rest[0]))):
        # a title over one short line (or none): a divider of the deck's parts — never a line that states a figure («За
        # год волонтёры собрали 48 тонн мусора» is the slide's point, shown as its content)
        r.role = "section"
    elif not r.title:
        r.title = fields.get("title") or _heading_of(r)
    # a caveat said on its own: the slide's footnote (the cover's small print) — never a sentence that states a figure
    for p in reversed(paras):
        ss = [x for x in p.sentences if x not in r.used]
        if len(ss) == 1 and words(ss[0]) <= 28 and _CAVEAT_RE.search(ss[0]) and not _has_figure(ss[0]) and (r.role == "cover" or len(paras) >= 3 or p is paras[-1]):
            r.footnote = end_sentence(ss[0])
            r.used.add(ss[0])
            break
    # the slide's stated result: the last sentence that opens with «Главный результат …», «Таким образом …», «Вывод: …»
    if r.role == "content":
        for p in reversed(paras):
            hit = next((x for x in reversed(p.sentences) if x not in r.used and _RESULT_RE.match(x)), None)
            if hit:
                r.takeaway = H.cap_first(end_sentence(re.sub(r"^(?:вывод|итог)\s*[:—–]\s*", "", hit, flags=re.I)))
                r.used.add(hit)
                break
    return r


def _drawn_whole(r: "Reading", note: "Part") -> bool:
    """A chart or table note the deck draws whole: a «|» table, or a note whose items hold every figure it gives."""
    if note.kind == "table" and any(ln.strip().startswith("|") for ln in (note.text or "").splitlines()):
        return True
    items = chart_items(note.text)
    if not items and note.kind == "chart":
        src = source_table(r, note)
        return src is not None and table_chart(note, src) is not None
    return bool(items) and note_covered(note.text, items)


# a sentence that speaks to the designer, not to the audience: an imperative at its head («Покажи структуру расходов
# на диаграмме», «Не рассчитывай срок окупаемости…») or one inside it («Разовые вложения показывай отдельно…»)
_TO_DESIGNER_RE = re.compile(
    r"^(?:не\s+)?(?:покажи|покажите|сделай|сделайте|укажи|укажите|добавь|добавьте|предложи|предложите|выдели|выделите|"
    r"используй|используйте|отметь|отметьте|подчеркни|перечисли|приведи|оформи|вынеси|раздели|сравни|рассчитай|рассчитывай|"
    r"складывай|прибавляй|представляй|перегружай|округляй|сохрани|поставь|размести|нарисуй|добавляй|покажи)\b",
    re.I,
)
_TO_DESIGNER_INSIDE_RE = re.compile(r"\b(?:показывай|выноси|располагай|оформляй|округляй)\b", re.I)
_THAT_RE = re.compile(r"^(?:укажи|укажите|отметь|отметьте|подчеркни|напомни),?\s+что\s+(?P<rest>.+)$", re.I)


def _nominative_tail(head: str) -> str:
    """«формулу» → «формула»: the heading the instruction named, as a heading (its last word out of the accusative)."""
    words_ = head.split()
    if words_ and re.fullmatch(r"[а-яё]{3,}[ую]", words_[-1], re.I):
        words_[-1] = words_[-1][:-1] + ("а" if words_[-1].endswith("у") else "я")
    return " ".join(words_)


def speaker_line(sentence: str) -> Optional[str]:
    """The sentence as the speaker's notes keep it: the author's content as written; an instruction to the designer
    as what it names («Добавь основные риски: слабый отклик…» → «Основные риски: слабый отклик…», «Укажи, что налоги не
    учитываются» → «Налоги не учитываются»); a pure instruction («Покажи структуру расходов на диаграмме») — None."""
    t = (sentence or "").strip()
    if not t or not (_TO_DESIGNER_RE.match(t) or (_TO_DESIGNER_INSIDE_RE.search(t) and not re.search(r"\d", t))):
        return t or None
    m = _THAT_RE.match(t)
    if m:
        rest = m.group("rest").strip()
        return rest[:1].upper() + rest[1:]
    m = re.match(r"^(?P<head>[^:«»]{2,80}):\s*(?P<rest>\S.*)$", t)
    if m:
        head = _TO_DESIGNER_RE.sub("", m.group("head")).strip()
        head = _nominative_tail(head)
        rest = m.group("rest").strip()
        return f"{head[:1].upper() + head[1:]}: {rest}" if head else rest[:1].upper() + rest[1:]
    return None


def _speaker_label(label: str) -> str:
    """A list's heading as the notes keep it: «Покажи пять основных показателей» → «Пять основных показателей»."""
    head = _TO_DESIGNER_RE.sub("", label or "").strip()
    head = _nominative_tail(head) if head != (label or "").strip() else head
    return head[:1].upper() + head[1:] if head else ""


def notes_of(r: Reading) -> str:
    """The slide's whole text for the speaker, paragraph by paragraph: the code aside (it is on the slide), a note for
    the designer as written when the slide cannot show its data (a chart note without figures, «[Здесь будет видео]»).
    Instructions to the designer are not the speaker's: an instruction that names content keeps the content under its
    heading, a pure one is left out (`speaker_line`)."""
    out = []
    for p in r.parts:
        if p.kind == "para":
            said = [x for x in (speaker_line(x) for x in (sentences(p.text) or [p.text])) if x]
            if said:
                out.append((f"{p.label}. " if p.label else "") + " ".join(said))
        elif p.kind == "flow":
            out.append((f"{p.label}: " if p.label else "") + " → ".join(p.items) + ".")
        elif p.kind == "list":
            lb = _speaker_label(p.label)
            out.append((f"{lb}:\n" if lb else "") + "\n".join(f"— {x}" for x in p.items))
        elif p.kind == "image":
            out.append(f"[{p.label or 'Изображение'}: {p.text}]")
        elif p.kind in ("chart", "table", "note"):
            # (decided per note: a note the slide or its continuation draws whole is not repeated; one read in part
            # or not at all stays here as written)
            if p.kind == "note" or not _drawn_whole(r, p):
                out.append("[" + ": ".join(x for x in (p.label, p.text) if x) + "]")
    if r.speaker:
        out.append(r.speaker)  # the deck's own speaker notes, as they were
    return "\n\n".join(x for x in out if x.strip())


# ------------------------------------------------------------------ what the template's samples hold


@dataclass
class Room:
    """What the template's own sample slides can hold, by kind — read from its analysed manifest, whatever the
    template: the kinds it has samples of, the item counts their groups take and the characters a cell or a text slot
    holds at the sample's size."""

    kinds: set = field(default_factory=set)
    cells: dict = field(default_factory=dict)  # kind → [(min_n, max_n, chars per cell)]
    text: dict = field(default_factory=dict)  # kind → the largest text slot of its samples (chars)
    dark: set = field(default_factory=set)  # content kinds with a dark sample
    art: set = field(default_factory=set)  # content kinds with an art sample
    # the largest text box beside the code (code samples) or the screen (mock-ups), 0 when they have none: a sample
    # made to show code or a screen alone takes the slide's words as a line under its heading
    side_text: dict = field(default_factory=dict)

    _TEXT_ROLES = ("body", "bullet_list", "card_body", "card_title", "number_label", "subtitle")

    @classmethod
    def of(cls, manifest) -> "Room":
        room = cls()
        if manifest is None:
            return room
        for p in manifest.patterns:
            if getattr(p, "reference", None) or (p.quality or 0) < 0.2:
                continue
            kind = p.kind.value
            room.kinds.add(kind)
            if p.family.value == "dark":
                room.dark.add(kind)
            if p.art_layout or p.decor_boxes:
                room.art.add(kind)
            by_shape = {s.shape_id: s for s in p.slots}
            grouped: set = set()
            for g in p.repeat_groups:
                if not g.member_shape_ids:
                    continue
                cell = [by_shape[x] for x in g.member_shape_ids[0] if x in by_shape]
                chars = sum(s.capacity.max_chars for s in cell if s.role.value in cls._TEXT_ROLES)
                for ids in g.member_shape_ids:
                    grouped.update(ids)
                if chars > 0:
                    room.cells.setdefault(kind, []).append((max(1, g.min_n), max(g.max_n, len(g.member_shape_ids)), chars))
            single = [s.capacity.max_chars for s in p.slots if s.shape_id not in grouped and s.role.value in cls._TEXT_ROLES]
            if single:
                room.text[kind] = max(room.text.get(kind, 0), max(single))
            if kind in ("code", "mockup"):
                from verstka.rendering.compose import MONO_RE

                side = [s.capacity.max_chars for s in p.slots if s.role.value in ("body", "bullet_list", "card_body") and not MONO_RE.search(s.style.font_family or "")]
                room.side_text[kind] = max(room.side_text.get(kind, 0), max(side, default=0))
        return room

    def alone(self, kind: str) -> bool:
        """The template's samples of this kind show code or a screen alone (no text box beside it)."""
        return kind in self.kinds and self.side_text.get(kind, 0) < 120

    def holds(self, kind: str, n: Optional[int] = None) -> bool:
        if kind not in self.kinds:
            return False
        if n is None or kind not in self.cells:
            return True
        return any(lo <= n <= hi for lo, hi, _ in self.cells[kind])

    def per_cell(self, kind: str, n: int, default: int) -> int:
        fits = [c for lo, hi, c in self.cells.get(kind, []) if lo <= n <= hi]
        return max(fits) if fits else default

    def body(self, kind: str, default: int) -> int:
        return self.text.get(kind) or default


# ------------------------------------------------------------------ the forms of a slide


# how each variant shows the author's text: the forms it reaches for first and how much of every paragraph it shows
# («full»: the sentences that fit, «lead»: the first sentence of each, «dense»: as many as fit a denser setting)
PROFILES: dict = {
    "structured": {
        "prose": ("cards", "two_column", "bullets"),
        "image": ("image_text", "mockup"),
        "stages": ("process", "timeline", "cards"),
        "list": ("cards", "bullets"),
        "density": "full",
        "budget": 900,
    },
    "visual": {
        "prose": ("quote", "big_number", "cards", "bullets"),
        "image": ("mockup", "image_text"),
        "stages": ("timeline", "process", "cards"),
        "list": ("cards", "bullets"),
        "density": "lead",
        "budget": 600,
    },
    "compact": {
        "prose": ("two_column", "bullets", "cards"),
        "image": ("image_text", "mockup"),
        "stages": ("two_column", "process", "bullets"),
        "list": ("bullets", "two_column"),
        "density": "dense",
        "budget": 1300,
    },
}
# the forms in the timeline's words — the build page draws a slide's sketch from them (web/src/lib/stage.ts)
_RU_FORM = {
    "title": "обложка", "thanks": "финальный слайд", "agenda": "повестка", "section": "разделитель", "cards": "карточки с текстом",
    "two_column": "две колонки текста", "bullets": "список", "quote": "цитата", "big_number": "крупная цифра",
    "stat_row": "ряд цифр", "process": "шаги по порядку", "timeline": "этапы на шкале", "image_text": "текст и место под изображение",
    "mockup": "макет экрана под изображение", "code": "код и пояснение", "chart": "диаграмма", "table": "таблица",
}
_CHART_FORM = {"pie": "круговая диаграмма", "doughnut": "кольцевая диаграмма", "column": "столбчатая диаграмма", "bar": "горизонтальная диаграмма", "line": "линейный график", "area": "график с областями"}


def fit_sentences(ss: list[str], budget: int, *, lead_only: bool = False) -> list[str]:
    """Whole sentences from the start while they fit `budget` characters — the first one always (a sentence is never
    cut); `lead_only`: the first sentence alone — with the next one when the first is only a label of a few words
    («Анализ истории.» alone left its card nearly empty beside cards of a whole sentence)."""
    out: list[str] = []
    used = 0
    for s in ss:
        short_lead = lead_only and len(out) == 1 and (len(out[0]) < 40 or words(out[0]) <= 4)
        if out and ((lead_only and not short_lead) or used + len(s) + 1 > budget):
            break
        out.append(s)
        used += len(s) + 1
    return out


def _join(ss: list[str]) -> str:
    return " ".join(x.strip() for x in ss if x.strip())


# a sentence that states one figure as its point («Предварительный бюджет проекта составляет 85 000 рублей»)
_STATES_RE = re.compile(
    r"\b(?:составля\w+|составил\w*|равн\w+|достиг\w*|достига\w+|сократил\w*|сократ\w+|снизил\w*|сниз\w+|уменьшил\w*|"
    r"вырос\w*|выросл\w*|увеличил\w*|занимал\w*|занима\w+|освободил\w*|сэкономил\w*|окупит\w*|окупа\w+|принес\w*|"
    r"дает|даёт|дал[аио]?|стоит|стоил\w*)\b",
    re.I,
)
_FIGURE_RE = re.compile(rf"(?<![\w.,])(?P<num>{_NUM_SRC})\s?(?P<unit>%|[а-яё₽$€]+\.?(?:\s?[а-яё]+)?)?", re.I)


def figure_of(sentence: str) -> Optional[str]:
    """The figure a sentence states as its point, with its unit as a slide writes it («85 000 ₽», «45 мин», «31,25%»);
    None when the sentence has no single such figure."""
    if not _STATES_RE.search(sentence):
        return None
    found = [m for m in _VALUE_RE.finditer(sentence)]
    if len(found) != 1:
        return None
    m = found[0]
    num = m.group("num").replace(" ", " ")
    tail = sentence[m.end() :]
    if tail.startswith("%"):
        return f"{num}%"
    unit, _ = unit_of(tail)
    if unit is None:
        return None
    return f"{num}{unit}" if unit == "%" else f"{num} {unit}"


@dataclass
class Form:
    kind: str
    slide: object  # OutlineSlide
    shown: int = 0  # characters of the author's text the form shows
    # the form the text itself dictates (its code, its chart's data, its picture, its steps or stages): taken even when
    # the template has no sample of it (then it is composed), never traded for a form of its prose
    structural: bool = False
    # the variant's own form of the slide (the visual variant's row of key figures, the compact one's table): taken
    # when the template has no sample of it too — composed in the template's style
    own: bool = False


def _slide(r: Reading, kind: str, **kw):
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import OutlineSlide

    en = latin(r.text)
    head = r.title or ((r.of("code")[0].label or ("Code example" if en else "Пример кода")) if r.of("code") else "") or (f"Slide {r.number}" if en else f"Слайд {r.number}")
    s = OutlineSlide(id=f"u{r.number}", kind=PatternKind(kind), headline=head, spec_ref=r.number, verbatim=True, **kw)
    s.notes = notes_of(r)
    return s


def _shown(s) -> int:
    c = s.content
    n = sum(len(x) for x in (*c.bullets, *c.paragraphs))
    n += sum(len(it.title) + len(it.text) + sum(len(b) for b in it.bullets) for it in (*c.items, *c.columns))
    n += sum(len(x.label) for x in c.numbers) + len(c.quote or "")
    return n


def _content(**kw):
    from verstka.schemas.outline import SlideContent

    return SlideContent(**kw)


def _item(title: str = "", text: str = "", bullets: Optional[list] = None):
    from verstka.schemas.outline import SlideItem

    return SlideItem(title=title, text=text, bullets=list(bullets or []))


def _sentences_for(paras: list[list[str]], density: str, per: int, total: int) -> list[list[str]]:
    """Each paragraph's sentences the slide shows: the lead sentence (visual), or whole sentences up to `per` characters
    a paragraph, the slide's `total` kept — shared fairly: every paragraph first takes its share of the slide (its
    lead sentence at least), what the shares left goes to the paragraphs in order, a whole sentence at a time. Taken
    in order alone, the first paragraphs spent the slide and the last card kept one sentence of two beside half
    an empty card."""
    lead_only = density == "lead"
    n = max(len(paras), 1)
    fair = min(per, max(total, 0) // n)
    out = []
    spent = 0
    for ss in paras:
        got = fit_sentences(ss, fair, lead_only=lead_only)
        size = sum(len(x) + 1 for x in got)
        if out and spent + size > total:
            break  # the slide holds no more: the paragraphs left are the speaker's (as they always were)
        out.append(got)
        spent += size
    left = total - spent
    if lead_only:
        # the lead sentence, and the paragraph's figure when the lead does not state it («Затраты времени уменьшились на
        # 55,6%…» after «Снижение расхода воды составило 31,25%»): a visual slide shows less text, never fewer facts
        for ss, got in zip(paras, out):
            if len(got) >= len(ss) or len(got) >= 2:
                continue
            lead_figs = set(re.findall(r"\d+(?:[.,]\d+)?", " ".join(got)))
            nxt = next((x for x in ss[len(got):] if re.search(r"\d", x) and not set(re.findall(r"\d+(?:[.,]\d+)?", x)) <= lead_figs), None)
            if nxt is not None and len(nxt) + 1 <= left and len(nxt) <= per:
                got.append(nxt)
                left -= len(nxt) + 1
    if not lead_only:
        for ss, got in zip(paras, out):
            used = sum(len(x) + 1 for x in got)
            while len(got) < len(ss):
                nxt = len(ss[len(got)]) + 1
                if used + nxt > per or nxt > left:
                    break
                got.append(ss[len(got)])
                used += nxt
                left -= nxt
    return out


def _cards(r: Reading, paras: list[list[str]], room: Room, prof: dict) -> Optional[Form]:
    n = len(paras)
    if not 2 <= n <= 6:
        return None
    # (never less than a composed card holds: a template whose card samples are small — Классика's four cells of a
    # hundred characters — kept the first sentence of each paragraph, and when no sample took the slide the composed
    # cards stood half empty with the rest of the author's text in the notes)
    per = max(room.per_cell("cards", n, 340), 340)
    per = max(140, min(int(per * 0.82), 480))
    if prof["density"] == "dense":
        per = int(per * 1.15)
    got = _sentences_for(paras, prof["density"], per, prof["budget"])
    if len(got) < n:
        return None
    labels = _labels(r, paras)
    items = [_item(title=lbl, text=_join(ss)) for lbl, ss in zip(labels, got)]
    s = _slide(r, "cards", content=_content(items=items), footnote=r.footnote, takeaway=r.takeaway, subtitle=r.lead)
    return Form("cards", s, _shown(s))


def _labels(r: Reading, paras: list[list[str]]) -> list[str]:
    """The paragraphs' subheadings (para_labels) when `paras` are the slide's own paragraphs, else none."""
    got = r.para_labels()
    return got if len(got) == len(paras) else [""] * len(paras)


def _labelled(label: str, line: str) -> str:
    return f"{label}: {line}" if label else line


def _columns(r: Reading, paras: list[list[str]], room: Room, prof: dict) -> Optional[Form]:
    n = len(paras)
    if n < 2:
        return None
    per_col = room.per_cell("two_column", 2, room.body("two_column", 700))
    per_col = max(300, min(int(per_col * 0.85), 900))
    total = min(prof["budget"], 2 * per_col)
    got = _sentences_for(paras, "full" if prof["density"] != "lead" else "lead", max(per_col // max(1, (n + 1) // 2), 160), total)
    half = (len(got) + 1) // 2
    labels = _labels(r, paras)
    lines = [_labelled(lbl, _join(ss)) for lbl, ss in zip(labels, got)]
    cols = [lines[:half], lines[half:]]
    if not cols[1]:
        return None
    items = [_item(bullets=col) for col in cols]
    s = _slide(r, "two_column", content=_content(columns=items), footnote=r.footnote, takeaway=r.takeaway, subtitle=r.lead)
    return Form("two_column", s, _shown(s))


def _bullets(r: Reading, paras: list[list[str]], room: Room, prof: dict) -> Optional[Form]:
    if not paras:
        return None
    total = min(prof["budget"], max(int(room.body("bullets", 700) * 0.9), 420))
    per = 260 if prof["density"] != "dense" else 340
    got = _sentences_for(paras, prof["density"], per, total)
    labels = _labels(r, paras)
    lines = [_labelled(lbl, _join(ss)) for lbl, ss in zip(labels, got) if ss]
    # (short lines — a step, an item — are a list: up to eight, as a list is shown; longer ones six)
    lines = lines[: 8 if lines and all(words(x) <= 12 for x in lines) else 6]
    if len(paras) == 1 and len(paras[0]) >= 3 and prof["density"] != "lead":
        lines = fit_sentences(paras[0], total)[:6]
        if lines and labels[0]:
            lines[0] = _labelled(labels[0], lines[0])
    s = _slide(r, "bullets", content=_content(bullets=lines), footnote=r.footnote, takeaway=r.takeaway, subtitle=r.lead)
    return Form("bullets", s, _shown(s))


def _quote(r: Reading, paras: list[list[str]]) -> Optional[Form]:
    """The slide's quoted message large — only on a slide that says little besides it (two paragraphs at most): a
    quote standing for five paragraphs would leave the slide's point in the notes."""
    q = r.quote_by()
    if q is None or len(paras) > 2:
        return None
    text, intro, by = q
    sub = intro if intro and words(intro) <= 20 else None
    s = _slide(r, "quote", content=_content(quote=text, quote_author=by), subtitle=sub, footnote=r.footnote, takeaway=r.takeaway)
    return Form("quote", s, _shown(s))


def _figure(r: Reading, paras: list[list[str]], prof: dict) -> Optional[Form]:
    """The slide's one stated figure large, its sentence under it whole; the other paragraphs' lead sentences beside."""
    from verstka.schemas.outline import NumberCallout

    hero = None
    for i, ss in enumerate(paras):
        for s_ in ss:
            fig = figure_of(s_)
            if fig and len(s_) <= 150:
                hero = (i, s_, fig)
                break
        if hero:
            break
    if hero is None:
        return None
    i, sent, fig = hero
    rest = [fit_sentences(ss, 220, lead_only=True)[0] for j, ss in enumerate(paras) if j != i and ss][:2]
    s = _slide(r, "big_number", content=_content(numbers=[NumberCallout(value=fig, label=H.strip_end(sent))], bullets=rest), footnote=r.footnote, takeaway=r.takeaway)
    return Form("big_number", s, _shown(s))


def _side_blocks(r: Reading, skip_label: bool = False) -> list[list[str]]:
    """The slide's text beside its code, picture or chart, in the author's order: a paragraph's sentences (one block), a
    list's lead line and each of its items (a block each), a sequence «а → б → в» as one line. `skip_label`: the first
    list's lead line is the slide's subtitle."""
    out: list[list[str]] = []
    first_list = True
    for p in r.parts:
        if p.kind == "para":
            ss = [x for x in p.sentences if x not in r.used]
            if ss:
                out.append(ss)
        elif p.kind == "list":
            if p.label and not (skip_label and first_list):
                out.append([p.label + ":"])
            first_list = False
            out.extend([x] for x in p.items)
        elif p.kind == "flow":
            out.append([(f"{p.label}: " if p.label else "") + " → ".join(p.items)])
    return out


def _list_lead(r: Reading) -> Optional[str]:
    """The lead line of the list that opens the slide («Панель показывает оператору главное:»): the slide's subtitle when
    the text gives none."""
    if r.lead is None and r.parts and r.parts[0].kind == "list" and r.parts[0].label and words(r.parts[0].label) <= 20:
        return r.parts[0].label
    return None


_PLACE_ASK_RE = re.compile(r"^(?:(?:здесь|тут|ниже)\s+(?:будет|нужн\w*|появится)|нужн\w*|добав\w*|встав\w*|место\s+(?:под|для))\s+", re.I)


def _place_of(part: Part, en: bool = False) -> tuple[str, str]:
    """(the place's caption head, what goes there in the author's words) for a picture, or for a chart, a table or
    another thing the note asks for without the data to draw it («[Здесь будет круговая диаграмма бюджета]»). `en`:
    the text is English — so are the heads."""
    if part.kind == "image":
        return ("Image" if en else "Изображение"), H.cap_first(part.text.strip()) if part.text else ""
    said = " ".join(": ".join(x for x in (part.label, part.text) if x).split())
    hint = H.cap_first(_PLACE_ASK_RE.sub("", said).strip())
    if part.kind == "chart":
        return ("Place for a chart" if en else "Место под диаграмму"), hint
    if part.kind == "table":
        return ("Place for a table" if en else "Место под таблицу"), hint
    if re.search(r"видео|video|ролик", said, re.I):
        return ("Place for a video" if en else "Место под видео"), hint
    return ("Place for an image" if en else "Место под изображение"), hint


# «не заполняй это место сгенерированным изображением», «без сгенерированных картинок», «не генерируй картинку»
_NO_GEN_RE = re.compile(r"не\s+(?:\S+\s+){0,4}?сгенерированн|без\s+(?:\S+\s+){0,1}?сгенерированн|не\s+генерируй", re.I)


def own_photo(text: str) -> bool:
    """The slide's text keeps its picture place for the author's own photo («Фото я добавлю самостоятельно», «оставь
    место под фотографию помещения», «не заполняй его сгенерированным изображением»): the image generator leaves it
    free. The bracketed notes that only describe the picture («[Место под изображение: …]») do not count."""
    from verstka.planning.brief_structure import is_photo_instruction

    plain = _INLINE_NOTE_RE.sub(" ", text or "")
    return bool(_NO_GEN_RE.search(plain)) or any(is_photo_instruction(x) for x in sentences(plain))


def _image(r: Reading, room: Room, prof: dict, kind: str, part: Optional[Part] = None) -> Optional[Form]:
    """The slide's text beside the place for its picture (or for the chart, the table, the video its note asks for
    without its data), the place captioned with what goes there."""
    part = part or r.of("image")[0]
    label, hint = _place_of(part, latin(r.text))
    if part.kind == "image" and part.label and not re.match(r"мест\w*\s+(?:под|для)", part.label, re.I):
        label = H.cap_first(part.label)
    sub = r.lead or _list_lead(r)
    # (a column beside a picture holds less than a slide of text, whatever the template's largest text slot)
    total = min(prof["budget"], 900, max(int(room.body(kind, 640) * 0.85), 360))
    per = 230 if prof["density"] != "dense" else 320
    got = _sentences_for(_side_blocks(r, skip_label=sub is not None and r.lead is None), "lead" if prof["density"] == "lead" else "full", per, total)
    lines = [_join(ss) for ss in got if ss][:6]
    if kind == "mockup" and room.alone("mockup"):
        # the template's screen mock-up stands alone on its slide (a device under the heading, no text box beside it):
        # the screen and its caption say it, the paragraphs are the speaker's — all but the slide's first sentence,
        # which stays under the heading as its lede: a slide never shows its heading and an empty place alone (where
        # no sample of the template took it, Классика's composed panel slide said nothing at all)
        if sub is None and got and got[0]:
            sub = got[0][0]
        lines = []
    own = part.kind != "image" or own_photo(r.text)  # a chart, a table, a video the author adds — or their own photo
    s = _slide(r, kind, content=_content(bullets=lines, photo_slot=label, photo_hint=hint or None, photo_own=own), footnote=r.footnote, takeaway=r.takeaway, subtitle=sub)
    return Form(kind, s, _shown(s))


def _code(r: Reading, room: Room, prof: dict) -> Form:
    from verstka.schemas.outline import CodeBlock

    code = r.of("code")[0]
    total = {"lead": 380, "full": 520, "dense": 700}[prof["density"]]
    total = min(total, max(int(room.body("code", 600) * 0.9), 260))
    sub = r.lead or _list_lead(r)
    got = _sentences_for(_side_blocks(r, skip_label=sub is not None and r.lead is None), "full" if prof["density"] != "lead" else "lead", total, total)
    lines = [_join(ss) for ss in got if ss]
    if prof["density"] == "lead" and room.alone("code"):
        # the visual variant takes the template's own code slide, made to show code alone: the code under the slide's
        # heading, the explanation in the speaker notes (the other variants show it beside the code)
        lines = []
    c = _content(paragraphs=lines, code=CodeBlock(text=code.text, language=code.lang, caption=code.label or None))
    s = _slide(r, "code", content=c, footnote=r.footnote, takeaway=r.takeaway, subtitle=sub)
    return Form("code", s, _shown(s))


# the words of a chart note that ask for the chart or name its type, not its subject: «Нужна круговая диаграмма
# распределения бюджета» → «распределения бюджета»
_ASK_WORDS_RE = re.compile(
    r"\b(?:нужн\w*|необходим\w*|требуется|добав\w*|покаж\w*|постро\w*|нарису\w*|встав\w*|сдела\w*|размест\w*|"
    r"(?:здесь|тут|ниже)\s+(?:будет|нужн\w*)|место\s+(?:под|для)|please|add|show|insert|need(?:ed|s)?|make|place\s+for)\b",
    re.I,
)
_CHART_NOUN_RE = re.compile(
    r"\b(?:(?:сравнительн|столбчат|кругов|кольцев|линейн|горизонтальн|секторн|точечн|отдельн)\w*\s+)*(?:диаграмм|график|гистограмм)\w*\b|"
    r"\b(?:(?:column|bar|pie|line|area|doughnut|donut|comparison|separate)\s+)*(?:chart|graph|plot)s?\b",
    re.I,
)
_TABLE_NOUN_RE = re.compile(r"\b(?:(?:сравнительн|итогов|сводн)\w*\s+)*таблиц\w*\b|\b(?:comparison\s+)?tables?\b", re.I)


def chart_title(label: str) -> Optional[str]:
    """The subject of a chart or table note as its title: the request and the chart's type taken out wherever they
    stand, the words after the chart noun back in the nominative («распределения бюджета» → «Распределение бюджета»)."""
    t = " ".join((label or "").split())
    if not t:
        return None
    t = _ASK_WORDS_RE.sub(" ", t)
    m = _CHART_NOUN_RE.search(t) or _TABLE_NOUN_RE.search(t)
    after_noun = False
    if m is not None:
        after_noun = not t[: m.start()].strip(" ,:—–-")
        t = t[: m.start()] + " " + t[m.end() :]
    t = " ".join(t.split()).strip(" ,:—–-.")
    t = re.sub(r"^(?:по|для|of|for)\s+", "", t, flags=re.I)
    if not t or not re.search(r"[A-Za-zА-Яа-яЁё]", t):
        return None
    if after_noun and re.match(r"[а-яё]", t, re.I):
        # the words after the chart's noun are its genitive complement («распределения бюджета»): a title only when they
        # come back to the nominative («цен» would not read as one)
        try:
            from verstka.planning.brief_structure import _nominative_of_genitive

            nom = _nominative_of_genitive(t)
        except Exception:  # noqa: BLE001
            nom = None
        if not nom:
            return None
        t = nom
    return H.cap_first(t)


def charts_of(r: Reading):
    """The charts the slide's notes ask for, drawn from each note's own data: [ChartSpec] (a split chart — one chart
    per indicator side by side — for figures of different units or when the note asks for it). A note whose data no
    chart shows as written gives none: a range («40–60 рублей»), items with different counts of figures, single
    figures of different units (litres beside minutes), a single figure — its data is a table or a row of figures
    (`note_table`, `note_figures`)."""
    from verstka.schemas.outline import ChartSpec, InlineSeries

    out = []
    for note in r.of("chart"):
        items = chart_items(note.text)
        if not items:
            # «[Столбчатая диаграмма: выручка по городам]» over a «|» table: the chart of every column of the table
            src = source_table(r, note)
            got = table_chart(note, src) if src is not None else None
            if got is not None:
                out.append(got)
            continue
        if any(it.span for it in items) or not note_covered(note.text, items):
            continue  # (a note read in part is shown as written: never a chart without some of its figures)
        sizes = {len(it.values) for it in items}
        if len(sizes) != 1:
            continue
        k = next(iter(sizes))
        units = {it.unit for it in items}
        if k == 1 and (len(items) < 2 or len(units) > 1):
            continue
        kind = chart_type_of(note.label, items)
        title = chart_title(note.label) if note.label else None
        if k == 1:
            unit = next(iter(units))
            out.append(ChartSpec(type=kind, title=title, unit=unit, categories=[it.label for it in items], series=[InlineSeries(name=title or "", values=[it.values[0] for it in items])]))
            continue
        names = pair_names(_pair_context(r, note, items), k, whole=r.text)
        if unnamed(names):
            continue  # figures the text does not name: no legend «1» / «2» — the note's rows as written (note_table)
        split = bool(_EACH_RE.search(note.text)) or len(units) > 1
        if split:
            series = [InlineSeries(name=it.label, values=list(it.values), unit=unit_label(it.unit, it.unit_words)) for it in items]
            out.append(ChartSpec(type="column" if kind in ("pie", "doughnut", "line", "area") else kind, title=title, categories=names, series=series, split=True))
        else:
            series = [InlineSeries(name=nm, values=[it.values[j] for it in items]) for j, nm in enumerate(names)]
            out.append(ChartSpec(type=kind if kind not in ("pie", "doughnut") else "column", title=title, unit=next(iter(units)) if units else None, categories=[it.label for it in items], series=series))
    return out


def _table_rows(part: "Part") -> list[list[str]]:
    """The rows of a «|» table part (its header first), [] when it is not one of two rows or more of equal width."""
    rows = [ln.strip().strip("|").split("|") for ln in (part.text or "").splitlines() if ln.strip().startswith("|")]
    rows = [[c.strip() for c in row] for row in rows if not all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in row)]
    return rows if len(rows) >= 2 and len({len(x) for x in rows}) == 1 else []


def source_table(r: "Reading", note: "Part") -> Optional["Part"]:
    """The «|» table a chart note without figures of its own is drawn from: the table right after it (or right before
    it) — «[Столбчатая диаграмма: выручка по городам]» over the table of the cities' figures, «[Диаграмма по данным
    таблицы]» under it."""
    if note.kind != "chart" or chart_items(note.text):
        return None
    k = next((i for i, p in enumerate(r.parts) if p is note), None)
    if k is None:
        return None
    for j in (k + 1, k - 1):
        if 0 <= j < len(r.parts) and r.parts[j].kind == "table" and _table_rows(r.parts[j]):
            return r.parts[j]
    return None


_CELL_RE = re.compile(rf"^(?P<num>{_NUM_SRC})\s?(?P<rest>.*)$")


def table_chart(note: "Part", table: "Part"):
    """The chart of a table a chart note asks for: the rows' first cells as its categories, every other column a series
    (its header the series' name) — every cell a figure (with one unit per column), else None (the table is shown as
    it is). Several series are never a pie; columns of different units are a split chart."""
    from verstka.schemas.outline import ChartSpec, InlineSeries

    rows = _table_rows(table)
    if len(rows) < 3 or len(rows[0]) < 2:
        return None
    head, body = rows[0], rows[1:]
    cats = [H.strip_end(row[0]) for row in body]
    if not all(cats) or len(set(cats)) != len(cats):
        return None
    cols = []
    for j in range(1, len(head)):
        vals, units = [], set()
        for row in body:
            m = _CELL_RE.match(thousands(row[j]).strip())
            if m is None:
                return None
            unit, after = unit_of(m.group("rest"))
            if after and not unit:
                return None  # words after the figure: a cell of text, not a value
            vals.append(number_value(m.group("num")))
            units.add(unit)
        if len(units) > 1:
            return None
        cols.append((head[j] or f"Ряд {j}", vals, next(iter(units))))
    label = note.label or note.text or ""
    kind = chart_type_of(label, [])
    if len(cols) > 1 and kind in ("pie", "doughnut"):
        kind = "column"
    title = (chart_title(note.label) or H.cap_first(H.strip_end(note.text or "")) or None) if note.label else chart_title(note.text or "")
    units = {u for _, _, u in cols}
    if len(units) > 1:
        series = [InlineSeries(name=nm, values=vals, unit=u) for nm, vals, u in cols]
        return ChartSpec(type="column" if kind in ("pie", "doughnut", "line", "area") else kind, title=title, categories=cats, series=series, split=True)
    series = [InlineSeries(name=nm, values=vals) for nm, vals, _ in cols]
    return ChartSpec(type=kind, title=title, unit=next(iter(units)), categories=cats, series=series)


def _drawn_tables(r: "Reading") -> set:
    """The tables (ids of their parts) the slide's chart notes are drawn from: shown as the chart, never again as a
    table of their own."""
    out = set()
    for note in r.of("chart"):
        src = source_table(r, note)
        if src is not None and table_chart(note, src) is not None:
            out.add(id(src))
    return out


def _data_notes(r: "Reading") -> list:
    drawn = _drawn_tables(r)
    return [n for n in r.of("chart") + r.of("table") if id(n) not in drawn]


def _cell(raw: str, unit: Optional[str], span_text: str = "") -> str:
    return " ".join(x for x in (raw.replace(" ", "\u00a0"), unit or "") if x)


def note_table(r: Reading):
    """The table a slide's notes give: a table written with «|» as it is (ten rows at most), else the items of a table or
    chart note no chart shows as written — a row per item, its figures as the note writes them («40–60 ₽»). None when
    the notes give no rows."""
    from verstka.schemas.outline import TableData

    for note in r.of("table"):
        rows = [ln.strip().strip("|").split("|") for ln in note.text.splitlines() if ln.strip().startswith("|")]
        rows = [[c.strip() for c in row] for row in rows if not all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in row)]
        if len(rows) >= 2 and len({len(x) for x in rows}) == 1:
            return TableData(columns=rows[0], rows=rows[1:])  # every row: a long table goes on over a second slide
    for note in [*r.of("table"), *r.of("chart")]:
        items = chart_items(note.text)
        if items and not note_covered(note.text, items):
            rows = _rows_as_written(note.text)
            if len(rows) >= 2:
                head = chart_title(note.label) or ("Value" if latin(r.text) else "Значение")
                return TableData(columns=["", head], rows=rows, caption=chart_title(note.label))
            continue
        if len(items) < 2:
            continue
        k = max(len(it.values) for it in items)
        if any(it.span for it in items):
            cols = ["", chart_title(note.label) or ("Value" if latin(r.text) else "Значение")]
            rows = [[it.label, _span_cell(it)] for it in items]
            return TableData(columns=cols, rows=rows, caption=chart_title(note.label))
        if len({len(it.values) for it in items}) != 1:
            continue
        names = pair_names(_pair_context(r, note, items), k, whole=r.text) if k >= 2 else []
        if names and not unnamed(names):
            rows = [[it.label, *[_cell(x, it.unit) for x in it.raw]] for it in items]
            return TableData(columns=["", *names], rows=rows, caption=chart_title(note.label))
        # figures the text does not name (two of each, nothing said of which is which): each row as the note writes it
        head = chart_title(note.label) or ("Value" if latin(r.text) else "Значение")
        rows = [[it.label, H.strip_end(it.text)] for it in items]
        return TableData(columns=["", head], rows=rows, caption=chart_title(note.label))
    return None


# the organisers' rule: a table shows ten rows at most; a longer one goes on over continuation slides
MAX_TABLE_ROWS = 10
_TOTAL_ROW_RE = re.compile(r"^(?:итого|всего|итог|сумма|среднее|в\s+среднем|total|sum|average|mean)\b", re.I)


def split_long_tables(slides: list) -> list[tuple]:
    """The deck's slides with every table of more than MAX_TABLE_ROWS rows split over continuation slides — «Продажи
    по месяцам (продолжение)», the header repeated, the parts as even as they can be, the totals rows («Итого»,
    «Среднее») with the last part, the slide's lines and subtitle with the first part and its conclusion and footnote
    with the last. No row of the author is lost or left to the notes. Returns (slide, the slide's index in `slides`,
    the part: 0 for the slide itself, 1… for its continuations)."""
    import math

    out: list[tuple] = []
    for i, s in enumerate(slides):
        t = s.content.table
        if t is None or len(t.rows) <= MAX_TABLE_ROWS:
            out.append((s, i, 0))
            continue
        rows = [list(r) for r in t.rows]
        tail: list = []
        while rows and len(tail) < 3 and _TOTAL_ROW_RE.match(str(rows[-1][0] if rows[-1] else "").strip()):
            tail.insert(0, rows.pop())
        k = max(2, math.ceil((len(rows) + len(tail)) / MAX_TABLE_ROWS))
        size = math.ceil(len(rows) / k)
        chunks = [rows[j : j + size] for j in range(0, len(rows), size)]
        if len(chunks[-1]) + len(tail) <= MAX_TABLE_ROWS:
            chunks[-1] = chunks[-1] + tail
        else:
            chunks.append(tail)
        more = "(continued)" if latin(s.headline) else "(продолжение)"
        for j, chunk in enumerate(chunks):
            c = s.model_copy(deep=True)
            c.content.table = t.model_copy(update={"rows": chunk})
            if j > 0:
                c.headline = f"{H.strip_end(s.headline)} {more}"
                c.subtitle = None
                c.content.bullets = []
                c.content.paragraphs = []
                c.notes = ""
            if j < len(chunks) - 1:
                c.takeaway = None
                c.footnote = None
            out.append((c, i, j))
    return out


def _rows_as_written(body: str) -> list[list[str]]:
    """A note's items as it writes them, a row each («Пекарня на Ленина» | «420 и 380 кг»): what no chart could read whole
    is still shown, never dropped."""
    data = _note_data(body)
    sm = _SUBJECT_RE.match(data)
    if sm is not None and _items_follow(sm.group("rest")):
        data = sm.group("rest")
    rows = []
    for chunk in (c.strip(" .") for part in _ITEM_SEP_RE.split(H.strip_end(data)) for c in _COMMA_ITEM_RE.split(part)):
        if not chunk:
            continue
        m = _LABEL_SEP_RE.search(chunk)
        rows.append([H.cap_first(chunk[: m.start()].strip()), chunk[m.end() :].strip()] if m else ["", chunk])
    return rows


def _span_cell(it: ChartItem) -> str:
    if it.span and len(it.raw) == 2:
        return _cell(f"{it.raw[0]}–{it.raw[1]}", it.unit)
    return ", ".join(_cell(x, it.unit) for x in it.raw)


def note_figures(r: Reading):
    """Single figures of different things a chart note gives (litres beside minutes, one figure alone): each its own
    callout, labelled by the note. None when the note gives none such."""
    from verstka.schemas.outline import NumberCallout

    for note in r.of("chart"):
        items = chart_items(note.text)
        if not items or len(items) > 4 or any(len(it.values) != 1 or it.span for it in items) or not note_covered(note.text, items):
            continue
        if len(items) >= 2 and len({it.unit for it in items}) == 1:
            continue  # one measure: a chart
        return [NumberCallout(value=_cell(it.raw[0], it.unit), label=it.label + (f" ({it.unit_words})" if it.unit_words else "")) for it in items]
    return None


def lines_beside_data(paras: list[list[str]], density: str) -> list[str]:
    """The sentences that stand beside a chart or a table: the first sentence of the first paragraph (what the data is)
    and of the last one (what it means), then of the others — one for the visual variant, up to four for the compact."""
    n = {"lead": 1, "full": 2, "dense": 4}[density]
    picks: list[str] = []
    if paras:
        order = [0, len(paras) - 1] + list(range(1, len(paras) - 1))
        for j in dict.fromkeys(order):
            ss = paras[j]
            if ss and len(picks) < n:
                picks.append(ss[0])
    return picks


def _beside(r: Reading, prof: dict) -> list[str]:
    """The lines beside the slide's data: its paragraphs' sentences (`lines_beside_data`), then — while there is room —
    its list whole, the lead line and every item (a list is never cut)."""
    n = {"lead": 1, "full": 2, "dense": 4}[prof["density"]]
    picks = lines_beside_data(r.paras(), prof["density"])
    for p in r.of("list"):
        if len(picks) >= n:
            break
        picks.extend(([p.label + ":"] if p.label else []) + p.items)
    return picks


def _block(r: "Reading", note: "Part") -> "Reading":
    """One data note of a slide as a reading of its own (with the slide's sentences, which may name its figures, and
    the table a chart note is drawn from)."""
    src = source_table(r, note)
    return Reading(number=r.number, title=r.title, parts=[note, *([src] if src is not None else []), *r.of("para")], text=r.text)


def _drawable(b: "Reading") -> bool:
    return bool(charts_of(b) or note_table(b) or note_figures(b)) or bool(b.parts and b.parts[0].kind == "image")


# the pictures of one slide that get a place of their own: the first beside the slide's text, the second on a
# continuation slide (a pair — before and after, two views — is the usual case); a gallery's further pictures stay
# described in the speaker notes (more continuations of one heading would repeat each other: the audit's
# duplicate_heading / duplicate_slides)
MAX_PICTURES = 2


def _picture_blocks(r: "Reading", skip: int = 1) -> list:
    """The slide's pictures its form does not show, each a reading of its own (a continuation slide's place)."""
    return [_block(r, p) for p in r.of("image")[skip:MAX_PICTURES]]


def _with_picture(r: "Reading", f: "Form") -> int:
    """The slide's first picture in its place beside the form's code or data, when the form keeps no place of its own
    (the place for a chart the author will add): how many of the slide's pictures the slide now shows."""
    imgs = r.of("image")
    c = f.slide.content
    if not imgs or c.photo_slot:
        return 0
    label, hint = _place_of(imgs[0], latin(r.text))
    if imgs[0].label and not re.match(r"мест\w*\s+(?:под|для)", imgs[0].label, re.I):
        label = H.cap_first(imgs[0].label)
    c.photo_slot, c.photo_hint, c.photo_own = label, hint or None, own_photo(r.text)
    return 1


def _left_over(r: "Reading", f: "Form") -> list:
    """The data notes of a slide its form does not show: the chart form shows the first two charts, the table form the
    first table, the figures form the first figures — the others are each a block of a continuation slide."""
    notes = _data_notes(r)
    if len(notes) < 2:
        return []
    blocks = [(n, _block(r, n)) for n in notes]
    if f.kind == "chart":
        drawn = [n for n, b in blocks if charts_of(b)][:2]
    elif f.kind == "table":
        drawn = [n for n, b in blocks if note_table(b)][:1]
    elif f.kind in ("stat_row", "big_number"):
        drawn = [n for n, b in blocks if note_figures(b)][:1]
    else:
        drawn = notes[:1]
    return [b for n, b in blocks if n not in drawn and _drawable(b)]


def _block_form(b: "Reading", profile: str) -> Optional["Form"]:
    prof = PROFILES.get(profile, PROFILES["structured"])
    if b.parts and b.parts[0].kind == "image":
        return _image(b, Room(), prof, "image_text", part=b.parts[0])
    return _chart(b, prof) or _table(b, prof) or _numbers(b, prof)


def expand_slides(slides: list, readings: Optional[list] = None, profile: str = "structured") -> list[tuple]:
    """The deck's slides with their continuations: a slide's other data blocks (`Reading.extra`) each on a slide «…
    (продолжение)» right after it, and every table longer than a slide shows split (split_long_tables). The slide's
    lines and subtitle stay with its first part, its conclusion and footnote go with its last. Returns (slide, the
    slide's index in `slides`, the part: 0 for the slide itself, 1… for its continuations)."""
    grouped: list[list] = []
    for i, s in enumerate(slides):
        group = [s.model_copy(deep=True)]
        r = readings[i] if readings is not None and i < len(readings) else None
        for b in (r.extra if r is not None else []):
            f = _block_form(b, profile)
            if f is None:
                continue
            c = f.slide.model_copy(deep=True)
            c.spec_ref, c.verbatim = s.spec_ref, True
            group.append(c)
        grouped.append(group)
    out: list[tuple] = []
    for i, group in enumerate(grouped):
        take, foot = group[0].takeaway, group[0].footnote
        parts = [x for g in group for x, _, _ in split_long_tables([g])]
        more = "(continued)" if latin(group[0].headline) else "(продолжение)"
        last = parts[-1]
        for j, c in enumerate(parts):
            if j > 0:
                c.headline = f"{H.strip_end(group[0].headline)} {more}"
                c.subtitle = None
                c.content.bullets = []
                c.content.paragraphs = []
                c.notes = ""
            c.takeaway = (take or c.takeaway) if c is last else None
            c.footnote = (foot or c.footnote) if c is last else None
            out.append((c, i, j))
    return out


def _chart(r: Reading, prof: dict) -> Optional[Form]:
    charts = charts_of(r)
    if not charts:
        return None
    c = _content(chart=charts[0], chart2=charts[1] if len(charts) > 1 else None, bullets=_beside(r, prof))
    s = _slide(r, "chart", content=c, footnote=r.footnote, takeaway=r.takeaway, subtitle=r.lead)
    return Form("chart", s, _shown(s))


def _table(r: Reading, prof: dict) -> Optional[Form]:
    t = note_table(r)
    if t is None:
        return None
    s = _slide(r, "table", content=_content(table=t, bullets=_beside(r, prof)[:2]), footnote=r.footnote, takeaway=r.takeaway, subtitle=r.lead)
    return Form("table", s, _shown(s))


def _numbers(r: Reading, prof: dict) -> Optional[Form]:
    nums = note_figures(r)
    if not nums:
        return None
    kind = "big_number" if len(nums) == 1 else "stat_row"
    s = _slide(r, kind, content=_content(numbers=nums, bullets=_beside(r, prof)[:2]), footnote=r.footnote, takeaway=r.takeaway, subtitle=r.lead)
    return Form(kind, s, _shown(s))


def _process(r: Reading, paras: list[list[str]], kind: str, prof: Optional[dict] = None) -> Optional[Form]:
    """The author's sequence («датчики → проверка показаний → …») as steps, headed by its own label («Последовательность
    работы») — never under a sentence that counts something else («состоит из четырех этапов» over five steps) —; the
    opening sentence of each paragraph of the slide under the steps, as many as the variant shows («28 °C … 25 °C»
    stayed only in the notes of a half-empty slide)."""
    flow = r.of("flow")
    if not flow:
        return None
    steps = flow[0].items[:8]
    label = H.strip_end(flow[0].label or "")
    sub = None
    leads = [p[0] for p in paras if p and words(p[0]) <= 32]
    if label and words(label) <= 8:
        sub = label
    elif paras and paras[0] and words(paras[0][0]) <= 30:
        sub = H.strip_end(paras[0][0])
        leads = leads[1:]
    keep = {"lead": 2, "full": 3, "dense": 4}.get((prof or {}).get("density", "full"), 3)
    s = _slide(r, kind, content=_content(items=[_item(title=x) for x in steps], bullets=leads[:keep]), subtitle=sub or r.lead, footnote=r.footnote, takeaway=r.takeaway)
    return Form(kind, s, _shown(s))


def _stages(r: Reading, room: Room, prof: dict, kind: str) -> Optional[Form]:
    st = r.stages()
    if not st:
        return None
    per = max(room.per_cell(kind, len(st), 260), 260)  # (never less than a composed step holds, as `_cards`)
    per = max(120, min(int(per * 0.8), 360))
    items = []
    for name, ss in st[:6]:
        items.append(_item(title=name, text=_join(fit_sentences(ss, per, lead_only=(prof["density"] == "lead")))))
    if kind == "two_column":
        return None
    s = _slide(r, kind, content=_content(items=items), footnote=r.footnote, takeaway=r.takeaway, subtitle=r.lead)
    return Form(kind, s, _shown(s))


def list_intro(r: Reading) -> Optional[str]:
    """The short paragraph that opens the slide over its list («Мы прошли три шага за месяц.» and the steps): the
    subtitle of the list's forms when the list has no lead line of its own."""
    if len(r.parts) >= 2 and r.parts[0].kind == "para" and r.parts[1].kind == "list" and not r.parts[1].label:
        ss = [x for x in r.parts[0].sentences if x not in r.used]
        if 1 <= len(ss) <= 2 and sum(words(x) for x in ss) <= 30:
            return H.strip_end(" ".join(ss))
    return None


def lead_paragraph(r: Reading) -> Optional[str]:
    """The paragraph that opens the slide before its list or its data (the coffee shop's area, seats and hours over its
    figure list): its sentences not used elsewhere, when it is short enough to stand as the slide's lead (three
    sentences, fifty words at most). None when the slide opens with its list or data."""
    if len(r.parts) < 2 or r.parts[0].kind != "para" or r.parts[1].kind not in ("list", "chart", "table", "flow"):
        return None
    ss = [x for x in r.parts[0].sentences if x not in r.used]
    if 1 <= len(ss) <= 3 and sum(words(x) for x in ss) <= 50:
        return " ".join(end_sentence(x) for x in ss)
    return None


def _list_form(r: Reading, kind: str, prof: dict) -> Optional[Form]:
    lst = r.of("list")
    if not lst:
        return None
    items = lst[0].items
    sub = lst[0].label or r.lead or list_intro(r)
    if kind == "cards":
        if not (2 <= len(items) <= 6 and all(len(x) <= 160 for x in items)):
            return None
        s = _slide(r, "cards", content=_content(items=[_item(title=x) for x in items]), subtitle=sub, footnote=r.footnote, takeaway=r.takeaway)
        return Form("cards", s, _shown(s))
    if kind == "two_column":
        if len(items) < 4:
            return None
        half = (len(items) + 1) // 2
        cols = [_item(bullets=items[:half]), _item(bullets=items[half:10])]
        s = _slide(r, "two_column", content=_content(columns=cols), subtitle=sub, footnote=r.footnote, takeaway=r.takeaway)
        return Form("two_column", s, _shown(s))
    s = _slide(r, "bullets", content=_content(bullets=items[:8]), subtitle=sub, footnote=r.footnote, takeaway=r.takeaway)
    return Form("bullets", s, _shown(s))


def forms_of(r: Reading, room: Room, profile: str) -> list[Form]:
    """The slide's forms in the order the variant reaches for them (the first that the template holds wins later). Never
    empty: a slide with nothing but its heading and a note for the designer shows the place for what the note asks."""
    prof = PROFILES.get(profile, PROFILES["structured"])
    paras = r.paras()
    out: list[Optional[Form]] = []
    if r.of("code"):
        f = _code(r, room, prof)
        r.extra = [b for b in (_block(r, n) for n in _data_notes(r)) if _drawable(b)] + _picture_blocks(r, _with_picture(r, f))
        return [f]
    notes = _data_notes(r)
    if notes:
        # the chart the note's data draws; else its table (a range, items of different counts), its figures (litres
        # beside minutes), or — no data at all — the place for the chart the author will add. The notes the form does
        # not show go on over continuation slides (a chart beside a table, a third chart)
        f = _chart(r, prof) or _table(r, prof) or _numbers(r, prof) or _image(r, room, prof, "image_text", part=notes[0])
        f.structural = True
        r.extra = _left_over(r, f) + _picture_blocks(r, _with_picture(r, f))
        return [f]
    if r.of("image"):
        hint = r.of("image")[0].text + " " + r.of("image")[0].label
        kinds = list(prof["image"]) if _SCREEN_RE.search(hint) else ["image_text"]
        r.extra = _picture_blocks(r)  # not only the first picture of the slide: the next on a continuation slide
        return [f for f in (_image(r, room, prof, k) for k in kinds) if f is not None]
    structural: list[Optional[Form]] = []
    if r.of("flow"):
        structural += [_process(r, paras, "process", prof), _process(r, paras, "timeline", prof)]
    if r.stages():
        structural += [_stages(r, room, prof, k) for k in prof["stages"]]
    for f in structural:
        if f is not None:
            f.structural = True
    out += structural
    if r.of("list"):
        out += [_list_form(r, k, prof) for k in prof["list"]]
    for k in prof["prose"]:
        if k == "cards":
            out.append(_cards(r, paras, room, prof))
        elif k == "two_column":
            out.append(_columns(r, paras, room, prof))
        elif k == "bullets":
            out.append(_bullets(r, paras, room, prof))
        elif k == "quote":
            out.append(_quote(r, paras))
        elif k == "big_number":
            out.append(_figure(r, paras, prof))
    out.append(_bullets(r, paras, room, prof))
    if r.of("list"):
        out.append(_list_form(r, "bullets", prof))
    got = [f for f in out if f is not None]
    if not got:
        rest = r.of("note")
        got = [_image(r, room, prof, "image_text", part=rest[0])] if rest else [Form("bullets", _slide(r, "bullets"), 0)]
    return got


# ------------------------------------------------------------------ the deck, one variant at a time


def _bookend(r: Reading):
    from verstka.schemas.outline import SlideContent, SlideItem

    if r.role == "cover":
        s = _slide(r, "title", subtitle=r.lead, footnote=r.footnote)
        return s
    if r.role == "closing":
        # the author's closing lines under the farewell's subtitle, not only in the notes («Датчики помогают видеть
        # изменения… Вопросы и обсуждение.»): one line under it, the way a cover shows its goal
        lead = H.strip_end(r.lead or "")
        rest = [x for p in r.paras() for x in p if H.strip_end(x) != lead]
        s = _slide(r, "thanks", subtitle=r.lead)
        if rest and sum(words(x) for x in rest) <= 35:
            s.content.paragraphs = [" ".join(rest)]
        return s
    if r.role == "agenda":
        lst = r.of("list")
        lines = lst[0].items if lst else [H.strip_end(ss[0]) for ss in r.paras()]
        return _slide(r, "agenda", content=SlideContent(items=[SlideItem(title=x) for x in lines[:8]]))
    if r.role == "section":
        paras = r.paras()
        sub = H.strip_end(paras[0][0]) if paras and paras[0] else r.lead
        return _slide(r, "section", subtitle=sub)
    return None


@dataclass
class Plan:
    """The verbatim plan: the deck's title, its slides per variant and the designer's line per slide."""

    title: str
    subtitle: Optional[str]
    readings: list[Reading]
    decks: dict  # variant → [OutlineSlide]
    lines: dict  # variant → [(position, message)]


def _part_name(title: str) -> bool:
    """The heading names a part of a deck («Проблема», «Наша команда»), not the deck itself («Итоги 2025 года»,
    «Рынок электромобилей в России»): a usual part's word, two or three words at most, no figure."""
    t = H.strip_end(title or "")
    return bool(SECTION_WORDS_RE.match(t)) and words(t) <= 3 and not re.search(r"\d", t)


_YEAR_ONLY_RE = re.compile(r"(?:.*\s)?(?:19|20)\d{2}(?:\s*(?:год\w*|г\.?))?")


def deck_title(readings: list[Reading], given: Optional[str]) -> str:
    cover = next((r for r in readings if r.role == "cover"), None)
    if given:
        return given
    if cover is not None and cover.title:
        return cover.title
    return readings[0].title if readings else "Презентация"


def _form_key(f: Form) -> str:
    return f.kind


def plan_deck(specs, manifest=None, variants: tuple = ("structured", "visual", "compact"), title: Optional[str] = None, forms_fn=None, room: Optional[Room] = None) -> Plan:
    """The user's slides, each in the author's own words, in a form per variant. The forms a variant reaches for come
    first; of those the first one the template has a sample for (and that does not make the third slide of one form
    in a row) is taken — a form the template has no sample of is composed from its design system, and only when no
    form of the slide has a sample. `room`: the template's measure when the caller has read it (`Room.of`)."""
    specs = sorted(specs, key=lambda sp: sp.number)
    n = len(specs)
    readings = [read_slide(sp.number, sp.title, sp.text, first=(i == 0), last=(i == n - 1 and n >= 2), deck=title, notes=getattr(sp, "notes", "") or "")
                for i, sp in enumerate(specs)]
    if room is None:
        try:
            room = Room.of(manifest)
        except Exception:  # noqa: BLE001 - the forms are then chosen without the template's measure
            room = Room()
    decks: dict = {}
    lines: dict = {}
    taken: dict[int, set] = {}  # slide position → the forms the variants before showed it in
    for v in variants:
        slides = []
        said = []
        kinds: list[str] = []
        for pos, r in enumerate(readings, 1):
            b = _bookend(r)
            if b is not None:
                slides.append(b)
                kinds.append(b.kind.value)
                said.append((pos, _line(pos, b)))
                continue
            forms = (forms_fn(r, v) if forms_fn is not None else forms_of(r, room, v)) or forms_of(r, room, v)
            pick = _choose(forms, room, kinds, avoid=taken.get(pos, set()))
            taken.setdefault(pos, set()).add(pick.kind)
            s = pick.slide
            slides.append(s)
            kinds.append(s.kind.value)
            said.append((pos, _line(pos, s)))
        decks[v] = slides
        lines[v] = said
    first = readings[0] if readings else None
    sub = first.lead if first is not None and first.role == "cover" else None
    return Plan(title=deck_title(readings, title), subtitle=sub, readings=readings, decks=decks, lines=lines)


def _items_n(s) -> int:
    c = s.content
    return len(c.items) or len(c.columns) or len(c.numbers) or None


def _choose(forms: list[Form], room: Room, kinds: list[str], avoid: Optional[set] = None) -> Form:
    """The form the slide takes: of the text's own forms (its code, data, steps, stages) when it has any, else of all —
    the first the template holds that is not the third slide of one form in a row; else the first it holds; else the
    first that breaks the row; else the first (it is composed). `avoid`: the forms the variants before showed the slide
    in — another of the variant's forms is taken when it shows as much of the text (four fifths of the first one's at
    least): three variants of one form on most slides were one deck three times."""
    def held(f: Form) -> bool:
        if f.own or f.kind in ("chart", "table", "code"):
            return True  # a chart stands on a chart sample or on any sample with room for it; code is composed when it has none
        return room.holds(f.kind, _items_n(f.slide)) or (f.kind == "mockup" and room.holds("image_text")) or (f.kind == "image_text" and room.holds("mockup"))

    def third(f: Form) -> bool:
        return len(kinds) >= 2 and kinds[-1] == f.kind and kinds[-2] == f.kind

    pool = [f for f in forms if f.structural] or forms
    for ok in (lambda f: held(f) and not third(f), held, lambda f: not third(f)):
        cands = [f for f in pool if ok(f)]
        if cands:
            if avoid and cands[0].kind in avoid:
                other = next((f for f in cands[1:] if f.kind not in avoid and f.shown >= 0.8 * cands[0].shown), None)
                if other is not None:
                    return other
            return cands[0]
    return pool[0]


def form_name(s) -> str:
    """The slide's form in the timeline's words («карточки с текстом», «код и пояснение», «круговая диаграмма»)."""
    ch = s.content.chart
    if s.kind.value == "chart" and ch is not None:
        name = _CHART_FORM.get(ch.type, "диаграмма")
        if ch.split and len(ch.series) > 1:
            name = {"столбчатая диаграмма": "столбчатые диаграммы", "горизонтальная диаграмма": "горизонтальные диаграммы", "линейный график": "линейные графики"}.get(name, name) + f" рядом ({len(ch.series)})"
        return name
    return _RU_FORM.get(s.kind.value, s.kind.value)


def _line(pos: int, s) -> str:
    k = s.kind.value
    head = s.headline
    if k == "title":
        return f"Дизайнер: слайд {pos} — обложка «{head}»" + (f", подзаголовок «{s.subtitle}»" if s.subtitle else "") + "."
    if k == "thanks":
        return f"Дизайнер: слайд {pos} — финальный слайд «{head}»."
    form = form_name(s)
    c = s.content
    extra = []
    if c.code is not None:
        n = len(c.code.text.splitlines())
        extra.append((f"{c.code.language} " if c.code.language else "") + f"{n} {'строка' if n % 10 == 1 and n % 100 != 11 else 'строки' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'строк'} кода")
    if c.photo_slot:
        extra.append("подпись к месту — из текста" if c.photo_hint else "место оставлено свободным")
    if c.chart is not None:
        extra.append("данные — из текста")
    return f"Дизайнер: слайд {pos} «{head}» — {form}" + (f" ({', '.join(extra)})" if extra else "") + "."


# ------------------------------------------------------------------ fitting after the render


def _same_block(block: str, target: str) -> bool:
    """The flagged element shows this block: one text starts the other (the slide may show it typeset, cut short)."""
    a, b = " ".join(block.replace("\u00a0", " ").split()).lower(), " ".join(target.replace("\u00a0", " ").split()).lower()
    k = min(len(a), len(b), 40)
    return k >= 8 and (a[:k] == b[:k] or a[:k] in b or b[:k] in a)


def drop_one_sentence(slide, target: Optional[str] = None) -> str:
    """A slide of the author's text that overflows its place shows one whole sentence less: the last sentence of its
    longest block (a card, a column's paragraph, a line of the list); a block of one sentence goes whole, the slide's
    last such block first, while two blocks stay. The speaker notes keep the slide's whole text. `target`: the text of
    the element that overflows — only its own block may give a sentence, and only one of two or more (a one-line title
    or label that runs over is no reason to cut another card's text). Returns what changed («skip» when nothing can
    go without losing the slide's point)."""
    c = slide.content
    if target is not None:
        holders = [(c.bullets, i) for i in range(len(c.bullets))] + [(c.paragraphs, i) for i in range(len(c.paragraphs))]
        for it in [*c.items, *c.columns]:
            if it.text:
                holders.append((it, -1))
            holders += [(it.bullets, i) for i in range(len(it.bullets))]
        for holder, i in holders:
            text = holder.text if i == -1 else holder[i]
            if not _same_block(text, target):
                continue
            ss = sentences(text)
            if len(ss) < 2:
                return "skip"
            if i == -1:
                holder.text = " ".join(ss[:-1])
            else:
                holder[i] = " ".join(ss[:-1])
            return f"one sentence less: «{ss[-1][:60]}» (it stays in the notes)"
        return "skip"
    blocks: list[tuple[int, str, object, int]] = []  # (length, where, holder, index)
    for i, b in enumerate(c.bullets):
        blocks.append((len(b), "bullets", c.bullets, i))
    for i, b in enumerate(c.paragraphs):
        blocks.append((len(b), "paragraphs", c.paragraphs, i))
    for it in [*c.items, *c.columns]:
        if it.text:
            blocks.append((len(it.text), "text", it, -1))
        for i, b in enumerate(it.bullets):
            blocks.append((len(b), "item_bullets", it.bullets, i))
    for length, where, holder, i in sorted(blocks, key=lambda t: -t[0]):
        text = holder.text if where == "text" else holder[i]
        ss = sentences(text)
        if len(ss) >= 2:
            new = " ".join(ss[:-1])
            if where == "text":
                holder.text = new
            else:
                holder[i] = new
            return f"one sentence less: «{ss[-1][:60]}» (it stays in the notes)"
    # every block is one sentence: the last line of a list of three or more goes
    for lst, name in ((c.bullets, "line"), (c.paragraphs, "paragraph")):
        if len(lst) >= 3:
            gone = lst.pop()
            return f"one {name} less: «{gone[:60]}» (it stays in the notes)"
    for it in [*c.items, *c.columns]:
        if len(it.bullets) >= 3:
            gone = it.bullets.pop()
            return f"one line less: «{gone[:60]}» (it stays in the notes)"
    return "skip"
