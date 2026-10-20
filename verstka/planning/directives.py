"""What the author asks of the designer (final polish M): «Нужен столбчатый график: …», «Покажи на графике по
неделям», «Сделай воронку», «Сравни с рынком: …», «Добавь картинку с экраном приложения», «данные в таблице ниже».

Such words are the slide's intent — its chart, funnel, comparison, picture — and never its text: `split_directive`
takes the ask off a sentence and keeps what the sentence says of its own («Сравни с рынком: по данным hh.ru, у
инженеров 47 дней» → «По данным hh.ru, у инженеров 47 дней»), `scrub_slide` / `scrub_outline` are the last check of
a planned deck (with and without a model): no line, heading, takeaway or label on a slide is an ask to the designer;
an ask whose data the slide's chart or table already shows goes whole, its data stays as text otherwise.

The rules rely on a handful of Russian/English verbs and design nouns — never on one brief.
"""

from __future__ import annotations

import re
from typing import Optional

from verstka.planning import heuristics as H

# what a designer is asked to draw or place
_OBJ = (
    r"(?:график\w*|диаграмм\w*|гистограмм\w*|чарт\w*|charts?|graphs?|воронк\w*|funnel|таблиц\w*|tables?|схем\w*|инфографик\w*|"
    r"картинк\w*|изображени\w*|фото\w*|фотографи\w*|иллюстраци\w*|images?|pictures?|иконк\w*|пиктограмм\w*|визуализаци\w*|"
    r"таймлайн\w*|timeline|временн\w*\s+шкал\w*|шкал\w*\s+времени|хронологи\w*|сравнени\w*|акцент\w*|слайд\w*)"
)
# a verb that always speaks to the designer (or the speaker): «Покажи …», «Сравни …», «Построй …»
_VERB_ALWAYS = r"(?:покажи|покажите|сравни|сравните|построй|постройте|нарисуй|нарисуйте|визуализируй|визуализируйте|отобрази|отобразите|изобрази|изобразите|проиллюстрируй|проиллюстрируйте|show|compare|visualize|plot|draw)"
# a verb that speaks to the designer only with a design object: «Сделай воронку», «Добавь картинку» (never «Сделай
# резервную копию», «Добавь второй фактор»)
_VERB_OBJ = r"(?:сделай|сделайте|добавь|добавьте|вставь|вставьте|выведи|выведите|оформи|оформите|дай|дайте|приведи|приведите|помести|поместите|размести|разместите|используй|используйте|поставь|поставьте|make|add|insert|use|put)"
_NEED = r"(?:нуж(?:ен|на|ны|но)|надо|требуется|желательно|хорошо\s+бы|хочу|хотелось\s+бы|было\s+бы\s+(?:здорово|хорошо)|need|want)"
_PREFIX = r"(?:(?:здесь|тут|сюда|на\s+этом\s+слайде|на\s+слайде|также|ещ[её]|и|а|потом|затем|дальше|далее|отдельно|обязательно|пожалуйста|тоже|сначала|в\s+конце)\s*,?\s+)*"

_ASK_RE = re.compile(
    rf"^{_PREFIX}(?:{_VERB_ALWAYS}(?:-ка)?\b|{_VERB_OBJ}\b(?=[^.!?]{{0,40}}?\b{_OBJ})|{_NEED}\b(?=[^.!?]{{0,40}}?\b{_OBJ}))",
    re.I,
)
# «данные в таблице ниже», «см. таблицу», «данные — в приложенных файлах»: a pointer for the designer, not the audience
_POINTER_RE = re.compile(
    r"^(?:\(?\s*)?(?:(?:все\s+)?данные|цифры|детали|подробности)?\s*[—–-]?\s*(?:см\.?\s+|смотри\s+)?(?:в|во)?\s*"
    r"(?:таблиц\w*|файл\w*|приложени\w*|приложенн\w*\s+\w+|вложени\w*)\s*(?:ниже|выше|приложен\w*)?\s*\)?$"
    r"|^(?:\(?\s*)?см\.?\s+(?:ниже|выше|таблиц\w*|файл\w*|приложени\w*)\s*\)?$"
    r"|^(?:(?:все\s+)?данные|цифры)\s*[—–-]?\s*(?:ниже|выше)$",
    re.I,
)
_NEG_RE = re.compile(r"^\s*не\s+", re.I)
_CLAUSE_SPLIT_RE = re.compile(r"(\s*[,;]\s+|\s+[—–]\s+)")


def is_directive(text: str) -> bool:
    """The whole sentence (or a lead before «:») asks the designer for something: «Нужна воронка», «Покажи на графике
    по неделям», «Сравни скорость сборки», «Добавь картинку с экраном приложения»."""
    t = " ".join((text or "").split()).strip(" «»\"")
    if not t or _NEG_RE.match(t):
        return False
    return bool(_ASK_RE.match(t)) or bool(_POINTER_RE.match(H.strip_end(t)))


def is_pointer(text: str) -> bool:
    return bool(_POINTER_RE.match(H.strip_end(" ".join((text or "").split()))))


_OBJ_STRIP_RE = re.compile(
    rf"^{_PREFIX}(?:{_VERB_ALWAYS}|{_VERB_OBJ}|{_NEED})\s+(?:(?:мне|нам|пожалуйста|тоже|ещ[её])\s+)*"
    rf"(?:(?:на|в\s+виде|через|с\s+помощью)\s+(?:\w+\s+)?(?:график\w*|диаграмм\w*|гистограмм\w*|слайд\w*|таблиц\w*)\s*,?\s*)?",
    re.I,
)


def directive_object(text: str) -> Optional[str]:
    """What the ask wants shown, as a heading would name it: «сравни скорость сборки» → «скорость сборки», «сделай
    воронку заказов» → «воронка заказов», «покажи на графике план и факт» → «план и факт»; None when it names nothing
    («Покажи на графике»)."""
    from verstka.planning.brief_structure import _nominative

    t = H.strip_end(" ".join((text or "").split()))
    rest = _OBJ_STRIP_RE.sub("", t, count=1).strip(" ,:—–-")
    if not rest or rest == t:
        return None
    rest = re.sub(r"\s+(?:на|в\s+виде)\s+(?:\w+\s+)?(?:график\w*|диаграмм\w*|гистограмм\w*)$", "", rest, flags=re.I).strip()
    if not rest or re.fullmatch(_OBJ, rest, re.I):
        # only the design noun («Сделай воронку»): it names the slide's form, the heading its subject
        return _nominative(rest) if rest and re.match(r"воронк|таблиц|схем|хронологи", rest, re.I) else None
    return _nominative(rest)


def split_directive(sentence: str) -> tuple[Optional[str], str]:
    """(the ask, what remains of the sentence as its own text). «Сравни с рынком: по данным hh.ru, у инженеров 47
    дней» → («Сравни с рынком», «По данным hh.ru, у инженеров 47 дней»); «Нужна воронка» → («Нужна воронка», «»);
    «Потом по направлениям — данные в таблице ниже, покажи на графике план и факт» → (…, «»); a sentence with no ask
    → (None, sentence)."""
    s = " ".join((sentence or "").split())
    if not s:
        return None, ""
    end = s[-1] if s[-1] in ".!?…" else ""
    body = s[:-1] if end else s
    # «Ask: data» — the ask is the lead before the colon
    m = re.match(r"^(?P<lead>[^:]{2,120}?)\s*:\s*(?P<rest>.*)$", body)
    if m and is_directive(m.group("lead")):
        rest = m.group("rest").strip()
        return m.group("lead").strip(), (H.cap_first(rest) + ("." if rest and rest[-1] not in ".!?…" else "")) if rest else ""
    if is_directive(body):
        return body, ""
    # an ask said as a clause of the sentence («…, покажи на графике план и факт»; «… — данные в таблице ниже»)
    parts = _CLAUSE_SPLIT_RE.split(body)
    clauses = parts[0::2]
    seps = parts[1::2]
    if len(clauses) < 2:
        return None, s
    asked = [i for i, c in enumerate(clauses) if i > 0 and (is_directive(c.strip()) or is_pointer(c.strip()))]
    if not asked:
        return None, s
    first = min(asked)
    # the ask runs to the sentence's end (its object may hold commas: «покажи на графике, как распределён найм»)
    keep = clauses[:first]
    ask = "".join(x for pair in zip(clauses[first:], seps[first:] + [""]) for x in pair).strip()
    rest = "".join(x for pair in zip(keep, seps[: len(keep) - 1] + [""]) for x in pair).strip(" ,;—–-")
    from verstka.planning.plan_form import _strip_seq

    rest = _strip_seq(rest)
    # what is left of a lead that only named the part («Потом по направлениям») is not a sentence of its own
    if not rest or (len(rest.split()) <= 3 and not re.search(r"\d", rest)):
        return ask, ""
    return ask, H.cap_first(rest) + (end or ".")


def _figures(text: str) -> set[float]:
    from verstka.planning.brief_structure import numbers_of

    return {round(v, 2) for v in numbers_of(text or "")}


def _shown_figures(slide) -> set[float]:
    c = slide.content
    out: set[float] = set()
    for ch in (c.chart, getattr(c, "chart2", None)):
        if ch is None:
            continue
        for s in ch.series:
            out.update(round(float(v), 2) for v in s.values if v is not None)
        out.update(v for cat in ch.categories for v in _figures(cat))
    if c.table is not None:
        for row in c.table.rows:
            for cell in row:
                out.update(_figures(cell))
    for n in c.numbers:
        out.update(_figures(n.value))
    for it in c.items:
        out.update(_figures(it.title + " " + (it.number or "")))
    return out


def clean_text(text: Optional[str], shown: Optional[set] = None) -> Optional[str]:
    """The text without its asks to the designer: each sentence's ask taken off (split_directive); the data an ask
    carried stays only when the slide does not show it already (`shown`: the figures of its chart, table, numbers)."""
    if not text:
        return text
    from verstka.planning.faithful import sentences

    out: list[str] = []
    changed = False
    for sent in sentences(text) or [text]:
        if re.search(r"слайд", sent, re.I) and not (strip_count_phrase(sent) or "").strip(" .!"):
            changed = True  # «6–8 слайдов.» — the deck's size, said to the planner, never a line of a slide
            continue
        ask, rest = split_directive(sent)
        if ask is None and re.search(r"[:—–]\s+\S", sent):
            # «Как менялось число обращений за год: Покажи рост.» — the ask joined to the line it is about
            cut = list(re.finditer(r"\s*[:—–]\s+(?=\S)", sent))[-1]
            head, tail = sent[: cut.start()], sent[cut.end():]
            a2, r2 = split_directive(tail)
            if a2 is not None and not r2.strip(" .!") and head.strip():
                changed = True
                out.append(H.strip_end(head.rstrip(" :—–")) + ".")
                continue
        if ask is None:
            out.append(sent)
            continue
        changed = True
        if rest and shown is not None:
            figs = _figures(rest)
            if figs and figs <= shown:
                rest = ""
        if rest:
            out.append(rest)
    if not changed:
        return text
    joined = " ".join(out).strip()
    if text.rstrip()[-1:] not in ".!?…" and joined.endswith("."):
        joined = joined[:-1]
    return joined


def scrub_slide(slide) -> list[str]:
    """Takes every ask to the designer off the slide's visible text (in place); what changed, in English."""
    c = slide.content
    shown = _shown_figures(slide)
    said: list[str] = []

    def fix(value: Optional[str], where: str) -> Optional[str]:
        new = clean_text(value, shown)
        if new != value:
            said.append(f"{where}: the ask «{(value or '')[:70]}» is the slide's intent, not its text")
        return new

    def fix_list(values: list[str], where: str) -> list[str]:
        out = []
        for v in values:
            nv = fix(v, where)
            if nv and nv.strip():
                out.append(nv)
        return out

    head = fix(slide.headline, "headline")
    if head and head.strip():
        slide.headline = head
    elif slide.headline:
        from verstka.planning.directives import directive_object

        obj = directive_object(slide.headline)
        if obj:
            slide.headline = H.cap_first(obj)
    slide.subtitle = fix(slide.subtitle, "subtitle") or None
    slide.takeaway = fix(slide.takeaway, "takeaway") or None
    slide.footnote = fix(slide.footnote, "footnote") or None
    c.bullets = fix_list(list(c.bullets), "line")
    c.paragraphs = fix_list(list(c.paragraphs), "paragraph")
    for group in (c.items, c.columns):
        keep = []
        for it in group:
            it.text = fix(it.text, "item") or ""
            it.bullets = fix_list(list(it.bullets), "item line")
            t = fix(it.title, "item title")
            if not (t or "").strip():
                if not it.text and not it.bullets:
                    continue
                t = ""
            it.title = t or ""
            keep.append(it)
        group[:] = keep
    keep_n = []
    for n in c.numbers:
        if is_directive(n.label) or is_directive(n.value):
            said.append(f"figure: the label «{n.label[:60]}» was an ask")
            continue
        keep_n.append(n)
    c.numbers = keep_n
    if c.chart is not None and c.chart.title and is_directive(c.chart.title):
        obj = directive_object(c.chart.title)
        c.chart.title = H.cap_first(obj) if obj else None
    if c.table is not None and c.table.caption and is_directive(c.table.caption):
        obj = directive_object(c.table.caption)
        c.table.caption = H.cap_first(obj) if obj else None
    return said


# the deck's size said to the planner, never a line of the deck («, слайдов 8–10», «6–8 слайдов», «на 10 слайдов»): the
# jury's cover read «, слайдов 8–10 · Доля обращений…»
_COUNT_PHRASE_RE = re.compile(
    r"[\s,;:—–·-]*(?:(?:не\s+более|не\s+больше|максимум|ровно|до|на|из)\s+)?"
    r"(?:слайдов\s*[:—–-]?\s*\d{1,2}(?:\s*(?:[–—−-]|до)\s*\d{1,2})?(?!\d)|\d{1,2}(?:\s*(?:[–—−-]|до)\s*\d{1,2})?\s+слайд(?:ов|а)?(?![а-яё]))",
    re.I,
)


def strip_count_phrase(text: Optional[str]) -> Optional[str]:
    """`text` without the deck's size said in it; the punctuation around the cut tidied."""
    if not text or not re.search(r"слайд", text, re.I):
        return text
    t = _COUNT_PHRASE_RE.sub("", text)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = re.sub(r"^[\s,;:—–·.-]+|[\s,;:—–·-]+$", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t


def scrub_outline(outline) -> list[str]:
    """scrub_slide over every slide of a planned deck; what changed (for the plan's warnings). The deck's size said
    in its title, the cover's title or subtitle is cut out of them."""
    out: list[str] = []
    for attr in ("title", "subtitle"):
        v = getattr(outline, attr, None)
        nv = strip_count_phrase(v)
        if nv != v:
            setattr(outline, attr, nv if (nv or attr == "subtitle") else v)
            out.append(f"deck {attr}: the slide count cut out of it")
    if outline.slides:
        cover = outline.slides[0]
        for attr in ("headline", "subtitle"):
            v = getattr(cover, attr, None)
            nv = strip_count_phrase(v)
            if nv != v and (nv or attr == "subtitle"):
                setattr(cover, attr, nv or None if attr == "subtitle" else nv)
                out.append(f"slide {cover.id}: the slide count cut out of its {attr}")
    for s in outline.slides:
        try:
            for x in scrub_slide(s):
                out.append(f"slide {s.id}: {x}")
        except Exception:  # noqa: BLE001 - the slide as planned
            continue
    return out


# «Добавь картинку с экраном приложения», «Нужна иллюстрация процесса сборки», «Вставь изображение склада»: a picture the
# author asks the deck to have (not the author's own photo — «фото я добавлю сам» keeps a free place, brief_structure)
_PICTURE_ASK_RE = re.compile(
    rf"(?:(?<=^)|(?<=[.!?]\s))(?P<ask>{_PREFIX}(?:добавь(?:те)?|вставь(?:те)?|помести(?:те)?|размести(?:те)?|нуж(?:ен|на|но|ны)|поставь(?:те)?)\s+"
    r"(?:сюда\s+|здесь\s+|на\s+слайд\s+)?(?P<what>(?:картинк|изображени|иллюстраци|рисун)\w*(?:\s+[^.!?\[\]]{2,80})?))[.!]?(?=\s|$)",
    re.I | re.M,
)


def picture_asks_as_notes(text: str) -> str:
    """Each picture the author asks for, said as a sentence of the slide, becomes the deck's own note on a line of its
    own («[Место под изображение: картинка с экраном приложения]»): the picture goes on that slide (planning/faithful,
    planning/pictures) and the ask never stays as its text."""
    if not text or not re.search(r"картинк|изображени|иллюстраци|рисун", text, re.I):
        return text
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith(("[", "|", "```")):
            out.append(line)
            continue
        notes: list[str] = []

        def repl(m: re.Match) -> str:
            what = H.strip_end(m.group("what"))
            obj = directive_object(m.group("ask")) or what
            # «картинка с экраном приложения» → «экран приложения»: what the picture shows, not that it is a picture
            mm = re.match(r"^(?:картинк|изображени|иллюстраци|рисун)\w*\s+(?:с|со)\s+(?P<w>\S+)(?P<r>.*)$", obj, re.I)
            if mm:
                w = mm.group("w")
                w = w[:-2] if re.search(r"[бвгдзклмнпрстфхцчшщ]ом$", w) else (w[:-3] + "а" if w.endswith("ой") and len(w) > 4 else w)
                obj = (w + mm.group("r")).strip()
            notes.append(f"[Место под изображение: {H.cap_first(obj)}]")
            return ""

        new = _PICTURE_ASK_RE.sub(repl, line)
        if notes:
            new = " ".join(new.split())
            out.extend([x for x in (new,) if x.strip()] + notes)
        else:
            out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")
