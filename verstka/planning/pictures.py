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
