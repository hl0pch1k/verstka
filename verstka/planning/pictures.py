"""A picture the author described beside the text («[Место под изображение: экран панели управления …]»).

The note is never a sentence of the deck: its free place goes on the slide that says what the author wrote next to it,
described, so the image model draws into it (verstka/images). Slides the user dictated («Слайд N», or headings laid
out as written) carry their notes in their own text (planning/faithful.py); this module serves the briefs whose slides
are cut by the architect (planning/agent.py) or by the rules planner (planning/outline.py). Before it, the live run of
2026-10-07 made a slide «Панель показывает три ключевых параметра» out of the note, and the deck had no picture.
"""

from __future__ import annotations

import re
from typing import Any

from verstka.planning import heuristics as H

# a bracketed note on a line of its own («[Место под изображение: экран панели …]», a note of several sentences too)
_PICTURE_NOTE_RE = re.compile(r"^[ \t]*\[(?P<body>[^\[\]]{3,})\][ \t]*[.;]?[ \t]*$", re.M)
_FRAMES = {"title", "agenda", "section", "thanks"}
_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.I)


def numbered_sentences(text: str) -> list[str]:
    """The brief's sentences in order (a list line is a sentence of its own), for the architect's numbers."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or re.match(r"^\|?\s*:?-{2,}", line):
            continue
        out.extend(H.split_sentences(line) or [line])
    return out


def picture_notes(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """The brief without its bracketed notes about a picture, and each note as (how many of the brief's sentences come
    before it, what the picture shows, the words after the note's label — «фото офиса добавлю сам» keeps the place for
    the author's own photo; the label «Место под изображение» itself never does). Notes about a chart or a table stay
    in the text: they ask for a form of the slide's own data."""
    from verstka.planning.faithful import _note_part

    text = text or ""
    kept: list[str] = []
    notes: list[tuple[int, str, str]] = []
    last = 0
    for m in _PICTURE_NOTE_RE.finditer(text):
        part = _note_part(m.group("body"))
        what = H.strip_end((part.text or part.label).strip())
        if part.kind != "image" or not what:
            continue
        kept.append(text[last:m.start()])
        notes.append((len(numbered_sentences("".join(kept))), H.cap_first(what), part.text.strip() if part.label else ""))
        last = m.end()
    kept.append(text[last:])
    return "".join(kept), notes


def _own(words: str, slide_text: str) -> bool:
    from verstka.planning.faithful import own_photo

    return bool(words and own_photo(words)) or own_photo(slide_text)


def place_pictures(units: list[Any], spans: dict[str, set[int]], notes: list[tuple[int, str, str]], warnings: list[str]) -> None:
    """The architect's slides (planning/agent.py `_Unit`): each note goes to the slide that holds the sentence just
    before it (the picture shows what the author wrote above it), else to the slide of the next sentence, else to the
    first slide still without a picture; one picture per slide, never on the cover or the closing slide."""
    for before, hint, words in notes:
        free = [u for u in units if not u.frame and not u.photo_hint]
        host = next((u for u in free if before in spans.get(u.key, set())), None)
        if host is None:
            later = [(min(n for n in spans.get(u.key, set()) if n > before), k, u) for k, u in enumerate(free) if any(n > before for n in spans.get(u.key, set()))]
            host = min(later, key=lambda x: (x[0], x[1]))[2] if later else (free[0] if free else None)
        if host is None:
            warnings.append(f"picture note left out (every slide already has a picture): {hint[:60]}")
            continue
        host.photo_hint = hint
        host.photo_own = _own(words, host.text)


def _stems(text: str) -> set[str]:
    return {w[:6] for w in _WORD_RE.findall((text or "").lower().replace("ё", "е"))}


def _slide_text(s: Any) -> str:
    c = s.content
    parts = [s.headline or "", s.subtitle or "", *c.bullets, *c.paragraphs]
    parts += [f"{it.title} {it.text} {' '.join(it.bullets)}" for it in [*c.items, *c.columns]]
    parts += [f"{n.value} {n.label}" for n in c.numbers]
    if c.table is not None:
        parts += [" ".join(c.table.columns), *(" ".join(r) for r in c.table.rows)]
    return " ".join(parts)


def place_pictures_by_text(outline: Any, text: str, notes: list[tuple[int, str, str]], warnings: list[str]) -> None:
    """The rules planner's slides: each note's place goes on the slide whose words share the most with the sentence
    just before the note (else the one just after it); with no such slide, on the content slide at the note's place
    in the brief. One picture per slide, never on a frame slide (cover, agenda, divider, closing)."""
    sents = numbered_sentences(text)
    for before, hint, words in notes:
        free = [s for s in outline.slides if s.kind.value not in _FRAMES and not s.content.photo_slot]
        if not free:
            warnings.append(f"picture note left out (every slide already has a picture): {hint[:60]}")
            continue
        host = None
        for anchor in (sents[before - 1] if before >= 1 else "", sents[before] if before < len(sents) else ""):
            want = _stems(anchor)
            scored = [(len(want & _stems(_slide_text(s))), -k, s) for k, s in enumerate(free)] if want else []
            best = max(scored, key=lambda x: (x[0], x[1]), default=None)
            if best is not None and best[0] >= 2:
                host = best[2]
                break
        if host is None:
            share = before / max(1, len(sents))
            host = free[min(len(free) - 1, int(share * len(free)))]
        c = host.content
        c.photo_slot = "Изображение"
        c.photo_hint = hint
        c.photo_own = _own(words, _slide_text(host))


# a slide with a picture gives it about half of its width: the text beside it stays short (VK's experts: a picture
# that fits helps, one squeezed beside a full slide harms — the owner's run of 17.10 had a picture beside a lead, four
# figures and two bullets)
PICTURE_MAX_POINTS = 4
PICTURE_MAX_NUMBERS = 3
PICTURE_MAX_CHARS = 420


def room_for_picture(lead: str = "", points: list[str] | None = None, numbers: list[str] | None = None, *, other: bool = False) -> bool:
    """A slide of the writer keeps its picture: no timeline, steps, table, chart or formula beside it (`other`), at most
    4 points or 3 figures, and the slide's words short enough for half of it."""
    points = [p for p in (points or []) if (p or "").strip()]
    numbers = [n for n in (numbers or []) if (n or "").strip()]
    if other or len(points) > PICTURE_MAX_POINTS or len(numbers) > PICTURE_MAX_NUMBERS or (points and len(numbers) > 2):
        return False
    return len(" ".join([lead or "", *points, *numbers])) <= PICTURE_MAX_CHARS


_NOTE_LINE_RE = re.compile(r"^\s*\[(?P<body>[^\[\]]{3,})\]\s*[.;]?\s*$")


def is_picture_note(line: str) -> bool:
    """A line that is the author's bracketed note about a picture («[Место под изображение: фасад офиса]»)."""
    from verstka.planning.faithful import _note_part

    m = _NOTE_LINE_RE.match(line or "")
    return bool(m) and _note_part(m.group("body")).kind == "image"


def strip_picture_notes(outline: Any, warnings: list[str]) -> None:
    """A picture's note never stands on a slide as its text: the designer copied it into the bullets of the live run
    of 18.10 («[Место под изображение: стеклянный фасад …]» as the slide's second point) — the place keeps it."""
    for s in getattr(outline, "slides", None) or []:
        c = s.content
        lines = [*c.bullets, *c.paragraphs, *(it.title for it in c.items), s.takeaway or "", s.subtitle or ""]
        if not any(is_picture_note(x) for x in lines):
            continue
        c.bullets = [x for x in c.bullets if not is_picture_note(x)]
        c.paragraphs = [x for x in c.paragraphs if not is_picture_note(x)]
        c.items = [it for it in c.items if not is_picture_note(it.title)]
        if is_picture_note(s.takeaway or ""):
            s.takeaway = None
        if is_picture_note(s.subtitle or ""):
            s.subtitle = None
        warnings.append(f"slide {s.id}: the picture's note left the slide's text")
