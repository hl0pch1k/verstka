"""Words of the knowledge base: a Russian stemmer (Snowball's Russian algorithm, written out here — no dependency),
the tokens a fragment and a query are compared by, the numbers a statement and a fragment share."""

from __future__ import annotations

import re
from functools import lru_cache

_VOWELS = "аеиоуыэюя"

_PERFECTIVE_1 = ("вшись", "вши", "в")  # after а / я
_PERFECTIVE_2 = ("ившись", "ывшись", "ивши", "ывши", "ив", "ыв")
_REFLEXIVE = ("ся", "сь")
_ADJECTIVE = ("ими", "ыми", "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей", "ий", "ый", "ой", "ем", "им", "ым", "ом",
              "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею")
_PARTICIPLE_1 = ("ем", "нн", "вш", "ющ", "щ")  # after а / я
_PARTICIPLE_2 = ("ивш", "ывш", "ующ")
_VERB_1 = ("ешь", "нно", "ете", "йте", "ла", "на", "ли", "ем", "ло", "но", "ет", "ют", "ны", "ть", "й", "л", "н")  # after а / я
_VERB_2 = ("ейте", "уйте", "ила", "ыла", "ена", "ите", "или", "ыли", "ило", "ыло", "ено", "ует", "уют", "ены", "ить", "ыть", "ишь",
           "ей", "уй", "ил", "ыл", "им", "ым", "ен", "ят", "ит", "ыт", "ую", "ю")
_NOUN = ("иями", "ями", "ами", "ией", "иям", "ием", "иях", "ев", "ов", "ие", "ье", "еи", "ии", "ей", "ой", "ий", "ям", "ем", "ам",
         "ом", "ах", "ях", "ию", "ью", "ия", "ья", "а", "е", "и", "й", "о", "у", "ы", "ь", "ю", "я")
_SUPERLATIVE = ("ейше", "ейш")
_DERIVATIONAL = ("ость", "ост")


def _sorted(t: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(t, key=len, reverse=True))


_PERFECTIVE_1, _PERFECTIVE_2, _REFLEXIVE, _ADJECTIVE = map(_sorted, (_PERFECTIVE_1, _PERFECTIVE_2, _REFLEXIVE, _ADJECTIVE))
_PARTICIPLE_1, _PARTICIPLE_2, _VERB_1, _VERB_2, _NOUN = map(_sorted, (_PARTICIPLE_1, _PARTICIPLE_2, _VERB_1, _VERB_2, _NOUN))


def _regions(w: str) -> tuple[int, int]:
    """(RV, R2) start positions."""
    rv = len(w)
    for i, ch in enumerate(w):
        if ch in _VOWELS:
            rv = i + 1
            break

    def r_after(start: int) -> int:
        for i in range(start + 1, len(w)):
            if w[i] not in _VOWELS and w[i - 1] in _VOWELS:
                return i + 1
        return len(w)

    r1 = r_after(0)
    r2 = r_after(r1) if r1 < len(w) else len(w)
    return rv, r2


def _strip(w: str, rv: int, endings: tuple[str, ...], after_a: bool = False) -> str | None:
    for e in endings:
        if w.endswith(e) and len(w) - len(e) >= rv:
            if after_a:
                k = len(w) - len(e)
                if k - 1 >= rv and w[k - 1] in "ая":
                    return w[:k]
                continue
            return w[: len(w) - len(e)]
    return None


@lru_cache(maxsize=200_000)
def stem_ru(word: str) -> str:
    """Snowball (Porter) Russian stem of a lowercase word."""
    w = word.lower().replace("ё", "е")
    if len(w) <= 2 or not re.fullmatch(r"[а-я]+", w):
        return w
    rv, r2 = _regions(w)
    # step 1
    got = _strip(w, rv, _PERFECTIVE_1, after_a=True) or _strip(w, rv, _PERFECTIVE_2)
    if got is not None:
        w = got
    else:
        w = _strip(w, rv, _REFLEXIVE) or w
        adj = _strip(w, rv, _ADJECTIVE)
        if adj is not None:
            w = _strip(adj, rv, _PARTICIPLE_1, after_a=True) or _strip(adj, rv, _PARTICIPLE_2) or adj
        else:
            v = _strip(w, rv, _VERB_1, after_a=True) or _strip(w, rv, _VERB_2)
            if v is not None:
                w = v
            else:
                w = _strip(w, rv, _NOUN) or w
    # step 2
    if w.endswith("и") and len(w) - 1 >= rv:
        w = w[:-1]
    # step 3
    for e in _DERIVATIONAL:
        if w.endswith(e) and len(w) - len(e) >= r2:
            w = w[: len(w) - len(e)]
            break
    # step 4
    if w.endswith("нн") and len(w) - 1 >= rv:
        w = w[:-1]
    else:
        s = _strip(w, rv, _SUPERLATIVE)
        if s is not None:
            w = s[:-1] if s.endswith("нн") else s
        elif w.endswith("ь") and len(w) - 1 >= rv:
            w = w[:-1]
    return w


_EN_SUFFIX = re.compile(r"(?:ing|ed|es|s|ly|ment|ness|tion|ions)$")


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if re.fullmatch(r"[а-я]+", w):
        return stem_ru(w)
    if re.fullmatch(r"[a-z]+", w) and len(w) > 4:
        return _EN_SUFFIX.sub("", w) or w
    return w


STOP = frozenset("""
а без более бы был была были было быть в вам вас весь во вот все всего всех вы где да даже для до его ее ей ему если есть
еще же за здесь и из или им их к как ко когда кто ли либо между меня мне может мы на над надо наш не него нее нет ни них
но ну о об однако он она они оно от очень по под при про с со так также такой там те тем то того тоже той только том ты
у уже хотя чего чей чем что чтобы чье чья эта эти это этот я также который которая которое которые которых этого этой
том себя свой своя свои своих сам сама само сами самый ещё через после перед около всё будет будут были
the a an of to in on for and or is are was were be by with as at from that this it its
презентация презентацию презентации презентаций слайд слайда слайдов слайды сделай сделайте создай подготовь расскажи
нужна нужно хочу тема теме тему
""".split())

STEM_MAX = 6
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*|\d+(?:[.,]\d+)?")


def tokens(text: str) -> list[str]:
    """The stems of a text's words (stop words out) and its numbers («1 240» → «1240», «12,5» → «12.5»)."""
    out: list[str] = []
    t = re.sub(r"(?<=\d)[\s  ](?=\d{3}(?!\d))", "", text or "")
    for m in _WORD_RE.finditer(t):
        w = m.group(0)
        if w[0].isdigit():
            out.append(w.replace(",", "."))
            continue
        lw = w.lower().replace("ё", "е")
        if lw in STOP or len(lw) < 2:
            continue
        for part in lw.split("-"):
            if part and part not in STOP:
                # a stem cut to STEM_MAX letters: Snowball's «квартал» → «кварта» and «кварталов» → «квартал» meet
                out.append(stem(part)[:STEM_MAX])
    return out


# ------------------------------------------------------------------ figures

_FIG_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[\s  ]\d{3})+|\d+)(?:[.,](\d+))?(?![\d])")


def figures(text: str) -> set[str]:
    """The numbers a text states, normalised: «1 240» → «1240», «12,5» → «12.5», «18%» → «18»."""
    out: set[str] = set()
    for m in _FIG_RE.finditer(text or ""):
        whole = re.sub(r"[\s  ]", "", m.group(1))
        frac = m.group(2)
        whole = whole.lstrip("0") or "0"
        out.add(f"{whole}.{frac.rstrip('0')}" if frac and frac.rstrip("0") else whole)
    return out


def figure_forms(n: str) -> set[str]:
    """A figure and the forms it can take in a document (a thousand as «1,2 тыс.» is not tried: the writer copies)."""
    return {n}


__all__ = ["STOP", "figures", "stem", "stem_ru", "tokens"]
