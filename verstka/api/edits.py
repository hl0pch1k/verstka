"""The chat agent's edits of a finished deck: what the person asks («на слайде 3 покажи расходы таблицей», «убери
слайд 5», «поменяй местами 2 и 3», «перенеси слайд 6 после второго», «на слайде 6 оставь место под фото», «верни как
было») read into one operation on one variant — the one on screen.

Moving and removing slides and undoing are exact operations on the variant's plan; everything else about a slide is the
slide designer's job (planning/revise.py): it redesigns that slide by the request, the compiler and grounding check it
against the brief like any slide of the agent. The variant is rendered again and its previous version kept
(pipeline/revise.py)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

_ORDINALS = {
    "перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8, "девят": 9, "десят": 10,
    "одиннадцат": 11, "двенадцат": 12,
}
_ORD_RX = "|".join(sorted(_ORDINALS, key=len, reverse=True))
_NUM = r"(\d{1,2})(?:\s*-?\s*(?:й|я|е|м|ом|ем|ой|ый|ий|го))?"

# a slide named by its number or its place: «слайд 3», «на слайде №3», «3-й слайд», «на третьем слайде», «последний»
_SLIDE_REFS = [
    re.compile(r"слайд\w*\s*(?:№\s*)?(\d{1,2})\b", re.I),
    re.compile(rf"\b{_NUM}\s+слайд", re.I),
    re.compile(rf"\b({_ORD_RX})\w*\s+слайд", re.I),
    re.compile(r"\b(последн)\w*\s+слайд|слайд\w*\s+(последн)\w*", re.I),
]
_THIS_RX = re.compile(r"\b(этот|этом|этого|эту|этой|здесь|тут|текущ\w*)\b", re.I)

# the verbs of a change: a request that has one of them and names a slide (or the slide on screen) is an edit
EDIT_RX = re.compile(
    r"\b(сделай|сделать|замени|заменить|покажи|показать|перепиши|переписать|сократи|сократить|добавь|добавить|убери|убрать|удали|"
    r"удалить|поменяй|поменять|помен\w+|измени|изменить|переделай|переделать|преврати|оформи|выдели|выделить|увеличь|уменьши|"
    r"перенеси|перенести|передвинь|поставь|перемести|верни|вернуть|отмени|отменить|откати|переформулируй|упрости|разбей|"
    r"раздели|объедини|дополни|подчеркни|вынеси|нарисуй|представь|перестрой|исправь\s+(?:заголов|текст|вывод|слайд))",
    re.I,
)
_UNDO_RX = re.compile(r"^\s*(?:пожалуйста\s*,?\s*)?(верни|вернуть|откати|отмени|отменить)\b(?!.*\bслайд\w*\s*\d)", re.I)
_DELETE_RX = re.compile(
    rf"\b(убери|удали|выкинь|выбрось|убрать|удалить)\s+(?:этот\s+|весь\s+)?(?:{_NUM}\s+|(?:{_ORD_RX})\w*\s+|последн\w*\s+)?"
    r"слайд\w*(?:\s*(?:№\s*)?\d{1,2})?(?:\s+целиком)?\s*[.!]?\s*$",
    re.I,
)
_SWAP_RX = re.compile(rf"помен\w*\s+(?:их\s+)?местами\s+(?:слайды\s+)?{_NUM}\s*(?:слайд\w*\s+)?и\s+{_NUM}", re.I)
_MOVE_RX = re.compile(
    rf"\b(?:перенеси|передвинь|поставь|перемести|перенести|переместить)\s+(?:слайд\w*\s*(?:№\s*)?)?{_NUM}(?:\s+слайд\w*)?\s+"
    rf"(после|перед|в\s+начало|в\s+конец)(?:\s+(?:слайда?\s*(?:№\s*)?)?(?:{_NUM}|({_ORD_RX})\w*))?",
    re.I,
)


@dataclass
class EditRequest:
    """One operation: undo | delete | swap | move | slide (the designer changes the slide by `text`)."""

    kind: str
    slides: list[int] = field(default_factory=list)  # 1-based positions in the variant
    target: Optional[int] = None  # move: the new position (1-based, after the move)
    text: str = ""


def slide_refs(message: str, total: int) -> list[int]:
    """The slides a message names, in order, 1-based; «последний» is the last one."""
    found: list[tuple[int, int]] = []
    for rx in _SLIDE_REFS:
        for m in rx.finditer(message):
            g = next((x for x in m.groups() if x), None)
            if g is None:
                continue
            if g.isdigit():
                n = int(g)
            elif g.lower().startswith("последн"):
                n = total
            else:
                n = next((v for k, v in _ORDINALS.items() if g.lower().startswith(k)), 0)
            if 1 <= n <= max(total, 1):
                found.append((m.start(), n))
    out: list[int] = []
    for _, n in sorted(found):
        if n not in out:
            out.append(n)
    return out


def looks_like_edit(message: str) -> bool:
    """A change of the deck on screen rather than a new deck or a question («почему слайд 3 такой» is a question)."""
    text = message.strip()
    if len(text) > 400 or re.search(r"презентац|колод", text, re.I):
        return False
    from verstka.planning.brief_structure import is_photo_instruction, photo_dropped

    # «на слайде 6 оставь место под фото», «убери место под фото»: the free place for the person's own photo
    return bool(EDIT_RX.search(text) or _UNDO_RX.search(text) or is_photo_instruction(text) or photo_dropped(text))


def parse_edit(message: str, on_screen: Optional[int], total: int) -> Optional[EditRequest]:
    """The operation a chat message asks for on a deck of `total` slides whose slide `on_screen` the person sees; None
    when it names no slide and none is on screen."""
    text = " ".join(message.split())
    if _UNDO_RX.search(text):
        return EditRequest(kind="undo", text=text)
    m = _SWAP_RX.search(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= total and 1 <= b <= total and a != b:
            return EditRequest(kind="swap", slides=[a, b], text=text)
    m = _MOVE_RX.search(text)
    if m:
        src = int(m.group(1))
        where = m.group(2).lower()
        ref = m.group(3) or m.group(4)
        dst_ref = None
        if ref:
            dst_ref = int(ref) if ref.isdigit() else next((v for k, v in _ORDINALS.items() if ref.lower().startswith(k)), None)
        if 1 <= src <= total:
            if where.startswith("в") and "начало" in where:
                target = 2  # after the cover
            elif where.startswith("в"):
                target = total
            elif dst_ref and 1 <= dst_ref <= total:
                # the new position counted after the slide leaves its place
                after = where == "после"
                target = dst_ref + (1 if after else 0) - (1 if src < dst_ref else 0)
            else:
                target = None
            if target is not None and target != src:
                return EditRequest(kind="move", slides=[src], target=max(1, min(total, target)), text=text)
    refs = slide_refs(text, total)
    if not refs and on_screen and _THIS_RX.search(text):
        refs = [on_screen]
    if _DELETE_RX.search(text):
        return EditRequest(kind="delete", slides=refs or ([on_screen] if on_screen else []), text=text) if (refs or on_screen) else None
    if not refs and on_screen:
        refs = [on_screen]
    if not refs:
        return None
    return EditRequest(kind="slide", slides=refs[:1], text=text)
