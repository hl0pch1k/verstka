"""Small helpers for texts people read in Russian: numbers with nouns, ratios."""

from __future__ import annotations


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


def typeset(text: str) -> str:
    """Russian display typesetting with no-break spaces: a dash never starts a line, a short preposition or
    conjunction never ends one, a figure stays with its unit, its thousands and its noun («12 400», «27 млн ₽»,
    «4 сервера»), a short compound word keeps its hyphen («GPU-сервера»)."""
    if not text:
        return text
    t = text.replace(" — ", NBSP + "— ").replace(" – ", NBSP + "– ")
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
