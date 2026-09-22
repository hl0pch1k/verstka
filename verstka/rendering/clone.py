"""Clone renderer: copy a sample slide and rewrite its slots with outline content."""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree
from pptx.slide import Slide

from verstka.analysis.patterns import container_inset
from verstka.analysis.shapes import looks_like_placeholder
from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.assets_pick import pick_asset, pick_icon
from verstka.rendering.charts import add_chart
from verstka.rendering.deck import DeckBuilder, element_bbox, is_nested, remove_element, renumber_ids, set_element_pos, shift_element, slide_shape_elements
from verstka.rendering.fonts import text_width_pt, wrap_lines
from verstka.rendering.fit import fit_size, grow_size
from verstka.rendering.groups import adjust_group, cell_bbox, cell_riders, cells_elements, reading_order_key, transform_element
from verstka.rendering.images import replace_picture
from verstka.rendering.tables import add_table
from verstka.rendering.textfill import ParagraphSpec, clear_text, ensure_txbody, fill_text, has_visible_style, set_text_size, shape_text, style_runs
from verstka.schemas.common import EMU_PER_PT, Bbox, PatternKind, SlotRole
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideItem
from verstka.schemas.template import Pattern, RepeatGroup, Slot, TemplateManifest

log = logging.getLogger(__name__)

TEXT_ROLES = {SlotRole.title, SlotRole.subtitle, SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption}
CELL_TEXT_ROLES = {SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.bullet_list, SlotRole.body}
_BODY_ROLES = (SlotRole.card_body, SlotRole.bullet_list, SlotRole.body)
_ITEM_KINDS = {PatternKind.cards, PatternKind.process, PatternKind.timeline, PatternKind.team, PatternKind.comparison, PatternKind.agenda, PatternKind.two_column}
_DEFAULT_INSETS = (91440, 45720, 91440, 45720)
_ICON_MAX_W = 0.06  # pictures narrower than this share of the slide are icons: part of the card design


@dataclass
class RenderedSlide:
    outline_id: str
    index: int
    mode: str
    pattern_id: Optional[str] = None
    composition: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


class _SlideCtx:
    def __init__(self, builder: DeckBuilder, slide: Slide, pattern: Pattern, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline) -> None:
        self.builder = builder
        self.slide = slide
        self.pattern = pattern
        self.manifest = manifest
        self.ws = ws
        self.outline = outline
        self.els = slide_shape_elements(slide)
        self.filled: set[str] = set()
        self.removed: set[str] = set()
        self.cell_member_ids: set[str] = set()  # every shape of a repeat-group cell that received an item
        self.warnings: list[str] = []
        self.next_id = builder.next_shape_id(slide)
        self.typo = manifest.tokens.typography
        self.scale = [s.size_pt for s in self.typo.scale]
        self.W, self.H = manifest.slide_size.w, manifest.slide_size.h
        self.role_of = {s.shape_id: s.role for s in pattern.slots}
        self.slot_of = {s.shape_id: s for s in pattern.slots}
        self.used_assets: set[str] = set()

    # ---- helpers ----------------------------------------------------------------
    def slots(self, *roles: SlotRole, unfilled: bool = True) -> list[Slot]:
        out = [s for s in self.pattern.slots if s.role in roles and s.shape_id in self.els]
        if unfilled:
            out = [s for s in out if s.shape_id not in self.filled and s.shape_id not in self.removed]
        return out

    def id_of(self, el: etree._Element) -> Optional[str]:
        nv = el.find(".//" + q("p:cNvPr"))
        return nv.get("id") if nv is not None else None

    def fill_el(self, el: etree._Element, slot: Optional[Slot], paragraphs: list[ParagraphSpec], *, size_hint: Optional[float] = None, min_ratio: float = 0.6, grow_to: Optional[float] = None, widen: bool = False) -> None:
        if not paragraphs:
            return
        box = element_bbox(el)
        style = slot.style if slot else None
        slot_size = style.size_pt if style and style.size_pt else self.typo.size_for("body")
        size = size_hint or slot_size
        bold = bool(style and style.bold) if style else False
        family = style.font_family if style and style.font_family else self.typo.primary_family
        target_size = size
        container = slot is not None and slot.container and etree.QName(el).localname == "sp"
        if container and box and box[2] > 0 and box[3] > 0:
            pad = container_inset(box[2], box[3])
            ensure_txbody(el, (pad, pad, pad, pad))
        insets = _body_insets(el)
        if box and box[2] > 0 and box[3] > 0:
            _wrap_inside(el, [p.text for p in paragraphs], family, size, bold, box, insets)
        if box and box[2] > 0 and box[3] > 0 and slot is not None and slot.role in _GROWABLE and not container:
            box = self._room_in_holder(el, box)
        if box and box[2] > 0 and box[3] > 0 and slot is not None and (widen or slot.role in (SlotRole.title, SlotRole.subtitle)):
            box = self._widen_on_backing(el, box, [p.text for p in paragraphs], family, size, bold, insets)
        if box and box[2] > 0 and box[3] > 0:
            res = fit_size([p.text for p in paragraphs], Bbox(x=box[0], y=box[1], w=box[2], h=box[3]), family, size, bold, self.scale, insets_emu=insets, line_spacing=self.typo.line_spacing, min_ratio=min_ratio)
            target_size = res.size_pt
            if grow_to and res.fits and target_size >= size:
                target_size = grow_size([p.text for p in paragraphs], Bbox(x=box[0], y=box[1], w=box[2], h=box[3]), family, target_size, bold, self.scale, grow_to, insets_emu=insets, line_spacing=self.typo.line_spacing)
            if not res.fits:
                if slot is not None and slot.role == SlotRole.number and len(paragraphs) == 1 and not is_nested(el):
                    # a single figure never wraps well: widen the box instead of clipping
                    need_w = int(text_width_pt(paragraphs[0].text, family, target_size, True) * EMU_PER_PT * 1.15) + insets[0] + insets[2]
                    if need_w > box[2] and box[0] + need_w <= self.W * 0.97:
                        set_element_pos(el, w=need_w)
                        self.warnings.append(f"widened number slot {slot.id}")
                    elif need_w > box[2]:
                        shrink = fit_size([p.text for p in paragraphs], Bbox(x=box[0], y=box[1], w=box[2], h=box[3]), family, size, bold, self.scale, insets_emu=insets, line_spacing=self.typo.line_spacing, min_ratio=0.2)
                        target_size = shrink.size_pt
                else:
                    self.warnings.append(f"text may overflow in {slot.id if slot else 'shape'} ({res.lines} lines)")
        if box and box[2] > 0 and box[3] > 0 and any(p.size_pt for p in paragraphs):
            # an emphasised line (a figure) may be larger than the rest only as far as the box height allows
            ls = self.typo.line_spacing
            usable_w = max((box[2] - insets[0] - insets[2]) / EMU_PER_PT, 1.0)
            usable_h = max((box[3] - insets[1] - insets[3]) / EMU_PER_PT, 1.0)
            rest = sum(max(len(wrap_lines(p.text, family, target_size, bold, usable_w)), 1) for p in paragraphs if not p.size_pt) * target_size * ls
            paragraphs = [ParagraphSpec(p.text, bullet=p.bullet, level=p.level, bold=p.bold, size_pt=p.size_pt, color_hex=p.color_hex) for p in paragraphs]
            for p in paragraphs:
                if p.size_pt and p.size_pt > target_size:
                    lines = max(len(wrap_lines(p.text, family, p.size_pt, True, usable_w)), 1)
                    room = (usable_h - rest) / (ls * lines)
                    p.size_pt = round(max(target_size, min(p.size_pt, room)), 1)
        explicit = size_hint is not None or target_size != slot_size or container
        fill_text(el, paragraphs, size_pt=target_size if explicit else None)
        if container:
            style_runs(el, family, style.color_hex if style else None)
        sid = self.id_of(el)
        if sid:
            self.filled.add(sid)

    def _room_in_holder(self, el: etree._Element, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """A text box drawn on a card may take the card's empty height below it — down to the next text or picture
        in the card, or to the card's inner edge (the sample's one-line box would otherwise force tiny type)."""
        if is_nested(el):
            return box
        bodyPr = el.find(q("p:txBody") + "/" + q("a:bodyPr"))
        if bodyPr is not None and bodyPr.get("anchor") == "b":
            return box
        bx = Bbox(x=box[0], y=box[1], w=box[2], h=box[3])
        tol = int(0.01 * self.W)
        tree = el.getparent()
        holder = None
        for other in tree:
            if other is el or etree.QName(other).localname != "sp" or shape_text(other).strip() or not _has_fill(other):
                continue
            b = element_bbox(other)
            if not b or b[2] * b[3] > 0.5 * self.W * self.H or b[2] * b[3] < 1.5 * bx.area:
                continue
            ob = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
            if ob.x - tol <= bx.x and ob.y - tol <= bx.y and ob.x2 + tol >= bx.x2 and ob.y2 + tol >= bx.y2 and (holder is None or ob.area < holder.area):
                holder = ob
        if holder is None:
            return box
        pad = max(min(bx.x - holder.x, int(0.04 * self.H)), int(0.012 * self.H))
        limit = holder.y2 - pad
        for other in tree:
            if other is el or etree.QName(other).localname not in ("sp", "pic", "graphicFrame", "grpSp"):
                continue
            b = element_bbox(other)
            if not b or (b[0], b[1], b[2], b[3]) == (holder.x, holder.y, holder.w, holder.h):
                continue
            inside = holder.x <= b[0] + b[2] / 2 <= holder.x2 and holder.y <= b[1] + b[3] / 2 <= holder.y2
            overlaps_x = b[0] < bx.x2 and b[0] + b[2] > bx.x
            is_content = etree.QName(other).localname != "sp" or shape_text(other).strip() or (self.id_of(other) or "") in self.slot_of
            if inside and overlaps_x and b[1] >= bx.y2 - tol and is_content:
                limit = min(limit, b[1] - int(0.012 * self.H))
        if limit <= bx.y2 + int(0.02 * self.H):
            return box
        set_element_pos(el, h=limit - bx.y)
        return (bx.x, bx.y, bx.w, limit - bx.y)

    def _widen_on_backing(self, el: etree._Element, box: tuple[int, int, int, int], texts: list[str], family: Optional[str], size: float, bold: bool, insets: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """A heading printed on a label (pill, plate) that is too short for the new text: the label and the text box
        grow to the right together, up to the next element in the same band (logos of the layout included) or the
        safe area; a heading that still needs two lines makes both one line taller."""
        if is_nested(el):
            return box
        bx = Bbox(x=box[0], y=box[1], w=box[2], h=box[3])
        tol = int(0.01 * self.W)
        backing = None
        for other in self.els.values():
            if other is el or is_nested(other) or other.getparent() is None or etree.QName(other).localname != "sp" or shape_text(other).strip() or not _has_fill(other):
                continue
            b = element_bbox(other)
            if not b or b[2] * b[3] > max(4 * bx.area, 1) or b[2] * b[3] > 0.25 * self.W * self.H:
                continue
            ob = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
            if ob.x - tol <= bx.x and ob.y - tol <= bx.y and ob.x2 + tol >= bx.x2 and ob.y2 + tol >= bx.y2 and (backing is None or ob.area < backing[1].area):
                backing = (other, ob)
        if backing is None:
            return box
        back_el, ob = backing
        need_w = int(max(text_width_pt(t, family, size, bold) for t in texts) * EMU_PER_PT * 1.05) + insets[0] + insets[2]
        if need_w <= bx.w:
            return box
        limit = int(self.manifest.tokens.spacing.safe_area.x2 * self.W)
        obstacles = [element_bbox(o) for o in self.els.values() if o is not el and o is not back_el and not is_nested(o) and o.getparent() is not None]
        obstacles += [(lambda b: (b.x, b.y, b.w, b.h))(c.bbox.to_emu(self.W, self.H)) for c in self.manifest.tokens.chrome]
        for b in obstacles:
            if not b or b[2] * b[3] >= 0.6 * self.W * self.H:
                continue
            if b[1] < ob.y2 and b[1] + b[3] > ob.y and b[0] >= ob.x2 - tol:
                limit = min(limit, b[0] - int(0.015 * self.W))
        grow = min(need_w - bx.w, limit - ob.x2)
        if grow <= 0:
            grow = 0
        width = bx.w + grow
        height_grow = 0
        res = fit_size(texts, Bbox(x=bx.x, y=bx.y, w=width, h=bx.h), family, size, bold, self.scale, insets_emu=insets, line_spacing=self.typo.line_spacing, min_ratio=0.8)
        if not res.fits:
            two = fit_size(texts, Bbox(x=bx.x, y=bx.y, w=width, h=10 ** 9), family, size, bold, self.scale, insets_emu=insets, line_spacing=self.typo.line_spacing, min_ratio=0.8)
            if two.lines == 2:
                height_grow = max(0, int(two.height_pt * EMU_PER_PT) + insets[1] + insets[3] - bx.h)
        if grow == 0 and height_grow == 0:
            return box
        set_element_pos(el, w=width, h=bx.h + height_grow)
        set_element_pos(back_el, w=ob.w + grow, h=ob.h + height_grow)
        self.warnings.append(f"label widened by {grow * 100 // self.W}% of the slide for the heading")
        return (bx.x, bx.y, width, bx.h + height_grow)

    def fill_slot(self, slot: Slot, paragraphs: list[ParagraphSpec], **kw) -> bool:
        el = self.els.get(slot.shape_id)
        if el is None:
            return False
        self.fill_el(el, slot, paragraphs, **kw)
        return True

    def remove_slot_shape(self, slot: Slot) -> None:
        el = self.els.get(slot.shape_id)
        if el is not None and not is_nested(el):
            remove_element(el)
            self.removed.add(slot.shape_id)

    def remove_el(self, el: etree._Element) -> None:
        sid = self.id_of(el)
        remove_element(el)
        if sid:
            self.removed.add(sid)

    def largest(self, slots: list[Slot]) -> Optional[Slot]:
        return max(slots, key=lambda s: s.bbox.area) if slots else None

    def smallest_font(self, slots: list[Slot]) -> Optional[Slot]:
        return min(slots, key=lambda s: (s.style.size_pt or 99.0)) if slots else None


_GROWABLE = {SlotRole.body, SlotRole.bullet_list, SlotRole.card_body, SlotRole.card_title, SlotRole.number_label, SlotRole.caption}


def _wrap_inside(el: etree._Element, texts: list[str], family: Optional[str], size: float, bold: bool, box: tuple[int, int, int, int], insets: tuple[int, int, int, int]) -> None:
    """A box set to «no wrap» for a one-word sample must wrap a longer text inside its own width, not run across
    the neighbouring column."""
    bodyPr = el.find(q("p:txBody") + "/" + q("a:bodyPr"))
    if bodyPr is None or bodyPr.get("wrap") != "none":
        return
    widest = max((text_width_pt(t, family, size, bold) for t in texts), default=0.0) * EMU_PER_PT
    if widest > box[2] - insets[0] - insets[2]:
        bodyPr.set("wrap", "square")


def _has_fill(el: etree._Element) -> bool:
    """A shape that paints an area: explicit solid/gradient/picture fill or a theme fill reference."""
    spPr = el.find(q("p:spPr"))
    if spPr is not None:
        if spPr.find(q("a:noFill")) is not None:
            return False
        if any(spPr.find(q(t)) is not None for t in ("a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill")):
            return True
    ref = el.find(q("p:style") + "/" + q("a:fillRef"))
    return ref is not None and (ref.get("idx") or "0") != "0"


def _body_insets(el: etree._Element) -> tuple[int, int, int, int]:
    """Text insets of a shape (the templates set explicit zeros; PowerPoint defaults apply when absent)."""
    txBody = el.find(q("p:txBody"))
    bodyPr = txBody.find(q("a:bodyPr")) if txBody is not None else None
    if bodyPr is None:
        return _DEFAULT_INSETS
    out = []
    for name, default in zip(("lIns", "tIns", "rIns", "bIns"), _DEFAULT_INSETS):
        v = bodyPr.get(name)
        try:
            out.append(int(v) if v is not None else default)
        except ValueError:
            out.append(default)
    return out[0], out[1], out[2], out[3]


# ---------------------------------------------------------------------------- content helpers


def _items_for(oslide: OutlineSlide) -> list[SlideItem]:
    c = oslide.content
    if c.items:
        return list(c.items)
    if c.columns:
        return list(c.columns)
    if c.numbers:
        return [SlideItem(title=n.value, text=n.label, number=n.value) for n in c.numbers]
    if oslide.kind in _ITEM_KINDS and c.bullets:
        return [SlideItem(title=b) for b in c.bullets]
    return []


def _item_body_paragraphs(item: SlideItem) -> list[ParagraphSpec]:
    out = [ParagraphSpec(item.text, bullet=False)] if item.text else []
    out += [ParagraphSpec(b, bullet=True) for b in item.bullets]
    return out


def _label_paragraphs(item: SlideItem) -> list[ParagraphSpec]:
    """Everything of an item except its figure: the title (bold when a text follows) and the text/bullets."""
    body = _item_body_paragraphs(item)
    head = item.title if item.title and item.title != item.number else ""
    if head and body:
        return [ParagraphSpec(head, bullet=False, bold=True)] + body
    if head:
        return [ParagraphSpec(head, bullet=False)]
    if body:
        return body
    return [ParagraphSpec(item.title, bullet=False)] if item.title else []


def _item_single_paragraphs(item: SlideItem, include_number: bool = True) -> list[ParagraphSpec]:
    """Everything of an item in one text shape (cells that have a single text slot)."""
    if item.number:
        if not include_number:
            return _label_paragraphs(item)
        return [ParagraphSpec(item.number, bullet=False, bold=True)] + _label_paragraphs(item)
    return _label_paragraphs(item)


def _ordinal(idx: int, sample: Optional[str]) -> str:
    """01 / 1 style sequence number matching the template's sample."""
    sm = (sample or "").strip()
    if len(sm) == 2 and sm.isdigit() and sm.startswith("0"):
        return f"{idx + 1:02d}"
    return str(idx + 1)


def _merge_items(items: list[SlideItem], n: int) -> list[SlideItem]:
    """Reduce items to n cells: plain theses are spread evenly as bullet lists, richer items fold into the last cell."""
    if len(items) <= n or n <= 0:
        return items
    if all(not x.text and not x.bullets for x in items):
        # every cell gets a share: 5 theses into 4 cells is 2+1+1+1, never 2+2+1 and an empty fourth card
        base, extra = divmod(len(items), n)
        out, k = [], 0
        for j in range(n):
            take = base + (1 if j < extra else 0)
            chunk = items[k : k + take]
            k += take
            if len(chunk) == 1:
                out.append(chunk[0])
            elif chunk:
                out.append(SlideItem(title="", bullets=[x.title for x in chunk], icon_hint=chunk[0].icon_hint, number=chunk[0].number))
        return out
    head = items[: n - 1]
    tail = items[n - 1 :]
    texts = [tail[0].text]
    bullets = list(tail[0].bullets)
    for x in tail[1:]:
        if x.text:
            texts.append(f"{x.title}: {x.text}")
        bullets += x.bullets
        if not x.text and not x.bullets:
            bullets.append(x.title)
    merged = SlideItem(title=tail[0].title, text="; ".join(t for t in texts if t), icon_hint=tail[0].icon_hint, number=tail[0].number, bullets=bullets)
    return head + [merged]


def _text_groups(ctx: _SlideCtx, exclude_number_only: bool = False) -> list[RepeatGroup]:
    out = []
    for g in ctx.pattern.repeat_groups:
        ids = {sid for cell in g.member_shape_ids for sid in cell}
        roles = {ctx.role_of.get(sid) for sid in ids}
        if roles & CELL_TEXT_ROLES and len(g.member_shape_ids) >= 2:
            if exclude_number_only and not (roles & {SlotRole.card_title, SlotRole.card_body, SlotRole.bullet_list, SlotRole.body}):
                continue
            out.append(g)
    return out


def _slot_chars(ctx: _SlideCtx, slot: Slot) -> int:
    if slot.capacity.max_chars:
        return slot.capacity.max_chars
    size = slot.style.size_pt or ctx.typo.size_for("body", 14.0)
    w_pt = slot.bbox.w * ctx.W / EMU_PER_PT
    h_pt = slot.bbox.h * ctx.H / EMU_PER_PT
    return int(max(w_pt / (0.55 * size), 0) * max(h_pt / (1.2 * size), 0))


def _cells_can_hold_bullets(ctx: _SlideCtx, bullets: list[str]) -> bool:
    """Bullets become cell items only when the biggest text group can actually show them (not legend chips)."""
    groups = _text_groups(ctx, exclude_number_only=True)
    if not groups:
        return False
    group = max(groups, key=lambda g: len(g.member_shape_ids))
    slots = [ctx.slot_of[sid] for cell in group.member_shape_ids for sid in cell if sid in ctx.slot_of and ctx.slot_of[sid].role in CELL_TEXT_ROLES]
    if not slots:
        return False
    if max(s.bbox.w for s in slots) < 0.10:
        return False
    need = sum(len(b) for b in bullets)
    return sum(_slot_chars(ctx, s) for s in slots) >= 0.5 * need


# ---------------------------------------------------------------------------- repeat-group cells


def _cell_sort_key(cells: list[list[etree._Element]], slide_h: int):
    return reading_order_key(cells, slide_h)


def _companions(ctx: _SlideCtx, group: RepeatGroup, before: list[Optional[Bbox]]) -> list[tuple[RepeatGroup, list[tuple[int, list[etree._Element]]]]]:
    """Other groups on the same axis whose cells sit in this group's cell positions: [(group, [(cell index, elements)])]."""
    boxes = [b for b in before if b is not None]
    if group.axis not in ("row", "column") or len(boxes) != len(before) or not boxes:
        return []
    row = group.axis == "row"
    starts = [b.x if row else b.y for b in boxes]
    size0 = boxes[0].w if row else boxes[0].h
    pitch = (starts[1] - starts[0]) if len(starts) > 1 else size0 + int(group.gap * (ctx.W if row else ctx.H))
    if pitch <= 0:
        return []
    band_lo = min((b.y if row else b.x) for b in boxes)
    band_hi = max((b.y2 if row else b.x2) for b in boxes)
    band_size = max((b.h if row else b.w) for b in boxes)
    out = []
    for g in ctx.pattern.repeat_groups:
        if g.id == group.id or g.axis != group.axis:
            continue
        mapped: list[tuple[int, list[etree._Element]]] = []
        ok = True
        for c in cells_elements(ctx.slide, g):
            b = cell_bbox(c)
            if b is None:
                ok = False
                break
            center = (b.x + b.w / 2) if row else (b.y + b.h / 2)
            i = int((center - starts[0]) // pitch)
            lo, hi = (b.y, b.y2) if row else (b.x, b.x2)
            gap = max(0, max(lo, band_lo) - min(hi, band_hi))
            # a companion row may sit far below its labels (VK Tech stat row: titles at 25% height, figures at 58%):
            # alignment along the axis is what matters, the cross-axis distance only has to stay within the content area
            if i < 0 or i >= len(starts) or gap > max(1.2 * max(band_size, hi - lo), 0.4 * (ctx.H if row else ctx.W)):
                ok = False
                break
            mapped.append((i, c))
        idx = [i for i, _ in mapped]
        if ok and mapped and len(set(idx)) == len(idx):
            out.append((g, mapped))
    return out


def _cell_entries(ctx: _SlideCtx, group: RepeatGroup, cell: list[etree._Element], extra: list[etree._Element]) -> list[tuple[etree._Element, Optional[Slot], Optional[SlotRole]]]:
    """(element, slot, role) for every member of a cell; duplicated cells (fresh ids) take roles by position."""
    src_ids = group.member_shape_ids[0]
    out = []
    for j, e in enumerate(cell):
        sid = ctx.id_of(e) or ""
        if sid in ctx.role_of:
            out.append((e, ctx.slot_of.get(sid), ctx.role_of[sid]))
        elif len(src_ids) == len(cell):
            out.append((e, ctx.slot_of.get(src_ids[j]), ctx.role_of.get(src_ids[j])))
        else:
            out.append((e, None, None))
    for e in extra:
        sid = ctx.id_of(e) or ""
        out.append((e, ctx.slot_of.get(sid), ctx.role_of.get(sid)))
    return out


def _reading_order(entries, under=None):
    """Entries by rows then columns; with `under` (a title element) the slots lined up below it come first."""
    tb = element_bbox(under) if under is not None else None

    def key(x):
        b = element_bbox(x[0])
        if not b:
            return (0, 0, 0)
        aligned = 0
        if tb:
            cx = b[0] + b[2] / 2
            aligned = 0 if tb[0] - b[2] * 0.2 <= cx <= tb[0] + tb[2] + b[2] * 0.2 else 1
        return (aligned, round(b[1] / 45720), b[0])

    return sorted(entries, key=key)


def _fill_one_cell(ctx: _SlideCtx, entries, chunk: list[SlideItem], cell_idx: int, *, include_number: bool, use_ordinals: bool, per_cell: int) -> None:
    """Write one item (or `per_cell` consecutive figures) into the text slots of a cell."""
    text = _reading_order([x for x in entries if x[2] in CELL_TEXT_ROLES and etree.QName(x[0]).localname == "sp"])
    nums = [x for x in text if x[2] == SlotRole.number]
    labels = [x for x in text if x[2] == SlotRole.number_label]
    titles = [x for x in text if x[2] == SlotRole.card_title]
    bodies = [x for x in text if x[2] in _BODY_ROLES]
    if not nums:
        bodies = _reading_order(labels + bodies)
        labels = []
    if not titles and len(bodies) >= 2:
        # two text boxes of different size in one cell: the bigger one is the card title (WorkSpace p13/p16 rows)
        sizes = [(s.style.size_pt if s is not None and s.style.size_pt else 0.0) for _, s, _ in bodies]
        big = max(range(len(bodies)), key=lambda i: sizes[i])
        if sizes[big] > 1.15 * min(sizes):
            titles = [bodies.pop(big)]
    item = chunk[0] if chunk else None

    def write(slot_list, paras, **kw):
        for k, (e, s, _) in enumerate(slot_list):
            if k == 0 and paras:
                ctx.fill_el(e, s, paras, **kw)
            else:
                clear_text(e)

    if item is None:
        write(text, [])
        return
    if per_cell > 1:
        # a cell with several figures (Education p46): consecutive items into consecutive number/label slots
        label_slots = labels or bodies
        for k, (e, s, _) in enumerate(nums):
            if k < len(chunk):
                ctx.fill_el(e, s, [ParagraphSpec(chunk[k].number or chunk[k].title)], min_ratio=0.35)
            else:
                clear_text(e)
        for k, (e, s, _) in enumerate(label_slots):
            paras = _label_paragraphs(chunk[k]) if k < len(chunk) else []
            if paras:
                ctx.fill_el(e, s, paras)
            else:
                clear_text(e)
        for k, it in enumerate(chunk):
            if k >= len(label_slots) and (it.text or it.bullets):
                ctx.warnings.append(f"label of «{it.number or it.title}» had no slot in cell {cell_idx + 1}")
        write(titles, [])
        if labels:
            write(bodies, [])
        return
    if len(text) == 1:
        e, s, _ = text[0]
        ctx.fill_el(e, s, _item_single_paragraphs(item, include_number=include_number))
        return
    if item.number and not include_number:
        # the figure goes to a standalone number slot: the cell shows the label only
        item = SlideItem(title=item.text or item.title, icon_hint=item.icon_hint, bullets=item.bullets)
    head: Optional[ParagraphSpec] = None
    if item.number:
        if nums:
            write(nums, [ParagraphSpec(item.number)], min_ratio=0.35)
        else:
            # no figure slot in the card: the figure leads it, set a few steps above the card's text
            host = titles[0][1] if titles else (bodies[0][1] if bodies else None)
            base = (host.style.size_pt if host is not None and host.style.size_pt else ctx.typo.size_for("body", 14.0))
            big = min(max(base * 1.7, base + 8), ctx.typo.size_for("h1", base * 2.4))
            head = ParagraphSpec(item.number, bullet=False, bold=True, size_pt=big)
        title = item.title if item.title and item.title != item.number else ""
    else:
        if nums:
            write(nums, [ParagraphSpec(_ordinal(cell_idx, nums[0][1].sample_text if nums[0][1] else None))] if use_ordinals else [], min_ratio=0.35)
        title = item.title
    body_paras = _item_body_paragraphs(item)
    body_slots = _reading_order(labels + bodies, under=titles[0][0] if titles else None)
    if head is not None:
        if titles:
            write(titles, [head])
            body = ([ParagraphSpec(title, bullet=False, bold=True)] if title else []) + body_paras
        else:
            body = [head] + ([ParagraphSpec(title, bullet=False, bold=True)] if title else []) + body_paras
    elif titles and title:
        if not body_paras:
            # a thesis card: the empty description slot leaves, the heading takes the card's height instead of
            # shrinking into its one-line box
            for e, _, _ in body_slots:
                if not is_nested(e) and e.getparent() is not None:
                    ctx.remove_el(e)
            body_slots = []
        write(titles, [ParagraphSpec(title)])
        body = body_paras
    elif title and body_paras:
        write(titles, [])
        body = [ParagraphSpec(title, bullet=False, bold=True)] + body_paras
    else:
        write(titles, [])
        body = body_paras or ([ParagraphSpec(title)] if title else [])
    if body and not body_slots:
        if titles and not head and title and not (item.text or item.bullets):
            pass  # the title slot already shows the whole item
        else:
            lost = "; ".join(p.text for p in body if p.text)
            ctx.warnings.append(f"text of «{item.number or item.title or lost[:20]}» had no slot in cell {cell_idx + 1}")
    write(body_slots, body)


def _fill_cells(ctx: _SlideCtx, items: list[SlideItem], use_ordinals: bool = True, text_only: bool = False) -> bool:
    """Write items into the pattern's biggest text-bearing repeat group (and the groups aligned with it). Returns True when handled."""
    groups = _text_groups(ctx, exclude_number_only=text_only)
    if not groups or not items:
        return False
    group = max(groups, key=lambda g: len(g.member_shape_ids))
    orig = cells_elements(ctx.slide, group)
    if not orig:
        return False
    orig.sort(key=_cell_sort_key(orig, ctx.H))
    before = [cell_bbox(c) for c in orig]
    companions = _companions(ctx, group, before)
    companion_ids = {g.id for g, _ in companions}
    src_roles = [ctx.role_of.get(sid) for sid in group.member_shape_ids[0]]
    comp_roles = {ctx.role_of.get(sid) for g, _ in companions for cell in g.member_shape_ids for sid in cell}
    numbers_in_cells = SlotRole.number in src_roles or SlotRole.number in comp_roles
    numeric_items = any(i.number for i in items)
    n_numeric = sum(1 for i in items if i.number)
    per_cell = max(1, src_roles.count(SlotRole.number)) if numeric_items else 1
    n_needed = -(-len(items) // per_cell)
    # titles, subtitles and companion cells are never riders: companions are mapped to their primary cell below
    protected = {sl.shape_id for sl in ctx.pattern.slots if sl.role in (SlotRole.title, SlotRole.subtitle)}
    protected |= {sid for g, _ in companions for cell in g.member_shape_ids for sid in cell}
    cells, ctx.next_id = adjust_group(ctx.slide, group, n_needed, ctx.W, ctx.H, ctx.next_id, protected_ids=protected)
    if not cells:
        return False
    cells.sort(key=_cell_sort_key(cells, ctx.H))  # same order as `before`: items, shifts and companions go by index
    after = [cell_bbox(c) for c in cells]
    # companion cells follow their primary cell: moved and resized with it, removed with it, copied for new cells
    extra: list[list[etree._Element]] = [[] for _ in cells]
    for g, mapped in companions:
        for i, c in mapped:
            if i < len(cells):
                b0, b1 = before[i], after[i]
                if b0 is not None and b1 is not None and (b0.x, b0.y, b0.w, b0.h) != (b1.x, b1.y, b1.w, b1.h):
                    for e in c:
                        if not is_nested(e):
                            transform_element(e, b0, b1, group.axis)
                extra[i].extend(c)
            else:
                for e in c:
                    ctx.remove_el(e)
        src_i = max((i for i, _ in mapped if i < len(before)), default=None)
        if src_i is None or len(cells) <= len(before) or src_i >= len(after):
            continue
        src = dict(mapped)[src_i]
        if any(is_nested(e) for e in src):
            continue
        for i in range(len(before), len(cells)):
            if after[i] is None or after[src_i] is None:
                continue
            anchor = src[-1]
            for e in src:
                ne = copy.deepcopy(e)
                ctx.next_id = renumber_ids(ne, ctx.next_id)
                anchor.addnext(ne)
                anchor = ne
                transform_element(ne, after[src_i], after[i], group.axis)
                old_id, new_id = ctx.id_of(e), ctx.id_of(ne)
                if old_id and new_id:
                    ctx.els[new_id] = ne
                    if old_id in ctx.slot_of:
                        ctx.slot_of[new_id] = ctx.slot_of[old_id]
                        ctx.role_of[new_id] = ctx.role_of[old_id]
                extra[i].append(ne)
    capacity = len(cells) * per_cell
    overflow: list[SlideItem] = []
    if numeric_items:
        overflow = items[capacity:]
        items = items[:capacity]
    else:
        items = _merge_items(items, len(cells))
        if len(items) > len(cells):
            ctx.warnings.append(f"{len(items) - len(cells)} items dropped: group holds {len(cells)}")
            items = items[: len(cells)]
    standalone_numbers = sorted([s for s in ctx.slots(SlotRole.number) if s.group_id != group.id and s.group_id not in companion_ids], key=lambda s: -(s.style.size_pt or 0.0))
    include_number = numbers_in_cells or not standalone_numbers or len(standalone_numbers) < n_numeric
    seen: set[str] = set()
    cell_bodies: list[tuple[etree._Element, Optional[Slot]]] = []
    cell_numbers: list[tuple[etree._Element, Optional[Slot]]] = []
    cell_titles: list[tuple[etree._Element, Optional[Slot]]] = []
    cell_heads: list[etree._Element] = []
    for cell_idx, cell in enumerate(cells):
        chunk = items[cell_idx * per_cell : (cell_idx + 1) * per_cell]
        entries = _cell_entries(ctx, group, cell, extra[cell_idx])
        # a shape listed in two cells (overlapping detection) belongs to the first one
        entries = [x for x in entries if (ctx.id_of(x[0]) or "") not in seen]
        seen.update(ctx.id_of(x[0]) or "" for x in entries)
        _fill_one_cell(ctx, entries, chunk, cell_idx, include_number=include_number, use_ordinals=use_ordinals, per_cell=per_cell)
        item = chunk[0] if chunk else None
        for e, slot, role in entries:
            if role == SlotRole.icon and item is not None and item.icon_hint and etree.QName(e).localname == "pic":
                picked = pick_icon(ctx.manifest, ctx.ws, item.icon_hint, exclude=ctx.used_assets)
                if picked:
                    aid, path = picked
                    if replace_picture(ctx.slide, e, path):
                        ctx.used_assets.add(aid)
                        sid = ctx.id_of(e)
                        if sid:
                            ctx.filled.add(sid)
        for e, _, _ in entries:
            for nv in e.iter(q("p:cNvPr")):
                ctx.cell_member_ids.add(nv.get("id"))
        for e, slot, role in entries:
            if (ctx.id_of(e) or "") in ctx.filled and etree.QName(e).localname == "sp" and e.getparent() is not None:
                if role == SlotRole.number:
                    cell_numbers.append((e, slot))
                elif role == SlotRole.card_title:
                    if item is not None and item.number and shape_text(e).strip() == item.number:
                        cell_heads.append(e)  # an emphasised figure: sized with the other figures, not with titles
                    else:
                        cell_titles.append((e, slot))
                elif role in _BODY_ROLES or role == SlotRole.number_label:
                    cell_bodies.append((e, slot))
    # one size for the same role in every card: the smallest that fits all of them, grown along the scale when all have room
    _harmonize(ctx, cell_bodies, cap=_text_cap(ctx))
    _harmonize(ctx, cell_titles, cap=None)
    _harmonize(ctx, cell_numbers, cap=None, min_ratio=0.35)
    _harmonize_first_lines(cell_heads)
    if numeric_items and not include_number:
        # figures live outside the group (big_number patterns): the largest standalone slot takes the first one
        for slot, item in zip(standalone_numbers, [i for i in items if i.number]):
            ctx.fill_slot(slot, [ParagraphSpec(item.number)], min_ratio=0.35)
    if overflow:
        _fill_standalone_items(ctx, overflow)
    return True


def _text_cap(ctx: _SlideCtx) -> float:
    """Running text may grow up to ~1.4× the body size of the template (never into heading sizes)."""
    body = ctx.typo.size_for("body", 14.0)
    return min(ctx.typo.size_for("h2", body * 1.4), body * 1.4)


def _harmonize(ctx: _SlideCtx, pairs: list[tuple[etree._Element, Optional[Slot]]], cap: Optional[float], min_ratio: float = 0.6) -> None:
    if len(pairs) < 2 and cap is None:
        return
    sizes: list[float] = []
    for e, slot in pairs:
        b = element_bbox(e)
        texts = [t for t in shape_text(e).split("\n")]
        if not b or b[2] <= 0 or b[3] <= 0 or not any(t.strip() for t in texts):
            continue
        style = slot.style if slot is not None else None
        base = style.size_pt if style and style.size_pt else ctx.typo.size_for("body", 14.0)
        family = style.font_family if style and style.font_family else ctx.typo.primary_family
        bold = bool(style and style.bold)
        box = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
        ins = _body_insets(e)
        res = fit_size(texts, box, family, base, bold, ctx.scale, insets_emu=ins, line_spacing=ctx.typo.line_spacing, min_ratio=min_ratio)
        size = res.size_pt
        if cap is not None and res.fits:
            size = grow_size(texts, box, family, size, bold, ctx.scale, cap, insets_emu=ins, line_spacing=ctx.typo.line_spacing)
        sizes.append(size)
    if sizes:
        common = min(sizes)
        for e, _ in pairs:
            set_text_size(e, common)


def _harmonize_first_lines(els: list[etree._Element]) -> None:
    """Figures leading their cards share one size: the smallest one that fitted."""
    firsts = []
    for e in els:
        p0 = e.find(q("p:txBody") + "/" + q("a:p"))
        sizes = [int(r.get("sz")) for r in p0.iter(q("a:rPr")) if r.get("sz")] if p0 is not None else []
        if sizes:
            firsts.append((p0, min(sizes)))
    if len(firsts) < 2:
        return
    common = min(sz for _, sz in firsts)
    for p0, _ in firsts:
        for r in list(p0.iter(q("a:rPr"))) + list(p0.iter(q("a:endParaRPr"))):
            r.set("sz", str(common))


def _nearest_label(slot: Slot, labels: list[Slot]) -> Optional[Slot]:
    if not labels:
        return None
    cx, cy = slot.bbox.x + slot.bbox.w / 2, slot.bbox.y + slot.bbox.h / 2

    def dist(lab: Slot) -> float:
        lx, ly = lab.bbox.x + lab.bbox.w / 2, lab.bbox.y + lab.bbox.h / 2
        return abs(lx - cx) + abs(ly - cy) + (0.5 if ly < cy - slot.bbox.h / 2 else 0.0)  # labels sit below or beside a figure

    return min(labels, key=dist)


def _fill_standalone_items(ctx: _SlideCtx, items: list[SlideItem]) -> None:
    """Items into ungrouped slots: numbers/labels first, then card titles/bodies, rest into a list slot."""
    numbers = sorted([s for s in ctx.slots(SlotRole.number) if s.shape_id not in ctx.cell_member_ids], key=lambda s: -(s.style.size_pt or 0.0))
    labels = [s for s in ctx.slots(SlotRole.number_label) if s.shape_id not in ctx.cell_member_ids]
    if numbers and any(i.number for i in items):
        num_items = [i for i in items if i.number]
        for slot, item in zip(numbers, num_items):
            ctx.fill_slot(slot, [ParagraphSpec(item.number)], min_ratio=0.35)
            lab = _nearest_label(slot, labels)
            paras = _label_paragraphs(item)
            if lab is not None and paras:
                ctx.fill_slot(lab, paras)
                labels.remove(lab)
            elif paras:
                ctx.warnings.append(f"label of «{item.number}» had no slot")
        placed = min(len(numbers), len(num_items))
        if len(num_items) > placed:
            ctx.warnings.append(f"{len(num_items) - placed} numbers had no slot: {', '.join(i.number or '' for i in num_items[placed:])}")
        items = [i for i in items if not i.number] + num_items[placed:]
    elif numbers and len(numbers) >= len(items) >= 2:
        # ordinal markers next to standalone card slots (agenda / process patterns)
        for idx, (slot, item) in enumerate(zip(sorted(numbers, key=lambda s: (s.bbox.y, s.bbox.x)), items)):
            ctx.fill_slot(slot, [ParagraphSpec(_ordinal(idx, slot.sample_text))], min_ratio=0.35)
    titles = ctx.slots(SlotRole.card_title)
    bodies = ctx.slots(SlotRole.card_body)
    n = max(len(titles), len(bodies))
    if n and items:
        items2 = _merge_items(items, n)
        for slot, item in zip(titles, items2):
            ctx.fill_slot(slot, [ParagraphSpec(item.title or item.number or "")] if (item.title or item.number) else [])
        for k, (slot, item) in enumerate(zip(bodies, items2)):
            if k < len(titles):
                ctx.fill_slot(slot, _item_body_paragraphs(item) or ([ParagraphSpec(item.title)] if item.title else []))
            else:
                ctx.fill_slot(slot, _item_single_paragraphs(item))  # no title slot for this body: the title goes bold on top
        if len(titles) > len(bodies):
            for item in items2[len(bodies) : len(titles)]:
                if item.text or item.bullets:
                    ctx.warnings.append(f"text of «{item.title}» had no slot")
        items = items2[n:]
    if items:
        target = ctx.slots(SlotRole.bullet_list, SlotRole.body)
        if target:
            big = ctx.largest(target)
            paras: list[ParagraphSpec] = []
            for i in items:
                head = i.number or i.title
                if i.bullets:
                    if head:
                        paras.append(ParagraphSpec(head, bullet=False, bold=True))
                    if i.text:
                        paras.append(ParagraphSpec(i.text, bullet=False))
                    paras += [ParagraphSpec(b, bullet=True) for b in i.bullets]
                else:
                    paras.append(ParagraphSpec(f"{head}: {i.text}" if i.text and head else (i.text or head), bullet=True))
            ctx.fill_slot(big, paras)
        else:
            ctx.warnings.append(f"{len(items)} items had no slot: {', '.join((i.number or i.title)[:30] for i in items)}")


# ---------------------------------------------------------------------------- native objects


def _clamp_to_safe(box: Bbox, ctx: _SlideCtx) -> Bbox:
    safe = ctx.manifest.tokens.spacing.safe_area
    x = max(box.x, int(safe.x * ctx.W))
    y = max(box.y, int(safe.y * ctx.H))
    x2 = min(box.x2, int(safe.x2 * ctx.W))
    y2 = min(box.y2, int(safe.y2 * ctx.H))
    if x2 - x >= 0.2 * ctx.W and y2 - y >= 0.15 * ctx.H:
        return Bbox(x=x, y=y, w=x2 - x, h=y2 - y)
    return box


def _grow_into_free_area(box: Bbox, ctx: _SlideCtx, oslide: Optional[OutlineSlide] = None) -> Bbox:
    """A sample table/chart area far smaller than the free content area (Education keeps a 25%-wide sample table)
    grows inside the safe area below its top edge — over text slots that will stay empty, never over anything else."""
    safe = ctx.manifest.tokens.spacing.safe_area
    if box.area >= 0.3 * ctx.W * ctx.H:
        return box
    keeps_text = bool(oslide and (oslide.content.paragraphs or oslide.content.bullets))
    tree = ctx.slide._element.cSld.find(q("p:spTree"))
    blockers = []
    for el in tree:
        if etree.QName(el).localname not in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp"):
            continue
        b = element_bbox(el)
        sid = ctx.id_of(el) or ""
        if not b or b[2] * b[3] >= 0.6 * ctx.W * ctx.H or sid in ctx.pattern.chrome_shape_ids:
            continue
        slot = ctx.slot_of.get(sid)
        if slot is not None and slot.role in (SlotRole.title, SlotRole.subtitle):
            if b[1] + b[3] <= box.y + int(0.01 * ctx.H):
                continue  # the heading above
        elif slot is not None and slot.role in TEXT_ROLES and sid not in ctx.filled and not has_visible_style(el) and not keeps_text:
            continue  # an empty text slot: the cleanup removes it
        blockers.append(Bbox(x=b[0], y=b[1], w=b[2], h=b[3]))
    x1, x2 = int(safe.x * ctx.W), int(safe.x2 * ctx.W)
    y2 = int(safe.y2 * ctx.H)
    gap_x, gap_y = int(0.02 * ctx.W), int(0.02 * ctx.H)
    for o in blockers:
        if o.y2 <= box.y or o.y >= y2:
            continue
        if o.x2 <= box.x + 1:
            x1 = max(x1, o.x2 + gap_x)
        elif o.x >= box.x2 - 1:
            x2 = min(x2, o.x - gap_x)
    for o in blockers:
        if o.x < x2 and o.x2 > x1 and o.y >= box.y2 - 1:
            y2 = min(y2, o.y - gap_y)
    grown = Bbox(x=min(box.x, x1), y=box.y, w=max(box.x2, x2) - min(box.x, x1), h=max(box.h, y2 - box.y))
    return grown if grown.area > box.area else box


def _place_native_object(ctx: _SlideCtx, oslide: OutlineSlide) -> None:
    c = oslide.content
    manifest = ctx.manifest
    # sample charts/tables/images on the slide are replaced by the native object
    candidates = ctx.slots(SlotRole.image)
    frames = [ctx.slot_of[sid] for sid, el in ctx.els.items() if etree.QName(el).localname == "graphicFrame" and sid in ctx.slot_of and sid not in ctx.removed]
    candidates = list({s.shape_id: s for s in candidates + frames}.values())
    box: Optional[Bbox] = None
    holders = [s for s in ctx.slots(SlotRole.body, SlotRole.card_body) if s.container and s.bbox.area >= 0.08 and not s.group_id]
    if holders and not any(s.bbox.area >= holders[0].bbox.area for s in candidates if s.bbox.area >= 0.08):
        # the template's empty panel is the card of the chart/table: keep it, draw the object inside its padding
        frame = max(holders, key=lambda s: s.bbox.area)
        el = ctx.els.get(frame.shape_id)
        b = element_bbox(el) if el is not None else None
        if b and b[2] > 0 and b[3] > 0:
            pad = container_inset(b[2], b[3])
            box = Bbox(x=b[0] + pad, y=b[1] + pad, w=b[2] - 2 * pad, h=b[3] - 2 * pad)
            ctx.filled.add(frame.shape_id)
            candidates = [s for s in candidates if s.bbox.area < 0.08]
            for s in candidates:
                ctx.remove_slot_shape(s)
            candidates = []
    big_candidates = [s for s in candidates if s.bbox.area >= 0.08]
    if box is None and ctx.pattern.kind in (PatternKind.chart, PatternKind.table) and not big_candidates:
        # the sample chart/table is drawn with shapes: clear everything except title/subtitle and use that area
        keep = {s.shape_id for s in ctx.pattern.slots if s.role in (SlotRole.title, SlotRole.subtitle)}
        union: Optional[Bbox] = None
        for sid, el in list(ctx.els.items()):
            if sid in keep or sid in ctx.removed or is_nested(el):
                continue
            b = element_bbox(el)
            if b and b[2] > 0 and b[3] > 0 and b[1] > 0.12 * ctx.H:
                bb = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
                union = bb if union is None else union.union(bb)
            remove_element(el)
            ctx.removed.add(sid)
        candidates = []
        if union is not None and union.area >= 0.1 * ctx.W * ctx.H:
            box = union
    if candidates:
        best = max(candidates, key=lambda s: s.bbox.area)
        el = ctx.els.get(best.shape_id)
        b = element_bbox(el) if el is not None else None
        box = Bbox(x=b[0], y=b[1], w=b[2], h=b[3]) if b and b[2] > 0 else best.bbox.to_emu(ctx.W, ctx.H)
        tbl = el.find(".//" + q("a:tbl")) if el is not None and etree.QName(el).localname == "graphicFrame" else None
        if tbl is not None:
            # Google-Slides exports keep a dummy frame extent; the grid columns and rows carry the real size
            grid_w = sum(int(g.get("w") or 0) for g in tbl.iter(q("a:gridCol")))
            rows_h = sum(int(r.get("h") or 0) for r in tbl.findall(q("a:tr")))
            box = Bbox(x=box.x, y=box.y, w=max(box.w, grid_w), h=max(box.h, rows_h))
        for s in candidates:
            ctx.remove_slot_shape(s)
    if box is None or box.area < 0.08 * ctx.W * ctx.H:
        text_slots = ctx.slots(SlotRole.body, SlotRole.bullet_list)
        if text_slots:
            big = ctx.largest(text_slots)
            el = ctx.els.get(big.shape_id)
            b = element_bbox(el) if el is not None else None
            if b and b[2] * b[3] > (box.area if box else 0):
                box = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
                ctx.remove_slot_shape(big)
    if box is None:
        safe = manifest.tokens.spacing.safe_area
        title_bottom = max((s.bbox.y2 for s in ctx.pattern.slots if s.role == SlotRole.title), default=safe.y)
        box = Bbox(x=int(safe.x * ctx.W), y=int((title_bottom + 0.03) * ctx.H), w=int(safe.w * ctx.W), h=int((safe.y2 - title_bottom - 0.05) * ctx.H))
    box = _clamp_to_safe(box, ctx) if not ctx.filled & {s.shape_id for s in holders} else box
    if not ctx.filled & {s.shape_id for s in holders}:
        box = _grow_into_free_area(box, ctx, oslide)
    # pictures the object would cover (sample screenshots, chart images marked as decoration) are removed
    for sid, el in list(ctx.els.items()):
        if sid in ctx.removed or etree.QName(el).localname != "pic" or is_nested(el):
            continue
        b = element_bbox(el)
        if not b or b[2] <= 0 or b[3] <= 0:
            continue
        pic_box = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
        if box.intersection(pic_box) > 0.3 * pic_box.area:
            remove_element(el)
            ctx.removed.add(sid)
    try:
        if c.chart is not None:
            add_chart(ctx.slide, box, c.chart, ctx.outline, manifest.components.chart_style, ctx.typo, text_hex=manifest.tokens.color_for("text.primary"), neutral_hex=next((t.hex for t in manifest.tokens.colors if t.role and t.role.startswith("neutral")), None))
        elif c.table is not None:
            add_table(ctx.slide, box, c.table, manifest.components.table_style, ctx.typo)
    except Exception as e:  # noqa: BLE001
        ctx.warnings.append(f"native object failed: {str(e)[:120]}")


# ---------------------------------------------------------------------------- cleanup helpers


def _remove_empty_cells(ctx: _SlideCtx) -> None:
    """A repeat-group cell with a text slot that received nothing loses all its shapes — and its riders (the icon
    chip next to a list line): no orphan avatars, chips or card backgrounds."""
    protected = {sl.shape_id for sl in ctx.pattern.slots if sl.role in (SlotRole.title, SlotRole.subtitle)} | set(ctx.pattern.chrome_shape_ids)
    for g in ctx.pattern.repeat_groups:
        live = [c for c in cells_elements(ctx.slide, g) if c]
        riders_of: dict[int, list[etree._Element]] = {}
        if live and not any(is_nested(e) for c in live for e in c):
            for c, r in zip(live, cell_riders(ctx.slide, g, live, protected)):
                for e in c:
                    riders_of[id(e)] = r
        for cell in g.member_shape_ids:
            if not any(ctx.role_of.get(sid) in CELL_TEXT_ROLES for sid in cell):
                continue
            if any(sid in ctx.filled for sid in cell):
                continue
            for sid in cell:
                el = ctx.els.get(sid)
                for rider in riders_of.get(id(el), []) if el is not None else []:
                    if rider.getparent() is not None and (ctx.id_of(rider) or "") not in ctx.filled:
                        ctx.remove_el(rider)
            for sid in cell:
                el = ctx.els.get(sid)
                if el is None or sid in ctx.removed or el.getparent() is None:
                    continue
                if is_nested(el):
                    if etree.QName(el).localname == "sp":
                        clear_text(el)
                    continue
                remove_element(el)
                ctx.removed.add(sid)


def _fill_label(ctx: _SlideCtx, title: Slot, oslide: OutlineSlide) -> None:
    """A short tag printed above the heading («Кейс», «Проблема» in a pill) carries the section name; without a
    section it is emptied (its pill then goes as an orphan) so running text never lands in a 1-line tag."""
    labels = [
        s for s in ctx.slots(SlotRole.body, SlotRole.caption, SlotRole.subtitle)
        if s.bbox.y2 <= title.bbox.y + 0.02 and s.bbox.h <= 0.1 and len(s.sample_text or "") <= 25 and s.shape_id != title.shape_id
    ]
    if not labels:
        return
    label = min(labels, key=lambda s: abs(s.bbox.y2 - title.bbox.y))
    tag = (oslide.section or "").strip()
    if tag and tag.lower() != oslide.headline.strip().lower() and len(tag) <= 40:
        ctx.fill_slot(label, [ParagraphSpec(tag)], min_ratio=0.8, widen=True)
    else:
        el = ctx.els.get(label.shape_id)
        if el is not None and has_visible_style(el) and not is_nested(el):
            ctx.remove_el(el)  # the tag is its own pill: an empty pill must not stay
        elif el is not None:
            clear_text(el)
        ctx.removed.add(label.shape_id)


def _remove_qr_codes(ctx: _SlideCtx) -> None:
    """QR codes of the template (a contact card on the closing slide) point to someone else's page."""
    qr_parts = {a.media_part for a in ctx.manifest.assets if a.kind == "qr" and a.media_part}
    if not qr_parts:
        return
    for pic in list(ctx.slide._element.cSld.iter(q("p:pic"))):
        blip = pic.find(".//" + q("a:blip"))
        rid = blip.get(q("r:embed")) if blip is not None else None
        try:
            part = ctx.slide.part.related_part(rid) if rid else None
        except KeyError:
            part = None
        if part is not None and str(part.partname).lstrip("/") in qr_parts:
            ctx.remove_el(pic)


def _remove_orphan_holders(ctx: _SlideCtx) -> None:
    """A plate whose text slots all stayed empty (a label pill without its tag, a note box without its note) goes,
    together with the small icons drawn on it. Plates that hold anything written, a picture or a chart stay."""
    W, H = ctx.W, ctx.H
    chrome = set(ctx.pattern.chrome_shape_ids)
    text_slots = [s for s in ctx.pattern.slots if s.role in TEXT_ROLES]
    tree = ctx.slide._element.cSld.find(q("p:spTree"))
    for sid, el in list(ctx.els.items()):
        if sid in ctx.removed or sid in ctx.filled or sid in chrome or el.getparent() is not tree or etree.QName(el).localname not in ("sp", "pic"):
            continue
        if etree.QName(el).localname == "sp" and (shape_text(el).strip() or not (_has_fill(el) or el.find(q("p:spPr") + "/" + q("a:ln")) is not None)):
            continue
        b = element_bbox(el)
        if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.5 * W * H:
            continue
        box = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])

        def inside(bx: Bbox) -> bool:
            cx, cy = bx.x + bx.w / 2, bx.y + bx.h / 2
            return box.x <= cx <= box.x2 and box.y <= cy <= box.y2

        hosted = [t for t in text_slots if t.shape_id != sid and inside(t.bbox.to_emu(W, H))]
        if not hosted or any(t.shape_id in ctx.filled for t in hosted):
            continue
        occupants = []
        busy = False
        for other in list(tree):
            if other is el or etree.QName(other).localname not in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp"):
                continue
            ob = element_bbox(other)
            if not ob or not inside(Bbox(x=ob[0], y=ob[1], w=ob[2], h=ob[3])):
                continue
            osid = ctx.id_of(other) or ""
            if etree.QName(other).localname == "graphicFrame" or osid in ctx.filled or shape_text(other).strip():
                busy = True
                break
            if ob[2] * ob[3] <= 0.2 * box.area:
                occupants.append(other)
        if busy:
            continue
        for o in [el] + occupants:
            ctx.remove_el(o)


def _remove_placeholder_boxes(ctx: _SlideCtx) -> None:
    """«Вставить фото / QR» boxes: the text shape plus the empty box drawn behind it (and any picture inside that box)."""
    for slot in ctx.pattern.slots:
        if slot.shape_id in ctx.filled or slot.shape_id in ctx.removed or not slot.sample_text:
            continue
        if not re.search(r"вставить|insert|qr|фото|photo|логотип|logo", slot.sample_text, re.I):
            continue
        el = ctx.els.get(slot.shape_id)
        if el is None or is_nested(el):
            continue
        tb = element_bbox(el)
        remove_element(el)
        ctx.removed.add(slot.shape_id)
        if not tb:
            continue
        text_box = Bbox(x=tb[0], y=tb[1], w=tb[2], h=tb[3])
        tol = int(0.005 * ctx.W)
        holders = []
        for sid, other in ctx.els.items():
            if sid in ctx.removed or sid in ctx.filled or is_nested(other) or etree.QName(other).localname not in ("sp", "pic"):
                continue
            if etree.QName(other).localname == "sp" and shape_text(other).strip():
                continue
            b = element_bbox(other)
            if not b or b[2] <= 0 or b[3] <= 0:
                continue
            ob = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
            if ob.area > 0.6 * ctx.W * ctx.H:
                continue  # a slide-sized background is not a photo box
            if ob.x - tol <= text_box.x and ob.y - tol <= text_box.y and ob.x2 + tol >= text_box.x2 and ob.y2 + tol >= text_box.y2:
                holders.append((ob, sid, other))
        if not holders:
            continue
        holders.sort(key=lambda h: h[0].area)
        box_b, box_sid, box_el = holders[0]
        remove_element(box_el)
        ctx.removed.add(box_sid)
        for ob, sid, other in holders[1:]:
            if etree.QName(other).localname == "pic" and box_b.intersection(ob) >= 0.8 * ob.area:
                remove_element(other)
                ctx.removed.add(sid)


_PAGE_NUMBER_RE = re.compile(r"^\s*(\d{1,3})\s*$")


def renumber_page_chrome(els: dict[str, etree._Element], chrome_ids: list[str], source_slide: int, index: int) -> int:
    """Hand-typed page numbers are chrome copied with the sample: write the slide's own position into them.

    A chrome text whose whole content is a 1–3 digit number close to the sample's position (designers sometimes do
    not count the title) is a page number; the zero padding of the sample is kept, native slide-number fields are
    left alone. Returns how many shapes were rewritten.
    """
    done = 0
    for sid in chrome_ids:
        el = els.get(sid)
        if el is None or etree.QName(el).localname != "sp" or el.find(".//" + q("a:fld")) is not None:
            continue
        m = _PAGE_NUMBER_RE.match(shape_text(el))
        if not m or abs(int(m.group(1)) - source_slide) > 2:
            continue
        ts = list(el.iter(q("a:t")))
        if not ts:
            continue
        ts[0].text = f"{index:0{len(m.group(1))}d}"
        for t in ts[1:]:
            t.text = ""
        done += 1
    return done


# ---------------------------------------------------------------------------- main


def render_clone(builder: DeckBuilder, plan_slide: LayoutSlide, oslide: OutlineSlide, pattern: Pattern, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline) -> tuple[Slide, list[str]]:
    slide = builder.clone_slide(pattern.source_slide)
    ctx = _SlideCtx(builder, slide, pattern, manifest, ws, outline)
    c = oslide.content
    renumber_page_chrome(ctx.els, pattern.chrome_shape_ids, pattern.source_slide, len(builder.created))

    # title / subtitle
    titles = ctx.slots(SlotRole.title)
    if titles:
        ctx.fill_slot(titles[0], [ParagraphSpec(oslide.headline)], min_ratio=0.7)
        _fill_label(ctx, titles[0], oslide)
    elif oslide.headline and oslide.kind not in (PatternKind.thanks,):
        ctx.warnings.append("pattern has no title slot")
    subtitle_text = oslide.subtitle or (oslide.section if oslide.kind not in (PatternKind.title, PatternKind.thanks, PatternKind.section) else None)
    subs = ctx.slots(SlotRole.subtitle)
    if not subs and oslide.subtitle and oslide.kind in (PatternKind.title, PatternKind.section, PatternKind.thanks) and titles:
        # title samples often keep an empty text box under the title that roles.py cannot name: it is the subtitle
        top = titles[0].bbox
        below = [s for s in ctx.slots(SlotRole.body, SlotRole.bullet_list, SlotRole.caption) if s.bbox.y >= top.y2 - 0.02]
        if below:
            subs = [min(below, key=lambda s: s.bbox.y)]
    if subs and subtitle_text:
        ctx.fill_slot(subs[0], [ParagraphSpec(subtitle_text)])
    elif oslide.subtitle:
        ctx.warnings.append("subtitle had no slot")

    # repeated items (cards, KPIs, steps, columns) — bullets too when the pattern is a list of cells
    items = _items_for(oslide)
    bullets_as_items = False
    if not items and c.bullets and _cells_can_hold_bullets(ctx, c.bullets):
        items = [SlideItem(title=b) for b in c.bullets]
        bullets_as_items = True
    use_ordinals = oslide.kind in (PatternKind.agenda, PatternKind.process, PatternKind.timeline)
    if items:
        handled = _fill_cells(ctx, items, use_ordinals=use_ordinals, text_only=bullets_as_items)
        if not handled:
            if bullets_as_items:
                items = []
                bullets_as_items = False
            else:
                _fill_standalone_items(ctx, items)

    # bullets / paragraphs / quote
    body_cap = ctx.typo.size_for("h2", ctx.typo.size_for("body", 14.0) * 1.3)
    text_cap = _text_cap(ctx)

    def _running_size(slot: Slot) -> Optional[float]:
        sz = slot.style.size_pt or 0
        return body_cap if sz > body_cap * 1.2 else None  # a KPI-sized slot must not carry running text at 60 pt

    if c.bullets and not bullets_as_items and oslide.kind not in _ITEM_KINDS:
        target = ctx.slots(SlotRole.bullet_list) or ctx.slots(SlotRole.body) or ctx.slots(SlotRole.card_body)
        if target:
            big = ctx.largest(target)
            ctx.fill_slot(big, [ParagraphSpec(b, bullet=True) for b in c.bullets], size_hint=_running_size(big), grow_to=text_cap)
        else:
            ctx.warnings.append("no slot for bullets")
    if c.paragraphs:
        target = ctx.slots(SlotRole.body) or ctx.slots(SlotRole.bullet_list) or ctx.slots(SlotRole.card_body) or ctx.slots(SlotRole.caption)
        if target:
            big = ctx.largest(target)
            lone = len(c.paragraphs) == 1 and len(c.paragraphs[0].split()) <= 25 and not c.bullets and not items
            cap = max(body_cap, ctx.typo.size_for("h1", body_cap) * 0.75) if lone else text_cap
            ctx.fill_slot(big, [ParagraphSpec(p, bullet=False) for p in c.paragraphs], size_hint=_running_size(big), grow_to=cap)
        elif oslide.kind not in (PatternKind.chart, PatternKind.table):
            ctx.warnings.append("no slot for paragraphs")
    if c.quote:
        target = ctx.slots(SlotRole.body, SlotRole.bullet_list, SlotRole.card_body, SlotRole.subtitle)
        if target:
            big = ctx.largest(target)
            ctx.fill_slot(big, [ParagraphSpec("«" + c.quote.strip("«»\"") + "»", bullet=False)], grow_to=body_cap)
            if c.quote_author:
                small_slots = ctx.slots(SlotRole.caption, SlotRole.card_body, SlotRole.body, SlotRole.subtitle, SlotRole.number_label)
                author_slot = ctx.smallest_font(small_slots)
                if author_slot is not None:
                    cap = ctx.typo.size_for("small", ctx.typo.size_for("body", 14.0))
                    size = min(author_slot.style.size_pt or cap, cap)
                    ctx.fill_slot(author_slot, [ParagraphSpec(c.quote_author)], size_hint=size)
        else:
            ctx.warnings.append("no slot for quote")

    # native chart / table
    if c.chart is not None or c.table is not None:
        _place_native_object(ctx, oslide)

    # illustration by hint
    if c.image_hint:
        imgs = ctx.slots(SlotRole.image)
        if imgs:
            path = pick_asset(manifest, ws, c.image_hint, exclude=ctx.used_assets)
            el = ctx.els.get(imgs[0].shape_id)
            if path and el is not None and etree.QName(el).localname == "pic":
                replace_picture(slide, el, path)
                ctx.filled.add(imgs[0].shape_id)

    # cleanup: cells that got nothing lose their anchors and chips, «Вставить фото / QR» boxes go with their text,
    # then unfilled text slots and stray placeholder text
    _remove_empty_cells(ctx)
    _remove_placeholder_boxes(ctx)
    for slot in list(ctx.pattern.slots):
        if slot.role not in TEXT_ROLES or slot.shape_id in ctx.filled or slot.shape_id in ctx.removed:
            continue
        el = ctx.els.get(slot.shape_id)
        if el is None or el.getparent() is None:
            continue
        if slot.container and not is_nested(el):
            remove_element(el)
            ctx.removed.add(slot.shape_id)
        elif has_visible_style(el) and not is_nested(el) and slot.bbox.area <= 0.08 and len(slot.sample_text or "") <= 40:
            remove_element(el)  # a painted label («Примечание» in a pill) without its text is an empty lozenge
            ctx.removed.add(slot.shape_id)
        elif has_visible_style(el) or is_nested(el):
            clear_text(el)
        else:
            remove_element(el)
            ctx.removed.add(slot.shape_id)
    for sid, el in list(ctx.els.items()):
        if sid in ctx.filled or sid in ctx.removed or etree.QName(el).localname != "sp":
            continue
        txt = shape_text(el)
        if txt.strip() and looks_like_placeholder(txt):
            clear_text(el)
    _remove_orphan_holders(ctx)
    # sample content pictures (photos, screenshots, chart images) that nothing replaced are stale: drop them
    has_visual = bool(c.image_hint or c.chart is not None or c.table is not None)
    drop_icons = oslide.kind in (PatternKind.thanks, PatternKind.title, PatternKind.section, PatternKind.quote)
    for slot in ctx.slots(SlotRole.image, SlotRole.icon):
        el = ctx.els.get(slot.shape_id)
        if el is None or is_nested(el) or el.getparent() is None:
            continue
        if slot.shape_id in ctx.cell_member_ids:
            # inside a card that received an item: a big picture is a stale sample chart/photo, a small one is the card's icon
            if slot.bbox.w > _ICON_MAX_W:
                remove_element(el)
                ctx.removed.add(slot.shape_id)
            continue
        if slot.role == SlotRole.icon and not drop_icons:
            continue
        if not has_visual or slot.bbox.area >= 0.05:
            remove_element(el)
            ctx.removed.add(slot.shape_id)
    _remove_qr_codes(ctx)
    if oslide.notes:
        try:
            slide.notes_slide.notes_text_frame.text = oslide.notes
        except Exception:  # noqa: BLE001
            pass
    return slide, ctx.warnings
