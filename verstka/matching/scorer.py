"""Explainable scoring of a template pattern for an outline slide."""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Optional

from verstka.matching.compat import kind_compat, needed_chars, needed_items
from verstka.planning.strategies import Strategy
from verstka.ru import bind_compounds
from verstka.schemas.common import Family, PatternKind, SlotRole
from verstka.schemas.outline import OutlineSlide
from verstka.schemas.template import Pattern, TemplateManifest

_GROUP_ROLES = {SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.icon}
_STANDALONE_KINDS = {PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.quote}
_CONTENT_ROLES = (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption)
_NUMBER_KINDS = {PatternKind.stat_row, PatternKind.big_number}


_BOOKEND_KINDS = (PatternKind.title, PatternKind.section, PatternKind.thanks)
# texts of a cover or closing sample that stand for data a deck never has (a speaker, his photo, a QR code): the
# renderer removes them with their frames, so they neither count as clutter nor as competition for the heading
_PLACEHOLDER_RE = re.compile(r"имя|фамили|должност|спикер|speaker|\bname\b|position|вставить|insert|\bqr\b|qr-|фото|photo|логотип|logo", re.I)
# words a line must not end on (a preposition, a conjunction): they are bound to the next word with a no-break space
_BOUND_WORDS = frozenset("в во на за с со к ко по о об от до из у и а но не ни да же ли бы".split())


@dataclass
class ScoreResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    fit: dict = field(default_factory=dict)


def is_placeholder_text(text: Optional[str]) -> bool:
    """A sample text that asks for a speaker, a photo, a QR code or a logo."""
    return bool(text and _PLACEHOLDER_RE.search(text))


def bind_short_words(text: str) -> str:
    """No-break spaces after one- and two-letter words and prepositions («в VK», «и план»), so that a display line
    never ends on one."""
    words = text.split(" ")
    out = []
    # a name in guillemets of up to three words («Точка кофе») is one unit: never broken across lines
    quoted: set[int] = set()
    i = 0
    while i < len(words):
        if words[i].startswith("«") and not words[i].rstrip(",.:;").endswith("»"):
            j = next((k for k in range(i + 1, min(i + 3, len(words))) if words[k].rstrip(",.:;").endswith("»")), None)
            if j is not None:
                quoted.update(range(i, j))
                i = j
        i += 1
    for i, w in enumerate(words):
        out.append(w)
        if i < len(words) - 1:
            bare = w.lower().strip("«»\"(),.:;")
            nxt = words[i + 1]
            if i in quoted:
                out.append("\u00a0")
            elif nxt and not any(ch.isalnum() for ch in nxt):
                out.append("\u00a0")  # a dash or a separator stays at the end of its line, never opens the next one
            elif bare and any(ch.isalnum() for ch in bare) and (len(bare) <= 2 or bare in _BOUND_WORDS) and w[-1:] not in ",.:;":
                out.append("\u00a0")
            else:
                out.append(" ")
    return bind_compounds("".join(out))


def display_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float) -> list[str]:
    """Greedy wrap the way PowerPoint and LibreOffice break a heading: at ordinary spaces and after hyphens, never at a
    no-break space. A word wider than the line is kept whole (the caller treats that as not fitting)."""
    from verstka.rendering.fonts import text_width_pt

    def width(s: str) -> float:
        return text_width_pt(s.replace("\u00a0", " "), family, size_pt, bold)

    tokens: list[str] = []  # pieces that may start a line; each keeps its trailing separator
    for word in text.replace("\n", " ").split(" "):
        if not word:
            continue
        parts = re.split(r"(?<=[^\s\u00a0-]-)(?=[^\s\u00a0\u2060-])", word)
        tokens.extend(parts[:-1])
        tokens.append(parts[-1] + " ")
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        cand = cur + tok
        if cur and width(cand.rstrip()) > width_pt:
            lines.append(cur.rstrip())
            cur = tok
        else:
            cur = cand
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def display_fit(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float, max_lines: int, scale: Optional[list[float]] = None, floor: float = 0.45, word_room: float = 1.0) -> tuple[float, int]:
    """The largest size ≤ `size_pt` at which a display heading takes at most `max_lines` lines of `width_pt` with no
    word wider than `word_room` of the line: (size, lines). Steps follow the template's own sizes where they fall in
    the range, with 5 % steps between them; below `floor` × size the smallest candidate is returned with its line
    count."""
    from verstka.rendering.fonts import text_width_pt

    cands = {round(size_pt, 2)}
    cands |= {round(s, 2) for s in (scale or []) if floor * size_pt <= s < size_pt}
    k = 0.95
    while k >= floor - 1e-9:
        cands.add(round(size_pt * k, 1))
        k -= 0.05
    words = [w for w in re.split(r"[\s\u00a0]+|(?<=-)(?!\u2060)", text) if w]
    last = (round(size_pt * floor, 1), 99)
    for s in sorted(cands, reverse=True):
        if any(text_width_pt(w, family, s, bold) > width_pt * word_room for w in words):
            last = (s, 99)
            continue
        n = len(display_lines(text, family, s, bold, width_pt))
        last = (s, n)
        if n <= max_lines:
            return s, n
    return last


def _break_tokens(text: str) -> list[str]:
    """Pieces a display line may start with, as display_lines breaks: each keeps its trailing space."""
    tokens: list[str] = []
    for word in text.replace("\n", " ").split(" "):
        if not word:
            continue
        parts = re.split(r"(?<=[^\s\u00a0-]-)(?=[^\s\u00a0\u2060-])", word)
        tokens.extend(parts[:-1])
        tokens.append(parts[-1] + " ")
    return tokens


# a word that closes a phrase («итоги пилота: …», «проблема — решение», a comma): a line likes to end after it
_PHRASE_END = re.compile(r"[:;,\u2014\u2013.!?\u00bb)]$")
# a Russian adjective or participle ending: it belongs with the noun that follows («умные / напоминания» reads broken)
_ADJ_END = re.compile(r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ого|его|ому|ему|ую|юю|ых|их|ыми|ими)$", re.I)


def balanced_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float, n_lines: int) -> Optional[list[str]]:
    """The heading broken into exactly `n_lines` lines of at most `width_pt`, the way a typesetter breaks a display
    heading: lines of even length, never a lone short word on the last line, a break after a colon, a dash or a comma
    rather than inside a phrase, never between an adjective and its noun. None when no such break exists."""
    from itertools import combinations

    from verstka.rendering.fonts import text_width_pt

    tokens = _break_tokens(text)
    k = len(tokens)
    if n_lines <= 1 or k < n_lines:
        return None
    cache: dict[tuple[int, int], float] = {}

    def width(a: int, b: int) -> float:
        if (a, b) not in cache:
            cache[(a, b)] = text_width_pt("".join(tokens[a:b]).rstrip().replace("\u00a0", " "), family, size_pt, bold)
        return cache[(a, b)]

    best: Optional[tuple[float, tuple[int, ...]]] = None
    for cuts in combinations(range(1, k), n_lines - 1):
        bounds = (0, *cuts, k)
        ws = [width(a, b) for a, b in zip(bounds, bounds[1:])]
        top = max(ws)
        if top > width_pt:
            continue
        cost = (top - min(ws)) / top if top else 0.0
        if bounds[-1] - bounds[-2] == 1 and ws[-1] < 0.45 * top:
            cost += 0.3  # a lone short word on the last line
        for c in cuts:
            word = tokens[c - 1].rstrip()
            if _PHRASE_END.search(word):
                cost -= 0.2
            elif _ADJ_END.search(word.lower()) and len(word) > 3 and tokens[c][:1].isalpha():
                cost += 0.15
        if best is None or cost < best[0] - 1e-9:
            best = (cost, bounds)
    if best is None:
        return None
    b = best[1]
    return ["".join(tokens[x:y]).rstrip() for x, y in zip(b, b[1:])]


def awkward_breaks(lines: list[str]) -> int:
    """How many line ends of a display heading split an adjective from its noun («Умные / напоминания»)."""
    n = 0
    for a, b in zip(lines, lines[1:]):
        words = a.replace("\u00a0", " ").split()
        last = words[-1] if words else ""
        if len(last) > 3 and _ADJ_END.search(last.lower()) and not _PHRASE_END.search(last) and b[:1].isalpha():
            n += 1
    return n


_TITLE_SPLIT = re.compile(r":\s+|\s+[—–]\s+")


def split_display_title(text: str) -> tuple[str, Optional[str]]:
    """«Умные напоминания в VK WorkSpace: итоги пилота и план запуска» → the cover heading «Умные напоминания в VK
    WorkSpace» and its subtitle «Итоги пилота и план запуска». A heading of two phrases joined by a colon or a dash is
    a title and a subtitle set on one line; on a cover each gets its own size. Unsplit when either part is a single
    word or the head is too short to stand as a title."""
    t = " ".join((text or "").split())
    m = _TITLE_SPLIT.search(t)
    if not m:
        return t, None
    head, tail = t[: m.start()].strip(), t[m.end() :].strip()
    if len(head.split()) < 2 or len(head) < 10 or len(tail.split()) < 2:
        return t, None
    return head, tail[:1].upper() + tail[1:]


def bookend_max_lines(kind: PatternKind, slot) -> int:
    """How many lines the heading of a cover or a divider (3) or of a closing slide (2) may take."""
    if kind == PatternKind.title:
        return 3
    if kind == PatternKind.section:
        return 3
    return 2


def _bookend_title_fit(slide: OutlineSlide, pattern: Pattern, manifest: TemplateManifest) -> Optional[tuple[float, int, float, object]]:
    """(fitted size, lines, fitted / sample size, title slot) of the slide heading set in the sample's title box —
    measured, not counted in characters: a cover title may take three lines at up to 0.85 of the sample size."""
    titles = [s for s in pattern.slots if s.role == SlotRole.title]
    if not titles or not slide.headline:
        return None
    t = max(titles, key=lambda s: s.bbox.area)
    typo = manifest.tokens.typography
    size0 = t.style.size_pt or typo.size_for("display", typo.size_for("h1", 24.0) * 1.6)
    x2 = t.bbox.x + t.bbox.w
    for c in manifest.tokens.chrome:
        # a picture of the layout that covers half of the heading box (a placeholder sized for the whole slide next
        # to a supergraphic) is not meant to be written over: the heading ends where it begins
        b = c.bbox
        if c.kind == "pic" and pattern.layout_part and c.source == f"layout:{pattern.layout_part}" and b.w * b.h < 0.6:
            if b.y < t.bbox.y + t.bbox.h and b.y + b.h > t.bbox.y and t.bbox.x + 0.12 < b.x < x2 and x2 - b.x >= 0.4 * t.bbox.w:
                x2 = b.x - 0.015
    # measured as the renderer sets it: 5 % of the line kept free, no word wider than 3/4 (bold) or 4/5 of the line
    w_pt = ((x2 - t.bbox.x) * manifest.slide_size.w / 12700 - 14.4) * 0.95
    if w_pt <= 20:
        return None
    scale = sorted({float(x) for x in (typo.sizes_used or [])} | {s.size_pt for s in typo.scale})
    head = split_display_title(slide.headline)[0] if slide.kind == PatternKind.title else slide.headline.strip()
    bold = bool(t.style.bold)
    size, lines = display_fit(bind_short_words(head), t.style.font_family or typo.primary_family, size0, bold, w_pt, bookend_max_lines(slide.kind, t), scale, word_room=0.75 if bold else 0.8)
    return size, lines, size / size0 if size0 else 1.0, t


def same_words(a: Optional[str], b: Optional[str]) -> bool:
    """Whether a heading repeats the sample's own text («Спасибо за внимание» on a «Спасибо за внимание!» sample)."""
    wa = set(re.findall(r"\w{3,}", (a or "").lower()))
    wb = set(re.findall(r"\w{3,}", (b or "").lower()))
    return bool(wa and wb) and len(wa & wb) >= 0.5 * max(len(wa), len(wb))


def _slot_capacity(pattern: Pattern, role: SlotRole) -> int:
    """Capacity for one instance of the role (first cell for grouped roles, sum for standalone roles)."""
    slots = [s for s in pattern.slots if s.role == role]
    if not slots:
        return 0
    if role in _GROUP_ROLES:
        grouped = [s for s in slots if s.group_id]
        return max((s.capacity.max_chars for s in (grouped or slots)), default=0)
    return sum(s.capacity.max_chars for s in slots)


def _number_holders(pattern: Pattern, group) -> int:
    """How many figures the clone renderer can place: the cells of the text group (grown up to max_n), otherwise the standalone number slots.

    Numbers are never merged, so every figure beyond this count is lost.
    """
    if group is not None:
        return max(len(group.member_shape_ids), group.max_n)
    return sum(1 for s in pattern.slots if s.role == SlotRole.number and not s.group_id)


def score_pattern(
    slide: OutlineSlide,
    pattern: Pattern,
    manifest: TemplateManifest,
    strategy: Strategy,
    prev_family: Optional[Family] = None,
    recent_ids: Optional[list[str]] = None,
    cover: Optional[Pattern] = None,
    divider: Optional[Pattern] = None,
) -> ScoreResult:
    """How well `pattern` suits `slide` (0…1.2) with the reasons. `cover` is the sample the deck's cover was cloned
    from: a closing slide answers it (same ground, ideally the same layout), the way a designer closes a deck, and a
    divider is set a step below it. `divider` is the sample of the deck's first section divider: every divider of a
    deck looks the same."""
    recent_ids = recent_ids or []
    reasons: list[str] = []
    fit: dict = {}
    if pattern.reference:
        return ScoreResult(0.0, [f"служебный слайд шаблона: {pattern.reference}"], fit)
    kind = kind_compat(slide.kind, pattern.kind)
    if kind <= 0:
        return ScoreResult(0.0, [f"тип {pattern.kind.value} несовместим с {slide.kind.value}"], fit)
    reasons.append(f"тип {pattern.kind.value} для {slide.kind.value}: {kind:.1f}")
    has_title_slot = any(s.role == SlotRole.title for s in pattern.slots)
    if slide.headline and not has_title_slot:
        if slide.kind in (PatternKind.title, PatternKind.section, PatternKind.thanks):
            # the heading of such a slide is its whole content: a sample whose title is baked into the picture is unusable
            return ScoreResult(0.0, reasons + ["в образце нет слота под заголовок (текст зашит в картинку или отсутствует)"], fit)
        if slide.kind != PatternKind.quote:
            kind *= 0.3
            reasons.append("в образце нет слота под заголовок: заголовок слайда потеряется")

    # chart / table / quote need room
    slide_kind = slide.kind
    data_room: Optional[float] = None
    if slide_kind in (PatternKind.chart, PatternKind.table) or slide.content.chart is not None or slide.content.table is not None:
        # the data object needs a free area: a sample chart/table (cleared by the renderer), a picture or a big text box
        room = max((s.bbox.area for s in pattern.slots if s.role in (SlotRole.image, SlotRole.body, SlotRole.bullet_list)), default=0.0)
        if pattern.kind in (PatternKind.chart, PatternKind.table):
            room = max(room, 0.35)
        data_room = min(1.0, room / 0.3)
        if room < 0.12:
            kind *= 0.3
            data_room = 0.2
            reasons.append("нет крупной области под диаграмму или таблицу")
        else:
            reasons.append(f"область под данные: {room:.0%} слайда")
    if slide_kind == PatternKind.quote and slide.content.quote:
        cap_q = max((s.capacity.max_chars for s in pattern.slots if s.role in (SlotRole.body, SlotRole.bullet_list, SlotRole.card_body, SlotRole.subtitle)), default=0)
        if cap_q < len(slide.content.quote) * 0.8:
            kind *= 0.5
            reasons.append("слоты слишком малы для цитаты")
        if any(len(g.member_shape_ids) >= 3 for g in pattern.repeat_groups):
            kind *= 0.4
            reasons.append("список ячеек не подходит для цитаты")

    # capacity in items
    n = needed_items(slide)
    cap = 1.0
    text_group_roles = (SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.bullet_list, SlotRole.body)
    groups = [g for g in pattern.repeat_groups if any(s.group_id == g.id and s.role in text_group_roles for s in pattern.slots)]
    group = max(groups, key=lambda g: len(g.member_shape_ids), default=None)
    if n >= 2:
        if group is not None:
            n_cells = len(group.member_shape_ids)
            fit["items"] = f"{n}/{group.max_n}"
            if group.min_n <= n <= group.max_n:
                cap = 1.0
                reasons.append(f"ёмкость группы {n} из {group.max_n} ячеек")
                if n_cells > 2 * n + 2:
                    cap = 0.75
                    reasons.append(f"группа из {n_cells} ячеек заметно больше нужных {n}")
            elif n > group.max_n:
                cap = 0.15 if n > group.max_n + 1 else 0.4
                reasons.append(f"не хватает ячеек: нужно {n}, максимум {group.max_n}")
            if group.axis == "grid" and group.rows * group.cols > n_cells and n < n_cells:
                # cells set in a zigzag (LCT roadmap: three above, two below, joined by lines): with a cell left
                # empty the figure breaks — a hole in the zigzag and connectors leading nowhere
                cap = min(cap, 0.55)
                reasons.append("ячейки стоят зигзагом: с пустой ячейкой макет развалится")
            if group.cell_bbox.area < 0.02 and slide_kind in (PatternKind.cards, PatternKind.process, PatternKind.comparison, PatternKind.team, PatternKind.two_column):
                cap = min(cap, 0.2)
                reasons.append("ячейки слишком малы для карточек")
        else:
            role_slots = sum(1 for s in pattern.slots if s.role in (SlotRole.card_title, SlotRole.number, SlotRole.bullet_list, SlotRole.body))
            if slide.kind in (PatternKind.bullets, PatternKind.agenda) and any(s.role == SlotRole.bullet_list for s in pattern.slots):
                cap = 1.0
                reasons.append("список помещается в один слот")
            elif role_slots >= n:
                cap = 0.8
                reasons.append(f"{role_slots} отдельных слотов под {n} элементов")
            else:
                cap = 0.25
                reasons.append(f"нет повторяющейся группы под {n} элементов")
            fit["items"] = f"{n}/{role_slots}"

    if data_room is not None and n < 2:
        cap = data_room  # no items to count: the capacity of such a slide is the room for its chart or table
    # text fit
    worst = 0.0
    bookend = slide.kind in _BOOKEND_KINDS
    title_fit = _bookend_title_fit(slide, pattern, manifest) if bookend else None
    for role_name, need in needed_chars(slide).items():
        role = SlotRole(role_name)
        if title_fit is not None and role == SlotRole.title:
            # the heading of a cover is measured in its box: three lines at 0.85 of the sample size are a perfect fit
            # below that it still reads as a cover while it stays a display size, clearly above the slide headings
            size_fit, lines_fit, ratio_fit, _ = title_fit
            h1 = manifest.tokens.typography.size_for("h1", 0.0)
            if ratio_fit >= 0.85 - 1e-6:
                ratio = 1.0
            elif ratio_fit >= 0.7 or (h1 and size_fit >= 1.2 * h1):
                ratio = 1.15
            elif not h1 or size_fit >= h1:
                ratio = 1.5
            else:
                ratio = 2.0
            fit["title_fit"] = f"{size_fit:g} пт, строк {lines_fit}"
            worst = max(worst, ratio)
            if ratio > 1.0:
                fit[f"overflow_{role_name}"] = round(ratio, 2)
            continue
        if bookend and role == SlotRole.subtitle and any(s.role == SlotRole.subtitle for s in pattern.slots):
            need = min(need, _slot_capacity(pattern, role))  # the subtitle box is re-set under the heading: it may wrap
        capacity = _slot_capacity(pattern, role)
        if capacity == 0:
            # bullets may go into a body slot and vice versa
            alt = {SlotRole.bullet_list: SlotRole.body, SlotRole.body: SlotRole.bullet_list, SlotRole.subtitle: SlotRole.body, SlotRole.card_body: SlotRole.body}.get(role)
            capacity = _slot_capacity(pattern, alt) if alt else 0
        if capacity == 0:
            ratio = 0.0 if need == 0 else (0.5 if role in (SlotRole.subtitle, SlotRole.number_label) else 2.0)
        else:
            ratio = need / capacity
        worst = max(worst, ratio)
        if ratio > 1.0:
            fit[f"overflow_{role_name}"] = round(ratio, 2)
    fit["text_ratio"] = round(worst, 2)
    # hard gates: a pattern without room for the slide's content would render a headline over stale sample shapes
    content = slide.content
    needed_roles = needed_chars(slide)
    content_need = sum(v for k, v in needed_roles.items() if k not in ("title", "subtitle"))
    content_cap = sum(s.capacity.max_chars for s in pattern.slots if s.role in _CONTENT_ROLES)
    has_data_object = content.chart is not None or content.table is not None
    if content_need > 0 and content_cap == 0 and not has_data_object:
        return ScoreResult(0.0, reasons + ["в паттерне нет ни одного слота под содержимое"], fit)
    if content_need > 0 and content_cap < 0.35 * content_need and not has_data_object:
        kind *= 0.3
        reasons.append(f"ёмкость слотов ({content_cap} симв.) намного меньше объёма содержимого ({content_need} симв.)")
    numbers_lost = False
    if slide_kind in _NUMBER_KINDS and n >= 1:
        holders = _number_holders(pattern, group)
        if n > holders:
            cap = 0.0
            kind *= 0.5
            numbers_lost = True
            reasons.append(f"числа не поместятся и будут потеряны: {n} чисел, мест {holders}")
        # figures set in rings drawn as pictures (VK Tech 41, 42, 45): only a percentage gets a true ring in their
        # place; «5 ч» or «31% → 12%» would stand without one next to a ring — the infographic falls apart
        rings = [s for s in pattern.slots if s.role == SlotRole.number and any(
            b.x <= s.bbox.x + s.bbox.w / 2 <= b.x + b.w and b.y <= s.bbox.y + s.bbox.h / 2 <= b.y + b.h
            and b.w * b.h >= 2 * s.bbox.w * s.bbox.h for b in pattern.decor_boxes)]
        values = [x.value for x in content.numbers]
        if rings and values and not all(re.match(r"^\s*\d{1,3}(?:[.,]\d+)?\s*%\s*$", v or "") for v in values):
            kind *= 0.6
            reasons.append("кольцевая инфографика, а числа — не проценты")
    n_items = needed_items(slide)
    text_slots = [s for s in pattern.slots if s.role in (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption)]
    if bookend:
        text_slots = [s for s in text_slots if not is_placeholder_text(s.sample_text)]  # speaker/QR blocks leave with their frames
    needed_slots = sum(1 for r in needed_roles if r not in ("title", "subtitle")) + max(n_items - 1, 0) * sum(1 for r in ("card_title", "card_body", "number", "number_label") if r in needed_roles)
    extra = max(len(text_slots) - max(needed_slots, 1), 0)
    clutter = min(0.3, 0.03 * extra)
    if clutter:
        reasons.append(f"{extra} лишних текстовых слотов останутся пустыми")
    if worst <= 1.0:
        text = 1.0
        reasons.append("текст помещается")
    elif worst <= 1.3:
        text = 0.7
        reasons.append(f"текст чуть длиннее ёмкости (×{worst:.2f}), нужен меньший кегль")
    elif worst <= 1.8:
        text = 0.4
        reasons.append(f"текст заметно длиннее ёмкости (×{worst:.2f}), потребуется сокращение")
    else:
        text = 0.15
        reasons.append(f"текст не помещается (×{worst:.2f})")
    # a pattern that needs the text shrunk ×1.8 renders tiny type: that outweighs an exact kind match
    if worst > 1.8:
        kind *= 0.6
    elif worst > 1.3:
        kind *= 0.85

    # family continuity
    fam = 1.0
    if slide.kind not in _STANDALONE_KINDS and prev_family is not None and pattern.family != prev_family:
        fam = 0.5
        reasons.append(f"семья {pattern.family.value} отличается от предыдущего слайда")

    # covers and closing slides are single; the same divider for every section is the template's own rhythm — a
    # repeat only breaks ties between equally good dividers
    diversity = (0.0 if slide.kind in (PatternKind.title, PatternKind.thanks) else -0.04 if bookend else -0.15) if pattern.id in recent_ids else 0.0
    if diversity:
        reasons.append("паттерн уже использован недавно")
    # the strategy weighs which kinds of slides to plan; the sample of a cover, divider or closing slide is chosen on fit
    weight = strategy.weight(pattern.kind.value) if pattern.kind == slide.kind and not bookend else 1.0
    if weight != 1.0:
        reasons.append(f"вес стратегии {strategy.name} для типа: ×{weight:.2f}")
    # a large sample image (photo, screenshot, chart picture) that the content cannot replace would stay as stale sample content
    has_visual = bool(content.image_hint or content.chart is not None or content.table is not None)
    stale_images = [s for s in pattern.slots if s.role == SlotRole.image and s.bbox.area >= 0.12]
    if stale_images and not has_visual:
        kind *= 0.6
        reasons.append("крупная картинка-образец останется без замены")
    # a decorative picture in the middle of the content area (a chart snapshot, a KPI ring) says the sample's own story
    stale_decor = [b for b in pattern.decor_boxes if b.area >= 0.08 and 0.15 < b.y + b.h / 2 < 0.85 and 0.15 < b.x + b.w / 2 < 0.85]
    if stale_decor and not has_visual and not bookend:  # on a cover or divider the sample's art is the point
        kind *= 0.6
        reasons.append("крупная иллюстрация образца посреди слайда не относится к содержанию")
    # strategy flavour: visual favours decorated/illustrated samples, compact favours denser samples, structured plain ones
    n_decor = len(pattern.decor_assets) + sum(1 for s in pattern.slots if s.role in (SlotRole.icon, SlotRole.image))
    if strategy.name == "visual":
        style = 0.08 if n_decor >= 1 else 0.0
    elif strategy.name == "compact":
        style = 0.08 * min(len(text_slots) / 8.0, 1.0)
    else:
        style = 0.04 if n_decor == 0 else 0.0
    if style:
        reasons.append(f"стиль стратегии {strategy.name}: +{style:.2f}")
    if slide.kind in _STANDALONE_KINDS and slide.kind != PatternKind.quote:
        # a cover: the heading is the design — the bigger it is set (relative to the template's own scale) and the
        # fewer content boxes stand around it, the more the sample is a cover rather than a content page
        typo = manifest.tokens.typography
        titles = [x for x in pattern.slots if x.role == SlotRole.title]
        size = max((x.style.size_pt or 0.0 for x in titles), default=0.0)
        ref = typo.size_for("display", typo.size_for("h1", 24.0) * 1.6)
        if title_fit is not None:
            size = title_fit[0]  # the size the heading really gets, not the sample's
        others = sum(1 for x in pattern.slots if x.role in (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body) and not is_placeholder_text(x.sample_text))
        hero = 0.12 * min(size / ref, 1.0) - 0.03 * min(others, 4) if ref else 0.0
        style += hero
        reasons.append(f"обложка: заголовок {size:.0f} пт, других текстов {others}: {hero:+.2f}")
        h1 = typo.size_for("h1", 0.0)
        sample_size = max((x.style.size_pt or 0.0 for x in titles), default=0.0)
        if h1 and sample_size and sample_size < 1.15 * h1:
            # a heading at the size of a content heading: the sample is a content page, not a cover or a divider
            style -= 0.15
            reasons.append(f"заголовок образца ({sample_size:.0f} пт) не крупнее заголовка слайда ({h1:.0f} пт): это не обложка")
        photos = [x for x in pattern.slots if x.role == SlotRole.image and x.bbox.area >= 0.015]
        if photos and not content.image_hint:
            style -= 0.06
            reasons.append("место под фото спикера останется пустым и уйдёт: слайд без него беднее")
        if title_fit is not None and title_fit[1] >= 2 and (title_fit[3].style.align or "") == "ctr":
            style -= 0.12
            reasons.append("заголовок по центру в несколько строк читается хуже, чем выровненный влево")
        if same_words(slide.headline, next((x.sample_text for x in titles if x.sample_text), None)):
            style += 0.06
            reasons.append("образец сделан под этот же текст заголовка")
        if slide.kind == PatternKind.section and cover is not None:
            cover_size = max((x.style.size_pt or 0.0 for x in cover.slots if x.role == SlotRole.title), default=0.0)
            if pattern.id == cover.id or (cover_size and abs(sample_size - cover_size) <= 0.05 * cover_size):
                style -= 0.08
                reasons.append("разделитель того же кегля, что обложка, выглядит второй обложкой")
        if slide.kind == PatternKind.section and divider is not None and pattern.id == divider.id:
            style += 0.1
            reasons.append("все разделители колоды одинаковы")
        if slide.kind == PatternKind.thanks and cover is not None:
            echo = (0.05 if pattern.family == cover.family else 0.0) + (0.03 if pattern.layout_part and pattern.layout_part == cover.layout_part else 0.0)
            if echo:
                style += echo
                reasons.append(f"закрывает колоду в паре с обложкой (слайд {cover.source_slide}): {echo:+.2f}")
    # the strategy weight scales only the kind term, so it cannot lift a pattern with failed capacity above 1.0
    base = 0.45 * kind * weight + 0.25 * cap + 0.1 * text + 0.05 * fam + 0.1 * pattern.quality + diversity - clutter + style
    score = max(0.0, min(1.2, base))
    if numbers_lost and score >= strategy.synth_threshold:
        # losing a fact is worse than any synthesized stat row: such a pattern may stay an alternative but never wins over synth
        score = max(0.0, strategy.synth_threshold - 0.05)
        reasons.append(f"балл опущен ниже порога синтеза {strategy.synth_threshold:.2f}, чтобы не терять числа")
    return ScoreResult(round(score, 3), reasons, fit)
