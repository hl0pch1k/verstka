"""Heuristic pattern kind for one slide."""

from __future__ import annotations

import re
from collections import Counter

from verstka.analysis.groups import group_membership
from verstka.analysis.roles import is_numeric_text
from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import PatternKind, ShapeKind, SlotRole
from verstka.schemas.template import RepeatGroup

_THANKS_RE = re.compile(r"спасибо|thank|q\s*&\s*a|вопрос|контакт|contact", re.I)
_AGENDA_RE = re.compile(r"оглавлен|содержан|agenda|повестк|план презентац", re.I)
_TIMELINE_RE = re.compile(r"таймлайн|timeline|roadmap|дорожн|этап|20\d\d", re.I)
_QUOTE_RE = re.compile(r"^[«\"“„']", re.U)
_MONO_RE = re.compile(r"consolas|courier|mono|menlo|fira code|jetbrains", re.I)
_TEAM_RE = re.compile(r"команд|team|спикер|speaker", re.I)
# whole words: «McKinsey Consulting» is no comparison («cons» inside a word), «Pros & Cons» is
_COMPARE_RE = re.compile(r"сравнен|(?<![\w])(?:vs\.?|против|до и после|before|after|плюсы|минусы|pros|cons|тариф\w*|saas|on-?premise)(?![\w])", re.I)
_NUM_SEQ_RE = re.compile(r"^0?\d{1,2}$")


def heuristic_kind(
    shapes: list[ShapeInfo],
    roles: dict[str, SlotRole],
    groups: list[RepeatGroup],
    slide_index: int,
    n_slides: int,
    slide_w: int,
    slide_h: int,
    data_box=None,
) -> tuple[PatternKind, float]:
    by_id = {s.id: s for s in shapes}
    membership = group_membership(groups)
    role_counts = Counter(roles.values())
    content = [s for s in shapes if roles.get(s.id) not in (SlotRole.chrome, SlotRole.decoration)]
    texts = [s for s in content if s.has_text]
    all_text = " ".join(s.plain_text for s in texts)
    title = next((s for s in shapes if roles.get(s.id) == SlotRole.title), None)
    title_text = title.plain_text if title else ""
    slide_area = float(slide_w * slide_h)

    frames = [s for s in shapes if s.kind == ShapeKind.graphic_frame]
    if any(f.frame_kind == "table" for f in frames):
        return PatternKind.table, 0.95
    if data_box is not None:
        return PatternKind.table, 0.85  # a table drawn with text boxes on plates
    if any(f.frame_kind == "chart" for f in frames):
        return PatternKind.chart, 0.95
    if any(f.frame_kind == "diagram" for f in frames):
        return PatternKind.process, 0.6

    n_numbers = role_counts.get(SlotRole.number, 0)
    n_cards = max((len(g.member_shape_ids) for g in groups), default=0)
    biggest_group = max(groups, key=lambda g: len(g.member_shape_ids), default=None)
    n_content = len(content)

    if _THANKS_RE.search(title_text) and n_content <= 8:
        return PatternKind.thanks, 0.9
    # a quote mark set as the heading («“» over a statement and «— Include a credit»: Dark Minimalist p18) is a quote
    if title is not None and re.fullmatch(r"\s*[«»“”„\"']{1,2}\s*", title.plain_text or ""):
        return PatternKind.quote, 0.8
    # a numbered list of sections in one box («1.Introduction / 2.About Us / 3.Our Projects») is the agenda
    for s in texts:
        lines = [ln.strip() for ln in (s.plain_text or "").splitlines() if ln.strip()]
        if len(lines) >= 3 and sum(1 for ln in lines if re.match(r"^\d{1,2}\s*[.)]\s*\S", ln)) >= 3:
            return PatternKind.agenda, 0.8
    if title is not None and title.text is not None:
        # (the numbers set by the list itself: the heading box holds three or more short numbered lines)
        paras = [p for p in title.text.paragraphs if p.text.strip()]
        if len(paras) >= 3 and all(p.has_bullet and len(p.text) <= 40 for p in paras):
            return PatternKind.agenda, 0.8
    # the first slide of a template is its cover: a photo, a card under the title, the author, the date and a few
    # marks around it (Canva / Google Slides covers carry 8–12 shapes) — never a comparison or a card row
    if slide_index == 1 and n_slides >= 3 and n_numbers < 3:
        # (a cover whose title is set as display words in boxes of their own — «ELEGANT / PITCH / DECK» of a Google
        # Slides template — or that carries a menu row and footers beside its title is the cover all the same: its
        # largest type is display-sized and clearly above the rest)
        sizes = sorted(((s.text.max_size_pt or 0.0) for s in texts if s.text is not None), reverse=True)
        display = max(32.0, 0.08 * slide_h / 12700)
        dominant = bool(sizes) and sizes[0] >= display and (len(sizes) == 1 or sizes[0] >= 1.5 * sizes[len(sizes) // 2])
        if (title is not None and n_content <= 12 and len(texts) <= 6) or dominant:
            return PatternKind.title, 0.85
    # ordinal markers 01, 02, 03… are sequence numbers, not KPIs → agenda / process / timeline
    ordinals = [s for s in texts if _NUM_SEQ_RE.match(s.plain_text.strip())]
    if len(ordinals) >= 3:
        values = sorted(int(s.plain_text.strip()) for s in ordinals)
        if values[0] <= 2 and values[-1] - values[0] <= len(values) + 1:
            if _AGENDA_RE.search(title_text) or _AGENDA_RE.search(all_text) or slide_index <= 3:
                return PatternKind.agenda, 0.8
            if _TIMELINE_RE.search(all_text):
                return PatternKind.timeline, 0.75
            return PatternKind.process, 0.75
    if slide_index <= 2 and title is not None and role_counts.get(SlotRole.subtitle, 0) >= 1 and n_cards == 0 and n_content <= 7 and n_numbers == 0:
        return PatternKind.title, 0.85
    small_pics = [s for s in shapes if roles.get(s.id) in (SlotRole.image, SlotRole.icon) and s.bbox.area / slide_area < 0.06]
    if slide_index <= 3 and title is not None and n_cards == 0 and n_numbers == 0 and n_content <= 4 and len(small_pics) == 1 and role_counts.get(SlotRole.image, 0) + role_counts.get(SlotRole.icon, 0) == 1 and role_counts.get(SlotRole.bullet_list, 0) == 0:
        return PatternKind.title, 0.7  # speaker variant of the title slide (avatar + name)
    if any(_MONO_RE.search(s.text.dominant_font or "") for s in texts if s.text) and any(len(s.plain_text) > 40 for s in texts):
        return PatternKind.code, 0.85
    # figures that are years in order (2010, 2011, 2012…) mark a timeline, not key figures (Education p42)
    num_texts = [by_id[i].plain_text.strip() for i, r in roles.items() if r == SlotRole.number and by_id.get(i) is not None]
    years = [int(x) for x in num_texts if re.fullmatch(r"(?:19|20)\d{2}", x)]
    if len(years) >= 3 and len(years) >= 0.8 * len(num_texts) and len(set(years)) == len(years) and max(years) - min(years) <= 3 * len(years):
        return PatternKind.timeline, 0.75
    if n_numbers >= 8:
        return PatternKind.chart, 0.6  # a chart or table drawn with shapes
    if n_numbers >= 3:
        return PatternKind.stat_row, 0.8
    if n_numbers in (1, 2):
        big = [by_id[i] for i, r in roles.items() if r == SlotRole.number and by_id[i].text and (by_id[i].text.max_size_pt or 0) >= 40]
        if big:
            return PatternKind.big_number, 0.8
    if _AGENDA_RE.search(title_text):
        return PatternKind.agenda, 0.9
    # numbered short items 01..06 → agenda / process
    numbered = [s for s in texts if _NUM_SEQ_RE.match(s.plain_text.strip())]
    if len(numbered) >= 3:
        if _AGENDA_RE.search(all_text) or slide_index <= 3:
            return PatternKind.agenda, 0.7
        if _TIMELINE_RE.search(all_text):
            return PatternKind.timeline, 0.7
        return PatternKind.process, 0.7
    # title-ish slides
    if slide_index == 1 and n_content <= 6:
        return PatternKind.title, 0.9
    # (a heading with a line under it beside a large picture — VK Tech p43's video call — or over a list and a photo
    # place — a speaker's page, p11 — is a page of content, not a divider)
    big_picture = any(roles.get(s.id) == SlotRole.image and s.bbox.area / slide_area >= 0.12 for s in shapes)
    photo_place = any(re.search(r"вставить\s+фото|insert\s+(?:photo|image)|^\s*иллюстрац|^\s*illustration", s.plain_text, re.I) for s in texts)
    divider_like = not big_picture and not photo_place and role_counts.get(SlotRole.bullet_list, 0) == 0
    if title is not None and role_counts.get(SlotRole.subtitle, 0) >= 1 and n_content <= 4 and n_cards == 0 and (slide_index <= 2 or divider_like):
        return PatternKind.title if slide_index <= 2 else PatternKind.section, 0.7
    body_chars = sum(len(t.plain_text) for t in texts if title is None or t.id != title.id)
    # a long statement in the heading's place over a short attribution — a name and a position — is a quote, not a
    # divider (Education p19: «VK активно развивается…» over «Владимир Кириенко, генеральный директор VK»)
    if title is not None and len(title.plain_text) > 100 and n_cards == 0:
        others = [s for s in texts if s.id != title.id and s.plain_text.strip()]
        if others and all(len(s.plain_text) <= 90 for s in others) and any(re.match(r"^[—–-]?\s*[А-ЯЁA-Z][а-яёa-z]+\s+[А-ЯЁA-Z][а-яёa-z]+", s.plain_text.strip()) for s in others):
            return PatternKind.quote, 0.75
    if title is not None and n_content <= 2 and n_cards == 0 and role_counts.get(SlotRole.bullet_list, 0) == 0 and body_chars <= 120 and (slide_index <= 2 or divider_like):
        return PatternKind.section, 0.7  # a divider: a heading and a line at most, never a list (nor a large picture)
    # team: group cells with a picture or a round avatar and name-like text
    if biggest_group is not None and n_cards >= 3:
        cells = biggest_group.member_shape_ids
        has_pics = sum(1 for cell in cells if any(by_id.get(i) and (by_id[i].kind == ShapeKind.pic or by_id[i].geometry == "ellipse") for i in cell))
        named = sum(1 for cell in cells if any(by_id.get(i) and re.search(r"имя|фамили|должност|\bname\b|position|role", by_id[i].plain_text, re.I) for i in cell))
        if (has_pics >= len(cells) * 0.6 or named >= len(cells) * 0.6) and (_TEAM_RE.search(all_text) or named >= len(cells) * 0.6):
            return PatternKind.team, 0.85
    # timeline: long connector/line plus ≥3 small aligned items
    lines = [s for s in shapes if (s.kind == ShapeKind.connector or (s.kind == ShapeKind.sp and s.geometry == "line") or (s.kind in (ShapeKind.pic, ShapeKind.sp) and s.bbox.h <= 0.02 * slide_h and (s.kind == ShapeKind.pic or s.is_visual_shape))) and s.bbox.w >= 0.4 * slide_w]
    if lines and n_cards >= 3 and biggest_group is not None and biggest_group.axis in ("row", "grid"):
        # points along a line (one row, or two rows of a long timeline): a cell stands by the line
        near = sum(1 for cell in biggest_group.member_shape_ids if any(abs(by_id[i].bbox.center[1] - ln.bbox.center[1]) <= 0.12 * slide_h for i in cell if i in by_id for ln in lines))
        if near >= 0.6 * len(biggest_group.member_shape_ids):
            return PatternKind.timeline, 0.75
    if _TIMELINE_RE.search(title_text) and n_cards >= 3:
        return PatternKind.timeline, 0.7
    if _COMPARE_RE.search(title_text) and 2 <= n_cards <= 3:
        return PatternKind.comparison, 0.75
    if biggest_group is not None and n_cards >= 2:
        cells = biggest_group.member_shape_ids
        text_cells = sum(1 for cell in cells if any(by_id.get(i) and (by_id[i].has_text or (by_id[i].text is not None and roles.get(i) in (SlotRole.card_title, SlotRole.card_body, SlotRole.body))) for i in cell))
        if text_cells >= max(2, int(len(cells) * 0.6)):
            if n_cards == 2 and biggest_group.axis == "row" and biggest_group.cell_bbox.w >= 0.35:
                return PatternKind.two_column, 0.7
            return PatternKind.cards, 0.75
    # image + text
    images = [s for s in shapes if roles.get(s.id) == SlotRole.image]
    big_images = [s for s in images if s.bbox.area / slide_area >= 0.12]
    if big_images:
        aspect = max(big_images, key=lambda s: s.bbox.area)
        ratio = aspect.bbox.w / max(aspect.bbox.h, 1)
        if 0.4 <= ratio <= 0.6 or re.search(r"мокап|mockup|скриншот|screenshot|интерфейс", all_text, re.I):
            return PatternKind.mockup, 0.65
        if texts:
            return PatternKind.image_text, 0.7
    quote_like = [s for s in texts if _QUOTE_RE.match(s.plain_text.strip()) and len(s.plain_text) > 30]
    if quote_like or (title is None and any((s.text.max_size_pt or 0) >= 24 and len(s.plain_text) > 60 for s in texts)):
        return PatternKind.quote, 0.6
    bodies = [s for s in texts if roles.get(s.id) == SlotRole.body and s.bbox.w >= 0.3 * slide_w]
    if len(bodies) == 2 and abs(bodies[0].bbox.y - bodies[1].bbox.y) < 0.1 * slide_h:
        return PatternKind.two_column, 0.65
    if role_counts.get(SlotRole.bullet_list, 0) >= 1:
        return PatternKind.bullets, 0.7
    if title is not None and n_content <= 3 and (role_counts.get(SlotRole.body, 0) + role_counts.get(SlotRole.subtitle, 0)) >= 1:
        return PatternKind.bullets, 0.5
    return PatternKind.freeform, 0.3
