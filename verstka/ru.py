"""Small helpers for texts people read in Russian: numbers with nouns, ratios."""

from __future__ import annotations


def ru_count(n: int, one: str, few: str, many: str) -> str:
    """«1 строка», «3 строки», «11 строк» — a number with the noun in the matching form."""
    m10, m100 = n % 10, n % 100
    word = one if m10 == 1 and m100 != 11 else few if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else many
    return f"{n} {word}"


def ru_times(ratio: float) -> str:
    """«в 1,3 раза» — a ratio the Russian way (decimal comma)."""
    return f"в {ratio:.1f} раза".replace(".", ",")
