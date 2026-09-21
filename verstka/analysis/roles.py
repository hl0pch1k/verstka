"""Heuristic slot roles for shapes on one slide."""

from __future__ import annotations

import re
from typing import Optional

from verstka.analysis.groups import group_membership
from verstka.analysis.shapes import ShapeInfo
from verstka.schemas.common import ShapeKind, SlotRole
from verstka.schemas.template import RepeatGroup, Typography

NUMERIC_RE = re.compile(r"^[\s\d.,%+×x><≈~$€₽£\-–—/]{1,10}(\s?(млн|млрд|тыс|k|m|b|%|x|×|ч|дн|раз|шт|₽|\$))?\s*$", re.I)


def is_numeric_text(text: str) -> bool:
    t = text.strip()
    return bool(t) and bool(NUMERIC_RE.match(t)) and any(ch.isdigit() for ch in t)


def _size(s: ShapeInfo) -> float:
    return (s.text.dominant_size_pt or s.text.max_size_pt or 0.0) if s.text else 0.0


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
        if s.id in chrome_ids:
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

    # cells: card title/body/icon
    for g in groups:
        for cell in g.member_shape_ids:
            members = [by_id[i] for i in cell if i in by_id and by_id[i].id not in roles]
            cell_texts = sorted([m for m in members if m.has_text], key=lambda m: (-(_size(m)), m.bbox.y))
            if cell_texts:
                head = cell_texts[0]
                bold_first = next((m for m in sorted(cell_texts, key=lambda m: m.bbox.y) if m.text.bold_share > 0.5), None)
                head = bold_first or head
                if len(cell_texts) == 1 and is_numeric_text(head.plain_text):
                    roles[head.id] = SlotRole.number
                elif len(cell_texts) == 1:
                    roles[head.id] = SlotRole.card_body
                else:
                    roles[head.id] = SlotRole.card_title
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
