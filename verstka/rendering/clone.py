"""Clone renderer: copy a sample slide and rewrite its slots with outline content."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree
from pptx.slide import Slide

from verstka.analysis.shapes import looks_like_placeholder
from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.assets_pick import pick_asset, pick_icon
from verstka.rendering.charts import add_chart
from verstka.rendering.deck import DeckBuilder, element_bbox, is_nested, remove_element, set_element_pos, slide_shape_elements
from verstka.rendering.fonts import text_width_pt
from verstka.rendering.fit import fit_size
from verstka.rendering.groups import adjust_group
from verstka.rendering.images import replace_picture
from verstka.rendering.tables import add_table
from verstka.rendering.textfill import ParagraphSpec, clear_text, fill_text, has_visible_style, shape_text
from verstka.schemas.common import EMU_PER_PT, Bbox, PatternKind, SlotRole
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideItem
from verstka.schemas.template import Pattern, RepeatGroup, Slot, TemplateManifest

log = logging.getLogger(__name__)

TEXT_ROLES = {SlotRole.title, SlotRole.subtitle, SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption}
CELL_TEXT_ROLES = {SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.bullet_list, SlotRole.body}
_ITEM_KINDS = {PatternKind.cards, PatternKind.process, PatternKind.timeline, PatternKind.team, PatternKind.comparison, PatternKind.agenda, PatternKind.two_column}


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

    def fill_el(self, el: etree._Element, slot: Optional[Slot], paragraphs: list[ParagraphSpec], *, size_hint: Optional[float] = None, min_ratio: float = 0.6) -> None:
        if not paragraphs:
            return
        box = element_bbox(el)
        style = slot.style if slot else None
        slot_size = style.size_pt if style and style.size_pt else self.typo.size_for("body")
        size = size_hint or slot_size
        bold = bool(style and style.bold) if style else False
        family = style.font_family if style and style.font_family else self.typo.primary_family
        target_size = size
        if box and box[2] > 0 and box[3] > 0:
            res = fit_size([p.text for p in paragraphs], Bbox(x=box[0], y=box[1], w=box[2], h=box[3]), family, size, bold, self.scale, line_spacing=self.typo.line_spacing, min_ratio=min_ratio)
            target_size = res.size_pt
            if not res.fits:
                if slot is not None and slot.role == SlotRole.number and len(paragraphs) == 1 and not is_nested(el):
                    # a single figure never wraps well: widen the box instead of clipping
                    need_w = int(text_width_pt(paragraphs[0].text, family, target_size, True) * EMU_PER_PT * 1.15) + 2 * 91440
                    if need_w > box[2] and box[0] + need_w <= self.W * 0.97:
                        set_element_pos(el, w=need_w)
                        self.warnings.append(f"widened number slot {slot.id}")
                    elif need_w > box[2]:
                        shrink = fit_size([p.text for p in paragraphs], Bbox(x=box[0], y=box[1], w=box[2], h=box[3]), family, size, bold, self.scale, line_spacing=self.typo.line_spacing, min_ratio=0.2)
                        target_size = shrink.size_pt
                else:
                    self.warnings.append(f"text may overflow in {slot.id if slot else 'shape'} ({res.lines} lines)")
        explicit = size_hint is not None or target_size < slot_size
        fill_text(el, paragraphs, size_pt=target_size if explicit else None)
        sid = self.id_of(el)
        if sid:
            self.filled.add(sid)

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

    def largest(self, slots: list[Slot]) -> Optional[Slot]:
        return max(slots, key=lambda s: s.bbox.area) if slots else None

    def smallest_font(self, slots: list[Slot]) -> Optional[Slot]:
        return min(slots, key=lambda s: (s.style.size_pt or 99.0)) if slots else None


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
    if item.bullets:
        return [ParagraphSpec(b, bullet=True) for b in item.bullets]
    if item.text:
        return [ParagraphSpec(item.text, bullet=False)]
    return []


def _item_single_paragraphs(item: SlideItem, include_number: bool = True) -> list[ParagraphSpec]:
    """Everything of an item in one text shape (cells that have a single text slot)."""
    if item.number:
        if not include_number:
            return [ParagraphSpec(item.text or item.title, bullet=False)]
        return [ParagraphSpec(item.number, bullet=False, bold=True)] + ([ParagraphSpec(item.text, bullet=False)] if item.text else [])
    out = [ParagraphSpec(item.title, bullet=False, bold=bool(item.text or item.bullets))]
    out += _item_body_paragraphs(item)
    return out


def _ordinal(idx: int, sample: Optional[str]) -> str:
    """01 / 1 style sequence number matching the template's sample."""
    sm = (sample or "").strip()
    if len(sm) == 2 and sm.isdigit() and sm.startswith("0"):
        return f"{idx + 1:02d}"
    return str(idx + 1)


def _merge_items(items: list[SlideItem], n: int) -> list[SlideItem]:
    """Fold items beyond n into the last one."""
    if len(items) <= n or n <= 0:
        return items
    head = items[: n - 1]
    tail = items[n - 1 :]
    texts = [tail[0].text] + [f"{x.title}: {x.text}" if x.text else x.title for x in tail[1:]]
    merged = SlideItem(title=tail[0].title, text="; ".join(t for t in texts if t), icon_hint=tail[0].icon_hint, number=tail[0].number, bullets=[b for x in tail for b in x.bullets])
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


def _fill_cells(ctx: _SlideCtx, items: list[SlideItem], use_ordinals: bool = True, text_only: bool = False) -> bool:
    """Write items into the pattern's biggest text-bearing repeat group. Returns True when handled."""
    groups = _text_groups(ctx, exclude_number_only=text_only)
    if not groups or not items:
        return False
    group = max(groups, key=lambda g: len(g.member_shape_ids))
    cells, ctx.next_id = adjust_group(ctx.slide, group, len(items), ctx.W, ctx.H, ctx.next_id)
    if not cells:
        return False
    numeric_items = any(i.number for i in items)
    if numeric_items:
        if len(items) > len(cells):
            ctx.warnings.append(f"{len(items) - len(cells)} numbers dropped: group holds {len(cells)}")
        items = items[: len(cells)]
    else:
        items = _merge_items(items, len(cells))
        if len(items) > len(cells):
            ctx.warnings.append(f"{len(items) - len(cells)} items dropped: group holds {len(cells)}")
    # roles by position inside a cell (all cells share one composition)
    src_ids = group.member_shape_ids[0]
    roles_template = [ctx.role_of.get(sid) for sid in src_ids]
    text_roles_in_cell = [r for r in roles_template if r in CELL_TEXT_ROLES]
    single_text = len(text_roles_in_cell) == 1
    numbers_in_cells = SlotRole.number in text_roles_in_cell
    standalone_numbers = [s for s in ctx.slots(SlotRole.number) if s.group_id != group.id]
    include_number = numbers_in_cells or not standalone_numbers
    for cell_idx, (cell, item) in enumerate(zip(cells, items)):
        if cell_idx < len(group.member_shape_ids) and len(group.member_shape_ids[cell_idx]) == len(cell):
            roles = [ctx.role_of.get(sid) for sid in group.member_shape_ids[cell_idx]]
            slots = [ctx.slot_of.get(sid) for sid in group.member_shape_ids[cell_idx]]
        else:
            roles = roles_template if len(roles_template) == len(cell) else [ctx.role_of.get(ctx.id_of(e) or "") for e in cell]
            slots = [ctx.slot_of.get(sid) for sid in src_ids] if len(src_ids) == len(cell) else [None] * len(cell)
        done: set[SlotRole] = set()
        for e, role, slot in zip(cell, roles, slots):
            tag = etree.QName(e).localname
            if role in (SlotRole.card_title, SlotRole.card_body, SlotRole.bullet_list, SlotRole.body, SlotRole.number, SlotRole.number_label) and tag == "sp":
                if single_text:
                    if role not in done:
                        ctx.fill_el(e, slot, _item_single_paragraphs(item, include_number=include_number))
                        done.add(role)
                    else:
                        clear_text(e)
                elif role == SlotRole.card_title and SlotRole.card_title not in done:
                    ctx.fill_el(e, slot, [ParagraphSpec(item.title)])
                    done.add(SlotRole.card_title)
                elif role in (SlotRole.card_body, SlotRole.bullet_list, SlotRole.body) and SlotRole.card_body not in done:
                    paras = _item_body_paragraphs(item) or ([ParagraphSpec(item.title)] if SlotRole.card_title not in text_roles_in_cell else [])
                    if paras:
                        ctx.fill_el(e, slot, paras)
                    else:
                        clear_text(e)
                    done.add(SlotRole.card_body)
                elif role == SlotRole.number and SlotRole.number not in done:
                    if item.number or use_ordinals:
                        value = item.number or _ordinal(cell_idx, slot.sample_text if slot else None)
                        ctx.fill_el(e, slot, [ParagraphSpec(value)], min_ratio=0.35)
                    else:
                        clear_text(e)
                    done.add(SlotRole.number)
                elif role == SlotRole.number_label and SlotRole.number_label not in done:
                    ctx.fill_el(e, slot, [ParagraphSpec(item.text or item.title)])
                    done.add(SlotRole.number_label)
                else:
                    clear_text(e)
            elif role == SlotRole.icon and item.icon_hint and tag == "pic":
                picked = pick_icon(ctx.manifest, ctx.ws, item.icon_hint, exclude=ctx.used_assets)
                if picked:
                    aid, path = picked
                    if replace_picture(ctx.slide, e, path):
                        ctx.used_assets.add(aid)
        for e in cell:
            for nv in e.iter(q("p:cNvPr")):
                ctx.filled.add(nv.get("id"))
    if numeric_items and not include_number:
        # figures live outside the group (big_number patterns): put them into the standalone number slots
        for slot, item in zip(standalone_numbers, items):
            ctx.fill_slot(slot, [ParagraphSpec(item.number)], min_ratio=0.35)
    return True


def _fill_standalone_items(ctx: _SlideCtx, items: list[SlideItem]) -> None:
    """Items into ungrouped slots: numbers/labels first, then card titles/bodies, rest into a list slot."""
    numbers = ctx.slots(SlotRole.number)
    labels = ctx.slots(SlotRole.number_label)
    placed = 0
    if numbers and any(i.number for i in items):
        num_items = [i for i in items if i.number]
        for slot, item in zip(numbers, num_items):
            ctx.fill_slot(slot, [ParagraphSpec(item.number)], min_ratio=0.35)
        for slot, item in zip(labels, num_items):
            ctx.fill_slot(slot, [ParagraphSpec(item.text or item.title)])
        placed = min(len(numbers), len(num_items))
        items = [i for i in items if not i.number] + num_items[placed:]
    elif numbers and len(numbers) >= len(items) >= 2:
        # ordinal markers next to standalone card slots (agenda / process patterns)
        for idx, (slot, item) in enumerate(zip(numbers, items)):
            ctx.fill_slot(slot, [ParagraphSpec(_ordinal(idx, slot.sample_text))], min_ratio=0.35)
    titles = ctx.slots(SlotRole.card_title)
    bodies = ctx.slots(SlotRole.card_body)
    n = max(len(titles), len(bodies))
    if n and items:
        items2 = _merge_items(items, n)
        for slot, item in zip(titles, items2):
            ctx.fill_slot(slot, [ParagraphSpec(item.title)])
        for slot, item in zip(bodies, items2):
            ctx.fill_slot(slot, _item_body_paragraphs(item) or [ParagraphSpec(item.title)])
        items = items2[n:]
    if items:
        target = ctx.slots(SlotRole.bullet_list, SlotRole.body)
        if target:
            big = ctx.largest(target)
            ctx.fill_slot(big, [ParagraphSpec(f"{i.number or i.title}: {i.text}" if i.text else (i.number or i.title), bullet=True) for i in items])
        else:
            ctx.warnings.append(f"{len(items)} items had no slot")


def _place_native_object(ctx: _SlideCtx, oslide: OutlineSlide) -> None:
    c = oslide.content
    manifest = ctx.manifest
    # sample charts/tables/images on the slide are replaced by the native object
    candidates = ctx.slots(SlotRole.image)
    frames = [ctx.slot_of[sid] for sid, el in ctx.els.items() if etree.QName(el).localname == "graphicFrame" and sid in ctx.slot_of and sid not in ctx.removed]
    candidates = list({s.shape_id: s for s in candidates + frames}.values())
    box: Optional[Bbox] = None
    big_candidates = [s for s in candidates if s.bbox.area >= 0.08]
    if ctx.pattern.kind in (PatternKind.chart, PatternKind.table) and not big_candidates:
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


# ---------------------------------------------------------------------------- main


def render_clone(builder: DeckBuilder, plan_slide: LayoutSlide, oslide: OutlineSlide, pattern: Pattern, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline) -> tuple[Slide, list[str]]:
    slide = builder.clone_slide(pattern.source_slide)
    ctx = _SlideCtx(builder, slide, pattern, manifest, ws, outline)
    c = oslide.content

    # title / subtitle
    titles = ctx.slots(SlotRole.title)
    if titles:
        ctx.fill_slot(titles[0], [ParagraphSpec(oslide.headline)], min_ratio=0.7)
    elif oslide.headline and oslide.kind not in (PatternKind.thanks,):
        ctx.warnings.append("pattern has no title slot")
    subtitle_text = oslide.subtitle or (oslide.section if oslide.kind not in (PatternKind.title, PatternKind.thanks, PatternKind.section) else None)
    subs = ctx.slots(SlotRole.subtitle)
    if subs and subtitle_text:
        ctx.fill_slot(subs[0], [ParagraphSpec(subtitle_text)])

    # repeated items (cards, KPIs, steps, columns) — bullets too when the pattern is a list of cells
    items = _items_for(oslide)
    bullets_as_items = False
    if not items and c.bullets and _text_groups(ctx, exclude_number_only=True):
        items = [SlideItem(title=b) for b in c.bullets]
        bullets_as_items = True
    use_ordinals = oslide.kind in (PatternKind.agenda, PatternKind.process, PatternKind.timeline)
    if items:
        handled = _fill_cells(ctx, items, use_ordinals=use_ordinals, text_only=bullets_as_items)
        if not handled:
            if bullets_as_items:
                items = []
            else:
                _fill_standalone_items(ctx, items)


    # bullets / paragraphs / quote
    body_cap = ctx.typo.size_for("h2", ctx.typo.size_for("body", 14.0) * 1.3)

    def _running_size(slot: Slot) -> Optional[float]:
        sz = slot.style.size_pt or 0
        return body_cap if sz > body_cap * 1.2 else None  # a KPI-sized slot must not carry running text at 60 pt

    if c.bullets and not bullets_as_items and oslide.kind not in _ITEM_KINDS:
        target = ctx.slots(SlotRole.bullet_list) or ctx.slots(SlotRole.body) or ctx.slots(SlotRole.card_body)
        if target:
            big = ctx.largest(target)
            ctx.fill_slot(big, [ParagraphSpec(b, bullet=True) for b in c.bullets], size_hint=_running_size(big))
        else:
            ctx.warnings.append("no slot for bullets")
    if c.paragraphs:
        target = ctx.slots(SlotRole.body) or ctx.slots(SlotRole.bullet_list) or ctx.slots(SlotRole.card_body) or ctx.slots(SlotRole.caption)
        if target:
            big = ctx.largest(target)
            ctx.fill_slot(big, [ParagraphSpec(p, bullet=False) for p in c.paragraphs], size_hint=_running_size(big))
        elif oslide.kind not in (PatternKind.chart, PatternKind.table):
            ctx.warnings.append("no slot for paragraphs")
    if c.quote:
        target = ctx.slots(SlotRole.body, SlotRole.bullet_list, SlotRole.card_body, SlotRole.subtitle)
        if target:
            big = ctx.largest(target)
            ctx.fill_slot(big, [ParagraphSpec("«" + c.quote.strip("«»\"") + "»", bullet=False)])
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

    # cleanup: unfilled text slots and stray placeholder text
    for slot in list(ctx.pattern.slots):
        if slot.role not in TEXT_ROLES or slot.shape_id in ctx.filled or slot.shape_id in ctx.removed:
            continue
        el = ctx.els.get(slot.shape_id)
        if el is None:
            continue
        if has_visible_style(el) or is_nested(el):
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
    # sample content pictures (photos, screenshots, chart images) that nothing replaced are stale: drop them
    has_visual = bool(c.image_hint or c.chart is not None or c.table is not None)
    drop_roles = (SlotRole.image, SlotRole.icon) if oslide.kind in (PatternKind.thanks, PatternKind.title, PatternKind.section, PatternKind.quote) else (SlotRole.image,)
    for slot in ctx.slots(*drop_roles):
        el = ctx.els.get(slot.shape_id)
        if el is None or is_nested(el):
            continue
        if not has_visual or slot.bbox.area >= 0.05:
            remove_element(el)
            ctx.removed.add(slot.shape_id)
    # "insert photo / QR" boxes: visible shapes whose only purpose was the placeholder text
    for slot in ctx.pattern.slots:
        if slot.shape_id in ctx.filled or slot.shape_id in ctx.removed or not slot.sample_text:
            continue
        if re.search(r"вставить|insert|qr|фото|photo|логотип|logo", slot.sample_text, re.I):
            el = ctx.els.get(slot.shape_id)
            if el is not None and not is_nested(el):
                remove_element(el)
                ctx.removed.add(slot.shape_id)
    if oslide.notes:
        try:
            slide.notes_slide.notes_text_frame.text = oslide.notes
        except Exception:  # noqa: BLE001
            pass
    return slide, ctx.warnings
