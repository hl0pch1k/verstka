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
# a template's own service slides — credits, «how to use this template», font and colour resources, instructions — as
# free template sites ship them (SlidesCarnival, Slidesgo, Canva exports): never a layout to build a slide on
_META_BRAND_RE = re.compile(r"(?<![\w])(?:slides\s?carnival|slidesgo|freepik|flaticon|storyset|pexels|pixabay|unsplash|showeet|slidemodel|presentationgo|envato|creative\s?market)(?![\w])", re.I)
_META_PHRASE_RE = re.compile(
    r"this presentation template|presentation template (?:is|was) (?:free|created)|thanks? to the following|happy designing|"
    r"resource page|design resources|use these (?:design )?resources|how to use this (?:presentation|template|deck)|instructions for use|"
    r"alternative resources|(?:please )?keep this slide|fonts? (?:&|and) colou?rs|free fonts? used|fonts used in this|"
    r"click on the [\"«]?(?:google slides|powerpoint|canva)|make a copy|as a google slides theme|"
    r"шрифты и цвета|как пользоваться (?:этим )?(?:шаблоном|презентацией)|инструкци\w* по использованию|ресурсы шаблона",
    re.I,
)


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
    # the slide's own words — not its chrome; a brand counts in a sentence («SlidesCarnival for the presentation
    # template»), never as a bare domain in a header or footer («SLIDESCARNIVAL.COM» stands on every slide)
    own = [s.plain_text for s in shapes if s.has_text and roles.get(s.id) != SlotRole.chrome]
    text = " ".join(own)
    branded = any(_META_BRAND_RE.search(t) and len(re.findall(r"[A-Za-zА-Яа-яЁё]{2,}", _META_BRAND_RE.sub(" ", t))) >= 2 and not re.fullmatch(r"\s*(?:https?://)?(?:www\.)?[\w.-]+\.\w{2,}/?\s*", t) for t in own)
    if _META_PHRASE_RE.search(text) or (branded and len(text) < 900):
        return "служебный слайд шаблона (источники, шрифты или инструкция)"
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
    # drawn mock-ups (a phone made of a group of shapes) and empty picture placeholders are sample content too
    slide_area = float(slide_w * slide_h)
    text_ids = {x.shape_id for x in slots if x.role in _TEXT_ROLES}
    groups_of: dict[str, list[ShapeInfo]] = {}
    for s in shapes:
        if s.group_path:
            groups_of.setdefault(s.group_path[0], []).append(s)
    for members in groups_of.values():
        if any(m.id in text_ids or m.has_text for m in members) or any(roles.get(m.id) == SlotRole.chrome for m in members):
            continue
        box = members[0].bbox
        for m in members[1:]:
            box = box.union(m.bbox)
        if 0.04 <= box.area / slide_area < 0.6:
            decor_boxes.append(box.to_frac(slide_w, slide_h))
    for s in shapes:
        if s.is_placeholder and s.ph_type == "pic" and not s.image_part and 0.04 <= s.bbox.area / slide_area < 0.6:
            decor_boxes.append(s.bbox.to_frac(slide_w, slide_h))
    title_shape = next((s for s in shapes if roles.get(s.id) == SlotRole.title), None)
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
        title_ph=title_shape.ph_type if title_shape is not None and title_shape.ph_type in ("title", "ctrTitle") else None,
    )


_CLOCK_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")


def mockup_on_layout(boxes: list, layout_shapes: Optional[list[ShapeInfo]], slide_w: int, slide_h: int) -> bool:
    """Some mock-up box is drawn by the layout: a shape of the layout's own, about the box's size (not the layout's
    full-bleed ground), covers most of it."""
    for b in boxes:
        box = Bbox(x=int(b.x * slide_w), y=int(b.y * slide_h), w=int(b.w * slide_w), h=int(b.h * slide_h))
        for s in layout_shapes or []:
            if s.is_placeholder or s.bbox.area > 2.5 * max(box.area, 1) or s.bbox.area >= 0.85 * slide_w * slide_h:
                continue
            if s.bbox.intersection(box) >= 0.8 * max(box.area, 1):
                return True
    return False


def mockup_boxes(shapes: list[ShapeInfo], slide_w: int, slide_h: int, layout_shapes: Optional[list[ShapeInfo]] = None) -> list:
    """Device mock-ups and empty picture frames of a sample (slide and layout art together): a portrait frame — a
    picture, a group holding a picture, or a filled shape — at least 45 % of the slide high and narrower than 0.6 of
    its height, that holds a screen (a picture of the group, an empty placeholder, a status-bar clock «9:41»); and
    every empty picture placeholder of ≥ 10 % of the slide (a photo half, not a logo slot). Without the content's own
    picture they stay empty."""
    slide_area = float(slide_w * slide_h)
    pool = list(shapes) + [s for s in (layout_shapes or []) if not s.is_placeholder]
    out: list[Bbox] = []
    frames: list[tuple[Bbox, bool]] = []  # (box, holds a picture of its own)
    groups: dict[str, list[ShapeInfo]] = {}
    for s in pool:
        if s.group_path:
            groups.setdefault(s.group_path[0], []).append(s)
    for members in groups.values():
        if any(m.has_text and not _CLOCK_RE.match(m.plain_text) for m in members):
            continue
        box = members[0].bbox
        for m in members[1:]:
            box = box.union(m.bbox)
        frames.append((box, any(m.kind == ShapeKind.pic for m in members)))
    for s in pool:
        if s.group_path or s.has_text:
            continue
        if s.kind == ShapeKind.pic or (s.kind == ShapeKind.sp and s.fill_hex and not s.is_placeholder):
            frames.append((s.bbox, False))

    def inside(o: ShapeInfo, box: Bbox) -> bool:
        cx, cy = o.bbox.x + o.bbox.w / 2, o.bbox.y + o.bbox.h / 2
        return box.x <= cx <= box.x2 and box.y <= cy <= box.y2 and o.bbox.area < box.area

    for box, own_pic in frames:
        if box.h < 0.45 * slide_h or box.w >= 0.6 * box.h or not 0.02 <= box.area / slide_area < 0.6:
            continue
        screen = own_pic or any(
            inside(o, box) and ((o.is_placeholder and not o.has_text and not o.image_part and o.ph_type in ("pic", "body", "obj", None)) or (o.has_text and _CLOCK_RE.match(o.plain_text)))
            for o in pool
        )
        if screen and not any(b.intersection(box) >= 0.8 * min(b.area, box.area) for b in out):
            out.append(box)
    # the device's body: a separate picture of the phone (with its halo) standing behind the screen — it holds the
    # screen box, is at most 3× larger, not a slide-wide ground and not a landscape strip (MyBrand's black phone left
    # behind when only the screen group was taken off the cover)
    for k, box in enumerate(out):
        for s in pool:
            if s.kind != ShapeKind.pic or s.group_path or s.has_text or s.bbox.area <= 0:
                continue
            b = s.bbox
            if b.intersection(box) >= 0.9 * box.area and b.area <= 3.0 * box.area and b.area < 0.6 * slide_area and b.w <= 1.2 * b.h:
                box = box.union(b)
        out[k] = box
    for s in shapes:
        if s.is_placeholder and s.ph_type == "pic" and not s.image_part and 0.10 <= s.bbox.area / slide_area < 0.6:
            if not any(b.intersection(s.bbox) >= 0.8 * min(b.area, s.bbox.area) for b in out):
                out.append(s.bbox)
    return [b.to_frac(slide_w, slide_h) for b in out]


_BOOKEND_KINDS = (PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.quote)


def _slot_signature(p: Pattern) -> tuple:
    return tuple(sorted(s.role.value for s in p.slots))


def dedupe_patterns(patterns: list[Pattern], bbox_tol: float = 0.02, free_tol: float = 0.10) -> list[Pattern]:
    """Drop near-identical patterns (same kind, family, role multiset, same slot geometry); keep the best quality.

    Two such samples on different layouts may differ in what the layout paints around the slots (a clean layout vs
    one with trees over the content band): when their free share differs by more than `free_tol`, the freer one is
    kept whatever the quality order."""
    kept: list[Pattern] = []
    for p in sorted(patterns, key=lambda p: (-p.quality, p.source_slide)):
        dup = None
        for n, k in enumerate(kept):
            if k.kind != p.kind or k.family != p.family or _slot_signature(k) != _slot_signature(p) or len(k.slots) != len(p.slots):
                continue
            ks = sorted(k.slots, key=lambda s: (s.role.value, s.bbox.y, s.bbox.x))
            ps = sorted(p.slots, key=lambda s: (s.role.value, s.bbox.y, s.bbox.x))
            if all(a.bbox.close_to(b.bbox, bbox_tol) for a, b in zip(ks, ps)):
                dup = n
                break
        if dup is None:
            kept.append(p)
            continue
        k = kept[dup]
        # content samples only: on a cover or a divider the layout's art is the design, not clutter
        if k.kind not in _BOOKEND_KINDS and k.layout_part != p.layout_part and k.free_share is not None and p.free_share is not None and p.free_share > k.free_share + free_tol:
            kept[dup] = p
    kept.sort(key=lambda p: p.source_slide)
    return kept
