"""Assemble slide patterns (slots with capacity, repeat groups, decor) and dedupe them."""

from __future__ import annotations

import re
from collections import Counter
from typing import Callable, Optional

from verstka.analysis.groups import group_membership
from verstka.analysis.shapes import ShapeInfo, looks_like_placeholder
from verstka.schemas.common import Bbox, EMU_PER_PT, Family, PatternKind, ShapeKind, SlotRole
from verstka.schemas.template import Capacity, ClassificationTrace, Pattern, RepeatGroup, Slot, SlotStyle

AVG_CHAR_EM = 0.52  # average glyph advance relative to font size for Latin/Cyrillic sans
AVG_CHAR_EM_BOLD = 0.56


def container_inset(w_emu: int, h_emu: int) -> int:
    """Padding inside an empty frame that receives text: 7% of its shorter side, 0.1–0.25 inch."""
    return int(min(max(0.07 * min(w_emu, h_emu), 91440), 228600))


def estimate_capacity(bbox: Bbox, size_pt: float, bold: bool = False, insets_emu: tuple[int, int, int, int] = (91440, 45720, 91440, 45720), line_spacing: float = 1.2) -> Capacity:
    if size_pt <= 0 or bbox.w <= 0 or bbox.h <= 0:
        return Capacity(max_chars=0, max_lines=0)
    usable_w_pt = max((bbox.w - insets_emu[0] - insets_emu[2]) / EMU_PER_PT, 0.0)
    usable_h_pt = max((bbox.h - insets_emu[1] - insets_emu[3]) / EMU_PER_PT, 0.0)
    char_w = size_pt * (AVG_CHAR_EM_BOLD if bold else AVG_CHAR_EM)
    chars_per_line = int(usable_w_pt / char_w) if char_w else 0
    lines = int(usable_h_pt / (size_pt * line_spacing)) if size_pt else 0
    lines = max(lines, 1)
    return Capacity(max_chars=max(chars_per_line, 1) * lines, max_lines=lines)


_HEX_RE = re.compile(r"(?:#|hex\s*#?)\s*[0-9a-f]{6}\b", re.I)


def reference_reason(shapes: list[ShapeInfo], roles: dict[str, SlotRole]) -> Optional[str]:
    """Samples that document the template instead of showing a layout: icon/logo sheets and palette swatches.

    They feed the asset library and the tokens, but cloning one as a content slide leaves dozens of stale icons.
    """
    small_pics = sum(1 for s in shapes if roles.get(s.id) in (SlotRole.icon, SlotRole.image, SlotRole.decoration) and s.kind == ShapeKind.pic)
    icons = sum(1 for s in shapes if roles.get(s.id) == SlotRole.icon)
    texts = sum(1 for s in shapes if s.has_text and roles.get(s.id) not in (None, SlotRole.chrome))
    if max(icons, small_pics) >= 12 and max(icons, small_pics) >= 2 * max(texts, 1):
        return f"лист иконок или логотипов ({max(icons, small_pics)} шт.)"
    if shapes:
        area = max(max(s.bbox.x2 for s in shapes), 1) * max(max(s.bbox.y2 for s in shapes), 1)
        tiny = sum(1 for s in shapes if not s.has_text and s.kind in (ShapeKind.sp, ShapeKind.pic) and s.bbox.area < 0.004 * area)
        if tiny >= 40 and tiny >= 4 * max(texts, 1):
            return f"лист графических элементов ({tiny} шт.)"
    swatches = sum(1 for s in shapes if s.has_text and _HEX_RE.search(s.plain_text))
    if swatches >= 3:
        return f"палитра шаблона ({swatches} образцов цвета)"
    links = sum(len(s.element.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}hlinkClick")) for s in shapes if s.element is not None and s.has_text)
    if links >= 3:
        return f"список полезных ссылок ({links} ссылок)"
    return None


def slot_style(s: ShapeInfo) -> SlotStyle:
    if not s.text:
        return SlotStyle()
    return SlotStyle(
        font_family=s.text.dominant_font,
        size_pt=s.text.dominant_size_pt,
        bold=s.text.bold_share > 0.5,
        color_hex=s.text.dominant_color,
        align=s.text.dominant_align,
    )


_TEXT_ROLES = {SlotRole.title, SlotRole.subtitle, SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption}


def build_pattern(
    pattern_id: str,
    slide_index: int,
    shapes: list[ShapeInfo],
    roles: dict[str, SlotRole],
    groups: list[RepeatGroup],
    trace: ClassificationTrace,
    family: Family,
    slide_w: int,
    slide_h: int,
    *,
    thumbnail: Optional[str] = None,
    layout_part: Optional[str] = None,
    asset_ids: Optional[dict[str, str]] = None,
    line_spacing: float = 1.2,
    body_size: float = 14.0,
    text_on: Optional[Callable[[Optional[str]], Optional[str]]] = None,
) -> Pattern:
    asset_ids = asset_ids or {}
    membership = group_membership(groups)
    slots: list[Slot] = []
    decor: list[str] = []
    counters: Counter = Counter()
    has_placeholder_text = False
    chrome: list[str] = []
    decor_boxes: list = []
    for s in sorted(shapes, key=lambda s: (s.bbox.y, s.bbox.x)):
        role = roles.get(s.id)
        if role == SlotRole.chrome:
            chrome.append(s.id)
            continue
        if role is None:
            continue
        if role == SlotRole.decoration:
            if s.image_part and s.image_part in asset_ids:
                decor.append(asset_ids[s.image_part])
            if s.kind == ShapeKind.pic and 0.04 <= s.bbox.area / float(slide_w * slide_h) < 0.6:
                decor_boxes.append(s.bbox.to_frac(slide_w, slide_h))
            continue
        container = role in (SlotRole.body, SlotRole.card_body) and not s.has_text and s.is_visual_shape
        if role in _TEXT_ROLES and not s.text and not container:
            continue
        counters[role.value] += 1
        slot_id = f"{role.value}_{counters[role.value]}"
        style = slot_style(s)
        if container:
            # an empty frame: body text of the template, coloured for the frame's own fill (or the slide under an outline)
            pad = container_inset(s.bbox.w, s.bbox.h)
            fill = s.fill_hex if s.fill_hex and s.fill_alpha >= 0.5 else None
            style = SlotStyle(size_pt=body_size, color_hex=text_on(fill) if text_on else None)
            cap = estimate_capacity(s.bbox, body_size, False, (pad, pad, pad, pad), line_spacing)
            sample = None
        elif role in _TEXT_ROLES and s.text:
            size = style.size_pt or 18.0
            cap = estimate_capacity(s.bbox, size, style.bold, s.text.insets_emu, line_spacing)
            sample = s.plain_text.strip()[:120] or None
            if sample and looks_like_placeholder(sample):
                has_placeholder_text = True
        else:
            cap = Capacity(max_chars=0, max_lines=0)
            sample = None
        gid = membership[s.id][0] if s.id in membership else None
        slots.append(Slot(id=slot_id, role=role, shape_id=s.id, bbox=s.bbox.to_frac(slide_w, slide_h), style=style, capacity=cap, group_id=gid, sample_text=sample, container=container))
    quality = 1.0
    if has_placeholder_text:
        quality -= 0.15  # placeholder text means a designer-made sample: mildly penalised only for dedupe ordering
    if trace.agreement < 0.5:
        quality -= 0.3
    if trace.kind == PatternKind.freeform:
        quality -= 0.2
    if not any(s.role in _TEXT_ROLES for s in slots):
        quality -= 0.5  # nothing to write into: decorative/blank sample
    reference = reference_reason(shapes, roles)
    return Pattern(
        id=pattern_id,
        source_slide=slide_index,
        kind=trace.kind,
        family=family,
        slots=slots,
        repeat_groups=groups,
        decor_assets=decor,
        quality=round(max(quality, 0.0), 3),
        thumbnail=thumbnail,
        classification=trace,
        layout_part=layout_part,
        chrome_shape_ids=chrome,
        reference=reference,
        decor_boxes=decor_boxes,
    )


def _slot_signature(p: Pattern) -> tuple:
    return tuple(sorted(s.role.value for s in p.slots))


def dedupe_patterns(patterns: list[Pattern], bbox_tol: float = 0.02) -> list[Pattern]:
    """Drop near-identical patterns (same kind, family, role multiset, same slot geometry); keep the best quality."""
    kept: list[Pattern] = []
    for p in sorted(patterns, key=lambda p: (-p.quality, p.source_slide)):
        dup = False
        for k in kept:
            if k.kind != p.kind or k.family != p.family or _slot_signature(k) != _slot_signature(p) or len(k.slots) != len(p.slots):
                continue
            ks = sorted(k.slots, key=lambda s: (s.role.value, s.bbox.y, s.bbox.x))
            ps = sorted(p.slots, key=lambda s: (s.role.value, s.bbox.y, s.bbox.x))
            if all(a.bbox.close_to(b.bbox, bbox_tol) for a, b in zip(ks, ps)):
                dup = True
                break
        if not dup:
            kept.append(p)
    kept.sort(key=lambda p: p.source_slide)
    return kept
