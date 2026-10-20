"""A long document is material, not a plan (jury 20.10, R13: a meeting transcript in DOCX became 159 slides of raw
speech — «Денис, Господи, я, блин, формат PTX», «Всё, я могу»).

`is_long_document(text)` — a text of its own the size of a document (a transcript, a report, a long PDF) that does not
dictate its slides («Слайд N. …»): laid out paragraph by paragraph it would be a deck of dozens of slides. Such a text
is condensed into a deck of 10–15 slides (or the number the person asked for): each slide one thought, its title the
conclusion, its lines the facts, figures and decisions of the document; spoken filler, greetings, the talk about the
meeting itself never reach a slide.

- with a model (`document_digest` skill): the model condenses the document into the slides' conclusions and points;
  every figure it writes must be in the document (a line with a figure the document does not state is dropped), a line
  of spoken filler is dropped, and a model that fails or answers too little leaves the rules' digest;
- without a model (`digest_by_rules`): the document's own sentences, scored by what they carry (figures, decisions,
  requirements, names) against what speech carries (fillers, first person, questions, the meeting's logistics), the
  best of each part of the document in its order — a title made of the part's best sentence.

The result is the deck's text in the analyst's form («Слайд 1. Обложка / Название: …», «Слайд N. Вывод» and «- » lines
under it), so the dictated-slide path lays it out with and without a model. The rules rely on word shapes and a small
Russian/English lexicon of speech and of decisions — never on one document.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import BaseModel, Field

from verstka.planning import heuristics as H
from verstka.ru import clip_words

log = logging.getLogger(__name__)

LONG_WORDS = 1200  # a text of its own longer than this is a document (a page of A4 is ~400 words)
LONG_PARAGRAPHS = 40  # … or this many paragraphs (a letter's plan has a handful)
DEFAULT_SLIDES = 12  # the deck of a document when the person asked for no count: cover + 10 content + closing
MAX_SLIDES = 15
MIN_SLIDES = 5
HEAD_WORDS = 12  # a slide's title: a conclusion of at most this many words
POINT_WORDS = 26
POINTS = 3  # lines under a title
DOC_CHARS = 60000
LEAD_HEAD = "Общие сведения"  # what the model reads of a document (a 1.5-hour transcript is ~40 000 characters)

_SLIDE_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:слайд|slide)\s*№?\s*\d{1,3}\b", re.I | re.M)
_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_TABLE_RE = re.compile(r"^\s*\|")
_HEAD_RE = re.compile(r"^\s*#{1,6}\s+(?P<t>.+?)\s*#*\s*$")
_ITEM_RE = re.compile(r"^\s*(?:[-–—•*·]|\d{1,2}[.)])\s+(?P<t>\S.*)$")
_TIMESTAMP_RE = re.compile(r"^\s*\[?\(?\d{1,2}:\d{2}(?::\d{2})?\)?\]?\s*")
_SPEAKER_RE = re.compile(r"^\s*(?:[А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+){1,2}|Спикер\s*\d+|Speaker\s*\d+|Участник\s*\d*|Модератор|Ведущий|Ведущая)\s*:\s+(?=\S)")
_FILE_NAME_RE = re.compile(r"\.(?:mp4|mp3|m4a|wav|mov|avi|docx?|pdf|pptx?|txt|md)\b|_\d", re.I)

# speech: what a talk says about itself and the words it fills pauses with
_FILLER_RE = re.compile(
    r"(?<![\wё])(?:блин|господи|короче|типа|как\s+бы|это\s+самое|так\s+сказать|скажем\s+так|в\s+общем(?:-то)?|ну\s+вот|вот\s+это|"
    r"на\s+самом\s+деле|если\s+честно|честно\s+говоря|я\s+думаю|мне\s+кажется|я\s+так\s+понимаю|понимаете|знаете|"
    r"слышно|видно\s+(?:меня|экран)|меня\s+слышно|секундочку|минуточку|извините|простите|кстати|ой|эм+|ээ+|ага|угу|"
    r"окей|ок\b|ладно|хорошо,|отлично,|супер|спасибо|благодарю|пожалуйста|до\s+свидания|всем\s+привет|значит|собственно|"
    r"видимо|конечно|то\s+есть|наверное|вообще(?:-то)?|получается|грубо\s+говоря|ну\s+и|ну,|да,|вот,|"
    r"you\s+know|i\s+mean|kind\s+of|sort\s+of|okay|thank\s+you|thanks)(?![\wё])",
    re.I,
)
_OPENER_RE = re.compile(
    r"^(?:итак|ну|вот|да|так|всё|все|хорошо|окей|ладно|отлично|значит|смотрите|слушайте|давайте|а|и|но|также|ещё|еще|"
    r"во-первых|во-вторых|в-третьих|в-четв[её]ртых|во-пятых|в\s+(?:том\s+)?числе|кроме\s+того|при\s+этом|поэтому|то\s+есть|"
    r"здесь|тут|конечно|собственно|в\s+целом|соответственно|"
    r"кстати|в\s+общем|короче|собственно|so|well|ok|okay|and|but)\b[,!.]?\s+",
    re.I,
)
_GREETING_RE = re.compile(r"\b(?:добрый\s+(?:день|вечер)|доброе\s+утро|здравствуй\w*|привет\w*|уважаемые|рады\s+приветствовать|коллеги,|друзья,|hello|good\s+(?:morning|afternoon))\b", re.I)
_MEETING_RE = re.compile(
    r"\b(?:микрофон\w*|камер\w*|чат\w*|подним\w*\s+рук\w*|руку|телемост\w*|демонстраци\w*\s+экрана|экран\w*|запис\w*\s+встреч\w*|"
    r"встреч\w*|созвон\w*|сесси\w*|вопрос\w*|ответ\w*|слово|ссылк\w*\s+на\s+запис\w*|meeting|microphone|camera|chat)\b",
    re.I,
)
_FIRST_PERSON_RE = re.compile(r"(?<![\wё])(?:я|мне|меня|мной|мой|моя|моё|мои|i|me|my)(?![\wё])", re.I)
_DECISION_RE = re.compile(
    r"\b(?:нужн\w*|необходим\w*|должн\w*|обязательн\w*|требовани\w*|требу\w*|важн\w*|главн\w*|ключев\w*|решени\w*|решил\w*|"
    r"договорил\w*|итог\w*|вывод\w*|результат\w*|срок\w*|дедлайн\w*|до\s+\d{1,2}\s+[а-я]+|оцени\w*|критери\w*|приоритет\w*|"
    r"рекоменд\w*|предлага\w*|просим|прошу|план\w*|цел[ьи]\w*|задач\w*|не\s+допуска\w*|нельзя|можно|запрещ\w*|разреш\w*|"
    r"выросл?\w*|снизил?\w*|увеличил?\w*|сократил?\w*|составил?\w*|достиг\w*|"
    r"must|should|need\w*|required?|decid\w*|result\w*|deadline|goal|priority|recommend\w*)\b",
    re.I,
)
_ASK_RE = re.compile(
    r"\b(?:просим|прошу|предлага\w*|предложени\w*|нужно\s+(?:выделить|утвердить|согласовать|принять|решить)|необходимо|"
    r"следующ\w*\s+шаг\w*|дальше\s+(?:нужно|мы)|итог\w*|вывод\w*|главное|договорил\w*|решил\w*|решени\w*|"
    r"ask|propose|next\s+steps?|we\s+decided|conclusion)\b",
    re.I,
)
_FIG_RE = re.compile(r"(?<![\w.,])\d+(?:[.,  ]\d+)*(?:\s?(?:%|₽|руб\w*|млн|млрд|тыс\.?|ч|час\w*|мин\w*|дн\w*|лет|год\w*|слайд\w*|шт\.?))?", re.I)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_QUOTED_RE = re.compile(r"«([^«»]{3,80})»")
_TERM_RE = re.compile(r"\b[A-Z]{2,}[A-Za-z0-9]*\b")
_STEM_RE = re.compile(r"[a-zа-яё0-9]{4,}", re.I)


def _plain(line: str) -> str:
    return re.sub(r"\*\*|__|`", "", line).strip()


def _words(text: str) -> int:
    return len(re.findall(r"[\wё]+", text))


def _stems(text: str) -> set[str]:
    return {w.lower()[:6] for w in _STEM_RE.findall(text)}


def _body(text: str) -> str:
    m = _FRONT_RE.match(text or "")
    return (text or "")[m.end():] if m else (text or "")


def is_long_document(text: str, plan_items: int = 0) -> bool:
    """A text of its own the size of a document, not a deck the person dictated: no «Слайд N.» marks, longer than
    LONG_WORDS words (or of LONG_PARAGRAPHS paragraphs and more) of prose. A long plan of short items, a few theses, a
    letter — none of them."""
    body = _body(text)
    if not body.strip() or _SLIDE_RE.search(body):
        return False
    lines = [ln for ln in body.splitlines() if ln.strip()]
    prose = [ln for ln in lines if not _TABLE_RE.match(ln)]
    words = sum(_words(ln) for ln in prose)
    if plan_items > MAX_SLIDES - 1:
        return True  # a letter of more parts than a deck has slides
    if words < LONG_WORDS // 3:
        return False
    paras = [ln for ln in prose if _words(ln) >= 12 and not _HEAD_RE.match(ln)]
    return words >= LONG_WORDS or len(paras) >= LONG_PARAGRAPHS


def deck_size(asked: Optional[int], words: int = 0) -> int:
    """The digest's slides with the cover: the person's count, else DEFAULT_SLIDES (a shorter document — a slide per
    ~40 of its words, 8 at least)."""
    if asked:
        return max(3, int(asked))
    if words and words < DEFAULT_SLIDES * 40:
        return max(10 if words >= 350 else 8, words // 40)
    return DEFAULT_SLIDES


SHORT_DOC_WORDS = 250  # without a model, a document of its own this long is digested too (a model would plan it)


def is_document(text: str) -> bool:
    """A text of its own worth a deck of several slides that dictates none (no «Слайд N.»): SHORT_DOC_WORDS words or
    more in six paragraphs or more. Without a model such a text is digested by the rules; with one, the planner reads it."""
    body = _body(text)
    if not body.strip() or _SLIDE_RE.search(body):
        return False
    lines = [ln for ln in body.splitlines() if ln.strip() and not _TABLE_RE.match(ln)]
    return sum(_words(ln) for ln in lines) >= SHORT_DOC_WORDS and sum(1 for ln in lines if _words(ln) >= 8) >= 6


# ------------------------------------------------------------------ reading the document


@dataclass
class _Sent:
    text: str
    pos: int  # the sentence's place in the document
    para: int
    score: float = 0.0
    words: int = 0


@dataclass
class _Doc:
    title: Optional[str]
    sentences: list[_Sent] = field(default_factory=list)
    heads: dict[int, str] = field(default_factory=dict)  # paragraph index → the heading it opens under
    tables: list[tuple[int, list[str], str]] = field(default_factory=list)  # (paragraph, rows, the line before it)
    words: int = 0
    speech: bool = False  # a talk (a transcript): its sentences are said, its slides restate them


# a talk's own turns of phrase: no slide line says them
_TALK_RE = re.compile(r"(?<![\wё])(?:давайте|если\s+вы|интересно\s+посмотреть|как-то|какие-то|какой-то|какая-то|в\s+целом|о\s+котор\w+\s+говорил\w*|"
                      r"так\s+вот|ничего\s+плохого|я\s+бы|мне\s+бы|вам\s+(?:скажу|расскажу)|мы\s+с\s+вами|как\s+вы\s+(?:знаете|видите)|"
                      r"это\s+тоже\s+в\s+плюс|будет\s+в\s+плюс|с\s+точки\s+зрения|(?:первый|второй|третий|следующий|интересный|хороший)\s+вопрос|"
                      r"вопрос\s*:|ответ\s*:|по-моему|вроде|может\s+быть|напомните|поправить|вместе\s+с\s+нами|на\s+встрече|"
                      r"(?<![а-яё])(?:вы|вас|вам|вами)(?![а-яё]))(?![\wё])", re.I)
_ASIDE_RE = re.compile(r",\s*(?:значит|вот|ну|как\s+бы|собственно|скажем|в\s+общем|кстати|конечно|видимо|наверное|да|то\s+есть|так\s+сказать|"
                       r"к\s+примеру|например|по\s+сути|грубо\s+говоря|честно\s+говоря|если\s+быть\s+\w+|соответственно|в\s+принципе|как\s+говорится)\s*(?=[,.!?]|$)", re.I)
_SPEECH_SWAPS = (
    (re.compile(r"^(?:ну|вот|итак|значит|так|да|смотрите|давайте)\s*,?\s+", re.I), ""),
    (re.compile(r"^если\s+говорить\s+(?:о|об|про)\s+[^,]{2,60},\s*(?:то\s+)?", re.I), ""),
    (re.compile(r"^(?:мы|я)\s+(?=[а-яё]+(?:ем|им|ём|ю|у)\b)", re.I), ""),  # «Мы предлагаем …» → «Предлагаем …»
    (re.compile(r"\b(?:у\s+нас|у\s+вас)\s+", re.I), ""),
    (re.compile(r"\bвы\s+(?:можете|сможете)\b", re.I), "можно"),
    (re.compile(r"\b(?:вам|вы)\s+(?:нужно|надо|необходимо|должны)\b", re.I), "нужно"),
    (re.compile(r"\b(?:ваш|ваша|ваше|ваши|вашего|вашей|вашему|вашим|ваших|вашу|наш|наша|наше|наши|нашего|нашей|нашему|нашим|наших|нашу)\s+", re.I), ""),
    (re.compile(r"\bвсё-таки\b\s*|\bвообще\b\s*|\bпросто\b\s*|\bдействительно\b\s*", re.I), ""),
)


def unspeak(s: str) -> str:
    """A sentence of a talk as a line of a slide: no asides («, значит,»), no lead-ins («Если говорить о формальностях,
    то»), no «мы»/«вы»/«ваш» — the statement itself («Мы предлагаем использовать модель…» → «Предлагаем использовать
    модель…», «прикрепить ссылку на ваше хранилище» → «прикрепить ссылку на хранилище»)."""
    t = _ASIDE_RE.sub("", s)
    for rx, rep in _SPEECH_SWAPS:
        t = rx.sub(rep, t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,")
    return H.cap_first(t) if t else s


def _clean_sentence(s: str) -> str:
    s = _TIMESTAMP_RE.sub("", s)
    s = _SPEAKER_RE.sub("", s)
    for _ in range(3):
        t = _OPENER_RE.sub("", s)
        if t == s:
            break
        s = t
    s = re.sub(r"\s+", " ", s).strip(" ,;—–-")
    return H.cap_first(s)


_QUESTION_RE = re.compile(r"^(?:\S+\s+)?(?:\S+\s+)?ли\b|^(?:как|что|почему|зачем|когда|где|кто|какой|какая|какие|сколько|можно\s+ли|нужно\s+ли)\b[^.!]*$", re.I)
_RELATIVE_RE = re.compile(r"\b(?:котор\w+|чей|чья|чьё|чьи)\b", re.I)
_FRAGMENT_RE = re.compile(r"^(?:котор\w+|что|чтобы|если|потому|поэтому|так\s+как|именно|это|то\s+есть|и|а|но|или|ли|как|где|когда)\b", re.I)


def _question(s: str) -> bool:
    return "?" in s or bool(_QUESTION_RE.search(s.strip()))


def score_sentence(s: str) -> float:
    """What a sentence carries for a slide (figures, decisions, requirements, names) against what speech carries
    (fillers, greetings, first person, questions, the meeting's own logistics). Below 1 — no slide line."""
    w = _words(s)
    if w < 5:
        return -5.0
    sc = 0.0
    figs = [m.group(0) for m in _FIG_RE.finditer(s) if not _YEAR_RE.fullmatch(m.group(0).strip())]
    sc += 1.6 * min(3, len(figs)) + 0.5 * min(2, len(_YEAR_RE.findall(s)))
    sc += 1.2 * min(3, len(_DECISION_RE.findall(s)))
    sc += 0.8 * min(2, len(_QUOTED_RE.findall(s))) + 0.4 * min(3, len(_TERM_RE.findall(s)))
    sc -= 2.5 * len(_FILLER_RE.findall(s))
    sc -= 2.0 * len(_TALK_RE.findall(s))
    if re.match(r"^[^\s,]+(?:\s[^\s,]+)?,\s", s):
        sc -= 3.0  # («Проектной работы, и всегда …»: a sentence cut by the transcript)
    sc -= 3.0 * bool(_GREETING_RE.search(s))
    sc -= 1.2 * min(3, len(_FIRST_PERSON_RE.findall(s)))
    sc -= 1.0 * min(3, len(_MEETING_RE.findall(s)))
    if _question(s):
        sc -= 3.0
    if w > 40:
        sc -= (w - 40) / 10
    if w < 8:
        sc -= 1.0
    return sc


def _read(text: str) -> _Doc:
    body = _body(text)
    lines = body.splitlines()
    doc = _Doc(title=None)
    speech = len(_FILLER_RE.findall(body)) + len(_FIRST_PERSON_RE.findall(body)) > max(8, _words(body) // 120)
    doc.speech = speech
    para = 0
    head: Optional[str] = None
    pending_table: list[str] = []
    prev_line = ""
    pos = 0
    for ln in lines + [""]:
        if _TABLE_RE.match(ln):
            pending_table.append(ln.strip())
            continue
        if pending_table:
            if len(pending_table) >= 3:
                doc.tables.append((para, list(pending_table), prev_line))
            pending_table = []
            para += 1
        s = ln.strip()
        if not s:
            continue
        hm = _HEAD_RE.match(s)
        if hm:
            t = _plain(hm.group("t"))
            if doc.title is None and not doc.sentences and not _FILE_NAME_RE.search(t):
                doc.title = H.strip_end(t)
            else:
                head = H.strip_end(t)
                doc.heads[para + 1] = head
            para += 1
            continue
        im = _ITEM_RE.match(s)
        raw = _plain(im.group("t") if im else s)
        doc.words += _words(raw)
        prev_line = raw
        for k, sent in enumerate(H.split_sentences(raw) or [raw]):
            c = _clean_sentence(sent)
            if not c:
                continue
            sc = score_sentence(c)
            if speech:
                c = unspeak(c)  # (scored as said — its speech counts against it —, shown as a statement) - (2.0 if sent.strip()[:1].islower() else 0.0)  # (a piece of a sentence cut by speech)
            if sc > -2:
                # a paragraph's first sentence says what it is about; the lead of an article («Общие сведения») most of all
                sc += (1.0 if k == 0 else 0.0) + (2.0 if head == LEAD_HEAD else 0.0)
            doc.sentences.append(_Sent(text=c, pos=pos, para=para, score=sc, words=_words(c)))
            pos += 1
        para += 1
    return doc


# ------------------------------------------------------------------ titles and lines


_TAIL_BAD = {
    "в", "во", "на", "с", "со", "к", "ко", "по", "за", "от", "до", "из", "у", "о", "об", "при", "для", "без", "через", "под", "над", "между",
    "и", "а", "но", "или", "либо", "что", "чтобы", "как", "где", "когда", "если", "то", "не", "ни", "это", "также", "так", "же", "ли",
    "связи", "соответствии", "отношении", "результате", "течение", "рамках", "качестве", "области", "счёт", "счет", "числе", "том",
    "котором", "которой", "которых", "который", "которая", "которое", "которые", "его", "её", "их", "свой", "своей", "своих", "the", "of",
    "and", "to", "in", "for", "with", "a", "an",
}
# a clause that hangs on the main one: «…, где показано», «…, которые …», «…, в том числе …» — never the end of a title
_SUBORDINATE_RE = re.compile(
    r",\s+(?=(?:котор\w+|где|когда|куда|откуда|что|чтобы|если|потому|поэтому|так\s+как|хотя|причём|причем|пока|после\s+того|"
    r"в\s+том\s+числе|включая|а\s+также|в\s+то\s+время|благодаря|несмотря|который|а\s+не|но\s+и)\b)|\s*;\s+|\s+\(",
    re.I,
)
_VERB_RE = re.compile(
    r"(?<![\wё])[а-яё]{2,}(?:ет|ют|ит|ят|ат|ут|ёт|ил|ила|ило|или|ал|ала|ало|али|ял|яла|яли|ос|осла|осли|ёс|ёл|ыл|ыла|ыли|ался|алась|ались|ется|ются|ится|ятся|"
    r"ен|ена|ено|ены|ан|ана|ано|аны|ён|ть|ться|ешь|ем|им)(?![\wё])|(?<![\wё])(?:есть|нет|нужн\w*|необходим\w*|должн\w*|можно|нельзя)(?![\wё])|\s[—–]\s",
    re.I,
)


def _balanced(t: str) -> bool:
    return t.count("«") == t.count("»") and t.count("(") == t.count(")") and t.count("\"") % 2 == 0


# a verb that needs what follows it: «мы ожидаем», «считаем», «является» — no end of a title
_DANGLING_RE = re.compile(r"^(?:ожида\w*|счита\w*|дума\w*|хоч\w*|хотим|хотят|говор\w*|скаж\w*|будет|будут|явля\w*|станет|стал[аио]?|"
                          r"составля\w*|составил\w*|включа\w*|означа\w*|получа\w*|показано|сказано|указано|следующ\w*|такие|такой|такая)$", re.I)
_PREP_CUT = ("в", "во", "на", "с", "со", "к", "по", "за", "от", "до", "из", "у", "о", "об", "при", "для", "без", "через", "под", "над", "между",
             "после", "перед", "около", "из-за", "благодаря", "согласно", "вокруг", "среди")


def _bare(word: str) -> str:
    return re.sub(r"[^\wё-]", "", word.lower())


def _clean_end(t: str) -> str:
    """The text without the words it may not end on (a preposition, a conjunction, «в связи», «в соответствии», «№»)."""
    ws = t.rstrip(" ,;:—–-").split()
    while len(ws) > 2 and (_bare(ws[-1]) in _TAIL_BAD or not _bare(ws[-1])):
        ws.pop()
    return " ".join(ws).rstrip(" ,;:—–-")


def _complete(t: str, max_words: int) -> bool:
    """A finished thought short enough for a title: 3+ words, a verb (or «X — Y»), quotes and brackets closed, an end that is
    no preposition or conjunction."""
    w = _words(t)
    if not 5 <= w <= max_words or not _balanced(t) or not _VERB_RE.search(" " + t):
        return False  # (4 words and fewer say no point: «Платформа как услуга — модель»)
    last = _bare((t.split() or [""])[-1])
    # («Предоставится, Qen 3.8 …», «Проектной работы, и всегда …»: a word or two cut off the sentence before)
    return (bool(last) and last not in _TAIL_BAD and not _DANGLING_RE.match(last) and not _FRAGMENT_RE.match(t)
            and not re.match(r"^[^\s,]+(?:\s[^\s,]+)?,\s", t))


def _phrase_cuts(t: str, limit: int) -> list[str]:
    """`t` shortened by its syntax: cut right before a preposition that opens a trailing phrase («…вырос на 1,2 м | в
    связи с подпором…»), the longest first, each within `limit` words."""
    ws = t.split()
    out = []
    for k in range(min(len(ws) - 1, limit), 2, -1):
        if _bare(ws[k]) in _PREP_CUT:
            out.append(" ".join(ws[:k]).rstrip(" ,;:—–-"))
    return out


def title_ok(t: str, max_words: int = HEAD_WORDS) -> bool:
    """A title that is a finished thought (see _complete)."""
    return _complete(t, max_words + 4)


def headline_of(sentence: str, max_words: int = HEAD_WORDS, fallback: Optional[str] = None) -> str:
    """A slide's title made of a sentence — always a finished thought, never a sentence cut off («…в связи», «…где
    показано»): the sentence itself when it fits (up to max_words + 4 words), else its main part — the clause before the
    first subordinate one («, где …», «, который …», «(…»), then without its trailing parts after commas — while it
    keeps its verb; a «Метка: текст» line its label and the head of the text; else `fallback` (the section's name); else
    the sentence cut where a phrase ends, never on a preposition or a conjunction."""
    ended = not sentence.rstrip().endswith(":")
    s = H.strip_end(sentence)
    # an aside in brackets is no part of a title («Байкал (бур. Байгал далай) — …», «заголовок-вывод («…»)»)
    bare = re.sub(r"\s*\([^()]*\)", "", s).strip()
    if _words(bare) >= 3 and _balanced(bare):
        s = bare
    # spoken asides between commas are no part of a title («…своих, значит, наработок», «Предоставится, если быть
    # суперточным, Qen 3.8 …»)
    s = re.sub(r",\s*(?:значит|к\s+примеру|например|собственно|конечно|видимо|наверное|так\s+сказать|скажем|в\s+общем|"
               r"если\s+быть\s+\w+|грубо\s+говоря|честно\s+говоря|да|вот|ну)\s*(?=,)", "", s, flags=re.I)
    s = re.sub(r"^(?:значит|к\s+примеру|например|собственно|конечно|ну|вот|да)\s*,\s*", "", s, flags=re.I)
    s = H.cap_first(s)
    limit = max_words + 4
    last = _bare((s.split() or [""])[-1])
    if (ended and _words(s) <= limit and _balanced(s) and last not in _TAIL_BAD and not _DANGLING_RE.match(last)
            and (_VERB_RE.search(" " + s) or ":" in s) and not _FRAGMENT_RE.match(s) and not _FILLER_RE.search(s)
            and not re.match(r"^[^\s,]+(?:\s[^\s,]+)?,\s", s)):  # («Критичные, какие-нибудь модели…»: words cut off their sentence)
        return s
    lab = re.match(r"^(?P<l>[^:«»()]{3,40}):\s+(?P<r>\S.+)$", s)
    if lab and _words(lab.group("l")) <= 4 and max_words - _words(lab.group("l")) >= 5:
        # «Выбор визуализации: ранжированный список из 2–3 вариантов …» — the label and the head of what it says
        rest = headline_of(lab.group("r"), max_words - _words(lab.group("l")), fallback=None)
        if _words(rest) >= 3 and _clean_end(rest) == rest:
            return H.cap_first(lab.group("l").strip()) + ": " + (rest[:1].lower() + rest[1:] if rest[1:2].islower() else rest)
    main = _SUBORDINATE_RE.split(s, maxsplit=1)[0].strip(" ,;:—–-")
    for cand in (main, *_shorter(main), *_phrase_cuts(main, limit)):
        if _complete(cand, limit):
            return H.cap_first(cand)
    # «Байкал — самое глубокое озеро на планете, крупнейший …»: the statement before the dash's tail
    if " — " in s:
        head = s.split(" — ", 1)[0]
        tail = s.split(" — ", 1)[1]
        tail_main = re.split(r",\s+|\s+[—–]\s+", tail, maxsplit=1)[0]
        cand = f"{head} — {tail_main}"
        if 5 <= _words(cand) <= limit and _balanced(cand) and _clean_end(cand) == cand and not _DANGLING_RE.match(_bare(cand.split()[-1])):
            return H.cap_first(cand)
    if fallback:
        return H.cap_first(H.strip_end(fallback))
    head = re.split(r",\s+|\s+[—–]\s+", main, maxsplit=1)[0]
    if 3 <= _words(head) <= limit and _balanced(head) and _clean_end(head) == head:
        return H.cap_first(head)  # «Тайминг на хокатоне»: the subject, never a run-on cut mid-phrase
    main = re.sub(r"^[^\s,]+(?:\s[^\s,]+)?,\s+(?=\S+\s+\S+\s+\S+)", "", main)  # (words cut off the sentence before)
    cut = _clean_end(clip_words(main if _words(main) >= 4 else s, limit))
    while not _balanced(cut) and _words(cut) > 3:
        cut = _clean_end(" ".join(cut.split()[:-1]))
    return H.cap_first(cut)


def _shorter(t: str) -> list[str]:
    """`t` without its trailing parts after commas, one by one (the longest first)."""
    parts = re.split(r",\s+", t)
    out = []
    while len(parts) > 1:
        parts = parts[:-1]
        out.append(", ".join(parts))
    return out


def point_of(sentence: str) -> str:
    s = H.strip_end(sentence)
    if _words(s) > POINT_WORDS:
        s = H.short(s, POINT_WORDS)
    return H.cap_first(s)


def _similar(a: str, b: str, share: float = 0.6) -> bool:
    sa, sb = _stems(a), _stems(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / min(len(sa), len(sb)) >= share


def _cover_title(doc: _Doc, title_hint: Optional[str]) -> str:
    for t in (title_hint, doc.title):
        if t and not _FILE_NAME_RE.search(t) and 1 <= _words(t) <= 14:
            return H.strip_end(t)
    quoted: dict[str, int] = {}
    for s in doc.sentences:
        for q in _QUOTED_RE.findall(s.text):
            quoted[q] = quoted.get(q, 0) + 1
    if quoted:
        q, n = max(quoted.items(), key=lambda kv: (kv[1], len(kv[0])))
        if n >= 2:
            return q
    for s in doc.sentences[:6]:
        for q in _QUOTED_RE.findall(s.text):
            if _words(q) >= 2:
                return q
    best = max(doc.sentences, key=lambda x: x.score, default=None)
    return headline_of(best.text, 8) if best is not None else "Главное из документа"


# ------------------------------------------------------------------ the deck's text


@dataclass
class DigestSlide:
    title: str
    points: list[str] = field(default_factory=list)
    table: list[str] = field(default_factory=list)


@dataclass
class Digest:
    title: str
    slides: list[DigestSlide]
    by: str = "rules"  # "rules" | "model"
    words: int = 0  # the document's words
    dropped: int = 0  # the document's sentences that reached no slide
    subtitle: str = ""
    source: Optional[dict] = None  # {"title", "url"}: the article the deck is made of (a topic without a model)

    def text(self) -> str:
        out = ["Слайд 1. Обложка", f"Название: {self.title}"] + ([f"Подзаголовок: {self.subtitle}"] if self.subtitle else [])
        for n, s in enumerate(self.slides, 2):
            out += ["", f"Слайд {n}. {s.title}"]
            mark = "- " if len(s.points) > 1 else ""  # (a lone line is the slide's text, not a list of one)
            out += [f"{mark}{H.strip_end(p)}." if not p.rstrip().endswith(("!", "?", "…")) and not H.ABBR_END_RE.search(p.strip()) else f"{mark}{p}" for p in s.points]
            if s.table:
                out += [""] + s.table
        return "\n".join(out).strip() + "\n"

    @property
    def size(self) -> int:
        return len(self.slides) + 1


def _buckets(doc: _Doc, n: int) -> list[list[_Sent]]:
    """The document's sentences in `n` consecutive parts: by its headings when it has about that many, else of about
    the same number of words each, cut between paragraphs."""
    sents = doc.sentences
    if not sents:
        return []
    heads = sorted(doc.heads)
    if 3 <= len(heads) <= n:
        bounds = heads
        out: list[list[_Sent]] = []
        cur: list[_Sent] = []
        k = 0
        for s in sents:
            while k < len(bounds) and s.para >= bounds[k]:
                if cur:
                    out.append(cur)
                cur = []
                k += 1
            cur.append(s)
        if cur:
            out.append(cur)
        return out
    if doc.words < 1000:
        # a short document: its sentences of substance shared out evenly, in order (its few words would leave word-sized
        # parts empty)
        real = [s for s in sents if s.words >= 6]
        k = max(1, -(-len(real) // max(1, n)))
        return [real[i:i + k] for i in range(0, len(real), k)]
    total = sum(s.words for s in sents)
    per = total / max(1, n)
    out = []
    cur = []
    acc = 0.0
    for i, s in enumerate(sents):
        cur.append(s)
        acc += s.words
        nxt = sents[i + 1] if i + 1 < len(sents) else None
        if acc >= per * (len(out) + 1) and (nxt is None or nxt.para != s.para) and len(out) < n - 1:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def digest_by_rules(text: str, slides: Optional[int] = None, *, title_hint: Optional[str] = None) -> Optional[Digest]:
    """The rules' digest of a long document (no model): None when the document has too little to say."""
    doc = _read(text)
    if not doc.sentences:
        return None
    size = deck_size(slides, doc.words)
    n_content = max(1, size - 2)  # cover and the closing
    per = 2 if doc.words < 1000 or doc.speech else POINTS  # a short document or a talk: fewer lines a slide, more slides
    point_floor = 2.0 if doc.speech else -99.0  # (a talk's weak sentences are speech, not facts)
    used: list[str] = []

    def fresh(s: _Sent) -> bool:
        return not any(_similar(s.text, u) for u in used)

    def heading_of(x: _Sent) -> Optional[str]:
        """The name of the document's section the sentence stands in (a title when its sentences give none)."""
        k = max((p for p in doc.heads if p <= x.para), default=None)
        h = doc.heads.get(k) if k is not None else None
        return h if h and h != LEAD_HEAD and 1 <= _words(h) <= 10 else None

    out: list[DigestSlide] = []
    tables = list(doc.tables[:2])
    n_text = max(1, n_content - len(tables))
    for floor in ((0.0,) if doc.words < 1000 else (2.0, 1.0, 0.0)):  # (a short document is all material)
        out, used = [], []
        carry: list[_Sent] = []
        for part in _buckets(doc, n_text):
            good = sorted((s for s in [*carry, *part] if s.score >= floor and s.words >= 6), key=lambda s: -s.score)
            carry = []
            pick: list[_Sent] = []
            for s in good:
                if fresh(s) and not any(_similar(s.text, p.text) for p in pick):
                    pick.append(s)
                if len(pick) >= per + 1:
                    break
            if not pick:
                continue
            lead = max(pick[:3], key=lambda s: s.score - max(0, s.words - HEAD_WORDS - 2) * 0.5 - 4 * bool(_FRAGMENT_RE.match(s.text))
                       - 3 * (not title_ok(headline_of(s.text))))
            title = headline_of(lead.text, fallback=heading_of(lead))
            rest = sorted((s for s in pick if s is not lead and s.score >= point_floor), key=lambda s: s.pos)
            points = [point_of(s.text) for s in rest][:per]
            if _words(H.strip_end(lead.text)) - _words(title) >= 3:
                points = [point_of(lead.text), *points][:per]
            lab = re.match(r"^(?P<l>[^:«»()]{3,50}):\s+(?P<r>\S.+)$", H.strip_end(lead.text))
            if not points and lab and _words(lab.group("l")) <= 6:
                # «Профилирование данных: типы колонок, временная ось, …» — its label heads it, what it says is its line
                title, points = H.cap_first(lab.group("l").strip()), [point_of(H.cap_first(lab.group("r")))]
            if not points:
                carry = pick  # a title alone is no slide (it would be laid out as a section): it joins the next part
                continue
            used.extend(s.text for s in pick)
            out.append(DigestSlide(title=title, points=points))
        if len(out) >= max(min(MIN_SLIDES, n_text), n_text - 1):
            break
    if not out:
        return None
    for para, rows, before in tables:
        cap = headline_of(before) if before and _words(before) >= 3 else "Данные документа"
        out.append(DigestSlide(title=cap, table=rows[:12]))
    # the closing: what the document decides or asks, of the sentences no slide said
    asks = sorted((s for s in doc.sentences if _ASK_RE.search(s.text) and s.score >= 1.0 and fresh(s)), key=lambda s: -s.score)[:POINTS]
    if asks and len(out) + 2 <= max(size, len(out) + 2):
        asks_in_order = sorted(asks, key=lambda s: s.pos)
        title = headline_of(asks[0].text)
        points = [point_of(s.text) for s in asks_in_order if s is not asks[0]][:POINTS]
        if _words(H.strip_end(asks[0].text)) - _words(title) >= 3:
            points = [point_of(asks[0].text), *points][:POINTS]
        if not points:
            # the ask alone: the deck's main conclusions under it (its first slides' titles)
            points = [x.title for x in out[:POINTS] if x.title != title]
        out.append(DigestSlide(title=title, points=points))
        used.extend(s.text for s in asks)
    limit = size - 1
    if len(out) > limit:
        out = out[: limit - 1] + [out[-1]]
    return Digest(title=_cover_title(doc, title_hint), slides=out, by="rules", words=doc.words,
                  dropped=max(0, len(doc.sentences) - len(used)))


# ------------------------------------------------------------------ the model's digest


class DigestSlideAnswer(BaseModel):
    title: str = Field(description="the slide's conclusion: one full statement, at most 12 words")
    points: list[str] = Field(default_factory=list, description="2–3 facts, figures or decisions that support it")


class DigestAnswer(BaseModel):
    """Output of `document_digest`."""

    title: str = ""
    slides: list[DigestSlideAnswer] = Field(default_factory=list)


_MAGNITUDE_RE = re.compile(r"\s*(%|млн|млрд|тыс|трлн|₽|руб|долл|\$|€|ч\b|час|мин|сек|дн|нед|мес|лет|год|слайд|шт|чел|раз)", re.I)


def _figures(text: str) -> set[str]:
    """The text's figures, each with its unit when one follows it («5 млн», «5 мин», «12 %»): «5 млн ₽» is not the «5»
    of «5 минут»."""
    t = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?!\d))", "", text or "")
    out = set()
    for m in re.finditer(r"\d+(?:[.,]\d+)?", t):
        num = m.group(0).replace(",", ".")
        u = _MAGNITUDE_RE.match(t[m.end():m.end() + 8])
        out.add(f"{num} {u.group(1).lower()[:3]}" if u else num)
    return out


def _speech(line: str) -> bool:
    return bool(_FILLER_RE.search(line) or _GREETING_RE.search(line)) or _question(line)


def check_answer(ans: DigestAnswer, source: str, size: int) -> Optional[Digest]:
    """The model's slides with every line it may not keep taken out: a figure the document does not state, spoken
    filler, a question. None when fewer than three slides stay."""
    have = _figures(source)
    slides: list[DigestSlide] = []
    for s in ans.slides:
        pts = [" ".join(p.split()) for p in s.points if p and p.strip()]
        pts = [p for p in pts if not (_figures(p) - have) and not _speech(p) and _words(p) >= 3][:POINTS]
        title = " ".join((s.title or "").split())
        if not title or (_figures(title) - have) or _speech(title):
            if not pts:
                continue
            title = headline_of(pts[0])
            pts = pts[1:]
        if _words(title) > HEAD_WORDS + 4:
            title = headline_of(title)
        pts = [point_of(p) for p in pts]
        if any(_similar(title, x.title, 0.75) for x in slides):
            continue
        slides.append(DigestSlide(title=H.cap_first(H.strip_end(title)), points=pts))
    limit = size - 1
    if len(slides) > limit:
        slides = slides[: limit - 1] + [slides[-1]]
    if len(slides) < 3:
        return None
    title = " ".join((ans.title or "").split())
    if not title or (_figures(title) - have) or _FILE_NAME_RE.search(title):
        title = ""
    return Digest(title=H.strip_end(title), slides=slides, by="model")


def digest_with_model(text: str, size: int, skills: Any, providers: Any, *, language: str = "ru") -> Optional[Digest]:
    """The model's digest of the document (skill `document_digest`); None when the model is not there, fails or answers
    too little."""
    if skills is None or providers is None or not getattr(providers, "has", lambda _r: False)("llm"):
        return None
    body = _body(text)
    got = None
    for _ in range(2):  # (a model that answered one slide instead of the deck is asked once more)
        try:
            r = skills.run("document_digest", providers, {
                "document": body[:DOC_CHARS], "content_slides": max(1, size - 2), "head_words": HEAD_WORDS, "language": language,
            })
            ans: DigestAnswer = r.parsed
        except Exception as e:  # noqa: BLE001 - the rules' digest then
            log.warning("document_digest failed: %s", str(e)[:200])
            return None
        got = check_answer(ans, body, size)
        if got is not None:
            break
    if got is None:
        return None
    if not got.title:
        got.title = _cover_title(_read(text), None)
    return got


def digest(text: str, slides: Optional[int] = None, *, skills: Any = None, providers: Any = None, title_hint: Optional[str] = None,
           language: str = "ru") -> Optional[Digest]:
    """The deck of a long document: the model's digest when there is a model, else (or when it fails) the rules'."""
    size = deck_size(slides)
    got = digest_with_model(text, size, skills, providers, language=language)
    if got is not None:
        if title_hint and not _FILE_NAME_RE.search(title_hint):
            got.title = H.strip_end(title_hint)
        got.words = _read(text).words
        return got
    return digest_by_rules(text, slides, title_hint=title_hint)


def note(d: Digest) -> str:
    """The analyst's line in the agent's log."""
    from verstka.ru import ru_count

    how = ("модель сжала его в выводы, цифры и решения" if d.by == "model"
           else "взял из него содержательные предложения — цифры, решения, требования; разговорную речь и организационные реплики оставил за кадром")
    return (f"Аналитик: длинный документ ({ru_count(d.words, 'слово', 'слова', 'слов')}) — это материал, а не план слайдов: "
            f"{how}; колода — {ru_count(d.size, 'слайд', 'слайда', 'слайдов')}, заголовок каждого — вывод.")


# ------------------------------------------------------------------ a topic without a model


_SKIP_SECTION_RE = re.compile(
    r"^(?:примечани|литератур|ссылки|см\.?\s*также|источник|галере|библиограф|комментари|фильмограф|дискограф|награды и звания|"
    r"высказывани|цитат|миф|легенд|фильм|песн|коллекционир|в\s+культуре|в\s+искусстве|в\s+литературе|название|этимолог|"
    r"notes|references|see also|external links|further reading|bibliography|gallery|in popular culture|etymology)",
    re.I,
)
_WIKI_NOISE_RE = re.compile(r"\[\d{1,3}\]|\[источник не указан[^\]]*\]|\u0301")


def article_document(text: str, title: str, max_sections: int) -> str:
    """A Wikipedia article as a document with its sections as headings: the lead («Общие сведения») and its first
    sections of substance, the reference lists left out."""
    from verstka.planning.reference import sections

    lead, secs = sections(_WIKI_NOISE_RE.sub("", text or ""))
    # «Байкал (бур. Байгал далай) — озеро …»: the name in other languages is no part of the statement
    lead = re.sub(r"\s*\((?:[^()]*?\b[а-яa-z]{2,5}\.\s[^()]*)\)", "", lead, count=2)
    secs = [(h, b) for h, b in secs if not _SKIP_SECTION_RE.match(h.strip()) and _words(b) >= 25]
    out = [f"# {title}", "", f"## {LEAD_HEAD}", lead.strip()]
    keep = sorted(sorted(range(len(secs)), key=lambda i: -_words(secs[i][1]))[: max(2, max_sections - 1)])  # the richest, in order
    for h, b in (secs[i] for i in keep):
        out += ["", f"## {h.strip()}", b.strip()]
    return "\n".join(out)


def reference_digest(topic: str, slides: Optional[int] = None, *, lang: str = "ru", cache_dir: Any = None,
                     config: Optional[dict] = None) -> Optional[Digest]:
    """A topic («Сделай презентацию про озеро Байкал») without a model: its Wikipedia article, digested by the rules —
    a slide per section of substance, its title the section's best sentence, its lines the sentences with its facts.
    None when the article cannot be found or fetched (no network, Wikipedia off)."""
    from verstka.planning.reference import fetch_reference
    from verstka.planning.topic_writer import topic_subject
    from verstka.planning.writer import load_config

    cfg = config if config is not None else load_config()
    rcfg = cfg.get("reference") or {}
    if not rcfg.get("enabled", True):
        return None
    from verstka.knowledge.compose import request_subject

    subject = topic_subject(request_subject(topic) or topic) or topic
    # «что такое облачные вычисления и какие бывают модели обслуживания» → «облачные вычисления»: what the article is about
    core = re.sub(r"^(?:что\s+так(?:ое|ие)|кто\s+так(?:ой|ая|ие)|о\s+том,?\s+(?:что|как)|как\s+устроен\w*|зачем\s+нужн\w*)\s+", "", subject.strip(), flags=re.I)
    core = re.split(r",?\s+(?:и\s+)?(?:какие|какой|какая|как|зачем|почему|что|чем|где|когда)\s+", core, maxsplit=1)[0]
    subject = core.strip(" ,.") or subject
    from verstka.planning.brief_structure import _nominative

    nom = _nominative(subject) or subject
    nom = re.sub(r"^(\w+)ю(?=\s)", r"\1я", nom) if re.match(r"^\w+ию\s", nom) else nom  # «историю шоколада» → «история шоколада»
    title = H.cap_first(H.strip_end(" ".join(nom.split())))
    try:
        ref = fetch_reference([title], subject, lang=lang, contact=str(rcfg.get("contact") or ""), timeout_s=float(rcfg.get("timeout_s", 6)),
                              cache_dir=cache_dir, cache_days=float(rcfg.get("cache_days", 7)))
    except Exception:  # noqa: BLE001 - no reference
        log.warning("reference for a topic without a model failed", exc_info=True)
        return None
    page = ref.main if ref is not None else None
    if page is not None and not ({w.lower()[:5] for w in _STEM_RE.findall(page.title)} & {w.lower()[:5] for w in _STEM_RE.findall(subject)}):
        log.info("the article «%s» is not about «%s»", page.title, subject)
        return None  # an article about something else is no source of the deck
    return page_digest(page, slides, title if _words(title) <= 8 else None)


def page_digest(page: Any, slides: Optional[int], title: Optional[str] = None) -> Optional[Digest]:
    """The rules' digest of a fetched Wikipedia page (planning/reference.RefPage); None without its text."""
    if page is None or not getattr(page, "text", ""):
        return None
    size = deck_size(slides)
    d = digest_by_rules(article_document(page.text, page.title, max(3, size - 2)), slides, title_hint=title or page.title)
    if d is None:
        return None
    d.subtitle = f"По статье «{page.title}» из Википедии"
    d.source = {"title": page.title, "url": page.url}
    return d


def no_source_text(topic: str) -> str:
    """The honest deck of a topic nobody could write: no model, no article — the cover and what to do."""
    from verstka.planning.topic_writer import topic_subject

    subject = topic_subject(topic) or topic
    from verstka.planning.brief_structure import _nominative

    core = re.sub(r"^для\s+", "", subject)
    core = _nominative(core) or core
    core = re.sub(r"^(\w+(?:инг|ент|ект|ер|ор))а(?=\s)", r"\1", core)  # «онбординга новых сотрудников» → «онбординг новых сотрудников»
    core = re.sub(r"^(\w+ци)и(?=\s)", r"\1я", core)  # «адаптации персонала» → «адаптация персонала»
    title = H.cap_first(H.strip_end(core))[:120]
    # «…: первая неделя, кто есть кто, инструменты, как ставят цели и что считается успехом» — what the deck must tell
    tail = topic.split(":", 1)[1] if ":" in topic else ""
    parts = [H.cap_first(H.strip_end(x.strip())) for x in re.split(r",\s*|\s+и\s+(?=(?:как|что|кто|где|когда|зачем|почему)\b)", tail) if len(x.split()) >= 1 and x.strip()]
    out = (f"Слайд 1. Обложка\nНазвание: {title}\n\n"
           "Слайд 2. Текст презентации не написан: модель недоступна, статья по теме не найдена\n"
           "- Модель, которая пишет текст по теме, сейчас не отвечает.\n"
           "- Статью по теме в Википедии найти не удалось.\n"
           "- Добавьте свой текст, документ или базу знаний — колода соберётся из них.\n")
    if 2 <= len(parts) <= 8:
        out += "\nСлайд 3. Что должна раскрыть презентация\n" + "".join(f"- {x}.\n" for x in parts)
    return out
