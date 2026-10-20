"""A plan in any form (final polish M): the outline a person writes for a deck — a numbered list («1. Где мы сейчас.
…»), bullets («- Что случилось: …»), the lines or paragraphs of a letter («Сначала — …», «Потом сравни …», «В конце
— что просим …») — read as the slides they ask for: one item, one slide, in the author's order.

`as_slides(text)` gives the brief back in the analyst's own form («Слайд N. Заголовок» and the item's lines under it,
planning/brief_structure.py), so the dictated-slide path takes it with and without a model: the item's words stay as
written (the title is the item's own lead — «Где мы сейчас», «Что случилось» — or its first clause), its tables go
with it, the letter's greeting, request line and sign-off are not slides. A text that already dictates its slides
(«Слайд 3. …»), has markdown headings of its own or reads as prose is left as it is (None).

The rules rely on line shapes (numbers, bullets, blank lines, tables) and a handful of Russian sequence words
(«сначала», «потом», «в конце») — never on one brief.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from verstka.planning import heuristics as H

_NUM_ITEM_RE = re.compile(r"^(?P<ind>\s*)(?:\*\*)?(?:(?:пункт|часть|блок|раздел|тема)\s*)?(?P<n>\d{1,2})\s*[.):]\s+(?:\*\*)?(?P<t>\S.*)$", re.I)
_BULLET_RE = re.compile(r"^(?P<ind>\s*)[-–—•*·]\s+(?P<t>\S.*)$")
_TABLE_RE = re.compile(r"^\s*\|")
_MD_HEAD_RE = re.compile(r"^\s*#{1,6}\s+\S")
_SLIDE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:слайд|slide)\s*№?\s*\d{1,3}\b", re.I | re.M)
_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)

# the words that open the next part of a letter's plan («Сначала общие итоги», «Потом по направлениям», «В конце —
# что просим»): the item's order word, not its title
_SEQ_RE = re.compile(
    r"^(?:(?:а|и)\s+)?(?:сначала|вначале|в\s+начале|для\s+начала|сперва|потом|затем|дальше|далее|после\s+этого|после\s+чего|"
    r"следом|отдельно|ещё|еще|также|в\s+конце|в\s+завершение|в\s+заключение|под\s+конец|напоследок|наконец|и\s+последнее|"
    r"во-первых|во-вторых|в-третьих|в-четв[её]ртых|первое|второе|третье|четв[её]ртое|последнее|"
    r"(?:первым|вторым|третьим|следующим|последним)\s+(?:слайдом|пунктом|делом))\b(?:\s*,\s*|\s*[—–-]\s*|\s*:\s*|\s+)",
    re.I,
)
_GREETING_RE = re.compile(
    r"^(?:(?:всем\s+)?привет|здравствуй(?:те)?|добрый\s+(?:день|вечер)|доброе\s+утро|коллеги|уважаемые?\s+\S+|hi|hello|dear\s+\S+)\b[^.!?]{0,40}[,!.]?\s*$",
    re.I,
)
_SIGN_OFF_RE = re.compile(
    r"^(?:(?:заранее\s+)?спасибо|благодарю|с\s+уважением|хорошего\s+дня|thanks|thank\s+you|best\s+regards|regards)\b[^.!?]{0,60}[.!]?\s*$",
    re.I,
)
# the line that asks for the deck itself («Нужна презентация для совета директоров по закрытию квартала», «Подготовь,
# пожалуйста, слайды к планёрке по складу»)
_TASK_RE = re.compile(
    r"\b(?:нуж(?:на|ен|ны|но)|подготовь(?:те)?|сделай(?:те)?|собери(?:те)?|сверстай(?:те)?|набросай(?:те)?|сгенерируй(?:те)?|"
    r"создай(?:те)?|прошу|помоги(?:те)?)\b[^.!?]{0,80}?\b(?:презентаци\w*|слайд\w*|колод\w*|деку|деки)\b",
    re.I,
)
# «Примерно так:», «Структура:», «План такой:», «Тезисы:» — the line that opens the plan
_LEAD_IN_RE = re.compile(
    r"^(?:примерно\s+так|вот\s+так|как-то\s+так|план(?:\s+такой)?|структура(?:\s+такая)?|тезисы|по\s+пунктам|что\s+рассказать|"
    r"о\s+ч[её]м\s+рассказать|содержание|пункты)\s*[:.]?\s*$",
    re.I,
)
_FIG_RE = re.compile(r"\d")
_BRACKET_RE = re.compile(r"\s*\(([^()]{3,80})\)")
_DASH_SPLIT_RE = re.compile(r"\s+[—–]\s+|\s+-\s+")


@dataclass
class PlanItem:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class PlanForm:
    """The plan the text gives: its items (one slide each), the deck's title and who it is for, and the form it was
    written in («numbered», «bullets», «letter»)."""

    form: str
    items: list[PlanItem]
    title: Optional[str] = None
    subtitle: Optional[str] = None
    audience: Optional[str] = None
    preamble: list[str] = field(default_factory=list)  # the lines kept before the slides (rules, the slide count)
    front: str = ""  # the text's front matter («---» … «---»), first as it was

    @property
    def text(self) -> str:
        """The plan in the analyst's form: «Название: …», the kept preamble, then «Слайд N. Заголовок» per item."""
        out: list[str] = [self.front.strip()] if self.front.strip() else []
        out.extend(self.preamble)
        # the cover first, as its own dictated slide: the plan's first item is content, never the deck's cover
        out.append("")
        out.append("Слайд 1. Обложка")
        out.append(f"Название: {self.title or 'Презентация'}")
        if self.subtitle:
            out.append(f"Подзаголовок: {H.strip_end(self.subtitle)}")
        for n, it in enumerate(self.items, 2):
            out.append("")
            out.append(f"Слайд {n}. {it.title}".rstrip())
            prev_table = False
            for ln in it.lines:
                table = _is_table(ln)
                if out and out[-1].strip() and table != prev_table and not out[-1].startswith("Слайд "):
                    out.append("")  # a table is a block of its own
                out.append(ln)
                prev_table = table
        return "\n".join(out).strip() + "\n"


# ------------------------------------------------------------------ small helpers


def _plain(line: str) -> str:
    return " ".join((line or "").replace("**", "").split())


def _is_table(line: str) -> bool:
    return bool(_TABLE_RE.match(line))


def _strip_seq(text: str) -> str:
    """«Сначала — сколько отгрузили: …» → «сколько отгрузили: …» (the order word goes, the item's words stay)."""
    t = text.strip()
    for _ in range(2):
        m = _SEQ_RE.match(t)
        if not m or len(t) - m.end() < 3:
            break
        t = t[m.end():].lstrip(" ,:—–-")
    return t


def _has_seq(text: str) -> bool:
    m = _SEQ_RE.match((text or "").strip())
    return bool(m) and len(text.strip()) - m.end() >= 3


def _words(text: str) -> int:
    return len(re.findall(r"[\wё%₽]+", text or ""))


def _title_case(text: str) -> str:
    t = H.strip_end(text.strip(" ,:;—–-")).strip()
    t = re.sub(r"^[«\"]|[»\"]$", "", t) if t.count("«") != t.count("»") else t
    return H.cap_first(t)


def _directive_title(label: str) -> Optional[str]:
    """«сравни скорость сборки» → «Скорость сборки», «сделай воронку заказов» → «Воронка заказов», «покажи на графике
    план и факт» → «План и факт»: what the designer is asked to show, as a heading."""
    from verstka.planning.directives import directive_object

    obj = directive_object(label)
    return H.cap_first(obj) if obj else None


def _split_item(text: str) -> tuple[str, list[str]]:
    """An item's title and lines: its own short lead («Где мы сейчас. В компании …», «Что случилось: с 10:02 …»,
    «Выручка — 312 млн ₽, рост 18%»), else its first clause; the order word of a letter («Сначала», «Потом») is not
    part of either. The lines keep every word of the item (a lead that is only a label is not repeated)."""
    from verstka.planning.directives import is_directive

    t = _strip_seq(_plain(text))
    if not t:
        return "", []
    # «как менялось число обращений за год (покажи рост)»: an ask to the designer in brackets is the slide's intent — a
    # line of its own the form is read from, never a part of the heading or of the text
    asks = [m.group(1).strip() for m in _BRACKET_RE.finditer(t) if is_directive(m.group(1).strip())]
    if asks:
        t = _BRACKET_RE.sub(lambda m: "" if is_directive(m.group(1).strip()) else m.group(0), t)
        t = re.sub(r"\s+([,.;:!?])", r"\1", " ".join(t.split())).strip()
        title, lines = _split_item(t) if t else ("", [])
        return title, [*lines, *(H.cap_first(H.strip_end(a)) + "." for a in asks)]
    sents = H.split_sentences(t) or [t]
    first = sents[0]
    # «Где мы сейчас. В компании 1 240 сотрудников …»: a short first sentence without figures is the title
    if len(sents) >= 2 and _words(first) <= 7 and not _FIG_RE.search(first) and not first.rstrip().endswith("?") and not is_directive(first):
        return _title_case(first), [H.cap_first(" ".join(sents[1:]))]
    # «Что случилось: с 10:02 до 12:47 …», «Сравни скорость сборки: в Подольске …»
    m = re.match(r"^(?P<label>[^:]{2,70}?)\s*:\s*(?P<rest>\S.*)?$", t)
    if m and _words(m.group("label")) <= 7 and is_directive(m.group("label")):
        # the ask stays with its data (the slide's form is read from it downstream), the heading names its object
        return _directive_title(m.group("label")) or _title_case(m.group("label")), [H.cap_first(t)]
    if m and m.group("rest") and _words(m.group("label")) <= 7 and not _FIG_RE.search(m.group("label")):
        label, rest = m.group("label"), m.group("rest")
        dashed = _DASH_SPLIT_RE.split(label)
        if len(dashed) > 1:
            # «Главная проблема — ночная смена: на неё …»: the title is the label's last part, the text keeps it all
            return _title_case(dashed[-1]), [H.cap_first(t)]
        return _title_case(label), [H.cap_first(rest)]
    # «Выручка — 312 млн ₽, рост 18% к 2 кварталу», «Главная проблема — ночная смена: …»: a short label before a dash
    parts = _DASH_SPLIT_RE.split(t, maxsplit=1)
    if len(parts) == 2 and 1 <= _words(parts[0]) <= 4 and not _FIG_RE.search(parts[0]) and not is_directive(parts[0]):
        return _title_case(parts[0]), [H.cap_first(t)]
    # a single statement («Общий бюджет снижается с 214 до 176 млн рублей»): it is the slide's point and its text
    if len(sents) == 1 and _words(first) <= 14:
        return _title_case(first), [H.cap_first(t)]
    # else the first clause of the first sentence, when it is short enough to be a heading
    clause = re.split(r"\s*[:;]\s+|,\s+(?=(?:но|а|и|что|потому|поэтому|чтобы)\b)", first)[0]
    if 2 <= _words(clause) <= 9 and clause != first:
        return _title_case(clause), [H.cap_first(t)]
    return _title_case(" ".join(first.split()[:8])) if _words(first) > 9 else _title_case(first), [H.cap_first(t)]


# ------------------------------------------------------------------ the deck's own lines


_FOR_RE = re.compile(r"\s+[—–-]\s+(?:(?:тезисы|план|презентаци\w*|слайды|доклад|выступлени\w*|материал\w*)\s+)?(?P<who>для\s+.+)$", re.I)
_TOPIC_AFTER_RE = re.compile(r"\b(?:презентаци\w*|слайд\w*)\s+(?P<rest>.+)$", re.I)
_AUD_RE = re.compile(r"\bдля\s+(?P<who>[^,.;:!?]+?)(?=\s+(?:по|о|об|про|к|на\s+тему)\s|[,.;:!?]|$)", re.I)
_TOPIC_RE = re.compile(r"\b(?:по|о|об|про|на\s+тему|к)\s+(?P<what>[^.!?]+?)\s*(?:[.!?:]|$)", re.I)


def _nominative_head(phrase: str) -> str:
    """«закрытию третьего квартала» → «Закрытие третьего квартала», «складу в Подольске» → «Склад в Подольске»,
    «итогам года» → «Итоги года»: the first word of a phrase after «по/к» back in the nominative (a few endings only;
    anything else stays as written)."""
    ws = phrase.split()
    if not ws:
        return phrase
    w = ws[0]
    low = w.lower()
    rules = (("иям", "ия"), ("ию", "ие"), ("ии", "ия"), ("ам", "и"), ("ям", "и"), ("ке", "ка"), ("ге", "га"), ("те", "та"), ("це", "ца"))
    new = None
    for end, rep in rules:
        if low.endswith(end) and len(low) > len(end) + 2:
            new = w[: len(w) - len(end)] + rep
            break
    if new is None and re.search(r"[бвгдзклмнпрстфхцчшщ]у$", low) and len(low) > 4:
        new = w[:-1]
    if new is not None:
        ws[0] = new
    return H.cap_first(" ".join(ws))


def _from_task(line: str) -> tuple[Optional[str], Optional[str]]:
    """The deck's topic and audience from the line that asks for it («нужна презентация для совета директоров по
    закрытию третьего квартала» → «Закрытие третьего квартала», «совет директоров»)."""
    sent = next((s for s in (H.split_sentences(line) or [line]) if _TASK_RE.search(s)), line)
    m = _TOPIC_AFTER_RE.search(sent)
    rest = m.group("rest") if m else ""
    who = None
    am = _AUD_RE.search(rest)
    if am:
        who = am.group("who").strip()
    tm = _TOPIC_RE.search(_AUD_RE.sub(" ", rest)) if rest else None
    topic = None
    if tm:
        what = tm.group("what").strip()
        # «к планёрке по складу …»: the subject is after the last «по»
        inner = re.search(r"\bпо\s+(?P<w>.+)$", what, re.I)
        if inner and re.match(r"^(?:планерк|планёрк|встреч|совещани|отч[её]т|созвон|комитет|совет)\w*\s", what, re.I):
            what = inner.group("w")
        topic = _nominative_head(H.strip_end(what))
    return topic, who


def _audience_phrase(who: str) -> str:
    """«совета директоров» → «Совет директоров» (the head word of «для …» back in the nominative, a few endings)."""
    ws = who.split()
    if not ws:
        return who
    w = ws[0]
    low = w.lower()
    for end, rep in (("ого", "ый"), ("ова", "ов"), ("ета", "ет"), ("ния", "ние"), ("ии", "ия"), ("ей", "и"), ("ов", "ы")):
        if low.endswith(end) and len(low) > len(end) + 2:
            if end in ("ей", "ов") and len(ws) == 1:
                break
            ws[0] = w[: len(w) - len(end)] + rep
            if end == "ого" and len(ws) > 1 and re.search(r"[бвгдзклмнпрстфхцчшщ]а$", ws[1].lower()) and len(ws[1]) > 4:
                ws[1] = ws[1][:-1]  # «операционного директора» → «Операционный директор»
            break
    else:
        if re.search(r"[бвгдзклмнпрстфхцчшщ]а$", low) and len(low) > 4:
            ws[0] = w[:-1]
    return H.cap_first(" ".join(ws))


# ------------------------------------------------------------------ the forms


def _list_items(lines: list[str], kind: str) -> tuple[list[str], list[tuple[str, list[str]]], list[str]]:
    """(lines before the list, items as (first line, the lines under it), lines after the list) for the top-level
    numbered or bulleted items of `lines`."""
    rx = _NUM_ITEM_RE if kind == "numbered" else _BULLET_RE
    marks = [(i, m) for i, ln in enumerate(lines) if (m := rx.match(ln))]
    if not marks:
        return lines, [], []
    top = min(len(m.group("ind").expandtabs(4)) for _, m in marks)
    marks = [(i, m) for i, m in marks if len(m.group("ind").expandtabs(4)) == top]
    before = lines[: marks[0][0]]
    items: list[tuple[str, list[str]]] = []
    for k, (i, m) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        items.append((m.group("t"), lines[i + 1 : end]))
    # after the last item: its own lines run to the first blank line followed by a plain paragraph that is not a table
    last_t, last_body = items[-1]
    after: list[str] = []
    body: list[str] = []
    blank = False
    for j, ln in enumerate(last_body):
        if not ln.strip():
            blank = True
            body.append(ln)
            continue
        if blank and not _is_table(ln) and not ln.startswith((" ", "\t")) and not _BULLET_RE.match(ln):
            after = last_body[j:]
            break
        body.append(ln)
    items[-1] = (last_t, body)
    return before, items, after


def _numbers_run(lines: list[str]) -> bool:
    nums = []
    ind = None
    for ln in lines:
        m = _NUM_ITEM_RE.match(ln)
        if m:
            i = len(m.group("ind").expandtabs(4))
            ind = i if ind is None else min(ind, i)
    for ln in lines:
        m = _NUM_ITEM_RE.match(ln)
        if m and len(m.group("ind").expandtabs(4)) == ind:
            nums.append(int(m.group("n")))
    return len(nums) >= 3 and nums == list(range(nums[0], nums[0] + len(nums))) and nums[0] in (0, 1)


def _chars(lines: list[str]) -> int:
    return sum(len(ln.strip()) for ln in lines if ln.strip())


def _item_lines(head: str, under: list[str]) -> PlanItem:
    title, lead = _split_item(head)
    rest = [ln.rstrip() for ln in under]
    while rest and not rest[0].strip():
        rest.pop(0)
    while rest and not rest[-1].strip():
        rest.pop()
    # sub-items keep their marks (a list under the item is the slide's list); a table stays a table
    body = [ln for ln in lead if ln.strip()] + [ln.strip() if not _is_table(ln) else ln.strip() for ln in rest]
    return PlanItem(title=title, lines=body)


def _preamble(lines: list[str]) -> tuple[Optional[str], Optional[str], Optional[str], list[str]]:
    """(title, subtitle, audience, kept lines) of the lines before the plan: a greeting goes, the request line gives
    the topic and the audience, a title line «План найма на 2027 год — для HR-комитета» is the title (and who it is
    for its subtitle), a lead-in «Примерно так:» goes; the rest (the slide count, rules) is kept."""
    title = subtitle = audience = None
    kept: list[str] = []
    for raw in lines:
        ln = _plain(raw)
        if not ln:
            continue
        if _GREETING_RE.match(ln) or _LEAD_IN_RE.match(ln):
            continue
        sents = H.split_sentences(ln) or [ln]
        if _TASK_RE.search(ln):
            topic, who = _from_task(ln)
            if topic and title is None:
                title = topic
            if who and audience is None:
                from verstka.planning.directives import strip_count_phrase

                audience = _audience_phrase(strip_count_phrase(who) or who)
            # the request's other sentences (the slide count, the audience said apart) stay
            for s in sents:
                if not _TASK_RE.search(s) and not _LEAD_IN_RE.match(s) and not re.match(r"^(?:примерно|вот)\s+так", s, re.I):
                    kept.append(s)
            continue
        m = re.match(r"^(?:тема|название|topic|title)\s*:\s*(?P<v>.+)$", ln, re.I)
        if m and title is None:
            v = m.group("v")
            vs = H.split_sentences(v) or [v]
            title = H.strip_end(vs[0]).strip("«»\" ")
            kept.extend(vs[1:])
            continue
        if title is None and _words(sents[0]) <= 16 and len(sents) <= 2:
            head = H.strip_end(sents[0])
            fm = _FOR_RE.search(head)
            if fm:
                title = head[: fm.start()].strip()
                # «— для финдиректора, примерный план:» — who it is for; the words about the plan itself are no subtitle
                who = re.sub(r",?\s*(?:вот\s+)?(?:примерн\w+|черновой|краткий)?\s*(?:план|структура|тезисы)\w*\s*:?\s*$", "", fm.group("who"), flags=re.I).strip(" ,:")
                subtitle = H.cap_first(who)
            else:
                title = head
            kept.extend(sents[1:])
            continue
        kept.append(ln)
    from verstka.planning.directives import strip_count_phrase

    # («— для операционного директора, слайдов 8–10»: the slide count stays a rule of the deck, never its title)
    return strip_count_phrase(title) or None, strip_count_phrase(subtitle) or None, strip_count_phrase(audience) or None, kept


def _letter_units(lines: list[str]) -> list[list[str]]:
    """The letter's parts: its paragraphs (blank-line separated, a table joins the paragraph before it), or its lines
    when the letter is written line by line (no blank lines between its parts)."""
    paras: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if not ln.strip():
            if cur:
                paras.append(cur)
                cur = []
            continue
        cur.append(ln)
    if cur:
        paras.append(cur)
    # a table paragraph belongs to the paragraph before it («… данные в таблице ниже» + the table)
    merged: list[list[str]] = []
    for p in paras:
        if merged and all(_is_table(x) for x in p):
            merged[-1].extend(p)
        else:
            merged.append(p)
    plain = [p for p in merged if not all(_is_table(x) for x in p)]
    if len(plain) <= 2 and any(len([x for x in p if not _is_table(x)]) >= 3 for p in plain):
        units: list[list[str]] = []
        for p in merged:
            for ln in p:
                if _is_table(ln) and units:
                    units[-1].append(ln)
                else:
                    units.append([ln])
        return units
    return merged


def _attach_asks(units: list[list[str]]) -> list[list[str]]:
    """A part that only asks the designer («Нужен столбчатый график стоимости заявки по каналам.») is the intent of the
    part before it (of the next one when it comes first): never a slide of its own."""
    from verstka.planning.directives import split_directive

    out: list[list[str]] = []
    pending: list[str] = []
    for u in units:
        text = " ".join(_plain(x) for x in u if not _is_table(x))
        sents = H.split_sentences(text) or [text]
        only_ask = bool(text) and not any(_is_table(x) for x in u) and all(split_directive(x)[0] is not None and not split_directive(x)[1] for x in sents)
        if only_ask:
            if out:
                out[-1] = [*out[-1], *u]
            else:
                pending.extend(u)
            continue
        out.append([*u, *pending] if pending else u)
        pending = []
    if pending and out:
        out[-1] = [*out[-1], *pending]
    return out


def _letter(lines: list[str]) -> Optional[PlanForm]:
    units = _letter_units(lines)
    if len(units) < 4:
        return None
    # the opening: greetings, the request, a title line, a lead-in — up to the first part of the plan
    k = 0
    pre: list[str] = []
    asked = False
    while k < len(units) and k < 3:
        u = units[k]
        text = " ".join(_plain(x) for x in u)
        if _GREETING_RE.match(text) or _LEAD_IN_RE.match(text):
            pre.extend(u)
            k += 1
            continue
        if _TASK_RE.search(text) and not _has_seq(text):
            pre.extend(u)
            asked = True
            k += 1
            continue
        if k == 0 and _words(text) <= 14 and not _FIG_RE.search(text.split("—")[0]) and len(u) == 1 and not _has_seq(text):
            pre.extend(u)  # a title line
            k += 1
            continue
        break
    body = units[k:]
    while body and _SIGN_OFF_RE.match(" ".join(_plain(x) for x in body[-1])):
        body = body[:-1]
    if len(body) < 3:
        return None
    body = _attach_asks(body)
    if len(body) < 3:
        return None
    seq = sum(1 for u in body if _has_seq(_plain(u[0])))
    lead_in = any(_LEAD_IN_RE.match(_plain(x)) or re.search(r"(?:примерно|вот)\s+так\s*:?\s*$", _plain(x), re.I) for x in pre)
    one_line = all(len([x for x in u if not _is_table(x)]) == 1 for u in body)
    # theses under a title line: short parts, each a point of its own («Кампания шла …», «Результаты по каналам:» and
    # its table, «Предложение: …»)
    theses = k >= 1 and not asked and len(body) >= 4 and all(_words(" ".join(x for x in u if not _is_table(x))) <= 45 for u in body)
    if not (seq >= 2 or (asked and (lead_in or one_line)) or theses):
        return None
    if any(_words(" ".join(u)) > 90 for u in body):
        return None  # long paragraphs: prose, not a plan
    items = [_item_lines(_plain(u[0]) if not _is_table(u[0]) else "", u[1:]) for u in body]
    if any(not it.title for it in items):
        return None
    title, subtitle, audience, kept = _preamble(pre)
    return PlanForm(form="letter", items=items, title=title, subtitle=subtitle, audience=audience, preamble=kept)


def read_plan(text: str) -> Optional[PlanForm]:
    """The plan the text is written as, or None when the text dictates its slides already, has its own markdown
    headings, or is prose (a document to lay out, not a plan)."""
    body = text or ""
    fm = _FRONT_RE.match(body)
    front = ""
    if fm:
        front, body = fm.group(0), body[fm.end():]
    if _SLIDE_RE.search(body):
        return None
    lines = body.splitlines()
    if sum(1 for ln in lines if _MD_HEAD_RE.match(ln)) >= 2:
        return None
    if "```" in body:
        return None
    total = _chars(lines)
    if total == 0:
        return None
    for kind in ("numbered", "bullets"):
        if kind == "numbered" and not _numbers_run(lines):
            continue
        before, raw_items, after = _list_items(lines, kind)
        if len(raw_items) < 3:
            continue
        inside = _chars([x for t, u in raw_items for x in [t, *u]])
        if inside < 0.5 * total or len([x for x in before if x.strip()]) > 4:
            continue
        if any(_words(t) < 1 for t, _ in raw_items):
            continue
        # a bulleted list of short words («- аналитика», «- облако») is a list on a slide, not a plan
        if kind == "bullets" and sum(1 for t, u in raw_items if _words(t) >= 4 or any(x.strip() for x in u)) < 3:
            continue
        from verstka.planning.directives import split_directive

        merged: list[tuple[str, list[str]]] = []
        for t, u in raw_items:
            ask, rest = split_directive(_plain(t))
            if merged and ask is not None and not rest and not any(x.strip() for x in u):
                merged[-1] = (merged[-1][0], [*merged[-1][1], _plain(t)])  # «- Нужна круговая диаграмма»: the item before it
                continue
            merged.append((t, u))
        raw_items = merged
        items = [_item_lines(t, u) for t, u in raw_items]
        # the item that only asks for the next one's data («Сравни статьи 2026 и 2027 годов:» over its table) is fine;
        # an empty title is not a slide
        items = [it for it in items if it.title]
        if len(items) < 3:
            continue
        tail = [x for x in after if x.strip()]
        signoff = [x for x in tail if _SIGN_OFF_RE.match(_plain(x))]
        rest = [x for x in tail if x not in signoff]
        if rest:
            items[-1].lines.extend(_plain(x) if not _is_table(x) else x.strip() for x in rest)
        title, subtitle, audience, kept = _preamble(before)
        return PlanForm(form=kind, items=items, title=title, subtitle=subtitle, audience=audience, preamble=kept, front=front)
    got = _letter(lines)
    if got is not None:
        got.front = front
    return got


def as_slides(text: str) -> Optional[PlanForm]:
    """The plan of `text` (read_plan) when it has three items or more; None leaves the text as it is."""
    try:
        p = read_plan(text)
    except Exception:  # noqa: BLE001 - the text as it is
        return None
    if p is None or len(p.items) < 3:
        return None
    return p
