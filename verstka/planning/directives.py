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


# ------------------------------------------------------------------ what the author says to the deck-maker (жюри 5)
# «сделай 8 слайдов, без картинок», «не выдумывай цифру», «проверь», «по-моему PaaS быстрее всех», «(наметки, таблицы
# приложил)», «Таблица по месяцам и SLA во вложении, цели — в регламенте (база знаний)»: rules of the deck, the author's
# guesses to check and pointers to the material are done (the count, no pictures, the data asked), never printed — on a
# data deck the jury read them on the cover and the slides (VKT-C, W-C, E-C, L-C, L-D).

_V = r"(?:и\s+|а\s+|но\s+|только\s+)?"
_PIC = r"(?:картин\w*|изображени\w*|фото\w*|иллюстраци\w*|рисунк\w*|анимаци\w*)"
_NOTE_RES = (
    # no pictures / pictures
    re.compile(rf"^{_V}(?:без|с|со)\s+{_PIC}(?:\s+(?:и|или)\s+{_PIC})?$", re.I),
    re.compile(rf"^{_V}{_PIC}\s+(?:не\s+(?:нужн\w*|надо|став\w*|добавля\w*|вставля\w*|рису\w*)|ненужн\w*)$", re.I),
    # never invent
    re.compile(rf"^{_V}(?:ничего\s+)?(?:не\s+(?:выдумыва|придумыва|додумыва|сочиня|фантазир|домысл|выдума|придума)\w*|без\s+(?:выдумок|домыслов|фантазий))\b", re.I),
    re.compile(r"^(?:выдумывать|придумывать|додумывать)\s+(?:ничего\s+)?не\s+(?:надо|нужно|стоит)\b", re.I),
    # the analyst's own work: «проверь», «посчитай по таблице выручки»
    re.compile(rf"^{_V}(?:проверь(?:те)?|перепроверь(?:те)?|посчитай(?:те)?|подсчитай(?:те)?|пересчитай(?:те)?|вычисли(?:те)?|сверь(?:те)?|"
               r"уточни(?:те)?|глянь(?:те)?|посмотри(?:те)?|прикинь(?:те)?|разберись|выясни(?:те)?)\b", re.I),
    # the author's guess («по-моему PaaS быстрее всех»): the data answers it, the deck never states it
    re.compile(rf"^{_V}(?:по-моему|по\s+моему|мне\s+кажется|кажется|я\s+думаю|думаю|наверное|вроде(?:\s+бы)?|если\s+не\s+ошибаюсь|подозреваю)\b", re.I),
    # pointers to the material: «таблицы приложил», «Таблица по месяцам и SLA во вложении», «цели — в регламенте»
    re.compile(r"(?:^|\s)(?:во\s+вложени\w*|в\s+приложени\w*|приложил\w*|приложены|приложена|приложен|прикрепил\w*|прилагаю|прикладываю|в\s+аттаче)$", re.I),
    re.compile(r"^[^—–:]{1,70}?\s*[—–-]\s*(?:в|во)\s+(?:файл\w*|таблиц\w*|вложени\w*|приложени\w*|баз\w*\s+знаний|регламент\w*|положени\w*|"
               r"отч[её]т\w*|\w*меморандум\w*|документ\w*|материал\w*|excel|xlsx|csv)(?:\s+[\w-]+){0,2}$", re.I),
    re.compile(r"^(?:все\s+|полные\s+|сырые\s+)?(?:данные|цифры|таблиц\w*|файл\w*|выгрузк\w*)(?:\s+[\w«»-]+){0,4}?\s+(?:в|во)\s+"
               r"(?:файл\w*|таблиц\w*|вложени\w*|приложени\w*)(?:\s+(?:ниже|выше))?$", re.I),
    re.compile(r"^(?:база\s+знаний|в\s+базе\s+знаний|см\.?\s.+|смотри\s.+)$", re.I),
    # the author's marks: «(наметки)», «(черновик)»
    re.compile(r"^(?:наметки|наброс\w*|черновик\w*|черновой(?:\s+\w+)?|драфт|draft|wip|todo|tbd|предварительн\w*|не\s+финал\w*|"
               r"примерн\w*(?:\s+(?:план|структура|наметки|тезисы))?|сыро\w*|для\s+себя|пока\s+наброс\w*|"
               r"причин\w*\s+(?:пока\s+)?не\s+зна\w*)$", re.I),
    # «О чём хочу рассказать:» — the line that opens the plan
    re.compile(r"^(?:о\s+ч[её]м\s+(?:хочу|хотим|хотел\w*|буду|будем|нужно|надо)\s+рассказать|что\s+(?:хочу|хотим)\s+рассказать)$", re.I),
)
# the rules of the deck as a whole («сделай 8 слайдов», «5 слайдов»): what is left of the clause without its count
_COUNT_LEFT_RE = re.compile(r"^(?:(?:сделай(?:те)?|подготовь(?:те)?|собери(?:те)?|нужно|нужн[аы]|надо|давай|уложись\s+в|уложиться\s+в|хватит|"
                            r"примерно|около|всего|ровно|итого|максимум|не\s+больше|не\s+более)\s*)*$", re.I)
_HEDGE_TAIL_RE = re.compile(r"\s+[—–]\s+(?=(?:по-моему|по\s+моему|мне\s+кажется|кажется|я\s+думаю|думаю|наверное|вроде|подозреваю|проверь)\b)", re.I)
_CHECK_RE = re.compile(r"^(?:и\s+|а\s+)?(?:проверь(?:те)?|перепроверь(?:те)?|сверь(?:те)?)$", re.I)


def is_author_note(clause: str) -> bool:
    """A clause the author says to whoever makes the deck, not to its audience: the deck's size, no pictures, «не
    выдумывай цифру», «проверь», a guess («по-моему …»), a pointer to the material («таблицы приложил», «цели — в
    регламенте»), a mark («наметки», «черновик»)."""
    c = " ".join((clause or "").replace(" ", " ").split()).strip(" .!,;:—–-«»\"")
    if not c:
        return False
    if re.search(r"слайд", c, re.I):
        left = strip_count_phrase(c)
        if left != c and _COUNT_LEFT_RE.match((left or "").strip(" ,.:;—–-")):
            return True
    if any(rx.search(c) for rx in _NOTE_RES):
        return True
    return is_pointer(c)


_STRONG_NOTE_RES = _NOTE_RES[:4]  # pictures and «не выдумывай»: a bracket with one of them is the author's note entirely
# what a plan keeps to be read by (the item's subject): «посчитай по таблице выручки» names the file the item is about,
# «по-моему PaaS быстрее всех» the series — the deck's last check takes them off the slides (scrub_author_notes)
_PLAN_KEEPS = (_NOTE_RES[4], _NOTE_RES[5])


def _is_note(clause: str, for_plan: bool) -> bool:
    if not is_author_note(clause):
        return False
    if for_plan:
        c = " ".join((clause or "").split()).strip(" .!,;:—–-")
        if any(rx.search(c) for rx in _PLAN_KEEPS) and not _CHECK_RE.match(c):
            return False
    return True


def _clean_brackets(text: str) -> str:
    def repl(m: re.Match) -> str:
        parts = [p.strip() for p in re.split(r"[,;]\s*", m.group(1)) if p.strip()]
        if not parts:
            return m.group(0)
        notes = [p for p in parts if is_author_note(p)]
        if not notes:
            return m.group(0)
        if len(notes) == len(parts) or any(rx.search(p) for p in notes for rx in _STRONG_NOTE_RES) or \
                any(re.search(r"слайд", p, re.I) for p in notes):
            return ""
        return " (" + ", ".join(p for p in parts if p not in notes) + ")"

    t = re.sub(r"\s*\(([^()]{1,120})\)", repl, text)
    # a bracket the line was cut through («Для правления (наметки», «VK Cloud, таблицы приложил)»)
    m = re.search(r"\s*\(([^()]*)$", t)
    if m and m.group(1).strip() and all(is_author_note(p) for p in re.split(r"[,;]\s*", m.group(1)) if p.strip()):
        t = t[: m.start()]
    m = re.match(r"^([^()]*)\)", t)
    if m:
        parts = re.split(r"(,\s+|;\s+)", m.group(1))
        tail = parts[-1]
        if is_author_note(tail):
            t = "".join(parts[:-2]) + t[m.end():]
    return t


# «Что просим: 3 кладовщика сделай 6 слайдов» — the deck's size glued to the line before it (a plan's last item and the
# count line after it, read as one)
_GLUED_COUNT_RE = re.compile(r"\s+(?:сделай(?:те)?|подготовь(?:те)?|собери(?:те)?|нужно|надо|давай|всего|итого)\s+(?:на\s+|ровно\s+|не\s+более\s+|до\s+)?"
                             r"\d{1,2}(?:\s*[–—-]\s*\d{1,2})?\s+слайд\w*", re.I)


def _clean_sentence(sent: str, for_plan: bool = False) -> str:
    s = _GLUED_COUNT_RE.sub("", sent.strip()).strip()
    end = s[-1] if s and s[-1] in ".!?…" else ""
    body = s[:-1].rstrip() if end else s
    pieces = re.split(r"(,\s+|;\s+)", body)
    clauses, seps = pieces[0::2], pieces[1::2]
    keep: list[tuple[str, str]] = []  # (separator before, clause)
    last_dropped = False
    for i, c in enumerate(clauses):
        sep = seps[i - 1] if i else ""
        if _is_note(c, for_plan):
            if _CHECK_RE.match(c.strip(" .!?")) and keep and not for_plan:
                # «госсектор выстрелил, проверь»: the guess before «проверь» goes with it — the data answers it
                psep, prev = keep[-1]
                cut = list(re.finditer(r"\s+[—–]\s+", prev))
                if cut:
                    keep[-1] = (psep, prev[: cut[-1].start()])
                elif len(keep) > 1:
                    keep.pop()
            last_dropped = True
            continue
        # «Какие сервисы тянут рост — по-моему PaaS быстрее всех»: the guess after a dash goes
        m = None if for_plan else _HEDGE_TAIL_RE.search(c)
        if m:
            c = c[: m.start()]
            last_dropped = True
        else:
            last_dropped = False
        if c.strip():
            keep.append((sep, c))
    if not keep:
        return ""
    out = "".join((sep if k else "") + c for k, (sep, c) in enumerate(keep)).strip(" ,;—–-")
    if not out:
        return ""
    if end:
        out += end if not last_dropped or end in ".…" else "."
    return out


def drop_author_notes(text: Optional[str], for_plan: bool = False) -> Optional[str]:
    """`text` without what the author says to the deck-maker (is_author_note): its brackets of notes, its clauses of
    rules, guesses and pointers; "" when nothing else is said. A text without such words comes back as it is."""
    if not text or not text.strip():
        return text
    t = _clean_brackets(text)
    sents = re.split(r"(?<=[.!?…])\s+(?=\S)", t.strip())
    out = [x for x in (_clean_sentence(s, for_plan) for s in sents) if x and x.strip(" .!?…,;:—–-")]
    joined = " ".join(out)
    joined = re.sub(r"\s+([,.;:!?])", r"\1", joined).strip()
    if joined.rstrip(".") == (text or "").strip().rstrip("."):
        return text
    if joined and not re.search(r"[.!?…]$", (text or "").strip()):
        joined = joined.rstrip(".")
    return H.cap_first(joined) if (text or "").strip()[:1].isupper() else joined


_LIST_MARK_RE = re.compile(r"^(\s*(?:[-–—•*·]|\d{1,2}\s*[.)])\s+)(.*)$")


def plan_text(text: str) -> str:
    """The author's text with what they say to the deck-maker taken out line by line (drop_author_notes) — the plan
    the deck is read from (plan_form.as_slides); a line that only said such things goes. The designer's asks («покажи
    рост») stay: the planner takes them as the slide's form; so do the analyst's asks and the author's guesses
    («посчитай по таблице выручки», «по-моему PaaS быстрее всех») — they name what the item is about, the deck's last
    check (scrub_author_notes) takes them off the slides."""
    out: list[str] = []
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("|"):
            out.append(line)
            continue
        m = _LIST_MARK_RE.match(line)
        mark, body = (m.group(1), m.group(2)) if m else ("", line)
        new = drop_author_notes(body, for_plan=True)
        if new is None or not new.strip(" .!?…,;:—–-"):
            continue
        out.append(mark + new)
    return "\n".join(out) + ("\n" if (text or "").endswith("\n") else "")


def _is_data_slide(s) -> bool:
    return getattr(s, "data", None) is not None or s.id in ("key-figures", "summary", "next-steps") or \
        (s.id.startswith("data-") and not s.id.startswith("data-plan"))


def scrub_author_notes(outline) -> list[str]:
    """The last check of a data deck (with and without a model, with and without a knowledge base): no cover, heading,
    line or note says what the author said to the deck-maker (drop_author_notes); the slides of the author's text lose
    their asks to the designer too (scrub_slide). The data slides keep their charts and conclusions — only a note that
    came into their words goes. A slide of text left with nothing to say goes. What changed, in English."""
    from verstka.schemas.common import PatternKind

    said: list[str] = []

    def fix(v: Optional[str], where: str) -> Optional[str]:
        nv = drop_author_notes(v)
        if nv != v:
            said.append(f"{where}: the author's note «{(v or '')[:60]}» cut")
        return nv

    for attr in ("title", "subtitle"):
        v = getattr(outline, attr, None)
        nv = fix(v, f"deck {attr}")
        if nv != v and (nv or attr == "subtitle"):
            setattr(outline, attr, nv or None)
    keep_slides = []
    cover = outline.slides[0] if outline.slides and outline.slides[0].kind == PatternKind.title else None
    if cover is not None and cover.headline and cover.subtitle:
        # «Итоги Q3 по поддержке» over «Итоги Q3 по поддержке для директора …»: the subtitle says only what is new
        head, sub = H.strip_end(cover.headline), cover.subtitle.strip()
        if sub.lower().startswith(head.lower()) and len(sub) > len(head) + 3:
            rest = sub[len(head):].strip(" ,—–-:")
            if rest:
                cover.subtitle = H.cap_first(rest)
                said.append("cover: the subtitle repeated the title — its new part kept")
    for s in outline.slides:
        c = s.content
        head = fix(s.headline, f"slide {s.id} headline")
        if head and head.strip():
            s.headline = head
        s.subtitle = fix(s.subtitle, f"slide {s.id} subtitle") or None
        s.takeaway = fix(s.takeaway, f"slide {s.id} takeaway") or None
        s.footnote = fix(s.footnote, f"slide {s.id} footnote") or None
        if s.notes:
            lines = [ln if ln.lstrip().startswith(("Источник", "Источники", "Посчитано")) else (drop_author_notes(ln) or "") for ln in s.notes.splitlines()]
            s.notes = "\n".join(ln for ln in lines if ln.strip()) or None
        if s.kind == PatternKind.title or _is_data_slide(s):
            keep_slides.append(s)
            continue
        seen: set[str] = set()
        bullets = []
        for b in c.bullets:
            nb = fix(b, f"slide {s.id} line")
            k = " ".join((nb or "").lower().split()).rstrip(".")
            if k == " ".join(H.strip_end(s.headline or "").lower().split()):
                continue  # («Какие сервисы тянут рост» under itself once its guess is gone)
            if nb and nb.strip(" .") and k not in seen:
                seen.add(k)
                bullets.append(nb)
        c.bullets = bullets
        c.paragraphs = [p for p in (fix(p, f"slide {s.id} paragraph") for p in c.paragraphs) if p and p.strip(" .")]
        for group in (c.items, c.columns):
            kept = []
            for it in group:
                it.title = fix(it.title, f"slide {s.id} item") or ""
                it.text = fix(it.text, f"slide {s.id} item") or ""
                it.bullets = [b for b in (fix(b, f"slide {s.id} item line") for b in it.bullets) if b and b.strip(" .")]
                if it.title or it.text or it.bullets or it.number:
                    kept.append(it)
            group[:] = kept
        try:
            said.extend(f"slide {s.id}: {x}" for x in scrub_slide(s))
        except Exception:  # noqa: BLE001 - the slide as it is
            pass
        if not (head or "").strip():
            # the heading was a note itself: the slide's first line heads it
            first = next((b for b in c.bullets), None)
            if first:
                s.headline = H.strip_end(first)
                c.bullets = c.bullets[1:]
        if s.id.startswith("data-plan") and c.bullets and not (c.paragraphs or c.items or c.columns or c.numbers or c.table is not None
                                                               or c.chart is not None) \
                and all(b.rstrip().endswith("?") and not re.search(r"\d", b) for b in c.bullets):
            # «Воронка: где теряем?» once its guess is gone: a question to the data, no words of the author's own — the
            # plan's bare item has no slide (planning/plan_data.py)
            said.append(f"slide {s.id}: only the author's question «{c.bullets[0][:50]}» — dropped")
            continue
        empty = not (c.bullets or c.paragraphs or c.items or c.columns or c.numbers or c.table is not None or c.chart is not None)
        if not (s.headline or "").strip() or (empty and s.kind != PatternKind.section and (s.id.startswith(("context", "ask")) or not (s.subtitle or ""))):
            said.append(f"slide {s.id}: only the author's notes — dropped")
            continue
        keep_slides.append(s)
    outline.slides = keep_slides
    return said
