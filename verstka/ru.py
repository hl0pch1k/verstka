"""Small helpers for texts people read in Russian: numbers with nouns, ratios."""

from __future__ import annotations

from typing import Optional


# roles of the type scale, the way a person names them
TYPE_ROLE_RU = {"display": "обложка", "h1": "заголовок", "h2": "подзаголовок", "h3": "заголовок блока", "body": "текст", "small": "мелкий текст", "caption": "подпись"}


def ru_num(value: float) -> str:
    """10.5 → «10,5», 36.0 → «36»."""
    return f"{value:g}".replace(".", ",")


# words that open a phrase (prepositions, conjunctions, particles): a shortened text never ends on one
_FUNCTION_WORDS = frozenset(
    "в во на за с со к ко по о об обо от до из у для при про без над под перед через между среди после около вокруг "
    "и а но или либо да что чтобы как если когда где куда который которая которое которые не ни же ли бы то это".split()
)


def _bare(word: str) -> str:
    return word.lower().strip(",;:—–-«»\"()")


def clip_words(text: str, max_words: int) -> str:
    """At most `max_words` words, cut where a phrase ends: right before a preposition or conjunction that opens the
    next phrase, never after one («…окупает разработку», not «…окупает разработку за»)."""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    for k in range(max_words, max(max_words - 5, 1), -1):
        if _bare(words[k - 1]) in _FUNCTION_WORDS:
            continue
        if _bare(words[k]) in _FUNCTION_WORDS or words[k - 1][-1] in ",;:":
            return " ".join(words[:k]).rstrip(" ,;:—–-")
    out = words[:max_words]
    while len(out) > 2 and _bare(out[-1]) in _FUNCTION_WORDS:
        out.pop()
    return " ".join(out).rstrip(" ,;:—–-")


def ru_count(n: int, one: str, few: str, many: str) -> str:
    """«1 строка», «3 строки», «11 строк» — a number with the noun in the matching form."""
    m10, m100 = n % 10, n % 100
    word = one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many
    return f"{n} {word}"


def ru_times(ratio: float) -> str:
    """«в 1,3 раза» — a ratio the Russian way (decimal comma)."""
    return f"в {ratio:.1f} раза".replace(".", ",")


NBSP = "\u00a0"
_BIND_AFTER = frozenset("в во на за с со к ко по о об от до из у и а но не ни же ли бы".split())
_UNIT_RE = __import__("re").compile(r"(?<=\d)[ ](?=(?:%|₽|руб|тыс|млн|млрд|ч\b|мин|сек|дн|мес|лет|год|раз|шт|ГБ|ТБ|МБ|×))")
_THOUSANDS_RE = __import__("re").compile(r"(?<=\d)[ ](?=\d{3}\b)")
_NUM_NOUN_RE = __import__("re").compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)[ ](?=[A-Za-zА-Яа-яЁё])")  # «4 GPU-сервера», «за 2 секунды»


WJ = "\u2060"  # word joiner: invisible, no glyph needed (Play has no no-break hyphen)
_COMPOUND_RE = __import__("re").compile(r"(?<=[^\W_])-(?=[^\W_])")


def bind_compounds(text: str) -> str:
    """A short compound word never breaks at its hyphen («GPU-сервера», «контакт-центра»): a word joiner after the
    hyphen. A long compound may still break there."""
    if "-" not in text:
        return text
    return "".join(_COMPOUND_RE.sub("-" + WJ, w) if len(w.strip("«»\"(),.:;!?")) <= 16 and WJ not in w else w for w in __import__("re").split(r"([ \u00a0]+)", text))


_ABBR2_RE = __import__("re").compile(r"(?<![А-Яа-яЁё])(п\.|т\.)\s+(п\.|е\.|д\.|к\.)")

# ---------------------------------------------------------------- figures: ranges, the minus, the percent sign (G5-16)

MINUS = "\u2212"  # «−69 %»: a true minus, as wide as a digit (Play, Inter, Roboto… all have it)
_re = __import__("re")
# «5-6 тысяч», «1941-1945», «10-15%» — two numbers joined by a hyphen are a range; not a date «2025-09-28», a phone
# «8-800-555», a code «Ту-144», «COVID-19», «5-6-летние», a time «9:00-18:00»
_RANGE_HYPHEN_RE = _re.compile(r"(?<![\w.,\-‐‑–—−/:])(\d+(?:[.,]\d+)?)[-‐‑]\u2060?(\d+(?:[.,]\d+)?)(?![\w\-‐‑–—−/:]|[.,]\d)")
# «5–6», «1941—1945»: the dash of a range never lets the line break before or after it («5 / –6 тыс.»)
_RANGE_DASH_RE = _re.compile(r"(?<=\d)\u2060?([–—])\u2060?(?=\d)")
# «-69%», «–5 °C»: a sign before a number that opens the text or follows a space or a bracket
_LEAD_MINUS_RE = _re.compile(r"(?:^|(?<=[\s\u00a0(«\"„\[/]))[-–](?=\d)")
_PCT_RE = _re.compile(r"(?<=\d)[ \u00a0\u202f\u2009]?%")
_PCT_STYLE: "__import__('contextvars').ContextVar[Optional[str]]" = __import__("contextvars").ContextVar("verstka_percent_style", default=None)


def percent_style_of(texts) -> Optional[str]:
    """How the source writes a percent: «tight» («42%») or «spaced» («42 %»), by the majority of its percents (a tie
    goes to the first one); None when it writes none."""
    tight = spaced = 0
    first = None
    for t in texts:
        for m in _PCT_RE.finditer(t or ""):
            kind = "tight" if m.group(0) == "%" else "spaced"
            first = first or kind
            tight += kind == "tight"
            spaced += kind == "spaced"
    if not tight and not spaced:
        return None
    return "tight" if tight > spaced else "spaced" if spaced > tight else first


@__import__("contextlib").contextmanager
def deck_typography(texts):
    """One percent style for everything typeset inside (a deck is rendered inside): the style of `texts` — the deck's
    own words, which come from the brief or the written text."""
    token = _PCT_STYLE.set(percent_style_of(texts))
    try:
        yield
    finally:
        _PCT_STYLE.reset(token)


def _lead_minus(m) -> str:
    before = m.string[: m.start()].rstrip(" \u00a0")
    return m.group(0) if before[-1:].isdigit() else MINUS  # «5 -6»: a range, not a sign


def typeset_figures(text: str) -> str:
    """The figures of a text set the Russian way — only these characters change: a range of two numbers takes an en dash
    bound to both numbers by word joiners («5-6 тыс.» → «5⁠–⁠6 тыс.», never broken as «5 / –6»), a sign before a number
    is a true minus («-69%» → «−69%»), and every percent follows the deck's style (`deck_typography`: «42%» or «42 %»
    with a no-break space)."""
    if not text or not any(ch.isdigit() for ch in text):
        return text
    t = _RANGE_HYPHEN_RE.sub(lambda m: f"{m.group(1)}–{m.group(2)}", text)
    t = _RANGE_DASH_RE.sub(lambda m: WJ + m.group(1) + WJ, t)
    t = _LEAD_MINUS_RE.sub(_lead_minus, t)
    style = _PCT_STYLE.get()
    if style == "tight":
        t = _PCT_RE.sub("%", t)
    elif style == "spaced":
        t = _PCT_RE.sub(NBSP + "%", t)
    return t


def typeset(text: str) -> str:
    """Russian display typesetting with no-break spaces: a dash never starts a line, a short preposition or
    conjunction never ends one, a figure stays with its unit, its thousands and its noun («12 400», «27 млн ₽»,
    «4 сервера»), a short compound word keeps its hyphen («GPU-сервера»); ranges, minus and percents as
    `typeset_figures`."""
    if not text:
        return text
    t = typeset_figures(text)
    t = t.replace(" — ", NBSP + "— ").replace(" – ", NBSP + "– ")
    t = _THOUSANDS_RE.sub(NBSP, t)
    t = _UNIT_RE.sub(NBSP, t)
    t = _NUM_NOUN_RE.sub(lambda m: m.group(1) + NBSP, t)
    t = t.replace(" ₽", NBSP + "₽")
    # «п. п.», «т. е.», «т. д.»: an abbreviation of two letters is one word on the slide («на 2 п.| п.» broke a headline)
    t = _ABBR2_RE.sub(lambda m: m.group(1) + NBSP + m.group(2), t)
    t = bind_compounds(t)
    words = t.split(" ")
    out = []
    for i, w in enumerate(words):
        out.append(w)
        if i < len(words) - 1:
            bare = w.lower().strip("«»\"(")
            out.append(NBSP if bare in _BIND_AFTER and not w.endswith((",", ".", ":", ";")) else " ")
    return "".join(out)
