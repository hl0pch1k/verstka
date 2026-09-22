"""Heuristic slot roles for shapes on one slide."""

from __future__ import annotations

import re
from typing import Optional

from verstka.analysis.groups import group_membership
from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import ShapeKind, SlotRole, contrast_ratio, hex_to_rgb
from verstka.schemas.template import RepeatGroup, Typography

NUMERIC_RE = re.compile(r"^[\s\d.,%+×x><≈~$€₽£\-–—/]{1,10}(\s?(млн|млрд|тыс|k|m|b|%|x|×|ч|дн|раз|шт|₽|\$))?\s*$", re.I)


_KPI_PLACEHOLDER_RE = re.compile(r"^[xхX]{1,4}\s?%?$|^[xхX]{1,3}\s?(млн|млрд|тыс|k|m)$", re.I)


def is_numeric_text(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if _KPI_PLACEHOLDER_RE.match(t):
        return True
    return bool(NUMERIC_RE.match(t)) and any(ch.isdigit() for ch in t)


def _size(s: ShapeInfo) -> float:
    return (s.text.dominant_size_pt or s.text.max_size_pt or 0.0) if s.text else 0.0


_SERVICE_PH = {"sldNum", "dt", "ftr", "hdr"}
_FRAME_GEOMETRIES = {None, "rect", "roundRect", "round1Rect", "round2SameRect", "round2DiagRect", "snip1Rect", "snip2SameRect", "snipRoundRect", "flowChartAlternateProcess", "flowChartProcess", "plaque"}


def _saturation(hex_: str) -> float:
    r, g, b = hex_to_rgb(hex_)
    mx, mn = max(r, g, b), min(r, g, b)
    return 0.0 if mx == 0 else (mx - mn) / mx


def is_empty_frame(s: ShapeInfo, shapes: list[ShapeInfo], slide_w: int, slide_h: int) -> bool:
    """An empty card/panel the designer left for content (the LCT template is made of them).

    A rectangular shape with a light/neutral fill or just an outline, big enough for a few lines, with no text of
    its own and nothing with text or a picture inside. Saturated accent blocks, slide-sized backgrounds, lines and
    circles stay decoration.
    """
    if s.kind != ShapeKind.sp or s.has_text or not s.is_visual_shape or s.geometry not in _FRAME_GEOMETRIES:
        return False
    if s.is_placeholder and s.ph_type not in (None, "body", "obj"):
        return False
    fw, fh = s.bbox.w / slide_w, s.bbox.h / slide_h
    if fw < 0.08 or fh < 0.06 or not (0.015 <= fw * fh <= 0.55) or fw > 0.9 or fh > 0.9:
        return False  # a slide-high or slide-wide block is a panel of the layout, not a card
    if s.bbox.x < 0 or s.bbox.y < 0 or s.bbox.x2 > slide_w * 1.001 or s.bbox.y2 > slide_h * 1.001:
        return False  # a frame running off the slide is an ornament
    if s.fill_hex is not None and s.fill_alpha >= 0.5 and _saturation(s.fill_hex) > 0.35:
        return False  # a coloured block is decoration (or a label behind a heading)
    for o in shapes:
        if o.id == s.id or o.bbox.area <= 0:
            continue
        overlap = s.bbox.intersection(o.bbox)
        if overlap <= 0.05 * o.bbox.area:
            continue
        if o.has_text or o.kind in (ShapeKind.pic, ShapeKind.graphic_frame) or o.is_placeholder or (o.text is not None and not o.is_visual_shape):
            return False  # it already hosts (or sits under) slots, pictures, text boxes — even empty ones
        cx, cy = o.bbox.x + o.bbox.w / 2, o.bbox.y + o.bbox.h / 2
        inside = s.bbox.x <= cx <= s.bbox.x2 and s.bbox.y <= cy <= s.bbox.y2
        if inside and o.is_visual_shape and o.bbox.area >= 0.05 * s.bbox.area and o.z > s.z:
            return False  # a panel holding other cards is a background, not a slot
    return True


def heuristic_roles(
    shapes: list[ShapeInfo],
    groups: list[RepeatGroup],
    chrome_ids: set[str],
    typography: Typography,
    slide_w: int,
    slide_h: int,
    image_kinds: Optional[dict[str, str]] = None,
) -> dict[str, SlotRole]:
    image_kinds = image_kinds or {}
    roles: dict[str, SlotRole] = {}
    membership = group_membership(groups)
    body_size = typography.size_for("body", 14.0)
    caption_size = typography.size_for("caption", typography.size_for("small", body_size * 0.75))
    slide_area = float(slide_w * slide_h)
    by_id = {s.id: s for s in shapes}

    for s in shapes:
        # slide number, date and footer placeholders are chrome by definition, even on a single sample
        if s.id in chrome_ids or s.ph_type in _SERVICE_PH:
            roles[s.id] = SlotRole.chrome

    texts = [s for s in shapes if s.has_text and s.id not in roles and s.kind != ShapeKind.graphic_frame]

    # title
    title: Optional[ShapeInfo] = next((s for s in texts if s.ph_type in ("title", "ctrTitle")), None)
    if title is None:
        # empty title placeholder still counts as a title slot
        title = next((s for s in shapes if s.ph_type in ("title", "ctrTitle") and s.id not in roles), None)
    if title is None:
        top_texts = [s for s in texts if s.id not in membership and s.bbox.y < 0.4 * slide_h and not is_numeric_text(s.plain_text)]
        if top_texts:
            biggest = max(top_texts, key=lambda s: (_size(s), -s.bbox.y))
            max_non_numeric = max((_size(s) for s in texts if not is_numeric_text(s.plain_text)), default=0.0)
            if _size(biggest) >= max(body_size * 1.15, max_non_numeric * 0.8):
                title = biggest
    if title is not None:
        roles[title.id] = SlotRole.title

    # subtitle
    for s in texts:
        if s.id in roles:
            continue
        if s.ph_type == "subTitle":
            roles[s.id] = SlotRole.subtitle
        elif title is not None and s.id not in membership:
            gap = s.bbox.y - title.bbox.y2
            overlaps_x = s.bbox.x < title.bbox.x2 and s.bbox.x2 > title.bbox.x
            if -0.02 * slide_h <= gap <= 0.08 * slide_h and overlaps_x and _size(s) < _size(title) and len(s.plain_text) <= 160:
                roles[s.id] = SlotRole.subtitle
                break
    # an empty subtitle placeholder is still the subtitle slot; an empty, low body placeholder directly under the
    # title on a sparse slide (title / section / thanks samples) is the designer's subtitle box, not a bullet list
    if title is not None and SlotRole.subtitle not in roles.values():
        for s in shapes:
            if s.id in roles or s.id in membership or s.kind != ShapeKind.sp or not s.is_placeholder or s.has_text:
                continue
            if s.ph_type == "subTitle":
                roles[s.id] = SlotRole.subtitle
                break
            if s.ph_type not in ("body", "obj"):
                continue
            gap = s.bbox.y - title.bbox.y2
            overlaps_x = s.bbox.x < title.bbox.x2 and s.bbox.x2 > title.bbox.x
            sparse = len(texts) <= 3 or title.ph_type == "ctrTitle"
            if -0.02 * slide_h <= gap <= 0.08 * slide_h and overlaps_x and s.bbox.h <= 0.15 * slide_h and sparse:
                roles[s.id] = SlotRole.subtitle
                break

    # numbers and labels
    numbers: list[ShapeInfo] = []
    for s in texts:
        if s.id in roles:
            continue
        if is_numeric_text(s.plain_text) and _size(s) >= max(body_size * 1.6, 20.0):
            roles[s.id] = SlotRole.number
            numbers.append(s)
    for n in numbers:
        best = None
        best_d = 1e18
        for s in texts:
            if s.id in roles or is_numeric_text(s.plain_text):
                continue
            below = s.bbox.y >= n.bbox.y2 - 0.02 * slide_h and s.bbox.y - n.bbox.y2 < 0.12 * slide_h and s.bbox.x < n.bbox.x2 and s.bbox.x2 > n.bbox.x
            right = abs(s.bbox.y - n.bbox.y) < 0.06 * slide_h and 0 <= s.bbox.x - n.bbox.x2 < 0.12 * slide_w
            if (below or right) and _size(s) < _size(n):
                d = abs(s.bbox.y - n.bbox.y2) + abs(s.bbox.x - n.bbox.x)
                if d < best_d:
                    best, best_d = s, d
        if best is not None:
            roles[best.id] = SlotRole.number_label

    # empty frames are containers: the text (or the chart/table) goes inside them
    for s in shapes:
        if s.id not in roles and is_empty_frame(s, shapes, slide_w, slide_h):
            roles[s.id] = SlotRole.card_body if s.id in membership else SlotRole.body

    # cells: card title/body/icon
    for g in groups:
        for cell in g.member_shape_ids:
            members = [by_id[i] for i in cell if i in by_id and by_id[i].id not in roles]
            # an empty invisible text box next to real text is a leftover, not a slot (VK Tech cards keep an emptied title box)
            with_text = [m for m in members if m.text is not None and m.has_text]
            cell_texts = sorted(with_text or [m for m in members if m.text is not None and not m.is_visual_shape], key=lambda m: (-(_size(m)), m.bbox.y))
            if cell_texts:
                head = cell_texts[0]
                bold_first = next((m for m in sorted(cell_texts, key=lambda m: m.bbox.y) if m.text.bold_share > 0.5), None)
                head = bold_first or head
                if len(cell_texts) == 1 and is_numeric_text(head.plain_text):
                    roles[head.id] = SlotRole.number
                elif len(cell_texts) == 1:
                    roles[head.id] = SlotRole.card_body
                else:
                    # a numeric head is a KPI (number + label), not a card title
                    roles[head.id] = SlotRole.number if is_numeric_text(head.plain_text) else SlotRole.card_title
                    for m in cell_texts:
                        if m.id not in roles:
                            roles[m.id] = SlotRole.number if is_numeric_text(m.plain_text) and _size(m) >= body_size * 1.5 else SlotRole.card_body
            for m in members:
                if m.id in roles:
                    continue
                if m.kind == ShapeKind.pic:
                    roles[m.id] = SlotRole.icon if min(m.bbox.w, m.bbox.h) < 0.12 * slide_w else SlotRole.image
                elif not m.has_text:
                    roles[m.id] = SlotRole.decoration

    # pictures
    for s in shapes:
        if s.id in roles or s.kind != ShapeKind.pic:
            continue
        kind = image_kinds.get(s.image_part or "", "")
        if kind == "logo":
            roles[s.id] = SlotRole.chrome
        elif kind == "icon" or min(s.bbox.w, s.bbox.h) < 0.08 * slide_w:
            roles[s.id] = SlotRole.icon
        elif kind in ("illustration", "pattern"):
            roles[s.id] = SlotRole.decoration
        else:
            overlaps_text = any(t.bbox.intersection(s.bbox) > 0.3 * t.bbox.area for t in texts if t.id != s.id)
            roles[s.id] = SlotRole.decoration if (overlaps_text and s.bbox.area / slide_area >= 0.25) else SlotRole.image

    # bullet lists, captions, body
    for s in texts:
        if s.id in roles:
            continue
        paras = [p for p in s.text.paragraphs if p.text.strip()]
        if len(paras) >= 2 and (s.text.has_bullets or any(p.level > 0 for p in paras) or len(paras) >= 3):
            roles[s.id] = SlotRole.bullet_list
        elif _size(s) <= caption_size and len(s.plain_text) <= 200:
            roles[s.id] = SlotRole.caption
        else:
            roles[s.id] = SlotRole.body

    # graphic frames and remaining visual shapes
    for s in shapes:
        if s.id in roles:
            continue
        if s.kind == ShapeKind.graphic_frame:
            roles[s.id] = SlotRole.image  # table/chart placeholder area; kind classification handles specifics
        elif s.kind == ShapeKind.connector:
            roles[s.id] = SlotRole.decoration
        elif s.is_visual_shape and not s.has_text:
            roles[s.id] = SlotRole.decoration
        elif s.kind == ShapeKind.sp and s.is_placeholder and s.ph_type in ("body", "obj") and not s.has_text:
            roles[s.id] = SlotRole.bullet_list
        else:
            roles[s.id] = SlotRole.decoration
    return roles
