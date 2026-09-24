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
