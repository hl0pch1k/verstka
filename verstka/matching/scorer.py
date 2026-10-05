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
from verstka.schemas.template import Pattern, Slot, TemplateManifest

_GROUP_ROLES = {SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.icon}
_STANDALONE_KINDS = {PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.quote}
_CONTENT_ROLES = (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption)
_NUMBER_KINDS = {PatternKind.stat_row, PatternKind.big_number}


_BOOKEND_KINDS = (PatternKind.title, PatternKind.section, PatternKind.thanks)
# a sample's place for a photo, a QR code or a logo («Вставить фото», «QR-код», «Insert photo»)
_PHOTO_PLACE_RE = re.compile(r"вставить|insert|\bqr\b|qr-|фото|photo|логотип|logo|иллюстрац|illustration", re.I)
# texts of a cover or closing sample that stand for data a deck never has (a speaker, his photo, a QR code): the
# renderer removes them with their frames, so they neither count as clutter nor as competition for the heading
_PLACEHOLDER_RE = re.compile(r"имя|фамили|должност|спикер|speaker|\bname\b|position|вставить|insert|\bqr\b|qr-|фото|photo|логотип|logo", re.I)
# words a line must not end on (a preposition, a conjunction): they are bound to the next word with a no-break space
_BOUND_WORDS = frozenset("в во на за с со к ко по о об от до из у и а но не ни да же ли бы".split())
# a figure is one unit on a display line: its thousands («120 000») and its unit («255 000 рублей», «42 %», «18,6 млрд»)
_DIGIT_GROUP_RE = re.compile(r"(?<=\d) (?=\d{3}(?!\d))")
_FIGURE_UNIT_RE = re.compile(r"(?<=\d) (?=(?:%|‰|₽|\$|€|руб|тыс|млн|млрд|трлн)(?![A-Za-z]))")


@dataclass
class ScoreResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    fit: dict = field(default_factory=dict)


def _cover_like(pattern: Pattern, manifest: TemplateManifest, sample_size: float) -> bool:
    """A sample is a cover by its own means, whatever the size of the content headings: its heading is a display size
    for the slide (≥ 7 % of the slide height — a template whose content headings are display-sized too, 88 pt on a
    15-inch slide, must not demote its real cover), or it is the first sample built on the title layout (ctrTitle
    placeholder or a layout of type «title»)."""
    if sample_size >= 0.07 * manifest.slide_size.h / 12700:
        return True
    first = next((p for p in sorted(manifest.patterns, key=lambda p: p.source_slide) if p.title_ph == "ctrTitle" or p.layout_type == "title"), None)
    return first is not None and first.id == pattern.id


def is_placeholder_text(text: Optional[str]) -> bool:
    """A sample text that asks for a speaker, a photo, a QR code or a logo."""
    return bool(text and _PLACEHOLDER_RE.search(text))


def bind_figures(text: str) -> str:
    """No-break spaces inside a figure and between a figure and its unit: «со 120 000 до 255 000 рублей» never breaks
    as «120 / 000» or «255 000 / рублей» (G1-16)."""
    if not text or not any(ch.isdigit() for ch in text):
        return text
    return _FIGURE_UNIT_RE.sub("\u00a0", _DIGIT_GROUP_RE.sub("\u00a0", text))


def bind_short_words(text: str) -> str:
    """No-break spaces after one- and two-letter words and prepositions («в VK», «и план»), so that a display line
    never ends on one; a figure keeps its thousands and its unit (`bind_figures`)."""
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
    return bind_compounds(bind_figures("".join(out)))


def display_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float, spc_pt: float = 0.0) -> list[str]:
    """Greedy wrap the way PowerPoint and LibreOffice break a heading: at ordinary spaces and after hyphens, never at a
    no-break space. A word wider than the line is kept whole (the caller treats that as not fitting). `spc_pt`: the
    heading's letter-spacing (a badge's title tracked 8 pt a letter)."""
    from verstka.rendering.fonts import text_width_pt

    def width(s: str) -> float:
        return text_width_pt(s.replace("\u00a0", " "), family, size_pt, bold, spc_pt=spc_pt)

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


def display_fit(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float, max_lines: int, scale: Optional[list[float]] = None, floor: float = 0.45, word_room: float = 1.0, spc_pt: float = 0.0) -> tuple[float, int]:
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
    # a word is what a line cannot break: words a no-break space binds («Точка кофе») are measured together, as the
    # renderer keeps them on one line
    words = [w for w in re.split(r"[ \t\r\n]+|(?<=-)(?!\u2060)", text) if w]
    last = (round(size_pt * floor, 1), 99)
    for s in sorted(cands, reverse=True):
        if any(text_width_pt(w, family, s, bold, spc_pt=spc_pt) > width_pt * word_room for w in words):
            last = (s, 99)
            continue
        n = len(display_lines(text, family, s, bold, width_pt, spc_pt=spc_pt))
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


def balanced_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float, n_lines: int, spc_pt: float = 0.0) -> Optional[list[str]]:
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
            cache[(a, b)] = text_width_pt("".join(tokens[a:b]).rstrip().replace("\u00a0", " "), family, size_pt, bold, spc_pt=spc_pt)
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


def cover_goal(slide: OutlineSlide) -> Optional[str]:
    """The cover's own line under its subtitle (Agent v2: the goal of the plan, «Цель: увеличить прибыль со 120 000 до
    255 000 рублей»): the first paragraph of a title slide's content. None on other slides or without one."""
    if slide.kind != PatternKind.title or not slide.content.paragraphs:
        return None
    first = " ".join((slide.content.paragraphs[0] or "").split())
    return first or None


def _needed_chars(slide: OutlineSlide) -> dict[str, int]:
    """needed_chars, less a cover's goal line: the renderer sets it under the subtitle on its own (a cover sample
    without a body box holds it as well as one with a speaker's name box)."""
    out = needed_chars(slide)
    goal = cover_goal(slide)
    if goal and "body" in out:
        out["body"] -= len(slide.content.paragraphs[0]) + 1
        if out["body"] <= 0:
            del out["body"]
    return out


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
    standalone = sum(1 for s in pattern.slots if s.role == SlotRole.number and not s.group_id)
    if group is not None:
        in_cells = any(s.group_id == group.id and s.role == SlotRole.number for s in pattern.slots)
        if not in_cells and standalone:
            # display figures of their own over a row of captions (VK Tech p42: «7» and «10» at 166 pt): the figures
            # stand in those, the captions only label them — a third figure would shrink into a caption box
            return standalone
        return max(len(group.member_shape_ids), group.max_n)
    return standalone


_MONEY_RE = re.compile(r"[₽$€£¥]|\bруб|\brub|\busd|\beur", re.I)


def photo_place(pattern: Pattern, pictures: Optional[list]) -> Optional[Slot]:
    """The sample's place for the user's own photo (`SlideContent.photo_slot`): its largest picture slot — a photo, a
    screenshot, a picture placeholder or a place drawn as a frame with «Вставить фото» — of 6 % of the slide and a
    quarter of its height and more; never the template's art (a 3D render) or a plate. None when it has none."""
    kinds = {getattr(x, "shape_id", None): getattr(x, "kind", None) for x in pictures or []}
    for s in sorted(pattern.slots, key=lambda x: -x.bbox.area):
        if s.role != SlotRole.image or s.bbox.area < 0.06 or s.bbox.h < 0.25:
            continue
        if kinds.get(s.shape_id) in ("art", "icon", "ground", "panel", "line", "bar"):
            continue
        return s
    return None


def pair_width(pattern: Pattern, pictures: Optional[list]) -> float:
    """How wide (share of the slide) the sample's place for data is — its drawn chart or table, or, on a chart sample,
    its chart pictures together (VK WorkSpace p20: two doughnuts side by side): a pair of charts stands there side by
    side."""
    widths = [pattern.data_box.w] if pattern.data_box is not None else []
    boxes = [x.box for x in pictures or [] if getattr(x, "kind", None) == "content" and x.box.area >= 0.05]
    if pattern.kind == PatternKind.chart:
        boxes += [s.bbox for s in pattern.slots if s.role == SlotRole.image and s.bbox.area >= 0.05] + [b for b in pattern.decor_boxes if b.area >= 0.05]
    if boxes:
        widths.append(max(b.x2 for b in boxes) - min(b.x for b in boxes))
    return max(widths, default=0.0)


def chart_picture_room(slide: OutlineSlide, pattern: Pattern, pictures: Optional[list]) -> float:
    """The area (share of the slide) of the sample's picture that shows a chart or data — `analysis.pictures` reads it
    as the sample's content, not as art — when the slide carries a chart or a table to put in its place; 0 otherwise.
    Covers, dividers and closing slides are never such samples."""
    if slide.content.chart is None and slide.content.table is None:
        return 0.0
    if pattern.kind in (PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.quote) or not pictures:
        return 0.0
    return max((p.area for p in pictures if p.kind == "content" and p.area >= 0.15), default=0.0)


def _gate_room(slide: OutlineSlide, pattern: Pattern, manifest: TemplateManifest) -> list[str]:
    """What the render's gate will find without room, read off the sample's own boxes (a soft estimate — the render
    squeezes the content for the conclusion): a content slide's subtitle on a sample without a subtitle box goes in
    the band between the heading's lines and the content (`clone_notes.place_lede`), its conclusion and footnote
    without a note box at the foot of the content or under the heading (`place_notes`). Office's samples took three
    slides with a subtitle «Цель — …» each and the gate turned all three down. Returns the reasons of the misses."""
    out: list[str] = []
    typo = manifest.tokens.typography
    fam = typo.primary_family
    safe = manifest.tokens.spacing.safe_area
    h_pt, w_pt = manifest.slide_size.h / 12700, manifest.slide_size.w / 12700
    title = next((x for x in pattern.slots if x.role == SlotRole.title), None)
    boxes = [x.bbox for x in pattern.slots if x.role in _CONTENT_ROLES or x.role == SlotRole.image]
    body = typo.size_for("body", 14.0)
    band = None
    if title is not None:
        size_t = title.style.size_pt or typo.size_for("h1", 28.0)
        n_t = len(display_lines(slide.headline or "", fam, size_t, True, max(title.bbox.w * w_pt - 14.4, 40.0))) or 1
        t_bottom = title.bbox.y + min(title.bbox.h, n_t * size_t * 1.2 / h_pt)
        under = [b for b in boxes if b.y >= title.bbox.y + 0.5 * title.bbox.h and b.x < title.bbox.x + title.bbox.w and b.x + b.w > title.bbox.x]
        band = min((b.y for b in under), default=safe.y + safe.h) - t_bottom
    sub = " ".join((slide.subtitle or "").split())
    if sub and band is not None and not any(x.role == SlotRole.subtitle for x in pattern.slots):
        size = typo.size_for("lead", body * 1.15) if len(sub) <= 120 else body
        need = len(display_lines(sub, fam, size, False, 0.78 * safe.w * w_pt)) * size * 1.2 / h_pt + 0.035
        if band < need:
            out.append("подзаголовку нет места между заголовком и содержимым образца")
    take, foot = " ".join((slide.takeaway or "").split()), " ".join((slide.footnote or "").split())
    if (take or foot) and not pattern.note_slot:
        width = 0.85 * safe.w * w_pt
        need = 0.0
        if take:
            need += len(display_lines(take, fam, body, True, width)) * body * 1.25 / h_pt + 0.04
        if foot:
            need += len(display_lines(foot, fam, 0.75 * body, False, width)) * 0.75 * body * 1.2 / h_pt + 0.02
        foot_room = safe.y + safe.h - max((b.y + b.h for b in boxes), default=safe.y)
        if foot_room < need and (band is None or band < need):
            out.append("выводу слайда нет места ни под содержимым образца, ни под заголовком")
    return out


def score_pattern(
    slide: OutlineSlide,
    pattern: Pattern,
    manifest: TemplateManifest,
    strategy: Strategy,
    prev_family: Optional[Family] = None,
    recent_ids: Optional[list[str]] = None,
    cover: Optional[Pattern] = None,
    divider: Optional[Pattern] = None,
    pictures: Optional[list] = None,
) -> ScoreResult:
    """How well `pattern` suits `slide` (0…1.2) with the reasons. `cover` is the sample the deck's cover was cloned
    from: a closing slide answers it (same ground, ideally the same layout), the way a designer closes a deck, and a
    divider is set a step below it. `divider` is the sample of the deck's first section divider: every divider of a
    deck looks the same. `pictures`: the sample's pictures as `analysis.pictures` reads them (art stays with new
    content, a photo, a screenshot or bars drawn for the sample's figures do not); None = not known."""
    recent_ids = recent_ids or []
    reasons: list[str] = []
    fit: dict = {}
    if pattern.reference:
        return ScoreResult(0.0, [f"служебный слайд шаблона: {pattern.reference}"], fit)
    kind = kind_compat(slide.kind, pattern.kind)
    if kind <= 0 and chart_picture_room(slide, pattern, pictures) > 0:
        # a chart drawn as a picture in the sample (Dark Minimalist p17: a line chart over «Item 1 … Item 5» beside
        # a paragraph): whatever the sample's kind, the slide's chart or table takes the picture's place
        kind = 0.6
    if kind <= 0:
        return ScoreResult(0.0, [f"тип {pattern.kind.value} несовместим с {slide.kind.value}"], fit)
    reasons.append(f"тип {pattern.kind.value} для {slide.kind.value}: {kind:.1f}")
    if slide.content.code is not None:
        # the user's code needs the sample's monospace box; the slide's lines another text box beside it
        from verstka.rendering.compose import MONO_RE

        text_roles = (SlotRole.body, SlotRole.bullet_list, SlotRole.card_body, SlotRole.caption)
        mono = [x for x in pattern.slots if x.role in text_roles and MONO_RE.search(x.style.font_family or "")]
        if not mono:
            return ScoreResult(0.0, reasons + ["в образце нет поля для кода"], fit)
        lines = [t for t in (*slide.content.paragraphs, *slide.content.bullets) if t.strip()]
        if lines and not [x for x in pattern.slots if x.role in text_roles and x not in mono and x.capacity.max_chars >= 120]:
            return ScoreResult(0.0, reasons + ["в образце с кодом нет места для пояснения"], fit)
    pics = list(pictures or [])
    art_ids = {p.shape_id for p in pics if p.kind in ("art", "panel", "line", "icon")}
    bookend0 = slide.kind in _BOOKEND_KINDS
    if pics and not bookend0:
        visual0 = bool(slide.content.image_hint or slide.content.chart is not None or slide.content.table is not None)
        story = [p for p in pics if p.kind in ("photo", "content") and p.area >= 0.03]
        if slide.content.photo_slot and photo_place(pattern, pics) is not None:
            # the user's own picture takes the sample's photo or screenshot place (`clone._make_photo_place`): the
            # sample's story goes with it; any other picture of the sample's story would stay
            place = photo_place(pattern, pics)
            story = [p for p in story if p.shape_id != place.shape_id]
            visual0 = visual0 or not story
        if story and not visual0:
            # a speaker's photo, a product screenshot, a chart drawn for the sample's figures («Item 1 … Item 5»):
            # the sample's own story stays a hole or a lie on new content — only a chart, a table or a picture of
            # the content takes its place
            return ScoreResult(0.0, reasons + ["фото, скриншот или диаграмма образца не относятся к содержанию"], fit)
        bars = [p for p in pics if p.kind == "bar"]
        if bars and slide.content.chart is None and slide.content.table is None:
            # bars drawn as pictures show the sample's figures: under our numbers they would show wrong lengths
            kind *= 0.2
            reasons.append("столбики образца нарисованы под его собственные данные")
        elif story and visual0:
            reasons.append("иллюстрацию образца заменит диаграмма или таблица")
    if not bookend0 and pattern.mockup_boxes and not slide.content.image_hint and not slide.content.photo_slot:
        # a device mock-up (a tablet, a phone, a laptop) shows a screen: without the content's own screenshot its
        # screen stays blank in the middle of the slide
        return ScoreResult(0.0, reasons + ["макет устройства в образце останется с пустым экраном"], fit)
    if not bookend0:
        # a place the sample keeps for a speaker's photo, a QR code or a logo («Вставить фото»): without the user's
        # photo it leaves with its frame and a hole stays where the sample's design had its picture
        holes = [s for s in pattern.slots if s.sample_text and _PHOTO_PLACE_RE.search(s.sample_text) and s.bbox.area >= 0.002]
        if holes and not slide.content.photo_slot and not slide.content.image_hint:
            return ScoreResult(0.0, reasons + ["место под фото в образце останется пустым"], fit)
        if slide.content.photo_slot:
            # the user's photo goes where the sample keeps its picture (`clone._make_photo_place`): a sample without
            # one is set by the composer, which leaves the place beside the content
            if photo_place(pattern, pics) is None:
                return ScoreResult(0.0, reasons + ["в образце нет места под фото"], fit)
            reasons.append("место под фото — на месте картинки образца")
        if slide.content.table is not None and pattern.data_box is not None:
            n_cols = len(slide.content.table.columns)
            if n_cols >= 3 and pattern.data_box.w < 0.6:
                kind *= 0.75
                reasons.append("таблица из трёх и более столбцов в узкой области образца")
            rows_need = len(slide.content.table.rows) + 1
            if pattern.data_rows and pattern.data_rows >= 2 * rows_need:
                # a table of three rows in a sample drawn for nine: the plate stands two-thirds empty under it
                kind *= 0.75
                reasons.append(f"таблица образца рассчитана на {pattern.data_rows} строк, у слайда {rows_need}")
        # a sample whose texts and pictures hold a small part of the slide (a coloured square with the heading at one
        # side, the rest left for a photo the sample does not have) sets new content in a corner of an empty slide
        # (the heading spans the slide on most samples: what counts is where the content stands under it — VK Tech
        # p20 keeps its four lines in the left third and the rest empty)
        boxes = [s.bbox for s in pattern.slots if s.role not in (SlotRole.chrome, SlotRole.title, SlotRole.subtitle)] + list(pattern.decor_boxes) + [p.box for p in pics if p.kind in ("art", "panel")]
        if boxes:
            # a heading set beside the content (Dark Minimalist p6: the title in the left half, three items in the
            # right one) is a part of the layout's spread; a heading over the content is not
            cy0, cy1 = min(b.y for b in boxes), max(b.y2 for b in boxes)
            for s in pattern.slots:
                if s.role in (SlotRole.title, SlotRole.subtitle) and min(s.bbox.y2, cy1) - max(s.bbox.y, cy0) >= 0.3 * s.bbox.h:
                    boxes.append(s.bbox)
        if boxes and pattern.data_box is None:
            x0, y0 = min(b.x for b in boxes), min(b.y for b in boxes)
            x1, y1 = max(b.x2 for b in boxes), max(b.y2 for b in boxes)
            # (only where the rest is really empty: the layout's own art — WorkSpace's spiral left of p4's list — fills it)
            if (x1 - x0) * (y1 - y0) < 0.45 and (x1 - x0) < 0.62 and (pattern.free_share is None or pattern.free_share >= 0.85):
                kind *= 0.5
                reasons.append(f"образец занимает {int(100 * (x1 - x0))}% ширины слайда: остальное останется пустым")
        c0 = slide.content
        if not (c0.paragraphs or c0.bullets or c0.quote or slide.subtitle) and slide.kind in (PatternKind.table, PatternKind.chart):
            # the sample's text column — its own boxes or a column of cards — stays empty beside the chart or table
            boxes_t = [s.bbox for s in pattern.slots if s.role in (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.subtitle) and (not s.group_id or not (c0.items or c0.numbers))]
            spare = 0.0
            if boxes_t:
                ux0, uy0 = min(b.x for b in boxes_t), min(b.y for b in boxes_t)
                ux1, uy1 = max(b.x2 for b in boxes_t), max(b.y2 for b in boxes_t)
                spare = min((ux1 - ux0) * (uy1 - uy0), sum(b.area for b in boxes_t) * 1.5)
            if spare >= 0.15:
                kind *= 0.6
                reasons.append("текстовая колонка образца останется пустой рядом с данными")
            elif spare >= 0.06:
                kind *= 0.8
                reasons.append("текстовая колонка образца останется пустой")
    if pattern.note_slot and not bookend0:
        if slide.takeaway:
            reasons.append("вывод слайда встанет в поле примечания образца")
        else:
            # the note band at the foot leaves with nothing to say: a hole where the sample's design had its band
            kind *= 0.6
            reasons.append("поле примечания образца останется пустым: у слайда нет вывода")
    if not bookend0:
        for why in _gate_room(slide, pattern, manifest):
            kind *= 0.85
            reasons.append(why)
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
        # — never the template's art (VK Tech p7's 3D spiral stays: a chart does not take its place)
        art_pics = {p.shape_id for p in pics if p.kind == "art"}
        room = max((s.bbox.area for s in pattern.slots if s.role in (SlotRole.image, SlotRole.body, SlotRole.bullet_list) and s.shape_id not in art_pics), default=0.0)
        if pattern.kind in (PatternKind.chart, PatternKind.table):
            room = max(room, 0.35)
        if pattern.data_box is not None:
            room = max(room, pattern.data_box.area)
        room = max(room, 0.85 * chart_picture_room(slide, pattern, pictures))  # a chart picture's place (less its margins)
        data_room = min(1.0, room / 0.3)
        if room < 0.12:
            kind *= 0.3
            data_room = 0.2
            reasons.append("нет крупной области под диаграмму или таблицу")
        else:
            reasons.append(f"область под данные: {room:.0%} слайда")
        if slide.content.chart2 is not None and slide.content.chart is not None:
            # a pair of charts stands side by side over most of the slide's width (`clone._draw_native`)
            if pair_width(pattern, pics) < 0.6:
                kind *= 0.3
                reasons.append("пара диаграмм не встанет рядом в область образца")
            else:
                reasons.append("пара диаграмм встанет рядом в область данных образца")
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
    bl = slide.content.bullets
    lines_in_cells = False
    if n < 2 and group is not None and slide.kind in (PatternKind.bullets, PatternKind.agenda) and len(bl) >= 2 and not slide.content.items:
        # a list set on a sample of rows or cards: each line takes a cell (the renderer's `_cells_can_hold_bullets`),
        # it is no single thought on a row of cards
        cell_chars = sum(x.capacity.max_chars for x in pattern.slots if x.group_id == group.id and x.role in text_group_roles)
        if cell_chars >= 0.5 * sum(len(b) for b in bl) and max((x.bbox.w for x in pattern.slots if x.group_id == group.id and x.role in text_group_roles), default=0.0) >= 0.10:
            n = len(bl)
            lines_in_cells = True
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
                if group.fixed:
                    # cells drawn in the template cannot grow by one: the render merges two items into a cell and
                    # the gate turns the sample down — a fallback at most (VK Tech p28, four reasons on three tiles).
                    # A free row of cards takes one more (WorkSpace p15: four offers on its three cards' row)
                    cap = min(cap, 0.2)
                reasons.append(f"не хватает ячеек: нужно {n}, максимум {group.max_n}")
            elif n < group.min_n:
                # cells drawn into the template's art (numbered tiles, tags, a staircase): an empty one stays on the slide
                cap = 0.1
                reasons.append(f"ячейки нарисованы в шаблоне: нужно ровно {group.min_n}, а пунктов {n}")
            if group.axis == "grid" and group.rows * group.cols > n_cells and n < n_cells and not group.fixed:
                # cells set in a zigzag (LCT roadmap: three above, two below, joined by lines): with a cell left
                # empty the figure breaks — a hole in the zigzag and connectors leading nowhere
                cap = min(cap, 0.55)
                reasons.append("ячейки стоят зигзагом: с пустой ячейкой макет развалится")
            if group.axis == "grid" and not group.fixed and group.rows >= 2 and n <= (group.rows - 1) * group.cols:
                # a grid that keeps fewer items than its rows hold leaves whole rows empty (the sample's cards grid
                # with three items): a row of cards says it better
                cap = min(cap, 0.25)
                reasons.append(f"в сетке {group.rows}×{group.cols} останется пустой целый ряд")
            if group.axis == "column" and not group.fixed and n_cells >= 4 and n <= n_cells // 2:
                cap = min(cap, 0.45)
                reasons.append(f"из {n_cells} строк образца останется {n}")
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

    untitled = slide.content.items or slide.content.columns
    if group is not None and untitled and all(not (i.title or "").strip() for i in untitled) and any((i.text or "").strip() or i.bullets for i in untitled):
        # paragraphs without headings (the author's text laid out as written) on cells with a heading box of their own
        # (Классика p12: a heading column beside the text): every heading cell would stand empty
        heads = {s.shape_id for s in pattern.slots if s.group_id == group.id and s.role == SlotRole.card_title}
        texts = {s.shape_id for s in pattern.slots if s.group_id == group.id and s.role in (SlotRole.card_body, SlotRole.body, SlotRole.bullet_list)}
        # (or a parallel column of cells of their own — Классика p12: the headings column beside the texts column)
        def words_column(og) -> bool:
            cells = [s for s in pattern.slots if s.group_id == og.id]
            return bool(cells) and all(s.role in (SlotRole.card_title, SlotRole.card_body, SlotRole.body, SlotRole.bullet_list) for s in cells) and not all(re.fullmatch(r"\W*\d{1,2}\W*", (s.sample_text or "").strip()) for s in cells)

        twin = any(og is not group and len(og.member_shape_ids) >= 2 and words_column(og) for og in groups)
        if (heads and texts and not heads & texts) or twin:
            cap = min(cap, 0.25)
            reasons.append("у пунктов нет заголовков: поля заголовков в ячейках образца остались бы пустыми")
    if data_room is not None and n < 2:
        cap = data_room  # no items to count: the capacity of such a slide is the room for its chart or table
    elif n < 2 and slide.kind not in _BOOKEND_KINDS:
        # one item (a statement, one figure) on a sample of a row or a grid of cards: every other card leaves
        big = max((len(g.member_shape_ids) for g in pattern.repeat_groups if any(s.group_id == g.id and s.role in (SlotRole.card_title, SlotRole.card_body, SlotRole.number) for s in pattern.slots)), default=0)
        if big >= 3:
            cap = min(cap, 0.2)
            reasons.append(f"одна мысль на образце из {big} карточек: остальные уйдут, останется пустота")
    # text fit
    worst = 0.0
    bookend = slide.kind in _BOOKEND_KINDS
    title_fit = _bookend_title_fit(slide, pattern, manifest) if bookend else None
    needs = _needed_chars(slide)
    items_n = slide.content.items or slide.content.columns
    if group is not None and items_n and "card_title" in needs and "card_body" in needs:
        # a cell with one text box (VK Tech p7, p8: a line beside an icon; p24: a paragraph on a card): the item's
        # heading and its text go into that box together, the heading bold on top (`clone._item_single_paragraphs`)
        cell_roles = {x.role for x in pattern.slots if x.group_id == group.id and x.role in (SlotRole.card_title, SlotRole.card_body)}
        if len(cell_roles) == 1:
            whole = max(len(i.title or "") + len(i.text or "") + sum(len(b) + 2 for b in i.bullets) + 2 for i in items_n)
            needs.pop("card_title", None)
            needs.pop("card_body", None)
            needs[next(iter(cell_roles)).value] = whole
    if lines_in_cells and "bullet_list" in needs:
        # each line is a cell's text: measured against a cell, not against one list box
        del needs["bullet_list"]
        cell_role = "card_title" if any(x.group_id == group.id and x.role == SlotRole.card_title for x in pattern.slots) else "card_body"
        needs[cell_role] = max(len(b) for b in bl)
    for role_name, need in needs.items():
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
        if role == SlotRole.title and not bookend and capacity:
            # a content heading takes the free width of its band and a second line before its type steps down (the
            # renderer widens the sample's box cut for «Заголовок»; the gate turns down a heading that shrank): two
            # lines over most of the safe width at the sample's size
            t0 = next((x for x in pattern.slots if x.role == SlotRole.title), None)
            size0 = (t0.style.size_pt if t0 is not None and t0.style.size_pt else None) or manifest.tokens.typography.size_for("h1", 28.0)
            width_pt = 0.8 * manifest.tokens.spacing.safe_area.w * manifest.slide_size.w / 12700
            capacity = max(capacity, int(2 * width_pt / (0.55 * size0)))
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
    items0 = slide.content.items or slide.content.columns
    if group is not None and items0 and n >= 2 and group.cell_bbox.area >= 0.05 and not group.fixed and group.member_shape_ids:
        # cards made for a paragraph each, given a line each, stand three-quarters empty (LCT p24's tall white cards
        # under three one-line theses): a sample with smaller cells says it better
        cell0 = set(group.member_shape_ids[0])
        cell_cap = sum(s.capacity.max_chars for s in pattern.slots if s.shape_id in cell0 and s.role in (SlotRole.card_title, SlotRole.card_body, SlotRole.body, SlotRole.bullet_list, SlotRole.number_label))
        need_cell = max(len(i.title or "") + len(i.text or "") + sum(len(b) + 2 for b in i.bullets) for i in items0)
        if cell_cap >= 120 and need_cell < 0.2 * cell_cap:
            # steps of a word or two («Датчики», «Проверка показаний») in cards made for paragraphs read as empty
            # slabs, not as a sequence: the sample of steps (or a composed one) says it better
            steps_in_cards = slide.kind in (PatternKind.process, PatternKind.timeline) and pattern.kind == PatternKind.cards and need_cell < 0.2 * cell_cap
            if steps_in_cards:
                fit["steps_in_cards"] = True
            kind *= 0.5 if steps_in_cards else 0.85
            reasons.append(f"ячейки образца рассчитаны на текст в {cell_cap // max(need_cell, 1)} раз длиннее")
    if slide.content.numbers:
        # a price list (tariff cards: «259 ₽» over «279 ₽» struck through, a discount pill, a «Кнопка»): its figures are
        # prices — the slide's months and multiples on it read as a shop window
        prices = [x for x in pattern.slots if x.role == SlotRole.number and x.sample_text and _MONEY_RE.search(x.sample_text)]
        money = [n for n in slide.content.numbers if _MONEY_RE.search(n.value or "")]
        if len(prices) >= 2 and len(money) < len(slide.content.numbers):
            kind *= 0.3
            reasons.append("числа образца — цены, у слайда другие числа")
    c_list = slide.content
    if not items0 and (c_list.bullets or c_list.paragraphs) and slide.kind not in _BOOKEND_KINDS:
        # three short lines in a text panel drawn for a page of text (LCT p13: a white panel two thirds of the slide
        # under «Переход на инференс…») stand in its top corner: a sample with a smaller field says them better
        big = max((x for x in pattern.slots if x.role in (SlotRole.body, SlotRole.bullet_list) and not x.group_id), key=lambda x: x.capacity.max_chars, default=None)
        need_list = sum(len(b) + 2 for b in c_list.bullets) + sum(len(t) + 1 for t in c_list.paragraphs)
        if big is not None and big.bbox.area >= 0.25 and big.capacity.max_chars >= 300 and need_list < 0.2 * big.capacity.max_chars:
            kind *= 0.8
            reasons.append(f"поле текста образца рассчитано на текст в {big.capacity.max_chars // max(need_list, 1)} раз длиннее")
    # hard gates: a pattern without room for the slide's content would render a headline over stale sample shapes
    content = slide.content
    needed_roles = _needed_chars(slide)
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
            and 2 * s.bbox.w * s.bbox.h <= b.w * b.h < 0.6 for b in pattern.decor_boxes)]
        values = [x.value for x in content.numbers]
        if rings and values and not all(re.match(r"^\s*\d{1,3}(?:[.,]\d+)?\s*%\s*$", v or "") for v in values):
            kind *= 0.6
            reasons.append("кольцевая инфографика, а числа — не проценты")
    n_items = needed_items(slide)
    text_slots = [s for s in pattern.slots if s.role in (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption)]
    if bookend:
        text_slots = [s for s in text_slots if not is_placeholder_text(s.sample_text)]  # speaker/QR blocks leave with their frames
    # (only the roles the slide fills: items of a title each take one box a card, not a title and an empty text box —
    # five such items on WorkSpace p12 counted ten boxes, and its second row of «Текст» cells, emptied, cost nothing)
    active = {r for r, v in needed_roles.items() if v > 0}
    needed_slots = sum(1 for r in active if r not in ("title", "subtitle")) + max(n_items - 1, 0) * sum(1 for r in ("card_title", "card_body", "number", "number_label") if r in active)
    extra = max(len(text_slots) - max(needed_slots, 1), 0)
    clutter = min(0.3, 0.03 * extra)
    if slide.kind == PatternKind.thanks and extra >= 2:
        # a closing slide's contact rows (name, mail, site) left empty stand as empty ruled rows under «Спасибо»
        # (Классика: the layout draws the rules, they cannot leave) — the template's cover closes the deck better
        clutter = min(0.3, 0.06 * extra)
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
    if slide.verbatim and worst >= 2.0 - 1e-6 and not bookend:
        # the author's own text is cut by whole sentences only: twice the sample's room is no fit (Классика p11 took
        # three stages in its two cells, the first stage's heading over its text) — another sample or a composed slide;
        # neither is a sample with no place at all for a part of it (×2.0: the cards' headings of the Office
        # template's two-column sample ran into one column, the other left empty)
        cap = min(cap, 0.2)
        reasons.append("текст автора вдвое больше места образца")

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
    # the template's art (renders, illustrations, plates) stays with new content: only a picture that is not art is
    # stale when nothing replaces it
    stale_images = [s for s in pattern.slots if s.role == SlotRole.image and s.bbox.area >= 0.12 and s.shape_id not in art_ids]
    if stale_images and not has_visual:
        kind *= 0.6
        reasons.append("крупная картинка-образец останется без замены")

    def _art_box(b) -> bool:
        return any(p.kind in ("art", "panel") and p.box.x <= b.x + b.w / 2 <= p.box.x2 and p.box.y <= b.y + b.h / 2 <= p.box.y2 for p in pics)

    # a decorative picture in the middle of the content area (a chart snapshot, a KPI ring) says the sample's own story
    stale_decor = [b for b in pattern.decor_boxes if b.area >= 0.08 and 0.15 < b.y + b.h / 2 < 0.85 and 0.15 < b.x + b.w / 2 < 0.85 and not _art_box(b)]
    if stale_decor and not has_visual and not bookend:  # on a cover or divider the sample's art is the point
        kind *= 0.6
        reasons.append("крупная иллюстрация образца посреди слайда не относится к содержанию")
    # strategy flavour: visual favours decorated/illustrated samples, compact favours denser samples, structured plain ones
    n_decor = len(pattern.decor_assets) + sum(1 for s in pattern.slots if s.role in (SlotRole.icon, SlotRole.image))
    has_art = any(p.kind == "art" and p.area >= 0.02 for p in pics)
    # (every variant takes the template's designed slides first — its illustrations, its drawn forms — over plain
    # cards: a deck of the template's own slides, not the same white card eleven times; the variants differ by which
    # of them they take, `matcher.OTHER_VARIANT_PENALTY`)
    # the variants look different: the visual one reaches for the template's art and its dark ground (a content
    # slide on the brand colour), the compact one for plain samples that hold the most text, the structured one between
    if strategy.name == "visual":
        style = 0.14 if has_art else (0.06 if n_decor >= 1 else 0.0)
        if pattern.family == Family.dark and not bookend:
            style += 0.06
    elif strategy.name == "compact":
        style = 0.08 * min(len(text_slots) / 8.0, 1.0) - (0.04 if has_art and not bookend else 0.0)
    else:
        style = 0.05 if has_art else (0.03 if n_decor >= 1 else 0.0)
    if style:
        reasons.append(f"стиль стратегии {strategy.name}: {style:+.2f}")
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
        if slide.kind == PatternKind.title and pattern.kind == PatternKind.title:
            # the template's own cover is the deck's cover: a divider with a giant word set on its own ground
            # (SlidesCarnival «lettering», «luxury») scored above it on its size alone and lost the cover's design
            style += 0.1
            reasons.append("обложка шаблона: +0.10")
        h1 = typo.size_for("h1", 0.0)
        sample_size = max((x.style.size_pt or 0.0 for x in titles), default=0.0)
        if h1 and sample_size and sample_size < 1.15 * h1 and not _cover_like(pattern, manifest, sample_size):
            # a heading at the size of a content heading: the sample is a content page, not a cover or a divider
            style -= 0.15
            reasons.append(f"заголовок образца ({sample_size:.0f} пт) не крупнее заголовка слайда ({h1:.0f} пт): это не обложка")
        if pattern.mockup_boxes and not content.image_hint:
            # a phone mock-up or an empty photo frame stays empty on the cover (no screenshot, no photo in the brief):
            # drawn by the layout it cannot be taken off the slide (−0.3: another bookend of the template — its closing
            # slide on the same ground — makes the better cover); drawn on the sample the renderer takes it off and
            # only an empty stretch of the ground is left, so it just breaks ties (−0.03): the template's real cover
            # keeps its place against a divider sample borrowed as a cover (MyBrand: a longer title that needs a
            # smaller size on the real cover must not hand the cover to a section slide)
            pen = 0.3 if pattern.mockup_on_layout else 0.03
            if slide.kind == PatternKind.thanks and max((b.w * b.h for b in pattern.mockup_boxes), default=0.0) >= 0.15:
                # a closing slide whose sample's frame takes a sixth of the slide and more: taken off, it leaves that
                # much of the slide blank beside «Спасибо» (Marketing's contact slide without its map) — the
                # template's other bookends close the deck better
                pen = max(pen, 0.15)
            style -= pen
            reasons.append(f"макет устройства или пустая рамка под фото останутся пустыми: −{pen:.2f}")
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
    elif fit.get("steps_in_cards") and score >= strategy.synth_threshold:
        score = max(0.0, strategy.synth_threshold - 0.05)
        reasons.append("шаги из пары слов в карточках для абзацев выглядят пустыми: слайд лучше собрать из дизайн-системы шаблона")
    elif cap <= 0.25 and not bookend and score >= strategy.synth_threshold:
        # the sample's cells cannot take this many items (a tile drawn with its numeral «04» left empty, a grid with a
        # whole row gone, one thought on a row of cards): a slide composed by the design system reads better
        score = max(0.0, strategy.synth_threshold - 0.05)
        reasons.append("ячейки образца не подходят к числу пунктов: слайд лучше собрать из дизайн-системы шаблона")
    return ScoreResult(round(score, 3), reasons, fit)
