"""Writer mode: the designer never adds a fact (gate 3 W3-1, W3-2, W3-6, W3-7, W3-11).

A written deck's slide is checked against the writer's text of that slide (the brief the agent read: «Слайд N. …»):

- every date, year, figure, name and rank of a timeline entry, a card, a dated line, a key figure's label, the
  headline and the takeaway occurs in ONE sentence of the slide's text together with the event it is attached to
  («1944 — США одержали победу в битве за Гуадалканал» where the sentence has no year took the year of the sentence
  before it: the entry is rebuilt from its own sentence, or loses the date);
- a timeline shows dates on every step (a step that lost its date turns the slide into «date — event» lines, a
  timeline of mostly undated steps into cards);
- a key figure's label is its sentence without the whole value phrase, at most six words, never a cut figure
  («К 2030 году в мире может быть 240» → «электромобилей может быть в мире к 2030 году»);
- a headline states no date, figure or rank its slide's sentences do not state together («Москвич 3е — первая
  серийная модель» over «одной из первых» → the working title), and its past-tense verb agrees with the gender the
  text gives the name («VK начал» where the text says «VK была основана» → «VK начала»);
- a takeaway is a sentence of the slide's text (or a faithful shortening of one) or nothing;
- «date — event» lines continue in lowercase after the dash («2023 — начата редомициляция»), names keep capitals;
- a short slide (two short lines on a slide of more sentences) shows the slide's sentences as cards, not a sparse list.

No model call; nothing here adds a word the slide's text does not have. `check_slide` mutates an OutlineSlide and
returns what it changed (for the agent's log)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from verstka.planning import heuristics as H
from verstka.schemas.common import PatternKind
from verstka.schemas.outline import NumberCallout, OutlineSlide, SlideItem

MAX_LABEL_WORDS = 6  # content words of a key figure's label
MAX_HEAD_WORDS = 13  # a sentence taken as a headline
MAX_LINE_WORDS = 20  # a sentence taken as a line or a card
DATED_SHARE = 0.8  # a timeline needs this share of dated steps to stay a time axis (every step, once checked)

# ------------------------------------------------------------------ words

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9+\-]*(?:\.[a-z]{2,4})?")
_STOP = frozenset(
    """и в во на с со к ко по о об обо от до из у за для при без через над под про а но или либо же ли бы не ни что
    чтобы как так там тут где когда если то тот та те это эти этот эта этого этой всё все весь вся всех всем мы вы они он
    она оно его её ее их им ими свой своя свое своё свои который которая которое которые которых также тоже ещё еще уже
    только лишь очень один одна одно одного одной одному одним одних после перед между среди каждый можно нужно будет
    будут было были был была есть быть этом том тем чем кто год года году годах годы годов гг г лет
    the a an of and or to in on for with by is are be as at from this that these those it its""".split()
)
_MONTH_STEMS = ("январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")
_MONTH_ALT = r"(?:январ[а-яё]*|феврал[а-яё]*|март[а-яё]*|апрел[а-яё]*|ма[йяе](?![а-яё])|июн[а-яё]*|июл[а-яё]*|август[а-яё]*|сентябр[а-яё]*|октябр[а-яё]*|ноябр[а-яё]*|декабр[а-яё]*)"
_MONTH_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
_MONTH_NOM = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
_YEAR_RE = re.compile(r"(?<![\d.,])(1\d{3}|20\d{2})(?![\d.,])")
_DAY_MONTH_RE = re.compile(rf"(?<![\d.,])(\d{{1,2}})\s+({_MONTH_ALT})(?![а-яё])", re.I)
_MONTH_WORD_RE = re.compile(rf"(?<![а-яёА-ЯЁ])({_MONTH_ALT})(?![а-яё])", re.I)
# a date phrase inside a sentence (with its preposition and «года»): «В 2010 году», «19 ноября 1942 года», «с августа
# 1942 года», «по февраль 1943 года», «В 1997–1998 годах», «в октябре», «В 1960-х годах», «По итогам января 2025 года»
_DATE_PHRASE_RE = re.compile(
    r"(?:(?<![\wё])(?:[ВвСсКк]|[Дд]о|[Пп]о|[Кк]\s+концу|[Пп]о\s+итогам)\s+)?"
    rf"(?:(?:\d{{1,2}}\s+)?{_MONTH_ALT}\s+)?"
    r"(?:1\d{3}|20\d{2})(?:\s*[–—-]\s*(?:1\d{3}|20\d{2}))?(?![\d.,])(?:-[а-я]{1,2})?"
    r"(?:\s+(?:годах|годов|годы|года|году|год|гг\.|г\.))?"
    rf"|(?:(?<![\wё])[ВвСс]\s+)(?:\d{{1,2}}\s+)?{_MONTH_ALT}(?![а-яё])"
    rf"|(?<![\d.,])\d{{1,2}}\s+{_MONTH_ALT}(?![а-яё])",
    re.I,
)
_RANK_RE = re.compile(
    r"(?<![\wё])(перв(?:ый|ая|ое|ые|ого|ой|ому|ым|ых|ую|ыми)|впервые|крупнейш\w*|сам(?:ый|ая|ое|ые|ого|ой|ым|ых|ую)\s+\w+|"
    r"единствен\w*|лучш\w*|наибол\w*|наимен\w*|рекордн\w*|больше\s+всего|меньше\s+всего)(?![\wё])",
    re.I,
)
_HEDGED_RANK_RE = re.compile(r"(?<![\wё])(?:одн\w*|один|в\s+числе)\s+(?:из\s+)?(?:самых\s+)?(перв\w*|крупнейш\w*|лучш\w*|лидер\w*|ведущ\w*)", re.I)
# an intensifier or an evaluation a takeaway may not add («активно развивается»)
_INTENSIFIER_RE = re.compile(
    r"(?<![\wё])(активн\w*|значительн\w*|стремительн\w*|быстр\w*|резк\w*|существенн\w*|успешн\w*|бурн\w*|огромн\w*|"
    r"важнейш\w*|решающ\w*|колоссальн\w*|масштабн\w*|впечатляющ\w*|выдающ\w*|уникальн\w*|доступн\w*|"
    r"популярн\w*|передов\w*|инновационн\w*|лидирующ\w*|эффективн\w*)(?![\wё])",
    re.I,
)
# how the text names one actor by different words («СССР» / «Советский Союз»)
_ALIASES = (
    ("ссср", "советск", "союз"),
    ("сша", "соедин", "америк", "штат"),
    ("рф", "росси"),
    ("великобр", "британ", "англи"),
    ("оон", "организац"),
    ("фрг", "германи"),
)
# a time told by the sentence before («В этот период», «в том же году», «Того же года»)
_RELATIVE_RE = re.compile(
    r"(?<![\wё])(?:(?:в|во)\s+)?(?:(?:этот|тот)\s+(?:же\s+)?период|(?:том|этом)\s+же\s+году|этом\s+году|того\s+же\s+года|"
    r"тогда\s+же|это\s+время|то\s+же\s+время|(?:том|этом)\s+же\s+месяце|того\s+же\s+месяца)(?![\wё])",
    re.I,
)
_SAME_MONTH_RE = re.compile(r"(?<![\wё])(?:в\s+)?(?:том|этом)\s+же\s+месяце|того\s+же\s+месяца", re.I)
_PREP = frozenset("в во на с со к ко по о об от до из у за для при без через над под про".split())


def _norm(w: str) -> str:
    return w.lower().replace("ё", "е")


def _is_month(w: str) -> bool:
    x = _norm(w)
    return bool(re.fullmatch(r"ма[йяе]", x)) or any(x.startswith(st) for st in _MONTH_STEMS if st != "ма")


def _month_of(w: str) -> int:
    x = _norm(w)
    if re.fullmatch(r"ма[йяе]", x):
        return 5
    return next((i for i, st in enumerate(_MONTH_STEMS, 1) if st != "ма" and x.startswith(st)), 0)


def _same_word(a: str, b: str) -> bool:
    """Two word forms of one word («смена» · «сменила», «Германия» · «Германии», «мира» · «мире»)."""
    a, b = _norm(a), _norm(b)
    if a == b:
        return True
    from verstka.planning.grounding import stem

    sa = stem(a)
    if len(sa) >= 3 and sa == stem(b):
        return True  # «Второй» · «Вторая»
    n = min(len(a), len(b))
    k = 0
    while k < n and a[k] == b[k]:
        k += 1
    if n <= 4:
        return k >= max(3, n - 1)
    return k >= min(5, n - 1)


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text or "")]


def _content(text: str) -> list[str]:
    """The content words of a text: no stop words, no months, no one- and two-letter words (a Latin or an upper-case
    name of two letters stays: «VK», «ИИ»)."""
    out = []
    for w in _words(text):
        lw = _norm(w)
        if lw in _STOP or _is_month(w) or re.match(r"^(?:тыс|млн|млрд|трлн|миллион|миллиард|тысяч|шт$|штук)", lw):
            continue
        if len(lw) < 3 and not (w.isupper() or re.match(r"[A-Za-z]", w)):
            continue
        out.append(w)
    return out


def _alias_hit(w: str, words: list[str]) -> bool:
    lw = _norm(w)
    for group in _ALIASES:
        if any(lw.startswith(g) for g in group):
            if any(_norm(x).startswith(g) for x in words for g in group):
                return True
    return False


def _has_word(w: str, words: list[str]) -> bool:
    return any(_same_word(w, x) for x in words) or _alias_hit(w, words)


def _has_name(w: str, words: list[str]) -> bool:
    """A name among the words, or its adjective («Япония» · «японской агрессии», «Германия» · «германские»)."""
    if _has_word(w, words):
        return True
    a = _norm(w)
    return len(a) >= 5 and any(len(x) >= 5 and _norm(x)[:4] == a[:4] for x in words)


def coverage(claim: str, sentence: str) -> float:
    """The share of the claim's content words the sentence has (word forms and the text's other names of an actor)."""
    cw = _content(claim)
    if not cw:
        return 1.0
    sw = _words(sentence)
    return sum(1 for w in cw if _has_word(w, sw)) / len(cw)


# ------------------------------------------------------------------ dates, figures, names, ranks


@dataclass
class _Dates:
    years: set = field(default_factory=set)
    months: set = field(default_factory=set)
    days: set = field(default_factory=set)  # (day, month)

    @property
    def any(self) -> bool:
        return bool(self.years or self.months or self.days)

    def within(self, other: "_Dates") -> bool:
        return self.years <= other.years and self.months <= other.months and self.days <= other.days


def dates_of(text: str) -> _Dates:
    d = _Dates()
    t = text or ""
    for m in _YEAR_RE.finditer(t):
        d.years.add(int(m.group(1)))
    for m in _DAY_MONTH_RE.finditer(t):
        mo = _month_of(m.group(2))
        if mo and 1 <= int(m.group(1)) <= 31:
            d.days.add((int(m.group(1)), mo))
            d.months.add(mo)
    for m in _MONTH_WORD_RE.finditer(t):
        w = m.group(1)
        if re.fullmatch(r"ма[йяе]", _norm(w)) and not re.search(r"(?:\d\s+|[ВвКкСс]\s+|[Дд]о\s+|[Пп]о\s+)$", t[: m.start()]):
            continue  # «Май» of a name, not a month
        mo = _month_of(w)
        if mo:
            d.months.add(mo)
    return d


def _values(text: str) -> list[float]:
    """The magnitudes of a text's figures that are not dates, years or clock times of a name («Восток-1»)."""
    from verstka.planning.grounding import _is_year, figures

    out = []
    t = text or ""
    for f in figures(t):
        if f.date is not None or _is_year(f) or not re.search(r"\d", t[f.start: f.end]):
            continue  # a date, a year, a count in words («тремя социальными сетями»: the slide's own list)
        out.append(f.mag)
    return out


def _same_value(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(a))


def _known_names(deck: str) -> set[str]:
    """The words the text writes with a capital inside a sentence (names: «Германией», «Советский»), lowercased."""
    out: set[str] = set()
    for line in (deck or "").splitlines():
        for sn in [p for x in (H.split_sentences(line) or [line]) for p in re.split(r"\s[—–]\s|:\s|^[—–-]\s", x)]:
            ws = re.findall(r"[«(„\"]?[A-Za-zА-Яа-яЁё][\w\-.+]*", sn)
            for i, w in enumerate(ws):
                core = w.lstrip("«(„\"")
                if i > 0 and core[:1].isupper() and not re.match(r"^(?:Слайд|Название|Подзаголовок)$", core):
                    out.add(_norm(core))
    return out


def names_of(text: str, known: set[str]) -> list[str]:
    """The names a claim states: «quoted» names, Latin words, upper-case abbreviations and capitalised words (the first
    word of a sentence only when the text writes it capitalised elsewhere too)."""
    t = text or ""
    out: list[str] = []
    for q in re.findall(r"«([^«»]{1,60})»", t):
        out.extend(w for w in _content(q) if len(w) >= 2)
    t2 = re.sub(r"«[^«»]*»", " ", t)
    starts = {0} | {m.end() for m in re.finditer(r"(?:[.!?:;—–]\s+|\(\s*)", t2)}
    for m in re.finditer(r"[A-Za-zА-Яа-яЁё][\w\-.+]*", t2):
        w = m.group(0).rstrip(".")
        if re.fullmatch(r"[IVXLC]+", w):
            continue  # «I квартал»: a number
        if re.match(r"[A-Za-z]", w):
            out.append(w)
            continue
        if not w[:1].isupper() or _is_month(w):
            continue
        if len(w) >= 2 and w.isupper():
            out.append(w)
            continue
        at_start = m.start() in starts or not t2[: m.start()].strip()
        if not at_start or any(_same_word(w, k) for k in known):
            out.append(w)
    return out


def ranks_of(text: str) -> list[str]:
    return [m.group(1) for m in _RANK_RE.finditer(text or "")]


def _rank_ok(rank: str, claim: str, sentence: str) -> bool:
    """The sentence states the rank the claim does, and does not hedge it («одной из первых» is not «первая»)."""
    stem_ = _norm(rank.split()[0])[:4]
    low = _norm(sentence)
    if stem_ == "само":  # «самый крупный» — the adjective after it carries the rank
        stem_ = _norm(rank.split()[-1])[:5]
    if not re.search(rf"(?<![а-яa-z]){re.escape(stem_)}", low):
        return False
    hedged = _HEDGED_RANK_RE.search(sentence or "")
    if hedged and _norm(hedged.group(1))[:4] == stem_[:4] and not _HEDGED_RANK_RE.search(claim or ""):
        return False
    return True


# ------------------------------------------------------------------ the slide's text


_SKIP_LINE_RE = re.compile(r"^(?:Нужна\s.*диаграмма|Укажи,\s+что\s+данные|Диаграмма\s*\([^)]*\)\s*:|Данные\s+приблизительные\.?$|Название:|Подзаголовок:|Тон\s+нейтральный|Слайд\s+\d)", re.I)


def _split(text: str) -> list[str]:
    try:
        from verstka.planning.writer import sentences_of

        return sentences_of(text)
    except Exception:  # noqa: BLE001 - the writer's splitter or the plain one
        return H.split_sentences(text or "") or ([text.strip()] if (text or "").strip() else [])


def slide_sentences(text: str) -> list[str]:
    """The sentences of a slide's writer text: its prose and its dated entries («— 1998 — …»), not its chart's data
    rows, the chart request or the caveat request."""
    out: list[str] = []
    data = False
    for line in (text or "").splitlines():
        t = line.strip()
        if not t or _SKIP_LINE_RE.match(t):
            continue
        if t.endswith(":"):
            data = not re.match(r"^Хронология:$", t)
            continue
        if re.match(r"^[—–-]\s", t):
            if not data:
                out.append(re.sub(r"^[—–-]\s*", "", t).rstrip(";."))
            continue
        data = False
        out.extend(_split(t))
    return [H.strip_end(x) for x in out if x and x.strip()]


@dataclass
class Source:
    """A slide's writer text as the checks read it."""

    sentences: list[str]
    dates: list[_Dates]
    deck: str = ""
    title: str = ""
    known: set = field(default_factory=set)
    genders: dict = field(default_factory=dict)
    topic: str = ""
    deck_sentences: Optional[list] = None
    before: list = field(default_factory=list)  # the deck's sentences before this slide's text (the last few)
    names: Optional[dict] = None  # the deck's names as subjects {nominative: gender} (clauses._nominative_forms)

    @classmethod
    def of(cls, text: str, deck: str = "", title: str = "", topic: str = "") -> "Source":
        sents = slide_sentences(text)
        ctx_years = dates_of(title).years  # «Доходы VK в 2019 году»: the slide's own year
        dates: list[_Dates] = []
        last: Optional[int] = None
        last_months: set = set()
        for s in sents:
            d = dates_of(s)
            if _SAME_MONTH_RE.search(s) and not d.months and last_months:
                d.months |= last_months  # «В том же месяце…»
            if d.months:
                last_months = set(d.months)
            if d.years:
                last = max(d.years)
            elif (d.days or d.months or _RELATIVE_RE.search(s)) and last is not None:
                # «3 сентября Великобритания…» after «1 сентября 1939 года…», «В этот период компания…» after «К 2019
                # году…»: the slide's year
                d.years.add(last)
            d.years |= ctx_years
            dates.append(d)
        whole = text if not deck else deck if text.strip() in deck else f"{deck}\n{text}"  # the slide's own text is the deck's
        at = whole.find(text.strip()[:80]) if text.strip() else -1
        before = slide_sentences(whole[:at])[-4:] if at > 0 else []
        return cls(sentences=sents, dates=dates, deck=whole, title=title, known=_known_names(whole), genders=entity_genders(whole), topic=topic, before=before)

    def name_forms(self) -> dict:
        if self.names is None:
            from verstka.planning.clauses import _nominative_forms

            self.names = _nominative_forms(self.deck)
        return self.names


def supports(claim: str, sentence: str, sdates: _Dates, known: set[str], need: float = 0.6, dates: bool = True, names: bool = True) -> bool:
    """ONE sentence states the claim: its dates (with the slide's year of a day written without one), its figures, its
    names and its ranks, and at least `need` of its content words."""
    if dates and not dates_of(claim).within(sdates):
        return False
    have = _values(sentence)
    if any(not any(_same_value(v, x) for x in have) for v in _values(claim)):
        return False
    sw = _words(sentence)
    if names and any(not _has_name(n, sw) for n in names_of(claim, known)):
        return False
    if any(not _rank_ok(r, claim, sentence) for r in ranks_of(claim)):
        return False
    return coverage(claim, sentence) >= need


def _supporting(claim: str, src: Source, need: float = 0.6, dates: bool = True, names: bool = True) -> Optional[int]:
    best: Optional[tuple[float, int]] = None
    for i, (s, d) in enumerate(zip(src.sentences, src.dates)):
        if supports(claim, s, d, src.known, need, dates, names):
            cv = coverage(claim, s)
            if best is None or cv > best[0]:
                best = (cv, i)
    return best[1] if best else None


def _event_sentence(event: str, src: Source, floor: float = 0.5, only: Optional[list[int]] = None) -> Optional[int]:
    """The sentence that tells the event (the most of its content words, its names), None when none tells it."""
    best: Optional[tuple[float, int]] = None
    ev_names = names_of(event, src.known)
    for i, s in enumerate(src.sentences):
        if only is not None and i not in only:
            continue
        cv = coverage(event, s)
        sw = _words(s)
        nm = sum(1 for n in ev_names if _has_word(n, sw)) / len(ev_names) if ev_names else 1.0
        score = cv + 0.5 * nm
        if cv >= floor and (nm >= 0.5 or not ev_names) and (best is None or score > best[0]):
            best = (score, i)
    return best[1] if best else None


# ------------------------------------------------------------------ rebuilding from a sentence

def _shorten(sentence: str) -> str:
    """The sentence as a headline reads it (no clock time, no time zone, no parentheses): _head_form."""
    return _head_form(sentence)


def trim(sentence: str, max_words: int) -> Optional[str]:
    """The sentence at most `max_words` long: as it is, or cut where a clause ends and the head says a whole thing
    (clauses.safe_cut — its own verb, no particle or governing word at its end, no contrast dropped: gate 4 G4-1); None
    when no cut is safe."""
    from verstka.planning.clauses import safe_cut

    return safe_cut(sentence, max_words)


def _fit_line(sentence: str, r: Optional["_Run"] = None) -> str:
    """A sentence as a line: whole up to 20 words (30 on a slide of three sentences or fewer: there is room), else cut
    where a clause ends, else whole — never a fragment (gate 4 G4-1)."""
    from verstka.planning.clauses import fit

    limit = 30 if r is not None and len(r.src.sentences) <= 3 else MAX_LINE_WORDS
    return fit(sentence, limit)


def date_title(sentence: str, sdates: _Dates) -> Optional[str]:
    """A timeline step's date for a sentence: «19 ноября 1942», «Октябрь 1939», «1997–1998», «1943»; None without."""
    if not sdates.years:
        if len(sdates.days) == 1:
            (day, mo), = sdates.days
            return f"{day} {_MONTH_GEN[mo - 1]}"
        return None
    years = sorted(sdates.years)
    if len(sdates.days) == 1 and len(years) == 1:
        (day, mo), = sdates.days
        return f"{day} {_MONTH_GEN[mo - 1]} {years[0]}"
    if len(sdates.months) == 1 and len(years) == 1 and not sdates.days:
        mo = next(iter(sdates.months))
        return f"{_MONTH_NOM[mo - 1]} {years[0]}"
    own = sorted(int(y) for y in _YEAR_RE.findall(sentence)) or years
    return f"{own[0]}–{own[-1]}" if own[0] != own[-1] else str(own[0])


def without_dates(sentence: str) -> str:
    """The sentence without its date phrases («В 2010 году компания была переименована…» → «Компания была
    переименована…»)."""
    s = _DATE_PHRASE_RE.sub(" ", sentence or "")
    s = _RELATIVE_RE.sub(" ", s)
    s = re.sub(r"\s+([,.;:])", r"\1", s)
    s = re.sub(r"^[\s,;:—–-]+", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = re.sub(r"^(?:[ВвКк]|[Сс])\s+(?=[,.]|$)", "", s)
    return H.cap_first(H.strip_end(s))


def event_text(sentence: str, max_words: int = MAX_LINE_WORDS) -> Optional[str]:
    t = without_dates(sentence)
    if len(t.split()) < 3:
        return None
    return trim(t, max_words)


# ------------------------------------------------------------------ lowercase after a date's dash

_VERBISH_RE = re.compile(r"(?:ла|ло|ли|ал|ил|ел|ыл|ул|ял|та|то|ты|на|но|ны|ет|ют|ит|ят|ся|сь|ть|ен|ан|ян)$")


def low_after_dash(rest: str, src: Source) -> str:
    """The event after «date — » starts in lowercase unless it starts with a name (the text writes it with a capital
    inside a sentence), an abbreviation, a Latin word or a quotation."""
    words = (rest or "").split()
    if not words:
        return rest
    first = words[0]
    core = first.strip("«»\"'()")
    if not core or not core[:1].isupper() or first[:1] in "«\"(" or (len(core) >= 2 and core.isupper()) or re.match(r"[A-Za-z]", core):
        return rest
    if any(_same_word(core, k) for k in src.known):
        return rest
    own = core.lower()[: max(3, len(core) - 2)]
    if _VERBISH_RE.search(_norm(core)) or re.search(rf"(?<![\wё]){re.escape(own)}", src.deck or ""):
        return rest[:1].lower() + rest[1:]
    return rest


# ------------------------------------------------------------------ gender of a name

# a name as a subject: at the start, after punctuation or «и / а / но» (not «убыток VK составил»: VK is not its subject)
_NAME_VERB_RE = re.compile(r"(?:^|(?<=[.!?:;,—–(«]\s)|(?<=[.!?:;,—–(«])|(?<=\sи\s)|(?<=\sа\s)|(?<=\sно\s)|(?<=году\s)|(?<=года\s))([A-Z][\w.+\-]*|[А-ЯЁ]{2,})\s+(?:[а-яё]+о\s+)?([а-яё]{2,}?(?:л|ла|ло|ли)(?:сь|ся)?)(?![\wё])", re.M)


def entity_genders(deck: str) -> dict[str, str]:
    """The grammatical gender the text gives a Latin or abbreviated name by its past-tense verbs: «VK была основана»,
    «VK изменила» → {"vk": "f"}. Majority; a tie gives nothing."""
    votes: dict[str, dict[str, int]] = {}
    for m in _NAME_VERB_RE.finditer(deck or ""):
        name, verb = _norm(m.group(1)), _norm(m.group(2))
        base = re.sub(r"(?:сь|ся)$", "", verb)
        g = "f" if base.endswith("ла") else "n" if base.endswith("ло") else "p" if base.endswith("ли") else "m" if base.endswith("л") else ""
        if g:
            votes.setdefault(name, {}).setdefault(g, 0)
            votes[name][g] += 1
    out = {}
    for name, v in votes.items():
        ranked = sorted(v.items(), key=lambda kv: -kv[1])
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            out[name] = ranked[0][0]
    return out


_DATE_STAL_RE = re.compile(rf"(?<![\wё])(\d{{1,2}}\s+{_MONTH_ALT})\s+(стал|был)(?=\s)", re.I)


def _date_neuter(text: str) -> str:
    """«12 апреля стал Днём космонавтики» → «12 апреля стало…»: a date as a subject is neuter."""
    return _DATE_STAL_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}о", text or "")


def agree_gender(text: str, genders: dict[str, str]) -> str:
    """Past-tense verbs right after a name in the gender the text gives it («VK начал работу» → «VK начала работу»)."""
    if not text or not genders:
        return text

    def fix(m: re.Match) -> str:
        name, verb = m.group(1), m.group(2)
        g = genders.get(_norm(name))
        if g not in ("m", "f"):
            return m.group(0)
        refl = re.search(r"(?:сь|ся)$", verb)
        base = verb[: refl.start()] if refl else verb
        if g == "f" and base.endswith("л") and not base.endswith("ла"):
            new = base + "а" + ("сь" if refl else "")
        elif g == "m" and base.endswith("ла"):
            new = base[:-1] + ("ся" if refl else "")
        else:
            return m.group(0)
        return m.group(0)[: m.start(2) - m.start(0)] + new + m.group(0)[m.end(2) - m.start(0):]

    return _NAME_VERB_RE.sub(fix, text)


# ------------------------------------------------------------------ key figures' labels

_HEDGE_WORD_RE = re.compile(r"(?:более|свыше|около|почти|примерно|менее|порядка|не\s+менее|не\s+более|всего|в\s+общей\s+сложности)\s*$", re.I)
_AUX_RE = re.compile(r"^(?:было|были|был|была|будет|будут|составил\w*|составля\w*|достиг\w*|равнял\w*|равн[аоы]?)$", re.I)
_UNIT_WORD_RE = re.compile(r"^(?:штук|шт\.?|единиц|ед\.?|раз|руб\w*|долл\w*|евро|₽|\$|€|%|процент\w*)$", re.I)
_LEAD_DATE_RE = re.compile(
    rf"^((?:[ВвКкСс]|[Пп]о\s+итогам|[Кк]\s+концу|[Нн]а\s+начало)\s+(?:(?:\d{{1,2}}\s+)?{_MONTH_ALT}\s+)?(?:1\d{{3}}|20\d{{2}})(?:-[а-я]{{1,2}})?(?:\s+(?:годах|года|году|год|г\.))?),?\s+",
)


def _label_words(label: str) -> int:
    return len([w for w in _content(label) if not _YEAR_RE.fullmatch(w)]) + len(_YEAR_RE.findall(label or ""))


_COPULA_RE = re.compile(r"^(?:составил\w*|составля\w*|достиг\w*|равнял\w*|равн[аоы]?|насчитывал\w*|превысил\w*)$", re.I)
_STOP_AFTER_RE = re.compile(r"^(?:и|а|но|или|что|как|который\w*|которая|которые|к|в|во|на|по|с|до|из|за|для|при|от|у)$", re.I)


def label_of(sentence: str, value: str, known: Optional[set] = None, year: Optional[int] = None) -> Optional[str]:
    """A key figure's label from its sentence: the clause of the figure without the whole value phrase (number, scale,
    unit, hedge), the counted noun first and the verb next to it, a leading date at the end, at most six content words,
    in lowercase (it continues the figure): «В 2024 году в России было зарегистрировано 59,6 тыс. электромобилей» →
    «электромобилей зарегистрировано в России в 2024 году»; «…совокупный доход компании составил 87,6 млрд рублей» →
    «совокупный доход компании в 2019 году»; «(80 % населения Земли)» → «населения Земли». Only these shapes: None for
    any other sentence («на территории 40 стран и вовлекала…»). `year`: the year a «в том же году» of it means."""
    from verstka.planning.grounding import _is_year, figures

    want = _values(value)
    if not want:
        return None
    fig = next((f for f in figures(sentence) if f.date is None and not _is_year(f) and _same_value(f.mag, want[0])), None)
    if fig is None:
        return None
    s = sentence
    if year:
        s = _RELATIVE_RE.sub(lambda m: f"в {year} году", s)
        fig = next((f for f in figures(s) if f.date is None and not _is_year(f) and _same_value(f.mag, want[0])), None)
        if fig is None:
            return None
    w0 = re.match(r"^([А-ЯЁ][а-яё]*)(?![\wё])", s)
    if w0 and not any(_same_word(w0.group(1), k) for k in (known or set())):
        s = s[:1].lower() + s[1:]  # «Во Второй мировой войне погибло…» → «…погибло во Второй мировой войне»
    # the clause of the figure
    bounds = [0] + [m.end() for m in re.finditer(r";\s+|,\s+(?:(?:а|но|однако|включая|в\s+том\s+числе|из\s+них)\s+)?|\(|\)|:\s+", s) if m.end() <= fig.start]
    start = max(bounds)
    ends = [m.start() for m in re.finditer(r";|,|\(|\)|\s[—–]\s(?!\d)", s) if m.start() >= fig.uend]
    end = min(ends) if ends else len(s)
    before = _HEDGE_WORD_RE.sub("", s[start: fig.start])
    after = [w.strip(".") for w in s[fig.uend: end].split() if w.strip(".")]
    while after and _UNIT_WORD_RE.match(after[0]):
        after = after[1:]
    counted: list[str] = []
    for w in after:
        if _STOP_AFTER_RE.match(w) or len(counted) >= 3 or (counted and w[:1].islower() and re.search(r"(?:[аеиыяу]л[аио]?|[аеиоуя]ли|ет|ит|ют|ят|ется|ются|лся|лась|лись)$", w)):
            break
        counted.append(w)
    rate = " ".join(after[len(counted): len(counted) + 2]).lower()
    if counted and re.fullmatch(r"(?:в|за)\s+(?:год|месяц|день|сутки|неделю|час)", rate):
        counted.append(rate)  # «около 3800 тонн урана в год»: the rate is what the figure counts (gate 4 G4-3)
    b = [w for w in re.sub(r"\s[—–-]\s*$", " ", before).split() if w not in ("—", "–", "-")]
    b = [w for w in b if not re.match(r"^(?:а|но|и|однако|что)$", w, re.I)]
    lead = ""
    joined = " ".join(b)
    m = _LEAD_DATE_RE.match(joined + " ")
    if m:
        lead = m.group(1)
        b = joined[m.end():].split()
    verbs: list[str] = []
    copula = False
    if b and re.match(r"^[а-яё]+$", b[-1]) and _COPULA_RE.match(b[-1]):
        copula = True
        b.pop()
    elif b and re.match(r"^[а-яё]+$", b[-1]) and (_VERBISH_RE.search(_norm(b[-1])) or _AUX_RE.match(b[-1])):
        verbs.insert(0, b.pop())
        while b and re.match(r"^(?:было|были|был|была|будет|будут|может|могут|могло|стало|стали)$", b[-1], re.I):
            verbs.insert(0, b.pop())
    elif b:
        return None  # a figure after a noun or a preposition («на территории 40 стран»): no label of this shape
    had_verb = bool(verbs)
    verbs = [v for v in verbs if not _AUX_RE.match(v)]
    rest = b
    if copula:
        if not rest or len(rest) > 5:
            return None
        words = rest + ([lead] if lead else [])  # «совокупный доход компании в 2019 году»
    elif had_verb:
        words = counted + verbs + rest + ([lead] if lead else [])  # «будет» alone: «электромобилей в мире к 2030 году»
        if not counted and not rest and verbs:
            # «а продано — 17,8 тыс. штук»: where and when from the sentence's own start
            m0 = _LEAD_DATE_RE.match(s)
            place = re.match(r"^\s*((?:в|во|на)\s+[А-ЯЁ][а-яё]+)", s[m0.end():]) if m0 else None
            if m0 and fig.start > m0.end():
                words = verbs + ([place.group(1)] if place else []) + [m0.group(1)]
    else:
        words = counted + ([lead] if lead else [])  # «(80 % населения Земли)»
    label = " ".join(x.strip(" ,;:—–") for x in words if x.strip(" ,;:—–"))
    label = re.sub(r"\s{2,}", " ", label).strip(" ,.;:—–")
    if not label or _label_words(label) > MAX_LABEL_WORDS or len(label.split()) < 2:
        return None
    if _values(label) or re.search(r"(?<![\wё])(?:и|в|во|на|с|к|по|о|от|до|из|за|для|при|а|но|включая|что)$", label, re.I):
        return None  # another figure, or a phrase cut off
    first = label.split()[0]
    if not (len(first) >= 2 and first.isupper()) and not any(_same_word(first, k) for k in (known or set())):
        label = label[:1].lower() + label[1:]
    label = re.sub(r"(?<=\s)(В|Во|К|По|На)(?=\s)", lambda m: m.group(1).lower(), label)
    return label


# what a figure measures: a label that names one of these must find it in the figure's sentence
_MEASURE_RE = re.compile(
    r"(?<![\wё])(прод|выручк|доход|прибыл|убыт|пользоват|аудитор|абонент|подписчик|сотрудник|работник|клиент|покупател|"
    r"экспорт|импорт|производ|выпуск|регистр|инвестиц|расход|затрат|стоимост|цен[аыуе]|населен|жител|потер|погиб|жертв|"
    r"участник|зрител|посетител|студент|учащ|парк|мобилиз|солдат|войск)",
    re.I,
)
_SOFT = ("one word",)


def bad_label(label: str, value: str, sentence: Optional[str], known: set[str], sdates: Optional[_Dates] = None) -> Optional[str]:
    """Why a key figure's label is not one: it repeats the figure, ends in a cut figure, has another figure, is longer
    than six words, gives a date or names a measure its sentence does not (hard), or it is one word (soft: rebuilt when
    its sentence gives a label, else kept)."""
    lb = H.strip_end(label or "")
    if not lb:
        return "empty"
    want = _values(value)
    have = _values(lb)
    if any(_same_value(v, x) for v in want for x in have):
        return "repeats the figure"
    if re.search(r"(?<![\wё])\d[\d\s]*(?:[.,]\d+)?\s*(?:тыс\.?|млн|млрд|трлн)?$", lb) and not _YEAR_RE.search(lb[-4:]):
        return "ends in a cut figure"
    if have:
        return "another figure in it"
    if _label_words(lb) > MAX_LABEL_WORDS:
        return "too long"
    if sentence:
        if not dates_of(lb).within(sdates if sdates is not None else dates_of(sentence)):
            return "a date its sentence does not give"
        low = _norm(sentence)
        if any(not re.search(rf"(?<![а-яa-z]){re.escape(_norm(m.group(1))[:4])}", low) for m in _MEASURE_RE.finditer(lb)):
            return "a measure its sentence does not count"
        noun = _counted_after(sentence, value)
        if noun and not any(_same_word(noun, w) for w in _words(lb)):
            return "loses what the figure counts"  # «54 · Россия экспортирует ядерные технологии» of «в 54 страны»
        rate = _rate_after(sentence, value)
        if rate and not re.search(r"(?<![\wё])(?:год|месяц|день|сутки|неделю|час|ежегодно|ежемесячно)", lb, re.I):
            return "loses the rate its sentence gives"
    if re.search(r"(?<![\wё])(?:кг|см|км|м|т|ч|мин|г)$", lb) or re.match(r"^[А-ЯЁ][а-яё]+\s+(?:кг|см|км|м|т|ч|мин)$", lb):
        return "a unit without its noun"  # «Вес кг» (gate 4 G4-3)
    if len(lb.split()) < 2:
        return "one word"
    return None


def _counted_after(sentence: str, value: str) -> Optional[str]:
    """The noun the figure counts, written right after it («в 54 страны» → «страны»); None for a unit, a scale word, a
    preposition or nothing."""
    from verstka.planning.grounding import _is_year, figures

    want = _values(value)
    f = next((f for f in figures(sentence or "") if want and f.date is None and not _is_year(f) and _same_value(f.mag, want[0])), None)
    if f is None:
        return None
    m = re.match(r"\s*([а-яё]{3,})", sentence[f.uend:])
    if not m:
        return None
    w = m.group(1)
    if _UNIT_WORD_RE.match(w) or _STOP_AFTER_RE.match(w) or re.match(r"^(?:тыс|млн|млрд|трлн|миллион|миллиард|тысяч|процент|раз|лет|год|года)", w):
        return None
    return w


def _rate_after(sentence: str, value: str) -> Optional[str]:
    """«около 3800 тонн природного урана в год»: the rate the sentence gives the figure, within five words after it."""
    from verstka.planning.grounding import _is_year, figures

    want = _values(value)
    f = next((f for f in figures(sentence or "") if want and f.date is None and not _is_year(f) and _same_value(f.mag, want[0])), None)
    if f is None:
        return None
    tail = " ".join(sentence[f.uend:].split()[:6])
    m = re.search(r"(?<![\wё])(?:в|за)\s+(год|месяц|день|сутки|неделю)(?![\wё])|ежегодно|ежемесячно", tail, re.I)
    return m.group(0) if m else None


# ------------------------------------------------------------------ the checks


@dataclass
class _Run:
    s: OutlineSlide
    src: Source
    changes: list[str]
    key: str

    def say(self, what: str) -> None:
        self.changes.append(f"slide {self.key}: {what}")


def _date_only(title: str) -> bool:
    """The title is a date («1944», «Февраль 1945», «1 сентября 1939», «2010 год», «1942–1943 гг.»)."""
    t = _DATE_PHRASE_RE.sub(" ", title or "")
    return dates_of(title).any and not re.sub(r"[\s,.;:—–()-]|год\w*|гг?\.?", "", t)


def _is_dated(title: str) -> bool:
    return dates_of(title or "").any


def _checkable(claim: str, known: set[str]) -> bool:
    return bool(dates_of(claim).any or _values(claim) or ranks_of(claim) or names_of(claim, known))


def _fix_entry(date: str, event: str, r: _Run) -> tuple[Optional[str], Optional[str]]:
    """A dated entry («date», «event»): as it is when ONE sentence states both; rebuilt from the sentence that tells the
    event (its own date, or none); (None, None) when no sentence tells the event."""
    src = r.src
    parts = [x for x in _split(event) if x.strip()]
    if len(parts) > 1:
        # an entry of several sentences: the first carries the date, each other one stays when the text tells it
        d0, e0 = _fix_entry(date, H.strip_end(parts[0]), r)
        if e0 is None:
            return None, None
        rest = [H.strip_end(x) for x in parts[1:] if _supporting(x, src, need=0.6, dates=False) is not None or _supported_with_antecedent(x, src, dates=False)]
        return d0, ". ".join([e0, *rest])
    claim = f"{date} — {event}"
    if _supporting(claim, src, need=0.6) is not None or _supported_with_antecedent(claim, src):
        return date, event
    i = _event_sentence(event, src)
    if i is None:
        return None, None
    sent, sd = src.sentences[i], src.dates[i]
    new_date = date if dates_of(date).any and dates_of(date).within(sd) else date_title(sent, sd)
    keep_event = (supports(event, sent, sd, src.known, 0.6, dates=False) or _supported_with_antecedent(event, src, i, dates=False)) and not dates_of(event).any
    if keep_event and not new_date and _VERB_FIRST_RE.match(event):
        keep_event = False  # «расширила портфель…» without its date has no subject: the sentence tells it
    new_event = event if keep_event else event_text(sent)
    if new_event is None or _orphan(new_event):
        return (None, None) if new_event is None or not keep_event else (new_date, event)
    return new_date, new_event


_VERB_FIRST_RE = re.compile(r"^[а-яё]+(?:ла|ло|ли|ал|ил|ел|ыл|ул|ял|ет|ют|ит|ят|лась|лось|лись|лся)\s", re.I)
_GENERIC_SUBJECT_RE = re.compile(r"(?<![\wё])(?:он|она|оно|они|его|её|ее|их|ему|ей|им|страна|страны|стране|компания|компании|государство|корабль|сервис)(?![\wё])", re.I)


def _supported_with_antecedent(claim: str, src: Source, only: Optional[int] = None, dates: bool = True) -> bool:
    """ONE sentence states the claim but for a name the sentence refers to by a pronoun or a general noun («Страна
    была разделена…» after «…вторжение в Польшу»): the name is in a sentence before it on the slide."""
    idx = [only] if only is not None else range(len(src.sentences))
    for i in idx:
        sn, sd = src.sentences[i], src.dates[i]
        if not _GENERIC_SUBJECT_RE.search(sn) or not supports(claim, sn, sd, src.known, 0.6, dates=dates, names=False):
            continue
        sw = _words(sn)
        before = _words(" ".join(src.sentences[:i]) + " " + src.topic)  # «В стране…» of a deck about Russia
        if all(_has_name(n, sw) or _has_name(n, before) for n in names_of(claim, src.known)):
            return True
    return False


def _check_items(r: _Run) -> None:
    s, c, src = r.s, r.s.content, r.src
    if not c.items or s.kind not in (PatternKind.timeline, PatternKind.cards, PatternKind.process, PatternKind.team):
        return
    out: list[SlideItem] = []
    changed = []
    for it in c.items:
        title, text = H.strip_end(it.title or ""), H.strip_end(it.text or "")
        if _date_only(title) and text:
            d, e = _fix_entry(title, text, r)
            if e is None:
                changed.append(f"«{title} — {text[:50]}» is not in the slide's text, dropped")
                continue
            if d != title or e != text:
                changed.append(f"«{title} — {text[:50]}» → «{(d + ' — ') if d else ''}{e[:50]}»")
            new = it.model_copy(update={"title": d or e, "text": H.cap_first(e) if d else ""})
            out.append(new)
            continue
        claim = f"{title} {text}".strip()
        ma = _LEAD_ADV_RE.match(f"{title} — {text}") if text and text[:1].islower() and not dates_of(title).any else None
        if ma and any(_norm(x).startswith(_norm(title)) and coverage(claim, x) >= 0.8 for x in src.sentences):
            # «После капитуляции Германии» · «некоторые части вермахта…»: one sentence cut in two
            changed.append(f"«{title} | {text[:40]}» → «{claim[:60]}»")
            out.append(it.model_copy(update={"title": claim, "text": ""}))
            continue
        if not _checkable(claim, src.known) or _supporting(claim, src, need=0.5) is not None or _supported_with_antecedent(claim, src):
            out.append(it)
            continue
        if not (dates_of(claim).any or _values(claim) or ranks_of(claim)):
            # names only («ВКонтакте» · социальная сеть): the names and the words on the slide, not one sentence
            slide_words = _words(" ".join(src.sentences))
            if all(_has_name(n, slide_words) for n in names_of(claim, src.known)) and coverage(claim, " ".join(src.sentences)) >= 0.5:
                out.append(it)
                continue
        if dates_of(claim).years:
            d, e = _fix_entry(" ".join(sorted({str(y) for y in dates_of(claim).years})), without_dates(claim), r)
            if e is None:
                changed.append(f"«{claim[:60]}» is not in the slide's text, dropped")
                continue
            new = it.model_copy(update={"title": d or e, "text": H.cap_first(e) if d else ""}) if (s.kind == PatternKind.timeline or _date_only(title)) else it.model_copy(update={"title": (f"{d} — {low_after_dash(e, src)}" if d else e), "text": ""})
            changed.append(f"«{claim[:60]}» → «{(new.title + ' ' + new.text).strip()[:60]}»")
            out.append(new)
            continue
        i = _event_sentence(claim, src)
        if i is None:
            changed.append(f"«{claim[:60]}» is not in the slide's text, dropped")
            continue
        line = _fit_line(src.sentences[i], r)
        if line is None:
            changed.append(f"«{claim[:60]}» is not what its sentence says, dropped")
            continue
        changed.append(f"«{claim[:60]}» → its sentence «{line[:60]}»")
        out.append(it.model_copy(update={"title": line, "text": "", "number": None}))
    # one entry per sentence
    seen: list[str] = []
    uniq = []
    for it in out:
        k = _norm(f"{it.title} {it.text}")
        if any(coverage(k, x) >= 0.9 and coverage(x, k) >= 0.9 for x in seen):
            continue
        seen.append(k)
        uniq.append(it)
    if changed:
        c.items = uniq
        r.say("entries checked against the text: " + "; ".join(changed))
    for it in c.items:
        if _date_only(it.title or "") and it.text and it.text[:1].islower():
            it.text = H.cap_first(it.text)


def _timeline_form(r: _Run) -> None:
    """A timeline has a date on every step: a few undated steps make «date — event» lines, mostly undated ones cards."""
    s, c = r.s, r.s.content
    if s.kind != PatternKind.timeline or not c.items:
        return
    dated = [it for it in c.items if _date_only(it.title or "") or _is_dated(it.title or "")]
    if len(dated) == len(c.items) and len(c.items) >= 2:
        return
    share = len(dated) / len(c.items)
    if share >= 0.5 and len(c.items) >= 2:
        lines = []
        for it in c.items:
            t, x = H.strip_end(it.title or ""), H.strip_end(it.text or "")
            if _is_dated(t) and x:
                lines.append(f"{t} — {low_after_dash(x, r.src)}")
            else:
                lines.append(H.cap_first(x if not t else f"{t}{': ' + x if x else ''}"))
        c.bullets = [x for x in lines if x][:6] + [b for b in c.bullets if b not in lines]
        c.items = []
        s.kind = PatternKind.bullets
        r.say(f"a timeline with {len(c.items) or len(lines) - len(dated)} undated step(s) → «date — event» lines")
    else:
        s.kind = PatternKind.cards if 2 <= len(c.items) <= 6 else PatternKind.bullets
        if s.kind == PatternKind.bullets:
            c.bullets = [H.strip_end(f"{it.title} — {it.text}" if it.text else it.title) for it in c.items][:6]
            c.items = []
        r.say(f"a timeline of undated steps → {s.kind.value}")


_DATE_ATOM = rf"(?:(?:\d{{1,2}}\s+)?{_MONTH_ALT}\s+)?(?:1\d{{3}}|20\d{{2}})(?![\d.,])(?:\s+(?:год[ау]?|г\.))?|\d{{1,2}}\s+{_MONTH_ALT}(?![а-яё])|{_MONTH_ALT}(?![а-яё])"
_LINE_DATE_RE = re.compile(rf"^((?:{_DATE_ATOM})(?:\s*[—–-]\s*(?:{_DATE_ATOM}))?)\s*[—–:]\s+(.+)$", re.I)
_LEAD_ADV_RE = re.compile(r"^((?:После|До|Во\s+время|В\s+ходе|В\s+результате|С|В|Во|На|К|По|При)\s+[^—–:]{2,40}?)\s+[—–]\s+(.+)$")


_PRED_FIRST_RE = re.compile(r"^([А-ЯЁ][а-яё]+(?:ют|ят|ет|ит|ут|ал|ил|ел|ла|ло|ли|лся|лась|лись))\s")


def _fragment_of(line: str, src: Source) -> Optional[str]:
    """A line that is the second half of a sentence cut at «, но / , а / и» and starts with its verb: the whole sentence
    («» when too long for a line); None when the line is not such a fragment."""
    m = _PRED_FIRST_RE.match(line or "")
    if not m:
        return None
    verb = m.group(1).lower()
    for sn in src.sentences:
        k = re.search(rf"(?:,\s+(?:но|а|однако)|\s+и)\s+{re.escape(verb)}(?![\wё])", sn, re.I)
        if k and coverage(line, sn[k.start():]) >= 0.7:
            return _fit_line(sn)
    return None


def _check_lines(r: _Run) -> None:
    """The slide's lines: a «date — event» line is checked like a timeline step; a line that states a date, a figure, a
    name or a rank no ONE sentence states becomes the sentence that tells it (or goes); «X — y» cut out of a sentence
    («После капитуляции Германии — некоторые части…») is the sentence again; lowercase after a date's dash."""
    c, src = r.s.content, r.src
    for attr in ("bullets", "paragraphs"):
        lines = list(getattr(c, attr))
        if not lines:
            continue
        out: list[str] = []
        changed = []
        for ln in lines:
            b = H.strip_end(ln)
            parts = [H.strip_end(x) for x in _split(b) if x.strip()]
            if len(parts) >= 2 and all(any(coverage(x, sn) >= 0.8 and coverage(sn, x) >= 0.8 for sn in src.sentences) for x in parts):
                out.append(ln)  # sentences of the text joined on one line (a line and the one that leans on it)
                continue
            m = _LINE_DATE_RE.match(b)
            if m and re.fullmatch(r"\d{4}", m.group(1).strip()) and any(float(m.group(1)) in _values(x) for x in src.sentences):
                m = None  # «1213 — Кораблей США»: a figure, not a year
            if m and dates_of(m.group(1)).years and len(m.group(2).split()) >= 2:
                d, e = _fix_entry(m.group(1).strip(), m.group(2).strip(), r)
                if e is None:
                    changed.append(f"«{b[:60]}» dropped")
                    continue
                sep = ":" if re.search(r"\s[—–]\s", e) else " —"
                new = f"{d}{sep} {low_after_dash(e, src)}" if d else H.cap_first(e)
                if new != b:
                    changed.append(f"«{b[:50]}» → «{new[:50]}»")
                out.append(new)
                continue
            ma = _LEAD_ADV_RE.match(b)
            if ma and not dates_of(ma.group(1)).any:
                joined = f"{ma.group(1)} {ma.group(2)}"
                if any(_norm(x).startswith(_norm(ma.group(1))) and coverage(joined, x) >= 0.8 for x in src.sentences):
                    changed.append(f"«{b[:50]}» → «{joined[:50]}»")
                    out.append(joined)
                    continue
            frag = _fragment_of(b, src)
            if frag is not None:
                # «Имеют меньшие расходы…» cut after «, но» of «Электромобили … отличаются …, но имеют …»: no subject
                changed.append(f"«{b[:50]}» has no subject → " + (f"its sentence «{frag[:50]}»" if frag else "dropped"))
                if frag:
                    out.append(frag)
                continue
            ev = [m.group(1) for m in _INTENSIFIER_RE.finditer(b) if not re.search(rf"(?<![а-яё]){re.escape(_norm(m.group(1))[:6])}", _norm(" ".join(src.sentences)))]
            if ev:
                # «…— доступные модели»: an evaluation the text does not give — the sentence the line shortens
                i = _event_sentence(re.sub("|".join(map(re.escape, ev)), " ", b), src)
                line = _fit_line(src.sentences[i], r) if i is not None else None
                changed.append(f"«{b[:50]}» evaluates ({', '.join(ev)}) → " + (f"its sentence «{line[:50]}»" if line else "dropped"))
                if line:
                    out.append(line)
                continue
            if _checkable(b, src.known) and _supporting(b, src, need=0.5) is None and not _supported_with_antecedent(b, src) and (dates_of(b).any or _values(b) or ranks_of(b)):
                figs = _values(b)
                with_figs = [k for k, x in enumerate(src.sentences) if all(any(_same_value(v, y) for y in _values(x)) for v in figs)]
                i = _event_sentence(b, src, only=with_figs)
                if i is None and figs and with_figs:
                    i = max(with_figs, key=lambda k: coverage(b, src.sentences[k]))  # the figure's own sentence tells it
                line = _fit_line(src.sentences[i], r) if i is not None else None
                if line is None:
                    changed.append(f"«{b[:60]}» is not in the slide's text, dropped")
                    continue
                changed.append(f"«{b[:50]}» → its sentence «{line[:50]}»")
                out.append(line)
                continue
            out.append(b if b != H.strip_end(ln) else ln)
        # no two lines of one sentence, no line another one says in full
        uniq: list[str] = []
        for k, x in enumerate(out):
            if any(coverage(x, y) >= 0.9 and coverage(y, x) >= 0.9 for y in uniq):
                continue
            if len(_content(x)) >= 3 and any(j != k and len(y.split()) > len(x.split()) and coverage(x, y) >= 0.9 for j, y in enumerate(out)):
                continue
            uniq.append(x)
        if changed or len(uniq) != len(lines):
            setattr(c, attr, uniq)
            if changed:
                r.say("lines checked against the text: " + "; ".join(changed))


def _chart_rank_ok(claim: str, s: OutlineSlide) -> bool:
    """A «больше всего / крупнейший / лидер» claim about the chart's largest category."""
    ch = s.content.chart
    if ch is None or not ch.categories or not ch.series or not ch.series[0].values:
        return False
    vals = ch.series[0].values
    top = ch.categories[max(range(len(vals)), key=lambda i: vals[i])]
    return coverage(top, claim) >= 0.5 and bool(re.search(r"больше\s+всего|крупнейш|наибол|лидер|основн|главн", claim, re.I))


# summary words a headline may use for what its slide lists («Ключевые события 1944–1945 годов»)
_GENERIC_RE = re.compile(r"^(?:ключев|основн|главн|важн|событи|дат[аыу]?$|даты|этап|факт|итог|хронолог|период|момент|ход$|списк)", re.I)


def _head_words(text: str, topic: list[str]) -> str:
    """A headline without its summary words and the deck's topic («Вторая мировая война»), for the coverage."""
    out = []
    for w in re.split(r"(\s+)", text or ""):
        core = w.strip("«»,.:;()—–")
        if core and (_GENERIC_RE.match(core) or any(_same_word(core, t) for t in topic)):
            continue
        out.append(w)
    return "".join(out)


def _check_headline(r: _Run) -> None:
    """The headline states no date, figure, rank or name the text does not: a full date or a figure in ONE sentence of
    its slide that tells what the headline attaches to it (several figures: their sentences together); a year in a
    sentence of the slide, the rest of the headline in that sentence or on the slide; a rank in a sentence of the
    deck, unhedged; names in the deck's text. Else the sentence of that date or figure (short enough for a headline),
    or the slide's working title. The past-tense verb after a name in the gender the text gives it."""
    s, src = r.s, r.src
    h = H.strip_end(s.headline or "")
    if not h:
        return
    new_h = _date_neuter(agree_gender(h, src.genders))
    if new_h != h:
        r.say(f"the headline «{h}» in the gender the text gives the name → «{new_h}»")
        s.headline = h = new_h
    topic_words = _content(src.topic)
    claim = _head_words(h, topic_words)
    d = dates_of(h)
    figs = _values(h)
    chart_rank = bool(ranks_of(h)) and _chart_rank_ok(h, s)
    rks = [] if chart_rank else ranks_of(h)
    h_cov = re.sub(r"больше\s+всего|меньше\s+всего|крупнейш\w*|наибол\w*", " ", claim, flags=re.I) if chart_rank else claim
    slide_text = " ".join(src.sentences) + " " + src.title
    deck_words = _words(src.deck)
    bad = [n for n in names_of(_head_words(h, topic_words), src.known) if not _has_name(n, deck_words)]
    why = None
    by_sentence = False
    if bad:
        why = f"names what the text does not ({', '.join(bad[:3])})"
    elif rks and not any(all(_rank_ok(x, h, sn) for x in rks) and coverage(re.sub(_DATE_PHRASE_RE, " ", h_cov), sn) >= 0.4 for sn in _split_deck(src)):
        why = "states a rank the text does not (or only hedged)"
    elif d.days or figs:
        by_sentence = True
        # the rank was checked above on the deck's sentences: here the date or the figure with its own event
        plain = re.sub(r"(?<![\wё])(?:перв\w*|впервые|крупнейш\w*|единствен\w*|лучш\w*|наибол\w*|наимен\w*|рекордн\w*)", " ", h_cov, flags=re.I)
        one = any(supports(plain, sn, sd, src.known, 0.5, names=False) for sn, sd in zip(src.sentences, src.dates))
        if not one:
            hits = [i for i, sn in enumerate(src.sentences) if any(any(_same_value(v, x) for x in _values(sn)) for v in figs) or (d.days & src.dates[i].days)]
            union = " ".join(src.sentences[i] for i in hits)
            u_dates = _Dates(set().union(*[src.dates[i].years for i in hits]) if hits else set(), set().union(*[src.dates[i].months for i in hits]) if hits else set(), set().union(*[src.dates[i].days for i in hits]) if hits else set())
            together = len(figs) + len(d.days) >= 2 and supports(h_cov, union, u_dates, src.known, 0.6, names=False)
            if not together:
                why = "states a date or a figure no sentence of its slide states with it"
    elif d.years:
        years = set().union(*[x.years for x in src.dates]) if src.dates else set()
        span = re.search(r"(?:1\d{3}|20\d{2})\s*[–—-]\s*(?:1\d{3}|20\d{2})", h)
        if span:
            if not years or not (min(years) <= min(d.years) and max(d.years) <= max(years)):
                why = "a span of years its slide does not cover"
        else:
            by_sentence = True
            missing = [y for y in d.years if not any(y in x.years for x in src.dates)]
            with_year = [i for i, x in enumerate(src.dates) if d.years & x.years]
            if missing:
                why = f"a year its slide does not give ({', '.join(map(str, missing))})"
            elif not any(coverage(h_cov, src.sentences[i]) >= 0.5 for i in with_year) and coverage(h_cov, slide_text) < (0.8 if len(d.years) == 1 else 0.6):
                why = "puts a year to what its sentence does not tell"
    if why is None:
        return
    new = None
    if by_sentence or rks:
        want = dates_of(h)
        cands = []
        for i, (sn, sd) in enumerate(zip(src.sentences, src.dates)):
            if not want.within(sd) or (figs and not any(any(_same_value(v, x) for x in _values(sn)) for v in figs)):
                continue
            cands.append((coverage(h, sn), i))
        shown = [*s.content.bullets, *s.content.paragraphs, *(f"{it.title} {it.text}" for it in s.content.items)]
        ok = []
        for _, i in sorted(cands, reverse=True):
            t = trim(src.sentences[i], MAX_HEAD_WORDS) or trim(_shorten(src.sentences[i]), MAX_HEAD_WORDS)
            if t and not ranks_of(t) and not _orphan(t):
                ok.append(t)
        # a sentence the slide does not show as a line, else the first one (its line then goes: the headline tells it)
        new = next((t for t in ok if not any(coverage(t, x) >= 0.8 and coverage(x, t) >= 0.6 for x in shown)), ok[0] if ok else None)
        if new is not None:
            c = s.content
            c.bullets = [x for x in c.bullets if not (coverage(x, new) >= 0.8 and coverage(new, x) >= 0.6)] if len(c.bullets) > 2 else c.bullets
            c.items = [it for it in c.items if not (coverage(f"{it.title} {it.text}", new) >= 0.8 and coverage(new, f"{it.title} {it.text}") >= 0.6)] if len(c.items) > 3 else c.items
    back = None
    if new is None:
        new = H.strip_end(src.title or "")
        # G4-2: the sentence the rejected headline told goes back onto the slide, as its first body line
        k = _event_sentence(h, src)
        if k is not None:
            from verstka.planning.clauses import fit

            back = _fit_line(src.sentences[k], r)
    if new and new != h:
        r.say(f"the headline «{h}» {why} → «{new}»")
        s.headline = new
        c = s.content
        shown = [*c.bullets, *c.paragraphs, *(f"{it.title} {it.text}" for it in c.items)]
        if back and not any(coverage(back, x) >= 0.8 for x in shown if x.strip()):
            _body_insert(r, back)
            r.say(f"the sentence of the rejected headline back as the first line «{back[:60]}»")


def _split_deck(src: Source) -> list[str]:
    if src.deck_sentences is None:
        src.deck_sentences = slide_sentences(src.deck)
    return src.deck_sentences


def _check_takeaway(r: _Run) -> None:
    s, src = r.s, r.src
    t = H.strip_end(s.takeaway or "")
    if not t:
        return
    t2 = agree_gender(t, src.genders)
    i = _supporting(t2, src, need=0.75)
    new_intens = [m.group(1) for m in _INTENSIFIER_RE.finditer(t2) if i is None or not re.search(rf"(?<![а-яё]){re.escape(_norm(m.group(1))[:5])}", _norm(src.sentences[i]))]
    if i is not None and not new_intens:
        if t2 != t:
            s.takeaway = t2
        return
    # the sentence of the slide the takeaway meant, when the slide does not show it yet (a sentence of the text, or none)
    c = s.content
    shown = [s.headline or "", *c.bullets, *c.paragraphs, *(f"{it.title} {it.text}" for it in c.items), *(f"{n.value} {n.label}" for n in c.numbers)]
    best = None
    for k, sn in enumerate(src.sentences):
        cand = trim(sn, 16)
        if not cand or _orphan(cand) or coverage(t2, sn) < 0.6 or any(coverage(cand, x) >= 0.6 or coverage(x, cand) >= 0.6 for x in shown if x.strip()):
            continue
        if not dates_of(t2).within(src.dates[k]) or any(not any(_same_value(v, y) for y in _values(sn)) for v in _values(t2)):
            continue  # the takeaway's date or figure is another sentence's
        if _INTENSIFIER_RE.search(cand) and not _INTENSIFIER_RE.search(t2):
            continue
        if best is None or coverage(t2, sn) > best[0]:
            best = (coverage(t2, sn), cand)
    new = best[1] if best else None
    r.say(f"the takeaway «{t[:70]}» is not a sentence of the slide's text → " + (f"its sentence «{new[:60]}»" if new else "dropped"))
    s.takeaway = new


def _hedge_before(sentence: str, value: str) -> Optional[str]:
    """The hedge the sentence writes right before the figure («более 70 миллионов» → «более»)."""
    from verstka.planning.grounding import _is_year, figures

    want = _values(value)
    if not want:
        return None
    f = next((f for f in figures(sentence) if f.date is None and not _is_year(f) and _same_value(f.mag, want[0])), None)
    if f is None:
        return None
    from verstka.planning.clauses import hedge_of

    return hedge_of(sentence, f.start)  # «около 3800», «более 70 млн» (gate 4 G4-3: «около» too)


def _not_a_figure(sentence: str, value: str) -> Optional[str]:
    """Why the value, as its sentence writes it, is not a key figure: «a time of day», «a project or model number», «a
    bound of a requirement», «a figure of a requirements list»; None for a figure."""
    from verstka.planning.clauses import figure_kind
    from verstka.planning.grounding import _is_year, figures

    want = _values(value)
    if not want:
        return _clock_value(value)
    f = next((f for f in figures(sentence) if f.date is None and not _is_year(f) and _same_value(f.mag, want[0])), None)
    if f is None:
        return None
    kind = figure_kind(sentence, f.start, f.end)
    return {"clock": "a time of day", "code": "a project or model number", "bound": "a bound of a requirement", "requirement": "a figure of a requirements list"}.get(kind or "")


def _clock_value(value: str) -> Optional[str]:
    return "a time of day" if re.fullmatch(r"\s*\d{1,2}:\d{2}\s*", value or "") else None


_SCALE_SHORT = (("трлн", "трлн"), ("триллион", "трлн"), ("млрд", "млрд"), ("миллиард", "млрд"), ("млн", "млн"), ("миллион", "млн"), ("тыс", "тыс."), ("тысяч", "тыс."))


def _rescaled(value: str, src: Source) -> Optional[tuple[str, int]]:
    """A key figure that lost its scale word («70» of «70 миллионов человек»): the value as its sentence writes it."""
    from verstka.planning.grounding import _is_year, figures

    fs = [f for f in figures(value or "") if f.date is None]
    if len(fs) != 1 or fs[0].scale != 1.0:
        return None
    for i, sn in enumerate(src.sentences):
        for f in figures(sn):
            if f.date is None and not _is_year(f) and f.scale != 1.0 and _same_value(f.value, fs[0].value):
                word = sn[f.end: f.uend].strip().lower()
                short = next((v for k, v in _SCALE_SHORT if word.startswith(k)), None)
                if short:
                    return f"{value.strip()} {short}", i
    return None


def _check_numbers(r: _Run) -> None:
    """Key figures: each is in a sentence of the slide, its label that sentence without the value phrase (only a bad
    label is rebuilt; a hard-bad one that cannot be becomes its sentence as a line), its hedge («более 70 млн») kept."""
    s, c, src = r.s, r.s.content, r.src
    if not c.numbers:
        return
    found: list[tuple[NumberCallout, Optional[int]]] = []
    not_figures: list[str] = []
    for n in list(c.numbers):
        want = _values(n.value)
        i = next((k for k, x in enumerate(src.sentences) if want and all(any(_same_value(v, y) for y in _values(x)) for v in want)), None)
        if i is None:
            fixed = _rescaled(n.value, src)
            if fixed is not None:
                r.say(f"the key figure {n.value} without its scale → «{fixed[0]}»")
                n.value, i = fixed
                want = _values(n.value)
        sn = src.sentences[i] if i is not None else None
        kind = _not_a_figure(sn, n.value) if sn else _clock_value(n.value)
        if kind:
            # G4-3: a time of day, a project number, a bound of a requirement is never a key figure — its sentence is
            r.say(f"the key figure {n.value} is {kind}, not a figure → its sentence")
            if sn:
                not_figures.append(sn)
            continue
        found.append((n, i))
        hedge = _hedge_before(sn, n.value) if sn else None
        if hedge and not re.match(r"^\s*(?:>|<|≈|~|более|свыше|около|почти|примерно|менее|порядка|приблизительно|не\s)", n.value or "", re.I):
            r.say(f"the key figure {n.value} as its sentence gives it → «{hedge} {n.value}»")
            n.value = f"{hedge} {n.value}"
    if not_figures:
        from verstka.planning.clauses import fit

        c.numbers = [n for n, _ in found]
        lines = []
        for sn in not_figures:
            t = _fit_line(sn, r)
            if not any(coverage(t, x) >= 0.9 for x in [*lines, *c.bullets]):
                lines.append(t)
        c.bullets = (lines + list(c.bullets))[:6]
        if len(c.numbers) < 2 and s.kind == PatternKind.stat_row or not c.numbers and s.kind == PatternKind.big_number:
            for n, i in found:
                t = _fit_line(src.sentences[i], r) if i is not None else None
                if t and not any(coverage(t, x) >= 0.9 for x in c.bullets):
                    c.bullets.insert(0, t)
            c.numbers = []
            s.kind = PatternKind.bullets
            return
    probs = {id(n): bad_label(n.label, n.value, src.sentences[i], src.known, src.dates[i]) for n, i in found if i is not None}
    if not any(probs.values()):
        return
    keep: list[NumberCallout] = []
    lines: list[str] = []
    new_labels: list[NumberCallout] = []
    for n, i in found:
        why = probs.get(id(n))
        if why is None:
            keep.append(n)
            continue
        sn = src.sentences[i]
        year = max(src.dates[i].years) if src.dates[i].years and not dates_of(sn).years else None
        lb = label_of(sn, n.value, src.known, year=year)
        if lb:
            lb = H.label_beside(n.value, lb, s.headline or "")  # the words the slide shows (the composer's own rule)
            r.say(f"the label «{(n.label or '')[:60]}» of {n.value} ({why}) → «{lb}»")
            n.label = lb
            keep.append(n)
            new_labels.append(n)
        elif why in _SOFT:
            keep.append(n)
        else:
            t = _fit_line(sn, r)
            r.say(f"the key figure {n.value} has no label its sentence gives («{(n.label or '')[:40]}»: {why}) → " + (f"the line «{t[:50]}»" if t else "dropped"))
            if t and not any(coverage(t, x) >= 0.9 for x in lines):
                lines.append(t)
    others = [n for n in keep if n not in new_labels]
    if new_labels and any((n.label or "")[:1].isupper() for n in others):
        # one case in a row: most labels rebuilt — the others continue their figures too; else the rebuilt ones capitalised
        if len(new_labels) >= len(others):
            for n in others:
                first = (n.label or "").split()[0] if (n.label or "").split() else ""
                if first and not first.isupper() and not any(_same_word(first, k) for k in src.known):
                    n.label = n.label[:1].lower() + n.label[1:]
        else:
            for n in new_labels:
                n.label = H.cap_first(n.label)
    if s.kind == PatternKind.stat_row and len(keep) < 2 and not c.chart and not c.table:
        for n in keep:
            i = next((k for m, k in found if m is n), None)
            t = _fit_line(src.sentences[i], r) if i is not None else None
            if t and not any(coverage(t, x) >= 0.9 for x in lines):
                lines.insert(0, t)
        keep = []
    if len(keep) == len(c.numbers) and not lines:
        return
    c.numbers = keep
    c.bullets = (lines + [b for b in c.bullets if not any(coverage(b, x) >= 0.9 for x in lines)])[:6]
    if not c.numbers and s.kind in (PatternKind.stat_row, PatternKind.big_number):
        s.kind = PatternKind.bullets


def _check_table(r: _Run) -> None:
    """A table of «Показатель | Значение» rows a variant made of the key figures: labels as key figures' labels; when
    they fail, the rows are the key figures again."""
    s, c, src = r.s, r.s.content, r.src
    t = c.table
    if t is None or len(t.columns) != 2 or not t.rows or any(len(row) != 2 for row in t.rows):
        return
    probs = []
    for label, value in t.rows:
        want = _values(value)
        i = next((k for k, x in enumerate(src.sentences) if want and all(any(_same_value(v, y) for y in _values(x)) for v in want)), None)
        why = bad_label(label, value, src.sentences[i], src.known, src.dates[i]) if i is not None else None
        if why:
            probs.append(label)  # a one-word row label («Погибло», «Государства») too: a row of key figures labels it
    if not probs:
        return
    if 2 <= len(t.rows) <= 4 and not c.chart:
        c.numbers = [NumberCallout(value=value, label=label) for label, value in t.rows]
        c.table = None
        s.kind = PatternKind.stat_row
        r.say(f"a table of key figures with labels that are not ({', '.join(p[:30] for p in probs)}) → a row of key figures")
        _check_numbers(r)


# where a card's title ends and its text goes on: never before a contrast («…, но отключилась…» stays in the title's
# sentence — gate 4 G4-1)
_CARD_SPLIT_RE = re.compile(r",\s+(?:включая|в\s+том\s+числе)\s|\s(?:из-за|благодаря|после)\s")


def _card_of(sentence: str) -> SlideItem:
    """A sentence as a card: whole when short, else its first clause as the card's title and the rest under it."""
    t = H.strip_end(sentence)
    if len(t.split()) <= 13:
        return SlideItem(title=t)
    for m in _CARD_SPLIT_RE.finditer(t):
        head, rest = t[: m.start()].rstrip(","), t[m.start():].lstrip(", ").strip()
        if 4 <= len(head.split()) <= 11 and len(rest.split()) >= 2 and head.count("«") == head.count("»"):
            return SlideItem(title=head, text=rest)
    return SlideItem(title=t)


_PRONOUN_RE = re.compile(r"(?<![\wё])(?:он|она|оно|они|его|её|ее|их|это|этот|эта|эти|там|тогда)(?![\wё])", re.I)


def _orphan(sentence: str) -> bool:
    """A sentence that leans on the one before it: a pronoun among its first six words."""
    head = " ".join((sentence or "").split()[:6])
    return bool(_PRONOUN_RE.search(head))


def _fill_short(r: _Run) -> None:
    """A slide of one or two short lines (the slide's text has more): its sentences as cards — two short lines on a
    slide are a sparse list (fill_ratio, gate 3 WWII s10, EV s5)."""
    s, c, src = r.s, r.s.content, r.src
    few_cards = s.kind == PatternKind.cards and 1 <= len(c.items) <= 2 and all(not it.text and not it.bullets for it in c.items) and not (c.bullets or c.paragraphs)
    if not (s.kind == PatternKind.bullets and not c.items or few_cards) or c.numbers or c.chart or c.table or c.columns or c.quote or c.formula:
        return
    lines = [it.title for it in c.items] if few_cards else [*c.paragraphs, *c.bullets]
    if len(lines) > 2 or sum(len(x.split()) for x in lines) > 24:
        return
    head = s.headline or ""
    pool = []
    when: dict[str, _Dates] = {}
    for k, (sn, sd) in enumerate(zip(src.sentences, src.dates)):
        t = _fit_line(sn, r)
        if t:
            t = _on_its_own(r, t, k)  # «Также она владеет…» → «VK владеет…»; None: it leans on another sentence
        if t:
            when[t] = sd
        if t and s.takeaway and coverage(t, s.takeaway) >= 0.8 and coverage(s.takeaway, t) >= 0.8:
            continue  # the takeaway says it
        if t is None or len(t.split()) < 4:
            continue
        says_it = coverage(head, t) >= 0.75 and coverage(t, head) >= 0.45  # the headline is this sentence, shortened
        if says_it or coverage(t, head) >= 0.75 or (coverage(t, head) >= 0.5 and dates_of(t).any and dates_of(t).within(dates_of(head))):
            continue  # the headline says it
        if not any(coverage(t, x) >= 0.85 for x in pool):
            pool.append(t)
    if len(pool) == 1 and len(lines) == 1 and s.kind == PatternKind.bullets and not few_cards:
        # one sentence under the headline: a statement set large, not a list of one line
        if c.bullets or c.paragraphs != [pool[0]]:
            c.paragraphs, c.bullets = [pool[0]], []
            r.say("a slide of one line → its sentence as a statement")
        return
    if len(pool) < 2 or len(pool) <= len(lines) and len(lines) >= 2 and all(len(x.split()) >= 8 for x in lines):
        return
    if few_cards and (len(pool) < len(lines) or sum(len(x.split()) for x in pool[:4]) < 1.3 * sum(len(x.split()) for x in lines)):
        return  # the cards say as much as the text has
    pool = pool[:4]
    steps = [(date_title(x, when[x]), event_text(x)) for x in pool if when.get(x) is not None and when[x].years]
    if len(pool) >= 3 and len(steps) == len(pool) and all(d and e for d, e in steps):
        # every sentence dated («1 сентября 1939 года…», «3 сентября…»): the slide's time axis
        try:
            from verstka.planning.writer import chrono_sort

            steps = chrono_sort(steps, lambda x: x[0])
        except Exception:  # noqa: BLE001 - the text's order
            pass
        s.kind = PatternKind.timeline
        c.items = [SlideItem(title=d, text=H.cap_first(e)) for d, e in steps]
        c.bullets, c.paragraphs = [], []
        r.say(f"a short slide ({len(lines)} line(s)) → its {len(pool)} dated sentences as a timeline")
        return
    s.kind = PatternKind.cards
    c.items = [_card_of(x) for x in pool]
    c.bullets, c.paragraphs = [], []
    r.say(f"a short slide ({len(lines)} line(s)) → its {len(pool)} sentences as cards")


def _complete_enumeration(r: _Run) -> None:
    """A list of the names one sentence enumerates («производят «Москвич», «Автотор», «АвтоВАЗ» и завод
    «Моторинвест»») keeps every one of them, in the sentence's order (gate 3 W3-2: «Москвич» was dropped)."""
    c, src = r.s.content, r.src
    attr = "bullets" if c.bullets else "items" if c.items and all(not it.text for it in c.items) else None
    if attr is None:
        return
    lines = c.bullets if attr == "bullets" else [it.title for it in c.items]
    if len(lines) < 2 or any(len(x.split()) > 4 for x in lines):
        return
    for sn in src.sentences:
        names = re.findall(r"«([^«»]{1,40})»", sn)
        if len(names) < 3:
            continue
        pos = {}
        for i, ln in enumerate(lines):
            hit = [k for k, nm in enumerate(names) if f"«{nm}»" in ln]
            if len(hit) == 1:
                pos[hit[0]] = i
        if len(pos) < 2 or len(pos) < len(lines) - 1:
            continue
        missing = [k for k in range(len(names)) if k not in pos]
        if not missing:
            return
        out = []
        for k, nm in enumerate(names):
            out.append(lines[pos[k]] if k in pos else f"«{nm}»")
        out += [ln for i, ln in enumerate(lines) if i not in pos.values()]
        if attr == "bullets":
            c.bullets = out[:6]
        else:
            c.items = [SlideItem(title=x) for x in out[:6]]
        r.say(f"the list of the names its sentence enumerates keeps them all (+{', '.join(names[k] for k in missing)})")
        return


def _refill(r: _Run) -> None:
    """A slide the checks left empty (every entry was the designer's, none the text's): the slide's sentences."""
    s, c, src = r.s, r.s.content, r.src
    if not c.is_empty or c.formula or c.chart2:
        return
    head = s.headline or ""
    pool: list[str] = []
    for k, sn in enumerate(src.sentences):
        t = _fit_line(sn, r)
        t = _on_its_own(r, t, k) if t else None
        if not t or coverage(head, t) >= 0.75 or any(coverage(t, x) >= 0.85 for x in pool):
            continue
        pool.append(t)
    if not pool:
        return
    if len(pool) >= 2:
        s.kind = PatternKind.cards
        c.items = [_card_of(x) for x in pool[:4]]
    else:
        s.kind = PatternKind.bullets
        c.bullets = pool[:1]
    r.say(f"no entry of the slide was in the text → its {len(pool[:4])} sentence(s)")


# ------------------------------------------------------------------ gate 4: whole sentences, lines on their own, headlines

HEAD_MAX_SENTENCE = 16  # a whole sentence (without its clock time and parentheses) as a headline
HEAD_MAX_CUT = 14  # a sentence's safe head as a headline (G4-5)
_GENERIC_TITLES = frozenset({"другие факты", "ключевые факты", "факты", "главное", "итоги", "в цифрах", "цифры", "данные", "хронология", "основное", "обзор", "введение", "заключение"})
_RELATIVE_START_RE = re.compile(r"^(?:В|Во)\s+(?:том\s+же|этом\s+же|этом|тот\s+же|этот)\s+году(?![\wё])|^(?:В|Во)\s+(?:этот|тот)\s+(?:же\s+)?период(?![\wё])|^(?:Тогда\s+же|В\s+это\s+время|В\s+то\s+же\s+время)(?![\wё])")
_CLOCK_PHRASE = r"в\s+\d{1,2}(?::\d{2}|\s+час\w*(?:\s+\d{1,2}\s+минут\w*)?)(?:\s+по\s+(?:московскому|местному)\s+времени)?"


def _clean(t: str) -> str:
    t = re.sub(r",\s*,", ",", t or "")
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = re.sub(r"^[\s,;:]+", "", t)
    t = re.sub(r"[\s,;:]+$", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _head_form(sentence: str) -> str:
    """A sentence as a headline reads it: no clock time, no time zone, no parentheses, both commas of a clock time
    that stood between them gone («12 апреля 1961 года, в 9 часов 7 минут по московскому времени, с космодрома…» →
    «12 апреля 1961 года с космодрома…»)."""
    t = re.sub(r"\s*\([^()]*\)", "", sentence or "")
    t = re.sub(rf",\s*{_CLOCK_PHRASE}\s*,", " ", t, flags=re.I)
    t = re.sub(rf"\s*(?<![\wё]){_CLOCK_PHRASE}", " ", t, flags=re.I)
    t = re.sub(r"(?<![\wё])по\s+(?:московскому|местному)\s+времени", " ", t, flags=re.I)
    return H.strip_end(_clean(t))


def generic_head(h: str, title: str = "") -> bool:
    """A headline that is a working title of the writer's storyline («Предпосылки и причины», «Ход событий
    (продолжение)», «Инфраструктура», «Другие факты»), not a statement (G4-5)."""
    hn = H.strip_end(h or "").strip().lower()
    if not hn:
        return True
    base = re.sub(r"\s*\(продолжение(?:\s+\d+)?\)\s*$", "", hn)
    if base != hn or base in _GENERIC_TITLES:
        return True
    try:
        from verstka.planning.writer import _working_title

        if _working_title(hn):
            return True
    except Exception:  # noqa: BLE001 - the writer's own list, else the rules below
        pass
    # a label of one or two words («Начало», «Инфраструктура»); the writer's own title of more («Инвесторы и доли»,
    # «Статистика пользователей»): a topic, kept
    return len(hn.split()) <= 2 and not re.search(r"\d", hn)


def _resolved_start(sentence: str, sdates: _Dates) -> Optional[str]:
    """A sentence whose time is told by the one before it («В том же году было продано…») with that year written
    («В 2024 году было продано…»); None when the year is not one; the sentence as it is without such a start."""
    m = _RELATIVE_START_RE.match(sentence or "")
    if not m:
        return sentence
    own = dates_of(sentence[m.end():])
    if own.years:
        return H.cap_first(_clean(sentence[m.end():]))
    if len(sdates.years) != 1:
        return None
    return f"В {next(iter(sdates.years))} году{sentence[m.end():]}"


def _sentence_of(line: str, src: Source, floor: float = 0.6) -> Optional[int]:
    best: Optional[tuple[float, int]] = None
    for i, sn in enumerate(src.sentences):
        cv = coverage(line, sn)
        if cv >= floor and (best is None or cv > best[0]):
            best = (cv, i)
    return best[1] if best else None


def _on_its_own(r: _Run, text: str, i: Optional[int]) -> Optional[str]:
    from verstka.planning.clauses import standalone

    before = list(r.src.before) + (r.src.sentences[:i] if i is not None else list(r.src.sentences))
    return standalone(text, before, names=r.src.name_forms())


def assertion(r: _Run, used: frozenset = frozenset(), skip: tuple = ()) -> Optional[tuple[str, int, bool]]:
    """A headline that states the slide's point from its own sentences (G4-5): the first sentence that reads on its
    own and fits whole (≤ 15 words without its clock time), else another one that does, else the first sentence's safe
    head (≤ 12 words). (headline, sentence index, whole); None when no sentence gives one. `used`: the other slides'
    headlines (normalised), never repeated."""
    from verstka.planning.clauses import has_predicate, safe_cut

    src = r.src
    cands: list[tuple[str, int, bool]] = []
    for i, (sn, sd) in enumerate(zip(src.sentences, src.dates)):
        if i in skip:
            continue
        t = _resolved_start(sn, sd)
        if t is None:
            continue
        t = _on_its_own(r, t, i)
        if t is None:
            continue
        t = _head_form(t)
        if len(t.split()) < 4 or not has_predicate(t) or ranks_of(t) and not all(_rank_ok(x, t, sn) for x in ranks_of(t)):
            continue
        if len(t.split()) <= HEAD_MAX_SENTENCE:
            cands.append((t, i, True))
        else:
            cut = safe_cut(t, HEAD_MAX_CUT)
            if cut and len(cut.split()) >= 5:  # (≤ 14 words: a head that keeps its «, но …» is longer than 12)
                cands.append((H.strip_end(cut), i, False))
    cands = [c for c in cands if _norm(c[0]) not in used]
    # a whole sentence (the first two first), else the first sentence's safe head — which leaves that sentence in the
    # body whole, said twice: the last resort
    whole = sorted((c for c in cands if c[2]), key=lambda c: (c[1] > 1, c[1]))
    if whole:
        return whole[0]
    first_cut = [c for c in cands if not c[2] and c[1] == 0 and len(c[0].split()) >= 6]
    return first_cut[0] if first_cut else (cands[0] if cands else None)


def _drop_told(r: _Run, i: int) -> None:
    """The body lines and cards that say the headline's sentence again go (while the body keeps something)."""
    c, sn = r.s.content, r.src.sentences[i]

    def same(x: str) -> bool:
        return bool(x) and coverage(x, sn) >= 0.8 and coverage(sn, x) >= 0.6

    for attr in ("bullets", "paragraphs"):
        lines = getattr(c, attr)
        keep = [x for x in lines if not same(x)]
        if len(keep) < len(lines) and (keep or c.items or c.numbers or c.chart or c.table or (attr == "bullets" and c.paragraphs) or (attr == "paragraphs" and c.bullets)):
            setattr(c, attr, keep)
    keep_i = [it for it in c.items if not same(f"{it.title} {it.text}".strip())]
    if len(keep_i) < len(c.items) and (keep_i or c.bullets or c.paragraphs):
        c.items = keep_i
        if r.s.kind == PatternKind.cards and len(keep_i) == 1 and not keep_i[0].bullets and not keep_i[0].number:
            # one card left: a line (the short-slide rule sets it as a statement)
            c.bullets = [H.strip_end(f"{keep_i[0].title} {keep_i[0].text}".strip())] + list(c.bullets)
            c.items = []
            r.s.kind = PatternKind.bullets


def _body_insert(r: _Run, line: str, first: bool = True) -> None:
    """A sentence onto the slide's body, in the form the slide has."""
    s, c = r.s, r.s.content
    if s.kind == PatternKind.timeline and c.items:
        i = _sentence_of(line, r.src)
        d = date_title(r.src.sentences[i], r.src.dates[i]) if i is not None else None
        e = event_text(r.src.sentences[i]) if i is not None else None
        if d and e:
            c.items.insert(0, SlideItem(title=d, text=H.cap_first(e)))
            try:
                from verstka.planning.writer import chrono_sort

                c.items = chrono_sort(c.items, lambda it: it.title or "")
            except Exception:  # noqa: BLE001 - the text's order
                pass
            return
    if c.items and not c.bullets and s.kind in (PatternKind.cards, PatternKind.process, PatternKind.team) and len(c.items) < 6:
        c.items.insert(0 if first else len(c.items), SlideItem(title=line))
        return
    if c.paragraphs and not c.bullets and not (c.items or c.numbers or c.chart or c.table):
        c.bullets, c.paragraphs = ([line] if first else []) + list(c.paragraphs) + ([] if first else [line]), []
        if s.kind not in (PatternKind.bullets,):
            s.kind = PatternKind.bullets
        return
    c.bullets = ([line] + list(c.bullets)) if first else (list(c.bullets) + [line])
    if not (c.items or c.numbers or c.chart or c.table or c.columns) and s.kind not in (PatternKind.bullets,):
        s.kind = PatternKind.bullets


def _whole_sentences(r: _Run) -> None:
    """G4-1: a line, a card or a takeaway that is the start of a slide's sentence cut where no clause ends («6 июня
    1944 года союзные силы США», «Выключение двигателя произошло только», «…проработала успешно» without «, но
    отключилась…») is the sentence — shortened where a clause ends, else whole."""
    from verstka.planning.clauses import cut_is_safe, fit

    src, c = r.src, r.s.content
    changed: list[str] = []

    def fix(x: str) -> str:
        if not x:
            return x
        for sn in src.sentences:
            if cut_is_safe(x, sn) is False:
                new = _fit_line(sn, r)
                changed.append(f"«{H.strip_end(x)[:50]}» → «{new[:50]}»")
                return new
        return x

    c.bullets = [fix(b) for b in c.bullets]
    c.paragraphs = [fix(b) for b in c.paragraphs]
    for it in c.items:
        if it.title and not it.text:
            it.title = fix(it.title)
    for col in c.columns:
        col.bullets = [fix(b) for b in col.bullets]
    if r.s.takeaway:
        r.s.takeaway = fix(r.s.takeaway)
    h = r.s.headline or ""
    for i, sn in enumerate(src.sentences):
        if cut_is_safe(h, sn) is False:
            whole = _head_form(sn)
            new = whole if len(whole.split()) <= HEAD_MAX_SENTENCE else (trim(whole, HEAD_MAX_CUT) or H.strip_end(src.title or ""))
            changed.append(f"the headline «{h[:50]}» → «{new[:50]}»")
            if new == H.strip_end(src.title or ""):
                _body_insert(r, _fit_line(sn, r))
            r.s.headline = new
            break
    if changed:
        r.say("sentences cut where no clause ends → whole: " + "; ".join(changed))


def _assert_headline(r: _Run) -> None:
    """G4-5: a headline that is the storyline's working title («Предпосылки и причины», «Ход событий (продолжение)»)
    or starts with a time the sentence before tells («В том же году…») states the slide's point from its own
    sentences instead; the body line that says the same sentence goes."""
    s, src = r.s, r.src
    h = H.strip_end(s.headline or "")
    m = _RELATIVE_START_RE.match(h)
    if m:
        i = _sentence_of(h, src, 0.5)
        new = _resolved_start(h, src.dates[i]) if i is not None else None
        if new:
            r.say(f"the headline «{h}» starts with a time the sentence before tells → «{new}»")
            s.headline = h = H.strip_end(new)
        else:
            h = ""
    from verstka.planning.clauses import strip_connector

    h2 = strip_connector(h) if h else h
    if h2 != h:
        r.say(f"the headline «{h}» without its connector → «{h2}»")
        s.headline = h = h2
    if h and not generic_head(h, src.title):
        return
    dated_lines = [x for x in s.content.bullets if _LINE_DATE_RE.match(H.strip_end(x))]
    if (s.kind == PatternKind.timeline and len(s.content.items) >= 3) or (len(dated_lines) >= 3 and len(dated_lines) >= 0.8 * len(s.content.bullets)):
        # a time axis under its label («Хронология»): a statement of one entry would say one of its steps twice
        base = re.sub(r"\s*\(продолжение(?:\s+\d+)?\)\s*$", "", h or H.strip_end(src.title or ""), flags=re.I)
        if base and base != s.headline:
            s.headline = base
        return
    got = assertion(r)
    if got is not None and got[2] and len(src.sentences) == 1:
        # the slide's one sentence: as the headline it would leave the body empty — the label stays over it
        got = None
    if got is None:
        base = re.sub(r"\s*\(продолжение(?:\s+\d+)?\)\s*$", "", H.strip_end(h or src.title or ""), flags=re.I)
        if base and base != s.headline:
            r.say(f"the headline «{s.headline}» → «{base}»")
            s.headline = base
        return
    new, i, whole = got
    r.say(f"the headline «{h or s.headline}» is a working title → «{new}»")
    s.headline = new
    if whole:
        _drop_told(r, i)


def _standalone_pass(r: _Run) -> None:
    """G4-6: a sentence on its own card, line or label reads on its own: no leading connector («Также компания…»),
    a leading «он / она» or a possessive «её» by the name the text gives («Также она владеет…» → «VK владеет…»); one
    that still leans on another sentence stays only right after that sentence on the slide, else it goes (the notes
    keep it)."""
    s, c, src = r.s, r.s.content, r.src
    changed: list[str] = []

    def one(x: str, shown: list[str]) -> Optional[str]:
        i = _sentence_of(x, src)
        y = _on_its_own(r, x, i)
        if y is not None:
            if y != x:
                changed.append(f"«{x[:40]}» → «{y[:40]}»")
            return y
        ante = (src.sentences[i - 1] if i else (src.before[-1] if src.before else None)) if i is not None else None
        if ante and any(p and (coverage(ante, p) >= 0.6 or coverage(p, ante) >= 0.6) for p in shown[-2:]):
            return "\x00" + x  # right after the sentence it leans on: joined to that line (below)
        changed.append(f"«{x[:40]}» leans on a sentence the slide does not show, dropped")
        return None

    for attr in ("bullets", "paragraphs"):
        lines = getattr(c, attr)
        out: list[str] = []
        for x in lines:
            y = one(x, [s.headline or "", *out])
            if y is None:
                continue
            if y.startswith("\x00"):
                y = y[1:]
                if out and len(out[-1].split()) + len(y.split()) <= 40:
                    # «…, а напиток взбивали до получения пены. Его пили только мужчины…»: one line, never a line that
                    # starts with a pronoun of the line before
                    changed.append(f"«{y[:40]}» joined to the line it leans on")
                    out[-1] = f"{H.strip_end(out[-1])}. {H.strip_end(y)}"
                    continue
            out.append(y)
        if out != lines and (out or c.items or c.numbers or c.chart or c.table):
            setattr(c, attr, out)
    items: list[SlideItem] = []
    for it in c.items:
        if _date_only(it.title or "") or not it.title:
            items.append(it)
            continue
        y = one(it.title, [s.headline or "", *(x.title for x in items)])
        if y is None:
            continue
        if y.startswith("\x00"):
            y = y[1:]
            if items and not items[-1].text and len(items[-1].title.split()) + len(y.split()) <= 30:
                items[-1] = items[-1].model_copy(update={"text": H.strip_end(y)})  # under the card it leans on
                changed.append(f"«{y[:40]}» under the card it leans on")
                continue
        items.append(it.model_copy(update={"title": y}) if y != it.title else it)
    if len(items) != len(c.items) or any(a is not b for a, b in zip(items, c.items)):
        if len(items) >= 2 or s.kind != PatternKind.cards or not c.items:
            c.items = items
    if changed:
        r.say("lines on their own: " + "; ".join(changed))


_DEFINITION_RE = re.compile(r"^([А-ЯЁA-Z«][^—–]{1,60}?)\s+[—–]\s+(?:это\s+)?\S")


def _definition_lead(r: _Run) -> None:
    """G4-14: a definition («Вторая мировая война — война двух коалиций…») is never a card: the headline tells it, or
    it is the slide's lead line (the subtitle)."""
    s, c, src = r.s, r.s.content, r.src
    defs = [i for i, sn in enumerate(src.sentences) if _DEFINITION_RE.match(sn) and not dates_of(sn.split("—")[0]).any]
    if not defs or s.kind not in (PatternKind.cards, PatternKind.process, PatternKind.bullets):
        return
    from verstka.planning.clauses import fit

    for i in defs:
        sn = src.sentences[i]
        hit = [it for it in c.items if coverage(f"{it.title} {it.text}", sn) >= 0.7 and (it.text or _DEFINITION_RE.match(it.title or ""))]
        if not hit:
            continue
        c.items = [it for it in c.items if it not in hit]
        told = coverage(s.headline or "", sn) >= 0.6
        if not told and not s.subtitle:
            s.subtitle = _fit_line(sn, r)
        r.say("a definition as a card → " + ("the headline tells it" if told else "the lead line"))
        if len(c.items) < 2 and s.kind == PatternKind.cards:
            c.bullets = [H.strip_end(f"{it.title} {it.text}".strip()) for it in c.items] + list(c.bullets)
            c.items = []
            s.kind = PatternKind.bullets


def _long_cards(r: _Run) -> None:
    """G4-14: a row of three or more cards that are each a long sentence (small type in small boxes) is a list."""
    s, c = r.s, r.s.content
    if s.kind != PatternKind.cards or len(c.items) < 2 or any(it.text or it.bullets or it.number for it in c.items):
        return
    n = [len((it.title or "").split()) for it in c.items]
    if (len(n) >= 3 and sum(n) / len(n) >= 10) or max(n) >= 16:
        c.bullets = [H.strip_end(it.title) for it in c.items][:6] + list(c.bullets)
        c.items = []
        s.kind = PatternKind.bullets
        r.say("cards of long sentences → a list")


def _keep_sentences(r: _Run) -> None:
    """G4-2: a written slide keeps its first dated sentence (its date with its event) and at least one whole sentence
    of its text in its body."""
    from verstka.planning.clauses import fit, has_predicate

    s, c, src = r.s, r.s.content, r.src
    if c.chart is not None or c.table is not None or s.kind in (PatternKind.chart, PatternKind.table, PatternKind.quote):
        return
    body = [*c.bullets, *c.paragraphs, *(f"{it.title} {it.text}".strip() for it in c.items), *(b for col in c.columns for b in col.bullets)]
    shown = [s.headline or "", s.subtitle or "", s.takeaway or "", *body, *(f"{n.value} {n.label}" for n in c.numbers)]
    first = next((i for i, sn in enumerate(src.sentences) if dates_of(sn).any), None)
    thin = len(body) <= 2 or generic_head(s.headline or "", src.title)
    if first is not None and thin:
        sn, sd = src.sentences[first], dates_of(src.sentences[first])
        told = any(x and (dates_of(x).years & sd.years or dates_of(x).days & sd.days) and (coverage(x, sn) >= 0.5 or coverage(sn, x) >= 0.5) for x in shown)
        if not told and not any(it.title and _date_only(it.title) and coverage(it.text or "", sn) >= 0.5 for it in c.items):
            line = _fit_line(sn, r)
            _body_insert(r, line)
            r.say(f"the slide's first dated sentence was not on it → «{line[:60]}»")
            body.insert(0, line)
    if c.numbers and not body:
        return
    whole = [x for x in body if has_predicate(x) and any(coverage(x, sn) >= 0.7 for sn in src.sentences)]
    told = " ".join(x for x in shown if x)
    if whole or not src.sentences or any(coverage(sn, told) >= 0.8 for sn in src.sentences):
        return  # a list of the names one sentence enumerates, under a headline that says the rest of it, tells it
    for i, sn in enumerate(src.sentences):
        line = _on_its_own(r, _fit_line(sn, r), i)
        if line and not (coverage(sn, s.headline or "") >= 0.8 and coverage(s.headline or "", sn) >= 0.6):
            _body_insert(r, line, first=False)
            r.say(f"no whole sentence on the slide → «{line[:60]}»")
            return


def _label_pronouns(r: _Run) -> None:
    """G4-6: a key figure's label never leans on another sentence («62 — государства в ней»): it is rebuilt from its
    sentence read on its own («В войне участвовали 62 государства» → «государства участвовали в войне»), else the
    figure is its sentence as a line."""
    from verstka.planning.clauses import _DEM_RE, _PERS_RE

    s, c, src = r.s, r.s.content, r.src
    if not c.numbers:
        return
    keep: list[NumberCallout] = []
    lines: list[str] = []
    for n in c.numbers:
        if not n.label or not (_PERS_RE.search(n.label) or _DEM_RE.search(n.label)):
            keep.append(n)
            continue
        want = _values(n.value)
        i = next((k for k, x in enumerate(src.sentences) if want and all(any(_same_value(v, y) for y in _values(x)) for v in want)), None)
        own = _on_its_own(r, src.sentences[i], i) if i is not None else None
        lb = label_of(own, n.value, src.known) if own else None
        if lb and not _PERS_RE.search(lb) and not _DEM_RE.search(lb):
            r.say(f"the label «{n.label}» of {n.value} leans on another sentence → «{lb}»")
            n.label = lb
            keep.append(n)
        else:
            line = _fit_line(own or (src.sentences[i] if i is not None else ""), r)
            r.say(f"the key figure {n.value} with the label «{n.label}» → " + (f"the line «{line[:50]}»" if line else "dropped"))
            if line:
                lines.append(line)
    if len(keep) == len(c.numbers):
        return
    c.numbers = keep
    c.bullets = (lines + list(c.bullets))[:6]
    if s.kind == PatternKind.stat_row and len(keep) < 2 or s.kind == PatternKind.big_number and not keep:
        c.bullets = [_fit_line(src.sentences[k], r) for n in keep for k in [next((j for j, x in enumerate(src.sentences) if _values(n.value) and all(any(_same_value(v, y) for y in _values(x)) for v in _values(n.value))), None)] if k is not None] + list(c.bullets)
        c.numbers = []
        s.kind = PatternKind.bullets


def _text_order(r: _Run) -> None:
    """The slide's lines in the order its text tells them (a line the checks put back went first: «Мирилашвили занял
    у отца…» before «Первыми инвесторами стали…»), when every line is one sentence of the text."""
    c, src = r.s.content, r.src
    for attr in ("bullets", "paragraphs"):
        lines = getattr(c, attr)
        if len(lines) < 2:
            continue
        if sum(1 for x in lines if _LINE_DATE_RE.match(H.strip_end(x))) >= 0.8 * len(lines):
            continue  # a dated list is in time order (agent._chrono_order)
        idx = [_sentence_of(x, src, 0.7) for x in lines]
        if any(i is None for i in idx) or len(set(idx)) != len(idx) or idx == sorted(idx):
            continue
        setattr(c, attr, [x for _, x in sorted(zip(idx, lines), key=lambda t: t[0])])


PROSE_WORDS = 15  # a list line longer than this reads as a paragraph («bullet_too_long» for the audit)
# where a long sentence splits into two lines that each stand on their own: «…, и VK была сформирована…», «…; …»
_SPLIT_AT_RE = re.compile(r",\s+и\s+(?=[А-ЯЁA-Z«]|[а-яё]+\s+[а-яё]+(?:ся|сь|л|ла|ло|ли|ет|ют|ит|ят)\b)|;\s+")


def _split_line(line: str) -> Optional[list[str]]:
    """A long sentence as two lines (gate 4 G4-1: «…or split it into two lines»): at «, и» before a clause with its own
    subject and verb, or at «;» — each part says a whole thing (its own predicate, no pronoun of the other); None."""
    from verstka.planning.clauses import has_predicate, head_ok, leans

    t = H.strip_end(line)
    for m in _SPLIT_AT_RE.finditer(t):
        head, tail = t[: m.start()].rstrip(" ,;"), t[m.end():].strip()
        if len(head.split()) < 5 or len(tail.split()) < 4 or not head_ok(head, t[m.start():]):
            continue
        if not has_predicate(tail) or leans(tail) or re.match(r"^[а-яё]+(?:ся|сь|л|ла|ло|ли|ет|ют|ит|ят)\s", tail):
            continue  # «…, и получила название VK»: the second half has no subject of its own
        return [head, H.cap_first(tail)]
    return None


def _prose_lines(r: _Run) -> None:
    """Whole sentences on a list (gate 4 G4-1 keeps them whole): a line of more than 15 words is split into two lines
    where it joins two clauses that each stand on their own; under key figures two or more long lines are one
    paragraph (the figures' block marks a list of lines, not one). The lines stay a list at the list's size — as
    paragraphs they are set smaller (15 pt against 18 pt on VK Tech)."""
    s, c = r.s, r.s.content
    lines = [*c.bullets, *c.paragraphs]
    if not lines or not any(len(x.split()) > PROSE_WORDS for x in lines):
        return
    if c.bullets and len(c.bullets) < 6:
        out: list[str] = []
        for b in c.bullets:
            parts = _split_line(b) if len(b.split()) > PROSE_WORDS and len(c.bullets) + len(out) < 6 else None
            out.extend(parts or [b])
        if out != c.bullets:
            r.say("long sentences split where two clauses join")
            c.bullets = out[:6]
    if c.numbers and s.kind in (PatternKind.stat_row, PatternKind.big_number):
        lines = [*c.bullets, *c.paragraphs]
        if len(lines) >= 2 and any(len(x.split()) > PROSE_WORDS for x in lines):
            joined = " ".join(x if x.rstrip().endswith((".", "!", "?", "…")) else x.rstrip() + "." for x in lines)
            c.paragraphs, c.bullets = [H.strip_end(joined)], []
            r.say("the lines under the key figures as one paragraph")


def _fix_values(r: _Run) -> None:
    """G4-16: «17,8 тыс» → «17,8 тыс.» in key figures and table cells; a label that starts with a name keeps its capital."""
    from verstka.planning.clauses import fix_scale

    c = r.s.content
    for n in c.numbers:
        v = fix_scale(n.value or "")
        if v != n.value:
            n.value = v
        if n.label:
            n.label = H.name_case(n.label, r.src.deck)
    if c.table is not None:
        c.table.rows = [[fix_scale(x) if j else H.name_case(x, r.src.deck) for j, x in enumerate(row)] for row in c.table.rows]
    for ch in (c.chart, c.chart2):
        if ch is not None:
            # G4-4: a category that is a name keeps its capital («Россия экспортирует…», never «россия …»)
            ch.categories = [H.name_case(x, r.src.deck) for x in ch.categories]


def unique_headlines(runs: list[tuple[OutlineSlide, str, str]], deck: str = "", topic: str = "") -> list[str]:
    """G4-5: no two slides of a deck under one headline («VK была основана в 1998 году» on s2 and s8): a later slide
    takes another statement of its own sentences. `runs`: (slide, its writer text, its title) in the deck's order.
    Returns the changes."""
    out: list[str] = []
    used: dict[str, int] = {}
    for k, (s, text, title) in enumerate(runs):
        if s.kind.value in ("title", "section", "thanks", "agenda") or not (s.headline or "").strip():
            continue
        key = _norm(H.strip_end(s.headline))
        if key not in used:
            used[key] = k
            continue
        src = Source.of(text, deck=deck, title=title, topic=topic)
        r = _Run(s=s, src=src, changes=out, key=s.id)
        got = assertion(r, used=frozenset(used))
        if got is None:
            continue
        new, i, whole = got
        old = H.strip_end(s.headline)
        r.say(f"the headline «{old}» is another slide's → «{new}»")
        s.headline = new
        if whole:
            _drop_told(r, i)
        # the old headline was a sentence of this slide: it stays on it, as a line
        j = _sentence_of(old, src, 0.8)
        c = s.content
        body = [*c.bullets, *c.paragraphs, *(f"{it.title} {it.text}".strip() for it in c.items)]
        if j is not None and j != i and not any(coverage(src.sentences[j], x) >= 0.8 for x in body):
            _body_insert(r, old)
        used[_norm(new)] = k
    return out


def check_slide(s: OutlineSlide, text: str, *, deck: str = "", title: str = "", topic: str = "", key: str = "") -> list[str]:
    """Validate one designed slide of a written deck against its writer text (see the module docstring). Mutates `s`;
    returns the changes."""
    if s.kind.value in ("title", "section", "thanks", "agenda") or not (text or "").strip():
        return []
    src = Source.of(text, deck=deck, title=title, topic=topic)
    if not src.sentences:
        return []
    changes: list[str] = []
    r = _Run(s=s, src=src, changes=changes, key=key or s.id)
    _check_items(r)
    _complete_enumeration(r)
    _timeline_form(r)
    _check_lines(r)
    _whole_sentences(r)
    _check_table(r)
    _check_numbers(r)
    _check_headline(r)
    _assert_headline(r)
    _check_takeaway(r)
    _refill(r)
    _fill_short(r)
    _standalone_pass(r)
    _definition_lead(r)
    _long_cards(r)
    _keep_sentences(r)
    _label_pronouns(r)
    _text_order(r)
    _prose_lines(r)
    _fix_values(r)
    _grammar(r)
    return changes


def _grammar(r: _Run) -> None:
    """The slide's lines and cards in the gender the text gives a name, a date as a subject neuter."""
    c, g = r.s.content, r.src.genders
    fix = lambda x: _date_neuter(agree_gender(x, g)) if x else x  # noqa: E731
    new_b = [fix(b) for b in c.bullets]
    new_p = [fix(b) for b in c.paragraphs]
    changed = new_b != c.bullets or new_p != c.paragraphs
    c.bullets, c.paragraphs = new_b, new_p
    for it in c.items:
        t, x = fix(it.title), fix(it.text)
        if t != it.title or x != it.text:
            it.title, it.text = t, x
            changed = True
    if r.s.takeaway and fix(r.s.takeaway) != r.s.takeaway:
        r.s.takeaway = fix(r.s.takeaway)
        changed = True
    if changed:
        r.say("the lines in the gender the text gives the names")
